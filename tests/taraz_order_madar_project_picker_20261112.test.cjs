'use strict';
/** Authenticated host-only project selection. Browser runs with synthetic state. */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const esbuild=require('esbuild');

const root=path.resolve(__dirname,'..');
const filename=path.join(root,'src/taraz_order_workspace.jsx');
const sourceRequire=require('node:module').createRequire(filename);
const nodeBundle=esbuild.buildSync({entryPoints:[filename],bundle:true,
  platform:'node',format:'cjs',write:false,
  external:['react','react/jsx-runtime','lucide-react'],
  loader:{'.css':'empty'},logLevel:'silent'});
const bundleModule={exports:{}};
new Function('require','module','exports',nodeBundle.outputFiles[0].text)(
  sourceRequire,bundleModule,bundleModule.exports);
const {verifyMadarProjectPage}=bundleModule.exports;

function page(overrides={}){
  return {connected:true,scope:'projects',offset:0,limit:50,
    financialEventCreated:false,items:{projects:[
      {id:'madar-project-01',name:'بسته‌بندی آبان',status:'active'},
    ]},counts:{projects:1},more:{projects:false},source:{
      kind:'madar-authorized-host-state-projection',
      serverAclApplied:true,readOnly:true,revision:'a'.repeat(64),
      actor:'madar-operator',readUtc:'2026-11-12T00:00:00+00:00',
    },...overrides};
}

test('verified host project page retains exact ID and source name',()=>{
  const confirmed=verifyMadarProjectPage(page());
  assert.deepEqual(confirmed.projects,[{id:'madar-project-01',name:'بسته‌بندی آبان'}]);
  assert.equal(confirmed.actor,'madar-operator');
  assert.equal(confirmed.revision,'a'.repeat(64));
});

test('reject local/stale/malformed/unscoped/duplicate/fake project claims',()=>{
  const wrong=[
    {source:{...page().source,kind:'madar-local-appdata-tasks-json',serverAclApplied:false}},
    {source:{...page().source,serverAclApplied:false}},
    {source:{...page().source,readOnly:false}},
    {source:{...page().source,revision:'bad'}},
    {financialEventCreated:true},
    {scope:'tasks'},
    {offset:50},
    {items:{projects:[{id:'id\u0000unsafe',name:'bad'}]}},
    {items:{projects:[{id:'madar-project-01',name:'پروژه'},
      {id:'madar-project-01',name:'نسخه دوم'}]},counts:{projects:2}},
    {items:{projects:[{id:'project-only'}]}},
    {items:{projects:[{id:'x'.repeat(121),name:'بیش از حد'}]}},
  ];
  wrong.forEach(data=>assert.equal(typeof verifyMadarProjectPage(page(data)).error,
    'string',JSON.stringify(data)));
});

test('native Edge: permissioned read, explicit project apply, independent order save',async()=>{
  let playwright;
  try{playwright=require('playwright');}
  catch{playwright=require(path.join(process.env.APPDATA||'','npm','node_modules','playwright'));}
  const source=[
    "import React from 'react';",
    "import {createRoot} from 'react-dom/client';",
    "import Orders from './src/taraz_order_workspace.jsx';",
    "window.projectReads=[];window.orderCommands=[];window.malformed=false;",
    "window.api={",
    "tarazOrderList:async()=>({orders:[],total:0,financialEventCreated:false}),",
    "tarazOrderCommand:async request=>{window.orderCommands.push(request);return {",
    "id:'c'.repeat(32),status:'draft',revision:1,financialEventCreated:false,...request.data};},",
    "tarazMadarDataRead:async(scope,offset,limit,consent,credentials,source)=>{",
    "window.projectReads.push({scope,offset,limit,consent,source,",
    "hasCredentials:!!credentials?.password});",
    "return {connected:true,scope,offset,limit,financialEventCreated:false,",
    "counts:{projects:51},more:{projects:offset===0},",
    "items:{projects:[offset===0?{id:'project-1',name:'پروژه نمونه اول'}:",
    "{id:'project-2',name:'پروژه نمونه دوم'}]},",
    "source:{kind:window.malformed?'madar-local-appdata-tasks-json':",
    "'madar-authorized-host-state-projection',serverAclApplied:!window.malformed,",
    "readOnly:true,revision:'a'.repeat(64),actor:'madar-user'}};},",
    "};",
    "createRoot(document.getElementById('root')).render(",
    "<Orders api={window.api} canEdit={true} canAdmin={true} currency='RIAL'/>);",
  ].join('\n');
  const built=await esbuild.build({stdin:{contents:source,resolveDir:root,
    sourcefile:'taraz-madar-order-picker-qa.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',outdir:'synthetic-output',
    write:false,logLevel:'silent'});
  const javascript=built.outputFiles.find(file=>file.path.endsWith('.js')).text;
  const stylesheet=built.outputFiles.find(file=>file.path.endsWith('.css'))?.text||'';
  const html='<!doctype html><html dir="rtl" lang="fa"><head><meta charset="utf-8">'+
    '<style>'+stylesheet+'</style></head><body><div id="root"></div><script>'+javascript+
    '</script></body></html>';
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-sandbox','--disable-extensions']});
  try{
    const browserPage=await browser.newPage();
    browserPage.setDefaultTimeout(7500);
    await browserPage.route('**/*',route=>route.request().url()==='https://order-madar-qa.invalid/'?
      route.fulfill({status:200,contentType:'text/html',body:html}):route.abort());
    await browserPage.goto('https://order-madar-qa.invalid/');
    await browserPage.getByRole('heading',{name:'سفارش‌ها',exact:true}).waitFor();
    await browserPage.getByRole('button',{name:'حرفه‌ای'}).click();
    const picker=browserPage.getByRole('region',{name:'انتخاب پروژه واقعی مدار'});
    assert.equal(await browserPage.evaluate(()=>window.projectReads.length),0);
    assert.equal(await browserPage.evaluate(()=>window.orderCommands.length),0);
    await picker.getByRole('checkbox',{name:/خواندن درخواستی/}).check();
    await picker.getByRole('textbox',{name:'نشانی HTTPS میزبان مدار'})
      .fill('https://127.0.0.1:48370');
    await picker.getByRole('textbox',{name:'اثر انگشت SHA-256 گواهی'})
      .fill('a'.repeat(64));
    await picker.getByRole('textbox',{name:'نام کاربری مدار'}).fill('operator');
    await picker.getByRole('textbox',{name:'گذرواژه مدار'}).fill('test-password-only');
    assert.equal(await browserPage.evaluate(()=>window.projectReads.length),0);
    await picker.getByRole('button',{name:'خواندن پروژه‌های مجاز مدار'}).click();
    await picker.getByText('فهرست از میزبان احراز هویت‌شده مدار دریافت شد.',
      {exact:false}).waitFor();
    assert.deepEqual(await browserPage.evaluate(()=>window.projectReads),[{
      scope:'projects',offset:0,limit:50,consent:true,source:'host',hasCredentials:true,
    }]);
    await picker.getByRole('button',{name:'صفحه بعد'}).click();
    await picker.getByRole('option',{name:/پروژه نمونه دوم/}).waitFor({state:'attached'});
    await picker.getByRole('combobox',{name:'پروژه مدار'}).selectOption('project-2');
    assert.equal(await browserPage.evaluate(()=>window.orderCommands.length),0);
    await picker.getByRole('button',{name:'اعمال شناسه انتخاب‌شده به سفارش'}).click();
    assert.equal(await browserPage.getByRole('textbox',{name:/ارجاع پروژه مرتبط/}).inputValue(),
      'project-2');
    assert.equal(await browserPage.evaluate(()=>window.orderCommands.length),0);
    assert.ok(await browserPage.getByText('شناسه انتخاب‌شده از مدار:',{exact:false}).count());
    await browserPage.getByRole('textbox',{name:'نام مشتری'}).fill('مشتری تست');
    await browserPage.getByRole('textbox',{name:'شرح سفارش'}).fill('جعبه چاپی');
    await browserPage.getByRole('textbox',{name:'تعداد سفارش'}).fill('100');
    await browserPage.getByRole('textbox',{name:'تعداد برنامه‌ریزی تولید'}).fill('120');
    await browserPage.getByRole('button',{name:'ذخیره سفارش'}).click();
    await browserPage.getByText('سفارش در میزبان ذخیره شد. هیچ سند مالی ایجاد نشده است.').waitFor();
    const commands=await browserPage.evaluate(()=>window.orderCommands);
    assert.equal(commands.length,1);
    assert.equal(commands[0].data.projectReference,'project-2');
    assert.equal(commands[0].manualConfirmation,false);
    assert.equal(commands[0].nextStatus,null);
    await browserPage.evaluate(()=>{window.malformed=true;});
    await picker.getByRole('button',{name:'خواندن پروژه‌های مجاز مدار'}).click();
    await picker.getByRole('alert').getByText('خواندن پروژه‌های مدار انجام نشد',
      {exact:false}).waitFor();
    assert.equal(await picker.getByRole('combobox',{name:'پروژه مدار'}).count(),0);
  }finally{await browser.close();}
});
