'use strict';
/** P1 acceptance: read-only installed-archive inspection and isolated Chromium
 * with the genuine current React components plus a synthetic in-memory host.
 * No installed program is launched and no ledger, profile or LAN is touched.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const esbuild=require(path.join(root,'node_modules','esbuild'));
const modules=path.join(root,'node_modules');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'', 'npm','node_modules','playwright'));}

const fixture=String.raw`import React from 'react';
import {createRoot} from 'react-dom/client';
import {StandaloneAccountingWorkspace} from './src/standalone_accounting_workspace.jsx';
import {TarazSileoToaster} from './src/taraz_sileo_feedback.jsx';
if(globalThis.crypto?.getRandomValues&&!globalThis.crypto.randomUUID){
 Object.defineProperty(globalThis.crypto,'randomUUID',{configurable:true,value:()=>{
  const b=new Uint8Array(16);crypto.getRandomValues(b);
  b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;
  const h=[...b].map(x=>x.toString(16).padStart(2,'0')).join('');
  return h.slice(0,8)+'-'+h.slice(8,12)+'-'+h.slice(12,16)+'-'+h.slice(16,20)+'-'+h.slice(20);
 }});
}
const view={currency:'RIAL',journals:[],accounts:{},parties:{},items:{},
 invoices:{},bills:{},receipts:{},payments:{},proformas:{},taxRules:{},
 contractorJobs:{},returns:{},cashAccounts:{},companyProfile:{legalName:'QA in-memory'},
 closedThrough:null,sequence:{invoice:0,bill:0}};
let revision=0;
window.__p1={commands:[],madarReads:[],lists:0,madarFailure:false,settingsFailure:false};
const snapshot=()=>({revision,view,capabilities:{canManage:true,canDraft:true,canAdmin:true},
 currentUser:{username:'qa-admin',role:'admin',jobTitle:''}});
const api={
 standaloneAccountingRead:async()=>snapshot(),
 standaloneAccountingCommand:async x=>{
  window.__p1.commands.push({type:x?.command?.type,expectedRevision:x?.expectedRevision});
  revision++;return snapshot();
 },
 standaloneAccountingTemplateList:async()=>({templates:[],defaultId:''}),
 tarazIntegrationList:async()=>{window.__p1.lists++;
  if(window.__p1.settingsFailure)throw Error('QA-MADAR-SECRET-470129');
  return {connected:false,requests:[],recovery:[],invalidCount:0};},
 tarazMadarDataRead:async(scope,offset,limit,consent,auth,source)=>{
  window.__p1.madarReads.push({scope,offset,limit,consent,source});
  if(window.__p1.madarFailure)throw Error('QA-MADAR-SECRET-470129');
  return {scope,offset,items:{[scope]:[]},counts:{[scope]:0},
   financialEventCreated:false,
   source:{kind:'madar-local-projection',readOnly:true,hostAuthenticated:false,mayBeStale:true}};
 }
};
createRoot(document.getElementById('root')).render(
 <><TarazSileoToaster/><StandaloneAccountingWorkspace api={api}
   canManage={true} canDraft={true} canAdmin={true}/></>);`;

async function compileCurrentSource(){
  const files=(await esbuild.build({
    stdin:{contents:fixture,resolveDir:root,sourcefile:'taraz-p1-browser-fixture.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',write:false,charset:'utf8',
    outdir:'taraz-p1-in-memory',logLevel:'silent',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'},
    plugins:[{name:'local-dependencies',setup(build){
      build.onResolve({filter:/^(react|react-dom\/client|react\/jsx-runtime|lucide-react|sileo|motion)$/},
        args=>({path:require.resolve(args.path,{paths:[modules]})}));
    }}]
  })).outputFiles;
  const js=files.find(f=>f.path.endsWith('.js'))?.text;
  assert.ok(js&&js.includes('taraz-feedback-host')&&js.includes('taraz-context-help-trigger'));
  return {js,css:files.find(f=>f.path.endsWith('.css'))?.text||''};
}

async function compileRealMain(){
  const files=(await esbuild.build({
    entryPoints:[path.join(root,'src','standalone_main.jsx')],
    bundle:true,platform:'browser',format:'iife',write:false,charset:'utf8',
    outdir:'taraz-p1-main-in-memory',logLevel:'silent',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl',
      '.woff2':'dataurl'},
    plugins:[{name:'local-dependencies',setup(build){
      build.onResolve({filter:/^\/fonts\//},args=>({path:args.path,external:true}));
      build.onResolve({filter:/^(react|react-dom\/client|react\/jsx-runtime|lucide-react|sileo|motion)$/},
        args=>({path:require.resolve(args.path,{paths:[modules]})}));
    }}]
  })).outputFiles;
  return {js:files.find(f=>f.path.endsWith('.js'))?.text,
    css:files.find(f=>f.path.endsWith('.css'))?.text||''};
}

async function browserPage(browser,assets,width,height=850){
  const context=await browser.newContext({viewport:{width,height},
    reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',route=>route.abort('blockedbyclient'));
  const page=await context.newPage();
  page.setDefaultTimeout(10000);
  const pageErrors=[];
  page.on('pageerror',e=>pageErrors.push(e.message));
  await page.setContent('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:assets.js});
  await page.locator('.taraz-context-help-trigger').waitFor();
  return {context,page,pageErrors};
}
async function drawerTab(page,tab){
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
  const drawer=page.getByRole('dialog',{name:'فهرست بخش‌های تراز'});
  await drawer.locator('[data-accounting-tab="'+tab+'"]').first().click();
  assert.equal(await drawer.count(),0);
}
async function helpClosesByPointer(page,expected){
  const button=page.locator('.taraz-context-help-trigger');
  await button.click();
  const dialog=page.getByRole('dialog',{name:'راهنمای '+expected});
  await dialog.waitFor();
  assert.equal(await dialog.getAttribute('dir'),'rtl');
  assert.equal(await dialog.getAttribute('aria-modal'),'true');
  assert.equal(await dialog.locator('ol > li').count()>0,true);
  assert.equal(await page.locator('body > .taraz-context-help-layer').count(),1);
  await dialog.getByRole('button',{name:'بستن راهنما'}).click();
  await dialog.waitFor({state:'detached'});
  assert.equal(await button.evaluate(el=>document.activeElement===el),true);
}

test('installed 1.0.2 contains the actual compiled P1 UI markers (read-only archive)',()=>{
  const installed=path.join(process.env.LOCALAPPDATA||'', 'Programs','Taraz');
  const pointer=path.join(installed,'current-version.txt');
  assert.equal(fs.readFileSync(pointer,'utf8').replace(/^\uFEFF/,'').trim(),'1.0.2');
  const exe=path.join(installed,'versions','1.0.2','Taraz.exe');
  const hash=crypto.createHash('sha256').update(fs.readFileSync(exe)).digest('hex');
  assert.equal(hash,'095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52');
  const py=String.raw`import json,sys
from PyInstaller.archive.readers import CArchiveReader
a=CArchiveReader(sys.argv[1]);names=[n for n in a.toc if n.replace('\\','/').lower().endswith('.js') and 'assets/' in n.replace('\\','/')]
blob=b'\n'.join(a.extract(n) for n in names)
marks={'sileo':b'taraz-feedback-host','contextHelp':b'taraz-context-help-trigger','rtl':b'taraz-vt-app','responsiveNav':b'sac-nav-more-trigger','madar':b'taraz-madar-dashboard','madarQuickNav':b'taraz-madar-quick-nav','printDesigner':b'sac-print-designer','invoiceDesign':b'invoiceDesign'}
print(json.dumps({'jsAssets':names,'size':len(blob),'markers':{k:v in blob for k,v in marks.items()}},sort_keys=True))`;
  const out=spawnSync('py',['-3.12','-B','-c',py,exe],{cwd:root,encoding:'utf8',timeout:30000});
  assert.equal(out.status,0,'PyInstaller read-only extraction failed: '+out.stderr);
  const evidence=JSON.parse(out.stdout.trim());
  assert.ok(evidence.jsAssets.length>0,'installed archive lacks compiled UI');
  for(const [feature,present] of Object.entries(evidence.markers))
    assert.equal(present,true,'installed v1.0.2 compiled asset missing '+feature);
});

test('desktop Chromium: contextual help pointer close, print designer canvas, no finance calls',async t=>{
  const assets=await compileCurrentSource();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());
  const {page,context,pageErrors}=await browserPage(browser,assets,1440,900);
  try{
    assert.equal(await page.locator('.sac-root').getAttribute('dir'),'rtl');
    await helpClosesByPointer(page,'داشبورد');
    await drawerTab(page,'invoice');
    await helpClosesByPointer(page,'فاکتورهای فروش');
    await drawerTab(page,'invoiceDesign');
    await page.getByRole('heading',{name:'طراح بصری قالب فاکتور'}).waitFor();
    await page.getByRole('textbox',{name:'نام قالب'}).fill('P1 QA visual template');
    await page.getByRole('textbox',{name:'نام چاپی شرکت'}).fill('Synthetic Print Title');
    await page.waitForFunction(()=>{
      const c=document.querySelector('.sac-print-canvas-shell canvas');
      return !!c&&c.width>500&&c.height>500&&!document.querySelector('.sac-print-error');
    });
    assert.equal(await page.getByRole('textbox',{name:'نام چاپی شرکت'}).inputValue(),
      'Synthetic Print Title');
    assert.deepEqual(await page.evaluate(()=>window.__p1.commands),[]);
    assert.deepEqual(pageErrors,[]);
  }finally{await context.close();}
});

test('390px Chromium: direct Madar tab, consent gate, help, RTL and viewport containment',async t=>{
  const assets=await compileCurrentSource();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());
  const {page,context,pageErrors}=await browserPage(browser,assets,390,844);
  try{
    assert.equal(await page.locator('.sac-root').getAttribute('dir'),'rtl');
    const quick=page.locator('.taraz-madar-quick-nav [data-accounting-tab="madar"]');
    await quick.click();
    assert.equal(await quick.getAttribute('aria-current'),'page');
    await page.getByRole('heading',{name:'اطلاعات مدار',exact:true}).first().waitFor();
    assert.deepEqual(await page.evaluate(()=>window.__p1.madarReads),[]);
    const explorer=page.locator('.taraz-madar-dashboard:not(.taraz-madar-home) .taraz-madar-explorer');
    await explorer.getByRole('checkbox',{name:/اجازه می‌دهم فقط با دکمه دریافت/}).check();
    assert.deepEqual(await page.evaluate(()=>window.__p1.madarReads),[]);
    await explorer.getByRole('button',{name:'خواندن اطلاعات انتخاب‌شده'}).click();
    await explorer.getByText('ممکن است داده محلی به‌روز نباشد.').waitFor();
    assert.deepEqual(await page.evaluate(()=>window.__p1.madarReads),[
      {scope:'projects',offset:0,limit:50,consent:true,source:'local'}]);
    const dims=await page.evaluate(()=>({viewport:innerWidth,
      document:document.documentElement.scrollWidth,body:document.body.scrollWidth,
      root:document.querySelector('.sac-root').getBoundingClientRect().width}));
    assert.ok(dims.document<=dims.viewport+1,
      'horizontal document overflow at 390px: '+JSON.stringify(dims));
    assert.ok(dims.root<=dims.viewport+1,
      'accounting app root too wide at 390px: '+JSON.stringify(dims));
    await drawerTab(page,'invoice');
    await helpClosesByPointer(page,'فاکتورهای فروش');
    assert.deepEqual(await page.evaluate(()=>window.__p1.commands),[]);
    assert.deepEqual(pageErrors,[]);
  }finally{await context.close();}
});

test('Madar failed read must not render raw host exception text in the page',async t=>{
  const assets=await compileCurrentSource();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());
  const {page,context,pageErrors}=await browserPage(browser,assets,1440);
  try{
    await page.evaluate(()=>window.__p1.madarFailure=true);
    await page.locator('.taraz-madar-quick-nav [data-accounting-tab="madar"]').click();
    const explorer=page.locator('.taraz-madar-dashboard:not(.taraz-madar-home) .taraz-madar-explorer');
    await explorer.getByRole('checkbox',{name:/اجازه می‌دهم فقط با دکمه دریافت/}).check();
    await explorer.getByRole('button',{name:'خواندن اطلاعات انتخاب‌شده'}).click();
    const alert=explorer.getByRole('alert');
    await alert.waitFor();
    assert.doesNotMatch(await alert.innerText(),/QA-MADAR-SECRET-470129/,
      'host exception secret is being shown to the operator');
    assert.deepEqual(await page.evaluate(()=>window.__p1.commands),[],
      'a failed Madar read must not post finance transactions');
    assert.deepEqual(pageErrors,[]);
  }finally{await context.close();}
});

test('settings connection failure cannot show a raw backend error token',async t=>{
  const assets=await compileCurrentSource();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());
  const {page,context,pageErrors}=await browserPage(browser,assets,1366);
  try{
    await page.evaluate(()=>window.__p1.settingsFailure=true);
    await drawerTab(page,'settings');
    await page.getByRole('button',{name:'اتصال به مدار'}).click();
    await page.getByRole('checkbox',{name:/ارجاع‌های مدار را دستی بررسی کنم/}).check();
    assert.equal(await page.evaluate(()=>window.__p1.lists),0);
    await page.getByRole('button',{name:'بررسی وضعیت اتصال'}).click();
    const message=page.locator('.taraz-settings-message.error');
    await message.waitFor();
    assert.doesNotMatch(await message.innerText(),/QA-MADAR-SECRET-470129/);
    assert.equal(await page.evaluate(()=>window.__p1.lists),1);
    assert.deepEqual(await page.evaluate(()=>window.__p1.commands),[]);
    assert.deepEqual(pageErrors,[]);
  }finally{await context.close();}
});

test('Sileo only confirms a manually accepted synthetic accounting revision',async t=>{
  const assets=await compileCurrentSource();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());
  const {page,context,pageErrors}=await browserPage(browser,assets,1366);
  try{
    const toast=page.locator('.taraz-feedback-host [data-sileo-viewport]');
    assert.equal(await toast.count(),0,'navigation must not display a false success notification');
    await drawerTab(page,'parties');
    const panel=page.locator('.sac-panel').filter({
      has:page.getByRole('heading',{name:'ثبت شخص جدید'})}).last();
    await panel.locator('input[placeholder="PERSON-001"]').fill('QA-PERSON-001');
    await panel.locator('input[required]:not([dir="ltr"])').fill('QA-CUSTOMER-SECRET-335');
    await panel.getByRole('button',{name:'ثبت شخص',exact:true}).click();
    await page.getByText('طرف‌حساب در دفتر میزبان ثبت شد.').waitFor();
    const result=await toast.innerText();
    assert.match(result,/طرف‌حساب در دفتر میزبان ثبت شد/);
    assert.doesNotMatch(result,/QA-CUSTOMER-SECRET-335|رسید رسمی صادر شد/);
    assert.deepEqual(await page.evaluate(()=>window.__p1.commands),[
      {type:'party.register',expectedRevision:0}]);
    assert.deepEqual(pageErrors,[]);
  }finally{await context.close();}
});

test('real standalone_main user and company action failures mask host exceptions',async t=>{
  const assets=await compileRealMain();
  assert.ok(assets.js?.includes('taraz-feedback-host'));
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());
  const context=await browser.newContext({viewport:{width:1366,height:850},
    reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',route=>route.abort('blockedbyclient'));
  try{
    const page=await context.newPage();
    page.setDefaultTimeout(10000);
    const pageErrors=[];
    page.on('pageerror',e=>pageErrors.push(e.message));
    await page.setContent('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
    await page.evaluate(()=>{
      window.__p1main={users:0,company:0,alerts:[],commands:0};
      window.alert=message=>window.__p1main.alerts.push(message);
      window.confirm=()=>true;
      const view={currency:'RIAL',journals:[],accounts:{},parties:{},items:{},
        invoices:{},bills:{},receipts:{},payments:{},proformas:{},taxRules:{},
        contractorJobs:{},returns:{},cashAccounts:{},
        companyProfile:{legalName:'QA company'},closedThrough:null,
        sequence:{invoice:0,bill:0}};
      window.madar={
        standaloneAccountingRead:async()=>({revision:0,view,
          capabilities:{canManage:true,canDraft:true,canAdmin:true},
          currentUser:{username:'qa-admin',role:'admin',jobTitle:''}}),
        standaloneAccountingCommand:async()=>{window.__p1main.commands++;
          throw Error('Unexpected finance command');},
        standaloneAccountingManageUsers:async()=>{window.__p1main.users++;
          throw Error('QA-STANDALONE-HOST-SECRET-2001');},
        standaloneAccountingRequestCompanySwitch:async()=>{window.__p1main.company++;
          throw Error('QA-STANDALONE-HOST-SECRET-2001');}
      };
    });
    if(assets.css)await page.addStyleTag({content:assets.css});
    await page.addScriptTag({content:assets.js});
    await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).waitFor();
    await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
    const drawer=page.getByRole('dialog',{name:'فهرست بخش‌های تراز'});
    await drawer.getByRole('button',{name:'کاربران'}).click();
    await page.waitForFunction(()=>window.__p1main.alerts.length===1);
    await drawer.getByRole('button',{name:'تغییر شرکت'}).click();
    await page.waitForFunction(()=>window.__p1main.alerts.length===2);
    const evidence=await page.evaluate(()=>structuredClone(window.__p1main));
    assert.equal(evidence.users,1);
    assert.equal(evidence.company,1);
    assert.equal(evidence.commands,0);
    for(const alert of evidence.alerts){
      assert.doesNotMatch(alert,/QA-STANDALONE-HOST-SECRET-2001/);
      assert.match(alert,/میزبان/);
    }
    assert.deepEqual(pageErrors,[]);
  }finally{await context.close();}
});
