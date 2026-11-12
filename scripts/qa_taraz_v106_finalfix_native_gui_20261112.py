"""Final v1.0.6 native GUI test, exact immutable EXE and private Windows desktop.

New QA artifacts only. Never switches desktops, sends global user input, submits
financial forms, runs the installer or signs code. Navigates through exact
owned UIA buttons, attempts private PrintWindow screenshots and closes only
the new QA window with WM_CLOSE. No force-termination of any process.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v103_native_gui_20261111 as native
from scripts import qa_taraz_v103_independent_acceptance_20261111 as backup
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acl
from scripts import build_taraz_v106_aaas_20261111 as builder

ARTIFACTS = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.6-aaas"
BUILD = ARTIFACTS / "build-e1723a88abe2"
EXE = BUILD / "binary" / "Taraz.exe"
SOURCE_SHA = "d926f949b1d002f9a9cdad55265efd313908d61e54e077a4b1b86d06cedc2c1b"
EXE_SHA = "eded01af7c8e2676b427a30f8bdabd41d59fba9df4e99a42995cd2d6184f6251"
RESULTS = ARTIFACTS / "finalfix-native-gui-qa-20261112"


class Blocked(RuntimeError):
    pass


def sha(file: Path) -> str:
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def no_links(file: Path) -> None:
    for item in (file, *file.parents):
        if item.exists() and (item.is_symlink() or bool(
            getattr(item.lstat(), "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )):
            raise Blocked("Linked/junction candidate or profile path")


def candidate() -> dict:
    if os.name != "nt":
        raise Blocked("Requires native Windows")
    for path in (EXE, BUILD / "build-report.json", RESULTS):
        no_links(path)
    if not EXE.is_file() or sha(EXE) != EXE_SHA:
        raise Blocked("Exact final immutable EXE missing or SHA mismatch")
    build = json.loads((BUILD / "build-report.json").read_text(encoding="utf-8"))
    compiled = build.get("compiled", {})
    if not (
        build.get("sourceFreezeSha256") == SOURCE_SHA
        and build.get("exeSha256") == EXE_SHA
        and build.get("status") == "V106_AAAS_NON_QA_BUILT_NOT_INSTALLED"
        and build.get("version") == "1.0.6"
        and build.get("installed") is False
        and build.get("pointerChanged") is False
        and compiled.get("qaOnly") is False
        and compiled.get("bridgeForwarded") is True
        and compiled.get("compiledByteParity") is True
        and compiled.get("peVersion") == "1.0.6.0"
    ):
        raise Blocked("Candidate report does not bind the final EXE and source")
    from PyInstaller.archive.readers import CArchiveReader
    bundle = CArchiveReader(str(EXE))
    manifest = compiled.get("assetsSha256", {})
    js = {k: v for k, v in manifest.items() if
          k.startswith("assets/accounting-") and k.endswith(".js")}
    if len(js) != 1:
        raise Blocked("Ambiguous compiled GUI JS")
    item, expected = next(iter(js.items()))
    frozen = bundle.extract("dist\\" + item.replace("/", "\\"))
    if not isinstance(frozen, bytes) or hashlib.sha256(frozen).hexdigest() != expected:
        raise Blocked("Embedded real EXE GUI assets mismatch")
    verified = backup.verify_backup(backup.BACKUP)
    if verified.get("filesRehashed") != 181:
        raise Blocked("Cold offline snapshot provenance not verified")
    return {"sourceSha": SOURCE_SHA, "exeSha": EXE_SHA,
            "embeddedJsSha": expected, "backupFilesRehashed": 181}


# Only navigational UIA button names. No record creation, deletion, approval,
# invoice post, Madar consent, finance issue or save action.
PRIVATE_UIA = r'''
param([Parameter(Mandatory=$true)][string]$OwnerIds,
      [Parameter(Mandatory=$true)][string]$ResultFile,
      [Parameter(Mandatory=$true)][string]$ScreenshotFolder)
$ErrorActionPreference='Stop'
$out=@{
 status='INITIAL'; ownedWindow=$false; startupCapture=$false;
 startupCaptureHasVariation=$false; screenshotPaths=@{};
 orderVisible=$false; orderInvoked=$false; orderContentVisible=$false;
 orderProfessionalInvoked=$false; orderProfessionalContentVisible=$false;
 invoiceVisible=$false; invoiceInvoked=$false; invoiceContentVisible=$false;
 invoiceBeginnerOpened=$false; invoiceBeginnerContentVisible=$false;
 printVisible=$false; printInvoked=$false; printContentVisible=$false;
 printScrollMessagePosted=$false; printScrolledImageCaptured=$false;
 drawerVisible=$false; drawerInvoked=$false; drawerOpen=$false;
 helpVisible=$false; helpInvoked=$false;
 uiAutomationExceptionType=''; perNavigation=@{};
 noFinanceActionAttempted=$true; noGlobalInputUsed=$true;
 privateWindowOwnerVerified=$false; safeTargetedWin32MessageAttempted=$false;
 targetedMessageAppliedToOwnedChild=$false; targetedMessageControl='';
 buttonErrors=@{}
}
try {
 Add-Type -AssemblyName UIAutomationClient
 Add-Type -AssemblyName UIAutomationTypes
 Add-Type -AssemblyName System.Drawing
 Add-Type -TypeDefinition @"
 using System;
 using System.Runtime.InteropServices;
 public static class TarazPrivateCapture {
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool PrintWindow(IntPtr hWnd, IntPtr hDC, uint flags);
 }
 public static class TarazPrivateInput {
  public struct Point { public int X; public int Y; }
  public struct Rect { public int L; public int T; public int R; public int B; }
  public delegate bool Callback(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(
    IntPtr parent, Callback callback, IntPtr lParam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(
    IntPtr hwnd, out uint pid);
  [DllImport("user32.dll",CharSet=CharSet.Unicode)]
  public static extern int GetClassName(IntPtr hwnd,System.Text.StringBuilder output,int count);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd,out Rect r);
  [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr hwnd,ref Point p);
  [DllImport("user32.dll")] public static extern bool PostMessage(
    IntPtr hwnd,uint message,IntPtr w,IntPtr l);
 }
"@
 $ids=@($OwnerIds.Split(',') | ForEach-Object {[int]$_})
 $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll(
  [System.Windows.Automation.TreeScope]::Children,
  [System.Windows.Automation.Condition]::TrueCondition)
 $ours=@($windows | Where-Object {
  ($ids -contains [int]$_.Current.ProcessId) -and
  $_.Current.Name -like '*تراز*'
 })
 if($ours.Count -ne 1){throw 'Private owned Taraz UIA window ambiguous'}
 $root=$ours[0]
 $out.ownedWindow=$true
 $out.privateWindowOwnerVerified=($ids -contains [int]$root.Current.ProcessId)
 function Named([string]$name) {
  $filter=New-Object System.Windows.Automation.PropertyCondition(
   [System.Windows.Automation.AutomationElement]::NameProperty,$name)
  $all=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$filter)
  return @($all | Where-Object { $ids -contains [int]$_.Current.ProcessId })
 }
 function Has([string[]]$names) {
  foreach($name in $names){if(@(Named $name).Count -gt 0){return $true}}
  return $false
 }
 function Activate([string]$name) {
  $controls=@(Named $name | Where-Object {
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
   $_.Current.IsEnabled
  })
  $observed=@{count=$controls.Count;invokePattern=$false;
    legacyPattern=$false;actionTaken=$false;postedPrivateWin32=$false;namedButton=$name}
  foreach($button in $controls) {
   try {
    $pattern=$null
    if($button.TryGetCurrentPattern(
       [System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){
       $observed.invokePattern=$true
       try{$pattern.Invoke();$observed.actionTaken=$true;break}catch{}
    }
    $legacy=$null
    if($button.TryGetCurrentPattern(
       [System.Windows.Automation.LegacyIAccessiblePattern]::Pattern,[ref]$legacy)){
       $observed.legacyPattern=$true
       try {
        if([int]$legacy.Current.Role -eq 43) {
         $legacy.DoDefaultAction();$observed.actionTaken=$true;break
        }
       } catch {}
    }
   } catch {
    $out.buttonErrors[$name]=$_.Exception.GetType().Name
   }
  }
  # Message input is strictly scoped to an owned WebView child HWND on this
  # private desktop. Never SendInput, SetForegroundWindow or SwitchDesktop.
  if(-not $observed.actionTaken -and $controls.Count -gt 0 -and
     $name -in @('بازکردن فهرست بخش‌های تراز','سفارش‌ها','طراحی فرم فاکتور')){
    try {
     $button=$controls[0]
     $b=$button.Current.BoundingRectangle
     if($b.Width -ge 12 -and $b.Height -ge 12 -and
        $b.Width -lt 1000 -and $b.Height -lt 160){
      $cx=[int][Math]::Round($b.X + $b.Width/2)
      $cy=[int][Math]::Round($b.Y + $b.Height/2)
      $target=[IntPtr]::Zero
      $found=New-Object 'System.Collections.Generic.List[System.IntPtr]'
      $cb=[TarazPrivateInput+Callback]{
       param($hwnd,$ignore)
       $owner=[uint32]0
       [void][TarazPrivateInput]::GetWindowThreadProcessId($hwnd,[ref]$owner)
       if($ids -notcontains [int]$owner){return $true}
       $cls=New-Object System.Text.StringBuilder 140
       [void][TarazPrivateInput]::GetClassName($hwnd,$cls,$cls.Capacity)
       if($cls.ToString() -notmatch 'Chrome_RenderWidgetHostHWND'){return $true}
       $rect=New-Object TarazPrivateInput+Rect
       if([TarazPrivateInput]::GetWindowRect($hwnd,[ref]$rect) -and
          $cx -ge $rect.L -and $cx -lt $rect.R -and
          $cy -ge $rect.T -and $cy -lt $rect.B){
        $found.Add($hwnd)
       }
       return $true
      }
      [void][TarazPrivateInput]::EnumChildWindows(
       [IntPtr]$root.Current.NativeWindowHandle,$cb,[IntPtr]::Zero)
      if($found.Count -eq 1) {
       $target=$found[0]
       $point=New-Object TarazPrivateInput+Point
       $point.X=$cx;$point.Y=$cy
       if([TarazPrivateInput]::ScreenToClient($target,[ref]$point) -and
          $point.X -ge 0 -and $point.Y -ge 0 -and
          $point.X -lt 32767 -and $point.Y -lt 32767){
        $lp=[IntPtr]::new(([int](($point.Y -shl 16) -bor $point.X)))
        $out.safeTargetedWin32MessageAttempted=$true
        $down=[TarazPrivateInput]::PostMessage(
          $target,[uint32]0x0201,[IntPtr]::new(1),$lp)
        $up=[TarazPrivateInput]::PostMessage(
          $target,[uint32]0x0202,[IntPtr]::Zero,$lp)
        $observed.postedPrivateWin32=($down -and $up)
        if($observed.postedPrivateWin32){
          $out.targetedMessageAppliedToOwnedChild=$true
          $out.targetedMessageControl=$name
        }
       }
      }
     }
    } catch {
      $out.buttonErrors[$name]=$_.Exception.GetType().Name
    }
  }
  $out.perNavigation[$name]=$observed
  return [bool]$observed.actionTaken
 }
 function Capture([string]$label) {
  $bounds=$root.Current.BoundingRectangle
  $w=[int][Math]::Ceiling($bounds.Width)
  $h=[int][Math]::Ceiling($bounds.Height)
  if($w -lt 400 -or $h -lt 250 -or $w -gt 2500 -or $h -gt 1800){return $false}
  $png=Join-Path $ScreenshotFolder ("private-"+$label+".png")
  $bmp=New-Object System.Drawing.Bitmap($w,$h)
  $graphics=[System.Drawing.Graphics]::FromImage($bmp)
  $handle=[IntPtr]::Zero
  try {
   $handle=$graphics.GetHdc()
   $ok=[TarazPrivateCapture]::PrintWindow(
     [IntPtr]$root.Current.NativeWindowHandle,$handle,[uint32]2)
   $graphics.ReleaseHdc($handle);$handle=[IntPtr]::Zero
   if($ok){
    $bmp.Save($png,[System.Drawing.Imaging.ImageFormat]::Png)
    $out.screenshotPaths[$label]=$png
    # A sampled pixel mismatch is a very weak paint witness, never visual QA.
    $pixels=@($bmp.GetPixel(2,2).ToArgb(),$bmp.GetPixel(
      [int]($w/2),[int]($h/2)).ToArgb(),$bmp.GetPixel(
      [int]($w/3),[int]($h/3)).ToArgb())
    return (@($pixels | Select-Object -Unique).Count -gt 1)
   }
   return $false
  } finally {
   if($handle -ne [IntPtr]::Zero){$graphics.ReleaseHdc($handle)}
   $graphics.Dispose();$bmp.Dispose()
  }
 }
 function ScrollPrivatePrint {
  $bounds=$root.Current.BoundingRectangle
  $x=[int][Math]::Round($bounds.X+$bounds.Width*.72)
  $y=[int][Math]::Round($bounds.Y+$bounds.Height*.70)
  $found=New-Object 'System.Collections.Generic.List[System.IntPtr]'
  $callback=[TarazPrivateInput+Callback]{
    param($hwnd,$ignore)
    $owner=[uint32]0
    [void][TarazPrivateInput]::GetWindowThreadProcessId($hwnd,[ref]$owner)
    if($ids -notcontains [int]$owner){return $true}
    $cls=New-Object System.Text.StringBuilder 140
    [void][TarazPrivateInput]::GetClassName($hwnd,$cls,$cls.Capacity)
    if($cls.ToString() -notmatch 'Chrome_RenderWidgetHostHWND'){return $true}
    $r=New-Object TarazPrivateInput+Rect
    if([TarazPrivateInput]::GetWindowRect($hwnd,[ref]$r) -and
      $x -ge $r.L -and $x -lt $r.R -and $y -ge $r.T -and $y -lt $r.B){
      $found.Add($hwnd)
    }
    return $true
  }
  [void][TarazPrivateInput]::EnumChildWindows(
    [IntPtr]$root.Current.NativeWindowHandle,$callback,[IntPtr]::Zero)
  if($found.Count -ne 1){return $false}
  $lp=[IntPtr]::new([int](($y -shl 16) -bor ($x -band 0xffff)))
  $wp=[IntPtr]::new([int](-120 -shl 16))
  $sent=$true
  foreach($i in 1..5){
    $sent=$sent -and [TarazPrivateInput]::PostMessage(
      $found[0],[uint32]0x020A,$wp,$lp)
    Start-Sleep -Milliseconds 60
  }
  return $sent
 }
 $out.startupCaptureHasVariation=Capture 'startup'
 $out.startupCapture=($out.screenshotPaths.ContainsKey('startup'))
 $out.orderVisible=Has @('سفارش‌ها','فرم ثبت سفارش','مدیریت سفارش‌های تراز')
 $out.invoiceVisible=Has @('فاکتورهای فروش','فروش','فاکتور فروش جدید')
 $out.printVisible=Has @('طراحی فرم فاکتور','طراح قالب چاپ فاکتور')
 $out.drawerVisible=Has @('بازکردن فهرست بخش‌های تراز')
 $out.helpVisible=Has @('راهنما','راهنمای داشبورد')
 # Try directly visible navigation buttons BEFORE drawer. On each navigation
 # inspect unique content markers, not the old button still mounted offscreen.
 try{$out.orderInvoked=Activate 'سفارش‌ها'}catch{$out.buttonErrors['سفارش‌ها']=$_.Exception.GetType().Name}
 if($out.orderInvoked){
  Start-Sleep -Milliseconds 500
  $out.orderContentVisible=Has @('مدیریت سفارش‌های تراز','فرم ثبت سفارش',
    'سفارش جدید','سطح فرم سفارش')
  $null=Capture 'order'
 }
 try{$out.invoiceInvoked=Activate 'فروش'}catch{$out.buttonErrors['فروش']=$_.Exception.GetType().Name}
 if(-not $out.invoiceInvoked){try{$out.invoiceInvoked=Activate 'فاکتورهای فروش'}catch{}}
 if($out.invoiceInvoked){
  Start-Sleep -Milliseconds 500
  $out.invoiceContentVisible=Has @('فاکتورهای فروش','ثبت فاکتور جدید',
    'فاکتور در یک صفحه','مشتری فاکتور')
  $null=Capture 'invoice'
 }
 try{$out.printInvoked=Activate 'طراحی فرم فاکتور'}catch{$out.buttonErrors['طراحی فرم فاکتور']=$_.Exception.GetType().Name}
 if($out.printInvoked){
  Start-Sleep -Milliseconds 500
  $out.printContentVisible=Has @('طراح قالب چاپ فاکتور',
    'شروع با چیدمان آماده','نام قالب','سبک چیدمان')
  $null=Capture 'print'
 }
 if(-not $out.printInvoked -or -not $out.orderInvoked){
  try{$out.drawerInvoked=Activate 'بازکردن فهرست بخش‌های تراز'}catch{$out.buttonErrors['بازکردن فهرست بخش‌های تراز']=$_.Exception.GetType().Name}
  if($out.drawerInvoked -or $out.targetedMessageAppliedToOwnedChild) {
   Start-Sleep -Milliseconds 450
   $out.drawerOpen=Has @('فهرست بخش‌های تراز','بستن فهرست')
   $null=Capture 'drawer'
   if($out.drawerOpen -and -not $out.orderInvoked){
     try{$out.orderInvoked=Activate 'سفارش‌ها'}catch{$out.buttonErrors['سفارش‌ها']=$_.Exception.GetType().Name}
     if($out.orderInvoked) {
       Start-Sleep -Milliseconds 500
       $out.orderContentVisible=Has @('فرم ثبت سفارش','سفارش جدید')
       $null=Capture 'order'
       if($out.orderContentVisible){
         try {
           $out.orderProfessionalInvoked=Activate 'حرفه‌ای'
           if($out.orderProfessionalInvoked){
             Start-Sleep -Milliseconds 350
             $out.orderProfessionalContentVisible=Has @(
               'شناسه طرف حساب موجود (اختیاری)','جزئیات تأمین')
             $null=Capture 'order-professional'
           }
         }catch{$out.buttonErrors['order-professional']=$_.Exception.GetType().Name}
       }
     }
   }
   # A successful order navigation dismisses the drawer. Reopen the same
   # verified private menu before attempting the print-designer action.
   if($out.orderInvoked -and -not (Has @('طراحی فرم فاکتور'))) {
     try {
       $again=Activate 'بازکردن فهرست بخش‌های تراز'
       Start-Sleep -Milliseconds 450
       $out.drawerOpen=Has @('فهرست بخش‌های تراز','بستن فهرست')
       $null=Capture 'drawer-before-print'
     }catch{
       $out.buttonErrors['reopen-private-menu']=$_.Exception.GetType().Name
     }
   }
   if(-not $out.printInvoked){
    try{$out.printInvoked=Activate 'طراحی فرم فاکتور'}catch{$out.buttonErrors['طراحی فرم فاکتور']=$_.Exception.GetType().Name}
    if($out.printInvoked) {
     Start-Sleep -Milliseconds 500
     $out.printContentVisible=Has @('طراح قالب چاپ فاکتور','نام قالب')
     $null=Capture 'print'
     try {
       $out.printScrollMessagePosted=ScrollPrivatePrint
       if($out.printScrollMessagePosted){
         Start-Sleep -Milliseconds 450
         $null=Capture 'print-scrolled'
         $out.printScrolledImageCaptured=$out.screenshotPaths.ContainsKey('print-scrolled')
       }
     }catch{$out.buttonErrors['print-private-scroll']=$_.Exception.GetType().Name}
    }
   }
  }
 }
 # Safely open a new invoice composer AFTER all other screen navigation. No
 # form input, save, issue, financial mutation or additional confirmation.
 if($out.printContentVisible) {
   try {
     $backToSales=Activate 'فروش'
     if($backToSales){
       Start-Sleep -Milliseconds 400
       $out.invoiceBeginnerOpened=Activate 'ثبت فاکتور جدید'
       if($out.invoiceBeginnerOpened) {
         Start-Sleep -Milliseconds 500
         $out.invoiceBeginnerContentVisible=Has @(
           'شرح ردیف 1','مشتری فاکتور','فاکتور در یک صفحه','بررسی پیش از ذخیره')
         $null=Capture 'invoice-beginner'
       }
     }
   }catch{$out.buttonErrors['open-unsaved-invoice-form']=$_.Exception.GetType().Name}
 }
 $out.status='PRIVATE_OWNED_UIA_RECORDED'
} catch {
 $out.status='UIA_PROBE_ERROR'
 $out.uiAutomationExceptionType=$_.Exception.GetType().Name
}
[IO.File]::WriteAllText($ResultFile,
 ($out | ConvertTo-Json -Depth 8 -Compress),[Text.UTF8Encoding]::new($false))
'''


def snapshot_pids() -> dict[int, float]:
    import psutil
    result = {}
    for process in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if (process.info.get("name") or "").casefold() == "taraz.exe":
                result[process.info["pid"]] = process.info["create_time"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return result


def owned_window_handles(desktop, valid_pids: set[int]) -> list[int]:
    """Only window handles enumerated on this new private Win32 desktop."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    windows = []

    @CALLBACK
    def visit(hwnd, _ignored):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in valid_pids or not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        if "تراز" in title.value:
            windows.append(int(hwnd))
        return True

    if not user32.EnumDesktopWindows(desktop.handle, visit, 0):
        raise Blocked("Could not enumerate private desktop owned windows")
    return windows


def helper_ui(desktop, pids: set[int], work: Path, env: dict) -> dict:
    powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    script = work / "private-profile" / "owned-uia.ps1"
    output = work / "private-profile" / "owned-uia.json"
    script.write_text(PRIVATE_UIA, encoding="utf-8-sig")
    pid, handle, thread = desktop.spawn(
        powershell, work, env,
        ("-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-OwnerIds", ",".join(map(str, sorted(pids))),
         "-ResultFile", str(output),
         "-ScreenshotFolder", str(work / "private-profile")),
    )
    kernel = ctypes.windll.kernel32
    try:
        finish = kernel.WaitForSingleObject(handle, 30000)
        if finish != 0:
            return {"status": "PRIVATE_UIA_WAIT_TIMEOUT_NO_TERMINATE",
                    "helperProcessMayRemain": True}
        if not output.is_file():
            return {"status": "PRIVATE_UIA_NO_OUTPUT"}
        payload = json.loads(output.read_text(encoding="utf-8-sig"))
        # Screenshots stay private; never inline or attach the clone by default.
        return payload
    finally:
        kernel.CloseHandle(handle)
        kernel.CloseHandle(thread)


def run() -> Path:
    pins = candidate()
    baseline = builder.installed_baseline()
    originals = snapshot_pids()
    if not RESULTS.exists():
        acl.secure_private_directory(RESULTS)
    work = RESULTS / ("qa-final-native-" + uuid.uuid4().hex[:12])
    acl.secure_private_directory(work)
    report_file = work / "native-gui-report.json"
    report = {"status": "STARTED", "build": BUILD.name, **pins,
              "nativeExeLaunched": False, "nativeWebViewLoaded": False,
              "accountingBridgePresent": False, "privateDesktop": False,
              "privateLedgerUnchanged": None, "baselineUnchanged": None,
              "priorTarazPidsPreserved": None, "qaProcessClosedGracefully": None,
              "noProcessForceKilled": True, "financeActionAttempted": False,
              "noRealDesktopInput": True}
    pid = 0
    handles = []
    ledger_file = None
    old_digest = None
    owned = {}
    try:
        runtime, paths = native.clone_offline_snapshot(work)
        ledger_file = paths["roaming"] / "standalone-accounting.sqlite3"
        old_digest = sha(ledger_file)
        status_file = work / "private-profile" / "native-status.json"
        env = native.isolated_env(runtime, paths, status_file, native.unused_port())
        # CDP was not supported by the frozen production WebView2. Do not
        # expose a long-lived port or try mutating the EXE.
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = " ".join(
            token for token in env.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "").split()
            if not token.startswith("--remote-debugging-"))
        for key in ("APPDATA", "LOCALAPPDATA", "TEMP"):
            if Path(env[key]).resolve() == Path(os.environ[key]).resolve():
                raise Blocked("Isolated QA environment equals live directory: " + key)
        with native.PrivateDesktop() as desktop:
            report["privateDesktop"] = True
            pid, process_handle, thread_handle = desktop.spawn(EXE, work, env)
            handles += [process_handle, thread_handle]
            import psutil
            proc = psutil.Process(pid)
            if Path(proc.exe()).resolve() != EXE.resolve():
                raise Blocked("Spawned PID binary identity mismatch")
            report["nativeExeLaunched"] = True
            owned[pid] = proc.create_time()
            start = time.monotonic()
            while time.monotonic() - start < 21 and not status_file.is_file():
                time.sleep(.3)
            if status_file.is_file():
                status = json.loads(status_file.read_text(encoding="utf-8"))
                report["nativeWebViewLoaded"] = status.get("loaded") is True
                report["accountingBridgePresent"] = status.get("accountingBridge") == "function"
            if not (report["nativeWebViewLoaded"] and report["accountingBridgePresent"]):
                raise Blocked("Native WebView/bridge startup gates failed")
            children = proc.children(recursive=True)
            for child in children:
                owned[child.pid] = child.create_time()
            report["ownedWebView2Count"] = sum(
                child.name().lower() == "msedgewebview2.exe" for child in children
            )
            report["privateWindowCount"] = len(owned_window_handles(desktop, set(owned)))
            report["uia"] = helper_ui(desktop, set(owned), work, env)
            # Post WM_CLOSE to one verified private QA window only.
            windows = owned_window_handles(desktop, set(owned))
            if len(windows) == 1:
                user32 = ctypes.windll.user32
                report["wmClosePostedToOwnedPrivateWindow"] = bool(
                    user32.PostMessageW(windows[0], 0x0010, 0, 0))
            else:
                report["wmClosePostedToOwnedPrivateWindow"] = False
            try:
                proc.wait(timeout=14)
                report["qaProcessClosedGracefully"] = True
            except psutil.TimeoutExpired:
                report["qaProcessClosedGracefully"] = False
                report["qaProcessRemainedRunningPid"] = pid
    except Exception as exc:
        report["executionExceptionType"] = type(exc).__name__
        report["executionError"] = str(exc)[:160]
    finally:
        for handle in handles:
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
        if ledger_file and ledger_file.is_file() and old_digest:
            report["privateLedgerUnchanged"] = sha(ledger_file) == old_digest
        try:
            report["baselineUnchanged"] = builder.installed_baseline() == baseline
        except Exception:
            report["baselineUnchanged"] = False
        report["priorTarazPidsPreserved"] = all(
            snapshot_pids().get(k) == v for k, v in originals.items())
        report["exactExeStillIntact"] = sha(EXE) == EXE_SHA
        # All stop conditions remain read-only; never psutil.kill/terminate.
        # Any stubborn QA child is reported as a blocker for human cleanup.
        screens = report.get("uia", {})
        validated = all((
            report["nativeExeLaunched"],
            report["nativeWebViewLoaded"],
            report["accountingBridgePresent"],
            report["privateDesktop"],
            report["baselineUnchanged"],
            report["privateLedgerUnchanged"],
            report["priorTarazPidsPreserved"],
            report["exactExeStillIntact"],
            report["qaProcessClosedGracefully"] is True,
            screens.get("ownedWindow") is True,
        ))
        visited = all(screens.get(key) is True for key in
                      ("orderContentVisible", "invoiceContentVisible", "printContentVisible"))
        report["status"] = (
            "PASS_NATIVE_THREE_SCREEN_NAVIGATION_VIEW_ONLY" if validated and visited
            else "PARTIAL_NATIVE_GUI_VIEW_ONLY" if validated
            else "INCOMPLETE_NATIVE_GUI_OR_SAFETY")
        report_file.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    option = parser.add_mutually_exclusive_group(required=True)
    option.add_argument("--static", action="store_true")
    option.add_argument("--run-private", action="store_true")
    opts = parser.parse_args()
    try:
        if opts.static:
            print(json.dumps({"status": "STATIC_PIN_ONLY", **candidate()},
                             indent=2, ensure_ascii=False))
            return 0
        result = run()
        report = json.loads(result.read_text(encoding="utf-8"))
        print(json.dumps({
            "status": report["status"], "report": str(result),
            "uia": report.get("uia", {}),
            "gracefulClose": report.get("qaProcessClosedGracefully"),
            "ledgerUnchanged": report.get("privateLedgerUnchanged"),
            "installedUnchanged": report.get("baselineUnchanged"),
            "priorPidsPreserved": report.get("priorTarazPidsPreserved")
        }, ensure_ascii=True))
        return 0 if report["status"] == "PASS_NATIVE_THREE_SCREEN_NAVIGATION_VIEW_ONLY" else 1
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "errorType": type(exc).__name__,
                          "error": str(exc)[:180]}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
