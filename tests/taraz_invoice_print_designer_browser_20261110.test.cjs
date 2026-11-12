'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const root=path.resolve(__dirname,'..');
const esbuild=require('esbuild');
let playwright;
try { playwright=require('playwright'); }
catch { playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
  'AppData','Roaming','npm','node_modules','playwright')); }

async function fixture(){
  const source=`import React from 'react';
import {createRoot} from 'react-dom/client';
import {StandaloneAccountingWorkspace} from './src/standalone_accounting_workspace.jsx';
window.__financeCommands=[];
window.__templateCalls=[];
window.__libraries={print:[],issuer:[],entry:[]};
window.__defaults={print:'',issuer:'',entry:''};
const view={currency:'RIAL',journals:[],accounts:{},parties:{},items:{},
  invoices:{},bills:{},receipts:{},payments:{},proformas:{},taxRules:{},
  contractorJobs:{},returns:{},cashAccounts:{},
  companyProfile:{legalName:'شرکت نمونه ثبت‌شده'},closedThrough:null,
  sequence:{invoice:0,bill:0}};
const api={
  standaloneAccountingRead:async()=>({revision:0,view,
    capabilities:{canManage:true,canDraft:true,canAdmin:true},
    currentUser:{username:'operator',role:'admin',jobTitle:''}}),
  standaloneAccountingCommand:async value=>{window.__financeCommands.push(value);
    throw Error('Finance commands forbidden in form designer test');},
  standaloneAccountingTemplateList:async kind=>({
    templates:window.__libraries[kind].map(x=>structuredClone(x)),
    defaultId:window.__defaults[kind]}),
  standaloneAccountingTemplateSave:async (kind,title,data,id)=>{
    window.__templateCalls.push({action:'save',kind,title});
    const templateId=id||'a'.repeat(32);
    const record={id:templateId,kind,title,data:structuredClone(data)};
    const items=window.__libraries[kind];
    const idx=items.findIndex(x=>x.id===templateId);
    if(idx<0)items.push(record);else items[idx]=record;
    return {id:templateId};
  },
  standaloneAccountingTemplateDefault:async(kind,id)=>{
    window.__templateCalls.push({action:'default',kind,id});
    window.__defaults[kind]=id;return {defaultId:id};
  },
  standaloneAccountingTemplateDelete:async(kind,id)=>{
    window.__libraries[kind]=window.__libraries[kind].filter(x=>x.id!==id);
  },
  standaloneAccountingTemplateDuplicate:async()=>{throw Error('Unexpected duplicate');},
};
let root;
window.__mount=()=>{
  if(root)root.unmount();
  root=createRoot(document.getElementById('root'));
  root.render(<StandaloneAccountingWorkspace api={api} canManage={true}
    canDraft={true} canAdmin={true}/>);
};
window.__mount();
`;
  const files=(await esbuild.build({
    stdin:{contents:source,resolveDir:root,sourcefile:'taraz-invoice-designer-qa.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',write:false,
    outdir:'taraz-invoice-designer-browser',logLevel:'silent',charset:'utf8',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'},
  })).outputFiles;
  return {js:files.find(f=>f.path.endsWith('.js')).text,
    css:files.find(f=>f.path.endsWith('.css'))?.text||''};
}

test('invoice designer is accessible; edits live PDF preview, saves to host and reloads',async t=>{
  const assets=await fixture();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});
  const errors=[];
  page.on('pageerror',error=>errors.push(String(error)));
  await page.setContent('<html dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:assets.js});
  const openDesigner=async()=>{
    await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
    await page.getByRole('dialog',{name:'فهرست بخش‌های تراز'})
      .getByRole('button',{name:'طراحی فرم فاکتور'}).click();
  };
  await openDesigner();
  await page.getByRole('region',{name:'محتوای صفحه حسابداری'})
    .getByRole('heading',{name:'طراح بصری قالب فاکتور'}).waitFor();
  await page.getByRole('textbox',{name:'نام قالب'}).fill('قالب فاکتور آریان');
  await page.getByRole('textbox',{name:'نام چاپی شرکت'}).fill('شرکت طراحی آزمایشی');
  await page.getByRole('textbox',{name:/سطر زیر سربرگ/}).fill('تهران، تلفن ۱۲۳');
  await page.getByRole('textbox',{name:'عنوان قیمت واحد'}).fill('نرخ واحد');
  await page.getByRole('textbox',{name:'متن پاورقی چاپ'}).fill('فقط برای بازبینی طرح');
  await page.getByRole('button',{name:/عنوان سند/}).click();
  await page.getByRole('textbox',{name:'عنوان فیلد'}).fill('فاکتور اختصاصی');
  await page.locator('.sac-print-canvas-shell canvas').waitFor();
  await page.waitForFunction(()=>{
    const c=document.querySelector('.sac-print-canvas-shell canvas');
    return c&&c.width>500&&c.height>500&&!document.querySelector('.sac-print-error');
  });
  assert.ok(await page.locator('.sac-print-canvas-shell canvas')
    .evaluate(c=>c.getContext('2d').getImageData(5,5,1,1).data[3]===255));
  assert.equal(await page.evaluate(()=>window.__financeCommands.length),0);

  await page.getByRole('button',{name:'ذخیره قالب چاپ'}).click();
  await page.getByText('قالب «قالب فاکتور آریان» در کتابخانه خصوصی این دفتر ذخیره شد.',{exact:false}).waitFor();
  assert.deepEqual(await page.evaluate(()=>window.__templateCalls[0]),
    {action:'save',kind:'print',title:'قالب فاکتور آریان'});
  assert.deepEqual(await page.evaluate(()=>{
    const d=window.__libraries.print[0].data;
    return [d.companyHeader,d.companySubtitle,d.footerText,d.table.labels.price,
      d.fields.find(f=>f.id==='title').label,d.page];
  }),['شرکت طراحی آزمایشی','تهران، تلفن ۱۲۳','فقط برای بازبینی طرح',
    'نرخ واحد','فاکتور اختصاصی','A4']);
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'دانلود PDF نمونه فرم'}).click();
  const download=await downloadPromise;
  assert.match(download.suggestedFilename(),/\.pdf$/);
  const file=await download.path();
  assert.ok(fs.readFileSync(file).subarray(0,8).toString().startsWith('%PDF-'));

  await page.getByRole('button',{name:'پیش‌فرض شرکت'}).click();
  await page.waitForFunction(()=>window.__defaults.print==='a'.repeat(32));
  await page.evaluate(()=>window.__mount());
  await openDesigner();
  assert.equal(await page.getByRole('textbox',{name:'نام چاپی شرکت'}).inputValue(),
    'شرکت طراحی آزمایشی');
  assert.equal(await page.getByRole('textbox',{name:'متن پاورقی چاپ'}).inputValue(),
    'فقط برای بازبینی طرح');
  assert.equal(await page.getByRole('textbox',{name:'عنوان قیمت واحد'}).inputValue(),
    'نرخ واحد');
  assert.deepEqual(await page.evaluate(()=>window.__financeCommands),[]);
  assert.deepEqual(errors,[]);
  const output=path.join(root,'tests','output');
  fs.mkdirSync(output,{recursive:true});
  await page.locator('.sac-print-designer').screenshot({path:path.join(output,
    'taraz_invoice_print_designer_20261110.png')});
});
