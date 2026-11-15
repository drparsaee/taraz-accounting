"""Exact v1.0.6 PowerShell installer and rollback on a private 1.0.4 clone.

This is NOT a production installation. The package has an explicit rehearsal
guard and *permanently blocks production Apply* until independent release gates
exist. This harness tests the same emitted install/activate/rollback scripts.
"""
from __future__ import annotations

import argparse
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
from scripts.qa_taraz_legacy_frozen_cloned_ui_20261114 import _original_postflight
from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import secure_private_directory
from scripts.build_taraz_v106_aaas_20261111 import installed_baseline, BASE_POINTER_SHA
from taraz_three_root_backup_20261114 import restore_three_root_backup
from taraz_legacy_workspace_bridge import migrate_restored_clone
from taraz_legacy_ownership_enrollment import stage_legacy_company


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ps(script: Path, environment: dict, *args: str) -> dict:
    executable = Path(os.environ['SystemRoot']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    invocation = [str(executable), '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                  'Bypass', '-File', str(script), *args]
    result = subprocess.run(invocation, env=environment, check=False,
                            capture_output=True, timeout=65)
    return {'exit': result.returncode,
            # Never publish stdout/stderr: may contain physical names or private paths.
            'accepted': result.returncode == 0}


def run(snapshot: Path, build: Path, output: Path) -> dict:
    if os.name != 'nt':
        raise RuntimeError('Windows isolated installer rehearsal required')
    snapshot, build, output = snapshot.resolve(), build.resolve(), output.resolve()
    package = build / 'offline-update'
    manifest = json.loads((package / 'update-manifest.json').read_text(encoding='utf-8'))
    exe = package / 'Taraz.exe'
    if (manifest.get('targetVersion') != '1.0.6' or
            manifest.get('installApplyAllowed') is not False or
            manifest.get('activateApplyAllowed') is not False or
            manifest.get('exeSha256') != _sha(exe)):
        raise RuntimeError('Package is not pinned and production-blocked')
    if not output.is_dir() or output.is_symlink():
        raise RuntimeError('Private QA output parent required')
    if any((p.info.get('name') or '').casefold() == 'taraz.exe' for p in
           __import__('psutil').process_iter(['name'])):
        raise RuntimeError('Taraz process is active, no installer rehearsal')
    baseline = installed_baseline()
    work = output / ('qa-' + uuid.uuid4().hex[:12])
    secure_private_directory(work)
    runtime = work / 'qa' / 'qa-runtime'
    (runtime / 'roaming').mkdir(parents=True)
    (runtime / 'localappdata').mkdir()
    roaming = runtime / 'roaming' / 'Taraz'
    local = runtime / 'localappdata' / 'Taraz'
    bridge = runtime / 'localappdata' / 'Madar-Taraz-Bridge'
    restore_three_root_backup(snapshot, roaming, local, bridge, offline_acknowledged=True)
    before = _original_postflight(snapshot, [roaming, local, bridge])
    if before['sqlite'] != 67 or before['otherFiles'] != 112:
        raise RuntimeError('Original real-data clone verification failed')
    marker = snapshot / 'TARAZ_THREE_ROOT_MANIFEST.json'
    migrated = migrate_restored_clone(roaming, local, bridge,
                                      original_snapshot_manifest=marker)
    staged = stage_legacy_company(roaming, local, bridge,
                                  original_snapshot_manifest=marker)
    if migrated['ledgerRevision'] != 609 or staged['ledger']['eventCount'] != 609:
        raise RuntimeError('Legacy book staging lost immutable history')

    target = runtime / 'localappdata' / 'Programs' / 'Taraz'
    old = target / 'versions' / '1.0.4' / 'Taraz.exe'
    old.parent.mkdir(parents=True, exist_ok=False)
    active_install = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'Taraz'
    with (active_install / 'versions' / '1.0.4' / 'Taraz.exe').open('rb') as source, old.open('xb') as dest:
        shutil.copyfileobj(source, dest)
    for name in ('current-version.txt', 'Run-Taraz.cmd'):
        shutil.copyfile(active_install / name, target / name)
    if (_sha(old) != baseline['exeSha256'] or
            _sha(target / 'current-version.txt') != BASE_POINTER_SHA):
        raise RuntimeError('Private 1.0.4 install baseline differs')

    env = dict(os.environ)
    env['LOCALAPPDATA'] = str(runtime / 'localappdata')
    env['TARAZ_QA_MODE'] = '1'
    env['TARAZ_QA_ROOT'] = str(work)
    scripts = {action: package / name for action, name in {
        'install': 'Install-Taraz-V106.ps1',
        'activate': 'Activate-Taraz-V106.ps1',
        'rollback': 'Rollback-Taraz-V106.ps1'}.items()}

    # Protection test: -Apply ALONE MUST be rejected even with an isolated env.
    denied = _ps(scripts['install'], env, '-Apply')
    if denied['accepted'] or (target / 'versions' / '1.0.6').exists():
        raise RuntimeError('Production Apply guard unexpectedly bypassed')

    install = _ps(scripts['install'], env, '-Apply', '-Rehearsal')
    new = target / 'versions' / '1.0.6' / 'Taraz.exe'
    if (not install['accepted'] or not new.is_file() or
            _sha(new) != manifest['exeSha256'] or
            _sha(target / 'current-version.txt') != BASE_POINTER_SHA):
        raise RuntimeError('Rehearsal installer failed exact EXE/parity gate')

    # Interrupted install before activation: v1.0.4 remains active.
    interrupted = _ps(scripts['rollback'], env, '-Apply', '-Rehearsal')
    if not interrupted['accepted'] or _sha(target / 'current-version.txt') != BASE_POINTER_SHA:
        raise RuntimeError('Interrupted pre-activation rollback not recoverable')

    activation = _ps(scripts['activate'], env, '-Apply', '-Rehearsal')
    if not activation['accepted'] or (target / 'current-version.txt').read_text(
            encoding='utf-8-sig').strip() != '1.0.6':
        raise RuntimeError('Private 1.0.6 activation failed')

    rollback = _ps(scripts['rollback'], env, '-Apply', '-Rehearsal')
    if (not rollback['accepted'] or _sha(target / 'current-version.txt') != BASE_POINTER_SHA or
            _sha(old) != baseline['exeSha256']):
        raise RuntimeError('Private executable/pointer rollback failed')

    # Back out the cloned v1.0.6 data migration using independently restored
    # directories. Never delete old/migrated data, retain it for inspection.
    replacements = []
    for role, existing in (('roaming_taraz', roaming), ('local_taraz', local),
                           ('local_bridge', bridge)):
        substitute = existing.parent / (existing.name + '-rollback-new')
        replacements.append(substitute)
    restore_three_root_backup(snapshot, *replacements, offline_acknowledged=True)
    _original_postflight(snapshot, replacements)
    old_profiles = []
    for original, replacement in zip((roaming, local, bridge), replacements):
        retirement = original.parent / (original.name + '-upgraded-retained')
        if retirement.exists():
            raise RuntimeError('Existing upgraded retirement path refused')
        original.rename(retirement)
        old_profiles.append(retirement)
        replacement.rename(original)
    after = _original_postflight(snapshot, [roaming, local, bridge])
    if before != after or (roaming / 'companies.json').exists():
        raise RuntimeError('Post-rollback financial profile differs from 1.0.4')

    result = {'status': 'PRIVATE_REAL_CLONE_INSTALL_ACTIVATE_ROLLBACK_PASS',
              'actualInstalledVersionUntouched': True,
              'private1_0_4ExeSha256': baseline['exeSha256'],
              'private1_0_6ExeSha256': _sha(new),
              'privatePointerAfterRollback': '1.0.4',
              'originalSourceFilesVerifiedAfterRollback': after,
              'productionApplyRejected': True,
              'interruptBeforeActivationRecoverable': True,
              'fullDataOriginalRestored': True,
              'upgradedCloneRetained': True,
              'crossRootRestoreAtomic': False,
              'enrollmentHumanDeclarationPerformed': False,
              'realProductionInstallationExecuted': False,
              'work': str(work)}
    with (work / 'installer-clone-verification.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.snapshot, args.build, args.output), sort_keys=True))
