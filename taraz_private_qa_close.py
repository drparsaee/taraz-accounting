"""Bounded private-QA close request routed through the real native close gate.

No financial gate bypass. A test harness can request the same window.destroy()
that the application's native close path already uses, but only on a strictly
isolated fresh QA Windows profile. No remote channel or production setting.
"""
from __future__ import annotations

import json
import os
import hashlib
from pathlib import Path
import secrets
from threading import Thread
import time


def _atomic_new(path: Path, payload: dict) -> None:
    with path.open('x', encoding='utf-8') as f:
        json.dump(payload, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())


def install_private_close_witness(window, api, data: Path, gate,
                                  *, env=None, monotonic=time.monotonic,
                                  sleep=time.sleep):
    """Install only on private qa-runtime roots; no effect in production."""
    e = os.environ if env is None else env
    destination = e.get('TARAZ_QA_CLOSE_DIR')
    if not destination:
        return False
    data = Path(data).resolve()
    folder = Path(destination)
    override = e.get('TARAZ_QA_DATA_DIR')
    if (e.get('TARAZ_QA_MODE') != '1' or not override or
            not folder.is_absolute() or not folder.is_dir() or
            folder.is_symlink() or folder.name != 'qa-close' or
            not (data == Path(override).resolve() or
                 data.parent.parent == Path(override).resolve()) or
            'qa' not in [segment.casefold() for segment in data.parts] or
            'qa-runtime' not in [segment.casefold() for segment in data.parts]):
        raise PermissionError('Private native close channel is not an isolated QA book')
    runtime = next((p for p in (data, *data.parents) if p.name == 'qa-runtime'), None)
    if runtime is None or folder.resolve() != runtime / 'qa-close':
        raise PermissionError('Private close channel outside isolated QA runtime')
    if any((folder / name).exists() for name in ('ready.json', 'request.json', 'result.json')):
        raise PermissionError('Private QA close intent must be create-only')

    def observer():
        nonce = secrets.token_hex(24)
        try:
            deadline = monotonic() + 20
            while monotonic() < deadline:
                try:
                    ready = window.evaluate_js(
                        "typeof window.__madarAccountingConfirmNativeClose === 'function'")
                except Exception:
                    ready = False
                if ready is True:
                    break
                sleep(.2)
            else:
                _atomic_new(folder / 'result.json', {'status': 'BLOCKED_JS_CLOSE_HANDLER_NOT_READY'})
                return
            # Optional real-React script, authored in repository QA and supplied
            # only to the frozen executable's isolated Windows account. It
            # interacts with actual UI/Bridge/SQLite. No source-hosted stand-in.
            ui_file = e.get('TARAZ_QA_UI_SCRIPT')
            if ui_file:
                stage = 'UI_SCRIPT_AUTHORIZATION'
                try:
                    script_path = Path(ui_file)
                    if (script_path.resolve() != runtime / 'qa-ui.js' or
                            script_path.is_symlink() or
                            not script_path.is_file() or script_path.stat().st_size > 70000 or
                            hashlib.sha256(script_path.read_bytes()).hexdigest() !=
                                e.get('TARAZ_QA_UI_SHA256')):
                        raise PermissionError('Untrusted frozen QA interaction script')
                    script = script_path.read_text(encoding='utf-8')
                    stage = 'UI_SCRIPT_EXECUTE'
                    if window.evaluate_js(script) is not True:
                        raise RuntimeError('Frozen QA UI script did not initialize')
                    deadline = monotonic() + 64
                    outcome = None
                    stage = 'UI_SCRIPT_OBSERVE'
                    while monotonic() < deadline:
                        try:
                            outcome = window.evaluate_js('window.__nativeQa||null')
                        except Exception:
                            outcome = None
                        if (type(outcome) is dict and
                                outcome.get('status') in ('PASS_WEBVIEW2_REAL_BRIDGE_DRAFT', 'FAIL')):
                            break
                        sleep(.35)
                    if type(outcome) is not dict or outcome.get('status') not in (
                            'PASS_WEBVIEW2_REAL_BRIDGE_DRAFT', 'FAIL'):
                        outcome = {'status': 'BLOCKED_UI_TEST_TIMEOUT'}
                    # Never emit private document text, paths, credentials or
                    # unbounded JS exception messages to a QA result.
                    allowed = {'status', 'revision', 'invoiceCount', 'proformaCount',
                               'journalCount', 'nativePdfBytes', 'customTemplateSaved',
                               'invoiceDraft', 'proformaDraft', 'phase',
                               'orderCount', 'orderDraft', 'orderUiVisible',
                               'aiUiVisible', 'aiHistoryCount', 'providerMode',
                               'providerAvailability', 'aiModelRan',
                               'orderFinancialEventCreated'}
                    output = {k:v for k,v in outcome.items()
                              if k in allowed and type(v) in (str, bool, int, float)}
                except Exception as exc:
                    output = {'status':'BLOCKED_UI_SCRIPT',
                              'phase':stage, 'errorKind':type(exc).__name__}
                _atomic_new(folder / 'ui-proof.json', output)
            _atomic_new(folder / 'ready.json',
                        {'version': 1, 'pid': os.getpid(), 'nonce': nonce,
                         'method': 'real-pywebview-native-close-guard'})
            deadline = monotonic() + 65
            while monotonic() < deadline:
                intent = folder / 'request.json'
                if not intent.exists():
                    sleep(.2)
                    continue
                if intent.is_symlink() or intent.stat().st_size > 512:
                    raise PermissionError('Private QA request unsafe')
                document = json.loads(intent.read_text(encoding='utf-8'))
                if document != {'version': 1, 'pid': os.getpid(),
                                'nonce': nonce, 'action': 'native-close'}:
                    raise PermissionError('Unrecognized private QA close request')
                # This does not set _approved, _switch_requested, or
                # _exit_backed_up. The JS confirmation and backup still decide.
                window.destroy()
                sleep(3)
                _atomic_new(folder / 'result.json',
                            {'status': 'NATIVE_CLOSE_REQUESTED',
                             'backupCompletedByGate': bool(getattr(api, '_exit_backed_up', False)),
                             'closeApproved': bool(getattr(gate, '_backup_accepted', False))})
                return
            _atomic_new(folder / 'result.json',
                        {'status': 'BLOCKED_NO_EXPLICIT_QA_CLOSE_REQUEST'})
        except Exception:
            # Do not serialize user data, credentials, paths or exception text.
            try:
                _atomic_new(folder / 'result.json',
                            {'status': 'BLOCKED_NATIVE_QA_CLOSE_WITNESS'})
            except OSError:
                pass

    window.events.loaded += lambda: Thread(target=observer, daemon=True).start()
    return True


def record_private_close_exit(enabled: bool, gate, *, backup_completed: bool):
    """Evidence from the real EXE just after its real close/backup cleanup."""
    if not enabled:
        return
    folder = Path(os.environ['TARAZ_QA_CLOSE_DIR'])
    report = gate.close_evidence()
    report['backupOnExitCompleted'] = backup_completed
    report['status'] = ('VERIFIED_NATIVE_CLOSE_AND_BACKUP'
                        if (backup_completed and
                            report['jsConfirmedCount'] >= 1 and
                            report['precloseBackupVerifiedCount'] >= 1 and
                            report['reentrantAcceptCount'] >= 1)
                        else 'INCOMPLETE_NATIVE_CLOSE_EVIDENCE')
    _atomic_new(folder / 'exit-proof.json', report)
