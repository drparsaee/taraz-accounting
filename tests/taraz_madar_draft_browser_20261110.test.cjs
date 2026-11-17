'use strict';

/** Real React/Chromium UI events, synthetic Taraz API only; no ledger or network. */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');

const madarNodeModules=path.resolve(__dirname,'..','..','..','000- Madar',
  'madar-p2-gantt-notifications-20261107','node_modules');
const esbuild=require(path.join(madarNodeModules,'esbuild'));
const root=path.resolve(__dirname,'..');
let playwright;
try{playwright=require(path.join(madarNodeModules,'playwright'));}
catch{
  playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
    'AppData','Roaming','npm','node_modules','playwright'));
}

const fixture=`import React from 'react';
import {createRoot} from 'react-dom/client';
import TarazSettings from './src/taraz_settings.jsx';
window.__mtrDrafts=[];
window.__mtrApiCalls=[];
const item={schema:1,source:'madar',id:'b'.repeat(32),
 taskId:'synthetic-task',projectId:'synthetic-project',title:'QA-only packaging order',
 amountRial:999999999,partyId:'untrusted-party'};
const api={
 tarazIntegrationList:async()=>{window.__mtrApiCalls.push('list');
   return {connected:true,requests:[item],invalidCount:0};},
 tarazIntegrationReview:async()=>{throw Error('Unexpected financial/review action');},
};
const params=new URLSearchParams(location.search);
const allowed=params.get('draft')!=='no';
createRoot(document.getElementById('root')).render(
 <TarazSettings api={api} canDraft={allowed} canManage={allowed}
  onDraftFromMadar={entry=>{window.__mtrDrafts.push(entry)}}/>);
`;

async function buildFixture(){
  const output=(await esbuild.build({
    stdin:{contents:fixture,resolveDir:root,sourcefile:'mtr-taraz-qa.jsx',loader:'jsx'},
    platform:'browser',format:'iife',bundle:true,write:false,
    logLevel:'silent',outdir:'mtr-taraz-qa-browser',charset:'utf8',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'},
    plugins:[{name:'local-known-react',setup(build){
      build.onResolve({filter:/^(react|react-dom\/client|react\/jsx-runtime|lucide-react)$/},
        args=>({path:require.resolve(args.path,{paths:[madarNodeModules]})}));
    }}],
  })).outputFiles;
  return {js:output.find(file=>file.path.endsWith('.js')).text,
    css:output.find(file=>file.path.endsWith('.css'))?.text||''};
}

test('Taraz incoming synthetic Madar request can be manually chosen as *draft*, no posting',async(t)=>{
  const assets=await buildFixture();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  await page.goto('about:blank?draft=yes');
  await page.setContent('<!doctype html><html dir="rtl" lang="fa"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:assets.js});
  await page.getByRole('button',{name:'اتصال به مدار'}).click();
  await page.getByRole('checkbox',{name:/ارجاع‌های مدار را دستی بررسی کنم/}).check();
  assert.deepEqual(await page.evaluate(()=>window.__mtrApiCalls),[]);
  await page.getByRole('button',{name:'بررسی وضعیت اتصال'}).click();
  await page.getByText('QA-only packaging order').waitFor();
  assert.equal(await page.getByRole('button',{name:'آماده‌سازی پیش‌نویس فروش'}).count(),1);
  await page.getByRole('button',{name:'آماده‌سازی پیش‌نویس فروش'}).click();
  const values=await page.evaluate(()=>({drafts:window.__mtrDrafts,calls:window.__mtrApiCalls}));
  assert.equal(values.drafts.length,1);
  assert.equal(values.drafts[0].id,'b'.repeat(32));
  assert.deepEqual(values.calls,['list']);
  assert.equal(await page.getByRole('button',{name:'تأیید تصمیم'}).count(),0);
});

test('Taraz non-draft role sees incoming request but cannot trigger invoice draft',async(t)=>{
  const assets=await buildFixture();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1000,height:800}});
  await page.goto('about:blank?draft=no');
  await page.setContent('<!doctype html><html dir="rtl" lang="fa"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  await page.addScriptTag({content:assets.js});
  await page.getByRole('button',{name:'اتصال به مدار'}).click();
  await page.getByRole('checkbox',{name:/ارجاع‌های مدار را دستی بررسی کنم/}).check();
  await page.getByRole('button',{name:'بررسی وضعیت اتصال'}).click();
  await page.getByText('QA-only packaging order').waitFor();
  assert.equal(await page.getByRole('button',{name:'آماده‌سازی پیش‌نویس فروش'}).count(),0);
  assert.deepEqual(await page.evaluate(()=>window.__mtrDrafts),[]);
});
