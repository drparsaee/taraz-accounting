"""Private Win32 WebView2 UI -> native Taraz order bridge -> disposable SQLite.

SOURCE-HOSTED latest compiled dist, NOT the installed/frozen production EXE.
No ordinary desktop input, banking, posting, process force kill or live data.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import psutil
import sys
import time
import uuid
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v103_native_gui_20261111 as private
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acl
from scripts import build_taraz_v106_aaas_20261111 as build
from scripts.qa_taraz_native_bridge_vertical_20261112 import Identity, QAAPI
from standalone_accounting_desktop import serve_accounting_page
from taraz_order_store import TarazOrderStore
from taraz_aaas_agent import CompanyAgentMemory

OUTPUT = ROOT.parents[1] / 'MTR-NEXT-UPDATE-CANDIDATES-20261110' / 'taraz-v1.0.6-aaas' / 'order-native-qa-20261112'
JS = r'''(() => {
  window.__orderNative={status:'STARTING',phase:'INITIAL'};
  const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const until=async(fn,limit=14000)=>{
    const end=Date.now()+limit;
    while(Date.now()<end){const answer=await fn();if(answer)return answer;await pause(80);}
    throw Error('ORDER_NATIVE_TIMEOUT_'+window.__orderNative.phase);
  };
  const click=(scope,name)=>{
    const buttons=Array.from(scope.querySelectorAll('button')).filter(b=>
      b.textContent.trim()===name&&!b.disabled);
    if(buttons.length!==1)throw Error('ORDER_NATIVE_BUTTON_'+name+'_'+buttons.length);
    buttons[0].click();
  };
  const field=(scope,label)=>{
    let fields=Array.from(scope.querySelectorAll('input,textarea')).filter(el=>
      el.getAttribute('aria-label')===label);
    if(!fields.length)fields=Array.from(scope.querySelectorAll('label'))
      .filter(el=>el.textContent.trim().startsWith(label))
      .map(el=>el.querySelector('input,textarea')).filter(Boolean);
    if(fields.length!==1)throw Error('ORDER_NATIVE_FIELD_'+label+'_'+fields.length);
    return fields[0];
  };
  const fill=(scope,label,value)=>{
    const el=field(scope,label);
    const setter=Object.getOwnPropertyDescriptor(
      el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;
    setter.call(el,String(value));el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
  };
  const confirmation=async(action)=>{
    const old=window.confirm;let calls=0;
    window.confirm=()=>{calls++;return true;};
    try{action();await pause(500);}finally{window.confirm=old;}
    if(calls!==1)throw Error('ORDER_NATIVE_CONFIRM_COUNT_'+calls);
  };
  const waitRevision=async rev=>until(async()=>{
    const out=await window.madar.tarazOrderList(0,100);
    return out.orders?.[0]?.revision===rev?out.orders[0]:null;
  });
  (async()=>{
    await until(()=>document.querySelector('.sac-root')&&
      typeof window.madar?.tarazOrderCommand==='function');
    window.__orderNative.phase='NAV';
    const menu=await until(()=>{
      const button=document.querySelector('[data-accounting-action="more"]');
      return button&&!button.disabled?button:null;
    });
    menu.click();
    const nav=await until(()=>document.querySelector('.taraz-vt-drawer [data-accounting-tab="orders"]'));
    nav.click();
    const scope=await until(()=>document.querySelector('.taraz-orders'));
    window.__orderNative.phase='FORM';
    fill(scope,'نام مشتری','مشتری بومی آزمایشی');
    fill(scope,'شرح سفارش','پاسپورت بومی QA');
    fill(scope,'تعداد سفارش','100');
    fill(scope,'تعداد برنامه‌ریزی تولید','120');
    fill(scope,'قیمت واحد (اختیاری، ریال)','25000');
    click(scope.querySelector('.taraz-orders-editor-head'),'حرفه‌ای');
    await until(()=>scope.querySelector('.taraz-orders-advanced'));
    click(scope.querySelector('.taraz-orders-advanced'),'افزودن مرحله');
    await until(()=>scope.querySelector('[aria-label="هزینه مرحله 1"]'));
    fill(scope,'هزینه مرحله 1','200000');
    click(scope.querySelector('.taraz-orders-editor-head'),'ساده');
    if(field(scope,'هزینه مرحله 1').value!=='200000')
      throw Error('ORDER_NATIVE_MODE_LOST_STAGE');
    window.__orderNative.phase='CREATE';
    click(scope,'ذخیره سفارش');
    const original=await waitRevision(1);
    if(original.quantity!==100||original.productionQuantity!==120||
      original.actualCostTotal!==null||original.financialEventCreated!==false)
      throw Error('ORDER_NATIVE_CREATE_INVALID');
    window.__orderNative.phase='COST';
    await until(()=>scope.querySelector('[aria-label="هزینه واقعی مرحله 1"]'));
    fill(scope,'هزینه واقعی مرحله 1','180000');
    fill(scope,'تاریخ هزینه مرحله 1','2026-11-12');
    click(scope,'ثبت هزینه واقعی');
    await waitRevision(2);
    window.__orderNative.phase='APPROVE_COST';
    await until(()=>Array.from(scope.querySelectorAll('button')).some(button=>
      button.textContent.trim()==='تأیید مالی هزینه'));
    await confirmation(()=>click(scope,'تأیید مالی هزینه'));
    const approved=await waitRevision(3);
    if(approved.actualCostTotal!==180000)throw Error('ORDER_NATIVE_COST_APPROVAL_FAILED');
    window.__orderNative.phase='PAYMENT';
    await until(()=>scope.querySelector('[aria-label="مبلغ پرداخت سفارش"]')&&
      !scope.querySelector('[aria-label="مبلغ پرداخت سفارش"]').disabled);
    fill(scope,'مبلغ پرداخت سفارش','500000');
    fill(scope,'روش پرداخت سفارش','bank-transfer');
    // Backend revision can be visible before React clears its busy/dirty
    // state. Require the actual action control to be enabled; never force it.
    await until(()=>Array.from(scope.querySelectorAll('button')).some(button=>
      button.textContent.trim()==='ثبت در پرونده سفارش (نه بانک)'&&
      !button.disabled));
    click(scope,'ثبت در پرونده سفارش (نه بانک)');
    const pending=await waitRevision(4);
    if(pending.paymentBalance!==2500000||pending.payments?.[0]?.status!=='recorded')
      throw Error('ORDER_NATIVE_RECORDED_PAYMENT_WRONGLY_SETTLED');
    const payment=pending.payments[0];
    window.__orderNative.phase='SETTLEMENT';
    await until(()=>scope.querySelector('[aria-label="مرجع تسویه '+payment.id+'"]'));
    fill(scope,'مرجع تسویه '+payment.id,'QA-NATIVE-REF-01');
    await confirmation(()=>click(scope,'تأیید دستی تسویه'));
    const settled=await waitRevision(5);
    if(settled.paymentBalance!==2000000||settled.payments[0].status!=='settled')
      throw Error('ORDER_NATIVE_PARTIAL_SETTLEMENT_INVALID');
    window.__orderNative.phase='AGENT_REVIEW';
    await until(()=>typeof window.madar?.tarazAgentOrderReview==='function'&&
      typeof window.madar?.tarazAgentMemoryList==='function'&&
      typeof window.madar?.tarazAgentMemoryCommand==='function'&&
      typeof window.madar?.tarazOrderFinanceDraft==='function');
    await until(()=>Array.from(scope.querySelectorAll('button')).some(button=>
      button.textContent.trim()==='بررسی سفارش با ابزارهای محلی'&&!button.disabled));
    click(scope,'بررسی سفارش با ابزارهای محلی');
    await until(()=>scope.querySelector('[aria-label="متن حافظه پیشنهادی سفارش"]'));
    fill(scope,'متن حافظه پیشنهادی سفارش','QA: تأیید هزینه واقعی با رسید انجام شود');
    window.__orderNative.phase='AGENT_PROPOSE';
    click(scope,'ثبت پیشنهاد، بدون تأیید خودکار');
    const proposed=await until(async()=>{
      const data=await window.madar.tarazAgentMemoryList(original.id);
      return data.revision===1&&data.entries?.[0]?.status==='proposed'?data:null;
    });
    window.__orderNative.phase='AGENT_HUMAN_APPROVE';
    await until(()=>Array.from(scope.querySelectorAll('button')).some(button=>
      button.textContent.trim()==='تأیید یادداشت'&&!button.disabled));
    await confirmation(()=>click(scope,'تأیید یادداشت'));
    const accepted=await until(async()=>{
      const data=await window.madar.tarazAgentMemoryList(original.id);
      return data.revision===2&&data.entries?.[0]?.status==='accepted'?data:null;
    });
    if(accepted.entries[0].reviewed_by!=='qa-webview2-operator'||
      accepted.entries[0].source_revision!==5||
      accepted.entries[0].id!==proposed.entries[0].id)
      throw Error('ORDER_NATIVE_AGENT_PROVENANCE_INVALID');
    window.__orderNative={status:'PASS_ORDER_NATIVE',phase:'DONE',
      orderId:original.id,finalRevision:5,approvedCost:180000,
      partiallySettled:500000,noFinancialEvent:true,
      nativeAgentReview:true,acceptedMemoryRevision:2};
  })().catch(e=>{window.__orderNative={status:'FAIL',
    phase:window.__orderNative.phase,error:String(e?.message||e).slice(0,110)};});
  return true;
})()'''


class OrderQAAPI(QAAPI):
    def standaloneAccountingCommand(self, request):
        raise PermissionError('Financial ledger mutations forbidden in order QA')

    def tarazOrderCommand(self, request):
        if type(request) is not dict or request.get('action') not in {
                'create', 'cost.record', 'cost.approve', 'payment.record', 'payment.settle'}:
            raise PermissionError('Non-allowlisted order QA action')
        return super().tarazOrderCommand(request)


def child(work: Path):
    if not (work / 'qa-owned-marker.json').is_file() or not Path(
            os.environ['APPDATA']).resolve().is_relative_to(work):
        raise RuntimeError('Private order QA identity failed')
    web=ROOT/'dist'
    api=OrderQAAPI(work/'private-book')
    server=serve_accounting_page(web)
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    import webview
    window=webview.create_window('تراز QA سفارش خصوصی',
        f'http://127.0.0.1:{server.server_port}/accounting.html',
        width=1530,height=1030,js_api=api)
    api._native_window=window
    result={'status':'NOT_RUN'}
    def live():
        nonlocal result
        try:
            for _ in range(190):
                time.sleep(.2)
                try:
                    ready=window.evaluate_js(
                        "Boolean(document.querySelector('.sac-root') && "
                        "typeof window.madar?.tarazOrderList==='function')")
                    if ready:break
                except Exception:pass
            else:raise RuntimeError('Native order UI startup timeout')
            window.evaluate_js(JS)
            for _ in range(220):
                time.sleep(.16)
                try:
                    raw=window.evaluate_js('JSON.stringify(window.__orderNative||{})')
                    state=json.loads(raw) if isinstance(raw,str) else raw
                    if state.get('status') in ('PASS_ORDER_NATIVE','FAIL'):
                        result=state
                        break
                except Exception:pass
            else:raise RuntimeError('Native order QA response timeout')
        except Exception as exc:
            result={'status':'FAIL','error':type(exc).__name__,'phase':'HOST'}
        finally:
            (work/'native-order-result.json').write_text(
                json.dumps(result,ensure_ascii=True,indent=2),encoding='utf-8')
            try:window.destroy()
            except Exception:pass
    try:webview.start(live,debug=False)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def parent():
    if not (ROOT/'dist'/'accounting.html').is_file():
        raise RuntimeError('Local compiled order UI missing')
    sha=build.digest_inventory(build.source_inventory())
    if not OUTPUT.exists():acl.secure_private_directory(OUTPUT)
    work=OUTPUT/('private-'+uuid.uuid4().hex[:12])
    acl.secure_private_directory(work)
    acl.secure_private_directory(work/'private-book')
    (work/'qa-owned-marker.json').write_text('{"syntheticOnly":true}',encoding='utf-8')
    runtime=work/'qa'/'qa-runtime'
    roots={}
    for key in ('roaming','localappdata','temp','userprofile','webview-profile'):
        roots[key]=runtime/key;roots[key].mkdir(parents=True,exist_ok=True)
    env=private.isolated_env(runtime,{'roaming':roots['roaming'],
        'local':roots['localappdata'],'bridge':roots['localappdata']},
        work/'qa-status.json',private.unused_port())
    env['PYTHONPATH']=str(ROOT)
    env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=(
        '--disable-background-networking --disable-sync --no-first-run '
        '--proxy-server=http://127.0.0.1:9 --proxy-bypass-list=<-loopback>')
    baseline=build.installed_baseline()
    user_processes={p.pid:p.create_time() for p in psutil.process_iter(['name'])
        if (p.info.get('name') or '').lower()=='taraz.exe'}
    with private.PrivateDesktop() as desktop:
        pid,hproc,hthread=desktop.spawn(Path(sys.executable),work,env,
            ('-B',str(Path(__file__).resolve()),'--child',str(work)))
        kernel=ctypes.windll.kernel32
        try:
            if kernel.WaitForSingleObject(hproc,130000)!=0:
                raise RuntimeError('QA native process did not exit; no force termination')
        finally:
            kernel.CloseHandle(hproc);kernel.CloseHandle(hthread)
    evidence=work/'native-order-result.json'
    result=json.loads(evidence.read_text(encoding='utf-8')) if evidence.exists() else {}
    rows=TarazOrderStore(work/'private-book').list()['orders']
    persisted=(len(rows)==1 and rows[0]['revision']==5 and
        rows[0]['costRecords'][0]['status']=='approved' and
        rows[0]['paymentBalance']==2000000 and rows[0]['financialEventCreated'] is False)
    agent_memory=CompanyAgentMemory(work/'private-book').list(rows[0]['id']) if len(rows)==1 else {}
    agent_persisted=(agent_memory.get('revision')==2 and
        len(agent_memory.get('entries',[]))==1 and
        agent_memory['entries'][0]['status']=='accepted' and
        agent_memory['entries'][0]['source_revision']==5 and
        agent_memory['entries'][0]['reviewed_by']=='qa-webview2-operator')
    unchanged=all(psutil.pid_exists(pid) and
        psutil.Process(pid).create_time()==when for pid,when in user_processes.items())
    report={'status':result.get('status'),'sourceHostedWebView2NotFrozenExe':True,
            'sourceSha256':sha,'sqliteReadback':persisted,
            'agentMemorySqliteReadback':agent_persisted,
            'installedBaselineUnchanged':baseline==build.installed_baseline(),
            'existingProcessesUnchanged':unchanged,
            'child':result,'evidence':str(work)}
    print(json.dumps(report,ensure_ascii=True))
    return 0 if (result.get('status')=='PASS_ORDER_NATIVE' and persisted and
        agent_persisted and
        report['installedBaselineUnchanged'] and unchanged) else 1


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--child':
        child(Path(sys.argv[2]))
    else:
        raise SystemExit(parent())
