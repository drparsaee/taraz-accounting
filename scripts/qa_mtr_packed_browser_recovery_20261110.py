"""Actual React Chromium clicks -> disposable shim -> latest SHA-pinned Taraz PYZ.

NO installed Taraz, personal accounting profile, ledger, finance posting,
external web request, deployment or network bridge is used.
This runs current real React source, not the installed executable window.
"""

from __future__ import annotations

from contextlib import ExitStack
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT / "scripts"
PINNED_RUNNER = SCRIPTS / "qa_mtr_latest_bundle_recovery_20261110.py"
MTR_NODE_MODULES = Path(
    r"D:\CoS-Test\000- Madar\madar-p2-gantt-notifications-20261107\node_modules"
)
_ID = re.compile(r"^[0-9a-f]{32}$")


class QARefused(RuntimeError):
    pass


def _load_existing_runner():
    """Read only the already implemented exact-hash packed-module gate."""
    if not PINNED_RUNNER.is_file() or PINNED_RUNNER.is_symlink():
        raise QARefused("SHA-pinned previous QA runner unavailable")
    spec = importlib.util.spec_from_file_location(
        "mtr_qa_latest_packaged_recovery_readonly", PINNED_RUNNER)
    if spec is None or spec.loader is None:
        raise QARefused("Cannot load pinned packaged QA helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _outcome(data: dict) -> dict:
    return {
        "backend": "EXACT_PINNED_TARAZ_PYZ_ONLY",
        "exeSha256": data["exeSha256"],
        "packedModuleSha256": data["packedModuleSha256"],
        "qaOnly": True,
        "installedExeLaunched": False,
        "financialEventCreated": False,
    }


def shim_child(root: Path, action: str, request_id: str, manual: bool) -> dict:
    """Host-visible QA methods, executed with *actual* packed PYZ code object."""
    runner = _load_existing_runner()
    helper = runner.previous_runner()
    # This validates every synthetic APPDATA/LOCALAPPDATA/TEMP/etc. path.
    helper.verify_scratch(root)
    code, evidence = runner.verify_latest_bundle()
    integration = helper.load_packed_module(code)
    if action == "combined-list":
        if request_id or manual:
            raise QARefused("Listing must be a read-only explicit operator refresh")
        pending = integration.list_requests(root)
        recovery = integration.list_recoverable_reviews(root)
        if recovery.get("recoveryTruncated") is True:
            raise QARefused("Cannot present truncated recovery as complete")
        incomplete = {item["id"] for item in recovery["recovery"]}
        pending["requests"] = [
            item for item in pending["requests"] if item["id"] not in incomplete
        ]
        data = {**pending, **recovery}
        if not isinstance(data.get("requests"), list) or not isinstance(
            data.get("recovery"), list
        ):
            raise QARefused("Actual packed module returned malformed Inbox data")
        if any(item.get("financialEventCreated") is not False
               for item in data["recovery"]):
            raise QARefused("Recovery listing is not explicitly nonfinancial")
        return {**_outcome(evidence), "action": action, "data": data}
    if action == "recover":
        if not manual or not _ID.fullmatch(request_id):
            raise QARefused("Recovery requires exact ID and manual confirmation")
        result = integration.recover_review(root, request_id)
        if result != {
            "id": request_id, "state": result.get("state"),
            "financialEventCreated": False,
        } or result["state"] not in ("reviewed", "rejected"):
            raise QARefused("Packed recovery returned unsupported metadata")
        return {**_outcome(evidence), "action": action, "data": result}
    raise QARefused("Only list and explicit recover are available to browser shim")


BROWSER_JS = r"""
'use strict';
// Browser flow owns no financial API; only strict SHA-pinned disposable shim.
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');
const execFileAsync = promisify(execFile);
const config = JSON.parse(process.env.MTR_QA_RECOVERY_CONFIG||'null');
if (!config || !Array.isArray(config.cases) || config.cases.length!==2) {
  throw Error('Invalid explicit bounded QA scenario count');
}
const esbuild = require(path.join(config.nodeModules, 'esbuild'));
const playwright = require(path.join(config.playwrightModules, 'playwright'));
const validId = /^[a-f0-9]{32}$/;
const events=[];
function childEnv(root) {
  const env={};
  for (const key of ['PATH','SYSTEMROOT','WINDIR','PATHEXT','COMSPEC',
                     'NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE']) {
    if (process.env[key]) env[key]=process.env[key];
  }
  const folders={
    APPDATA:'qa-profile/roaming', LOCALAPPDATA:'qa-profile/local',
    TEMP:'qa-profile/temp', TMP:'qa-profile/temp',
    USERPROFILE:'qa-profile/user', HOME:'qa-profile/home',
    TARAZ_QA_DATA_DIR:'qa-profile/qa/ledger'
  };
  for (const [name,rel] of Object.entries(folders)) {
    const folder=path.join(root,rel);
    fs.mkdirSync(folder,{recursive:true});
    env[name]=folder;
  }
  env.TARAZ_QA_MODE='1';
  env.PYTHONDONTWRITEBYTECODE='1';
  env.PYTHONNOUSERSITE='1';
  return env;
}
function checkResponse(raw, action) {
  if (raw.length>32768 || raw.trim().split(/\r?\n/).length!==1) {
    throw Error('Unsafe shim response length/shape');
  }
  const value=JSON.parse(raw.trim());
  if (value.backend!=='EXACT_PINNED_TARAZ_PYZ_ONLY' ||
      value.action!==action || value.qaOnly!==true ||
      value.exeSha256!==config.exeSha256 ||
      value.packedModuleSha256!==config.moduleSha256 ||
      value.installedExeLaunched!==false ||
      value.financialEventCreated!==false ||
      !value.data || typeof value.data!=='object') {
    throw Error('Shim did not attest exact current packed PYZ contract');
  }
  if (action==='combined-list') {
    if (value.data.connected!==true || !Array.isArray(value.data.requests) ||
        !Array.isArray(value.data.recovery)) throw Error('Malformed packed Inbox listing');
  } else if (value.data.financialEventCreated!==false) {
    throw Error('Not a metadata-only recovery receipt');
  }
  return value.data;
}
async function callShim(item,action,id='',manual=false) {
  if (!validId.test(item.id) || !['reviewed','rejected'].includes(item.decision)) {
    throw Error('Invalid synthetic case binding');
  }
  if (action==='recover' && (id!==item.id || manual!==true)) {
    throw Error('Unapproved recovery attempt');
  }
  if (action==='combined-list' && (id!=='' || manual!==false)) {
    throw Error('Unexpected listing authority');
  }
  const args=['-I','-B',config.python,'--child','--root',item.root,
              '--shim-action',action,'--request-id',id];
  if (manual)args.push('--manual-action');
  let response;
  try{
    ({stdout:response}=await execFileAsync(config.pythonExe,args,{
      cwd:item.root,env:childEnv(item.root),windowsHide:true,timeout:25000,
      maxBuffer:32768,encoding:'utf8'
    }));
  }catch(err){
    throw Error('Pinned packed Python child refused '+action+' ('+
                String(err.code||'FAILED')+')');
  }
  const data=checkResponse(response,action);
  events.push({case:item.decision,action,manual,
               result:action==='recover'?data.state:'listed'});
  return data;
}
async function compileActualReact(){
  const entry=[
    "import React from 'react';",
    "import {createRoot} from 'react-dom/client';",
    "import TarazSettings from './src/taraz_settings.jsx';",
    "const api={",
    " tarazIntegrationList:()=>window.__qaRecovery('combined-list','',false),",
    " tarazIntegrationRecover:(id,confirmed)=>window.__qaRecovery('recover',id,confirmed),",
    " tarazIntegrationReview:()=>{throw Error('No normal review allowed in recovery QA')},",
    " standaloneAccountingCommand:()=>{throw Error('No financial command allowed')}",
    "};",
    "createRoot(document.getElementById('root')).render(",
    " <TarazSettings api={api} canManage={true} canDraft={false}/>);"
  ].join('\n');
  const result=(await esbuild.build({
    stdin:{contents:entry,resolveDir:config.project,
           sourcefile:'mtr-current-browser-to-packed-qa.jsx',loader:'jsx'},
    bundle:true,platform:'browser',format:'iife',
    write:false,logLevel:'silent',charset:'utf8',
    outdir:'mtr-current-packed-recovery-browser',
    loader:{'.css':'css','.jpg':'dataurl','.svg':'dataurl','.png':'dataurl'},
    plugins:[{name:'bounded-readonly-local-react-deps',setup(build){
      build.onResolve({filter:/^(react|react-dom\/client|react\/jsx-runtime|lucide-react)$/},
        args=>({path:require.resolve(args.path,{paths:[config.nodeModules]})}));
    }}],
  })).outputFiles;
  const js=result.find(p=>p.path.endsWith('.js'))?.text;
  if(!js)throw Error('Actual Taraz React JSX did not compile');
  return {js,css:result.find(p=>p.path.endsWith('.css'))?.text||''};
}
async function run(){
  const assets=await compileActualReact();
  // One browser for both decisions; synthetic ephemeral profile under QA root.
  const browser=await playwright.chromium.launch({
    executablePath:config.browserExecutable,headless:true,
    args:['--no-first-run','--disable-background-networking',
          '--disable-default-apps','--disable-sync',
          '--no-default-browser-check','--disable-component-update'],
    env:childEnv(config.cases[0].root)
  });
  const reports=[];
  try {
    for (const item of config.cases){
      const context=await browser.newContext({viewport:{width:1280,height:900}});
      await context.route('**/*', route=>route.abort());
      const page=await context.newPage();
      const stats={list:0,recover:0,review:0,finance:0};
      try {
        await page.exposeFunction('__qaRecovery',async(action,id,manual)=>{
          if (action==='combined-list'){
            if(id!=='' || manual!==false || stats.list>=2 ||
               (stats.list===1 && stats.recover!==1)) {
              throw Error('Unprompted or duplicate Inbox refresh');
            }
            stats.list++;
          }else if(action==='recover'){
            if(id!==item.id || manual!==true ||
               stats.list!==1 || stats.recover!==0){
              throw Error('Duplicate, automatic or unconfirmed packed recovery');
            }
            stats.recover++;
          }else{
            stats.review++;
            throw Error('Normal review/finance is blocked in QA');
          }
          return callShim(item,action,id,manual);
        });
        await page.setContent('<!doctype html><html lang="fa" dir="rtl">'+
          '<head><meta charset="utf-8"></head><body><main id="root"></main></body></html>');
        if(assets.css) await page.addStyleTag({content:assets.css});
        await page.addScriptTag({content:assets.js});
        await page.getByRole('button',{name:'اتصال به مدار'}).click();
        const consent=page.getByRole('checkbox',{
          name:/ارجاع‌های مدار را دستی بررسی کنم/
        });
        const refresh=page.getByRole('button',{name:'بررسی وضعیت اتصال'});
        assert.equal(await refresh.isDisabled(),true);
        assert.deepEqual(stats,{list:0,recover:0,review:0,finance:0});
        await consent.check();
        assert.equal(await refresh.isEnabled(),true);
        assert.equal(stats.list,0,'Consent must not auto-query Inbox');
        assert.equal(stats.recover,0,'Consent must not auto-recover');
        await refresh.click();
        const button=page.getByRole('button',{name:'بازیابی دستی تصمیم ناتمام'});
        await button.waitFor({timeout:12000});
        assert.equal(stats.list,1);
        assert.equal(stats.recover,0);
        assert.equal(await page.getByText('QA-only packaging service').count(),1);
        // Opt-in, refresh and merely showing recovery never touches receipt.
        assert.equal(await page.getByRole('button',{name:'تأیید تصمیم'}).count(),0);
        await button.click();
        const approval=page.getByRole('group',{name:'تأیید تصمیم ارجاع'});
        await approval.waitFor({timeout:8000});
        assert.equal(await approval.getByText('تأیید بازیابی تصمیم پایدار').count(),1);
        assert.equal(stats.recover,0,'First recovery click cannot execute backend');
        // Cancel once, prove cancellation has no side effect.
        await approval.getByRole('button',{name:'انصراف'}).click();
        assert.equal(await approval.count(),0);
        assert.equal(stats.recover,0,'Cancellation cannot recover');
        await button.click();
        await approval.waitFor();
        assert.equal(stats.recover,0);
        await approval.getByRole('button',{name:'تأیید تصمیم'}).click();
        await page.getByText('تصمیم قبلی از ثبت پایدار بازیابی شد. هیچ سند مالی ایجاد نشد.')
          .waitFor({timeout:12000});
        await page.getByText('ارجاع بررسی‌نشده‌ای در صندوق وجود ندارد.')
          .waitFor({timeout:12000});
        // The success label is set before the asynchronous Inbox refresh.
        // Wait for the actual React recovery row to disappear.
        await button.waitFor({state:'detached',timeout:12000});
        assert.equal(await button.count(),0);
        assert.deepEqual(stats,{list:2,recover:1,review:0,finance:0});
        const trace=events.filter(x=>x.case===item.decision);
        assert.deepEqual(trace.map(x=>x.action),
          ['combined-list','recover','combined-list']);
        assert.equal(trace[1].manual,true);
        assert.equal(trace[1].result,item.decision);
        reports.push({
          decision:item.decision,initialReadsBeforeConsent:0,
          onlyManualReads:true,initialManualRefreshCount:1,
          secondConfirmation:true,cancellationNoSideEffect:true,
          packedRecoveryCalls:stats.recover,postRecoveryReads:1,
          normalReviewCalls:stats.review,financialCalls:stats.finance,
          browserActuallyClicked:true,
        });
      }finally{
        await context.close();
      }
    }
  }finally{
    await browser.close();
  }
  return {status:'CURRENT_REACT_CHROMIUM_TO_PINNED_PYZ_RECOVERY_PASS',
    qaOnly:true,exeSha256:config.exeSha256,
    packedModuleSha256:config.moduleSha256,installedExeLaunched:false,
    noFinanceActions:true,reports,invocations:events};
}
run().then(report=>process.stdout.write(JSON.stringify(report)+'\n'))
  .catch(error=>{
    process.stderr.write(JSON.stringify({status:'BLOCKED',
      reason:String(error?.stack||error?.message||error).slice(0,1400)})+'\n');
    process.exitCode=2;
  });
"""


def _node_runtime() -> tuple[Path, Path]:
    """Bounded existing QA dependencies; no package installation or edits."""
    if not MTR_NODE_MODULES.is_dir() or MTR_NODE_MODULES.is_symlink():
        raise QARefused("Trusted local esbuild/React dependencies are missing")
    for name in ("esbuild", "react", "react-dom", "lucide-react"):
        if not (MTR_NODE_MODULES / name).is_dir():
            raise QARefused("Missing required JSX dependency: " + name)
    # Existing read-only QA tool uses globally installed Playwright; this is
    # a tooling dependency only, never the Taraz accounting application profile.
    home = os.environ.get("USERPROFILE")
    if not home:
        raise QARefused("No explicit tooling-only Playwright runtime location")
    global_modules = Path(home) / "AppData" / "Roaming" / "npm" / "node_modules"
    if not (global_modules / "playwright").is_dir():
        raise QARefused("Existing Playwright tooling package is unavailable")
    return MTR_NODE_MODULES, global_modules


def _system_browser() -> Path:
    # Never derive the browser executable from the user's real LOCALAPPDATA.
    for candidate in (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise QARefused("No system-installed Chromium browser executable available")


def prepare_case(runner, helper, root: Path, decision: str) -> dict:
    identifier = uuid.uuid4().hex
    source = helper.write_proposal(root, identifier)
    original = source.read_bytes()
    interrupted = runner.spawn_child(
        root, "review", identifier, decision, fault="before-receipt")
    interrupted_data = runner.parse_child(interrupted, success=False)
    if interrupted_data.get("exception") != "OSError":
        raise QARefused("Packed PYZ failed to produce an after-move crash fixture")
    reviewed = root / "reviewed"
    moved = reviewed / (identifier + ".json")
    intent = reviewed / (identifier + ".intent.json")
    receipt = reviewed / (identifier + ".review.json")
    if source.exists() or moved.read_bytes() != original or receipt.exists():
        raise QARefused("After-move durable fixture invalid")
    metadata = json.loads(intent.read_text(encoding="utf-8"))
    if (metadata.get("sourceDigest") != hashlib.sha256(original).hexdigest()
            or metadata.get("state") != decision
            or metadata.get("financialEventCreated") is not False):
        raise QARefused("After-move fixture lacks source-bound nonfinancial intent")
    return {"root": str(root), "id": identifier, "decision": decision,
            "sourceDigest": metadata["sourceDigest"],
            "intentBefore": intent.read_bytes(), "payloadBefore": moved.read_bytes()}


def _require_final(root: Path, prepared: dict) -> dict:
    reviewed = root / "reviewed"
    identifier = prepared["id"]
    intent = reviewed / (identifier + ".intent.json")
    receipt = reviewed / (identifier + ".review.json")
    moved = reviewed / (identifier + ".json")
    if (intent.read_bytes() != prepared["intentBefore"]
            or moved.read_bytes() != prepared["payloadBefore"]
            or not receipt.is_file()):
        raise QARefused("Browser flow altered durable intent or original proposal")
    data = json.loads(receipt.read_text(encoding="utf-8"))
    durable = json.loads(intent.read_text(encoding="utf-8"))
    if data != {key: value for key, value in durable.items()
                if key != "sourceDigest"}:
        raise QARefused("Actual packed receipt does not exactly match durable intent")
    if data["financialEventCreated"] is not False:
        raise QARefused("Unexpected financial claim in packed metadata receipt")
    return {"decision": prepared["decision"], "sourceDigestVerified": True,
            "receiptPersisted": True, "financialEventCreated": False}


def _frontend_source_snapshot(helper) -> dict[str, str]:
    files = (
        PROJECT / "src" / "taraz_settings.jsx",
        PROJECT / "src" / "taraz_settings_integration.js",
    )
    checksums = {}
    for path in files:
        helper.refuse_link(path)
        if not path.is_file() or path.stat().st_size > 250000:
            raise QARefused("Actual React recovery source missing or unbounded")
        checksums[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return checksums


def run_browser() -> dict:
    if sys.version_info[:2] != (3, 12):
        raise QARefused("Actual PYZ code test requires Python 3.12")
    runner = _load_existing_runner()
    helper = runner.previous_runner()
    _, build = runner.verify_latest_bundle()
    if build["exeSha256"] != runner.EXE_SHA256 or (
            build["packedModuleSha256"] != runner.PYZ_MODULE_SHA256):
        raise QARefused("Newest QA EXE or packed PYZ manifest changed")
    modules, playwright_modules = _node_runtime()
    browser_executable = _system_browser()
    frontend_snapshot = _frontend_source_snapshot(helper)
    with ExitStack() as stack:
        prepared = []
        for decision in ("reviewed", "rejected"):
            root = stack.enter_context(helper.sandbox())
            prepared.append(prepare_case(runner, helper, root, decision))
        env = helper.sandbox_env(Path(prepared[0]["root"]))
        config = {"cases": [
            {key: item[key] for key in ("root", "id", "decision")}
            for item in prepared
        ], "project": str(PROJECT), "nodeModules": str(modules),
            "playwrightModules": str(playwright_modules),
            "browserExecutable": str(browser_executable),
            "exeSha256": runner.EXE_SHA256,
            "moduleSha256": runner.PYZ_MODULE_SHA256,
            "python": str(Path(__file__).resolve()),
            "pythonExe": sys.executable}
        env["MTR_QA_RECOVERY_CONFIG"] = json.dumps(config)
        browser = subprocess.run(
            ["node", "-"], input=BROWSER_JS, cwd=PROJECT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=135,
            check=False)
        if browser.returncode != 0:
            raise QARefused("Browser-to-packed recovery QA blocked: " +
                            browser.stderr[-1450:])
        lines = browser.stdout.strip().splitlines()
        if len(lines) != 1 or len(lines[0]) > 25000:
            raise QARefused("React-to-packed browser process returned invalid report")
        answer = json.loads(lines[0])
        if (answer.get("status") !=
                "CURRENT_REACT_CHROMIUM_TO_PINNED_PYZ_RECOVERY_PASS"
                or answer.get("exeSha256") != runner.EXE_SHA256
                or answer.get("packedModuleSha256") != runner.PYZ_MODULE_SHA256
                or len(answer.get("reports", [])) != 2):
            raise QARefused("Browser result did not attest exact packed recovery")
        for trace in answer["reports"]:
            if (trace.get("packedRecoveryCalls") != 1 or
                    trace.get("normalReviewCalls") != 0 or
                    trace.get("financialCalls") != 0 or
                    trace.get("browserActuallyClicked") is not True or
                    trace.get("secondConfirmation") is not True):
                raise QARefused("No single, explicit, financial-free UI recovery")
        saved = [_require_final(Path(item["root"]), item) for item in prepared]
        if _frontend_source_snapshot(helper) != frontend_snapshot:
            raise QARefused("Current React source changed during Chromium QA")
        answer["durableVerification"] = saved
        answer["testedCurrentReactSourceSha256"] = frontend_snapshot
        answer["syntheticOnly"] = True
        answer["installedProgramLaunched"] = False
        answer["realLedgerAccessed"] = False
        # Synthetic IDs and path locations are not needed in a user-facing log.
        return answer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--shim-action", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--manual-action", action="store_true")
    parser.add_argument("--manifest-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.child:
            if args.manifest_only or args.root is None:
                raise QARefused("Malformed isolated child request")
            result = shim_child(args.root, args.shim_action,
                                args.request_id, args.manual_action)
        elif args.manifest_only:
            runner = _load_existing_runner()
            _, result = runner.verify_latest_bundle()
        else:
            result = run_browser()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "type": type(exc).__name__,
                          "reason": str(exc)[:650]}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
