'use strict';
/** QA-only read of v1.0.3 compiled candidate and synthetic Edge interaction.
 * Assertions distinguish demonstrated unsafe text from safe masked failures.
 * Never invokes native Taraz, installs anything or fetches LAN/finance data.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
const candidate=String.raw`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\build-eb9d4f2ab076`;
const sourceRoot=path.join(candidate,'source','src');
const binary=path.join(candidate,'binary','Taraz.exe');
const asset=path.join(candidate,'web','dist','assets','accounting-IoqJ3LzK.js');
const css=path.join(candidate,'web','dist','assets','accounting-Cn_dODL0.css');
const secret='QA-V103-HOST-SECRET-72973';
const getSha=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'', 'npm','node_modules','playwright'));}

test('audited frozen v1.0.3 compiled JS matches embedded EXE archive byte-for-byte',()=>{
  assert.equal(getSha(binary),'e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c');
  assert.equal(getSha(asset),'001e9e7e622fee9cc375461b754847a978c0b16563a72a4cd8e5d784ca8512b4');
  const py=String.raw`import json,hashlib,sys
from PyInstaller.archive.readers import CArchiveReader
a=CArchiveReader(sys.argv[1])
b=a.extract('dist\\assets\\accounting-IoqJ3LzK.js')
print(json.dumps({'size':len(b),'sha256':hashlib.sha256(b).hexdigest()}))`;
  const run=spawnSync('py',['-3.12','-B','-c',py,binary],
    {cwd:root,encoding:'utf8',timeout:30000});
  assert.equal(run.status,0,'PyInstaller read-only inspect failed: '+run.stderr);
  assert.deepEqual(JSON.parse(run.stdout.trim()),{
    size:906944,sha256:getSha(asset)});
  for(const file of ['personal_parsian_company.jsx','personal_parsian_invoices.jsx',
    'personal_parsian_extended.jsx','personal_parsian_bank_movements.jsx',
    'parsian_raw_archive_explorer.jsx','provider_csv_migration.jsx',
    'taraz_home_command.jsx','taraz_settings.jsx','taraz_madar_dashboard.jsx',
    'standalone_main.jsx']){
    assert.ok(fs.existsSync(path.join(sourceRoot,file)),file+' absent from frozen source');
    assert.equal(getSha(path.join(sourceRoot,file)),getSha(path.join(root,'src',file)),
      'current worktree differs from frozen candidate: '+file);
  }
});

async function syntheticPage(browser,modes={}){
  const context=await browser.newContext({viewport:{width:1400,height:920},
    reducedMotion:'reduce',serviceWorkers:'block'});
  await context.route('**/*',route=>route.abort('blockedbyclient'));
  await context.route('https://taraz-qa.invalid/accounting.html',route=>route.fulfill({
    status:200,contentType:'text/html',body:'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>',
  }));
  const page=await context.newPage();
  page.setDefaultTimeout(8500);
  const pageErrors=[];
  page.on('pageerror',e=>pageErrors.push(e.message));
  await page.goto('https://taraz-qa.invalid/accounting.html');
  await page.evaluate(({secret,modes})=>{
    window.__v103={calls:[],commands:0};
    const fail=name=>{window.__v103.calls.push(name);
      return Promise.reject(Error(secret+' :: '+name));};
    const view={currency:'RIAL',journals:[],accounts:{},parties:{},items:{},
      invoices:{},bills:{},receipts:{},payments:{},proformas:{},
      taxRules:{},contractorJobs:{},returns:{},cashAccounts:{},
      companyProfile:{legalName:'QA only',history:[]},closedThrough:null,
      sequence:{invoice:0,bill:0}};
    const read=()=>({revision:0,view,
      capabilities:{canManage:true,canDraft:true,canAdmin:true},
      currentUser:{username:'qa-admin',role:'admin',jobTitle:''}});
    window.madar={
      standaloneAccountingRead:async()=>read(),
      standaloneAccountingCommand:async()=>{window.__v103.commands++;
        throw Error('Finance command forbidden in QA fixture');},
      standaloneAccountingParsianHistory:()=>fail('history'),
      standaloneAccountingParsianCompany:()=>fail('company'),
      standaloneAccountingParsianExtended:()=>fail('extended'),
      standaloneAccountingParsianArchiveIndex:()=>
        modes.archiveIndex==='fail'?fail('archiveIndex'):Promise.resolve([{
          year:'1405',tableCount:1,rowCount:2,currencyVerified:true,
          tables:[{name:'tbl_Synthetic',rows:2}]}]),
      standaloneAccountingParsianArchiveRows:()=>fail('archiveRows'),
      standaloneAccountingCsvChooseFile:()=>fail('csvChoose'),
      tarazIntegrationList:()=>fail('madarInbox'),
      tarazMadarDataRead:()=>fail('madarData'),
    };
  },{secret,modes});
  await page.addStyleTag({content:fs.readFileSync(css,'utf8')});
  await page.addScriptTag({type:'module',content:fs.readFileSync(asset,'utf8')});
  try{await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).waitFor();}
  catch(error){throw Error('Frozen compiled startup blocked: '+JSON.stringify({
    pageErrors,html:(await page.locator('body').innerText()).slice(0,600),
    hasRoot:await page.locator('.sac-root').count(),
  })+'; '+error.message);}
  return {context,page,pageErrors};
}

async function navigate(page,tab){
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
  const drawer=page.getByRole('dialog',{name:'فهرست بخش‌های تراز'});
  await drawer.locator('[data-accounting-tab="'+tab+'"]').first().click();
  await drawer.waitFor({state:'detached'});
}

test('actual v103 compiled UI: synthetic backend exceptions and visible raw text',async t=>{
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(async()=>browser.close());
  async function proveLeak(label,tab,selector,apiName,action){
    if(process.env.V103_AUDIT_CASE&&!label.includes(process.env.V103_AUDIT_CASE))return;
    await t.test(label,async()=>{
      const {context,page,pageErrors}=await syntheticPage(browser);
      try{
        if(tab)await navigate(page,tab);
        if(action)await action(page);
        const sink=page.locator(selector).first();
        try{await sink.waitFor();}
        catch(error){throw Error('UI path not reached: '+JSON.stringify({
          calls:await page.evaluate(()=>window.__v103),
          pageErrors,
          alerts:(await page.locator('[role="alert"]').allTextContents()).slice(0,8),
          h1:(await page.locator('h1').allTextContents()).slice(0,5),
          body:(await page.locator('body').innerText()).slice(0,600)
        })+'; '+error.message);}
        const message=await sink.innerText();
        assert.ok(message.includes(secret+' :: '+apiName),
          'expected to prove this exact error leakage; observed: '+message.slice(0,200));
        const calls=await page.evaluate(()=>window.__v103);
        assert.ok(calls.calls.includes(apiName),apiName+' stub never invoked');
        assert.equal(calls.commands,0,'no synthetic test must issue a finance command');
        assert.deepEqual(pageErrors,[]);
      }finally{await context.close();}
    });
  }
  await proveLeak('P1: company archive detail exposes backend exception',
    'company','.ppc-root.ppc-error','company');
  await proveLeak('P1: overview financial history message exposes backend exception',
    null,'.tdh-warning[role="alert"]','history');
  await proveLeak('P1: migration extended-history UI exposes backend exception',
    'migration','.ppe-root.ppe-error','extended');
  await proveLeak('P1: migration historical invoices UI exposes backend exception',
    'migration','.ppi-root.ppi-error','history');
  await proveLeak('P1: bank and cash history UI exposes backend exception',
    'cash','.ppbm-notice[role="alert"]','history');
  await proveLeak('P1: archive row-load UI exposes backend exception after manual table selection',
    'migration','.pra-records .pra-error','archiveRows',async page=>{
      await page.locator('.pra-table-list button').getByText('tbl_Synthetic').click();
    });
  await proveLeak('P1: migration CSV chooser displays backend exception text',
    'migration','.pcsv-error[role="alert"]','csvChoose',async page=>{
      await page.locator('.pcsv-dataset').first()
        .getByRole('button',{name:'انتخاب CSV'}).click();
    });
  if(!process.env.V103_AUDIT_CASE)await t.test('control: already fixed Madar inbox does not display raw exception',async()=>{
    const {context,page,pageErrors}=await syntheticPage(browser);
    try{
      await navigate(page,'settings');
      await page.getByRole('button',{name:'اتصال به مدار'}).click();
      await page.getByRole('checkbox',{name:/ارجاع‌های مدار را دستی بررسی کنم/}).check();
      await page.getByRole('button',{name:'بررسی وضعیت اتصال'}).click();
      const sink=page.locator('.taraz-settings-message.error');
      await sink.waitFor();
      assert.doesNotMatch(await sink.innerText(),/QA-V103-HOST-SECRET-72973/);
      assert.deepEqual(pageErrors,[]);
    }finally{await context.close();}
  });
});
