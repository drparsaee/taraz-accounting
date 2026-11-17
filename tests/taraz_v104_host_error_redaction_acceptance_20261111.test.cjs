'use strict';
/** Taraz v104 *compiled* error-message acceptance. No source-only fallback.
 * Explicit TARAZ_V104_BUILD_DIR selects one detached, finished build. The
 * parent path, EXE PE/PYZ versions, and embedded JS identity are release gates.
 * A missing/unbuilt candidate MUST fail the test rather than skip it.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const parent=String.raw`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1`;
const oldJsSha='001e9e7e622fee9cc375461b754847a978c0b16563a72a4cd8e5d784ca8512b4';
const oldExeSha='e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c';
const pinnedStageFingerprint='6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1';
const pinnedStageJsSha='b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453';
const secret='QA-V104-HOST-SECRET-91317';
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const readJson=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const fail=why=>{throw Error('BLOCKED_V104_COMPILED_ACCEPTANCE: '+why);};
const requireFile=p=>{if(!fs.statSync(p,{throwIfNoEntry:false})?.isFile())fail('missing file '+p);return p;};
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'', 'npm','node_modules','playwright'));}

function compiledArtifact(){
  const selected=process.env.TARAZ_V104_BUILD_DIR?.trim();
  if(!selected)fail('set TARAZ_V104_BUILD_DIR to an explicit finished v1.0.4 build directory');
  if(!path.win32.isAbsolute(selected))fail('build path must be absolute');
  const expected=fs.realpathSync.native(parent);
  const build=fs.realpathSync.native(selected);
  if(path.win32.normalize(path.dirname(build)).toLowerCase()!==
    path.win32.normalize(expected).toLowerCase() ||
    !/^build-[a-z0-9-]+$/i.test(path.basename(build))){
    fail('build must be a direct build-* child of '+parent+'; source-stage/v103 paths refused');
  }
  const report=readJson(requireFile(path.join(build,'build-report.json')));
  if(report.version!=='1.0.4'||report.status!=='PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED'||
    report.installed!==false||report.pointerChanged!==false){
    fail('build report lacks a completed uninstalled v1.0.4 non-QA candidate status');
  }
  const pkg=readJson(requireFile(path.join(build,'source','package.json')));
  if(pkg.version!=='1.0.4')fail('source package version is not v1.0.4');
  const html=fs.readFileSync(requireFile(path.join(build,'web','dist','accounting.html')),'utf8');
  const script=html.match(/\bsrc=["']\.\/assets\/([^"']+\.js)["']/);
  const style=html.match(/\bhref=["']\.\/assets\/([^"']+\.css)["']/);
  if(!script||!style)fail('compiled accounting.html asset links not found');
  const scriptRelative='assets/'+script[1],cssRelative='assets/'+style[1];
  const js=fs.readFileSync(requireFile(path.join(build,'web','dist',...scriptRelative.split('/'))));
  const css=fs.readFileSync(requireFile(path.join(build,'web','dist',...cssRelative.split('/'))));
  const exe=requireFile(path.join(build,'binary','Taraz.exe'));
  const exeSha=sha(fs.readFileSync(exe));
  const jsSha=sha(js);
  if(exeSha===oldExeSha||jsSha===oldJsSha)fail('v1.0.3 frozen binaries/assets refused as v1.0.4');
  if(report.compiled?.peVersion!=='1.0.4.0'||
    report.compiled?.pyzVersion!=='1.0.4'||report.compiled?.nonQaRuntime!==true)
    fail('build-report lacks 1.0.4 PE/PYZ and non-QA evidence');
  const helper=String.raw`import sys,json,hashlib,ctypes,types
from PyInstaller.archive.readers import CArchiveReader
exe,name=sys.argv[1:]
a=CArchiveReader(exe)
blob=a.extract('dist\\'+name.replace('/','\\'))
pyz=a.open_embedded_archive('PYZ.pyz')
code=pyz.extract('taraz_release_version')
if not isinstance(code,types.CodeType): raise RuntimeError('missing release Python code')
v=ctypes.windll.version
v.GetFileVersionInfoSizeW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)]
v.GetFileVersionInfoSizeW.restype=ctypes.c_ulong
n=v.GetFileVersionInfoSizeW(exe,ctypes.byref(ctypes.c_ulong()))
if not n: raise RuntimeError('PE version resource absent')
buf=ctypes.create_string_buffer(n)
v.GetFileVersionInfoW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
v.GetFileVersionInfoW.restype=ctypes.c_int
if not v.GetFileVersionInfoW(exe,0,n,buf): raise RuntimeError('PE version unreadable')
ptr,length=ctypes.c_void_p(),ctypes.c_uint()
v.VerQueryValueW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_uint)]
v.VerQueryValueW.restype=ctypes.c_int
if not v.VerQueryValueW(buf,'\\',ctypes.byref(ptr),ctypes.byref(length)):raise RuntimeError('PE fixed version missing')
w=ctypes.cast(ptr,ctypes.POINTER(ctypes.c_uint32))
if w[0]!=0xFEEF04BD:raise RuntimeError('PE signature invalid')
pe=f'{w[2]>>16}.{w[2]&65535}.{w[3]>>16}.{w[3]&65535}'
print(json.dumps({'assetSha':hashlib.sha256(blob).hexdigest(),
  'assetBytes':len(blob),'peVersion':pe,'pyzCodeHas104':'1.0.4' in code.co_consts,
  'pyzAppVersionName':'APP_VERSION' in code.co_names,
  'pyzQaOnlyName':'QA_ONLY' in code.co_names}))`;
  const run=spawnSync('py',['-3.12','-B','-c',helper,exe,scriptRelative],
    {encoding:'utf8',timeout:40000});
  if(run.status!==0)fail('read-only EXE inspection failed: '+(run.stderr||run.stdout).slice(0,400));
  const native=JSON.parse(run.stdout.trim());
  if(native.assetSha!==jsSha||native.assetBytes!==js.byteLength||
    native.peVersion!=='1.0.4.0'||native.pyzCodeHas104!==true||
    native.pyzAppVersionName!==true||native.pyzQaOnlyName!==true){
    fail('actual executable embedded JS / PE / release PYZ differs from v1.0.4 build');
  }
  return {build,js:js.toString('utf8'),css:css.toString('utf8'),exeSha,jsSha};
}

function stageUiArtifact(){
  const chosen=process.env.TARAZ_V104_STAGE_DIR?.trim();
  if(!chosen)fail('TARAZ_V104_STAGE_DIR unset');
  if(!path.win32.isAbsolute(chosen))fail('v104 Vite stage path must be absolute');
  const expected=fs.realpathSync.native(parent);
  const stage=fs.realpathSync.native(chosen);
  if(path.win32.normalize(path.dirname(stage)).toLowerCase()!==
    path.win32.normalize(expected).toLowerCase()||
    !/^vite-qa-[a-z0-9]+$/i.test(path.basename(stage)))
    fail('Vite QA directory must be a direct vite-qa-* child of v104 root');
  const attestationPath=requireFile(path.join(stage,'vite-qa-report.json'));
  const report=readJson(attestationPath);
  if(report.status!=='STAGE_UI_ONLY'||report.compiledFrontend!==true||
    report.compiledExeBuilt!==false||report.compiledBundleReleaseReady!==false||
    report.installedTarazTouched!==false||report.sourceShaBeforeAfterIdentical!==true||
    report.patchedSourceSha256!==pinnedStageFingerprint||
    report.viteJsSha256!==pinnedStageJsSha||
    report.browserQaVerified!==false)
    fail('Vite stage attestation is not a recognized frozen source-only QA build');
  const sourceStage=fs.realpathSync.native(report.sourceStagePath||'');
  if(path.win32.normalize(path.dirname(sourceStage)).toLowerCase()!==
    path.win32.normalize(expected).toLowerCase()||
    !/^source-stage-[a-z0-9]+$/i.test(path.basename(sourceStage)))
    fail('Vite source stage must be a detached v104 source-stage-* directory');
  const stageReportPath=requireFile(path.join(sourceStage,'stage-report.json'));
  const inventoryPath=requireFile(path.join(sourceStage,'patched-source-sha256.json'));
  if(sha(fs.readFileSync(stageReportPath))!==report.sourceStageReportSha256||
    sha(fs.readFileSync(inventoryPath))!==report.sourceInventorySha256)
    fail('detached source stage report or inventory changed after Vite build');
  const sourceReport=readJson(stageReportPath);
  const inventory=readJson(inventoryPath);
  if(sourceReport.status!=='V104_PATCHED_SOURCE_FROZEN_QA_PENDING_NO_EXE'||
    sourceReport.executableBuilt!==false||sourceReport.sourceCount!==131||
    sourceReport.patchedSourceSha256!==report.patchedSourceSha256||
    Object.keys(inventory).length!==131)
    fail('source-stage status, revision, or inventory count is inconsistent');
  // Verify the actual 131 staged input bytes and the same canonical inventory
  // fingerprint algorithm as the original Taraz v103/v104 stage builders.
  for(const [relative,digest] of Object.entries(inventory)){
    if(!/^[a-zA-Z0-9_./-]+$/.test(relative)||relative.startsWith('/')||
       relative.split('/').includes('..')||!/^[0-9a-f]{64}$/.test(digest))
      fail('malformed source inventory entry');
    const item=requireFile(path.join(sourceStage,'source',...relative.split('/')));
    if(sha(fs.readFileSync(item))!==digest)fail('staged source input changed: '+relative);
  }
  const sorted=Object.entries(inventory).sort(([a],[b])=>a<b?-1:a>b?1:0);
  const pythonJson='{'+sorted.map(([key,value])=>
    JSON.stringify(key)+': '+JSON.stringify(value)).join(', ')+'}';
  const digest=sha(Buffer.from(pythonJson,'utf8'));
  if(digest!==pinnedStageFingerprint)fail('staged source fingerprint mismatch: '+digest);
  const htmlPath=requireFile(path.join(stage,'dist','accounting.html'));
  const html=fs.readFileSync(htmlPath,'utf8');
  const script=html.match(/\bsrc=["']\.\/assets\/([^"']+\.js)["']/);
  const style=html.match(/\bhref=["']\.\/assets\/([^"']+\.css)["']/);
  if(!script||!style||!/^accounting-[a-z0-9_-]+\.js$/i.test(script[1])||
    !/^accounting-[a-z0-9_-]+\.css$/i.test(style[1]))
    fail('Vite HTML references invalid account assets');
  if(script[1]!==report.vitedJsFile||style[1]!==report.vitedCssFile||
    sha(fs.readFileSync(htmlPath))!==report.viteHtmlSha256)
    fail('Vite index or selected asset names no longer match attestation');
  const js=fs.readFileSync(requireFile(path.join(stage,'dist','assets',script[1])));
  const css=fs.readFileSync(requireFile(path.join(stage,'dist','assets',style[1])));
  if(sha(js)!==report.viteJsSha256||sha(css)!==report.viteCssSha256||
    sha(js)===oldJsSha)fail('Vite assets changed or stale v103 JS substituted');
  return {build:stage,js:js.toString('utf8'),css:css.toString('utf8'),
    jsSha:sha(js),sourceFingerprint:digest,mode:'STAGE_UI_ONLY'};
}

function selectedArtifact(){
  if(process.env.TARAZ_V104_STAGE_DIR&&process.env.TARAZ_V104_BUILD_DIR)
    fail('select exactly one of TARAZ_V104_STAGE_DIR or TARAZ_V104_BUILD_DIR');
  if(process.env.TARAZ_V104_STAGE_DIR)return stageUiArtifact();
  const result=compiledArtifact();
  return {...result,mode:'EXE_COMPILED_UI'};
}

async function makePage(browser,assets,{history='throw'}={}){
  const context=await browser.newContext({viewport:{width:1400,height:900},
    reducedMotion:'reduce',serviceWorkers:'block'});
  const network={blocked:0,fulfilledFixture:0};
  await context.route('**/*',route=>{
    if(route.request().url()==='https://taraz-qa.invalid/accounting.html'){
      network.fulfilledFixture++;
      return route.fulfill({status:200,contentType:'text/html',body:
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>'});
    }
    network.blocked++;
    return route.abort('blockedbyclient');
  });
  const page=await context.newPage();
  page.setDefaultTimeout(9000);
  const pageErrors=[];
  page.on('pageerror',e=>pageErrors.push(e.message));
  await page.goto('https://taraz-qa.invalid/accounting.html');
  await page.evaluate(({secret,history})=>{
    window.__v104={calls:[],commands:0};
    const reject=method=>{window.__v104.calls.push(method);
      return Promise.reject(Error(secret+' :: '+method+' ; AUTH=confidential-host-value'));};
    const view={currency:'RIAL',journals:[],accounts:{},parties:{},items:{},
      invoices:{},bills:{},receipts:{},payments:{},proformas:{},
      taxRules:{},contractorJobs:{},returns:{},cashAccounts:{},
      companyProfile:{legalName:'QA synthetic',history:[]},closedThrough:null,
      sequence:{invoice:0,bill:0}};
    window.madar={
      standaloneAccountingRead:async()=>({revision:0,view,
        capabilities:{canManage:true,canDraft:true,canAdmin:true},
        currentUser:{username:'qa-admin',role:'admin',jobTitle:''}}),
      standaloneAccountingCommand:async()=>{window.__v104.commands++;throw Error('Finance call forbidden');},
      standaloneAccountingParsianHistory:()=>history==='bad195'
        ?(window.__v104.calls.push('history-invalid-195'),Promise.resolve({invoices:[]})):reject('history'),
      standaloneAccountingParsianCompany:()=>reject('company'),
      standaloneAccountingParsianExtended:()=>reject('extended'),
      standaloneAccountingParsianArchiveIndex:()=>Promise.resolve([{
        year:'1405',tableCount:1,rowCount:2,currencyVerified:true,
        tables:[{name:'tbl_Synthetic',rows:2}]}]),
      standaloneAccountingParsianArchiveRows:()=>reject('archiveRows'),
      standaloneAccountingCsvChooseFile:()=>reject('csvChoose'),
      standaloneAccountingCsvPreview:()=>reject('csvPreview'),
    };
  },{secret,history});
  await page.addStyleTag({content:assets.css});
  await page.addScriptTag({type:'module',content:assets.js});
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).waitFor();
  return {context,page,network,pageErrors};
}

async function go(page,tab){
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
  const drawer=page.getByRole('dialog',{name:'فهرست بخش‌های تراز'});
  await drawer.locator('[data-accounting-tab="'+tab+'"]').first().click();
  await drawer.waitFor({state:'detached'});
}

test('v1.0.4 compiled host-message acceptance, explicit stage-only or EXE mode',async t=>{
  const assets=selectedArtifact();
  t.diagnostic('VERIFIED_MODE='+assets.mode+' JS_SHA256='+assets.jsSha+
    (assets.sourceFingerprint?' SOURCE_SHA256='+assets.sourceFingerprint:''));
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(async()=>browser.close());

  async function redacted(title,{tab,selector,method,meaning,action}){
    await t.test(title,async()=>{
      const {context,page,network,pageErrors}=await makePage(browser,assets);
      try{
        if(tab)await go(page,tab);
        if(action)await action(page);
        const sink=page.locator(selector).first();
        await sink.waitFor();
        const message=(await sink.innerText()).trim();
        assert.ok(meaning.test(message),'operator message is not meaningful: '+message);
        assert.doesNotMatch(message,/QA-V104-HOST-SECRET-91317|AUTH=confidential-host-value/);
        assert.doesNotMatch(await page.locator('body').innerText(),
          /QA-V104-HOST-SECRET-91317|AUTH=confidential-host-value/);
        const calls=await page.evaluate(()=>window.__v104);
        assert.ok(calls.calls.includes(method),'synthetic failing '+method+' API never called');
        assert.equal(calls.commands,0,'must never send finance command');
        assert.equal(network.fulfilledFixture,1,'one intercepted synthetic page only');
        assert.deepEqual(pageErrors,[],'no uncaught page exception');
      }finally{await context.close();}
    });
  }

  await redacted('company archive host exception must be masked',{
    tab:'company',selector:'.ppc-root.ppc-error',method:'company',
    meaning:/(شرکت|مشخصات).*(پارسیان|آرشیو|بکاپ|خواندن|ناموفق)/});
  await redacted('overview history host exception must be masked',{
    selector:'.tdh-warning[role="alert"]',method:'history',
    meaning:/(تاریخی|سوابق).*(ناموفق|نشد|دریافت)/});
  await redacted('migration extended source host exception must be masked',{
    tab:'migration',selector:'.ppe-root.ppe-error',method:'extended',
    meaning:/(داده|تکمیلی|پارسیان).*(ناموفق|نشد)/});
  await redacted('historical invoices host exception must be masked',{
    tab:'migration',selector:'.ppi-root.ppi-error',method:'history',
    meaning:/(پارسیان|فاکتور|آرشیو).*(ناموفق|نشد|خواند)/});
  await redacted('historical bank and cash host exception must be masked',{
    tab:'cash',selector:'.ppbm-notice[role="alert"]',method:'history',
    meaning:/(بانک|صندوق|تاریخی).*(ناموفق|نشد)/});
  await redacted('archive rows error must be masked after user-selected table',{
    tab:'migration',selector:'.pra-records .pra-error',method:'archiveRows',
    meaning:/(آرشیو|سطر|جدول).*(ناموفق|نشد|نیست)/,
    action:async page=>page.locator('.pra-table-list button')
      .getByText('tbl_Synthetic').click()});
  await redacted('CSV chooser host exception must be masked',{
    tab:'migration',selector:'.pcsv-error[role="alert"]',method:'csvChoose',
    meaning:/(CSV|فایل|انتخاب).*(ناموفق|نشد)/,
    action:async page=>page.locator('.pcsv-dataset').first()
      .getByRole('button',{name:'انتخاب CSV'}).click()});

  await t.test('trusted locally-authored 195-invoice validation message stays visible',async()=>{
    const {context,page,network,pageErrors}=await makePage(browser,assets,{history:'bad195'});
    try{
      await go(page,'invoice');
      const alert=page.locator('.ppi-root.ppi-error');
      await alert.waitFor();
      assert.match(await alert.innerText(),/اطلاعات معتبر ۱۹۵ فاکتور پارسیان دریافت نشد/);
      assert.doesNotMatch(await page.locator('body').innerText(),/QA-V104-HOST-SECRET-91317/);
      const calls=await page.evaluate(()=>window.__v104);
      assert.ok(calls.calls.includes('history-invalid-195'));
      assert.equal(calls.commands,0);
      assert.equal(network.fulfilledFixture,1);
      assert.deepEqual(pageErrors,[]);
    }finally{await context.close();}
  });
  await t.test('trusted locally-authored CSV request validation stays visible',async()=>{
    const {context,page,network,pageErrors}=await makePage(browser,assets);
    try{
      await go(page,'migration');
      await page.locator('.pcsv-panel .pcsv-config select').first().selectOption('RIAL');
      await page.getByRole('button',{name:'اجرای پیش‌نمایش فقط‌خواندنی'}).click();
      const alert=page.locator('.pcsv-error[role="alert"]');
      await alert.waitFor();
      assert.match(await alert.innerText(),/انتخاب هر سه فایل CSV الزامی است/);
      const calls=await page.evaluate(()=>window.__v104);
      assert.ok(!calls.calls.includes('csvPreview'),
        'invalid local input must be rejected before native preview bridge');
      assert.equal(calls.commands,0);
      assert.equal(network.fulfilledFixture,1);
      assert.deepEqual(pageErrors,[]);
    }finally{await context.close();}
  });
});
