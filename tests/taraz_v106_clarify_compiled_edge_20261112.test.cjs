'use strict';
/** Real compiled second v1.0.6 UI bytes in Edge with a synthetic host.
 * NOT native WebView2 automation, Ollama inference, or financial posting.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');

const base=path.resolve(__dirname,'..','..','..','MTR-NEXT-UPDATE-CANDIDATES-20261110',
  'taraz-v1.0.6-aaas','build-81cd2dc22365');
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'','npm','node_modules','playwright'));}
function assets(){
  const report=JSON.parse(fs.readFileSync(path.join(base,'build-report.json'),'utf8'));
  assert.equal(report.sourceFreezeSha256,
    'cb9c84a349cc09c8f343a8b1b3a5a4fcec1bfa9fa9ec5a0d8d41424e219cad31');
  assert.equal(report.exeSha256,
    '4b5d17a460e1f5de827f0d36e63e72e27140362b79def5fd268e6e76b7f95731');
  const folder=path.join(base,'web','dist');
  const html=fs.readFileSync(path.join(folder,'accounting.html'),'utf8');
  const jsName=html.match(/\bsrc=["']\.\/assets\/([^"']+\.js)["']/)?.[1];
  const cssName=html.match(/\bhref=["']\.\/assets\/([^"']+\.css)["']/)?.[1];
  assert.ok(jsName&&cssName,'compiled HTML references expected JS and CSS');
  const js=fs.readFileSync(path.join(folder,'assets',jsName));
  const css=fs.readFileSync(path.join(folder,'assets',cssName));
  assert.equal(sha(js),report.compiled.assetsSha256['assets/'+jsName]);
  assert.equal(sha(css),report.compiled.assetsSha256['assets/'+cssName]);
  return {js:js.toString('utf8'),css:css.toString('utf8')};
}

test('second immutable v106 compiled UI navigates order, invoice and print editor, unsaved only',async t=>{
  const built=assets();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true});
  t.after(()=>browser.close());
  const context=await browser.newContext({viewport:{width:1440,height:1000},
    serviceWorkers:'block',reducedMotion:'reduce'});
  t.after(()=>context.close());
  let blocked=0;
  let bundleAssetsServed=0;
  await context.route('**/*',route=>{
    const requestUrl=route.request().url();
    if(requestUrl==='https://taraz-compiled-qa.invalid/accounting.html'){
      return route.fulfill({status:200,contentType:'text/html',body:
        '<!doctype html><html dir="rtl" lang="fa"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>'});
    }
    const url=new URL(requestUrl);
    if(url.origin==='https://taraz-compiled-qa.invalid'&&
        /^\/assets\/[\w.-]+$/.test(url.pathname)){
      const full=path.join(base,'web','dist',url.pathname.slice(1));
      if(fs.existsSync(full)&&fs.statSync(full).isFile()){
        const ext=path.extname(full);
        const kind=ext==='.woff2'?'font/woff2':ext==='.css'?'text/css':
          ext==='.js'?'application/javascript':ext==='.svg'?'image/svg+xml':
          ext==='.jpg'?'image/jpeg':ext==='.png'?'image/png':'application/octet-stream';
        bundleAssetsServed++;
        return route.fulfill({status:200,contentType:kind,body:fs.readFileSync(full)});
      }
    }
    blocked++;
    return route.abort('blockedbyclient');
  });
  const page=await context.newPage();
  page.setDefaultTimeout(12500);
  const pageErrors=[];
  page.on('pageerror',error=>pageErrors.push(error.name));
  await page.goto('https://taraz-compiled-qa.invalid/accounting.html');
  await page.evaluate(()=>{
    const view={currency:'RIAL',journals:[],
      accounts:{'4000':{id:'4000',name:'درآمد فروش آزمایشی',kind:'revenue'}},
      parties:{'QA-CUSTOMER':{id:'QA-CUSTOMER',name:'مشتری ساختگی',kind:'customer'}},
      items:{'QA-ITEM':{id:'QA-ITEM',name:'چاپ آزمایشی',unit:'متر',active:true}},
      invoices:{},bills:{},receipts:{},payments:{},proformas:{},
      taxRules:{},contractorJobs:{},returns:{},cashAccounts:{},
      companyProfile:{legalName:'شرکت ساختگی'},closedThrough:null,
      sequence:{invoice:0,bill:0}};
    window.__qa={writes:[],ordersRead:0,read:0,realHost:false};
    const snapshot=()=>({revision:0,view,
      capabilities:{canManage:true,canDraft:true,canAdmin:true},
      currentUser:{username:'qa-synthetic',role:'admin',jobTitle:''}});
    window.madar={
      standaloneAccountingRead:async()=>{window.__qa.read++;return snapshot();},
      standaloneAccountingTemplateList:async()=>({templates:[],defaultId:''}),
      standaloneAccountingCommand:async payload=>{
        window.__qa.writes.push({kind:'finance',type:payload?.command?.type});
        throw Error('NO_SYNTHETIC_LEDGER_WRITES_ALLOWED');
      },
      tarazOrderList:async()=>{window.__qa.ordersRead++;return {orders:[],financialEventCreated:false};},
      tarazOrderCommand:async()=>{window.__qa.writes.push({kind:'order'});
        throw Error('NO_ORDER_WRITES_ALLOWED');},
      tarazOrderSuggest:async()=>({source:'SYNTHETIC_MOCK',modelRan:false}),
      tarazPrintSuggest:async()=>({source:'SYNTHETIC_MOCK',modelRan:false})
    };
  });
  await page.addStyleTag({content:built.css});
  await page.addScriptTag({type:'module',content:built.js});
  await page.locator('.sac-root').waitFor();
  const nav=async id=>{
    const direct=page.locator('[data-accounting-tab="'+id+'"]:visible').first();
    if(await direct.count())return direct.click();
    await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
    await page.getByRole('dialog',{name:'فهرست بخش‌های تراز'})
      .locator('[data-accounting-tab="'+id+'"]').first().click();
  };

  await nav('orders');
  await page.locator('.taraz-orders-editor').waitFor();
  assert.ok(await page.locator('.taraz-orders-list').count());
  await page.locator('.taraz-orders-intake textarea')
    .fill('مشتری: تست تراز\nشرح سفارش: چاپ بدون ثبت\nتعداد فروش: ۱۲ عدد تولید: ۱۴');
  await page.getByRole('button',{name:'حرفه‌ای',exact:true}).click();
  await page.locator('.taraz-orders-advanced').waitFor();
  assert.ok(await page.getByRole('button',{name:'پیشنهاد با مدل محلی'}).count()>0);

  // Edit invoice last: its unsaved-draft guard intentionally blocks navigation.
  await nav('invoiceDesign');
  const designer=page.locator('.sac-print-designer');
  await designer.waitFor();
  await designer.getByRole('combobox',{name:'سبک چیدمان'}).selectOption('compact');
  await designer.getByRole('button',{name:'اعمال چیدمان انتخابی'}).click();
  assert.equal(await designer.getByRole('combobox',{name:'کاغذ'}).inputValue(),'A5');
  await designer.getByLabel('واحد',{exact:true}).check();
  assert.equal(await designer.getByLabel('واحد',{exact:true}).isChecked(),true);
  await page.waitForFunction(()=>{
    const canvas=document.querySelector('.sac-print-canvas-shell canvas');
    return canvas&&canvas.width>100&&canvas.height>100;
  });
  assert.ok(await designer.getByRole('button',{name:'پیشنهاد طراحی'}).count()>0);
  await page.locator('[data-accounting-action="invoice"]:visible').first().click();
  const beginner=page.locator('.sac-invoice-beginner-pane');
  await beginner.waitFor();
  await beginner.getByRole('textbox',{name:'شرح ردیف 1'}).fill('QA چاپ آزمایشی');
  await beginner.getByRole('textbox',{name:'تعداد ردیف 1'}).fill('2');
  await beginner.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('13000');
  await beginner.locator('.sac-beginner-preview').waitFor();
  assert.deepEqual(await page.evaluate(()=>window.__qa.writes),[]);
  // Any non-fixture request was blocked before it left the test browser.
  console.log('COMPILED_V106_EDGE_EVIDENCE',JSON.stringify({
    orderScreen:true,orderAdvanced:true,printDesigner:true,
    printPresetAndUnitColumn:true,invoiceBeginner:true,
    financialCommands:0,externalRequestsBlocked:blocked,
    bundledAssetRequestsServed:bundleAssetsServed}));
  assert.deepEqual(pageErrors,[]);
  assert.ok(await page.evaluate(()=>window.__qa.ordersRead)>0);
});
