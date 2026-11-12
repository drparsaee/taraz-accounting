const test=require('node:test');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const fs=require('node:fs');
const pref=import(pathToFileURL(path.join(__dirname,'../src/taraz_settings_preferences.js')).href);
const bridge=import(pathToFileURL(path.join(__dirname,'../src/taraz_settings_integration.js')).href);

function memoryStorage(initial={}){
  const data=new Map(Object.entries(initial));
  return {getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v),values:data};
}

test('user preferences normalize unexpected values and preserve valid choices',async()=>{
  const {normalizeTarazSettings}=await pref;
  assert.deepEqual(normalizeTarazSettings({theme:'system',font:'vazirmatn',size:'large',
    width:'wide',motion:'reduce'}),{
    theme:'system',font:'vazirmatn',size:'large',width:'wide',motion:'reduce'});
  const normalized=normalizeTarazSettings({theme:'pay',font:'unknown'});
  assert.equal(normalized.theme,'dark');
  assert.equal(normalized.font,'estedad');
  assert.equal(normalized.width,'comfortable');
  assert.equal(normalizeTarazSettings(null).theme,'dark');
});

test('settings persist, apply real document attributes and honor system dark mode',async()=>{
  const {readTarazSettings,saveTarazSettings,applyTarazSettings,effectiveTarazTheme}=await pref;
  const storage=memoryStorage({'taraz-ui-theme':'light'});
  const root={dataset:{}};
  assert.equal(readTarazSettings(storage).theme,'light');
  const next=saveTarazSettings({theme:'system',font:'tahoma',size:'large',
    width:'wide',motion:'reduce'},{storage,root,systemDark:true,emit:false});
  assert.equal(root.dataset.theme,'dark');
  assert.equal(root.dataset.tarazSize,'large');
  assert.equal(root.dataset.tarazWidth,'wide');
  assert.equal(root.dataset.tarazMotion,'reduce');
  assert.deepEqual(readTarazSettings(storage),next);
  assert.equal(storage.getItem('taraz-ui-theme'),'system');
  applyTarazSettings(next,root,false);
  assert.equal(root.dataset.theme,'light');
  assert.equal(effectiveTarazTheme('dark',false),'dark');
});

test('bridge status reads only by explicit invocation and validates metadata',async()=>{
  const {integrationCapabilities,listTarazIntegration}=await bridge;
  let listCalls=0;let ledgerCalls=0;
  const api={
    standaloneAccountingCommand:()=>ledgerCalls++,
    tarazIntegrationList:async()=>{
      listCalls++;
      return {connected:true,invalidCount:1,requests:[
        {id:'EX-1',taskId:'TASK-1',title:'synthetic request'},
        {id:null,taskId:'bad',title:'invalid'}]};
    }
  };
  assert.deepEqual(integrationCapabilities(api),{canList:true,canReview:false,canRecover:false});
  assert.equal(listCalls,0);
  const result=await listTarazIntegration(api);
  assert.equal(listCalls,1);
  assert.equal(result.requests.length,1);
  assert.equal(result.requests[0].title,'synthetic request');
  assert.equal(ledgerCalls,0);
  await assert.rejects(()=>listTarazIntegration({}),/در دسترس نیست/);
  await assert.rejects(()=>listTarazIntegration({
    tarazIntegrationList:async()=>({connected:'yes',requests:[]})
  }),/معتبر نیست/);
});

test('bridge review allows only explicit reviewed/rejected acknowledgement and no ledger command',async()=>{
  const {reviewTarazIntegration}=await bridge;
  const calls=[];
  const api={
    standaloneAccountingCommand:()=>{throw Error('ledger must not be called');},
    tarazIntegrationReview:async(id,decision)=>{
      calls.push([id,decision]);return {id,state:decision,financialEventCreated:false};
    }
  };
  await assert.rejects(()=>reviewTarazIntegration(api,'X','approved'),/معتبر نیست/);
  assert.equal(calls.length,0);
  assert.deepEqual(await reviewTarazIntegration(api,'EX-1','reviewed'),
    {id:'EX-1',state:'reviewed',financialEventCreated:false});
  assert.deepEqual(calls,[['EX-1','reviewed']]);
  await assert.rejects(()=>reviewTarazIntegration({
    tarazIntegrationReview:async()=>({id:'EX-1',state:'rejected',financialEventCreated:true})
  },'EX-1','rejected'),/بدون ثبت مالی/);
});

test('recovery is an explicit manual nonfinancial native action and not a redecision',async()=>{
  const {listTarazIntegration,recoverTarazIntegration}=await bridge;
  const id='a'.repeat(32), calls=[];
  const api={
    standaloneAccountingCommand:()=>{throw Error('ledger must not be called');},
    tarazIntegrationList:async()=>({connected:true,requests:[],recovery:[
      {id,taskId:'task-1',title:'Synthetic restart',state:'reviewed',financialEventCreated:false},
      {id:'forged',taskId:'task-1',title:'bad',state:'reviewed',financialEventCreated:false},
    ]}),
    tarazIntegrationRecover:async(key,manual)=>{
      calls.push([key,manual]);return {id:key,state:'reviewed',financialEventCreated:false};
    },
  };
  const listed=await listTarazIntegration(api);
  assert.equal(listed.recovery.length,1);
  assert.equal(calls.length,0);
  assert.deepEqual(await recoverTarazIntegration(api,id,'reviewed'),
    {id,state:'reviewed',financialEventCreated:false});
  assert.deepEqual(calls,[[id,true]]);
  await assert.rejects(()=>recoverTarazIntegration(api,id,'rejected'),/پایدار/);
  await assert.rejects(()=>recoverTarazIntegration(api,'forged','reviewed'),/معتبر نیست/);
  await assert.rejects(()=>recoverTarazIntegration({},id,'reviewed'),/در دسترس نیست/);
});

test('settings are a dedicated tab and never link payment or ledger calls',()=>{
  const base=path.join(__dirname,'../src');
  const app=fs.readFileSync(path.join(base,'standalone_accounting_workspace.jsx'),'utf8');
  const settings=fs.readFileSync(path.join(base,'taraz_settings.jsx'),'utf8');
  assert.match(app,/tab==='settings'&&<TarazSettings/);
  assert.match(settings,/tarazIntegrationList|listTarazIntegration/);
  assert.match(settings,/اشتراک و خرید/);
  assert.match(settings,/خرید اشتراک \(غیرفعال\)/);
  assert.doesNotMatch(settings,/standaloneAccountingCommand|http:\/\/|https:\/\//);
});
