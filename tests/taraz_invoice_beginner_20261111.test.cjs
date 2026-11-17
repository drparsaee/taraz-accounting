'use strict';
/** Real Vite-build UI + Edge; entirely synthetic host, network fully blocked.
 * No Windows EXE, installed accounting ledger, real customer, or finance API.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');

const root=path.resolve(__dirname,'..');
const dist=process.env.TARAZ_BEGINNER_VITE_DIR;
const sha=buffer=>crypto.createHash('sha256').update(buffer).digest('hex');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'', 'npm','node_modules','playwright'));}

function viteAssets(){
  assert.ok(dist&&path.win32.isAbsolute(dist),
    'TARAZ_BEGINNER_VITE_DIR must point to an explicit detached compiled Vite directory');
  assert.notEqual(path.win32.normalize(dist).toLowerCase(),
    path.win32.normalize(path.join(root,'dist')).toLowerCase());
  const html=fs.readFileSync(path.join(dist,'accounting.html'),'utf8');
  const jsName=html.match(/\bsrc=["']\.\/assets\/([^"']+\.js)["']/)?.[1];
  const cssName=html.match(/\bhref=["']\.\/assets\/([^"']+\.css)["']/)?.[1];
  assert.match(jsName||'',/^accounting-[\w-]+\.js$/);
  assert.match(cssName||'',/^accounting-[\w-]+\.css$/);
  const js=fs.readFileSync(path.join(dist,'assets',jsName));
  const css=fs.readFileSync(path.join(dist,'assets',cssName));
  assert.ok(js.toString('utf8').includes('فاکتور در یک صفحه'));
  assert.ok(js.toString('utf8').includes('invoice.create'));
  assert.ok(css.toString('utf8').includes('.sac-invoice-beginner'));
  return {js:js.toString('utf8'),css:css.toString('utf8'),jsSha:sha(js),cssSha:sha(css)};
}

async function prepare(browser,assets,{width=1366}={}){
  const context=await browser.newContext({viewport:{width,height:960},
    serviceWorkers:'block',reducedMotion:'reduce'});
  let blocked=0;
  await context.route('**/*',route=>{
    if(route.request().url()==='https://taraz-beginner-qa.invalid/accounting.html'){
      return route.fulfill({status:200,contentType:'text/html',body:
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>'});
    }
    blocked++;
    return route.abort('blockedbyclient');
  });
  const page=await context.newPage();
  page.setDefaultTimeout(12000);
  const uncaught=[];
  page.on('pageerror',e=>uncaught.push(e.message));
  await page.goto('https://taraz-beginner-qa.invalid/accounting.html');
  await page.evaluate(()=>{
    const view={currency:'RIAL',journals:[],
      accounts:{'4000':{id:'4000',name:'درآمد فروش',kind:'revenue'}},
      parties:{'CUST-QA':{id:'CUST-QA',name:'مشتری آزمایشی تراز',kind:'customer'}},
      items:{},invoices:{},bills:{},receipts:{},payments:{},proformas:{},
      taxRules:{},contractorJobs:{},returns:{},cashAccounts:{},companyProfile:{legalName:'Synthetic QA'},
      cheques:{},warehouses:{},stock:{},stockMovements:{},closedThrough:null,
      sequence:{invoice:0,bill:0}};
    let revision=0;
    window.__qa={commands:[],reads:0,realFinance:0};
    const snapshot=()=>({revision,view,capabilities:{canManage:true,canDraft:true,canAdmin:true},
      currentUser:{username:'qa-only',role:'admin',jobTitle:''}});
    window.madar={
      standaloneAccountingRead:async()=>{window.__qa.reads++;return snapshot();},
      standaloneAccountingTemplateList:async()=>({templates:[],defaultId:''}),
      standaloneAccountingCommand:async argument=>{
        // Synthetic in-memory host only; never forwards to a real finance API.
        const command=structuredClone(argument.command);
        window.__qa.commands.push({command,expectedRevision:argument.expectedRevision});
        if(command.type==='invoice.create'){
          const subtotal=command.lines.reduce((sum,line)=>sum+line.quantity*line.unitPrice,0);
          view.invoices[command.invoiceId]={id:command.invoiceId,status:'draft',
            partyId:command.partyId,documentDate:command.documentDate,lines:command.lines,
            discount:command.discount,tax:command.tax,total:subtotal-command.discount+command.tax,
            allocated:0};
        }
        revision++;
        return snapshot();
      },
    };
  });
  await page.addStyleTag({content:assets.css});
  await page.addScriptTag({type:'module',content:assets.js});
  await page.locator('.sac-root').waitFor();
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
  const drawer=page.getByRole('dialog',{name:'فهرست بخش‌های تراز'});
  await drawer.locator('[data-accounting-tab="invoice"]').first().click();
  await page.getByRole('button',{name:'ثبت فاکتور جدید'}).click();
  await page.locator('.sac-invoice-beginner-pane').waitFor();
  return {context,page,uncaught,requests:()=>blocked};
}

test('beginner invoice uses real current Vite assets; no implicit financial commands',async t=>{
  const assets=viteAssets();
  t.diagnostic('BEGINNER_VITE_JS_SHA256='+assets.jsSha+' CSS_SHA256='+assets.cssSha);
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());
  async function scenario(name,body,opts={}){
    await t.test(name,async()=>{
      const {page,context,uncaught}=await prepare(browser,assets,opts);
      try{
        await body(page);
        assert.deepEqual(uncaught,[],'uncaught browser errors');
        assert.equal(await page.evaluate(()=>window.__qa.realFinance),0);
      }finally{await context.close();}
    });
  }

  await scenario('default is one-page beginner; empty save explains errors without calling finance',async page=>{
    assert.equal(await page.getByRole('button',{name:'ساده و سریع'}).getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('.sac-invoice-editor').getAttribute('novalidate'),'');
    assert.equal(await page.locator('#sac-wizard-panel-document').isVisible(),false);
    assert.equal(await page.locator('.sac-invoice-beginner-pane').isVisible(),true);
    assert.equal(await page.getByRole('searchbox',{name:'جست‌وجوی مشتری'}).isVisible(),true);
    assert.deepEqual(await page.evaluate(()=>window.__qa.commands),[]);
    await page.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
    await page.locator('.sac-invoice-beginner-pane [role="alert"]').waitFor();
    assert.match(await page.locator('.sac-invoice-beginner-pane [role="alert"]').innerText(),
      /شناسه|طرف|مشتری|تکمیل|شرح/);
    assert.deepEqual(await page.evaluate(()=>window.__qa.commands),[]);
  });

  await scenario('two lines and customer update live total; no autosave, only explicit draft create',async page=>{
    await page.getByRole('combobox',{name:'مشتری فاکتور'}).selectOption('CUST-QA');
    await page.getByRole('textbox',{name:'شرح ردیف 1'}).fill('خدمات طراحی بسته‌بندی');
    await page.getByRole('textbox',{name:'شرح ردیف 1'}).press('Enter');
    assert.deepEqual(await page.evaluate(()=>window.__qa.commands),[],
      'Enter inside beginner input must not trigger an implicit draft save');
    await page.getByRole('textbox',{name:'تعداد ردیف 1'}).fill('2');
    await page.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('150000');
    await page.getByRole('button',{name:'افزودن کالا یا خدمت'}).click();
    await page.getByRole('textbox',{name:'شرح ردیف 2'}).fill('کنترل فایل چاپی');
    await page.getByRole('textbox',{name:'تعداد ردیف 2'}).fill('1');
    await page.getByRole('textbox',{name:'قیمت ردیف 2'}).fill('50000');
    await page.getByRole('textbox',{name:'قیمت ردیف 2'}).press('Enter');
    assert.deepEqual(await page.evaluate(()=>window.__qa.commands),[],
      'no implicit save even after the full invoice becomes valid');
    const preview=page.locator('.sac-beginner-preview');
    await page.waitForFunction(()=>document.querySelector('.sac-beginner-preview')
      ?.textContent?.includes('۳۵۰'));
    assert.match(await preview.innerText(),/۳۵۰/);
    assert.match(await page.locator('.sac-beginner-check').innerText(),/اطلاعات اصلی تکمیل است/);
    assert.deepEqual(await page.evaluate(()=>window.__qa.commands),[],'editing must not autosave');
    await page.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
    await page.waitForFunction(()=>window.__qa.commands.length===1);
    const actions=await page.evaluate(()=>window.__qa.commands);
    assert.equal(actions.length,1);
    assert.equal(actions[0].command.type,'invoice.create');
    assert.equal(actions[0].command.partyId,'CUST-QA');
    assert.equal(actions[0].command.lines.length,2);
    assert.equal(actions[0].command.lines[0].quantity,2);
    assert.equal(actions[0].command.lines[1].unitPrice,50000);
    assert.equal(actions[0].command.discount,0);
    assert.equal(actions[0].command.tax,0);
    assert.ok(!actions.some(a=>a.command.type==='invoice.issue'||a.command.type==='invoice.approve'));
  });

  await scenario('switching to advanced editor and back preserves customer, lines, and no writes',async page=>{
    await page.getByRole('combobox',{name:'مشتری فاکتور'}).selectOption('CUST-QA');
    await page.getByRole('textbox',{name:'شرح ردیف 1'}).fill('چاپ لیبل');
    await page.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('70000');
    await page.getByRole('button',{name:'حالت حرفه‌ای'}).click();
    assert.equal(await page.locator('.sac-invoice-beginner-pane').count(),0);
    assert.equal(await page.locator('#sac-wizard-panel-document').isVisible(),true);
    assert.equal(await page.locator('.sac-invoice-editor [data-invoice-row="0"][data-invoice-col="0"]').inputValue(),
      'چاپ لیبل');
    await page.getByRole('button',{name:'ساده و سریع'}).click();
    assert.equal(await page.getByRole('combobox',{name:'مشتری فاکتور'}).inputValue(),'CUST-QA');
    assert.equal(await page.getByRole('textbox',{name:'قیمت ردیف 1'}).inputValue(),'70000');
    assert.deepEqual(await page.evaluate(()=>window.__qa.commands),[]);
  });

  await scenario('narrow view remains one-screen, removing line never saves',async page=>{
    await page.getByRole('button',{name:'افزودن کالا یا خدمت'}).click();
    assert.equal(await page.locator('.sac-beginner-row').count(),2);
    await page.getByRole('button',{name:'حذف ردیف 2'}).click();
    assert.equal(await page.locator('.sac-beginner-row').count(),1);
    assert.equal(await page.locator('.sac-wizard-step-nav').count(),0);
    assert.deepEqual(await page.evaluate(()=>window.__qa.commands),[]);
  },{width:390});

  await scenario('orders navigation exposes independent AaaS form without creating finance entries',async page=>{
    await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
    const drawer=page.getByRole('dialog',{name:'فهرست بخش‌های تراز'});
    await drawer.locator('[data-accounting-tab="orders"]').first().click();
    await page.getByRole('region',{name:'مدیریت سفارش‌های تراز'}).waitFor();
    assert.equal(await page.getByRole('region',{name:'مدیریت سفارش‌های تراز'})
      .getByRole('heading',{name:'سفارش‌ها',exact:true}).isVisible(),true);
    assert.equal(await page.getByRole('region',{name:'فرم ثبت سفارش'}).isVisible(),true);
    assert.match(await page.locator('.taraz-orders').innerText(),/مستقل از سند مالی/);
    assert.deepEqual(await page.evaluate(()=>window.__qa.commands),[]);
  });
});
