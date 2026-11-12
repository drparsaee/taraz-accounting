"""Isolated REAL pywebview (WebView2) -> TarazAPI -> SQLite invoice vertical.

This is a SOURCE-HOSTED native WebView test, not the frozen PyInstaller EXE.
No installed data, inherited user profile, physical printer, finance issue,
desktop switching or global keyboard/mouse interaction is permitted.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import psutil
import subprocess
import sys
import time
import uuid
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v103_native_gui_20261111 as private
from standalone_accounting_desktop import AccountingDesktopAPI, serve_accounting_page
from taraz_desktop import TarazAPI
from standalone_accounting import StandaloneAccountingStore, AccountingRevisionConflict
from standalone_accounting_template_store import StandaloneAccountingTemplateStore

OUTPUT = ROOT.parents[1] / 'MTR-NEXT-UPDATE-CANDIDATES-20261110' / 'taraz-v1.0.6-aaas' / 'native-source-bridge-qa-20261112'
SOURCE_JS_SHA = 'edd23084c2fba26f47f8ea4f6876f427c2576423cb5fcb4ff4617665d5f15518'
BUILD = ROOT.parents[1] / 'MTR-NEXT-UPDATE-CANDIDATES-20261110' / 'taraz-v1.0.6-aaas' / 'build-357bec1519e9'
EXE_SHA = 'f369f99947ad5c7d7c436e4e5716466d5b69e2aeb807b9fba052a26664f3d978'
QA_PARTY = 'QA-WEBVIEW2-NATIVE-01'
QA_DESCRIPTION = 'چاپ آزمایشی WebView2'

class Identity:
    user = {'username':'qa-webview2-operator','role':'admin',
            'financeView':True,'financeEdit':True,'jobTitle':'QA'}

    def require_session(self, token, required='viewer'):
        if token != 'qa-webview2-private-only':
            raise PermissionError('Invalid isolated QA identity')
        return dict(self.user)

    def accounting_accounts(self):
        return {self.user['username']: dict(self.user)}


class QAAPI(TarazAPI):
    def __init__(self, directory):
        ident = Identity()
        AccountingDesktopAPI.__init__(self, directory,
                                      authenticated_user=ident.user,
                                      identity_store=ident,
                                      identity_token='qa-webview2-private-only')
        self._requires_migration = False

    def standaloneAccountingCommand(self, request):
        command=request.get('command') if type(request) is dict else None
        if not isinstance(command,dict) or command.get('type') not in {
            'party.register','invoice.create','invoice.update',
            'proforma.create','proforma.update'}:
            raise PermissionError('QA hard stop: no posting/approval/issue')
        return super().standaloneAccountingCommand(request)


JS_QA = r'''(() => {
  window.__nativeQa={status:'STARTING',errors:[],phase:'INITIAL',noIssueAttempted:true};
  const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const until=async(fn,limit=10000)=>{
    const untilTime=Date.now()+limit;
    while(Date.now()<untilTime){
      const value=await fn();if(value)return value;await pause(80);
    }
    throw Error('NATIVE_QA_TIMEOUT_'+window.__nativeQa.phase);
  };
  const click=(root,label)=>{
    const buttons=Array.from(root.querySelectorAll('button')).filter(el=>
      el.textContent.trim()===label&&!el.disabled);
    if(buttons.length!==1)throw Error('NATIVE_QA_BUTTON_'+label+'_'+buttons.length);
    buttons[0].click();
  };
  const fill=(root,label,value)=>{
    let controls=Array.from(root.querySelectorAll('input,textarea')).filter(el=>
      el.getAttribute('aria-label')===label);
    if(!controls.length)controls=Array.from(root.querySelectorAll('label'))
      .filter(el=>el.textContent.trim().startsWith(label))
      .map(el=>el.querySelector('input,textarea')).filter(Boolean);
    if(controls.length!==1)throw Error('NATIVE_QA_FIELD_'+label+'_'+controls.length);
    const el=controls[0];
    const setter=Object.getOwnPropertyDescriptor(
      el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;
    setter.call(el,String(value));el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
  };
  (async()=>{
    await until(()=>document.querySelector('.sac-root'));
    await until(()=>typeof window.madar?.standaloneAccountingRead==='function');
    window.__nativeQa.phase='READ';
    const before=await window.madar.standaloneAccountingRead();
    if(before.revision!==0)throw Error('NATIVE_QA_EXPECTED_EMPTY_LEDGER');
    const invoiceTab=await until(()=>document.querySelector('[data-accounting-tab="invoice"]'));
    invoiceTab.click();
    const newButton=await until(()=>document.querySelector('[data-accounting-action="invoice"]'));
    newButton.click();
    const pane=await until(()=>document.querySelector('.sac-invoice-beginner-pane'));
    window.__nativeQa.phase='CUSTOMER';
    click(pane,'مشتری جدید');
    await until(()=>pane.querySelector('input[aria-label="شناسه مشتری جدید"]'));
    fill(pane,'شناسه مشتری جدید','QA-WEBVIEW2-NATIVE-01');
    fill(pane,'نام مشتری جدید','مشتری آزمایشی WebView2');
    const oldConfirm=window.confirm;
    let confirmations=0;
    window.confirm=()=>{confirmations++;return true;};
    try {click(pane,'تأیید و ثبت مشتری در دفتر');}
    finally {await pause(750);window.confirm=oldConfirm;}
    const customer=await until(()=>document.querySelector('.sac-invoice-beginner-pane')?.textContent
      .includes('مشتری آزمایشی WebView2'));
    if(!customer||confirmations!==1)throw Error('NATIVE_QA_CUSTOMER_NOT_REGISTERED');
    window.__nativeQa.phase='DRAFT';
    fill(pane,'شرح ردیف 1','چاپ آزمایشی WebView2');
    fill(pane,'تعداد ردیف 1','3');
    fill(pane,'قیمت ردیف 1','4500');
    fill(pane,'یادداشت سند','صرفاً آزمایش خصوصی');
    await pause(400);
    click(pane,'ذخیره پیش‌نویس فاکتور');
    await until(()=>document.querySelector('[aria-label="پیش‌نمایش چاپ فاکتور"]'),15000);
    window.__nativeQa.phase='SQLITE';
    const after=await window.madar.standaloneAccountingRead();
    const saved=Object.values(after.view.invoices);
    if(saved.length!==1||saved[0].status!=='draft'||saved[0].total!==13500||
      saved[0].partyId!=='QA-WEBVIEW2-NATIVE-01'||after.view.journals.length!==0)
      throw Error('NATIVE_QA_NOT_ACTUALLY_PERSISTED');
    const iframe=document.querySelector('[aria-label="پیش‌نمایش چاپ فاکتور"] iframe');
    let pdfLength=0;
    if(iframe?.src?.startsWith('blob:')){
      const blob=await (await fetch(iframe.src)).arrayBuffer();
      const bytes=new Uint8Array(blob);pdfLength=bytes.length;
      if(bytes.length<1000||String.fromCharCode(...bytes.slice(0,5))!=='%PDF-')
        throw Error('NATIVE_QA_PDF_INVALID');
    }else throw Error('NATIVE_QA_PDF_PREVIEW_MISSING');
    window.__nativeQa.phase='PRINT_NAV';
    const menu=await until(()=>document.querySelector('[data-accounting-action="more"]'));
    menu.click();
    const nav=await until(()=>document.querySelector('.taraz-vt-drawer [data-accounting-tab="invoiceDesign"]'));
    nav.click();
    window.__nativeQa.phase='PRINT_READY';
    const design=await until(()=>document.querySelector('.sac-print-designer'));
    fill(design,'نام قالب','QA WebView2 Custom');
    click(design,'افزودن ستون سفارشی');
    await until(()=>design.querySelector('input')&&design.textContent.includes('عنوان ستون سفارشی custom_1'));
    fill(design,'عنوان ستون سفارشی custom_1','واحد سفارشی');
    const combo=Array.from(design.querySelectorAll('label')).find(el=>
      el.textContent.trim().startsWith('متغیر ستون سفارشی custom_1'))?.querySelector('select');
    if(!combo)throw Error('NATIVE_QA_CUSTOM_SELECT_MISSING');
    combo.value='unit';combo.dispatchEvent(new Event('change',{bubbles:true}));
    await pause(250);
    window.__nativeQa.phase='PRINT_SAVE';
    click(document.querySelector('.sac-invoice-template-studio'),'ذخیره قالب چاپ');
    const templates=await until(async()=>{
      const data=await window.madar.standaloneAccountingTemplateList('print');
      return data.templates?.find(t=>t.title==='QA WebView2 Custom')||null;
    },12000);
    if(!templates.data.table.customColumns?.some(col=>
      col.id==='custom_1'&&col.label==='واحد سفارشی'&&col.source==='unit'))
      throw Error('NATIVE_QA_CUSTOM_TEMPLATE_INVALID');
    window.__nativeQa.phase='PROFORMA';
    const saleTab=await until(()=>document.querySelector('.taraz-vt-primary [data-accounting-tab="invoice"]'));
    saleTab.click();
    const create=await until(()=>document.querySelector('[data-accounting-action="invoice"]'));
    create.click();
    const quotePane=await until(()=>document.querySelector('.sac-invoice-beginner-pane'));
    const radio=quotePane.querySelector('input[name="taraz-beginner-kind"][value="proforma"]');
    if(!radio)throw Error('NATIVE_QA_PROFORMA_RADIO_MISSING');
    radio.click();
    await until(()=>quotePane.textContent.includes('پیش‌فاکتور در یک صفحه'));
    const party=quotePane.querySelector('select[aria-label="مشتری فاکتور"]');
    if(!party)throw Error('NATIVE_QA_EXISTING_CUSTOMER_SELECT_MISSING');
    party.value='QA-WEBVIEW2-NATIVE-01';party.dispatchEvent(new Event('change',{bubbles:true}));
    fill(quotePane,'شرح ردیف 1','پیشنهاد قیمت آزمایشی WebView2');
    fill(quotePane,'تعداد ردیف 1','2');
    fill(quotePane,'قیمت ردیف 1','2500');
    await pause(350);
    click(quotePane,'ذخیره پیش‌فاکتور');
    const proforma=await until(async()=>{
      const current=await window.madar.standaloneAccountingRead();
      return Object.values(current.view.proformas||{}).find(doc=>
        doc.partyId==='QA-WEBVIEW2-NATIVE-01'&&doc.total===5000)||null;
    },12000);
    if(proforma.status!=='draft')throw Error('NATIVE_QA_PROFORMA_NOT_DRAFT');
    const finalLedger=await window.madar.standaloneAccountingRead();
    if(finalLedger.view.journals.length!==0||Object.keys(finalLedger.view.invoices).length!==1)
      throw Error('NATIVE_QA_UNEXPECTED_POSTING_AFTER_PROFORMA');
    window.__nativeQa={status:'PASS_WEBVIEW2_REAL_BRIDGE_DRAFT',phase:'DONE',
      revision:finalLedger.revision,invoiceCount:saved.length,
      proformaCount:Object.keys(finalLedger.view.proformas).length,
      proformaDraft:true,journalCount:finalLedger.view.journals.length,
      invoiceDraft:true,amountVerified:true,customerConfirmationCount:confirmations,
      nativePdfBytes:pdfLength,customTemplateSaved:true,noIssueAttempted:true};
  })().catch(e=>{window.__nativeQa={status:'FAIL',phase:window.__nativeQa.phase,
    errorType:String(e?.message||e).slice(0,110),noIssueAttempted:true};});
  return true;
})()'''

JS_QA_RELOAD = r'''(() => {
  window.__nativeReloadQa={status:'STARTING',phase:'INITIAL'};
  const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const until=async(fn,limit=11000)=>{
    const end=Date.now()+limit;
    while(Date.now()<end){const result=await fn();if(result)return result;await pause(75);}
    throw Error('NATIVE_RELOAD_TIMEOUT_'+window.__nativeReloadQa.phase);
  };
  const click=(root,name)=>{
    const buttons=Array.from(root.querySelectorAll('button')).filter(btn=>
      btn.textContent.trim()===name&&!btn.disabled);
    if(buttons.length!==1)throw Error('NATIVE_RELOAD_BUTTON_'+name+'_'+buttons.length);
    buttons[0].click();
  };
  const fill=(root,label,value)=>{
    const controls=Array.from(root.querySelectorAll('input,textarea')).filter(el=>
      el.getAttribute('aria-label')===label);
    if(controls.length!==1)throw Error('NATIVE_RELOAD_FIELD_'+label+'_'+controls.length);
    const el=controls[0];
    const setter=Object.getOwnPropertyDescriptor(
      el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;
    setter.call(el,String(value));el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
  };
  (async()=>{
    await until(()=>document.querySelector('.sac-root')&&
      typeof window.madar?.standaloneAccountingRead==='function');
    window.__nativeReloadQa.phase='BACKEND_READ';
    const initial=await window.madar.standaloneAccountingRead();
    const original=Object.values(initial.view.invoices||{});
    if(initial.revision!==3||original.length!==1||original[0].total!==13500||
      original[0].partyId!=='QA-WEBVIEW2-NATIVE-01'||
      original[0].note!=='صرفاً آزمایش خصوصی'||
      original[0].createdBy!=='qa-webview2-operator'||!original[0].createdAt||
      original[0].editedAt||original[0].editedBy||
      Object.keys(initial.view.proformas||{}).length!==1||initial.view.journals.length!==0)
      throw Error('NATIVE_RELOAD_SQLITE_DRAFT_LOST');
    const templates=await window.madar.standaloneAccountingTemplateList('print');
    const stored=templates.templates?.find(t=>t.title==='QA WebView2 Custom');
    if(!stored||stored.data.table.customColumns?.[0]?.source!=='unit')
      throw Error('NATIVE_RELOAD_PRINT_TEMPLATE_LOST');
    window.__nativeReloadQa.phase='UI_REOPEN';
    const invoiceTab=await until(()=>document.querySelector('.taraz-vt-primary [data-accounting-tab="invoice"]'));
    invoiceTab.click();
    const list=await until(()=>document.querySelector('.sac-root')?.textContent.includes('ویرایش پیش‌نویس')
      ?document.querySelector('.sac-root'):null);
    click(list,'ویرایش پیش‌نویس');
    await until(()=>document.querySelector('.sac-invoice-editor'));
    const chooser=await until(()=>document.querySelector('[role="group"][aria-label="نوع نمایش فرم فاکتور"]'));
    const mode=()=>Array.from(chooser.querySelectorAll('button')).find(btn=>
      btn.getAttribute('aria-pressed')==='true')?.textContent.trim();
    if(mode()!=='حالت حرفه‌ای')throw Error('NATIVE_RELOAD_NOT_IN_PROFESSIONAL_MODE');
    click(chooser,'ساده و سریع');
    await until(()=>document.querySelector('.sac-invoice-beginner-pane'));
    const currentPane=()=>document.querySelector('.sac-invoice-beginner-pane');
    const verifyForm=(quantity,note)=>{
      const pane=currentPane();
      if(!pane)throw Error('NATIVE_RELOAD_BEGINNER_PANE_NOT_MOUNTED');
      const input=label=>pane.querySelector('[aria-label="'+label+'"]');
      if(mode()!=='ساده و سریع'||input('تعداد ردیف 1')?.value!==quantity||
        input('شرح ردیف 1')?.value!=='چاپ آزمایشی WebView2'||
        input('قیمت ردیف 1')?.value!=='4500'||
        input('مشتری فاکتور')?.value!=='QA-WEBVIEW2-NATIVE-01'||
        input('یادداشت سند')?.value!==note)
        throw Error('NATIVE_RELOAD_MODE_LOST_SHARED_DATA');
    };
    verifyForm('3','صرفاً آزمایش خصوصی');
    window.__nativeReloadQa.phase='MODES';
    click(chooser,'راهنمای مرحله‌ای');
    await until(()=>mode()==='راهنمای مرحله‌ای');
    click(chooser,'حالت حرفه‌ای');
    await until(()=>mode()==='حالت حرفه‌ای');
    click(chooser,'ساده و سریع');
    await until(()=>mode()==='ساده و سریع');
    verifyForm('3','صرفاً آزمایش خصوصی');
    window.__nativeReloadQa.phase='UPDATE';
    fill(currentPane(),'تعداد ردیف 1','4');
    fill(currentPane(),'یادداشت سند','ویرایش بومی آزمایشی');
    await pause(200);
    click(chooser,'حالت حرفه‌ای');
    await until(()=>mode()==='حالت حرفه‌ای');
    click(chooser,'ساده و سریع');
    await until(()=>mode()==='ساده و سریع');
    verifyForm('4','ویرایش بومی آزمایشی');
    click(currentPane(),'ذخیره پیش‌نویس فاکتور');
    const revised=await until(async()=>{
      const state=await window.madar.standaloneAccountingRead();
      const updated=Object.values(state.view.invoices||{})[0];
      return state.revision===4&&updated?.total===18000?state:null;
    },12000);
    const changed=Object.values(revised.view.invoices)[0];
    if(Object.keys(revised.view.invoices||{}).length!==1||
       changed.id!==original[0].id||changed.status!=='draft'||
       changed.partyId!==original[0].partyId||
       changed.documentDate!==original[0].documentDate||
       changed.note!=='ویرایش بومی آزمایشی'||
       changed.createdBy!==original[0].createdBy||
       changed.createdAt!==original[0].createdAt||
       changed.editedBy!=='qa-webview2-operator'||!changed.editedAt||
       changed.editedAt<changed.createdAt||
       revised.view.journals.length!==0||
       Object.keys(revised.view.proformas||{}).length!==1)
      throw Error('NATIVE_RELOAD_UPDATE_CHANGED_FINANCIAL_STATE');
    window.__nativeReloadQa.phase='PROFORMA_EDIT';
    const originalProforma=Object.values(revised.view.proformas)[0];
    if(originalProforma.status!=='draft'||originalProforma.total!==5000)
      throw Error('NATIVE_RELOAD_PROFORMA_BASELINE_MISSING');
    window.__nativeReloadQa.phase='PROFORMA_TAB';
    const menu=await until(()=>document.querySelector('[data-accounting-action="more"]'));
    menu.click();
    const proformaTab=await until(()=>document.querySelector('.taraz-vt-drawer [data-accounting-tab="proforma"]'));
    proformaTab.click();
    window.__nativeReloadQa.phase='PROFORMA_LIST';
    await until(()=>document.querySelector('.sac-root')?.textContent.includes('پیش‌فاکتورهای فروش مستقل'));
    window.__nativeReloadQa.phase='PROFORMA_ROW';
    const quoteRow=await until(()=>Array.from(document.querySelectorAll('tr')).find(row=>
      Array.from(row.querySelectorAll('strong')).some(el=>
        el.textContent.trim()===originalProforma.id)));
    click(quoteRow,'ویرایش');
    window.__nativeReloadQa.phase='PROFORMA_FORM';
    const quotePanel=await until(()=>Array.from(document.querySelectorAll('.sac-panel')).find(el=>
      el.querySelector('h2')?.textContent.trim()==='ویرایش پیش‌فاکتور '+originalProforma.id));
    const quoteInput=label=>Array.from(quotePanel.querySelectorAll('label')).find(el=>
      el.querySelector('span')?.textContent.trim()===label)?.querySelector('input');
    if(quoteInput('تعداد')?.value!=='2'||quoteInput('شرح')?.value!==
      'پیشنهاد قیمت آزمایشی WebView2'||quoteInput('شرایط و توضیحات')?.value!=='')
      throw Error('NATIVE_RELOAD_PROFORMA_FORM_NOT_RESTORED');
    const q=quoteInput('تعداد');
    const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
    setter.call(q,'3');q.dispatchEvent(new Event('input',{bubbles:true}));
    q.dispatchEvent(new Event('change',{bubbles:true}));
    const note=quoteInput('شرایط و توضیحات');
    setter.call(note,'اصلاح پیش‌فاکتور بومی');note.dispatchEvent(new Event('input',{bubbles:true}));
    note.dispatchEvent(new Event('change',{bubbles:true}));
    await pause(300);
    window.__nativeReloadQa.phase='PROFORMA_SAVE';
    click(quotePanel,'ثبت اصلاح');
    window.__nativeReloadQa.phase='PROFORMA_COMMIT';
    const final=await until(async()=>{
      const ledger=await window.madar.standaloneAccountingRead();
      return ledger.revision===5&&ledger.view.proformas?.[originalProforma.id]?.total===7500
        ?ledger:null;
    },12000);
    const editedQuote=final.view.proformas[originalProforma.id];
    if(Object.keys(final.view.proformas).length!==1||editedQuote.status!=='draft'||
       editedQuote.partyId!==originalProforma.partyId||
       editedQuote.note!=='اصلاح پیش‌فاکتور بومی'||
       final.view.invoices[changed.id]?.total!==18000||final.view.journals.length!==0)
      throw Error('NATIVE_RELOAD_PROFORMA_EDIT_CHANGED_FINANCIAL_STATE');
    window.__nativeReloadQa={status:'PASS_RELOAD_EDIT_WEBVIEW2',phase:'DONE',
      sameInvoiceId:true,editedAmount:18000,revision:final.revision,
      allThreeModesPreserved:true,auditAttributionVerified:true,
      proformaPreserved:true,proformaEditedSameId:true,proformaEditedAmount:7500,
      customTemplatePreserved:true,
      journalsUnchanged:true,issueAttempted:false};
  })().catch(e=>{window.__nativeReloadQa={status:'FAIL',phase:window.__nativeReloadQa.phase,
    errorType:String(e?.message||e).slice(0,110),issueAttempted:false};});
  return true;
})()'''


def current_source_assets():
    """Pin the current compiled source UI without claiming frozen EXE parity."""
    web = ROOT / 'dist'
    html = web / 'accounting.html'
    asset_dir = web / 'assets'
    scripts = list(asset_dir.glob('accounting-*.js'))
    styles = list(asset_dir.glob('accounting-*.css'))
    if (not html.is_file() or len(scripts) != 1 or len(styles) != 1):
        raise RuntimeError('Exactly one current compiled Taraz UI asset pair required')
    markup = html.read_text(encoding='utf-8')
    if scripts[0].name not in markup or styles[0].name not in markup:
        raise RuntimeError('Compiled HTML does not reference pinned UI assets')
    return {item.name:hashlib.sha256(item.read_bytes()).hexdigest()
            for item in (html, scripts[0], styles[0])}


def child(work: Path):
    if not (work / 'qa-owned-marker.json').is_file():
        raise RuntimeError('Private QA marker unavailable')
    if not Path(os.environ['APPDATA']).resolve().is_relative_to(work):
        raise RuntimeError('Live roaming profile inherited by child')
    marker=json.loads((work/'qa-owned-marker.json').read_text(encoding='utf-8'))
    if marker.get('mode')=='current-source':
        from scripts import build_taraz_v106_aaas_20261111 as build
        if (marker.get('sourceSha256')!=build.digest_inventory(build.source_inventory())
                or marker.get('compiledAssets')!=current_source_assets()):
            raise RuntimeError('Current source/compiled assets changed after private QA preflight')
        web=ROOT/'dist'
    elif marker.get('mode')=='frozen-parity':
        web=BUILD/'web'/'dist'
        if not web.is_dir():
            raise RuntimeError('Frozen compiled UI not present')
        expected=hashlib.sha256((web/'assets'/'accounting-DKQ-HWh2.js').read_bytes()).hexdigest()
        if expected!=SOURCE_JS_SHA:
            raise RuntimeError('Frozen WebView JavaScript bytes differ')
    else:
        raise RuntimeError('Unknown private QA source mode')
    api = QAAPI(work/'private-book')
    server = serve_accounting_page(web)
    server_thread = Thread(target=server.serve_forever,daemon=True)
    server_thread.start()
    import webview
    window = webview.create_window('تراز QA خصوصی WebView2',
                                   f'http://127.0.0.1:{server.server_port}/accounting.html',
                                   width=1490,height=950,js_api=api)
    api._native_window=window
    result = {'status':'NOT_RUN'}
    def test_live():
        nonlocal result
        try:
            success=False
            # Full regression runs leave Edge workers and Python tests to settle;
            # a cold native WebView2 may start significantly slower than a
            # dedicated smoke run. Observe readiness, never guess success.
            latest_startup='UNOBSERVED'
            latest_error='NONE'
            for attempt in range(180):
                time.sleep(.2)
                try:
                    raw=window.evaluate_js("JSON.stringify({readyState:document.readyState,"
                        "hasRoot:!!document.querySelector('.sac-root'),"
                        "hasBridge:typeof window.madar?.standaloneAccountingRead==='function'})")
                    state=json.loads(raw) if isinstance(raw,str) else raw
                    latest_startup=state.get('readyState','UNKNOWN')
                    if state.get('hasRoot') and state.get('hasBridge'):
                        success=True
                        break
                except Exception as exc:
                    latest_error=type(exc).__name__
                    continue
            if not success:
                raise RuntimeError('Native WebView2 startup gate blocked: '+
                    latest_startup+' / '+latest_error)
            window.evaluate_js(JS_QA)
            for attempt in range(160):
                time.sleep(.14)
                try:
                    raw=window.evaluate_js('JSON.stringify(window.__nativeQa||{})')
                    observed=json.loads(raw) if isinstance(raw,str) else raw
                    if observed.get('status') in ('PASS_WEBVIEW2_REAL_BRIDGE_DRAFT','FAIL'):
                        result=observed;break
                except Exception:
                    continue
            else:
                result={'status':'FAIL','errorType':'NATIVE_QA_REPORT_TIMEOUT'}
            if result.get('status')=='PASS_WEBVIEW2_REAL_BRIDGE_DRAFT':
                window.evaluate_js('window.location.reload()')
                ready=False
                for attempt in range(140):
                    time.sleep(.18)
                    try:
                        if window.evaluate_js("Boolean(document.querySelector('.sac-root') && "
                            "typeof window.madar?.standaloneAccountingRead==='function')"):
                            ready=True
                            break
                    except Exception:
                        continue
                if not ready:
                    raise RuntimeError('Native QA second WebView load unavailable')
                window.evaluate_js(JS_QA_RELOAD)
                result['afterReload']={'status':'NOT_OBSERVED'}
                for attempt in range(185):
                    time.sleep(.16)
                    try:
                        raw=window.evaluate_js('JSON.stringify(window.__nativeReloadQa||{})')
                        observed=json.loads(raw) if isinstance(raw,str) else raw
                        if observed.get('status') in ('PASS_RELOAD_EDIT_WEBVIEW2','FAIL'):
                            result['afterReload']=observed
                            break
                    except Exception:
                        continue
                if result['afterReload'].get('status')!='PASS_RELOAD_EDIT_WEBVIEW2':
                    result['status']='FAIL'
                    result['errorType']='NATIVE_RELOAD_EDIT_NOT_ACCEPTED'
        except Exception as exc:
            result={'status':'FAIL','errorType':type(exc).__name__,'error':str(exc)[:90]}
        finally:
            (work/'native-result.json').write_text(json.dumps(result,ensure_ascii=True,indent=2)+'\n',
                                                    encoding='utf-8')
            try: window.destroy()
            except Exception: pass
    try:
        webview.start(test_live,debug=False)
    finally:
        server.shutdown();server.server_close();server_thread.join(timeout=5)


def parent(*, current_source=False):
    from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acl
    from scripts import build_taraz_v106_aaas_20261111 as build
    from PyInstaller.archive.readers import CArchiveReader
    actual_source_sha=build.digest_inventory(build.source_inventory())
    compiled_assets=None
    if current_source:
        compiled_assets=current_source_assets()
    else:
        exe=BUILD/'binary'/'Taraz.exe'
        if not exe.is_file() or hashlib.sha256(exe.read_bytes()).hexdigest()!=EXE_SHA:
            raise RuntimeError('Frozen Taraz EXE identity failed; source QA cannot proceed')
        frozen_js=CArchiveReader(str(exe)).extract('dist\\assets\\accounting-DKQ-HWh2.js')
        if (not isinstance(frozen_js,bytes) or
                hashlib.sha256(frozen_js).hexdigest()!=SOURCE_JS_SHA or
                frozen_js!=(BUILD/'web'/'dist'/'assets'/'accounting-DKQ-HWh2.js').read_bytes()):
            raise RuntimeError('Native QA source assets are not byte-identical to frozen EXE')
        report=json.loads((BUILD/'build-report.json').read_text(encoding='utf-8'))
        if (report.get('sourceFreezeSha256')!=actual_source_sha or
                report.get('exeSha256')!=EXE_SHA or report.get('installed') is not False):
            raise RuntimeError('Current full runtime source fingerprint differs from immutable build')
        local_build=ROOT/'dist'/'assets'/'accounting-DKQ-HWh2.js'
        if not local_build.is_file() or local_build.read_bytes()!=frozen_js:
            raise RuntimeError('Current source Vite build differs from frozen EXE; refuse stale native QA')
    if not OUTPUT.exists(): acl.secure_private_directory(OUTPUT)
    work=OUTPUT/('qa-private-'+uuid.uuid4().hex[:12]);acl.secure_private_directory(work)
    (work/'qa-owned-marker.json').write_text(json.dumps({
        'syntheticOnly':True,'timestamp':time.time(),
        'mode':'current-source' if current_source else 'frozen-parity',
        'sourceSha256':actual_source_sha,
        'compiledAssets':compiled_assets,
    }),encoding='utf-8')
    runtime=work/'qa'/'qa-runtime';runtime.mkdir(parents=True)
    roots={}
    for key in ('roaming','localappdata','temp','userprofile','webview-profile'):
        roots[key]=runtime/key;roots[key].mkdir(parents=True)
    environment=private.isolated_env(runtime,{'roaming':roots['roaming'],
            'local':roots['localappdata'],'bridge':roots['localappdata']},
            work/'qa-status.json',private.unused_port())
    environment['PYTHONPATH']=str(ROOT)
    environment['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']='--disable-background-networking --disable-sync --no-first-run --proxy-server=http://127.0.0.1:9 --proxy-bypass-list=<-loopback>'
    baseline=build.installed_baseline()
    user_pids={p.pid:p.create_time() for p in psutil.process_iter(['name'])
               if (p.info.get('name') or '').lower()=='taraz.exe'}
    with private.PrivateDesktop() as desktop:
        executable=Path(sys.executable)
        pid,hproc,hthread=desktop.spawn(executable,work,environment,
                              ('-B',str(Path(__file__).resolve()),'--child',str(work)))
        kernel=ctypes.windll.kernel32
        try:
            finished=kernel.WaitForSingleObject(hproc,150000)
            if finished!=0:
                raise RuntimeError('QA source WebView did not exit normally; no force terminate used')
        finally:
            kernel.CloseHandle(hproc);kernel.CloseHandle(hthread)
    evidence=work/'native-result.json'
    result=json.loads(evidence.read_text(encoding='utf-8')) if evidence.is_file() else {'status':'NO_CHILD_EVIDENCE'}
    book=work/'private-book'/'standalone-accounting.sqlite3'
    saved=False
    proforma_saved=False
    journal_unchanged=False
    stale_revision_rejected=False
    audit_preserved=False
    if book.is_file():
        store=StandaloneAccountingStore(book)
        state=store.read(actor=Identity.user['username'],
                         accounts=Identity().accounting_accounts())
        invoices=[row for row in state['view']['invoices'].values() if row.get('partyId')==QA_PARTY]
        saved=(state['revision']==5 and len(invoices)==1 and
               invoices[0]['total']==18000 and invoices[0]['status']=='draft' and
               invoices[0]['note']=='ویرایش بومی آزمایشی')
        if saved:
            invoice=invoices[0]
            audit_preserved=(invoice.get('createdBy')==Identity.user['username'] and
                             invoice.get('editedBy')==Identity.user['username'] and
                             bool(invoice.get('createdAt')) and bool(invoice.get('editedAt')) and
                             invoice.get('createdAt')<=invoice.get('editedAt'))
            # A stale CAS update must not create a sixth event or mutate a draft.
            try:
                QAAPI(work/'private-book').standaloneAccountingCommand({
                    'expectedRevision':4,
                    'command':{'type':'invoice.update','eventId':'qa-native-stale-cas-rejected',
                               'invoiceId':invoice['id'],'partyId':invoice['partyId'],
                               'documentDate':invoice['documentDate'],
                               'note':'NOT PERSISTED','lines':invoice['lines']}})
            except AccountingRevisionConflict:
                stale_revision_rejected=True
            after_stale=StandaloneAccountingStore(book).read(
                actor=Identity.user['username'],accounts=Identity().accounting_accounts())
            stale_revision_rejected=(stale_revision_rejected and after_stale==state)
        quotes=[row for row in state['view']['proformas'].values() if row.get('partyId')==QA_PARTY]
        proforma_saved=(len(quotes)==1 and quotes[0]['total']==7500 and
                         quotes[0]['status']=='draft' and
                         quotes[0]['note']=='اصلاح پیش‌فاکتور بومی')
        journal_unchanged=state['view']['journals']==[]
    persisted_custom=False
    if book.is_file():
        templates=StandaloneAccountingTemplateStore(book.parent).list('print')['templates']
        persisted_custom=any(t['title']=='QA WebView2 Custom' and
             any(c.get('source')=='unit' and c.get('label')=='واحد سفارشی'
                 for c in t['data']['table'].get('customColumns',[])) for t in templates)
    previous_unchanged=True
    for pid,when in user_pids.items():
        try:
            if psutil.Process(pid).create_time()!=when:previous_unchanged=False
        except psutil.NoSuchProcess:
            previous_unchanged=False
    source_unchanged=(actual_source_sha==build.digest_inventory(build.source_inventory())
                      and (not current_source or compiled_assets==current_source_assets()))
    report={'status':result.get('status'),'sameCompiledUiAsFrozenExe':not current_source,
            'sourceHostedNativeNotProductionExe':True,
            'sourceMode':'current-source' if current_source else 'frozen-parity',
            'sourceSha256':actual_source_sha,'sourceUnchangedDuringQa':source_unchanged,
            'syntheticInvoiceReallySaved':saved,'syntheticProformaReallySaved':proforma_saved,
            'noGeneralJournal':journal_unchanged,
            'staleRevisionRejectedWithoutMutation':stale_revision_rejected,
            'createEditAuditVerified':audit_preserved,
            'customPrintTemplateReallySaved':persisted_custom,
            'installedBaselineUnchanged':baseline==build.installed_baseline(),
            'previousTarazProcessesUnchanged':previous_unchanged,
            'childReport':result,'evidenceFolder':str(work)}
    print(json.dumps(report,ensure_ascii=True))
    return 0 if (result.get('status')=='PASS_WEBVIEW2_REAL_BRIDGE_DRAFT' and
        saved and proforma_saved and journal_unchanged and persisted_custom and
        stale_revision_rejected and audit_preserved and
        result.get('afterReload',{}).get('status')=='PASS_RELOAD_EDIT_WEBVIEW2' and
        report['installedBaselineUnchanged'] and previous_unchanged and
        source_unchanged) else 1

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--child':child(Path(sys.argv[2]))
    elif len(sys.argv)==2 and sys.argv[1]=='--current-source':
        raise SystemExit(parent(current_source=True))
    elif len(sys.argv)==1:
        raise SystemExit(parent())
    else:
        raise SystemExit('Unknown private native QA arguments')
