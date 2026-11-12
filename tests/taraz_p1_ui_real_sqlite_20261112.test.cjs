'use strict';
/** Actual compiled UI -> localhost bridge -> authenticated Python API -> SQLite.
 * Synthetic operator/company only; NO production ledger, EXE install or issue.
 * Unlike previous browser tests, NO in-memory fake finance host is used.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs/promises');
const {spawn}=require('node:child_process');

const ROOT=path.resolve(__dirname,'..');
const FIXTURE=path.join(ROOT,'tests','taraz_p1_real_backend_http_fixture_20261112.py');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'', 'npm','node_modules','playwright'));}

async function startBackend(){
  const child=spawn('py',['-3.12','-B',FIXTURE],{cwd:ROOT,
    windowsHide:true,stdio:['ignore','pipe','pipe'],
    env:{...process.env,PYTHONDONTWRITEBYTECODE:'1',
      TARAZ_QA_WEB_ASSETS:'current-source-dist'}});
  let errors='';
  child.stderr.on('data',chunk=>{errors+=String(chunk).slice(0,2000);});
  const line=await Promise.race([
    new Promise((resolve,reject)=>{
      let buffer='';
      child.stdout.on('data',chunk=>{
        buffer+=chunk.toString('utf8');
        if(buffer.includes('\n'))resolve(buffer.split('\n')[0]);
      });
      child.on('error',reject);
      child.on('exit',code=>reject(Error('QA Python backend exited '+code+': '+errors)));
    }),
    new Promise((_,reject)=>setTimeout(()=>reject(Error('QA Python startup timeout '+errors)),12000))
  ]);
  const info=JSON.parse(line);
  assert.equal(info.isolated,true);
  assert.ok(Number.isInteger(info.port)&&info.port>0);
  const base='http://127.0.0.1:'+info.port;
  return {base,async stop(){
    if(child.exitCode!==null)return;
    try{await fetch(base+'/__qa_shutdown',{method:'POST',signal:AbortSignal.timeout(1500)});}
    catch{/* Shutdown is best-effort; never touch unrelated PIDs. */}
    await Promise.race([new Promise(resolve=>child.once('exit',resolve)),
      new Promise(resolve=>setTimeout(resolve,2000))]);
    if(child.exitCode===null)throw Error('QA-only Python backend did not stop gracefully');
  }};
}

test('compiled Taraz UI persists invoice and print templates through REAL ephemeral Python/SQLite',async t=>{
  const backend=await startBackend();
  t.after(()=>backend.stop());
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());
  const context=await browser.newContext({viewport:{width:1440,height:1050},
    reducedMotion:'reduce',serviceWorkers:'block'});
  t.after(()=>context.close());
  let offLocal=0;
  await context.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(url.hostname==='127.0.0.1'&&url.port===new URL(backend.base).port)
      return route.continue();
    offLocal++;
    return route.abort('blockedbyclient');
  });
  const page=await context.newPage();
  page.setDefaultTimeout(14000);
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(backend.base+'/accounting.html');
  await page.locator('.sac-root').waitFor();
  const initial=await page.evaluate(()=>window.madar.standaloneAccountingRead());
  assert.equal(initial.revision,0);
  assert.equal(Object.keys(initial.view.invoices).length,0);

  await page.locator('[data-accounting-action="invoice"]:visible').first().click();
  let pane=page.locator('.sac-invoice-beginner-pane');
  await pane.waitFor();
  await pane.getByRole('button',{name:'مشتری جدید'}).click();
  await pane.getByRole('textbox',{name:'شناسه مشتری جدید'}).fill('QA-ACTUAL-1');
  await pane.getByRole('textbox',{name:'نام مشتری جدید'}).fill('مشتری آزمایشی واقعی');
  page.once('dialog',dialog=>dialog.accept());
  await pane.getByRole('button',{name:'تأیید و ثبت مشتری در دفتر'}).click();
  await page.waitForFunction(()=>document.querySelector('.sac-invoice-beginner-pane')?.textContent.includes('مشتری آزمایشی واقعی'));
  await pane.getByRole('textbox',{name:'شرح ردیف 1'}).fill('چاپ تست رابط');
  await pane.getByRole('textbox',{name:'تعداد ردیف 1'}).fill('4');
  await pane.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('3000');
  await pane.getByRole('textbox',{name:'یادداشت سند'}).fill('صرفاً دادهٔ تست QA');
  await pane.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
  await page.getByRole('region',{name:'پیش‌نمایش چاپ فاکتور'}).waitFor();
  let data=await page.evaluate(()=>window.madar.standaloneAccountingRead());
  assert.equal(data.revision,2,'Party registration and draft must be two persistent events');
  const [invoice]=Object.values(data.view.invoices);
  assert.equal(invoice.status,'draft');
  assert.equal(invoice.total,12000);
  assert.equal(invoice.partyId,'QA-ACTUAL-1');
  assert.equal(invoice.note,'صرفاً دادهٔ تست QA');
  assert.equal(data.view.journals.length,0,'No official financial posting');

  await page.reload();
  await page.locator('.sac-root').waitFor();
  data=await page.evaluate(()=>window.madar.standaloneAccountingRead());
  assert.equal(data.revision,2,'Read must come from reopened SQLite-backed API');
  assert.equal(data.view.invoices[invoice.id].total,12000);
  const invoiceTab=page.locator('[data-accounting-tab="invoice"]:visible').first();
  await invoiceTab.click();
  await page.getByRole('button',{name:'ویرایش پیش‌نویس'}).first().click();
  // Editing opens professional mode on the SAME persisted domain model.
  await page.getByRole('textbox',{name:'شرح ردیف 1'}).count();
  assert.match(await page.locator('.sac-root').innerText(),/ویرایش پیش‌نویس/);
  await page.getByRole('group',{name:'نوع نمایش فرم فاکتور'})
    .getByRole('button',{name:'ساده و سریع'}).click();
  const editPane=page.locator('.sac-invoice-beginner-pane');
  await editPane.waitFor();
  assert.equal(await editPane.getByRole('textbox',{name:'شرح ردیف 1'}).inputValue(),
    'چاپ تست رابط');
  assert.equal(await editPane.getByRole('textbox',{name:'تعداد ردیف 1'}).inputValue(),'4');
  await editPane.getByRole('textbox',{name:'تعداد ردیف 1'}).fill('5');
  await editPane.getByRole('textbox',{name:'یادداشت سند'}).fill('ویرایش تأییدشدهٔ QA');
  await editPane.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
  await page.getByRole('region',{name:'پیش‌نمایش چاپ فاکتور'}).waitFor();
  const revised=await page.evaluate(()=>window.madar.standaloneAccountingRead());
  assert.equal(revised.revision,3);
  assert.equal(revised.view.invoices[invoice.id].total,15000);
  assert.equal(revised.view.invoices[invoice.id].note,'ویرایش تأییدشدهٔ QA');
  assert.equal(revised.view.invoices[invoice.id].status,'draft');
  assert.deepEqual(revised.view.journals,[]);

  // A real backend print template is persisted per disposable company, without
  // writing financial journal entries. This checks frontend/backend parity.
  const before=await page.evaluate(()=>window.madar.standaloneAccountingRead());
  const print=await page.evaluate(async()=>{
    const seed={format:'madar-print-layout-v1',version:1,title:'طرح QA',page:'A5',
      orientation:'portrait',margin:7,font:'Vazirmatn',color:'#203239',logo:'',
      logoLayout:{x:9,y:9,width:26,height:17},companyHeader:'چاپ تست',
      companySubtitle:'دادهٔ آزمایش',footerText:'QA',
      fields:['title','seller','buyer','number','date','note'].map(id=>({
        id,label:id,visible:true,x:90,y:40,size:11})),
      table:{y:73,showQuantity:true,showPrice:true,showTotal:true,
        rowHeight:8.5,columns:['description','quantity','price','total'],
        labels:{description:'شرح',quantity:'تعداد',price:'فی',total:'مبلغ'}},
      totalsY:260,signature:'امضا'};
    const saved=await window.madar.standaloneAccountingTemplateSave('print',seed.title,seed);
    const listed=await window.madar.standaloneAccountingTemplateList('print');
    return {saved,listed};
  });
  assert.equal(print.listed.templates.length,1);
  assert.equal(print.listed.templates[0].id,print.saved.id);
  assert.equal(print.listed.templates[0].data.page,'A5');
  // Now edit and save from the ACTUAL compiled print-designer UI, through the
  // exact same Python template host (not a synthetic template mock).
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
  // The current professional editor may be considered dirty even if its
  // persisted values were only reopened; explicitly discard QA draft UI state.
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('dialog',{name:'فهرست بخش‌های تراز'})
    .getByRole('button',{name:'طراحی فرم فاکتور'}).click();
  await page.getByRole('heading',{name:'طراح بصری قالب فاکتور'}).waitFor();
  await page.getByRole('textbox',{name:'نام قالب'}).fill('قالب اصلاح‌شده از رابط QA');
  await page.getByRole('button',{name:'افزودن ستون سفارشی'}).click();
  await page.getByRole('textbox',{name:'عنوان ستون سفارشی custom_1'}).fill('واحد اختصاصی QA');
  await page.getByRole('combobox',{name:'متغیر ستون سفارشی custom_1'}).selectOption('unit');
  await page.getByRole('button',{name:'ذخیره قالب'}).click();
  await page.waitForFunction(async()=>{
    const response=await window.madar.standaloneAccountingTemplateList('print');
    return response.templates.some(template=>template.title==='قالب اصلاح‌شده از رابط QA');
  });
  const savedByUi=await page.evaluate(()=>window.madar.standaloneAccountingTemplateList('print'));
  const savedCustom=savedByUi.templates.find(template=>
    template.title==='قالب اصلاح‌شده از رابط QA');
  assert.ok(savedCustom);
  assert.deepEqual(savedCustom.data.table.customColumns,
    [{id:'custom_1',label:'واحد اختصاصی QA',source:'unit'}]);
  assert.ok(savedCustom.data.table.columns.includes('custom_1'));
  await page.reload();
  await page.locator('.sac-root').waitFor();
  const reloadedTemplates=await page.evaluate(()=>window.madar.standaloneAccountingTemplateList('print'));
  const retainedCustom=reloadedTemplates.templates.find(template=>
    template.title==='قالب اصلاح‌شده از رابط QA');
  assert.ok(retainedCustom);
  assert.equal(retainedCustom.data.table.customColumns[0].source,'unit');

  // The draft is a real SQLite document. Export it through the actual
  // invoice-screen button, not by calling the renderer behind the UI.
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
  await page.getByRole('dialog',{name:'فهرست بخش‌های تراز'})
    .locator('button[data-accounting-tab="invoice"]').first().click();
  await page.getByText('تنظیمات بیشتر چاپ و صدور فاکتور').click();
  await page.getByRole('combobox',{name:'قالب چاپ فاکتور'}).selectOption('custom');
  const [pdf]=await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button',{name:'PDF',exact:true}).first().click()
  ]);
  assert.ok(pdf.suggestedFilename().endsWith('.pdf'));
  const bytes=await fs.readFile(await pdf.path());
  const pdfData=bytes.toString('latin1');
  assert.ok(pdfData.startsWith('%PDF-1.4'));
  assert.match(pdfData,/\/Type \/Page \/Parent/);
  assert.match(pdfData,/startxref\s+\d+\s+%%EOF/);
  assert.ok(bytes.length>1000);

  // Separate operational order lifecycle, same company, REAL order SQLite.
  await page.getByRole('button',{name:'بازکردن فهرست بخش‌های تراز'}).click();
  await page.getByRole('dialog',{name:'فهرست بخش‌های تراز'})
    .getByRole('button',{name:'سفارش‌ها'}).first().click();
  const orders=page.getByRole('region',{name:'مدیریت سفارش‌های تراز'});
  await orders.waitFor();
  await orders.getByRole('textbox',{name:'نام مشتری'}).fill('مشتری سفارش آزمایشی');
  await orders.getByRole('textbox',{name:'شرح سفارش'}).fill('سفارش جعبه چاپی');
  await orders.getByRole('textbox',{name:'تعداد سفارش'}).fill('100');
  await orders.getByRole('textbox',{name:'تعداد برنامه‌ریزی تولید'}).fill('120');
  await orders.getByRole('group',{name:'سطح فرم سفارش'})
    .getByRole('button',{name:'حرفه‌ای'}).click();
  await orders.getByRole('textbox',{name:/ارجاع پروژه مرتبط/}).fill('QA-PO-20261112');
  await orders.getByRole('button',{name:'افزودن مرحله'}).click();
  await orders.getByRole('combobox',{name:'نوع مرحله 1'}).selectOption('print');
  await orders.getByRole('textbox',{name:'تأمین کننده مرحله 1'}).fill('چاپخانه آزمایشی');
  await orders.getByRole('textbox',{name:'هزینه مرحله 1'}).fill('2000');
  await orders.getByRole('button',{name:'ذخیره سفارش'}).click();
  await orders.getByText('سفارش در میزبان ذخیره شد. هیچ سند مالی ایجاد نشده است.').waitFor();
  let orderList=await page.evaluate(()=>window.madar.tarazOrderList());
  assert.equal(orderList.orders.length,1);
  let savedOrder=orderList.orders[0];
  assert.equal(savedOrder.quantity,100);
  assert.equal(savedOrder.productionQuantity,120);
  assert.equal(savedOrder.scrapQuantity,null);
  assert.equal(savedOrder.productionOverageQuantity,20);
  assert.equal(savedOrder.wasteQuantity,null,'20 planned overage must NOT be called scrap');
  assert.equal(savedOrder.status,'draft');
  assert.equal(savedOrder.costStages[0].estimatedCost,2000);
  assert.equal(savedOrder.projectReference,'QA-PO-20261112');
  // Remove the one-shot unsaved-editor handler if no such dialog was raised.
  // Otherwise both registered handlers race to accept the order confirmation.
  page.removeAllListeners('dialog');
  const acceptedOrderConfirmations=[];
  page.on('dialog',dialog=>{
    acceptedOrderConfirmations.push(dialog.message());
    void dialog.accept();
  });
  await orders.getByRole('button',{name:'تأیید سفارش'}).click();
  await orders.getByRole('button',{name:'شروع اجرا'}).click();
  await orders.getByRole('textbox',{name:'تولید واقعی (اختیاری)'}).fill('120');
  await orders.getByRole('textbox',{name:'ضایعات واقعی (اختیاری)'}).fill('5');
  await orders.getByRole('textbox',{name:'مازاد سالم (اختیاری)'}).fill('15');
  await orders.getByRole('button',{name:'ثبت اندازه‌گیری با تأیید'}).click();
  orderList=await page.evaluate(()=>window.madar.tarazOrderList());
  savedOrder=orderList.orders[0];
  assert.equal(savedOrder.status,'in_production');
  assert.equal(savedOrder.scrapQuantity,5);
  assert.equal(savedOrder.healthySurplusQuantity,15);
  assert.equal(savedOrder.productionReconciliation.state,'balanced');
  await orders.getByRole('button',{name:'ثبت تحویل'}).click();
  orderList=await page.evaluate(()=>window.madar.tarazOrderList());
  assert.equal(orderList.orders[0].status,'delivered');
  assert.equal(orderList.orders[0].financialEventCreated,false);
  assert.equal(acceptedOrderConfirmations.length,4,
    'Approve, start, record counts and deliver require four operator confirmations');
  await page.reload();
  await page.locator('.sac-root').waitFor();
  orderList=await page.evaluate(()=>window.madar.tarazOrderList());
  assert.equal(orderList.orders[0].status,'delivered','Order readback after full UI reload');
  const after=await page.evaluate(()=>window.madar.standaloneAccountingRead());
  assert.equal(before.revision,after.revision);
  assert.deepEqual(after.view.journals,[]);
  assert.deepEqual(errors,[]);
  assert.equal(offLocal,0,'Compiled app must not make any external requests in QA');
});
