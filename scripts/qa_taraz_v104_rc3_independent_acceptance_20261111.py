"""Read-only RC3 v104 independent binary gate; optional *disposable* PS5.1 QA.

This DOES NOT install or start real Taraz, operate on real ledgers, or approve a
production release. Actual installer -Apply is permitted ONLY within a private
synthetic LOCALAPPDATA after an independently SHA-pinned worker26 prior test
witness for this exact RC3 build has been supplied. No original files written.
"""
from __future__ import annotations

import argparse
import ctypes
import dis
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
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.4-p1"
SOURCE_STAGE = OUTPUT / "source-stage-ca9761aa43d8"
VITE_STAGE = OUTPUT / "vite-qa-72ee216638e4"
BUILD = OUTPUT / "build-0bde36e11d99"
RC1_REJECTED = OUTPUT / "build-6d851f756264"
BACKUP = ROOT.parents[1] / "MTR-REAL-UPGRADE-BACKUPS-20261110" / "taraz-v103-cold-20261111"
COUNT = 131
SOURCE_SHA = "e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de"
SOURCE_MAP_SHA = "b31db9348ad61f132be02788adfbbf5b93cc532f7f25bed25a7c701d8ed4ef11"
SOURCE_REPORT_SHA = "2813cbcaeab16b7cbc9ce9b79d19fa3f5c24688cc2906e7fed06352f0a0b0ebe"
VITE_JS_SHA = "3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9"
VITE_REPORT_SHA = "5940d2765b6a9ff6810078364fb5422c1eb112697f7f02f46156aa85624d69b8"
EXE_SHA = "9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce"
ZIP_SHA = "1a9ca13c914385c92be68ffdd2034c723843dde1846fa548762864aa98ac134e"
MANIFEST_SHA = "b6ac2e3050274e3ec8e3bcaaf32b694d673b1747cfab580245136ec500e65bc6"
REPORT_SHA = "510de237a7fcea8553e0a64951bf76f3f7bef722318585db016d4e602df8b9fb"
RC1_EXE_SHA = "8e2a8026b48e278df95693d9349f5a566df9b75c12497882b3bebca96679adc6"
RC1_SOURCE_SHA = "6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1"
V102_SHA = "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52"
BACKUP_MAP_SHA = "8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d"
BACKUP_REPORT_SHA = "68bb6e26b9a9a10818e6752a7cc1475a3861c5f380f2021eb5c112a74cd7d2c9"
WORKER26_DOCUMENT = ROOT / "docs" / "TARAZ_V104_P1_SECURE_RC2_20261111.md"
WORKER26_DOCUMENT_SHA = "6f4dafda65de6095f200be7cdd48306136592369d4819eefb9a0372ce54b310d"
MAX_JSON = 5 * 1024 * 1024
MAX_SOURCE = 32 * 1024 * 1024
MAX_EXE = 80 * 1024 * 1024
MAX_ZIP = 85 * 1024 * 1024
MAX_BACKUP = 300 * 1024 * 1024
ZIP_NAMES = frozenset({
    "Taraz.exe", "Install-Taraz-V104.ps1", "Activate-Taraz-V104.ps1",
    "package.json", "package-lock.json", "source-sha256.json", "update-manifest.json",
})
EXPECTED_MODULES = {
    "taraz_madar_data_reader": frozenset({
        "local_madar_available", "read_local_madar_state", "read_authorized_madar_state",
        "_network_config", "_validate_paging"}),
    "standalone_accounting_template_store": frozenset({
        "save", "set_default", "delete", "duplicate"}),
    "taraz_integration": frozenset(),
    "personal_parsian_bridge": frozenset(),
    "standalone_accounting_auto_backup": frozenset(),
}
NATIVE_BRIDGE = frozenset({
    "tarazMadarDataOverview", "tarazMadarDataRead",
    "tarazIntegrationList", "tarazIntegrationReview", "tarazIntegrationRecover",
})
EXTERNAL_QA = {
    "rc2-source-stage": 10,
    "rc2-original-seven-edge": 7,
    "rc2-residual-three-edge": 3,
}


class NoGo(RuntimeError):
    """Fail closed on missing, unsafe, ambiguous or mismatched evidence."""


def pin(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch("[a-f0-9]{64}", value) is None:
        raise NoGo("Expected explicit lowercase 64-digit SHA256")
    return value


def check_path(path: Path, *, directory: bool = False, limit: int = MAX_EXE) -> Path:
    path = Path(path).absolute()
    if os.name == "nt" and (not path.drive or path.drive.startswith("\\\\")):
        raise NoGo("Absolute local drive required; UNC refused")
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and
                                getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
            raise NoGo("Symlink/junction/reparse in artifact path")
    if directory:
        if not path.is_dir():
            raise NoGo("Expected directory missing")
    else:
        if (not path.is_file() or not stat.S_ISREG(path.stat().st_mode)
                or path.stat().st_size > limit or path.stat().st_nlink != 1):
            raise NoGo("Expected bounded independent non-hardlinked regular file")
    return path


def digest(path: Path, *, limit: int = MAX_EXE) -> str:
    check_path(path, limit=limit)
    sha = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def exact(path: Path, known: str, *, limit: int = MAX_EXE) -> str:
    if digest(path, limit=limit) != pin(known):
        raise NoGo("Byte SHA256 mismatch: " + path.name)
    return known


def safe_name(value: object) -> Path:
    if (not isinstance(value, str) or not value or len(value) > 500 or
            value.startswith("/") or "\\" in value or ":" in value or "//" in value or
            re.search(r'[\x00-\x1f<>|"?*]', value)):
        raise NoGo("Unsafe source/ZIP member path")
    elements = value.split("/")
    if any(part in ("", ".", "..") or part.endswith((".", " ")) for part in elements):
        raise NoGo("Invalid relative path components")
    return Path(*PurePosixPath(value).parts)


def read_obj(path: Path) -> dict:
    check_path(path, limit=MAX_JSON)
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError) as error:
        raise NoGo("Invalid independent JSON witness") from error
    if not isinstance(obj, dict):
        raise NoGo("Expected JSON object")
    return obj


def source_fingerprint(entries: dict) -> str:
    if not isinstance(entries, dict) or len(entries) != COUNT:
        raise NoGo("Frozen source inventory not 131 records")
    for key, value in entries.items():
        safe_name(key)
        pin(value)
    if len({k.casefold() for k in entries}) != COUNT:
        raise NoGo("Case-ambiguous duplicate source paths")
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode("utf-8")).hexdigest()


def entire_tree_matches(root: Path, expected: dict, *, staged: frozenset = frozenset()) -> int:
    check_path(root, directory=True)
    found: set[str] = set()
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            check_path(Path(folder) / name, directory=True)
        for name in files:
            file = Path(folder) / name
            relative = file.relative_to(root).as_posix()
            if relative not in expected:
                raise NoGo("Unlisted file in pinned tree")
            if relative not in staged:
                exact(file, expected[relative], limit=MAX_SOURCE)
            found.add(relative)
    if found != set(expected):
        raise NoGo("Frozen tree missing members")
    return len(found)


def source_authority() -> dict:
    check_path(SOURCE_STAGE, directory=True)
    exact(SOURCE_STAGE / "stage-report.json", SOURCE_REPORT_SHA, limit=MAX_JSON)
    exact(SOURCE_STAGE / "patched-source-sha256.json", SOURCE_MAP_SHA, limit=MAX_JSON)
    report = read_obj(SOURCE_STAGE / "stage-report.json")
    inventory = read_obj(SOURCE_STAGE / "patched-source-sha256.json")
    if (report.get("status") != "V104_RC3_SOURCE_ONLY_EDGE_QA_PENDING"
            or report.get("sourceSha256") != SOURCE_SHA
            or report.get("sourceCount") != COUNT
            or report.get("executableBuilt") is not False
            or report.get("releaseApproved") is not False
            or report.get("dynamicEdgeApproved") is not False
            or report.get("changedSourceFiles") !=
            ["src/accounting_management_dashboard.jsx"]
            or report.get("startingSourceSha256") !=
            "aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8"
            or source_fingerprint(inventory) != SOURCE_SHA):
        raise NoGo("RC3 source not exact independently frozen stage")
    checked = entire_tree_matches(SOURCE_STAGE / "source", inventory)
    return {"sourceCount": checked, "sourceSha256": SOURCE_SHA, "files": inventory}


def vite_authority() -> dict:
    check_path(VITE_STAGE, directory=True)
    exact(VITE_STAGE / "rc3-vite-qa-report.json", VITE_REPORT_SHA, limit=MAX_JSON)
    record = read_obj(VITE_STAGE / "rc3-vite-qa-report.json")
    if (record.get("status") != "V104_RC3_STAGE_UI_ONLY_EDGE_QA_PENDING"
            or record.get("stage") != str(SOURCE_STAGE)
            or record.get("sourceSha256") != SOURCE_SHA
            or record.get("sourceCount") != COUNT
            or record.get("sourceStageReportSha256") != SOURCE_REPORT_SHA
            or record.get("sourceInventoryFileSha256") != SOURCE_MAP_SHA
            or record.get("jsSha256") != VITE_JS_SHA
            or record.get("compiledExe") is not False
            or record.get("dynamicEdgeApproved") is not False):
        raise NoGo("Vite stage mismatched or falsely claims native/Edge approval")
    assets = {}
    for key, sha in (("jsRelativePath", "jsSha256"),
                     ("cssRelativePath", "cssSha256"),
                     ("htmlRelativePath", "htmlSha256")):
        path = safe_name(record.get(key))
        if not path.parts or path.parts[0] != "dist":
            raise NoGo("Vite source outside dist")
        exact(VITE_STAGE / path, record.get(sha), limit=MAX_SOURCE)
        assets[path.relative_to("dist").as_posix()] = record[sha]
    return {"viteJsSha256": VITE_JS_SHA, "assetPins": assets}


def backup_authority() -> dict:
    check_path(BACKUP, directory=True)
    exact(BACKUP / "snapshot-manifest.json", BACKUP_MAP_SHA, limit=MAX_JSON)
    exact(BACKUP / "backup-acceptance-report.json", BACKUP_REPORT_SHA, limit=MAX_JSON)
    manifest = read_obj(BACKUP / "snapshot-manifest.json")
    report = read_obj(BACKUP / "backup-acceptance-report.json")
    files = manifest.get("files")
    witness = report.get("backup")
    if (not isinstance(files, dict) or len(files) != 181
            or manifest.get("fileCount") != 181
            or manifest.get("totalBytes") != 124011875
            or manifest.get("verifiedNoOverwrite") is not True
            or manifest.get("allFilesIncluded") is not True
            or not isinstance(manifest.get("sqliteChecks"), dict)
            or len(manifest["sqliteChecks"]) != 67
            or report.get("status") != "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING"
            or report.get("installedBefore") != "1.0.2"
            or report.get("installedAfter") != "1.0.2"
            or report.get("installedExeSha256") != V102_SHA
            or not isinstance(witness, dict)
            or witness.get("fileCount") != 181
            or witness.get("sqliteValidatedCount") != 67
            or witness.get("backupRoot") != str(BACKUP)
            or witness.get("manifestSha256") != BACKUP_MAP_SHA
            or witness.get("independentReadback") is not True):
        raise NoGo("Original 181-file cold backup authority invalid")
    found: set[str] = set()
    total = 0
    backup_files = BACKUP / "files"
    check_path(backup_files, directory=True)
    for parent, directories, names in os.walk(backup_files, followlinks=False):
        for name in directories:
            check_path(Path(parent) / name, directory=True)
        for name in names:
            path = Path(parent) / name
            key = path.relative_to(backup_files).as_posix()
            rel = safe_name(key)
            if (not rel.parts or rel.parts[0] not in ("roaming", "local", "bridge")
                    or key not in files):
                raise NoGo("Unexpected cold backup content")
            row = files[key]
            if not isinstance(row, dict) or not isinstance(row.get("bytes"), int):
                raise NoGo("Incomplete cold backup member metadata")
            exact(path, row.get("sha256"), limit=MAX_BACKUP)
            if path.stat().st_size != row["bytes"]:
                raise NoGo("Cold backup byte size drift")
            found.add(key)
            total += row["bytes"]
            if total > MAX_BACKUP:
                raise NoGo("Cold backup bounded byte size exceeded")
    if found != set(files) or total != manifest["totalBytes"] or total != witness.get("totalBytes"):
        raise NoGo("Cold backup membership/byte total differs")
    return {"rehashedFiles": len(found), "rehashedBytes": total,
            "sqliteChecksFromPriorWitnessNotRerun": 67,
            "manifestSha256": BACKUP_MAP_SHA, "acceptanceReportSha256": BACKUP_REPORT_SHA}


def installed_authority() -> dict:
    if os.name != "nt" or not os.getenv("LOCALAPPDATA"):
        raise NoGo("Installed v102 authority requires Windows local profile")
    root = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz"
    check_path(root, directory=True)
    pointer = root / "current-version.txt"
    launcher = root / "Run-Taraz.cmd"
    old_exe = root / "versions" / "1.0.2" / "Taraz.exe"
    if check_path(pointer).read_text(encoding="utf-8-sig").strip() != "1.0.2":
        raise NoGo("Installed pointer not original v102")
    exact(old_exe, V102_SHA)
    if "versions\\%TARAZ_VERSION%\\Taraz.exe" not in check_path(
            launcher).read_text(encoding="utf-8", errors="replace"):
        raise NoGo("Versioned launcher contract differs")
    if (root / "versions" / "1.0.4").exists() or (root / "versions" / "1.0.4").is_symlink():
        raise NoGo("Real installed v104 path already exists")
    return {"pointer": "1.0.2", "version104Installed": False,
            "baselineBinarySha256": V102_SHA,
            "pointerSha256": digest(pointer), "launcherSha256": digest(launcher)}


def pe_fixed_version(path: Path) -> str:
    check_path(path)
    if os.name != "nt":
        raise NoGo("Cannot independently read PE resource outside Windows")
    library = ctypes.windll.version
    library.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    library.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
    size = library.GetFileVersionInfoSizeW(str(path), ctypes.byref(ctypes.c_ulong()))
    if not 64 <= size <= 1_000_000:
        raise NoGo("No native fixed version resource")
    buff = ctypes.create_string_buffer(size)
    library.GetFileVersionInfoW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    library.GetFileVersionInfoW.restype = ctypes.c_int
    if library.GetFileVersionInfoW(str(path), 0, size, buff) == 0:
        raise NoGo("PE version resource read failed")
    location, length = ctypes.c_void_p(), ctypes.c_uint()
    library.VerQueryValueW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    library.VerQueryValueW.restype = ctypes.c_int
    if not library.VerQueryValueW(buff, "\\", ctypes.byref(location), ctypes.byref(length)):
        raise NoGo("PE VS_FIXEDFILEINFO missing")
    data = ctypes.cast(location, ctypes.POINTER(ctypes.c_uint32))
    if data[0] != 0xFEEF04BD:
        raise NoGo("PE fixed info signature wrong")
    return (f"{data[2] >> 16}.{data[2] & 65535}."
            f"{data[3] >> 16}.{data[3] & 65535}")


def assigned_constant(code: types.CodeType, key: str):
    items = list(dis.get_instructions(code))
    for i, item in enumerate(items):
        if (i > 0 and item.opname in ("STORE_NAME", "STORE_GLOBAL")
                and item.argval == key and items[i - 1].opname == "LOAD_CONST"):
            return items[i - 1].argval
    raise NoGo("Frozen PYZ missing direct literal constant: " + key)


def recursive_methods(code: types.CodeType) -> set[str]:
    names = set()
    for item in code.co_consts:
        if isinstance(item, types.CodeType):
            names.add(item.co_name)
            names.update(recursive_methods(item))
    return names


def recursive_strings(code: types.CodeType) -> list[str]:
    strings = []
    for item in code.co_consts:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, types.CodeType):
            strings.extend(recursive_strings(item))
    return strings


def inspect_native_binary(path: Path, ui_root: Path, claimed: dict) -> dict:
    """PE resource + frozen PYZ static code + full PyInstaller CArchive UI bytes."""
    from PyInstaller.archive.readers import CArchiveReader

    if pe_fixed_version(path) != "1.0.4.0":
        raise NoGo("Actual RC3 native PE version is not 1.0.4.0")
    outer = CArchiveReader(str(path))
    embedded = outer.open_embedded_archive("PYZ.pyz")
    version = embedded.extract("taraz_release_version")
    if (not isinstance(version, types.CodeType)
            or assigned_constant(version, "APP_VERSION") != "1.0.4"
            or assigned_constant(version, "QA_ONLY") is not False
            or assigned_constant(version, "BUILD_CHANNEL") != "offline-production-candidate"):
        raise NoGo("RC3 PYZ version/release channel still QA-only or old")
    entry_data = outer.extract("taraz_desktop")
    if not isinstance(entry_data, bytes):
        raise NoGo("Actual compiled taraz_desktop entrypoint absent")
    try:
        entry = marshal.loads(entry_data)
    except (ValueError, TypeError, EOFError) as error:
        raise NoGo("Compiled entrypoint marshal unreadable") from error
    if (not isinstance(entry, types.CodeType)
            or not NATIVE_BRIDGE <= recursive_methods(entry)
            or "_taraz_qa_launch_gate" in recursive_methods(entry)):
        raise NoGo("Missing native methods or QA gate left in EXE")
    for name, expected in EXPECTED_MODULES.items():
        code = embedded.extract(name)
        if not isinstance(code, types.CodeType) or not expected <= recursive_methods(code):
            raise NoGo("PYZ missing module/method: " + name)
    bridge = embedded.extract("standalone_accounting_desktop")
    if not isinstance(bridge, types.CodeType):
        raise NoGo("Compiled accounting WebView bridge absent")
    scripts = [text for text in recursive_strings(bridge)
               if "window.madar = Object.fromEntries(" in text]
    if len(scripts) != 1 or not all("'" + name + "'" in scripts[0] for name in NATIVE_BRIDGE):
        raise NoGo("WebView API forwarding incomplete")
    members = {key.replace("\\", "/"): key for key in outer.toc}
    seen = {}
    check_path(ui_root, directory=True)
    for folder, dirs, filenames in os.walk(ui_root, followlinks=False):
        for name in dirs:
            check_path(Path(folder) / name, directory=True)
        for name in filenames:
            file = Path(folder) / name
            relative = file.relative_to(ui_root).as_posix()
            if relative not in claimed:
                raise NoGo("Compiled HTML asset unlisted in manifest")
            actual = exact(file, claimed[relative], limit=MAX_SOURCE)
            member = members.get("dist/" + relative)
            if not member:
                raise NoGo("Compiled UI file not embedded in real EXE")
            actual_bytes = outer.extract(member)
            if not isinstance(actual_bytes, bytes) or hashlib.sha256(
                    actual_bytes).hexdigest() != actual:
                raise NoGo("Embedded EXE UI asset SHA differs from disk")
            seen[relative] = actual
    if seen != claimed or len(seen) != 15:
        raise NoGo("Expected exactly 15 compiled UI assets including JS")
    js = {key: sha for key, sha in seen.items() if key.endswith(".js")}
    if len(js) != 1 or next(iter(js.values())) != VITE_JS_SHA:
        raise NoGo("Embedded RC3 JS not independently Edge tested JS")
    return {"peVersion": "1.0.4.0", "pyzVersion": "1.0.4",
            "nativeMethodCount": len(NATIVE_BRIDGE), "pyzModulesCount": len(EXPECTED_MODULES),
            "uiAssetsRehashedInsideExe": len(seen), "jsSha256": VITE_JS_SHA,
            "realExeLaunched": False, "compiledGuiDynamicallyTestedHere": False}


def verify_offline_zip(zip_path: Path, package: Path) -> dict:
    exact(zip_path, ZIP_SHA, limit=MAX_ZIP)
    check_path(package, directory=True)
    members = {file.name: file for file in package.iterdir()}
    if set(members) != ZIP_NAMES or any(not path.is_file() for path in members.values()):
        raise NoGo("Exactly seven offline package files required")
    sha = {name: digest(path) for name, path in members.items()}
    with zipfile.ZipFile(zip_path) as archive:
        listing = archive.infolist()
        if len(listing) != 7 or {row.filename for row in listing} != ZIP_NAMES:
            raise NoGo("ZIP member list missing/extra/duplicate")
        for row in listing:
            safe_name(row.filename)
            if row.is_dir() or row.file_size > MAX_EXE:
                raise NoGo("ZIP entry not bounded file")
            hasher = hashlib.sha256()
            with archive.open(row) as reader:
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    hasher.update(chunk)
            if hasher.hexdigest() != sha[row.filename]:
                raise NoGo("ZIP member data SHA differs from extracted original")
    return {"zipSha256": ZIP_SHA, "membersRehashed": len(sha), "memberSha256": sha}


def qa_witnesses(report: dict, manifest: dict) -> dict:
    security = manifest.get("secureRepackage", {})
    claims = report.get("qaBeforeBuild")
    if not isinstance(claims, dict) or claims != report.get("qa") or claims != security.get("qa"):
        raise NoGo("Builder's independent upstream QA witnesses missing or inconsistent")
    if set(claims) != set(EXTERNAL_QA):
        raise NoGo("Must pin 3 QA groups: 10 source + 7 original + 3 inverse")
    results = {}
    for name, minimum in EXTERNAL_QA.items():
        row = claims.get(name)
        if not isinstance(row, dict) or row.get("checksPassed", 0) < minimum:
            raise NoGo("Prebuild QA group absent/incomplete: " + name)
        expected_file = Path(row.get("path", ""))
        sha = row.get("sha256")
        if (expected_file.parent != OUTPUT / "qa-evidence-rc3-prime-59c27fd65bbe"
                or not expected_file.is_file()):
            raise NoGo("Upstream QA witness path untrusted")
        exact(expected_file, sha, limit=MAX_JSON)
        item = read_obj(expected_file)
        if (item.get("kind") != name
                or item.get("status") != "PASS"
                or item.get("sourceStage") != str(SOURCE_STAGE)
                or item.get("sourceSha256") != SOURCE_SHA
                or item.get("sourceCount") != COUNT
                or item.get("failures") != 0
                or item.get("skipped") != 0
                or item.get("exitCode") != 0
                or item.get("checksPassed", 0) < minimum
                or not isinstance(item.get("command"), str)
                or not item["command"].strip()):
            raise NoGo("Exact upstream independent QA content not approved")
        if name != "rc2-source-stage" and (
                item.get("verifiedMode") != "RC3_INVERTED_STAGE_UI_ONLY"
                or item.get("viteQaRoot") != str(VITE_STAGE)
                or item.get("viteJsSha256") != VITE_JS_SHA
                or item.get("financialCommands") != 0
                or item.get("compiledNativeExeTested") is not False):
            raise NoGo("Edge acceptance must be for exact staged RC3 JS only")
        results[name] = {"checksPassed": item["checksPassed"], "sha256": sha}
    return results


def installer_contract(offline: Path, mf: dict) -> dict:
    for name, key in (("Install-Taraz-V104.ps1", "installScriptSha256"),
                      ("Activate-Taraz-V104.ps1", "activationScriptSha256")):
        exact(offline / name, mf.get(key), limit=MAX_SOURCE)
    install = (offline / "Install-Taraz-V104.ps1").read_text(encoding="utf-8")
    active = (offline / "Activate-Taraz-V104.ps1").read_text(encoding="utf-8")
    for text in (install, active):
        for needle in (
                "param([switch]$Apply", "Set-StrictMode -Version Latest",
                "TarazV104SecureLinkInfo", "HardlinkCount", "$parent=$item.Directory",
                "Get-CimInstance", "function CheckBackup", "function SafePath",
                "function CheckPackagePins", "RequireAbsent",
                SOURCE_SHA, SOURCE_MAP_SHA, EXE_SHA, V102_SHA):
            if needle not in text:
                raise NoGo("Hardened v104 installer guard/source/exe pin not found")
        if any(needle in text for needle in (
                "Start-Process", "$item=$item.Parent", "TarazV103SecureLinkInfo",
                "1.0.3", "__FREEZE_SHA__", "__NEW_SHA__")):
            raise NoGo("Unsafe legacy installer syntax or placeholders")
    for token in ("current-version-pre-1.0.4.txt", "current-version-1.0.4-pending.txt",
                  "Run-Taraz-pre-1.0.4.cmd",
                  "[IO.File]::Replace($pending,$pointer,$oldPointer,$true)"):
        if token not in active:
            raise NoGo("RC3 activation pointer/backup contract changed")
    return {"installScriptSha256": mf["installScriptSha256"],
            "activationScriptSha256": mf["activationScriptSha256"],
            "pointerBackupName": "current-version-pre-1.0.4.txt",
            "launcherBackupName": "Run-Taraz-pre-1.0.4.cmd",
            "atomicPointerReplaceDeclared": True, "executedOnRealProfile": False}


def inspect(build: Path) -> dict:
    build = check_path(build, directory=True)
    if build != BUILD:
        raise NoGo("Only observed worker26 RC3 build-0bde36e11d99 is admissible")
    original = check_path(RC1_REJECTED / "binary" / "Taraz.exe")
    exact(original, RC1_EXE_SHA)
    source = source_authority()
    vite = vite_authority()
    baseline = installed_authority()
    backup = backup_authority()
    exact(build / "build-report.json", REPORT_SHA, limit=MAX_JSON)
    report = read_obj(build / "build-report.json")
    off = check_path(build / "offline-update", directory=True)
    exact(off / "update-manifest.json", MANIFEST_SHA, limit=MAX_JSON)
    mf = read_obj(off / "update-manifest.json")
    security = mf.get("secureRepackage", {})
    if not isinstance(security, dict):
        raise NoGo("RC3 secureRepackage absent")
    if not (
            report.get("status") == "PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED"
            and report.get("releaseCandidateRevision") == mf.get("releaseCandidateRevision") == "RC3"
            and report.get("version") == mf.get("targetVersion") == "1.0.4"
            and report.get("sourceFileCount") == mf.get("sourceFilesCount") == COUNT
            and report.get("sourceFreezeSha256") == mf.get("sourceSnapshotSha256") == SOURCE_SHA
            and report.get("sourceStagePath") == security.get("sourceStagePath") == str(SOURCE_STAGE)
            and report.get("sourceStageReportSha256") == security.get("sourceStageReportSha256") == SOURCE_REPORT_SHA
            and security.get("sourceStageInventorySha256") == SOURCE_MAP_SHA
            and report.get("output") == str(BUILD)
            and report.get("exe") == str(build / "binary" / "Taraz.exe")
            and report.get("zip") == str(build / "Taraz-v1.0.4-P1-RC3-SECURE-OFFLINE-UPDATE.zip")
            and report.get("exeSha256") == mf.get("exeSha256") == EXE_SHA
            and report.get("zipSha256") == ZIP_SHA
            and report.get("manifestSha256") == MANIFEST_SHA
            and mf.get("installedBaselineVersion") == "1.0.2"
            and mf.get("installedBaselineSha256") == V102_SHA
            and mf.get("qaOnly") is False
            and mf.get("productionCandidate") is True
            and mf.get("unsigned") is True
            and mf.get("installed") is False
            and mf.get("pointerActivated") is False
            and mf.get("activationApprovalGranted") is False
            and mf.get("financePostingProven") is False
            and mf.get("installedGuiTested") is False
            and mf.get("compiledEdgeRedactionApproved") is False
            and report.get("installed") is False
            and report.get("pointerChanged") is False
            and report.get("releaseApproved") is False
            and security.get("rollbackIncluded") is False
            and security.get("productionApproved") is False
            and security.get("launcherBackupName") == "Run-Taraz-pre-1.0.4.cmd"
            and security.get("hardlinkAndAncestorGuard") == "Win32-linkcount-and-each-ancestor"):
        raise NoGo("EXE report and offline manifest/RC3 metadata disagree")
    evidence = qa_witnesses(report, mf)
    inventory_file = off / "source-sha256.json"
    exact(inventory_file, mf.get("sourceFileManifestSha256"), limit=MAX_JSON)
    original_manifest = read_obj(inventory_file)
    if original_manifest != source["files"] or source_fingerprint(original_manifest) != SOURCE_SHA:
        raise NoGo("Packaged 131-file freeze differs from RC3 staged source")
    build_source = check_path(build / "source", directory=True)
    excluded = frozenset({"taraz_desktop.py", "package.json", "package-lock.json"})
    for relative, sha in original_manifest.items():
        if relative not in excluded:
            exact(build_source / safe_name(relative), sha, limit=MAX_SOURCE)
    stamped = mf.get("stagedVersionSourceSha256")
    if not isinstance(stamped, dict):
        raise NoGo("Build-only package/native version source pins absent")
    for name, key in (
            ("taraz_desktop.py", "nativeEntrySha256"),
            ("taraz_release_version.py", "versionModuleSha256"),
            ("package.json", "packageSha256"),
            ("package-lock.json", "lockSha256")):
        exact(build_source / name, stamped.get(key), limit=MAX_SOURCE)
    for name, key in (("package.json", "stagedPackageSha256"),
                      ("package-lock.json", "stagedLockSha256")):
        exact(off / name, mf.get(key), limit=MAX_SOURCE)
        exact(build_source / name, mf.get(key), limit=MAX_SOURCE)
    package, lock = read_obj(off / "package.json"), read_obj(off / "package-lock.json")
    if [package.get("version"), lock.get("version"),
            lock.get("packages", {}).get("", {}).get("version")] != ["1.0.4"] * 3:
        raise NoGo("New native snapshot did not stamp 1.0.4 package/lock")
    exe = build / "binary" / "Taraz.exe"
    exact(exe, EXE_SHA)
    exact(off / "Taraz.exe", EXE_SHA)
    if mf.get("exeBytes") != exe.stat().st_size or EXE_SHA == RC1_EXE_SHA:
        raise NoGo("Native RC3 EXE size/SHA old or inconsistent")
    reported_assets = report.get("compiled", {}).get("uiAssetsSha256")
    if not isinstance(reported_assets, dict) or reported_assets != mf.get(
            "compiledEvidence", {}).get("uiAssetsSha256"):
        raise NoGo("Compiled UI inventory claims conflict")
    for filename, sha in vite["assetPins"].items():
        if reported_assets.get(filename) != sha:
            raise NoGo("Native compilation differed from exact RC3 Vite HTML/CSS/JS")
    binary = inspect_native_binary(exe, build / "web" / "dist", reported_assets)
    if (report.get("compiled", {}).get("peVersion") != binary["peVersion"]
            or report.get("compiled", {}).get("pyzVersion") != binary["pyzVersion"]):
        raise NoGo("Reported PE/PYZ claims conflict with independent archive inspection")
    scripts = installer_contract(off, mf)
    if (report.get("installScriptSha256") != scripts["installScriptSha256"]
            or report.get("activationScriptSha256") != scripts["activationScriptSha256"]):
        raise NoGo("Script SHAs not identical in actual report and package")
    zip_result = verify_offline_zip(
        build / "Taraz-v1.0.4-P1-RC3-SECURE-OFFLINE-UPDATE.zip", off)
    if zip_result["memberSha256"]["Taraz.exe"] != EXE_SHA:
        raise NoGo("RC3 real ZIP EXE member hash differs")
    return {"subgate": "RC3_STATIC_BINARY_SOURCE_BACKUP_ZIP_GO",
            "productionReleaseApproved": False,
            "candidate": str(build), "exeSha256": EXE_SHA,
            "zipSha256": ZIP_SHA, "manifestSha256": MANIFEST_SHA,
            "reportSha256": REPORT_SHA, "sourceSha256": SOURCE_SHA,
            "sourceFilesRehashed": source["sourceCount"],
            "embedded": binary, "zipMembersRehashed": zip_result["membersRehashed"],
            "compiledViteSha256": VITE_JS_SHA, "upstreamStageEdge": evidence,
            "originalInstalled": baseline, "originalBackup": backup,
            "installerStatic": scripts,
            "installerSyntheticRun": False,
            "financePostingVerified": False,
            "installedCompiledGuiVerifiedHere": False}


def prior_worker26_qa(path: Path | None, expected_sha: str, build: Path) -> dict:
    """No PS1 -Apply without separate *already executed*, pinned worker26 native QA."""
    if path is None:
        raise NoGo("Worker26 prior RC3 native QA witness was not supplied")
    exact(path, expected_sha, limit=MAX_JSON)
    witness = read_obj(path)
    if (witness.get("status") != "PASS"
            or witness.get("candidate") != str(build)
            or witness.get("candidateExeSha256") != EXE_SHA
            or witness.get("testsFailed") != 0
            or not isinstance(witness.get("testsPassed"), int)
            or isinstance(witness["testsPassed"], bool)
            or witness["testsPassed"] < 1
            or witness.get("actualWindowsPS51Tested") is not True
            or witness.get("installedProfileChanged") is not False
            or witness.get("financePosted") is not False):
        raise NoGo("Worker26 RC3 Windows native script test completion unproven")
    return {"worker26QaSha256": expected_sha, "worker26NativeTests": witness["testsPassed"]}


def prior_worker26_pinned_document() -> dict:
    """Read OWN worker26 post-run native QA report; DO NOT fabricate a JSON witness.

    A separately observed prime rerun of these tests also reported 20/20
    pass with no skips. This function validates the actual original document
    bytes and literal test claims; it does *not* pretend to rerun 20 tests.
    """
    exact(WORKER26_DOCUMENT, WORKER26_DOCUMENT_SHA, limit=MAX_SOURCE)
    body = WORKER26_DOCUMENT.read_text(encoding="utf-8")
    for needle in (
        "Native Windows PowerShell 5.1 test command",
        "20 tests passed, 0 failed, 0 skipped",
        "tests.test_taraz_v104_p1_secure_rc2_20261111",
        "current-version-pre-1.0.4.txt",
        "Run-Taraz-pre-1.0.4.cmd",
        "disposable",
        EXE_SHA, ZIP_SHA, MANIFEST_SHA, REPORT_SHA,
        "NO_GO",
    ):
        if needle not in body:
            raise NoGo("Worker26 pinned native PS5.1 completion document missing evidence")
    suite = ROOT / "tests" / "test_taraz_v104_p1_secure_rc2_20261111.py"
    check_path(suite, limit=MAX_SOURCE)
    source = suite.read_text(encoding="utf-8")
    for marker in ("NativeRealRC3Disposable", "test_real_ps51_install_then_activate_with_backups",
                   "test_hardlinked_pointer_rejected_before_install",
                   "test_nested_install_junction_rejected",
                   "TARAZ_V104_RC3_BUILD_DIR"):
        if marker not in source:
            raise NoGo("Worker26 documented native suite no longer contains expected QA")
    return {"source": "worker26 originally authored document, prime reran independently",
            "documentSha256": WORKER26_DOCUMENT_SHA,
            "priorWindowsPS51TestsReportedPass": 20,
            "compiledBinary": EXE_SHA,
            "productionReleaseApproved": False}


def run_disposable(build: Path, inspected: dict) -> dict:
    """Only synthetic profile installation, no operation on real finance data."""
    if os.name != "nt" or shutil.which("powershell.exe") is None:
        raise NoGo("Actual native PS5.1 needed")
    original = installed_authority()
    backup = backup_authority()
    real_root = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz"
    check_path(build / "offline-update", directory=True)
    with tempfile.TemporaryDirectory(prefix="taraz-rc3-accept-", dir=str(OUTPUT)) as name:
        base = Path(name)
        offline = base / "offline"
        shutil.copytree(build / "offline-update", offline, symlinks=False)
        if {p.name for p in offline.iterdir()} != ZIP_NAMES:
            raise NoGo("Fixture offline inventory incomplete")
        product = base / "private-local" / "Programs" / "Taraz"
        old_bin = product / "versions" / "1.0.2" / "Taraz.exe"
        old_bin.parent.mkdir(parents=True)
        shutil.copyfile(real_root / "versions" / "1.0.2" / "Taraz.exe", old_bin)
        exact(old_bin, V102_SHA)
        launcher = product / "Run-Taraz.cmd"
        shutil.copyfile(real_root / "Run-Taraz.cmd", launcher)
        pointer = product / "current-version.txt"
        pointer.write_bytes(b"1.0.2\r\n")
        finance = base / "private-roaming" / "Taraz"
        finance.mkdir(parents=True)
        sentinel = finance / "NONFINANCIAL_SYNTHETIC_SENTINEL.txt"
        sentinel.write_bytes(b"NO_REAL_RECORDS_OR_ACCOUNTING")
        baseline_files = {
            "pointer": digest(pointer),
            "launcher": digest(launcher),
            "oldExe": digest(old_bin),
            "sentinel": digest(sentinel),
        }
        temporary = base / "private-tmp"
        temporary.mkdir()
        env = dict(os.environ, LOCALAPPDATA=str(base / "private-local"),
                   APPDATA=str(base / "private-roaming"), USERPROFILE=str(base),
                   TEMP=str(temporary), TMP=str(temporary),
                   PYTHONDONTWRITEBYTECODE="1")

        def invoke(*, activate: bool = False, apply: bool = False,
                   mode: str = "normal") -> subprocess.CompletedProcess:
            """Test-only CIM function blocks all OTHER Windows Taraz GUI sessions."""
            script = offline / (("Activate" if activate else "Install") + "-Taraz-V104.ps1")
            fake = {
                "normal": "function Get-CimInstance { @() }\n",
                "running": "function Get-CimInstance { @([pscustomobject]@{Name='Taraz.exe'}) }\n",
                "cim-fail": "function Get-CimInstance { throw 'Synthetic-CIM-QA-FAIL' }\n",
            }.get(mode)
            if fake is None:
                raise NoGo("Unknown disposable process scenario")
            wrapper = base / ("fixture-" + mode + ("-activation" if activate else "-installation")
                              + ("-apply" if apply else "-dry") + ".ps1")
            ps = (fake + "$ErrorActionPreference='Stop'\n"
                  + "try {\n"
                  + "& '" + str(script).replace("'", "''") + "' "
                  + ("-Apply " if apply else "")
                  + "-BackupRoot '" + str(BACKUP).replace("'", "''") + "' "
                  + "-BackupManifestSha256 '" + BACKUP_MAP_SHA + "' "
                  + "-BackupReportSha256 '" + BACKUP_REPORT_SHA + "'\n"
                  + "} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 2 }\n")
            wrapper.write_text(ps, encoding="utf-8-sig")
            return subprocess.run([
                "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                env=env, cwd=base, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", timeout=180,
                check=False)

        def success(result, marker: str):
            if result.returncode != 0 or marker not in result.stdout:
                raise NoGo("Disposable positive PS1 failed: " + marker +
                           " exit=" + str(result.returncode) + " " + result.stderr[-350:])

        def rejected(result, name: str):
            if result.returncode == 0 or "BLOCKED" not in (
                    result.stdout + result.stderr).upper():
                raise NoGo("Unsafe synthetic state did not fail closed: " + name)

        success(invoke(), "READY_FOR_CREATE_ONLY_1.0.4_INSTALL")
        if digest(pointer) != baseline_files["pointer"]:
            raise NoGo("No-Apply installer preflight mutated synthetic pointer")
        success(invoke(apply=True), "INSTALLED_SIDE_BY_SIDE_1.0.4_POINTER_REMAINS_1.0.2")
        newly = product / "versions" / "1.0.4" / "Taraz.exe"
        exact(newly, EXE_SHA)
        if digest(pointer) != baseline_files["pointer"]:
            raise NoGo("Installer changed pointer before activation")
        success(invoke(activate=True), "READY_TO_ACTIVATE_1.0.4_OLD_VERSION_RETAINED")
        success(invoke(activate=True, apply=True),
                "ACTIVATED_1.0.4_VERSION_1.0.2_RETAINED")
        if (pointer.read_text(encoding="utf-8-sig").strip() != "1.0.4"
                or (product / "current-version-pre-1.0.4.txt")
                .read_text(encoding="utf-8-sig").strip() != "1.0.2"
                or (product / "current-version-1.0.4-pending.txt").exists()
                or digest(product / "Run-Taraz-pre-1.0.4.cmd") != baseline_files["launcher"]):
            raise NoGo("Atomic activation pointer/launcher backups inconsistent")
        if (digest(newly) != EXE_SHA or digest(old_bin) != baseline_files["oldExe"]
                or digest(launcher) != baseline_files["launcher"]
                or digest(sentinel) != baseline_files["sentinel"]):
            raise NoGo("Synthetic binary or finance sentinel changed")
        rejected(invoke(activate=True, apply=True), "repeated activation")
        # Restore only the throwaway pointer before negative scenarios.
        pointer.write_bytes(b"1.0.2\r\n")
        (product / "current-version-pre-1.0.4.txt").unlink()
        (product / "Run-Taraz-pre-1.0.4.cmd").unlink()
        # A second install must be create-only and blocked.
        rejected(invoke(apply=True), "preexisting v104 version")
        # New hardlink to original synthetic pointer forces SafePath rejection.
        link = base / "duplicate-pointer-hardlink.txt"
        os.link(pointer, link)
        rejected(invoke(activate=True, apply=True), "hardlink pointer")
        link.unlink()
        rejected(invoke(activate=True, apply=True, mode="running"), "Taraz active")
        rejected(invoke(activate=True, apply=True, mode="cim-fail"), "CIM unavailable")
        # Private junction in a required original version directory; never
        # point at another user's profile or any real installed directory.
        old_folder = old_bin.parent
        private_real = old_folder.parent / "QA_ONLY_ORIGINAL_1.0.2"
        old_folder.rename(private_real)
        creation = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(old_folder), str(private_real)],
            cwd=base, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=30)
        if creation.returncode != 0 or not old_folder.is_junction():
            raise NoGo("Unable to create private NTFS junction negative fixture")
        rejected(invoke(activate=True, apply=True), "junction ancestor")
        if digest(sentinel) != baseline_files["sentinel"]:
            raise NoGo("Finance sentinel mutated by disposable scripts")
    if installed_authority() != original or backup_authority() != backup:
        raise NoGo("Real installed v102 or 181-file cold backup changed")
    return {"subgate": "RC3_DISPOSABLE_INSTALL_ACTIVATION_GO",
            "profile": "temporary synthetic only", "actualPowershell51Used": True,
            "actualNewExeSha256": EXE_SHA, "noFinancialTransactions": True,
            "tests": ["preflight no Apply", "side-by-side Apply",
                      "dry-run activate", "atomic activation Apply",
                      "original pointer backup", "launcher backup",
                      "both executable hashes", "finance sentinel unchanged",
                      "duplicate activation rejected", "duplicate install rejected",
                      "hardlink pointer rejected", "running Taraz rejected",
                      "CIM failure rejected", "junction ancestor rejected"],
            "realInstalledUnchanged": True, "productionReleaseApproved": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=BUILD)
    parser.add_argument("--disposable-test", action="store_true")
    parser.add_argument("--worker26-qa-report", type=Path)
    parser.add_argument("--worker26-qa-sha256", default="")
    parser.add_argument("--use-pinned-worker26-doc", action="store_true",
                        help="Require exact original SHA-pinned worker26 native 20/20 PS5.1 report")
    args = parser.parse_args()
    try:
        outcome = inspect(args.candidate)
        if args.disposable_test:
            if args.use_pinned_worker26_doc:
                if args.worker26_qa_report is not None or args.worker26_qa_sha256:
                    raise NoGo("Specify exactly one independent prior worker26 proof mode")
                outcome["priorWorker26NativeQA"] = prior_worker26_pinned_document()
            else:
                outcome["priorWorker26NativeQA"] = prior_worker26_qa(
                    args.worker26_qa_report, args.worker26_qa_sha256, args.candidate)
            outcome["disposable"] = run_disposable(args.candidate, outcome)
            outcome["installerSyntheticRun"] = True
            outcome["subgate"] = "RC3_STATIC_AND_DISPOSABLE_GO_PRODUCTION_NO_GO"
        print(json.dumps(outcome, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (NoGo, OSError, ValueError, KeyError, TypeError,
            zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print("RC3 INDEPENDENT NO_GO: " + type(error).__name__ + ": " +
              str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
