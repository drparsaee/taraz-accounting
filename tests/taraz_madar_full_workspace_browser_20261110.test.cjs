'use strict';

/**
 * Full current-source Taraz accounting workspace in synthetic Chromium.
 * A manually selected Madar inbox item becomes an IN-MEMORY invoice text
 * suggestion, with no account/party/price or accounting API mutation.
 * No installed EXE, profile, LAN or financial ledger is accessed.
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
catch{playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
  'AppData','Roaming','npm','node_modules','playwright'));}

async function buildFixture(){
  const body=`import React from 'react';
import {createRoot} from 'react-dom/client';
import {StandaloneAccountingWorkspace} from './src/standalone_accounting_workspace.jsx';
window.__accountingCommands=[];
window.__inboxReads=[];
const item={schema:1,source:'madar',id:'c'.repeat(32),
 taskId:'synthetic-task',projectId:'synthetic-project',title:'QA packaging service offer',
 amountRial:99887766,partyId:'foreign-customer',accountId:'1100',
 tax:'999',currency:'TOMAN'};
const view={currency:'RIAL',journals:[],accounts:{},parties:{},items:{},
 invoices:{},bills:{},receipts:{},payments:{},proformas:{},taxRules:{},
 contractorJobs:{},returns:{},cashAccounts:{},companyProfile:{legalName:'Synthetic QA Company'},
 closedThrough:null,sequence:{invoice:0,bill:0}};
const api={
 standaloneAccountingRead:async()=>({revision:0,view,
  capabilities:{canManage:true,canDraft:true,canAdmin:true},
  currentUser:{username:'synthetic-admin',role:'admin',jobTitle:''}}),
 standaloneAccountingCommand:async value=>{
   window.__accountingCommands.push(value);
   throw Error('Unexpected finance mutation in draft-only test');
 },
 tarazIntegrationList:async()=>{
   window.__inboxReads.push('list');
   return {connected:true,requests:[item],invalidCount:0};
 },
 tarazIntegrationReview:async()=>{
   throw Error('Unexpected review side effect');
 },
};
createRoot(document.getElementById('root')).render(
 <StandaloneAccountingWorkspace api={api} canManage={true}
   canDraft={true} canAdmin={true}/>);
`;
  const built=(await esbuild.build({
    stdin:{contents:body,resolveDir:root,sourcefile:'full-taraz-mtr-qa.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',write:false,
    outdir:'full-taraz-mtr-in-memory',charset:'utf8',logLevel:'silent',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'},
    plugins:[{name:'known-local-dependencies',setup(build){
      build.onResolve({filter:/^(react|react-dom\/client|react\/jsx-runtime|lucide-react)$/},
        args=>({path:require.resolve(args.path,{paths:[modules]})}));
    }}],
  })).outputFiles;
  return {js:built.find(f=>f.path.endsWith('.js')).text,
    css:built.find(f=>f.path.endsWith('.css'))?.text||''};
}

test('real full Taraz UI turns manual Madar review item into text-only unsaved invoice draft',async(t)=>{
  const assets=await buildFixture();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1400,height:1000}});
  await page.setContent('<html dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:assets.js});
  const settings=page.locator('.taraz-vt-dock [data-accounting-tab="settings"]');
  await settings.click();
  await page.getByRole('button',{name:'اتصال به مدار'}).click();
  await page.getByRole('checkbox',{name:/ارجاع‌های مدار را دستی بررسی کنم/}).check();
  assert.deepEqual(await page.evaluate(()=>window.__inboxReads),[]);
  await page.getByRole('button',{name:'بررسی وضعیت اتصال'}).click();
  await page.getByText('QA packaging service offer').waitFor();
  await page.getByRole('button',{name:'آماده‌سازی پیش‌نویس فروش'}).click();
  await page.locator('.sac-invoice-editor').waitFor();
  const observed=await page.evaluate(()=>{
    const editor=document.querySelector('.sac-invoice-editor');
    const values=[...editor.querySelectorAll('input,textarea,select')]
      .map(field=>({type:field.tagName,label:field.getAttribute('aria-label')||'',
                   value:field.value||''}));
    return {values,commands:window.__accountingCommands,
      inboxReads:window.__inboxReads,
      bodyText:editor.textContent||''};
  });
  assert.ok(observed.values.some(field=>field.value==='QA packaging service offer'),
    'only the exact Madar title should populate a draft row');
  assert.ok(observed.values.some(field=>field.value===''),
    'party and price are not automatically selected');
  for(const forbidden of ['99887766','foreign-customer']){
    assert.ok(!observed.values.some(field=>field.value.includes(forbidden)),
      'unverified finance input was not copied: '+forbidden);
  }
  assert.deepEqual(observed.commands,[],'no finance command may run during prefilling');
  assert.deepEqual(observed.inboxReads,['list']);
});
