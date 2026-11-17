"""Create-only, SHA-pinned Taraz 1.0.3 secure offline update.

Never edits the original frozen EXE, ZIP, source or manifest and NEVER
installs to a real user profile. Native PS5.1 disposable acceptance is
implemented in tests/test_taraz_v103_secure_repackage_20261111.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import uuid
import zipfile

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
PARENT = PROJECT.parents[1]
OUTPUT_PARENT = PARENT / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.3-p1"
FROZEN = OUTPUT_PARENT / "build-eb9d4f2ab076"
FROZEN_OFFLINE = FROZEN / "offline-update"
FROZEN_ZIP = FROZEN / "Taraz-v1.0.3-P1-OFFLINE-SIDE-BY-SIDE-UPDATE.zip"
FROZEN_EXE_SHA = "e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c"
FROZEN_REPORT_SHA = "5303e16ed411d55b34aa81178a79b7e883dd4d56b7e5210ce068dffebb9fbf94"
FROZEN_MANIFEST_SHA = "0f76af740467a1630be9aca7477df5f4a920fdfc879a9aa68a29807f5ecac634"
FROZEN_ZIP_SHA = "4e46df72c488f824b9a5eb9683b8d7f32b7d1f94d4af2858f9c8623b40ca0eae"
FROZEN_SOURCE_SHA = "a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279"
V102_EXE_SHA = "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52"
ROLLBACK_SOURCE = OUTPUT_PARENT / "rollback-gate-3714fee2ca06"
ROLLBACK_FILES = {
    "Rollback-Taraz-V103-To-V102.ps1": "39b62821db04b3c2fc8de783148bf1e374113802fa1d36702cb89ab50c970c5a",
    "rollback-gate-manifest.json": "dcf868d2f483c7514ce5f80c3713850a14d78aa2e1d71d6aeb8c9700af7be1f6",
}
ORIGINAL_HASHES = {
    "Activate-Taraz-V103.ps1": "623f89e19d1e640767cf4bec6c1a2b9304a7513f4a2658faf3b67df7a3b825d5",
    "Install-Taraz-V103.ps1": "fd5cb5ddc024370cce21388c8f906bb6d46e849b628351fd65cd18cadefbb08a",
    "package-lock.json": "63d46914ebbccb59f806e9b77c58b15e8e102c227faf70806e5db6a9dca124ec",
    "package.json": "ca84f86131934ab52b9a505a4f723041c184db5ac1ace90d59eb9b48026f273f",
    "source-sha256.json": "c52add36e487dbdac07e120067c88e1f9ad1dc3272a16938d33ade5fbf5bd373",
    "Taraz.exe": FROZEN_EXE_SHA,
    "update-manifest.json": FROZEN_MANIFEST_SHA,
}
MAX_FILE_SIZE = 80 * 1024 * 1024


class SecurePackageBlocked(RuntimeError):
    pass


def regular(path: Path, *, folder: bool = False) -> Path:
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and bool(getattr(part.lstat(), "st_file_attributes", 0) & 0x400)):
            raise SecurePackageBlocked("symlink or reparse path refused: " + str(part))
    if folder:
        if not path.is_dir():
            raise SecurePackageBlocked("directory unavailable: " + str(path))
    elif not path.is_file() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > MAX_FILE_SIZE:
        raise SecurePackageBlocked("file absent/non-regular/oversized: " + str(path))
    return path


def sha(path: Path) -> str:
    regular(path)
    digester = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digester.update(chunk)
    return digester.hexdigest()


def same_sha(path: Path, expected: str, context: str) -> None:
    if not re.fullmatch("[a-f0-9]{64}", expected) or sha(path) != expected:
        raise SecurePackageBlocked("SHA mismatch: " + context)


def load_json(path: Path) -> dict:
    regular(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise SecurePackageBlocked("JSON above cap")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise SecurePackageBlocked("JSON root not object")
    return data


def frozen_preflight() -> dict:
    regular(FROZEN_OFFLINE, folder=True)
    regular(FROZEN, folder=True)
    regular(OUTPUT_PARENT, folder=True)
    same_sha(FROZEN / "build-report.json", FROZEN_REPORT_SHA, "frozen build report")
    for name, expected in ORIGINAL_HASHES.items():
        same_sha(FROZEN_OFFLINE / name, expected, "original " + name)
    same_sha(FROZEN_ZIP, FROZEN_ZIP_SHA, "frozen offline ZIP")
    with zipfile.ZipFile(FROZEN_ZIP) as z:
        if len(z.infolist()) != len(ORIGINAL_HASHES) or set(z.namelist()) != set(ORIGINAL_HASHES):
            raise SecurePackageBlocked("frozen ZIP membership changed")
        for info in z.infolist():
            if info.is_dir() or info.file_size > MAX_FILE_SIZE:
                raise SecurePackageBlocked("frozen ZIP has unexpected member type/size")
            if hashlib.sha256(z.read(info.filename)).hexdigest() != ORIGINAL_HASHES[info.filename]:
                raise SecurePackageBlocked("frozen ZIP payload mismatch: " + info.filename)
    manifest = load_json(FROZEN_OFFLINE / "update-manifest.json")
    report = load_json(FROZEN / "build-report.json")
    if not (
        manifest.get("targetVersion") == report.get("version") == "1.0.3"
        and manifest.get("peVersion") == report.get("compiled", {}).get("peVersion") == "1.0.3.0"
        and manifest.get("sourceSnapshotSha256") == report.get("sourceFreezeSha256") == FROZEN_SOURCE_SHA
        and manifest.get("exeSha256") == report.get("exeSha256") == FROZEN_EXE_SHA
        and manifest.get("installedBaselineSha256") == V102_EXE_SHA
        and manifest.get("qaOnly") is False and manifest.get("productionCandidate") is True
        and report.get("status") == "PRODUCTION_V103_P1_CANDIDATE_BUILT_NOT_INSTALLED"
        and manifest.get("sourceFilesCount") == report.get("sourceFileCount") == 131
        and manifest.get("installScriptSha256") == ORIGINAL_HASHES["Install-Taraz-V103.ps1"]
        and manifest.get("activationScriptSha256") == ORIGINAL_HASHES["Activate-Taraz-V103.ps1"]
    ):
        raise SecurePackageBlocked("frozen runtime evidence contradictory")
    return {"manifest": manifest, "report": report, "buildReportSha256": sha(FROZEN / "build-report.json")}


def rollback_companion_preflight() -> dict:
    regular(ROLLBACK_SOURCE, folder=True)
    for name, expected in ROLLBACK_FILES.items():
        same_sha(ROLLBACK_SOURCE / name, expected, "worker29 latest rollback " + name)
    witness = load_json(ROLLBACK_SOURCE / "rollback-gate-manifest.json")
    pins = witness.get("pinnedArtifacts", {})
    if not isinstance(pins, dict) or not (
        witness.get("schemaVersion") == 1
        and witness.get("application") == "Taraz"
        and witness.get("tool") == "operator-rollback"
        and witness.get("fromVersion") == "1.0.3"
        and witness.get("toVersion") == "1.0.2"
        and witness.get("frozenRun") == str(FROZEN)
        and witness.get("scriptSha256") == ROLLBACK_FILES["Rollback-Taraz-V103-To-V102.ps1"]
        and witness.get("rollbackExecuted") is False
        and witness.get("installedPointerTouched") is False
        and witness.get("operatorOnly") is True
        and witness.get("requiresApply") is True
        and pins.get("candidateExeSha256") == FROZEN_EXE_SHA
        and pins.get("candidateSourceSha256") == FROZEN_SOURCE_SHA
        and pins.get("candidateManifestSha256") == FROZEN_MANIFEST_SHA
        and pins.get("previousInstalledExeSha256") == V102_EXE_SHA
    ):
        raise SecurePackageBlocked("operator rollback provenance/pins differ")
    return {"sourceGate": str(ROLLBACK_SOURCE), "scriptSha256": ROLLBACK_FILES[
        "Rollback-Taraz-V103-To-V102.ps1"], "manifestSha256": ROLLBACK_FILES[
        "rollback-gate-manifest.json"]}


_SECURE_GUARDS = r'''Set-StrictMode -Version Latest
# Verified call-side security primitives for Windows PowerShell 5.1.
# No path to another installation is inferred from a display name.
if(-not ('TarazV103SecureLinkInfo' -as [type])) {
  try {
    Add-Type -Language CSharp -ErrorAction Stop -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class TarazV103SecureLinkInfo {
  [StructLayout(LayoutKind.Sequential)] public struct FILETIME {
    public UInt32 low;
    public UInt32 high;
  }
  [StructLayout(LayoutKind.Sequential)] public struct BY_HANDLE_FILE_INFORMATION {
    public UInt32 attrs;
    public FILETIME creation;
    public FILETIME access;
    public FILETIME write;
    public UInt32 volume;
    public UInt32 sizeHigh;
    public UInt32 sizeLow;
    public UInt32 linkCount;
    public UInt32 indexHigh;
    public UInt32 indexLow;
  }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  static extern SafeFileHandle CreateFile(string name, UInt32 access, UInt32 share,
      IntPtr security, UInt32 creation, UInt32 flags, IntPtr templateFile);
  [DllImport("kernel32.dll", SetLastError=true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  static extern bool GetFileInformationByHandle(SafeFileHandle handle,
      out BY_HANDLE_FILE_INFORMATION info);
  public static uint HardlinkCount(string filename) {
    // OPEN_REPARSE_POINT and BACKUP_SEMANTICS; read attributes only.
    using(var handle=CreateFile(filename,0x80,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) {
      if(handle.IsInvalid) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
      BY_HANDLE_FILE_INFORMATION info;
      if(!GetFileInformationByHandle(handle,out info))
        throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
      return info.linkCount;
    }
  }
}
'@
  } catch { Deny 'Cannot initialize Windows hardlink inspection' }
}
function CanonicalLocal([string]$path) {
  if([string]::IsNullOrWhiteSpace($path)) { Deny 'Empty path' }
  if($path -cnotmatch '^[A-Za-z]:\\' -or
     $path -match '(^|[\\/])\.{1,2}([\\/]|$)' -or
     $path.Substring(2).Contains(':') -or
     $path.Contains('/') -or
     $path.Contains('*') -or $path.Contains('?')) { Deny 'Unsafe path/drive/traversal' }
  $full=[IO.Path]::GetFullPath($path)
  if($full -cnotmatch '^[A-Za-z]:\\' -or $full.StartsWith('\\')) { Deny 'Nonlocal path' }
  return $full
}
function SafePath([string]$path) {
  $cursor=CanonicalLocal $path
  $count=0
  while($true) {
    if(++$count -gt 64) { Deny 'Path ancestor limit exceeded' }
    $item=Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
    if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      Deny 'Linked/junction path refused'
    }
    if($item -is [IO.FileInfo]) {
      try { $links=[TarazV103SecureLinkInfo]::HardlinkCount($item.FullName) }
      catch { Deny 'Cannot inspect hardlink count' }
      if($links -ne 1) { Deny 'Hardlinked or invalid-link-count file refused' }
      # Windows PowerShell 5.1 FileInfo.Parent does NOT enumerate ancestors.
      $parent=$item.Directory
    } elseif($item -is [IO.DirectoryInfo]) {
      $parent=$item.Parent
    } else { Deny 'Unsupported filesystem entry' }
    if($null -eq $parent) { break }
    if($parent.FullName -eq $cursor) { Deny 'Filesystem ancestor did not advance' }
    $cursor=$parent.FullName
  }
}
function RequireAbsent([string]$path) {
  $full=CanonicalLocal $path
  $existing=Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
  if($null -ne $existing -or (Test-Path -LiteralPath $full)) {
    Deny 'Existing path: create-only; never overwrite'
  }
  $parent=[IO.Path]::GetDirectoryName($full)
  SafePath $parent
}
function Digest([string]$path) {
  SafePath $path
  if(-not (Test-Path -LiteralPath $path -PathType Leaf)) { Deny 'Required file absent' }
  (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}
function CheckPackagePins {
  SafePath $PSScriptRoot
  SafePath $PSCommandPath
  $packed=Join-Path $PSScriptRoot 'update-manifest.json'
  $m=Get-Content -LiteralPath $packed -Raw -Encoding UTF8 | ConvertFrom-Json
  if($m.schemaVersion -ne 1 -or $m.targetVersion -ne '1.0.3' -or
     $m.exeSha256 -cne '__NEW_SHA__' -or
     $m.installedBaselineSha256 -cne '__OLD_SHA__' -or
     $m.sourceSnapshotSha256 -cne '__FREEZE_SHA__' -or
     $m.secureRepackage.schemaVersion -ne 1 -or
     $m.secureRepackage.originalManifestSha256 -cne '__ORIGINAL_MANIFEST_SHA__' -or
     $m.secureRepackage.hardlinkAndAncestorGuard -cne 'Win32-linkcount-and-each-ancestor') {
    Deny 'Secure candidate manifest/version/pin mismatch'
  }
  if((Digest (Join-Path $PSScriptRoot 'Install-Taraz-V103.ps1')) -cne [string]$m.installScriptSha256 -or
     (Digest (Join-Path $PSScriptRoot 'Activate-Taraz-V103.ps1')) -cne [string]$m.activationScriptSha256 -or
     (Digest (Join-Path $PSScriptRoot 'source-sha256.json')) -cne [string]$m.sourceFileManifestSha256 -or
     (Digest (Join-Path $PSScriptRoot 'package.json')) -cne [string]$m.stagedPackageSha256 -or
     (Digest (Join-Path $PSScriptRoot 'package-lock.json')) -cne [string]$m.stagedLockSha256) {
    Deny 'Secure package member hash/links mismatch'
  }
}
'''

_SECURE_BACKUP = r'''function CheckBackup([string]$root,[string]$manifestSha,[string]$reportSha) {
  if(-not $root -or $manifestSha -cnotmatch '^[0-9a-f]{64}$' -or $reportSha -cnotmatch '^[0-9a-f]{64}$') {
    Deny 'Fresh independently pinned 1.0.2 backup required'
  }
  SafePath $root
  $filesRoot=Join-Path $root 'files'
  SafePath $filesRoot
  $manifestFile=Join-Path $root 'snapshot-manifest.json'
  $reportFile=Join-Path $root 'backup-acceptance-report.json'
  if((Digest $manifestFile) -cne $manifestSha -or (Digest $reportFile) -cne $reportSha) {
    Deny 'Independent backup SHA changed'
  }
  $m=Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
  $r=Get-Content -LiteralPath $reportFile -Raw -Encoding UTF8 | ConvertFrom-Json
  if($r.status -ne 'VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING' -or
     $r.installedBefore -ne '1.0.2' -or $r.installedAfter -ne '1.0.2' -or
     $r.backup.backupRoot -cne $root -or
     $r.backup.independentReadback -ne $true -or
     $r.backup.manifestSha256 -cne $manifestSha -or
     $m.schemaVersion -ne 1 -or $m.verifiedNoOverwrite -ne $true -or
     $m.allFilesIncluded -ne $true) { Deny 'Backup evidence incomplete' }
  $entries=@($m.files.PSObject.Properties)
  $sql=@($m.sqliteChecks.PSObject.Properties)
  if($entries.Count -lt 1 -or $entries.Count -gt 2000 -or
     $entries.Count -ne [int]$m.fileCount -or
     $entries.Count -ne [int]$r.backup.fileCount -or
     $sql.Count -lt 1 -or $sql.Count -ne [int]$r.backup.sqliteValidatedCount) {
    Deny 'Backup file or SQLite count mismatch'
  }
  $total=0L
  foreach($entry in $entries) {
    $relative=[string]$entry.Name
    if($relative -cnotmatch '^(roaming|local|bridge)/' -or
       $relative -match '(^|/)\.{1,2}(/|$)' -or
       $relative.Contains(':') -or $relative.Contains('\\') -or
       $relative.Contains('*') -or $relative.Contains('?')) {
      Deny 'Backup record contains unsafe relative name'
    }
    $file=Join-Path $filesRoot $relative.Replace('/',[IO.Path]::DirectorySeparatorChar)
    $digest=Digest $file
    $info=Get-Item -LiteralPath $file -Force -ErrorAction Stop
    if($info.Length -ne [long]$entry.Value.bytes -or
       $digest -cne [string]$entry.Value.sha256) { Deny 'Backup record changed' }
    $total += $info.Length
    if($total -gt 314572800) { Deny 'Backup byte limit exceeded' }
  }
  # Use manual bounded enumeration: never recursively follow unverified links.
  $folders=New-Object 'System.Collections.Generic.Queue[string]'
  $folders.Enqueue($filesRoot)
  $found=0
  $inspected=0
  while($folders.Count -gt 0) {
    $directory=$folders.Dequeue()
    SafePath $directory
    foreach($item in @(Get-ChildItem -LiteralPath $directory -Force -ErrorAction Stop)) {
      $inspected++
      if($inspected -gt 6000) { Deny 'Backup enumeration limit exceeded' }
      SafePath $item.FullName
      if($item -is [IO.DirectoryInfo]) { $folders.Enqueue($item.FullName) }
      elseif($item -is [IO.FileInfo]) { $found++ }
      else { Deny 'Unexpected backup entry type' }
    }
  }
  if($found -ne $entries.Count -or $total -ne [long]$m.totalBytes -or
     $total -ne [long]$r.backup.totalBytes) { Deny 'Backup files or byte totals mismatch' }
}
'''

_INSTALL_TAIL = r'''CheckPackagePins
if(-not $env:LOCALAPPDATA){Deny 'LOCALAPPDATA unavailable'}
$local=CanonicalLocal $env:LOCALAPPDATA
SafePath $local
$root=Join-Path $local 'Programs\\Taraz'
$versions=Join-Path $root 'versions'
$old=Join-Path $versions '1.0.2\\Taraz.exe'
$newDir=Join-Path $versions '1.0.3'
$new=Join-Path $newDir 'Taraz.exe'
$pointer=Join-Path $root 'current-version.txt'
$launcher=Join-Path $root 'Run-Taraz.cmd'
$payload=Join-Path $PSScriptRoot 'Taraz.exe'
SafePath $root
SafePath $versions
SafePath $old
SafePath $pointer
SafePath $launcher
SafePath $payload
CheckNoTaraz
if((Digest $old) -cne '__OLD_SHA__'){Deny 'Installed v1.0.2 SHA mismatch'}
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -cne '1.0.2'){
  Deny 'Installed pointer is not exactly 1.0.2'
}
if((Get-Content -LiteralPath $launcher -Raw -Encoding UTF8) -cnotmatch 'versions\\%TARAZ_VERSION%\\Taraz\.exe'){
  Deny 'Versioned launcher contract mismatch'
}
if((Digest $payload) -cne '__NEW_SHA__'){Deny 'Secure payload SHA mismatch'}
CheckBackup $BackupRoot $BackupManifestSha256 $BackupReportSha256
if($VerifyExisting) {
  SafePath $newDir
  if((Digest $new) -cne '__NEW_SHA__') { Deny 'Existing v1.0.3 EXE SHA mismatch' }
  Write-Output 'EXISTING_SIDE_BY_SIDE_1.0.3_VERIFIED'
  exit 0
}
RequireAbsent $newDir
if(-not $Apply) {Write-Output 'READY_FOR_CREATE_ONLY_1.0.3_INSTALL'; exit 0}
# Re-check right before creating a new version directory. Never overwrite.
CheckNoTaraz
SafePath $versions
RequireAbsent $newDir
New-Item -ItemType Directory -Path $newDir -ErrorAction Stop | Out-Null
SafePath $newDir
RequireAbsent $new
$source=[IO.File]::Open($payload,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
try {
  $target=[IO.File]::Open($new,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {$source.CopyTo($target);$target.Flush($true)} finally {$target.Dispose()}
} finally {$source.Dispose()}
if((Digest $new) -cne '__NEW_SHA__') { Deny 'Installed EXE readback SHA/hardlink failed' }
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -cne '1.0.2') {
  Deny 'Installed pointer changed during side-by-side install'
}
Write-Output 'INSTALLED_SIDE_BY_SIDE_1.0.3_POINTER_REMAINS_1.0.2'
'''

_ACTIVATE_TAIL = r'''CheckPackagePins
if(-not $env:LOCALAPPDATA){Deny 'LOCALAPPDATA unavailable'}
$local=CanonicalLocal $env:LOCALAPPDATA
SafePath $local
$root=Join-Path $local 'Programs\\Taraz'
$versions=Join-Path $root 'versions'
$old=Join-Path $versions '1.0.2\\Taraz.exe'
$new=Join-Path $versions '1.0.3\\Taraz.exe'
$pointer=Join-Path $root 'current-version.txt'
$launcher=Join-Path $root 'Run-Taraz.cmd'
$payload=Join-Path $PSScriptRoot 'Taraz.exe'
$installer=Join-Path $PSScriptRoot 'Install-Taraz-V103.ps1'
$oldPointer=Join-Path $root 'current-version-pre-1.0.3.txt'
$launcherBackup=Join-Path $root 'Run-Taraz-pre-1.0.3.cmd'
$pending=Join-Path $root 'current-version-1.0.3-pending.txt'
foreach($path in @($root,$versions,$old,$new,$pointer,$launcher,$payload,$installer)) {
  SafePath $path
}
CheckNoTaraz
if((Digest $old) -cne '__OLD_SHA__' -or (Digest $new) -cne '__NEW_SHA__' -or
   (Digest $payload) -cne '__NEW_SHA__') { Deny 'Activation old/new/payload EXE pin mismatch' }
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -cne '1.0.2') {
  Deny 'Installed pointer not v1.0.2'
}
if((Get-Content -LiteralPath $launcher -Raw -Encoding UTF8) -cnotmatch 'versions\\%TARAZ_VERSION%\\Taraz\.exe'){
  Deny 'Versioned launcher contract mismatch'
}
CheckBackup $BackupRoot $BackupManifestSha256 $BackupReportSha256
RequireAbsent $oldPointer
RequireAbsent $pending
RequireAbsent $launcherBackup
& $installer -VerifyExisting -BackupRoot $BackupRoot -BackupManifestSha256 $BackupManifestSha256 -BackupReportSha256 $BackupReportSha256 | Out-Null
if(-not $Apply) {Write-Output 'READY_TO_ACTIVATE_1.0.3_OLD_VERSION_RETAINED'; exit 0}
CheckNoTaraz
SafePath $pointer
SafePath $launcher
RequireAbsent $pending
RequireAbsent $oldPointer
RequireAbsent $launcherBackup
$launcherDigest=Digest $launcher
$src=[IO.File]::Open($launcher,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
try {
  $dst=[IO.File]::Open($launcherBackup,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {$src.CopyTo($dst);$dst.Flush($true)} finally {$dst.Dispose()}
} finally {$src.Dispose()}
if((Digest $launcherBackup) -cne $launcherDigest) { Deny 'Launcher backup SHA failed' }
[IO.File]::WriteAllText($pending,"1.0.3`r`n",[Text.UTF8Encoding]::new($false))
SafePath $pending
CheckNoTaraz
if((Digest $old) -cne '__OLD_SHA__' -or (Digest $new) -cne '__NEW_SHA__' -or
   (Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -cne '1.0.2') {
   Deny 'Activation changed before atomic pointer replace'
}
[IO.File]::Replace($pending,$pointer,$oldPointer,$true)
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -cne '1.0.3' -or
   (Get-Content -LiteralPath $oldPointer -Raw -Encoding UTF8).Trim() -cne '1.0.2' -or
   (Digest $launcher) -cne $launcherDigest -or
   (Digest $launcherBackup) -cne $launcherDigest) {
  Deny 'Activation pointer/launcher backup readback failed'
}
Write-Output 'ACTIVATED_1.0.3_VERSION_1.0.2_RETAINED'
'''


def secure_ps_scripts() -> dict[str, str]:
    """New scripts retain protocol but replace vulnerable SafePath wholesale."""
    # Cross-check source script before deriving each new one; fail closed if
    # original source changes. The hardlink and ancestor helper is shared.
    for name in ("Install-Taraz-V103.ps1", "Activate-Taraz-V103.ps1"):
        source = (FROZEN_OFFLINE / name).read_text(encoding="utf-8")
        if ("$item=$item.Parent" not in source or
                "function SafePath([string]$path)" not in source):
            raise SecurePackageBlocked("Unexpected original unsafe script shape: " + name)
    header = "$ErrorActionPreference='Stop'\n" + (
        "function Deny([string]$reason) { throw ('TARAZ V103 SECURE UPDATE BLOCKED: ' + $reason) }\n")
    security = (_SECURE_GUARDS + "\n" + _SECURE_BACKUP + "\n" +
                "function CheckNoTaraz {\n" +
                "try { $processes=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.Name -match '^Taraz(?:-v[0-9.]+.*)?\\.exe$' }) }\n" +
                "catch { Deny 'Cannot establish Taraz process inactivity' }\n" +
                "if($processes.Count -gt 0) { Deny 'Taraz is running' }\n}\n")
    variables = {
        "__NEW_SHA__": FROZEN_EXE_SHA,
        "__OLD_SHA__": V102_EXE_SHA,
        "__FREEZE_SHA__": FROZEN_SOURCE_SHA,
        "__ORIGINAL_MANIFEST_SHA__": FROZEN_MANIFEST_SHA,
    }
    outputs = {}
    for name, param, tail in (
        ("Install-Taraz-V103.ps1",
         "param([switch]$Apply,[switch]$VerifyExisting,[string]$BackupRoot='',"
         "[string]$BackupManifestSha256='', [string]$BackupReportSha256='')\n",
         _INSTALL_TAIL),
        ("Activate-Taraz-V103.ps1",
         "param([switch]$Apply,[string]$BackupRoot='',"
         "[string]$BackupManifestSha256='', [string]$BackupReportSha256='')\n",
         _ACTIVATE_TAIL),
    ):
        value = param + header + security + "\n" + tail
        for token, replacement in variables.items():
            value = value.replace(token, replacement)
        if "__" in value or "$item=$item.Parent" in value or "Start-Process" in value:
            raise SecurePackageBlocked("Incomplete/unsafe secure installer script")
        outputs[name] = value
    return outputs


def verify_secure_output(folder: Path, *, expect_source: bool = True) -> dict:
    """Rehash every packed byte against new manifest and old immutable source."""
    folder = regular(folder, folder=True)
    if not folder.parent == OUTPUT_PARENT or not folder.name.startswith("secure-repackage-"):
        raise SecurePackageBlocked("untrusted output folder")
    source = frozen_preflight() if expect_source else None
    offline = regular(folder / "offline-update", folder=True)
    manifest = load_json(offline / "update-manifest.json")
    original = source["manifest"] if source else load_json(FROZEN_OFFLINE / "update-manifest.json")
    metadata = manifest.get("secureRepackage", {})
    if not isinstance(metadata, dict) or metadata.get("schemaVersion") != 1:
        raise SecurePackageBlocked("missing secure repackage metadata")
    if not (metadata.get("originalManifestSha256") == FROZEN_MANIFEST_SHA and
            metadata.get("hardlinkAndAncestorGuard") == "Win32-linkcount-and-each-ancestor"):
        raise SecurePackageBlocked("security guard manifest changed")
    companion = rollback_companion_preflight()
    if metadata.get("rollbackCompanion") != companion:
        raise SecurePackageBlocked("secure package rollback companion metadata drift")
    companion_dir = regular(folder / "operator-rollback", folder=True)
    if set(path.name for path in companion_dir.iterdir()) != set(ROLLBACK_FILES):
        raise SecurePackageBlocked("operator rollback companion inventory drift")
    for name, expected_sha in ROLLBACK_FILES.items():
        same_sha(companion_dir / name, expected_sha, "operator rollback companion " + name)
    for k, oldval in original.items():
        if k in {"installScriptSha256", "activationScriptSha256"}:
            continue
        if manifest.get(k) != oldval:
            raise SecurePackageBlocked("original immutable manifest value changed: " + k)
    script_hashes = {
        "Install-Taraz-V103.ps1": manifest.get("installScriptSha256"),
        "Activate-Taraz-V103.ps1": manifest.get("activationScriptSha256"),
    }
    expected = dict(ORIGINAL_HASHES)
    expected.update(script_hashes)
    expected["update-manifest.json"] = sha(offline / "update-manifest.json")
    if set(path.name for path in offline.iterdir()) != set(expected):
        raise SecurePackageBlocked("unpacked member inventory mismatch")
    for name, expected_sha in expected.items():
        same_sha(offline / name, expected_sha, "secure payload " + name)
        if name not in script_hashes and name != "update-manifest.json":
            same_sha(offline / name, ORIGINAL_HASHES[name], "original asset parity " + name)
    for name, value in secure_ps_scripts().items():
        if (offline / name).read_text(encoding="utf-8") != value:
            raise SecurePackageBlocked("unexpected secure script contents: " + name)
    archive = folder / "Taraz-v1.0.3-P1-SECURE-OFFLINE-UPDATE.zip"
    with zipfile.ZipFile(regular(archive)) as z:
        members = z.infolist()
        if len(members) != 7 or set(z.namelist()) != set(expected):
            raise SecurePackageBlocked("secure ZIP membership mismatch")
        for info in members:
            if info.is_dir() or info.file_size > MAX_FILE_SIZE:
                raise SecurePackageBlocked("invalid member in secure ZIP")
            if hashlib.sha256(z.read(info.filename)).hexdigest() != expected[info.filename]:
                raise SecurePackageBlocked("secure ZIP byte mismatch " + info.filename)
    return {
        "status": "SECURE_REPACKAGE_BYTE_PINS_VERIFIED",
        "folder": str(folder), "exeSha256": sha(offline / "Taraz.exe"),
        "originalExeSha256": FROZEN_EXE_SHA, "originalZipSha256": FROZEN_ZIP_SHA,
        "originalManifestSha256": FROZEN_MANIFEST_SHA,
        "newManifestSha256": expected["update-manifest.json"],
        "secureZipSha256": sha(archive),
        "operatorRollbackCompanion": companion,
        "scriptSha256": script_hashes, "zipEntriesVerified": len(expected),
        "productionInstalled": False,
        "signatureApproved": False, "releaseApproved": False,
    }


def build() -> Path:
    if os.name != "nt":
        raise SecurePackageBlocked("requires Windows")
    existing = frozen_preflight()
    rollback_companion_preflight()
    regular(OUTPUT_PARENT, folder=True)
    scripts = secure_ps_scripts()
    folder = OUTPUT_PARENT / ("secure-repackage-" + uuid.uuid4().hex[:12])
    folder.mkdir(exist_ok=False)
    try:
        offline = folder / "offline-update"
        offline.mkdir(exist_ok=False)
        companion_directory = folder / "operator-rollback"
        companion_directory.mkdir(exist_ok=False)
        for name in ROLLBACK_FILES:
            with (ROLLBACK_SOURCE / name).open("rb") as src, (companion_directory / name).open("xb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
        for name in ORIGINAL_HASHES:
            if name in ("update-manifest.json", *scripts.keys()):
                continue
            with (FROZEN_OFFLINE / name).open("rb") as src, (offline / name).open("xb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
        for name, value in scripts.items():
            with (offline / name).open("x", encoding="utf-8", newline="\n") as out:
                out.write(value)
        manifest = dict(existing["manifest"])
        manifest["installScriptSha256"] = sha(offline / "Install-Taraz-V103.ps1")
        manifest["activationScriptSha256"] = sha(offline / "Activate-Taraz-V103.ps1")
        manifest["secureRepackage"] = {
            "schemaVersion": 1,
            "originalManifestSha256": FROZEN_MANIFEST_SHA,
            "originalZipSha256": FROZEN_ZIP_SHA,
            "originalBuildReportSha256": existing["buildReportSha256"],
            "hardlinkAndAncestorGuard": "Win32-linkcount-and-each-ancestor",
            "launcherBackupName": "Run-Taraz-pre-1.0.3.cmd",
            "pathPolicy": "local-absolute-no-reparse-no-hardlinks",
            "sourceUnmodified": True,
            "rollbackCompanion": rollback_companion_preflight(),
            "installed": False,
            "disposablePS51Tested": False,
            "productionApproved": False,
        }
        with (offline / "update-manifest.json").open("x", encoding="utf-8", newline="\n") as dst:
            json.dump(manifest, dst, ensure_ascii=True, indent=2, sort_keys=True)
            dst.write("\n")
        package = folder / "Taraz-v1.0.3-P1-SECURE-OFFLINE-UPDATE.zip"
        with zipfile.ZipFile(package, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for item in sorted(offline.iterdir()):
                z.write(item, item.name)
        report = verify_secure_output(folder)
        report["status"] = "SECURE_REPACKAGE_BUILT_NOT_INSTALLED_OR_APPROVED"
        with (folder / "secure-repackage-report.json").open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=True, sort_keys=True, indent=2)
            file.write("\n")
    except BaseException:
        # Preserve evidence of any failed incomplete run; do not silently
        # delete potentially interesting create-only build artifacts.
        raise
    return folder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true")
    group.add_argument("--verify", type=Path)
    args = parser.parse_args()
    try:
        if args.build:
            folder = build()
            result = verify_secure_output(folder)
        else:
            result = verify_secure_output(args.verify)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
        return 0
    except (SecurePackageBlocked, ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "REJECTED", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    sys.exit(main())
