"""Close exactly one proven QA-owned orphan via WM_CLOSE, never terminate.

Applies only to the first explicitly identified 2026-11-12 frozen CDP probe.
Does not use global input, switch desktops, change app data, or kill a process.
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import psutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import qa_taraz_v106_finalfix_native_gui_20261112 as view
from scripts.qa_taraz_v106_safe_orphan_recovery_20261112 import private_desktop_for

WORK=(ROOT.parents[1]/'MTR-NEXT-UPDATE-CANDIDATES-20261110'/
    'taraz-v1.0.6-aaas'/'frozen-aaas-cdp-private-qa-20261112'/'qa-ae8e9da53239')
PID=40276
EXE=(ROOT.parents[1]/'MTR-NEXT-UPDATE-CANDIDATES-20261110'/
     'taraz-v1.0.6-aaas'/'build-05511322d050'/'binary'/'Taraz.exe')
SHA='fd613f23883dc716277811fc6a908f18bec823bfac39a9ddb76392f59be24ee9'

def run():
    original=json.loads((WORK/'frozen-cdp-report.json').read_text(encoding='utf-8'))
    proc=psutil.Process(PID)
    if (original.get('status')!='BLOCKED' or original.get('noForcedTermination') is not True
        or original.get('mode')!='REAL_FROZEN_EXE_CDP'
        or proc.cwd().casefold()!=str(WORK).casefold()
        or Path(proc.exe()).resolve()!=EXE.resolve()
        or hashlib.sha256(EXE.read_bytes()).hexdigest()!=SHA):
        raise RuntimeError('Orphan QA ownership could not be proved')
    name=private_desktop_for(PID)
    if not name.startswith('TarazNativeQA_'):
        raise RuntimeError('Private desktop identity unavailable')
    user32=ctypes.WinDLL('user32',use_last_error=True)
    user32.OpenDesktopW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,
                                  wintypes.BOOL,wintypes.DWORD]
    user32.OpenDesktopW.restype=wintypes.HANDLE
    handle=user32.OpenDesktopW(name,0,False,0x0001|0x0040)
    if not handle:
        raise RuntimeError('Exact QA desktop could not be opened')
    ledger=(WORK/'private-profile'/'qa'/'qa-runtime'/
            'roaming'/'Taraz'/'standalone-accounting.sqlite3')
    before=hashlib.sha256(ledger.read_bytes()).hexdigest()
    result={'qaPid':PID,'privateDesktopMatched':True,'forcedTermination':False,
            'qaPathVerified':True,'windowsMatched':0,'gracefulClose':False}
    try:
        class AttachedDesktop:
            pass
        desktop=AttachedDesktop()
        desktop.handle=handle
        pids={PID}|{child.pid for child in proc.children(recursive=True)}
        windows=view.owned_window_handles(desktop,pids)
        result['windowsMatched']=len(windows)
        if len(windows)!=1:
            raise RuntimeError('QA-owned window count not exactly one')
        result['wmClosePosted']=bool(user32.PostMessageW(windows[0],0x0010,0,0))
        if not result['wmClosePosted']:
            raise RuntimeError('Win32 refused exact owned-window close request')
        try:
            proc.wait(timeout=15)
            result['gracefulClose']=True
        except psutil.TimeoutExpired:
            result['remainingQaPid']=PID
    finally:
        user32.CloseDesktop(handle)
        result['clonedLedgerUnchanged']=hashlib.sha256(ledger.read_bytes()).hexdigest()==before
        result['installedBaselineIntact']=view.builder.installed_baseline()['version']=='1.0.4'
        result['status']='GRACEFUL_QA_RECOVERY' if (
            result['gracefulClose'] and result['clonedLedgerUnchanged'] and
            result['installedBaselineIntact']) else 'BLOCKED_RECOVERY'
        (WORK/'qa-recovery-result.json').write_text(
            json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    if sys.argv[1:]!=['--close-owned-private']:
        raise SystemExit('Explicit --close-owned-private required')
    report=run()
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(0 if report['status']=='GRACEFUL_QA_RECOVERY' else 1)
