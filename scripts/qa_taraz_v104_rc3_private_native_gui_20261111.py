"""Fail-closed native Windows startup smoke for the EXACT uninstalled RC3 Taraz EXE.

Imports proven v103 private desktop / cold-backup-copy primitives READ ONLY.
There is no SwitchDesktop, global input, installed-profile access by the EXE,
Madar service call, financial command, native click, or production activation.
The report contains only status/boolean/count evidence, not private ledger data.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import time
import types
import uuid

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

# Source-provenance reuse, not edits, monkeypatches, or launching legacy EXEs.
from scripts import qa_taraz_v103_native_gui_20261111 as legacy
from scripts import qa_taraz_v103_independent_acceptance_20261111 as pins
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as private_acl

ROOT = PROJECT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110"
BUILD = ROOT / "taraz-v1.0.4-p1" / "build-0bde36e11d99"
EXE = BUILD / "binary" / "Taraz.exe"
EXE_SHA = "9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce"
SOURCE_SHA = "e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de"
JS_SHA = "3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9"
BACKUP = pins.BACKUP
OUTPUT = ROOT / "taraz-v104-rc3-private-native-gui-qa"
PE_VERSION = "1.0.4.0"


class NativeBlocked(RuntimeError):
    """Failed safety gate, not native release acceptance."""


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for part in iter(lambda: source.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def safe_file(path: Path) -> Path:
    for component in (path, *path.parents):
        if component.exists() and (component.is_symlink() or
               bool(getattr(component.lstat(), "st_file_attributes", 0) & 0x400)):
            raise NativeBlocked("Refused reparse or symlink in trusted path")
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise NativeBlocked("Required regular candidate file missing")
    return path


def baseline() -> dict:
    """No mutations. Verifies EXE/PYZ/PE/UI and 181-bytewise cold backup."""
    if os.name != "nt":
        raise NativeBlocked("Native Windows GUI requires Windows")
    safe_file(EXE)
    if digest(EXE) != EXE_SHA:
        raise NativeBlocked("Pinned RC3 EXE SHA mismatch; never launch")
    report = json.loads(safe_file(BUILD / "build-report.json").read_text(encoding="utf-8"))
    if (report.get("exeSha256") != EXE_SHA or report.get("version") != "1.0.4" or
            report.get("sourceFreezeSha256") != SOURCE_SHA or
            report.get("releaseCandidateRevision") != "RC3" or
            report.get("status") != "PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED" or
            report.get("installed") is not False or
            report.get("pointerChanged") is not False or
            report.get("compiled", {}).get("nonQaRuntime") is not True or
            report.get("compiled", {}).get("peVersion") != PE_VERSION or
            report.get("compiled", {}).get("pyzVersion") != "1.0.4" or
            report.get("viteStage", {}).get("jsSha256") != JS_SHA):
        raise NativeBlocked("RC3 build report is not the approved uninstalled candidate")
    if pins.pe_fixed_version(EXE) != PE_VERSION:
        raise NativeBlocked("Actual native PE fixed-file version mismatch")
    from PyInstaller.archive.readers import CArchiveReader
    outer = CArchiveReader(str(EXE))
    js = outer.extract("dist\\assets\\accounting-5ZRme707.js")
    if not isinstance(js, bytes) or hashlib.sha256(js).hexdigest() != JS_SHA:
        raise NativeBlocked("Actual EXE embedded JS differs from RC3 source")
    code = outer.open_embedded_archive("PYZ.pyz").extract("taraz_release_version")
    if not isinstance(code, types.CodeType) or (
            pins._assigned_constant(code, "APP_VERSION") != "1.0.4" or
            pins._assigned_constant(code, "QA_ONLY") is not False):
        raise NativeBlocked("Actual PYZ is not nonQA 1.0.4")
    installed = pins.installed_baseline(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz")
    if not installed["futureFolderAbsent"] or (
            Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz" / "versions" / "1.0.4").exists():
        raise NativeBlocked("Installed version 1.0.4 already exists: unsafe to run QA")
    backed_up = pins.verify_backup(BACKUP)
    if backed_up.get("filesRehashed") != 181:
        raise NativeBlocked("Cold backup 181-file integrity was not verified")
    return {"installed": installed, "backup": backed_up}


def live_process_facts() -> dict:
    """Observe only PID/start identity; never signal or query user UI content."""
    import psutil
    processes = {}
    for process in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if (process.info["name"] or "").casefold() == "taraz.exe":
                processes[process.info["pid"]] = float(process.info["create_time"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes


def visible_window_facts() -> dict[int, int]:
    """Read-only EnumWindows on original desktop; no title/cursor/input."""
    if os.name != "nt":
        return {}
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    result = {}

    @callback_type
    def observe(hwnd, _ignored):
        if user32.IsWindowVisible(hwnd):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            result[int(hwnd)] = owner.value
        return True

    if not user32.EnumWindows(observe, 0):
        raise NativeBlocked("Could not observe original desktop windows for noninterference gate")
    return result


def capture_owned(root_pid: int, tracked: dict[int, float]) -> set[int]:
    import psutil
    try:
        root = psutil.Process(root_pid)
        if Path(root.exe()).resolve() != EXE.resolve():
            raise NativeBlocked("Owned root process executable identity changed")
        tracked[root.pid] = root.create_time()
        for item in root.children(recursive=True):
            try:
                tracked[item.pid] = item.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except psutil.NoSuchProcess:
        pass
    return set(tracked)


def stop_owned(root_pid: int, tracked: dict[int, float]) -> dict:
    """Only kill processes whose exact PID and creation time were recorded."""
    import psutil
    capture_owned(root_pid, tracked)
    owned = []
    for pid, created in tracked.items():
        try:
            process = psutil.Process(pid)
            if process.create_time() == created:
                owned.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    for process in reversed(owned):
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(owned, timeout=8)
    return {"ownedProcessesObserved": len(tracked),
            "ownedProcessesLeftAlive": len(alive),
            "unrelatedPidTargeted": False}


# The UIA reader is launched *on the same private non-input desktop*.
# It does NOT invoke a button or click, even a view-only one. This avoids
# accidentally invoking a Madar service or an accounting bridge.
PRIVATE_READONLY_UIA_PS = r'''
param([Parameter(Mandatory=$true)][string]$OwnerIds,
      [Parameter(Mandatory=$true)][string]$ResultFile)
$ErrorActionPreference='Stop'
$answer=@{status='BLOCKED_UIA'; ownedWindow=$false; startupControlsObserved=$false;
  navigationReadOnly=$true; navigationPerformed=$false;
  madarServiceActionAttempted=$false; financeActionAttempted=$false;
  ownedNamedControlCount=0; privateOwnerMatch=$false}
try {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
  $ids=@($OwnerIds.Split(',') | ForEach-Object { [int]$_ })
  $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll(
    [System.Windows.Automation.TreeScope]::Children,
    [System.Windows.Automation.Condition]::TrueCondition)
  $ours=@($windows | Where-Object {
    ($ids -contains $_.Current.ProcessId) -and $_.Current.Name -like '*تراز*'
  })
  if($ours.Count -ne 1){throw 'Owned private UIA window not unique'}
  $root=$ours[0]
  $answer.ownedWindow=$true
  $answer.privateOwnerMatch=($ids -contains [int]$root.Current.ProcessId)
  $names=@('اطلاعات مدار','طراحی فرم فاکتور',
    'بازکردن فهرست بخش‌های تراز','راهنما','نام قالب')
  foreach($name in $names){
    $match=$root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
      (New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty,$name)))
    if($null -ne $match -and ($ids -contains [int]$match.Current.ProcessId)){
      $answer.ownedNamedControlCount++
    }
  }
  $answer.startupControlsObserved=($answer.ownedNamedControlCount -gt 0)
  $answer.status='READ_ONLY_PRIVATE_UIA_COMPLETED'
}catch{
  $answer.status='UIA_NOT_AVAILABLE'
}
[IO.File]::WriteAllText($ResultFile,($answer|ConvertTo-Json -Compress),
  [Text.UTF8Encoding]::new($false))
'''


def private_uia_readonly(desktop: legacy.PrivateDesktop, owned: set[int],
                         work: Path, environment: dict) -> dict:
    ps = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not ps.is_file():
        return {"status": "POWERSHELL_UNAVAILABLE"}
    script = work / "private-profile" / "read-private-ui.ps1"
    result = work / "private-profile" / "read-private-ui.json"
    script.write_text(PRIVATE_READONLY_UIA_PS, encoding="utf-8-sig")
    pid, handle, thread = desktop.spawn(ps, work, environment, (
        "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
        "-ExecutionPolicy", "Bypass", "-File", str(script),
        "-OwnerIds", ",".join(map(str, sorted(owned))), "-ResultFile", str(result)))
    kernel = ctypes.windll.kernel32
    try:
        waited = kernel.WaitForSingleObject(handle, 16000)
        if waited != 0:
            # Only helper process handle returned by our own CreateProcessW.
            kernel.TerminateProcess(handle, 1)
            return {"status": "PRIVATE_UIA_TIMEOUT"}
        if not result.is_file():
            return {"status": "PRIVATE_UIA_NO_RESULT"}
        payload = json.loads(result.read_text(encoding="utf-8"))
        approved = {"status", "ownedWindow", "startupControlsObserved", "navigationReadOnly",
                    "navigationPerformed", "madarServiceActionAttempted", "financeActionAttempted",
                    "ownedNamedControlCount", "privateOwnerMatch"}
        return {key: value for key, value in payload.items() if key in approved}
    finally:
        kernel.CloseHandle(handle)
        kernel.CloseHandle(thread)


def cloned_ledger_head(path: Path) -> tuple:
    if not path.is_file():
        raise NativeBlocked("Cold-backup clone does not contain a private accounting ledger")
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        row = db.execute("SELECT revision,digest FROM standalone_accounting WHERE id=1").fetchone()
    if not isinstance(row, tuple) or len(row) != 2:
        raise NativeBlocked("Cold-backup clone has no valid ledger head")
    return row  # Never log revision or digest: private data.


def run() -> Path:
    evidence = baseline()  # Verifies everything BEFORE any private process launch.
    if OUTPUT.is_symlink():
        raise NativeBlocked("Output root is a symlink")
    OUTPUT.mkdir(exist_ok=True, parents=True)
    work = OUTPUT / ("qa-rc3-" + uuid.uuid4().hex[:12])
    private_acl.secure_private_directory(work)
    native_report = work / "private-profile" / "native-report.json"
    report_file = work / "native-result.json"
    before_pid = live_process_facts()
    before_windows = visible_window_facts()
    result = {"status": "BLOCKED", "candidateSha256": EXE_SHA,
              "realNonQaExeLaunched": False, "privateNonInputDesktopCreated": False,
              "offlineColdBackupFilesRehashed": evidence["backup"]["filesRehashed"],
              "installedPointerBefore": evidence["installed"]["version"],
              "installedPointerAfter": None, "noFinanceActionAttempted": True,
              "noMadarServiceActionAttempted": True,
              "noProductionActivation": True, "noInputDesktopSwitch": True,
              "originalTarazProcessCount": len(before_pid),
              "originalVisibleWindowCount": len(before_windows)}
    pid = 0
    tracked: dict[int, float] = {}
    handles = (None, None)
    ledger_path = None
    ledger_before = None
    try:
        runtime, roots = legacy.clone_offline_snapshot(work)
        ledger_path = roots["roaming"] / "standalone-accounting.sqlite3"
        ledger_before = cloned_ledger_head(ledger_path)
        env = legacy.isolated_env(runtime, roots, native_report, legacy.unused_port())
        if any(Path(env[key]).resolve() == Path(os.environ[key]).resolve()
               for key in ("APPDATA", "LOCALAPPDATA", "TEMP")):
            raise NativeBlocked("Private profile environment resolved to ambient user profile")
        with legacy.PrivateDesktop() as desktop:
            result["privateNonInputDesktopCreated"] = True
            pid, ph, th = desktop.spawn(EXE, work, env)
            handles = (ph, th)
            result["realNonQaExeLaunched"] = True
            capture_owned(pid, tracked)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    capture_owned(pid, tracked)
                    if native_report.is_file() and any(
                            s == "msedgewebview2.exe" for s in _owned_names(tracked)):
                        break
                    time.sleep(.4)
                capture_owned(pid, tracked)
                result["ownedPrivateTarazWindow"] = bool(desktop.owned_windows(set(tracked)))
                result["ownedWebView2Count"] = sum(
                    s == "msedgewebview2.exe" for s in _owned_names(tracked))
                result["privateUia"] = private_uia_readonly(desktop, set(tracked), work, env)
                if native_report.is_file():
                    raw = json.loads(native_report.read_text(encoding="utf-8"))
                    result["nativeWebViewReport"] = {
                        "loaded": raw.get("loaded") is True,
                        "accountingBridgePresent": raw.get("accountingBridge") == "function",
                        "taskBridgeNotExposed": raw.get("taskBridgeExposed") != "function"}
                else:
                    result["nativeWebViewReport"] = {"loaded": False}
                if not (result["ownedPrivateTarazWindow"] and
                        result["ownedWebView2Count"] > 0 and
                        result["nativeWebViewReport"].get("loaded") and
                        result["nativeWebViewReport"].get("accountingBridgePresent")):
                    raise NativeBlocked("Native private window/WebView2 startup not fully observed")
                result["status"] = "PASS_REAL_RC3_PRIVATE_NATIVE_STARTUP_VIEW_ONLY"
            finally:
                result["cleanup"] = stop_owned(pid, tracked)
    except Exception as error:
        result["status"] = "BLOCKED_OR_INCOMPLETE_RC3_NATIVE_GUI"
        result["errorType"] = type(error).__name__
        result["error"] = str(error)[:220]
    finally:
        if pid:
            try:
                result["cleanup"] = stop_owned(pid, tracked)
            except Exception as error:
                result["cleanup"] = {"errorType": type(error).__name__}
        for handle in handles:
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
        if ledger_path is not None and ledger_before is not None:
            try:
                result["privateLedgerUnchanged"] = cloned_ledger_head(ledger_path) == ledger_before
            except Exception:
                result["privateLedgerUnchanged"] = False
        try:
            installed_after = pins.installed_baseline(
                Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz")
            result["installedPointerAfter"] = installed_after["version"]
            result["installedBaselineUnchanged"] = installed_after == evidence["installed"]
            result["backupVerifiedAfter"] = pins.verify_backup(BACKUP)["filesRehashed"] == 181
            result["candidateExeUnchanged"] = digest(EXE) == EXE_SHA
            after_pid = live_process_facts()
            result["originalTarazPidsIntact"] = all(
                after_pid.get(p) == started for p, started in before_pid.items())
            after_windows = visible_window_facts()
            result["originalVisibleWindowsStillOwned"] = all(
                after_windows.get(hwnd) == owner for hwnd, owner in before_windows.items())
            result["originalVisibleWindowCountAfter"] = len(after_windows)
        except Exception as error:
            result["postflightErrorType"] = type(error).__name__
            result["installedBaselineUnchanged"] = False
        if not (result.get("installedBaselineUnchanged") and
                result.get("backupVerifiedAfter") and
                result.get("candidateExeUnchanged") and
                result.get("privateLedgerUnchanged") and
                result.get("originalTarazPidsIntact") and
                result.get("originalVisibleWindowsStillOwned") and
                result.get("cleanup", {}).get("ownedProcessesLeftAlive") == 0):
            result["status"] = "BLOCKED_POSTFLIGHT_PRIVATE_OR_USER_BASELINE"
        report_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    return report_file


def _owned_names(tracked: dict[int, float]) -> list[str]:
    import psutil
    names = []
    for pid, created in tracked.items():
        try:
            item = psutil.Process(pid)
            if item.create_time() == created:
                names.append(item.name().casefold())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return names


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    mutually = cli.add_mutually_exclusive_group(required=True)
    mutually.add_argument("--static-only", action="store_true")
    mutually.add_argument("--run-private-native", action="store_true")
    options = cli.parse_args()
    try:
        if options.static_only:
            pre = baseline()
            print(json.dumps({"status": "STATIC_ONLY_NATIVE_NOT_LAUNCHED",
                              "exeSha256": EXE_SHA,
                              "installedVersion": pre["installed"]["version"],
                              "coldBackupFilesVerified": pre["backup"]["filesRehashed"]}))
        else:
            report = run()
            data = json.loads(report.read_text(encoding="utf-8"))
            print(json.dumps({"status": data["status"], "report": str(report),
                              "realNonQaExeLaunched": data["realNonQaExeLaunched"],
                              "nativeWebViewLoaded": data.get("nativeWebViewReport", {}).get("loaded", False),
                              "noUserWindowInterference": data.get("originalVisibleWindowsStillOwned", False),
                              "ownedProcessesLeftAlive": data.get("cleanup", {}).get("ownedProcessesLeftAlive")},
                             ensure_ascii=False))
            sys.exit(0 if data["status"] == "PASS_REAL_RC3_PRIVATE_NATIVE_STARTUP_VIEW_ONLY" else 1)
    except Exception as error:
        print(json.dumps({"status": "BLOCKED", "errorType": type(error).__name__,
                          "error": str(error)[:240]}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
