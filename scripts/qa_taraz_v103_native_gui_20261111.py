"""Isolated native smoke for the SHA-pinned *non-QA* Taraz 1.0.3 executable.

Creates a NEW non-input Win32 desktop; NEVER SwitchDesktop/SetForegroundWindow.
The required migrated source is copied from an independently verified OFFLINE
backup into a new ACL-restricted disposable profile. No live accounting profile,
installed executable, user windows, registry or Madar service is touched.
All CDP output is a strict allowlist of booleans; private ledger text is not read.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import qa_taraz_v103_independent_acceptance_20261111 as pins
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as safe_copy

EXE = (PROJECT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" /
       "taraz-v1.0.3-p1" / "build-eb9d4f2ab076" / "binary" / "Taraz.exe")
EXE_SHA = "e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c"
BACKUP = pins.BACKUP
OUTPUT = PROJECT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v103-private-native-gui-qa"
PLAYWRIGHT = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "playwright"


class NativeBlocked(RuntimeError):
    """Failed or incomplete candidate acceptance, never a release approval."""


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for buf in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def pin() -> dict:
    if os.name != "nt" or not EXE.is_file() or EXE.is_symlink():
        raise NativeBlocked("SHA-pinned Windows executable unavailable")
    if digest(EXE) != EXE_SHA:
        raise NativeBlocked("Compiled candidate SHA mismatch; EXE not launched")
    if not PLAYWRIGHT.is_dir():
        raise NativeBlocked("Known Playwright dependency unavailable")
    base = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz"
    original = pins.installed_baseline(base)
    evidence = pins.verify_backup(BACKUP)
    return {"installed": original, "backup": evidence}


def clone_offline_snapshot(work: Path) -> tuple[Path, dict]:
    """Private copy only. Never open the live installed user's original ledger."""
    private = work / "private-profile"
    private.mkdir(exist_ok=False)
    runtime = private / "qa" / "qa-runtime"
    runtime.mkdir(parents=True, exist_ok=False)
    roots = {
        "roaming": runtime / "roaming" / "Taraz",
        "local": runtime / "localappdata" / "Taraz",
        "bridge": runtime / "localappdata" / "Madar-Taraz-Bridge",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=False)
    manifests = json.loads((BACKUP / "snapshot-manifest.json").read_text(encoding="utf-8"))["files"]
    for name, details in manifests.items():
        rel = Path(name)
        if len(rel.parts) < 2 or rel.parts[0] not in roots or ".." in rel.parts:
            raise NativeBlocked("Refused unexpected offline backup member")
        source = BACKUP / "files" / rel
        pins._regular(source)
        target = roots[rel.parts[0]].joinpath(*rel.parts[1:])
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as inp, target.open("xb") as out:
            shutil.copyfileobj(inp, out, 1024 * 1024)
        if target.stat().st_size != details["bytes"] or digest(target) != details["sha256"]:
            raise NativeBlocked("Private offline backup copy mismatch")
    return runtime, roots


def isolated_env(runtime: Path, roots: dict, report: Path, port: int) -> dict:
    env = dict(os.environ)
    for key in list(env):
        if key.upper().startswith("TARAZ_") or key.upper().startswith("WEBVIEW2_") or key.upper() == "PYTHONPATH":
            env.pop(key, None)
    for name, part in {
        "APPDATA": "roaming", "LOCALAPPDATA": "localappdata",
        "USERPROFILE": "userprofile", "HOME": "userprofile",
        "TEMP": "temp", "TMP": "temp", "PYINSTALLER_CONFIG_DIR": "pyinstaller-config",
        "PYTHONPYCACHEPREFIX": "pycache", "WEBVIEW2_USER_DATA_FOLDER": "webview-profile",
        "XDG_CACHE_HOME": "cache",
    }.items():
        path = runtime / part
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    env.update({
        "TARAZ_QA_MODE": "1",
        "TARAZ_QA_DATA_DIR": str(roots["roaming"]),
        "TARAZ_QA_REPORT": str(report),
        "PYTHONDONTWRITEBYTECODE": "1",
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": (
            f"--remote-debugging-port={port} --remote-debugging-address=127.0.0.1 "
            "--force-renderer-accessibility --disable-background-networking --disable-sync "
            "--disable-component-update --disable-extensions --no-first-run "
            "--no-default-browser-check --proxy-server=http://127.0.0.1:9 "
            "--proxy-bypass-list=<-loopback>"),
    })
    if any(Path(env[key]).resolve() == Path(os.environ.get(key, "")).resolve()
           for key in ("APPDATA", "LOCALAPPDATA", "TEMP")):
        raise NativeBlocked("Refused ambient user profile reuse")
    if "qa" not in [item.lower() for item in Path(env["TARAZ_QA_DATA_DIR"]).parts]:
        raise NativeBlocked("Taraz QA path marker absent")
    return env


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def safe_webview_diagnostics(root_pid: int, port: int) -> dict:
    """Boolean-only child runtime facts; never emit args, paths or credentials."""
    import psutil
    try:
        main=psutil.Process(root_pid)
        children=[main,*main.children(recursive=True)]
    except psutil.NoSuchProcess:
        children=[]
    webviews=[]
    for child in children:
        try:
            if child.name().casefold()=="msedgewebview2.exe":
                args=child.cmdline()
                webviews.append({"remoteDebugFlag": any(
                    item.startswith("--remote-debugging-port=") for item in args),
                    "expectedPortFlag": any(
                    item=="--remote-debugging-port="+str(port) for item in args),
                    "runtimeProfileIsolated": any(
                    "qa-runtime" in item.casefold() for item in args)})
        except (psutil.NoSuchProcess,psutil.AccessDenied):
            continue
    try:
        with socket.create_connection(("127.0.0.1",port),timeout=.4):
            listening=True
    except OSError:
        listening=False
    return {"ownedWebView2Count":len(webviews),"anyRemoteDebugFlag":any(
        x["remoteDebugFlag"] for x in webviews),
        "expectedPortFlag":any(x["expectedPortFlag"] for x in webviews),
        "anyIsolatedWebviewProfileArg":any(x["runtimeProfileIsolated"] for x in webviews),
        "cdpPortListening":listening}


class StartupInfoW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class PrivateDesktop:
    """Separate non-input desktop; no user desktop API calls are allowed."""
    def __init__(self):
        self.name = "TarazNativeQA_" + uuid.uuid4().hex[:14]
        self.handle = None

    def __enter__(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                          ctypes.c_void_p, wintypes.DWORD,
                                          wintypes.DWORD, ctypes.c_void_p]
        user32.CreateDesktopW.restype = wintypes.HANDLE
        self.handle = user32.CreateDesktopW(self.name, None, None, 0, 0x1FF, None)
        if not self.handle:
            raise NativeBlocked("Could not create isolated Win32 desktop: " + str(ctypes.get_last_error()))
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle:
            ctypes.windll.user32.CloseDesktop(self.handle)
            self.handle = None

    def spawn(self, executable: Path, cwd: Path, env: dict,
              arguments: tuple[str, ...] = ()) -> tuple[int, int, int]:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD,
            ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(StartupInfoW),
            ctypes.POINTER(ProcessInfo)]
        kernel.CreateProcessW.restype = wintypes.BOOL
        start = StartupInfoW()
        start.cb = ctypes.sizeof(start)
        start.lpDesktop = "WinSta0\\" + self.name
        info = ProcessInfo()
        block = ctypes.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in sorted(env.items())) + "\0\0")
        cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(executable),*arguments]))
        if not kernel.CreateProcessW(str(executable), cmd, None, None, False,
                 0x00000400 | 0x00000200, ctypes.cast(block, ctypes.c_void_p),
                 str(cwd), ctypes.byref(start), ctypes.byref(info)):
            raise NativeBlocked("Private desktop CreateProcessW failed: " + str(ctypes.get_last_error()))
        return int(info.dwProcessId), int(info.hProcess), int(info.hThread)

    def owned_windows(self, pids: set[int]) -> list[dict]:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        result = []
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, callback_type, wintypes.LPARAM]
        @callback_type
        def collect(hwnd, ignored):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in pids:
                return True
            caption = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, caption, len(caption))
            if "تراز" in caption.value:
                result.append({"pid": pid.value, "isTarazTitle": True,
                               "visible": bool(user32.IsWindowVisible(hwnd))})
            return True
        if not user32.EnumDesktopWindows(self.handle, collect, 0):
            raise NativeBlocked("Could not enumerate only private desktop windows")
        return result


PRIVATE_UIA_PS = r'''
param([Parameter(Mandatory=$true)][string]$OwnerIds,
      [Parameter(Mandatory=$true)][string]$ResultFile)
$ErrorActionPreference='Stop'
$result=@{status='NOT_OBSERVED';windowOwned=$false;
  madarTabAccessible=$false;helpButtonAccessible=$false;
  helpCloseControlAccessible=$false;invoiceDesignerNavAccessible=$false;
  invoiceDesignerFormAccessible=$false;sileoAccessible=$false;
  childWindowCount=0;childWebViewClassCount=0;
  directChildUiAccessibleCount=0;namedDescendantCount=0;
  privateOwnerMatch=$false;noFinanceActionAttempted=$true;
  safeNavigationAttempted=$false;madarTabInvoked=$false;
  madarContentHeaderAccessible=$false;madarContentSourceAccessible=$false;
  madarConsentAccessible=$false;helpDialogOpenedViaUIA=$false;
  helpClosedViaUIA=$false;printNavInvoked=$false;
  printDesignerAccessibleAfterNav=$false;
  helpExactAfterNavAccessible=$false;menuExactAfterNavAccessible=$false;
  helpExactAfterNavInvokable=$false;menuExactAfterNavInvokable=$false;
  helpNamedOwnerMatched=$false;helpNamedButtonMatched=$false;helpNamedEnabled=$false;
  menuNamedOwnerMatched=$false;menuNamedButtonMatched=$false;menuNamedEnabled=$false}
try {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
  Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class TarazPrivateHwndAudit {
    public delegate bool Callback(IntPtr hwnd, IntPtr lParam);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern int GetClassName(IntPtr hwnd, StringBuilder buffer, int capacity);
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")]
    public static extern bool EnumChildWindows(IntPtr hwnd, Callback callback, IntPtr lParam);
}
"@
  $pids=@($OwnerIds.Split(',') | ForEach-Object { [int]$_ })
  $root=[System.Windows.Automation.AutomationElement]::RootElement
  $elements=$root.FindAll([System.Windows.Automation.TreeScope]::Children,
     [System.Windows.Automation.Condition]::TrueCondition)
  $own=@($elements | Where-Object {
      ($pids -contains $_.Current.ProcessId) -and $_.Current.Name -like '*تراز*'
  })
  if($own.Count -ne 1){ throw 'No uniquely owned private Taraz UI Automation window' }
  $window=$own[0]
  $result.windowOwned=$true
  $result.privateOwnerMatch=($pids -contains [int]$window.Current.ProcessId)
  $childHandles=New-Object 'System.Collections.Generic.List[System.IntPtr]'
  $callback=[TarazPrivateHwndAudit+Callback]{param($hwnd,$unused)
    $process=[uint32]0
    [void][TarazPrivateHwndAudit]::GetWindowThreadProcessId($hwnd,[ref]$process)
    if($pids -contains [int]$process){
      if($childHandles.Count -lt 128){$childHandles.Add($hwnd)}
    }
    return $true
  }
  [void][TarazPrivateHwndAudit]::EnumChildWindows(
    [IntPtr]$window.Current.NativeWindowHandle,$callback,[IntPtr]::Zero)
  $result.childWindowCount=$childHandles.Count
  $result.childWebViewClassCount=0
  $result.directChildUiAccessibleCount=0
  function FindNamed([string]$name){
    $cond=New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::NameProperty,$name)
    return $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$cond)
  }
  $result.namedDescendantCount=0
  $targets=@('اطلاعات مدار','راهنما','راهنمای داشبورد','بستن راهنما',
    'طراحی فرم فاکتور','نام قالب')
  foreach($target in $targets){
    if($null -ne (FindNamed $target)){$result.namedDescendantCount++}
  }
  $result.madarTabAccessible=($null -ne (FindNamed 'اطلاعات مدار'))
  $help=FindNamed 'راهنمای داشبورد'
  if($null -eq $help){$help=FindNamed 'راهنما'}
  $result.helpButtonAccessible=($null -ne $help)
  $result.helpCloseControlAccessible=($null -ne (FindNamed 'بستن راهنما'))
  $result.invoiceDesignerNavAccessible=($null -ne (FindNamed 'طراحی فرم فاکتور'))
  $result.invoiceDesignerFormAccessible=($null -ne (FindNamed 'نام قالب'))
  foreach($handle in $childHandles){
    try {
      $buffer=New-Object System.Text.StringBuilder 140
      [void][TarazPrivateHwndAudit]::GetClassName($handle,$buffer,$buffer.Capacity)
      if($buffer.ToString() -match 'Chrome|WebView|Internet Explorer|RenderWidget'){
        $result.childWebViewClassCount++
      }
      $child=[System.Windows.Automation.AutomationElement]::FromHandle($handle)
      if($null -ne $child){
        $directChildren=$child.FindAll([System.Windows.Automation.TreeScope]::Children,
          [System.Windows.Automation.Condition]::TrueCondition)
        if($directChildren.Count -gt 0){$result.directChildUiAccessibleCount++}
        foreach($name in $targets){
          $cond=New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty,$name)
          if($null -ne $child.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$cond)){
            if($name -eq 'اطلاعات مدار'){$result.madarTabAccessible=$true}
            if($name -eq 'بستن راهنما'){$result.helpCloseControlAccessible=$true}
            if($name -eq 'طراحی فرم فاکتور'){$result.invoiceDesignerNavAccessible=$true}
            if($name -eq 'نام قالب'){$result.invoiceDesignerFormAccessible=$true}
          }
        }
      }
    }catch{
      # Some child HWNDs have no supported UIA provider. Do not query other windows.
    }
  }
  # Only safe view navigation. Never click a consent checkbox, refresh,
  # invoice, save, issue, payment, reject, or external integration control.
  function FindOwnedButton([string]$name){
    $condition=New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::NameProperty,$name)
    $matches=$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
    $buttons=@($matches | Where-Object {
      ($pids -contains [int]$_.Current.ProcessId) -and
      $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
      $_.Current.IsEnabled
    })
    if($buttons.Count -eq 1){return $buttons[0]}
    return $null
  }
  function InvokeSafeNavigation([string]$name){
    if($name -notin @('اطلاعات مدار','راهنمای اطلاعات مدار',
      'بستن راهنما','بازکردن فهرست بخش‌های تراز','طراحی فرم فاکتور')){
      throw 'Rejected non-allowlisted UIA action'
    }
    $element=FindOwnedButton $name
    if($null -eq $element){return $false}
    $pattern=$null
    if($element.TryGetCurrentPattern(
      [System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){
      $pattern.Invoke()
      return $true
    }
    # WebView2 browser controls can provide MSAA's button default action
    # without exposing UIA InvokePattern. Require exact role=pushbutton (43)
    # and an owned, enabled, allowlisted control before any safe action.
    try {
      $legacy=$null
      if($element.TryGetCurrentPattern(
          [System.Windows.Automation.LegacyIAccessiblePattern]::Pattern,[ref]$legacy)){
        if([int]$legacy.Current.Role -eq 43){
          $legacy.DoDefaultAction()
          return $true
        }
      }
    }catch{ return $false }
    return $false
  }
  function CanInvokeNamedButton([string]$name){
    $button=FindOwnedButton $name
    if($null -eq $button){return $false}
    $pattern=$null
    return $button.TryGetCurrentPattern(
      [System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)
  }
  function NamedButtonFacts([string]$name){
    $condition=New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::NameProperty,$name)
    $matches=$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
    $same=@($matches | Where-Object {$pids -contains [int]$_.Current.ProcessId})
    $button=@($same | Where-Object {
      $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
    return @{owned=($same.Count -gt 0);button=($button.Count -gt 0);
      enabled=(@($button | Where-Object {$_.Current.IsEnabled}).Count -gt 0)}
  }
  $result.safeNavigationAttempted=$true
  if(InvokeSafeNavigation 'اطلاعات مدار'){
    $result.madarTabInvoked=$true
    Start-Sleep -Milliseconds 750
    $result.madarContentHeaderAccessible=($null -ne (FindNamed 'ارتباط مدار و تراز'))
    $result.madarContentSourceAccessible=($null -ne (FindNamed 'رابط میزبان'))
    $result.madarConsentAccessible=($null -ne (FindNamed 'اجازه می‌دهم اطلاعات صندوق مدار را به درخواست خودم بخوانم'))
    $result.helpExactAfterNavAccessible=($null -ne (FindNamed 'راهنمای اطلاعات مدار'))
    $result.menuExactAfterNavAccessible=($null -ne (FindNamed 'بازکردن فهرست بخش‌های تراز'))
    $hf=NamedButtonFacts 'راهنمای اطلاعات مدار'
    $mf=NamedButtonFacts 'بازکردن فهرست بخش‌های تراز'
    $result.helpNamedOwnerMatched=$hf.owned
    $result.helpNamedButtonMatched=$hf.button
    $result.helpNamedEnabled=$hf.enabled
    $result.menuNamedOwnerMatched=$mf.owned
    $result.menuNamedButtonMatched=$mf.button
    $result.menuNamedEnabled=$mf.enabled
    $result.helpExactAfterNavInvokable=CanInvokeNamedButton 'راهنمای اطلاعات مدار'
    $result.menuExactAfterNavInvokable=CanInvokeNamedButton 'بازکردن فهرست بخش‌های تراز'
    if(InvokeSafeNavigation 'راهنمای اطلاعات مدار'){
      Start-Sleep -Milliseconds 300
      $result.helpDialogOpenedViaUIA=($null -ne (FindNamed 'بستن راهنما'))
      if($result.helpDialogOpenedViaUIA){
        $result.helpClosedViaUIA=(InvokeSafeNavigation 'بستن راهنما')
      }
    }
    if(InvokeSafeNavigation 'بازکردن فهرست بخش‌های تراز'){
      Start-Sleep -Milliseconds 350
      $result.printNavInvoked=(InvokeSafeNavigation 'طراحی فرم فاکتور')
      if($result.printNavInvoked){
        Start-Sleep -Milliseconds 600
        $result.printDesignerAccessibleAfterNav=($null -ne (FindNamed 'طراح قالب چاپ فاکتور')) -or
          ($null -ne (FindNamed 'نام قالب'))
      }
    }
  }
  $result.status='READ_ONLY_OWNED_HWND_UIA_COMPLETED'
}catch{
  $result.status='UIA_NOT_AVAILABLE'
  $result.errorKind='UIAutomationQueryFailed'
}
$json=$result|ConvertTo-Json -Depth 4 -Compress
[IO.File]::WriteAllText($ResultFile,$json,[Text.UTF8Encoding]::new($false))
'''


def private_uia_probe(desktop: PrivateDesktop, owned: set[int], work: Path,
                      environment: dict) -> dict:
    """Invoke only named owned controls; no SwitchDesktop or OS mouse input."""
    powershell=Path(os.environ['SystemRoot'])/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    if not powershell.is_file():
        return {'status':'POWERSHELL_UNAVAILABLE'}
    source=work/'private-profile'/'qa-private-uia.ps1'
    output=work/'private-profile'/'qa-private-uia.json'
    # Windows PowerShell 5.1 assumes ANSI for scripts lacking a UTF-8 BOM;
    # that would corrupt the Persian UIA labels before the parser runs.
    source.write_text(PRIVATE_UIA_PS,encoding='utf-8-sig')
    ids=','.join(str(x) for x in sorted(owned))
    pid, handle, thread=desktop.spawn(powershell,work,environment,(
      '-NoProfile','-NonInteractive','-WindowStyle','Hidden',
      '-ExecutionPolicy','Bypass','-File',str(source),
      '-OwnerIds',ids,'-ResultFile',str(output)))
    kernel=ctypes.windll.kernel32
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    try:
        finished=kernel.WaitForSingleObject(handle,25000)
        if finished!=0:
            kernel.TerminateProcess(handle,1)
            return {'status':'PRIVATE_UIA_TIMEOUT'}
        if not output.is_file():
            code=wintypes.DWORD(0)
            kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
            kernel.GetExitCodeProcess(handle,ctypes.byref(code))
            return {'status':'PRIVATE_UIA_NO_REPORT', 'uiaProcessExitCode':int(code.value)}
        result=json.loads(output.read_text(encoding='utf-8'))
        safe_numbers={'childWindowCount','childWebViewClassCount',
                      'directChildUiAccessibleCount','namedDescendantCount'}
        return {key:value for key,value in result.items() if isinstance(value,bool) or
                key in ('status','errorKind') or (key in safe_numbers and type(value) is int)}
    finally:
        kernel.CloseHandle(handle)
        kernel.CloseHandle(thread)


def capture_owned(root_pid: int, tracked: dict[int, float]) -> set[int]:
    import psutil
    try:
        main = psutil.Process(root_pid)
        if Path(main.exe()).resolve() != EXE.resolve():
            raise NativeBlocked("Owned process identity changed")
        tracked[root_pid] = main.create_time()
        for item in main.children(recursive=True):
            try:
                tracked[item.pid] = item.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except psutil.NoSuchProcess:
        pass
    return set(tracked)


def stop_owned(root_pid: int, tracked: dict[int, float]) -> dict:
    """Kill only descendants recorded from the exact CreateProcessW PID tree."""
    import psutil
    capture_owned(root_pid, tracked)
    owned = []
    for pid, created in tracked.items():
        try:
            item = psutil.Process(pid)
            if item.create_time() == created:
                owned.append(item)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    for item in reversed(owned):
        try: item.kill()
        except psutil.NoSuchProcess: pass
    _, alive = psutil.wait_procs(owned, timeout=9)
    return {"ownedProcessesObserved": len(tracked),
            "ownedProcessesLeftAlive": len(alive), "unrelatedProcessKilled": False}


CDP_JS = r"""
const {chromium}=require(process.argv[2]);
const fs=require('node:fs');
const port=Number(process.argv[1]);
const out=process.argv[3];
const observed={webView2Attached:false,accountingRoot:false,madarNav:false,
  madarPage:false,sileoMounted:false,helpOpened:false,helpClosedViaPointer:false,
  printDesignerOpened:false,printPreviewRendered:false,templateSaved:false,
  financeCommandCalled:false,externalRequestsObserved:0,externalRequestsBlocked:0};
const allowed=u=>{try{const x=new URL(u);return x.protocol==='http:'&&
  (x.hostname==='127.0.0.1'||x.hostname==='localhost')}catch{return false}};
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let browser;
(async()=>{
  let page,context;
  for(let attempt=0;attempt<85;attempt++){
    try{
      browser=await chromium.connectOverCDP('http://127.0.0.1:'+port,{timeout:2300});
      context=browser.contexts()[0];
      for(const p of context?.pages()||[])if(allowed(p.url())&&p.url().includes('accounting.html'))page=p;
      if(page)break;
      await browser.close();browser=undefined;
    }catch(e){if(browser){try{await browser.close()}catch{}browser=undefined}}
    await pause(380);
  }
  if(!page)throw Error('Owned WebView2 CDP accounting target did not appear');
  observed.webView2Attached=true;
  page.setDefaultTimeout(7500);
  page.on('request',request=>{if(!allowed(request.url())&&!request.url().startsWith('blob:')&&
    !request.url().startsWith('data:'))observed.externalRequestsObserved++});
  await context.route('**/*',route=>{if(allowed(route.request().url()))return route.continue();
    observed.externalRequestsBlocked++;return route.abort('blockedbyclient')});
  await page.locator('.sac-root').waitFor({timeout:13000});
  observed.accountingRoot=true;
  observed.sileoMounted=await page.locator('.taraz-feedback-host').count()===1;
  observed.madarNav=await page.locator('.taraz-madar-quick-nav [data-accounting-tab="madar"]').count()===1;
  if(!observed.madarNav)throw Error('No direct Madar top navigation in compiled GUI');
  await page.locator('.taraz-madar-quick-nav [data-accounting-tab="madar"]').click();
  await page.locator('.taraz-madar-dashboard:not(.taraz-madar-home)').waitFor();
  observed.madarPage=true;
  const help=page.locator('.taraz-context-help-trigger');
  await help.click();
  await page.locator('.taraz-context-help-dialog').waitFor();
  observed.helpOpened=true;
  await page.locator('.taraz-context-help-close').click();
  await page.locator('.taraz-context-help-dialog').waitFor({state:'detached'});
  observed.helpClosedViaPointer=true;
  await page.locator('.sac-nav-more-trigger').click();
  await page.locator('.taraz-vt-drawer [data-accounting-tab="invoiceDesign"]').click();
  const designer=page.locator('.sac-print-designer');
  await designer.waitFor();
  observed.printDesignerOpened=true;
  const canvas=designer.locator('canvas[aria-label="نمای فاکتور قابل طراحی"]');
  await canvas.waitFor();
  observed.printPreviewRendered=await canvas.evaluate(x=>x.width>=600&&x.height>=600);
  const tag='QA-V103-PRIVATE-'+Math.random().toString(16).slice(2,12);
  const title=designer.locator('label').filter({hasText:'نام قالب'}).first().locator('input');
  await title.fill(tag);
  await page.getByRole('button',{name:'ذخیره قالب چاپ',exact:true}).click();
  await page.getByText('قالب «'+tag+'» در کتابخانه خصوصی این دفتر ذخیره شد.',{exact:false}).waitFor();
  observed.templateSaved=true;
  const toast=await page.locator('.taraz-feedback-host').innerText();
  observed.sileoToastShown=toast.includes('تغییرات قالب در میزبان ذخیره شد');
  observed.noExternalRequests=observed.externalRequestsObserved===0&&observed.externalRequestsBlocked===0;
  if(!observed.noExternalRequests)throw Error('Unexpected external browser request');
  if(!Object.entries(observed).filter(([k])=>k!=='sileoToastShown'&&k!=='externalRequestsObserved'&&
      k!=='externalRequestsBlocked'&&k!=='financeCommandCalled').every(([,v])=>v===true)){
    throw Error('Missing required compiled native UI feature');
  }
  fs.writeFileSync(out,JSON.stringify({status:'PASS',...observed},null,2)+'\n',{flag:'wx'});
})().catch(e=>{
  fs.writeFileSync(out,JSON.stringify({status:'FAIL',...observed,errorType:'CDP_CHECK_FAILED',
    error:String(e.message||e).slice(0,230)},null,2)+'\n',{flag:'wx'});
  process.exitCode=1;
}).finally(async()=>{if(browser)try{await browser.close()}catch{}});
"""


def run() -> Path:
    sources = pin()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    work = OUTPUT / ("qa-v103-" + uuid.uuid4().hex[:12])
    safe_copy.secure_private_directory(work)
    report_file = work / "native-result.json"
    outcome = {"status": "BLOCKED", "candidateSha256": EXE_SHA,
               "realNonQaExeLaunched": False, "privateDesktopCreated": False,
               "copiedOfflineBackupUsed": True, "syntheticEmptyProfileUsed": False,
               "installedVersionBefore": sources["installed"]["version"],
               "installedVersionAfter": None, "installedProfileWritten": False,
               "productionActivation": False}
    process_handle = thread_handle = None
    pid = 0
    tracked = {}
    started = None
    copied_ledger = None
    ledger_before = None
    try:
        runtime, roots = clone_offline_snapshot(work)
        copied_ledger = roots["roaming"] / "standalone-accounting.sqlite3"
        import sqlite3
        with sqlite3.connect(copied_ledger.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            ledger_before = db.execute("SELECT revision,digest FROM standalone_accounting WHERE id=1").fetchone()
        if not ledger_before:
            raise NativeBlocked("Cloned accounting book has no verified ledger head")
        native_report = work / "private-profile" / "native-webview-report.json"
        cdp_result = work / "private-profile" / "native-cdp-result.json"
        environment = isolated_env(runtime, roots, native_report, unused_port())
        port = int(environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"].split("--remote-debugging-port=")[1].split()[0])
        with PrivateDesktop() as desktop:
            outcome["privateDesktopCreated"] = True
            pid, process_handle, thread_handle = desktop.spawn(EXE, work, environment)
            outcome["realNonQaExeLaunched"] = True
            started = time.monotonic()
            capture_owned(pid, tracked)
            try:
                deadline=time.monotonic()+18
                while time.monotonic()<deadline and not native_report.exists():
                    time.sleep(.35)
                outcome["webView2RuntimeDiagnostics"]=safe_webview_diagnostics(pid,port)
                capture_owned(pid, tracked)
                outcome["uia"] = private_uia_probe(desktop,set(tracked),work,environment)
                if outcome["webView2RuntimeDiagnostics"]["cdpPortListening"]:
                    node = subprocess.run(["node", "-e", CDP_JS, str(port), str(PLAYWRIGHT), str(cdp_result)],
                        cwd=work, env=environment, capture_output=True, text=True,
                        errors="replace", timeout=83)
                    node_exit=node.returncode
                else:
                    node_exit=1
                outcome["ownedPrivateTarazWindow"] = bool(desktop.owned_windows(set(tracked)))
                if cdp_result.is_file():
                    observed = json.loads(cdp_result.read_text(encoding="utf-8"))
                    outcome["gui"] = observed
                else:
                    outcome["gui"] = {"status": "CDP_PORT_UNAVAILABLE"}
                if native_report.is_file():
                    native = json.loads(native_report.read_text(encoding="utf-8"))
                    outcome["nativeWebViewReport"] = {
                        "loaded": native.get("loaded") is True,
                        "accountingBridgePresent": native.get("accountingBridge") == "function",
                        "taskBridgeNotExposed": native.get("taskBridgeExposed") != "function",
                    }
                else:
                    outcome["nativeWebViewReport"] = {"loaded": False}
                outcome["nodeExitCode"] = node_exit
                outcome["runtimeSeconds"] = round(time.monotonic()-started, 2)
                if node_exit or not outcome["ownedPrivateTarazWindow"] or not all(
                        outcome["nativeWebViewReport"].values()) or outcome["gui"].get("status") != "PASS":
                    raise NativeBlocked("Compiled private desktop/WebView2 interactive acceptance incomplete")
                outcome["status"] = "PASS_REAL_NON_QA_PRIVATE_NATIVE_GUI"
            finally:
                outcome["cleanup"] = stop_owned(pid, tracked)
    except Exception as error:
        outcome["status"] = "FAIL_OR_INCOMPLETE_NATIVE_GUI"
        outcome["errorType"] = type(error).__name__
        outcome["error"] = str(error)[:270]
    finally:
        if pid:
            try: outcome["cleanup"] = stop_owned(pid, tracked)
            except Exception as error: outcome["cleanup"] = {"error": type(error).__name__}
        if process_handle:
            ctypes.windll.kernel32.CloseHandle(process_handle)
        if thread_handle:
            ctypes.windll.kernel32.CloseHandle(thread_handle)
        if copied_ledger is not None and ledger_before is not None:
            try:
                import sqlite3
                with sqlite3.connect(copied_ledger.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
                    db.execute("PRAGMA query_only=ON")
                    after_ledger=db.execute(
                        "SELECT revision,digest FROM standalone_accounting WHERE id=1").fetchone()
                    outcome["privateLedgerUnchanged"] = ledger_before == after_ledger
            except Exception as error:
                outcome["privateLedgerUnchanged"] = False
                outcome["privateLedgerReadbackError"] = type(error).__name__
        after = pins.installed_baseline(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz")
        outcome["installedVersionAfter"] = after["version"]
        outcome["installedBaselineUnchanged"] = after == sources["installed"]
        outcome["candidateExeUnchanged"] = digest(EXE) == EXE_SHA
        outcome["offlineBackupVerifiedAfter"] = pins.verify_backup(BACKUP)["filesRehashed"] == 181
        if (not outcome["installedBaselineUnchanged"] or not outcome["candidateExeUnchanged"] or
                not outcome["offlineBackupVerifiedAfter"] or
                outcome.get("privateLedgerUnchanged") is not True or
                outcome.get("cleanup", {}).get("ownedProcessesLeftAlive", 1)):
            outcome["status"] = "FAIL_CLEANUP_OR_BASELINE_CHANGED"
        report_file.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_file


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--run-private-native", action="store_true",
                     help="Explicitly launch only pinned executable on new hidden Win32 desktop")
    cli.add_argument("--static-only", action="store_true")
    options = cli.parse_args()
    try:
        if options.run_private_native:
            destination = run()
            info = json.loads(destination.read_text(encoding="utf-8"))
            print(json.dumps({"status": info["status"], "report": str(destination),
                "exePinned": info["candidateExeUnchanged"],
                "nativeWebViewLoaded": info.get("nativeWebViewReport", {}).get("loaded", False),
                "installedBaselineUnchanged": info["installedBaselineUnchanged"]}, ensure_ascii=False))
            sys.exit(0 if info["status"] == "PASS_REAL_NON_QA_PRIVATE_NATIVE_GUI" else 1)
        else:
            item = pin()
            print(json.dumps({"status": "STATIC_PIN_PASS_NATIVE_NOT_LAUNCHED",
                              "candidateSha256": EXE_SHA,
                              "installedVersion": item["installed"]["version"],
                              "offlineBackupVerified": item["backup"]["filesRehashed"]}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"status": "BLOCKED", "errorType": type(error).__name__,
                          "error": str(error)[:270]}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
