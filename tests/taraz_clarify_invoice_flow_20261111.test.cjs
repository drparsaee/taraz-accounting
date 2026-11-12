'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Module=require('node:module');
const esbuild=require('esbuild');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');

const root=path.resolve(__dirname,'..');
const wizard=path.join(root,'src','accounting_invoice_wizard.jsx');
const workspace=path.join(root,'src','standalone_accounting_workspace.jsx');

function readWizard(){
  const code=esbuild.buildSync({entryPoints:[wizard],bundle:true,platform:'node',
    format:'cjs',write:false,loader:{'.css':'empty'},external:['react'],
    target:'es2022'}).outputFiles[0].text;
  const loaded=new Module(wizard,module);
  loaded.filename=wizard;
  loaded.paths=Module._nodeModulePaths(path.dirname(wizard));
  loaded._compile(code,wizard);
  return loaded.exports;
}
const ui=readWizard();

test('Clarify invoice and workspace JSX parse with real esbuild JSX transformer',()=>{
  const transformed=esbuild.transformSync(fs.readFileSync(workspace,'utf8'),{
    loader:'jsx',format:'esm',target:'es2022'});
  assert.match(transformed.code,/openSavedDocumentPreview/);
  assert.match(transformed.code,/party\.register/);
  assert.match(transformed.code,/buildStandaloneProformaCommand/);
  assert.match(transformed.code,/invoiceRowsForSubmission/);
});

test('catalog code is only suggested for unique active real catalog match',()=>{
  const items={
    'I-1':{id:'I-1',sku:'BOX-101',name:'جعبه مقوایی',unit:'عدد',active:true},
    'I-2':{id:'I-2',sku:'PRINT-202',name:'چاپ پوستر',unit:'متر مربع',active:true},
    'I-3':{id:'I-3',sku:'OLD-3',name:'جعبه قدیمی',unit:'عدد',active:false},
  };
  assert.equal(ui.suggestedInvoiceCatalogItem('جعبه مقوایی',items).id,'I-1');
  assert.equal(ui.suggestedInvoiceCatalogItem('PRINT-202',items).unit,'متر مربع');
  assert.equal(ui.suggestedInvoiceCatalogItem('جعبه قدیمی',items),null);
  assert.equal(ui.suggestedInvoiceCatalogItem('چاپ',items),null);
  assert.equal(ui.suggestedInvoiceCatalogItem('جعبه',{...items,
    'I-4':{id:'I-4',sku:'B4',name:'جعبه پلاستیکی',unit:'عدد',active:true}}),null);
  // The returned suggestion is a candidate; user must choose whether to link it.
});

test('auto-created trailing blank row is omitted, partially edited row is retained',()=>{
  const full={description:'طراحی',quantity:'2',unitPrice:'3000',accountId:'',itemId:''};
  const blank={description:'',quantity:'1',unitPrice:'',accountId:'',itemId:''};
  assert.deepEqual(ui.invoiceRowsForSubmission([full,blank,blank]),[full]);
  assert.equal(ui.invoiceRowsForSubmission([full,{...blank,quantity:'2'}]).length,2);
  assert.equal(ui.invoiceRowsForSubmission([blank]).length,1);
});

test('edited Madar note is never regenerated and extra explanation round-trips',()=>{
  const edited='یادداشت با متن بازنویسی‌شده توسط کاربر';
  const combined=ui.composeInvoiceExplanation(edited,'توضیح مستقل برای چاپ');
  assert.deepEqual(ui.splitInvoiceExplanation(combined),{
    note:edited,extraExplanation:'توضیح مستقل برای چاپ'});
  assert.equal(ui.composeInvoiceExplanation('',''),'');
  assert.equal(ui.composeInvoiceExplanation('','فقط توضیح'),
    'توضیح تکمیلی تراز: فقط توضیح');
  assert.deepEqual(ui.splitInvoiceExplanation('توضیح تکمیلی تراز: فقط توضیح'),{
    note:'',extraExplanation:'فقط توضیح'});
  assert.equal(ui.composeInvoiceExplanation('','').includes('مدار'),false);
});

test('walk-in resolves only uniquely registered customer; no invented party ID',()=>{
  const walk={id:'WALK-1',name:'مشتری حضوری',kind:'customer'};
  assert.equal(ui.existingWalkInCustomer([]),null);
  assert.deepEqual(ui.existingWalkInCustomer([walk]),walk);
  assert.equal(ui.existingWalkInCustomer([walk,{id:'WALK-2',name:'مشتری متفرقه'}]),null);
});

test('one-page beginner renders real unit, optional explanation and safe document selection',()=>{
  const html=renderToStaticMarkup(React.createElement(ui.BeginnerInvoiceEditor,{
    document:{partyId:'CUSTOMER-1',documentId:'PF-1405-1',documentDate:'2026-11-11',
      discount:'0',note:''},
    customers:[{id:'CUSTOMER-1',name:'مشتری واقعی',kind:'customer'}],
    accounts:{'4000':{id:'4000',name:'درآمد',kind:'revenue'}},
    items:{'ITEM-1':{id:'ITEM-1',sku:'SKU-1',name:'چاپ پوستر',unit:'متر مربع',active:true}},
    rows:[{description:'چاپ پوستر',quantity:'2',unitPrice:'3000',itemId:''}],
    tax:'0',documentType:'proforma',unitLabel:'ریال',extraExplanation:'',
    dateControl:React.createElement('input',{type:'date',defaultValue:'2026-11-11'}),
  }));
  for(const label of ['پیش‌فاکتور','فاکتور فروش','مشتری جدید','مشتری حضوری',
    'پیشنهاد کاتالوگ ردیف 1','متر مربع','رد پیشنهاد','توضیح تکمیلی',
    'ردیف سفارشی بدون کد کالا','ذخیره پیش‌فاکتور']){
    assert.ok(html.includes(label),`missing expected label: ${label}`);
  }
  assert.ok(html.includes('name="taraz-beginner-kind"'));
  assert.ok(!html.includes('invoice.issue'));
});

test('real Edge/Vite: inline customer, explicit catalog choice, draft and proforma PDF preview',
  {skip:!process.env.TARAZ_CLARIFY_BROWSER_URL},async t=>{
    const playwright=require(path.join(process.env.APPDATA||'', 'npm','node_modules','playwright'));
    const browser=await playwright.chromium.launch({channel:'msedge',headless:true,
      args:['--no-first-run','--disable-background-networking']});
    t.after(()=>browser.close());
    const context=await browser.newContext({viewport:{width:1440,height:960}});
    t.after(()=>context.close());
    await context.addInitScript(()=>{
      const view={currency:'RIAL',journals:[],
        accounts:{'4000':{id:'4000',name:'درآمد فروش',kind:'revenue'}},
        parties:{'CUST-OLD':{id:'CUST-OLD',name:'مشتری قدیمی',kind:'customer'}},
        items:{'ITEM-ONE':{id:'ITEM-ONE',sku:'SKU-ONE',name:'چاپ پوستر',
          kind:'service',unit:'متر مربع',active:true}},
        invoices:{},bills:{},receipts:{},payments:{},proformas:{},taxRules:{},
        contractorJobs:{},returns:{},cashAccounts:{},companyProfile:{legalName:'Synthetic Test'},
        cheques:{},warehouses:{},stock:{},stockMovements:{},closedThrough:null,
        sequence:{invoice:0,bill:0}};
      let revision=0;
      window.__clarifyQa={commands:[],view};
      const snapshot=()=>({revision,view,
        capabilities:{canManage:true,canDraft:true,canAdmin:true},
        currentUser:{username:'clarify-test',role:'admin',jobTitle:''}});
      window.madar={
        standaloneAccountingRead:async()=>snapshot(),
        standaloneAccountingTemplateList:async()=>({templates:[],defaultId:''}),
        standaloneAccountingCommand:async({command,expectedRevision})=>{
          if(expectedRevision!==revision)throw Error('synthetic revision mismatch');
          window.__clarifyQa.commands.push(structuredClone(command));
          if(command.type==='party.register'){
            if(view.parties[command.partyId])throw Error('duplicate party');
            view.parties[command.partyId]={id:command.partyId,name:command.name,
              kind:command.kind,creditLimit:command.creditLimit};
          }else if(['invoice.create','proforma.create'].includes(command.type)){
            if(!view.parties[command.partyId])throw Error('unknown party');
            const isQuote=command.type==='proforma.create';
            const key=isQuote?'proformaId':'invoiceId';
            const totalLines=command.lines.map(line=>({...line,
              total:line.quantity*line.unitPrice}));
            const subtotal=totalLines.reduce((sum,line)=>sum+line.total,0);
            const id=command[key];
            view[isQuote?'proformas':'invoices'][id]={id,partyId:command.partyId,
              documentDate:command.documentDate,lines:totalLines,
              subtotal,discount:command.discount,tax:command.tax,
              total:subtotal-command.discount+command.tax,note:command.note||'',
              status:'draft',number:null,allocated:0};
          }else throw Error('unexpected financial command: '+command.type);
          revision++;
          return snapshot();
        }
      };
    });
    const page=await context.newPage();
    page.setDefaultTimeout(15000);
    const uncaught=[];
    page.on('pageerror',error=>uncaught.push(error.message));
    await page.goto(process.env.TARAZ_CLARIFY_BROWSER_URL+'/accounting.html');
    await page.locator('.sac-root').waitFor();
    await page.locator('[data-accounting-action="invoice"]').click();
    const beginner=page.locator('.sac-invoice-beginner-pane');
    await beginner.waitFor();
    await beginner.getByRole('button',{name:'مشتری جدید'}).click();
    await beginner.getByRole('textbox',{name:'شناسه مشتری جدید'}).fill('CUST-NEW');
    await beginner.getByRole('textbox',{name:'نام مشتری جدید'}).fill('مشتری واقعی جدید');
    page.once('dialog',dialog=>dialog.accept());
    await beginner.getByRole('button',{name:'تأیید و ثبت مشتری در دفتر'}).click();
    await page.waitForFunction(()=>window.__clarifyQa.commands.length===1);
    assert.equal((await page.evaluate(()=>window.__clarifyQa.commands))[0].type,'party.register');
    await beginner.getByRole('textbox',{name:'شرح ردیف 1'}).fill('چاپ پوستر');
    await beginner.getByRole('group',{name:'پیشنهاد کاتالوگ ردیف 1'}).waitFor();
    await beginner.getByRole('button',{name:'تأیید کد پیشنهادی'}).click();
    assert.match(await beginner.innerText(),/متر مربع/);
    await beginner.getByRole('textbox',{name:'تعداد ردیف 1'}).fill('2');
    await beginner.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('9000');
    await beginner.getByRole('textbox',{name:'قیمت ردیف 1'}).press('Enter');
    await beginner.locator('[data-beginner-row="1"]').waitFor();
    await beginner.getByRole('textbox',{name:'توضیح تکمیلی'}).fill('توضیح تست برای چاپ');
    await beginner.getByRole('button',{name:'ذخیره پیش‌نویس فاکتور'}).click();
    await page.waitForFunction(()=>window.__clarifyQa.commands.some(c=>c.type==='invoice.create'));
    await page.locator('.sac-saved-print-preview iframe').waitFor();
    const commands=await page.evaluate(()=>window.__clarifyQa.commands);
    assert.equal(commands.find(c=>c.type==='invoice.create').partyId,'CUST-NEW');
    assert.equal(commands.find(c=>c.type==='invoice.create').lines.length,1);
    assert.equal(commands.find(c=>c.type==='invoice.create').lines[0].itemId,'ITEM-ONE');
    assert.match(commands.find(c=>c.type==='invoice.create').note,/توضیح تست برای چاپ/);
    assert.equal(commands.filter(c=>/\.issue$|\.approve$/.test(c.type)).length,0);

    await page.locator('[data-accounting-action="invoice"]').click();
    await beginner.getByRole('radio',{name:/پیش‌فاکتور/}).check();
    await beginner.getByRole('combobox',{name:'مشتری فاکتور'}).selectOption('CUST-OLD');
    await beginner.getByRole('textbox',{name:'شرح ردیف 1'}).fill('خدمات سفارشی');
    await beginner.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('3000');
    await beginner.getByRole('button',{name:'ذخیره پیش‌فاکتور'}).click();
    await page.waitForFunction(()=>window.__clarifyQa.commands.some(c=>c.type==='proforma.create'));
    await page.locator('.sac-saved-print-preview iframe').waitFor();
    assert.equal((await page.evaluate(()=>window.__clarifyQa.commands))
      .filter(c=>/\.create$/.test(c.type)&&c.type!=='party.register').length,2);
    assert.deepEqual(uncaught,[]);
  });
