'use strict';
/**
 * Independent RC3 *actual PyInstaller EXE* -> isolated Edge acceptance.
 * This suite NEVER runs the EXE. It inspects its CArchive in read-only Python,
 * and feeds the EXE-EXTRACTED JS/CSS bytes (not disk Vite JS) to Edge.
 * 13 leaf cases are reused byte-for-byte from the previously successful,
 * SHA-pinned RC3 residual suite. No existing QA source is modified.
 */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const crypto=require('node:crypto');
const vm=require('node:vm');
const {spawnSync}=require('node:child_process');

const root=String.raw`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1`;
const pinnedStage=path.join(root,'source-stage-ca9761aa43d8');
const pinnedVite=path.join(root,'vite-qa-72ee216638e4');
const pinnedVersion='1.0.4';
const pinnedSourceSha='e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de';
const pinnedViteJsSha='3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9';
const pinnedViteCssSha='1b267d6655ad7b78c4ee02fa4eedde46bfa7c1c711e3883020f7ef0f9cc74cbf';
const pinnedExeSha='9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce';
const pinnedJsName='accounting-5ZRme707.js';
const pinnedCssName='accounting-Cn_dODL0.css';
const priorExeSha='8e2a8026b48e278df95693d9349f5a566df9b75c12497882b3bebca96679adc6';
const qaSourcePath=path.join(__dirname,'taraz_v104_residual_exception_leak_20261111.test.cjs');
const pinnedQaSourceSha='0b6612f345e856c958f7d31bb2098c057fc0d076bcf403dbdc366a0d0bf35f4f';
const secret='QA-V104-RESIDUAL-LOCAL-58317';
const sha=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const reject=why=>{throw Error('BLOCKED_RC3_EXE_ACCEPTANCE: '+why);};
const readFile=p=>{
  const s=fs.statSync(p,{throwIfNoEntry:false});
  if(!s?.isFile())reject('missing required file '+p);
  return fs.readFileSync(p);
};
const readJson=p=>JSON.parse(readFile(p).toString('utf8'));
const sameDir=(left,right)=>path.win32.normalize(left).toLowerCase()===
  path.win32.normalize(right).toLowerCase();
let playwright;
try{playwright=require('playwright');}
catch{playwright=require(path.join(process.env.APPDATA||'','npm','node_modules','playwright'));}

function extractActualExe(){
  const selected=process.env.TARAZ_V104_RC3_BUILD_DIR?.trim();
  if(!selected)reject('TARAZ_V104_RC3_BUILD_DIR required: explicit finished RC3 build-* path');
  if(!path.win32.isAbsolute(selected))reject('build selection must be an absolute Windows path');
  const build=fs.realpathSync.native(selected);
  if(!sameDir(path.dirname(build),fs.realpathSync.native(root))||
     !/^build-[a-z0-9-]+$/i.test(path.basename(build)))
    reject('build must be a direct build-* child of known v1.0.4 candidate root');
  // A separate observed candidate digest prohibits substituting the old v104
  // RC1/RC2 build or swapping in a future unreviewed binary under this path.
  const report=readJson(path.join(build,'build-report.json'));
  if(report.version!==pinnedVersion||report.releaseCandidateRevision!=='RC3'||
     report.status!=='PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED'||
     report.installed!==false||report.pointerChanged!==false||
     report.releaseApproved!==false||report.realLedgerModified!==false||
     report.sourceFreezeSha256!==pinnedSourceSha||report.sourceFileCount!==131||
     report.compiled?.peVersion!=='1.0.4.0'||
     report.compiled?.pyzVersion!==pinnedVersion||
     report.compiled?.nonQaRuntime!==true)
    reject('RC3 completed, noninstalled, nonQA source/build attestation missing or inconsistent');
  if(!sameDir(fs.realpathSync.native(report.sourceStagePath),
      fs.realpathSync.native(pinnedStage)))reject('build not from pinned RC3 source stage');
  if(sha(readFile(path.join(pinnedStage,'stage-report.json')))!==report.sourceStageReportSha256)
    reject('RC3 staged source report changed');
  if(!sameDir(fs.realpathSync.native(report.viteStage?.root),
      fs.realpathSync.native(pinnedVite)))reject('RC3 build not from pinned Vite stage');
  const viteReportPath=path.join(pinnedVite,'rc3-vite-qa-report.json');
  const vite=readJson(viteReportPath);
  if(sha(readFile(viteReportPath))!==report.viteStage?.reportSha256||
     vite.status!=='V104_RC3_STAGE_UI_ONLY_EDGE_QA_PENDING'||
     vite.sourceSha256!==pinnedSourceSha||vite.jsSha256!==pinnedViteJsSha||
     report.viteStage?.jsSha256!==pinnedViteJsSha||
     vite.cssSha256!==pinnedViteCssSha)
    reject('RC3 Vite attestation does not match pinned source/JS/CSS');
  const pkg=readJson(path.join(build,'source','package.json'));
  if(pkg.version!==pinnedVersion)reject('built package metadata is not v1.0.4');
  const html=readFile(path.join(build,'web','dist','accounting.html'));
  const htmlText=html.toString('utf8');
  const jsMatch=htmlText.match(/\bsrc=["']\.\/assets\/([^"']+\.js)["']/);
  const cssMatch=htmlText.match(/\bhref=["']\.\/assets\/([^"']+\.css)["']/);
  if(jsMatch?.[1]!==pinnedJsName||cssMatch?.[1]!==pinnedCssName||
     sha(html)!==vite.htmlSha256)
    reject('built HTML does not reference exact attested RC3 JavaScript/CSS');
  const exe=path.join(build,'binary','Taraz.exe');
  const exeSha=sha(readFile(exe));
  if(exeSha!==pinnedExeSha||exeSha===priorExeSha||report.exeSha256!==exeSha)
    reject('actual RC3 EXE SHA256 changed or old binary was substituted');

  // The CArchive and PYZ metadata are inspected in-memory. No file is written,
  // EXE executed, installer launched, nor Windows profile modified.
  const py=String.raw`import sys,json,hashlib,base64,ctypes,types
from PyInstaller.archive.readers import CArchiveReader
exe,jsname,cssname=sys.argv[1:]
a=CArchiveReader(exe)
js=a.extract('dist\\assets\\'+jsname)
css=a.extract('dist\\assets\\'+cssname)
html=a.extract('dist\\accounting.html')
if not all(isinstance(x,bytes) for x in (js,css,html)):raise RuntimeError('CArchive UI byte extraction failed')
pyz=a.open_embedded_archive('PYZ.pyz')
code=pyz.extract('taraz_release_version')
if not isinstance(code,types.CodeType):raise RuntimeError('release module PYZ is not compiled code')
scope={'__builtins__':{}}
exec(code,scope)
version=scope.get('APP_VERSION')
qa=scope.get('QA_ONLY')
channel=scope.get('BUILD_CHANNEL')
v=ctypes.windll.version
v.GetFileVersionInfoSizeW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)]
v.GetFileVersionInfoSizeW.restype=ctypes.c_ulong
n=v.GetFileVersionInfoSizeW(exe,ctypes.byref(ctypes.c_ulong()))
if not n:raise RuntimeError('PE file version resource missing')
buf=ctypes.create_string_buffer(n)
v.GetFileVersionInfoW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
v.GetFileVersionInfoW.restype=ctypes.c_int
if not v.GetFileVersionInfoW(exe,0,n,buf):raise RuntimeError('PE version read failed')
ptr,length=ctypes.c_void_p(),ctypes.c_uint()
v.VerQueryValueW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_uint)]
v.VerQueryValueW.restype=ctypes.c_int
if not v.VerQueryValueW(buf,'\\',ctypes.byref(ptr),ctypes.byref(length)):raise RuntimeError('PE fixed file version missing')
w=ctypes.cast(ptr,ctypes.POINTER(ctypes.c_uint32))
if w[0]!=0xFEEF04BD:raise RuntimeError('PE version signature invalid')
pe=f'{w[2]>>16}.{w[2]&65535}.{w[3]>>16}.{w[3]&65535}'
print(json.dumps({'pe':pe,'pyz':version,'qa':qa,'channel':channel,
  'jsSha':hashlib.sha256(js).hexdigest(),'cssSha':hashlib.sha256(css).hexdigest(),
  'htmlSha':hashlib.sha256(html).hexdigest(),
  'js':base64.b64encode(js).decode('ascii'),
  'css':base64.b64encode(css).decode('ascii')}))`;
  const result=spawnSync('py',['-3.12','-B','-c',py,exe,pinnedJsName,pinnedCssName],
    {encoding:'utf8',timeout:60000,maxBuffer:10*1024*1024});
  if(result.status!==0)reject('read-only PyInstaller inspection failed: '+
    (result.stderr||result.stdout||result.error?.message||'unknown').slice(0,600));
  const extracted=JSON.parse(result.stdout.trim());
  if(extracted.pe!=='1.0.4.0'||extracted.pyz!==pinnedVersion||
     extracted.qa!==false||extracted.channel!=='offline-production-candidate')
    reject('ACTUAL compiled PE/PYZ version or nonQA channel does not match v1.0.4');
  const js=Buffer.from(extracted.js,'base64');
  const css=Buffer.from(extracted.css,'base64');
  if(extracted.jsSha!==pinnedViteJsSha||sha(js)!==pinnedViteJsSha||
     extracted.cssSha!==pinnedViteCssSha||sha(css)!==pinnedViteCssSha||
     extracted.htmlSha!==vite.htmlSha256||
     sha(readFile(path.join(build,'web','dist','assets',pinnedJsName)))!==sha(js)||
     sha(readFile(path.join(build,'web','dist','assets',pinnedCssName)))!==sha(css)||
     sha(readFile(path.join(pinnedVite,'dist','assets',pinnedJsName)))!==sha(js)||
     sha(readFile(path.join(pinnedVite,'dist','assets',pinnedCssName)))!==sha(css))
    reject('EXE-extracted exact JS/CSS bytes differ from pinned Vite RC3 asset');
  return {build,exeSha,jsSha:sha(js),cssSha:sha(css),
    js:js.toString('utf8'),css:css.toString('utf8')};
}

// Reuse ONLY the known, SHA-pinned browser scenario body. The original frozen
// QA file remains untouched. We substitute solely its asset factory; the
// returned byte buffers originate in the REAL EXE CArchive inspection above.
// An in-memory VM evaluates the source without filesystem/network/process or
// require() access. This prevents silently reducing 13 scenarios by accident.
function registerFrozenRc3Scenarios(embedded){
  const original=readFile(qaSourcePath);
  if(sha(original)!==pinnedQaSourceSha)
    reject('frozen 13-case QA source changed: independent review required');
  const source=original.toString('utf8');
  const anchor='async function makePage(browser,asset,{mode=\'normal\'}={}){';
  const start=source.indexOf(anchor);
  if(start<0||source.indexOf(anchor,start+1)!==-1)
    reject('frozen browser scenario anchor not uniquely found');
  const remainder=source.slice(start);
  const originalFactory='const asset=validateViteStage();';
  const testSuiteAnchor="test('v104 exact detached Vite stage residual local/native error channels',async t=>{";
  if(remainder.split(originalFactory).length!==2||
     remainder.split(testSuiteAnchor).length!==2)
    reject('frozen suite asset injection or suite anchor changed');
  let tests=remainder.replace(originalFactory,'const asset=globalThis.__exeEmbeddedAsset;')
    .replace(testSuiteAnchor,"test('RC3 real EXE-extracted JavaScript: 13 isolated Edge leak/validation cases',async t=>{");
  const diagnosis=/t\.diagnostic\(\(rc3\?[\s\S]*?\);\s*const browser=/;
  if(!diagnosis.test(tests))reject('frozen suite diagnostics could not be pinned');
  tests=tests.replace(diagnosis,
    "t.diagnostic('VERIFIED_MODE=RC3_EXE_EXTRACTED_EDGE JS_SHA256='+asset.jsSha);\n  const browser=");
  const context={
    __exeEmbeddedAsset:embedded,rc3:true,rc2:false,repaired:true,
    secret,test,assert,playwright,Buffer,
  };
  vm.runInNewContext("'use strict';\n"+tests,context,{
    filename:'pinned-rc3-scenarios-from-real-exe.cjs',timeout:15000});
}

let embedded;
try{embedded=extractActualExe();}
catch(error){test('RC3 new EXE compiled approval prerequisite (fail closed)',()=>{throw error;});}
if(embedded){
  test('RC3 actual EXE / PE / PYZ / embedded asset integrity gate',()=>{
    assert.equal(embedded.exeSha,pinnedExeSha);
    assert.equal(embedded.jsSha,pinnedViteJsSha);
    assert.equal(embedded.cssSha,pinnedViteCssSha);
  });
  registerFrozenRc3Scenarios(embedded);
}
