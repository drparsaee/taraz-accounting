'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const esbuild=require('esbuild');
const root=path.resolve(__dirname,'..');
const filename=path.join(root,'src/taraz_order_workspace.jsx');

function load(){
  const built=esbuild.buildSync({
    entryPoints:[filename],bundle:true,platform:'node',format:'cjs',
    write:false,external:['react','react/jsx-runtime','lucide-react'],
    loader:{'.css':'empty'},logLevel:'silent',
  });
  const mod={exports:{}};
  const sourceRequire=require('node:module').createRequire(filename);
  new Function('require','module','exports',built.outputFiles[0].text)(
    sourceRequire,mod,mod.exports);
  return mod.exports;
}
function fixture(){
  return {kind:'sale',customerId:'',customerName:'مشتری حضوری',
    title:'پاسپورت تبلیغاتی',description:'',unit:'عدد',quantity:'۱۰۰',
    productionQuantity:'۱۲۰',unitPrice:'',costStages:[],notes:''};
}
const ui=fs.readFileSync(filename,'utf8');
const {prepareTarazOrderDraft,orderCompleteness}=load();
const intake=require('../src/taraz_order_intake.js');

test('compiled component exports a working source-level form, not only a concept',()=>{
  assert.equal(typeof load().default,'function');
  assert.match(ui,/tarazOrderList/);
  assert.match(ui,/tarazOrderCommand/);
  assert.match(ui,/action:'transition'/);
  assert.match(ui,/manualConfirmation:true/);
  assert.match(ui,/aria-label="سطح فرم سفارش"/);
  assert.match(ui,/mode==='advanced'/);
  assert.doesNotMatch(ui,/standaloneAccountingCommand|invoice\.issue/);
  assert.match(ui,/financeAction\('payment\.record'/);
  assert.match(ui,/financialEventCreated!==false/);
});

test('beginner 100 sold / 120 planned production with unknown price never invents amounts',()=>{
  const value=prepareTarazOrderDraft(fixture(),'RIAL');
  assert.deepEqual(value.data&&{
    quantity:value.data.quantity,planned:value.data.productionQuantity,
    currency:value.data.currency,unitPrice:value.data.unitPrice,
  },{quantity:100,planned:120,currency:'RIAL',unitPrice:null});
  assert.deepEqual(orderCompleteness(fixture()),[]);
});

test('professional stage costs retain unknown suppliers/amounts as empty or null',()=>{
  const form=fixture();
  form.costStages=[{kind:'print',supplier:'چاپخانه',description:'',
    estimatedCost:''},{kind:'bindery',supplier:'',description:'صحافی',
    estimatedCost:'۳۵۰۰۰۰'}];
  const parsed=prepareTarazOrderDraft(form,'TOMAN');
  assert.deepEqual(parsed.data.costStages.map(x=>x.estimatedCost),[null,350000]);
});

test('missing customer, quantity, bad quote and false sold/produced ratio rejected',()=>{
  const form=fixture();form.customerName='';
  assert.match(prepareTarazOrderDraft(form).error,/مشتری|تأمین‌کننده/);
  form.customerName='مشتری';form.quantity='bad';
  assert.match(prepareTarazOrderDraft(form).error,/عدد/);
  form.quantity='100';form.productionQuantity='99';
  assert.match(prepareTarazOrderDraft(form).error,/تولید/);
  form.productionQuantity='120';form.unitPrice='-1';
  assert.match(prepareTarazOrderDraft(form).error,/قیمت/);
});

test('the UI does not claim AI auto pricing or posting, and requires manual approval',()=>{
  assert.match(ui,/AI و قیمت‌گذاری خودکار تا زمان اتصال و تأیید واقعی فعال نیستند/);
  assert.match(ui,/هیچ سند مالی ایجاد نشده است/);
  assert.match(ui,/globalThis\.confirm/);
  assert.match(ui,/result|بازخوانی|ترتیب/);
});

test('conservative local free-text intake proposes 100 sale / 120 production without invented price',()=>{
  const proposal=intake.extractLocalOrderHints(
    'مشتری: شرکت نمونه\nشرح سفارش: پاسپورت تبلیغاتی\nتعداد فروش: ۱۰۰ عدد\nتولید: ۱۲۰\nچاپ و صحافی');
  assert.equal(proposal.fields.customerName,'شرکت نمونه');
  assert.equal(proposal.fields.title,'پاسپورت تبلیغاتی');
  assert.equal(proposal.fields.quantity,'100');
  assert.equal(proposal.fields.productionQuantity,'120');
  assert.deepEqual(proposal.suggestedStages,['print','bindery']);
  assert.equal(proposal.externalModelCalled,false);
  assert.equal(proposal.financialEventCreated,false);
  assert.ok(!JSON.stringify(proposal).includes('unitPrice'));
});

test('unstructured text never invents customer, quantity or billable amount',()=>{
  const proposal=intake.extractLocalOrderHints('سلام برای چاپ کار جدید تماس می‌گیرم.');
  assert.equal(proposal.fields.customerName,'');
  assert.equal(proposal.fields.quantity,'');
  assert.ok(proposal.missing.includes('تعداد سفارش'));
  assert.equal(proposal.financialEventCreated,false);
});
