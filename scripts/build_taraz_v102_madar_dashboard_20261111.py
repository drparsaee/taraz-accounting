"""Create-only, non-QA Taraz 1.0.2 installer with a visible Madar dashboard.

Default invocation only verifies prerequisites. Real builds require a caller-
supplied SHA-256 freeze of the ENTIRE runtime source input inventory, after the
frontend and backend owners have both finished and stopped editing. The script
never installs or switches the real Taraz launcher.
"""
from __future__ import annotations

import hashlib
import json
import marshal
import os
from pathlib import Path
import shutil
import sys
import types
import uuid
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_taraz_v101_local_update_20261110 as previous

BuildBlocked = previous.BuildBlocked
SOURCE = ROOT
PARENT = SOURCE.parents[1]
OUTPUT = PARENT / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.2-madar-dashboard"
BACKUP = PARENT / "MTR-REAL-UPGRADE-BACKUPS-20261110" / "taraz-v102-cold-20261111"
EXPECTED_BACKUP_SHA = "0817ffeb5178767c292e64e5b73db4814665b67e8465a829c3ffb254fa924767"
EXPECTED_BACKUP_REPORT_SHA = "f7f5ae2915ccafd3eb16c6809c11cd3fb5fee8288ba7bbaedc3e0257803bcf77"
EXPECTED_INSTALLED_SHA = "5b5a550f3b95cda8352f757cd9e61d44a62531e0e4dfe0fc6d586a0d6a452d4b"
EXPECTED_BACKUP_FILES = 181
EXPECTED_BACKUP_BYTES = 124011875
EXPECTED_SQLITE_CHECKS = 67
BASE_VERSION = "1.0.1"
NEXT_VERSION = "1.0.2"
REQUIRED_NATIVE = {
    "tarazMadarDataOverview", "tarazMadarDataRead",
    "tarazIntegrationList", "tarazIntegrationReview", "tarazIntegrationRecover",
}
REQUIRED_READER = {
    "MadarReadError", "local_madar_available", "read_local_madar_state",
    "read_authorized_madar_state", "_network_config", "_validate_paging",
}
REQUIRED_FRONTEND = (
    b"taraz-madar-dashboard", b"tarazMadarDataRead",
    b"invoiceDesign", b"taraz-feedback-host",
    "\u0627\u0637\u0644\u0627\u0639\u0627\u062a \u0645\u062f\u0627\u0631".encode("utf-8"),
)


def source_inventory() -> dict[str, str]:
    expected = previous.source_hashes(SOURCE)
    for rel in (
        "taraz_desktop.py", "standalone_accounting_desktop.py",
        "taraz_madar_data_reader.py", "src/taraz_madar_dashboard.jsx",
        "src/taraz_madar_dashboard.css", "src/standalone_accounting_workspace.jsx",
        "src/accounting_top_ribbon.jsx", "package.json", "package-lock.json",
    ):
        if rel not in expected:
            raise BuildBlocked("Expected dashboard runtime source missing: " + rel)
    source_text = (SOURCE / "src" / "taraz_madar_dashboard.jsx").read_text(encoding="utf-8")
    if ("MadarDataExplorer" not in source_text or "tarazMadarDataRead" not in source_text
            or "TarazMadarDashboard" not in source_text):
        raise BuildBlocked("Madar dashboard full-data explorer source is unfinished")
    api = (SOURCE / "taraz_desktop.py").read_text(encoding="utf-8")
    if any(("def " + name + "(") not in api for name in REQUIRED_NATIVE):
        raise BuildBlocked("Expected real Taraz native APIs not frozen")
    return expected


def inventory_digest(values: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode("utf-8")).hexdigest()


def verify_backup() -> dict:
    from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import independently_verify_backup
    previous.refuse_links(BACKUP)
    manifest_file = BACKUP / "snapshot-manifest.json"
    previous.refuse_links(manifest_file)
    if not manifest_file.is_file() or previous.sha(manifest_file) != EXPECTED_BACKUP_SHA:
        raise BuildBlocked("Pinned v1.0.2 cold-backup manifest missing or changed")
    report_file = BACKUP / "backup-acceptance-report.json"
    previous.refuse_links(report_file)
    if not report_file.is_file() or previous.sha(report_file) != EXPECTED_BACKUP_REPORT_SHA:
        raise BuildBlocked("Independent cold backup acceptance report absent or changed")
    report = json.loads(report_file.read_text(encoding="utf-8"))
    witness = report.get("backup", {})
    if (report.get("status") != "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING"
            or report.get("installedBefore") != BASE_VERSION
            or report.get("installedAfter") != BASE_VERSION
            or witness.get("manifestSha256") != EXPECTED_BACKUP_SHA
            or witness.get("backupRoot") != str(BACKUP)
            or witness.get("fileCount") != EXPECTED_BACKUP_FILES
            or witness.get("totalBytes") != EXPECTED_BACKUP_BYTES
            or witness.get("sqliteValidatedCount") != EXPECTED_SQLITE_CHECKS
            or witness.get("independentReadback") is not True):
        raise BuildBlocked("Independent cold backup acceptance report content mismatches")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (manifest.get("schemaVersion") != 1 or manifest.get("verifiedNoOverwrite") is not True
            or manifest.get("allFilesIncluded") is not True
            or manifest.get("fileCount") != EXPECTED_BACKUP_FILES
            or manifest.get("totalBytes") != EXPECTED_BACKUP_BYTES
            or len(manifest.get("sqliteChecks", {})) != EXPECTED_SQLITE_CHECKS):
        raise BuildBlocked("Cold-backup count, size or integrity witness invalid")
    # Independently validate EVERY saved byte and copied SQLite database.
    independently_verify_backup(BACKUP)
    return {
        "root": str(BACKUP), "manifestSha256": EXPECTED_BACKUP_SHA,
        "reportSha256": EXPECTED_BACKUP_REPORT_SHA,
        "fileCount": EXPECTED_BACKUP_FILES, "totalBytes": EXPECTED_BACKUP_BYTES,
        "sqliteValidatedCount": EXPECTED_SQLITE_CHECKS, "independentReadback": True,
    }


def verify_installed() -> dict:
    from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import no_active_taraz
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise BuildBlocked("Native Windows Taraz installation required")
    no_active_taraz()
    installed = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz"
    pointer = installed / "current-version.txt"
    launcher = installed / "Run-Taraz.cmd"
    old = installed / "versions" / BASE_VERSION / "Taraz.exe"
    for item in (installed, pointer, launcher, old):
        previous.refuse_links(item)
        if not item.exists():
            raise BuildBlocked("Installed 1.0.1 baseline incomplete")
    if pointer.read_text(encoding="utf-8-sig").strip() != BASE_VERSION:
        raise BuildBlocked("Installed version pointer is not 1.0.1")
    if previous.sha(old) != EXPECTED_INSTALLED_SHA:
        raise BuildBlocked("Installed 1.0.1 binary digest changed")
    if "versions\\%TARAZ_VERSION%\\Taraz.exe" not in launcher.read_text(
            encoding="utf-8", errors="replace"):
        raise BuildBlocked("Installed versioned launcher contract changed")
    next_root = installed / "versions" / NEXT_VERSION
    previous.refuse_links(next_root)
    if next_root.exists():
        raise BuildBlocked("1.0.2 already installed; refusing an overwrite")
    return {
        "version": BASE_VERSION, "exeSha256": EXPECTED_INSTALLED_SHA,
        "pointerSha256": previous.sha(pointer), "launcherSha256": previous.sha(launcher),
        "root": str(installed),
    }


def stage_version(snapshot: Path) -> dict[str, str]:
    package = snapshot / "package.json"
    lock = snapshot / "package-lock.json"
    p = json.loads(package.read_text(encoding="utf-8"))
    l = json.loads(lock.read_text(encoding="utf-8"))
    # The tracked source still declares 1.0.0. Only the detached snapshot
    # is versioned. Real binaries do not inherit an old QA EXE or guard.
    if (p.get("name") != "taraz-accounting" or l.get("name") != "taraz-accounting"
            or [p.get("version"), l.get("version"),
                l.get("packages", {}).get("", {}).get("version")] != ["1.0.0"] * 3):
        raise BuildBlocked("Unrecognized tracked version/lock inputs")
    p["version"] = NEXT_VERSION
    l["version"] = NEXT_VERSION
    l["packages"][""]["version"] = NEXT_VERSION
    package.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lock.write_text(json.dumps(l, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mod = snapshot / "taraz_release_version.py"
    mod.write_text(
        '"""Non-QA Taraz 1.0.2 native release module."""\n'
        'APP_VERSION = "1.0.2"\nQA_ONLY = False\n'
        'BUILD_CHANNEL = "offline-production-candidate"\n', encoding="utf-8")
    entry = snapshot / "taraz_desktop.py"
    original = entry.read_text(encoding="utf-8")
    anchor = "from __future__ import annotations\n"
    if (original.count(anchor) != 1 or "_taraz_qa_launch_gate" in original
            or "taraz_release_version" in original):
        raise BuildBlocked("Unexpected original Taraz entrypoint version/QA instrumentation")
    entry.write_text(original.replace(anchor, anchor +
        '\nfrom taraz_release_version import APP_VERSION as _taraz_app_version\n'
        'if _taraz_app_version != "1.0.2":\n'
        '    raise RuntimeError("Taraz 1.0.2 release version mismatch")\n', 1),
        encoding="utf-8")
    return {"packageSha256": previous.sha(package), "lockSha256": previous.sha(lock),
            "versionModuleSha256": previous.sha(mod), "nativeEntrySha256": previous.sha(entry)}


def pe_version_file(resource: Path) -> None:
    # Reuse the proven Windows PE resource syntax, with a new exact version.
    previous.version_resource(resource)
    original = resource.read_text(encoding="utf-8")
    updated = original.replace("1,0,1,0", "1,0,2,0").replace(
        "1.0.1.0", "1.0.2.0")
    if "1.0.1.0" in updated or "1,0,1,0" in updated:
        raise BuildBlocked("Old 1.0.1 version bytes leaked into PE resource")
    resource.write_text(updated, encoding="utf-8")


def compiled_version(exe: Path) -> str:
    import ctypes
    lib = ctypes.windll.version
    lib.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    lib.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
    size = lib.GetFileVersionInfoSizeW(str(exe), ctypes.byref(ctypes.c_ulong()))
    if not size:
        raise BuildBlocked("Frozen 1.0.2 EXE has no Windows PE version metadata")
    buf = ctypes.create_string_buffer(size)
    lib.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    lib.GetFileVersionInfoW.restype = ctypes.c_int
    if not lib.GetFileVersionInfoW(str(exe), 0, size, buf):
        raise BuildBlocked("PE version resource readback failed")
    ptr, length = ctypes.c_void_p(), ctypes.c_uint()
    lib.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    lib.VerQueryValueW.restype = ctypes.c_int
    if not lib.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
        raise BuildBlocked("Frozen fixed product version unavailable")
    words = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32))
    if words[0] != 0xFEEF04BD:
        raise BuildBlocked("Frozen PE resource signature invalid")
    version = f"{words[2] >> 16}.{words[2] & 65535}.{words[3] >> 16}.{words[3] & 65535}"
    if version != "1.0.2.0":
        raise BuildBlocked("Frozen PE is not native v1.0.2.0: " + version)
    return version


def inspect_binary(exe: Path, dist: Path) -> dict:
    from PyInstaller.archive.readers import CArchiveReader
    from scripts.qa_mtr_taraz_build_20261110 import _code_strings

    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    version_code = pyz.extract("taraz_release_version")
    if not isinstance(version_code, types.CodeType):
        raise BuildBlocked("Non-QA release version module missing in PYZ")
    if "1.0.2" not in version_code.co_consts or "QA_ONLY" not in version_code.co_names:
        raise BuildBlocked("Frozen release module not 1.0.2")
    entry_blob = archive.extract("taraz_desktop")
    if not isinstance(entry_blob, bytes):
        raise BuildBlocked("Frozen Taraz native entrypoint absent")
    entry = marshal.loads(entry_blob)
    if not isinstance(entry, types.CodeType):
        raise BuildBlocked("Frozen Taraz entrypoint is invalid")
    available = previous.methods(entry)
    if not REQUIRED_NATIVE <= available or "_taraz_qa_launch_gate" in available:
        raise BuildBlocked("Frozen Taraz native Madar APIs missing or QA gate retained")
    pyz_bridge = pyz.extract("standalone_accounting_desktop")
    if not isinstance(pyz_bridge, types.CodeType):
        raise BuildBlocked("Frozen WebView2 native bridge module missing")
    literals = _code_strings(pyz_bridge)
    forwarders = [s for s in literals if "window.madar = Object.fromEntries(" in s]
    if len(forwarders) != 1 or not all(("'" + method + "'") in forwarders[0]
                                     for method in REQUIRED_NATIVE):
        raise BuildBlocked("WebView2 bridge does not forward Madar read APIs")
    reader = pyz.extract("taraz_madar_data_reader")
    if not isinstance(reader, types.CodeType):
        raise BuildBlocked("Frozen native Madar reader missing from PYZ")
    if not REQUIRED_READER <= previous.methods(reader):
        raise BuildBlocked("Frozen Madar reader functions are missing")
    store = pyz.extract("standalone_accounting_template_store")
    if not isinstance(store, types.CodeType) or not {
        "save", "set_default", "delete", "duplicate",
    } <= previous.methods(store):
        raise BuildBlocked("Existing invoice designer native persistence missing")
    packed_paths = {name.replace("\\", "/"): name for name in archive.toc}
    all_assets, js_assets = {}, {}
    for file in sorted(dist.rglob("*")):
        if not file.is_file():
            continue
        relative = file.relative_to(dist).as_posix()
        key = packed_paths.get("dist/" + relative)
        if not key:
            raise BuildBlocked("Packaged front-end asset missing: " + relative)
        packed = archive.extract(key)
        if not isinstance(packed, bytes) or hashlib.sha256(packed).hexdigest() != previous.sha(file):
            raise BuildBlocked("Frozen UI differs byte-for-byte from Vite: " + relative)
        all_assets[relative] = previous.sha(file)
        if relative.endswith(".js"):
            js_assets[relative] = previous.sha(file)
    if not js_assets:
        raise BuildBlocked("Frozen production JS not compiled")
    js = b" ".join((dist / path).read_bytes() for path in js_assets)
    missing = [token.decode("utf-8", errors="replace") for token in REQUIRED_FRONTEND
               if token not in js]
    if missing:
        raise BuildBlocked("Dashboard/Nav/consented data-read UI missing from JS: " + ",".join(missing))
    if "taraz-madar-dashboard" not in (SOURCE / "src/taraz_madar_dashboard.jsx").read_text(encoding="utf-8"):
        raise BuildBlocked("Dashboard source changed under verification")
    return {"peVersion": compiled_version(exe), "compiledJsSha256": js_assets,
            "allCompiledUiAssetsSha256": all_assets,
            "frozenNativeMethods": sorted(REQUIRED_NATIVE),
            "frozenReaderMethods": sorted(REQUIRED_READER),
            "webview2BridgeForwarded": True, "dashboardCompiled": True,
            "invoiceDesignerPreserved": True, "nonQaRuntime": True}


def rewrite_versions(script: str) -> str:
    # Reserve the previous release before replacing the older baseline. This
    # keeps 1.0.1 immutable and only targets the fresh versions/1.0.2 directory.
    return script.replace("1.0.1", "<NEW_VERSION>").replace(
        "1.0.0", BASE_VERSION).replace("<NEW_VERSION>", NEXT_VERSION).replace(
        "V101", "V102").replace("v101", "v102")


BACKUP_VERIFICATION_PS = r'''function CheckBackup([string]$root) {
  SafePath $root
  $r=Join-Path $root 'backup-acceptance-report.json'
  $m=Join-Path $root 'snapshot-manifest.json'
  if((Digest $m) -ne '__BACKUP_MANIFEST_SHA__' -or
     (Digest $r) -ne '__BACKUP_REPORT_SHA__'){Deny 'Cold-backup evidence SHA changed'}
  $report=Get-Content -LiteralPath $r -Raw -Encoding UTF8 | ConvertFrom-Json
  $manifest=Get-Content -LiteralPath $m -Raw -Encoding UTF8 | ConvertFrom-Json
  if($report.status -ne 'VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING' -or
     $report.installedBefore -ne '1.0.1' -or
     $report.installedAfter -ne '1.0.1' -or
     $report.backup.independentReadback -ne $true -or
     $report.backup.sqliteValidatedCount -ne 67 -or
     $report.backup.manifestSha256 -ne '__BACKUP_MANIFEST_SHA__' -or
     $manifest.schemaVersion -ne 1 -or $manifest.fileCount -ne 181 -or
     $manifest.totalBytes -ne 124011875 -or
     $manifest.verifiedNoOverwrite -ne $true -or
     $manifest.allFilesIncluded -ne $true -or
     @($manifest.sqliteChecks.PSObject.Properties).Count -ne 67){
     Deny 'Independent cold-backup witness invalid'
  }
  $all=0L
  $files=@($manifest.files.PSObject.Properties)
  if($files.Count -ne 181){Deny 'Cold-backup inventory incomplete'}
  foreach($item in $files){
    $relative=[string]$item.Name
    if($relative -notmatch '^(roaming|local|bridge)/' -or
       $relative -match '(^|/)\.\.(/|$)' -or $relative.Contains(':')){
       Deny 'Unsafe backup inventory path'
    }
    $path=Join-Path (Join-Path $root 'files') $relative.Replace('/',[IO.Path]::DirectorySeparatorChar)
    SafePath $path
    $file=Get-Item -LiteralPath $path -ErrorAction Stop
    if($file.Length -ne [long]$item.Value.bytes -or (Digest $path) -ne [string]$item.Value.sha256){
      Deny 'Cold-backup file bytes changed'
    }
    $all += $file.Length
  }
  if($all -ne 124011875 -or
     @(Get-ChildItem -LiteralPath (Join-Path $root 'files') -Recurse -File -Force).Count -ne 181){
    Deny 'Cold-backup file set changed'
  }
}
'''


def installation_scripts(exe_sha: str) -> tuple[str, str]:
    install = rewrite_versions(previous.INSTALL_SCRIPT)
    prefix = "function CheckBackup([string]$root) {"
    suffix = "if(-not $env:LOCALAPPDATA)"
    start = install.index(prefix)
    end = install.index(suffix, start)
    install = install[:start] + BACKUP_VERIFICATION_PS + install[end:]
    activate = rewrite_versions(previous.ACTIVATE_SCRIPT)
    start = activate.index("if((Digest (Join-Path $BackupRoot 'backup-acceptance-report.json'))")
    end = activate.index("if(Test-Path -LiteralPath $oldCopy)", start)
    activate = activate[:start] + (
        "if((Digest (Join-Path $BackupRoot 'snapshot-manifest.json')) -ne '__BACKUP_MANIFEST_SHA__' -or\n"
        "   (Digest (Join-Path $BackupRoot 'backup-acceptance-report.json')) -ne '__BACKUP_REPORT_SHA__')"
        "{Deny 'Cold backup attestation changed'}\n"
    ) + activate[end:]
    substitutions = {
        "__BACKUP_ROOT__": str(BACKUP).replace("'", "''"),
        "__BACKUP_MANIFEST_SHA__": EXPECTED_BACKUP_SHA,
        "__BACKUP_REPORT_SHA__": EXPECTED_BACKUP_REPORT_SHA,
        "__BASELINE_SHA__": EXPECTED_INSTALLED_SHA,
        "__NEW_EXE_SHA__": exe_sha,
    }
    result = []
    for script in (install, activate):
        for token, value in substitutions.items():
            script = script.replace(token, value)
        if any(token in script for token in substitutions):
            raise BuildBlocked("Unresolved installation/activation template token")
        if "versions\\1.0.1\\Taraz.exe" not in script and "versions\\1.0.1" not in script:
            raise BuildBlocked("Script cannot locate pinned installed 1.0.1 baseline")
        if "versions\\1.0.2" not in script:
            raise BuildBlocked("Script cannot locate side-by-side 1.0.2")
        result.append(script)
    if "Install-Taraz-V102.ps1" not in result[1]:
        raise BuildBlocked("Activation script does not verify the v1.0.2 installation")
    return result[0], result[1]


def package_update(run: Path, exe: Path, expected: dict[str, str], staged: dict,
                   observed: dict, backup: dict, baseline: dict) -> dict:
    folder = run / "offline-update"
    folder.mkdir(exist_ok=False)
    exe_copy = folder / "Taraz.exe"
    with exe.open("rb") as source, exe_copy.open("xb") as dest:
        shutil.copyfileobj(source, dest, 1024 * 1024)
    exe_sha = previous.sha(exe)
    if previous.sha(exe_copy) != exe_sha:
        raise BuildBlocked("Offline copy SHA differs")
    install, activate = installation_scripts(exe_sha)
    install_path = folder / "Install-Taraz-V102.ps1"
    activate_path = folder / "Activate-Taraz-V102.ps1"
    install_path.write_text(install, encoding="utf-8")
    activate_path.write_text(activate, encoding="utf-8")
    source_file = folder / "source-sha256.json"
    source_file.write_text(json.dumps(expected, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest_file = folder / "update-manifest.json"
    manifest = {
        "schemaVersion": 1, "application": "Taraz", "targetVersion": NEXT_VERSION,
        "sourceBaselinePackageVersion": "1.0.0", "installedBaselineVersion": BASE_VERSION,
        "productionCandidate": True, "qaOnly": False, "unsigned": True,
        "installed": False, "pointerActivated": False, "realLedgerModified": False,
        "previousVersionRetained": BASE_VERSION,
        "defaultDataRoot": "%APPDATA%\\Taraz",
        "launcherContract": "versions\\%TARAZ_VERSION%\\Taraz.exe",
        "exeSha256": exe_sha, "exeBytes": exe.stat().st_size,
        "peVersion": observed["peVersion"], "sourceSnapshotSha256": inventory_digest(expected),
        "sourceFilesCount": len(expected), "sourceFileManifestSha256": previous.sha(source_file),
        "stagedVersionSourceHashes": staged, "compiledEvidence": observed,
        "coldBackup": backup,
        "installedBaseline": baseline,
        "madarReaderReadOnlyProjectionsOnly": True,
        "financePostingByMadarDashboardTested": False,
    }
    manifest_file.write_text(json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2)
                             + "\n", encoding="utf-8")
    zip_path = run / "Taraz-v1.0.2-MADAR-DASHBOARD-OFFLINE-UPDATE.zip"
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zip_file:
        for file in sorted(folder.iterdir()):
            zip_file.write(file, file.name)
    with zipfile.ZipFile(zip_path) as zip_file:
        if zip_file.testzip() is not None:
            raise BuildBlocked("Offline ZIP readback failed")
    return {"exe": str(exe), "exeSha256": exe_sha, "zip": str(zip_path),
            "zipSha256": previous.sha(zip_path),
            "installScript": str(install_path), "installScriptSha256": previous.sha(install_path),
            "activationScript": str(activate_path),
            "activationScriptSha256": previous.sha(activate_path),
            "manifest": str(manifest_file), "manifestSha256": previous.sha(manifest_file)}


def build(frozen_source_sha: str) -> Path:
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise BuildBlocked("Native build requires Windows Python 3.12")
    if (len(frozen_source_sha) != 64
            or any(c not in "0123456789abcdef" for c in frozen_source_sha)):
        raise BuildBlocked("Source freeze must be an explicit lowercase SHA-256")
    expected = source_inventory()
    if inventory_digest(expected) != frozen_source_sha:
        raise BuildBlocked("Source is not the explicit worker20/22 approved frozen revision")
    backup = verify_backup()
    installed = verify_installed()
    previous.refuse_links(OUTPUT.parent)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    run = OUTPUT / ("build-" + uuid.uuid4().hex[:12])
    run.mkdir(exist_ok=False)
    report_file = run / "build-report.json"
    report: dict = {"status": "IN_PROGRESS", "version": NEXT_VERSION,
                    "sourceFreezeSha256": frozen_source_sha, "installed": False,
                    "realLedgerModified": False, "pointerChanged": False, "output": str(run)}
    try:
        snapshot = run / "source"
        previous.snapshot_source(SOURCE, snapshot, expected)
        versioned = stage_version(snapshot)
        from scripts.qa_mtr_taraz_build_20261110 import _trusted_modules, _safe_copytree
        deps = _trusted_modules()
        _safe_copytree(deps, snapshot / "node_modules")
        environment = previous.offline_environment(run)
        dist = run / "web" / "dist"
        dist.parent.mkdir()
        previous.run_command([
            shutil.which("node") or "node", str(snapshot / "node_modules" / "vite" / "bin" / "vite.js"),
            "build", "--config", str(snapshot / "vite.config.js"),
            "--outDir", str(dist), "--emptyOutDir",
        ], cwd=snapshot, env=environment, log=run / "vite-build.log", timeout=240)
        if not (dist / "accounting.html").is_file():
            raise BuildBlocked("Vite did not compile the accounting entrypoint")
        resource = run / "taraz-v102-pe-version.txt"
        pe_version_file(resource)
        binary = run / "binary"
        binary.mkdir()
        previous.run_command([
            sys.executable, "-B", "-m", "PyInstaller", "--onefile", "--windowed",
            "--noconfirm", "--version-file", str(resource), "--name", "Taraz",
            "--hidden-import", "taraz_madar_data_reader",
            "--hidden-import", "standalone_accounting_template_store",
            "--hidden-import", "taraz_integration",
            "--hidden-import", "personal_parsian_bridge",
            "--hidden-import", "standalone_accounting_auto_backup",
            "--icon", str(snapshot / "assets" / "taraz.ico"),
            "--add-data", str(dist) + ";dist",
            "--distpath", str(binary),
            "--workpath", str(run / "pyinstaller" / "work"),
            "--specpath", str(run / "pyinstaller" / "spec"),
            "--paths", str(snapshot), str(snapshot / "taraz_desktop.py"),
        ], cwd=snapshot, env=environment, log=run / "pyinstaller-build.log", timeout=780)
        executable = binary / "Taraz.exe"
        if not executable.is_file():
            raise BuildBlocked("Native non-QA 1.0.2 EXE not generated")
        observed = inspect_binary(executable, dist)
        if inventory_digest(source_inventory()) != frozen_source_sha:
            raise BuildBlocked("Worker-owned runtime source drifted after frozen snapshot")
        if verify_installed() != installed:
            raise BuildBlocked("Installed 1.0.1 changed while building")
        packaged = package_update(run, executable, expected, versioned, observed, backup, installed)
        report.update({"status": "PRODUCTION_V102_CANDIDATE_BUILT_NOT_INSTALLED",
                       "sourceInputCount": len(expected), "compiled": observed,
                       "baseline": installed, "backup": backup, **packaged})
    except Exception as exc:
        report.update({"status": "BLOCKED", "errorType": type(exc).__name__, "error": str(exc)})
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        raise
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return report_file


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fingerprint", action="store_true",
                        help="Print current read-only source fingerprint; does NOT authorize source freeze")
    parser.add_argument("--build", action="store_true",
                        help="Build only after worker20 and worker22 confirm frozen sources")
    parser.add_argument("--frozen-sha", default="",
                        help="Explicit fingerprint approved after both worker freezes")
    args = parser.parse_args()
    try:
        if args.fingerprint:
            print(inventory_digest(source_inventory()))
            return 0
        if args.build:
            report_path = build(args.frozen_sha)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            print(json.dumps({k: report[k] for k in (
                "status", "output", "exeSha256", "zip", "zipSha256", "manifestSha256"
            )}, ensure_ascii=False, indent=2))
            return 0
        verify_backup()
        verify_installed()
        # Source is intentionally NOT captured before worker20+22 freeze.
        print("V102_BUILDER_READY_AWAITING_BACKEND_FRONTEND_FREEZE")
        return 0
    except Exception as exc:
        print(f"TARAZ V102 BUILD BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
