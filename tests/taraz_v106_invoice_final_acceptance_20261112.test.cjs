'use strict';
/** Final frozen 1.0.6 invoice-only acceptance. Synthetic host, no live ledger.
 * The Edge page executes the immutable release bundle, never mutable source.
 * EXE parity checks extract PyInstaller archive members, not build-report claims.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const ROOT=path.resolve(__dirname,'..');
// Keep the historical baseline reproducible while allowing explicit tests of
// the corrected immutable EXE. Each choice pins source and binary independently.
const RELEASE_PINS=Object.freeze({
  'build-777cb53341bb':{
    exe:'54aa3f8ca32703bbc20a033a281197fb1e1cbe88889d6951e92803c702b4b6a4',
    source:'d07e92f054066858459d4d836de7bf4a56ece0362e8ae9ece755e743ef7a5fcf'
  },
  'build-e1723a88abe2':{
    exe:'eded01af7c8e2676b427a30f8bdabd41d59fba9df4e99a42995cd2d6184f6251',
    source:'d926f949b1d002f9a9cdad55265efd313908d61e54e077a4b1b86d06cedc2c1b'
  },
  'build-250eead995ca':{
    exe:'ca290b6c250be0d2c09c92502426d0649343255a019dd1a93f2c2cb18671d308',
    source:'b6d63424fbccda75d6fe2699c7ffc07442d403d4e5564b5563389b06eea45362'
  },
  'build-98e815dd931c':{
    exe:'b7d27d1a44c6980a3121827eee9d502ea52a8c27f6d75f67ac67f86bddd09db7',
    source:'9248a80030bbbfb1d794b2169a9ea0f17d70facf968de328195bccfd64a78861'
  },
  'build-7e54afa3c1a5':{
    exe:'e7020686f15d67b2ae888caef3c65b271494ec98a672fc902f390f35ae33ee63',
    source:'91b33ad118c8b855dc1207d491b7fc01675a8d1caa5fc30717beb4d4a3cfc642'
  },
  'build-357bec1519e9':{
    exe:'f369f99947ad5c7d7c436e4e5716466d5b69e2aeb807b9fba052a26664f3d978',
    source:'800134e38c7a865aa6a8dfbf48d6cf527a8cd297c1edb6d9739b4a4242fb184d'
  }
});
const BUILD_ID=process.env.TARAZ_TEST_FROZEN_BUILD||'build-777cb53341bb';
if(!Object.hasOwn(RELEASE_PINS,BUILD_ID))throw Error('Unknown immutable Taraz QA build');
const BUILD=path.resolve(ROOT,'..','..','MTR-NEXT-UPDATE-CANDIDATES-20261110',
  'taraz-v1.0.6-aaas',BUILD_ID);
const EXE=path.join(BUILD,'binary','Taraz.exe');
const WEB=path.join(BUILD,'web','dist');
const ORIGIN='https://taraz-final-invoice-qa.invalid';
const EXE_SHA=RELEASE_PINS[BUILD_ID].exe;
const FREEZE_SHA=RELEASE_PINS[BUILD_ID].source;
const sha=buffer=>crypto.createHash('sha256').update(buffer).digest('hex');
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'','npm','node_modules','playwright'));}

function releaseAssets(){
  assert.ok(fs.statSync(BUILD).isDirectory(),'Final immutable build directory missing');
  const report=JSON.parse(fs.readFileSync(path.join(BUILD,'build-report.json'),'utf8'));
  assert.equal(report.sourceFreezeSha256,FREEZE_SHA);
  assert.equal(report.exeSha256,EXE_SHA);
  assert.equal(report.compiled.compiledByteParity,true,'builder claims parity; independently check below');
  assert.equal(sha(fs.readFileSync(EXE)),EXE_SHA,'actual frozen EXE hash');
  const html=fs.readFileSync(path.join(WEB,'accounting.html'));
  const text=html.toString('utf8');
  const jsName=text.match(/\bsrc=["']\.\/assets\/([^"']+\.js)["']/)?.[1];
  const cssName=text.match(/\bhref=["']\.\/assets\/([^"']+\.css)["']/)?.[1];
  assert.ok(jsName&&cssName,'HTML must reference hashed JS and CSS');
  const selected=['accounting.html','assets/'+jsName,'assets/'+cssName];
  const bytes=selected.map(file=>fs.readFileSync(path.join(WEB,file)));
  for(let i=0;i<selected.length;i++)assert.equal(sha(bytes[i]),
    report.compiled.assetsSha256[selected[i]],'manifest mismatch '+selected[i]);
  return {report,selected,bytes,js:bytes[1].toString('utf8'),
    css:bytes[2].toString('utf8'),names:{js:jsName,css:cssName}};
}

test('exact final EXE embeds byte-identical frozen accounting HTML/JS/CSS',()=>{
  const built=releaseAssets();
  // Only read EXE archive: no execution of installed or release binary.
  const program=[
    'import sys, json, hashlib',
    'from PyInstaller.archive.readers import CArchiveReader',
    'archive=CArchiveReader(sys.argv[1])',
    'names={name.replace(chr(92),chr(47)):name for name in archive.toc}',
    'result={}',
    'for relative in sys.argv[2:]:',
    '  actual=archive.extract(names["dist/"+relative])',
    '  if not isinstance(actual,bytes): raise TypeError(relative)',
    '  result[relative]={"sha256":hashlib.sha256(actual).hexdigest(),"bytes":len(actual)}',
    'print(json.dumps(result,sort_keys=True))'
  ].join('\n');
  const process=spawnSync('python',['-B','-c',program,EXE,...built.selected],
    {encoding:'utf8',windowsHide:true,timeout:30000,maxBuffer:1024*1024});
  assert.equal(process.error,undefined,'Python archive inspection process');
  assert.equal(process.status,0,'EXE extraction: '+String(process.stderr).slice(-1000));
  const embedded=JSON.parse(process.stdout);
  for(let i=0;i<built.selected.length;i++){
    const file=built.selected[i],fromExe=embedded[file];
    assert.equal(fromExe.sha256,sha(built.bytes[i]),'actual EXE member differs: '+file);
    assert.equal(fromExe.bytes,built.bytes[i].length,'size differs: '+file);
  }
  assert.equal(built.report.version,'1.0.6');
  console.log('FINAL_V106_BINARY_PARITY',JSON.stringify({
    exeSha256:EXE_SHA,build:path.basename(BUILD),
    javascript:built.selected[1],javascriptSha256:sha(built.bytes[1]),
    stylesheet:built.selected[2],stylesheetSha256:sha(built.bytes[2]),
    parity:'extracted from EXE, SHA-256 and byte length equal'}));
});

async function openTestPage(browser,built,{profile='standard'}={}){
  const context=await browser.newContext({viewport:{width:1440,height:960},
    serviceWorkers:'block',reducedMotion:'reduce',acceptDownloads:false});
  let externalBlocked=0;
  await context.route('**/*',route=>{
    if(route.request().url()===ORIGIN+'/accounting.html')
      return route.fulfill({status:200,contentType:'text/html',body:
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8"></head><body><div id="root"></div></body></html>'});
    externalBlocked++;
    return route.abort('blockedbyclient');
  });
  await context.addInitScript(profile=>{
    const poster={id:'ITEM-POSTER',sku:'POSTER-2',name:'چاپ پوستر',kind:'service',
      unit:'متر مربع',active:true};
    const view={currency:'RIAL',journals:[],
      accounts:{'4000':{id:'4000',name:'درآمد خدمات',kind:'revenue'}},
      parties:{
        'EXISTING-1':{id:'EXISTING-1',name:'مشتری قبلی',kind:'customer'},
        ...(profile==='walkin-existing'?{
          'WALKIN-1':{id:'WALKIN-1',name:'مشتری حضوری',kind:'customer'}}:{})
      },items:{[poster.id]:poster,
        'ITEM-INACTIVE':{id:'ITEM-INACTIVE',sku:'OLD',name:'چاپ قدیمی',
          kind:'goods',unit:'جعبه',active:false}},
      invoices:{},bills:{},receipts:{},payments:{},proformas:{},
      taxRules:{},contractorJobs:{},returns:{},cashAccounts:{},
      companyProfile:{legalName:'شرکت تست بی‌خطر'},
      cheques:{},warehouses:{},stock:{},stockMovements:{},closedThrough:null,
      sequence:{invoice:0,bill:0}};
    let revision=0;
    const proposal={schema:1,source:'madar',id:'b'.repeat(32),
      taskId:'TASK-TEST',projectId:'PROJECT-TEST',
      title:'شرح پیشنهادی مدار - داده تست'};
    window.__invoiceQa={commands:[],view,proposal,reads:0,external:false};
    const snapshot=()=>({revision,view,capabilities:{canManage:true,canDraft:true,canAdmin:true},
      currentUser:{username:'invoice-final-qa',role:'admin',jobTitle:''}});
    window.madar={
      standaloneAccountingRead:async()=>{
        window.__invoiceQa.reads++;
        return snapshot();
      },
      standaloneAccountingTemplateList:async()=>({templates:[],defaultId:''}),
      tarazIntegrationList:async()=>({connected:true,requests:[proposal],recovery:[],
        invalidCount:0,financialEventCreated:false}),
      standaloneAccountingCommand:async({command,expectedRevision})=>{
        if(expectedRevision!==revision)throw Error('QA revision mismatch');
        const copy=structuredClone(command);
        window.__invoiceQa.commands.push(copy);
        if(command.type==='party.register'){
          if(view.parties[command.partyId])throw Error('QA duplicate party');
          view.parties[command.partyId]={id:command.partyId,name:command.name,
            kind:command.kind,creditLimit:command.creditLimit};
        }else if(command.type==='invoice.create'||command.type==='proforma.create'){
          if(!view.parties[command.partyId])throw Error('QA unknown party');
          if(!command.lines?.length||command.lines.some(line=>!line.description||
              line.quantity<=0||!Number.isSafeInteger(line.unitPrice)))
            throw Error('QA invalid rows');
          const quote=command.type==='proforma.create';
          const id=command[quote?'proformaId':'invoiceId'];
          const lines=command.lines.map(line=>({...line,total:line.quantity*line.unitPrice}));
          const subtotal=lines.reduce((sum,row)=>sum+row.total,0);
          const collection=view[quote?'proformas':'invoices'];
          if(collection[id])throw Error('QA duplicate document');
          collection[id]={id,partyId:command.partyId,documentDate:command.documentDate,
            lines,subtotal,discount:command.discount,tax:command.tax,
            total:subtotal-command.discount+command.tax,
            note:command.note||'',status:'draft',allocated:0,
            createdAt:'2026-11-11T22:30:00Z',createdBy:'qa-user',
            number:null,postedEntryId:null};
        }else throw Error('QA REFUSED unrequested financial mutation: '+command.type);
        revision++;
        return snapshot();
      }
    };
  },profile);
  const page=await context.newPage();
  page.setDefaultTimeout(13000);
  const uncaught=[];
  page.on('pageerror',error=>uncaught.push(error.message));
  await page.goto(ORIGIN+'/accounting.html');
  await page.addStyleTag({content:built.css});
  await page.addScriptTag({content:built.js,type:'module'});
  await page.locator('.sac-root').waitFor();
  return {context,page,uncaught,externalBlocked:()=>externalBlocked};
}

async function newInvoice(page){
  await page.locator('[data-accounting-action="invoice"]:visible').first().click();
  const pane=page.locator('.sac-invoice-beginner-pane');
  await pane.waitFor();
  return pane;
}
async function savedPreview(page,kind){
  await page.getByRole('region',{name:kind==='proforma'?
    'پیش‌نمایش چاپ پیش‌فاکتور':'پیش‌نمایش چاپ فاکتور'}).waitFor();
  const section=page.locator('.sac-saved-print-preview');
  assert.match(await section.locator('iframe').getAttribute('src'),/^blob:/);
  assert.equal(await section.locator('a[href^="blob:"]').count(),1);
  assert.equal(await page.evaluate(()=>window.__invoiceQa.commands.filter(c=>
    ['invoice.issue','invoice.approve','journal.manual','receipt.record'].includes(c.type)).length),0);
}

test('frozen Edge invoice flows exercise actual compiled code against isolated synthetic host',async t=>{
  const built=releaseAssets();
  const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
    args:['--no-first-run','--disable-background-networking']});
  t.after(()=>browser.close());

  await t.test('new customer confirmation, catalog reject then accept, unit, auto-line, note edit, draft+PDF',async()=>{
    const {context,page,uncaught,externalBlocked}=await openTestPage(browser,built);
    try{
      const pane=await newInvoice(page);
      await pane.getByRole('button',{name:'مشتری جدید'}).click();
      await pane.getByRole('textbox',{name:'شناسه مشتری جدید'}).fill('NEW-TEST-1');
      await pane.getByRole('textbox',{name:'نام مشتری جدید'}).fill('مشتری ساختگی جدید');
      page.once('dialog',dialog=>dialog.dismiss());
      await pane.getByRole('button',{name:'تأیید و ثبت مشتری در دفتر'}).click();
      assert.deepEqual(await page.evaluate(()=>window.__invoiceQa.commands),[],
        'canceling confirmation must not register a party');
      page.once('dialog',dialog=>dialog.accept());
      await pane.getByRole('button',{name:'تأیید و ثبت مشتری در دفتر'}).click();
      await page.waitForFunction(()=>window.__invoiceQa.commands.length===1);
      assert.equal((await page.evaluate(()=>window.__invoiceQa.commands))[0].type,'party.register');
      await pane.getByRole('textbox',{name:'شرح ردیف 1'}).fill('چاپ پوستر');
      const suggestion=pane.getByRole('group',{name:'پیشنهاد کاتالوگ ردیف 1'});
      await suggestion.waitFor();
      assert.match(await suggestion.innerText(),/متر مربع/);
      await suggestion.getByRole('button',{name:'رد پیشنهاد'}).click();
      assert.equal(await suggestion.count(),0);
      await pane.getByRole('textbox',{name:'شرح ردیف 1'}).fill('چاپ پوستر ویژه');
      await suggestion.waitFor();
      await suggestion.getByRole('button',{name:'تأیید کد پیشنهادی'}).click();
      assert.match(await pane.locator('[data-beginner-row="0"]').innerText(),/متر مربع/);
      await pane.getByRole('textbox',{name:'تعداد ردیف 1'}).fill('2');
      await pane.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('17000');
      await pane.getByRole('textbox',{name:'قیمت ردیف 1'}).press('Enter');
      await pane.locator('[data-beginner-row="1"]').waitFor();
      await pane.getByRole('textbox',{name:'یادداشت سند'}).fill('متن نوشته‌شدهٔ اپراتور');
      await pane.getByRole('textbox',{name:'توضیح تکمیلی'}).fill('شرح تکمیلی آزمایشی');
      await pane.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
      await page.waitForFunction(()=>window.__invoiceQa.commands.some(c=>c.type==='invoice.create'));
      await savedPreview(page,'invoice');
      const commands=await page.evaluate(()=>window.__invoiceQa.commands);
      assert.deepEqual(commands.map(c=>c.type),['party.register','invoice.create']);
      const invoice=commands[1];
      assert.equal(invoice.partyId,'NEW-TEST-1');
      assert.equal(invoice.lines.length,1,'auto-added blank last row must not be posted');
      assert.equal(invoice.lines[0].itemId,'ITEM-POSTER');
      assert.equal(invoice.lines[0].quantity,2);
      assert.match(invoice.note,/متن نوشته‌شدهٔ اپراتور/);
      assert.match(invoice.note,/شرح تکمیلی آزمایشی/);
      assert.deepEqual(uncaught,[]);
      assert.ok(externalBlocked()>=0);
    }finally{await context.close();}
  });

  await t.test('walk-in existing account reuses real ID with no extra party write',async()=>{
    const {context,page,uncaught}=await openTestPage(browser,built,{profile:'walkin-existing'});
    try{
      const pane=await newInvoice(page);
      await pane.getByRole('button',{name:'مشتری حضوری'}).click();
      assert.match(await pane.innerText(),/مشتری حضوری ثبت‌شده انتخاب شد/);
      await pane.getByRole('textbox',{name:'شرح ردیف 1'}).fill('خدمت حضوری');
      await pane.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('5000');
      await pane.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
      await savedPreview(page,'invoice');
      const commands=await page.evaluate(()=>window.__invoiceQa.commands);
      assert.deepEqual(commands.map(x=>x.type),['invoice.create']);
      assert.equal(commands[0].partyId,'WALKIN-1');
      assert.equal(commands[0].lines[0].itemId,undefined);
      assert.deepEqual(uncaught,[]);
    }finally{await context.close();}
  });

  await t.test('walk-in without registered party cannot save until explicit party.register',async()=>{
    const {context,page,uncaught}=await openTestPage(browser,built);
    try{
      const pane=await newInvoice(page);
      await pane.getByRole('button',{name:'مشتری حضوری'}).click();
      await pane.getByRole('textbox',{name:'شرح ردیف 1'}).fill('خدمت بدون کد');
      await pane.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('7000');
      await pane.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
      assert.deepEqual(await page.evaluate(()=>window.__invoiceQa.commands),[]);
      await pane.getByRole('textbox',{name:'شناسه مشتری جدید'}).fill('WALK-NEW');
      page.once('dialog',dialog=>dialog.accept());
      await pane.getByRole('button',{name:'تأیید و ثبت مشتری در دفتر'}).click();
      await page.waitForFunction(()=>window.__invoiceQa.commands.length===1);
      await pane.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
      await savedPreview(page,'invoice');
      const commands=await page.evaluate(()=>window.__invoiceQa.commands);
      assert.deepEqual(commands.map(x=>x.type),['party.register','invoice.create']);
      assert.equal(commands[0].name,'مشتری حضوری');
      assert.equal(commands[1].partyId,'WALK-NEW');
      assert.equal(commands[1].lines[0].itemId,undefined);
      assert.deepEqual(uncaught,[]);
    }finally{await context.close();}
  });

  await t.test('explicit proforma and uncoded unit; no invoice or journal posting',async()=>{
    const {context,page,uncaught}=await openTestPage(browser,built);
    try{
      const pane=await newInvoice(page);
      await pane.getByRole('radio',{name:/پیش‌فاکتور/}).check();
      await pane.getByRole('combobox',{name:'مشتری فاکتور'}).selectOption('EXISTING-1');
      await pane.getByRole('textbox',{name:'شرح ردیف 1'}).fill('خدمت کاملاً سفارشی');
      assert.match(await pane.locator('[data-beginner-row="0"]').innerText(),/واحد:\s*عدد/);
      await pane.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('6000');
      await pane.getByRole('button',{name:'ذخیره پیش‌فاکتور'}).click();
      await savedPreview(page,'proforma');
      const commands=await page.evaluate(()=>window.__invoiceQa.commands);
      assert.deepEqual(commands.map(x=>x.type),['proforma.create']);
      assert.equal(commands[0].partyId,'EXISTING-1');
      assert.equal(commands[0].lines[0].itemId,undefined);
      assert.deepEqual(uncaught,[]);
    }finally{await context.close();}
  });

  await t.test('beginner, guided and professional share unsaved invoice state',async()=>{
    const {context,page,uncaught}=await openTestPage(browser,built);
    try{
      const pane=await newInvoice(page);
      await pane.getByRole('combobox',{name:'مشتری فاکتور'}).selectOption('EXISTING-1');
      await pane.getByRole('textbox',{name:'شرح ردیف 1'}).fill('خدمت چاپ آزمایشی');
      await pane.getByRole('textbox',{name:'تعداد ردیف 1'}).fill('3');
      await pane.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('1200');
      await pane.getByRole('textbox',{name:'یادداشت سند'}).fill('یادداشت حفظ شود');
      const modes=page.getByRole('group',{name:'نوع نمایش فرم فاکتور'});
      await modes.getByRole('button',{name:'حالت حرفه‌ای'}).click();
      await modes.getByRole('button',{name:'راهنمای مرحله‌ای'}).click();
      await modes.getByRole('button',{name:'ساده و سریع'}).click();
      const again=page.locator('.sac-invoice-beginner-pane');
      await again.waitFor();
      assert.equal(await again.getByRole('combobox',{name:'مشتری فاکتور'}).inputValue(),'EXISTING-1');
      assert.equal(await again.getByRole('textbox',{name:'شرح ردیف 1'}).inputValue(),'خدمت چاپ آزمایشی');
      assert.equal(await again.getByRole('textbox',{name:'تعداد ردیف 1'}).inputValue(),'3');
      assert.equal(await again.getByRole('textbox',{name:'قیمت ردیف 1'}).inputValue(),'1200');
      assert.equal(await again.getByRole('textbox',{name:'یادداشت سند'}).inputValue(),'یادداشت حفظ شود');
      assert.deepEqual(await page.evaluate(()=>window.__invoiceQa.commands),[]);
      await again.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
      await savedPreview(page,'invoice');
      const commands=await page.evaluate(()=>window.__invoiceQa.commands);
      assert.equal(commands.length,1);
      assert.equal(commands[0].lines.length,1);
      assert.equal(commands[0].lines[0].quantity,3);
      assert.equal(commands[0].lines[0].unitPrice,1200);
      assert.equal(commands[0].note,'یادداشت حفظ شود');
      assert.deepEqual(uncaught,[]);
    }finally{await context.close();}
  });

  await t.test('hide suggestions survives reload; deleted Madar note stays deleted',async()=>{
    const {context,page,uncaught}=await openTestPage(browser,built);
    try{
      const pane=await newInvoice(page);
      await pane.getByRole('textbox',{name:'شرح ردیف 1'}).fill('چاپ پوستر');
      await pane.getByRole('group',{name:'پیشنهاد کاتالوگ ردیف 1'}).waitFor();
      await pane.getByRole('button',{name:'دیگر پیشنهاد کد کالا نشان داده نشود'}).click();
      assert.equal(await pane.getByRole('group',{name:'پیشنهاد کاتالوگ ردیف 1'}).count(),0);
      assert.equal(await page.evaluate(()=>localStorage.getItem('taraz-invoice-item-suggestions-v1')),
        'hidden');
      // Browser-controlled reload retains UI prefs; fixture host remains synthetic.
      await page.reload();
      await page.addStyleTag({content:built.css});
      await page.addScriptTag({content:built.js,type:'module'});
      await page.locator('.sac-root').waitFor();
      await page.locator('[data-accounting-tab="madar"]:visible').first().click();
      const dash=page.locator('.taraz-madar-dashboard').first();
      await dash.getByRole('checkbox').check();
      await dash.getByRole('button',{name:'دریافت / بازخوانی ارجاع‌های مدار'}).click();
      await dash.getByRole('button',{name:'آماده‌سازی متن پیش‌نویس'}).click();
      await pane.waitFor();
      assert.equal(await pane.getByRole('button',{name:'دیگر پیشنهاد کد کالا نشان داده نشود'}).count(),0);
      const note=pane.getByRole('textbox',{name:'یادداشت سند'});
      const initial=await note.inputValue();
      assert.match(initial,/پیشنهاد محلی مدار/);
      await note.fill('اصلاح‌شده با نظر اپراتور');
      await pane.getByRole('textbox',{name:'شرح ردیف 1'}).fill('شرح بازنویسی‌شده');
      assert.equal(await note.inputValue(),'اصلاح‌شده با نظر اپراتور');
      await note.fill('');
      await pane.getByRole('textbox',{name:'تعداد ردیف 1'}).fill('2');
      assert.equal(await note.inputValue(),'');
      await pane.getByRole('combobox',{name:'مشتری فاکتور'}).selectOption('EXISTING-1');
      await pane.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('8000');
      await pane.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
      await savedPreview(page,'invoice');
      const commands=await page.evaluate(()=>window.__invoiceQa.commands);
      assert.equal(commands.length,1);
      assert.equal(commands[0].type,'invoice.create');
      assert.equal(commands[0].note,undefined,'deleted Madar suggestion not re-injected');
      assert.equal(commands[0].lines[0].description,'شرح بازنویسی‌شده');
      assert.deepEqual(uncaught,[]);
    }finally{await context.close();}
  });
});
