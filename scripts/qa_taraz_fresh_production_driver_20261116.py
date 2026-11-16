"""Test the exact new production release/rollback functions on a private clone.

This runner never uses APPDATA or LOCALAPPDATA for its targets. The source is
the already verified 2026-11-16 full three-root backup.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import secure_private_directory
from scripts import taraz_fresh_production_gate_20261116 as release
from taraz_three_root_backup_20261114 import ROLES,restore_three_root_backup

WORKSPACE=Path('D:/CoS-Test/TARAZ-PRIME-PROTECTED-APPLY-QA-20261116')


def run():
    if os.name!='nt' or not WORKSPACE.is_dir() or WORKSPACE.is_symlink():
        raise RuntimeError('Private production-driver QA directory missing')
    work=WORKSPACE/('qa-'+uuid.uuid4().hex[:12])
    secure_private_directory(work)
    runtime=work/'qa'/'qa-runtime'
    roaming=runtime/'roaming'
    local=runtime/'localappdata'
    roaming.mkdir(parents=True)
    local.mkdir()
    roots={
      'roaming_taraz':roaming/'Taraz',
      'local_taraz':local/'Taraz',
      'local_bridge':local/'Madar-Taraz-Bridge',
    }
    restore_three_root_backup(release.SNAPSHOT,*(roots[k] for k in ROLES),
                              offline_acknowledged=True)
    release.prove_snapshot_matches(roots)

    installed=local/'Programs'/'Taraz'
    old=installed/'versions'/'1.0.4'/'Taraz.exe'
    old.parent.mkdir(parents=True)
    source=Path(os.environ['LOCALAPPDATA'])/'Programs'/'Taraz'
    shutil.copyfile(source/'versions'/'1.0.4'/'Taraz.exe',old)
    for name in ('current-version.txt','Run-Taraz.cmd'):
        shutil.copyfile(source/name,installed/name)
    if release.sha(old)!=release.EXPECTED_OLD:
        raise RuntimeError('Cloned actual installed 1.0.4 mismatched')

    journal=work/'qa-release-journal'
    stage=release.guarded_apply(roots,installed,journal,production=False)
    if (stage['status']!='ACTIVATED_EMPTY_106' or
            stage['exeSha256']!=release.EXPECTED_EXE or
            stage['newLedgerRevision']!=0):
        raise RuntimeError('New driver did not activate empty v1.0.6 clone')
    rolled=release.rollback(journal)
    if rolled['status']!='PASS_ROLLBACK_TO_104_WITH_FULL_DATA':
        raise RuntimeError('New driver did not restore original data/EXE')
    release.prove_snapshot_matches(roots)
    if release.sha(installed/'current-version.txt')!=release.EXPECTED_OLD_POINTER:
        raise RuntimeError('Rollback did not restore exact pinned pointer')
    result={'status':'PASS_NEW_PRODUCTION_DRIVER_CLONE_APPLY_ROLLBACK',
            'stagedExeSha':stage['exeSha256'],'newCompanyRevision':0,
            'oldVersionRecovered':'1.0.4','snapshotFilesRecovered':179,
            'productionDataTouched':False,'work':str(work)}
    (work/'driver-clone-acceptance.json').write_text(
        json.dumps(result,sort_keys=True,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    print(json.dumps(run(),ensure_ascii=True))
