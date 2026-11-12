'use strict';
/** Isolated print-designer acceptance with synthetic invoices and no ledger writes. */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const esbuild=require('esbuild');

const root=path.resolve(__dirname,'..');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'', 'npm','node_modules','playwright'));}

async function fixture(){
  const source=`import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import Designer from './src/accounting_print_designer.jsx';
import {DEFAULT_PRINT_TEMPLATE,validatePrintTemplate,applyPrintLayoutPreset,
  PRINT_LAYOUT_PRESETS,renderPrintTemplatePages,buildCustomPrintExport,invoiceLineUnit}
  from './src/accounting_print_template.js';
const doc={id:'INV-TEST-1',number:'F-100',documentDate:'2026-11-11',
  status:'draft',lines:Array.from({length:32},(_,i)=>({
    description:'سطر آزمایشی '+(i+1),quantity:2,unitPrice:10000,total:20000,
    itemId:i===0?'ITEM-42':'',accountId:i===0?'ACC-7':''})),
  subtotal:640000,discount:0,tax:0,total:640000};
  const context={kind:'invoice',doc,party:'مشتری آزمایشی',
  company:{legalName:'شرکت تست'},currency:'RIAL',items:{
    'ITEM-42':{id:'ITEM-42',unit:'متر',name:'آزمایش کالا'}
  }};
window.__qa={DEFAULT_PRINT_TEMPLATE,validatePrintTemplate,applyPrintLayoutPreset,
  PRINT_LAYOUT_PRESETS,renderPrintTemplatePages,buildCustomPrintExport,invoiceLineUnit,doc,context,
  writes:[],saves:[]};
const original=CanvasRenderingContext2D.prototype.fillText;
CanvasRenderingContext2D.prototype.fillText=function(value,...args){
  window.__qa.writes.push({text:String(value),x:args[0],y:args[1],width:args[2]});
  return original.call(this,value,...args);
};
function App(){
  const [template,setTemplate]=useState(DEFAULT_PRINT_TEMPLATE);
  window.__qa.template=template;
  return <Designer value={template} onChange={setTemplate} context={context}
    onSave={next=>window.__qa.saves.push(next)}/>;
}
createRoot(document.getElementById('root')).render(<App/>);
`;
  const files=(await esbuild.build({
    stdin:{contents:source,resolveDir:root,sourcefile:'taraz-clarify-print-fixture.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',write:false,logLevel:'silent',
    outdir:'taraz-print-clarify-fixture',charset:'utf8',
    loader:{'.css':'css','.png':'dataurl','.jpg':'dataurl','.svg':'dataurl'}
  })).outputFiles;
  return {js:files.find(f=>f.path.endsWith('.js')).text,
    css:files.find(f=>f.path.endsWith('.css'))?.text||''};
}

test('backwards-compatible layouts, bounded columns and no fabricated invoice data',async t=>{
  const assets=await fixture();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1400,height:980}});
  const errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  await page.setContent('<html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:assets.js});
  await page.getByRole('button',{name:'اعمال چیدمان انتخابی'}).waitFor();
  assert.equal(await page.getByText('پیشنهاد چیدمان با مدل محلی').count(),0);
  const contract=await page.evaluate(()=>{
    const {DEFAULT_PRINT_TEMPLATE:base,validatePrintTemplate:validate,
      applyPrintLayoutPreset:apply,PRINT_LAYOUT_PRESETS:presets}=window.__qa;
    const legacy=structuredClone(base);
    delete legacy.logoLayout;
    delete legacy.table.columns;
    delete legacy.table.rowHeight;
    delete legacy.companyHeader;
    delete legacy.companySubtitle;
    delete legacy.footerText;
    const normalized=validate(legacy);
    const formats=presets.map(p=>{
      const t=apply(normalized,p.id);
      return [p.id,t.page,t.orientation,t.fields.length,t.table.columns.length];
    });
    const rejected=[];
    for(const cols of [['description','description'],['quantity'],
      ['description','evil'],['description','__proto__']]){
      try{validate({...normalized,table:{...normalized.table,columns:cols}});}
      catch{rejected.push(cols.join(','));}
    }
    try{validate({...normalized,logoLayout:{x:190,y:20,width:36,height:23}});}
    catch{rejected.push('off-page-logo');}
    // A5 must not accept a table header below the paper's bottom edge.
    const compact=apply(normalized,'compact');
    try{validate({...compact,table:{...compact.table,y:205}});}
    catch{rejected.push('off-page-A5-table');}
    const unitFromItem=window.__qa.invoiceLineUnit({itemId:'ITEM-42'},
      window.__qa.context.items);
    const unitForUncoded=window.__qa.invoiceLineUnit({description:'بدون کد'},
      window.__qa.context.items);
    const unitForUnknown=window.__qa.invoiceLineUnit({itemId:'NOT-CATALOGED'},
      window.__qa.context.items);
    return {formats,normalized:normalized.logoLayout,columns:normalized.table.columns,
      rejected,unitFromItem,unitForUncoded,unitForUnknown};
  });
  assert.equal(contract.formats.length,3);
  assert.deepEqual(contract.formats.map(x=>x[1]),['A4','A4','A5']);
  assert.deepEqual(contract.columns,['description','quantity','price','total']);
  assert.equal(contract.rejected.length,6);
  assert.ok(contract.rejected.includes('off-page-A5-table'));
  assert.deepEqual(contract.normalized,{x:12,y:12,width:36,height:23});
  assert.deepEqual([contract.unitFromItem,contract.unitForUncoded,contract.unitForUnknown],
    ['متر','عدد','—']);

  await page.getByRole('combobox',{name:'سبک چیدمان'}).selectOption('compact');
  await page.getByRole('button',{name:'اعمال چیدمان انتخابی'}).click();
  assert.equal(await page.getByRole('combobox',{name:'کاغذ'}).inputValue(),'A5');
  assert.equal(await page.getByRole('spinbutton',{name:'شروع جدول (mm)'}).getAttribute('max'),'133');
  await page.getByLabel('شناسه کالا یا خدمت',{exact:true}).check();
  await page.getByLabel('واحد',{exact:true}).check();
  await page.getByRole('button',{name:'انتقال شناسه کالا یا خدمت به بالا'}).click();
  await page.getByRole('button',{name:'انتقال شناسه کالا یا خدمت به بالا'}).click();
  await page.getByRole('button',{name:'ذخیره قالب'}).click();
  const saved=await page.evaluate(()=>window.__qa.saves[0]);
  assert.equal(saved.page,'A5');
  assert.deepEqual(saved.table.columns,['description','quantity','itemId','price','total','unit']);
  await page.waitForFunction(()=>window.__qa.writes.some(x=>x.text==='ITEM-42'));
  const rowData=await page.evaluate(()=>window.__qa.writes.map(x=>x.text));
  assert.ok(rowData.includes('ITEM-42'));
  assert.ok(rowData.includes('متر'));
  assert.ok(rowData.includes('عدد'));
  assert.ok(rowData.some(x=>x==='—'));
  assert.equal(errors.length,0,errors.join('\n'));
});

test('local-model suggestion is capability-gated, verified and requires human apply',async t=>{
  const assets=await fixture();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1400,height:1000}});
  const errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  await page.setContent('<html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:`window.__aiCalls=[];
window.madar={tarazPrintSuggest:async prompt=>{
  window.__aiCalls.push(prompt);
  const layout={page:'A5',orientation:'portrait',font:'Tahoma',color:'#235c66'};
  return window.__aiCalls.length===1?
    {layout,source:'UNKNOWN',modelRan:false}:
    {layout,source:'LOCAL_OLLAMA',modelRan:true};
}};`});
  await page.addScriptTag({content:assets.js});
  await page.getByRole('button',{name:'پیشنهاد طراحی'}).waitFor();
  await page.getByRole('textbox',{name:'شرح طرح دلخواه'}).fill('فرم اداری خوانا و مینیمال');
  await page.getByRole('button',{name:'پیشنهاد طراحی'}).click();
  await page.getByRole('alert').getByText(/مدل محلی پاسخ معتبر نداد/).waitFor();
  assert.equal(await page.getByRole('button',{name:'اعمال پیشنهاد روی طرح'}).count(),0);
  await page.getByRole('button',{name:'پیشنهاد طراحی'}).click();
  await page.getByText('طرح پیشنهادی؛ هنوز اعمال نشده است').waitFor();
  assert.equal(await page.getByRole('combobox',{name:'کاغذ'}).inputValue(),'A4');
  assert.equal(await page.getByRole('combobox',{name:'فونت'}).inputValue(),'Vazirmatn');
  await page.waitForFunction(()=>document.querySelector('.sac-print-ai-proposal canvas')?.width>100);
  await page.getByRole('button',{name:'اعمال پیشنهاد روی طرح'}).click();
  assert.equal(await page.getByRole('combobox',{name:'کاغذ'}).inputValue(),'A5');
  assert.equal(await page.getByRole('combobox',{name:'فونت'}).inputValue(),'Tahoma');
  assert.equal(await page.evaluate(()=>window.__qa.template.color),'#235c66');
  assert.deepEqual(await page.evaluate(()=>window.__aiCalls),
    ['فرم اداری خوانا و مینیمال','فرم اداری خوانا و مینیمال']);
  assert.equal(await page.evaluate(()=>window.__qa.saves.length),0);
  assert.equal(errors.length,0,errors.join('\n'));
});

test('user-defined print column safely maps a real row variable and survives save',async t=>{
  const assets=await fixture();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1400,height:1000}});
  const errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  await page.setContent('<html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:assets.js});
  const add=page.getByRole('button',{name:'افزودن ستون سفارشی'});
  await add.click();
  await page.getByRole('textbox',{name:'عنوان ستون سفارشی custom_1'}).fill('واحد سفارشی');
  await page.getByRole('combobox',{name:'متغیر ستون سفارشی custom_1'}).selectOption('unit');
  await page.waitForFunction(()=>window.__qa.template.table.customColumns?.[0]?.label==='واحد سفارشی');
  const rendered=await page.evaluate(async()=>{
    const q=window.__qa;
    q.writes.length=0;
    const pages=await q.renderPrintTemplatePages(q.template,q.context,{scale:2});
    return {pages:pages.length,columns:q.template.table.columns,
      custom:q.template.table.customColumns,
      text:q.writes.map(x=>x.text)};
  });
  assert.deepEqual(rendered.custom,[{id:'custom_1',label:'واحد سفارشی',source:'unit'}]);
  assert.ok(rendered.columns.includes('custom_1'));
  assert.ok(rendered.text.includes('واحد سفارشی'));
  assert.ok(rendered.text.includes('متر'));
  assert.ok(rendered.pages>1);
  assert.equal(rendered.text.filter(value=>/^سطر آزمایشی \d+$/.test(value)).length,32);
  await page.getByRole('button',{name:'ذخیره قالب'}).click();
  const saved=await page.evaluate(()=>window.__qa.saves[0]);
  assert.equal(saved.table.customColumns[0].source,'unit');
  assert.equal(saved.table.customColumns[0].label,'واحد سفارشی');
  await page.getByRole('button',{name:'حذف ستون سفارشی custom_1'}).click();
  const after=await page.evaluate(()=>window.__qa.template.table);
  assert.deepEqual(after.customColumns,[]);
  assert.ok(!after.columns.includes('custom_1'));
  for(let n=0;n<4;n++)await add.click();
  assert.equal(await add.isDisabled(),true);
  assert.deepEqual(errors,[]);
});

test('logo drag, preview window and multipage PDF use the same template',async t=>{
  const assets=await fixture();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1400,height:1000}});
  const errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  await page.setContent('<html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:assets.js});
  await page.getByRole('button',{name:'اعمال چیدمان انتخابی'}).waitFor();
  await page.locator('input[type="file"]').setInputFiles({name:'logo.png',mimeType:'image/png',
    buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==','base64')});
  await page.waitForFunction(()=>window.__qa.template.logo.startsWith('data:image/png;base64,'));
  await page.getByRole('button',{name:/انتخاب لوگو برای جابه‌جایی روی صفحه/}).click();
  const canvas=page.locator('.sac-print-canvas-shell canvas');
  await canvas.waitFor();
  const rect=await canvas.boundingBox();
  const from={x:rect.x+rect.width*(18/210),y:rect.y+rect.height*(18/297)};
  const to={x:from.x+rect.width*(18/210),y:from.y+rect.height*(22/297)};
  await page.mouse.move(from.x,from.y);
  await page.mouse.down();
  await page.mouse.move(to.x,to.y,{steps:5});
  await page.mouse.up();
  const location=await page.evaluate(()=>window.__qa.template.logoLayout);
  assert.ok(location.x>12&&location.y>12,JSON.stringify(location));
  const prepared=await page.evaluate(async()=>{
    const q=window.__qa;
    q.writes.length=0;
    const pages=await q.renderPrintTemplatePages(q.template,q.context,{scale:2});
    const renderedLineDescriptions=q.writes.map(item=>item.text)
      .filter(value=>/^سطر آزمایشی \d+$/.test(value));
    const output=await q.buildCustomPrintExport({template:q.template,
      kind:'invoice',doc:q.doc,party:q.context.party,company:q.context.company,
      currency:'RIAL',items:q.context.items,format:'pdf',pattern:'qa-{kind}-{id}'});
    const bytes=new Uint8Array(await output.blob.arrayBuffer());
    return {pages:pages.length,filename:output.filename,
      prefix:Array.from(bytes.slice(0,5),x=>String.fromCharCode(x)).join(''),
      length:bytes.length,renderedLineDescriptions};
  });
  assert.ok(prepared.pages>1,JSON.stringify(prepared));
  assert.equal(prepared.renderedLineDescriptions.length,32,
    'No line can be omitted or repeated across physical invoice pages');
  assert.equal(new Set(prepared.renderedLineDescriptions).size,32,
    'All 32 invoice lines must render exactly once');
  assert.equal(prepared.prefix,'%PDF-');
  assert.ok(prepared.length>1000);
  assert.match(prepared.filename,/\.pdf$/);
  const popupEvent=page.waitForEvent('popup');
  await page.getByRole('button',{name:'پیش‌نمایش همه صفحات'}).click();
  const popup=await popupEvent;
  await popup.locator('img.sheet').first().waitFor();
  assert.equal(await popup.locator('img.sheet').count(),prepared.pages);
  assert.equal(errors.length,0,errors.join('\n'));
});
