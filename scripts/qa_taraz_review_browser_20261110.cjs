'use strict';

/**
 * Taraz's REAL current JSX review UI with a synthetic in-memory API fixture.
 * Reads ONE JSON request from stdin; no local profile, HTTP or ledger reads.
 * Returns the verified manual click intent, NOT a Taraz finance receipt.
 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const project=path.resolve(__dirname,'..');
const madarNodeModules=path.resolve(project,'..','..','000- Madar',
  'madar-p2-gantt-notifications-20261107','node_modules');
const esbuild=require(path.join(madarNodeModules,'esbuild'));
let playwright;
try{playwright=require(path.join(madarNodeModules,'playwright'));}
catch{
  playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
    'AppData','Roaming','npm','node_modules','playwright'));
}

function validateRequest(value){
  if(!value||typeof value!=='object'||Array.isArray(value)||
     value.schema!==1||value.source!=='madar'||
     typeof value.id!=='string'||!/^[0-9a-f]{32}$/.test(value.id)||
     typeof value.taskId!=='string'||!value.taskId||value.taskId.length>180||
     typeof value.projectId!=='string'||!value.projectId||value.projectId.length>180||
     typeof value.title!=='string'||!value.title.trim()||value.title.length>300){
    throw Error('Synthetic Taraz UI request does not match schema-1 metadata');
  }
  return value;
}

async function buildSource(){
  const entry=`import React from 'react';
import {createRoot} from 'react-dom/client';
import TarazSettings from './src/taraz_settings.jsx';
window.__tarazManualReviewCalls=[];
window.__tarazInboxReads=0;
let pending=[window.__tarazQaRequest];
const api={
 tarazIntegrationList:async()=>{
   window.__tarazInboxReads++;
   return {connected:true,requests:pending,invalidCount:0};
 },
 tarazIntegrationReview:async(id,decision)=>{
   window.__tarazManualReviewCalls.push({id,decision});
   pending=pending.filter(item=>item.id!==id);
   return {id,state:decision,financialEventCreated:false};
 },
};
createRoot(document.getElementById('root')).render(
 <TarazSettings api={api} canManage={true} canDraft={true}/>);
`;
  const built=(await esbuild.build({
    stdin:{contents:entry,resolveDir:project,sourcefile:'mtr-taraz-review-qa.jsx',loader:'jsx'},
    platform:'browser',format:'iife',bundle:true,write:false,
    outdir:'mtr-taraz-review-qa-browser',logLevel:'silent',charset:'utf8',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'},
    plugins:[{name:'known-react-dependencies',setup(build){
      build.onResolve({filter:/^(react|react-dom\/client|react\/jsx-runtime|lucide-react)$/},
        args=>({path:require.resolve(args.path,{paths:[madarNodeModules]})}));
    }}],
  })).outputFiles;
  return {js:built.find(item=>item.path.endsWith('.js')).text,
    css:built.find(item=>item.path.endsWith('.css'))?.text||''};
}

async function run(syntheticProposal,decision='reviewed'){
  const payload=validateRequest(syntheticProposal);
  if(decision!=='reviewed'&&decision!=='rejected')
    throw Error('Only an explicit metadata review/rejection is permitted');
  const assets=await buildSource();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    await page.setContent('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><main id="root"></main></body></html>');
    if(assets.css)await page.addStyleTag({content:assets.css});
    await page.evaluate(value=>{window.__tarazQaRequest=value;},payload);
    await page.addScriptTag({content:assets.js});
    await page.getByRole('button',{name:'اتصال به مدار'}).click();
    await page.getByRole('checkbox',{name:/ارجاع‌های مدار را دستی بررسی کنم/}).check();
    const before=await page.evaluate(()=>window.__tarazInboxReads);
    assert.equal(before,0,'Taraz must not read inbox automatically');
    await page.getByRole('button',{name:'بررسی وضعیت اتصال'}).click();
    await page.getByText(payload.title).waitFor();
    await page.getByRole('button',{name:decision==='reviewed'?'بررسی شد':'رد ارجاع'}).click();
    assert.deepEqual(await page.evaluate(()=>window.__tarazManualReviewCalls),[],
      'Review needs explicit second confirmation');
    await page.getByRole('button',{name:'تأیید تصمیم'}).click();
    await page.getByText('ارجاع در صندوق اتصال بررسی شد. هیچ سند مالی ایجاد نشد.').waitFor();
    const result=await page.evaluate(()=>({
      calls:window.__tarazManualReviewCalls,
      reads:window.__tarazInboxReads,
    }));
    assert.deepEqual(result.calls,[{id:payload.id,decision}]);
    assert.equal(result.reads,2,'One manual read and one post-confirm refresh');
    assert.equal(await page.getByText(payload.title).count(),0);
    return {sourceTarazBrowserManualReviewClicked:true,
      proposalId:payload.id,decision,
      explicitUserClickAndConfirmation:true,automaticInboxReads:before,
      subsequentManualAndPostReviewReads:result.reads,
      officialTarazReceiptVerified:false,financialEventCreated:false,
      installedTarazExecutableLaunched:false};
  }finally{
    await browser.close();
  }
}

if(require.main===module){
  (async()=>{
    if(process.argv.length>3||
       (process.argv.length===3&&process.argv[2]!=='--reject'))
      throw Error('Usage: node qa_taraz_review_browser_20261110.cjs [--reject]');
    const raw=fs.readFileSync(0,'utf8');
    if(raw.length>32768)throw Error('Synthetic UI request exceeds file bound');
    const result=await run(JSON.parse(raw),process.argv[2]==='--reject'?'rejected':'reviewed');
    process.stdout.write(JSON.stringify(result)+'\n');
  })().catch(error=>{
    process.stderr.write(String(error?.stack||error).slice(0,1500)+'\n');
    process.exitCode=1;
  });
}

module.exports={run,validateRequest};
