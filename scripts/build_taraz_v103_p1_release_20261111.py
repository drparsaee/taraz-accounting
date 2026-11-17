"""Create-only, non-QA Taraz 1.0.3 offline P1 upgrade candidate.

No build without the prime-approved complete source fingerprint. Never launch
the EXE, touch Taraz finance data, alter the installed pointer, or overwrite a
versioned installation. Activation is a separate guarded operator operation.
"""
from __future__ import annotations

import ctypes
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
from scripts import build_taraz_v102_madar_dashboard_20261111 as v102

base = v102.previous
BuildBlocked = base.BuildBlocked
VERSION = "1.0.3"
BASE_VERSION = "1.0.2"
BASE_SHA256 = "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52"
SOURCE = ROOT
OUTPUT = SOURCE.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.3-p1"
PYZ_MODULES = {
    "taraz_madar_data_reader": set(v102.REQUIRED_READER),
    "standalone_accounting_template_store": {"save", "set_default", "delete", "duplicate"},
}


def inventory() -> dict[str, str]:
    return v102.source_inventory()


def fingerprint(values: dict[str, str] | None = None) -> str:
    return v102.inventory_digest(inventory() if values is None else values)


def installed_preflight() -> dict:
    from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import no_active_taraz

    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise BuildBlocked("Requires native Windows Taraz installation")
    no_active_taraz()
    root = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz"
    pointer, launcher = root / "current-version.txt", root / "Run-Taraz.cmd"
    exe = root / "versions" / BASE_VERSION / "Taraz.exe"
    future = root / "versions" / VERSION
    for item in (root, pointer, launcher, exe, future):
        base.refuse_links(item)
    if not pointer.is_file() or not launcher.is_file() or not exe.is_file():
        raise BuildBlocked("Installed Taraz 1.0.2 baseline is incomplete")
    if pointer.read_text(encoding="utf-8-sig").strip() != BASE_VERSION:
        raise BuildBlocked("Installed version pointer is not 1.0.2")
    if base.sha(exe) != BASE_SHA256:
        raise BuildBlocked("Installed Taraz 1.0.2 executable SHA-256 changed")
    if "versions\\%TARAZ_VERSION%\\Taraz.exe" not in launcher.read_text(
            encoding="utf-8", errors="replace"):
        raise BuildBlocked("Installed Taraz launcher contract changed")
    if future.exists():
        raise BuildBlocked("Installed Taraz 1.0.3 folder already exists")
    return {"version": BASE_VERSION, "exeSha256": BASE_SHA256,
            "pointerSha256": base.sha(pointer), "launcherSha256": base.sha(launcher),
            "root": str(root), "futureFolderAbsent": True}


def stage_version(snapshot: Path) -> dict[str, str]:
    package, lock = snapshot / "package.json", snapshot / "package-lock.json"
    p = json.loads(package.read_text(encoding="utf-8"))
    l = json.loads(lock.read_text(encoding="utf-8"))
    if (p.get("name") != "taraz-accounting" or l.get("name") != "taraz-accounting"
            or [p.get("version"), l.get("version"),
                l.get("packages", {}).get("", {}).get("version")] != ["1.0.0"] * 3):
        raise BuildBlocked("Unrecognized source package/lock version inputs")
    p["version"] = l["version"] = l["packages"][""]["version"] = VERSION
    package.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lock.write_text(json.dumps(l, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    module = snapshot / "taraz_release_version.py"
    module.write_text('"""Taraz non-QA offline release version."""\n'
                      'APP_VERSION = "1.0.3"\nQA_ONLY = False\n'
                      'BUILD_CHANNEL = "offline-production-candidate"\n', encoding="utf-8")
    entry = snapshot / "taraz_desktop.py"
    original = entry.read_text(encoding="utf-8")
    anchor = "from __future__ import annotations\n"
    if (original.count(anchor) != 1 or "_taraz_qa_launch_gate" in original
            or "taraz_release_version" in original):
        raise BuildBlocked("Unexpected native entrypoint instrumentation")
    entry.write_text(original.replace(anchor, anchor +
                     '\nfrom taraz_release_version import APP_VERSION as _taraz_app_version\n'
                     'if _taraz_app_version != "1.0.3":\n'
                     '    raise RuntimeError("Taraz 1.0.3 version mismatch")\n', 1),
                     encoding="utf-8")
    if "TARAZ_QA_RUN_ROOT" in entry.read_text(encoding="utf-8"):
        raise BuildBlocked("QA-only environment guard leaked into candidate")
    return {"packageSha256": base.sha(package), "lockSha256": base.sha(lock),
            "versionModuleSha256": base.sha(module), "nativeEntrySha256": base.sha(entry)}


def pe_resource(path: Path) -> None:
    v102.pe_version_file(path)
    value = path.read_text(encoding="utf-8")
    if value.count("1,0,2,0") != 2 or value.count("1.0.2.0") != 2:
        raise BuildBlocked("Unexpected PE resource version template")
    value = value.replace("1,0,2,0", "1,0,3,0").replace("1.0.2.0", "1.0.3.0")
    path.write_text(value, encoding="utf-8")


def pe_version(exe: Path) -> str:
    if os.name != "nt":
        raise BuildBlocked("Native Windows PE version verification required")
    lib = ctypes.windll.version
    lib.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    lib.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
    size = lib.GetFileVersionInfoSizeW(str(exe), ctypes.byref(ctypes.c_ulong()))
    if not size:
        raise BuildBlocked("Compiled 1.0.3 EXE lacks a PE version resource")
    buf = ctypes.create_string_buffer(size)
    lib.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    lib.GetFileVersionInfoW.restype = ctypes.c_int
    if not lib.GetFileVersionInfoW(str(exe), 0, size, buf):
        raise BuildBlocked("PE resource unreadable")
    ptr, length = ctypes.c_void_p(), ctypes.c_uint()
    lib.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    lib.VerQueryValueW.restype = ctypes.c_int
    if not lib.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
        raise BuildBlocked("PE fixed version missing")
    words = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32))
    if words[0] != 0xFEEF04BD:
        raise BuildBlocked("PE fixed version signature mismatch")
    found = f"{words[2] >> 16}.{words[2] & 65535}.{words[3] >> 16}.{words[3] & 65535}"
    if found != "1.0.3.0":
        raise BuildBlocked("Expected PE version 1.0.3.0; got " + found)
    return found


def inspect_binary(exe: Path, dist: Path) -> dict:
    from PyInstaller.archive.readers import CArchiveReader
    from scripts.qa_mtr_taraz_build_20261110 import _code_strings

    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    module = pyz.extract("taraz_release_version")
    if (not isinstance(module, types.CodeType) or VERSION not in module.co_consts
            or not {"APP_VERSION", "QA_ONLY", "BUILD_CHANNEL"} <= set(module.co_names)):
        raise BuildBlocked("Frozen 1.0.3 release PYZ module missing or incorrect")
    entry_bytes = archive.extract("taraz_desktop")
    if not isinstance(entry_bytes, bytes):
        raise BuildBlocked("Frozen native entrypoint missing")
    entry = marshal.loads(entry_bytes)
    if not isinstance(entry, types.CodeType):
        raise BuildBlocked("Frozen native entrypoint is invalid")
    required = set(v102.REQUIRED_NATIVE)
    methods = base.methods(entry)
    if not required <= methods or "_taraz_qa_launch_gate" in methods:
        raise BuildBlocked("Frozen native Madar APIs missing or QA gate leaked")
    bridge = pyz.extract("standalone_accounting_desktop")
    if not isinstance(bridge, types.CodeType):
        raise BuildBlocked("Frozen WebView2 bridge missing")
    scripts = [s for s in _code_strings(bridge) if "window.madar = Object.fromEntries(" in s]
    if len(scripts) != 1 or not all("'" + name + "'" in scripts[0] for name in required):
        raise BuildBlocked("Frozen WebView2 bridge Madar API allowlist incomplete")
    for name, needed in PYZ_MODULES.items():
        code = pyz.extract(name)
        if not isinstance(code, types.CodeType) or not needed <= base.methods(code):
            raise BuildBlocked("Frozen native module missing required methods: " + name)
    paths = {name.replace("\\", "/"): name for name in archive.toc}
    assets, js = {}, {}
    for item in sorted(dist.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(dist).as_posix()
        member = paths.get("dist/" + rel)
        if member is None:
            raise BuildBlocked("Compiled UI file absent from EXE: " + rel)
        blob = archive.extract(member)
        if not isinstance(blob, bytes) or hashlib.sha256(blob).hexdigest() != base.sha(item):
            raise BuildBlocked("Packed UI bytes do not match Vite: " + rel)
        assets[rel] = base.sha(item)
        if rel.endswith(".js"):
            js[rel] = base.sha(item)
    if not js:
        raise BuildBlocked("No frozen production JavaScript")
    frontend = b" ".join((dist / rel).read_bytes() for rel in js)
    if any(token not in frontend for token in v102.REQUIRED_FRONTEND):
        raise BuildBlocked("Required production Madar dashboard/UI bundle missing")
    return {"peVersion": pe_version(exe), "pyzVersion": VERSION,
            "nonQaRuntime": True, "nativeMethods": sorted(required),
            "bridgeForwarded": True, "nativeModuleMethods": {k: sorted(v) for k, v in PYZ_MODULES.items()},
            "uiAssetsSha256": assets, "compiledJsSha256": js,
            "compiledUiMatchesFrozenExe": True, "installedGuiTested": False}


_SHELL_HEADER = r'''$ErrorActionPreference='Stop'
function Deny([string]$reason) { throw ('TARAZ 1.0.3 UPGRADE BLOCKED: ' + $reason) }
function Digest([string]$path) {
  if(-not (Test-Path -LiteralPath $path -PathType Leaf)){Deny ('Missing file: ' + $path)}
  (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function SafePath([string]$path) {
  $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
  while($null -ne $item) {
    if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){Deny 'Linked/junction path refused'}
    $item=$item.Parent
  }
}
function CheckNoTaraz {
  try {$processes=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {$_.Name -match '^Taraz(?:-v[0-9.]+.*)?\.exe$'})}
  catch {Deny 'Cannot establish Taraz process inactivity'}
  if($processes.Count -gt 0){Deny 'Taraz process is running'}
}
function CheckBackup([string]$root,[string]$manifestSha,[string]$reportSha) {
  if(-not $root -or $manifestSha -cnotmatch '^[0-9a-f]{64}$' -or $reportSha -cnotmatch '^[0-9a-f]{64}$'){
    Deny 'New independent 1.0.2 cold-backup root and separately verified SHA-256 hashes required'
  }
  SafePath $root
  $manifestFile=Join-Path $root 'snapshot-manifest.json'
  $reportFile=Join-Path $root 'backup-acceptance-report.json'
  SafePath $manifestFile
  SafePath $reportFile
  if((Digest $manifestFile) -cne $manifestSha -or (Digest $reportFile) -cne $reportSha){Deny 'Cold backup attestation SHA changed'}
  $m=Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
  $r=Get-Content -LiteralPath $reportFile -Raw -Encoding UTF8 | ConvertFrom-Json
  if($r.status -ne 'VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING' -or
     $r.installedBefore -ne '1.0.2' -or $r.installedAfter -ne '1.0.2' -or
     $r.backup.backupRoot -ne $root -or $r.backup.independentReadback -ne $true -or
     $r.backup.manifestSha256 -cne $manifestSha -or
     $m.schemaVersion -ne 1 -or $m.verifiedNoOverwrite -ne $true -or
     $m.allFilesIncluded -ne $true){Deny 'New independent 1.0.2 backup evidence is incomplete'}
  $entries=@($m.files.PSObject.Properties)
  if($entries.Count -lt 1 -or $entries.Count -gt 200000 -or
     $entries.Count -ne [int]$m.fileCount -or $entries.Count -ne [int]$r.backup.fileCount -or
     @($m.sqliteChecks.PSObject.Properties).Count -lt 1 -or
     @($m.sqliteChecks.PSObject.Properties).Count -ne [int]$r.backup.sqliteValidatedCount){
    Deny 'Cold backup file/SQLite witness inventory inconsistent'
  }
  $total=0L
  foreach($e in $entries) {
    $relative=[string]$e.Name
    if($relative -notmatch '^(roaming|local|bridge)/' -or
       $relative -match '(^|/)\.\.(/|$)' -or $relative.Contains(':') -or
       $relative.Contains('\')){Deny 'Unsafe cold-backup relative path'}
    $file=Join-Path (Join-Path $root 'files') $relative.Replace('/',[IO.Path]::DirectorySeparatorChar)
    SafePath $file
    $info=Get-Item -LiteralPath $file -ErrorAction Stop
    if($info.Length -ne [long]$e.Value.bytes -or (Digest $file) -cne [string]$e.Value.sha256){
      Deny 'Cold backup source bytes changed'
    }
    $total+=$info.Length
  }
  if($total -ne [long]$m.totalBytes -or $total -ne [long]$r.backup.totalBytes -or
    @(Get-ChildItem -LiteralPath (Join-Path $root 'files') -Recurse -File -Force).Count -ne $entries.Count){
    Deny 'Cold backup total bytes/files mismatched'
  }
}
if(-not $env:LOCALAPPDATA){Deny 'LOCALAPPDATA unavailable'}
$root=Join-Path $env:LOCALAPPDATA 'Programs\Taraz'
$old=Join-Path $root 'versions\1.0.2\Taraz.exe'
$new=Join-Path $root 'versions\1.0.3\Taraz.exe'
$pointer=Join-Path $root 'current-version.txt'
$launcher=Join-Path $root 'Run-Taraz.cmd'
$payload=Join-Path $PSScriptRoot 'Taraz.exe'
$manifestFile=Join-Path $PSScriptRoot 'update-manifest.json'
SafePath $root
SafePath $old
SafePath $pointer
SafePath $launcher
SafePath $payload
SafePath $manifestFile
CheckNoTaraz
if((Digest $old) -cne '__BASE_SHA__'){Deny 'Installed 1.0.2 baseline binary changed'}
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.2'){Deny 'Installed version pointer changed'}
if((Get-Content -LiteralPath $launcher -Raw) -notmatch 'versions\\%TARAZ_VERSION%\\Taraz\.exe'){
  Deny 'Taraz versioned launcher contract changed'
}
$manifest=Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
if($manifest.targetVersion -ne '1.0.3' -or $manifest.installedBaselineVersion -ne '1.0.2' -or
   $manifest.qaOnly -ne $false -or $manifest.productionCandidate -ne $true -or
   $manifest.exeSha256 -cne '__NEW_EXE_SHA__' -or (Digest $payload) -cne '__NEW_EXE_SHA__'){
  Deny 'Payload version/manifest/hash mismatch'
}
CheckBackup $BackupRoot $BackupManifestSha256 $BackupReportSha256
'''


_INSTALL_TAIL = r'''$destination=Join-Path $root 'versions\1.0.3'
if($VerifyExisting){
  SafePath $destination
  SafePath $new
  if((Digest $new) -cne '__NEW_EXE_SHA__'){Deny 'Existing installed 1.0.3 bytes differ'}
  Write-Output 'EXISTING_SIDE_BY_SIDE_1.0.3_VERIFIED'
  exit 0
}
if(Test-Path -LiteralPath $destination){Deny '1.0.3 already present; never overwrite'}
if(-not $Apply){Write-Output 'READY_FOR_CREATE_ONLY_1.0.3_INSTALL'; exit 0}
CheckNoTaraz
New-Item -ItemType Directory -Path $destination -ErrorAction Stop | Out-Null
SafePath $destination
$input=[IO.File]::OpenRead($payload)
try {
  $output=[IO.File]::Open($new,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {$input.CopyTo($output); $output.Flush($true)} finally {$output.Dispose()}
} finally {$input.Dispose()}
if((Digest $new) -cne '__NEW_EXE_SHA__'){Deny 'Installed 1.0.3 readback SHA mismatch'}
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.2'){
  Deny 'Version pointer changed during install'
}
Write-Output 'INSTALLED_SIDE_BY_SIDE_1.0.3_POINTER_REMAINS_1.0.2'
'''


_ACTIVATE_TAIL = r'''$oldPointer=Join-Path $root 'current-version-pre-1.0.3.txt'
$temp=Join-Path $root 'current-version-1.0.3-pending.txt'
if(Test-Path -LiteralPath $oldPointer){Deny 'Activation pointer backup already exists; never overwrite'}
if(Test-Path -LiteralPath $temp){Deny 'Pending pointer already exists; never overwrite'}
$installer=Join-Path $PSScriptRoot 'Install-Taraz-V103.ps1'
SafePath $installer
& $installer -VerifyExisting -BackupRoot $BackupRoot -BackupManifestSha256 $BackupManifestSha256 -BackupReportSha256 $BackupReportSha256 | Out-Null
if(-not $Apply){Write-Output 'READY_TO_ACTIVATE_1.0.3_OLD_VERSION_RETAINED'; exit 0}
CheckNoTaraz
[IO.File]::WriteAllText($temp,"1.0.3`r`n",[Text.UTF8Encoding]::new($false))
[IO.File]::Replace($temp,$pointer,$oldPointer,$true)
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.3'){
  Deny 'Activation pointer readback failed'
}
Write-Output 'ACTIVATED_1.0.3_VERSION_1.0.2_RETAINED'
'''


def installation_scripts(exe_sha: str) -> tuple[str, str]:
    if len(exe_sha) != 64 or any(c not in "0123456789abcdef" for c in exe_sha):
        raise BuildBlocked("Invalid EXE SHA-256 for installer")
    scripts = []
    for header, tail in (
            ("param([switch]$Apply,[switch]$VerifyExisting,[string]$BackupRoot='',"
             "[string]$BackupManifestSha256='', [string]$BackupReportSha256='')\n", _INSTALL_TAIL),
            ("param([switch]$Apply,[string]$BackupRoot='',"
             "[string]$BackupManifestSha256='', [string]$BackupReportSha256='')\n", _ACTIVATE_TAIL)):
        value = header + _SHELL_HEADER + tail
        value = value.replace("__BASE_SHA__", BASE_SHA256).replace("__NEW_EXE_SHA__", exe_sha)
        if "__BASE_SHA__" in value or "__NEW_EXE_SHA__" in value:
            raise BuildBlocked("Unresolved PowerShell release template")
        scripts.append(value)
    return scripts[0], scripts[1]


def package_update(run: Path, exe: Path, expected: dict[str, str], staged: dict,
                   observed: dict, baseline: dict) -> dict:
    folder = run / "offline-update"
    folder.mkdir(exist_ok=False)
    output_exe = folder / "Taraz.exe"
    with exe.open("rb") as src, output_exe.open("xb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
    exe_sha = base.sha(exe)
    if base.sha(output_exe) != exe_sha:
        raise BuildBlocked("Offline copy SHA does not match native build")
    installer, activator = installation_scripts(exe_sha)
    install_file = folder / "Install-Taraz-V103.ps1"
    activate_file = folder / "Activate-Taraz-V103.ps1"
    install_file.write_text(installer, encoding="utf-8")
    activate_file.write_text(activator, encoding="utf-8")
    for name in ("package.json", "package-lock.json"):
        with (run / "source" / name).open("rb") as src, (folder / name).open("xb") as dst:
            shutil.copyfileobj(src, dst)
    source_file = folder / "source-sha256.json"
    source_file.write_text(json.dumps(expected, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schemaVersion": 1, "application": "Taraz", "targetVersion": VERSION,
        "installedBaselineVersion": BASE_VERSION, "installedBaselineSha256": BASE_SHA256,
        "productionCandidate": True, "qaOnly": False, "unsigned": True,
        "installed": False, "pointerActivated": False, "realLedgerModified": False,
        "previousVersionRetained": BASE_VERSION, "freshIndependentBackupRequired": True,
        "freshIndependentBackupVerified": False, "activationApprovalGranted": False,
        "defaultDataRoot": "%APPDATA%\\Taraz",
        "launcherContract": "versions\\%TARAZ_VERSION%\\Taraz.exe",
        "exeSha256": exe_sha, "exeBytes": exe.stat().st_size,
        "peVersion": observed["peVersion"], "pyzVersion": observed["pyzVersion"],
        "sourceSnapshotSha256": fingerprint(expected),
        "sourceFilesCount": len(expected), "sourceFileManifestSha256": base.sha(source_file),
        "stagedVersionSourceSha256": staged,
        "stagedPackageSha256": base.sha(folder / "package.json"),
        "stagedLockSha256": base.sha(folder / "package-lock.json"),
        "compiledEvidence": observed, "installedBaseline": baseline,
        "installScriptSha256": base.sha(install_file),
        "activationScriptSha256": base.sha(activate_file),
        "financePostingProven": False, "installedGuiTested": False,
    }
    manifest_file = folder / "update-manifest.json"
    manifest_file.write_text(json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    archive = run / "Taraz-v1.0.3-P1-OFFLINE-SIDE-BY-SIDE-UPDATE.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for path in sorted(folder.iterdir()):
            z.write(path, path.name)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None or set(z.namelist()) != {p.name for p in folder.iterdir()}:
            raise BuildBlocked("Offline ZIP archive failed integrity/completeness readback")
        if any(hashlib.sha256(z.read(p.name)).hexdigest() != base.sha(p)
               for p in folder.iterdir()):
            raise BuildBlocked("Offline ZIP member differs from source package")
    return {"exe": str(exe), "exeSha256": exe_sha, "zip": str(archive),
            "zipSha256": base.sha(archive), "manifest": str(manifest_file),
            "manifestSha256": base.sha(manifest_file),
            "installScript": str(install_file), "installScriptSha256": base.sha(install_file),
            "activationScript": str(activate_file), "activationScriptSha256": base.sha(activate_file)}


def build(frozen_source_sha: str) -> Path:
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise BuildBlocked("Windows Python 3.12 required for native 1.0.3 build")
    if len(frozen_source_sha) != 64 or any(c not in "0123456789abcdef" for c in frozen_source_sha):
        raise BuildBlocked("Explicit approved lowercase SHA-256 source freeze required")
    expected = inventory()
    if fingerprint(expected) != frozen_source_sha:
        raise BuildBlocked("Current P1 sources differ from explicitly approved freeze")
    installed = installed_preflight()
    base.refuse_links(OUTPUT.parent)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    base.refuse_links(OUTPUT)
    run = OUTPUT / ("build-" + uuid.uuid4().hex[:12])
    run.mkdir(exist_ok=False)
    report_file = run / "build-report.json"
    report = {"status": "IN_PROGRESS", "version": VERSION, "output": str(run),
              "sourceFreezeSha256": frozen_source_sha, "installed": False,
              "pointerChanged": False, "realLedgerModified": False}
    try:
        snapshot = run / "source"
        base.snapshot_source(SOURCE, snapshot, expected)
        staged = stage_version(snapshot)
        from scripts.qa_mtr_taraz_build_20261110 import _trusted_modules, _safe_copytree
        _safe_copytree(_trusted_modules(), snapshot / "node_modules")
        environment = base.offline_environment(run)
        dist = run / "web" / "dist"
        dist.parent.mkdir()
        base.run_command([shutil.which("node") or "node",
                          str(snapshot / "node_modules" / "vite" / "bin" / "vite.js"),
                          "build", "--config", str(snapshot / "vite.config.js"),
                          "--outDir", str(dist), "--emptyOutDir"],
                         cwd=snapshot, env=environment, log=run / "vite-build.log", timeout=240)
        if not (dist / "accounting.html").is_file():
            raise BuildBlocked("Vite production entrypoint absent")
        resource = run / "taraz-v103-pe-version.txt"
        pe_resource(resource)
        binary = run / "binary"
        binary.mkdir()
        base.run_command([sys.executable, "-B", "-m", "PyInstaller", "--onefile", "--windowed",
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
                         cwd=snapshot, env=environment, log=run / "pyinstaller-build.log", timeout=780)
        executable = binary / "Taraz.exe"
        base.refuse_links(executable)
        if not executable.is_file():
            raise BuildBlocked("Native 1.0.3 executable was not built")
        observed = inspect_binary(executable, dist)
        if fingerprint(inventory()) != frozen_source_sha:
            raise BuildBlocked("Runtime source drift during native build")
        if installed_preflight() != installed:
            raise BuildBlocked("Installed 1.0.2 baseline changed during build")
        packaged = package_update(run, executable, expected, staged, observed, installed)
        report.update({"status": "PRODUCTION_V103_P1_CANDIDATE_BUILT_NOT_INSTALLED",
                       "sourceFileCount": len(expected), "compiled": observed,
                       "baseline": installed, "freshIndependentBackupVerified": False,
                       **packaged})
    except Exception as exc:
        report.update({"status": "BLOCKED", "errorType": type(exc).__name__, "error": str(exc)})
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_file


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fingerprint", action="store_true", help="Read-only runtime source fingerprint; not approval")
    parser.add_argument("--build", action="store_true", help="Create 1.0.3 candidate after prime source freeze")
    parser.add_argument("--frozen-sha", default="", help="Exact approved P1 source fingerprint")
    args = parser.parse_args()
    try:
        if args.fingerprint:
            print(fingerprint())
            return 0
        if args.build:
            output = build(args.frozen_sha)
            result = json.loads(output.read_text(encoding="utf-8"))
            print(json.dumps({key: result[key] for key in (
                "status", "output", "exeSha256", "zip", "zipSha256", "manifestSha256")},
                ensure_ascii=False, indent=2))
            return 0
        installed_preflight()
        print("V103_BUILDER_READY_AWAITING_PRIME_P1_SOURCE_FREEZE_AND_FRESH_BACKUP_GATE")
        return 0
    except Exception as exc:
        print(f"TARAZ V103 BUILD BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
