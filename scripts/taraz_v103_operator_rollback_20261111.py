"""Generate a pinned, operator-only Taraz 1.0.3 -> 1.0.2 rollback gate.

Create-only output lives under the existing isolated v1.0.3 P1 candidate root.
The generator neither runs its PowerShell output nor edits installed Taraz,
finance profiles, or the frozen release candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True

SOURCE = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (SOURCE.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110"
               / "taraz-v1.0.3-p1")
FROZEN_RUN = OUTPUT_ROOT / "build-eb9d4f2ab076"
FROZEN_EXE = FROZEN_RUN / "offline-update" / "Taraz.exe"
FROZEN_MANIFEST = FROZEN_RUN / "offline-update" / "update-manifest.json"
FROZEN_REPORT = FROZEN_RUN / "build-report.json"
FROZEN_EXE_SHA = "e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c"
FROZEN_MANIFEST_SHA = "0f76af740467a1630be9aca7477df5f4a920fdfc879a9aa68a29807f5ecac634"
FROZEN_SOURCE_SHA = "a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279"
OLD_EXE_SHA = "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52"
SCRIPT_NAME = "Rollback-Taraz-V103-To-V102.ps1"


class RollbackBlocked(RuntimeError):
    """Any unrecognized or changed prerequisite prevents generation."""


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def refuse_links(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and
                getattr(item.lstat(), "st_file_attributes", 0) & 0x400):
            raise RollbackBlocked(f"Unsafe symlink/reparse point: {item}")


def frozen_candidate_preflight() -> dict:
    """Only immutable release artifact metadata and EXE, no live account data."""
    for path in (OUTPUT_ROOT, FROZEN_RUN, FROZEN_EXE, FROZEN_MANIFEST, FROZEN_REPORT):
        refuse_links(path)
    for path in (FROZEN_EXE, FROZEN_MANIFEST, FROZEN_REPORT):
        if not path.is_file():
            raise RollbackBlocked("Pinned frozen candidate artifact missing: " + str(path))
    if sha(FROZEN_EXE) != FROZEN_EXE_SHA or sha(FROZEN_MANIFEST) != FROZEN_MANIFEST_SHA:
        raise RollbackBlocked("Frozen v1.0.3 candidate executable or manifest changed")
    manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
    report = json.loads(FROZEN_REPORT.read_text(encoding="utf-8"))
    if (manifest.get("targetVersion") != "1.0.3"
            or manifest.get("peVersion") != "1.0.3.0"
            or manifest.get("installedBaselineVersion") != "1.0.2"
            or manifest.get("exeSha256") != FROZEN_EXE_SHA
            or manifest.get("installedBaselineSha256") != OLD_EXE_SHA
            or manifest.get("sourceSnapshotSha256") != FROZEN_SOURCE_SHA
            or report.get("status") != "PRODUCTION_V103_P1_CANDIDATE_BUILT_NOT_INSTALLED"
            or report.get("exeSha256") != FROZEN_EXE_SHA
            or report.get("sourceFreezeSha256") != FROZEN_SOURCE_SHA):
        raise RollbackBlocked("Frozen v1.0.3 release report/manifest contract mismatch")
    return {"candidateExeSha256": FROZEN_EXE_SHA,
            "candidateManifestSha256": FROZEN_MANIFEST_SHA,
            "candidateSourceSha256": FROZEN_SOURCE_SHA,
            "previousInstalledExeSha256": OLD_EXE_SHA,
            "baseVersion": "1.0.2", "currentVersionRequired": "1.0.3"}


_PS_TEMPLATE = r'''param([switch]$Apply)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

function Deny([string]$reason) { throw ('TARAZ 1.0.3 ROLLBACK BLOCKED: ' + $reason) }

function SafeExisting([string]$path) {
  if([string]::IsNullOrWhiteSpace($path)) { Deny 'Empty required path' }
  $absolute=[IO.Path]::GetFullPath($path)
  if($absolute -notmatch '^[a-zA-Z]:\\' -or $absolute.StartsWith('\\')) {
    Deny 'Untrusted non-local path'
  }
  try { $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop }
  catch { Deny ('Missing or inaccessible required path: ' + $path) }
  while($null -ne $item) {
    if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      Deny ('Linked/junction path refused: ' + $path)
    }
    if($item -is [IO.FileInfo]) {
      $item=$item.Directory
    } else {
      $item=$item.Parent
    }
  }
}

function CheckSingleHardlink([string]$path) {
  SafeExisting $path
  if(-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    Deny 'Cannot prove regular unlinked file'
  }
  # NTFS hardlinks do not carry the ReparsePoint bit. Prove exactly one link
  # through the Windows filesystem, and fail closed when unavailable.
  $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
  if([string]$item.LinkType -eq 'HardLink') {
    Deny ('Hardlink forbidden: ' + $path)
  }
  try {
    $links=@(& fsutil.exe hardlink list $path 2>$null)
    if($LASTEXITCODE -ne 0) { Deny 'Cannot independently inspect hardlink count' }
    $names=@($links | Where-Object { [string]$_ -and ([string]$_).Trim().StartsWith('\') })
    if($names.Count -ne 1) { Deny ('Hardlink count not exactly one: ' + $path) }
  } catch {
    Deny ('Cannot independently prove a single hardlink: ' + $path)
  }
}

function RequireAbsent([string]$path) {
  $item=Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
  if($null -ne $item -or (Test-Path -LiteralPath $path)) {
    Deny ('Already exists; never overwrite: ' + $path)
  }
}

function Digest([string]$path) {
  SafeExisting $path
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)) { Deny ('Not a regular file: ' + $path) }
  return (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}

function CheckNoTaraz {
  try {
    $processes=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
      $_.Name -match '^Taraz(?:-v[0-9.]+.*)?\.exe$'
    })
  } catch { Deny 'Cannot establish Taraz process inactivity' }
  if($processes.Count -gt 0) { Deny 'Taraz process is running' }
}

function CheckVersion([string]$path,[int]$build) {
  SafeExisting $path
  $version=(Get-Item -LiteralPath $path -ErrorAction Stop).VersionInfo
  if($version.FileMajorPart -ne 1 -or $version.FileMinorPart -ne 0 -or
     $version.FileBuildPart -ne $build -or $version.FilePrivatePart -ne 0 -or
     $version.ProductMajorPart -ne 1 -or $version.ProductMinorPart -ne 0 -or
     $version.ProductBuildPart -ne $build -or $version.ProductPrivatePart -ne 0) {
    Deny ('Invalid native PE version expected 1.0.' + $build + '.0')
  }
}

function CheckWriteRights([string]$path,[System.Security.AccessControl.FileSystemRights]$required) {
  SafeExisting $path
  $info=Get-Item -LiteralPath $path -Force -ErrorAction Stop
  if(($info.Attributes -band [IO.FileAttributes]::ReadOnly) -ne 0) {
    Deny ('Path is read-only: ' + $path)
  }
  try {
    $acl=Get-Acl -LiteralPath $path -ErrorAction Stop
    $user=[System.Security.Principal.WindowsIdentity]::GetCurrent()
    $members=@($user.User.Value)
    $members+=@($user.Groups | ForEach-Object { $_.Value })
    $allow=[int64]0
    $deny=[int64]0
    foreach($entry in $acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])) {
      if($members -notcontains $entry.IdentityReference.Value) { continue }
      $rights=[int64]$entry.FileSystemRights
      if($entry.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Deny) {
        $deny=($deny -bor $rights)
      } else {
        $allow=($allow -bor $rights)
      }
    }
    $need=[int64]$required
    if(($deny -band $need) -ne 0 -or ($allow -band $need) -ne $need) {
      Deny ('Insufficient or denied ACL for pointer rollback: ' + $path)
    }
  } catch {
    Deny ('Cannot prove writable ACL: ' + $path)
  }
}

if(-not $env:LOCALAPPDATA) { Deny 'LOCALAPPDATA missing' }
if($env:LOCALAPPDATA -notmatch '^[a-zA-Z]:\\') { Deny 'LOCALAPPDATA must be a local absolute directory' }
$root=Join-Path $env:LOCALAPPDATA 'Programs\Taraz'
$versions=Join-Path $root 'versions'
$oldDir=Join-Path $versions '1.0.2'
$newDir=Join-Path $versions '1.0.3'
$old=Join-Path $oldDir 'Taraz.exe'
$new=Join-Path $newDir 'Taraz.exe'
$pointer=Join-Path $root 'current-version.txt'
$launcher=Join-Path $root 'Run-Taraz.cmd'
$activationBackup=Join-Path $root 'current-version-pre-1.0.3.txt'
$rollbackBackup=Join-Path $root 'current-version-pre-rollback-1.0.3.txt'
$pending=Join-Path $root 'current-version-rollback-to-1.0.2-pending.txt'

function VerifyState {
  foreach($path in @($root,$versions,$oldDir,$newDir,$old,$new,$pointer,
                      $launcher,$activationBackup)) { SafeExisting $path }
  foreach($path in @($old,$new,$pointer,$launcher,$activationBackup)) {
    CheckSingleHardlink $path
  }
  RequireAbsent $rollbackBackup
  RequireAbsent $pending
  CheckNoTaraz
  if((Digest $old) -cne '__OLD_SHA__') { Deny 'Original v1.0.2 binary hash changed' }
  if((Digest $new) -cne '__NEW_SHA__') { Deny 'Current v1.0.3 binary hash changed' }
  CheckVersion $old 2
  CheckVersion $new 3
  if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8 -ErrorAction Stop).Trim() -cne '1.0.3') {
    Deny 'Current pointer is not precisely 1.0.3'
  }
  if((Get-Content -LiteralPath $activationBackup -Raw -Encoding UTF8 -ErrorAction Stop).Trim() -cne '1.0.2') {
    Deny 'Original 1.0.2 pointer backup missing or modified'
  }
  $launch=Get-Content -LiteralPath $launcher -Raw -ErrorAction Stop
  if($launch -cnotmatch 'versions\\%TARAZ_VERSION%\\Taraz\.exe') {
    Deny 'Versioned launcher contract changed'
  }
  # Get-Acl is read-only. This gate requires explicit current-token rights
  # for the atomic pointer replacement and backup creation.
  CheckWriteRights $root ([System.Security.AccessControl.FileSystemRights]::Write)
  $needed=[System.Security.AccessControl.FileSystemRights]::Write -bor
          [System.Security.AccessControl.FileSystemRights]::Delete
  CheckWriteRights $pointer $needed
}

VerifyState
if(-not $Apply) {
  Write-Output 'READY_FOR_OPERATOR_ROLLBACK_1.0.3_TO_1.0.2_NO_CHANGES'
  exit 0
}

# Recheck everything immediately before the only planned mutation.
VerifyState
$utf8=[Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($pending,"1.0.2`r`n",$utf8)
try {
  SafeExisting $pending
  if((Get-Content -LiteralPath $pending -Raw -Encoding UTF8).Trim() -cne '1.0.2') {
    Deny 'Pending rollback pointer bytes invalid'
  }
  CheckNoTaraz
  foreach($path in @($old,$new,$pointer,$launcher,$activationBackup)) {
    CheckSingleHardlink $path
  }
  if((Digest $old) -cne '__OLD_SHA__' -or (Digest $new) -cne '__NEW_SHA__') {
    Deny 'Executable bytes changed during pointer switch'
  }
  if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -cne '1.0.3') {
    Deny 'Pointer changed before atomic replacement'
  }
  if((Get-Content -LiteralPath $activationBackup -Raw -Encoding UTF8).Trim() -cne '1.0.2') {
    Deny 'Original activation backup changed during pointer switch'
  }
  RequireAbsent $rollbackBackup
  [IO.File]::Replace($pending,$pointer,$rollbackBackup,$true)
} finally {
  # Only remove this script's own temporary pointer if File.Replace failed.
  if(Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending -Force -ErrorAction Stop }
}

if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -cne '1.0.2' -or
   (Get-Content -LiteralPath $rollbackBackup -Raw -Encoding UTF8).Trim() -cne '1.0.3' -or
   (Digest $old) -cne '__OLD_SHA__' -or (Digest $new) -cne '__NEW_SHA__' -or
   (Get-Content -LiteralPath $activationBackup -Raw -Encoding UTF8).Trim() -cne '1.0.2') {
  Deny 'Atomic pointer replacement completed but final readback failed: inspect manually'
}
Write-Output 'ROLLED_BACK_POINTER_TO_1.0.2_BOTH_BINARIES_RETAINED'
'''


def powershell_script() -> str:
    rendered = _PS_TEMPLATE.replace("__OLD_SHA__", OLD_EXE_SHA).replace("__NEW_SHA__", FROZEN_EXE_SHA)
    if "__OLD_SHA__" in rendered or "__NEW_SHA__" in rendered:
        raise RollbackBlocked("Unresolved release rollback pin")
    if "param([switch]$Apply)" not in rendered or "if(-not $Apply)" not in rendered:
        raise RollbackBlocked("No safe operator switch contract")
    return rendered


def generate() -> Path:
    if os.name != "nt":
        raise RollbackBlocked("Native Windows required for operator rollback candidate")
    pins = frozen_candidate_preflight()
    refuse_links(OUTPUT_ROOT)
    if not OUTPUT_ROOT.is_dir():
        raise RollbackBlocked("Frozen release output parent absent")
    rendered = powershell_script()
    output = OUTPUT_ROOT / ("rollback-gate-" + uuid.uuid4().hex[:12])
    refuse_links(output)
    output.mkdir(exist_ok=False)
    script = output / SCRIPT_NAME
    with script.open("x", encoding="utf-8", newline="\n") as file:
        file.write(rendered)
    manifest = {
        "schemaVersion": 1, "application": "Taraz", "tool": "operator-rollback",
        "fromVersion": "1.0.3", "toVersion": "1.0.2", "operatorOnly": True,
        "createdOnly": True, "rollbackExecuted": False, "profilesTouched": False,
        "installedPointerTouched": False, "requiresApply": True,
        "pointerBackupRequired": "current-version-pre-1.0.3.txt",
        "rollbackPointerBackup": "current-version-pre-rollback-1.0.3.txt",
        "scriptName": SCRIPT_NAME, "scriptSha256": sha(script),
        "pinnedArtifacts": pins, "frozenRun": str(FROZEN_RUN),
    }
    manifest_file = output / "rollback-gate-manifest.json"
    with manifest_file.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if sha(script) != manifest["scriptSha256"]:
        raise RollbackBlocked("Script readback SHA mismatch")
    return manifest_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true",
                        help="Create a new isolated rollback gate; does not run PowerShell")
    parser.add_argument("--preflight", action="store_true",
                        help="Read-only frozen candidate SHA/manifest checks")
    args = parser.parse_args()
    try:
        if args.preflight:
            print(json.dumps(frozen_candidate_preflight(), indent=2))
            return 0
        if not args.generate:
            parser.print_help()
            return 0
        manifest = generate()
        result = json.loads(manifest.read_text(encoding="utf-8"))
        print(json.dumps({"status": "OPERATOR_ROLLBACK_GATE_CREATED_NOT_EXECUTED",
                          "root": str(manifest.parent), "script": str(manifest.parent / SCRIPT_NAME),
                          "scriptSha256": result["scriptSha256"],
                          "manifestSha256": sha(manifest)}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"TARAZ ROLLBACK GATE BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
