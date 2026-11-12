"""Inspect ONLY a SHA-pinned orphan QA WebView on its own Win32 desktop.

Read-only: no keyboard/mouse, window close, process termination, finance write,
global UI automation or desktop switch. The offline clone stays untouched.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import psutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v103_native_gui_20261111 as native

PID = 23868
DESKTOP = "TarazNativeQA_0144fa507b4344"
EXPECTED_EXE = (ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" /
                "taraz-v1.0.6-aaas" / "build-250eead995ca" / "binary" / "Taraz.exe")
SHA = "ca290b6c250be0d2c09c92502426d0649343255a019dd1a93f2c2cb18671d308"
WORK = (ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" /
        "taraz-v1.0.6-aaas" / "current-source-native-input-probe-20261112" /
        "qa-final-native-0ed3b7f7994c")

PRIVATE_POWERSHELL = r'''
param([Parameter(Mandatory=$true)][string]$OwnerIds,
      [Parameter(Mandatory=$true)][string]$ResultFile,
      [switch]$Discard)
$ErrorActionPreference='Stop'
$out=@{status='INITIAL';ownedRootCount=0;ownedWindowCount=0;
  unsavedDialogCandidateCount=0;confirmButtons=@{};
  knownDiscardPromptMatched=$false;
  inspectedOnly=(-not $Discard);noInputSent=$true;gracefulDiscardInvoked=$false}
try {
 Add-Type -AssemblyName UIAutomationClient
 Add-Type -AssemblyName UIAutomationTypes
 $ids=@($OwnerIds.Split(',')|ForEach-Object{[int]$_})
 $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll(
  [System.Windows.Automation.TreeScope]::Children,
  [System.Windows.Automation.Condition]::TrueCondition)
 $ours=@($windows | Where-Object { $ids -contains [int]$_.Current.ProcessId })
 $out.ownedWindowCount=$ours.Count
 $out.ownedRootCount=@($ours|Where-Object{$_.Current.Name -like '*تراز*'}).Count
 $names=@('Yes','No','OK','Cancel','بله','خیر','تأیید','انصراف','لغو',
           'Discard','Leave','Close','Continue')
 $safeDiscardDialogs=New-Object System.Collections.ArrayList
 foreach($window in $ours){
   if($window.Current.ControlType -ne [System.Windows.Automation.ControlType]::Window){continue}
   $buttons=$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
   $prompts=@($buttons|Where-Object{
     ($_.Current.Name -match 'تغییرات را کنار بگذاریم|هنوز ذخیره نشده|پنجره را ببندیم') -and
     $ids -contains [int]$_.Current.ProcessId
   })
   if($prompts.Count -gt 0){$out.knownDiscardPromptMatched=$true}
   $interesting=@($buttons|Where-Object{
     $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
     $_.Current.IsEnabled -and $names -contains $_.Current.Name -and
     $ids -contains [int]$_.Current.ProcessId
   })
   if($interesting.Count -gt 0){
    $out.unsavedDialogCandidateCount++
    foreach($button in $interesting){
      $name=$button.Current.Name
      $out.confirmButtons[$name]=1+([int]$out.confirmButtons[$name])
    }
   }
   if($prompts.Count -gt 0 -and
     @($interesting|Where-Object{$_.Current.Name -eq 'OK'}).Count -eq 1 -and
     @($interesting|Where-Object{$_.Current.Name -eq 'Cancel'}).Count -eq 1){
     [void]$safeDiscardDialogs.Add(@($interesting|Where-Object{$_.Current.Name -eq 'OK'})[0])
   }
 }
 if($Discard){
  if($out.ownedRootCount -ne 1 -or $out.unsavedDialogCandidateCount -ne 1 -or
     $safeDiscardDialogs.Count -ne 1 -or -not $out.knownDiscardPromptMatched){
    throw 'Private QA discard dialog identity is not uniquely proven'
  }
  $pattern=$null
  if(-not $safeDiscardDialogs[0].TryGetCurrentPattern(
      [System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){
    throw 'Private QA native OK has no safe InvokePattern'
  }
  $out.noInputSent=$false
  $pattern.Invoke()
  $out.gracefulDiscardInvoked=$true
  $out.status='EXACT_PRIVATE_QA_DISCARD_INVOKED'
 }else{
 $out.status='READ_ONLY_OWNED_DESKTOP_AUDITED'
 }
}catch{$out.status='PRIVATE_UIA_ERROR';$out.errorType=$_.Exception.GetType().Name}
[IO.File]::WriteAllText($ResultFile,($out|ConvertTo-Json -Depth 5 -Compress),
 [Text.UTF8Encoding]::new($false))
'''


def verify_orphan():
    proc = psutil.Process(PID)
    if Path(proc.exe()).resolve() != EXPECTED_EXE.resolve():
        raise RuntimeError("Exact QA orphan executable mismatch")
    digest = hashlib.sha256(EXPECTED_EXE.read_bytes()).hexdigest()
    if digest != SHA:
        raise RuntimeError("Exact QA binary hash mismatch")
    if not WORK.is_dir() or not (WORK / "native-gui-report.json").is_file():
        raise RuntimeError("Original QA evidence missing")
    original = json.loads((WORK / "native-gui-report.json").read_text(encoding="utf-8"))
    if original.get("qaProcessRemainedRunningPid") != PID or original.get("exeSha") != SHA:
        raise RuntimeError("QA owner report mismatch")
    return proc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    option = parser.add_mutually_exclusive_group(required=True)
    option.add_argument("--inspect", action="store_true")
    option.add_argument("--discard-private", action="store_true")
    opts = parser.parse_args()
    proc = verify_orphan()
    from scripts import build_taraz_v106_aaas_20261111 as builder
    baseline = builder.installed_baseline()
    ledger = (WORK / "private-profile" / "qa" / "qa-runtime" /
              "roaming" / "Taraz" / "standalone-accounting.sqlite3")
    if not ledger.is_file():
        raise RuntimeError("Pinned QA clone ledger unavailable")
    prior_ledger_digest = hashlib.sha256(ledger.read_bytes()).hexdigest()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    handle = user32.OpenDesktopW(DESKTOP, 0, False, 0x0001 | 0x0002 | 0x0040 | 0x0080)
    if not handle:
        raise RuntimeError("QA private desktop unavailable")
    desktop = native.PrivateDesktop()
    desktop.name = DESKTOP
    desktop.handle = handle
    pids = [PID]
    pids.extend(child.pid for child in proc.children(recursive=True))
    private = WORK / "private-profile"
    runtime = private / "qa" / "qa-runtime"
    paths = {"roaming": runtime / "roaming" / "Taraz",
             "local": runtime / "localappdata" / "Taraz",
             "bridge": runtime / "localappdata" / "Madar-Taraz-Bridge"}
    env = native.isolated_env(runtime, paths, private / "qa-audit-status.json",
                              native.unused_port())
    power = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    script = private / "qa-orphan-readonly.ps1"
    result = private / "qa-orphan-readonly.json"
    script.write_text(PRIVATE_POWERSHELL, encoding="utf-8-sig")
    pid = hprocess = hthread = 0
    try:
        args = (
            "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
            "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-OwnerIds", ",".join(map(str, pids)), "-ResultFile", str(result))
        pid, hprocess, hthread = desktop.spawn(power, WORK, env,
            args + (("-Discard",) if opts.discard_private else ()))
        kernel = ctypes.windll.kernel32
        if kernel.WaitForSingleObject(hprocess, 18000) != 0:
            raise RuntimeError("Private read-only helper did not exit; no terminate attempted")
        if not result.is_file():
            raise RuntimeError("Private read-only UIA report missing")
        report = json.loads(result.read_text(encoding="utf-8-sig"))
        if opts.discard_private and report.get("gracefulDiscardInvoked") is True:
            try:
                proc.wait(timeout=12)
                report["qaProcessClosedGracefully"] = True
            except psutil.TimeoutExpired:
                report["qaProcessClosedGracefully"] = False
        report["qaLedgerUnchanged"] = (
            hashlib.sha256(ledger.read_bytes()).hexdigest() == prior_ledger_digest)
        report["installedBaselineUnchanged"] = (builder.installed_baseline() == baseline)
        report["noProcessForceKilled"] = True
        print(json.dumps(report, ensure_ascii=False))
    finally:
        kernel = ctypes.windll.kernel32
        for h in (hprocess, hthread):
            if h:
                kernel.CloseHandle(h)
        user32.CloseDesktop(handle)


if __name__ == "__main__":
    main()
