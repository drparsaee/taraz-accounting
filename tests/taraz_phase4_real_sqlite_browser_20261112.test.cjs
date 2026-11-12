'use strict';
/** Compiled React -> real local Taraz API -> disposable SQLite. No mock host. */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {spawn}=require('node:child_process');
const ROOT=path.resolve(__dirname,'..');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'','npm','node_modules','playwright'));}

async function backend(){
  const child=spawn('py',['-3.12','-B',
    path.join(ROOT,'tests','taraz_p1_real_backend_http_fixture_20261112.py')],{
    cwd:ROOT,windowsHide:true,stdio:['ignore','pipe','pipe'],
    env:{...process.env,TARAZ_QA_WEB_ASSETS:'current-source-dist',
      TARAZ_QA_PHASE4_ORDERS:'1',PYTHONDONTWRITEBYTECODE:'1'},
  });
  let stderr='';
  child.stderr.on('data',bytes=>{stderr+=String(bytes).slice(0,1600);});
  const first=await Promise.race([
    new Promise((resolve,reject)=>{
      let buffer='';
      child.stdout.on('data',chunk=>{
        buffer+=chunk.toString();
        if(buffer.includes('\n'))resolve(buffer.split('\n')[0]);
      });
      child.once('error',reject);
      child.once('exit',code=>reject(Error('QA backend exited '+code+': '+stderr)));
    }),
    new Promise((_,reject)=>setTimeout(()=>reject(Error('QA startup timed out')),15000)),
  ]);
  const data=JSON.parse(first);
  assert.equal(data.isolated,true);
  const base='http://127.0.0.1:'+data.port;
  return {base,async stop(){
    if(child.exitCode!==null)return;
    await fetch(base+'/__qa_shutdown',{method:'POST',signal:AbortSignal.timeout(1500)});
    await Promise.race([
      new Promise(resolve=>child.once('exit',resolve)),
      new Promise((_,reject)=>setTimeout(()=>reject(Error('QA backend failed graceful exit')),5000)),
    ]);
  }};
}

async function ordersPage(page){
  await page.locator('[data-accounting-action="more"]').click();
  await page.locator('.taraz-vt-drawer [data-accounting-tab="orders"]').first().click();
  await page.locator('.taraz-orders-header h2').waitFor();
}
async function current(page){
  return page.evaluate(async()=>((await window.madar.tarazOrderList(0,100)).orders[0]));
}
async function revision(page,expected){
  await page.waitForFunction(async rev=>{
    const rows=(await window.madar.tarazOrderList(0,100)).orders;
    return rows[0]?.revision===rev;
  },expected,{timeout:15000});
}

test('Phase4 passport: six stages, actual costs, partial/full settlement, production, accounting draft',async t=>{
  const local=await backend();
  t.after(()=>local.stop());
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());
  const context=await browser.newContext({viewport:{width:1560,height:1100},
    reducedMotion:'reduce',serviceWorkers:'block'});
  t.after(()=>context.close());
  await context.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(url.hostname==='127.0.0.1'&&url.port===new URL(local.base).port)
      return route.continue();
    return route.abort('blockedbyclient');
  });
  const page=await context.newPage();
  page.setDefaultTimeout(20000);
  await page.goto(local.base+'/accounting.html');
  await page.locator('.sac-root').waitFor();
  await page.evaluate(()=>window.madar.standaloneAccountingCommand({
    expectedRevision:0,command:{type:'party.register',eventId:'QA-PASSPORT-PARTY',
      partyId:'QA-CUSTOMER-1',name:'مشتری QA پاسپورت',kind:'customer'},
  }));
  await ordersPage(page);
  await page.getByRole('textbox',{name:'نام مشتری'}).fill('مشتری QA پاسپورت');
  await page.getByRole('textbox',{name:'شرح سفارش'}).fill('پاسپورت آزمایشی');
  await page.getByRole('textbox',{name:'تعداد سفارش'}).fill('100');
  await page.getByRole('textbox',{name:'تعداد برنامه‌ریزی تولید'}).fill('120');
  await page.getByRole('textbox',{name:/قیمت واحد/}).fill('25000');
  await page.getByRole('button',{name:'حرفه‌ای'}).click();
  await page.getByRole('textbox',{name:'شناسه طرف حساب موجود (اختیاری)'})
    .fill('QA-CUSTOMER-1');
  const stages=[
    ['print',200000,220000],['bindery',100000,110000],['sewing',100000,90000],
    ['laser',80000,85000],['packaging',90000,95000],['shipping',60000,65000],
  ];
  for(let i=0;i<stages.length;i++){
    await page.getByRole('button',{name:'افزودن مرحله'}).click();
    await page.getByLabel('نوع مرحله '+(i+1)).selectOption(stages[i][0]);
    await page.getByLabel('هزینه مرحله '+(i+1)).fill(String(stages[i][1]));
  }
  await page.getByRole('button',{name:'ساده',exact:true}).click();
  assert.equal(await page.getByLabel('هزینه مرحله 1').inputValue(),'200000');
  await page.getByRole('button',{name:'ذخیره سفارش'}).click();
  await revision(page,1);
  let order=await current(page);
  assert.equal(order.quantity,100);
  assert.equal(order.productionQuantity,120);
  assert.equal(order.estimatedCostTotal,630000);
  assert.equal(order.actualCostTotal,null);
  assert.equal(order.financialEventCreated,false);
  let nextRevision=1;
  for(let i=0;i<stages.length;i++){
    await page.getByLabel('هزینه واقعی مرحله '+(i+1)).fill(String(stages[i][2]));
    await page.getByLabel('تاریخ هزینه مرحله '+(i+1)).fill('2026-11-12');
    await page.locator('.taraz-orders-finance-line').nth(i)
      .getByRole('button',{name:'ثبت هزینه واقعی'}).click();
    await revision(page,++nextRevision);
    order=await current(page);
    assert.equal(order.costRecords.find(c=>c.stage_index===i).status,'recorded');
    page.once('dialog',dialog=>dialog.accept());
    await page.locator('.taraz-orders-finance-line').nth(i)
      .getByRole('button',{name:'تأیید مالی هزینه'}).click();
    await revision(page,++nextRevision);
  }
  assert.equal((await current(page)).actualCostTotal,665000);

  await page.getByLabel('مبلغ پرداخت سفارش').fill('500000');
  await page.getByLabel('روش پرداخت سفارش').fill('bank-transfer');
  await page.getByRole('button',{name:'ثبت در پرونده سفارش (نه بانک)'}).click();
  await revision(page,++nextRevision);
  order=await current(page);
  assert.equal(order.paymentBalance,2500000,
    'Recording a payment is not proof of settlement');
  const payment=order.payments[0];
  await page.getByLabel('مرجع تسویه '+payment.id).fill('QA-TRX-SINGLE-1');
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'تأیید دستی تسویه'}).click();
  await revision(page,++nextRevision);
  order=await current(page);
  assert.equal(order.paymentBalance,2000000);
  assert.equal(order.payments[0].status,'settled');
  assert.equal(order.payments[0].approved_by,'qa-invoice-operator');
  await page.getByLabel('مبلغ پرداخت سفارش').fill('2000000');
  await page.getByLabel('روش پرداخت سفارش').fill('bank-transfer');
  await page.getByLabel('طرف حساب پرداخت سفارش').fill('مشتری QA پاسپورت');
  await page.getByRole('button',{name:'ثبت در پرونده سفارش (نه بانک)'}).click();
  await revision(page,++nextRevision);
  order=await current(page);
  await page.getByLabel('مرجع تسویه '+order.payments[1].id).fill('QA-TRX-SINGLE-2');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('.taraz-orders-finance-line').filter({
    has:page.getByLabel('مرجع تسویه '+order.payments[1].id)})
    .getByRole('button',{name:'تأیید دستی تسویه'}).click();
  await revision(page,++nextRevision);
  order=await current(page);
  assert.equal(order.paymentBalance,0);
  assert.equal(order.settledPaymentTotal,2500000);
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'تأیید سفارش'}).click();
  await revision(page,++nextRevision);
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'شروع اجرا'}).click();
  await revision(page,++nextRevision);
  await page.getByRole('textbox',{name:'تولید واقعی (اختیاری)'}).fill('120');
  await page.getByRole('textbox',{name:'ضایعات واقعی (اختیاری)'}).fill('5');
  await page.getByRole('textbox',{name:'مازاد سالم (اختیاری)'}).fill('15');
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'ثبت اندازه‌گیری با تأیید'}).click();
  await revision(page,++nextRevision);
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'ثبت تحویل'}).click();
  await revision(page,++nextRevision);
  order=await current(page);
  assert.equal(order.productionReconciliation.state,'balanced');
  assert.equal(order.realizedProfit,1835000);
  assert.ok(order.financialPreview?.previewDigest);
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'تأیید بسته ارجاع مالی (بدون صدور سند)'}).click();
  await revision(page,++nextRevision);
  await page.getByLabel('تاریخ پیش‌نویس حسابداری سفارش').fill('2026-11-12');
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'بازبینی و تأیید انسانی ایجاد پیش‌نویس حسابداری'}).click();
  await page.getByText('پیش‌نویس حسابداری ایجاد یا بازخوانی شد').waitFor();
  let ledger=await page.evaluate(()=>window.madar.standaloneAccountingRead());
  const draft=Object.values(ledger.view.invoices)[0];
  assert.equal(draft.status,'draft');
  assert.equal(draft.sourceId,order.id);
  assert.equal(draft.sourceType,'taraz.order');
  assert.equal(draft.total,2500000);
  assert.equal(draft.postedEntryId,null);
  assert.deepEqual(ledger.view.journals,[]);
  await page.getByRole('button',{name:'بررسی سفارش با ابزارهای محلی'}).click();
  await page.getByText('بررسی ابزارهای محلی انجام شد.').waitFor();
  await page.getByLabel('متن حافظه پیشنهادی سفارش')
    .fill('خروجی پاسپورت با سند هزینه و پرداخت‌ها کنترل شد');
  await page.getByRole('button',{name:'ثبت پیشنهاد، بدون تأیید خودکار'}).click();
  await page.getByText('در انتظار بررسی انسان').waitFor();
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'تأیید یادداشت'}).click();
  await page.getByText('پذیرفته‌شده').waitFor();
  const memory=await page.evaluate(async id=>window.madar.tarazAgentMemoryList(id),order.id);
  assert.equal(memory.revision,2);
  assert.equal(memory.entries.length,1);
  assert.equal(memory.entries[0].status,'accepted');
  assert.equal(memory.entries[0].source_revision,nextRevision);
  assert.equal(memory.entries[0].reviewed_by,'qa-invoice-operator');
  await page.reload();
  await ordersPage(page);
  order=await current(page);
  assert.equal(order.costRecords.length,6);
  assert.equal(order.actualCostTotal,665000);
  assert.equal(order.payments[0].status,'settled');
  assert.equal(order.financeHandoff.prepared_by,'qa-invoice-operator');
  assert.equal(order.auditTrail.length,nextRevision);
  await page.getByRole('button',{name:'مشاهده جزئیات'}).first().click();
  await page.getByRole('button',{name:'بررسی سفارش با ابزارهای محلی'}).click();
  await page.getByText('خروجی پاسپورت با سند هزینه و پرداخت‌ها کنترل شد').waitFor();
  ledger=await page.evaluate(()=>window.madar.standaloneAccountingRead());
  assert.equal(ledger.revision,2);
  assert.deepEqual(ledger.view.journals,[]);
});
