"""Create or verify a QA-only, hash-pinned *offline update candidate*.

The folder's target label is v1.0.1, but the frozen executable was built
from package.json v1.0.0 and contains NO verified v1.0.1 version resource.
This is NOT a v1.0.1 installer, a working auto-updater or release approval.

No installed program is launched/modified. No APPDATA/Taraz, live ledger,
network, services, signing, deployment or installation is touched.
Create-only output: D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.1

Usage:
  py -3.12 -B scripts/qa_taraz_v101_update_package_20261110.py
  py -3.12 -B scripts/qa_taraz_v101_update_package_20261110.py --verify ZIP_PATH
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

sys.dont_write_bytecode = True

SOURCE = Path(__file__).resolve().parents[1]
QA_ROOT = SOURCE.parents[1]
OUTPUT = QA_ROOT / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.1"
REPORT = QA_ROOT / "MTR-TARAZ-QA-BUNDLE-20261110" / "qa-4ae81695ac39" / "qa-build-report.json"
PAYLOAD_BASENAME = "Taraz-MTR-QA-4ae81695ac39.exe"
ZIP_BASENAME = "Taraz-target-v1.0.1-QA-binary-from-v1.0.0-OFFLINE-REVIEW-ONLY.zip"
OUTER_MANIFEST = "offline-candidate-manifest.json"
QA_SHA = "49ef093765801c56fc1b9e04eabe3d8370d7db7982de51a28ef996e7079dc7d6"
QA_BYTES = 17033670
SOURCE_SHA = "3b39a7f55d30b98064f5df5ec913ef0e544f41dc46614cb7102d39c766166be7"
INSTALLED_PIN = "de5005579039bd86890c1dca1f5f1d9c760e6c47579a42f649f80096f158e70c"
TARGET_VERSION = "1.0.1"  # label ONLY; do not modify or imply EXE version.
SOURCE_VERSION = "1.0.0"
MAX_ARCHIVE_BYTES = 100_000_000
MAX_MEMBER_BYTES = 60_000_000
EXPECTED_MEMBERS = (
    "payload/" + PAYLOAD_BASENAME,
    "manifest.json",
    "CHECK_BEFORE_ANY_INSTALL.md",
    "INSTALL_BLOCKED.md",
    "ROLLBACK_PRECONDITIONS.md",
)
SHA_RE = re.compile("^[a-f0-9]{64}$")


class CandidateBlocked(RuntimeError):
    pass


def no_links(path: Path) -> None:
    if not path.is_absolute():
        raise CandidateBlocked("Paths must be absolute")
    for item in (path, *path.parents):
        if not os.path.lexists(item):
            continue
        meta = item.lstat()
        if (stat.S_ISLNK(meta.st_mode)
                or bool(getattr(meta, "st_file_attributes", 0) & 0x400)
                or getattr(item, "is_junction", lambda: False)()):
            raise CandidateBlocked("Symlink/junction/reparse point refused")


def file_sha(path: Path, max_bytes: int = MAX_ARCHIVE_BYTES) -> tuple[str, int]:
    no_links(path)
    if not path.is_file():
        raise CandidateBlocked("Required file unavailable")
    before = path.stat()
    if not 0 < before.st_size <= max_bytes:
        raise CandidateBlocked("File outside bounded size")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            if size > max_bytes:
                raise CandidateBlocked("File exceeds maximum allowed size")
            digest.update(chunk)
    after = path.stat()
    if size != before.st_size or size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise CandidateBlocked("File changed while calculating SHA-256")
    return digest.hexdigest(), size


def read_json(path: Path) -> dict:
    no_links(path)
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise CandidateBlocked("Missing or oversized manifest")
    try:
        data = json.loads(path.read_text(encoding="utf8"))
    except (UnicodeError, ValueError) as error:
        raise CandidateBlocked("Invalid JSON evidence") from error
    if not isinstance(data, dict):
        raise CandidateBlocked("Expected JSON object")
    return data


def current_source_fingerprint(source: Path) -> tuple[str, int]:
    """Use existing READ-ONLY source snapshot inventory, never trigger a build."""
    gate = source / "scripts" / "qa_taraz_next_version_release_gate_20261110.py"
    no_links(gate)
    spec = importlib.util.spec_from_file_location("taraz_readonly_gate", gate)
    if spec is None or spec.loader is None:
        raise CandidateBlocked("Read-only source gate module not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.source_snapshot(source)
    return result["sha256"], result["inputCount"]


def validate_evidence(*, source: Path, qa_report: Path,
                      installed_exe: Path, pinned_qa_sha: str = QA_SHA,
                      pinned_qa_bytes: int = QA_BYTES,
                      pinned_installed_sha: str = INSTALLED_PIN,
                      pinned_source_sha: str = SOURCE_SHA,
                      source_snapshot=None) -> dict:
    """Validate provenance without invoking EXE, updater or finance APIs."""
    if not SHA_RE.fullmatch(pinned_qa_sha) or not SHA_RE.fullmatch(pinned_source_sha):
        raise CandidateBlocked("Invalid SHA pins")
    pkg = read_json(source / "package.json")
    lock = read_json(source / "package-lock.json")
    if not (pkg.get("version") == lock.get("version")
            == (lock.get("packages") or {}).get("", {}).get("version")
            == SOURCE_VERSION):
        raise CandidateBlocked("Source/lock version mismatch; not frozen 1.0.0")
    if TARGET_VERSION == SOURCE_VERSION:
        raise CandidateBlocked("Target label must not be mistaken for package version")
    report = read_json(qa_report)
    if (report.get("status") != "QA_BUNDLE_VERIFIED"
            or report.get("qaOnly") is not True
            or report.get("installed") is not False
            or report.get("releaseReady") is not False
            or report.get("realLedgerAccessed") is not False):
        raise CandidateBlocked("Report is not safely limited to a QA build")
    if not isinstance(report.get("source"), str):
        raise CandidateBlocked("Missing exact QA source")
    if Path(report["source"]) != source:
        raise CandidateBlocked("QA report belongs to another source tree")
    if (report.get("sourceSnapshotSha256") != pinned_source_sha
            or report.get("sourceInputCount") != 128):
        raise CandidateBlocked("QA report source fingerprint not from reviewed snapshot")
    if not isinstance(report.get("exe"), str):
        raise CandidateBlocked("QA EXE path absent")
    qa_exe = Path(report["exe"])
    no_links(qa_exe)
    if (qa_exe.name != PAYLOAD_BASENAME
            or qa_exe.parent != qa_report.parent / "pyinstaller" / "dist"):
        raise CandidateBlocked("Unexpected QA EXE or report directory")
    qa_sha, qa_size = file_sha(qa_exe)
    if (qa_sha != pinned_qa_sha or qa_size != pinned_qa_bytes
            or report.get("exeSha256") != qa_sha
            or report.get("exeSizeBytes") != qa_size):
        raise CandidateBlocked("QA EXE differs from frozen report and SHA pin")
    flags = report.get("compiledNewUISurfaces")
    if not isinstance(flags, dict) or any(flags.get(name) is not True
                                          for name in ("sileoToastReactHost",
                                                       "perSectionContextHelpTrigger")):
        raise CandidateBlocked("Compiled UI feature evidence missing")
    if (report.get("packedHtmlBridgeForwarderPresent") is not True
            or (report.get("packedDurableReview") or {}).get(
                "sourceBoundDurableIntentCode") is not True):
        raise CandidateBlocked("Expected QA native review evidence missing")
    source_sha, inputs = (source_snapshot(source) if source_snapshot
                          else current_source_fingerprint(source))
    if source_sha != pinned_source_sha or inputs != report["sourceInputCount"]:
        raise CandidateBlocked("Current source differs from pinned QA source snapshot")
    installed_sha, installed_size = file_sha(installed_exe)
    if installed_sha != pinned_installed_sha or installed_size != 16_968_567:
        raise CandidateBlocked("Installed 1.0.0 program changed from known pin")
    # Known source-only modules absent from actual frozen QA PYZ. Never claim
    # those modules are in this payload based on their source presence.
    from PyInstaller.archive.readers import CArchiveReader
    packed = CArchiveReader(str(qa_exe)).open_embedded_archive("PYZ.pyz")
    expected_absent = (
        "taraz_mtr_review_attestation_issuer",
        "taraz_mtr_finance_witness_issuer",
        "taraz_mtr_finance_binding_authority",
        "taraz_mtr_peer_registry",
        "taraz_mtr_peer_http",
    )
    if "taraz_integration" not in packed.toc:
        raise CandidateBlocked("Current QA EXE lacks metadata integration")
    presence = {name: name in packed.toc for name in expected_absent}
    return {
        "qaBinaryPath": str(qa_exe),
        "qaBinarySha256": qa_sha,
        "qaBinaryBytes": qa_size,
        "sourcePackageVersion": SOURCE_VERSION,
        "sourceSnapshotSha256": source_sha,
        "sourceInputCount": inputs,
        "installedBaselineFolderVersion": SOURCE_VERSION,
        "installedBaselineSha256": installed_sha,
        "installedBaselineBytes": installed_size,
        "packedFeaturePresence": presence,
    }


CHECK = """# بررسی بسته آفلاین تراز (فقط خواندنی)

**توقف نصب:** پوشه v1.0.1 فقط هدف پیشنهادی است. فایل اجرایی موجود
QA-only است و از سورس نسخه 1.0.0 ساخته شده؛ هیچ نسخه داخلی 1.0.1 تأیید نشده است.

1. پیش از هر اقدامی ZIP را فقط در یک پوشه آزمایشی جدا بررسی کنید.
2. SHA-256 خود ZIP را با offline-candidate-manifest.json (کنار ZIP) تطبیق دهید.
3. پس از استخراج در یک پوشه موقت، هش payload با manifest.json داخل ZIP
   و هش گزارش QA اولیه تطبیق داده شود.
4. هیچ فایل این بسته نصب‌کننده، آپدیتر یا مجوز دسترسی به داده‌های حسابداری نیست.
5. اسکریپت بررسی فقط ورودی را می‌خواند:
   py -3.12 -B scripts/qa_taraz_v101_update_package_20261110.py --verify PATH_TO_ZIP
   خروجی VERIFIED_QA_ARCHIVE_NOT_INSTALLABLE به معنی آماده نصب بودن نیست.
"""

INSTALL = """# وضعیت نصب: BLOCKED / NO_GO

این ZIP به درخواست کاربر فقط «بسته نامزد به‌روزرسانی آفلاین» است.
payload/Taraz-MTR-QA-4ae81695ac39.exe برنامه آزمایشی QA بوده و Setup نیست.
بازنام‌گذاری آن باعث ارتقا به نسخه 1.0.1 نمی‌شود؛ هرگونه نصب یا اجرای مستقیم
روی پروفایل واقعی و جایگزینی نسخه نصب‌شده 1.0.0 **ممنوع** است.

پیش‌شرط‌های گیت آینده: ساخت نسخه واقعی 1.0.1 با نسخه داخلی و مانیفست هماهنگ؛
سازنده نصب‌گر مستقل تراز و امضای معتبر؛ روش به‌روزرسانی آفلاین احرازشده؛
شواهد پشتیبان سه‌مخزنه و بازیابی؛ آزمون نصب/لغو/بازگردانی روی ویندوز موقت؛
بسته‌بندی کامل peer/issuer و قرارداد رسید مالی مستقل. بدون این شواهد NO_GO.
"""

ROLLBACK = """# بازگشت امن: فقط برنامه، نه دستور اجرای خودکار

قبل از نصب نسخه آینده، از هر سه مخزن داده موردنیاز با مسیر و مجوزهای صریح،
پشتیبان «create-only» مستقل بگیرید و SHA/اندازه/اسکیما/مالکیت را بازخوانی کنید.
در محیط موقت مستقل از صحت بازیابی نسخه 1.0.0 و داده‌های پشتیبان مطمئن شوید.
پنجره مهاجرت/قطع خدمت و حالت توقف در crash را مستند کنید.

اگر نصب آزمایشی شکست خورد، از نصب روی کاربر واقعی خودداری کنید؛
بدون شواهد سازگاری اسکیما، فایل حسابداری جدید را با نسخه قدیم باز نکنید.
هر بازگردانی باید مقصد تازه و کنترل هش مستقل داشته باشد؛ هرگز روی پایگاه
داده زنده overwrite خودکار انجام ندهید. این ZIP ابزار rollback ندارد.
"""


def manifest_from(evidence: dict) -> dict:
    return {
        "schemaVersion": 1,
        "application": "Taraz",
        "packageKind": "OFFLINE_UPDATE_REVIEW_CANDIDATE_QA_ONLY",
        "packageTargetLabel": TARGET_VERSION,
        "targetVersionInstalledOrBuilt": False,
        "payloadSourcePackageVersion": SOURCE_VERSION,
        "payloadEmbeddedBinaryVersionVerified": False,
        "payloadEmbeddedBinaryVersion": None,
        "payload": {
            "path": EXPECTED_MEMBERS[0],
            "sha256": evidence["qaBinarySha256"],
            "bytes": evidence["qaBinaryBytes"],
            "sourceSnapshotSha256": evidence["sourceSnapshotSha256"],
            "sourceInputCount": evidence["sourceInputCount"],
        },
        "installedBaseline": {
            "folderVersion": SOURCE_VERSION,
            "sha256": evidence["installedBaselineSha256"],
            "bytes": evidence["installedBaselineBytes"],
            "readOnlyInspected": True,
        },
        "compiledQA": {
            "sileoAndContextHelpReported": True,
            "sourceOnlyPeerAndFinanceModulePacked": evidence["packedFeaturePresence"],
        },
        "updateApiConfigured": False,
        "realInstaller": False,
        "safeToInstall": False,
        "releaseDecision": "NO_GO",
        "officialFinanceReceiptVerified": False,
        "installedUserOrLedgerAccessed": False,
        "requiredBeforeRealUpgrade": [
            "Build and independently attest a real >1.0.0 Taraz executable and installer",
            "Pin publisher signature and verify offline installer/update authority",
            "Prove per-store create-only backups, migrations and rollback readback",
            "Verify packed peer/finance authority and authenticated official receipt",
            "Run safe installed upgrade/rollback and native GUI authentication tests",
        ],
    }


def canonical_json(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _add_blob(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(2026, 11, 10, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (0o100644 << 16)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, payload)


def build(*, source: Path = SOURCE, qa_report: Path = REPORT,
          installed_exe: Path | None = None, output: Path = OUTPUT,
          expected_qa_sha: str = QA_SHA, source_snapshot=None) -> dict:
    if installed_exe is None:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise CandidateBlocked("LOCALAPPDATA unavailable for installed EXE readback")
        installed_exe = (Path(local) / "Programs" / "Taraz" / "versions"
                         / SOURCE_VERSION / "Taraz.exe")
    no_links(source)
    no_links(qa_report)
    no_links(installed_exe)
    no_links(output)
    if output.resolve() == source.resolve() or source in output.parents:
        raise CandidateBlocked("Candidate must be created outside the source worktree")
    evidence = validate_evidence(
        source=source, qa_report=qa_report, installed_exe=installed_exe,
        pinned_qa_sha=expected_qa_sha, source_snapshot=source_snapshot
    )
    if output.exists():
        if not output.is_dir():
            raise CandidateBlocked("Output path is not a directory")
        if any(output.iterdir()):
            raise CandidateBlocked("Output already contains files; create-only, no overwrite")
    else:
        # No modification to existing installed/user data or existing output.
        output.mkdir(parents=True, exist_ok=False)
    zip_path = output / ZIP_BASENAME
    outer_path = output / OUTER_MANIFEST
    if zip_path.exists() or outer_path.exists():
        raise CandidateBlocked("Candidate outputs already exist; refusing replacement")
    inner = manifest_from(evidence)
    with zipfile.ZipFile(zip_path, mode="x", allowZip64=False) as archive:
        # Already-compressed PyInstaller payload is streamed, not read into RAM.
        with archive.open(EXPECTED_MEMBERS[0], "w", force_zip64=False) as inside:
            with Path(evidence["qaBinaryPath"]).open("rb") as src:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    inside.write(block)
        _add_blob(archive, "manifest.json", canonical_json(inner))
        _add_blob(archive, "CHECK_BEFORE_ANY_INSTALL.md", CHECK.encode("utf8"))
        _add_blob(archive, "INSTALL_BLOCKED.md", INSTALL.encode("utf8"))
        _add_blob(archive, "ROLLBACK_PRECONDITIONS.md", ROLLBACK.encode("utf8"))
    # The verification pass is mandatory BEFORE emitting the outer hash manifest.
    verified = verify_zip(zip_path, expected_qa_sha=expected_qa_sha)
    archive_sha, archive_size = file_sha(zip_path)
    outer = {
        "schemaVersion": 1,
        "status": "VERIFIED_QA_ARCHIVE_NOT_INSTALLABLE",
        "packageKind": "OFFLINE_UPDATE_REVIEW_CANDIDATE_QA_ONLY",
        "targetLabel": TARGET_VERSION,
        "actualSourceVersion": SOURCE_VERSION,
        "sourceSnapshotSha256": evidence["sourceSnapshotSha256"],
        "zipName": zip_path.name,
        "zipSha256": archive_sha,
        "zipBytes": archive_size,
        "payloadSha256": expected_qa_sha,
        "payloadBytes": evidence["qaBinaryBytes"],
        "membersVerified": verified["membersVerified"],
        "safeToInstall": False,
        "releaseDecision": "NO_GO",
        "installedModified": False,
        "realInstallerCreated": False,
    }
    # Exclusive creation: previous run output cannot be silently replaced.
    with outer_path.open("x", encoding="utf8", newline="\n") as handle:
        handle.write(json.dumps(outer, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return {"status": outer["status"], "zip": str(zip_path),
            "outerManifest": str(outer_path), "zipSha256": archive_sha,
            "zipBytes": archive_size, "payloadSourceVersion": SOURCE_VERSION,
            "targetLabelOnly": TARGET_VERSION, "installable": False,
            "releaseDecision": "NO_GO"}


def verify_zip(path: Path, *, expected_qa_sha: str = QA_SHA) -> dict:
    """Verify complete ZIP in streams, read-only. No extraction or execution."""
    if not SHA_RE.fullmatch(expected_qa_sha):
        raise CandidateBlocked("Invalid expected payload hash")
    file_sha(path)  # validates size, links, and unchanged bytes
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if set(names) != set(EXPECTED_MEMBERS) or len(names) != len(EXPECTED_MEMBERS):
            raise CandidateBlocked("Unexpected, duplicate or missing ZIP member")
        for info in infos:
            member_path = PurePosixPath(info.filename)
            if (info.filename.startswith("/") or "\\" in info.filename
                    or ".." in member_path.parts or info.is_dir()
                    or info.file_size > MAX_MEMBER_BYTES
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise CandidateBlocked("Unsafe ZIP entry")
        doc = json.loads(archive.read("manifest.json").decode("utf8"))
        if (doc.get("schemaVersion") != 1 or doc.get("packageTargetLabel") != TARGET_VERSION
                or doc.get("payloadSourcePackageVersion") != SOURCE_VERSION
                or doc.get("payloadEmbeddedBinaryVersionVerified") is not False
                or doc.get("safeToInstall") is not False
                or doc.get("realInstaller") is not False
                or doc.get("releaseDecision") != "NO_GO"
                or doc.get("targetVersionInstalledOrBuilt") is not False
                or doc.get("updateApiConfigured") is not False):
            raise CandidateBlocked("Manifest falsely claims release/update safety")
        payload = doc.get("payload") or {}
        if (payload.get("path") != EXPECTED_MEMBERS[0]
                or payload.get("sha256") != expected_qa_sha
                or payload.get("bytes") != QA_BYTES):
            raise CandidateBlocked("Packaged QA payload not pinned to known build")
        digest = hashlib.sha256()
        count = 0
        with archive.open(EXPECTED_MEMBERS[0], "r") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                count += len(chunk)
                if count > MAX_MEMBER_BYTES:
                    raise CandidateBlocked("Payload decompression exceeds bound")
                digest.update(chunk)
        if digest.hexdigest() != expected_qa_sha or count != QA_BYTES:
            raise CandidateBlocked("Payload bytes inconsistent with source QA EXE")
        for name in EXPECTED_MEMBERS[2:]:
            if len(archive.read(name)) > 128 * 1024:
                raise CandidateBlocked("Documentation exceeds bound")
    return {"status": "VERIFIED_QA_ARCHIVE_NOT_INSTALLABLE",
            "zipSha256": file_sha(path)[0], "payloadSha256": expected_qa_sha,
            "membersVerified": list(EXPECTED_MEMBERS),
            "safeToInstall": False, "releaseDecision": "NO_GO"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path,
                        help="Read-only offline ZIP validation. Never extracts or installs")
    args = parser.parse_args(argv)
    try:
        result = verify_zip(args.verify) if args.verify is not None else build()
    except (CandidateBlocked, FileNotFoundError, OSError, ValueError,
            zipfile.BadZipFile) as error:
        print(json.dumps({"status": "BLOCKED", "releaseDecision": "NO_GO",
                          "safeToInstall": False, "error": str(error)},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
