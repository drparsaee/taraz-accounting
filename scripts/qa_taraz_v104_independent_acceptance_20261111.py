"""Independent read-only Taraz 1.0.4 P1 candidate acceptance.

NO installed profile, real accounting, services or user desktop writes.
An explicit *separate* worker26 test witness is required before optional
Windows PowerShell installer/activation exercise on a disposable profile.
Passing artifact tests never grants production / finance / live-GUI signoff.
"""
from __future__ import annotations

import argparse
import ctypes
import dis
import difflib
import hashlib
import json
import marshal
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import uuid
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT = PARENT / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.4-p1"
STAGE = OUTPUT / "source-stage-959986753b61"
VITE = OUTPUT / "vite-qa-1ff6df468d81"
BACKUP = PARENT / "MTR-REAL-UPGRADE-BACKUPS-20261110" / "taraz-v103-cold-20261111"
STAGE_SOURCE_SHA = "6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1"
ORIGINAL_SOURCE_SHA = "a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279"
STAGE_MAP_SHA = "12f54656851c65e981d6bf20bb86952029d57ef79081d26c5dde51d6565f1add"
VITE_JS_SHA = "b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453"
V103_JS_SHA = "001e9e7e622fee9cc375461b754847a978c0b16563a72a4cd8e5d784ca8512b4"
V102_SHA = "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52"
BACKUP_MANIFEST_SHA = "8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d"
BACKUP_REPORT_SHA = "68bb6e26b9a9a10818e6752a7cc1475a3861c5f380f2021eb5c112a74cd7d2c9"
MAX_JSON = 2 * 1024 * 1024
MAX_SOURCE = 30 * 1024 * 1024
MAX_EXE = 80 * 1024 * 1024
MAX_ARCHIVE = 85 * 1024 * 1024
MAX_BACKUP_TOTAL = 300 * 1024 * 1024
COUNT = 131
ZIP_NAMES = frozenset({
    "Taraz.exe", "Install-Taraz-V104.ps1", "Activate-Taraz-V104.ps1",
    "package.json", "package-lock.json", "source-sha256.json",
    "update-manifest.json",
})
NATIVE_METHODS = frozenset({
    "tarazMadarDataOverview", "tarazMadarDataRead",
    "tarazIntegrationList", "tarazIntegrationReview", "tarazIntegrationRecover",
})
PYZ_MODULES = {
    "taraz_madar_data_reader": {
        "local_madar_available", "read_local_madar_state",
        "read_authorized_madar_state", "_network_config", "_validate_paging",
    },
    "standalone_accounting_template_store": {
        "save", "set_default", "delete", "duplicate",
    },
    "taraz_integration": set(),
    "personal_parsian_bridge": set(),
    "standalone_accounting_auto_backup": set(),
}
PATCHED = frozenset({
    "src/accounting_action_home.jsx", "src/parsian_raw_archive_explorer.jsx",
    "src/personal_parsian_bank_movements.jsx", "src/personal_parsian_company.jsx",
    "src/personal_parsian_dashboard.jsx", "src/personal_parsian_extended.jsx",
    "src/personal_parsian_invoices.jsx", "src/provider_csv_migration.jsx",
    "src/taraz_home_command.jsx",
})
REJECTED_V104_BUILD = OUTPUT / "build-6d851f756264"
REJECTED_V104_EXE_SHA = "8e2a8026b48e278df95693d9349f5a566df9b75c12497882b3bebca96679adc6"
REJECTED_V104_ZIP_SHA = "721bbf8d6fd461fb1317fb1394b26d0ad67237d4fbc8f3d9cbfc8442b5f79777"
RC2_TARGETS = frozenset({
    "src/accounting_print_designer.jsx",
    "src/accounting_operational_panels.jsx",
    "src/accounting_management_dashboard.jsx",
})

# Source-only RC2 patch anchors. Keep existing self-authored validation:
# - print designer image size/type and template validator remain unchanged
# - bank CSV file-size, structural and row-specific parser diagnostics survive;
#   arbitrary File.text() errors NEVER enter those parser diagnostics
# - management range validator precedes the masked analytics catch.
RC2_PATCHES = {
    "src/accounting_print_designer.jsx": (
        "}).catch(e=>{if(active)setError(e.message||'پیش‌نمایش ناموفق بود.');})",
        "}).catch(_error=>{if(active)setError('پیش‌نمایش ناموفق بود؛ قالب چاپ و تصویر را بررسی کنید.');})",
    ),
    "src/accounting_management_dashboard.jsx": (
        "catch(err){return {analytics:null,error:err?.message||'محاسبه شاخص‌های مدیریتی ناموفق بود.'};}",
        "catch(_error){return {analytics:null,error:'محاسبه شاخص‌های مدیریتی ناموفق بود؛ داده‌های منبع را بررسی کنید.'};}",
    ),
    "src/accounting_operational_panels.jsx": (
        "          try{\n"
        "            if(file.size>1024*1024)throw Error('فایل CSV بیش از ۱ مگابایت است.');\n"
        "            const value=await file.text();\n"
        "            setImportRows(parseAccountingBankCSV(value,{\n"
        "              accounts:view.accounts,existing:view.bankStatements,today}));\n"
        "          }catch(err){setImportError(err.message||'خواندن فایل معتبر نبود.');}\n"
        "          finally{setImportReading(false);}",
        "          try{\n"
        "            if(file.size>1024*1024){\n"
        "              setImportError('فایل CSV بیش از ۱ مگابایت است.');return;\n"
        "            }\n"
        "            let value;\n"
        "            try{value=await file.text();}\n"
        "            catch(_error){\n"
        "              setImportError('خواندن فایل CSV بانک ناموفق بود.');return;\n"
        "            }\n"
        "            try{\n"
        "              setImportRows(parseAccountingBankCSV(value,{\n"
        "                accounts:view.accounts,existing:view.bankStatements,today}));\n"
        "            }catch(err){\n"
        "              const message=String(err?.message||'');\n"
        "              const authored=new Set([\n"
        "                'فایل CSV بیش از ۱ مگابایت است یا معتبر نیست.',\n"
        "                'تاریخ مرجع ثبت معتبر نیست.',\n"
        "                'عنوان ستون‌های CSV باید دقیقاً مطابق قالب اعلام‌شده باشد.',\n"
        "                'تعداد ردیف باید بین ۱ و ۵۰۰ باشد.',\n"
        "              ]);\n"
        "              const rowError=/^(?:قالب ردیف [0-9]{1,3} معتبر نیست\\.|شناسه، حساب بانکی یا تاریخ ردیف [0-9]{1,3} معتبر نیست\\.|شناسه مرجع بانک در ردیف [0-9]{1,3} معتبر نیست\\.|مبلغ ردیف [0-9]{1,3} باید عدد صحیح علامت‌دار باشد\\.|شناسه یا مرجع بانکی تکراری در ردیف [0-9]{1,3} وجود دارد\\.)$/;\n"
        "              setImportError(authored.has(message)||rowError.test(message)\n"
        "                ?message:'خواندن فایل معتبر نبود.');\n"
        "            }\n"
        "          }finally{setImportReading(false);}",
    ),
}


class Blocked(RuntimeError):
    """A missing or inconsistent witness must never become a GO."""


def hash_file(path: Path, *, max_bytes: int = MAX_EXE) -> str:
    regular(path, max_bytes=max_bytes)
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for piece in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(piece)
    return hasher.hexdigest()


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_ok(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value) is not None


def regular(path: Path, *, directory: bool = False, max_bytes: int = MAX_EXE) -> Path:
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and
                                getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
            raise Blocked("Symlink/junction/reparse path refused")
    if directory:
        if not path.is_dir():
            raise Blocked("Required directory absent")
    elif not (path.is_file() and stat.S_ISREG(path.stat().st_mode)
              and 0 <= path.stat().st_size <= max_bytes):
        raise Blocked("Required file unavailable/nonregular/oversized")
    return path


def checked_hash(path: Path, expected: object, *, cap: int = MAX_EXE) -> str:
    if not sha_ok(expected) or hash_file(path, max_bytes=cap) != expected:
        raise Blocked("Missing/mismatched pinned file hash")
    return expected


def load_json(path: Path) -> dict:
    regular(path, max_bytes=MAX_JSON)
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError, UnicodeError) as exc:
        raise Blocked("Unparseable JSON witness") from exc
    if not isinstance(obj, dict):
        raise Blocked("Expected JSON object witness")
    return obj


def relative(name: object) -> Path:
    if (not isinstance(name, str) or not name or len(name) > 500
            or name.startswith("/") or "\\" in name or ":" in name
            or "//" in name or name.endswith("/")
            or re.search(r'[<>|"?*\x00-\x1f]', name)):
        raise Blocked("Unsafe relative source/ZIP filename")
    parts = PurePosixPath(name).parts
    if (not parts or any(part in (".", "..", "") or
                         part.endswith((".", " ")) for part in parts)):
        raise Blocked("Untrusted path traversal")
    return Path(*parts)


def fingerprint(entries: dict) -> str:
    if (not isinstance(entries, dict) or
            any(not sha_ok(value) or not isinstance(name, str)
                for name, value in entries.items())):
        raise Blocked("Invalid 131-file source hash inventory")
    for name in entries:
        relative(name)
    if len(set(x.casefold() for x in entries)) != len(entries):
        raise Blocked("Case-fold duplicate manifest path")
    return hash_bytes(json.dumps(entries, sort_keys=True).encode("utf-8"))


def check_source_tree(folder: Path, entries: dict) -> int:
    regular(folder, directory=True)
    found = set()
    for base, folders, files in os.walk(folder, followlinks=False):
        for entry in folders:
            regular(Path(base) / entry, directory=True)
        for name in files:
            file = Path(base) / name
            key = file.relative_to(folder).as_posix()
            if key not in entries:
                raise Blocked("Unlisted source file")
            checked_hash(file, entries[key], cap=MAX_SOURCE)
            found.add(key)
    if found != set(entries):
        raise Blocked("Missing source file in 131-file stage")
    return len(found)


def verify_stage() -> dict:
    regular(STAGE, directory=True)
    manifest = STAGE / "patched-source-sha256.json"
    checked_hash(manifest, STAGE_MAP_SHA, cap=MAX_JSON)
    stage_report = load_json(STAGE / "stage-report.json")
    files = load_json(manifest)
    if not (len(files) == COUNT
            and fingerprint(files) == STAGE_SOURCE_SHA
            and stage_report.get("status") == "V104_PATCHED_SOURCE_FROZEN_QA_PENDING_NO_EXE"
            and stage_report.get("patchedSourceSha256") == STAGE_SOURCE_SHA
            and stage_report.get("patchedInventoryFileSha256") == STAGE_MAP_SHA
            and stage_report.get("frozenStartingSha256") == ORIGINAL_SOURCE_SHA
            and stage_report.get("editedSourceFileCount") == len(PATCHED)
            and set(stage_report.get("editedSourceFiles", [])) == PATCHED
            and stage_report.get("executableBuilt") is False):
        raise Blocked("131-file v104 stage source authority incomplete")
    check_source_tree(STAGE / "source", files)
    return {"sourceCount": COUNT, "sha256": STAGE_SOURCE_SHA,
            "stageReportSha256": hash_file(STAGE / "stage-report.json", max_bytes=MAX_JSON),
            "inventoryFileSha256": STAGE_MAP_SHA, "inventory": files}


def verify_vite(stage: dict) -> dict:
    regular(VITE, directory=True)
    report = load_json(VITE / "vite-qa-report.json")
    if not (report.get("status") == "STAGE_UI_ONLY"
            and report.get("patchedSourceSha256") == stage["sha256"]
            and report.get("sourceStagePath") == str(STAGE)
            and report.get("sourceStageReportSha256") == stage["stageReportSha256"]
            and report.get("sourceInventorySha256") == stage["inventoryFileSha256"]
            and report.get("compiledFrontend") is True
            and report.get("compiledExeBuilt") is False
            and report.get("compiledBundleReleaseReady") is False
            and report.get("browserQaVerified") is False):
        raise Blocked("UI-only stage provenance conflicts")
    entries = {}
    for key, digest_key in (("jsRelativePath", "viteJsSha256"),
                            ("cssRelativePath", "viteCssSha256"),
                            ("htmlRelativePath", "viteHtmlSha256")):
        rel = relative(report.get(key))
        if rel.parts[0] != "dist":
            raise Blocked("Vite asset outside dist")
        checked_hash(VITE / rel, report.get(digest_key), cap=MAX_SOURCE)
        entries[rel.relative_to("dist").as_posix()] = report[digest_key]
    if report.get("viteJsSha256") != VITE_JS_SHA:
        raise Blocked("Original stage-Edge JS pin differs")
    return {"sha256": VITE_JS_SHA, "assetPins": entries,
            "reportSha256": hash_file(VITE / "vite-qa-report.json", max_bytes=MAX_JSON)}


def installed_baseline() -> dict:
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise Blocked("Windows LOCALAPPDATA required for real read-only baseline")
    root = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz"
    regular(root, directory=True)
    pointer = root / "current-version.txt"
    launcher = root / "Run-Taraz.cmd"
    exe = root / "versions" / "1.0.2" / "Taraz.exe"
    if regular(pointer).read_text(encoding="utf-8-sig").strip() != "1.0.2":
        raise Blocked("Installed original pointer not 1.0.2")
    checked_hash(exe, V102_SHA)
    if "versions\\%TARAZ_VERSION%\\Taraz.exe" not in regular(launcher).read_text(
            encoding="utf-8", errors="replace"):
        raise Blocked("Installed launcher version contract changed")
    if (root / "versions" / "1.0.4").exists() or (root / "versions" / "1.0.4").is_symlink():
        raise Blocked("Installed v1.0.4 destination already exists")
    return {"pointerVersion": "1.0.2", "baselineExeSha256": V102_SHA,
            "pointerSha256": hash_file(pointer), "launcherSha256": hash_file(launcher),
            "installedV104Absent": True}


def backup_readback() -> dict:
    regular(BACKUP, directory=True)
    checked_hash(BACKUP / "snapshot-manifest.json", BACKUP_MANIFEST_SHA, cap=MAX_JSON)
    checked_hash(BACKUP / "backup-acceptance-report.json", BACKUP_REPORT_SHA, cap=MAX_JSON)
    mf = load_json(BACKUP / "snapshot-manifest.json")
    report = load_json(BACKUP / "backup-acceptance-report.json")
    witness = report.get("backup")
    files = mf.get("files")
    if (not isinstance(files, dict) or len(files) != 181
            or not isinstance(mf.get("sqliteChecks"), dict)
            or len(mf["sqliteChecks"]) != 67
            or mf.get("fileCount") != 181
            or mf.get("totalBytes") != 124_011_875
            or mf.get("verifiedNoOverwrite") is not True
            or mf.get("allFilesIncluded") is not True
            or report.get("status") != "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING"
            or report.get("installedBefore") != "1.0.2"
            or report.get("installedAfter") != "1.0.2"
            or not isinstance(witness, dict)
            or witness.get("backupRoot") != str(BACKUP)
            or witness.get("manifestSha256") != BACKUP_MANIFEST_SHA
            or witness.get("independentReadback") is not True
            or witness.get("fileCount") != 181
            or witness.get("sqliteValidatedCount") != 67):
        raise Blocked("Independent 181-file cold-backup evidence invalid")
    found, total = set(), 0
    for base, dirs, names in os.walk(BACKUP / "files", followlinks=False):
        for dirname in dirs:
            regular(Path(base) / dirname, directory=True)
        for name in names:
            path = Path(base) / name
            rel = path.relative_to(BACKUP / "files").as_posix()
            if relative(rel).parts[0] not in ("roaming", "local", "bridge") or rel not in files:
                raise Blocked("Unlisted/unsafe cold-backup file")
            item = files[rel]
            if not isinstance(item, dict) or not isinstance(item.get("bytes"), int):
                raise Blocked("Backup manifest file entry lacks size")
            checked_hash(path, item.get("sha256"), cap=MAX_BACKUP_TOTAL)
            if path.stat().st_size != item["bytes"]:
                raise Blocked("Backup source size changed")
            total += item["bytes"]
            if total > MAX_BACKUP_TOTAL:
                raise Blocked("Backup size exceeds independent budget")
            found.add(rel)
    if found != set(files) or total != mf["totalBytes"] or total != witness.get("totalBytes"):
        raise Blocked("Backup source set/total does not agree")
    return {"filesRehashed": len(found), "bytesRehashed": total,
            "sqliteValidatedByPriorWitnessOnly": 67,
            "manifestSha256": BACKUP_MANIFEST_SHA, "acceptanceSha256": BACKUP_REPORT_SHA}


def discover_build() -> Path:
    regular(OUTPUT, directory=True)
    builds = [path for path in OUTPUT.glob("build-*") if path.is_dir()
              and (path / "build-report.json").is_file()]
    if len(builds) != 1:
        raise Blocked("Expected ONE completed worker26 build; found " + str(len(builds)))
    return regular(builds[0], directory=True)


def check_release_metadata(report: dict, mf: dict, source: dict) -> None:
    if not (report.get("status") == "PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED"
            and report.get("version") == "1.0.4"
            and report.get("sourceFreezeSha256") == source["sha256"]
            and report.get("sourceFileCount") == COUNT
            and report.get("installed") is False
            and report.get("pointerChanged") is False
            and report.get("releaseApproved") is False
            and mf.get("targetVersion") == "1.0.4"
            and mf.get("sourceSnapshotSha256") == source["sha256"]
            and mf.get("sourceFilesCount") == COUNT
            and mf.get("installedBaselineVersion") == "1.0.2"
            and mf.get("installedBaselineSha256") == V102_SHA
            and mf.get("peVersion") == "1.0.4.0"
            and mf.get("pyzVersion") == "1.0.4"
            and mf.get("qaOnly") is False
            and mf.get("productionCandidate") is True
            and mf.get("unsigned") is True
            and mf.get("installed") is False
            and mf.get("pointerActivated") is False
            and mf.get("activationApprovalGranted") is False
            and mf.get("financePostingProven") is False
            and mf.get("compiledEdgeRedactionApproved") is False):
        raise Blocked("Candidate manifest or report status/versions contradicted")


def pe_version(exe: Path) -> str:
    regular(exe)
    if os.name != "nt":
        raise Blocked("Native PE resource inspection requires Windows")
    library = ctypes.windll.version
    library.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    library.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
    size = library.GetFileVersionInfoSizeW(str(exe), ctypes.byref(ctypes.c_ulong()))
    if not 64 <= size <= 1_000_000:
        raise Blocked("Missing fixed PE version info")
    memory = ctypes.create_string_buffer(size)
    library.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong,
                                            ctypes.c_ulong, ctypes.c_void_p]
    library.GetFileVersionInfoW.restype = ctypes.c_int
    if not library.GetFileVersionInfoW(str(exe), 0, size, memory):
        raise Blocked("PE resource read failed")
    pointer, length = ctypes.c_void_p(), ctypes.c_uint()
    library.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                       ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(ctypes.c_uint)]
    library.VerQueryValueW.restype = ctypes.c_int
    if not library.VerQueryValueW(memory, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        raise Blocked("Missing PE fixed version record")
    data = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))
    if data[0] != 0xFEEF04BD:
        raise Blocked("Invalid PE fixed version signature")
    return (f"{data[2] >> 16}.{data[2] & 65535}."
            f"{data[3] >> 16}.{data[3] & 65535}")


def assigned(code: types.CodeType, name: str):
    commands = list(dis.get_instructions(code))
    for i, command in enumerate(commands):
        if (i > 0 and command.opname in ("STORE_NAME", "STORE_GLOBAL")
                and command.argval == name and commands[i-1].opname == "LOAD_CONST"):
            return commands[i-1].argval
    raise Blocked("Missing literal release assignment: " + name)


def methods(code: types.CodeType) -> set[str]:
    names: set[str] = set()
    for child in code.co_consts:
        if isinstance(child, types.CodeType):
            names.add(child.co_name)
            names.update(methods(child))
    return names


def strings(code: types.CodeType) -> list[str]:
    found = [x for x in code.co_consts if isinstance(x, str)]
    for nested in code.co_consts:
        if isinstance(nested, types.CodeType):
            found += strings(nested)
    return found


def inspect_exe(exe: Path, ui: Path, expected_assets: dict) -> dict:
    from PyInstaller.archive.readers import CArchiveReader

    if pe_version(exe) != "1.0.4.0":
        raise Blocked("Compiled executable actual PE != 1.0.4.0")
    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    release = pyz.extract("taraz_release_version")
    if not isinstance(release, types.CodeType) or (
            assigned(release, "APP_VERSION") != "1.0.4"
            or assigned(release, "QA_ONLY") is not False
            or assigned(release, "BUILD_CHANNEL") != "offline-production-candidate"):
        raise Blocked("EXE PYZ release not exactly non-QA 1.0.4")
    entry = archive.extract("taraz_desktop")
    if not isinstance(entry, bytes):
        raise Blocked("Native taraz_desktop entrypoint absent")
    try:
        entry_code = marshal.loads(entry)
    except (ValueError, TypeError, EOFError) as exc:
        raise Blocked("Invalid compiled native entry") from exc
    if not isinstance(entry_code, types.CodeType) or not NATIVE_METHODS <= methods(entry_code):
        raise Blocked("Native required Madar methods missing")
    if "_taraz_qa_launch_gate" in methods(entry_code):
        raise Blocked("QA-only entry guard found in native")
    for name, expected in PYZ_MODULES.items():
        part = pyz.extract(name)
        if not isinstance(part, types.CodeType) or not expected <= methods(part):
            raise Blocked("Missing required compiled PYZ module")
    bridge = pyz.extract("standalone_accounting_desktop")
    if not isinstance(bridge, types.CodeType):
        raise Blocked("Compiled WebView bridge absent")
    allowlist = [x for x in strings(bridge) if "window.madar = Object.fromEntries(" in x]
    if len(allowlist) != 1 or not all("'" + x + "'" in allowlist[0] for x in NATIVE_METHODS):
        raise Blocked("WebView native bridge forwarding incomplete")
    mapping = {key.replace("\\", "/"): key for key in archive.toc}
    files = {}
    for folder, dirs, names in os.walk(ui, followlinks=False):
        for name in dirs:
            regular(Path(folder) / name, directory=True)
        for name in names:
            path = Path(folder) / name
            rel = path.relative_to(ui).as_posix()
            if rel not in expected_assets:
                raise Blocked("Extra compiled UI asset not in manifest")
            local_sha = checked_hash(path, expected_assets[rel], cap=MAX_SOURCE)
            member = mapping.get("dist/" + rel)
            if not member:
                raise Blocked("Compiled UI asset missing from EXE")
            embedded = archive.extract(member)
            if not isinstance(embedded, bytes) or hash_bytes(embedded) != local_sha:
                raise Blocked("Compiled UI asset differs inside EXE")
            files[rel] = local_sha
    if files != expected_assets or not any(x.endswith(".js") for x in files):
        raise Blocked("Compiled UI full asset set mismatch")
    js = [sha for name, sha in files.items() if name.endswith(".js")]
    if len(js) != 1 or js[0] != VITE_JS_SHA or V103_JS_SHA in js:
        raise Blocked("Actual EXE compiled JS not the Edge-tested 1.0.4-stage byte")
    return {"peVersion": "1.0.4.0", "pyzVersion": "1.0.4",
            "qaOnly": False, "nativeMethodsVerified": len(NATIVE_METHODS),
            "pyzModulesVerified": len(PYZ_MODULES), "embeddedAssetsVerified": len(files),
            "embeddedJsSha256": VITE_JS_SHA,
            "compiledRedactionDynamicVerifiedHere": False}


def secure_installer_static(install: str, activate: str) -> dict:
    for script in (install, activate):
        for required in ("param([switch]$Apply", "Set-StrictMode -Version Latest",
                         "function SafePath", "function CanonicalLocal",
                         "function CheckPackagePins", "function CheckBackup",
                         "function CheckNoTaraz", "HardlinkCount",
                         "$parent=$item.Directory", "RequireAbsent",
                         "Get-CimInstance", "TarazV104SecureLinkInfo"):
            if required not in script:
                raise Blocked("Installer missing a required fail-closed guard: " + required)
        if any(x in script for x in ("$item=$item.Parent", "Start-Process",
                                    "TarazV103SecureLinkInfo", "__NEW_SHA__", "1.0.3")):
            raise Blocked("Unsafe inherited installer placeholder/version")
        if "1.0.4" not in script or "1.0.2" not in script:
            raise Blocked("Installer 1.0.4 / 1.0.2 version anchors missing")
    for required in ("[IO.File]::Replace($pending,$pointer,$oldPointer,$true)",
                     "Run-Taraz-pre-1.0.4.cmd", "current-version-pre-1.0.4.txt",
                     "current-version-1.0.4-pending.txt"):
        if required not in activate:
            raise Blocked("Activation has wrong pointer/launcher backup naming")
    if "INSTALLED_SIDE_BY_SIDE_1.0.4_POINTER_REMAINS_1.0.2" not in install:
        raise Blocked("Install pointer-state contract missing")
    return {"requiredHardlinkGuard": True, "fileInfoDirectoryAncestry": True,
            "activationPointerNaming": "1.0.4", "nativeWriteTestedHere": False}


def verify_zip_members(zip_path: Path, package_files: dict[str, Path]) -> dict:
    if set(package_files) != ZIP_NAMES:
        raise Blocked("Expected seven exact detached v104 offline members")
    regular(zip_path, max_bytes=MAX_ARCHIVE)
    hashes = {name: hash_file(path) for name, path in package_files.items()}
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if len(members) != len(ZIP_NAMES) or {m.filename for m in members} != ZIP_NAMES:
            raise Blocked("Missing/duplicate/unexpected ZIP member")
        if len({m.filename.casefold() for m in members}) != len(members):
            raise Blocked("Ambiguous ZIP member names")
        for member in members:
            if member.is_dir() or member.file_size > MAX_EXE:
                raise Blocked("Invalid ZIP member type/size")
            relative(member.filename)
            with archive.open(member) as stream:
                digest = hashlib.sha256()
                while True:
                    portion = stream.read(1024 * 1024)
                    if not portion:
                        break
                    digest.update(portion)
            if digest.hexdigest() != hashes[member.filename]:
                raise Blocked("ZIP member bytes differ from 7-file offline directory")
    return {"zipMembersRehashed": len(ZIP_NAMES), "zipSha256":
            hash_file(zip_path, max_bytes=MAX_ARCHIVE)}


def inspect_candidate(build: Path, stage: dict, vite: dict) -> dict:
    regular(build, directory=True)
    if build.parent.resolve() != OUTPUT.resolve() or not re.fullmatch(r"build-[0-9a-f]{12}", build.name):
        raise Blocked("Candidate must be worker26 build under v104 root")
    report = load_json(build / "build-report.json")
    off = regular(build / "offline-update", directory=True)
    mf = load_json(off / "update-manifest.json")
    check_release_metadata(report, mf, stage)
    inventory = load_json(off / "source-sha256.json")
    if len(inventory) != COUNT or fingerprint(inventory) != STAGE_SOURCE_SHA:
        raise Blocked("Candidate offline frozen 131-file source SHA wrong")
    if inventory != stage["inventory"]:
        raise Blocked("Candidate source hashes not equal to staged source")
    checked_hash(off / "source-sha256.json", mf.get("sourceFileManifestSha256"), cap=MAX_JSON)
    build_source = build / "source"
    for name, sha in inventory.items():
        if name not in ("taraz_desktop.py", "package.json", "package-lock.json"):
            checked_hash(build_source / relative(name), sha, cap=MAX_SOURCE)
    staged = mf.get("stagedVersionSourceSha256")
    if not isinstance(staged, dict):
        raise Blocked("Missing detached 1.0.4 staged version witness")
    for rel, key in (("taraz_desktop.py", "nativeEntrySha256"),
                     ("taraz_release_version.py", "versionModuleSha256"),
                     ("package.json", "packageSha256"),
                     ("package-lock.json", "lockSha256")):
        checked_hash(build_source / rel, staged.get(key), cap=MAX_SOURCE)
    for name, key in (("package.json", "stagedPackageSha256"),
                      ("package-lock.json", "stagedLockSha256")):
        checked_hash(off / name, mf.get(key), cap=MAX_SOURCE)
        checked_hash(build_source / name, mf.get(key), cap=MAX_SOURCE)
    package, lock = load_json(off / "package.json"), load_json(off / "package-lock.json")
    if [package.get("version"), lock.get("version"),
            lock.get("packages", {}).get("", {}).get("version")] != ["1.0.4"] * 3:
        raise Blocked("Actual candidate package/lock version not 1.0.4")
    expected_binary = report.get("exeSha256")
    if not sha_ok(expected_binary) or expected_binary != mf.get("exeSha256"):
        raise Blocked("EXE hash unpinned by report+manifest")
    binary = build / "binary" / "Taraz.exe"
    checked_hash(binary, expected_binary)
    checked_hash(off / "Taraz.exe", expected_binary)
    if mf.get("exeBytes") != binary.stat().st_size:
        raise Blocked("Native candidate EXE byte count wrong")
    claimed = report.get("compiled", {}).get("uiAssetsSha256")
    if (not isinstance(claimed, dict) or not claimed
            or claimed != mf.get("compiledEvidence", {}).get("uiAssetsSha256")
            or mf.get("compiledEvidence", {}).get("compiledJsSha256") != {
                k: v for k, v in claimed.items() if k.endswith(".js")}):
        raise Blocked("Compiled UI manifest disagreement")
    html_rel = next((name for name in claimed if name == "accounting.html"), None)
    if html_rel is None:
        raise Blocked("Compiled HTML entry absent")
    for name, pin in vite["assetPins"].items():
        if claimed.get(name) != pin:
            raise Blocked("New Vite JS/CSS/HTML differs from staged Edge asset")
    compiled = inspect_exe(binary, build / "web" / "dist", claimed)
    if (report.get("compiled", {}).get("peVersion") != compiled["peVersion"]
            or report.get("compiled", {}).get("pyzVersion") != compiled["pyzVersion"]):
        raise Blocked("Build report compiled PE/PYZ conflicts with real binary")
    for name, key in (("Install-Taraz-V104.ps1", "installScriptSha256"),
                      ("Activate-Taraz-V104.ps1", "activationScriptSha256")):
        checked_hash(off / name, mf.get(key), cap=MAX_SOURCE)
        if report.get(key) != mf[key]:
            raise Blocked("Packaged script SHA conflicts with build report")
    script = secure_installer_static(
        (off / "Install-Taraz-V104.ps1").read_text(encoding="utf-8"),
        (off / "Activate-Taraz-V104.ps1").read_text(encoding="utf-8"))
    security = mf.get("secureRepackage", {})
    if (security.get("hardlinkAndAncestorGuard") != "Win32-linkcount-and-each-ancestor"
            or security.get("sourceStageInventorySha256") != STAGE_MAP_SHA
            or security.get("sourceStagePath") != str(STAGE)
            or security.get("launcherBackupName") != "Run-Taraz-pre-1.0.4.cmd"
            or security.get("rollbackIncluded") is not False
            or security.get("productionApproved") is not False):
        raise Blocked("Source/installer security provenance mismatch")
    for kind, report_key in (("applied-source-stage", "stageQA"),
                             ("staged-edge-redaction", "stagedEdgeQA")):
        witness = security.get(report_key)
        cited = report.get("sourceStageQA" if kind == "applied-source-stage"
                           else "stagedEdgeQA")
        if not isinstance(witness, dict) or cited != witness:
            raise Blocked("External stage/Edge QA witness conflicts with signed build record")
        if (witness.get("kind") != kind or not sha_ok(witness.get("reportSha256"))
                or not isinstance(witness.get("path"), str)):
            raise Blocked("External QA witness not pinned")
        witness_path = Path(witness["path"])
        checked_hash(witness_path, witness["reportSha256"], cap=MAX_JSON)
        independent = load_json(witness_path)
        if (independent.get("kind") != kind or independent.get("status") != "PASS"
                or independent.get("sourceStage") != str(STAGE)
                or independent.get("sourceSha256") != STAGE_SOURCE_SHA
                or independent.get("sourceCount") != COUNT
                or independent.get("failures") != 0
                or not isinstance(independent.get("checksPassed"), int)
                or independent["checksPassed"] < 1
                or independent["checksPassed"] != witness.get("checksPassed")):
            raise Blocked("External stage/Edge QA witness content not genuine PASS for pinned source")
    package_files = {path.name: path for path in off.iterdir() if path.is_file()}
    if set(package_files) != ZIP_NAMES:
        raise Blocked("Offline package must contain exactly 7 files")
    for path in off.iterdir():
        if not path.is_file():
            raise Blocked("Nonregular offline package member")
    zip_path = build / "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip"
    checked_hash(zip_path, report.get("zipSha256"), cap=MAX_ARCHIVE)
    verified_zip = verify_zip_members(zip_path, package_files)
    if report.get("zip") != str(zip_path):
        raise Blocked("Untrusted offline ZIP path in build report")
    return {"status": "STATIC_V104_BINARY_ZIP_AND_SOURCE_PASSED_NO_GO",
            "exeSha256": expected_binary, "zipSha256": hash_file(zip_path, max_bytes=MAX_ARCHIVE),
            "manifestSha256": hash_file(off / "update-manifest.json", max_bytes=MAX_JSON),
            "buildReportSha256": hash_file(build / "build-report.json", max_bytes=MAX_JSON),
            "sourceFreezeSha256": STAGE_SOURCE_SHA, "sourceFilesRehashed": COUNT,
            "zipMemberCount": verified_zip["zipMembersRehashed"],
            "compiled": compiled, "installer": script,
            "nativeExecuted": False, "financePostingProven": False,
            "worker27CompiledGuiRedactionApproval": False,
            "operatorRollbackApproved": False}


def independent_worker26_witness(path: Path, pin: str, build: Path) -> dict:
    """Do not run executable PowerShell unless *external* worker26 test says PASS.

    The witness is provenance/sequence gating, not a substitute for our own
    disposable tests. The independent test verifies the pinned witness bytes.
    """
    if path is None or not sha_ok(pin):
        raise Blocked("Exact external worker26 disposable QA report SHA required")
    checked_hash(path, pin, cap=MAX_JSON)
    proof = load_json(path)
    if (proof.get("status") != "PASS" or
            proof.get("buildDirectory") != str(build) or
            proof.get("testsFailed") != 0 or
            not isinstance(proof.get("testsPassed"), int) or
            proof["testsPassed"] < 1 or
            proof.get("installedProfileChanged") is not False or
            proof.get("financePosted") is not False):
        raise Blocked("Worker26 test witness does not prove disposable script tests")
    return {"worker26WitnessSha256": pin, "worker26TestsPassed": proof["testsPassed"]}


def propose_rc2_text(relative_path: str, text: str) -> str:
    if relative_path not in RC2_PATCHES:
        raise Blocked("RC2 path not in reviewed three-sink ownership")
    old, updated = RC2_PATCHES[relative_path]
    newline = "\r\n" if "\r\n" in text else "\n"
    source_anchor, replacement = old.replace("\n", newline), updated.replace("\n", newline)
    if text.count(source_anchor) != 1:
        raise Blocked("Unreviewed or drifted original RC2 source handler")
    patched = text.replace(source_anchor, replacement, 1)
    if patched == text or source_anchor in patched:
        raise Blocked("RC2 source masking not a unique change")
    return patched


def build_rc2_source_stage() -> Path:
    """Detached RC2: 131 exact Stage B inputs, ONLY three newly masked sources."""
    before = verify_stage()
    checked_hash(REJECTED_V104_BUILD / "binary" / "Taraz.exe", REJECTED_V104_EXE_SHA)
    checked_hash(REJECTED_V104_BUILD /
                 "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip",
                 REJECTED_V104_ZIP_SHA, cap=MAX_ARCHIVE)
    run = OUTPUT / ("source-stage-" + uuid.uuid4().hex[:12])
    if run.exists() or run.is_symlink():
        raise Blocked("RC2 output destination already exists")
    run.mkdir(exist_ok=False)
    output_report = run / "stage-report.json"
    summary = {"status": "BLOCKED", "parentStage": str(STAGE),
               "startingSourceSha256": STAGE_SOURCE_SHA,
               "originalV104Build": str(REJECTED_V104_BUILD),
               "originalV104BuildModified": False,
               "originalV103OrInstalledModified": False,
               "executableBuilt": False, "releaseApproved": False,
               "dynamicRC2EdgeVerified": False, "financeSignoff": False}
    try:
        # Existing source snapshot helper is the same trusted 131-input path
        # used for the original stage. It refuses writes to existing dirs.
        from scripts.build_taraz_v103_p1_release_20261111 import base
        copy = run / "source"
        base.snapshot_source(STAGE / "source", copy, before["inventory"])
        check_source_tree(copy, before["inventory"])
        patches = run / "reviewed-patches"
        patches.mkdir(exist_ok=False)
        new_map = dict(before["inventory"])
        patch_evidence = {}
        for name in sorted(RC2_TARGETS):
            path = copy / relative(name)
            old = path.read_bytes().decode("utf-8")
            if hash_bytes(old.encode("utf-8")) != before["inventory"][name]:
                raise Blocked("RC2 source before patch diverged")
            proposed = propose_rc2_text(name, old)
            contents = proposed.encode("utf-8")
            with path.open("wb") as writer:
                writer.write(contents)
                writer.flush()
                os.fsync(writer.fileno())
            target_sha = hash_file(path, max_bytes=MAX_SOURCE)
            diff = "".join(difflib.unified_diff(
                old.splitlines(keepends=True), proposed.splitlines(keepends=True),
                fromfile="a/" + name, tofile="b/" + name, n=3))
            if not diff.startswith("--- a/" + name + "\n") or "@@" not in diff:
                raise Blocked("RC2 patch format invalid")
            patch_file = patches / (name.replace("/", "__") + ".patch")
            with patch_file.open("x", encoding="utf-8", newline="\n") as writer:
                writer.write(diff)
            new_map[name] = target_sha
            patch_evidence[name] = {"beforeSha256": before["inventory"][name],
                                    "afterSha256": target_sha,
                                    "patch": patch_file.name,
                                    "patchSha256": hash_file(patch_file, max_bytes=MAX_SOURCE)}
        changes = {key for key in new_map if new_map[key] != before["inventory"][key]}
        if changes != RC2_TARGETS:
            raise Blocked("Only three approved RC2 source files may differ")
        if (len(new_map) != COUNT or new_map["package.json"] != before["inventory"]["package.json"]
                or new_map["package-lock.json"] != before["inventory"]["package-lock.json"]):
            raise Blocked("RC2 package/lock or 131-file membership drift")
        check_source_tree(copy, new_map)
        if verify_stage()["sha256"] != STAGE_SOURCE_SHA:
            raise Blocked("Original detached source stage changed during RC2 copy")
        checked_hash(REJECTED_V104_BUILD / "binary" / "Taraz.exe", REJECTED_V104_EXE_SHA)
        checked_hash(REJECTED_V104_BUILD /
                     "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip",
                     REJECTED_V104_ZIP_SHA, cap=MAX_ARCHIVE)
        inventory_path = run / "patched-source-sha256.json"
        with inventory_path.open("x", encoding="utf-8", newline="\n") as writer:
            writer.write(json.dumps(new_map, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        patch_index = run / "rc2-patch-evidence.json"
        with patch_index.open("x", encoding="utf-8", newline="\n") as writer:
            writer.write(json.dumps(patch_evidence, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        summary.update({"status": "V104_RC2_SOURCE_ONLY_DYNAMIC_QA_PENDING",
                        "sourceCount": COUNT, "changedFiles": sorted(changes),
                        "changedFileCount": len(changes),
                        "patchedSourceSha256": fingerprint(new_map),
                        "patchedInventoryFileSha256": hash_file(inventory_path, max_bytes=MAX_JSON),
                        "patchEvidenceSha256": hash_file(patch_index, max_bytes=MAX_JSON),
                        "noExeBuilt": True, "originalStageRehashedAndUnchanged": True,
                        "originalCandidateRehashedAndUnchanged": True,
                        "stagedPackageVersionUntouched": "1.0.0"})
    except Exception as exc:
        summary["error"] = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
        with output_report.open("x", encoding="utf-8", newline="\n") as writer:
            writer.write(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        raise
    with output_report.open("x", encoding="utf-8", newline="\n") as writer:
        writer.write(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return output_report


def _synthetic_layout(tmp: Path, build: Path) -> dict:
    """Copy only pinned EXEs and scripts; new blank synthetic accounting profile."""
    real_root = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz"
    original = real_root / "versions" / "1.0.2" / "Taraz.exe"
    checked_hash(original, V102_SHA)
    product = tmp / "local" / "Programs" / "Taraz"
    old = product / "versions" / "1.0.2" / "Taraz.exe"
    old.parent.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(original, old)
    checked_hash(old, V102_SHA)
    launcher = product / "Run-Taraz.cmd"
    shutil.copyfile(real_root / "Run-Taraz.cmd", launcher)
    if "versions\\%TARAZ_VERSION%\\Taraz.exe" not in launcher.read_text(
            encoding="utf-8", errors="replace"):
        raise Blocked("Copied launcher lost original v102 compatibility")
    pointer = product / "current-version.txt"
    pointer.write_bytes(b"1.0.2\r\n")
    roaming = tmp / "roaming" / "Taraz"
    roaming.mkdir(parents=True)
    sentinel = roaming / "synthetic-only-data-sentinel.txt"
    sentinel.write_bytes(b"INVENTED_QA_SENTINEL_NO_REAL_ACCOUNTING_HISTORY")
    offline = tmp / "offline"
    shutil.copytree(build / "offline-update", offline, symlinks=False)
    if {x.name for x in offline.iterdir()} != ZIP_NAMES:
        raise Blocked("Synthetic copied offline source differs from 7-pack")
    env = dict(os.environ, LOCALAPPDATA=str(tmp / "local"),
               APPDATA=str(tmp / "roaming"), USERPROFILE=str(tmp),
               TEMP=str(tmp / "tmp"), TMP=str(tmp / "tmp"),
               PYTHONDONTWRITEBYTECODE="1")
    (tmp / "tmp").mkdir()
    return {"tmp": tmp, "product": product, "pointer": pointer, "old": old,
            "launcher": launcher, "sentinel": sentinel,
            "offline": offline, "env": env}


def _fixture_sha(folder: Path) -> dict[str, str]:
    observed = {}
    if not folder.exists():
        return observed
    for base, dirs, names in os.walk(folder, followlinks=False):
        for name in dirs:
            regular(Path(base) / name, directory=True)
        for name in names:
            file = Path(base) / name
            observed[file.relative_to(folder).as_posix()] = hash_file(file)
    return observed


def _invoke_script(fixture: dict, *, activate: bool = False, apply: bool = False,
                   no_taraz: str = "clear") -> subprocess.CompletedProcess:
    if os.name != "nt" or shutil.which("powershell.exe") is None:
        raise Blocked("Windows PowerShell 5.1 required for fixture test")
    if no_taraz not in ("clear", "running", "unavailable"):
        raise Blocked("Invalid test-only process fixture")
    # Test-only CIM wrapper ensures unrelated concurrent private GUI QA cannot
    # perturb a fixture. The immutable packaged operator scripts are unedited.
    fake_cim = {
        "clear": "function Get-CimInstance { @() }\n",
        "running": ("function Get-CimInstance { "
                    "@([pscustomobject]@{Name='Taraz.exe'}) }\n"),
        "unavailable": "function Get-CimInstance { throw 'QA synthetic CIM failure' }\n",
    }[no_taraz]
    name = ("Activate" if activate else "Install") + "-Taraz-V104.ps1"
    actual = fixture["offline"] / name
    backup = str(BACKUP).replace("'", "''")
    script = str(actual).replace("'", "''")
    wrapper = fixture["tmp"] / ("invoke-" + ("activate" if activate else "install")
                                 + "-" + no_taraz + ("-apply" if apply else "-check")
                                 + ".ps1")
    body = (fake_cim + "& '" + script + "' "
            + ("-Apply " if apply else "")
            + "-BackupRoot '" + backup + "' "
            + "-BackupManifestSha256 '" + BACKUP_MANIFEST_SHA + "' "
            + "-BackupReportSha256 '" + BACKUP_REPORT_SHA + "'\n")
    with wrapper.open("x", encoding="utf-8-sig") as stream:
        stream.write(body)
    return subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
        env=fixture["env"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", timeout=180, check=False)


def _require_script_success(result: subprocess.CompletedProcess, message: str) -> None:
    if result.returncode != 0 or message not in result.stdout:
        raise Blocked("Disposable PowerShell expected state transition absent: "
                      + message + " / exit=" + str(result.returncode)
                      + " / diagnostic=" + result.stderr[-400:])


def _require_script_block(result: subprocess.CompletedProcess, label: str) -> None:
    if (result.returncode == 0 or
            "TARAZ V104 SECURE UPDATE BLOCKED" not in (result.stdout + result.stderr)):
        raise Blocked("Disposable negative script gate did not fail closed: " + label)


def exercise_disposable_scripts(build: Path, pinned: dict) -> dict:
    """No native EXE startup: use only an isolated Windows profile and original backup read-only."""
    if os.name != "nt":
        raise Blocked("Windows required for native PowerShell fixture")
    before_real = installed_baseline()
    before_backup = backup_readback()
    checked_hash(build / "offline-update" / "Taraz.exe", pinned["exeSha256"])
    output = {"disposableFixtureOnly": True, "productionFilesModified": False,
              "financialTransactionsPosted": False, "nativeExeLaunched": False}
    with tempfile.TemporaryDirectory(prefix="qa-v104-install-", dir=str(OUTPUT)) as base:
        temp = Path(base)
        positive = _synthetic_layout(temp / "positive", build)
        before_profile = _fixture_sha(positive["product"]) | _fixture_sha(positive["sentinel"].parent)
        _require_script_success(
            _invoke_script(positive), "READY_FOR_CREATE_ONLY_1.0.4_INSTALL")
        if (_fixture_sha(positive["product"]) | _fixture_sha(positive["sentinel"].parent)
                != before_profile):
            raise Blocked("Preflight wrote to a fixture")
        _require_script_success(
            _invoke_script(positive, apply=True),
            "INSTALLED_SIDE_BY_SIDE_1.0.4_POINTER_REMAINS_1.0.2")
        new = positive["product"] / "versions" / "1.0.4" / "Taraz.exe"
        checked_hash(new, pinned["exeSha256"])
        checked_hash(positive["old"], V102_SHA)
        if positive["pointer"].read_text(encoding="utf-8-sig").strip() != "1.0.2":
            raise Blocked("Disposable side-by-side install switched pointer early")
        _require_script_success(
            _invoke_script(positive, activate=True), "READY_TO_ACTIVATE_1.0.4_OLD_VERSION_RETAINED")
        _require_script_success(
            _invoke_script(positive, activate=True, apply=True),
            "ACTIVATED_1.0.4_VERSION_1.0.2_RETAINED")
        if (positive["pointer"].read_text(encoding="utf-8-sig").strip() != "1.0.4"
                or (positive["product"] / "current-version-pre-1.0.4.txt")
                .read_text(encoding="utf-8-sig").strip() != "1.0.2"
                or (positive["product"] / "current-version-1.0.4-pending.txt").exists()
                or hash_file(positive["launcher"]) !=
                    hash_file(positive["product"] / "Run-Taraz-pre-1.0.4.cmd")):
            raise Blocked("Disposable activation pointer or launcher backup failed")
        checked_hash(new, pinned["exeSha256"])
        checked_hash(positive["old"], V102_SHA)
        if positive["sentinel"].read_bytes() != b"INVENTED_QA_SENTINEL_NO_REAL_ACCOUNTING_HISTORY":
            raise Blocked("Synthetic finance sentinel changed")
        output["preflightInstallActivation"] = "PASSED_REAL_PINNED_EXE_IN_DISPOSABLE_PROFILE"
        output["bothBinariesRetained"] = True
        output["pointerBackupNamedV104"] = True
        output["launcherBackupNamedV104"] = True
        negative = _synthetic_layout(temp / "negative", build)
        anchor = negative["tmp"] / "synthetic-hardlink-pointer.txt"
        os.link(negative["pointer"], anchor)
        _require_script_block(_invoke_script(negative), "hardlinked pointer")
        if (negative["product"] / "versions" / "1.0.4").exists():
            raise Blocked("Unsafe hardlink created disposable v104 install")
        anchor.unlink()
        _require_script_block(_invoke_script(negative, no_taraz="running"), "running Taraz")
        _require_script_block(_invoke_script(negative, no_taraz="unavailable"), "CIM unavailable")
        output["hardlinkAndProcessNegativeGates"] = True
        # Junction in an executable ancestor: always make an independent
        # disposable directory. If Windows cannot create it, DO NOT claim pass.
        junction = _synthetic_layout(temp / "junction", build)
        version_dir = junction["product"] / "versions" / "1.0.2"
        backing = junction["product"] / "versions" / "synthetic-real-v102"
        version_dir.rename(backing)
        command = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-Command", "New-Item -ItemType Junction -Path '" +
             str(version_dir).replace("'", "''") + "' -Target '" +
             str(backing).replace("'", "''") + "' -ErrorAction Stop | Out-Null"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False)
        if command.returncode != 0 or not (version_dir.is_junction() or version_dir.is_symlink()):
            raise Blocked("Junction fixture could not be created; no safety signoff")
        _require_script_block(_invoke_script(junction), "ancestor junction")
        if (junction["product"] / "versions" / "1.0.4").exists():
            raise Blocked("Unsafe ancestor junction created disposable v104 install")
        output["ancestorJunctionNegativeGate"] = True
    if installed_baseline() != before_real or backup_readback() != before_backup:
        raise Blocked("Production v102 or original 181 backup bytes changed during fixture tests")
    output["realV102AndBackupBeforeAfterUnchanged"] = True
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true",
                        help="Independently rehash stage+backup+installed baseline; no build required")
    parser.add_argument("--candidate", type=Path, help="Specific completed worker26 build-* directory")
    parser.add_argument("--discover", action="store_true",
                        help="Require exactly one completed v104 build-* candidate")
    parser.add_argument("--disposable-test", action="store_true",
                        help="Only with independently pinned worker26 prior test report")
    parser.add_argument("--worker26-report", type=Path)
    parser.add_argument("--worker26-report-sha256", default="")
    parser.add_argument("--rc2-stage", action="store_true",
                        help="Create-only copy of 131 source inputs with 3 narrow RC2 UI patches")
    args = parser.parse_args()
    try:
        if args.rc2_stage:
            if args.candidate or args.discover or args.disposable_test:
                raise Blocked("RC2 source stage cannot simultaneously inspect/install candidate")
            result = build_rc2_source_stage()
            summary = load_json(result)
            print(json.dumps({"status": summary["status"], "sourceStage": str(result.parent),
                              "patchedSourceSha256": summary["patchedSourceSha256"],
                              "modifiedSources": summary["changedFileCount"],
                              "compiledExeBuilt": False}, ensure_ascii=False, indent=2))
            return 0
        source = verify_stage()
        vite = verify_vite(source)
        baseline = installed_baseline()
        backup = backup_readback()
        status = {"status": "V104_NO_GO_ARTIFACT_NOT_YET_VERIFIED",
                  "stage": source["sha256"], "viteJsSha256": vite["sha256"],
                  "installedBaseline": baseline, "coldBackup": backup,
                  "financeSignoff": False, "releaseApproved": False}
        if args.preflight and not args.candidate and not args.discover:
            status["status"] = "READ_ONLY_INPUT_PREFLIGHT_PASS_NO_BUILD_GO"
        else:
            selected = args.candidate if args.candidate else discover_build()
            candidate = inspect_candidate(selected, source, vite)
            status.update({"candidate": candidate, "status":
                           "STATIC_V104_ARTIFACTS_PASS_BUT_PRODUCTION_NO_GO"})
            if args.disposable_test:
                status["worker26PriorTests"] = independent_worker26_witness(
                    args.worker26_report, args.worker26_report_sha256, selected)
                status["disposableWindows"] = exercise_disposable_scripts(selected, candidate)
                status["status"] = "STATIC_AND_DISPOSABLE_V104_ACCEPTANCE_PASS_PRODUCTION_NO_GO"
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0
    except (Blocked, OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        print("V104 INDEPENDENT NO_GO: " + type(exc).__name__ + ": " + str(exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
