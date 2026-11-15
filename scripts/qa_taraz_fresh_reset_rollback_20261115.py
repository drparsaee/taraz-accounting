"""Actual offline installer and full fresh-reset rollback on a verified clone.

Preserves every 1.0.4 legacy member in a separately identified archive, starts
one genuine empty Windows-bound book, installs/activates the unchanged v1.0.6
payload in a private copy of the real installation layout, and restores the
original app pointer and all three data roots from their retained clone.

NO legacy enrollment and NO migration. NO production changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_taraz_v106_aaas_20261111 import BASE_POINTER_SHA, installed_baseline
from scripts.qa_taraz_real_clone_installer_rollback_20261115 import _ps
from scripts.qa_taraz_legacy_frozen_cloned_ui_20261114 import _original_postflight
from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import secure_private_directory
from taraz_three_root_backup_20261114 import (
    restore_three_root_backup, verify_three_root_backup)
from taraz_fresh_windows_workspace import (
    stage_new_empty_root, inspect_fresh_workspace)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(snapshot: Path, build: Path, output: Path) -> dict:
    if os.name != 'nt':
        raise RuntimeError('Windows-only clone QA')
    snapshot, build, output = (Path(p).resolve() for p in
                               (snapshot, build, output))
    if not output.is_dir() or output.is_symlink():
        raise RuntimeError('Private QA output parent must already exist')
    profile = verify_three_root_backup(snapshot)
    if profile['mode'] != 'legacy' or profile['sqlite'] != 67:
        raise RuntimeError('Incorrect source snapshot for fresh reset')
    package = build / 'offline-update'
    manifest = json.loads((package / 'update-manifest.json').read_text(encoding='utf-8'))
    executable = package / 'Taraz.exe'
    if (manifest.get('targetVersion') != '1.0.6' or
            manifest.get('installApplyAllowed') is not False or
            manifest.get('activateApplyAllowed') is not False or
            manifest.get('exeSha256') != _sha(executable)):
        raise RuntimeError('Unverified non-installed offline payload')
    baseline = installed_baseline()
    work = output / ('qa-' + uuid.uuid4().hex[:12])
    secure_private_directory(work)
    runtime = work / 'qa' / 'qa-runtime'
    (runtime / 'roaming').mkdir(parents=True)
    (runtime / 'localappdata').mkdir()
    paths = {
        'roaming_taraz': runtime / 'roaming' / 'Taraz',
        'local_taraz': runtime / 'localappdata' / 'Taraz',
        'local_bridge': runtime / 'localappdata' / 'Madar-Taraz-Bridge',
    }
    originals = list(paths.values())
    restore_three_root_backup(snapshot, *originals, offline_acknowledged=True)
    before = _original_postflight(snapshot, originals)
    if (before['sqlite'] != 67 or before['otherFiles'] != 112 or
            before['rows'] != 25745):
        raise RuntimeError('Restored legacy accounting history is not intact')

    archive_dir = work / 'old-data-retained'
    archive_dir.mkdir()
    archives = []
    for role, original in paths.items():
        archived = archive_dir / role
        original.rename(archived)
        archives.append(archived)
    if _original_postflight(snapshot, archives) != before:
        raise RuntimeError('Retained 1.0.4 archive changed during relocation')
    fresh = stage_new_empty_root(paths['roaming_taraz'])
    paths['local_taraz'].mkdir()
    paths['local_bridge'].mkdir()
    if (fresh['ledgerRevision'] != 0 or not fresh['windowsPrincipalBound'] or
            (paths['roaming_taraz'] / 'legacy-workspace.json').exists()):
        raise RuntimeError('New account inherited old ledger or legacy identity')
    if any(any(paths[key].iterdir()) for key in ('local_taraz', 'local_bridge')):
        raise RuntimeError('Fresh companion root unexpectedly contains old entries')

    install = runtime / 'localappdata' / 'Programs' / 'Taraz'
    old = install / 'versions' / '1.0.4' / 'Taraz.exe'
    old.parent.mkdir(parents=True)
    original_install = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'Taraz'
    with (original_install / 'versions' / '1.0.4' / 'Taraz.exe').open('rb') as src:
        with old.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    for member in ('current-version.txt', 'Run-Taraz.cmd'):
        shutil.copyfile(original_install / member, install / member)
    if (_sha(old) != baseline['exeSha256'] or
            _sha(install / 'current-version.txt') != BASE_POINTER_SHA):
        raise RuntimeError('Local 1.0.4 install clone does not match')
    env = dict(os.environ)
    env.update({'LOCALAPPDATA':str(runtime / 'localappdata'),
                'TARAZ_QA_MODE':'1','TARAZ_QA_ROOT':str(work)})
    install_script = package / 'Install-Taraz-V106.ps1'
    activate_script = package / 'Activate-Taraz-V106.ps1'
    rollback_script = package / 'Rollback-Taraz-V106.ps1'
    if _ps(install_script, env, '-Apply')['accepted']:
        raise RuntimeError('Production Apply bypass unexpectedly allowed')
    if not _ps(install_script, env, '-Apply', '-Rehearsal')['accepted']:
        raise RuntimeError('Actual installer refused verified isolated 1.0.4')
    future = install / 'versions' / '1.0.6' / 'Taraz.exe'
    if _sha(future) != manifest['exeSha256']:
        raise RuntimeError('Actual package EXE does not match installed payload')
    if not _ps(activate_script, env, '-Apply', '-Rehearsal')['accepted']:
        raise RuntimeError('Actual activation failed on restored 1.0.4')
    if (install / 'current-version.txt').read_text(encoding='utf-8-sig').strip() != '1.0.6':
        raise RuntimeError('Clone did not activate 1.0.6')
    if inspect_fresh_workspace(paths['roaming_taraz'])['ledgerRevision'] != 0:
        raise RuntimeError('Clone activation unexpectedly imported old data')
    if not _ps(rollback_script, env, '-Apply', '-Rehearsal')['accepted']:
        raise RuntimeError('Actual rollback script failed')
    if (_sha(install / 'current-version.txt') != BASE_POINTER_SHA or
            _sha(old) != baseline['exeSha256']):
        raise RuntimeError('Clone old EXE or old pointer not restored')

    preserved_new = work / 'new-empty-data-retained'
    preserved_new.mkdir()
    for role, original in paths.items():
        original.rename(preserved_new / role)
    for role, original in paths.items():
        (archive_dir / role).rename(original)
    after = _original_postflight(snapshot, originals)
    if after != before or (paths['roaming_taraz'] / 'companies.json').exists():
        raise RuntimeError('Original data roots failed independent rollback proof')

    result = {'status':'PASS_VERIFIED_FRESH_DATA_RESET_EXE_INSTALL_AND_FULL_ROLLBACK_CLONE',
              'actualLiveDataChanged':False,'originalLedgerEventsRestored':609,
              'originalStoresAfterRollback':after,
              'retainedNewEmptyDataForReview':True,
              'newCompanyWindowsBound':True,'newLedgerRevisionBeforeRollback':0,
              'noLegacyMigrationOrEnrollment':True,
              'productionInstallerApplyRemainsLocked':True,
              'oldExeSha256':baseline['exeSha256'],
              'newExeSha256':manifest['exeSha256'],
              'activeCloneVersionAfterRollback':'1.0.4',
              'work':str(work)}
    with (work / 'fresh-reset-rollback-evidence.json').open('x', encoding='utf-8') as f:
        json.dump(result, f, sort_keys=True, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    a = parser.parse_args()
    print(json.dumps(run(a.snapshot, a.build, a.output), ensure_ascii=False))
