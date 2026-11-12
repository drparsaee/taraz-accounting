/** Explicit, isolated P1 regression runner. NOT a native Windows release gate.
 * Builds only the local Vite dist, then uses ephemeral QA SQLite and Edge.
 * It does not launch/install Taraz.exe, touch the user's ledger or approve issues.
 */
import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=process.env.TARAZ_PYTHON ||
  (process.platform==='win32'?'py':'python3');
const pythonArgs=(process.platform==='win32'&&python==='py'?['-3.12']:[]);
const pythonTests=[
  'tests.test_taraz_print_page_bounds_20261112',
  'tests.test_taraz_invoice_template_bridge_20261110',
  'tests.test_taraz_invoice_native_bridge_vertical_20261112',
  'tests.test_taraz_clarify_product_contract_20261111',
  'tests.test_taraz_clarify_order_20261111'
];
const nodeTests=[
  'tests/taraz_print_contract_parity_20261112.test.cjs',
  'tests/taraz_clarify_print_20261111.test.cjs',
  'tests/taraz_invoice_print_designer_browser_20261110.test.cjs',
  'tests/taraz_clarify_order_20261111.test.cjs',
  'tests/taraz_p1_ui_real_sqlite_20261112.test.cjs'
];
const nativeCurrent=process.argv.includes('--native-current-source');
const nativeFrozenParity=process.argv.includes('--native-source');
if(nativeCurrent&&nativeFrozenParity){
  console.error('Choose only one explicit native evidence mode.');
  process.exit(2);
}
const nativeRequested=nativeCurrent||nativeFrozenParity;
if(nativeRequested&&process.platform!=='win32'){
  console.error('Native WebView2 acceptance requires Windows.');
  process.exit(2);
}
const vite=path.join(root,'node_modules','vite','bin','vite.js');
const playwright=path.join(root,'node_modules','playwright','package.json');
if(!existsSync(vite)||!existsSync(playwright)){
  console.error('Missing locked local dev dependencies. Run npm ci first.');
  process.exit(2);
}
for(const filename of nodeTests){if(!existsSync(path.join(root,filename))){
  console.error('Missing expected P1 test '+filename);process.exit(2);
}}
const steps=[
  ['Compile local UI, no EXE/installer',process.execPath,[vite,'build']],
  ['Python backend+SQLite isolated acceptance',python,[...pythonArgs,'-B','-m','unittest',
    ...pythonTests,'-q']],
  ['Browser+PDF+order+print parity acceptance',process.execPath,
    ['--test','--test-concurrency=1',...nodeTests]],
];
if(nativeRequested)steps.push([
  'Private native Windows WebView2 + real Python/SQLite + PDF + template ('+
    (nativeCurrent?'current-source':'frozen-parity')+')',
  python,[...pythonArgs,'-B','scripts/qa_taraz_native_bridge_vertical_20261112.py',
    ...(nativeCurrent?['--current-source']:[])]
]);
for(const [label,command,args] of steps){
  console.log(`\n### ${label}`);
  const result=spawnSync(command,args,{cwd:root,env:{...process.env,
    PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1'},
    stdio:'inherit',windowsHide:true,timeout:180000});
  if(result.error||result.status!==0){
    console.error(`P1 gate FAILED: ${label}; exit=${result.status}; `+
      (result.error?.message||''));
    process.exit(result.status||1);
  }
}
console.log('\nP1 SOURCE/EDGE/SQLITE'+(nativeRequested?
  '/SOURCE-HOSTED WEBVIEW2 ('+(nativeCurrent?'current-source':'frozen-parity')+')':'')+
  ' REGRESSIONS PASS; frozen native EXE clickthrough and physical printer NOT ACCEPTED.');
