"""Bounded owner-specific UIA inspection of a historic private QA warning.

Only exact PID, binary hash, private profile and private WinSta0 desktop.
The optional acknowledgement dismisses ONLY a uniquely observed informational
browser alert. It never approves unsaved financial edits or bypasses a guard.
No force termination, global keyboard, or foreground desktop access.
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
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.qa_taraz_v103_native_gui_20261111 import PrivateDesktop

PARENT = 37456
CHILD = 26844
EXE = Path("D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/"
           "taraz-v1.0.6-aaas/build-5e5253cd7449/binary/Taraz.exe")
SHA = "d4692dfaf66b4de52e778bea59099ad2ea661f4e47493877a4ca9d4b6c322305"
WORK = Path("D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/"
            "taraz-v1.0.6-aaas/fresh-windows-frozen-qa-20261115/qa-3443357975f2")
ALERT = "عملیات مالی هنوز در حال انجام است. پس از پایان عملیات دوباره برای خروج اقدام کنید."

PS = r'''
param([int]$ParentPid,[int]$ChildPid,[string]$Report,[switch]$Acknowledge)
$ErrorActionPreference='Stop'
$state=@{status='BLOCKED';mainWindowCount=0;alertCount=0;okCount=0;
  confirmCount=0;matchedExactAlert=$false;acknowledged=$false;
  noGlobalInput=$true;noForceTermination=$true}
try {
 Add-Type -AssemblyName UIAutomationClient
 Add-Type -AssemblyName UIAutomationTypes
 $roots=[System.Windows.Automation.AutomationElement]::RootElement.FindAll(
   [System.Windows.Automation.TreeScope]::Children,
   [System.Windows.Automation.Condition]::TrueCondition)
 $owned=@($roots|Where-Object{
    @($ParentPid,$ChildPid) -contains [int]$_.Current.ProcessId -and
    $_.Current.Name -eq 'تراز | حسابداری'})
 $state.mainWindowCount=$owned.Count
 if($owned.Count -ne 1){throw 'Owned accounting window not unique'}
 $nodes=$owned[0].FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
 $texts=@($nodes|Where-Object {
    $_.Current.Name -eq 'عملیات مالی هنوز در حال انجام است. پس از پایان عملیات دوباره برای خروج اقدام کنید.' -and
    @($ParentPid,$ChildPid) -contains [int]$_.Current.ProcessId
 })
 $state.alertCount=$texts.Count
 $dialogs=@($nodes|Where-Object{
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window -and
    $_.Current.Name -like '*says*' -and
    @($ParentPid,$ChildPid) -contains [int]$_.Current.ProcessId
 })
 $state.confirmCount=$dialogs.Count
 $buttons=@($nodes|Where-Object{
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
    $_.Current.Name -eq 'OK' -and $_.Current.IsEnabled -and
    @($ParentPid,$ChildPid) -contains [int]$_.Current.ProcessId
 })
 $state.okCount=$buttons.Count
 $state.matchedExactAlert=($texts.Count -eq 1 -and $dialogs.Count -eq 1 -and $buttons.Count -eq 1)
 if($Acknowledge){
    if(-not $state.matchedExactAlert){throw 'Exact owned alert not proved; no UI action'}
    $pattern=$null
    if(-not $buttons[0].TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){
      throw 'Exact OK not invokable'
    }
    $pattern.Invoke()
    $state.acknowledged=$true
    $state.status='EXACT_PRIVATE_BUSY_ALERT_DISMISSED'
 }else{
    $state.status='READONLY_PRIVATE_QA_ALERT_INSPECTED'
 }
} catch {
 $state.status='PRIVATE_QA_UIA_BLOCKED'
 $state.errorType=$_.Exception.GetType().Name
}
[IO.File]::WriteAllText($Report,($state|ConvertTo-Json -Depth 5 -Compress),
 [Text.UTF8Encoding]::new($false))
'''


def run(*, acknowledge: bool = False):
    if os.name != "nt":
        raise RuntimeError("Windows-only QA")
    p, c = psutil.Process(PARENT), psutil.Process(CHILD)
    if (c.ppid() != PARENT or Path(p.exe()).resolve() != EXE.resolve() or
            Path(c.exe()).resolve() != EXE.resolve() or
            hashlib.sha256(EXE.read_bytes()).hexdigest() != SHA):
        raise RuntimeError("QA executable identity mismatch")
    if not (WORK / "fresh-windows-frozen-result.json").is_file():
        raise RuntimeError("Historical QA evidence not present")
    evidence = json.loads((WORK / "fresh-windows-frozen-result.json").read_text())
    if (evidence.get("exeSha256") != SHA or evidence.get("private") is not True or
            evidence.get("gracefulExit") is not False):
        raise RuntimeError("QA evidence mismatch")
    scope = str((WORK / "qa" / "qa-runtime").resolve()).casefold()
    for proc in (p, c):
        env = proc.environ()
        if (env.get("TARAZ_QA_MODE") != "1" or
                not env.get("TARAZ_QA_DATA_DIR", "").casefold().startswith(scope + "\\") or
                not env.get("APPDATA", "").casefold().startswith(scope + "\\") or
                not env.get("LOCALAPPDATA", "").casefold().startswith(scope + "\\")):
            raise RuntimeError("QA process used nonprivate environment")
    desktop_name = None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.LPWSTR, wintypes.LPARAM)
    DESKCB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.EnumDesktopsW.argtypes = [wintypes.HANDLE, CALLBACK, wintypes.LPARAM]
    user32.OpenDesktopW.argtypes = [wintypes.LPWSTR, wintypes.DWORD,
                                    wintypes.BOOL, wintypes.DWORD]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, DESKCB, wintypes.LPARAM]
    user32.EnumDesktopWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    candidates = []

    @CALLBACK
    def inspect(name, _):
        if not name.startswith("TarazNativeQA_"):
            return True
        handle = user32.OpenDesktopW(name, 0, False, 0xC1)
        if not handle:
            return True
        found = []

        @DESKCB
        def visit(hwnd, __):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == CHILD:
                buf = ctypes.create_unicode_buffer(120)
                user32.GetWindowTextW(hwnd, buf, len(buf))
                if buf.value == "تراز | حسابداری":
                    found.append(hwnd)
            return True

        user32.EnumDesktopWindows(handle, visit, 0)
        user32.CloseDesktop(handle)
        if len(found) == 1:
            candidates.append(name)
        return True

    user32.EnumDesktopsW(user32.GetProcessWindowStation(), inspect, 0)
    if len(candidates) != 1:
        raise RuntimeError("Exactly one owned private desktop not proved")
    desktop_name = candidates[0]
    output = WORK / ("owned-alert-ack-" if acknowledge else "owned-alert-inspect-")
    output = Path(str(output) + uuid.uuid4().hex[:12])
    output.mkdir()
    script = output / "private-alert.ps1"
    result = output / "result.json"
    script.write_text(PS, encoding="utf-8-sig")
    env = dict(os.environ)
    private = WORK / "qa" / "qa-runtime"
    for var, subdir in (("APPDATA", "roaming"), ("LOCALAPPDATA", "localappdata"),
                        ("TEMP", "temp"), ("TMP", "temp"), ("USERPROFILE", "userprofile")):
        env[var] = str(private / subdir)
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    ui = PrivateDesktop()
    ui.name = desktop_name
    ui.handle = user32.OpenDesktopW(desktop_name, 0, False, 0xC1)
    if not ui.handle:
        raise RuntimeError("Private desktop no longer available")
    hp = ht = 0
    try:
        _, hp, ht = ui.spawn(powershell, output, env,
            ("-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-ParentPid", str(PARENT), "-ChildPid", str(CHILD),
             "-Report", str(result), *(("-Acknowledge",) if acknowledge else ())))
        if ctypes.windll.kernel32.WaitForSingleObject(hp, 20000) != 0 or not result.is_file():
            raise RuntimeError("Private QA alert helper did not finish normally")
        data = json.loads(result.read_text(encoding="utf-8-sig"))
        data["output"] = str(output)
        return data
    finally:
        for item in (hp, ht):
            if item:
                ctypes.windll.kernel32.CloseHandle(item)
        user32.CloseDesktop(ui.handle)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--acknowledge-exact-busy-alert", action="store_true")
    opt = parser.parse_args()
    print(json.dumps(run(acknowledge=opt.acknowledge_exact_busy_alert), ensure_ascii=False))
