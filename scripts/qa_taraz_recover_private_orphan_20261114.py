"""Scope-limited recovery of ONE verified synthetic Frozen QA window.

Default is read-only. --graceful-close clicks only the QA-owned
'Back without saving' control (if uniquely invokable), then requests normal
WM_CLOSE on the exact private-window HWND. There is never a force kill,
SendInput, SwitchDesktop, global keyboard, live ledger access, or installation.
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
from scripts.qa_taraz_v103_native_gui_20261111 import PrivateDesktop

EXE = Path('D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/'
           'taraz-v1.0.6-aaas/build-8ad80825928e/binary/Taraz.exe')
EXE_SHA = '70eb46a3430985cca18aeaaf21339a2c7f49fca3f75066f091a8600d862dc512'
RUN = Path('D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/'
           'taraz-v1.0.6-aaas/frozen-synthetic-private-uia-20261112/qa-3edf86189818')
PARENT_PID = 35236
CHILD_PID = 33388
DESKTOP = 'TarazNativeQA_ce71e4c34aa648'

UIA = r"""
param([int]$Target,[string]$OwnerIds,[string]$ResultFile,[switch]$Close)
$ErrorActionPreference='Stop'
$ids=@($OwnerIds.Split(',') | ForEach-Object {[int]$_})
$result=@{status='NOT_OBSERVED';targetPid=$Target;windowCount=0;
  abortControlCount=0;abortControlInvoke=$false;abortActionTaken=$false;
  ownedWindowUnique=$false;noGlobalInput=$true;noForceTermination=$true;
  closeRequested=$false;errorType=''}
try {
 Add-Type -AssemblyName UIAutomationClient
 Add-Type -AssemblyName UIAutomationTypes
 $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll(
  [System.Windows.Automation.TreeScope]::Children,
  [System.Windows.Automation.Condition]::TrueCondition)
 $ours=@($windows | Where-Object {
    $_.Current.ProcessId -eq $Target -and $_.Current.Name -eq 'تراز | حسابداری'
 })
 $result.windowCount=$ours.Count
 if($ours.Count -ne 1){throw 'Exact QA window was not uniquely available'}
 $result.ownedWindowUnique=$true
 $root=$ours[0]
 $desc=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
   [System.Windows.Automation.Condition]::TrueCondition)
 $result.qaDescendantCount=$desc.Count
 $result.qaAccessibleControls=@($desc | Select-Object -First 55 | ForEach-Object {
  @{name=[string]$_.Current.Name;
    control=[string]$_.Current.ControlType.ProgrammaticName;
    owner=[int]$_.Current.ProcessId}
 })
 $result.qaButtonNames=@($desc | Where-Object {
   $ids -contains [int]$_.Current.ProcessId -and
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button
 } | Select-Object -First 70 | ForEach-Object {$_.Current.Name})
 $result.qaEditNames=@($desc | Where-Object {
   $ids -contains [int]$_.Current.ProcessId -and
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit
 } | Select-Object -First 40 | ForEach-Object {$_.Current.Name})
 # A normal browser confirm from the QA-owned app is currently blocking
 # all page controls. Approving its *explicit discard* is permitted only
 # with the exact inspected Persian text on the private QA window.
 $expected='اطلاعات این فرم حسابداری هنوز ذخیره نشده است. پنجره را ببندیم و تغییرات را کنار بگذاریم؟'
 $dialogs=@($desc | Where-Object {
  $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window -and
  $ids -contains [int]$_.Current.ProcessId -and
  $_.Current.Name -like '127.0.0.1:* says'
 })
 $messages=@($desc | Where-Object {
  $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Text -and
  $ids -contains [int]$_.Current.ProcessId -and
  $_.Current.Name -eq $expected
 })
 $ok=@($desc | Where-Object {
  $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
  $ids -contains [int]$_.Current.ProcessId -and
  $_.Current.Name -eq 'OK' -and $_.Current.IsEnabled
 })
 $result.syntheticCloseConfirmationMatched=($dialogs.Count -eq 1 -and
   $messages.Count -eq 1 -and $ok.Count -eq 1)
 if($Close -and $result.syntheticCloseConfirmationMatched){
  $okPattern=$null
  if($ok[0].TryGetCurrentPattern(
     [System.Windows.Automation.InvokePattern]::Pattern,[ref]$okPattern)){
     $okPattern.Invoke()
     $result.syntheticDiscardApproved=$true
     Start-Sleep -Milliseconds 700
  }
 }
 $filter=New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::NameProperty,'بازگشت بدون ذخیره')
 $buttons=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$filter)
 $eligible=@($buttons | Where-Object { $ids -contains [int]$_.Current.ProcessId -and
  $_.Current.IsEnabled -and
  $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button })
 $result.abortControlCount=$eligible.Count
 if($eligible.Count -eq 1){
  $pattern=$null
  $result.abortControlInvoke=$eligible[0].TryGetCurrentPattern(
    [System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)
  if($Close -and $result.abortControlInvoke){
    $pattern.Invoke()
    $result.abortActionTaken=$true
    Start-Sleep -Milliseconds 850
  }
 }
 $result.status='OWNED_UIA_INSPECTED'
} catch { $result.status='UIA_INSPECTION_FAILED';
         $result.errorType=$_.Exception.GetType().Name }
[IO.File]::WriteAllText($ResultFile,($result|ConvertTo-Json -Depth 6 -Compress),
 [Text.UTF8Encoding]::new($false))
"""


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--graceful-close',action='store_true')
    args=parser.parse_args()
    if os.name!='nt':
        raise RuntimeError('Windows only')
    parent=psutil.Process(PARENT_PID)
    child=psutil.Process(CHILD_PID)
    if (Path(parent.exe()).resolve()!=EXE.resolve() or
        Path(child.exe()).resolve()!=EXE.resolve() or
        child.ppid()!=PARENT_PID or
        hashlib.sha256(EXE.read_bytes()).hexdigest()!=EXE_SHA):
        raise PermissionError('Exact synthetic EXE process identity mismatch')
    owner = json.loads((RUN/'synthetic-ownership.json').read_text(encoding='utf-8'))
    if owner != {'syntheticOnly':True,'candidate':EXE.parent.parent.name,
                  'exeSha256':EXE_SHA}:
        raise PermissionError('Private test ownership evidence mismatch')
    user32=ctypes.WinDLL('user32',use_last_error=True)
    user32.OpenDesktopW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    user32.OpenDesktopW.restype=wintypes.HANDLE
    handle=user32.OpenDesktopW(DESKTOP,0,False,0x1FF)
    if not handle:
        raise RuntimeError('Specified QA desktop is unavailable')
    private=PrivateDesktop()
    private.name=DESKTOP
    private.handle=handle
    script=RUN/'private-profile'/'recover-owned-synthetic.ps1'
    report=RUN/'private-profile'/('recover-close.json' if args.graceful_close
                                    else 'recover-inspect.json')
    script.write_text(UIA,encoding='utf-8-sig')
    powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    env=dict(os.environ)
    base=RUN/'private-profile'/'qa'/'qa-runtime'
    for name,part in [('APPDATA','roaming'),('LOCALAPPDATA','localappdata'),
                      ('TEMP','temp'),('TMP','temp'),('USERPROFILE','userprofile')]:
        path=base/part
        if not path.is_dir():
            raise RuntimeError('QA runtime path not found')
        env[name]=str(path)
    owner_pids={PARENT_PID,CHILD_PID}
    owner_pids.update(p.pid for p in parent.children(recursive=True))
    worker=thread=None
    try:
        pid,worker,thread=private.spawn(powershell,RUN,env,
            ('-NoProfile','-NonInteractive','-WindowStyle','Hidden',
             '-ExecutionPolicy','Bypass','-File',str(script),'-Target',str(CHILD_PID),
             '-OwnerIds',','.join(str(pid) for pid in sorted(owner_pids)),
             '-ResultFile',str(report),
             *(['-Close'] if args.graceful_close else [])))
        result_wait=ctypes.windll.kernel32.WaitForSingleObject(worker,12000)
        if result_wait!=0 or not report.is_file():
            raise RuntimeError('Private UIA helper did not safely complete')
        observed=json.loads(report.read_text(encoding='utf-8-sig'))
        if args.graceful_close and observed.get('syntheticDiscardApproved'):
            try:
                parent.wait(timeout=16)
                observed['parentExitedNormally']=True
            except psutil.TimeoutExpired:
                observed['parentExitedNormally']=False
        elif args.graceful_close and observed['ownedWindowUnique']:
            # No automatic dismissal of a confirmation dialog. A valid
            # original window is the only candidate for a normal close.
            owner= wintypes.DWORD()
            HWND=ctypes.c_void_p
            user32.EnumDesktopWindows.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.LPARAM]
            user32.GetWindowThreadProcessId.argtypes=[HWND,ctypes.POINTER(wintypes.DWORD)]
            user32.GetWindowTextW.argtypes=[HWND,wintypes.LPWSTR,ctypes.c_int]
            handles=[]
            CALLBACK=ctypes.WINFUNCTYPE(wintypes.BOOL,HWND,wintypes.LPARAM)
            @CALLBACK
            def window(hwnd,_):
                user32.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
                if owner.value==CHILD_PID:
                    title=ctypes.create_unicode_buffer(120)
                    user32.GetWindowTextW(hwnd,title,120)
                    if title.value=='تراز | حسابداری':
                        handles.append(hwnd)
                return True
            user32.EnumDesktopWindows(private.handle,window,0)
            if len(handles)==1:
                observed['closeRequested']=bool(user32.PostMessageW(handles[0],0x0010,0,0))
                try:
                    parent.wait(timeout=12)
                    observed['parentExitedNormally']=True
                except psutil.TimeoutExpired:
                    observed['parentExitedNormally']=False
            else:
                observed['closeRequested']=False
                observed['matchingWindowCount']=len(handles)
        print(json.dumps(observed,ensure_ascii=True))
        return 0 if observed.get('parentExitedNormally') or (
            not args.graceful_close and observed['status']=='OWNED_UIA_INSPECTED') else 1
    finally:
        for h in (worker,thread):
            if h:ctypes.windll.kernel32.CloseHandle(h)
        user32.CloseDesktop(private.handle)


if __name__=='__main__':
    raise SystemExit(main())
