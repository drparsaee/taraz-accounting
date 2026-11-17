'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const root=path.resolve(__dirname,'..');
const esbuild=require('esbuild');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.USERPROFILE||process.env.HOME||'',
  'AppData','Roaming','npm','node_modules','playwright'));}

const fixture=`import React from 'react';
import {createRoot} from 'react-dom/client';
import {StandaloneAccountingWorkspace} from './src/standalone_accounting_workspace.jsx';
const id1='1'.repeat(32),id2='2'.repeat(32),id3='3'.repeat(32);
const proposal=(id,title,projectId)=>({schema:1,source:'madar',id,
  taskId:'task-'+id[0],projectId,title,amountRial:875000});
window.__bridge={calls:[],pending:[
  proposal(id1,'طراحی بسته‌بندی سفارشی','packaging'),
  proposal(id2,'آماده‌سازی چاپ افست','printing')],
  recovery:[{...proposal(id3,'تصمیم قدیمی در انتظار بازیابی','legacy'),
    state:'rejected',financialEventCreated:false}],decisions:{[id3]:'rejected'}};
const view={currency:'RIAL',journals:[],accounts:{},parties:{},items:{},
  invoices:{},bills:{},receipts:{},payments:{},proformas:{},taxRules:{},
  contractorJobs:{},returns:{},cashAccounts:{},
  companyProfile:{legalName:'دفتر تست ایزوله'},closedThrough:null,
  sequence:{invoice:0,bill:0}};
const api={
  standaloneAccountingRead:async()=>({revision:0,view,
    capabilities:{canManage:true,canDraft:true,canAdmin:true},
    currentUser:{username:'synthetic-admin',role:'admin',jobTitle:''}}),
  standaloneAccountingCommand:async data=>{
    window.__bridge.calls.push({method:'FINANCE',data});
    throw Error('Finance posting forbidden');
  },
  tarazIntegrationList:async()=>{
    window.__bridge.calls.push({method:'list'});
    return {connected:true,invalidCount:0,recoveryInvalidCount:0,
      recoveryTruncated:false,requests:structuredClone(window.__bridge.pending),
      recovery:structuredClone(window.__bridge.recovery)};
  },
  tarazIntegrationReview:async(id,state)=>{
    window.__bridge.calls.push({method:'review',id,state});
    const index=window.__bridge.pending.findIndex(x=>x.id===id);
    if(index<0)throw Error('unknown proposal');
    window.__bridge.pending.splice(index,1);
    window.__bridge.decisions[id]=state;
    return {id,state,financialEventCreated:false};
  },
  tarazIntegrationRecover:async(id,consented)=>{
    window.__bridge.calls.push({method:'recover',id,consented});
    if(consented!==true||!window.__bridge.decisions[id])throw Error('invalid recovery');
    window.__bridge.recovery=window.__bridge.recovery.filter(x=>x.id!==id);
    return {id,state:window.__bridge.decisions[id],financialEventCreated:false};
  },
  tarazMadarDataRead:async(scope,offset,limit,consent,connection,source)=>{
    window.__bridge.calls.push({method:'dataRead',scope,offset,source,
      consent,hasAuth:!!connection?.password});
    if(consent!==true)throw Error('Missing explicit consent');
    if(source==='host'&&!connection?.password)throw Error('Missing Madar host login');
    const items=Array.from({length:55},(_,i)=>({id:'item-'+i,
      title:'کار ثبت‌شده شماره '+i,projectId:'project-demo',status:'todo',
      description:'شرح داده غیرمالی'}));
    const rows=items.slice(offset,offset+limit);
    return {connected:true,scope,offset,limit,counts:{[scope]:55},
      items:{[scope]:rows},more:{[scope]:offset+rows.length<55},
      source:{kind:source==='host'?'madar-authorized-host-state-projection':
        'madar-local-appdata-tasks-json',readOnly:true,hostAuthenticated:source==='host',
        serverAclApplied:source==='host',mayBeStale:source==='local'},
      financialEventCreated:false};
  },
};
createRoot(document.getElementById('root')).render(
  <StandaloneAccountingWorkspace api={api} canManage canDraft canAdmin/>);
`;

async function assets(){
  const files=(await esbuild.build({
    stdin:{contents:fixture,resolveDir:root,sourcefile:'taraz-madar-dashboard-full-ui.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',write:false,logLevel:'silent',
    outdir:'taraz-madar-dashboard-full-ui',charset:'utf8',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'},
  })).outputFiles;
  return {js:files.find(f=>f.path.endsWith('.js')).text,
    css:files.find(f=>f.path.endsWith('.css'))?.text||''};
}

test('home and dedicated Madar navigation show consented inbox, filters, review/reject/recovery, no finance posting',async t=>{
  const {js,css}=await assets();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1440,height:950}});
  const errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.setContent('<html dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>');
  if(css)await page.addStyleTag({content:css});
  await page.addScriptTag({content:js});
  const home=page.locator('.taraz-madar-home');
  await home.getByRole('heading',{name:'اطلاعات مدار',exact:true}).waitFor();
  assert.equal(await page.locator('.taraz-madar-quick-nav [data-accounting-tab="madar"]').count(),1);
  assert.equal(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='list').length),0,
    'opening dashboard cannot automatically read external inbox');

  await home.getByRole('checkbox',{name:/اجازه می‌دهم اطلاعات صندوق مدار/}).check();
  assert.equal(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='list').length),0);
  await home.getByRole('button',{name:/دریافت \/ بازخوانی ارجاع‌های مدار/}).click();
  await home.getByText('طراحی بسته‌بندی سفارشی').waitFor();
  assert.equal(await home.locator('.taraz-madar-request').count(),2);
  assert.ok(await home.getByText('منبع: صندوق ارجاع مدار در میزبان تراز').count()>0);
  await home.getByRole('searchbox',{name:'جست‌وجوی ارجاع'}).fill('افست');
  assert.equal(await home.locator('.taraz-madar-request').count(),1);
  await home.getByRole('searchbox',{name:'جست‌وجوی ارجاع'}).fill('');

  await home.getByRole('button',{name:'بررسی شد'}).first().click();
  const confirm=home.getByRole('group',{name:'تأیید دستی ارجاع مدار'});
  await confirm.getByText('طراحی بسته‌بندی سفارشی').waitFor();
  assert.equal(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='review').length),0);
  await confirm.getByRole('button',{name:'انصراف'}).click();
  assert.equal(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='review').length),0);
  await home.getByRole('button',{name:'بررسی شد'}).first().click();
  await confirm.getByRole('button',{name:'تأیید نهایی تصمیم'}).click();
  await home.getByText('تصمیم ارجاع در میزبان ثبت شد',{exact:false}).waitFor();
  assert.deepEqual(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='review')),
    [{method:'review',id:'1'.repeat(32),state:'reviewed'}]);
  assert.equal(await home.locator('.taraz-madar-request').count(),1);

  await home.getByRole('button',{name:'رد ارجاع'}).click();
  await confirm.getByText('آماده‌سازی چاپ افست').waitFor();
  await confirm.getByRole('button',{name:'تأیید نهایی تصمیم'}).click();
  await home.getByText('تصمیم ارجاع در میزبان ثبت شد',{exact:false}).waitFor();
  assert.deepEqual(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='review').at(-1)),
    {method:'review',id:'2'.repeat(32),state:'rejected'});

  await home.getByRole('combobox',{name:'وضعیت'}).selectOption('recovery');
  await home.getByText('تصمیم قدیمی در انتظار بازیابی').waitFor();
  await home.getByRole('button',{name:'بازیابی دستی تصمیم پیشین'}).click();
  await confirm.getByRole('button',{name:'تأیید نهایی تصمیم'}).click();
  await home.getByText('تصمیم پیشین از میزبان بازیابی شد',{exact:false}).waitFor();
  assert.deepEqual(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='recover')),
    [{method:'recover',id:'3'.repeat(32),consented:true}]);

  await page.locator('.taraz-madar-quick-nav [data-accounting-tab="madar"]').click();
  const tab=page.locator('.taraz-madar-dashboard:not(.taraz-madar-home)');
  await tab.getByRole('heading',{name:'اطلاعات مدار',exact:true}).waitFor();
  assert.equal(await page.locator('.taraz-madar-quick-nav [aria-current="page"]').count(),1);
  assert.equal(await tab.getByRole('checkbox',{name:/اجازه می‌دهم اطلاعات صندوق مدار/}).isChecked(),false,
    'switching views requires new on-demand consent');
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
  await page.getByRole('dialog',{name:'فهرست بخش‌های تراز'})
    .getByRole('button',{name:'اطلاعات مدار'}).waitFor();
  await page.getByRole('button',{name:'بستن فهرست'}).click();

  const explorer=tab.locator('.taraz-madar-explorer');
  assert.equal(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='dataRead').length),0,
    'external data cannot be fetched without new explicit consent');
  await explorer.getByRole('checkbox',{name:/اجازه می‌دهم فقط با دکمه دریافت/}).check();
  await explorer.getByRole('combobox',{name:'نوع اطلاعات'}).selectOption('tasks');
  assert.equal(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='dataRead').length),0);
  await explorer.getByRole('button',{name:'خواندن اطلاعات انتخاب‌شده'}).click();
  await explorer.getByText('کار ثبت‌شده شماره 0').waitFor();
  assert.equal(await explorer.locator('.taraz-madar-request').count(),50);
  assert.ok(await explorer.getByText('ممکن است داده محلی به‌روز نباشد.').isVisible());
  await explorer.getByRole('button',{name:'صفحه بعد'}).click();
  await explorer.getByText('کار ثبت‌شده شماره 54').waitFor();
  assert.equal(await explorer.locator('.taraz-madar-request').count(),5);
  assert.deepEqual(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='dataRead').map(
    ({scope,offset,source,consent})=>({scope,offset,source,consent}))),[
    {scope:'tasks',offset:0,source:'local',consent:true},
    {scope:'tasks',offset:50,source:'local',consent:true},
  ]);
  await explorer.getByRole('combobox',{name:'منبع داده'}).selectOption('host');
  assert.equal(await explorer.locator('.taraz-madar-request').count(),0,
    'switching sources clears stale local data');
  await explorer.getByRole('textbox',{name:'نشانی میزبان HTTPS'}).fill('https://192.168.1.10:48370');
  await explorer.getByRole('textbox',{name:'اثر انگشت SHA-256'}).fill('a'.repeat(64));
  await explorer.getByRole('textbox',{name:'نام کاربری مدار'}).fill('demo-user');
  await explorer.getByRole('textbox',{name:'گذرواژه مدار'}).fill('ephemeral-password');
  await explorer.getByRole('button',{name:'خواندن اطلاعات انتخاب‌شده'}).click();
  await explorer.getByText('محدودیت دسترسی پروژه‌ها توسط میزبان اعمال شده است.').waitFor();
  assert.deepEqual(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='dataRead').at(-1)),
    {method:'dataRead',scope:'tasks',offset:0,source:'host',consent:true,hasAuth:true});
  assert.deepEqual(await page.evaluate(()=>window.__bridge.calls.filter(x=>x.method==='FINANCE')),[]);
  assert.deepEqual(errors,[]);
  const output=path.join(root,'tests','output');
  fs.mkdirSync(output,{recursive:true});
  await tab.screenshot({path:path.join(output,'taraz_madar_dashboard_20261111.png')});
});

test('current full workspace source includes visible Madar section and on-demand host calls',()=>{
  const workspace=fs.readFileSync(path.join(root,'src/standalone_accounting_workspace.jsx'),'utf8');
  const ribbon=fs.readFileSync(path.join(root,'src/accounting_top_ribbon.jsx'),'utf8');
  const dashboard=fs.readFileSync(path.join(root,'src/taraz_madar_dashboard.jsx'),'utf8');
  assert.match(workspace,/\['madar','اطلاعات مدار'\]/);
  assert.match(workspace,/tab==='madar'&&<TarazMadarDashboard/);
  assert.match(workspace,/tab==='overview'&&<>[\s\S]*?<TarazMadarDashboard/);
  assert.match(ribbon,/className="taraz-madar-quick-nav"/);
  assert.match(dashboard,/listTarazIntegration\(api\)/);
  assert.match(dashboard,/reviewTarazIntegration\(api,id,state\)/);
  assert.match(dashboard,/recoverTarazIntegration\(api,id,state\)/);
  assert.match(dashboard,/tarazMadarDataRead\(scope,nextOffset,50,true,auth,source\)/);
  assert.doesNotMatch(dashboard,/standaloneAccountingCommand\(/);
});
