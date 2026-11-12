"""Independent, fail-closed Taraz v1.0.3 artifact/backup acceptance.

Reads existing candidate files and installed v1.0.2. Optional disposable
PowerShell side-by-side installation/activation test is confined to a fresh
D:/CoS-Test temporary directory and never starts the Taraz executable.
Always returns NO_GO; operator, GUI and real finance acceptance are separate.
"""
from __future__ import annotations

import argparse
import ctypes
import dis
import hashlib
import importlib.util
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
import time
import types
import uuid
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
PARENT = SOURCE.parents[1]
CANDIDATES = PARENT / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.3-p1"
BACKUP = PARENT / "MTR-REAL-UPGRADE-BACKUPS-20261110" / "taraz-v103-cold-20261111"
FROZEN_SHA = "a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279"
INSTALLED_V102_SHA = "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52"
BACKUP_MANIFEST_SHA = "8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d"
BACKUP_REPORT_SHA = "68bb6e26b9a9a10818e6752a7cc1475a3861c5f380f2021eb5c112a74cd7d2c9"
ROLLBACK_ROOT = CANDIDATES / "rollback-gate-dad44a3c6367"
ROLLBACK_SCRIPT_SHA = "34b15cfea1e3407a73888ac17fcfc353158f6f329d940d0f58159eea7230f334"
ROLLBACK_MANIFEST_SHA = "030d6402cd3428fb0902767654e7d3513cb7327843b1f93421726ea28565372b"
REVIEWED_INSTALL_SHA = "fd5cb5ddc024370cce21388c8f906bb6d46e849b628351fd65cd18cadefbb08a"
REVIEWED_ACTIVATE_SHA = "623f89e19d1e640767cf4bec6c1a2b9304a7513f4a2658faf3b67df7a3b825d5"
MAX_JSON = 5 * 1024 * 1024
MAX_BACKUP_BYTES = 300 * 1024 * 1024
MODULES = {
    "taraz_madar_data_reader": {"local_madar_available", "read_local_madar_state",
                                "read_authorized_madar_state", "_network_config", "_validate_paging"},
    "standalone_accounting_template_store": {"save", "set_default", "delete", "duplicate"},
    "taraz_integration": set(),
    "personal_parsian_bridge": set(),
    "standalone_accounting_auto_backup": set(),
}
NATIVE_METHODS = {"tarazMadarDataOverview", "tarazMadarDataRead",
                  "tarazIntegrationList", "tarazIntegrationReview", "tarazIntegrationRecover"}
EXPECTED_BUNDLE_FILES = {
    "Taraz.exe", "Install-Taraz-V103.ps1", "Activate-Taraz-V103.ps1",
    "source-sha256.json", "update-manifest.json", "package.json", "package-lock.json",
}


class Rejected(RuntimeError):
    pass


def _regular(path: Path, folder: bool = False) -> Path:
    path = Path(path).absolute()
    for component in (path, *path.parents):
        if component.is_symlink() or (component.exists() and bool(
                getattr(component.lstat(), "st_file_attributes", 0) & 0x400)):
            raise Rejected("linked/reparse path: " + str(component))
    if folder:
        if not path.is_dir():
            raise Rejected("required directory missing: " + str(path))
    elif not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise Rejected("required regular file missing: " + str(path))
    return path


def _digest(path: Path) -> str:
    _regular(path)
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _json(path: Path) -> dict:
    _regular(path)
    if path.stat().st_size > MAX_JSON:
        raise Rejected("JSON file too large: " + str(path))
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, ValueError) as error:
        raise Rejected("invalid JSON: " + str(path)) from error
    if not isinstance(value, dict):
        raise Rejected("JSON root must be object")
    return value


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch("[0-9a-f]{64}", value))


def _same_hash(path: Path, expected: object, description: str) -> str:
    if not _sha(expected):
        raise Rejected("missing pinned SHA: " + description)
    actual = _digest(path)
    if actual != expected:
        raise Rejected("SHA mismatch: " + description)
    return actual


def _safe_rel(value: object) -> Path:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value or ":" in value:
        raise Rejected("unsafe relative name")
    parts = PurePosixPath(value).parts
    if any(segment in ("", ".", "..") for segment in parts):
        raise Rejected("unsafe traversal")
    return Path(*parts)


def _fp(mapping: dict) -> str:
    if not all(isinstance(name, str) and _sha(value) for name, value in mapping.items()):
        raise Rejected("invalid source inventory entry")
    return hashlib.sha256(json.dumps(mapping, sort_keys=True).encode("utf-8")).hexdigest()


def discover(path: Path = CANDIDATES) -> Path:
    _regular(path, folder=True)
    completed = sorted(folder for folder in path.glob("build-*")
                       if folder.is_dir() and (folder / "build-report.json").is_file())
    if len(completed) != 1:
        raise Rejected("expected exactly one completed build, found " + str(len(completed)) +
                       "; select --build explicitly")
    return _regular(completed[0], folder=True)


def installed_baseline(root: Path) -> dict:
    _regular(root, folder=True)
    pointer = root / "current-version.txt"
    launcher = root / "Run-Taraz.cmd"
    version = _regular(pointer).read_text(encoding="utf-8-sig").strip()
    if version != "1.0.2":
        raise Rejected("installed version pointer is not 1.0.2")
    exe = root / "versions" / "1.0.2" / "Taraz.exe"
    _same_hash(exe, INSTALLED_V102_SHA, "installed 1.0.2 binary")
    if "versions\\%TARAZ_VERSION%\\Taraz.exe" not in _regular(launcher).read_text(
            encoding="utf-8", errors="replace"):
        raise Rejected("installed launcher contract changed")
    if (root / "versions" / "1.0.3").exists():
        raise Rejected("v1.0.3 already installed; never overwrite")
    return {"version": version, "exeSha256": _digest(exe),
            "pointerSha256": _digest(pointer), "launcherSha256": _digest(launcher),
            "futureFolderAbsent": True, "exeBytes": exe.stat().st_size}


def pe_fixed_version(exe: Path) -> str:
    _regular(exe)
    if os.name != "nt":
        raise Rejected("Windows PE resource inspection requires Windows")
    lib = ctypes.windll.version
    lib.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    lib.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
    length = lib.GetFileVersionInfoSizeW(str(exe), ctypes.byref(ctypes.c_ulong()))
    if not (64 <= length <= 1_000_000):
        raise Rejected("missing or oversized native PE version resource")
    data = ctypes.create_string_buffer(length)
    lib.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    lib.GetFileVersionInfoW.restype = ctypes.c_int
    if not lib.GetFileVersionInfoW(str(exe), 0, length, data):
        raise Rejected("native PE version resource unreadable")
    ptr, size = ctypes.c_void_p(), ctypes.c_uint()
    lib.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    lib.VerQueryValueW.restype = ctypes.c_int
    if not lib.VerQueryValueW(data, "\\", ctypes.byref(ptr), ctypes.byref(size)) or size.value < 16:
        raise Rejected("PE VS_FIXEDFILEINFO unavailable")
    words = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32))
    if words[0] != 0xFEEF04BD:
        raise Rejected("PE fixed-file-info signature mismatch")
    return f"{words[2] >> 16}.{words[2] & 65535}.{words[3] >> 16}.{words[3] & 65535}"


def _recursive_methods(code: types.CodeType) -> set[str]:
    found = set()
    for child in code.co_consts:
        if isinstance(child, types.CodeType):
            found.add(child.co_name)
            found.update(_recursive_methods(child))
    return found


def _find_named_code(code: types.CodeType, name: str) -> types.CodeType | None:
    if code.co_name == name:
        return code
    for child in code.co_consts:
        if isinstance(child, types.CodeType):
            found = _find_named_code(child, name)
            if found is not None:
                return found
    return None


def _assigned_constant(code: types.CodeType, variable: str) -> object:
    instructions = list(dis.get_instructions(code))
    for i in range(1, len(instructions)):
        if (instructions[i].opname in ("STORE_NAME", "STORE_GLOBAL") and
                instructions[i].argval == variable and
                instructions[i - 1].opname == "LOAD_CONST"):
            return instructions[i - 1].argval
    raise Rejected("static assignment absent: " + variable)


def _contains_literal(value: object, needle: object) -> bool:
    if isinstance(value, tuple):
        return any(_contains_literal(item, needle) for item in value)
    return value == needle


def inspect_pyz(exe: Path, ui_dir: Path, expected_ui: dict) -> dict:
    """Read frozen marshal bytecode as data; never execute/import it."""
    from PyInstaller.archive.readers import CArchiveReader

    _regular(exe)
    outer = CArchiveReader(str(exe))
    embedded = outer.open_embedded_archive("PYZ.pyz")
    module = embedded.extract("taraz_release_version")
    if not isinstance(module, types.CodeType):
        raise Rejected("frozen release version module absent")
    if ("1.0.3" not in module.co_consts or
            not {"APP_VERSION", "QA_ONLY", "BUILD_CHANNEL"} <= set(module.co_names)):
        raise Rejected("frozen release version module cannot prove 1.0.3")
    # Static bytecode data only: inspect named assignments; do not execute.
    if (_assigned_constant(module, "QA_ONLY") is not False or
            _assigned_constant(module, "APP_VERSION") != "1.0.3"):
        raise Rejected("frozen module is QA-only or has wrong release version assignment")
    entry_blob = outer.extract("taraz_desktop")
    if not isinstance(entry_blob, bytes):
        raise Rejected("frozen taraz_desktop entrypoint absent")
    try:
        entry = marshal.loads(entry_blob)
    except (ValueError, TypeError, EOFError) as error:
        raise Rejected("frozen entrypoint marshal invalid") from error
    if not isinstance(entry, types.CodeType):
        raise Rejected("frozen entrypoint is not code")
    native = _recursive_methods(entry)
    if not NATIVE_METHODS <= native or "_taraz_qa_launch_gate" in native:
        raise Rejected("required native methods missing or QA gate present")
    for name, required in MODULES.items():
        code = embedded.extract(name)
        if not isinstance(code, types.CodeType) or not required <= _recursive_methods(code):
            raise Rejected("frozen PYZ module missing required methods: " + name)
        if name == "taraz_integration":
            listing = _find_named_code(code, "list_requests")
            if (listing is None or not _contains_literal(listing.co_consts, "pendingTruncated")
                    or 201 not in listing.co_consts or 100 not in listing.co_consts):
                raise Rejected("frozen taraz_integration.list_requests lacks bounded pendingTruncated signal")
    bridge = embedded.extract("standalone_accounting_desktop")
    if not isinstance(bridge, types.CodeType):
        raise Rejected("frozen WebView2 bridge missing")
    def strings(code: types.CodeType) -> list[str]:
        found = [part for part in code.co_consts if isinstance(part, str)]
        for inner in code.co_consts:
            if isinstance(inner, types.CodeType):
                found.extend(strings(inner))
        return found
    forwarders = [part for part in strings(bridge) if "window.madar = Object.fromEntries(" in part]
    if len(forwarders) != 1 or not all("'" + name + "'" in forwarders[0] for name in NATIVE_METHODS):
        raise Rejected("WebView2 bridge forwarder incomplete")
    packed = {name.replace("\\", "/"): name for name in outer.toc}
    observed: dict[str, str] = {}
    for name, expected in sorted(expected_ui.items()):
        relative = _safe_rel(name)
        file = ui_dir / relative
        actual = _same_hash(file, expected, "compiled UI asset " + name)
        key = packed.get("dist/" + name)
        if not key:
            raise Rejected("UI asset not embedded: " + name)
        blob = outer.extract(key)
        if not isinstance(blob, bytes) or hashlib.sha256(blob).hexdigest() != actual:
            raise Rejected("UI asset bytes differ between dist and frozen EXE: " + name)
        observed[name] = actual
    physical = {item.relative_to(ui_dir).as_posix()
                for item in ui_dir.rglob("*") if item.is_file()}
    if physical != set(expected_ui) or not any(name.endswith(".js") for name in observed):
        raise Rejected("compiled UI asset inventory incomplete")
    js_parts = [(ui_dir / name).read_text(encoding="utf-8") for name in observed if name.endswith(".js")]
    rendered_js = "\n".join(js_parts)
    for feature, token in {
        "pendingFlag": "pendingTruncated",
        "pendingTruncatedWarning": "فهرست ارجاع‌های در انتظار کامل نیست",
        "madarGuideKey": "madar",
        "madarGuideCaution": "ارجاع‌های مدار فقط دادهٔ پیشنهادی‌اند",
        "invoiceDesignGuideKey": "invoiceDesign",
        "invoiceDesignGuideCaution": "ذخیرهٔ قالب چاپ سند مالی یا فاکتور جدید نمی‌سازد",
    }.items():
        if token not in rendered_js:
            raise Rejected("frozen compiled UI missing required P0 feature: " + feature)
    return {"status": "STATIC_PYZ_AND_ASSETS_VERIFIED",
            "pyzVersion": "1.0.3", "nativeMethodCount": len(NATIVE_METHODS),
            "requiredPyzModules": sorted(MODULES), "uiAssetsMatched": len(observed),
            "bridgeForwardersPresent": True,
            "pendingTruncatedFrozenPyzAndUi": True,
            "contextualHelpMadarAndInvoiceDesignInUi": True,
            "entryCodeExecuted": False}


def verify_candidate(build: Path, *, pe_reader=pe_fixed_version,
                     pyz_reader=inspect_pyz) -> dict:
    build = _regular(build, folder=True)
    report = _json(build / "build-report.json")
    if (report.get("status") != "PRODUCTION_V103_P1_CANDIDATE_BUILT_NOT_INSTALLED"
            or report.get("version") != "1.0.3" or report.get("sourceFreezeSha256") != FROZEN_SHA
            or Path(report.get("output", "")) != build):
        raise Rejected("build report version/status/source freeze differs")
    offline = build / "offline-update"
    manifest = _json(offline / "update-manifest.json")
    frozen = _json(offline / "source-sha256.json")
    if _fp(frozen) != FROZEN_SHA or len(frozen) != report.get("sourceFileCount"):
        raise Rejected("frozen runtime source manifest diverges from approved fingerprint")
    if not (manifest.get("sourceSnapshotSha256") == FROZEN_SHA and
            manifest.get("sourceFilesCount") == len(frozen) and
            manifest.get("targetVersion") == "1.0.3" and
            manifest.get("installedBaselineVersion") == "1.0.2" and
            manifest.get("installedBaselineSha256") == INSTALLED_V102_SHA and
            manifest.get("application") == "Taraz" and
            manifest.get("qaOnly") is False and manifest.get("productionCandidate") is True):
        raise Rejected("candidate manifest claims inconsistent")
    _same_hash(offline / "source-sha256.json", manifest.get("sourceFileManifestSha256"),
               "source manifest")
    binary = build / "binary" / "Taraz.exe"
    expected_binary_sha = report.get("exeSha256")
    if not (report.get("exe") == str(binary) and _sha(expected_binary_sha)
            and expected_binary_sha == manifest.get("exeSha256")):
        raise Rejected("report/manifest executable path and SHA mismatch")
    _same_hash(binary, expected_binary_sha, "built candidate EXE")
    _same_hash(offline / "Taraz.exe", expected_binary_sha, "offline payload EXE")
    if not (binary.stat().st_size == manifest.get("exeBytes")
            and report.get("compiled", {}).get("peVersion") == "1.0.3.0"):
        raise Rejected("candidate EXE length or compiled version claims inconsistent")
    for report_key, relative in (("manifest", "update-manifest.json"),
                                 ("installScript", "Install-Taraz-V103.ps1"),
                                 ("activationScript", "Activate-Taraz-V103.ps1")):
        file = offline / relative
        if report.get(report_key) != str(file):
            raise Rejected("untrusted report path: " + report_key)
        actual = _same_hash(file, report.get(report_key + "Sha256"), report_key)
        if report_key in ("installScript", "activationScript"):
            _same_hash(file, manifest.get(report_key + "Sha256"), report_key + " manifest pin")
    for name, key in (("package.json", "stagedPackageSha256"),
                      ("package-lock.json", "stagedLockSha256")):
        _same_hash(offline / name, manifest.get(key), "staged package pin: " + name)
        _same_hash(build / "source" / name, manifest.get(key), "staged source pin: " + name)
    package = _json(offline / "package.json")
    lock = _json(offline / "package-lock.json")
    if [package.get("version"), lock.get("version"), lock.get("packages", {}).get("", {}).get("version")] != ["1.0.3"] * 3:
        raise Rejected("staged package/lock version mismatch")
    version_module = build / "source" / "taraz_release_version.py"
    _same_hash(version_module, manifest.get("stagedVersionSourceSha256", {}).get("versionModuleSha256"),
               "staged release module")
    _same_hash(build / "source" / "taraz_desktop.py",
               manifest.get("stagedVersionSourceSha256", {}).get("nativeEntrySha256"),
               "staged native entrypoint")
    frozen_match = []
    for name, source_sha in frozen.items():
        source_file = build / "source" / _safe_rel(name)
        if name in ("package.json", "package-lock.json", "taraz_desktop.py"):
            continue
        _same_hash(source_file, source_sha, "frozen source: " + name)
        frozen_match.append(name)
    version = pe_reader(binary)
    if version != "1.0.3.0" or manifest.get("peVersion") != version:
        raise Rejected("actual PE resource is not 1.0.3.0")
    claimed_assets = report.get("compiled", {}).get("uiAssetsSha256")
    if not isinstance(claimed_assets, dict) or claimed_assets != manifest.get("compiledEvidence", {}).get("uiAssetsSha256"):
        raise Rejected("compiled UI inventory claims conflict")
    pyz = pyz_reader(binary, build / "web" / "dist", claimed_assets)
    archive = build / "Taraz-v1.0.3-P1-OFFLINE-SIDE-BY-SIDE-UPDATE.zip"
    if report.get("zip") != str(archive):
        raise Rejected("build ZIP report path changed")
    archive_sha = _same_hash(archive, report.get("zipSha256"), "offline ZIP")
    packaged = {path.name: path for path in offline.iterdir() if path.is_file()}
    if set(packaged) != EXPECTED_BUNDLE_FILES:
        raise Rejected("unpacked offline file list has missing/unexpected entries")
    with zipfile.ZipFile(archive, "r") as zipfile_in:
        entries = zipfile_in.infolist()
        if len(entries) != len(EXPECTED_BUNDLE_FILES) or {entry.filename for entry in entries} != EXPECTED_BUNDLE_FILES:
            raise Rejected("ZIP file inventory missing/duplicate/unexpected")
        for entry in entries:
            _safe_rel(entry.filename)
            if entry.is_dir() or entry.file_size > 75 * 1024 * 1024:
                raise Rejected("invalid ZIP entry")
            content_sha = hashlib.sha256()
            with zipfile_in.open(entry) as reader:
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    content_sha.update(chunk)
            if content_sha.hexdigest() != _digest(packaged[entry.filename]):
                raise Rejected("ZIP payload differs: " + entry.filename)
    return {
        "status": "ARTIFACT_PINS_PE_PYZ_ZIP_VERIFIED", "candidateDir": str(build),
        "exeSha256": expected_binary_sha, "exeBytes": binary.stat().st_size,
        "peVersion": version, "sourceFreezeSha256": _fp(frozen),
        "frozenInputCount": len(frozen), "snapshotUnstagedInputsRehashed": len(frozen_match),
        "archiveSha256": archive_sha, "zipMembersRehashed": len(EXPECTED_BUNDLE_FILES),
        "pyz": pyz, "installScriptSha256": _digest(offline / "Install-Taraz-V103.ps1"),
        "activationScriptSha256": _digest(offline / "Activate-Taraz-V103.ps1"),
        "buildReportSha256": _digest(build / "build-report.json"),
        "candidateReportedUnsigned": manifest.get("unsigned"),
        "installedGuiTested": False, "financePostingProven": False,
        "manifest": manifest,
    }


def verify_backup(backup: Path = BACKUP) -> dict:
    backup = _regular(backup, folder=True)
    mf = backup / "snapshot-manifest.json"
    rf = backup / "backup-acceptance-report.json"
    _same_hash(mf, BACKUP_MANIFEST_SHA, "v103 fresh backup manifest")
    _same_hash(rf, BACKUP_REPORT_SHA, "v103 fresh backup report")
    manifest, report = _json(mf), _json(rf)
    witness = report.get("backup", {})
    files = manifest.get("files")
    if (not isinstance(files, dict) or len(files) != 181 or
            manifest.get("fileCount") != len(files) or
            manifest.get("schemaVersion") != 1 or
            manifest.get("verifiedNoOverwrite") is not True or
            manifest.get("allFilesIncluded") is not True or
            not isinstance(manifest.get("sqliteChecks"), dict) or
            len(manifest["sqliteChecks"]) != 67 or
            report.get("status") != "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING" or
            report.get("installedBefore") != "1.0.2" or
            report.get("installedAfter") != "1.0.2" or
            report.get("installedExeSha256") != INSTALLED_V102_SHA or
            witness.get("fileCount") != len(files) or
            witness.get("sqliteValidatedCount") != 67 or
            witness.get("backupRoot") != str(backup) or
            witness.get("manifestSha256") != BACKUP_MANIFEST_SHA or
            witness.get("independentReadback") is not True):
        raise Rejected("fresh backup manifest and acceptance evidence inconsistent")
    expected: set[str] = set()
    size_total = 0
    for name, details in sorted(files.items()):
        rel = _safe_rel(name)
        if rel.parts[0] not in ("roaming", "local", "bridge"):
            raise Rejected("cold backup root not allowed")
        expected.add(rel.as_posix())
        file = backup / "files" / rel
        if not isinstance(details, dict) or not isinstance(details.get("bytes"), int):
            raise Rejected("cold backup file entry invalid")
        if _regular(file).stat().st_size != details["bytes"]:
            raise Rejected("cold backup byte count differs")
        _same_hash(file, details.get("sha256"), "cold backup file " + name)
        size_total += details["bytes"]
        if size_total > MAX_BACKUP_BYTES:
            raise Rejected("cold backup exceeds bounded byte budget")
    actual: set[str] = set()
    for folder, subdirs, names in os.walk(backup / "files", followlinks=False):
        for name in subdirs:
            _regular(Path(folder) / name, folder=True)
        for name in names:
            file = _regular(Path(folder) / name)
            actual.add(file.relative_to(backup / "files").as_posix())
    if (actual != expected or size_total != manifest.get("totalBytes") or
            size_total != witness.get("totalBytes")):
        raise Rejected("fresh backup file list/total mismatch")
    return {"status": "FRESH_V102_BACKUP_BYTES_MATCH", "filesRehashed": len(files),
            "bytesRehashed": size_total, "sqliteChecksReportedNotRerun": 67,
            "sourceVersion": report["installedBefore"], "manifestSha256": BACKUP_MANIFEST_SHA,
            "reportSha256": BACKUP_REPORT_SHA}


def disposable_install(build: Path, installed: Path, backup: Path, validated: dict,
                       *, subprocess_runner=subprocess.run) -> dict:
    """Executes pinned PowerShell scripts ONLY with a new disposable LOCALAPPDATA.

    The packaged update has no rollback script; a separate Python pointer
    restoration in the disposable root demonstrates reversibility of pointer
    state, not an operator-approved production rollback.
    """
    if os.name != "nt":
        raise Rejected("disposable script exercise requires Windows")
    offline = build / "offline-update"
    if (validated.get("installScriptSha256") != REVIEWED_INSTALL_SHA
            or validated.get("activationScriptSha256") != REVIEWED_ACTIVATE_SHA):
        raise Rejected("installer script SHA has not been independently reviewed for disposable execution")
    installed_baseline(installed)
    with tempfile.TemporaryDirectory(prefix="taraz-v103-disposable-", dir=str(PARENT)) as temp:
        root = Path(temp)
        isolated_local = root / "local"
        product = isolated_local / "Programs" / "Taraz"
        shutil.copytree(offline, root / "offline")
        target = product / "versions" / "1.0.2"
        target.mkdir(parents=True)
        shutil.copyfile(installed / "versions" / "1.0.2" / "Taraz.exe", target / "Taraz.exe")
        shutil.copyfile(installed / "Run-Taraz.cmd", product / "Run-Taraz.cmd")
        (product / "current-version.txt").write_bytes(b"1.0.2\r\n")
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(isolated_local)
        env["APPDATA"] = str(root / "roaming")
        env["USERPROFILE"] = str(root)
        env["TEMP"] = str(root / "temp")
        env["TMP"] = env["TEMP"]
        (root / "temp").mkdir()
        (root / "roaming").mkdir()
        cmd_prefix = [
            "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File",
        ]
        sha_options = [
            "-BackupRoot", str(backup), "-BackupManifestSha256", BACKUP_MANIFEST_SHA,
            "-BackupReportSha256", BACKUP_REPORT_SHA,
        ]
        calls = []

        def run_file(script_name: str, *options: str, expected: str) -> None:
            command = cmd_prefix + [str(root / "offline" / script_name), *options, *sha_options]
            completed = subprocess_runner(command, cwd=str(root), env=env, timeout=100,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         encoding="utf-8", errors="replace", check=False)
            calls.append({"script": script_name, "phase": list(options),
                          "exitCode": completed.returncode,
                          "expectedMarkerObserved": expected in completed.stdout})
            if completed.returncode != 0 or expected not in completed.stdout:
                raise Rejected("disposable PowerShell " + script_name +
                               " failed: " + completed.stdout[-350:])

        run_file("Install-Taraz-V103.ps1", expected="READY_FOR_CREATE_ONLY_1.0.3_INSTALL")
        run_file("Install-Taraz-V103.ps1", "-Apply",
                 expected="INSTALLED_SIDE_BY_SIDE_1.0.3_POINTER_REMAINS_1.0.2")
        new_exe = product / "versions" / "1.0.3" / "Taraz.exe"
        _same_hash(new_exe, validated["exeSha256"], "disposable new EXE")
        if (product / "current-version.txt").read_text(encoding="utf-8").strip() != "1.0.2":
            raise Rejected("disposable install prematurely switched version pointer")
        run_file("Activate-Taraz-V103.ps1", expected="READY_TO_ACTIVATE_1.0.3_OLD_VERSION_RETAINED")
        run_file("Activate-Taraz-V103.ps1", "-Apply", expected="ACTIVATED_1.0.3_VERSION_1.0.2_RETAINED")
        pointer = product / "current-version.txt"
        original = product / "current-version-pre-1.0.3.txt"
        if pointer.read_text(encoding="utf-8").strip() != "1.0.3" or original.read_text(
                encoding="utf-8").strip() != "1.0.2":
            raise Rejected("disposable activation did not preserve original version pointer")
        if not (product / "versions" / "1.0.2" / "Taraz.exe").is_file():
            raise Rejected("disposable upgrade discarded the old executable")
        # Exercise a manual rollback *only in disposable files*, not through an
        # unprovided production rollback command.
        os.replace(original, pointer)
        if pointer.read_text(encoding="utf-8").strip() != "1.0.2":
            raise Rejected("disposable pointer rollback failed")
        _same_hash(product / "versions" / "1.0.2" / "Taraz.exe", INSTALLED_V102_SHA,
                   "disposable retained old binary")
        return {"status": "DISPOSABLE_INSTALL_ACTIVATE_AND_MANUAL_POINTER_RESTORE_PASSED",
                "powershellStagesPassed": len(calls), "steps": calls,
                "installedExeRehashed": True, "oldExeRehashed": True,
                "realInstallerRollbackScriptTested": False, "temporaryFolderRemovedAfterExit": True}


def private_desktop_gui_smoke(build: Path, backup: Path, validated: dict) -> dict:
    """Launch ONLY the pinned v103 EXE on a fresh private Win32 desktop/job.

    Reuses an existing, read-only Windows desktop/job wrapper. Never switches
    desktop or sends input to an ordinary user desktop. No finance interaction.
    """
    if os.name != "nt":
        raise Rejected("private Windows desktop unavailable")
    binary = _regular(build / "binary" / "Taraz.exe")
    _same_hash(binary, validated.get("exeSha256"), "private desktop v103 EXE")
    bridge_path = PARENT / "ArtiosMamad" / "qa_compiled_gui_v051.py"
    _regular(bridge_path)
    name = "_taraz_private_gui_win32_helper"
    spec = importlib.util.spec_from_file_location(name, bridge_path)
    if spec is None or spec.loader is None:
        raise Rejected("known Windows private-desktop helper cannot be loaded")
    helper = importlib.util.module_from_spec(spec)
    sys.modules[name] = helper
    try:
        spec.loader.exec_module(helper)
    finally:
        sys.modules.pop(name, None)
    # Existing helper is reused for Win32 lifecycle only, no ArtiosCAD code
    # or user desktop interaction; cwd is overwritten in this process alone.
    helper.APP_ROOT = build

    class PrivateTarazAPI(helper.WindowsAPI):
        @staticmethod
        def _env_block(root: Path):
            values = dict(os.environ)
            qa = root / "qa"
            for key in list(values):
                if key.upper().startswith("TARAZ_") or key.upper() in (
                        "PYTHONPATH", "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"):
                    del values[key]
            mapping = {
                "APPDATA": qa / "appdata", "LOCALAPPDATA": qa / "localappdata",
                "USERPROFILE": qa / "user", "HOME": qa / "user",
                "TEMP": qa / "temp", "TMP": qa / "temp",
                "WEBVIEW2_USER_DATA_FOLDER": qa / "webview2",
                "PYINSTALLER_CONFIG_DIR": qa / "pyinstaller",
            }
            for key, target in mapping.items():
                target.mkdir(parents=True, exist_ok=True)
                values[key] = str(target)
            values.update({
                "TARAZ_QA_MODE": "1",
                "TARAZ_QA_DATA_DIR": str(qa / "appdata" / "Taraz"),
                "TARAZ_DATA_DIR": str(qa / "appdata" / "Taraz"),
                "TARAZ_QA_REPORT": str(qa / "taraz-private-gui-report.json"),
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": (
                    "--disable-background-networking --disable-sync "
                    "--disable-component-update --disable-extensions --no-first-run"),
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            import ctypes as ct
            buffer = "".join(f"{key}={value}\0" for key, value in sorted(
                values.items(), key=lambda item: item[0].upper())) + "\0"
            return ct.create_unicode_buffer(buffer)

    def private_exception_dialog_text(api, window) -> list[str]:
        """Read-only child controls of OUR private, job-owned exception HWND."""
        import ctypes as ct
        from ctypes import wintypes as wt
        found: list[str] = []
        callback_type = ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        api.u.EnumChildWindows.argtypes = [wt.HWND, callback_type, wt.LPARAM]
        api.u.EnumChildWindows.restype = wt.BOOL

        def receive(hwnd, _param):
            size = api.u.GetWindowTextLengthW(hwnd)
            if 0 < size < 10000:
                value = ct.create_unicode_buffer(size + 1)
                api.u.GetWindowTextW(hwnd, value, len(value))
                if value.value.strip():
                    found.append(value.value[:6000])
            return True

        callback = callback_type(receive)
        api.u.EnumChildWindows(window.hwnd, callback, 0)
        return found[:12]

    with tempfile.TemporaryDirectory(prefix="taraz-v103-private-gui-", dir=str(PARENT)) as location:
        root = Path(location)
        snapshot = _json(backup / "snapshot-manifest.json").get("files", {})
        if len(snapshot) != 181:
            raise Rejected("unexpected private GUI backup file inventory")
        for rel, details in sorted(snapshot.items()):
            relative = _safe_rel(rel)
            branch, *suffix = relative.parts
            if branch not in ("roaming", "local", "bridge") or not suffix:
                raise Rejected("private GUI snapshot has unsupported path")
            destinations = {
                "roaming": root / "qa" / "appdata" / "Taraz",
                "local": root / "qa" / "localappdata" / "Taraz",
                "bridge": root / "qa" / "localappdata" / "Madar-Taraz-Bridge",
            }
            dest = destinations[branch].joinpath(*suffix)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with _regular(backup / "files" / relative).open("rb") as source, dest.open("xb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
            _same_hash(dest, details.get("sha256"), "private GUI copied backup byte " + rel)

        api = PrivateTarazAPI()
        desktop = job = 0
        process = None
        observed = {
            "status": "NOT_CONFIRMED", "isolatedDesktop": False,
            "ownJobCreated": False, "binaryLaunchedSuspendedThenAssigned": False,
            "backgroundOnly": True, "userDesktopInputSent": False,
            "candidateExeSha256": validated["exeSha256"],
        }
        try:
            desktop_name = "ArtiosMamadQA_Taraz_" + uuid.uuid4().hex[:16]
            desktop = api.desktop_create(desktop_name)
            observed["isolatedDesktop"] = True
            job = api.job_create()
            observed["ownJobCreated"] = True
            process, resumed = api.launch_suspended_in_job(
                job=job, desktop_name=desktop_name, executable=binary,
                synthetic_root=root)
            observed["binaryLaunchedSuspendedThenAssigned"] = bool(resumed)
            own_pid = int(process.dwProcessId)
            own_windows: list[dict] = []
            report_path = root / "qa" / "taraz-private-gui-report.json"
            deadline = time.monotonic() + 32
            while time.monotonic() < deadline:
                pids = api.job_process_ids(job)
                if own_pid not in pids:
                    raise Rejected("new binary not retained in the private job")
                windows = api.private_desktop_windows(desktop, pids)
                own_windows = [w.report() for w in windows if w.title][:12]
                exception_windows = [w for w in windows if w.title == "Unhandled exception in script"
                                     and w.pid in pids]
                if exception_windows:
                    observed["exceptionDialogChildTexts"] = private_exception_dialog_text(
                        api, exception_windows[0])
                    observed["status"] = "PRIVATE_DESKTOP_SCRIPT_EXCEPTION"
                    break
                if own_windows and report_path.is_file():
                    break
                time.sleep(0.30)
            observed["ownedWindowCount"] = len(own_windows)
            observed["ownedWindowTitles"] = [item["title"] for item in own_windows]
            observed["nativeReportPresent"] = report_path.is_file()
            if observed["nativeReportPresent"]:
                native = _json(report_path)
                observed["nativeWebViewLoaded"] = native.get("loaded") is True
                observed["nativeAccountingBridgePresent"] = native.get("accountingBridge") == "function"
                observed["taskBridgeAbsent"] = native.get("taskBridgeExposed") != "function"
            if observed["status"] != "PRIVATE_DESKTOP_SCRIPT_EXCEPTION":
                observed["status"] = ("PRIVATE_DESKTOP_WEBVIEW2_SMOKE_PASSED"
                                      if all((observed.get("ownedWindowCount", 0),
                                              observed.get("nativeWebViewLoaded"),
                                              observed.get("nativeAccountingBridgePresent"),
                                              observed.get("taskBridgeAbsent")))
                                      else "PRIVATE_DESKTOP_STARTED_WEBVIEW_NOT_PROVEN")
        finally:
            # This job was created and populated by our own suspended process.
            # Never enumerate or terminate any other app/process/user desktop.
            if job:
                api.k.TerminateJobObject(job, 0)
                if process is not None:
                    api.k.WaitForSingleObject(process.hProcess, 6000)
                    api.k.CloseHandle(process.hThread)
                    api.k.CloseHandle(process.hProcess)
                api.k.CloseHandle(job)
            if desktop:
                api.desktop_close(desktop)
        return observed


def verify_windows_drive_regex(source: str) -> None:
    """Reject an incomplete .NET escape in a single-quoted PS drive-root regex."""
    if "'^[a-zA-Z]:\\'" in source:
        raise Rejected("rollback PowerShell absolute-path regex has an invalid trailing escape")


def verify_operator_rollback(root: Path = ROLLBACK_ROOT, build: Path | None = None,
                             *, required_script_sha: str = ROLLBACK_SCRIPT_SHA,
                             required_manifest_sha: str = ROLLBACK_MANIFEST_SHA) -> dict:
    """Independently read and pin the separate worker29 operator rollback gate."""
    root = _regular(root, folder=True)
    if build is None:
        build = discover()
    _regular(build, folder=True)
    if root.parent != CANDIDATES or not root.name.startswith("rollback-gate-"):
        raise Rejected("rollback gate must be within pinned candidate workspace")
    script_file = root / "Rollback-Taraz-V103-To-V102.ps1"
    manifest_file = root / "rollback-gate-manifest.json"
    _same_hash(script_file, required_script_sha, "independent rollback script pin")
    _same_hash(manifest_file, required_manifest_sha, "independent rollback manifest pin")
    manifest = _json(manifest_file)
    pins = manifest.get("pinnedArtifacts", {})
    if not isinstance(pins, dict) or not (
            manifest.get("schemaVersion") == 1 and
            manifest.get("application") == "Taraz" and
            manifest.get("tool") == "operator-rollback" and
            manifest.get("fromVersion") == "1.0.3" and
            manifest.get("toVersion") == "1.0.2" and
            manifest.get("scriptName") == script_file.name and
            manifest.get("frozenRun") == str(build) and
            manifest.get("scriptSha256") == required_script_sha and
            manifest.get("requiresApply") is True and
            manifest.get("operatorOnly") is True and
            manifest.get("createdOnly") is True and
            manifest.get("rollbackExecuted") is False and
            manifest.get("installedPointerTouched") is False and
            manifest.get("profilesTouched") is False and
            manifest.get("pointerBackupRequired") == "current-version-pre-1.0.3.txt" and
            manifest.get("rollbackPointerBackup") == "current-version-pre-rollback-1.0.3.txt" and
            pins.get("previousInstalledExeSha256") == INSTALLED_V102_SHA and
            pins.get("candidateExeSha256") == _digest(build / "binary" / "Taraz.exe") and
            pins.get("candidateSourceSha256") == FROZEN_SHA and
            pins.get("candidateManifestSha256") == _digest(
                build / "offline-update" / "update-manifest.json")):
        raise Rejected("independent operator rollback metadata or candidate pins inconsistent")
    source = script_file.read_text(encoding="utf-8-sig")
    # A single trailing backslash in a .NET regex escapes its terminator.
    # Both local absolute-path checks must use TWO literal backslashes in
    # the single-quoted PowerShell regex (one regex-escaped backslash).
    verify_windows_drive_regex(source)
    required_fragments = (
        "param([switch]$Apply)", "if(-not $Apply)", "Set-StrictMode -Version Latest",
        "CheckNoTaraz", "Get-CimInstance Win32_Process",
        "CheckVersion $old 2", "CheckVersion $new 3",
        "CheckWriteRights $root", "CheckWriteRights $pointer",
        "RequireAbsent $rollbackBackup", "RequireAbsent $pending",
        "[IO.File]::Replace($pending,$pointer,$rollbackBackup,$true)",
        "current-version-pre-1.0.3.txt", "current-version-pre-rollback-1.0.3.txt",
        "READY_FOR_OPERATOR_ROLLBACK_1.0.3_TO_1.0.2_NO_CHANGES",
        "ROLLED_BACK_POINTER_TO_1.0.2_BOTH_BINARIES_RETAINED",
        INSTALLED_V102_SHA, pins["candidateExeSha256"],
    )
    missing = [fragment for fragment in required_fragments if fragment not in source]
    if missing:
        raise Rejected("rollback lacks reviewed preconditions: " + ", ".join(missing[:4]))
    for dangerous in ("Invoke-Expression", "Invoke-WebRequest", "Start-Process",
                      "Set-ExecutionPolicy", "Remove-Item -Recurse", "SwitchDesktop"):
        if dangerous in source:
            raise Rejected("unexpected executable/action token in reviewed rollback: " + dangerous)
    return {
        "status": "OPERATOR_ROLLBACK_STATIC_PIN_AND_GUARDS_VERIFIED",
        "rollbackScriptSha256": _digest(script_file),
        "rollbackManifestSha256": _digest(manifest_file),
        "scriptBytes": script_file.stat().st_size,
        "operatorApplyRequired": True, "currentVersionRequired": "1.0.3",
        "oldAndNewExeShaPinned": True, "peVersionsCheckedInScript": True,
        "cimNoRunningTarazGuardPresent": True,
        "pointerWriteAclPrecheckPresent": True,
        "noOverwriteGuardsPresent": True, "atomicPointerReplacementPresent": True,
        "actuallyRanInstaller": False, "actuallyRanRollback": False,
    }


def disposable_operator_rollback(build: Path, installed: Path, rollback_dir: Path,
                                 static: dict) -> dict:
    """Black-box exercise of separately pinned rollback PS1 on fake install.

    Operates only within a newly created disposable root. Real binaries are
    copied unchanged. The script itself reads no real data or backup profile.
    """
    if os.name != "nt":
        raise Rejected("rollback PowerShell acceptance requires Windows")
    if static.get("status") != "OPERATOR_ROLLBACK_STATIC_PIN_AND_GUARDS_VERIFIED":
        raise Rejected("disposable rollback requires independent SHA and static guard approval")
    old_binary = _regular(installed / "versions" / "1.0.2" / "Taraz.exe")
    candidate_binary = _regular(build / "binary" / "Taraz.exe")
    _same_hash(old_binary, INSTALLED_V102_SHA, "rollback fixture old binary")
    script_file = _regular(rollback_dir / "Rollback-Taraz-V103-To-V102.ps1")
    _same_hash(script_file, ROLLBACK_SCRIPT_SHA, "rollback fixture reviewed script")
    _same_hash(candidate_binary, _json(rollback_dir / "rollback-gate-manifest.json")[
        "pinnedArtifacts"]["candidateExeSha256"], "rollback fixture candidate binary")

    with tempfile.TemporaryDirectory(prefix="taraz-v103-independent-rollback-", dir=str(PARENT)) as tmp:
        root = Path(tmp)
        local = root / "qa" / "local"
        product = local / "Programs" / "Taraz"
        old = product / "versions" / "1.0.2" / "Taraz.exe"
        new = product / "versions" / "1.0.3" / "Taraz.exe"
        old.parent.mkdir(parents=True)
        new.parent.mkdir(parents=True)
        shutil.copyfile(old_binary, old)
        shutil.copyfile(candidate_binary, new)
        _same_hash(old, INSTALLED_V102_SHA, "disposable rollback old binary")
        _same_hash(new, _digest(candidate_binary), "disposable rollback new binary")
        pointer = put_pointer = product / "current-version.txt"
        pointer.write_bytes(b"1.0.3\r\n")
        activated = product / "current-version-pre-1.0.3.txt"
        activated.write_bytes(b"1.0.2\r\n")
        shutil.copyfile(installed / "Run-Taraz.cmd", product / "Run-Taraz.cmd")
        fake_finance = root / "qa" / "roaming" / "Taraz" / "ledger-test-only.bin"
        fake_finance.parent.mkdir(parents=True)
        fake_finance.write_bytes(b"DISPOSABLE-LEDGER-CANARY-DO-NOT-POST")
        finance_sha = _digest(fake_finance)
        before = {name: _digest(path) for name, path in (
            ("oldExe", old), ("newExe", new), ("pointer", pointer),
            ("activatedPointerBackup", activated), ("ledgerCanary", fake_finance))}
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(local)
        env["APPDATA"] = str(root / "qa" / "roaming")
        env["USERPROFILE"] = str(root / "qa")
        env["TEMP"] = str(root / "qa" / "temp")
        env["TMP"] = env["TEMP"]
        Path(env["TEMP"]).mkdir()

        def invoke(*options: str) -> subprocess.CompletedProcess:
            return subprocess.run([
                "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(script_file), *options,
            ], env=env, cwd=str(root), capture_output=True, text=True,
               encoding="utf-8", errors="replace", check=False, timeout=90)

        preflight = invoke()
        if preflight.returncode or "READY_FOR_OPERATOR_ROLLBACK_1.0.3_TO_1.0.2_NO_CHANGES" not in preflight.stdout:
            raise Rejected("disposable rollback preflight failed: " +
                           (preflight.stdout + preflight.stderr)[-350:])
        if before != {name: _digest(path) for name, path in (
                ("oldExe", old), ("newExe", new), ("pointer", pointer),
                ("activatedPointerBackup", activated), ("ledgerCanary", fake_finance))}:
            raise Rejected("read-only rollback preflight modified fixture bytes")
        if (product / "current-version-pre-rollback-1.0.3.txt").exists():
            raise Rejected("rollback preflight prematurely created pointer backup")
        applied = invoke("-Apply")
        if applied.returncode or "ROLLED_BACK_POINTER_TO_1.0.2_BOTH_BINARIES_RETAINED" not in applied.stdout:
            raise Rejected("disposable rollback apply failed: " +
                           (applied.stdout + applied.stderr)[-350:])
        back = product / "current-version-pre-rollback-1.0.3.txt"
        if (pointer.read_text(encoding="utf-8").strip() != "1.0.2"
                or back.read_text(encoding="utf-8").strip() != "1.0.3"
                or activated.read_text(encoding="utf-8").strip() != "1.0.2"):
            raise Rejected("disposable rollback failed atomic pointer/backup readback")
        if (_digest(old) != before["oldExe"] or _digest(new) != before["newExe"]
                or _digest(fake_finance) != finance_sha):
            raise Rejected("disposable rollback mutated binary or synthetic ledger")
        second = invoke("-Apply")
        if second.returncode == 0 or pointer.read_text(encoding="utf-8").strip() != "1.0.2":
            raise Rejected("rollback second apply did not fail closed")
        return {"status": "DISPOSABLE_OPERATOR_ROLLBACK_APPLY_PASSED",
                "preflightExit": preflight.returncode, "applyExit": applied.returncode,
                "secondApplyRefused": True, "versionsRetained": True,
                "syntheticLedgerCanaryShaUnchanged": True,
                "productionProfileOrPointerModified": False, "realFinanceRollbackProven": False}


def inspect(build: Path | None = None, backup: Path = BACKUP,
            installed: Path | None = None, *, run_disposable: bool = False,
            run_private_gui: bool = False,
            rollback: Path = ROLLBACK_ROOT, run_disposable_rollback: bool = False) -> dict:
    output = {"decision": "NO_GO", "checks": {}, "gates": []}
    checks, gates = output["checks"], output["gates"]
    if installed is None:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise Rejected("LOCALAPPDATA environment variable absent")
        installed = Path(local) / "Programs" / "Taraz"
    if build is None:
        try:
            build = discover()
        except (Rejected, OSError) as error:
            checks["candidate"] = {"status": "NOT_READY", "error": str(error)}
            gates.append("candidate_not_ready")
    else:
        build = _regular(build, folder=True)
    validated = None
    if build is not None:
        try:
            validated = verify_candidate(build)
            checks["candidate"] = {key: value for key, value in validated.items() if key != "manifest"}
        except (Rejected, OSError, ValueError, zipfile.BadZipFile,
                ModuleNotFoundError, KeyError) as error:
            checks["candidate"] = {"status": "FAILED", "error": str(error)}
            gates.append("candidate_independent_binary_or_package_parity_failed")
    try:
        checks["installed"] = installed_baseline(installed)
    except (Rejected, OSError, ValueError) as error:
        checks["installed"] = {"status": "FAILED", "error": str(error)}
        gates.append("installed_v102_baseline_unverified")
    try:
        checks["backup"] = verify_backup(backup)
    except (Rejected, OSError, ValueError) as error:
        checks["backup"] = {"status": "FAILED", "error": str(error)}
        gates.append("fresh_v102_backup_unverified")
    if run_disposable:
        if (validated is not None and checks["installed"].get("version") == "1.0.2"
                and checks["backup"].get("status") == "FRESH_V102_BACKUP_BYTES_MATCH"):
            try:
                checks["disposable"] = disposable_install(build, installed, backup, validated)
            except (Rejected, OSError, subprocess.TimeoutExpired) as error:
                checks["disposable"] = {"status": "FAILED", "error": str(error)}
                gates.append("disposable_side_by_side_upgrade_or_pointer_restore_failed")
        else:
            checks["disposable"] = {"status": "SKIPPED", "reason": "required evidence has not passed"}
            gates.append("disposable_exercise_skipped_due_to_failed_prerequisite")
    else:
        checks["disposable"] = {"status": "NOT_RUN", "reason": "use --disposable for controlled temporary test"}
        gates.append("disposable_installer_acceptance_not_run")
    if run_private_gui:
        if (validated is not None and checks["installed"].get("version") == "1.0.2"
                and checks["backup"].get("status") == "FRESH_V102_BACKUP_BYTES_MATCH"):
            try:
                checks["privateGui"] = private_desktop_gui_smoke(build, backup, validated)
                if checks["privateGui"]["status"] != "PRIVATE_DESKTOP_WEBVIEW2_SMOKE_PASSED":
                    gates.append("native_gui_private_desktop_webview_not_proven")
            except (Rejected, OSError, ValueError, ImportError) as error:
                checks["privateGui"] = {"status": "FAILED", "error": str(error)}
                gates.append("native_gui_private_desktop_failed")
        else:
            checks["privateGui"] = {"status": "SKIPPED", "reason": "independent pins/backup not verified"}
            gates.append("native_gui_private_desktop_skipped_due_to_prerequisite")
    else:
        checks["privateGui"] = {"status": "NOT_RUN", "reason": "use --private-gui for own-desktop smoke"}
        gates.append("native_gui_private_desktop_not_run")
    rollback_validated = None
    if validated is not None:
        try:
            rollback_validated = verify_operator_rollback(rollback, build)
            checks["rollback"] = rollback_validated
        except (Rejected, OSError, ValueError, KeyError) as error:
            checks["rollback"] = {"status": "NOT_VERIFIED", "error": str(error)}
            gates.append("operator_rollback_artifact_unverified")
    else:
        checks["rollback"] = {"status": "SKIPPED", "reason": "candidate not independently verified"}
        gates.append("operator_rollback_artifact_skipped")
    if run_disposable_rollback:
        if (rollback_validated is not None and checks["installed"].get("version") == "1.0.2"):
            try:
                checks["disposableRollback"] = disposable_operator_rollback(
                    build, installed, rollback, rollback_validated)
            except (Rejected, OSError, subprocess.TimeoutExpired, ValueError) as error:
                checks["disposableRollback"] = {"status": "FAILED", "error": str(error)}
                gates.append("disposable_operator_rollback_failed")
        else:
            checks["disposableRollback"] = {"status": "SKIPPED", "reason": "pinned artifact/baseline missing"}
            gates.append("disposable_operator_rollback_unverified")
    else:
        checks["disposableRollback"] = {"status": "NOT_RUN", "reason": "use --disposable-rollback"}
        gates.append("disposable_operator_rollback_not_run")
    gates.extend(["real_gui_login_and_madar_permissions_not_independently_tested",
                  "real_financial_posting_and_ledger_migration_unverified",
                  "publisher_signing_unverified_candidate_reports_unsigned",
                  "operator_release_approval_absent"])
    output["gates"] = sorted(set(gates))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, help="specific completed build directory, if multiple exist")
    parser.add_argument("--installed", type=Path, help="override installed root for controlled tests")
    parser.add_argument("--backup", type=Path, default=BACKUP)
    parser.add_argument("--disposable", action="store_true",
                        help="run reviewed install+activate scripts in temporary LOCALAPPDATA only")
    parser.add_argument("--private-gui", action="store_true",
                        help="launch pinned GUI on own Windows desktop + private kill-on-close job")
    parser.add_argument("--rollback", type=Path, default=ROLLBACK_ROOT,
                        help="independent worker29 operator rollback artifact location")
    parser.add_argument("--disposable-rollback", action="store_true",
                        help="execute pinned operator rollback on a temporary fake v103 installation only")
    args = parser.parse_args()
    try:
        result = inspect(args.build, args.backup, args.installed,
                         run_disposable=args.disposable, run_private_gui=args.private_gui,
                         rollback=args.rollback, run_disposable_rollback=args.disposable_rollback)
    except (Rejected, OSError, ValueError, subprocess.TimeoutExpired) as error:
        result = {"decision": "NO_GO", "checks": {}, "gates": ["audit_failed_closed"],
                  "error": type(error).__name__ + ": " + str(error)}
    # Work even when Windows PowerShell stdout uses CP1256/legacy code pages.
    print(json.dumps(result, indent=2, ensure_ascii=True, sort_keys=True))
    return 2


if __name__ == "__main__":
    sys.exit(main())
