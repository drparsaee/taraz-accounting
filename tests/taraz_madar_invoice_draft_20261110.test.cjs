'use strict';

const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Module=require('node:module');
const esbuild=require('esbuild');

const root=path.resolve(__dirname,'..');
const source=path.join(root,'src','taraz_madar_invoice_draft.js');
const compiled=esbuild.buildSync({entryPoints:[source],bundle:true,
  platform:'node',format:'cjs',write:false,logLevel:'silent'}).outputFiles[0].text;
const dynamic=new Module(source,module);
dynamic.filename=source;
dynamic.paths=Module._nodeModulePaths(path.dirname(source));
dynamic._compile(compiled,source);
const {madarProposalInvoiceSuggestion}=dynamic.exports;

const proposal=()=>({schema:1,source:'madar',id:'a'.repeat(32),
  taskId:'synthetic-task',projectId:'synthetic-project',
  title:'بررسی بسته‌بندی آزمایشی',amountRial:125000,
  partyId:'unverified-customer',postingAuthorized:true});

test('Madar proposal suggests only in-memory description and warning, never amount/party',()=>{
  const result=madarProposalInvoiceSuggestion(proposal());
  assert.deepEqual(result.row,{description:'بررسی بسته‌بندی آزمایشی',
    quantity:'1',unitPrice:'',accountId:'',itemId:''});
  assert.match(result.note,/منبع مالی تأییدنشده/);
  assert.match(result.note,/a{32}/);
  assert.equal(result.sourceId,'a'.repeat(32));
  for(const secret of ['125000','unverified-customer','postingAuthorized'])
    assert.doesNotMatch(JSON.stringify(result),new RegExp(secret));
  assert.ok(Object.isFrozen(result));
  assert.ok(Object.isFrozen(result.row));
});

test('untrusted amount, fake official status and currency cannot prefill finance fields',()=>{
  for(const amount of [0,9e15,Infinity,'999999999999999',null,'مبلغ']){
    const suggestion=madarProposalInvoiceSuggestion({...proposal(),amountRial:amount,
      financialEventCreated:true,officialTarazReceipt:'fake',currency:'TOMAN'});
    assert.equal(suggestion.row.unitPrice,'');
    assert.equal(suggestion.row.accountId,'');
    assert.equal(suggestion.row.itemId,'');
  }
});

test('invalid, cross-source, unbounded, malformed proposal is refused',()=>{
  for(const changed of [
    {source:'stranger'},{schema:2},{id:'../'},{id:'A'.repeat(32)},
    {taskId:''},{projectId:''},{title:''},{title:'x'.repeat(301)},
    {title:'Invoice\u0000payload'},
    {title:'Invoice\u202eXX'},
  ]){
    assert.throws(()=>madarProposalInvoiceSuggestion({...proposal(),...changed}),
      /ارجاع مدار/);
  }
  assert.throws(()=>madarProposalInvoiceSuggestion(null),/ارجاع مدار/);
});

test('real Taraz workspace and settings bundle, but do not auto-post on integration',()=>{
  const workspace=fs.readFileSync(path.join(root,'src','standalone_accounting_workspace.jsx'),'utf8');
  const settings=fs.readFileSync(path.join(root,'src','taraz_settings.jsx'),'utf8');
  assert.match(workspace,/const startMadarInvoiceSuggestion=proposal=>/);
  assert.match(workspace,/if\(!openQuickInvoice\(\)\)return false/);
  assert.match(workspace,/setRows\(\[suggestion\.row\]\)/);
  assert.match(workspace,/onDraftFromMadar=\{startMadarInvoiceSuggestion\}/);
  assert.match(settings,/onClick=\{\(\)=>onDraftFromMadar\(item\)\}/);
  const bundle=esbuild.buildSync({
    entryPoints:[path.join(root,'src','standalone_accounting_workspace.jsx')],
    bundle:true,platform:'browser',format:'esm',write:false,
    charset:'utf8',outdir:'mtr-in-memory-taraz',logLevel:'silent',
    external:['react','react-dom','react/jsx-runtime','lucide-react'],
    loader:{'.css':'empty','.jpg':'dataurl','.png':'dataurl','.svg':'dataurl'},
  }).outputFiles.find(file=>file.path.endsWith('.js'));
  assert.ok(bundle?.text?.length>20000);
  assert.match(bundle.text,/منبع مالی تأییدنشده/);
});
