"""Independent, bounded GUI acceptance of the second immutable Taraz 1.0.6 EXE.

Only the SHA-pinned compiled executable is launched on a separate non-input
Windows desktop with an ACL-restricted offline-backup QA clone. Browser actions
navigate and modify UNSAVED form state, never call an accounting/order write,
submit a form, print to a physical printer, or access an installed user window.
Run --static first, then --run-private-native. Reports contain only booleans.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v103_native_gui_20261111 as private
from scripts import qa_taraz_v103_independent_acceptance_20261111 as backup
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as access
from scripts import build_taraz_v106_aaas_20261111 as builder

BASE = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.6-aaas"
BUILD = BASE / "build-81cd2dc22365"
EXE = BUILD / "binary" / "Taraz.exe"
SOURCE_SHA = "cb9c84a349cc09c8f343a8b1b3a5a4fcec1bfa9fa9ec5a0d8d41424e219cad31"
EXE_SHA = "4b5d17a460e1f5de827f0d36e63e72e27140362b79def5fd268e6e76b7f95731"
JS_NAME = "assets/accounting-CVrWdeBJ.js"
JS_SHA = "1e6a207dcbb92e9388b12b932c6e798268792fabb15ea63f226c9660b0ef2654"
RESULTS = BASE / "clarify-native-qa-20261112"
PLAYWRIGHT = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "playwright"


class QABlocked(RuntimeError):
    pass


def hash_file(filename):
    stream_hash = hashlib.sha256()
    with filename.open("rb") as file:
        for data in iter(lambda: file.read(1024 * 1024), b""):
            stream_hash.update(data)
    return stream_hash.hexdigest()


def prereq():
    if os.name != "nt":
        raise QABlocked("Requires native Windows")
    for item in (EXE, BUILD / "build-report.json"):
        if not item.is_file() or item.is_symlink():
            raise QABlocked("Immutable build file missing or symlinked")
    if hash_file(EXE) != EXE_SHA:
        raise QABlocked("Compiled EXE differs from pinned second build")
    build = json.loads((BUILD / "build-report.json").read_text(encoding="utf-8"))
    if not (
        build.get("status") == "V106_AAAS_NON_QA_BUILT_NOT_INSTALLED"
        and build.get("version") == "1.0.6"
        and build.get("sourceFreezeSha256") == SOURCE_SHA
        and build.get("sourceFilesCount") == 138
        and build.get("exeSha256") == EXE_SHA
        and build.get("installed") is False
        and build.get("pointerChanged") is False
        and build.get("compiled", {}).get("qaOnly") is False
        and build.get("compiled", {}).get("bridgeForwarded") is True
        and build.get("compiled", {}).get("compiledByteParity") is True
        and build.get("compiled", {}).get("peVersion") == "1.0.6.0"
        and build.get("compiled", {}).get("assetsSha256", {}).get(JS_NAME) == JS_SHA
    ):
        raise QABlocked("Build report source/compiled provenance mismatch")
    # Independent readback of UI bytes from actual EXE container.
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(EXE))
    binary = archive.extract("dist\\assets\\" + JS_NAME.split("/")[-1])
    if not isinstance(binary, bytes) or hashlib.sha256(binary).hexdigest() != JS_SHA:
        raise QABlocked("Compiled embedded WebView JS differs from second build")
    if not PLAYWRIGHT.is_dir():
        raise QABlocked("Known shared Playwright package unavailable")
    if backup.verify_backup(backup.BACKUP).get("filesRehashed") != 181:
        raise QABlocked("Cold backup not verified, cloning blocked")
    return {"sourceSha": SOURCE_SHA, "exeSha": EXE_SHA,
            "compiledJsSha": JS_SHA, "coldBackupFilesVerified": 181}


CDP_JS = r"""
'use strict';
const {chromium}=require(process.argv[2]);
const fs=require('node:fs');
const port=Number(process.argv[1]);
const file=process.argv[3];
const observations={
  realEmbeddedWebViewAttached:false, rootMounted:false,
  cdpConnected:false, cdpContextsSeen:0, cdpPagesSeen:0,
  cdpAllowedAccountingPagesSeen:0, cdpDistinctErrorKinds:[],
  orderScreen:false, orderBeginner:false, orderProfessional:false,
  orderRequestEntered:false, orderLocalHintsAttempted:false,
  orderModelButtonAvailable:false, orderSaved:false,
  invoiceBeginnerScreen:false, invoiceCustomerControl:false,
  invoiceLineEdited:false, invoiceCalculationVisible:false,
  invoiceSaved:false, printDesignerScreen:false,
  printCanvasRendered:false, printPresetApplied:false,
  printColumnToggleWorked:false, printPreviewOpened:false,
  printLocalAiVisible:false, printLocalAiSuggested:false,
  hostOrderListMethod:false, hostOrderSuggestMethod:false,
  hostPrintSuggestMethod:false, hostAccountingReadMethod:false,
  externalRequestsBlocked:0, externalRequestsObserved:0,
  unhandledPageErrors:0, uiErrorCodes:[],
  ledgerCommandsInvokedByHarness:0, orderCommandsInvokedByHarness:0,
  physicalPrinterUsed:false, changedInstalledApp:false,
  actionsOnRealDesktop:false
};
let browser;
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const local=u=>{try{const x=new URL(u);return x.protocol==='http:'&&
  (x.hostname==='127.0.0.1'||x.hostname==='localhost')}catch{return false}};
const step=async(key,work)=>{
  try{await work();observations[key]=true;}
  catch(e){observations.uiErrorCodes.push(key+':'+(e?.name||'Error'));}
};
const selectTab=async(page,key)=>{
  const direct=page.locator('[data-accounting-tab="'+key+'"]:visible').first();
  if(await direct.count()){await direct.click();return;}
  await page.locator('.sac-nav-more-trigger:visible').first().click();
  await page.locator('.taraz-vt-drawer [data-accounting-tab="'+key+'"]:visible').first().click();
};
(async()=>{
  let page,context;
  for(let i=0;i<72;i++){
    try{
      browser=await chromium.connectOverCDP('http://127.0.0.1:'+port,{timeout:2000});
      observations.cdpConnected=true;
      context=browser.contexts()[0];
      observations.cdpContextsSeen=Math.max(observations.cdpContextsSeen,browser.contexts().length);
      observations.cdpPagesSeen=Math.max(observations.cdpPagesSeen,context?.pages().length||0);
      observations.cdpAllowedAccountingPagesSeen=Math.max(
        observations.cdpAllowedAccountingPagesSeen,
        (context?.pages()||[]).filter(p=>local(p.url())&&p.url().includes('accounting.html')).length);
      page=(context?.pages()||[]).find(p=>local(p.url())&&p.url().includes('accounting.html'));
      if(page)break;
      await browser.close();browser=null;
    }catch(e){
      const name=e?.name||'Error';
      if(!observations.cdpDistinctErrorKinds.includes(name))
        observations.cdpDistinctErrorKinds.push(name);
      if(browser){try{await browser.close()}catch{}browser=null}
    }
    await wait(350);
  }
  if(!page)throw Error('NO_OWNED_WEBVIEW_ACCOUNTING_TARGET');
  observations.realEmbeddedWebViewAttached=true;
  page.setDefaultTimeout(4500);
  page.on('pageerror',()=>{observations.unhandledPageErrors++});
  page.on('request',request=>{
    const url=request.url();
    if(!local(url)&&!url.startsWith('data:')&&!url.startsWith('blob:'))
      observations.externalRequestsObserved++;
  });
  await context.route('**/*',route=>{
    const url=route.request().url();
    if(local(url)||url.startsWith('blob:')||url.startsWith('data:'))
      return route.continue();
    observations.externalRequestsBlocked++;
    return route.abort('blockedbyclient');
  });
  await page.locator('.sac-root').waitFor({timeout:18000});
  observations.rootMounted=true;
  const hostMethods=await page.evaluate(()=>({
    read:typeof window.madar?.standaloneAccountingRead==='function',
    orderList:typeof window.madar?.tarazOrderList==='function',
    orderSuggest:typeof window.madar?.tarazOrderSuggest==='function',
    printSuggest:typeof window.madar?.tarazPrintSuggest==='function'
  }));
  observations.hostAccountingReadMethod=hostMethods.read;
  observations.hostOrderListMethod=hostMethods.orderList;
  observations.hostOrderSuggestMethod=hostMethods.orderSuggest;
  observations.hostPrintSuggestMethod=hostMethods.printSuggest;
  await step('orderScreen',async()=>{
    await selectTab(page,'orders');
    await page.locator('.taraz-orders-editor').waitFor({timeout:8000});
  });
  if(observations.orderScreen){
    observations.orderModelButtonAvailable=await page.getByRole('button',{name:'پیشنهاد با مدل محلی'}).count()>0;
    await step('orderRequestEntered',async()=>{
      await page.locator('.taraz-orders-intake textarea').fill(
        'مشتری: آزمون محلی\nشرح سفارش: چاپ آزمایشی بدون ثبت\nتعداد فروش: 12 عدد، تولید 14 عدد');
    });
    await step('orderLocalHintsAttempted',async()=>{
      await page.getByRole('button',{name:'استخراج اطلاعات (آفلاین)'}).click();
      await page.locator('.taraz-orders-hint').first().waitFor({timeout:3500});
    });
    await step('orderProfessional',async()=>{
      await page.getByRole('button',{name:'حرفه‌ای',exact:true}).click();
      await page.locator('.taraz-orders-advanced').waitFor();
    });
  }
  await step('invoiceBeginnerScreen',async()=>{
    await page.locator('[data-accounting-action="invoice"]:visible').first().click();
    await page.locator('.sac-invoice-beginner-pane').waitFor({timeout:9000});
  });
  if(observations.invoiceBeginnerScreen){
    observations.invoiceCustomerControl=await page.getByRole('combobox',{name:'مشتری فاکتور'}).count()>0;
    await step('invoiceLineEdited',async()=>{
      await page.getByRole('textbox',{name:'شرح ردیف 1'}).fill('QA فقط نمایش بدون ذخیره');
      await page.getByRole('textbox',{name:'تعداد ردیف 1'}).fill('2');
      await page.getByRole('textbox',{name:'قیمت ردیف 1'}).fill('13500');
    });
    observations.invoiceCalculationVisible=await page.locator('.sac-beginner-preview').count()>0;
  }
  await step('printDesignerScreen',async()=>{
    await selectTab(page,'invoiceDesign');
    await page.locator('.sac-print-designer').waitFor({timeout:9000});
  });
  if(observations.printDesignerScreen){
    observations.printLocalAiVisible=await page.getByRole('button',{name:'پیشنهاد طراحی'}).count()>0;
    const canvas=page.locator('canvas[aria-label="نمای فاکتور قابل طراحی"]');
    await canvas.waitFor();
    observations.printCanvasRendered=await canvas.evaluate(el=>el.width>=250&&el.height>=250);
    await step('printPresetApplied',async()=>{
      await page.getByRole('combobox',{name:'سبک چیدمان'}).selectOption('compact');
      await page.getByRole('button',{name:'اعمال چیدمان انتخابی'}).click();
      if(await page.getByRole('combobox',{name:'کاغذ'}).inputValue()!=='A5')
        throw Error('PRESET_DID_NOT_APPLY');
    });
    await step('printColumnToggleWorked',async()=>{
      const option=page.getByLabel('واحد',{exact:true});
      await option.check();
      if(!await option.isChecked())throw Error('COLUMN_UNCHECKED');
    });
    await step('printPreviewOpened',async()=>{
      const opened=page.waitForEvent('popup',{timeout:7000});
      await page.getByRole('button',{name:'پیش‌نمایش همه صفحات'}).click();
      const window=await opened;
      await window.locator('img.sheet').first().waitFor({timeout:7000});
      await window.close();
    });
    // AI remains visible if and only if authenticated host bridge is present.
    // No model request here: model latency/service availability are separate.
  }
  const required=['realEmbeddedWebViewAttached','rootMounted','hostAccountingReadMethod',
    'orderScreen','orderProfessional','orderRequestEntered','invoiceBeginnerScreen',
    'invoiceLineEdited','printDesignerScreen','printCanvasRendered','printPresetApplied',
    'printColumnToggleWorked'];
  const mandatory=required.every(x=>observations[x]===true);
  observations.status=mandatory?'PASS_NATIVE_CLARIFY_GUI_READONLY':'PARTIAL_NATIVE_CLARIFY_GUI';
})().catch(err=>{
  observations.status='FAILED_NATIVE_GUI_HARNESS';
  observations.uiErrorCodes.push('fatal:'+(err?.name||'Error'));
}).finally(async()=>{
  try{fs.writeFileSync(file,JSON.stringify(observations,null,2)+'\n',{flag:'wx'});}
  catch{process.exitCode=2;}
  if(browser)try{await browser.close()}catch{}
});
"""


def processes():
    import psutil
    found = {}
    for item in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if (item.info.get("name") or "").lower() == "taraz.exe":
                found[item.pid] = item.info["create_time"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def run():
    checks = prereq()
    before = processes()
    access.secure_private_directory(RESULTS) if not RESULTS.exists() else None
    work = RESULTS / ("qa-v106-" + uuid.uuid4().hex[:12])
    access.secure_private_directory(work)
    destination = work / "native-acceptance.json"
    report = {"status": "BLOCKED", "sourceFreezeSha256": SOURCE_SHA,
              "candidateExeSha256": EXE_SHA, "candidateBuiltNotInstalled": True,
              "coldBackupFilesVerified": checks["coldBackupFilesVerified"],
              "privateDesktopCreated": False, "privateQaDataUsed": False,
              "installedBaselinePreserved": None, "oldTarazProcessesPreserved": None,
              "nativeWebViewLoaded": False, "accountingBridgePresent": False,
              "ownedProcessesRemaining": None}
    root_pid = 0
    h_process = h_thread = None
    owned = {}
    originally_installed = builder.installed_baseline()
    ledger = None
    ledger_before = None
    try:
        runtime, paths = private.clone_offline_snapshot(work)
        report["privateQaDataUsed"] = True
        ledger = paths["roaming"] / "standalone-accounting.sqlite3"
        ledger_before = hash_file(ledger)
        native_status = work / "private-profile" / "native-startup.json"
        ui_file = work / "private-profile" / "webview-qa.json"
        port = private.unused_port()
        env = private.isolated_env(runtime, paths, native_status, port)
        for key in ("APPDATA", "LOCALAPPDATA", "TEMP"):
            if Path(env[key]).resolve() == Path(os.environ[key]).resolve():
                raise QABlocked("QA process inherited live " + key)
        with private.PrivateDesktop() as desktop:
            report["privateDesktopCreated"] = True
            root_pid, h_process, h_thread = desktop.spawn(EXE, work, env)
            import psutil
            parent = psutil.Process(root_pid)
            if Path(parent.exe()).resolve() != EXE.resolve():
                raise QABlocked("QA PID does not belong to pinned executable")
            owned[root_pid] = parent.create_time()
            for child in parent.children(recursive=True):
                owned[child.pid] = child.create_time()
            started = time.monotonic()
            while time.monotonic() - started < 16 and not native_status.is_file():
                time.sleep(.3)
            report["webViewDiagnosticsBeforeCDP"] = private.safe_webview_diagnostics(root_pid, port)
            if parent.is_running():
                for child in parent.children(recursive=True):
                    owned[child.pid] = child.create_time()
            report["privateUiAutomation"] = private.private_uia_probe(
                desktop, set(owned), work, env)
            # Isolated CDP automation is attached exclusively to this process's
            # WebView debug port. It has no desktop mouse or keyboard operations.
            if report["webViewDiagnosticsBeforeCDP"]["cdpPortListening"]:
                try:
                    result = subprocess.run(
                        ["node", "-e", CDP_JS, str(port), str(PLAYWRIGHT), str(ui_file)],
                        cwd=work, env=env, timeout=104, capture_output=True,
                        text=True, errors="replace")
                    report["webviewHarnessExitCode"] = result.returncode
                except subprocess.TimeoutExpired:
                    report["webviewHarnessExitCode"] = "TIMEOUT"
            else:
                report["webviewHarnessExitCode"] = "NOT_RUN_DEBUG_PORT_ABSENT"
                report["screens"] = {
                    "status": "NOT_EXECUTED_CDP_PORT_UNAVAILABLE",
                    "orderScreen": False, "invoiceBeginnerScreen": False,
                    "printDesignerScreen": False,
                    "hostApiExecutionTested": False, "modelInferenceTested": False,
                    "financeActionAttempted": False,
                    "reason": "WEBVIEW2_REMOTE_DEBUG_FLAG_ABSENT",
                }
            if native_status.is_file():
                data = json.loads(native_status.read_text(encoding="utf-8"))
                report["nativeWebViewLoaded"] = data.get("loaded") is True
                report["accountingBridgePresent"] = data.get("accountingBridge") == "function"
            if ui_file.is_file():
                report["screens"] = json.loads(ui_file.read_text(encoding="utf-8"))
            report["webViewDiagnosticsAfterCDP"] = private.safe_webview_diagnostics(root_pid, port)
            if parent.is_running():
                for child in parent.children(recursive=True):
                    owned[child.pid] = child.create_time()
            report["ownedPrivateWindowSeen"] = bool(desktop.owned_windows(set(owned)))
    except Exception as exc:
        report["status"] = "FAILED_OR_BLOCKED"
        report["errorType"] = type(exc).__name__
        report["error"] = str(exc)[:180]
    finally:
        if root_pid:
            # Track only this exact spawned EXE and its children.
            try:
                import psutil
                root = psutil.Process(root_pid)
                if Path(root.exe()).resolve() == EXE.resolve():
                    owned[root_pid] = root.create_time()
                    for child in root.children(recursive=True):
                        owned[child.pid] = child.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            import psutil
            kill = []
            for pid, start in owned.items():
                try:
                    item = psutil.Process(pid)
                    if item.create_time() == start:
                        kill.append(item)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            for item in reversed(kill):
                try:
                    item.kill()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(kill, timeout=8)
            report["ownedProcessesRemaining"] = len(alive)
        except Exception as exc:
            report["cleanupErrorType"] = type(exc).__name__
        for handle in (h_process, h_thread):
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
        report["oldTarazProcessesPreserved"] = all(
            processes().get(pid) == started for pid, started in before.items())
        report["installedBaselinePreserved"] = (
            builder.installed_baseline() == originally_installed)
        report["qaLedgerBytesUnchanged"] = bool(
            ledger and ledger.is_file() and ledger_before == hash_file(ledger))
        report["candidateExeUnchanged"] = hash_file(EXE) == EXE_SHA
        screens = report.get("screens", {})
        report["status"] = (
            "PASS_PRIVATE_NATIVE_CLARIFY_READONLY" if
            screens.get("status") == "PASS_NATIVE_CLARIFY_GUI_READONLY"
            and report.get("nativeWebViewLoaded")
            and report.get("accountingBridgePresent")
            and report.get("ownedPrivateWindowSeen")
            and report.get("ownedProcessesRemaining") == 0
            and report.get("oldTarazProcessesPreserved")
            and report.get("installedBaselinePreserved")
            and report.get("qaLedgerBytesUnchanged")
            and report.get("candidateExeUnchanged")
            else "PARTIAL_OR_FAILED_PRIVATE_NATIVE_CLARIFY")
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--static", action="store_true")
    mode.add_argument("--run-private-native", action="store_true")
    opts = parser.parse_args()
    try:
        if opts.static:
            print(json.dumps({"status": "STATIC_PIN_PASS_NOT_GUI",
                              **prereq()}, ensure_ascii=False, indent=2))
            return 0
        result = run()
        data = json.loads(result.read_text(encoding="utf-8"))
        print(json.dumps({"status": data["status"], "report": str(result),
                          "screens": data.get("screens", {}),
                          "originalProcessesIntact": data.get("oldTarazProcessesPreserved"),
                          "privateLedgerUnchanged": data.get("qaLedgerBytesUnchanged")},
                         ensure_ascii=False))
        return 0 if data["status"] == "PASS_PRIVATE_NATIVE_CLARIFY_READONLY" else 1
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "errorType": type(exc).__name__,
                          "message": str(exc)[:180]}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
