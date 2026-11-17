"""READ ONLY: identify an exact QA-owned Taraz process and its Win32 desktop.

Never sends an input, closes a window, or terminates any process.
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import psutil

PID = 23868  # exact remained-running PID from the failed 2026-11-12 QA report
EXPECTED_SHA = "ca290b6c250be0d2c09c92502426d0649343255a019dd1a93f2c2cb18671d308"
EXPECTED = Path(__file__).resolve().parents[3] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.6-aaas" / "build-250eead995ca" / "binary" / "Taraz.exe"

def main():
    if os.name != "nt":
        raise RuntimeError("Windows only")
    proc = psutil.Process(PID)
    exact = Path(proc.exe()).resolve() == EXPECTED.resolve()
    fingerprint = hashlib.sha256(EXPECTED.read_bytes()).hexdigest() if exact else None
    if not exact or fingerprint != EXPECTED_SHA:
        raise RuntimeError("PID or QA EXE pin mismatched; refusing inspection")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD,
                                                  ctypes.POINTER(wintypes.DWORD)]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    names = set()
    for tid in [record.id for record in proc.threads()]:
        h = user32.GetThreadDesktop(tid)
        if not h:
            continue
        actual = wintypes.DWORD()
        chars = ctypes.create_unicode_buffer(260)
        if user32.GetUserObjectInformationW(h, 2, chars, ctypes.sizeof(chars), ctypes.byref(actual)):
            names.add(chars.value)
    # A process thread may not grant GetThreadDesktop; enumerate only this
    # caller's window station, then verify the exact target PID owns a window.
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.EnumDesktopsW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumDesktopsW.restype = wintypes.BOOL
    user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumDesktopWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
    desktops = set()
    owned_window_classes = []
    owned_child_classes = []
    pid_set = {PID} | {p.pid for p in proc.children(recursive=True)}
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumChildWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    OWNED = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enumerate_window(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == PID:
            desktops.add(active_desktop[0])
        if owner.value in pid_set:
            cls = ctypes.create_unicode_buffer(130)
            user32.GetClassNameW(hwnd, cls, len(cls))
            owned_window_classes.append({"ownerIsRoot": owner.value == PID,
                                         "windowClass": cls.value,
                                         "visible": bool(user32.IsWindowVisible(hwnd))})
            CHILD = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def capture_child(child, _):
                child_owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(child, ctypes.byref(child_owner))
                if child_owner.value not in pid_set:
                    return True
                child_cls = ctypes.create_unicode_buffer(130)
                user32.GetClassNameW(child, child_cls, len(child_cls))
                owned_child_classes.append({"class": child_cls.value,
                                            "visible": bool(user32.IsWindowVisible(child))})
                return True
            callback_child = CHILD(capture_child)
            user32.EnumChildWindows(hwnd, callback_child, 0)
        return True
    window_callback = OWNED(enumerate_window)
    active_desktop = [""]
    DESKTOP_ENUMERATE = 0x40
    DT = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.LPWSTR, wintypes.LPARAM)
    def enumerate_desktop(name, _):
        if not name.startswith("TarazNativeQA_"):
            return True
        handle = user32.OpenDesktopW(name, 0, False, DESKTOP_ENUMERATE)
        if handle:
            active_desktop[0] = name
            user32.EnumDesktopWindows(handle, window_callback, 0)
            user32.CloseDesktop(handle)
        return True
    desktop_callback = DT(enumerate_desktop)
    user32.EnumDesktopsW(user32.GetProcessWindowStation(), desktop_callback, 0)
    print(json.dumps({"pid": PID, "sameQaExe": exact,
                      "verifiedExeSha": fingerprint == EXPECTED_SHA,
                      "qaDesktopNames": sorted(name for name in names if name.startswith("TarazNativeQA_")),
                      "matchingOwnedPrivateDesktops": sorted(desktops),
                      "ownedPrivateWindowClasses": owned_window_classes,
                      "ownedChildClasses": owned_child_classes[:80],
                      "otherDesktopCount": len(names) - sum(name.startswith("TarazNativeQA_") for name in names),
                      "processRunning": proc.is_running()}))

if __name__ == "__main__":
    main()
