'use strict';
/** Current-source Taraz React in disposable Chromium, synthetic host ONLY.
 * Never opens installed Taraz, a finance ledger, remote URL or user profile.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const modules=path.join(root,'node_modules');
const esbuild=require(path.join(modules,'esbuild'));
const madarModules=path.resolve(root,'..','..','000- Madar',
  'madar-p2-gantt-notifications-20261107','node_modules');
let playwright;
try{playwright=require(path.join(madarModules,'playwright'));}
catch{playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
  'AppData','Roaming','npm','node_modules','playwright'));}
const source=fs.readFileSync(path.join(root,'src','standalone_accounting_workspace.jsx'),'utf8');
const match=source.match(/const SECTIONS=\[([\s\S]*?)\];/);
assert.ok(match,'current source must have real visible nav');
const labels=Object.fromEntries([...match[1].matchAll(/\['([^']+)','([^']+)'\]/g)]
  .map(([,id,label])=>[id,label]));
const secrets=['QA-PRIVATE-INVOICE-438927','QA-SECRET-TOKEN-7001',
  'QA-PRIVATE-CUSTOMER-7022'];

const fixture=String.raw`import React from 'react';
import {createRoot} from 'react-dom/client';
import {StandaloneAccountingWorkspace} from './src/standalone_accounting_workspace.jsx';
import {TarazSileoToaster} from './src/taraz_sileo_feedback.jsx';
// about:blank is not a secure origin, so randomUUID is absent in synthetic
// Chromium. Provide ONLY this fixture's CSPRNG-backed UUID equivalent.
// Never add fallback UUID generation to Taraz production source.
if(globalThis.crypto?.getRandomValues&&!globalThis.crypto.randomUUID){
 Object.defineProperty(globalThis.crypto,'randomUUID',{
   configurable:true,value:()=>{
     const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);
     bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
     const hex=[...bytes].map(x=>x.toString(16).padStart(2,'0')).join('');
     return hex.slice(0,8)+'-'+hex.slice(8,12)+'-'+hex.slice(12,16)+
       '-'+hex.slice(16,20)+'-'+hex.slice(20);
   }
 });
}
const view={currency:'RIAL',journals:[],accounts:{},parties:{},items:{},
 invoices:{},bills:{},receipts:{},payments:{},proformas:{},taxRules:{},
 contractorJobs:{},returns:{},cashAccounts:{},companyProfile:{legalName:'Synthetic QA'},
 closedThrough:null,sequence:{invoice:0,bill:0}};
window.__qa={commands:[],reviews:[],reads:0,lists:0,mode:window.__qaMode||'ack'};
let revision=0;
const item={schema:1,source:'madar',id:'a'.repeat(32),taskId:'qa-task',
 projectId:'qa-project',title:'QA-PRIVATE-INVOICE-438927',
 amountRial:98989898,token:'QA-SECRET-TOKEN-7001'};
const snapshot=()=>({revision,view,capabilities:{canManage:true,canDraft:true,canAdmin:true},
 currentUser:{username:'qa-admin',role:'admin',jobTitle:''}});
const api={
 standaloneAccountingRead:async()=>{window.__qa.reads++;return snapshot();},
 standaloneAccountingCommand:async request=>{
   window.__qa.commands.push({type:request?.command?.type,
     eventId:request?.command?.eventId,expectedRevision:request?.expectedRevision});
   if(window.__qa.mode==='error')throw Error('QA-SECRET-TOKEN-7001');
   if(window.__qa.mode==='uncertain')return snapshot();
   revision++;return snapshot();
 },
 tarazIntegrationList:async()=>{window.__qa.lists++;
   return {connected:true,invalidCount:0,requests:[item],recovery:[]};},
 tarazIntegrationReview:async(id,decision)=>{
   window.__qa.reviews.push([id,decision]);
   if(window.__qa.mode==='review-error')throw Error('QA-SECRET-TOKEN-7001');
   if(window.__qa.mode==='review-wrong-id')
     return {id:'b'.repeat(32),state:decision,financialEventCreated:false};
   return {id,state:decision,financialEventCreated:false};
 }
};
createRoot(document.getElementById('root')).render(
 <><TarazSileoToaster/><StandaloneAccountingWorkspace api={api}
 canManage={true} canDraft={true} canAdmin={true}/></>);`;

async function build(){
  const files=(await esbuild.build({
    stdin:{contents:fixture,resolveDir:root,sourcefile:'taraz-sileo-help-qa.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',write:false,charset:'utf8',
    outdir:'taraz-sileo-help-memory-only',logLevel:'silent',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'},
    plugins:[{name:'local-dependencies',setup(build){
      build.onResolve({filter:/^(react|react-dom\/client|react\/jsx-runtime|lucide-react|sileo|motion)$/},
        args=>({path:require.resolve(args.path,{paths:[modules]})}));
    }}]
  })).outputFiles;
  const js=files.find(f=>f.path.endsWith('.js'))?.text;
  assert.ok(js?.includes('taraz-feedback-host')&&js.includes('taraz-context-help-trigger'),
    'current compiled UI must contain actual Sileo host and contextual help');
  return {js,css:files.find(f=>f.path.endsWith('.css'))?.text||''};
}
async function pageFor(browser,assets,mode='ack'){
  const context=await browser.newContext({viewport:{width:1400,height:950},
    reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',route=>route.abort('blockedbyclient'));
  const page=await context.newPage();
  page.setDefaultTimeout(5500);
  page.on('pageerror',error=>console.error('[Taraz QA browser page error]',error.message));
  await page.setContent('<!doctype html><html lang="fa" dir="rtl"><head>'+
    '<meta charset="utf-8"></head><body><main id="root"></main></body></html>');
  await page.evaluate(mode=>window.__qaMode=mode,mode);
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:assets.js});
  await page.locator('.taraz-context-help-trigger').waitFor();
  return {context,page};
}
const state=page=>page.evaluate(()=>structuredClone(window.__qa));
const toast=page=>page.locator('.taraz-feedback-host [data-sileo-viewport]');
const dialog=page=>page.getByRole('dialog',{name:/راهنمای/});
async function navigate(page,tab){
  const primary=page.locator('.taraz-vt-primary [data-accounting-tab="'+tab+'"]');
  if(await primary.count())await primary.click();
  else{
    await page.locator('.sac-nav-more-trigger').click();
    await page.locator('.taraz-vt-drawer [data-accounting-tab="'+tab+'"]').click();
  }
}
async function openGuide(page,tab){
  await page.locator('.taraz-context-help-trigger').click();
  const d=dialog(page);await d.waitFor();
  assert.equal(await d.getAttribute('dir'),'rtl');
  assert.equal(await d.getAttribute('aria-modal'),'true');
  assert.equal(await d.locator('h2').innerText(),'راهنمای '+labels[tab]);
  const steps=await d.locator('ol > li').allTextContents();
  assert.ok(steps.length>=1&&steps.length<=3,'guide should be short');
  return steps;
}
function safeToast(text){
  for(const secret of secrets)assert.ok(!text.includes(secret),'toast leaked private payload');
  assert.doesNotMatch(text,/رسید رسمی (صادر|تأیید) شد/);
}
async function submitParty(page){
  await navigate(page,'parties');
  const panel=page.locator('.sac-panel').filter({
    has:page.getByRole('heading',{name:'ثبت شخص جدید'})
  }).last();
  await panel.waitFor();
  await panel.locator('input[placeholder="PERSON-001"]').fill('QA-PARTY-001');
  await panel.locator('input[required]:not([dir="ltr"])').fill('QA-PRIVATE-CUSTOMER-7022');
  await panel.getByRole('button',{name:'ثبت شخص',exact:true}).click();
}
async function review(page,decision){
  await navigate(page,'settings');
  await page.getByRole('button',{name:'اتصال به مدار'}).click();
  await page.getByRole('checkbox',{name:/ارجاع‌های مدار را دستی بررسی کنم/}).check();
  assert.equal((await state(page)).lists,0);
  await page.getByRole('button',{name:'بررسی وضعیت اتصال'}).click();
  await page.getByText('QA-PRIVATE-INVOICE-438927').waitFor();
  await page.getByRole('button',{name:decision,exact:true}).click();
  assert.deepEqual((await state(page)).reviews,[],'review requires second confirmation');
  await page.getByRole('button',{name:'تأیید تصمیم'}).click();
}

test('real-current Taraz help + Sileo host synthetic Chromium QA; one browser, no network',async t=>{
  const assets=await build();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(async()=>browser.close());

  await t.test('actual dashboard/invoice/reports help switch with tab; RTL, Escape and focus',async()=>{
    const {page,context}=await pageFor(browser,assets);
    try{
      await page.locator('.taraz-vt-primary [data-accounting-tab="overview"]').waitFor();
      const home=await openGuide(page,'overview');
      assert.match(home.join(' '),/دفتر/);
      await page.keyboard.press('Escape');
      await dialog(page).waitFor({state:'detached'});
      assert.equal(await page.locator('.taraz-context-help-trigger')
        .evaluate(el=>el===document.activeElement),true);
      await navigate(page,'invoice');
      const invoice=await openGuide(page,'invoice');
      assert.match(invoice.join(' '),/پیش‌نویس/);
      // Actual native Chromium pointer click, NOT force:true or DOM .click().
      // The pre-fix invoice stacking context intercepted these pointer events.
      assert.equal(await dialog(page).locator(
        '[data-taraz-context-help-portal]').count(),0);
      assert.equal(await page.locator(
        'body > .taraz-context-help-layer[data-taraz-context-help-portal="true"]')
        .count(),1,'help modal must escape work-mode stacking context');
      await page.getByRole('button',{name:'بستن راهنما'}).click();
      await dialog(page).waitFor({state:'detached'});
      assert.equal(await page.locator('.taraz-context-help-trigger')
        .evaluate(el=>el===document.activeElement),true,
      'pointer-close must restore focus to same real help trigger');
      await navigate(page,'reports');
      const reports=await openGuide(page,'reports');
      assert.match(reports.join(' '),/گزارش/);
      assert.notDeepEqual(invoice,reports);
      assert.equal(await toast(page).count(),0,'navigation/help must not emit a toast');
      assert.deepEqual((await state(page)).commands,[]);
    }finally{await context.close();}
  });

  await t.test('only validated synthetic host ACK after manual party submit shows safe toast',async()=>{
    const {page,context}=await pageFor(browser,assets);
    try{
      assert.deepEqual((await state(page)).commands,[]);
      await submitParty(page);
      await page.getByText('طرف‌حساب در دفتر میزبان ثبت شد.').waitFor();
      const calls=(await state(page)).commands;
      assert.equal(calls.length,1);
      assert.equal(calls[0].type,'party.register');
      assert.equal(calls[0].expectedRevision,0);
      const message=await toast(page).innerText();
      safeToast(message);
      assert.match(message,/طرف‌حساب در دفتر میزبان ثبت شد/);
    }finally{await context.close();}
  });

  for(const mode of ['uncertain','error']){
    await t.test('host '+mode+' never creates success toast/auto retry',async()=>{
      const {page,context}=await pageFor(browser,assets,mode);
      try{
        await submitParty(page);
        await page.getByText(/نتیجه عملیات نامشخص است؛ پیش از تکرار همان شناسه را بازیابی کنید/).waitFor();
        const message=await toast(page).innerText();
        safeToast(message);
        assert.match(message,/نتیجه عملیات نامشخص است/);
        assert.ok(!message.includes('طرف‌حساب در دفتر میزبان ثبت شد.'));
        const visibleError=await page.locator('.sac-alert.error').allTextContents();
        const content=visibleError.join(' ');
        assert.match(content,mode==='error'?
          /نتیجه فرمان در میزبان نامشخص است/:/نسخهٔ دفتر پس از فرمان پیش نرفت/);
        for(const secret of secrets)assert.ok(!content.includes(secret),
          'raw host exception leaked in in-page accounting alert');
        assert.equal((await state(page)).commands.length,1);
        assert.equal(await page.getByRole('button',{name:'بازیابی با همان شناسه عملیات'}).count(),1);
      }finally{await context.close();}
    });
  }

  await t.test('manual nonfinancial Madar review ACK shows no fake finance receipt or command',async()=>{
    const {page,context}=await pageFor(browser,assets);
    try{
      await review(page,'بررسی شد');
      await page.getByText('وضعیت ارجاع در صندوق محلی ثبت شد؛ سند مالی ایجاد نشده است.').waitFor();
      safeToast(await toast(page).innerText());
      assert.equal((await state(page)).reviews.length,1);
      assert.deepEqual((await state(page)).commands,[]);
    }finally{await context.close();}
  });

  for(const mode of ['review-error','review-wrong-id']){
    await t.test('Madar '+mode+' denies success toast and finance posting',async()=>{
      const {page,context}=await pageFor(browser,assets,mode);
      try{
        await review(page,'رد ارجاع');
        if(mode==='review-error')
          await page.getByText('تأیید وضعیت ارجاع ممکن نشد. صفحه اتصال را بررسی کنید.').waitFor();
        else
          await page.locator('.taraz-settings-message.error').waitFor();
        if(mode==='review-error'){
          const message=await toast(page).innerText();
          safeToast(message);
          assert.match(message,/تأیید وضعیت ارجاع ممکن نشد/);
        }else{
          assert.equal(await toast(page).count(),0,
            'bad reviewed-record ID must not create a green success toast');
        }
        const message=await toast(page).count()?await toast(page).innerText():'';
        assert.ok(!message.includes('وضعیت ارجاع در صندوق محلی ثبت شد'));
        assert.deepEqual((await state(page)).commands,[]);
      }finally{await context.close();}
    });
  }
});
