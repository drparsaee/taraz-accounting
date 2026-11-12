"""Official CDP attach to the *actual*, SHA-pinned frozen Taraz WebView2.

Read-only initial probe. Launches the uninstalled EXE on a private Win32
desktop with a copied independently verified offline QA profile. Never runs
the Python accounting host, overrides window.madar, installs software, changes
the live finance data, sends global input, force-kills processes or changes
the Windows registry. No secret/source accounting data is printed.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import psutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v106_finalfix_native_gui_20261112 as pinned
from scripts import qa_taraz_v103_native_gui_20261111 as native
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acl

BUILD = pinned.ARTIFACTS / 'build-8498c703dc4d'
EXE = BUILD / 'binary' / 'Taraz.exe'
EXE_SHA = '3462cfb0dc93365e202686691eb74cc1b97dcde0333c44266191db934a42e9f4'
SOURCE_SHA = '1661fab1c4e6dd66a70bd596f002a28d7db11dd30816c1ac20d0422d392abe4f'
OUTPUT = pinned.ARTIFACTS / 'frozen-aaas-cdp-private-qa-20261112'

CDP_PROBE = r'''
const {chromium}=require(process.argv[3]);
const fs=require('node:fs');
const port=Number(process.argv[2]),out=process.argv[4];
let browser;
const result={status:'BLOCKED',frozenExe:true,pythonHostUsed:false,
  cdPAttached:false,bridgeReal:false,invoicePresent:false,orderPresent:false,
  printPresent:false,financialWriteAttempted:false};
async function main(){
  browser=await chromium.connectOverCDP('http://127.0.0.1:'+port,{timeout:8500});
  const contexts=browser.contexts();
  if(contexts.length!==1)throw Error('PRIVATE_WEBVIEW_CONTEXT_AMBIGUOUS');
  const candidates=contexts[0].pages().filter(p=>{
    try{const u=new URL(p.url());return u.hostname==='127.0.0.1'&&
      u.pathname==='/accounting.html';}catch{return false;}
  });
  if(candidates.length!==1)throw Error('PRIVATE_WEBVIEW_PAGE_AMBIGUOUS');
  const page=candidates[0];
  result.cdPAttached=true;
  await page.locator('.sac-root').waitFor({timeout:11000});
  result.bridgeReal=await page.evaluate(()=>
    typeof window.madar?.standaloneAccountingRead==='function' &&
    typeof window.madar?.standaloneAccountingCommand==='function' &&
    typeof window.madar?.tarazOrderList==='function');
  result.invoicePresent=await page.locator('[data-accounting-tab="invoice"]').count()>0;
  result.orderPresent=await page.locator('[data-accounting-tab="orders"]').count()>0;
  result.printPresent=await page.locator('[data-accounting-tab="invoiceDesign"]').count()>0;
  if(!result.bridgeReal||!result.invoicePresent||!result.orderPresent||
     !result.printPresent)throw Error('FROZEN_UI_BRIDGE_OR_TABS_UNAVAILABLE');
  result.status='PASS_REAL_FROZEN_EXE_CDP_READ_ONLY';
}
main().catch(e=>{result.status='BLOCKED';result.errorType=String(e.message||e).slice(0,125);
  process.exitCode=1;}).finally(async()=>{
  if(browser)try{await browser.close()}catch{}
  fs.writeFileSync(out,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
});
'''


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run():
    if os.name!='nt' or not EXE.is_file() or sha(EXE)!=EXE_SHA:
        raise RuntimeError('Exact private frozen candidate unavailable')
    original_source=pinned.builder.digest_inventory(pinned.builder.source_inventory())
    if original_source!=SOURCE_SHA:
        raise RuntimeError('Runtime source differs from frozen candidate')
    report=json.loads((BUILD/'build-report.json').read_text(encoding='utf-8'))
    if (report.get('exeSha256')!=EXE_SHA or
            report.get('sourceFreezeSha256')!=SOURCE_SHA or
            report.get('installed') is not False):
        raise RuntimeError('Frozen build identity gate refused')
    baseline=pinned.builder.installed_baseline()
    old_pids=pinned.snapshot_pids()
    if not OUTPUT.exists():
        acl.secure_private_directory(OUTPUT)
    work=OUTPUT/('qa-'+uuid.uuid4().hex[:12])
    acl.secure_private_directory(work)
    report_path=work/'frozen-cdp-report.json'
    result={'status':'BLOCKED','exeSha256':EXE_SHA,'sourceSha256':SOURCE_SHA,
            'mode':'REAL_FROZEN_EXE_CDP', 'sourceHosted':False,
            'installedBaselineUnchanged':False,'previousTarazPidsUnchanged':False,
            'qaProcessClosedGracefully':False,'noForcedTermination':True}
    hproc=hthread=0
    pid=0
    ledger=None
    initial_digest=None
    try:
        runtime,roots=native.clone_offline_snapshot(work)
        ledger=roots['roaming']/'standalone-accounting.sqlite3'
        initial_digest=sha(ledger)
        marker=roots['roaming']/'.taraz-private-cdp-qa.json'
        marker.write_text(json.dumps({
            'privateQaOnly':True,'profile':str(roots['roaming'].resolve())
        },ensure_ascii=False),encoding='utf-8')
        status_file=work/'private-profile'/'native-startup.json'
        cdp_result=work/'private-profile'/'cdp-result.json'
        port=native.unused_port()
        env=native.isolated_env(runtime,roots,status_file,port)
        env['TARAZ_QA_CDP_PORT']=str(port)
        if ('--remote-debugging-address=127.0.0.1' not in
                env.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS','')):
            raise RuntimeError('Loopback-only CDP flag not enforced')
        playwright=ROOT/'node_modules'/'playwright'
        if not playwright.is_dir():
            raise RuntimeError('Project-local Playwright unavailable')
        with native.PrivateDesktop() as desktop:
            pid,hproc,hthread=desktop.spawn(EXE,work,env)
            proc=psutil.Process(pid)
            try:
                if Path(proc.exe()).resolve()!=EXE.resolve():
                    raise RuntimeError('Private child EXE path mismatch')
                deadline=time.monotonic()+32
                while time.monotonic()<deadline:
                    if (status_file.is_file() and
                        native.safe_webview_diagnostics(pid,port)['cdpPortListening']):
                        break
                    time.sleep(.3)
                diag=native.safe_webview_diagnostics(pid,port)
                result['startupReportExists']=status_file.is_file()
                result['cdpPortListening']=diag['cdpPortListening']
                result['cdpFlagInOwnedWebView']=diag['expectedPortFlag']
                result['privateWebViewProfile']=diag['anyIsolatedWebviewProfileArg']
                if not (result['cdpPortListening'] and result['cdpFlagInOwnedWebView']):
                    raise RuntimeError('Private WebView2 did not open verified CDP transport')
                # Browser debug service must bind only loopback, not LAN.
                listeners=[con for con in psutil.net_connections(kind='tcp')
                    if con.laddr and con.laddr.port==port and
                    con.status==psutil.CONN_LISTEN]
                if (len(listeners)!=1 or
                    listeners[0].laddr.ip not in ('127.0.0.1','::1')):
                    raise RuntimeError('CDP bind address is not isolated loopback')
                script=work/'private-profile'/'probe.cjs'
                script.write_text(CDP_PROBE,encoding='utf-8')
                completed=subprocess.run(
                    ['node',str(script),str(port),str(playwright),str(cdp_result)],
                    cwd=work,env=env,capture_output=True,text=True,errors='replace',
                    check=False)
                result['cdpRunnerExitCode']=completed.returncode
                result['cdp']=json.loads(
                    cdp_result.read_text(encoding='utf-8')) if cdp_result.is_file() else {'status':'NO_REPORT'}
            finally:
                # This runs even if CDP preflight or Playwright fails. Never
                # terminate, signal other processes or switch user desktops.
                owned={pid}
                try: owned.update(x.pid for x in proc.children(recursive=True))
                except psutil.Error: pass
                try:
                    windows=pinned.owned_window_handles(desktop,owned)
                    result['privateOwnedTarazWindows']=len(windows)
                    if len(windows)==1:
                        result['closePostedToOwnedWindow']=bool(
                            ctypes.windll.user32.PostMessageW(windows[0],0x0010,0,0))
                    else:
                        result['closePostedToOwnedWindow']=False
                except Exception as exc:
                    result['privateCloseErrorType']=type(exc).__name__
                try:
                    proc.wait(timeout=14)
                    result['qaProcessClosedGracefully']=True
                except psutil.TimeoutExpired:
                    result['qaProcessRemainedRunningPid']=pid
    except Exception as exc:
        result['errorType']=type(exc).__name__
        result['error']=str(exc)[:175]
    finally:
        if hproc: ctypes.windll.kernel32.CloseHandle(hproc)
        if hthread: ctypes.windll.kernel32.CloseHandle(hthread)
        result['installedBaselineUnchanged']=pinned.builder.installed_baseline()==baseline
        result['previousTarazPidsUnchanged']=pinned.snapshot_pids()==old_pids
        result['privateLedgerUnchanged']=(ledger is not None and
            ledger.is_file() and sha(ledger)==initial_digest)
        result['candidateUnchanged']=sha(EXE)==EXE_SHA
        result['status']=('PASS_FROZEN_CDP_PROBE' if
            result.get('cdp',{}).get('status')=='PASS_REAL_FROZEN_EXE_CDP_READ_ONLY' and
            result['qaProcessClosedGracefully'] and
            result['installedBaselineUnchanged'] and
            result['previousTarazPidsUnchanged'] and
            result['privateLedgerUnchanged'] and
            result['candidateUnchanged'] else 'BLOCKED')
        report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result,report_path


if __name__=='__main__':
    if sys.argv[1:]!=['--run-private']:
        raise SystemExit('Explicit --run-private required; no EXE spawned')
    outcome,path=run()
    print(json.dumps({'status':outcome['status'],'report':str(path),
        'cdp':outcome.get('cdp',{}),'error':outcome.get('error'),
        'gracefulExit':outcome['qaProcessClosedGracefully'],
        'baselineUnchanged':outcome['installedBaselineUnchanged'],
        'ledgerUnchanged':outcome['privateLedgerUnchanged']},ensure_ascii=False))
    raise SystemExit(0 if outcome['status']=='PASS_FROZEN_CDP_PROBE' else 1)
