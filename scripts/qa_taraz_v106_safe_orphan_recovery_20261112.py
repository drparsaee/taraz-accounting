"""Allowlisted dynamic recovery of a single CURRENT QA-owned private WebView.

Never kills a process. The only optional mutation accepts an independently
verified pending unsaved-change discard on a fully isolated QA desktop.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import psutil
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_orphan_private_dialog_audit_20261112 as recovery

ARTIFACTS = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.6-aaas"
ALLOWED = {
    "build-250eead995ca": "ca290b6c250be0d2c09c92502426d0649343255a019dd1a93f2c2cb18671d308",
    "build-98e815dd931c": "b7d27d1a44c6980a3121827eee9d502ea52a8c27f6d75f67ac67f86bddd09db7",
}


def private_desktop_for(pid):
    owner = psutil.Process(pid)
    allowed = {pid} | {child.pid for child in owner.children(recursive=True)}
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.EnumDesktopsW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPARAM]
    user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    matches = []
    VISITOR = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in allowed:
            title = ctypes.create_unicode_buffer(250)
            user32.GetWindowTextW(hwnd, title, len(title))
            if "تراز" in title.value:
                matches.append(active[0])
        return True
    callback = VISITOR(visit)
    active = [""]
    DESKTOP = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.LPWSTR, wintypes.LPARAM)
    def enum_desktop(name, _):
        if not re.fullmatch(r"TarazNativeQA_[0-9a-f]{14}", name or ""):
            return True
        handle = user32.OpenDesktopW(name, 0, False, 0x0040)
        if handle:
            active[0] = name
            user32.EnumDesktopWindows(handle, callback, 0)
            user32.CloseDesktop(handle)
        return True
    user32.EnumDesktopsW(user32.GetProcessWindowStation(), DESKTOP(enum_desktop), 0)
    unique = set(matches)
    if len(matches) != 1 or len(unique) != 1:
        raise RuntimeError("QA orphan has no unique owned private Taraz window")
    return next(iter(unique))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="An exact generated QA native-gui-report.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect", action="store_true")
    mode.add_argument("--discard-private", action="store_true")
    args = parser.parse_args()
    file = Path(args.report).resolve()
    if (file.name != "native-gui-report.json" or
            not file.is_file() or not file.is_relative_to(ARTIFACTS.resolve()) or
            not file.parent.name.startswith("qa-final-native-")):
        raise RuntimeError("Untrusted native QA report path")
    doc = json.loads(file.read_text(encoding="utf-8"))
    build = doc.get("build")
    pid = doc.get("qaProcessRemainedRunningPid")
    if (build not in ALLOWED or doc.get("exeSha") != ALLOWED[build] or
            type(pid) is not int or pid <= 0 or
            doc.get("noProcessForceKilled") is not True or
            doc.get("qaProcessClosedGracefully") is not False or
            doc.get("privateDesktop") is not True):
        raise RuntimeError("Report is not a known stale private QA-owned process")
    desktop = private_desktop_for(pid)
    recovery.PID = pid
    recovery.DESKTOP = desktop
    recovery.WORK = file.parent
    recovery.EXPECTED_EXE = ARTIFACTS / build / "binary" / "Taraz.exe"
    recovery.SHA = ALLOWED[build]
    sys.argv = ["safe-orphan-recovery", "--discard-private" if args.discard_private else "--inspect"]
    recovery.main()


if __name__ == "__main__":
    main()
