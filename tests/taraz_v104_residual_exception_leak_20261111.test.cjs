'use strict';
/** QA-only residual exception exposure probes on exact detached v104 Vite UI.
 * No native app is launched. All HTTP requests intercepted. Financial command
 * bridge throws BEFORE any write and records attempted calls separately.
 * Passing a positive local-throw test means that a raw local error IS visible,
 * not that its path is safe or that a native backend exception was leaked.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const root=String.raw`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1`;
const vite=path.join(root,'vite-qa-1ff6df468d81');
const sourceStage=path.join(root,'source-stage-959986753b61');
const secret='QA-V104-RESIDUAL-LOCAL-58317';
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const file=p=>fs.readFileSync(p);
const readJson=p=>JSON.parse(file(p).toString('utf8'));
const pinnedSource='6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1';
const pinnedJs='b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453';
const rc2=Boolean(process.env.TARAZ_V104_RESIDUAL_RC2_STAGE_DIR);
const rc3=Boolean(process.env.TARAZ_V104_RESIDUAL_RC3_STAGE_DIR);
const repaired=rc2||rc3;
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'', 'npm','node_modules','playwright'));}

function validateViteStage(){
  let selectedVite=vite,selectedSourceStage=sourceStage,
    requiredSource=pinnedSource,requiredJs=pinnedJs;
  assert.ok(!(rc2&&rc3),'select exactly one of RC2 or RC3 Vite modes');
  if(repaired){
    selectedVite=fs.realpathSync.native(rc3?
      process.env.TARAZ_V104_RESIDUAL_RC3_STAGE_DIR:
      process.env.TARAZ_V104_RESIDUAL_RC2_STAGE_DIR);
    assert.equal(path.win32.normalize(path.dirname(selectedVite)).toLowerCase(),
      path.win32.normalize(fs.realpathSync.native(root)).toLowerCase(),
      'Vite repair directory must be an isolated child of known v104 root');
    assert.match(path.basename(selectedVite),/^vite-qa-[A-Za-z0-9]+$/);
    assert.notEqual(path.win32.normalize(selectedVite).toLowerCase(),
      path.win32.normalize(vite).toLowerCase(),
      'original vulnerable Vite artifact cannot impersonate repaired build');
    if(rc3)assert.notEqual(path.basename(selectedVite).toLowerCase(),
      'vite-qa-899a40d30820','failed RC2 Vite cannot impersonate repaired RC3');
    requiredSource=(rc3?process.env.TARAZ_V104_RESIDUAL_RC3_SOURCE_SHA256:
      process.env.TARAZ_V104_RESIDUAL_RC2_SOURCE_SHA256)||'';
    requiredJs=(rc3?process.env.TARAZ_V104_RESIDUAL_RC3_JS_SHA256:
      process.env.TARAZ_V104_RESIDUAL_RC2_JS_SHA256)||'';
    assert.match(requiredSource,/^[0-9a-f]{64}$/,
      'new repair source sha256 must be explicitly pinned before test');
    assert.match(requiredJs,/^[0-9a-f]{64}$/,
      'new repair JavaScript sha256 must be explicitly pinned before test');
    assert.notEqual(requiredSource,pinnedSource);
    assert.notEqual(requiredJs,pinnedJs);
    if(rc3){
      assert.notEqual(requiredSource,
        'aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8',
        'unfixed RC2 source hash forbidden for RC3');
      assert.notEqual(requiredJs,
        '39295ea85bf2d6ee9fd94fce862c2bc505d4ac6ce01153fbc7ef9d8eea0b5b79',
        'unfixed RC2 Vite JS hash forbidden for RC3');
    }
  }
  const v=readJson(path.join(selectedVite,
    rc3?'rc3-vite-qa-report.json':rc2?'rc2-vite-qa-report.json':'vite-qa-report.json'));
  if(repaired){
    selectedSourceStage=fs.realpathSync.native(v.stage||'');
    assert.equal(path.win32.normalize(path.dirname(selectedSourceStage)).toLowerCase(),
      path.win32.normalize(fs.realpathSync.native(root)).toLowerCase(),
      'repair source stage must reside in fixed v104 root');
    assert.match(path.basename(selectedSourceStage),/^source-stage-[A-Za-z0-9]+$/);
    if(rc3)assert.notEqual(path.basename(selectedSourceStage).toLowerCase(),
      'source-stage-146b4c62e3f8','unfixed RC2 source stage forbidden for RC3');
  }
  const s=readJson(path.join(selectedSourceStage,'stage-report.json'));
  const inventoryFile=path.join(selectedSourceStage,'patched-source-sha256.json');
  const inventory=readJson(inventoryFile);
  if(repaired){
    assert.equal(v.status,rc3?'V104_RC3_STAGE_UI_ONLY_EDGE_QA_PENDING':
      'V104_RC2_STAGE_UI_ONLY_EDGE_QA_PENDING');
    if(rc3)assert.equal(v.compiledExe,false);
    else {assert.equal(v.viteExitCode,0);assert.equal(v.nativeExeBuilt,false);}
    assert.equal(v.releaseApproved,false);
    assert.equal(v.sourceCount,131);
    assert.equal(s.status,rc3?'V104_RC3_SOURCE_ONLY_EDGE_QA_PENDING':
      'V104_RC2_SOURCE_ONLY_DYNAMIC_QA_PENDING');
    assert.equal(s.executableBuilt,false);
    assert.equal(v.sourceSha256,requiredSource);
    if(rc3){
      assert.deepEqual(s.changedSourceFiles,['src/accounting_management_dashboard.jsx'],
        'RC3 must change exactly one named source file');
      assert.equal(s.startingSourceSha256,
        'aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8',
        'RC3 must build from pinned RC2 stage');
      assert.equal(s.sourceSha256,requiredSource);
    }
  }else{
    assert.equal(v.status,'STAGE_UI_ONLY');
    assert.equal(v.compiledFrontend,true);
    assert.equal(v.compiledExeBuilt,false);
    assert.equal(v.compiledBundleReleaseReady,false);
    assert.equal(s.status,'V104_PATCHED_SOURCE_FROZEN_QA_PENDING_NO_EXE');
    assert.equal(v.patchedSourceSha256,requiredSource);
  }
  assert.equal(rc3?s.sourceSha256:s.patchedSourceSha256,requiredSource);
  assert.equal(v.sourceStageReportSha256,sha(file(path.join(selectedSourceStage,'stage-report.json'))));
  assert.equal(repaired?v.sourceInventoryFileSha256:v.sourceInventorySha256,sha(file(inventoryFile)));
  assert.equal(Object.keys(inventory).length,131);
  for(const [relative,digest] of Object.entries(inventory)){
    assert.match(relative,/^[A-Za-z0-9_./-]+$/);
    assert.ok(!relative.split('/').includes('..')&&!relative.startsWith('/'));
    assert.equal(sha(file(path.join(selectedSourceStage,'source',...relative.split('/')))),digest,
      'source stage changed: '+relative);
  }
  const sorted=Object.entries(inventory).sort(([a],[b])=>a<b?-1:a>b?1:0);
  const fingerprint=sha(Buffer.from('{'+sorted.map(([k,d])=>
    JSON.stringify(k)+': '+JSON.stringify(d)).join(', ')+'}','utf8'));
  assert.equal(fingerprint,requiredSource);
  if(rc3){
    const rc2Inventory=readJson(path.join(root,'source-stage-146b4c62e3f8',
      'patched-source-sha256.json'));
    const changed=Object.keys(inventory).filter(p=>inventory[p]!==rc2Inventory[p]).sort();
    assert.deepEqual(changed,['src/accounting_management_dashboard.jsx'],
      'RC3 source inventory must differ only at intended analytics component');
  }
  const html=file(path.join(selectedVite,'dist','accounting.html')).toString('utf8');
  assert.equal(sha(Buffer.from(html)),repaired?v.htmlSha256:v.viteHtmlSha256);
  const jsMatch=html.match(/\bsrc=["']\.\/assets\/(accounting-[A-Za-z0-9_-]+\.js)["']/);
  const cssMatch=html.match(/\bhref=["']\.\/assets\/(accounting-[A-Za-z0-9_-]+\.css)["']/);
  assert.ok(jsMatch&&cssMatch,'missing compiled accounting assets');
  assert.equal(jsMatch[1],repaired?path.basename(v.jsRelativePath):v.vitedJsFile);
  assert.equal(cssMatch[1],repaired?path.basename(v.cssRelativePath):v.vitedCssFile);
  const js=file(path.join(selectedVite,'dist','assets',jsMatch[1]));
  const css=file(path.join(selectedVite,'dist','assets',cssMatch[1]));
  assert.equal(sha(js),requiredJs);
  assert.equal(sha(css),repaired?v.cssSha256:v.viteCssSha256);
  for(const name of ['accounting_operational_panels.jsx',
    'accounting_management_dashboard.jsx','accounting_print_designer.jsx',
    'standalone_accounting_workspace.jsx']){
    assert.ok(inventory['src/'+name],name+' absent from source inventory');
  }
  return {js:js.toString('utf8'),css:css.toString('utf8'),
    sourceSha:requiredSource,jsSha:requiredJs,rc2,rc3};
}

async function makePage(browser,asset,{mode='normal'}={}){
  const context=await browser.newContext({viewport:{width:1420,height:960},
    serviceWorkers:'block',reducedMotion:'reduce'});
  const net={fixture:0,other:0};
  await context.route('**/*',route=>{
    if(route.request().url()==='https://taraz-residual-qa.invalid/accounting.html'){
      net.fixture++;
      return route.fulfill({status:200,contentType:'text/html',body:
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>'});
    }
    net.other++;
    return route.abort('blockedbyclient');
  });
  const page=await context.newPage();
  page.setDefaultTimeout(9500);
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('https://taraz-residual-qa.invalid/accounting.html');
  await page.evaluate(({secret,mode})=>{
    window.__residual={attempts:0,writes:0,read:0,printContextThrows:0,
      localFileThrows:0,events:[]};
    const today=new Date().toISOString().slice(0,10);
    const view={currency:'RIAL',journals:[],accounts:{
      '1010':{id:'1010',name:'Synthetic bank',liquid:true,kind:'asset',debitMinusCredit:0}},
      parties:{},items:{},invoices:{},bills:{},receipts:{},payments:{},
      proformas:{},returns:{},cheques:{},stockMovements:{},stock:{},warehouses:{},
      bankStatements:{},taxRules:{},contractorJobs:{},cashAccounts:{},
      companyProfile:{legalName:'QA-only',history:[]},closedThrough:null,
      sequence:{invoice:0,bill:0}};
    const rejectRead=method=>{
      window.__residual.events.push('host-read-'+method);
      return Promise.reject(Error(secret+'::HOST_READ_'+method));
    };
    if(mode==='management-malformed-host-data'){
      view.invoices[secret]={id:secret,status:'issued',postingDate:today,
        total:-1,returnedAmount:0,lines:[],partyId:'',documentDate:today};
    }
    if(mode==='purchase-local-validation'){
      view.warehouses={'WH-QA':{id:'WH-QA',name:'Synthetic warehouse'}};
      view.items={'ITEM-QA':{id:'ITEM-QA',name:'Synthetic item',kind:'goods',stockTracked:true}};
      view.bills={'BILL-QA':{id:'BILL-QA',status:'issued',discount:125,tax:0,
        lines:[{itemId:'ITEM-QA',description:'Synthetic row',quantity:2,unitPrice:100,total:200}],
        total:75,returnedQuantities:[0]}};
    }
    window.madar={
      standaloneAccountingRead:async()=>{
        window.__residual.read++;
        return {revision:0,view,
          capabilities:{canManage:true,canDraft:true,canAdmin:true},
          currentUser:{username:'qa-admin',role:'admin',jobTitle:''}};
      },
      // Deliberately reject before any accounting write. This is an attempted
      // bridge invocation, NOT a recorded finance transaction.
      standaloneAccountingCommand:async()=>{
        window.__residual.attempts++;
        window.__residual.events.push('pre-write synthetic rejection');
        throw Error(secret+'::NATIVE_COMMAND_REJECT');
      },
      standaloneAccountingParsianHistory:()=>rejectRead('history'),
      standaloneAccountingParsianCompany:()=>rejectRead('company'),
      standaloneAccountingParsianExtended:()=>rejectRead('extended'),
      standaloneAccountingParsianArchiveIndex:async()=>[{
        year:'1405',tableCount:1,rowCount:1,currencyVerified:true,
        tables:[{name:'tbl_Synthetic',rows:1}]}],
      standaloneAccountingParsianArchiveRows:()=>rejectRead('archiveRows'),
      standaloneAccountingCsvChooseFile:()=>rejectRead('csvChoose'),
    };
    if(mode==='print-local-exception'){
      const original=HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext=function(type,...rest){
        if(type==='2d'&&this.width>=500){
          window.__residual.printContextThrows++;
          throw Error(secret+'::CANVAS_RENDER_FAILURE');
        }
        return original.call(this,type,...rest);
      };
    }
    if(mode==='file-local-exception'){
      File.prototype.text=async function(){
        window.__residual.localFileThrows++;
        throw Error(secret+'::FILE_READ_FAILURE');
      };
    }
  },{secret,mode});
  await page.addStyleTag({content:asset.css});
  await page.addScriptTag({type:'module',content:asset.js});
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).waitFor();
  return {page,context,net,errors};
}

async function navigate(page,tab){
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
  const drawer=page.getByRole('dialog',{name:'فهرست بخش‌های تراز'});
  await drawer.locator('[data-accounting-tab="'+tab+'"]').first().click();
  await drawer.waitFor({state:'detached'});
}

test('v104 exact detached Vite stage residual local/native error channels',async t=>{
  const asset=validateViteStage();
  t.diagnostic((rc3?'RC3_INVERTED_STAGE_UI_ONLY':rc2?'RC2_INVERTED_STAGE_UI_ONLY':
    'EXPOSURE_EVIDENCE_STAGE_UI_ONLY')+
    ': source='+asset.sourceSha+' JS='+asset.jsSha);
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());
  async function run(label,mode,body){
    await t.test(label,async()=>{
      const session=await makePage(browser,asset,{mode});
      try{
        await body(session);
        assert.equal(session.net.fixture,1);
        assert.deepEqual(session.errors,[],'uncaught page errors');
        assert.equal((await session.page.evaluate(()=>window.__residual)).writes,0);
      }finally{await session.context.close();}
    });
  }

  await run('InlineForm authored validation is visible without a finance command',
    'normal',async({page})=>{
      await navigate(page,'cash');
      const form=page.locator('.sac-operational-form').filter({
        has:page.locator('h3',{hasText:'ثبت ردیف صورتحساب بانکی'})});
      await form.waitFor();
      await form.locator('label.sac-field').filter({hasText:'شناسه رکورد بانک'})
        .locator('input').fill('QA-BANK-STATEMENT-1');
      await form.locator('label.sac-field').filter({hasText:'مبلغ علامت‌دار'})
        .locator('input').fill('abc');
      await form.locator('label.sac-field').filter({hasText:'شناسه مرجع بانک'})
        .locator('input').fill('QA-REFERENCE');
      await form.locator('button[type="submit"]').click();
      const message=await form.locator('.sac-alert.error').innerText();
      assert.match(message,/مبلغ|عدد|صحیح|نامعتبر/);
      assert.doesNotMatch(message,/QA-V104-RESIDUAL-LOCAL-58317/);
      assert.equal((await page.evaluate(()=>window.__residual)).attempts,0);
    });

  await run('InlineForm intercepted host write failure stays masked by workspace execute',
    'normal',async({page})=>{
      await navigate(page,'cash');
      const form=page.locator('.sac-operational-form').filter({
        has:page.locator('h3',{hasText:'ثبت ردیف صورتحساب بانکی'})});
      await form.waitFor();
      await form.locator('label.sac-field').filter({hasText:'شناسه رکورد بانک'})
        .locator('input').fill('QA-BANK-STATEMENT-2');
      await form.locator('label.sac-field').filter({hasText:'مبلغ علامت‌دار'})
        .locator('input').fill('2000');
      await form.locator('label.sac-field').filter({hasText:'شناسه مرجع بانک'})
        .locator('input').fill('QA-REFERENCE');
      await form.locator('button[type="submit"]').click();
      await page.waitForFunction(()=>window.__residual.attempts===1);
      const body=await page.locator('body').innerText();
      assert.doesNotMatch(body,/QA-V104-RESIDUAL-LOCAL-58317/);
      assert.match(await page.locator('.sac-alert.error').first().innerText(),
        /نامشخص|بازیابی|میزبان|نتیجه/);
      assert.equal((await page.evaluate(()=>window.__residual)).writes,0);
      assert.equal(await form.locator('.sac-alert.error').count(),0,
        'InlineForm must not receive raw host rejection');
    });

  await run(repaired?'print preview LOCAL canvas exception is masked in compiled UI':
    'print preview LOCAL canvas exception is directly visible in compiled UI',
    'print-local-exception',async({page})=>{
      await navigate(page,'invoiceDesign');
      const sink=page.locator('.sac-print-designer .sac-print-error');
      await sink.waitFor();
      const message=await sink.innerText();
      if(repaired){
        assert.doesNotMatch(message,/QA-V104-RESIDUAL-LOCAL-58317/);
        assert.match(message,/پیش.?نمایش|چاپ|خطا|ناموفق|قالب/);
        assert.doesNotMatch(await page.locator('body').innerText(),
          /QA-V104-RESIDUAL-LOCAL-58317/);
      }else assert.match(message,/QA-V104-RESIDUAL-LOCAL-58317::CANVAS_RENDER_FAILURE/);
      const state=await page.evaluate(()=>window.__residual);
      assert.ok(state.printContextThrows>0,'canvas failure injection was not reached');
      assert.equal(state.attempts,0);
    });

  await run(repaired?'bank CSV browser File.text LOCAL exception is masked':
    'bank CSV browser File.text LOCAL exception is directly visible',
    'file-local-exception',async({page})=>{
      await navigate(page,'cash');
      await page.getByRole('textbox',{name:'فایل CSV بانک'}).count();
      await page.locator('input[type="file"][aria-label="فایل CSV بانک"]').setInputFiles({
        name:'synthetic-bank.csv',mimeType:'text/csv',
        buffer:Buffer.from('statementId;accountId;date;amount;reference\n','utf8')});
      const sink=page.locator('.sac-panel').filter({
        has:page.locator('h3',{hasText:'ورود دسته‌ای صورتحساب بانک از CSV آفلاین'})})
        .locator('.sac-alert.error');
      await sink.waitFor();
      const message=await sink.innerText();
      if(repaired){
        assert.doesNotMatch(message,/QA-V104-RESIDUAL-LOCAL-58317/);
        assert.match(message,/CSV|فایل|خواندن|ناموفق|معتبر/);
        assert.doesNotMatch(await page.locator('body').innerText(),
          /QA-V104-RESIDUAL-LOCAL-58317/);
      }else assert.match(message,/QA-V104-RESIDUAL-LOCAL-58317::FILE_READ_FAILURE/);
      const state=await page.evaluate(()=>window.__residual);
      assert.equal(state.localFileThrows,1);
      assert.equal(state.attempts,0);
    });

  await run(repaired?'management dashboard masks malformed host invoice ID':
    'management dashboard with malformed host invoice ID: classify reachability',
    'management-malformed-host-data',async({page})=>{
      const expand=page.locator('details.sac-vtr-management-details').filter({
        has:page.locator('summary',{hasText:'گزارش‌های تحلیلی و یادآورهای مدیریتی'})});
      await expand.locator('summary').click();
      const result=await page.locator('.mdash-error[role="alert"]').first().innerText();
      assert.match(result,repaired?/داشبورد|مدیریتی|شاخص|تحلیل|ناموفق|معتبر/:/مبلغ نامعتبر|فاکتور/);
      // Deliberately test actual propagation from a malformed host view. If
      // secret appears, this proves echo of a host-controlled key, NOT a
      // native Promise rejection or an installed WebView2 exploit.
      if(repaired){
        assert.ok(!result.includes(secret),'RC2 still exposes hostile invoice key: '+result);
        assert.doesNotMatch(await page.locator('body').innerText(),
          /QA-V104-RESIDUAL-LOCAL-58317/);
      }else assert.ok(result.includes(secret),'host-controlled invoice key was sanitized: '+result);
      assert.equal((await page.evaluate(()=>window.__residual)).attempts,0);
    });

  await run('discount allocation :297 exposes locally authored validation, not native error',
    'purchase-local-validation',async({page})=>{
      await navigate(page,'items');
      const form=page.locator('.sac-operational-form').filter({
        has:page.locator('h3',{hasText:'ثبت رسید، حواله، انتقال و اصلاح موجودی'})});
      await form.waitFor();
      await form.locator('label.sac-field').filter({hasText:'انبار مبدأ'})
        .locator('select').selectOption('WH-QA');
      await form.locator('label.sac-field').filter({hasText:'کالای دارای رهگیری'})
        .locator('select').selectOption('ITEM-QA');
      await form.locator('label.sac-field').filter({hasText:'تعداد صحیح در واحد پایه'})
        .locator('input').fill('1');
      await form.locator('label.sac-field').filter({hasText:'فاکتور خرید قطعی'})
        .locator('select').selectOption('BILL-QA');
      await form.locator('label.sac-field').filter({hasText:'تخصیص تخفیف خرید'})
        .locator('select').selectOption('per-line-exact');
      const panel=page.locator('[aria-label="تخصیص دقیق تخفیف خرید"]');
      await panel.waitFor();
      await panel.locator('input[aria-label="تخفیف ردیف 1"]').fill('abc');
      const error=await panel.locator('[role="alert"]').innerText();
      assert.match(error,/تخفیف|عدد|معتبر|صحیح|ردیف/);
      assert.doesNotMatch(error,/QA-V104-RESIDUAL-LOCAL-58317/);
      assert.equal((await page.evaluate(()=>window.__residual)).attempts,0);
    });

  // The first v104 baseline already has a standalone seven-leak acceptance
  // suite. RC2/RC3 independently replays the same native read rejections on
  // its own attested Vite asset; they must stay masked after residual fixes.
  if(repaired){
    const regressions=[
      {title:'company archive backend rejection stays masked',tab:'company',
        selector:'.ppc-root.ppc-error',method:'company',meaning:/شرکت|پارسیان|بکاپ|ناموفق/},
      {title:'overview history backend rejection stays masked',tab:null,
        selector:'.tdh-warning[role="alert"]',method:'history',meaning:/تاریخی|سوابق|ناموفق/},
      {title:'migration extended backend rejection stays masked',tab:'migration',
        selector:'.ppe-root.ppe-error',method:'extended',meaning:/پارسیان|تکمیلی|ناموفق/},
      {title:'migration invoices backend rejection stays masked',tab:'migration',
        selector:'.ppi-root.ppi-error',method:'history',meaning:/پارسیان|آرشیو|ناموفق/},
      {title:'cash bank history backend rejection stays masked',tab:'cash',
        selector:'.ppbm-notice[role="alert"]',method:'history',meaning:/بانک|صندوق|ناموفق/},
      {title:'archive table rows backend rejection stays masked',tab:'migration',
        selector:'.pra-records .pra-error',method:'archiveRows',meaning:/آرشیو|سطر|ناموفق/,
        action:async page=>page.locator('.pra-table-list button').getByText('tbl_Synthetic').click()},
      {title:'CSV choose backend rejection stays masked',tab:'migration',
        selector:'.pcsv-error[role="alert"]',method:'csvChoose',meaning:/CSV|فایل|انتخاب|ناموفق/,
        action:async page=>page.locator('.pcsv-dataset').first()
          .getByRole('button',{name:'انتخاب CSV'}).click()},
    ];
    for(const regression of regressions){
      await run('historical v103 leak regression: '+regression.title,'normal',async({page})=>{
        if(regression.tab)await navigate(page,regression.tab);
        if(regression.action)await regression.action(page);
        const sink=page.locator(regression.selector).first();
        await sink.waitFor();
        const message=await sink.innerText();
        assert.match(message,regression.meaning);
        assert.doesNotMatch(message,/QA-V104-RESIDUAL-LOCAL-58317/);
        assert.doesNotMatch(await page.locator('body').innerText(),
          /QA-V104-RESIDUAL-LOCAL-58317/);
        const state=await page.evaluate(()=>window.__residual);
        assert.ok(state.events.includes('host-read-'+regression.method),
          'fake host method not invoked: '+regression.method);
        assert.equal(state.attempts,0);
      });
    }
  }
});
