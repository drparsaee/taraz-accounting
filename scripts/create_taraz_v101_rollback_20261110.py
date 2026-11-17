"""Generate a separate immutable, local, fail-closed Taraz 1.0.1 rollback rescue.

Creation is read-only toward the installation and accounting profile. Only the
explicit -Apply action in the GENERATED script can switch 1.0.1 back to 1.0.0.
The 1.0.0 and 1.0.1 binaries, finance data and backups are never deleted.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

SOURCE = Path(__file__).resolve().parents[1]
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from scripts import build_taraz_v101_local_update_20261110 as primary

COMPILED = primary.OUTPUT / "build-057caff5080e"
EXPECTED_NEW = "5b5a550f3b95cda8352f757cd9e61d44a62531e0e4dfe0fc6d586a0d6a452d4b"
EXPECTED_POINTER = "4ca8bbd3c595ee306226c6996b32b8d47a900217c55a7ed0cfc868ee444f34f1"
EXPECTED_REPORT = "23b185accb2b2e58bb6191ad13872a7479712e6c0c1e4da04439561610b597e2"


class RescueBlocked(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


ROLLBACK = r'''param([switch]$Apply,[string]$BackupRoot='__BACKUP_ROOT__')
$ErrorActionPreference='Stop'
function Deny([string]$why){ throw ('TARAZ ROLLBACK BLOCKED: ' + $why) }
function AssertPath([string]$value){
  if(-not(Test-Path -LiteralPath $value)){Deny 'Required file or folder missing'}
  $p=Get-Item -LiteralPath $value -Force -ErrorAction Stop
  while($null -ne $p){
    if(($p.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){Deny 'Junction/symlink refused'}
    $p=$p.Parent
  }
}
function Digest([string]$value){
  AssertPath $value
  if(-not(Test-Path -LiteralPath $value -PathType Leaf)){Deny 'Required regular file missing'}
  return (Get-FileHash -LiteralPath $value -Algorithm SHA256).Hash.ToLowerInvariant()
}
function AssertNotRunning {
  try {
    $procs=@(Get-CimInstance Win32_Process -ErrorAction Stop |
      Where-Object { $_.Name -match '^Taraz(?:-.*)?\.exe$' })
  } catch { Deny 'Cannot prove Taraz is closed' }
  if($procs.Count -gt 0){Deny 'Close all Taraz windows before rollback'}
}
function VerifyIndependentBackup([string]$root){
  AssertPath $root
  $r=Join-Path $root 'backup-acceptance-report.json'
  $m=Join-Path $root 'snapshot-manifest.json'
  if((Digest $r) -ne '__BACKUP_REPORT_SHA__' -or
     (Digest $m) -ne '__BACKUP_MANIFEST_SHA__'){Deny 'Pinned backup evidence was changed'}
  $report=Get-Content -LiteralPath $r -Raw -Encoding UTF8 | ConvertFrom-Json
  $manifest=Get-Content -LiteralPath $m -Raw -Encoding UTF8 | ConvertFrom-Json
  if($report.status -ne 'VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING' -or
     $report.installedBefore -ne '1.0.0' -or
     $report.backup.independentReadback -ne $true -or
     $report.backup.fileCount -ne __FILE_COUNT__ -or
     $report.backup.sqliteValidatedCount -ne __SQLITE_COUNT__ -or
     $manifest.fileCount -ne __FILE_COUNT__ -or
     $manifest.totalBytes -ne __TOTAL_BYTES__ -or
     $manifest.verifiedNoOverwrite -ne $true -or
     $manifest.allFilesIncluded -ne $true){Deny 'Backup witness mismatch'}
  if(@($manifest.sqliteChecks.PSObject.Properties).Count -ne __SQLITE_COUNT__){
    Deny 'SQLite verification witness missing'
  }
  $items=@($manifest.files.PSObject.Properties)
  if($items.Count -ne __FILE_COUNT__){Deny 'Backup file count changed'}
  $total=0L
  foreach($item in $items){
    $relative=[string]$item.Name
    if($relative -notmatch '^(roaming|local|bridge)/' -or
       $relative -match '(^|/)\.\.(/|$)' -or $relative.Contains(':')){
      Deny 'Backup manifest path is invalid'
    }
    $file=Join-Path (Join-Path $root 'files') $relative.Replace('/',[IO.Path]::DirectorySeparatorChar)
    if((Digest $file) -ne [string]$item.Value.sha256){Deny 'Backup file digest changed'}
    $size=(Get-Item -LiteralPath $file -ErrorAction Stop).Length
    if($size -ne [long]$item.Value.bytes){Deny 'Backup file length changed'}
    $total += $size
  }
  if($total -ne __TOTAL_BYTES__ -or
     @(Get-ChildItem -LiteralPath (Join-Path $root 'files') -File -Recurse -Force).Count -ne __FILE_COUNT__){
     Deny 'Backup file set differs from witness'
  }
}
if(-not $env:LOCALAPPDATA){Deny 'LOCALAPPDATA unavailable'}
$root=Join-Path $env:LOCALAPPDATA 'Programs\Taraz'
$versions=Join-Path $root 'versions'
$old=Join-Path $versions '1.0.0\Taraz.exe'
$new=Join-Path $versions '1.0.1\Taraz.exe'
$launcher=Join-Path $root 'Run-Taraz.cmd'
$pointer=Join-Path $root 'current-version.txt'
$original=Join-Path $root 'current-version-pre-1.0.1.txt'
$pending=Join-Path $root 'current-version-rollback-1.0.0-pending.txt'
$recovery=Join-Path $root 'current-version-1.0.1-before-rollback.txt'
AssertPath $root
AssertPath $versions
AssertPath (Join-Path $versions '1.0.0')
AssertPath (Join-Path $versions '1.0.1')
AssertNotRunning
if((Digest $old) -ne '__OLD_EXE_SHA__' -or (Digest $new) -ne '__NEW_EXE_SHA__'){
  Deny 'One installed executable differs from the pinned binary'
}
if((Digest $launcher) -ne '__LAUNCHER_SHA__'){Deny 'Launcher changed'}
if((Digest $original) -ne '__PRE_POINTER_SHA__' -or
   (Get-Content -LiteralPath $original -Raw -Encoding UTF8).Trim() -ne '1.0.0'){
  Deny 'Original 1.0.0 pointer backup is missing or corrupt'
}
VerifyIndependentBackup $BackupRoot
$version=(Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim()
if($version -eq '1.0.0'){
  if((Digest $pointer) -ne '__PRE_POINTER_SHA__'){Deny 'Unexpected active 1.0.0 pointer bytes'}
  Write-Output 'ALREADY_VERSION_1.0.0_ACTIVE_NO_MUTATION'
  exit 0
}
if($version -ne '1.0.1'){Deny 'Only active version 1.0.1 may be rolled back'}
if(Test-Path -LiteralPath $pending){Deny 'Unresolved previous rollback attempt'}
if(Test-Path -LiteralPath $recovery){Deny 'Rollback backup target already exists'}
if(-not $Apply){Write-Output 'READY_FOR_ATOMIC_ROLLBACK_TO_1.0.0'; exit 0}
AssertNotRunning
# Use the EXACT bytes from the pinned original pointer, keeping the old
# version and both executable directories intact.
$originalBytes=[IO.File]::ReadAllBytes($original)
$stream=[IO.File]::Open($pending,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try{$stream.Write($originalBytes,0,$originalBytes.Length);$stream.Flush($true)}
finally{$stream.Dispose()}
if((Digest $pending) -ne '__PRE_POINTER_SHA__'){Deny 'Staged rollback pointer digest differs'}
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.1'){
  Deny 'Pointer changed while preparing rollback'
}
[IO.File]::Replace($pending,$pointer,$recovery,$true)
if((Digest $pointer) -ne '__PRE_POINTER_SHA__'){Deny 'Atomic rollback pointer readback failed'}
if((Get-Content -LiteralPath $recovery -Raw -Encoding UTF8).Trim() -ne '1.0.1'){
  Deny 'Rollback prior-pointer backup readback failed'
}
Write-Output 'ROLLED_BACK_TO_1.0.0_BOTH_VERSIONS_RETAINED'
'''


def render(*, backup_root: Path, backup_report_sha: str, backup_manifest_sha: str,
           old_exe_sha: str, new_exe_sha: str, launcher_sha: str,
           pre_pointer_sha: str, file_count: int, total_bytes: int,
           sqlite_count: int) -> str:
    if not backup_root.is_absolute():
        raise RescueBlocked("Explicit absolute backup directory required")
    for value in (backup_report_sha, backup_manifest_sha, old_exe_sha, new_exe_sha,
                  launcher_sha, pre_pointer_sha):
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise RescueBlocked("SHA must be lowercase hexadecimal SHA-256")
    if file_count < 1 or total_bytes < 1 or sqlite_count < 1:
        raise RescueBlocked("Unverified backup count")
    substitutions = {
        "__BACKUP_ROOT__": str(backup_root).replace("'", "''"),
        "__BACKUP_REPORT_SHA__": backup_report_sha,
        "__BACKUP_MANIFEST_SHA__": backup_manifest_sha,
        "__OLD_EXE_SHA__": old_exe_sha, "__NEW_EXE_SHA__": new_exe_sha,
        "__LAUNCHER_SHA__": launcher_sha, "__PRE_POINTER_SHA__": pre_pointer_sha,
        "__FILE_COUNT__": str(file_count), "__TOTAL_BYTES__": str(total_bytes),
        "__SQLITE_COUNT__": str(sqlite_count),
    }
    script = ROLLBACK
    for placeholder, value in substitutions.items():
        script = script.replace(placeholder, value)
    if any(placeholder in script for placeholder in substitutions):
        raise RescueBlocked("Unresolved rollback template placeholder")
    return script


def create() -> Path:
    build_report_file = COMPILED / "build-report.json"
    primary.refuse_links(build_report_file)
    if not build_report_file.is_file():
        raise RescueBlocked("Pinned production build report absent")
    report = json.loads(build_report_file.read_text(encoding="utf-8"))
    if (report.get("status") != "PRODUCTION_CANDIDATE_BUILT_NOT_INSTALLED"
            or report.get("exeSha256") != EXPECTED_NEW
            or report.get("manifestSha256") != EXPECTED_REPORT
            or report.get("baseline", {}).get("pointerSha256") != EXPECTED_POINTER):
        raise RescueBlocked("Known production source witness mismatch")
    package_exe = COMPILED / "offline-update" / "Taraz.exe"
    if primary.sha(package_exe) != EXPECTED_NEW:
        raise RescueBlocked("Pinned update EXE changed")
    backup = primary.require_backup()
    baseline = report["baseline"]
    if os.name != "nt":
        raise RescueBlocked("Rollback artifact requires Windows")
    installed = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz"
    old = installed / "versions" / "1.0.0" / "Taraz.exe"
    new = installed / "versions" / "1.0.1" / "Taraz.exe"
    launcher = installed / "Run-Taraz.cmd"
    for path in (old, new, launcher):
        primary.refuse_links(path)
        if not path.is_file():
            raise RescueBlocked("Expected side-by-side installed binary missing")
    if primary.sha(old) != primary.EXPECTED_V100_SHA or primary.sha(new) != EXPECTED_NEW:
        raise RescueBlocked("Real installed binary hashes differ")
    if primary.sha(launcher) != baseline["launcherSha256"]:
        raise RescueBlocked("Installed launcher hash differs")
    script = render(
        backup_root=Path(backup["root"]),
        backup_report_sha=backup["reportSha256"],
        backup_manifest_sha=backup["manifestSha256"],
        old_exe_sha=primary.EXPECTED_V100_SHA, new_exe_sha=EXPECTED_NEW,
        launcher_sha=baseline["launcherSha256"], pre_pointer_sha=EXPECTED_POINTER,
        file_count=backup["fileCount"], total_bytes=backup["totalBytes"],
        sqlite_count=backup["sqliteValidatedCount"],
    )
    rescue_root = primary.OUTPUT / ("rollback-rescue-" + uuid.uuid4().hex[:12])
    rescue_root.mkdir(exist_ok=False)
    rescue_script = rescue_root / "Rollback-Taraz-V101.ps1"
    with rescue_script.open("x", encoding="utf-8") as file:
        file.write(script)
    manifest_file = rescue_root / "rollback-rescue-manifest.json"
    metadata = {
        "status": "ROLLBACK_RESCUE_CREATED_NOT_EXECUTED",
        "rollbackScriptSha256": primary.sha(rescue_script),
        "rollbackScript": str(rescue_script),
        "targetAfterRollback": "1.0.0",
        "expectedActiveBeforeRollback": "1.0.1",
        "installedBinarySha256": EXPECTED_NEW, "oldBinarySha256": primary.EXPECTED_V100_SHA,
        "backupManifestSha256": backup["manifestSha256"],
        "preActivationPointerSha256": EXPECTED_POINTER,
        "installedPointerChanged": False,
        "dataWritten": False, "rollbackExecuted": False,
    }
    with manifest_file.open("x", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return manifest_file


if __name__ == "__main__":
    try:
        path = create()
        print(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ROLLBACK RESCUE BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
