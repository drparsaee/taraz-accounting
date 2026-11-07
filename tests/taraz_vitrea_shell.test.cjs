const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const src=path.join(__dirname,'..','src');
const nav=fs.readFileSync(path.join(src,'accounting_navigation_shell.jsx'),'utf8');
const app=fs.readFileSync(path.join(src,'standalone_accounting_workspace.jsx'),'utf8');
const css=fs.readFileSync(path.join(src,'taraz_vitrea_shell.css'),'utf8');

test('Taraz has a compact Madar-style top capsule and icon dock',()=>{
  for(const hook of ['taraz-vt-topline','taraz-vt-primary','taraz-vt-dock',
    'taraz-vt-drawer','taraz-vt-brand']){
    assert.ok(nav.includes(hook),hook);
    assert.ok(css.includes(hook),hook);
  }
  assert.match(app,/taraz-vt-app/);
});

test('All authorized accounting sections remain in the drawer',()=>{
  assert.match(nav,/accountingVisibleSections/);
  assert.match(nav,/groups\.map\(group/);
  assert.match(nav,/group\.items\.filter\(key=>labels\.has\(key\)\)/);
  assert.match(nav,/data-accounting-tab=\{key\}/);
  assert.match(nav,/aria-current=\{tab===key\?'page'/);
});

test('Search, quick actions and theme control have functional callbacks',()=>{
  for(const hook of ['data-accounting-action="invoice"',
    'data-accounting-action="payment"','data-accounting-action="reports"',
    'data-accounting-action="theme"','data-accounting-action="search"']){
    assert.ok(nav.includes(hook),hook);
  }
  assert.match(nav,/saveTarazSettings\(/);
  assert.match(nav,/applyTarazSettings\(/);
  assert.match(nav,/onClick=\{toggleTheme\}/);
});

test('Graphite and frosted tokens cover light, dark and mobile layouts',()=>{
  for(const hook of ['--vs-glass','--vs-ink','--vs-edge','--sac-paper',
    ':root[data-theme="dark"]','.taraz-vt-drawer','@media(max-width:880px)']){
    assert.ok(css.includes(hook),hook);
  }
  assert.match(css,/prefers-reduced-motion/);
});

test('Navigation does not attempt direct task state or financial posting',()=>{
  assert.doesNotMatch(nav,/getState|journal\.manual|standaloneAccountingCommand|queue_saved_task/);
});
