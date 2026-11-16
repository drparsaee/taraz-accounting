"""One bounded Win32 action for a verified historic isolated Taraz QA alert.

Only acknowledges the exact informational 'financial operation still running'
alert. It does not approve or bypass the financial native/JS close gate.
After acknowledgement, the existing normal close tool may be tried once.
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
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from scripts.qa_taraz_owned_private_graceful_close_20261115 import run as request_normal_close

PARENT = 37456
CHILD = 26844
EXE = Path(
    'D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.6-aaas/'
    'build-5e5253cd7449/binary/Taraz.exe'
)
SHA = 'd4692dfaf66b4de52e778bea59099ad2ea661f4e47493877a4ca9d4b6c322305'
ROOT = Path(
    'D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.6-aaas/'
    'fresh-windows-frozen-qa-20261115/qa-3443357975f2/qa/qa-runtime'
)
ALERT = 'عملیات مالی هنوز در حال انجام است. پس از پایان عملیات دوباره برای خروج اقدام کنید.'


def identity():
    if os.name != 'nt':
        raise RuntimeError('Windows-only private QA procedure')
    p, c = psutil.Process(PARENT), psutil.Process(CHILD)
    if (c.ppid() != PARENT or Path(p.exe()).resolve() != EXE.resolve() or
            Path(c.exe()).resolve() != EXE.resolve() or
            hashlib.sha256(EXE.read_bytes()).hexdigest() != SHA):
        raise PermissionError('Historical frozen QA PID/hash mismatch')
    for process in (p, c):
        env = process.environ()
        for variable, suffix in (
            ('APPDATA', 'roaming'), ('LOCALAPPDATA', 'localappdata'),
            ('TARAZ_QA_DATA_DIR', 'roaming/Taraz'),
        ):
            value = env.get(variable)
            if not value or Path(value).resolve() != (ROOT / suffix).resolve():
                raise PermissionError('Historical QA environment not pinned')
        if env.get('TARAZ_QA_MODE') != '1':
            raise PermissionError('Historical process not QA-only')
    return p, c


def inspect(*, acknowledge=False):
    identity()
    user32 = ctypes.WinDLL('user32',use_last_error=True)
    DESKTOP = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.LPWSTR,wintypes.LPARAM)
    WINDOWS = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.EnumDesktopsW.argtypes = [wintypes.HANDLE,DESKTOP,wintypes.LPARAM]
    user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE,WINDOWS,wintypes.LPARAM]
    user32.EnumChildWindows.argtypes = [wintypes.HWND,WINDOWS,wintypes.LPARAM]
    user32.OpenDesktopW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    user32.OpenDesktopW.restype = wintypes.HANDLE
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
    user32.SetThreadDesktop.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]

    def describe(hwnd):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        name = ctypes.create_unicode_buffer(512)
        cls = ctypes.create_unicode_buffer(150)
        user32.GetClassNameW(hwnd,cls,len(cls))
        user32.GetWindowTextW(hwnd,name,len(name))
        return {'pid':owner.value,'hwnd':int(hwnd),'name':name.value,
                'class':cls.value,'visible':bool(user32.IsWindowVisible(hwnd))}

    matched = []
    @DESKTOP
    def desktop(name, unused):
        if not name.startswith('TarazNativeQA_'):
            return True
        handle = user32.OpenDesktopW(name,0,False,0xC1)
        if not handle:
            return True
        try:
            @WINDOWS
            def top(hwnd, ignored):
                root = describe(hwnd)
                if (root['pid'] != CHILD or root['class'] != '#32770'
                        or not root['visible']):
                    return True
                controls = []
                @WINDOWS
                def child(c, ignored):
                    row=describe(c)
                    if row['pid']==CHILD and row['visible']:
                        controls.append(row)
                    return True
                user32.EnumChildWindows(hwnd,child,0)
                texts = [c for c in controls if c['class']=='Static' and c['name']==ALERT]
                buttons = [c for c in controls if c['class']=='Button' and c['name']=='OK']
                if len(texts)==1 and len(buttons)==1:
                    matched.append({'desktop':name,'dialog':root,'button':buttons[0],
                                    'messageMatched':True})
                return True
            user32.EnumDesktopWindows(handle,top,0)
        finally:
            user32.CloseDesktop(handle)
        return True
    if not user32.EnumDesktopsW(user32.GetProcessWindowStation(),desktop,0):
        raise RuntimeError('Could not inspect owner private desktops')
    if len(matched) != 1:
        return {'status':'BLOCKED','exactBusyAlertCount':len(matched),
                'acknowledged':False,'normalCloseRequested':False}
    result={'status':'PRIVATE_BUSY_ALERT_VERIFIED','exactBusyAlertCount':1,
            'acknowledged':False,'normalCloseRequested':False}
    if acknowledge:
        entry = matched[0]
        hdesk = user32.OpenDesktopW(entry['desktop'],0,False,0xC1)
        if not hdesk:
            raise RuntimeError('Exact private desktop unavailable for info alert')
        evidence={'posted':False,'threadBound':False}
        def dispatch():
            if not user32.SetThreadDesktop(hdesk):
                return
            evidence['threadBound']=True
            matching=[]
            @WINDOWS
            def recheck(hwnd, _):
                child = describe(hwnd)
                if (child['pid']==CHILD and child['class']=='Button' and
                        child['name']=='OK' and child['hwnd']==entry['button']['hwnd']):
                    matching.append(hwnd)
                return True
            # EnumChildWindows still checks exact ownership of this button;
            # it must still be under the same already-verified dialog.
            user32.EnumChildWindows(wintypes.HWND(entry['dialog']['hwnd']),recheck,0)
            if len(matching)==1 and user32.IsWindow(matching[0]):
                evidence['posted']=bool(user32.PostMessageW(matching[0],0x00F5,0,0))
        worker=threading.Thread(target=dispatch,daemon=True)
        worker.start()
        worker.join(timeout=5)
        user32.CloseDesktop(hdesk)
        if worker.is_alive() or not evidence['threadBound'] or not evidence['posted']:
            raise RuntimeError('Real owned info alert cannot be acknowledged')
        result['status']='PRIVATE_INFORMATIONAL_ALERT_ACKNOWLEDGED'
        result['acknowledged']=True
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acknowledge',action='store_true')
    parser.add_argument('--then-request-normal-close',action='store_true')
    args=parser.parse_args()
    if args.then_request_normal_close and not args.acknowledge:
        raise SystemExit('No close without a verified exact alert acknowledgement')
    result=inspect(acknowledge=args.acknowledge)
    if args.then_request_normal_close and result['acknowledged']:
        result['normalClose']=request_normal_close(PARENT,EXE,SHA,close=True)
        result['normalCloseRequested']=result['normalClose'].get('closeRequested',False)
    print(json.dumps(result,ensure_ascii=True))
