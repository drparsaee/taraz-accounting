const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {pathToFileURL}=require('node:url');

const sourceRoot=path.join(__dirname,'../src');
const data=import(pathToFileURL(path.join(sourceRoot,'taraz_context_help_data.js')).href);
const main=fs.readFileSync(path.join(sourceRoot,'standalone_accounting_workspace.jsx'),'utf8');
const settings=fs.readFileSync(path.join(sourceRoot,'taraz_settings.jsx'),'utf8');
const component=fs.readFileSync(path.join(sourceRoot,'taraz_context_help.jsx'),'utf8');
const styles=fs.readFileSync(path.join(sourceRoot,'taraz_context_help.css'),'utf8');

function actualSections(){
  const match=main.match(/const SECTIONS=\[([\s\S]*?)\];/);
  assert.ok(match,'must read actual Taraz visible navigation source');
  return [...match[1].matchAll(/\['([^']+)','([^']+)'\]/g)]
    .map(([,key,label])=>[key,label]);
}
function actualSettingsPages(){
  const match=settings.match(/const PAGES=\[([\s\S]*?)\];/);
  assert.ok(match,'must read real settings page IDs');
  return [...match[1].matchAll(/\['([^']+)','([^']+)'/g)]
    .map(([,key,label])=>[key,label]);
}
const sections=actualSections();
const get=async()=>await data;
const config=(tab,more={})=>({
  tab,sections,role:'admin',...more
});

test('ALL real accounting sections have compact, specific help and no fake tabs',async()=>{
  const {TARAZ_ACCOUNTING_HELP_KEYS,resolveTarazContextHelp,visibleTarazHelpSections}=await get();
  const actual=sections.map(([key])=>key);
  assert.equal(new Set(actual).size,actual.length,'source nav keys must be unique');
  assert.deepEqual([...TARAZ_ACCOUNTING_HELP_KEYS].sort(),[...actual].sort());
  assert.deepEqual(visibleTarazHelpSections({sections,role:'admin'}),sections.map(
    ([id,label])=>({id,label})));
  for(const [tab,sourceLabel] of sections){
    const guide=resolveTarazContextHelp(config(tab));
    assert.ok(guide,'missing '+tab);
    assert.equal(guide.id,tab);
    assert.equal(guide.label,sourceLabel);
    assert.ok(Array.isArray(guide.steps)&&guide.steps.length>=1&&guide.steps.length<=3);
    for(const step of guide.steps){
      assert.equal(typeof step,'string');
      assert.ok(step.trim().length>=15&&step.length<=220,tab+': '+step);
    }
    assert.ok(guide.caution===undefined||
      (typeof guide.caution==='string'&&guide.caution.length<=210));
  }
});

test('settings help matches ALL actual subpages and limitations are explicit',async()=>{
  const {TARAZ_SETTINGS_HELP_PAGES,resolveTarazContextHelp}=await get();
  const pages=actualSettingsPages();
  assert.deepEqual([...TARAZ_SETTINGS_HELP_PAGES].sort(),
    pages.map(([id])=>id).sort());
  for(const [id,actualLabel] of pages){
    const guide=resolveTarazContextHelp(config('settings',{context:'settings.'+id}));
    assert.ok(guide,'missing settings '+id);
    assert.ok(guide.label.includes(actualLabel));
    assert.ok(guide.steps.length>=1&&guide.steps.length<=3);
  }
  assert.match(resolveTarazContextHelp(config('settings',{
    context:'settings.subscription'
  })).caution,/نیست/);
  assert.match(resolveTarazContextHelp(config('settings',{
    context:'settings.integration'
  })).caution,/سند مالی ایجاد نمی‌کند/);
});

test('never expose a help panel for a section missing from current visible nav',async()=>{
  const {resolveTarazContextHelp,visibleTarazHelpSections}=await get();
  for(const badTab of ['payee-account','unknown','',null,undefined,'__proto__']){
    assert.equal(resolveTarazContextHelp(config(badTab)),null);
  }
  assert.equal(resolveTarazContextHelp(config('invoice',{sections:[]})),null);
  assert.equal(resolveTarazContextHelp(config('migration',{role:'viewer'})),null);
  assert.equal(resolveTarazContextHelp(config('migration',{role:'editor'})),null);
  assert.deepEqual(visibleTarazHelpSections({sections,role:'viewer'})
    .some(item=>item.id==='migration'),false);
  assert.equal(resolveTarazContextHelp(config('invoice',{
    sectionAccess:{invoice:false}
  })),null);
  assert.equal(resolveTarazContextHelp(config('settings',{
    context:'settings.integration',sectionAccess:{settings:false}
  })),null);
  assert.equal(resolveTarazContextHelp(config('overview',{
    context:'settings.general'
  })),null);
  assert.equal(resolveTarazContextHelp(config('invoice',{role:'superuser'})),null);
});

test('actual source label is used instead of a made-up or cached title',async()=>{
  const {resolveTarazContextHelp}=await get();
  const changed=sections.map(([id,label])=>[id,id==='invoice'?'فروش سفارشی میزبان':label]);
  assert.equal(resolveTarazContextHelp(config('invoice',{
    sections:changed
  })).label,'فروش سفارشی میزبان');
  const hidden=changed.filter(([id])=>id!=='invoice');
  assert.equal(resolveTarazContextHelp(config('invoice',{sections:hidden})),null);
});

test('action guides require actual visible control + restricted host capability',async()=>{
  const {TARAZ_HELP_ACTIONS,resolveTarazContextHelp}=await get();
  assert.deepEqual([...TARAZ_HELP_ACTIONS].sort(),
    ['users','switchCompany','recovery','approval','backup','companySecurity','charts'].sort());
  for(const name of TARAZ_HELP_ACTIONS){
    const tab=name==='approval'?'invoice':name==='charts'?'overview':'settings';
    assert.equal(resolveTarazContextHelp(config(tab,{
      context:'action.'+name
    })),null,'action must start hidden: '+name);
  }
  const user=resolveTarazContextHelp(config('settings',{
    context:'action.users',capabilities:{usersVisible:true,canAdmin:true}
  }));
  assert.ok(user&&user.label.includes('کاربران'));
  assert.equal(resolveTarazContextHelp(config('settings',{
    role:'viewer',context:'action.users',capabilities:{usersVisible:true,canAdmin:true}
  })),null);
  assert.ok(resolveTarazContextHelp(config('settings',{
    context:'action.switchCompany',capabilities:{switchCompanyVisible:true}
  })));
  assert.ok(resolveTarazContextHelp(config('overview',{
    context:'action.recovery',capabilities:{recoveryVisible:true}
  })));
  assert.equal(resolveTarazContextHelp(config('migration',{
    context:'action.recovery',capabilities:{recoveryVisible:true}
  })),null);
  assert.ok(resolveTarazContextHelp(config('invoice',{
    context:'action.approval',capabilities:{canManage:true,approvalVisible:true}
  })));
  assert.equal(resolveTarazContextHelp(config('bill',{
    context:'action.approval',capabilities:{canManage:true,approvalVisible:true}
  })),null);
  assert.ok(resolveTarazContextHelp(config('settings',{
    context:'action.backup',capabilities:{backupVisible:true}
  })));
  assert.ok(resolveTarazContextHelp(config('company',{
    context:'action.companySecurity',capabilities:{
      canAdmin:true,companySecurityVisible:true
    }
  })));
  assert.equal(resolveTarazContextHelp(config('company',{
    role:'viewer',context:'action.companySecurity',
    capabilities:{canAdmin:true,companySecurityVisible:true}
  })),null);
  assert.ok(resolveTarazContextHelp(config('overview',{
    context:'action.charts',capabilities:{chartsVisible:true}
  })));
  assert.equal(resolveTarazContextHelp(config('settings',{
    context:'action.charts',capabilities:{chartsVisible:true}
  })),null);
});

test('no dangerous implication of automated finance or nonexistent online subscription',async()=>{
  const {resolveTarazContextHelp}=await get();
  const guide=(tab,context)=>resolveTarazContextHelp(config(tab,{context}));
  assert.match(guide('invoice').caution,/پیش‌نویس/);
  assert.match(guide('proforma').caution,/دفترکل نمی‌سازد/);
  assert.match(guide('cheques').caution,/وصول قطعی/);
  assert.match(guide('reports').caution,/ارائه نکند/);
  assert.match(guide('migration').caution,/انتقال کامل/);
  assert.match(guide('settings','settings.integration').caution,/خودکار/);
  assert.match(guide('settings','settings.account').caution,/راه‌اندازی نشده/);
  assert.match(guide('period').caution,/بستن دوره/);
});

test('JSX provides accessible RTL button and modal keyboard/focus semantics',()=>{
  assert.match(component,/export default function TarazContextHelp/);
  assert.match(component,/resolveTarazContextHelp\(/);
  assert.match(component,/aria-haspopup="dialog"/);
  assert.match(component,/aria-expanded=\{open\}/);
  assert.match(component,/role="dialog" aria-modal="true"/);
  assert.match(component,/aria-labelledby=\{titleId\}/);
  assert.match(component,/aria-describedby=\{descId\}/);
  assert.match(component,/dir="rtl"/);
  assert.match(component,/event\.key==='Escape'/);
  assert.match(component,/event\.key==='Tab'/);
  assert.match(component,/closeRef\.current\?\.focus\(\)/);
  assert.match(component,/opener\.current\.focus\(\)/);
  assert.match(component,/type="button"/);
  assert.match(component,/if\(!help\|\|disabled\)return null/);
  assert.doesNotMatch(component,/standaloneAccountingCommand|window\.fetch|fetch\(/);
  assert.match(styles,/:focus-visible/);
  assert.match(styles,/max-height/);
  assert.match(styles,/prefers-reduced-motion/);
});
