"""User-visible no-password fresh-start capability in a real Frozen Taraz EXE.

Strictly PRIVATE data and Win32 desktop, no production mutation or credentials.
Verifies actual empty, bound account after a graceful EXE shutdown. This is not
full financial/AI UI acceptance.
"""
from __future__ import annotations

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v103_native_gui_20261111 as native
from scripts import qa_taraz_ai_frozen_real_auth_20261114 as frozen
from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import secure_private_directory
from taraz_fresh_windows_workspace import inspect_fresh_workspace, stage_new_empty_root


BUSINESS_UI = r'''(() => {
  let stage='WAIT_INVOICE';
  const pause=ms=>new Promise(r=>setTimeout(r,ms));
  const until=async(fn,max=16000)=>{
    const deadline=Date.now()+max;
    while(Date.now()<deadline){const value=await fn();if(value)return value;await pause(100);}
    throw Error('BUSINESS_QA_TIMEOUT');
  };
  const click=(root,text)=>{
    const matches=[...root.querySelectorAll('button')].filter(
      el=>el.textContent.trim()===text&&!el.disabled);
    if(matches.length!==1)throw Error('BUSINESS_QA_BUTTON_NOT_UNIQUE');
    matches[0].click();
  };
  const fill=(root,label,value)=>{
    let field=[...root.querySelectorAll('input,textarea')].filter(
      el=>el.getAttribute('aria-label')===label);
    if(field.length===0){
      field=[...root.querySelectorAll('label')].filter(
        el=>el.textContent.trim().startsWith(label)).map(el=>{
          const forId=el.getAttribute('for');
          return forId?document.getElementById(forId):el.querySelector('input,textarea');
        }).filter(Boolean);
    }
    if(field.length!==1)throw Error('BUSINESS_QA_INPUT_NOT_UNIQUE');
    const element=field[0];
    const prototype=element.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype,'value').set.call(element,value);
    element.dispatchEvent(new Event('input',{bubbles:true}));
    element.dispatchEvent(new Event('change',{bubbles:true}));
  };
  (async()=>{
    const previous=await until(()=>window.__nativeQa?.status==='INVOICE_STAGE_COMPLETE'?
      window.__nativeQa:null,35000);
    stage='OPEN_ORDERS';
    const menu=await until(()=>document.querySelector('[data-accounting-action="more"]'));
    menu.click();
    const orderTab=await until(()=>document.querySelector(
      '.taraz-vt-drawer [data-accounting-tab="orders"]'));
    orderTab.click();
    const orders=await until(()=>document.querySelector(
      'section.taraz-orders[aria-label="مدیریت سفارش‌های تراز"]'));
    stage='FILL_ORDER';
    fill(orders,'نام مشتری','مشتری آزمایشی سفارش');
    fill(orders,'شرح سفارش','سفارش آزمایشی چاپ');
    fill(orders,'تعداد سفارش','10');
    fill(orders,'تعداد برنامه‌ریزی تولید','12');
    stage='SAVE_ORDER';
    click(orders,'ذخیره سفارش');
    stage='READ_ORDER';
    const listed=await until(async()=>{
      const result=await window.madar.tarazOrderList(0,50);
      return result?.orders?.length===1?result:null;
    });
    const order=listed.orders[0];
    if(order.status!=='draft'||order.quantity!==10||
       order.productionQuantity!==12||order.financialEventCreated!==false)
      throw Error('BUSINESS_QA_REAL_ORDER_MISMATCH');
    stage='OPEN_AI';
    // AI is a primary navigation tab in accounting_nav_search.js.
    // Changing sections closes the drawer, so do not reopen it here.
    const aiTab=await until(()=>document.querySelector(
      '.taraz-vt-primary [data-accounting-tab="ai"]:not(:disabled)'));
    aiTab.click();
    const chat=await until(()=>document.querySelector('.taraz-ai-chat'));
    stage='READ_PROVIDER';
    const provider=await window.madar.tarazAiProviderStatus();
    if(provider?.modelRan!==false||provider?.enabledForActions!==false)
      throw Error('BUSINESS_QA_PROVIDER_POLICY_UNEXPECTED');
    stage='CREATE_CHAT';
    click(chat,'گفتگوی جدید');
    stage='FILL_CHAT';
    const composer=await until(()=>chat.querySelector('textarea:not([disabled])'));
    fill(chat,'دستور فارسی شما','یک پیشنهاد فاکتور برای مشتری آزمایشی با یک کالا و قیمت منبع معتبر ارائه کن.');
    stage='SEND_CHAT';
    click(chat,'ثبت درخواست و تهیه پیشنهاد');
    stage='READ_CHAT';
    const history=await until(async()=>{
      const list=await window.madar.tarazAiChatList('');
      if(list?.conversations?.length!==1)return null;
      const found=await window.madar.tarazAiChatRead(list.conversations[0].id);
      return found?.messages?.length===2?found:null;
    });
    const after=await window.madar.standaloneAccountingRead();
    stage='VERIFY_NO_POSTING';
    if(after.view.journals.length!==0||after.revision!==previous.revision)
      throw Error('BUSINESS_QA_UNEXPECTED_FINANCIAL_POSTING');
    window.__nativeQa={...previous,status:'PASS_WEBVIEW2_REAL_BRIDGE_DRAFT',
      phase:'DONE',orderCount:listed.orders.length,orderDraft:true,
      orderUiVisible:true,orderFinancialEventCreated:false,
      aiUiVisible:!!chat.querySelector('.taraz-ai-compose'),
      aiHistoryCount:history.messages.length,
      providerMode:provider.mode,providerAvailability:provider.availability,
      aiModelRan:provider.modelRan};
  })().catch(_=>{window.__nativeQa={status:'FAIL',phase:stage,
      invoiceDraft:true,orderUiVisible:!!document.querySelector('.taraz-orders-header'),
      aiUiVisible:!!document.querySelector('.taraz-ai-chat')}});
  return true;
})()'''

OUTPUT = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.6-aaas" / "fresh-windows-frozen-qa-20261115"


def _sha(p: Path) -> str:
    with p.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def _name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def run(exe: Path, expected_sha: str, *, real_ui: bool = False):
    if os.name != "nt" or not exe.is_file() or _sha(exe) != expected_sha:
        raise RuntimeError("Pinned Windows candidate unavailable")
    # A previous failed *isolated* QA close may leave a process alive. Never
    # mistake it for a production writer, never touch it, and never share its
    # data root. Only the SHA-pinned historical QA fixture is tolerated.
    historical = (OUTPUT.parent / 'build-5e5253cd7449' / 'binary' / 'Taraz.exe').resolve()
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').casefold() != 'taraz.exe':
            continue
        environ = process.environ()
        other_root = Path(environ.get('TARAZ_QA_DATA_DIR', '/not-private')).resolve()
        if (Path(process.exe()).resolve() != historical or
                environ.get('TARAZ_QA_MODE') != '1' or
                'qa-runtime' not in [part.casefold() for part in other_root.parts] or
                not str(other_root).casefold().startswith(str(OUTPUT).casefold())):
            raise RuntimeError('Unrecognized running Taraz process, no fresh QA launch')
    if not OUTPUT.is_dir():
        secure_private_directory(OUTPUT)
    work = OUTPUT / ("qa-" + uuid.uuid4().hex[:12])
    secure_private_directory(work)
    runtime = work / "qa" / "qa-runtime"
    (runtime / "roaming").mkdir(parents=True)
    (runtime / "localappdata").mkdir()
    close_folder = runtime / 'qa-close'
    close_folder.mkdir()
    if real_ui:
        from scripts.qa_taraz_native_bridge_vertical_20261112 import JS_QA
        interaction = runtime / 'qa-ui.js'
        exact = "status:'PASS_WEBVIEW2_REAL_BRIDGE_DRAFT',phase:'DONE'"
        if JS_QA.count(exact) != 1:
            raise RuntimeError('Real invoice UI scripted acceptance contract changed')
        # The two independent IIFEs MUST have a semicolon separator. A
        # newline alone interprets the second as calling the first result.
        interaction.write_text(JS_QA.replace(exact, "status:'INVOICE_STAGE_COMPLETE',phase:'BUSINESS'")+
                               ";\n"+BUSINESS_UI, encoding='utf-8')
    fresh = runtime / "roaming" / "Taraz"
    staged = stage_new_empty_root(fresh)
    if staged["ledgerRevision"] != 0 or staged["role"] != "admin":
        raise RuntimeError("Empty Windows account did not bootstrap")
    env = native.isolated_env(runtime, {
        "roaming": fresh, "local": runtime / "localappdata" / "Taraz",
        "bridge": runtime / "localappdata" / "Madar-Taraz-Bridge",
    }, work / "native-startup.json", native.unused_port())
    env["TARAZ_QA_DATA_DIR"] = str(fresh)
    env["TARAZ_QA_CLOSE_DIR"] = str(close_folder)
    if real_ui:
        env['TARAZ_QA_UI_SCRIPT'] = str(interaction)
        env['TARAZ_QA_UI_SHA256'] = _sha(interaction)
    result = {"status": "BLOCKED", "private": True,
              "installed104Unchanged": True, "testLedgerRevision": 0,
              "noNativeLoginOrEnrollmentWindow": False,
              "realTarazWebviewWindowVisible": False,
              "gracefulExit": False, "closeGuardBackupVerified": False,
              "realUiRequested": real_ui,
              "exeSha256": expected_sha}
    with native.PrivateDesktop() as desktop:
        pid, handle, thread = desktop.spawn(exe, work, env)
        try:
            deadline = time.monotonic() + 28
            observed = set()
            while time.monotonic() < deadline:
                try:
                    _, owned = frozen._owned_processes(pid, exe)
                    windows = frozen._owned_private_windows(desktop, owned)
                except frozen.FrozenAuthBlocked:
                    time.sleep(.35)
                    continue
                observed.update(_name(h) for h in windows)
                if "تراز | حسابداری" in observed:
                    result["realTarazWebviewWindowVisible"] = True
                    break
                time.sleep(.35)
            result["noNativeLoginOrEnrollmentWindow"] = (
                not any("ورود امن" in label or "تأیید یک‌باره" in label
                        or "انتخاب شرکت" in label for label in observed))
            if result["realTarazWebviewWindowVisible"]:
                ready_path = close_folder / 'ready.json'
                deadline = time.monotonic() + (91 if real_ui else 19)
                while time.monotonic() < deadline and not ready_path.is_file():
                    time.sleep(.2)
                if ready_path.is_file():
                    ready = json.loads(ready_path.read_text(encoding='utf-8'))
                    if (ready.get('version') == 1 and
                            ready.get('method') == 'real-pywebview-native-close-guard' and
                            ready.get('pid') in frozen._owned_processes(pid, exe)[1]):
                        with (close_folder / 'request.json').open('x', encoding='utf-8') as file:
                            json.dump({'version': 1, 'pid': ready['pid'],
                                       'nonce': ready['nonce'], 'action': 'native-close'}, file)
                        result['realNativeCloseRequested'] = True
        finally:
            try:
                process = psutil.Process(pid)
                process.wait(timeout=35 if real_ui else 23)
                result['gracefulExit'] = True
            except (psutil.TimeoutExpired, psutil.Error):
                result['gracefulExit'] = False
            try:
                report = close_folder / 'exit-proof.json'
                if report.is_file():
                    proof = json.loads(report.read_text(encoding='utf-8'))
                    result['closeGuardEvidence'] = proof
                    result['closeGuardBackupVerified'] = proof.get('status') == (
                        'VERIFIED_NATIVE_CLOSE_AND_BACKUP')
            except frozen.FrozenAuthBlocked:
                pass
            ctypes.windll.kernel32.CloseHandle(handle)
            ctypes.windll.kernel32.CloseHandle(thread)
    after = inspect_fresh_workspace(fresh)
    result["revisionAfterExit"] = after["ledgerRevision"]
    if real_ui:
        proof = close_folder / 'ui-proof.json'
        result['realUiEvidence'] = (json.loads(proof.read_text(encoding='utf-8'))
                                     if proof.is_file() else {'status': 'MISSING'})
        result['realUiPassed'] = (result['realUiEvidence'].get('status') ==
            'PASS_WEBVIEW2_REAL_BRIDGE_DRAFT' and
            result['realUiEvidence'].get('nativePdfBytes', 0) > 1000 and
            result['realUiEvidence'].get('journalCount') == 0 and
            result['realUiEvidence'].get('orderCount') == 1 and
            result['realUiEvidence'].get('orderDraft') is True and
            result['realUiEvidence'].get('orderFinancialEventCreated') is False and
            result['realUiEvidence'].get('aiHistoryCount') == 2 and
            result['realUiEvidence'].get('aiModelRan') is False)
    expected_revision = 3 if real_ui else 0
    if (result["realTarazWebviewWindowVisible"] and
            result["noNativeLoginOrEnrollmentWindow"] and
            result["gracefulExit"] and result['closeGuardBackupVerified'] and
            after["ledgerRevision"] == expected_revision and
            (not real_ui or result['realUiPassed'])):
        result["status"] = ("PASS_FROZEN_REAL_REACT_INVOICE_PROFORMA_PDF"
                            if real_ui else "PASS_FROZEN_FRESH_WINDOWS_ACCOUNT_OPEN")
    (work / "fresh-windows-frozen-result.json").write_text(
        json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    return {"status": result["status"], "work": str(work), **result}


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4) or (len(sys.argv)==4 and sys.argv[3]!='--real-ui'):
        raise SystemExit("Usage: QA script <exact candidate exe> <sha256> [--real-ui]")
    print(json.dumps(run(Path(sys.argv[1]), sys.argv[2], real_ui=len(sys.argv)==4), ensure_ascii=True))
