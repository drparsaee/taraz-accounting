'use strict';
/** Source regression only. This does not claim the installed frozen EXE was rebuilt. */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const esbuild=require('esbuild');
let playwright;
try {playwright=require('playwright');}
catch {playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
  'AppData','Roaming','npm','node_modules','playwright'));}
const root=path.resolve(__dirname,'..');

test('verified fresh company has real zero counters; never calls old Parsian API',async t=>{
  const entry=`import React from 'react';
import {createRoot} from 'react-dom/client';
import TarazHomeCommand from './src/taraz_home_command.jsx';
const root=createRoot(document.getElementById('root'));
const base={currency:'RIAL',journals:[],invoices:{},bills:{},accounts:{},
  parties:{},receipts:{},payments:{},items:{},companyWorkspaceId:'a'.repeat(32)};
window.__oldApiCalls=0;
const api={standaloneAccountingParsianHistory:async()=>{
  window.__oldApiCalls+=1;throw Error('Unverified personal accounting ledger');
}};
window.__render=(fresh)=>{
  root.render(<TarazHomeCommand api={api} view={{...base,
    ...(fresh?{freshWindowsWorkspace:true}:{})}} referenceDate="2026-11-16"/>);
};
window.__render(true);`;
  const output=(await esbuild.build({
    stdin:{contents:entry,resolveDir:root,sourcefile:'fresh-home-qa.jsx',loader:'jsx'},
    bundle:true,write:false,platform:'browser',format:'iife',outdir:'fresh-home-qa',
    logLevel:'silent',charset:'utf8',loader:{'.css':'css','.png':'dataurl','.svg':'dataurl'},
  })).outputFiles;
  const script=output.find(x=>x.path.endsWith('.js')).text;
  const style=output.find(x=>x.path.endsWith('.css'))?.text;
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1360,height:900}});
  const errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.setContent('<html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(style)await page.addStyleTag({content:style});
  await page.addScriptTag({content:script});
  await page.getByText('منبع: دفتر مستقل جدید تراز',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>window.__oldApiCalls),0);
  assert.equal(await page.getByText('دریافت سوابق تاریخی ناموفق بود.').count(),0);
  const values=await page.locator('.tdh-stat-number').allTextContents();
  assert.equal(values.length,4);
  assert.deepEqual(values,['۰','۰','۰','۰']);
  await page.evaluate(()=>window.__render(false));
  await page.getByText(/Unverified personal accounting ledger/).waitFor();
  assert.equal(await page.evaluate(()=>window.__oldApiCalls),1);
  assert.deepEqual(errors,[]);
});
