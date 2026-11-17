'use strict';

/**
 * P0 Taraz manual durable-review recovery: real current-source React/JSX
 * events in isolated headless Edge with an in-memory, nonfinancial mock API.
 *
 * NEVER loads a real Taraz EXE, user profile, LAN peer, SQLite store, or
 * accounting/financial API.  Compiles JSX in memory; browser is disposable.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');

const root=path.resolve(__dirname,'..');
const modules=path.resolve(root,'..','..','000- Madar',
  'madar-p2-gantt-notifications-20261107','node_modules');
const esbuild=require(path.join(modules,'esbuild'));
let playwright;
try{playwright=require(path.join(modules,'playwright'));}
catch{
  playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
    'AppData','Roaming','npm','node_modules','playwright'));
}
const ID='a'.repeat(32);

const fixture=String.raw`import React from 'react';
import {createRoot} from 'react-dom/client';
import TarazSettings from './src/taraz_settings.jsx';
const mode=window.__qaMode;
const record={id:'${ID}',taskId:'qa-task-001',title:'QA synthetic interrupted review',
  state:'reviewed',financialEventCreated:false};
const forged={...record,id:'not-a-valid-request-id',title:'FORGED-NEVER-RENDER'};
window.__qa={calls:[],recovered:false,requests:0};
const api={
  tarazIntegrationList:async()=>{
    window.__qa.calls.push(['list']);
    window.__qa.requests++;
    if(mode==='list-error')throw Error('Synthetic host list unavailable');
    return {connected:true,requests:[],invalidCount:0,recoveryInvalidCount:1,
      recoveryTruncated:false,recovery:mode==='missing-intent-list'||window.__qa.recovered
        ? []:[record,forged]};
  },
  tarazIntegrationReview:async()=>{
    window.__qa.calls.push(['review-forbidden']);
    throw Error('Review/redecision must never run in recovery test');
  },
  tarazIntegrationRecover:async(id,manual)=>{
    window.__qa.calls.push(['recover',id,manual]);
    if(mode==='missing-intent')throw Error('Synthetic durable intent missing on disk');
    if(mode==='stale-reply')return {id,state:'rejected',financialEventCreated:false};
    if(mode==='financial-reply')return {id,state:'reviewed',financialEventCreated:true};
    if(mode==='wrong-id')return {id:'b'.repeat(32),state:'reviewed',financialEventCreated:false};
    window.__qa.recovered=true;
    return {id,state:'reviewed',financialEventCreated:false};
  },
  standaloneAccountingRead:async()=>{
    window.__qa.calls.push(['finance-read-forbidden']);
    throw Error('Forbidden accounting read');
  },
  standaloneAccountingCommand:async()=>{
    window.__qa.calls.push(['finance-command-forbidden']);
    throw Error('Forbidden finance mutation');
  }
};
if(mode==='missing-list-api')delete api.tarazIntegrationList;
if(mode==='missing-recover-api')delete api.tarazIntegrationRecover;
const permitted=mode!=='viewer';
createRoot(document.getElementById('root')).render(
  <TarazSettings api={api} canManage={permitted} canAdmin={false}
    canDraft={false}/>);
`;

async function bundleCurrentSource(){
  const output=(await esbuild.build({
    stdin:{contents:fixture,resolveDir:root,sourcefile:'synthetic-taraz-recovery.jsx',
      loader:'jsx'},
    platform:'browser',format:'iife',bundle:true,write:false,
    outdir:'synthetic-taraz-recovery-in-memory',charset:'utf8',logLevel:'silent',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'},
    plugins:[{name:'only-known-local-modules',setup(build){
      build.onResolve({filter:/^(react|react-dom\/client|react\/jsx-runtime|lucide-react)$/},
        args=>({path:require.resolve(args.path,{paths:[modules]})}));
    }}],
  })).outputFiles;
  const js=output.find(file=>file.path.endsWith('.js'))?.text;
  assert.ok(js?.length>1000,'current Taraz settings React must compile');
  return {js,css:output.find(file=>file.path.endsWith('.css'))?.text||''};
}

async function freshPage(browser,assets,mode){
  const context=await browser.newContext({viewport:{width:1280,height:960},
    serviceWorkers:'block'});
  // The application runs on about:blank with all executable code in memory.
  // Deny any unexpected HTTP(S)/file request instead of reaching a real peer.
  await context.route('**/*',route=>route.abort('blockedbyclient'));
  const page=await context.newPage();
  await page.setContent(
    '<!doctype html><html dir="rtl" lang="fa"><head><meta charset="utf-8"></head>'+
    '<body><main id="root"></main></body></html>');
  await page.evaluate(m=>{window.__qaMode=m;},mode);
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:assets.js});
  await page.getByRole('button',{name:'اتصال به مدار'}).waitFor();
  return {page,context};
}

async function calls(page){
  return page.evaluate(()=>structuredClone(window.__qa.calls));
}

function recoveryButton(page){
  return page.getByRole('button',{name:'بازیابی دستی تصمیم ناتمام'});
}

async function openAndOptIn(page){
  await page.getByRole('button',{name:'اتصال به مدار'}).click();
  const consent=page.getByRole('checkbox',
    {name:/ارجاع‌های مدار را دستی بررسی کنم/});
  assert.equal(await consent.isChecked(),false,'default consent must be off');
  assert.deepEqual(await calls(page),[],'mount and tab navigation must not list');
  assert.equal(await recoveryButton(page).count(),0,
    'no unrequested recovery queue should be shown');
  await consent.check();
  assert.deepEqual(await calls(page),[],'opt-in alone must not list or recover');
  return page.getByRole('button',{name:'بررسی وضعیت اتصال'});
}

async function manualRefresh(page){
  const refresh=await openAndOptIn(page);
  assert.equal(await refresh.isEnabled(),true);
  await refresh.click();
  await page.getByText('QA synthetic interrupted review').waitFor();
  assert.deepEqual(await calls(page),[['list']],
    'only one explicit list after manual refresh');
  assert.equal(await page.getByText('FORGED-NEVER-RENDER').count(),0,
    'invalid non-durable entry cannot produce UI recovery action');
}

function forbiddenCalls(observed){
  assert.ok(observed.every(call=>!['finance-read-forbidden',
      'finance-command-forbidden','review-forbidden'].includes(call[0])),
    'neither finance APIs nor new review/redecision API may be invoked');
}

test('current Taraz React manual durable-review recovery UI: explicit two-click flow and fail-closed negatives',
  async t=>{
    const assets=await bundleCurrentSource();
    const browser=await playwright.chromium.launch({
      channel:'msedge',headless:true,
      args:['--no-first-run','--disable-background-networking'],
    });
    t.after(async()=>browser.close());

    await t.test('opt-in and manual refresh show only durable incomplete review; double confirmation recovers once',async()=>{
      const {page,context}=await freshPage(browser,assets,'normal');
      try{
        await manualRefresh(page);
        assert.equal(await recoveryButton(page).count(),1);
        assert.equal(await page.getByText('تصمیم ثبت‌شده اما ناتمام: بررسی شد').count(),1);
        assert.equal(await page.getByRole('button',{name:'بررسی شد'}).count(),0,
          'no new pending request/redecision UI must appear');
        await recoveryButton(page).click();
        assert.equal(await page.getByRole('group',{name:'تأیید تصمیم ارجاع'}).count(),1);
        assert.deepEqual(await calls(page),[['list']],
          'clicking recovery candidate only opens a second confirmation');
        await page.getByRole('button',{name:'تأیید تصمیم'}).click();
        await page.getByText('تصمیم قبلی از ثبت پایدار بازیابی شد. هیچ سند مالی ایجاد نشد.').waitFor();
        await page.getByText('QA synthetic interrupted review').waitFor({state:'detached'});
        const observed=await calls(page);
        assert.deepEqual(observed,[['list'],['recover',ID,true],['list']],
          'one manual recover with explicit true; one bounded post-success readback');
        assert.equal(await recoveryButton(page).count(),0);
        forbiddenCalls(observed);
      }finally{await context.close();}
    });

    await t.test('viewer sees decision but cannot initiate recovery or finance APIs',async()=>{
      const {page,context}=await freshPage(browser,assets,'viewer');
      try{
        await manualRefresh(page);
        assert.equal(await recoveryButton(page).count(),1);
        assert.equal(await recoveryButton(page).isDisabled(),true);
        await recoveryButton(page).click({force:true}).catch(()=>{});
        assert.deepEqual(await calls(page),[['list']]);
        assert.equal(await page.getByRole('button',{name:'تأیید تصمیم'}).count(),0);
      }finally{await context.close();}
    });

    await t.test('first recovery click then cancellation never calls native recover',async()=>{
      const {page,context}=await freshPage(browser,assets,'normal');
      try{
        await manualRefresh(page);
        await recoveryButton(page).click();
        assert.equal(await page.getByRole('group',{name:'تأیید تصمیم ارجاع'}).count(),1);
        assert.deepEqual(await calls(page),[['list']]);
        await page.getByRole('button',{name:'انصراف'}).click();
        assert.equal(await page.getByRole('group',{name:'تأیید تصمیم ارجاع'}).count(),0);
        assert.equal(await recoveryButton(page).count(),1);
        assert.deepEqual(await calls(page),[['list']]);
      }finally{await context.close();}
    });

    await t.test('missing recovery method disables action without fallback to review',async()=>{
      const {page,context}=await freshPage(browser,assets,'missing-recover-api');
      try{
        await manualRefresh(page);
        assert.equal(await recoveryButton(page).isDisabled(),true);
        assert.deepEqual(await calls(page),[['list']]);
      }finally{await context.close();}
    });

    await t.test('missing native list capability disables even the refresh',async()=>{
      const {page,context}=await freshPage(browser,assets,'missing-list-api');
      try{
        await page.getByRole('button',{name:'اتصال به مدار'}).click();
        await page.getByRole('checkbox',{name:/ارجاع‌های مدار را دستی بررسی کنم/}).check();
        assert.equal(await page.getByRole('button',{name:'بررسی وضعیت اتصال'}).isDisabled(),true);
        assert.equal(await recoveryButton(page).count(),0);
        assert.deepEqual(await calls(page),[]);
      }finally{await context.close();}
    });

    await t.test('missing durable intent in manual list produces no recovery action',async()=>{
      const {page,context}=await freshPage(browser,assets,'missing-intent-list');
      try{
        const refresh=await openAndOptIn(page);
        await refresh.click();
        await page.getByText(/بازیابی‌های نامعتبر یا متعارض/).waitFor();
        assert.equal(await recoveryButton(page).count(),0);
        assert.deepEqual(await calls(page),[['list']]);
      }finally{await context.close();}
    });

    for(const [mode,errorText] of [
      ['missing-intent','Synthetic durable intent missing on disk'],
      ['stale-reply','نتیجه بازیابی با تصمیم پایدار بدون ثبت مالی سازگار نیست.'],
      ['financial-reply','نتیجه بازیابی با تصمیم پایدار بدون ثبت مالی سازگار نیست.'],
      ['wrong-id','نتیجه بازیابی با تصمیم پایدار بدون ثبت مالی سازگار نیست.'],
    ]){
      await t.test(mode+' fails closed without duplicate recovery, redecision or financial mutation',async()=>{
        const {page,context}=await freshPage(browser,assets,mode);
        try{
          await manualRefresh(page);
          await recoveryButton(page).click();
          assert.deepEqual(await calls(page),[['list']],
            'must not recover without explicit second confirmation');
          await page.getByRole('button',{name:'تأیید تصمیم'}).click();
          await page.getByRole('alert').filter({hasText:errorText}).waitFor();
          const observed=await calls(page);
          assert.deepEqual(observed,[['list'],['recover',ID,true]],
            'one failed manual attempt must not trigger automatic retry/refresh');
          assert.equal(await recoveryButton(page).count(),1);
          forbiddenCalls(observed);
        }finally{await context.close();}
      });
    }

    await t.test('host list error remains error, with no auto recover',async()=>{
      const {page,context}=await freshPage(browser,assets,'list-error');
      try{
        const refresh=await openAndOptIn(page);
        await refresh.click();
        await page.getByRole('alert')
          .filter({hasText:'Synthetic host list unavailable'}).waitFor();
        assert.deepEqual(await calls(page),[['list']]);
        assert.equal(await recoveryButton(page).count(),0);
      }finally{await context.close();}
    });
  });
