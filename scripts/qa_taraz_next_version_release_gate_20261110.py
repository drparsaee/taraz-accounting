"""Bounded, read-only Taraz next-version release gate (NOT an installer).

Static evidence is NOT a proxy for signing, installed GUI, real authentication,
data-migration rollback, or an official Madar/Taraz finance receipt.
NO_GO is the intentionally fail-closed decision until independent release
evidence and a genuine higher-version candidate are available.

Run with Python 3.12: py -3.12 -B scripts/qa_taraz_next_version_release_gate_20261110.py
This tool reads only source inputs, installed *program EXE*, explicit QA bundle,
and optional candidate artifacts. It does not open APPDATA/Taraz or any ledger.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import marshal
import os
from pathlib import Path
import re
import stat
import sys
import types

sys.dont_write_bytecode = True

SOURCE = Path(__file__).resolve().parents[1]
QA_PARENT = SOURCE.parents[1] / "MTR-TARAZ-QA-BUNDLE-20261110"
DEFAULT_QA_REPORT = QA_PARENT / "qa-4ae81695ac39" / "qa-build-report.json"
INSTALLED_VERSION = "1.0.0"  # Folder label; installed PE has no embedded ProductVersion.
PINNED_INSTALLED_SHA256 = (
    "de5005579039bd86890c1dca1f5f1d9c760e6c47579a42f649f80096f158e70c"
)
SOURCE_EXCLUDES = frozenset((
    "node_modules", "dist", "release", "build", ".git", "__pycache__",
))
ROOT_INPUTS = frozenset(("accounting.html", "vite.config.js", "package.json",
                         "package-lock.json"))
MANDATORY_SOURCE = frozenset((
    "taraz_desktop.py", "taraz_integration.py",
    "src/standalone_accounting_workspace.jsx", "src/taraz_context_help.jsx",
    "src/taraz_sileo_feedback.jsx",
))
INTEGRATION_MODULES = (
    "taraz_mtr_review_attestation_issuer",
    "taraz_mtr_finance_witness_issuer",
    "taraz_mtr_finance_binding_authority",
    "taraz_mtr_peer_registry",
    "taraz_mtr_peer_http",
)
QA_FLAGS = ("sileoToastReactHost", "perSectionContextHelpTrigger")
VERSION = re.compile(r"^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
MAX_JSON_BYTES = 65536
MAX_SOURCE_FILES = 2000
MAX_SOURCE_BYTES = 300_000_000
MAX_BINARY_BYTES = 250_000_000


class GateBlocked(ValueError):
    """Unreadable, unsafe, or insufficient evidence can never imply GO."""


def _no_links(path: Path) -> None:
    """Reject symlinks, junctions/reparse points anywhere in an inspected path."""
    if not path.is_absolute():
        raise GateBlocked("A path was not absolute")
    for part in (path, *path.parents):
        if not os.path.lexists(part):
            continue
        s = part.lstat()
        if (stat.S_ISLNK(s.st_mode)
                or bool(getattr(s, "st_file_attributes", 0) & 0x400)
                or getattr(part, "is_junction", lambda: False)()):
            raise GateBlocked("Inspected path contains a link or junction")


def _file_hash(path: Path, limit: int = MAX_BINARY_BYTES) -> tuple[str, int]:
    _no_links(path)
    if not path.is_file():
        raise GateBlocked("Required evidence file missing or not regular")
    before = path.stat()
    if before.st_size < 1 or before.st_size > limit:
        raise GateBlocked("Evidence file outside size bounds")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            size += len(chunk)
            if size > limit:
                raise GateBlocked("Evidence changed or exceeds size bounds")
            digest.update(chunk)
    after = path.stat()
    if size != before.st_size or size != after.st_size or (
            before.st_mtime_ns != after.st_mtime_ns):
        raise GateBlocked("Evidence file changed during read")
    return digest.hexdigest(), size


def _json(path: Path) -> dict:
    _no_links(path)
    if not path.is_file():
        raise GateBlocked("JSON evidence file missing")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise GateBlocked("JSON evidence exceeds size limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError, OSError) as exc:
        raise GateBlocked("Invalid JSON evidence") from exc
    if not isinstance(value, dict):
        raise GateBlocked("JSON evidence must be an object")
    return value


def version_tuple(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise GateBlocked("Version must be a stable, strict x.y.z (no prerelease)")
    return tuple(int(part) for part in value.split("."))


def installed_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise GateBlocked("LOCALAPPDATA unavailable; cannot inspect installed program")
    return (Path(local) / "Programs" / "Taraz" / "versions"
            / INSTALLED_VERSION / "Taraz.exe")


def _function_names(code: types.CodeType) -> set[str]:
    names = {code.co_name}
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            names |= _function_names(value)
    return names


def inspect_installed(exe: Path) -> dict:
    """Only hash-gated static PyInstaller archive reads, NEVER packed execution."""
    result = {"versionLabel": INSTALLED_VERSION,
              "versionEvidence": "installed folder name, not PE ProductVersion",
              "verified": False}
    measured, size = _file_hash(exe, MAX_BINARY_BYTES)
    result["sha256"] = measured
    result["bytes"] = size
    if measured != PINNED_INSTALLED_SHA256:
        raise GateBlocked("Installed Taraz EXE differs from reviewed SHA-256 pin")
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(exe))
    code = archive.open_embedded_archive("PYZ.pyz").extract("taraz_integration")
    if not isinstance(code, types.CodeType):
        raise GateBlocked("Installed archive lacks expected integration bytecode")
    names = _function_names(code)
    result["preMoveDurableIntentPresent"] = "_atomic_json" in names
    result["perRequestLockPresent"] = "_request_lock" in names
    result["verified"] = True
    return result


def source_snapshot(root: Path) -> dict:
    """Replicate the frozen QA builder's shipped-input SHA manifest, read-only."""
    _no_links(root)
    if not root.is_dir():
        raise GateBlocked("Source folder missing")
    entries: dict[str, str] = {}
    total = 0
    for folder, dirs, files in os.walk(root, followlinks=False):
        relative = Path(folder).relative_to(root)
        if relative.parts and relative.parts[0] in SOURCE_EXCLUDES:
            dirs.clear()
            continue
        selected = []
        for name in dirs:
            if name in SOURCE_EXCLUDES:
                continue
            child = Path(folder) / name
            _no_links(child)
            selected.append(name)
        dirs[:] = selected
        for name in files:
            relative_file = relative / name
            if not (
                (len(relative_file.parts) == 1 and
                 (name.endswith(".py") or name in ROOT_INPUTS))
                or relative_file.parts[0] in ("src", "public", "assets")
            ):
                continue
            path = Path(folder) / name
            _no_links(path)
            digest, size = _file_hash(path, MAX_SOURCE_BYTES)
            total += size
            if total > MAX_SOURCE_BYTES or len(entries) >= MAX_SOURCE_FILES:
                raise GateBlocked("Source inventory exceeds bounded size or count")
            entries[relative_file.as_posix()] = digest
    missing = MANDATORY_SOURCE - entries.keys()
    if missing:
        raise GateBlocked("Missing mandatory source files: " + ",".join(sorted(missing)))
    manifest = dict(sorted(entries.items()))
    return {
        "sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest(),
        "inputCount": len(manifest),
        "manifest": manifest,
    }


def inspect_source(root: Path) -> dict:
    snapshot = source_snapshot(root)
    pkg = _json(root / "package.json")
    lock = _json(root / "package-lock.json")
    pkg_version = pkg.get("version")
    lock_version = lock.get("version")
    lock_root = (lock.get("packages") or {}).get("", {}).get("version")
    try:
        version_tuple(pkg_version)
    except GateBlocked as exc:
        raise GateBlocked("Invalid source version") from exc
    if lock_version != pkg_version or lock_root != pkg_version:
        raise GateBlocked("Package and lockfile version mismatch")
    installer_script = (pkg.get("scripts") or {}).get("dist:rc", "")
    builder = root / "scripts" / "build_integrated_v122.py"
    # Static AST only; NEVER call release/update functions or import TarazAPI.
    ast_tree = ast.parse((root / "taraz_desktop.py").read_bytes())
    api = next((x for x in ast_tree.body
                if isinstance(x, ast.ClassDef) and x.name == "TarazAPI"), None)
    if api is None:
        raise GateBlocked("TarazAPI not present in source")
    updater = {}
    for name in ("releaseCheck", "releaseDownload", "releaseInstall"):
        method = next((x for x in api.body
                       if isinstance(x, ast.FunctionDef) and x.name == name), None)
        updater[name] = bool(method and len(method.body) == 1
                             and isinstance(method.body[0], ast.Raise)
                             and "not configured" in ast.unparse(method.body[0]).lower())
    return {
        "version": pkg_version,
        "lockVersion": lock_version,
        "snapshotSha256": snapshot["sha256"],
        "sourceInputCount": snapshot["inputCount"],
        "updaterUnconfigured": all(updater.values()),
        # AST cannot verify a working authenticated/signed updater.
        "updaterVerifiedConfigured": False,
        "updaterRaisesByMethod": updater,
        "distRcReferencesLegacyBuilder": isinstance(installer_script, str)
        and "scripts/build_integrated_v122.py" in installer_script,
        "installerBuilderPresent": builder.is_file() and not builder.is_symlink(),
        "integrationSourceModulesPresent": {
            name: (root / (name + ".py")).is_file()
            for name in INTEGRATION_MODULES
        },
    }


def _strict_beneath(path: Path, base: Path) -> None:
    _no_links(path)
    _no_links(base)
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise GateBlocked("Candidate or QA evidence outside permitted QA root") from exc


def inspect_qa(report_file: Path, source: dict,
               *, qa_parent: Path = QA_PARENT) -> dict:
    _strict_beneath(report_file, qa_parent)
    report = _json(report_file)
    if (report.get("status") != "QA_BUNDLE_VERIFIED"
            or report.get("qaOnly") is not True
            or report.get("installed") is not False
            or report.get("releaseReady") is not False
            or report.get("realLedgerAccessed") is not False):
        raise GateBlocked("Report is not the expected bounded QA-only status")
    if (report.get("sourceSnapshotSha256") != source["snapshotSha256"]
            or report.get("sourceInputCount") != source["sourceInputCount"]):
        raise GateBlocked("QA build source snapshot is not current")
    if not isinstance(report.get("source"), str):
        raise GateBlocked("QA report lacks exact source provenance")
    if os.path.normcase(os.path.normpath(report["source"])) != os.path.normcase(
            os.path.normpath(str(SOURCE))):
        raise GateBlocked("QA report source path differs from current isolated source")
    if (not isinstance(report.get("output"), str)
            or os.path.normcase(os.path.normpath(report["output"])) !=
            os.path.normcase(os.path.normpath(str(report_file.parent)))):
        raise GateBlocked("QA report output directory mismatch")
    if not isinstance(report.get("exe"), str):
        raise GateBlocked("QA report executable path missing")
    exe = Path(report["exe"])
    _strict_beneath(exe, report_file.parent / "pyinstaller" / "dist")
    if not (exe.name.startswith("Taraz-MTR-QA-") and exe.suffix.lower() == ".exe"):
        raise GateBlocked("Expected QA-only EXE name missing")
    sha, size = _file_hash(exe)
    if sha != report.get("exeSha256") or size != report.get("exeSizeBytes"):
        raise GateBlocked("QA executable digest or length disagrees with report")
    flags = report.get("compiledNewUISurfaces")
    if not isinstance(flags, dict) or any(flags.get(key) is not True for key in QA_FLAGS):
        raise GateBlocked("QA report lacks compiled Sileo or contextual help")
    if (report.get("packedHtmlBridgeForwarderPresent") is not True
            or (report.get("packedDurableReview") or {}).get(
                "sourceBoundDurableIntentCode") is not True):
        raise GateBlocked("QA report lacks durable/HTML forwarder proof")
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    packed = set(pyz.toc)
    if "taraz_integration" not in packed:
        raise GateBlocked("Actual packed PYZ lacks Taraz metadata integration")
    assets = [name for name in archive.toc
              if name.replace("\\", "/").startswith("dist/assets/")
              and name.lower().endswith(".js")]
    if not assets or len(assets) > 30:
        raise GateBlocked("Unexpected compiled JS asset inventory")
    blobs = [archive.extract(name) for name in assets]
    if any(not isinstance(blob, bytes) or len(blob) > 20_000_000 for blob in blobs):
        raise GateBlocked("Invalid compressed JS evidence")
    ui = b" ".join(blobs)
    compiled = {
        "sileo": b"taraz-feedback-host" in ui,
        "contextHelp": b"taraz-context-help-trigger" in ui,
    }
    if not all(compiled.values()):
        raise GateBlocked("Actual QA archive missing compiled UI elements")
    return {
        "status": "QA_BUNDLE_VERIFIED_NOT_RELEASE",
        "sha256": sha, "bytes": size,
        "sourceSnapshotSha256": report["sourceSnapshotSha256"],
        "compiled": compiled,
        "packedTarazIntegrationPresent": True,
        "sourceIntegrationModuleInPYZ": {
            name: name in packed for name in INTEGRATION_MODULES
        },
        "officialFinancialReceiptVerified": False,
        "installed": False,
        "releaseReady": False,
    }


def _looks_pe(path: Path) -> bool:
    with path.open("rb") as fh:
        if fh.read(2) != b"MZ":
            return False
        fh.seek(0x3C)
        ptr = fh.read(4)
        if len(ptr) != 4:
            return False
        offset = int.from_bytes(ptr, "little")
        if not (64 <= offset <= 1_048_576):
            return False
        fh.seek(offset)
        return fh.read(4) == b"PE\x00\x00"


def inspect_candidate(version: str | None, manifest: Path | None,
                      source: dict, *, qa_root: Path) -> dict:
    """Read-only version/hash preflight; a manifest is never a trust signature."""
    if not version and manifest is None:
        return {"status": "NOT_SUPPLIED"}
    candidate = {"status": "NO_GO_STATIC_CANDIDATE"}
    try:
        declared = version
        if manifest is not None:
            _strict_beneath(manifest, qa_root)
            data = _json(manifest)
            if set(data) != {"schemaVersion", "application", "version",
                             "installerPath", "installerSha256", "installerBytes"}:
                raise GateBlocked("Candidate manifest has missing or unexpected fields")
            if data["schemaVersion"] != 1 or data["application"] != "Taraz":
                raise GateBlocked("Candidate manifest schema/application unsupported")
            if version is not None and version != data["version"]:
                raise GateBlocked("Explicit candidate version differs from manifest")
            declared = data["version"]
        candidate["declaredVersion"] = declared
        if version_tuple(declared) <= version_tuple(INSTALLED_VERSION):
            raise GateBlocked("Candidate must have a STRICTLY higher stable version")
        candidate["versionAdvanced"] = True
        if source.get("version") != declared:
            raise GateBlocked("Source package/lock version does not match candidate")
        if manifest is None:
            raise GateBlocked("A version alone cannot prove an installer candidate")
        if not isinstance(data["installerPath"], str):
            raise GateBlocked("Candidate installer path is invalid")
        installer = Path(data["installerPath"])
        _strict_beneath(installer, qa_root)
        if (installer.suffix.lower() != ".exe"
                or installer.name.lower().startswith("taraz-mtr-qa-")
                or "qa-only" in installer.name.lower()):
            raise GateBlocked("QA-only binary cannot be promoted into an installer")
        if not (isinstance(data["installerSha256"], str)
                and SHA256.fullmatch(data["installerSha256"])
                and type(data["installerBytes"]) is int):
            raise GateBlocked("Invalid candidate installer digest/size fields")
        digest, size = _file_hash(installer)
        if digest != data["installerSha256"] or size != data["installerBytes"]:
            raise GateBlocked("Candidate installer hash/size mismatch")
        if not _looks_pe(installer):
            raise GateBlocked("Candidate does not contain a PE executable header")
        candidate.update({
            "status": "HASH_MATCH_DECLARED_VERSION_ONLY",
            "sha256": digest, "bytes": size,
            "declaredVersionNotBinaryVerified": True,
            "signedInstallerVerified": False,
            "installerExecutionPerformed": False,
        })
    except (GateBlocked, OSError, ValueError) as exc:
        candidate.update({"status": "NO_GO_STATIC_CANDIDATE",
                          "reason": str(exc)})
    return candidate


MINIMUM_UPGRADES = (
    "Bump Taraz source package.json AND package-lock.json above installed "
    "1.0.0; verify version inside a real candidate rather than a filename.",
    "Replace missing dist:rc installer builder with audited Taraz-specific, "
    "create-only higher-version installer; verify publisher signature and "
    "WebView2/prerequisites. Never overwrite the installed 1.0.0 in QA.",
    "Implement a verified Taraz-owned update or explicit secure offline-upgrade "
    "contract with pinned artifact, version, publisher and rollback.",
    "Integrate host-authenticated Madar/Taraz peer/review and finance issuer "
    "modules into a real candidate, verify independent authenticated identities "
    "and durable signed receipts. Metadata reviews are NOT invoice posting.",
    "Prove pre-upgrade three-data-store create-only backups, independent readback, "
    "migration and rollback in disposable environments, including failure cases.",
    "Run source+packed+installed synthetic/UI and exact candidate install/upgrade "
    "compatibility checks, operator-approved installation and post-install "
    "verification before any public release GO.",
)


def decision(installed: dict, source: dict, qa: dict,
             candidate: dict) -> dict:
    blockers: list[str] = []
    if not installed.get("verified"):
        blockers.append("INSTALLED_BINARY_UNVERIFIED")
    if not installed.get("preMoveDurableIntentPresent") or not installed.get(
            "perRequestLockPresent"):
        blockers.append("INSTALLED_1_0_0_LACKS_DURABLE_REVIEW")
    try:
        if version_tuple(source.get("version")) <= version_tuple(INSTALLED_VERSION):
            blockers.append("SOURCE_NOT_NEWER_THAN_INSTALLED")
    except GateBlocked:
        blockers.append("SOURCE_VERSION_INVALID")
    if source.get("updaterUnconfigured") is True:
        blockers.append("TARAZ_UPDATER_NOT_CONFIGURED")
    if source.get("updaterVerifiedConfigured") is not True:
        blockers.append("SECURE_UPDATER_OR_OFFLINE_UPGRADE_UNVERIFIED")
    if not source.get("installerBuilderPresent"):
        blockers.append("TARAZ_INSTALLER_BUILDER_MISSING")
    if qa.get("status") != "QA_BUNDLE_VERIFIED_NOT_RELEASE":
        blockers.append("QA_BINARY_UNVERIFIED")
    else:
        missing = [name for name, loaded in
                   qa.get("sourceIntegrationModuleInPYZ", {}).items()
                   if loaded is not True]
        if missing:
            blockers.append("PEER_AND_FINANCE_ISSUERS_NOT_PACKED")
    if candidate.get("status") != "HASH_MATCH_DECLARED_VERSION_ONLY":
        blockers.append("NO_VERIFIABLE_HIGHER_VERSION_INSTALLER_CANDIDATE")
    # THESE CANNOT BE WAIVED BY USER-SUPPLIED JSON OR AN EXE HASH.
    blockers.extend([
        "SIGNED_INSTALLER_IDENTITY_UNVERIFIED",
        "UPGRADE_BACKUP_MIGRATION_ROLLBACK_NOT_PROVEN",
        "REAL_INSTALL_AUTH_AND_POST_UPGRADE_SMOKE_NOT_PROVEN",
        "OFFICIAL_CROSS_APP_FINANCE_RECEIPT_NOT_PROVEN",
    ])
    return {
        "schemaVersion": 1,
        "decision": "NO_GO",  # Static-only gate cannot issue production release GO.
        "scope": "READ_ONLY_STATIC_AND_SYNTHETIC_RELEASE_GATE",
        "qaOnly": True,
        "releaseApproved": False,
        "installedExecutableLaunched": False,
        "installerBuiltOrLaunched": False,
        "ledgerOrProfileAccessed": False,
        "officialFinanceReceiptVerified": False,
        "blockers": blockers,
        "minimumNextVersionUpgrades": list(MINIMUM_UPGRADES),
    }


def run(*, root: Path = SOURCE, exe: Path | None = None,
        qa_report: Path = DEFAULT_QA_REPORT,
        candidate_version: str | None = None,
        candidate_manifest: Path | None = None) -> dict:
    """Fail closed and return JSON-readable reasons; never alter any artifact."""
    checks: dict[str, dict] = {}
    for key, fn in (
        ("source", lambda: inspect_source(root)),
        ("installed", lambda: inspect_installed(exe or installed_path())),
    ):
        try:
            checks[key] = fn()
        except Exception as exc:
            checks[key] = {"verified": False, "status": "UNVERIFIED",
                           "reason": str(exc)}
    try:
        checks["qa"] = inspect_qa(qa_report, checks["source"])
    except Exception as exc:
        checks["qa"] = {"status": "UNVERIFIED", "reason": str(exc)}
    try:
        checks["candidate"] = inspect_candidate(
            candidate_version, candidate_manifest, checks["source"],
            qa_root=SOURCE.parents[1])
    except Exception as exc:
        checks["candidate"] = {"status": "NO_GO_STATIC_CANDIDATE",
                               "reason": str(exc)}
    result = decision(checks["installed"], checks["source"],
                      checks["qa"], checks["candidate"])
    result["evidence"] = checks
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-report", type=Path, default=DEFAULT_QA_REPORT,
                        help="Read-only report within the known D: QA root")
    parser.add_argument("--candidate-version", help="Future strict x.y.z only")
    parser.add_argument("--candidate-manifest", type=Path,
                        help="Optional read-only installer manifest within D: QA root")
    args = parser.parse_args(argv)
    result = run(qa_report=args.qa_report, candidate_version=args.candidate_version,
                 candidate_manifest=args.candidate_manifest)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["decision"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
