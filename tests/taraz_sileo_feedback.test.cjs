'use strict';

/** Source-only UI toasts. No profile, network, installed EXE, company or ledger. */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const esbuild=require('esbuild');
const main=fs.readFileSync(path.join(root,'src/standalone_main.jsx'),'utf8');
const workspace=fs.readFileSync(path.join(root,'src/standalone_accounting_workspace.jsx'),'utf8');

function sourceModule(){
  const source=path.join(root,'src/taraz_sileo_feedback.jsx');
  const built=esbuild.buildSync({
    entryPoints:[source],bundle:true,platform:'node',format:'cjs',
    write:false,external:['react','react/jsx-runtime','sileo'],
    loader:{'.css':'empty'},logLevel:'silent',
  });
  const mod={exports:{}};
  const sourceRequire=require('node:module').createRequire(source);
  new Function('require','module','exports',built.outputFiles[0].text)(
    sourceRequire,mod,mod.exports);
  return mod.exports;
}

test('exactly one Toaster at actual accounting React root, not in sections or render loops',()=>{
  assert.equal((main.match(/<TarazSileoToaster\b/g)||[]).length,1);
  assert.equal((workspace.match(/<TarazSileoToaster\b/g)||[]).length,0);
  assert.match(main,/<TarazSileoToaster\s*\/>[\s\S]*<AccountingErrorBoundary>/);
  assert.match(workspace,/tarazIntegrationFeedbackApi\(api\)/);
  assert.match(workspace,/api=\{integrationFeedbackApi\}/);
});

test('UI messages have bounded whitelisted copy; a UI toast is never finance receipt',()=>{
  const {describeTarazFeedback}=sourceModule();
  const exposed=JSON.stringify({
    company:'PRIVATE-COMPANY-NAME',
    amount:'987654321',
    token:'SECRET-TOKEN',
    customer:'PRIVATE-CUSTOMER',
    journal:'J:SECRET',
  });
  const samples=[
    {kind:'commit',section:'invoice',commandType:'invoice.issue',
      payload:exposed},
    {kind:'commit',section:'bill',commandType:'bill.issue',
      payload:exposed},
    {kind:'commit',section:'settlements',commandType:'payment.record',
      payload:exposed},
    {kind:'commit',section:'company',commandType:'company.update',
      payload:exposed},
    {kind:'commit',section:'reports',commandType:'unknown-private-command',
      payload:exposed},
    {kind:'draft',section:'settings',payload:exposed},
    {kind:'review',section:'settings',payload:exposed},
    {kind:'requested',section:'reports',payload:exposed},
    {kind:'uncertain',section:'settlements',payload:exposed},
    {kind:'invalid',section:'invoice',payload:exposed},
  ];
  for(const event of samples){
    const outcome=describeTarazFeedback(event);
    assert.ok(['success','warning','error','info'].includes(outcome.level));
    assert.ok(outcome.title.length>0&&outcome.title.length<110);
    assert.ok(outcome.description.length>0&&outcome.description.length<110);
    const message=JSON.stringify(outcome);
    for(const secret of ['PRIVATE-COMPANY','987654321','SECRET-TOKEN',
                         'PRIVATE-CUSTOMER','J:SECRET']){
      assert.ok(!message.includes(secret),secret);
    }
    assert.doesNotMatch(message,/رسید رسمی (صادر|تأیید) شد/);
  }
  assert.match(describeTarazFeedback({kind:'commit',commandType:'invoice.issue'})
    .description,/رسید رسمی/);
  assert.match(describeTarazFeedback({kind:'draft'}).title,/هیچ سند مالی/);
  assert.match(describeTarazFeedback({kind:'uncertain'}).title,/نامشخص/);
});

test('scoped Taraz integration adapter only toasts verified manual metadata reply',async()=>{
  const {tarazIntegrationFeedbackApi}=sourceModule();
  const notifications=[];
  const id='a'.repeat(32),recoveryId='c'.repeat(32),wrong='b'.repeat(32);
  const state={calls:[],tamper:false,throwError:false};
  const api={
    tarazIntegrationList:async()=>({
      connected:true,requests:[],recovery:[
        {id:recoveryId,state:'reviewed',financialEventCreated:false},
      ],
    }),
    tarazIntegrationReview:async(request,decision)=>{
      state.calls.push(['review',request,decision]);
      if(state.throwError)throw Error('PRIVATE BACKEND FAILURE: secret');
      return {id:state.tamper?wrong:request,state:decision,financialEventCreated:false};
    },
    tarazIntegrationRecover:async(request,manual)=>{
      state.calls.push(['recover',request,manual]);
      if(state.throwError)throw Error('PRIVATE BACKEND FAILURE: secret');
      return {id:request,state:state.tamper?'rejected':'reviewed',
        financialEventCreated:false};
    },
    standaloneAccountingRead:async()=>({role:'no-action'}),
  };
  const scoped=tarazIntegrationFeedbackApi(api,event=>notifications.push(event));
  assert.equal(typeof scoped.standaloneAccountingRead,'function');
  assert.equal((await scoped.standaloneAccountingRead()).role,'no-action');
  await scoped.tarazIntegrationList();
  assert.equal(notifications.length,0,'list/read must never toast');
  await scoped.tarazIntegrationReview(id,'reviewed');
  assert.deepEqual(notifications,[{kind:'review',section:'settings'}]);
  state.tamper=true;
  await scoped.tarazIntegrationReview(id,'rejected');
  await scoped.tarazIntegrationRecover(recoveryId,true);
  assert.equal(notifications.length,1,'forged ID or stale decision must not toast');
  state.tamper=false;
  await scoped.tarazIntegrationRecover(recoveryId,true);
  assert.deepEqual(notifications[1],{kind:'recover',section:'settings'});
  state.throwError=true;
  await assert.rejects(scoped.tarazIntegrationReview(id,'reviewed'),/PRIVATE BACKEND FAILURE/);
  assert.deepEqual(notifications[2],{kind:'reviewError',section:'settings'});
  assert.ok(!JSON.stringify(notifications).includes('PRIVATE BACKEND FAILURE'));
});

test('ledger commits only notify after current backend response validation',()=>{
  const send=workspace.slice(workspace.indexOf('const send=async(command,'),
    workspace.indexOf('const retryUncertain=async'));
  assert.ok(send.indexOf('validateStandaloneResponse(payload)')>=0);
  assert.ok(send.indexOf('validateStandaloneResponse(payload)')<
    send.indexOf('if(result.revision<=attemptedRevision)'));
  assert.ok(send.indexOf('if(result.revision<=attemptedRevision)')<
    send.indexOf("tarazToast({kind:'commit'"));
  assert.match(send,/if\(result\.revision<=attemptedRevision\)\{[\s\S]*?pending\.current=command;[\s\S]*?setPendingRetry\(true\);[\s\S]*?return false;/);
  assert.match(send,/if\(live\.current\)tarazToast\(\{kind:conflict\?'conflict':'uncertain'/);
  assert.doesNotMatch(send,/tarazToast\(\{kind:'success'/);
  assert.match(workspace,/tarazToast\(\{kind:'requested',section:'reports'\}\)/);
  assert.match(workspace,/tarazToast\(\{kind:'draft',section:'settings'\}\)/);
});

test('toaster styles enforce RTL and media reduced-motion',()=>{
  const css=fs.readFileSync(path.join(root,'src/taraz_sileo_feedback.css'),'utf8');
  const jsx=fs.readFileSync(path.join(root,'src/taraz_sileo_feedback.jsx'),'utf8');
  assert.match(jsx,/dir="rtl"/);
  assert.match(jsx,/theme=\{theme\}/);
  assert.match(jsx,/MutationObserver/);
  assert.match(css,/direction:rtl/);
  assert.match(css,/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css,/animation:none !important/);
  assert.match(css,/transition:none !important/);
});

test('real Sileo 0.1.6 renders a single RTL toast for an explicit safe UI event',async t=>{
  let playwright;
  try{
    const madarModules=path.resolve(root,'..','..','000- Madar',
      'madar-p2-gantt-notifications-20261107','node_modules');
    playwright=require(path.join(madarModules,'playwright'));
  }catch{
    try{
      playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
        'AppData','Roaming','npm','node_modules','playwright'));
    }catch{t.skip('No local Playwright installation; static & API tests remain runnable');return;}
  }
  const fixture=String.raw`import React from 'react';
import {createRoot} from 'react-dom/client';
import {TarazSileoToaster,tarazToast} from './src/taraz_sileo_feedback.jsx';
createRoot(document.getElementById('root')).render(<>
  <TarazSileoToaster/>
  <button id="issue" onClick={()=>tarazToast({kind:'commit',
    commandType:'invoice.issue',section:'invoice',
    payload:{token:'LEAK-DO-NOT-RENDER'}})}>Synthetic confirmed host result</button>
  <button id="warning" onClick={()=>tarazToast({kind:'uncertain',
    section:'settlements',payload:{token:'LEAK-DO-NOT-RENDER'}})}>Synthetic uncertain result</button>
</>);`;
  const built=(await esbuild.build({
    stdin:{contents:fixture,resolveDir:root,sourcefile:'taraz-sileo-browser-qa.jsx',
      loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',write:false,
    outdir:'taraz-sileo-synthetic-in-memory',charset:'utf8',logLevel:'silent',
    loader:{'.css':'css'},
  })).outputFiles;
  const script=built.find(file=>file.path.endsWith('.js')).text;
  const styles=built.find(file=>file.path.endsWith('.css'))?.text||'';
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const context=await browser.newContext({viewport:{width:900,height:600},
    reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',route=>route.abort('blockedbyclient'));
  const page=await context.newPage();
  await page.setContent('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head>'+
    '<body><div id="root"></div></body></html>');
  if(styles)await page.addStyleTag({content:styles});
  await page.addScriptTag({content:script});
  await page.locator('#issue').click();
  await page.getByText('ثبت میزبان: صدور فاکتور (نه رسید اتصال)').waitFor();
  assert.equal(await page.locator('[data-sileo-viewport]').count(),1);
  assert.equal(await page.locator('[data-sileo-viewport]').evaluate(el=>
    el.closest('[dir="rtl"]')?.getAttribute('dir')),'rtl');
  assert.ok(!(await page.locator('[data-sileo-viewport]').innerText())
    .includes('LEAK-DO-NOT-RENDER'));
  await page.evaluate(()=>{document.documentElement.dataset.theme='dark';});
  await page.locator('[data-sileo-viewport][data-theme="dark"]').waitFor({timeout:4000});
  await page.evaluate(()=>{document.documentElement.dataset.theme='light';});
  await page.locator('[data-sileo-viewport][data-theme="light"]').waitFor({timeout:4000});
  const motion=await page.locator('[data-sileo-toast]').first().evaluate(el=>
    ({transition:getComputedStyle(el).transitionDuration,
      animation:getComputedStyle(el).animationDuration}));
  assert.ok(motion.transition.split(',').every(s=>['0s','0ms'].includes(s.trim())));
  await page.locator('#warning').click();
  await page.getByText(/نتیجه عملیات نامشخص است/).waitFor();
  assert.equal(await page.locator('[data-sileo-viewport]').count(),1);
  assert.ok(!(await page.locator('[data-sileo-viewport]').innerText())
    .includes('LEAK-DO-NOT-RENDER'));
  await context.close();
});

test('actual Taraz accounting root: same/stale ledger revisions and viewer never toast saved',async t=>{
  let playwright;
  try{
    const modules=path.resolve(root,'..','..','000- Madar',
      'madar-p2-gantt-notifications-20261107','node_modules');
    playwright=require(path.join(modules,'playwright'));
  }catch{
    try{
      playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
        'AppData','Roaming','npm','node_modules','playwright'));
    }catch{t.skip('Headless Edge / Playwright unavailable');return;}
  }
  const output=(await esbuild.build({
    entryPoints:[path.join(root,'src/standalone_main.jsx')],
    bundle:true,platform:'browser',format:'iife',write:false,
    outdir:'taraz-sileo-root-synthetic-only',charset:'utf8',
    logLevel:'silent',
    plugins:[{name:'synthetic-no-font-file-reads',setup(build){
      build.onResolve({filter:/^\/fonts\//},args=>({
        path:args.path,external:true,
      }));
    }}],
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl',
      '.svg':'dataurl','.woff2':'dataurl','.woff':'dataurl'},
  })).outputFiles;
  const script=output.find(file=>file.path.endsWith('.js')).text;
  const css=output.find(file=>file.path.endsWith('.css'))?.text||'';
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  async function scenario(mode){
    const context=await browser.newContext({viewport:{width:1350,height:950},
      serviceWorkers:'block',reducedMotion:'reduce'});
    await context.route('**/*',route=>route.abort('blockedbyclient'));
    const page=await context.newPage();
    const errors=[];
    page.on('pageerror',error=>errors.push(String(error.message).slice(0,200)));
    await page.setContent('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head>'+
      '<body><main id="root"></main></body></html>');
    await page.evaluate(chosen=>{
      // about:blank isn't a secure origin. Supply a fresh synthetic test-only
      // UUID API; the real app relies on the native secure WebView origin.
      Object.defineProperty(window.crypto,'randomUUID',{configurable:true,
        value:()=> '00000000-0000-4000-8000-'+Math.random().toString(16).slice(2).padEnd(12,'0')});
      const invoice={
        id:'INV-QA',partyId:'qa-party',documentDate:'2026-11-10',
        dueDate:'',status:'draft',total:1500,allocated:0,
        number:null,returnedAmount:0,discount:0,tax:0,
        lines:[{description:'SYNTHETIC',quantity:1,unitPrice:1500}],
      };
      const draftView={
        currency:'RIAL',journals:[],accounts:{},parties:{'qa-party':{id:'qa-party',
          name:'SYNTHETIC PARTY'}},items:{},invoices:{'INV-QA':invoice},
        bills:{},receipts:{},payments:{},proformas:{},taxRules:{},
        contractorJobs:{},returns:{},cashAccounts:{},sequence:{invoice:1,bill:0},
        companyProfile:{legalName:'SYNTHETIC ONLY'},closedThrough:null,
      };
      window.__qa={calls:[],mode:chosen};
      window.confirm=()=>true;
      const snapshot=(revision,view=draftView)=>({
        revision,view,
        capabilities:{canManage:chosen!=='viewer',canDraft:chosen!=='viewer',
          canAdmin:chosen!=='viewer'},
        currentUser:{username:'synthetic-user',
          role:chosen==='viewer'?'viewer':'admin',jobTitle:''},
      });
      window.madar={
        standaloneAccountingRead:async()=>snapshot(0),
        standaloneAccountingCommand:async envelope=>{
          window.__qa.calls.push(envelope);
          if(chosen==='conflict')throw new Error('revision conflict synthetic');
          if(chosen==='stale')return snapshot(-1);
          if(chosen==='same')return snapshot(0);
          return snapshot(1,{...draftView,invoices:{
            'INV-QA':{...invoice,status:'approved'}}});
        },
      };
    },mode);
    if(css)await page.addStyleTag({content:css});
    await page.addScriptTag({content:script});
    try{
      await page.locator('.taraz-vt-primary [data-accounting-tab="invoice"]')
        .click({timeout:6500});
    }catch(error){
      const body=await page.locator('body').innerText();
      throw new Error('Synthetic invoice navigation unavailable; errors='+
        JSON.stringify(errors)+'; body='+body.slice(0,350)+'; '+error.message.slice(0,140));
    }
    const action=page.locator('.sac-actions button').filter({hasText:/^تأیید$/}).first();
    if(mode==='viewer'){
      assert.equal(await action.count(),0,'viewer cannot issue finance command');
      assert.deepEqual(await page.evaluate(()=>window.__qa.calls),[]);
      assert.equal(await page.locator('[data-sileo-toast]').count(),0,
        'viewer must not receive an invented save toast');
      await context.close();
      return;
    }
    await action.waitFor({timeout:6500});
    await action.click();
    await page.waitForFunction(()=>window.__qa.calls.length===1,null,{timeout:6500});
    const actual=await page.evaluate(()=>window.__qa.calls);
    assert.equal(actual[0].command.type,'invoice.approve');
    assert.equal(actual[0].expectedRevision,0);
    if(mode==='success'){
      await page.getByText('تأیید فاکتور در دفتر میزبان ثبت شد.').waitFor();
      assert.equal(await page.locator('.sac-alert.error').count(),0);
    }else if(mode==='same'){
      await page.getByText(/نسخهٔ دفتر پس از فرمان پیش نرفت/).waitFor();
      await page.getByText(/نتیجه عملیات نامشخص است/).first().waitFor();
      assert.ok((await page.locator('.sac-alert.error').count())>=1);
      await page.getByRole('button',{name:/بازیابی با همان شناسه عملیات/}).waitFor();
    }else if(mode==='conflict'){
      await page.getByText(/تعارض نسخه دفتر رخ داد/).waitFor({timeout:6500});
      assert.equal(await page.getByText('revision conflict synthetic').count(),0,
        'backend exception details must not appear in the page');
      assert.ok(!(await page.locator('.sac-alert').allTextContents())
        .some(text=>text.includes('revision conflict synthetic')),
        'visible alerts must redact raw backend exception details');
      await page.getByText(/دادهٔ دفتر تغییر کرده است/).waitFor({timeout:6500});
    }else{
      await page.getByText(/نتیجه عملیات نامشخص است/).first().waitFor();
    }
    const titles=await page.locator('[data-sileo-title]').allTextContents();
    if(mode!=='success'){
      assert.ok(!titles.some(title=>title.includes('تأیید فاکتور در دفتر میزبان ثبت شد')),
        'unknown results must not be visually promoted to saved');
    }
    assert.equal(await page.locator('[data-sileo-viewport]').count(),1);
    assert.ok((await page.locator('[data-sileo-viewport]').innerText())
      .indexOf('SYNTHETIC PARTY')===-1);
    await context.close();
  }
  for(const mode of ['same','stale','conflict','viewer','success']){
    await t.test('synthetic accounting response '+mode,()=>scenario(mode));
  }
});
