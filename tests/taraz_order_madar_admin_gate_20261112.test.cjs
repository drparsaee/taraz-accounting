'use strict';
/** Read-only UI authorization regression; synthetic browser host, no Taraz data. */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const esbuild=require('esbuild');
const root=path.resolve(__dirname,'..');

test('non-admin order editor cannot display or trigger the privileged Madar project picker',async()=>{
  let playwright;
  try{playwright=require('playwright');}
  catch{playwright=require(path.join(process.env.APPDATA||'', 'npm','node_modules','playwright'));}
  const script=[
    "import React from 'react';",
    "import {createRoot} from 'react-dom/client';",
    "import Order from './src/taraz_order_workspace.jsx';",
    'window.qa={reads:0};',
    'window.api={tarazOrderList:async()=>({orders:[],total:0}),',
    'tarazOrderCommand:async()=>{throw Error("NOT_EXPECTED");},',
    'tarazMadarDataRead:async()=>{window.qa.reads++;throw Error("NO_PERMISSION");}};',
    "createRoot(document.getElementById('root')).render(<Order api={window.api} canEdit={true} canAdmin={false} currency='RIAL'/>);",
  ].join('\n');
  const compiled=await esbuild.build({stdin:{contents:script,resolveDir:root,
    sourcefile:'taraz-admin-gate.jsx',loader:'jsx'},bundle:true,
    platform:'browser',format:'iife',write:false,outdir:'synthetic-output',logLevel:'silent'});
  const js=compiled.outputFiles.find(f=>f.path.endsWith('.js')).text;
  const css=compiled.outputFiles.find(f=>f.path.endsWith('.css'))?.text||'';
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  try{
    const page=await browser.newPage();
    const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',route=>route.request().url()==='https://taraz-no-admin.invalid/'?
      route.fulfill({status:200,contentType:'text/html',body:
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>'+css+
        '</style></head><body><div id="root"></div><script>'+js+'</script></body></html>'}):route.abort());
    await page.goto('https://taraz-no-admin.invalid/');
    await page.getByRole('heading',{name:'سفارش‌ها',exact:true}).waitFor();
    await page.getByRole('button',{name:'حرفه‌ای'}).click();
    assert.equal(await page.getByRole('region',{name:'انتخاب پروژه واقعی مدار'}).count(),0);
    assert.equal(await page.getByRole('textbox',{name:/ارجاع پروژه مرتبط/}).count(),1,
      'non-admin should still be allowed to type a manual project reference');
    assert.equal(await page.evaluate(()=>window.qa.reads),0);
    assert.deepEqual(errors,[]);
  }finally{await browser.close();}
});
