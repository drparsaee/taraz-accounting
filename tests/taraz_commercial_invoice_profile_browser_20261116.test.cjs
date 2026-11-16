'use strict';
// Browser-visible source acceptance: two brands, one legal accounting company.
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const esbuild=require('esbuild');
const root=path.resolve(__dirname,'..');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
  'AppData','Roaming','npm','node_modules','playwright'));}

async function fixture(){
  const src=`import React from 'react';
import {createRoot} from 'react-dom/client';
import {StandaloneAccountingWorkspace} from './src/standalone_accounting_workspace.jsx';
window.__commands=[];
window.__calls=[];
window.__libs={print:[],issuer:[],entry:[],brand:[]};
window.__defaults={print:'',issuer:'',entry:'',brand:''};
const view={currency:'RIAL',journals:[],accounts:{},parties:{},items:{},
  invoices:{},bills:{},receipts:{},payments:{},proformas:{},taxRules:{},
  contractorJobs:{},returns:{},cashAccounts:{},
  companyProfile:{legalName:'هویت رسمی دفتر نمونه',nationalId:'1234567890'},closedThrough:null,
  freshWindowsWorkspace:true,sequence:{invoice:0,bill:0}};
const api={
  standaloneAccountingRead:async()=>({revision:0,view,
    capabilities:{canManage:true,canDraft:true,canAdmin:true},
    currentUser:{username:'operator',role:'admin',jobTitle:''}}),
  standaloneAccountingCommand:async value=>{window.__commands.push(value);
    throw Error('Never write financial data in this fixture');},
  standaloneAccountingTemplateList:async kind=>({
    templates:window.__libs[kind].map(x=>structuredClone(x)),
    defaultId:window.__defaults[kind]}),
  standaloneAccountingTemplateSave:async (kind,title,data,id)=>{
    window.__calls.push({kind,title,data:structuredClone(data)});
    const identifier=id||('' + 'abcdef0123456789').repeat(2).slice(0,31)+(window.__libs[kind].length+1);
    const item={id:identifier,kind,title,data:structuredClone(data)};
    const values=window.__libs[kind];
    const index=values.findIndex(row=>row.id===identifier);
    if(index>=0)values[index]=item;else values.push(item);
    if(!window.__defaults[kind])window.__defaults[kind]=identifier;
    return structuredClone(item);
  },
  standaloneAccountingTemplateDefault:async (kind,id)=>{
    window.__defaults[kind]=id;return {defaultId:id};},
  standaloneAccountingTemplateDelete:async (kind,id)=>{
    window.__libs[kind]=window.__libs[kind].filter(row=>row.id!==id);
    if(window.__defaults[kind]===id)window.__defaults[kind]='';
    return {templates:window.__libs[kind],defaultId:window.__defaults[kind]};},
  standaloneAccountingTemplateDuplicate:async()=>{throw Error('not needed');},
};
let mounted;
window.__mount=()=>{
  if(mounted)mounted.unmount();
  mounted=createRoot(document.getElementById('root'));
  mounted.render(<StandaloneAccountingWorkspace api={api} canManage={true}
    canDraft={true} canAdmin={true}/>);
};
window.__mount();`;
  const parts=(await esbuild.build({stdin:{contents:src,resolveDir:root,
    sourcefile:'taraz-commercial-profile-qa.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',write:false,
    outdir:'taraz-commercial-profile-browser',logLevel:'silent',charset:'utf8',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'}})).outputFiles;
  return {js:parts.find(p=>p.path.endsWith('.js')).text,
    css:parts.find(p=>p.path.endsWith('.css'))?.text||''};
}

test('commercial issuer profiles persist independently from official legal issuer, no ledger commands',async t=>{
  const assets=await fixture();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1500,height:1000},acceptDownloads:true});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.setContent('<html dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(assets.css)await page.addStyleTag({content:assets.css});
  await page.addScriptTag({content:assets.js});
  const open=async()=>{
    await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
    await page.getByRole('dialog',{name:'فهرست بخش‌های تراز'})
      .getByRole('button',{name:'طراحی فرم فاکتور'}).click();
  };
  await open();
  await page.getByRole('heading',{name:'پروفایل‌های تجاری صدور فاکتور'}).waitFor();
  await page.getByRole('textbox',{name:'نام تجاری',exact:true}).fill('کارما');
  await page.getByRole('textbox',{name:'سربرگ تکمیلی'}).fill('چاپ و تبلیغات کارما');
  await page.getByRole('textbox',{name:'اطلاعات تماس روی چاپ'}).fill('تماس نمونه');
  await page.getByRole('button',{name:'ذخیره پروفایل'}).click();
  await page.waitForFunction(()=>window.__libs.brand.length===1);
  assert.equal(await page.evaluate(()=>window.__libs.brand[0].data.profile.displayName),'کارما');
  assert.equal(await page.evaluate(()=>window.__libs.brand[0].data.format),
    'taraz-commercial-invoice-profile-v1');
  await page.getByRole('button',{name:'نام تجاری جدید'}).click();
  await page.getByRole('textbox',{name:'نام تجاری',exact:true}).fill('بارنگ');
  await page.getByRole('button',{name:'ذخیره پروفایل'}).click();
  await page.waitForFunction(()=>window.__libs.brand.length===2);
  assert.deepEqual(await page.evaluate(()=>window.__libs.brand.map(x=>x.title)),['کارما','بارنگ']);
  assert.deepEqual(await page.evaluate(()=>window.__libs.issuer),[]);
  assert.deepEqual(await page.evaluate(()=>window.__commands),[]);
  await page.evaluate(()=>window.__mount());
  await open();
  const brands=page.getByRole('combobox',{name:'انتخاب نام تجاری فاکتور'});
  const firstId=await page.evaluate(()=>window.__libs.brand[0].id);
  await brands.selectOption(firstId);
  assert.equal(await page.getByRole('textbox',{name:'نام تجاری',exact:true}).inputValue(),'کارما');
  const downloadable=page.waitForEvent('download');
  await page.getByRole('button',{name:'دانلود PDF نمونه فرم'}).click();
  const downloaded=await downloadable;
  assert.match(downloaded.suggestedFilename(),/\.pdf$/);
  const pdf=fs.readFileSync(await downloaded.path());
  assert.ok(pdf.length>1000 && pdf.subarray(0,5).toString()==='%PDF-');
  assert.deepEqual(errors,[]);
});
