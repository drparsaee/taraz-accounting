"""Interactive screenshot/Win32-input fallback for verified native WebView2 QA.

Runs a single pinned non-QA 1.0.1 EXE on an isolated private COPY of the
previously validated real backup. Receives small JSON commands on stdin and
only clicks inside the exact owned QA window. It never operates production.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import psutil
import pyautogui

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.qa_taraz_v101_nonqa_native_gui_20261110 import (
    QA_OUT, NEW_EXE, BACKUP, pin_sources, copy_private_profile, isolated_env,
    stop_qa_process_tree, finance_row)
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acceptance

MAX_SECONDS = 160
user32 = ctypes.windll.user32
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]


def qa_window(pid):
    root = psutil.Process(pid)
    child_pids = {root.pid, *(p.pid for p in root.children(recursive=True))}
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, unused):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value not in child_pids or not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, len(title))
        if "تراز" in title.value:
            found.append((hwnd, owner.value))
        return True

    user32.EnumWindows(callback, 0)
    if len(found) != 1:
        raise RuntimeError(f"Expected one owned Taraz QA window, found {len(found)}")
    return found[0][0]


def owned_bounds(hwnd):
    rectangle = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
        raise RuntimeError("Cannot query QA window rectangle")
    l, t, r, b = rectangle.left, rectangle.top, rectangle.right, rectangle.bottom
    if r-l < 750 or b-t < 450:
        raise RuntimeError("QA window unexpectedly small")
    return l, t, r-l, b-t


def make_screenshot(hwnd, work, counter):
    x,y,w,h = owned_bounds(hwnd)
    # Screenshots may show private accounting values from the *cloned* ledger.
    # Store only under the ACL-restricted QA data directory.
    filename = work / "private-profile" / f"native-window-{counter:02d}.png"
    pyautogui.screenshot(region=(x, y, w, h)).save(filename)
    return {"image": str(filename), "width": w, "height": h}


def network_status(pid):
    try:
        processes = [psutil.Process(pid), *psutil.Process(pid).children(recursive=True)]
    except psutil.NoSuchProcess:
        return {"processes":0,"nonLoopbackConnections":[]}
    unexpected=[]
    for p in processes:
        try:
            for conn in p.net_connections(kind="inet"):
                if conn.raddr:
                    ip = ipaddress.ip_address(conn.raddr.ip)
                    if getattr(ip,"ipv4_mapped",None):ip=ip.ipv4_mapped
                    if not ip.is_loopback:
                        unexpected.append({"pid":p.pid,"process":p.name(),
                                           "scope":"private" if ip.is_private else "public",
                                           "state":conn.status})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {"processes":len(processes), "nonLoopbackConnections":unexpected}


def safe_field_library(library, marker):
    if not library.is_file():
        return {"present":False, "markerSaved":False}
    content=json.loads(library.read_text(encoding="utf-8"))
    found=[item for item in content.get("templates",[]) if item.get("kind")=="print"
           and item.get("title")==marker]
    return {"present":True, "markerSaved":len(found)==1,
            "markerIdDigest":acceptance.sha(library) if found else None}


def run():
    pin_sources()
    acceptance.no_active_taraz()
    local=Path(os.environ["LOCALAPPDATA"])
    initial=acceptance.installed_baseline(local)
    QA_OUT.mkdir(parents=True,exist_ok=True)
    work=QA_OUT / ("screen-"+uuid.uuid4().hex[:12])
    work.mkdir(exist_ok=False)
    report=work / "screen-test-result.json"
    observed={"status":"IN_PROGRESS","realDataWritten":False,
              "productionPointerChanged":False,"events":[],"uncontrolledNetworkObserved":False}
    process=None
    try:
        runtime, paths=copy_private_profile(work / "private-profile")
        finance=paths["roaming"] / "standalone-accounting.sqlite3"
        old_revision=finance_row(finance)
        ui_report=work / "private-profile" / "qa-webview-native-report.json"
        env=isolated_env(runtime,paths,ui_report,0)
        # Browser-only QA guard: request all Chromium HTTP(S) traffic through
        # an unserved local proxy while allowing the native local UI loopback.
        # This is defense in depth, NOT proof of blocked OS-level egress.
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            "--disable-background-networking --disable-sync "
            "--disable-component-update --no-first-run "
            "--proxy-server=http://127.0.0.1:9 "
            "--proxy-bypass-list=<-loopback>")
        log=work / "private-profile" / "qa-stderr.log"
        with log.open("xb") as output:
            process=subprocess.Popen([str(NEW_EXE)],cwd=str(work),env=env,
                                     stdout=output,stderr=subprocess.STDOUT)
        started=time.monotonic()
        while time.monotonic()-started<25 and not ui_report.exists() and process.poll() is None:
            time.sleep(.25)
        if not ui_report.exists():
            raise RuntimeError("Native app did not report WebView2 ready")
        outcome=json.loads(ui_report.read_text(encoding="utf-8"))
        if outcome.get("loaded") is not True or outcome.get("accountingBridge")!="function":
            raise RuntimeError("Native WebView2 diagnostics failed")
        hwnd=qa_window(process.pid)
        user32.ShowWindow(hwnd,9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(.6)
        counter=0
        marker="QA-V101-SCREEN-"+uuid.uuid4().hex[:10]
        window=make_screenshot(hwnd,work,counter)
        print(json.dumps({"ready":True,"marker":marker,"qaPid":process.pid,
                          "screen":window,"network":network_status(process.pid)},ensure_ascii=False),flush=True)
        deadline=time.monotonic()+MAX_SECONDS
        while time.monotonic()<deadline:
            raw=sys.stdin.readline()
            if not raw: break
            request=json.loads(raw)
            action=request.get("action")
            if action=="exit": break
            if not user32.IsWindow(hwnd) or process.poll() is not None:
                raise RuntimeError("QA window/process disappeared")
            x,y,w,h=owned_bounds(hwnd)
            if action=="click":
                xx=int(request["x"]); yy=int(request["y"])
                if not(0<=xx<w and 0<=yy<h):
                    raise RuntimeError("Refused click outside QA window")
                user32.SetForegroundWindow(hwnd)
                pyautogui.click(x+xx,y+yy)
                time.sleep(.3)
            elif action=="write":
                value=request.get("text")
                if value!=marker:
                    raise RuntimeError("Refused non-unique QA marker input")
                user32.SetForegroundWindow(hwnd)
                pyautogui.write(value,interval=.02)
            elif action=="scroll":
                xx=int(request.get("x",w//2)); yy=int(request.get("y",h//2))
                steps=int(request.get("steps",0))
                if not (50<=xx<w-50 and 70<=yy<h-45 and -5<=steps<=5 and steps!=0):
                    raise RuntimeError("Refused scroll outside bounded QA content")
                user32.SetForegroundWindow(hwnd)
                pyautogui.moveTo(x+xx,y+yy,duration=.1)
                pyautogui.scroll(steps)
                time.sleep(.45)
            elif action=="press":
                key=request.get("key")
                if key not in ("esc","tab","enter","f5","ctrl+a","ctrl+r","pgup","pgdn"):
                    raise RuntimeError("Unsupported input key")
                if "+" in key:pyautogui.hotkey(*key.split("+"))
                else:pyautogui.press(key)
            elif action not in ("capture","inspect"):
                raise RuntimeError("Unknown action")
            counter+=1
            safety=network_status(process.pid)
            if safety["nonLoopbackConnections"]:
                observed["uncontrolledNetworkObserved"]=True
            inspect={"financeUnchanged":finance_row(finance)==old_revision,
                     "library":safe_field_library(paths["roaming"] / "invoice-templates.json",marker),
                     "network":safety}
            if action!="inspect":inspect["screen"]=make_screenshot(hwnd,work,counter)
            observed["events"].append({"action":action,"financeUnchanged":inspect["financeUnchanged"],
                                       "markerSaved":inspect["library"]["markerSaved"]})
            print(json.dumps(inspect,ensure_ascii=False),flush=True)
        observed["status"]="SCREEN_QA_ENDED"
    except Exception as exc:
        observed.update({"status":"SCREEN_QA_FAILED","errorType":type(exc).__name__,
                         "error":str(exc)})
        print(json.dumps({"error":str(exc)},ensure_ascii=False),flush=True)
    finally:
        if process is not None:
            try:stop_qa_process_tree(process.pid)
            except Exception as exc:observed["cleanupError"]=str(exc)
        if "finance" in locals():
            observed["financeCloneUnchanged"]=finance_row(finance)==old_revision
        acceptance.independently_verify_backup(BACKUP)
        observed["productionPointerChanged"]=acceptance.installed_baseline(local)!=initial
        report.write_text(json.dumps(observed,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"report":str(report),"status":observed["status"],
                          "financeCloneUnchanged":observed.get("financeCloneUnchanged"),
                          "productionPointerChanged":observed["productionPointerChanged"]},ensure_ascii=False),flush=True)


if __name__=="__main__":run()
