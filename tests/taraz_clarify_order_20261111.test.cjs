'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const esbuild=require('esbuild');

const root=path.resolve(__dirname,'..');
const filename=path.join(root,'src/taraz_order_workspace.jsx');
const sourceRequire=require('node:module').createRequire(filename);
const artifact=esbuild.buildSync({entryPoints:[filename],bundle:true,
  platform:'node',format:'cjs',write:false,
  external:['react','react/jsx-runtime','lucide-react'],
  loader:{'.css':'empty'},logLevel:'silent'});
const mod={exports:{}};
new Function('require','module','exports',artifact.outputFiles[0].text)(
  sourceRequire,mod,mod.exports);
const {prepareTarazOrderDraft,orderProductionReview}=mod.exports;
const {extractLocalOrderHints}=require('../src/taraz_order_intake.js');

const fixture=()=>({
  kind:'sale',customerId:'',customerName:'نمونه',title:'جعبه مقوایی',
  description:'',unit:'عدد',quantity:'۱۰۰',productionQuantity:'۱۲۰',
  actualProducedQuantity:'',scrapQuantity:'',healthySurplusQuantity:'',
  projectReference:'P-12',scheduleStartDate:'2026-11-11',
  scheduleDueDate:'2026-11-18',procurementNotes:'',
  unitPrice:'',costStages:[],notes:'',
});

test('quantity conservation distinguishes planned, actual, scrap, healthy surplus',()=>{
  const form=fixture();
  assert.equal(orderProductionReview(form).state,'incomplete');
  assert.equal(prepareTarazOrderDraft(form).data.actualProducedQuantity,null);
  form.actualProducedQuantity='۱۲۰';
  form.scrapQuantity='۵';
  form.healthySurplusQuantity='۱۵';
  const result=prepareTarazOrderDraft(form);
  assert.equal(result.data.quantity,100);
  assert.equal(result.data.productionQuantity,120);
  assert.equal(result.data.actualProducedQuantity,120);
  assert.equal(result.data.scrapQuantity,5);
  assert.equal(result.data.healthySurplusQuantity,15);
  assert.equal(orderProductionReview(form).state,'balanced');
  form.healthySurplusQuantity='۰';
  assert.deepEqual({state:orderProductionReview(form).state,
    balance:orderProductionReview(form).balance},
    {state:'unallocated',balance:15});
  form.actualProducedQuantity='۵۰';
  form.scrapQuantity='۶۰';
  assert.match(prepareTarazOrderDraft(form).error,/ضایعات/);
});

test('missing costs, stage suppliers, project and scheduling are kept as actual unknowns',()=>{
  const form=fixture();
  form.costStages=[{kind:'print',supplier:'',description:'',estimatedCost:''}];
  assert.deepEqual(prepareTarazOrderDraft(form).data.costStages,[
    {kind:'print',supplier:'',description:'',estimatedCost:null}]);
  assert.equal(prepareTarazOrderDraft(form).data.projectReference,'P-12');
  form.scheduleDueDate='2026-02-30';
  assert.match(prepareTarazOrderDraft(form).error,/زمان‌بندی/);
});

test('offline rules read only explicitly stated measured numbers and flag conflicts',()=>{
  const hint=extractLocalOrderHints('مشتری: نمونه\nشرح سفارش: جعبه مقوایی\n'+
    'تعداد فروش: ۱۰۰ عدد\nتولید برنامه‌ای: ۱۲۰\n'+
    'تولید واقعی: ۱۲۰\nضایعات: ۵\nمازاد سالم: ۱۵\n'+
    'پروژه: P-12\nموعد تحویل: 2026-11-18\nچاپ، صحافی');
  assert.deepEqual([
    hint.fields.quantity,hint.fields.productionQuantity,hint.fields.actualProducedQuantity,
    hint.fields.scrapQuantity,hint.fields.healthySurplusQuantity],
    ['100','120','120','5','15']);
  assert.equal(hint.fields.projectReference,'P-12');
  assert.equal(hint.fields.scheduleDueDate,'2026-11-18');
  assert.equal(hint.manualReviewRequired,true);
  assert.equal(hint.externalModelCalled,false);
  assert.equal(hint.financialEventCreated,false);
  const productionOnly=extractLocalOrderHints('تولید: ۱۲۰ عدد');
  assert.equal(productionOnly.fields.quantity,'');
  assert.equal(productionOnly.fields.productionQuantity,'120');
  const conflict=extractLocalOrderHints('تعداد فروش: ۱۰۰\nتولید: ۹۰');
  assert.ok(conflict.warnings.some(x=>x.includes('کمتر')));
});

test('synthetic Edge: local-model suggestion is inspectable and never saves automatically',async()=>{
  let playwright;
  try{playwright=require('playwright');}
  catch{playwright=require(path.join(process.env.APPDATA||'','npm','node_modules','playwright'));}
  const source=[
    "import React from 'react';",
    "import {createRoot} from 'react-dom/client';",
    "import Orders from './src/taraz_order_workspace.jsx';",
    "window.calls=[];window.orders=[];window.modelCalls=0;",
    "const toOrder=(data,status,revision,id)=>{",
    "const complete=[data.actualProducedQuantity,data.scrapQuantity,data.healthySurplusQuantity].every(x=>x!==null);",
    "const balanced=complete&&data.actualProducedQuantity-data.scrapQuantity-data.healthySurplusQuantity===data.quantity;",
    "return {...data,id,status,revision,financialEventCreated:false,wasteQuantityIsLegacyEstimate:false,",
    "productionReconciliation:{state:balanced?'balanced':'incomplete'}};};",
    "window.api={",
    "tarazOrderList:async()=>({orders:window.orders.map(o=>({...o})),financialEventCreated:false}),",
    "tarazOrderSuggest:async()=>{window.modelCalls++;return {source:'LOCAL_OLLAMA',modelRan:true,externalModelCalled:false,financialEventCreated:false,",
    "fields:{customerName:'مشتری پیشنهادی',title:'کارت ویزیت',quantity:'100',productionQuantity:'120'},",
    "suggestedStages:['print'],warnings:['تعداد و مشخصات را تأیید کنید.']};},",
    "tarazOrderCommand:async r=>{window.calls.push(r);let next;",
    "if(r.action==='create'){next=toOrder(r.data,'draft',1,'0'.repeat(32));}",
    "else{const prev=window.orders.find(o=>o.id===r.orderId);",
    "next=r.action==='transition'?toOrder(prev,r.nextStatus,prev.revision+1,prev.id):",
    "toOrder(r.data,prev.status,prev.revision+1,prev.id);}",
    "window.orders=[next];return next;}};",
    "createRoot(document.getElementById('root')).render(<Orders api={window.api} canEdit={true} canAdmin={true} currency='RIAL'/>);",
  ].join('\n');
  const output=await esbuild.build({stdin:{contents:source,resolveDir:root,
      sourcefile:'taraz-clarify-browser-harness.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',outdir:'synthetic-output',
    write:false,logLevel:'silent'});
  const javascript=output.outputFiles.find(file=>file.path.endsWith('.js')).text;
  const stylesheet=output.outputFiles.find(file=>file.path.endsWith('.css'))?.text||'';
  const html='<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'+
    '<style>'+stylesheet+'</style></head><body><div id="root"></div><script>'+javascript+'</script></body></html>';
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-sandbox','--disable-extensions']});
  try{
    const page=await browser.newPage();
    page.setDefaultTimeout(9000);
    await page.route('**/*',route=>route.request().url()==='https://taraz-clarify-qa.invalid/'?
      route.fulfill({status:200,contentType:'text/html',body:html}):route.abort());
    await page.goto('https://taraz-clarify-qa.invalid/');
    await page.getByRole('heading',{name:'سفارش‌ها',exact:true}).waitFor();
    await page.getByRole('textbox',{name:'درخواست مشتری را بنویسید یا جای‌گذاری کنید'})
      .fill('چاپ ۱۰۰ عدد کارت ویزیت');
    await page.getByRole('button',{name:'پیشنهاد با مدل محلی'}).click();
    await page.getByText('پیشنهاد مدل محلی: همه موارد را با درخواست اصلی تطبیق دهید.').waitFor();
    assert.equal(await page.evaluate(()=>window.modelCalls),1);
    assert.equal(await page.evaluate(()=>window.calls.length),0);
    assert.equal(await page.getByRole('textbox',{name:'نام مشتری'}).inputValue(),'');
    await page.getByRole('button',{name:'اعمال پیشنهاد به فرم'}).click();
    assert.equal(await page.getByRole('textbox',{name:'نام مشتری'}).inputValue(),'مشتری پیشنهادی');
    assert.equal(await page.evaluate(()=>window.calls.length),0);
    await page.getByRole('button',{name:'ذخیره سفارش'}).click();
    await page.getByText('سفارش در میزبان ذخیره شد. هیچ سند مالی ایجاد نشده است.').waitFor();
    assert.equal(await page.evaluate(()=>window.calls.length),1);
    assert.equal(await page.evaluate(()=>window.calls[0].manualConfirmation),false);
    page.on('dialog',dialog=>dialog.accept());
    await page.getByRole('button',{name:'تأیید سفارش'}).click();
    await page.getByRole('button',{name:'شروع اجرا'}).click();
    await page.getByRole('textbox',{name:'تولید واقعی (اختیاری)'}).fill('120');
    await page.getByRole('textbox',{name:'ضایعات واقعی (اختیاری)'}).fill('5');
    await page.getByRole('textbox',{name:'مازاد سالم (اختیاری)'}).fill('15');
    await page.getByRole('button',{name:'ثبت اندازه‌گیری با تأیید'}).click();
    assert.equal(await page.evaluate(()=>window.calls.length),4);
    assert.equal(await page.evaluate(()=>window.calls[3].manualConfirmation),true);
    assert.equal(await page.evaluate(()=>window.calls[3].data.scrapQuantity),5);
    assert.equal(await page.evaluate(()=>window.calls[3].data.healthySurplusQuantity),15);
  }finally{await browser.close();}
});
