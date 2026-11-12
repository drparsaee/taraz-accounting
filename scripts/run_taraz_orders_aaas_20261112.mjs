/** Isolated, repeatable Phase4/5/6 source-level acceptance.
 *
 * Real disposable SQLite, compiled Edge UI, optional actual Windows WebView2
 * source host. Never upgrades an installed EXE, posts a journal or connects
 * to the real Madar host without explicit operator credentials.
 */
import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=process.env.TARAZ_PYTHON||(process.platform==='win32'?'py':'python3');
const args=(process.platform==='win32'&&python==='py'?['-3.12']:[]);
const native=process.argv.includes('--native-source');
if(native&&process.platform!=='win32'){
  console.error('Real Windows WebView2 source-hosted QA requires Windows.');
  process.exit(2);
}
const nodeTests=[
  'tests/taraz_order_workspace.test.cjs',
  'tests/taraz_order_browser.test.cjs',
  'tests/taraz_phase4_real_sqlite_browser_20261112.test.cjs',
  'tests/taraz_v106_madar_project_contract_20261112.test.cjs',
];
const pythonTests=[
  'tests.test_taraz_order_store_20261111',
  'tests.test_taraz_order_finance_20261112',
  'tests.test_taraz_order_accounting_draft_20261112',
  'tests.test_taraz_aaas_agent_20261112',
  'tests.test_taraz_aaas_natural_request_20261112',
  'tests.test_taraz_madar_order_link_20261112',
  'tests.test_taraz_madar_order_api_gate_20261112',
  'tests.test_taraz_madar_order_sync_20261112',
  'tests.test_taraz_private_cdp_gate_20261112',
  'tests.test_taraz_frozen_aaas_inventory_20261112',
  'tests.test_taraz_prime_independent_qa_20261112',
];
for(const filename of nodeTests){
  if(!existsSync(path.join(root,filename))){
    console.error('Expected test absent: '+filename);
    process.exit(2);
  }
}
const steps=[
  ['Compile current React UI',process.execPath,
    [path.join(root,'node_modules','vite','bin','vite.js'),'build']],
  ['Real backend and SQLite acceptance',python,
    [...args,'-B','-m','unittest',...pythonTests,'-q']],
  ['React/Edge and source/contract acceptance',process.execPath,
    ['--test','--test-concurrency=1',...nodeTests]],
];
if(native)steps.push(['Private real WebView2 source-hosted order+agent journey',
  python,[...args,'-B','scripts/qa_taraz_order_native_20261112.py']]);
for(const [name,cmd,commandArgs] of steps){
  console.log('\n### '+name);
  const result=spawnSync(cmd,commandArgs,{cwd:root,windowsHide:true,
    env:{...process.env,PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1'},
    stdio:'inherit',timeout:240000});
  if(result.error||result.status!==0){
    console.error('Orders/AaaS regression FAILED at '+name+
      '; exit='+result.status+'; '+(result.error?.message||''));
    process.exit(result.status||1);
  }
}
console.log('\nPHASE4/5/6 SOURCE, SQLITE, EDGE'+
  (native?', SOURCE-HOSTED NATIVE WEBVIEW2':'')+
  ' QA PASSED; frozen EXE, live Madar synchronization, independently reviewed integration and physical printing NOT ACCEPTED.');
