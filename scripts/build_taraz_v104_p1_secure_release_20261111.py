"""Fail-closed, create-only Windows Taraz v1.0.4 P1 secure release builder.

The builder consumes ONLY the exact 131 independently rehashed source-stage
files. It has no access to production finance data for writes. A native build
requires explicitly pinned *separate* stage QA and staged-Edge QA evidence;
unbuilt source and unauthenticated status claims never grant a release GO.

Default and --preflight are READ-ONLY. Do not invoke --build before both
separate source-stage QA gates have actually passed and evidence is supplied.
The compiled EXE/ZIP is a QA candidate, not approval to install or publish.
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
import sys
import types
import uuid
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_taraz_v103_p1_release_20261111 as legacy
from scripts import taraz_v103_secure_repackage_20261111 as secure

base = legacy.base
BuildBlocked = base.BuildBlocked
VERSION = "1.0.4"
BASE_VERSION = "1.0.2"
BASE_SHA = "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52"
V103_FROZEN_SOURCE_SHA = "a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279"
V103_EXE_SHA = "e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c"
V103_UI_SHA = "001e9e7e622fee9cc375461b754847a978c0b16563a72a4cd8e5d784ca8512b4"
OUTPUT = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.4-p1"
STAGE = OUTPUT / "source-stage-959986753b61"
STAGE_SHA = "6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1"
STAGE_INVENTORY_FILE_SHA = "12f54656851c65e981d6bf20bb86952029d57ef79081d26c5dde51d6565f1add"
COUNT = 131
PATCHED = frozenset({
    "src/accounting_action_home.jsx",
    "src/parsian_raw_archive_explorer.jsx",
    "src/personal_parsian_bank_movements.jsx",
    "src/personal_parsian_company.jsx",
    "src/personal_parsian_dashboard.jsx",
    "src/personal_parsian_extended.jsx",
    "src/personal_parsian_invoices.jsx",
    "src/provider_csv_migration.jsx",
    "src/taraz_home_command.jsx",
})
ORIGINAL_FROZEN_INVENTORY = (
    secure.FROZEN_OFFLINE / "source-sha256.json"
)
BACKUP = ROOT.parents[1] / "MTR-REAL-UPGRADE-BACKUPS-20261110" / "taraz-v103-cold-20261111"
BACKUP_MANIFEST_SHA = "8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d"
BACKUP_REPORT_SHA = "68bb6e26b9a9a10818e6752a7cc1475a3861c5f380f2021eb5c112a74cd7d2c9"
NATIVE_MODULES = legacy.PYZ_MODULES
MAX_SOURCE_BYTES = 30 * 1024 * 1024
MAX_REPORT_BYTES = 1_000_000
MAX_EXE_BYTES = 80 * 1024 * 1024


def _regular(path: Path, *, folder: bool = False, cap: int = MAX_SOURCE_BYTES) -> Path:
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and
                 getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
            raise BuildBlocked("Linked or reparse path refused: " + str(part))
    if folder:
        if not path.is_dir():
            raise BuildBlocked("Required directory missing: " + str(path))
    elif not path.is_file() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > cap:
        raise BuildBlocked("Required regular file missing or oversized: " + str(path))
    return path


def _sha(path: Path, *, cap: int = MAX_SOURCE_BYTES) -> str:
    _regular(path, cap=cap)
    result = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            result.update(part)
    return result.hexdigest()


def _json(path: Path, cap: int = MAX_REPORT_BYTES) -> dict:
    _regular(path, cap=cap)
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise BuildBlocked("Required JSON object missing: " + str(path))
    return value


def _rel(name: str) -> Path:
    if (not isinstance(name, str) or not name or name.startswith("/")
            or any(x in name for x in ("\\", ":", "*", "?", "//"))):
        raise BuildBlocked("Unsafe snapshot-relative name")
    parts = PurePosixPath(name).parts
    if any(item in ("", ".", "..") for item in parts):
        raise BuildBlocked("Snapshot relative path traversal")
    return Path(*parts)


def inventory_sha(items: dict[str, str]) -> str:
    if not all(isinstance(k, str) and re.fullmatch("[0-9a-f]{64}", str(v)) for k, v in items.items()):
        raise BuildBlocked("Noncanonical SHA inventory")
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode("utf-8")).hexdigest()


def source_preflight(stage: Path = STAGE, *, expected_sha: str = STAGE_SHA) -> dict:
    """Verify 131 input *file bytes*, not just producer report or map digest."""
    _regular(stage, folder=True)
    if stage != STAGE:
        raise BuildBlocked("Only the exact pinned v104 applied-source-stage is authorized")
    mf = stage / "patched-source-sha256.json"
    report_file = stage / "stage-report.json"
    source = stage / "source"
    _regular(source, folder=True)
    if _sha(mf) != STAGE_INVENTORY_FILE_SHA:
        raise BuildBlocked("Applied source-stage inventory file SHA changed")
    records = _json(mf)
    if len(records) != COUNT or inventory_sha(records) != expected_sha:
        raise BuildBlocked("131-source fingerprint differs from pinned applied stage")
    produced = _json(report_file)
    if not (
        produced.get("sourceCount") == COUNT
        and produced.get("patchedSourceSha256") == expected_sha
        and produced.get("patchedInventoryFileSha256") == STAGE_INVENTORY_FILE_SHA
        and produced.get("frozenStartingSha256") == V103_FROZEN_SOURCE_SHA
        and produced.get("status") in (
            "V104_PATCHED_SOURCE_FROZEN_QA_PENDING_NO_EXE",
            "V104_PATCHED_SOURCE_QA_VERIFIED_NO_EXE")
        and produced.get("targetVersion") == VERSION
        and produced.get("editedSourceFileCount") == len(PATCHED)
        and set(produced.get("editedSourceFiles", [])) == PATCHED
        and produced.get("executableBuilt") is False
        and produced.get("baseVersionFieldsUnchanged") is True
    ):
        raise BuildBlocked("Applied stage provenance/report differs")
    original = _json(ORIGINAL_FROZEN_INVENTORY)
    if len(original) != COUNT or inventory_sha(original) != V103_FROZEN_SOURCE_SHA:
        raise BuildBlocked("Original v103 frozen inputs do not match source")
    if records.keys() != original.keys():
        raise BuildBlocked("Applied 131-file source membership drift")
    actually_changed = {name for name in records if records[name] != original[name]}
    if actually_changed != PATCHED:
        raise BuildBlocked("Expected exactly nine sourced JSX redaction file changes")
    seen: set[str] = set()
    for name, digest in records.items():
        relative = _rel(name)
        file = source / relative
        if _sha(file) != digest:
            raise BuildBlocked("Actual staged file byte SHA mismatch: " + name)
        seen.add(relative.as_posix())
    extra: set[str] = set()
    for parent, dirs, files in os.walk(source, followlinks=False):
        for dirname in dirs:
            _regular(Path(parent) / dirname, folder=True)
        for filename in files:
            file = _regular(Path(parent) / filename)
            extra.add(file.relative_to(source).as_posix())
    if extra != seen:
        raise BuildBlocked("Source snapshot has unlisted or missing file")
    pkg = _json(source / "package.json")
    lock = _json(source / "package-lock.json")
    if (pkg.get("name") != "taraz-accounting"
            or lock.get("name") != "taraz-accounting"):
        raise BuildBlocked("Source package name mismatch")
    if [pkg.get("version"), lock.get("version"),
        lock.get("packages", {}).get("", {}).get("version")] != ["1.0.0"] * 3:
        raise BuildBlocked("Source version must remain 1.0.0 until detached staging")
    return {
        "stage": str(stage), "source": str(source), "sourceCount": COUNT,
        "sourceSha256": inventory_sha(records),
        "inventoryFileSha256": _sha(mf), "stageReportSha256": _sha(report_file),
        "editedSourceFiles": sorted(actually_changed), "snapshot": records,
        "status": produced["status"], "compiledExecutableExists": False,
    }


def _approved_qa_report(path: Path, pin: str, kind: str, stage: dict) -> dict:
    """Fail closed unless an explicitly selected, SHA-pinned external QA report passed.

    The report must be *separate* from stage-report.json; neither writing a
    source-stage file nor blindly claiming 'PASS' constitutes an audit.
    """
    if not path or not re.fullmatch("[0-9a-f]{64}", pin or ""):
        raise BuildBlocked("Explicit SHA-pinned " + kind + " QA evidence required")
    file = _regular(path, cap=MAX_REPORT_BYTES)
    if file == STAGE / "stage-report.json" or file == STAGE / "patched-source-sha256.json":
        raise BuildBlocked("Producer stage metadata is not independent QA")
    if _sha(file) != pin:
        raise BuildBlocked(kind + " QA report SHA differs from explicitly selected pin")
    data = _json(file)
    if not (
        data.get("kind") == kind
        and data.get("status") == "PASS"
        and data.get("sourceStage") == stage["stage"]
        and data.get("sourceSha256") == stage["sourceSha256"]
        and data.get("sourceCount") == COUNT
        and data.get("failures") == 0
        and isinstance(data.get("checksPassed"), int)
        and data["checksPassed"] > 0
    ):
        raise BuildBlocked(kind + " QA report missing independent PASS/source proof")
    return {"kind": kind, "path": str(file), "reportSha256": pin,
            "checksPassed": data["checksPassed"]}


def approved_build_inputs(stage: Path, source_sha: str, stage_qa: Path | None,
                          stage_qa_sha: str, edge_qa: Path | None,
                          edge_qa_sha: str) -> dict:
    if source_sha != STAGE_SHA:
        raise BuildBlocked("Prime-approved exact applied-stage SHA required")
    proof = source_preflight(stage, expected_sha=source_sha)
    qa_stage = _approved_qa_report(stage_qa, stage_qa_sha, "applied-source-stage", proof)
    qa_edge = _approved_qa_report(edge_qa, edge_qa_sha, "staged-edge-redaction", proof)
    return {"stage": proof, "stageQA": qa_stage, "stagedEdgeQA": qa_edge}


def stage_version(snapshot: Path) -> dict[str, str]:
    """Add v1.0.4 markers ONLY to the new build snapshot (not staged source)."""
    package = snapshot / "package.json"
    lock = snapshot / "package-lock.json"
    p, l = _json(package), _json(lock)
    if (p.get("name") != "taraz-accounting" or l.get("name") != "taraz-accounting"
            or [p.get("version"), l.get("version"),
                l.get("packages", {}).get("", {}).get("version")] != ["1.0.0"] * 3):
        raise BuildBlocked("Unexpected source package version before staging")
    p["version"] = l["version"] = l["packages"][""]["version"] = VERSION
    package.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lock.write_text(json.dumps(l, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    module = snapshot / "taraz_release_version.py"
    if module.exists():
        raise BuildBlocked("Refuse overwrite existing staged release-version module")
    module.write_text('"""Taraz v1.0.4 non-QA offline version."""\n'
                      'APP_VERSION = "1.0.4"\nQA_ONLY = False\n'
                      'BUILD_CHANNEL = "offline-production-candidate"\n', encoding="utf-8")
    entry = snapshot / "taraz_desktop.py"
    original = entry.read_text(encoding="utf-8")
    anchor = "from __future__ import annotations\n"
    if (original.count(anchor) != 1 or "_taraz_qa_launch_gate" in original
            or "taraz_release_version" in original or "TARAZ_QA_RUN_ROOT" in original):
        raise BuildBlocked("Unexpected native entry QA/version instrumented source")
    entry.write_text(original.replace(anchor, anchor +
                     '\nfrom taraz_release_version import APP_VERSION as _taraz_app_version\n'
                     'if _taraz_app_version != "1.0.4":\n'
                     '    raise RuntimeError("Taraz 1.0.4 version mismatch")\n', 1),
                     encoding="utf-8")
    return {"packageSha256": _sha(package), "lockSha256": _sha(lock),
            "versionModuleSha256": _sha(module), "nativeEntrySha256": _sha(entry)}


def pe_resource(path: Path) -> None:
    """Reuse v102 verified PE fixture, replacing only strict version markers."""
    legacy.v102.pe_version_file(path)
    original = path.read_text(encoding="utf-8")
    if original.count("1,0,2,0") != 2 or original.count("1.0.2.0") != 2:
        raise BuildBlocked("Unexpected original PE version resource template")
    path.write_text(original.replace("1,0,2,0", "1,0,4,0").replace("1.0.2.0", "1.0.4.0"),
                    encoding="utf-8")


def _assigned_constant(code: types.CodeType, variable: str):
    instructions = list(dis.get_instructions(code))
    for i in range(1, len(instructions)):
        if (instructions[i].opname in ("STORE_NAME", "STORE_GLOBAL")
                and instructions[i].argval == variable
                and instructions[i - 1].opname == "LOAD_CONST"):
            return instructions[i - 1].argval
    raise BuildBlocked("Missing exact PYZ release assignment: " + variable)


def inspect_binary(exe: Path, dist: Path) -> dict:
    """Inspect the *actual* native PE, PYZ and embedded UI bytes. No EXE launch."""
    from PyInstaller.archive.readers import CArchiveReader
    from scripts.qa_mtr_taraz_build_20261110 import _code_strings
    from scripts.qa_taraz_v103_independent_acceptance_20261111 import pe_fixed_version

    _regular(exe, cap=MAX_EXE_BYTES)
    pe = pe_fixed_version(exe)
    if pe != "1.0.4.0":
        raise BuildBlocked("Actual PE resource differs from 1.0.4.0: " + pe)
    carchive = CArchiveReader(str(exe))
    pyz = carchive.open_embedded_archive("PYZ.pyz")
    release = pyz.extract("taraz_release_version")
    if (not isinstance(release, types.CodeType)
            or _assigned_constant(release, "APP_VERSION") != VERSION
            or _assigned_constant(release, "QA_ONLY") is not False
            or _assigned_constant(release, "BUILD_CHANNEL") != "offline-production-candidate"):
        raise BuildBlocked("Frozen release PYZ is QA-only or not v1.0.4")
    entry_blob = carchive.extract("taraz_desktop")
    if not isinstance(entry_blob, bytes):
        raise BuildBlocked("Missing frozen native entrypoint")
    try:
        entry = marshal.loads(entry_blob)
    except (TypeError, ValueError, EOFError) as exc:
        raise BuildBlocked("Frozen entrypoint marshal corrupt") from exc
    if not isinstance(entry, types.CodeType):
        raise BuildBlocked("Entry payload is not code")
    required = set(legacy.v102.REQUIRED_NATIVE)
    native_methods = base.methods(entry)
    if not required <= native_methods or "_taraz_qa_launch_gate" in native_methods:
        raise BuildBlocked("Frozen native entry Madar interfaces absent or QA-only")
    bridge = pyz.extract("standalone_accounting_desktop")
    if not isinstance(bridge, types.CodeType):
        raise BuildBlocked("Frozen WebView2 bridge absent")
    forwarders = [value for value in _code_strings(bridge)
                  if "window.madar = Object.fromEntries(" in value]
    if len(forwarders) != 1 or not all("'" + name + "'" in forwarders[0] for name in required):
        raise BuildBlocked("Native WebView2 bridge allowlist changed")
    for name, needed in NATIVE_MODULES.items():
        code = pyz.extract(name)
        if not isinstance(code, types.CodeType) or not needed <= base.methods(code):
            raise BuildBlocked("Missing expected PYZ module: " + name)
    mapping = {name.replace("\\", "/"): name for name in carchive.toc}
    embedded, js = {}, {}
    for path in sorted(dist.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(dist).as_posix()
        member = mapping.get("dist/" + relative)
        if not member:
            raise BuildBlocked("Compiled asset not embedded in EXE: " + relative)
        buffer = carchive.extract(member)
        checksum = _sha(path)
        if not isinstance(buffer, bytes) or hashlib.sha256(buffer).hexdigest() != checksum:
            raise BuildBlocked("Frozen exe embedded UI differs: " + relative)
        embedded[relative] = checksum
        if relative.endswith(".js"):
            js[relative] = checksum
    if not js or any(value == V103_UI_SHA for value in js.values()) or _sha(exe, cap=MAX_EXE_BYTES) == V103_EXE_SHA:
        raise BuildBlocked("Compiled v1.0.4 shares forbidden frozen v1.0.3 EXE/JS bytes")
    html = (dist / "accounting.html").read_text(encoding="utf-8")
    if ("assets/" not in html or not any(b"taraz-madar-dashboard" in (dist / name).read_bytes()
                                      for name in js)):
        raise BuildBlocked("Expected actual production UI entrypoint missing")
    return {"peVersion": pe, "pyzVersion": VERSION, "nonQaRuntime": True,
            "nativeMethods": sorted(required), "bridgeForwarded": True,
            "nativeModuleMethods": {key: sorted(value) for key, value in NATIVE_MODULES.items()},
            "uiAssetsSha256": embedded, "compiledJsSha256": js,
            "compiledUiMatchesFrozenExe": True,
            "compiledRedactionEdgeApproved": False, "installedGuiTested": False}


def secure_installation_scripts(exe_sha: str, source_sha: str = STAGE_SHA) -> dict[str, str]:
    """Reuse tested Win32 hardlink/junction guards, but with EVERY v104 pin/name.

    No v103 rollback script, original v103 manifest, or old frozen script body
    is packaged into the new v104 ZIP. The v102 baseline remains intentional.
    """
    if not re.fullmatch("[0-9a-f]{64}", exe_sha or "") or exe_sha == V103_EXE_SHA:
        raise BuildBlocked("New v104 native EXE SHA must be a new pinned value")
    if source_sha != STAGE_SHA:
        raise BuildBlocked("Unknown v104 source freeze for secure PowerShell scripts")
    if not all((hasattr(secure, name) for name in
                ("_SECURE_GUARDS", "_SECURE_BACKUP", "_INSTALL_TAIL", "_ACTIVATE_TAIL"))):
        raise BuildBlocked("Reviewed v103 Win32 security templates unavailable")
    header = (
        "$ErrorActionPreference='Stop'\n"
        "function Deny([string]$reason) { throw ('TARAZ V104 SECURE UPDATE BLOCKED: ' + $reason) }\n"
    )
    ancestor = secure._SECURE_GUARDS
    ancestor = ancestor.replace(
        "m.secureRepackage.originalManifestSha256",
        "m.secureRepackage.sourceStageInventorySha256")
    security = (
        ancestor + "\n" + secure._SECURE_BACKUP + "\n"
        + "function CheckNoTaraz {\n"
        + "try { $processes=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.Name -match '^Taraz(?:-v[0-9.]+.*)?\\.exe$' }) }\n"
        + "catch { Deny 'Cannot establish Taraz process inactivity' }\n"
        + "if($processes.Count -gt 0) { Deny 'Taraz is running' }\n}\n"
    )
    parameters = {
        "Install-Taraz-V104.ps1":
            "param([switch]$Apply,[switch]$VerifyExisting,[string]$BackupRoot='',"
            "[string]$BackupManifestSha256='', [string]$BackupReportSha256='')\n",
        "Activate-Taraz-V104.ps1":
            "param([switch]$Apply,[string]$BackupRoot='',"
            "[string]$BackupManifestSha256='', [string]$BackupReportSha256='')\n",
    }
    values: dict[str, str] = {}
    for name, tail in (
        ("Install-Taraz-V104.ps1", secure._INSTALL_TAIL),
        ("Activate-Taraz-V104.ps1", secure._ACTIVATE_TAIL),
    ):
        script = parameters[name] + header + security + "\n" + tail
        script = script.replace("TarazV103", "TarazV104")
        script = script.replace("V103", "V104").replace("v103", "v104")
        script = script.replace("1.0.3", VERSION)
        for needle, replacement in {
            "__NEW_SHA__": exe_sha,
            "__OLD_SHA__": BASE_SHA,
            "__FREEZE_SHA__": source_sha,
            "__ORIGINAL_MANIFEST_SHA__": STAGE_INVENTORY_FILE_SHA,
        }.items():
            script = script.replace(needle, replacement)
        if (re.search("__[A-Z_]+__", script) or
                "1.0.3" in script or "V103" in script or "v103" in script or
                "$item=$item.Parent" in script or
                "Start-Process" in script or
                "TarazV104SecureLinkInfo" not in script):
            raise BuildBlocked("Unresolved/unsafe v103 reference in secure v104 script")
        values[name] = script
    assert "[IO.File]::Replace($pending,$pointer,$oldPointer,$true)" in values["Activate-Taraz-V104.ps1"]
    assert "Run-Taraz-pre-1.0.4.cmd" in values["Activate-Taraz-V104.ps1"]
    assert "Install-Taraz-V104.ps1" in values["Activate-Taraz-V104.ps1"]
    return values


def installed_preflight() -> dict:
    """Read-only installed v102 pin and future v104 absence; never launch."""
    from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import no_active_taraz

    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise BuildBlocked("Windows with installed v102 baseline required")
    no_active_taraz()
    root = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz"
    pointer, launcher = root / "current-version.txt", root / "Run-Taraz.cmd"
    exe = root / "versions" / BASE_VERSION / "Taraz.exe"
    future = root / "versions" / VERSION
    for item in (root, pointer, launcher, exe, future):
        base.refuse_links(item)
    if not (root.is_dir() and pointer.is_file() and launcher.is_file() and exe.is_file()):
        raise BuildBlocked("Installed v1.0.2 baseline paths missing")
    if pointer.read_text(encoding="utf-8-sig").strip() != BASE_VERSION:
        raise BuildBlocked("Installed pointer is not v1.0.2")
    if _sha(exe, cap=MAX_EXE_BYTES) != BASE_SHA:
        raise BuildBlocked("Installed v1.0.2 binary SHA changed")
    if "versions\\%TARAZ_VERSION%\\Taraz.exe" not in launcher.read_text(
            encoding="utf-8", errors="replace"):
        raise BuildBlocked("Installed launcher contract changed")
    if future.exists():
        raise BuildBlocked("v1.0.4 installed version folder already exists")
    return {
        "version": BASE_VERSION, "exeSha256": BASE_SHA, "root": str(root),
        "pointerSha256": _sha(pointer), "launcherSha256": _sha(launcher),
        "futureFolderAbsent": True,
    }


def stage_vite_preflight(stage: dict, *, vite_dir: Path,
                        expected_js_sha: str) -> dict:
    """Independent byte check of worker29 detached Vite QA snapshot."""
    if not re.fullmatch("[0-9a-f]{64}", expected_js_sha or ""):
        raise BuildBlocked("Exact pinned Vite JS SHA required")
    _regular(vite_dir, folder=True)
    if (vite_dir.parent != OUTPUT or
            not re.fullmatch(r"vite-qa-[a-z0-9]+", vite_dir.name)):
        raise BuildBlocked("Vite QA directory must be direct v104 child")
    report_file = vite_dir / "vite-qa-report.json"
    manifest = _json(report_file)
    if not (
        manifest.get("status") == "STAGE_UI_ONLY"
        and manifest.get("compiledFrontend") is True
        and manifest.get("compiledExeBuilt") is False
        and manifest.get("compiledBundleReleaseReady") is False
        and manifest.get("installedTarazTouched") is False
        and manifest.get("sourceShaBeforeAfterIdentical") is True
        and manifest.get("patchedSourceSha256") == stage["sourceSha256"]
        and manifest.get("sourceStagePath") == stage["stage"]
        and manifest.get("sourceStageReportSha256") == stage["stageReportSha256"]
        and manifest.get("sourceInventorySha256") == stage["inventoryFileSha256"]
        and manifest.get("viteJsSha256") == expected_js_sha
        and manifest.get("browserQaVerified") is False
    ):
        raise BuildBlocked("Detached Vite artifact claimed state/source differs")
    actual = {}
    for field, sha_field in (
        ("jsRelativePath", "viteJsSha256"),
        ("cssRelativePath", "viteCssSha256"),
        ("htmlRelativePath", "viteHtmlSha256"),
    ):
        relative = _rel(manifest.get(field))
        source = vite_dir / relative
        if not relative.parts or relative.parts[0] != "dist":
            raise BuildBlocked("Vite QA asset outside isolated dist")
        digest = _sha(source)
        if digest != manifest.get(sha_field):
            raise BuildBlocked("Vite QA actual asset SHA mismatch: " + field)
        actual[field] = {"relative": relative.as_posix(), "sha256": digest}
    return {"root": str(vite_dir), "reportSha256": _sha(report_file),
            "ui": actual, "jsSha256": expected_js_sha}


def package_secure_update(run: Path, exe: Path, expected_source: dict,
                          staged: dict, observed: dict, baseline: dict,
                          source_proof: dict, qa: dict, vite: dict) -> dict:
    """Seven-member secure ZIP, SHA pins and no copied v103 rollback/script."""
    exe_sha = _sha(exe, cap=MAX_EXE_BYTES)
    if exe_sha == V103_EXE_SHA or observed.get("peVersion") != "1.0.4.0":
        raise BuildBlocked("Old native executable accidentally supplied to v104 package")
    package = run / "offline-update"
    package.mkdir(exist_ok=False)
    payload = package / "Taraz.exe"
    with exe.open("rb") as src, payload.open("xb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
    if _sha(payload, cap=MAX_EXE_BYTES) != exe_sha:
        raise BuildBlocked("v104 payload copy SHA not equal to compiled EXE")
    ps = secure_installation_scripts(exe_sha, source_proof["sourceSha256"])
    for name, body in ps.items():
        with (package / name).open("x", encoding="utf-8", newline="\n") as file:
            file.write(body)
    for name in ("package.json", "package-lock.json"):
        with (run / "source" / name).open("rb") as src, (package / name).open("xb") as dst:
            shutil.copyfileobj(src, dst)
    inventory_file = package / "source-sha256.json"
    with inventory_file.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(expected_source, file, sort_keys=True, indent=2)
        file.write("\n")
    manifest = {
        "schemaVersion": 1, "application": "Taraz", "targetVersion": VERSION,
        "installedBaselineVersion": BASE_VERSION, "installedBaselineSha256": BASE_SHA,
        "qaOnly": False, "productionCandidate": True, "unsigned": True,
        "installed": False, "pointerActivated": False, "activationApprovalGranted": False,
        "realLedgerModified": False, "financePostingProven": False,
        "installedGuiTested": False, "compiledEdgeRedactionApproved": False,
        "previousVersionRetained": BASE_VERSION, "freshIndependentBackupRequired": True,
        "freshIndependentBackupVerified": False,
        "defaultDataRoot": "%APPDATA%\\Taraz",
        "launcherContract": "versions\\%TARAZ_VERSION%\\Taraz.exe",
        "exeSha256": exe_sha, "exeBytes": exe.stat().st_size,
        "peVersion": observed["peVersion"], "pyzVersion": observed["pyzVersion"],
        "sourceSnapshotSha256": source_proof["sourceSha256"],
        "sourceFilesCount": len(expected_source),
        "sourceFileManifestSha256": _sha(inventory_file),
        "stagedVersionSourceSha256": staged,
        "stagedPackageSha256": _sha(package / "package.json"),
        "stagedLockSha256": _sha(package / "package-lock.json"),
        "compiledEvidence": observed, "installedBaseline": baseline,
        "installScriptSha256": _sha(package / "Install-Taraz-V104.ps1"),
        "activationScriptSha256": _sha(package / "Activate-Taraz-V104.ps1"),
        "secureRepackage": {
            "schemaVersion": 1,
            "sourceStageInventorySha256": STAGE_INVENTORY_FILE_SHA,
            "sourceStageReportSha256": source_proof["stageReportSha256"],
            "sourceStagePath": source_proof["stage"], "hardlinkAndAncestorGuard":
                "Win32-linkcount-and-each-ancestor",
            "launcherBackupName": "Run-Taraz-pre-1.0.4.cmd",
            "pathPolicy": "local-absolute-no-reparse-no-hardlinks",
            "stageQA": qa["stageQA"], "stagedEdgeQA": qa["stagedEdgeQA"],
            "viteStage": vite,
            "rollbackIncluded": False,
            "rollbackReason": "v103 rollback hashes cannot apply to new v104 EXE",
            "productionApproved": False,
        },
    }
    manifest_file = package / "update-manifest.json"
    with manifest_file.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(manifest, file, ensure_ascii=True, sort_keys=True, indent=2)
        file.write("\n")
    archive = run / "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in sorted(package.iterdir()):
            z.write(file, file.name)
    unpacked = {file.name: _sha(file, cap=MAX_EXE_BYTES) for file in package.iterdir()}
    expected_members = {
        "Taraz.exe", "Install-Taraz-V104.ps1", "Activate-Taraz-V104.ps1",
        "package.json", "package-lock.json", "source-sha256.json",
        "update-manifest.json",
    }
    if set(unpacked) != expected_members:
        raise BuildBlocked("Unexpected secure v104 ZIP membership")
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        if len(members) != len(expected_members) or set(z.namelist()) != expected_members:
            raise BuildBlocked("Secure v104 ZIP missing/duplicate/unexpected entries")
        for member in members:
            if (member.is_dir() or member.file_size > MAX_EXE_BYTES
                    or hashlib.sha256(z.read(member.filename)).hexdigest()
                    != unpacked[member.filename]):
                raise BuildBlocked("Secure v104 ZIP member bytes changed")
    return {
        "exe": str(exe), "exeSha256": exe_sha, "zip": str(archive),
        "zipSha256": _sha(archive, cap=MAX_EXE_BYTES),
        "manifest": str(manifest_file), "manifestSha256": _sha(manifest_file),
        "installScript": str(package / "Install-Taraz-V104.ps1"),
        "installScriptSha256": unpacked["Install-Taraz-V104.ps1"],
        "activationScript": str(package / "Activate-Taraz-V104.ps1"),
        "activationScriptSha256": unpacked["Activate-Taraz-V104.ps1"],
    }


def build(*, stage: Path = STAGE, expected_sha: str, stage_qa: Path,
          stage_qa_sha: str, edge_qa: Path, edge_qa_sha: str,
          vite_dir: Path, vite_js_sha: str) -> Path:
    """Create isolated candidate AFTER independent stage/source and Edge gates."""
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise BuildBlocked("Native Windows Python 3.12 required")
    proof = approved_build_inputs(stage, expected_sha, stage_qa, stage_qa_sha,
                                  edge_qa, edge_qa_sha)
    source_proof = proof["stage"]
    vite = stage_vite_preflight(source_proof, vite_dir=vite_dir,
                               expected_js_sha=vite_js_sha)
    baseline = installed_preflight()
    _regular(OUTPUT, folder=True)
    run = OUTPUT / ("build-" + uuid.uuid4().hex[:12])
    run.mkdir(exist_ok=False)
    report_path = run / "build-report.json"
    report = {
        "status": "IN_PROGRESS", "version": VERSION, "output": str(run),
        "sourceFreezeSha256": expected_sha, "sourceFileCount": COUNT,
        "sourceStagePath": str(stage), "sourceStageReportSha256":
            source_proof["stageReportSha256"],
        "installed": False, "pointerChanged": False, "realLedgerModified": False,
        "stagedRedactionApproved": True, "compiledRedactionApproved": False,
        "releaseApproved": False,
    }
    try:
        expected = source_proof["snapshot"]
        snapshot = run / "source"
        base.snapshot_source(Path(source_proof["source"]), snapshot, expected)
        staged = stage_version(snapshot)
        from scripts.qa_mtr_taraz_build_20261110 import _trusted_modules, _safe_copytree
        _safe_copytree(_trusted_modules(), snapshot / "node_modules")
        environment = base.offline_environment(run)
        dist = run / "web" / "dist"
        dist.parent.mkdir()
        base.run_command(
            [shutil.which("node") or "node",
             str(snapshot / "node_modules" / "vite" / "bin" / "vite.js"),
             "build", "--config", str(snapshot / "vite.config.js"),
             "--outDir", str(dist), "--emptyOutDir"],
            cwd=snapshot, env=environment,
            log=run / "vite-build.log", timeout=240,
        )
        if not (dist / "accounting.html").is_file():
            raise BuildBlocked("Vite v104 production accounting.html absent")
        # Fail closed if newly compiled JS diverges from already QA-pinned Vite.
        for item in vite["ui"].values():
            name = item["relative"].removeprefix("dist/")
            compiled_file = dist / _rel(name)
            if _sha(compiled_file) != item["sha256"]:
                raise BuildBlocked("Native build Vite JS/CSS/HTML differs from staged Edge QA " + name)
        resource = run / "taraz-v104-pe-version.txt"
        pe_resource(resource)
        binary = run / "binary"
        binary.mkdir()
        base.run_command(
            [sys.executable, "-B", "-m", "PyInstaller", "--onefile", "--windowed",
             "--noconfirm", "--version-file", str(resource), "--name", "Taraz",
             "--hidden-import", "taraz_madar_data_reader",
             "--hidden-import", "standalone_accounting_template_store",
             "--hidden-import", "taraz_integration",
             "--hidden-import", "personal_parsian_bridge",
             "--hidden-import", "standalone_accounting_auto_backup",
             "--icon", str(snapshot / "assets" / "taraz.ico"),
             "--add-data", str(dist) + ";dist", "--distpath", str(binary),
             "--workpath", str(run / "pyinstaller" / "work"),
             "--specpath", str(run / "pyinstaller" / "spec"),
             "--paths", str(snapshot), str(snapshot / "taraz_desktop.py")],
            cwd=snapshot, env=environment,
            log=run / "pyinstaller-build.log", timeout=780,
        )
        executable = binary / "Taraz.exe"
        _regular(executable, cap=MAX_EXE_BYTES)
        evidence = inspect_binary(executable, dist)
        if source_preflight(stage)["sourceSha256"] != expected_sha:
            raise BuildBlocked("Source-stage actual bytes changed during native build")
        if installed_preflight() != baseline:
            raise BuildBlocked("Installed baseline drift during isolated build")
        packed = package_secure_update(
            run, executable, expected, staged, evidence, baseline,
            source_proof, proof, vite)
        report.update({
            "status": "PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED",
            "compiled": evidence, "baseline": baseline,
            "staged": staged, "sourceStageQA": proof["stageQA"],
            "stagedEdgeQA": proof["stagedEdgeQA"],
            "viteStage": vite, "freshIndependentBackupVerified": False,
            **packed,
        })
    except Exception as error:
        report.update({"status": "BLOCKED", "errorType": type(error).__name__,
                       "error": str(error)})
        report_path.write_text(json.dumps(report, sort_keys=True, ensure_ascii=True, indent=2) + "\n",
                               encoding="utf-8")
        raise
    report_path.write_text(json.dumps(report, sort_keys=True, ensure_ascii=True, indent=2) + "\n",
                           encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true",
                        help="read-only SHA inventory validation; NOT an approval")
    parser.add_argument("--build", action="store_true",
                        help="create-only build; must provide explicit independent QA pins")
    parser.add_argument("--stage", type=Path, default=STAGE)
    parser.add_argument("--frozen-sha", default="")
    parser.add_argument("--stage-qa", type=Path)
    parser.add_argument("--stage-qa-sha", default="")
    parser.add_argument("--edge-qa", type=Path)
    parser.add_argument("--edge-qa-sha", default="")
    parser.add_argument("--vite-dir", type=Path)
    parser.add_argument("--vite-js-sha", default="")
    args = parser.parse_args()
    try:
        if args.build:
            result = build(
                stage=args.stage, expected_sha=args.frozen_sha,
                stage_qa=args.stage_qa, stage_qa_sha=args.stage_qa_sha,
                edge_qa=args.edge_qa, edge_qa_sha=args.edge_qa_sha,
                vite_dir=args.vite_dir, vite_js_sha=args.vite_js_sha,
            )
            print(json.dumps(_json(result), sort_keys=True, ensure_ascii=True, indent=2))
            return 0
        proof = source_preflight(args.stage)
        summary = {key: val for key, val in proof.items() if key != "snapshot"}
        summary["candidateBuildAuthorized"] = False
        summary["independentStageQA"] = "NOT_SUPPLIED"
        summary["independentStagedEdgeQA"] = "NOT_SUPPLIED"
        print(json.dumps(summary, sort_keys=True, ensure_ascii=True, indent=2))
        return 0
    except (BuildBlocked, OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print("TARAZ V104 CREATE-ONLY BUILD BLOCKED: " +
              type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

