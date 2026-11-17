'use strict';
/**
 * Real current Taraz React Chromium buttons -> Playwright exposeFunction ->
 * Python child -> exact SHA-pinned installed Taraz 1.0.0 API code objects.
 * All persistent writes stay within an existing disposable QA Inbox.
 * No installed EXE launch, finance ledger, real user profile or network.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');
const execFileAsync = promisify(execFile);
const TARAZ = path.resolve(__dirname,'..');
const MADAR = path.resolve(TARAZ,'..','..','000- Madar',
  'madar-p2-gantt-notifications-20261107');
const CLI = path.join(MADAR,'scripts','qa_taraz_shipped_api_cli_20261110.py');
const HASH = 'de5005579039bd86890c1dca1f5f1d9c760e6c47579a42f649f80096f158e70c';
const modules = path.join(MADAR,'node_modules');
const esbuild = require(path.join(modules,'esbuild'));
const playwright = (() => {
  try {return require(path.join(modules,'playwright'));}
  catch {
    // Read-only installed QA dependency, NOT a ledger. Prime may supply an
    // explicit path if USERPROFILE is already redirected to a QA sandbox.
    const supplied=process.env.MTR_QA_PLAYWRIGHT_MODULES;
    const home=process.env.USERPROFILE || process.env.HOME;
    const candidate=supplied ?
      path.join(supplied,'playwright') :
      path.join(home||'', 'AppData','Roaming','npm','node_modules','playwright');
    return require(candidate);
  }
})();
const fail = message => {throw Error(message);};
function checkDir(p) {
  const st=fs.lstatSync(p);
  if(!st.isDirectory()||st.isSymbolicLink()||
     fs.realpathSync.native(p)!==path.resolve(p))fail('Unsafe QA directory');
}
function parseArgs(argv) {
  const allowed=new Set(['--bridge','--id','--programs','--python','--reject']);
  const options=new Map();
  for(let i=0;i<argv.length;i++){
    const k=argv[i];
    if(!allowed.has(k)||options.has(k))fail('Unknown/duplicate QA argument');
    if(k==='--reject'){options.set(k,true);continue;}
    if(i+1>=argv.length || argv[i+1].startsWith('--'))fail('Missing QA argument value');
    options.set(k,argv[++i]);
  }
  const id=options.get('--id');
  if(typeof id!=='string'||!/^[0-9a-f]{32}$/.test(id))fail('Invalid bound QA proposal ID');
  const arg=options.get('--bridge');
  if(typeof arg!=='string'||!path.isAbsolute(arg))fail('QA bridge must be absolute');
  const bridge=path.resolve(arg),local=path.dirname(bridge);
  const root=path.dirname(path.dirname(local));
  if(!/^madar-qa-taraz-bridge-ui-[a-zA-Z0-9_-]{4,80}$/.test(path.basename(root))||
     bridge!==path.join(root,'AppData','Local','Madar-Taraz-Bridge'))
    fail('QA bridge is not exact disposable folder layout');
  const temp=path.resolve(process.env.TEMP||os.tmpdir());
  if(![path.dirname(root),path.join(root,'Temp')].includes(temp))
    fail('QA root does not belong to current disposable temp environment');
  for(const part of [root,path.join(root,'AppData'),local,
       path.join(root,'AppData','Roaming'),path.join(root,'Temp'),bridge,
       path.join(bridge,'pending')])checkDir(part);
  const programs=options.get('--programs')||
    process.env.MTR_QA_INSTALLED_PROGRAMS_ROOT||
    (process.env.LOCALAPPDATA&&path.join(process.env.LOCALAPPDATA,'Programs'));
  if(typeof programs!=='string'||!path.isAbsolute(programs)||
     path.basename(programs)!=='Programs')fail('Explicit installed Programs directory needed');
  checkDir(programs);
  if(!fs.statSync(CLI).isFile()||fs.lstatSync(CLI).isSymbolicLink())
    fail('Read-only packaged API CLI unavailable');
  const python=options.get('--python')||'py';
  if(typeof python!=='string'||!python.trim())fail('Missing Python executable');
  return {root,bridge,id,programs,python,
    decision:options.has('--reject')?'rejected':'reviewed'};
}
function parseContract(stdout,action){
  if(typeof stdout!=='string'||stdout.length>32768)fail('Invalid backend JSON size');
  const lines=stdout.trim().split(/\r?\n/);
  if(lines.length!==1)fail('Backend returned multiple lines');
  const obj=JSON.parse(lines[0]);
  if(!obj||typeof obj!=='object'||Array.isArray(obj)||
     obj.schemaVersion!==1||obj.action!==action||
     obj.backend!=='SHA_PINNED_TARAZ_1_0_0_BYTECODE'||
     obj.installedTarazExeSha256!==HASH||
     obj.syntheticPrincipalOnly!==true||
     obj.installedExeLaunched!==false||obj.officialFinancePosted!==false||
     obj.durableSourceDigestIntentPresent!==false||
     !/^[0-9a-f]{64}$/.test(obj.qaProposalSourceSha256||''))
    fail('Backend did not prove exact shipped Taraz code');
  if(action==='preflight'){
    if(obj.packagedMethodCodeLoaded!==true||
       obj.inboxMethodInvoked!==false||obj.reviewMethodInvoked!==false)
      fail('Preflight cannot invoke Inbox or Review');
    return obj;
  }
  if(obj.actualPackagedTarazApiInvoked!==true||!obj.data||
     typeof obj.data!=='object'||Array.isArray(obj.data))
    fail('No shipped Taraz API invocation');
  if(action==='list'){
    if(obj.data.connected!==true||obj.data.invalidCount!==0||
       !Array.isArray(obj.data.requests)||obj.data.requests.length>1)
      fail('Invalid shipped Taraz Inbox result');
  }else if(obj.data.financialEventCreated!==false){
    fail('Invalid finance-event assertion from backend');
  }
  return {data:obj.data,sourceSha256:obj.qaProposalSourceSha256};
}
async function callNative(config,action,decision=null){
  const args=['-3.12','-B',CLI,'--action',action,'--bridge',config.bridge,
    '--programs',config.programs,'--id',config.id,'--role','editor'];
  if(action==='review')args.push('--decision',decision);
  const env={...process.env,
    APPDATA:path.join(config.root,'AppData','Roaming'),
    LOCALAPPDATA:path.join(config.root,'AppData','Local'),
    TEMP:path.join(config.root,'Temp'),TMP:path.join(config.root,'Temp'),
    USERPROFILE:config.root,HOME:config.root,PYTHONDONTWRITEBYTECODE:'1'};
  let stdout;
  try {
    ({stdout}=await execFileAsync(config.python,args,{
      cwd:MADAR,env,windowsHide:true,timeout:25000,maxBuffer:32768,
      encoding:'utf8'}));
  }catch(error){
    let reason='CHILD_PROCESS_FAILURE';
    try {
      const denied=JSON.parse(String(error?.stdout||'').trim());
      if(denied?.status==='DENIED'&&denied?.schemaVersion===1&&
         denied.action===action&&
         ['AUTH_DENIED','QA_BLOCKED'].includes(denied.errorCode)){
        reason=denied.errorCode+':'+
          (typeof denied.phase==='string'&&/^[A-Z_a-z]{1,36}$/.test(denied.phase)
            ? denied.phase:'UNCLASSIFIED')+':'+
          (typeof denied.reasonCode==='string'&&/^[A-Z_]{1,48}$/.test(denied.reasonCode)
            ? denied.reasonCode:'UNCLASSIFIED_REASON');
      }
    }catch{}
    throw Error('PACKAGED_API_'+action.toUpperCase()+'_'+reason);
  }
  try {
    return parseContract(stdout,action);
  }catch(error){
    throw Error('PACKAGED_API_'+action.toUpperCase()+'_CONTRACT_INVALID');
  }
}
async function buildReact(){
  const entry=[
    "import React from 'react';",
    "import {createRoot} from 'react-dom/client';",
    "import TarazSettings from './src/taraz_settings.jsx';",
    "const api={",
    " tarazIntegrationList:()=>window.__qaNativeTaraz('list',null,null),",
    " tarazIntegrationReview:(id,decision)=>window.__qaNativeTaraz('review',id,decision),",
    "};",
    "createRoot(document.getElementById('root')).render(",
    " <TarazSettings api={api} canManage={true} canDraft={true}/>);"
  ].join('\n');
  const files=(await esbuild.build({
    stdin:{contents:entry,resolveDir:TARAZ,
      sourcefile:'qa-shipped-taraz-ui.jsx',loader:'jsx'},
    platform:'browser',format:'iife',bundle:true,write:false,
    outdir:'qa-shipped-taraz-ui',logLevel:'silent',charset:'utf8',
    loader:{'.css':'css','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'},
    plugins:[{name:'read-only-react-deps',setup(build){
      build.onResolve({filter:/^(react|react-dom\/client|react\/jsx-runtime|lucide-react)$/},
        a=>({path:require.resolve(a.path,{paths:[modules]})}));
    }}]
  })).outputFiles;
  const js=files.find(f=>f.path.endsWith('.js'))?.text;
  if(!js)fail('Current real Taraz JSX could not be compiled');
  return {js,css:files.find(f=>f.path.endsWith('.css'))?.text||''};
}
async function run(config) {
  let stage='preflight';
  let nativeFailure='NONE';
  const report={
    schemaVersion:1,status:'PASS',
    scope:'CURRENT_TARAZ_CHROMIUM_TO_SHA_PINNED_INSTALLED_TARAZAPI_CODE',
    installedTarazExeSha256:HASH,proposalId:config.id,decision:config.decision,
    syntheticPrincipalOnly:true,installedTarazExeLaunched:false,
    officialTarazReceiptVerified:false,financialEventCreated:false,
    realProfileAccessed:false,externalNetworkUsed:false,
    inboxAutomaticReads:0,nativeInboxReads:0,nativeReviewCalls:0,
    explicitManualOptIn:false,secondConfirmation:false,
    shippedReviewCalledByBrowser:false,readbackAfterReview:false,
    qaSourceDigestMatchedBeforeAndAfterMove:false,
    durableIntentMarkerPresent:false,crashRecoveryParityWithCurrentSource:false
  };
  const pre=await callNative(config,'preflight');
  assert.equal(pre.packagedMethodCodeLoaded,true);
  const initialSha=pre.qaProposalSourceSha256;
  const assets=await buildReact();
  const invocations=[];
  let context;
  try{
    stage='chromium_launch';
    const profile=path.join(config.root,'TarazBrowserQaProfile');
    if(fs.existsSync(profile))fail('QA browser profile already exists');
    context=await playwright.chromium.launchPersistentContext(profile,{
      channel:'msedge',headless:true,viewport:{width:1280,height:900},
      args:['--no-first-run','--disable-background-networking',
            '--disable-default-apps','--disable-sync']
    });
    await context.route('**/*',route=>route.abort());
    const page=context.pages()[0]||await context.newPage();
    await page.exposeFunction('__qaNativeTaraz',async(action,id,decision)=>{
      const operation=action;
      try {
      if(action==='list'){
        if(id!==null||decision!==null||report.nativeInboxReads>=2)
          fail('Unexpected additional native Inbox read');
        const answered=await callNative(config,'list');
        const data=answered.data;
        if(answered.sourceSha256!==initialSha)
          fail('Source proposal digest changed during shipped Inbox read');
        report.nativeInboxReads++;
        invocations.push('list');
        if(report.nativeInboxReads===1){
          if(data.requests.length!==1||data.requests[0].id!==config.id)
            fail('Shipped Taraz Inbox returned unexpected proposal');
        }else{
          if(report.nativeReviewCalls!==1||data.requests.length!==0)
            fail('Shipped Taraz did not read back consumed proposal');
          report.readbackAfterReview=true;
        }
        return data;
      }
      if(action==='review'){
        if(id!==config.id||decision!==config.decision||
           report.nativeInboxReads!==1||report.nativeReviewCalls!==0)
          fail('Unauthorized or duplicate native Review attempt');
        const answered=await callNative(config,'review',decision);
        const data=answered.data;
        if(answered.sourceSha256!==initialSha)
          fail('Source proposal digest changed across shipped metadata review');
        if(data.id!==config.id||data.state!==config.decision||
           data.financialEventCreated!==false)
          fail('Shipped Taraz review returned invalid receipt');
        report.nativeReviewCalls++;
        report.shippedReviewCalledByBrowser=true;
        invocations.push('review');
        return data;
      }
      fail('Unexpected browser-to-native operation');
      }catch(error){
        nativeFailure=operation.toUpperCase()+':'+
          String(error?.message||error).replace(/[^A-Z0-9_:]/g,'_').slice(0,120);
        throw error;
      }
    });
    stage='mount_current_react';
    await page.setContent('<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><main id="root"></main></body></html>');
    if(assets.css)await page.addStyleTag({content:assets.css});
    await page.addScriptTag({content:assets.js});
    stage='navigate_integration';
    await page.getByRole('button',{name:'اتصال به مدار'}).click();
    assert.equal(report.nativeInboxReads,0,'Settings navigation triggered automatic read');
    assert.equal(report.nativeReviewCalls,0);
    const consent=page.getByRole('checkbox',{name:/ارجاع‌های مدار را دستی بررسی کنم/});
    const refresh=page.getByRole('button',{name:'بررسی وضعیت اتصال'});
    assert.equal(await refresh.isDisabled(),true,'Consent must be opt-in');
    await consent.check();
    report.explicitManualOptIn=await consent.isChecked();
    assert.equal(report.nativeInboxReads,0,'Opt-in alone triggered read');
    assert.equal(await refresh.isEnabled(),true);
    stage='manual_refresh';
    await refresh.click();
    stage='await_visible_native_inbox_row';
    try{
      await page.getByRole('button',{
        name:config.decision==='reviewed'?'بررسی شد':'رد ارجاع'
      }).waitFor({timeout:10000});
    }catch(error){
      const alerts=await page.locator('[role="alert"]').count();
      const inboxSummary=await page.locator('.taraz-settings-connection-summary').count();
      const requestCount=await page.locator('.taraz-settings-request').count();
      throw Error('STAGE_'+stage.toUpperCase()+
        '_NATIVE_'+nativeFailure+
        '_READS_'+report.nativeInboxReads+
        '_REVIEWS_'+report.nativeReviewCalls+
        '_ALERTS_'+alerts+'_SUMMARY_'+inboxSummary+
        '_REQUESTS_'+requestCount);
    }
    assert.equal(report.nativeInboxReads,1);
    assert.equal(report.nativeReviewCalls,0);
    stage='review_choice';
    await page.getByRole('button',{name:config.decision==='reviewed'?'بررسی شد':'رد ارجاع'}).click();
    report.secondConfirmation=await page.getByRole('group',{name:'تأیید تصمیم ارجاع'}).isVisible();
    assert.equal(report.nativeReviewCalls,0,'Selection must not invoke native review');
    stage='second_confirmation';
    await page.getByRole('button',{name:'تأیید تصمیم'}).click();
    try {
      await page.getByText('ارجاع در صندوق اتصال بررسی شد. هیچ سند مالی ایجاد نشد.').waitFor({timeout:7500});
      // UI sets success *before* awaiting its post-decision Inbox refresh.
      // Wait for the real packaged readback to render, not the optimistic label.
      await page.getByText('ارجاع بررسی‌نشده‌ای در صندوق وجود ندارد.').waitFor({timeout:7500});
    }catch(error){
      const message=await page.locator('body').innerText();
      fail('Native review did not reach UI success: reads='+
        report.nativeInboxReads+', reviews='+report.nativeReviewCalls+
        ', visible='+message.slice(-850));
    }
    assert.equal(report.nativeInboxReads,2);
    assert.equal(report.nativeReviewCalls,1);
    assert.equal(report.readbackAfterReview,true);
    assert.deepEqual(invocations,['list','review','list']);
    report.qaSourceDigestMatchedBeforeAndAfterMove=true;
    stage='completed';
    report.actualCurrentReactChromiumClicked=true;
    report.explicitManualRefresh=true;
    return report;
  }finally{
    if(context)await context.close();
  }
}
if(require.main===module){
  (async()=>{
    const result=await run(parseArgs(process.argv.slice(2)));
    process.stdout.write(JSON.stringify(result)+'\n');
  })().catch(error=>{
    process.stderr.write('Taraz packaged native browser QA blocked: '+
      String(error?.message||error).slice(0,400)+'\n');
    process.exitCode=2;
  });
}
module.exports={parseArgs,parseContract,callNative,run};
