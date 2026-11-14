"""Frozen EXE UI acceptance on a verified, separately restored real-data clone.

READ-ONLY for financial records. No live APPDATA usage, real registration,
native login bypass, posting, installed executable or forced process shutdown.
The unclaimed historical book is deliberately a *viewer*, not an admin.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import qa_taraz_ai_frozen_real_auth_20261114 as frozen
from scripts import qa_taraz_v103_native_gui_20261111 as native
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acl
from scripts.qa_taraz_legacy_real_clone_20261114 import _book
from scripts.qa_taraz_legacy_frozen_postflight_20261114 import _sqlite_rows
from taraz_desktop import private_qa_cdp_port
from taraz_legacy_workspace_bridge import migrate_restored_clone
from taraz_three_root_backup_20261114 import restore_three_root_backup


SCRIPT = r'''"use strict";
const fs=require('node:fs');
const {chromium}=require(process.argv[3]);
const port=Number(process.argv[2]),dest=process.argv[4],phase=process.argv[5];
const result={phase,status:'BLOCKED',frozenExe:true,sourceHosted:false,
 actualUiReadback:false,accountingReadOnly:false,ordersOpened:false,
 aiOpened:false,chatRecovered:false,revisionMatched:false};
let browser;
const assert=(v,code)=>{if(!v)throw Error(code);};
async function main(){
 browser=await chromium.connectOverCDP('http://127.0.0.1:'+port,{timeout:10000});
 assert(browser.contexts().length===1,'CONTEXT_AMBIGUOUS');
 const pages=browser.contexts()[0].pages().filter(p=>{
   try{let u=new URL(p.url());return u.hostname==='127.0.0.1' &&
     u.pathname==='/accounting.html';}catch{return false;}
 });
 assert(pages.length===1,'PAGE_AMBIGUOUS');
 const page=pages[0];
 await page.locator('.sac-root').waitFor({state:'visible',timeout:20000});
 assert((await page.title()).includes('تراز'),'APP_BRANDING');
 const before=await page.evaluate(()=>window.madar.standaloneAccountingRead());
 assert(before.revision===609,'LEGACY_REVISION_MISMATCH');
 assert(before.currentUser?.role==='viewer' &&
   before.capabilities?.canManage===false &&
   before.capabilities?.canDraft===false &&
   before.view?.legacyWorkspaceState?.identityStatus==='identity_pending',
   'UNCLAIMED_ACL_NOT_ENFORCED');
 result.revisionMatched=true;result.accountingReadOnly=true;
 const orders=page.locator('[data-accounting-tab="orders"]');
 assert(await orders.count()===1,'ORDERS_NAV_AMBIGUOUS');
 await orders.click();
 await page.locator('.taraz-orders').waitFor({state:'visible',timeout:16000});
 result.ordersOpened=true;
 const ai=page.locator('[data-accounting-tab="ai"]');
 assert(await ai.count()===1,'AI_NAV_AMBIGUOUS');
 await ai.click();
 const chat=page.locator('.taraz-ai-chat');
 await chat.waitFor({state:'visible',timeout:16000});
 result.aiOpened=true;
 if(phase==='create'){
   await chat.getByRole('button',{name:'گفتگوی جدید',exact:true}).click();
   const textarea=chat.locator('.taraz-ai-compose textarea');
   await textarea.waitFor({state:'visible',timeout:15000});
   await textarea.fill('سلام. این گفت‌وگو فقط آزمایش محلی است.');
   await chat.getByRole('button',{name:'ثبت درخواست و تهیه پیشنهاد',exact:true}).click();
   await page.waitForFunction(async()=>{
     const v=await window.madar.tarazAiChatList('');
     return Array.isArray(v?.conversations) && v.conversations.length>0;
   },undefined,{timeout:20000});
 }else{
   const entries=chat.locator('.taraz-ai-conversation-list button');
   await entries.first().waitFor({state:'visible',timeout:18000});
   await entries.first().click();
   await chat.locator('.taraz-ai-messages article').first().waitFor({state:'visible',timeout:15000});
   result.chatRecovered=true;
 }
 const after=await page.evaluate(()=>window.madar.standaloneAccountingRead());
 assert(after.revision===609 && after.capabilities?.canManage===false,
   'FINANCIAL_LEDGER_CHANGED');
 const provider=await page.evaluate(()=>window.madar.tarazAiProviderStatus());
 result.providerMode=String(provider?.mode||'unknown');
 result.actualUiReadback=true;
 result.status='PASS_FROZEN_LEGACY_VIEWER_UI';
}
main().catch(e=>{result.errorCode=String(e?.message||e).slice(0,96);process.exitCode=1;})
 .finally(async()=>{
   if(browser)try{await browser.close()}catch{}
   fs.writeFileSync(dest,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
 });
'''


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _original_postflight(snapshot: Path, roots: list[Path]) -> dict:
    """All original snapshot members, by exact role, after the frozen EXE exits."""
    document = json.loads((snapshot / 'TARAZ_THREE_ROOT_MANIFEST.json').read_text(
        encoding='utf-8'))
    matched_dbs = matched_other = rows = tables = 0
    for role, root in zip(('roaming_taraz', 'local_taraz', 'local_bridge'), roots):
        for entry in document['roots'][role]['files']:
            source = snapshot / role / entry['path']
            copied = root / entry['path']
            if not copied.is_file() or copied.is_symlink():
                raise RuntimeError('Original snapshot member missing after frozen launch')
            if entry['kind'] in ('sqlite', 'sqlite-archive'):
                original, restored = _sqlite_rows(source), _sqlite_rows(copied)
                if original != restored:
                    raise RuntimeError('Frozen launch changed original database records')
                matched_dbs += 1
                tables += original[1]
                rows += original[2]
            else:
                if _sha(copied) != entry['sha256']:
                    raise RuntimeError('Frozen launch changed original non-SQLite member')
                matched_other += 1
    return {'status': 'ORIGINAL_104_DATA_PRESERVED', 'sqlite': matched_dbs,
            'otherFiles': matched_other, 'tables': tables, 'rows': rows}


def run(snapshot: Path, exe: Path, exe_sha: str, source_sha: str, output: Path):
    if os.name != 'nt':
        raise RuntimeError('Frozen private Windows execution required')
    snapshot, exe, output = snapshot.resolve(), exe.resolve(), output.resolve()
    frozen.validate_candidate(exe, exe_sha, source_sha)
    if not output.is_dir() or output.is_symlink():
        raise RuntimeError('Existing isolated output directory required')
    frozen._resources_available(output)
    import psutil
    before_pids = {p.pid for p in psutil.process_iter(['name'])
                   if (p.info.get('name') or '').casefold() == 'taraz.exe'}
    if before_pids:
        raise RuntimeError('Unrelated Taraz executable active; frozen run refused')
    work = output / ('qa-' + uuid.uuid4().hex[:12])
    acl.secure_private_directory(work)
    runtime = work / 'qa' / 'qa-runtime'
    (runtime / 'roaming').mkdir(parents=True)
    (runtime / 'localappdata').mkdir()
    roots = [runtime / 'roaming' / 'Taraz', runtime / 'localappdata' / 'Taraz',
             runtime / 'localappdata' / 'Madar-Taraz-Bridge']
    restored = restore_three_root_backup(snapshot, *roots, offline_acknowledged=True)
    migrated = migrate_restored_clone(*roots,
        original_snapshot_manifest=snapshot / 'TARAZ_THREE_ROOT_MANIFEST.json')
    before = _book(snapshot / 'roaming_taraz' / 'standalone-accounting.sqlite3')
    if before != _book(roots[0] / 'standalone-accounting.sqlite3'):
        raise RuntimeError('Financial clone differs before frozen startup')
    with (roots[0] / '.taraz-private-cdp-qa.json').open('x', encoding='utf-8') as out:
        json.dump({'privateQaOnly': True, 'profile': str(roots[0].resolve())}, out)
    node = shutil.which('node')
    playwright = PROJECT / 'node_modules' / 'playwright'
    if not node or not playwright.is_dir():
        raise RuntimeError('Local Playwright/node unavailable')
    runner = work / 'frozen-legacy-ui.cjs'
    runner.write_text(SCRIPT, encoding='utf-8')
    outcomes = []
    for phase in ('create', 'reopen'):
        port = native.unused_port()
        env = native.isolated_env(runtime, {
            'roaming': roots[0], 'local': roots[1], 'bridge': roots[2]},
            work / ('native-' + phase + '.json'), port)
        env['TARAZ_QA_CDP_PORT'] = str(port)
        if private_qa_cdp_port(roots[0], env) != port:
            raise RuntimeError('Private-only CDP not authorized by source')
        if _sha(exe) != exe_sha:
            raise RuntimeError('Frozen binary changed')
        phase_result = {'phase': phase, 'status': 'BLOCKED',
                        'gracefulShutdown': False, 'ownedCdp': False}
        with native.PrivateDesktop() as desktop:
            pid, handle, thread = desktop.spawn(exe, work, env)
            try:
                phase_result['ownedCdpProof'] = frozen._confirmed_private_cdp(pid, exe, port)
                phase_result['ownedCdp'] = True
                result = work / ('ui-' + phase + '.json')
                run_js = subprocess.run([node, str(runner), str(port), str(playwright),
                    str(result), phase], cwd=work, env=env,
                    capture_output=True, timeout=90, check=False)
                if not result.is_file():
                    raise RuntimeError('Private CDP UI report absent')
                report = json.loads(result.read_text(encoding='utf-8'))
                phase_result['ui'] = report
                if run_js.returncode or report.get('status') != 'PASS_FROZEN_LEGACY_VIEWER_UI':
                    raise RuntimeError('Private frozen UI acceptance blocked')
                phase_result['status'] = 'PASS_FROZEN_LEGACY_VIEWER_UI'
            except Exception as exc:
                phase_result['errorKind'] = type(exc).__name__
                # Deliberately do not report exceptions containing private profile paths.
                phase_result['errorCode'] = (
                    str(exc)[:100] if isinstance(exc, frozen.FrozenAuthBlocked)
                    else 'PRIVATE_QA_FAILURE')
                try:
                    # Boolean-only WebView child flags; no credentials or paths.
                    phase_result['webviewDiagnostics'] = native.safe_webview_diagnostics(
                        pid, port)
                except Exception:
                    phase_result['webviewDiagnostics'] = {'status': 'UNAVAILABLE'}
            finally:
                phase_result['close'] = frozen._graceful_close(desktop, pid, exe)
                phase_result['gracefulShutdown'] = phase_result['close']['graceful']
                ctypes.windll.kernel32.CloseHandle(handle)
                ctypes.windll.kernel32.CloseHandle(thread)
        outcomes.append(phase_result)
        if phase_result['status'] != 'PASS_FROZEN_LEGACY_VIEWER_UI' or not phase_result['gracefulShutdown']:
            break
        if _book(roots[0] / 'standalone-accounting.sqlite3') != before:
            raise RuntimeError('Clone ledger mutated after frozen read-only session')
    status = 'PASS' if len(outcomes) == 2 and all(
        x['status'] == 'PASS_FROZEN_LEGACY_VIEWER_UI' and x['gracefulShutdown']
        for x in outcomes) else 'BLOCKED'
    postflight = None
    if outcomes and all(x['gracefulShutdown'] for x in outcomes):
        try:
            postflight = _original_postflight(snapshot, roots)
        except Exception as exc:
            status = 'BLOCKED'
            postflight = {'status': 'BLOCKED', 'errorKind': type(exc).__name__}
    result = {'status': status, 'frozenExeSha256': exe_sha, 'sourceSha256': source_sha,
              'cloneDirectory': str(work), 'legacyWorkspaceId': migrated['workspaceId'],
              'originalSQLiteRestored': restored['sqlite'],
              'originalFileRestored': restored['files'], 'sessions': outcomes,
              'postflight': postflight, 'installedAppChanged': False,
              'newCompanyOwnerVerified': False, 'financialWriteExecuted': False,
              'full104UpgradeAccepted': False, 'installerRollbackAccepted': False}
    with (work / 'frozen-legacy-acceptance.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--exe-sha', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    doc = run(args.snapshot, args.exe, args.exe_sha, args.source_sha, args.output)
    print(json.dumps({'status': doc['status'],
                      'sessions': [{'phase': x['phase'], 'status': x['status'],
                                    'gracefulShutdown': x['gracefulShutdown'],
                                    'errorKind': x.get('errorKind')}
                                   for x in doc['sessions']],
                      'originalSQLiteRestored': doc['originalSQLiteRestored'],
                      'cloneDirectory': doc['cloneDirectory']}, ensure_ascii=False))
