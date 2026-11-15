"""Second REAL Frozen EXE launch using the SAME isolated Windows-bound book.

Only an earlier verified private fresh-start QA workspace is accepted. This
does not recreate the company, clear its ledger, touch production, or issue a
financial document. First-run evidence is retained under renamed QA fixtures.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import psutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_fresh_windows_frozen_20261115 as first
from scripts import qa_taraz_v103_native_gui_20261111 as native
from scripts import qa_taraz_ai_frozen_real_auth_20261114 as frozen
from taraz_fresh_windows_workspace import inspect_fresh_workspace

RESTART_UI = r'''(() => {
  window.__nativeQa={status:'STARTING',phase:'RESTART_READ'};
  const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const until=async(fn,max=15000)=>{
    const deadline=Date.now()+max;
    while(Date.now()<deadline){const value=await fn();if(value)return value;await pause(100);}
    throw Error('FROZEN_RESTART_TIMEOUT');
  };
  (async()=>{
    await until(()=>typeof window.madar?.standaloneAccountingRead==='function');
    const account=await window.madar.standaloneAccountingRead();
    const invoices=Object.values(account.view.invoices||{});
    const proformas=Object.values(account.view.proformas||{});
    if(account.revision!==3||invoices.length!==1||proformas.length!==1||
       invoices[0].status!=='draft'||invoices[0].total!==13500||
       invoices[0].partyId!=='QA-WEBVIEW2-NATIVE-01'||
       proformas[0].status!=='draft'||proformas[0].total!==5000||
       account.view.journals.length!==0)
      throw Error('RESTART_ACCOUNTING_READBACK_MISMATCH');
    window.__nativeQa.phase='RESTART_ORDER';
    const orders=await window.madar.tarazOrderList(0,50);
    if(orders?.orders?.length!==1||orders.orders[0].status!=='draft'||
       orders.orders[0].quantity!==10||orders.orders[0].productionQuantity!==12||
       orders.orders[0].financialEventCreated!==false)
      throw Error('RESTART_ORDER_READBACK_MISMATCH');
    window.__nativeQa.phase='RESTART_CHAT_DPAPI';
    const list=await window.madar.tarazAiChatList('');
    if(list?.conversations?.length!==1)throw Error('RESTART_CHAT_LIST_MISMATCH');
    const chat=await window.madar.tarazAiChatRead(list.conversations[0].id);
    if(chat?.messages?.length!==2||!chat.messages.every(
       msg=>typeof msg.content==='string'&&msg.content.length>0))
      throw Error('RESTART_DPAPI_CHAT_UNREADABLE');
    window.__nativeQa.phase='RESTART_PROVIDER';
    const provider=await window.madar.tarazAiProviderStatus();
    if(provider?.modelRan!==false||provider?.enabledForActions!==false)
      throw Error('RESTART_AI_PROVIDER_POLICY_CHANGED');
    window.__nativeQa.phase='REOPEN_INVOICE_UI';
    const invoiceTab=await until(()=>document.querySelector(
      '.taraz-vt-primary [data-accounting-tab="invoice"]:not(:disabled)'));
    invoiceTab.click();
    // Reopen the persisted invoice as a read-only detail view. Opening its
    // editor marks the draft dirty, requiring an explicit discard dialog at
    // native shutdown; QA must not bypass that genuine financial guard.
    const detail=await until(()=>{
      const candidates=[...document.querySelectorAll('.sac-actions button')].filter(
        btn=>btn.textContent.trim()==='مشاهده جزئیات'&&!btn.disabled);
      return candidates.length===1?candidates[0]:null;
    });
    detail.click();
    const reopened=await until(()=>document.querySelector(
      'section.sac-document-detail[aria-label="مشاهده فاکتور"]'));
    if(!reopened||document.querySelector('.sac-invoice-editor')||
       !document.querySelector('.taraz-vt-primary [data-accounting-tab="invoice"][aria-current="page"]'))
      throw Error('RESTART_INVOICE_UI_NOT_OPENED');
    window.__nativeQa={status:'PASS_WEBVIEW2_REAL_BRIDGE_DRAFT',phase:'DONE',
      revision:account.revision,invoiceCount:1,invoiceDraft:true,
      proformaCount:1,proformaDraft:true,journalCount:0,
      orderCount:1,orderDraft:true,orderFinancialEventCreated:false,
      orderUiVisible:true,aiUiVisible:true,aiHistoryCount:2,
      providerMode:provider.mode,providerAvailability:provider.availability,
      aiModelRan:provider.modelRan};
  })().catch(_=>{window.__nativeQa={status:'FAIL',
    phase:window.__nativeQa?.phase||'RESTART_UNKNOWN'};});
  return true;
})()'''

def _safe_private_work(work: Path):
    approved = first.OUTPUT.resolve(strict=True)
    work = work.resolve(strict=True)
    if (work.parent != approved or not work.name.startswith('qa-') or
            any(part.is_symlink() for part in (work, *work.parents))):
        raise PermissionError('Restart requires exactly one verified private QA worktree')
    result = json.loads((work / 'fresh-windows-frozen-result.json').read_text(encoding='utf-8'))
    if (result.get('status') != 'PASS_FROZEN_REAL_REACT_INVOICE_PROFORMA_PDF' or
            result.get('gracefulExit') is not True or
            result.get('closeGuardBackupVerified') is not True or
            result.get('realUiPassed') is not True):
        raise PermissionError('Earlier real frozen QA acceptance missing')
    return work, result


def run(work: Path, exe: Path, sha: str):
    if os.name != 'nt' or not exe.is_file() or first._sha(exe) != sha:
        raise RuntimeError('Exact Windows frozen candidate SHA mismatch')
    work, previous = _safe_private_work(work)
    if previous.get('exeSha256') != sha:
        raise RuntimeError('Restart candidate is not the first-run executable')
    runtime = work / 'qa' / 'qa-runtime'
    fresh = runtime / 'roaming' / 'Taraz'
    info = inspect_fresh_workspace(fresh)
    if info['ledgerRevision'] != 3 or not info['windowsPrincipalBound']:
        raise RuntimeError('Restart book is not verified original fresh book')
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').casefold() != 'taraz.exe':
            continue
        environment = process.environ()
        candidate = Path(process.exe()).resolve()
        other_data = Path(environment.get('TARAZ_QA_DATA_DIR', '/not-qa')).resolve()
        historical = first.OUTPUT.parent / 'build-5e5253cd7449' / 'binary' / 'Taraz.exe'
        if (other_data == fresh.resolve() or
                candidate != historical.resolve() or
                environment.get('TARAZ_QA_MODE') != '1'):
            raise RuntimeError('Unknown or same-book Taraz process present')

    close = runtime / 'qa-close'
    first_close = runtime / 'qa-close-first-run'
    interaction = runtime / 'qa-ui.js'
    first_script = runtime / 'qa-ui-first-run.js'
    if (first_close.exists() or first_script.exists() or
            not close.is_dir() or close.is_symlink() or
            not interaction.is_file() or interaction.is_symlink() or
            not (close / 'exit-proof.json').is_file() or
            not (close / 'ui-proof.json').is_file()):
        raise PermissionError('QA restart evidence is not create-only')
    if json.loads((close / 'exit-proof.json').read_text(encoding='utf-8')).get('status') != (
            'VERIFIED_NATIVE_CLOSE_AND_BACKUP'):
        raise RuntimeError('Previous financial close guard did not complete')
    close.rename(first_close)
    interaction.rename(first_script)
    close.mkdir()
    with interaction.open('x', encoding='utf-8') as output:
        output.write(RESTART_UI)
    env = native.isolated_env(runtime, {
        'roaming': fresh, 'local': runtime / 'localappdata' / 'Taraz',
        'bridge': runtime / 'localappdata' / 'Madar-Taraz-Bridge',
    }, work / 'native-restart.json', native.unused_port())
    env.update({'TARAZ_QA_DATA_DIR':str(fresh),
                'TARAZ_QA_CLOSE_DIR':str(close),
                'TARAZ_QA_UI_SCRIPT':str(interaction),
                'TARAZ_QA_UI_SHA256':hashlib.sha256(interaction.read_bytes()).hexdigest()})
    outcome = {'status':'BLOCKED','private':True,'firstRunRetained':True,
               'sha':sha,'firstRevision':info['ledgerRevision'],'gracefulExit':False}
    with native.PrivateDesktop() as desktop:
        pid, handle, thread = desktop.spawn(exe, work, env)
        try:
            deadline = time.monotonic() + 35
            opened = False
            while time.monotonic() < deadline:
                try:
                    _, owned = frozen._owned_processes(pid, exe)
                    windows = frozen._owned_private_windows(desktop, owned)
                except frozen.FrozenAuthBlocked:
                    time.sleep(.25)
                    continue
                if any(first._name(hwnd) == 'تراز | حسابداری' for hwnd in windows):
                    opened = True
                    break
                time.sleep(.25)
            outcome['realWebviewWindowOpened'] = opened
            ready = close / 'ready.json'
            deadline = time.monotonic() + 100
            while opened and time.monotonic() < deadline and not ready.is_file():
                time.sleep(.2)
            if ready.is_file():
                proof = json.loads(ready.read_text(encoding='utf-8'))
                if (proof.get('method') == 'real-pywebview-native-close-guard' and
                        proof.get('pid') in frozen._owned_processes(pid, exe)[1]):
                    with (close / 'request.json').open('x', encoding='utf-8') as request:
                        json.dump({'version':1,'pid':proof['pid'],'nonce':proof['nonce'],
                                   'action':'native-close'},request)
        finally:
            try:
                psutil.Process(pid).wait(timeout=35)
                outcome['gracefulExit'] = True
            except (psutil.TimeoutExpired, psutil.Error):
                outcome['gracefulExit'] = False
            ctypes.windll.kernel32.CloseHandle(handle)
            ctypes.windll.kernel32.CloseHandle(thread)
    ui = close / 'ui-proof.json'
    exit_proof = close / 'exit-proof.json'
    outcome['ui'] = json.loads(ui.read_text(encoding='utf-8')) if ui.is_file() else {'status':'MISSING'}
    outcome['nativeCloseBackup'] = (json.loads(exit_proof.read_text(encoding='utf-8'))
        .get('status') == 'VERIFIED_NATIVE_CLOSE_AND_BACKUP') if exit_proof.is_file() else False
    outcome['lastRevision'] = inspect_fresh_workspace(fresh)['ledgerRevision']
    if (outcome.get('realWebviewWindowOpened') and outcome['gracefulExit'] and
            outcome['nativeCloseBackup'] and outcome['lastRevision']==3 and
            outcome['ui'].get('status')=='PASS_WEBVIEW2_REAL_BRIDGE_DRAFT' and
            outcome['ui'].get('phase')=='DONE' and
            outcome['ui'].get('aiHistoryCount')==2 and
            outcome['ui'].get('orderCount')==1 and
            outcome['ui'].get('journalCount')==0):
        outcome['status']='PASS_FROZEN_SAME_PROFILE_RESTART_DRAFT_ORDER_DPAPI_CHAT'
    with (work / 'fresh-windows-restart-evidence.json').open('x', encoding='utf-8') as output:
        json.dump(outcome, output, sort_keys=True, indent=2)
    return outcome


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--sha', required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.work,args.exe,args.sha),ensure_ascii=False))
