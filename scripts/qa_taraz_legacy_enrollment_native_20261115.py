"""Exact frozen Taraz.exe, real 1.0.4 clone, private native enrollment UI.

Does not pretend a Declaration occurred, type credentials or allow financial
modification. Readback is performed independently after a graceful close.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_ai_frozen_real_auth_20261114 as frozen
from scripts import qa_taraz_v103_native_gui_20261111 as native
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acl
from scripts.qa_taraz_legacy_frozen_cloned_ui_20261114 import _original_postflight
from taraz_legacy_workspace_bridge import migrate_restored_clone
from taraz_legacy_ownership_enrollment import stage_legacy_company, pending_company
from taraz_three_root_backup_20261114 import restore_three_root_backup


def _window_title(hwnd) -> str:
    window = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(wintypes.HWND(hwnd), window, len(window))
    return window.value


def run(snapshot: Path, exe: Path, exe_sha: str, source_sha: str,
        output: Path) -> dict:
    if os.name != 'nt':
        raise RuntimeError('Native Windows enrollment UI acceptance required')
    frozen.validate_candidate(exe, exe_sha, source_sha)
    output = output.resolve()
    if not output.is_dir() or output.is_symlink():
        raise RuntimeError('Private QA parent must already exist')
    import psutil
    if any((p.info.get('name') or '').casefold() == 'taraz.exe'
           for p in psutil.process_iter(['name'])):
        raise RuntimeError('Another Taraz executable is running; no owned QA launch')
    work = output / ('qa-' + uuid.uuid4().hex[:12])
    acl.secure_private_directory(work)
    runtime = work / 'qa' / 'qa-runtime'
    (runtime / 'roaming').mkdir(parents=True)
    (runtime / 'localappdata').mkdir()
    roaming = runtime / 'roaming' / 'Taraz'
    local = runtime / 'localappdata' / 'Taraz'
    bridge = runtime / 'localappdata' / 'Madar-Taraz-Bridge'
    restore_three_root_backup(snapshot, roaming, local, bridge, offline_acknowledged=True)
    marker = snapshot / 'TARAZ_THREE_ROOT_MANIFEST.json'
    migrated = migrate_restored_clone(roaming, local, bridge,
                                      original_snapshot_manifest=marker)
    staged = stage_legacy_company(roaming, local, bridge,
                                  original_snapshot_manifest=marker)
    if (staged['roleGrants'] or staged['ledger']['revision'] != migrated['ledgerRevision']
            or pending_company(roaming) is None):
        raise RuntimeError('Ownerless company staging failed')
    env = native.isolated_env(runtime, {'roaming': roaming, 'local': local,
            'bridge': bridge}, work / 'native-startup.json', native.unused_port())
    outcome = {'status': 'BLOCKED', 'frozenExe': True,
               'candidateSha256': exe_sha, 'createdAdministrator': False,
               'humanDeclarationRecorded': False, 'realFinanceWrite': False,
               'nativeEnrollmentVisible': False, 'gracefulShutdown': False}
    with native.PrivateDesktop() as desktop:
        pid, handle, thread = desktop.spawn(exe, work, env)
        try:
            deadline = time.monotonic() + 24
            while time.monotonic() < deadline:
                _parent, children = frozen._owned_processes(pid, exe)
                try:
                    visible = frozen._owned_private_windows(desktop, children)
                except frozen.FrozenAuthBlocked:
                    # On a fresh non-input desktop EnumDesktopWindows can fail
                    # before Tk has created its first window. Retry boundedly.
                    time.sleep(.35)
                    continue
                if any(_window_title(hwnd) == 'تراز | تأیید یک‌باره مسئول دفتر قدیمی'
                       for hwnd in visible):
                    outcome['nativeEnrollmentVisible'] = True
                    break
                time.sleep(.35)
            if outcome['nativeEnrollmentVisible']:
                outcome['status'] = 'NATIVE_OWNERLESS_ENROLLMENT_VISIBLE'
        finally:
            try:
                outcome['close'] = frozen._graceful_close(desktop, pid, exe)
                outcome['gracefulShutdown'] = outcome['close']['graceful'] is True
            except frozen.FrozenAuthBlocked:
                outcome['close'] = {'graceful': False, 'reason': 'PRIVATE_DESKTOP_NOT_READY'}
            if not outcome['gracefulShutdown']:
                from scripts.qa_taraz_owned_private_graceful_close_20261115 import run as safe_close
                try:
                    recovery = safe_close(pid, exe, exe_sha, close=True)
                    outcome['closeRecovery'] = recovery
                    outcome['gracefulShutdown'] = recovery['gracefullyExited']
                except Exception:
                    outcome['closeRecovery'] = {'status': 'NO_GRACEFUL_RECOVERY_AVAILABLE'}
            ctypes.windll.kernel32.CloseHandle(handle)
            ctypes.windll.kernel32.CloseHandle(thread)
    outcome['postflight'] = (_original_postflight(snapshot, [roaming, local, bridge])
                             if outcome['gracefulShutdown'] else None)
    after = pending_company(roaming)
    if (after is None or outcome['postflight'] is None or
            outcome['postflight']['sqlite'] != 67 or
            outcome['postflight']['otherFiles'] != 112):
        outcome['status'] = 'BLOCKED'
    with (work / 'native-enrollment-acceptance.json').open('x', encoding='utf-8') as f:
        json.dump(outcome, f, indent=2, ensure_ascii=False, sort_keys=True)
    return {'status': outcome['status'], 'nativeEnrollmentVisible':
            outcome['nativeEnrollmentVisible'], 'gracefulShutdown':
            outcome['gracefulShutdown'], 'postflight': outcome['postflight'],
            'work': str(work)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--exe-sha', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.snapshot, args.exe, args.exe_sha,
                         args.source_sha, args.output), ensure_ascii=False))
