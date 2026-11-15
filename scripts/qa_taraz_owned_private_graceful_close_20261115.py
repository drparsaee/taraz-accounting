"""Gracefully request close of exactly one SHA-pinned owned private QA EXE.

Never terminates any process and never posts mouse/keyboard input. Can locate
a private desktop by the already-owned Taraz process's GUI thread handle.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import threading
import time
import psutil


def run(pid: int, target: Path, expected_sha: str, *, close: bool = False) -> dict:
    parent = psutil.Process(pid)
    target = Path(target).resolve()
    if (Path(parent.exe()).resolve() != target or
            hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha or
            'MTR-NEXT-UPDATE-CANDIDATES' not in target.as_posix()):
        raise RuntimeError('Unrecognized process or frozen QA binary')
    owned = [parent, *parent.children(recursive=True)]
    pids = {p.pid for p in owned if Path(p.exe()).resolve() == target}
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, callback, wintypes.LPARAM]
    user32.EnumDesktopWindows.restype = wintypes.BOOL
    found = {}
    found_desktop = {}
    desktops_seen = []
    desktop_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.LPWSTR, wintypes.LPARAM)
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.EnumDesktopsW.argtypes = [wintypes.HANDLE, desktop_callback, wintypes.LPARAM]
    user32.EnumDesktopsW.restype = wintypes.BOOL
    user32.OpenDesktopW.argtypes = [wintypes.LPWSTR, wintypes.DWORD,
                                   wintypes.BOOL, wintypes.DWORD]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL

    def collect(desktop, desktop_name=None):
        @callback
        def visit(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value in pids:
                title = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title, len(title))
                if title.value.startswith('تراز | '):
                    found[int(hwnd)] = title.value
                    if desktop_name:
                        found_desktop[int(hwnd)] = desktop_name
            return True
        user32.EnumDesktopWindows(desktop, visit, 0)

    @desktop_callback
    def inspect_desktop(name, _):
        if not name.startswith('TarazNativeQA_'):
            return True
        desktops_seen.append(name)
        handle = user32.OpenDesktopW(name, 0, False, 0xC1)
        if handle:
            try:
                collect(handle, name)
            finally:
                user32.CloseDesktop(handle)
        return True

    user32.EnumDesktopsW(user32.GetProcessWindowStation(), inspect_desktop, 0)
    for proc in owned:
        if proc.pid not in pids:
            continue
        for thread in proc.threads():
            desktop = user32.GetThreadDesktop(thread.id)
            if not desktop:
                continue

            collect(desktop)
    reported = {'ownerPid': pid, 'ownedPids': sorted(pids),
                'privateDesktopsSeen': len(desktops_seen),
                'windowCount': len(found), 'foundExpectedWindow': any(
                    title.startswith('تراز | ') for title in found.values()),
                'closeRequested': False, 'gracefullyExited': False}
    if close and len(found) == 1:
        hwnd = next(iter(found))
        result = {'sent': False, 'error': 0}
        # A GUI HWND from another desktop is not valid in the caller thread.
        # Use a fresh private thread attached ONLY to this identified desktop.
        name = found_desktop.get(hwnd)
        user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
        user32.SetThreadDesktop.restype = wintypes.BOOL
        handle = user32.OpenDesktopW(name, 0, False, 0xC1) if name else None

        def dispatch():
            if not handle or not user32.SetThreadDesktop(handle):
                result['error'] = ctypes.get_last_error()
                return
            found_here = []
            @callback
            def owned(hwnd_here, _):
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd_here, ctypes.byref(owner))
                if int(hwnd_here) == hwnd and owner.value in pids:
                    found_here.append(hwnd_here)
                return True
            user32.EnumDesktopWindows(handle, owned, 0)
            if len(found_here) != 1:
                result['error'] = 1400
                return
            if user32.PostMessageW(found_here[0], 0x0010, 0, 0):
                result['sent'] = True
            else:
                result['error'] = ctypes.get_last_error()

        thread = threading.Thread(target=dispatch, daemon=True)
        thread.start()
        thread.join(timeout=8)
        if handle:
            user32.CloseDesktop(handle)
        if result['sent']:
            reported['closeRequested'] = True
            try:
                parent.wait(timeout=22)
            except psutil.TimeoutExpired:
                pass
            reported['gracefullyExited'] = not psutil.pid_exists(pid)
        else:
            reported['postError'] = result['error']
    return reported


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--pid', type=int, required=True)
    p.add_argument('--exe', type=Path, required=True)
    p.add_argument('--sha', required=True)
    p.add_argument('--close', action='store_true')
    args = p.parse_args()
    print(json.dumps(run(args.pid, args.exe, args.sha, close=args.close)))
