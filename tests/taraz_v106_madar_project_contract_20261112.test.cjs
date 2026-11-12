'use strict';
/** Independent contract audit. In-memory fixtures only, no real Madar credentials. */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const esbuild=require('esbuild');
const root=path.resolve(__dirname,'..');
const file=path.join(root,'src/taraz_order_workspace.jsx');
const nodeBuild=esbuild.buildSync({entryPoints:[file],bundle:true,platform:'node',
  format:'cjs',write:false,loader:{'.css':'empty'},logLevel:'silent',
  external:['react','react/jsx-runtime','lucide-react']});
const mod={exports:{}};
new Function('require','module','exports',nodeBuild.outputFiles[0].text)(
  require('node:module').createRequire(file),mod,mod.exports);
const {verifyMadarProjectPage}=mod.exports;
const frozenRoot=path.resolve(root,'..','..','MTR-NEXT-UPDATE-CANDIDATES-20261110',
  'taraz-v1.0.6-aaas','build-777cb53341bb','source','src');

const identity={kind:'madar-authorized-host-state-projection',
  serverAclApplied:true,readOnly:true,revision:'a'.repeat(64),
  actor:'madar-user',readUtc:'2026-11-12T00:00:00Z'};
const project={id:'real-project-01',name:'پروژه چاپ'};
const page=(other={})=>({connected:true,scope:'projects',offset:0,limit:50,
  counts:{projects:1},items:{projects:[project]},more:{projects:false},
  source:{...identity},financialEventCreated:false,...other});
const python=(lines)=>{
  const code=lines.join('\n');
  const p=process.platform==='win32';
  const result=spawnSync(p?'py':'python3',
    p?['-3.12','-B','-c',code]:['-B','-c',code],
    {cwd:root,encoding:'utf8',timeout:25000,
      env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
  assert.equal(result.error,undefined,String(result.error||''));
  assert.equal(result.status,0,(result.stdout||'')+'\n'+(result.stderr||''));
  return result.stdout;
};

test('picker matches actual Madar project id/name/title projection, rejects false identity',()=>{
  assert.deepEqual(verifyMadarProjectPage(page()).projects,[project]);
  assert.deepEqual(verifyMadarProjectPage(page({
    items:{projects:[{id:'title-project',title:'پروژه بدون name'}]},
  })).projects,[{id:'title-project',name:'پروژه بدون name'}]);
  const rejected=[
    {scope:'tasks'},
    {financialEventCreated:true},
    {source:{...identity,kind:'madar-local-appdata-tasks-json',
      mayBeStale:true,serverAclApplied:false}},
    {source:{...identity,serverAclApplied:false}},
    {source:{...identity,readOnly:false}},
    {source:{...identity,revision:'fake'}},
    {source:{...identity,actor:''}},
    {items:{projects:[{id:'bad\u0000id',name:'invalid'}]}},
    {items:{projects:[{id:'a'.repeat(121),name:'invalid'}]}},
    {items:{projects:[{id:'',name:'invalid'}]}},
    {items:{projects:[{id:'id-only'}]}},
    {items:{projects:[{id:'same',name:'first'},{id:'same',name:'second'}]},
      counts:{projects:2}},
  ];
  for(const sample of rejected){
    assert.equal(typeof verifyMadarProjectPage(page(sample)).error,'string',
      'Expected rejection of '+JSON.stringify(sample));
  }
});

test('actual TarazAPI role/consent/host routing prevents unauthorized project read',()=>{
  const output=python([
    'from taraz_desktop import TarazAPI',
    'import taraz_madar_data_reader as rdr',
    'from threading import RLock',
    'from unittest.mock import patch',
    'class Operator:',
    '    def __init__(self,admin): self._lock=RLock(); self.admin=admin; self.roles=[]',
    '    def _require_authenticated(self,required="viewer"):',
    '        self.roles.append(required)',
    '        if required=="admin" and not self.admin: raise PermissionError("not admin")',
    '        return {"role":"admin" if self.admin else "editor"}',
    'connection={"url":"https://127.0.0.1:48370","fingerprint":"a"*64,',
    '    "username":"operator","password":"synthetic-password"}',
    'with patch.object(rdr,"read_authorized_madar_state",return_value={"financialEventCreated":False}) as remote, patch.object(rdr,"read_local_madar_state") as local:',
    '    for actor,approval in ((Operator(False),True),(Operator(True),False)):',
    '        try: TarazAPI.tarazMadarDataRead(actor,"projects",0,50,approval,connection,"host")',
    '        except PermissionError: pass',
    '        else: raise AssertionError("unauthorized request accepted")',
    '    remote.assert_not_called(); local.assert_not_called()',
    '    admin=Operator(True)',
    '    assert TarazAPI.tarazMadarDataRead(admin,"projects",0,50,True,connection,"host")["financialEventCreated"] is False',
    '    remote.assert_called_once_with(scope="projects",connection=connection,explicit_consent=True,offset=0,limit=50)',
    '    local.assert_not_called()',
    '    assert "admin" in admin.roles',
    'print("ACTUAL_API_ROLE_CONSENT_HOST_ONLY_PASS")',
  ]);
  assert.match(output,/ACTUAL_API_ROLE_CONSENT_HOST_ONLY_PASS/);
});

test('actual Madar reader checks TLS transport policy, ACL principal, revision and redaction',()=>{
  const output=python([
    'import taraz_madar_data_reader as r',
    'from unittest.mock import patch',
    'import json,hashlib',
    'conn={"url":"https://127.0.0.1:48370","fingerprint":"f"*64,"username":"operator","password":"synthetic-password"}',
    'principal={"username":"operator","role":"viewer","projects":["P1"]}',
    'state={"projects":[{"id":"P1","name":"Named project","secret":"HIDDEN-SECRET","price":"HIDDEN-PRICE"}],"tasks":[]}',
    'digest=hashlib.sha256(json.dumps(state,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()',
    'login={"token":"T"*40,"user":principal}',
    'snapshot={"state":state,"user":principal,"revision":digest}',
    'with patch.object(r,"_pinned_json",side_effect=[login,snapshot]) as calls:',
    '    view=r.read_authorized_madar_state(scope="projects",connection=conn,explicit_consent=True,offset=0,limit=50)',
    '    assert calls.call_count==2',
    '    assert calls.call_args_list[0].args[3:5]==("POST","/api/login")',
    '    assert calls.call_args_list[1].args[3:5]==("GET","/api/state")',
    '    assert view["items"]["projects"]==[{"id":"P1","name":"Named project"}]',
    '    assert view["source"]["serverAclApplied"] is True',
    '    assert view["source"]["revision"]==digest',
    '    assert view["financialEventCreated"] is False',
    '    raw=json.dumps(view)',
    '    for secret in ("synthetic-password","HIDDEN-SECRET","HIDDEN-PRICE","TTTT"): assert secret not in raw',
    'for tampered in ({**snapshot,"revision":"0"*64},{**snapshot,"user":{**principal,"projects":["P2"]}}):',
    '    with patch.object(r,"_pinned_json",side_effect=[login,tampered]):',
    '        try: r.read_authorized_madar_state(scope="projects",connection=conn,explicit_consent=True,offset=0,limit=50)',
    '        except r.MadarReadError: pass',
    '        else: raise AssertionError("tampered replay accepted")',
    'with patch.object(r,"_pinned_json") as calls:',
    '    for bad in ({**conn,"url":"http://127.0.0.1:48370"},{**conn,"url":"https://example.com:443"},{**conn,"fingerprint":""}):',
    '        try: r.read_authorized_madar_state(scope="projects",connection=bad,explicit_consent=True)',
    '        except r.MadarReadError: pass',
    '        else: raise AssertionError("unsafe network target accepted")',
    '    calls.assert_not_called()',
    'print("REAL_READER_PRINCIPAL_REVISION_REDACTION_PASS")',
  ]);
  assert.match(output,/REAL_READER_PRINCIPAL_REVISION_REDACTION_PASS/);
});

test('validly shaped replay with old readUtc is still accepted: freshness not proven',()=>{
  const replay=verifyMadarProjectPage(page({
    source:{...identity,readUtc:'2000-01-01T00:00:00Z'},
  }));
  assert.equal(replay.projects[0].id,'real-project-01');
  assert.equal(replay.readUtc,'2000-01-01T00:00:00Z');
  assert.equal(verifyMadarProjectPage(page()).revision,replay.revision);
});

test('archived build-777 predates admin gate; current source has both role checks',t=>{
  const frozenPicker=path.join(frozenRoot,'taraz_order_workspace.jsx');
  const frozenCaller=path.join(frozenRoot,'standalone_accounting_workspace.jsx');
  if(!fs.existsSync(frozenPicker)||!fs.existsSync(frozenCaller)){
    t.skip('Immutable build-777 source snapshot unavailable on this machine');
    return;
  }
  const current=fs.readFileSync(file,'utf8');
  const frozen=fs.readFileSync(frozenPicker,'utf8');
  const frozenContainer=fs.readFileSync(frozenCaller,'utf8');
  assert.match(current,/canAdmin&&<section className="taraz-orders-madar-picker"/);
  // Check archival provenance rather than treating an older, immutable build
  // as the release target for a newly compiled current-source Vite bundle.
  // These assertions also guard against an undocumented retroactive edit to
  // the historical snapshot.
  assert.equal(frozen.includes('canAdmin&&<section className="taraz-orders-madar-picker"'),
    false,'Historical build-777 unexpectedly changed');
  const frozenOrderProps=frozenContainer.match(/<TarazOrderWorkspace api=\{api\}[\s\S]*?\/>/)?.[0]||'';
  assert.equal(frozenOrderProps.includes('canAdmin={canAdmin}'),
    false,'Historical build-777 caller unexpectedly changed');
  const currentContainer=fs.readFileSync(path.join(root,'src',
    'standalone_accounting_workspace.jsx'),'utf8');
  const currentOrderProps=currentContainer.match(/<TarazOrderWorkspace api=\{api\}[\s\S]*?\/>/)?.[0]||'';
  assert.ok(currentOrderProps.includes('canAdmin={canAdmin}'),
    'Current caller must forward admin capability');
});

test('Edge admin-only picker: explicit consent, stale in-flight discard, no finance or credential persistence',async()=>{
  let playwright;
  try{playwright=require('playwright');}
  catch{playwright=require(path.join(process.env.APPDATA||'','npm','node_modules','playwright'));}
  const source=[
    "import React from 'react';",
    "import {createRoot} from 'react-dom/client';",
    "import Orders from './src/taraz_order_workspace.jsx';",
    "const isAdmin=new URLSearchParams(location.search).get('admin')!=='0';",
    "window.audit={reads:[],orders:[],finance:0,localWrites:0,delayedResolve:null};",
    "const originalSet=Storage.prototype.setItem;",
    "Storage.prototype.setItem=function(k,v){window.audit.localWrites++;return originalSet.call(this,k,v);};",
    "window.mode='good';",
    "window.result=(id='real-project-01')=>({connected:true,scope:'projects',offset:0,limit:50,",
    " counts:{projects:1},items:{projects:[{id,name:'پروژه واقعی مدار'}]},",
    " more:{projects:false},source:{kind:'madar-authorized-host-state-projection',",
    " serverAclApplied:true,readOnly:true,actor:'madar-user',revision:'a'.repeat(64)},",
    " financialEventCreated:false});",
    "const api={",
    " tarazOrderList:async()=>({orders:[],total:0,financialEventCreated:false}),",
    " tarazOrderCommand:async req=>{window.audit.orders.push(req);return {",
    " ...req.data,id:'c'.repeat(32),status:'draft',revision:1,financialEventCreated:false};},",
    " standaloneAccountingCommand:async()=>{window.audit.finance++;throw Error('finance prohibited');},",
    " tarazMadarDataRead:async(scope,offset,limit,consent,credentials,source)=>{",
    " window.audit.reads.push({scope,offset,limit,consent,source,hasPassword:!!credentials.password});",
    " if(window.mode==='pending')return new Promise(resolve=>window.audit.delayedResolve=resolve);",
    " if(window.mode==='badId')return window.result('bad\\u0000id');",
    " if(window.mode==='local')return {...window.result(),source:{",
    " kind:'madar-local-appdata-tasks-json',serverAclApplied:false,readOnly:true,",
    " actor:'madar-user',revision:'a'.repeat(64)}};",
    " return window.result();",
    " }};",
    "createRoot(document.getElementById('root')).render(",
    "<Orders api={api} canEdit={true} canAdmin={isAdmin} currency='RIAL'/>);",
  ].join('\n');
  const output=(await esbuild.build({stdin:{contents:source,resolveDir:root,
      sourcefile:'taraz-v106-contract-qa.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',outdir:'synthetic-out',
    write:false,logLevel:'silent'})).outputFiles;
  const script=output.find(f=>f.path.endsWith('.js')).text;
  const css=output.find(f=>f.path.endsWith('.css'))?.text||'';
  const html='<html lang="fa" dir="rtl"><head><meta charset="utf-8"><style>'+
    css+'</style></head><body><div id="root"></div><script>'+
    script+'</script></body></html>';
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-sandbox','--disable-extensions']});
  try{
    const context=await browser.newContext();
    await context.route('**/*',route=>
      route.request().url().startsWith('https://taraz-v106-qa.invalid/')?
        route.fulfill({status:200,contentType:'text/html',body:html}):route.abort());
    const viewer=await context.newPage();
    viewer.setDefaultTimeout(7000);
    await viewer.goto('https://taraz-v106-qa.invalid/?admin=0');
    await viewer.getByRole('button',{name:'حرفه‌ای'}).click();
    assert.equal(await viewer.getByRole('region',{name:'انتخاب پروژه واقعی مدار'}).count(),0);
    assert.equal(await viewer.evaluate(()=>window.audit.reads.length),0);
    await viewer.close();

    const page=await context.newPage();
    page.setDefaultTimeout(7000);
    await page.goto('https://taraz-v106-qa.invalid/?admin=1');
    await page.getByRole('button',{name:'حرفه‌ای'}).click();
    const picker=page.getByRole('region',{name:'انتخاب پروژه واقعی مدار'});
    assert.equal(await page.evaluate(()=>window.audit.reads.length),0);
    await picker.getByRole('checkbox',{name:/خواندن درخواستی/}).check();
    assert.equal(await page.evaluate(()=>window.audit.reads.length),0);
    await picker.getByRole('textbox',{name:'نشانی HTTPS میزبان مدار'})
      .fill('https://127.0.0.1:48370');
    await picker.getByRole('textbox',{name:'اثر انگشت SHA-256 گواهی'})
      .fill('a'.repeat(64));
    await picker.getByRole('textbox',{name:'نام کاربری مدار'}).fill('operator');
    const secret='SYNTHETIC-MADAR-PASSWORD';
    await picker.getByRole('textbox',{name:'گذرواژه مدار'}).fill(secret);
    assert.equal(await page.evaluate(()=>window.audit.reads.length),0);
    await picker.getByRole('button',{name:'خواندن پروژه‌های مجاز مدار'}).click();
    await picker.getByRole('combobox',{name:'پروژه مدار'}).waitFor();
    assert.deepEqual(await page.evaluate(()=>window.audit.reads),[{
      scope:'projects',offset:0,limit:50,consent:true,source:'host',hasPassword:true,
    }]);
    const ref=page.getByRole('textbox',{name:/ارجاع پروژه مرتبط/});
    assert.equal(await ref.inputValue(),'');
    await picker.getByRole('combobox',{name:'پروژه مدار'}).selectOption('real-project-01');
    assert.equal(await ref.inputValue(),'');
    assert.equal(await page.evaluate(()=>window.audit.orders.length),0);
    await picker.getByRole('button',{name:'اعمال شناسه انتخاب‌شده به سفارش'}).click();
    assert.equal(await ref.inputValue(),'real-project-01');
    assert.equal(await page.evaluate(()=>window.audit.orders.length),0);
    await page.getByRole('textbox',{name:'نام مشتری'}).fill('مشتری تست');
    await page.getByRole('textbox',{name:'شرح سفارش'}).fill('چاپ تست');
    await page.getByRole('textbox',{name:'تعداد سفارش'}).fill('100');
    await page.getByRole('textbox',{name:'تعداد برنامه‌ریزی تولید'}).fill('120');
    await page.getByRole('button',{name:'ذخیره سفارش'}).click();
    await page.getByText('سفارش در میزبان ذخیره شد. هیچ سند مالی ایجاد نشده است.').waitFor();
    const result=await page.evaluate(()=>window.audit);
    assert.equal(result.orders.length,1);
    assert.equal(result.orders[0].action,'create');
    assert.equal(result.orders[0].data.projectReference,'real-project-01');
    assert.equal(result.orders[0].manualConfirmation,false);
    assert.equal(result.finance,0);
    assert.equal(result.localWrites,0);
    assert.equal(JSON.stringify(result.orders).includes(secret),false);
    assert.equal(JSON.stringify(result.orders).includes('fingerprint'),false);

    await page.evaluate(()=>window.mode='badId');
    await picker.getByRole('button',{name:'خواندن پروژه‌های مجاز مدار'}).click();
    await picker.getByRole('alert').waitFor();
    assert.equal(await picker.getByRole('combobox',{name:'پروژه مدار'}).count(),0);
    await page.evaluate(()=>window.mode='local');
    await picker.getByRole('button',{name:'خواندن پروژه‌های مجاز مدار'}).click();
    await picker.getByRole('alert').waitFor();
    assert.equal(await picker.getByRole('combobox',{name:'پروژه مدار'}).count(),0);

    // A delayed request must be ignored if credentials change after its start.
    await page.evaluate(()=>window.mode='pending');
    await picker.getByRole('button',{name:'خواندن پروژه‌های مجاز مدار'}).click();
    await page.waitForFunction(()=>typeof window.audit.delayedResolve==='function');
    await picker.getByRole('textbox',{name:'نام کاربری مدار'}).fill('newoperator');
    await page.evaluate(()=>window.audit.delayedResolve(window.result('stale-project')));
    await page.waitForTimeout(120);
    assert.equal(await picker.getByRole('combobox',{name:'پروژه مدار'}).count(),0);
    assert.equal(await ref.inputValue(),'real-project-01');
    await picker.getByRole('checkbox',{name:/خواندن درخواستی/}).uncheck();
    assert.equal(await picker.getByRole('textbox',{name:'گذرواژه مدار'}).count(),0);
    assert.equal(await page.evaluate(()=>window.audit.localWrites),0);
    await page.reload();
    await page.getByRole('button',{name:'حرفه‌ای'}).click();
    const newPicker=page.getByRole('region',{name:'انتخاب پروژه واقعی مدار'});
    assert.equal(await newPicker.getByRole('checkbox',{name:/خواندن درخواستی/}).isChecked(),false);
    assert.equal(await page.evaluate(()=>localStorage.length+sessionStorage.length),0);
  }finally{await browser.close();}
});
