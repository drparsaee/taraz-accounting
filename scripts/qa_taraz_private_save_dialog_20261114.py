"""Inspect one owned Windows Save As dialog on a private Frozen QA desktop.

No global input or real-user desktop access. Read-only unless --save is given.
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
import time
import uuid

WORK = Path(
    'D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.6-aaas/'
    'frozen-synthetic-private-uia-20261112/qa-8d2a2170c741')
EXE = Path(
    'D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.6-aaas/'
    'build-e13b4438f5d4/binary/Taraz.exe')
SHA = '300dfff312dad2c5e5cc3984fc5afb39bc381857889989d4072ab83a34b592d3'
DESKTOP = 'TarazNativeQA_7f3f729ca0dc42'
ROOT_PID = 27308


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--save',action='store_true')
    parser.add_argument('--inspect-uia',action='store_true')
    parser.add_argument('--native-controls',action='store_true')
    parser.add_argument('--private-worker',action='store_true',
                        help=argparse.SUPPRESS)
    args=parser.parse_args()
    assert sys.platform=='win32'
    owner=json.loads((WORK/'synthetic-ownership.json').read_text(encoding='utf-8'))
    assert owner=={'syntheticOnly':True,'candidate':EXE.parent.parent.name,'exeSha256':SHA}
    root=psutil.Process(ROOT_PID)
    assert Path(root.exe()).resolve()==EXE.resolve()
    assert hashlib.sha256(EXE.read_bytes()).hexdigest()==SHA
    pids={ROOT_PID}|{process.pid for process in root.children(recursive=True)}
    user32=ctypes.WinDLL('user32',use_last_error=True)
    user32.OpenDesktopW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    user32.OpenDesktopW.restype=wintypes.HANDLE
    user32.EnumDesktopWindows.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.IsWindowVisible.argtypes=[wintypes.HWND]
    user32.EnumChildWindows.argtypes=[wintypes.HWND,ctypes.c_void_p,wintypes.LPARAM]
    if args.save and not args.private_worker:
        # Windows HWND/control messages are valid only from a thread on the
        # same desktop. Spawn a fresh helper on this *existing* QA desktop,
        # rather than switching the user's desktop or using global input.
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from scripts.qa_taraz_v103_native_gui_20261111 import PrivateDesktop
        private=PrivateDesktop()
        private.name=DESKTOP
        private.handle=user32.OpenDesktopW(DESKTOP,0,False,0x1FF)
        if not private.handle:
            raise RuntimeError('Cannot open exactly the owned QA desktop')
        runtime=WORK/'private-profile'/'qa'/'qa-runtime'
        report=WORK/'private-profile'/('qa-private-save-'+uuid.uuid4().hex[:8]+'.json')
        env=dict(os.environ)
        for name,folder in [('APPDATA','roaming'),('LOCALAPPDATA','localappdata'),
                            ('TEMP','temp'),('TMP','temp'),
                            ('USERPROFILE','userprofile')]:
            source=runtime/folder
            if not source.is_dir():
                raise RuntimeError('Isolated helper environment not found')
            env[name]=str(source)
        env['TARAZ_QA_PRIVATE_SAVE_RESULT']=str(report)
        pid=process=thread=None
        try:
            pid,process,thread=private.spawn(Path(sys.executable),WORK,env,(
                '-B',str(Path(__file__).resolve()),'--save','--private-worker'))
            outcome=ctypes.windll.kernel32.WaitForSingleObject(process,30000)
            if outcome!=0 or not report.is_file():
                raise RuntimeError('Owned private Save As helper did not finish')
            evidence=json.loads(report.read_text(encoding='utf-8'))
            print(json.dumps({'status':'QA_PRIVATE_SAVE_RESULT',
                'report':str(report),'saved':evidence.get('saved'),
                'blocked':evidence.get('blocked'),
                'locationNoticeAckPosted':evidence.get('locationNoticeAckPosted'),
                'qaPathSet':evidence.get('qaPathSet'),
                'saveButtonPosted':evidence.get('saveButtonPosted'),
                'pdfPath':evidence.get('pdfPath'),
                'pdfBytes':evidence.get('pdfBytes')},ensure_ascii=True))
            return 0 if evidence.get('saved') else 1
        finally:
            if process:ctypes.windll.kernel32.CloseHandle(process)
            if thread:ctypes.windll.kernel32.CloseHandle(thread)
            user32.CloseDesktop(private.handle)
    handle=user32.OpenDesktopW(DESKTOP,0,False,0x1FF)
    if not handle:raise RuntimeError('Exact private QA desktop is unavailable')
    objects=[]
    TYPE=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    @TYPE
    def callback(hwnd,ignore):
        pid=wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value not in pids:return True
        title=ctypes.create_unicode_buffer(512)
        cls=ctypes.create_unicode_buffer(128)
        user32.GetWindowTextW(hwnd,title,512)
        user32.GetClassNameW(hwnd,cls,128)
        if cls.value!='#32770':return True
        entry={'handle':int(hwnd),'pid':pid.value,'name':title.value,'class':cls.value,
               'visible':bool(user32.IsWindowVisible(hwnd)),'children':[]}
        @TYPE
        def child(childhwnd,_):
            childpid=wintypes.DWORD()
            user32.GetWindowThreadProcessId(childhwnd,ctypes.byref(childpid))
            if childpid.value not in pids:return True
            text=ctypes.create_unicode_buffer(256)
            childcls=ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(childhwnd,text,256)
            user32.GetClassNameW(childhwnd,childcls,128)
            entry['children'].append({'hwnd':int(childhwnd),'class':childcls.value,
                                      'text':text.value,'visible':bool(user32.IsWindowVisible(childhwnd))})
            return True
        user32.EnumChildWindows(hwnd,child,0)
        objects.append(entry)
        return True
    try:
        if not user32.EnumDesktopWindows(handle,callback,0):
            raise RuntimeError('Cannot enumerate exact QA desktop')
    finally:
        user32.CloseDesktop(handle)
    if args.native_controls:
        matches=[entry for entry in objects if entry['name']=='Save As' and
                 entry['visible'] and entry['pid'] in pids]
        if len(matches)!=1:
            raise RuntimeError('Exact QA Save As is unavailable')
        user32.GetDlgCtrlID.argtypes=[wintypes.HWND]
        user32.GetDlgCtrlID.restype=ctypes.c_int
        class Rect(ctypes.Structure):
            _fields_=[('left',ctypes.c_long),('top',ctypes.c_long),
                      ('right',ctypes.c_long),('bottom',ctypes.c_long)]
        user32.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(Rect)]
        useful=[]
        for entry in matches[0]['children']:
            if entry['class'] not in ('Edit','ComboBox','Button','ComboBoxEx32'):
                continue
            item=wintypes.HWND(entry['hwnd'])
            rect=Rect()
            user32.GetWindowRect(item,ctypes.byref(rect))
            useful.append({'class':entry['class'],'label':entry['text'],
                           'visible':entry['visible'],'handle':entry['hwnd'],
                           'controlId':user32.GetDlgCtrlID(item),
                           'bounds':[rect.left,rect.top,rect.right,rect.bottom]})
        print(json.dumps({'status':'PRIVATE_SAVE_AS_NATIVE_CONTROLS',
            'dialogPid':matches[0]['pid'],'controls':useful},ensure_ascii=True))
        return 0
    if args.inspect_uia:
        matches=[d for d in objects if d['visible'] and
                 d['name']=='Save As' and d['pid'] in pids]
        if len(matches)!=1:
            raise RuntimeError('Exact QA native Save As dialog unavailable')
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from scripts.qa_taraz_v103_native_gui_20261111 import PrivateDesktop
        private=PrivateDesktop()
        private.name=DESKTOP
        private.handle=user32.OpenDesktopW(DESKTOP,0,False,0x1FF)
        if not private.handle:
            raise RuntimeError('Exact QA desktop handle unavailable')
        runtime=WORK/'private-profile'/'qa'/'qa-runtime'
        env=dict(os.environ)
        for name,folder in [('APPDATA','roaming'),('LOCALAPPDATA','localappdata'),
                            ('TEMP','temp'),('TMP','temp'),('USERPROFILE','userprofile')]:
            path=runtime/folder
            if not path.is_dir():
                raise RuntimeError('QA-only profile is missing')
            env[name]=str(path)
        report=WORK/'private-profile'/('qa-save-dialog-uia-'+uuid.uuid4().hex[:8]+'.json')
        script=Path(__file__).with_name('qa_taraz_private_save_dialog_uia_20261114.ps1')
        powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        hproc=hthread=None
        try:
            _,hproc,hthread=private.spawn(powershell,WORK,env,(
                '-NoProfile','-NonInteractive','-WindowStyle','Hidden',
                '-ExecutionPolicy','Bypass','-File',str(script),
                '-TargetWindow',str(matches[0]['handle']),'-ResultFile',str(report)))
            if ctypes.windll.kernel32.WaitForSingleObject(hproc,15000)!=0 or not report.is_file():
                raise RuntimeError('Private Save As UIAutomation inspection unavailable')
            data=json.loads(report.read_text(encoding='utf-8'))
            useful=[item for item in data['controls'] if item['type'] in
                    ('ControlType.Edit','ControlType.Button','ControlType.ComboBox')]
            print(json.dumps({'status':data['status'],'report':str(report),
                'controlCount':len(data['controls']),'inputsAndButtons':useful[:65]},
                ensure_ascii=True))
            return 0
        finally:
            if hproc:ctypes.windll.kernel32.CloseHandle(hproc)
            if hthread:ctypes.windll.kernel32.CloseHandle(hthread)
            user32.CloseDesktop(private.handle)
    evidence={'exeSha256':SHA,'privateDesktop':DESKTOP,
              'ownerPids':sorted(pids),'dialogs':objects,'saved':False}
    if args.save:
        # The only authorized output is a new file inside the QA-owned
        # synthetic workspace. No common user Downloads/desktop is used.
        folder=(WORK/'private-downloads').resolve()
        target=(folder/'QA-FROZEN-INV-1405-0001.pdf').resolve()
        if not folder.is_dir() or folder.is_symlink() or target.parent!=folder or (
                target.exists() or target.is_symlink()):
            raise PermissionError('QA-owned PDF output path is not safe/new')
        errors=[d for d in objects if d['visible'] and
                d['name']=='Location is not available']
        saves=[d for d in objects if d['visible'] and
               d['name']=='Save As']
        if len(errors)>1 or len(saves)!=1 or len(objects)!=len(errors)+1:
            raise RuntimeError('Expected one private Save As and at most one location notice')
        user32.IsWindow.argtypes=[wintypes.HWND]
        user32.PostMessageW.argtypes=[
            wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        user32.PostMessageW.restype=wintypes.BOOL
        def exact_child(dialog,name,class_name):
            candidates=[c for c in dialog['children'] if c['visible'] and
                        c['text']==name and c['class']==class_name]
            if len(candidates)!=1:
                raise RuntimeError('Ambiguous owned Save As control '+name)
            child=wintypes.HWND(candidates[0]['hwnd'])
            childpid=wintypes.DWORD()
            user32.GetWindowThreadProcessId(child,ctypes.byref(childpid))
            still_window=bool(user32.IsWindow(child))
            if childpid.value not in pids or not still_window:
                raise PermissionError(
                    f'Dialog control changed ownership: pid={childpid.value}, '
                    f'allowed={childpid.value in pids}, isWindow={still_window}')
            return child
        if errors:
            error_ok=exact_child(errors[0],'OK','Button')
            evidence['locationNoticeAckPosted']=bool(
                user32.PostMessageW(error_ok,0x00F5,0,0)) # BM_CLICK
            time.sleep(0.65)
        if errors and user32.IsWindow(wintypes.HWND(errors[0]['handle'])):
            evidence['blocked']='LOCATION_NOTICE_NOT_DISMISSED'
        else:
            save_dialog=saves[0]
            class Rect(ctypes.Structure):
                _fields_=[('left',ctypes.c_long),('top',ctypes.c_long),
                          ('right',ctypes.c_long),('bottom',ctypes.c_long)]
            user32.GetDlgCtrlID.argtypes=[wintypes.HWND]
            user32.GetDlgCtrlID.restype=ctypes.c_int
            user32.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(Rect)]
            evidence['saveAsControls']=[]
            for field in save_dialog['children']:
                if field['class'] not in ('Edit','ComboBox','Button','ComboBoxEx32'):
                    continue
                hwnd=wintypes.HWND(field['hwnd'])
                bounds=Rect()
                user32.GetWindowRect(hwnd,ctypes.byref(bounds))
                evidence['saveAsControls'].append({
                    'class':field['class'],'label':field['text'],
                    'visible':field['visible'],'id':user32.GetDlgCtrlID(hwnd),
                    'bounds':[bounds.left,bounds.top,bounds.right,bounds.bottom]})
            edits=[c for c in save_dialog['children'] if
                   c['visible'] and c['class']=='Edit']
            if len(edits)!=1:
                evidence['blocked']='SAVE_AS_FILENAME_EDIT_AMBIGUOUS'
            else:
                edit=wintypes.HWND(edits[0]['hwnd'])
                editpid=wintypes.DWORD()
                user32.GetWindowThreadProcessId(edit,ctypes.byref(editpid))
                if editpid.value not in pids or not user32.IsWindow(edit):
                    raise PermissionError('Filename edit is not QA-owned')
                user32.SendMessageTimeoutW.argtypes=[
                    wintypes.HWND,wintypes.UINT,wintypes.WPARAM,ctypes.c_void_p,
                    wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
                user32.SendMessageTimeoutW.restype=ctypes.c_void_p
                result=ctypes.c_size_t()
                filename=ctypes.create_unicode_buffer(str(target))
                sent=user32.SendMessageTimeoutW(edit,0x000C,0,
                    ctypes.cast(filename,ctypes.c_void_p),2,2000,ctypes.byref(result))
                readback=ctypes.create_unicode_buffer(1024)
                # GetWindowText does not read another process's Edit control.
                # WM_GETTEXT is Windows' supported marshalled control message.
                read_result=ctypes.c_size_t()
                read_message=user32.SendMessageTimeoutW(edit,0x000D,len(readback),
                    ctypes.cast(readback,ctypes.c_void_p),2,2000,
                    ctypes.byref(read_result))
                evidence['qaSetMessageDelivered']=bool(sent)
                evidence['qaSetMessageResult']=int(result.value)
                evidence['qaGetMessageDelivered']=bool(read_message)
                evidence['qaGetLength']=int(read_result.value)
                evidence['qaEditReadback']=readback.value
                evidence['qaPathSet']=(bool(sent) and bool(read_message) and
                                       readback.value==str(target))
                evidence['qaFilenameReadbackMatched']=(readback.value==str(target))
                if evidence['qaPathSet']:
                    save_button=exact_child(save_dialog,'&Save','Button')
                    evidence['saveButtonPosted']=bool(
                        user32.PostMessageW(save_button,0x00F5,0,0))
                    for _ in range(25):
                        if target.is_file():
                            break
                        time.sleep(.2)
                    evidence['saved']=target.is_file()
                    if evidence['saved']:
                        evidence['pdfPath']=str(target)
                        evidence['pdfBytes']=target.stat().st_size
                else:
                    evidence['blocked']='QA_FILENAME_VALUE_NOT_ACCEPTED'
    (WORK/'private-profile'/'qa-save-dialog-inspection.json').write_text(
        json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.private_worker:
        private_result=Path(os.environ['TARAZ_QA_PRIVATE_SAVE_RESULT']).resolve()
        if private_result.parent!=(WORK/'private-profile').resolve() or (
                private_result.is_symlink() or private_result.exists()):
            raise PermissionError('Private save result destination invalid')
        private_result.write_text(
            json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=True))
    return 0 if not args.save or evidence['saved'] else 1


if __name__=='__main__':
    raise SystemExit(main())
