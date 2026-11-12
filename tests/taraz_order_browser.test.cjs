'use strict';
/** Browser proof in synthetic data only: no Windows profile, network or ledger. */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const esbuild=require('esbuild');
const root=path.resolve(__dirname,'..');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'','npm','node_modules','playwright'));}

async function content(){
  const source=[
    "import React from 'react';",
    "import {createRoot} from 'react-dom/client';",
    "import Orders from './src/taraz_order_workspace.jsx';",
    "window.calls=[];window.saved=[];window.failWrite=false;",
    "window.api={",
    "tarazOrderList:async()=>({orders:window.saved.map(order=>({...order})),total:window.saved.length,financialEventCreated:false}),",
    "tarazOrderCommand:async req=>{",
    "window.calls.push(req);if(window.failWrite)throw Error('SECRET-PRIVATE-ERROR-321');",
    "let out;if(req.action==='create'){",
    "out={id:String(window.saved.length+1).padStart(32,'0'),...req.data,status:'draft',revision:1,",
    "financialEventCreated:false,estimatedSalesTotal:null,wasteQuantity:req.data.productionQuantity-req.data.quantity};",
    "window.saved.unshift(out);",
    "}else{",
    "out=window.saved.find(x=>x.id===req.orderId);",
    "if(!out||out.revision!==req.expectedRevision)throw Error('stale');",
    "out=req.action==='transition'?{...out,status:req.nextStatus,revision:out.revision+1}:",
    "{...out,...req.data,revision:out.revision+1};",
    "window.saved=window.saved.map(x=>x.id===out.id?out:x);",
    "}return out;}};",
    "createRoot(document.getElementById('root')).render(",
    "<Orders api={window.api} canEdit={true} canAdmin={true} currency='RIAL'/>);",
  ].join('\n');
  const output=await esbuild.build({stdin:{
    contents:source,resolveDir:root,sourcefile:'taraz-order-harness.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',outdir:'synthetic-output',
    write:false,logLevel:'silent'});
  const js=output.outputFiles.find(f=>f.path.endsWith('.js')).text;
  const css=output.outputFiles.find(f=>f.path.endsWith('.css'))?.text||'';
  return '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'+
    '<style>body{font-family:Tahoma;background:#f2f6f6;margin:0;padding:18px}'+css+
    '</style></head><body><div id="root"></div><script>'+js+'</script></body></html>';
}
async function start(){
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-sandbox','--disable-extensions']});
  try{
    const page=await browser.newPage();
    page.setDefaultTimeout(7000);
    const html=await content();
    await page.route('**/*',route=>route.request().url()==='https://taraz-orders-qa.invalid/'?
      route.fulfill({status:200,contentType:'text/html',body:html}):route.abort());
    await page.goto('https://taraz-orders-qa.invalid/');
    await page.getByRole('heading',{name:'سفارش‌ها',exact:true}).waitFor({timeout:5000});
    return {browser,page};
  }catch(error){await browser.close();throw error;}
}
async function fill(page){
  await page.getByRole('textbox',{name:'نام مشتری'}).fill('مشتری تست');
  await page.getByRole('textbox',{name:'شرح سفارش'}).fill('پاسپورت تبلیغاتی');
  await page.getByRole('textbox',{name:'تعداد سفارش'}).fill('۱۰۰');
  await page.getByRole('textbox',{name:'تعداد برنامه‌ریزی تولید'}).fill('۱۲۰');
}
test('real private Edge: beginner entry, order saved, human-approved, no finance',async()=>{
  const {browser,page}=await start();
  try{
    await page.getByRole('button',{name:'ذخیره سفارش'}).click();
    assert.equal(await page.evaluate(()=>window.calls.length),0);
    await fill(page);
    await page.getByRole('button',{name:'ذخیره سفارش'}).click();
    await page.getByText('سفارش در میزبان ذخیره شد. هیچ سند مالی ایجاد نشده است.').waitFor();
    const calls=await page.evaluate(()=>window.calls);
    assert.equal(calls.length,1);assert.equal(calls[0].action,'create');
    assert.equal(calls[0].data.quantity,100);
    assert.equal(calls[0].data.productionQuantity,120);
    assert.equal(calls[0].data.unitPrice,null);
    assert.equal(calls[0].manualConfirmation,false);
    const actions=await page.locator('.taraz-orders-card-actions button').allTextContents();
    if(!actions.some(x=>x.includes('تأیید سفارش'))){
      console.log('ORDER_BROWSER_DIAGNOSTIC',JSON.stringify({
        actions,saved:await page.evaluate(()=>window.saved),
        list:await page.locator('.taraz-orders-list').innerText(),
      }));
    }
    page.once('dialog',dialog=>dialog.accept());
    await page.getByRole('button',{name:'تأیید سفارش'}).click({timeout:3500});
    await page.getByText('وضعیت سفارش ثبت و دوباره از میزبان خوانده شد').waitFor();
    assert.equal(await page.evaluate(()=>window.calls[1].manualConfirmation),true);
    assert.equal(await page.evaluate(()=>window.saved[0].status),'approved');
  }finally{await browser.close();}
});
test('real private Edge: backend failure not exposed and no false success',async()=>{
  const {browser,page}=await start();
  try{
    await page.evaluate(()=>{window.failWrite=true;});
    await fill(page);
    await page.getByRole('button',{name:'ذخیره سفارش'}).click();
    await page.getByText('نتیجه ذخیره نامشخص است.').waitFor();
    assert.ok(!(await page.locator('body').innerText()).includes('SECRET-PRIVATE-ERROR-321'));
    assert.equal(await page.evaluate(()=>window.saved.length),0);
  }finally{await browser.close();}
});
