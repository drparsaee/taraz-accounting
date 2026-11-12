"""Build a genuine, offline Taraz 1.0.1 production *candidate*.

Only new, create-only artifacts are written in D:/CoS-Test. The existing
Taraz launcher, version pointer, installed binaries and real data are read
for preflight evidence but never modified. Activation is a separate guarded
step packaged for the prime agent to independently validate and execute.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import marshal
import os
from pathlib import Path
import shutil
import subprocess
import sys
import types
import uuid
import zipfile

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parents[1]
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
PARENT = SOURCE.parents[1]
OUTPUT = PARENT / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.1-production-candidate"
BACKUP = PARENT / "MTR-REAL-UPGRADE-BACKUPS-20261110" / "taraz-backup-4ea33b2b953d"
EXPECTED_BACKUP_REPORT_SHA = "635e309317eb81ce27bbfd35ed7e432b05e6edcb68e63002c7863c742a7a704f"
EXPECTED_BACKUP_MANIFEST_SHA = "b854970e6e99f8abeec001cdb4c8f9c4e501eca6a919a8436cd02dfb87907afb"
EXPECTED_V100_SHA = "de5005579039bd86890c1dca1f5f1d9c760e6c47579a42f649f80096f158e70c"
VERSION = "1.0.1"
NATIVE_BRIDGE_METHODS = (
    "standaloneAccountingTemplateList", "standaloneAccountingTemplateSave",
    "standaloneAccountingTemplateDelete", "standaloneAccountingTemplateDefault",
    "standaloneAccountingTemplateDuplicate",
)
REQUIRED_UI = (
    b"invoiceDesign", b"sac-invoice-template-studio",
    b"standaloneAccountingTemplateSave", b"standaloneAccountingTemplateDefault",
    b"taraz-feedback-host", "طراحی فرم فاکتور".encode("utf-8"),
)


class BuildBlocked(RuntimeError):
    pass


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def refuse_links(path: Path) -> None:
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            attributes = getattr(item.lstat(), "st_file_attributes", 0)
            if item.is_symlink() or attributes & 0x400:
                raise BuildBlocked("Reparse point or symlink refused: " + str(item))


def source_hashes(source: Path) -> dict[str, str]:
    # Reuse the attested selection of runtime source inputs, never QA build
    # fixtures, old dist outputs, test output or the working-tree .git state.
    sys.path.insert(0, str(SOURCE / "scripts"))
    from qa_mtr_taraz_build_20261110 import _tree_fingerprint
    refuse_links(source)
    return _tree_fingerprint(source)


def snapshot_source(source: Path, target: Path, expected: dict[str, str]) -> None:
    target.mkdir(exist_ok=False)
    for rel, digest in expected.items():
        origin = source / rel
        refuse_links(origin)
        if not origin.is_file() or sha(origin) != digest:
            raise BuildBlocked("Source changed before snapshot: " + rel)
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        with origin.open("rb") as old, destination.open("xb") as new:
            shutil.copyfileobj(old, new, 1024 * 1024)
        if sha(destination) != digest:
            raise BuildBlocked("Source copy digest mismatch: " + rel)
    if source_hashes(source) != expected:
        raise BuildBlocked("Source changed during snapshot")


def stage_version(snapshot: Path) -> dict[str, str]:
    package = snapshot / "package.json"
    lock = snapshot / "package-lock.json"
    p = json.loads(package.read_text(encoding="utf-8"))
    l = json.loads(lock.read_text(encoding="utf-8"))
    if [p.get("version"), l.get("version"), l.get("packages", {}).get("", {}).get("version")] != ["1.0.0"] * 3:
        raise BuildBlocked("Cannot version a source with unknown or mismatched package locks")
    if p.get("name") != "taraz-accounting" or l.get("name") != "taraz-accounting":
        raise BuildBlocked("Unexpected source package identity")
    p["version"] = VERSION
    l["version"] = VERSION
    l["packages"][""]["version"] = VERSION
    package.write_text(json.dumps(p, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lock.write_text(json.dumps(l, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    module = snapshot / "taraz_release_version.py"
    module.write_text(
        '"""Taraz non-QA application release version, bundled in PYZ."""\n'
        'APP_VERSION = "1.0.1"\n'
        'QA_ONLY = False\n'
        'BUILD_CHANNEL = "offline-production-candidate"\n',
        encoding="utf-8",
    )
    entry = snapshot / "taraz_desktop.py"
    original = entry.read_text(encoding="utf-8")
    anchor = "from __future__ import annotations\n"
    if original.count(anchor) != 1 or "_taraz_qa_launch_gate" in original:
        raise BuildBlocked("Unexpected Taraz native entry or QA launch guard")
    entry.write_text(original.replace(anchor, anchor +
        '\nfrom taraz_release_version import APP_VERSION as _taraz_app_version\n'
        'if _taraz_app_version != "1.0.1":\n'
        '    raise RuntimeError("Taraz release version mismatch")\n', 1), encoding="utf-8")
    if "TARAZ_QA_RUN_ROOT" in entry.read_text(encoding="utf-8"):
        raise BuildBlocked("QA-only environment launch gate leaked into release")
    return {"package": sha(package), "lock": sha(lock), "releaseModule": sha(module),
            "nativeEntry": sha(entry)}


def offline_environment(target: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("TARAZ_")}
    for name, sub in (
        ("APPDATA", "isolated/appdata"), ("LOCALAPPDATA", "isolated/localappdata"),
        ("USERPROFILE", "isolated/userprofile"), ("HOME", "isolated/home"),
        ("TEMP", "isolated/temp"), ("TMP", "isolated/temp"),
        ("PYINSTALLER_CONFIG_DIR", "isolated/pyi-cache"),
        ("PYTHONPYCACHEPREFIX", "isolated/pycache"),
        ("npm_config_cache", "isolated/npm-cache"),
    ):
        path = target / sub
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_command(args: list[str], *, cwd: Path, env: dict, log: Path, timeout: int) -> None:
    try:
        done = subprocess.run(args, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        log.write_text("TIMEOUT", encoding="utf-8")
        raise BuildBlocked("Compiler timeout: " + str(log)) from exc
    log.write_text(done.stdout, encoding="utf-8")
    if done.returncode:
        raise BuildBlocked("Compiler failed: " + str(log) + " (" + str(done.returncode) + ") " + done.stdout[-600:])


def require_backup() -> dict:
    from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import independently_verify_backup
    report = BACKUP / "backup-acceptance-report.json"
    manifest = BACKUP / "snapshot-manifest.json"
    for path in (report, manifest):
        refuse_links(path)
        if not path.is_file():
            raise BuildBlocked("Required independently verified backup is missing")
    if sha(report) != EXPECTED_BACKUP_REPORT_SHA or sha(manifest) != EXPECTED_BACKUP_MANIFEST_SHA:
        raise BuildBlocked("Pinned backup attestation changed")
    attestation = json.loads(report.read_text(encoding="utf-8"))
    summary = attestation.get("backup", {})
    if (attestation.get("status") != "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING"
            or attestation.get("installedBefore") != "1.0.0"
            or summary.get("backupRoot") != str(BACKUP)
            or summary.get("fileCount") != 178
            or summary.get("totalBytes") != 124011301
            or summary.get("sqliteValidatedCount") != 67
            or summary.get("independentReadback") is not True
            or summary.get("manifestSha256") != EXPECTED_BACKUP_MANIFEST_SHA):
        raise BuildBlocked("Backup witness doesn't match required independent validation")
    independently_verify_backup(BACKUP)
    return {"root": str(BACKUP), "reportSha256": sha(report),
            "manifestSha256": sha(manifest), "fileCount": 178,
            "totalBytes": 124011301, "sqliteValidatedCount": 67}


def installed_contract() -> dict:
    from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import installed_baseline, no_active_taraz
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise BuildBlocked("A Windows installation is required")
    no_active_taraz()
    baseline = installed_baseline(Path(os.environ["LOCALAPPDATA"]), expected_sha=EXPECTED_V100_SHA)
    if (Path(baseline["root"]) / "versions" / "1.0.1").exists():
        raise BuildBlocked("Taraz 1.0.1 version already exists: no overwrite")
    return baseline


def version_resource(path: Path) -> None:
    content = '''VSVersionInfo(
  ffi=FixedFileInfo(filevers=(1,0,1,0), prodvers=(1,0,1,0),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0,0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Taraz'),
    StringStruct('FileDescription', 'Taraz accounting desktop'),
    StringStruct('FileVersion', '1.0.1.0'),
    StringStruct('ProductName', 'Taraz'),
    StringStruct('ProductVersion', '1.0.1.0'),
    StringStruct('OriginalFilename', 'Taraz.exe')
  ])]), VarFileInfo([VarStruct('Translation', [1033,1200])])]
)\n'''
    path.write_text(content, encoding="utf-8")


def pe_version(exe: Path) -> str:
    if os.name != "nt":
        raise BuildBlocked("Windows PE verification is required")
    lib = ctypes.windll.version
    lib.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    lib.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
    size = lib.GetFileVersionInfoSizeW(str(exe), ctypes.byref(ctypes.c_ulong()))
    if not size:
        raise BuildBlocked("Compiled EXE lacks PE version resource")
    buf = ctypes.create_string_buffer(size)
    lib.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    lib.GetFileVersionInfoW.restype = ctypes.c_int
    if not lib.GetFileVersionInfoW(str(exe), 0, size, buf):
        raise BuildBlocked("PE version readback failed")
    ptr, length = ctypes.c_void_p(), ctypes.c_uint()
    lib.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    lib.VerQueryValueW.restype = ctypes.c_int
    if not lib.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
        raise BuildBlocked("PE fixed version missing")
    words = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32))
    if words[0] != 0xFEEF04BD:
        raise BuildBlocked("PE version signature corrupted")
    found = f"{words[2] >> 16}.{words[2] & 65535}.{words[3] >> 16}.{words[3] & 65535}"
    if found != "1.0.1.0":
        raise BuildBlocked("Incorrect PE version: " + found)
    return found


def methods(code: types.CodeType) -> set[str]:
    names = {code.co_name}
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            names.update(methods(c))
    return names


def inspect_binary(exe: Path, web_dist: Path) -> dict:
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    version = pyz.extract("taraz_release_version")
    if not isinstance(version, types.CodeType):
        raise BuildBlocked("Frozen production version is absent from PYZ")
    if "QA_ONLY" not in version.co_names or False not in version.co_consts:
        raise BuildBlocked("Frozen PYZ does not identify non-QA release")
    native_bytes = archive.extract("taraz_desktop")
    if not isinstance(native_bytes, bytes):
        raise BuildBlocked("Frozen Taraz native main is absent")
    native = marshal.loads(native_bytes)
    if not isinstance(native, types.CodeType):
        raise BuildBlocked("Frozen main bytecode invalid")
    if "_taraz_qa_launch_gate" in methods(native):
        raise BuildBlocked("QA launch gate leaked into native production EXE")
    for name, module_name in (("native", "standalone_accounting_desktop"),
                              ("store", "standalone_accounting_template_store")):
        code = pyz.extract(module_name)
        if not isinstance(code, types.CodeType):
            raise BuildBlocked("Required PYZ " + name + " module absent")
        available = methods(code)
        expected = set(NATIVE_BRIDGE_METHODS) if name == "native" else {
            "save", "delete", "set_default", "duplicate", "_validate_print_design"}
        if not expected <= available:
            raise BuildBlocked("Frozen " + module_name + " missing " + str(sorted(expected - available)))
    packed_paths = {name.replace("\\", "/"): name for name in archive.toc}
    pinned_js: dict[str, str] = {}
    pinned_dist: dict[str, str] = {}
    for file in sorted(web_dist.rglob("*")):
        if not file.is_file():
            continue
        key = file.relative_to(web_dist).as_posix()
        archived_name = packed_paths.get("dist/" + key)
        if not archived_name:
            raise BuildBlocked("Frozen UI asset missing: " + key)
        packaged = archive.extract(archived_name)
        if not isinstance(packaged, bytes) or hashlib.sha256(packaged).hexdigest() != sha(file):
            raise BuildBlocked("Frozen asset differs from compiled source: " + key)
        pinned_dist[key] = sha(file)
        if key.endswith(".js"):
            pinned_js[key] = pinned_dist[key]
    if not pinned_js:
        raise BuildBlocked("No frozen JS assets")
    blob = b" ".join((web_dist / rel).read_bytes() for rel in pinned_js)
    missing = [key.decode("ascii") for key in REQUIRED_UI if key not in blob]
    if missing:
        raise BuildBlocked("Compiled invoice designer/feedback UI missing: " + ",".join(missing))
    if not (web_dist / "accounting.html").is_file():
        raise BuildBlocked("Frozen UI index unavailable")
    return {"peVersion": pe_version(exe), "compiledJsSha256": pinned_js,
            "allCompiledUiAssetsSha256": pinned_dist,
            "nativeTemplateMethods": list(NATIVE_BRIDGE_METHODS),
            "pyzSourceBound": True, "nonQaRuntime": True,
            "invoiceDesignerCompiled": True}


INSTALL_SCRIPT = r'''param([switch]$Apply,[switch]$VerifyExisting,[string]$BackupRoot='__BACKUP_ROOT__')
$ErrorActionPreference='Stop'
function Deny([string]$reason) { throw ('TARAZ 1.0.1 INSTALL BLOCKED: ' + $reason) }
function Digest([string]$path) {
  if(-not (Test-Path -LiteralPath $path -PathType Leaf)){ Deny 'Required file missing' }
  return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function SafePath([string]$path) {
  $p=Get-Item -LiteralPath $path -Force -ErrorAction Stop
  while($null -ne $p) {
    if(($p.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){Deny 'Linked or junction path refused'}
    $p=$p.Parent
  }
}
function CheckNoTaraz {
  try { $procs=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.Name -match '^Taraz(?:-v[0-9.]+.*)?\.exe$' }) }
  catch { Deny 'Cannot prove Taraz processes are stopped' }
  if($procs.Count -gt 0){ Deny 'Taraz is running; close all windows' }
}
function CheckBackup([string]$root) {
  SafePath $root
  $r=Join-Path $root 'backup-acceptance-report.json'
  $m=Join-Path $root 'snapshot-manifest.json'
  if((Digest $r) -ne '__BACKUP_REPORT_SHA__' -or (Digest $m) -ne '__BACKUP_MANIFEST_SHA__'){Deny 'Trusted backup SHA differs'}
  $report=Get-Content -LiteralPath $r -Raw -Encoding UTF8 | ConvertFrom-Json
  $manifest=Get-Content -LiteralPath $m -Raw -Encoding UTF8 | ConvertFrom-Json
  if($report.status -ne 'VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING' -or $report.installedBefore -ne '1.0.0' -or
     $report.backup.independentReadback -ne $true -or $report.backup.fileCount -ne 178 -or
     $report.backup.sqliteValidatedCount -ne 67 -or $manifest.fileCount -ne 178 -or
     $manifest.totalBytes -ne 124011301 -or $manifest.verifiedNoOverwrite -ne $true -or
     $manifest.allFilesIncluded -ne $true){Deny 'Backup evidence is incomplete'}
  if(@($manifest.sqliteChecks.PSObject.Properties).Count -ne 67){Deny 'SQLite readback evidence mismatch'}
  $entries=@($manifest.files.PSObject.Properties)
  if($entries.Count -ne 178){Deny 'Backup inventory count mismatch'}
  $all=0L
  foreach($entry in $entries){
    $name=[string]$entry.Name
    if($name -notmatch '^(roaming|local|bridge)/' -or $name -match '(^|/)\.\.(/|$)' -or $name.Contains(':')){Deny 'Unsafe backup inventory path'}
    $relative=$name.Replace('/',[IO.Path]::DirectorySeparatorChar)
    $file=Join-Path (Join-Path $root 'files') $relative
    SafePath $file
    $actual=Get-Item -LiteralPath $file -ErrorAction Stop
    if($actual.Length -ne [long]$entry.Value.bytes -or (Digest $file) -ne [string]$entry.Value.sha256){Deny 'Backup bytes changed'}
    $all += $actual.Length
  }
  if($all -ne 124011301 -or @(Get-ChildItem -LiteralPath (Join-Path $root 'files') -Recurse -File -Force).Count -ne 178){Deny 'Backup file set changed'}
}
if(-not $env:LOCALAPPDATA){Deny 'LOCALAPPDATA unavailable'}
$root=Join-Path $env:LOCALAPPDATA 'Programs\Taraz'
$old=Join-Path $root 'versions\1.0.0\Taraz.exe'
$pointer=Join-Path $root 'current-version.txt'
$launcher=Join-Path $root 'Run-Taraz.cmd'
$destination=Join-Path $root 'versions\1.0.1'
$payload=Join-Path $PSScriptRoot 'Taraz.exe'
$manifestFile=Join-Path $PSScriptRoot 'update-manifest.json'
SafePath $root
CheckNoTaraz
if((Digest $old) -ne '__BASELINE_SHA__'){Deny 'Installed 1.0.0 binary changed'}
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.0'){Deny 'Installed version pointer is no longer 1.0.0'}
if((Get-Content -LiteralPath $launcher -Raw) -notmatch 'versions\\%TARAZ_VERSION%\\Taraz\.exe'){Deny 'Unknown launcher contract'}
$manifest=Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
if($manifest.targetVersion -ne '1.0.1' -or $manifest.productionCandidate -ne $true -or (Digest $payload) -ne '__NEW_EXE_SHA__' -or $manifest.exeSha256 -ne '__NEW_EXE_SHA__'){Deny 'Payload SHA or version mismatch'}
if($VerifyExisting){
  if((Digest (Join-Path $destination 'Taraz.exe')) -ne '__NEW_EXE_SHA__'){Deny 'Installed 1.0.1 bytes changed'}
} elseif(Test-Path -LiteralPath $destination){Deny 'Version 1.0.1 already exists; never overwrite'}
CheckBackup $BackupRoot
if($VerifyExisting){ Write-Output 'EXISTING_SIDE_BY_SIDE_1.0.1_VERIFIED'; exit 0 }
if(-not $Apply){ Write-Output 'READY_FOR_CREATE_ONLY_SIDE_BY_SIDE_INSTALL'; exit 0 }
CheckNoTaraz
New-Item -ItemType Directory -Path $destination -ErrorAction Stop | Out-Null
SafePath $destination
$target=Join-Path $destination 'Taraz.exe'
$input=[IO.File]::OpenRead($payload)
try {
  $out=[IO.File]::Open($target,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try { $input.CopyTo($out); $out.Flush($true) } finally { $out.Dispose() }
} finally { $input.Dispose() }
if((Digest $target) -ne '__NEW_EXE_SHA__'){Deny 'Installed 1.0.1 readback failed'}
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.0'){Deny 'Pointer changed while installing'}
Write-Output 'INSTALLED_SIDE_BY_SIDE_1.0.1_POINTER_STILL_1.0.0'
'''

ACTIVATE_SCRIPT = r'''param([switch]$Apply,[string]$BackupRoot='__BACKUP_ROOT__')
$ErrorActionPreference='Stop'
function Deny([string]$reason){ throw ('TARAZ ACTIVATION BLOCKED: ' + $reason) }
function Digest([string]$path){ if(-not(Test-Path -LiteralPath $path -PathType Leaf)){Deny 'Missing file'}; (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
if(-not $env:LOCALAPPDATA){Deny 'LOCALAPPDATA unavailable'}
$root=Join-Path $env:LOCALAPPDATA 'Programs\Taraz'
$old=Join-Path $root 'versions\1.0.0\Taraz.exe'
$new=Join-Path $root 'versions\1.0.1\Taraz.exe'
$pointer=Join-Path $root 'current-version.txt'
$oldCopy=Join-Path $root 'current-version-pre-1.0.1.txt'
$temp=Join-Path $root 'current-version-1.0.1-pending.txt'
if((Digest $old) -ne '__BASELINE_SHA__' -or (Digest $new) -ne '__NEW_EXE_SHA__'){Deny 'Installed binary digest mismatch'}
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.0'){Deny 'Pointer baseline changed'}
if((Digest (Join-Path $BackupRoot 'backup-acceptance-report.json')) -ne '__BACKUP_REPORT_SHA__' -or
   (Digest (Join-Path $BackupRoot 'snapshot-manifest.json')) -ne '__BACKUP_MANIFEST_SHA__'){Deny 'Backup attestation changed'}
if(Test-Path -LiteralPath $oldCopy){Deny 'Prior activation backup already present'}
if(Test-Path -LiteralPath $temp){Deny 'Prior pending pointer already present'}
try { $procs=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.Name -match '^Taraz(?:-v[0-9.]+.*)?\.exe$' }) }
catch { Deny 'Cannot establish process inactivity' }
if($procs.Count -gt 0){Deny 'Taraz is running'}
if(-not $Apply){Write-Output 'READY_TO_ACTIVATE_1.0.1_OLD_VERSION_PRESERVED'; exit 0}
# Exact backup readback is repeated with the install verifier, including every file.
& (Join-Path $PSScriptRoot 'Install-Taraz-V101.ps1') -VerifyExisting -BackupRoot $BackupRoot | Out-Null
if($LASTEXITCODE -and $LASTEXITCODE -ne 0){Deny 'Installation attestation failed'}
[IO.File]::WriteAllText($temp, "1.0.1`r`n",[Text.UTF8Encoding]::new($false))
[IO.File]::Replace($temp,$pointer,$oldCopy,$true)
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.1'){Deny 'Pointer activation readback failed'}
Write-Output 'ACTIVATED_1.0.1_LEGACY_1.0.0_EXE_RETAINED'
'''


def staged_scripts(exe_sha: str) -> tuple[str, str]:
    replacements = {
        "__BACKUP_ROOT__": str(BACKUP).replace("'", "''"),
        "__BACKUP_REPORT_SHA__": EXPECTED_BACKUP_REPORT_SHA,
        "__BACKUP_MANIFEST_SHA__": EXPECTED_BACKUP_MANIFEST_SHA,
        "__BASELINE_SHA__": EXPECTED_V100_SHA,
        "__NEW_EXE_SHA__": exe_sha,
    }
    scripts = []
    for raw in (INSTALL_SCRIPT, ACTIVATE_SCRIPT):
        content = raw
        for token, replacement in replacements.items():
            content = content.replace(token, replacement)
        if "__" in content and any(token in content for token in replacements):
            raise BuildBlocked("Unresolved PowerShell script placeholders")
        scripts.append(content)
    return scripts[0], scripts[1]


def offline_package(target: Path, exe: Path, source: dict, staged: dict, observed: dict, backup: dict, baseline: dict) -> dict:
    package = target / "offline-update"
    package.mkdir(exist_ok=False)
    new_exe = package / "Taraz.exe"
    with exe.open("rb") as old, new_exe.open("xb") as fresh:
        shutil.copyfileobj(old, fresh, 1024 * 1024)
    exe_sha = sha(exe)
    if sha(new_exe) != exe_sha:
        raise BuildBlocked("Offline release EXE differs from build")
    install, activate = staged_scripts(exe_sha)
    for name, value in (("Install-Taraz-V101.ps1", install), ("Activate-Taraz-V101.ps1", activate)):
        (package / name).write_text(value, encoding="utf-8")
    fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    source_file = package / "source-sha256.json"
    source_file.write_text(json.dumps(source, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schemaVersion": 1, "application": "Taraz", "targetVersion": VERSION,
        "productionCandidate": True, "qaOnly": False, "unsigned": True,
        "installerExecuted": False, "pointerActivated": False, "defaultDataRoot": "%APPDATA%\\Taraz",
        "previousVersionRetained": "1.0.0", "launcherContract": "versions\\%TARAZ_VERSION%\\Taraz.exe",
        "compiledPEVersion": observed["peVersion"], "exeSha256": exe_sha,
        "exeBytes": exe.stat().st_size, "sourceSnapshotSha256": fingerprint,
        "sourceFilesCount": len(source), "originalSourceFilesSha256": sha(source_file),
        "stagedSourceSha256": staged, "compiledJsSha256": observed["compiledJsSha256"],
        "allCompiledUiAssetsSha256": observed["allCompiledUiAssetsSha256"],
        "nativeTemplateMethods": observed["nativeTemplateMethods"],
        "pyzSourceBound": observed["pyzSourceBound"],
        "invoiceDesignerCompiled": observed["invoiceDesignerCompiled"],
        "backup": backup,
        "installedBaseline": {k: baseline[k] for k in ("version", "exeSha256", "pointerSha256", "launcherSha256")},
        "financePeerActivationTested": False, "webView2Bundled": False,
    }
    manifest_file = package / "update-manifest.json"
    manifest_file.write_text(json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive_file = target / "Taraz-v1.0.1-OFFLINE-SIDE-BY-SIDE-UPDATE.zip"
    with zipfile.ZipFile(archive_file, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(package.iterdir()):
            archive.write(file, file.name)
    with zipfile.ZipFile(archive_file) as archive:
        if archive.testzip() is not None:
            raise BuildBlocked("ZIP readback integrity check failed")
    return {"packageFolder": str(package), "zip": str(archive_file),
            "zipSha256": sha(archive_file), "exeSha256": exe_sha,
            "manifestSha256": sha(manifest_file), "installScriptSha256": sha(package / "Install-Taraz-V101.ps1"),
            "activateScriptSha256": sha(package / "Activate-Taraz-V101.ps1")}


def build() -> Path:
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise BuildBlocked("Windows Python 3.12 required for frozen binary")
    refuse_links(SOURCE)
    refuse_links(OUTPUT.parent)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    refuse_links(OUTPUT)
    target = OUTPUT / ("build-" + uuid.uuid4().hex[:12])
    target.mkdir(exist_ok=False)
    report_file = target / "build-report.json"
    report = {"status": "IN_PROGRESS", "installed": False,
              "productionPointerChanged": False, "realLedgerModified": False,
              "targetVersion": VERSION, "output": str(target)}
    try:
        backup = require_backup()
        baseline = installed_contract()
        expected = source_hashes(SOURCE)
        snapshot = target / "snapshot"
        snapshot_source(SOURCE, snapshot, expected)
        staged = stage_version(snapshot)
        from scripts.qa_mtr_taraz_build_20261110 import _trusted_modules, _safe_copytree
        dependency_root = _trusted_modules()
        _safe_copytree(dependency_root, snapshot / "node_modules")
        env = offline_environment(target)
        web = target / "web" / "dist"
        web.parent.mkdir()
        run_command([shutil.which("node") or "node", str(snapshot / "node_modules" / "vite" / "bin" / "vite.js"),
                     "build", "--config", str(snapshot / "vite.config.js"),
                     "--outDir", str(web), "--emptyOutDir"], cwd=snapshot,
                    env=env, log=target / "vite-build.log", timeout=240)
        if not (web / "accounting.html").is_file():
            raise BuildBlocked("Vite failed to create accounting.html")
        resource = target / "taraz-v101-version.txt"
        version_resource(resource)
        exe_dir = target / "binary"
        exe_dir.mkdir()
        run_command([sys.executable, "-B", "-m", "PyInstaller", "--onefile", "--windowed",
                     "--noconfirm", "--version-file", str(resource), "--name", "Taraz",
                     "--hidden-import", "standalone_accounting_template_store",
                     "--hidden-import", "taraz_integration",
                     "--hidden-import", "personal_parsian_bridge",
                     "--hidden-import", "standalone_accounting_auto_backup",
                     "--icon", str(snapshot / "assets" / "taraz.ico"),
                     "--add-data", str(web) + ";dist", "--distpath", str(exe_dir),
                     "--workpath", str(target / "pyinstaller" / "work"),
                     "--specpath", str(target / "pyinstaller" / "spec"),
                     "--paths", str(snapshot), str(snapshot / "taraz_desktop.py")],
                    cwd=snapshot, env=env, log=target / "pyinstaller-build.log", timeout=780)
        exe = exe_dir / "Taraz.exe"
        if not exe.is_file() or exe.is_symlink():
            raise BuildBlocked("Actual production Taraz.exe not generated")
        observed = inspect_binary(exe, web)
        if source_hashes(SOURCE) != expected:
            raise BuildBlocked("Source inputs changed during production build")
        installed_contract()
        package = offline_package(target, exe, expected, staged, observed, backup, baseline)
        report.update({"status": "PRODUCTION_CANDIDATE_BUILT_NOT_INSTALLED",
                       "sourceFileCount": len(expected), "compiled": observed,
                       "backup": backup, "baseline": baseline, **package,
                       "sourceChangesDetected": False})
    except Exception as exc:
        report.update({"status": "BLOCKED", "errorType": type(exc).__name__, "error": str(exc)})
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_file


if __name__ == "__main__":
    try:
        path = build()
        data = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps({key: data[key] for key in (
            "status", "output", "exeSha256", "zip", "zipSha256", "manifestSha256")}, indent=2))
    except Exception as error:
        print(f"TARAZ PRODUCTION CANDIDATE BLOCKED: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
