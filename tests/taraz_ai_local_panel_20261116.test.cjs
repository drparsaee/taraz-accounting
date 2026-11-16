'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const esbuild=require('esbuild');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
  'AppData','Roaming','npm','node_modules','playwright'));}
const project=path.resolve(__dirname,'..');

test('local model panel only invokes manual text inference and never financial commands',async t=>{
  const entry=`import React from 'react';
import {createRoot} from 'react-dom/client';
import TarazAiLocalPanel from './src/taraz_ai_local_panel.jsx';
window.__statusCalls=0;window.__localRequests=[];window.__financialCalls=0;
const api={
  tarazAiLocalStatus:async()=>{window.__statusCalls++;return {
    available:true,provider:'ollama',models:[{name:'qwen3:0.6b',bytes:522000000}],
    modelRan:false,financialActionsEnabled:false,qualityVerified:false};},
  tarazAiLocalGenerate:async payload=>{window.__localRequests.push(payload);
    return {provider:'ollama',modelRan:true,response:'پاسخ واقعی آزمایشی',
      journalPosted:false,financialActionsEnabled:false};},
  standaloneAccountingCommand:async()=>{window.__financialCalls++;},
};
createRoot(document.getElementById('root')).render(
  <TarazAiLocalPanel api={api} canEdit={true}/>);
`;
  const output=(await esbuild.build({stdin:{contents:entry,resolveDir:project,
    sourcefile:'local-model-qa.jsx',loader:'jsx'},
    bundle:true,write:false,platform:'browser',format:'iife',
    outdir:'local-model-qa',logLevel:'silent',charset:'utf8',
    loader:{'.css':'css','.png':'dataurl','.svg':'dataurl'}})).outputFiles;
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage();
  await page.setContent('<html lang="fa" dir="rtl"><div id="root"></div></html>');
  await page.addScriptTag({content:output.find(f=>f.path.endsWith('.js')).text});
  await page.locator('summary').click();
  await page.waitForFunction(()=>document.querySelector('select')?.value==='qwen3:0.6b');
  assert.deepEqual(await page.evaluate(()=>window.__localRequests),[]);
  await page.getByLabel('درخواست متنی فارسی').fill('سلام');
  await page.getByRole('button',{name:'ارسال به مدل محلی'}).click();
  await page.getByText('پاسخ واقعی آزمایشی').waitFor();
  const result=await page.evaluate(()=>({
    requests:window.__localRequests,financial:window.__financialCalls}));
  assert.equal(result.requests.length,1);
  assert.deepEqual(result.requests[0],{
    model:'qwen3:0.6b',prompt:'سلام',manualConsent:true});
  assert.equal(result.financial,0);
});
