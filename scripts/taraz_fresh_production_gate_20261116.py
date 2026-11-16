"""Fresh-start Taraz production release gate, never an unlocked old installer.

All checks run before the first mutation. A production --apply is refused if
Madar, Taraz, a bridge writer, an unverified backup, or an unsafe path exists.
The legacy archive remains untouched and the previous executable is retained.

The v1.0.6 offline-update manifest intentionally has production Apply disabled.
This orchestrator does NOT edit its flags or invoke its locked scripts as if
they were authorized; it checks the pinned payload and performs a separate
explicit, rollback-journaled in-place installation only after its own gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import psutil
import shutil
import sys
from time import time_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.taraz_live_three_root_backup_20261114 import (
    source_roots,_db_rows_digest,_no_installed_taraz_process)
from taraz_three_root_backup_20261114 import (
    ROLES,_scan,_kind,_secure_digest,verify_three_root_backup)
from taraz_fresh_windows_workspace import (
    stage_new_empty_root,inspect_fresh_workspace)

BUILD = Path('D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/'
             'taraz-v1.0.6-aaas/build-5eaec2d34649')
SNAPSHOT = Path('D:/CoS-Test/TARAZ-FRESH-START-FINAL-BACKUP-20261116-A/snapshot')
VERIFICATION = SNAPSHOT.parent / 'verification.json'
CLONE_EVIDENCE = Path(
    'D:/CoS-Test/TARAZ-PRIME-CLONE-20261116/qa-2e7807644380/'
    'fresh-reset-rollback-evidence.json')
DRIVER_CLONE_EVIDENCE = Path(
    'D:/CoS-Test/TARAZ-PRIME-PROTECTED-APPLY-QA-20261116/qa-135627d8f15e/'
    'driver-clone-acceptance.json')
EXPECTED_EXE = 'd0dd7bace4039688cc18768b232bc36bccd5aa1933f4d59bcb253b352b2ac3f2'
EXPECTED_OLD = '9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce'
EXPECTED_LAUNCHER = '93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21'
EXPECTED_OLD_POINTER = 'eb8d72a2c4783965876f89d494d6ecdd3502c814e0229d50cea66eb65169856d'
RELEASE_DIR = Path('D:/CoS-Test/TARAZ-PRIME-FRESH-PRODUCTION-20261116')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_existing(path: Path, *, directory=True):
    """Reject symbolic links and NTFS reparse points anywhere on the path."""
    path = Path(path).absolute()
    for item in (path,*path.parents):
        if item.exists():
            stat=item.stat(follow_symlinks=False)
            if item.is_symlink() or stat.st_file_attributes & 0x400:
                raise PermissionError('Unexpected symlink/reparse point: '+str(item))
    if directory and not path.is_dir():
        raise FileNotFoundError(str(path))
    if not directory and not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def pinned_package():
    package = safe_existing(BUILD/'offline-update')
    manifest_path = safe_existing(package/'update-manifest.json',directory=False)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    binary = safe_existing(package/'Taraz.exe',directory=False)
    if (manifest.get('targetVersion')!='1.0.6' or
            manifest.get('exeSha256')!=EXPECTED_EXE or
            manifest.get('sourceFingerprintSha256')!=
              'f06c9727b72c54b2cbd166a60adf2b4b00ca96e58cdf73ba1085ecbe6aafb186' or
            manifest.get('qaOnly') is not False or
            # A disabled original Apply is expected, and is NOT modified.
            manifest.get('installApplyAllowed') is not False or
            manifest.get('activateApplyAllowed') is not False or
            sha(binary)!=EXPECTED_EXE):
        raise PermissionError('Unpinned or unexpectedly activated distribution')
    return binary


def baseline(install: Path):
    install=safe_existing(install)
    old=safe_existing(install/'versions'/'1.0.4'/'Taraz.exe',directory=False)
    launcher=safe_existing(install/'Run-Taraz.cmd',directory=False)
    pointer=safe_existing(install/'current-version.txt',directory=False)
    if (sha(old)!=EXPECTED_OLD or sha(launcher)!=EXPECTED_LAUNCHER or
            sha(pointer)!=EXPECTED_OLD_POINTER or
            pointer.read_text(encoding='utf-8-sig').strip()!='1.0.4'):
        raise PermissionError('Baseline 1.0.4 path or fingerprint drifted')
    if ((install/'versions'/'1.0.6').exists() or
            (install/'current-version-pre-1.0.6.txt').exists()):
        raise PermissionError('v1.0.6 already staged or activation pending')
    return pointer


def prove_snapshot_matches(roots: dict[str,Path], snapshot=SNAPSHOT):
    recovered=verify_three_root_backup(snapshot)
    if recovered['mode']!='legacy' or recovered['sqlite']!=67 or recovered['files']!=179:
        raise RuntimeError('Unexpected backup membership or mode')
    for role in ROLES:
        active=safe_existing(roots[role])
        copy=safe_existing(snapshot/role)
        ad,af,asides=_scan(active)
        bd,bf,bsides=_scan(copy)
        if ad!=bd or set(af)!=set(bf):
            raise RuntimeError('Active root has diverged from recovered backup: '+role)
        for name in af:
            a,b=active/name,copy/name
            if _kind(name)=='sqlite':
                if _db_rows_digest(a)!=_db_rows_digest(b):
                    raise RuntimeError('Live SQLite rows differ from recovery: '+role)
            elif _secure_digest(a)!=_secure_digest(b):
                raise RuntimeError('Active financial file differs from recovery: '+role)
    return recovered


def prove_clone():
    result=json.loads(safe_existing(CLONE_EVIDENCE,directory=False).read_text(encoding='utf-8'))
    if (result.get('status')!='PASS_VERIFIED_FRESH_DATA_RESET_EXE_INSTALL_AND_FULL_ROLLBACK_CLONE'
            or result.get('oldExeSha256')!=EXPECTED_OLD
            or result.get('newExeSha256')!=EXPECTED_EXE
            or result.get('newLedgerRevisionBeforeRollback')!=0
            or result.get('originalLedgerEventsRestored')!=609
            or result.get('originalStoresAfterRollback',{}).get('rows')!=25745):
        raise RuntimeError('Latest final backup clone rollback not accepted')
    verification=json.loads(safe_existing(VERIFICATION,directory=False).read_text(encoding='utf-8'))
    if (verification.get('status')!='VERIFIED_SAME_PRINCIPAL_SNAPSHOT_AND_ISOLATED_RESTORE'
            or verification.get('dpapiSamePrincipalReadback') is not True
            or verification.get('sourceWriteDenialHeldForAllDataFiles') is not True
            or verification.get('databasesWithMatchingRows')!=67
            or verification.get('totalSqlRowsCompared')!=25745):
        raise RuntimeError('Latest final backup readback not verified')
    driver=json.loads(safe_existing(DRIVER_CLONE_EVIDENCE,directory=False).read_text(encoding='utf-8'))
    if (driver.get('status')!='PASS_NEW_PRODUCTION_DRIVER_CLONE_APPLY_ROLLBACK'
            or driver.get('stagedExeSha')!=EXPECTED_EXE
            or driver.get('oldVersionRecovered')!='1.0.4'
            or driver.get('newCompanyRevision')!=0
            or driver.get('snapshotFilesRecovered')!=179
            or driver.get('productionDataTouched') is not False):
        raise RuntimeError('Production driver itself has not passed clone rollback')
    return result


def no_live_writers():
    """Don't relocate a bridge directory while its Madar owner can write."""
    _no_installed_taraz_process()
    live=[]
    for process in psutil.process_iter(['name','exe']):
        name=(process.info.get('name') or '').casefold()
        if 'madar' in name or 'taraz' in name:
            live.append({'name':name,'pid':process.pid})
    if live:
        raise RuntimeError('Madar/Taraz processes still active; normal close required: '+
                           ','.join(x['name'] for x in live))
    return True


def production_preflight():
    reasons=[]
    try:
        if os.name!='nt' or os.environ.get('TARAZ_QA_MODE'):
            raise RuntimeError('Real Windows production profile required')
        no_live_writers()
    except Exception as exc:
        reasons.append('WRITERS: '+str(exc)[:240])
    try:
        pinned_package()
        install=Path(os.environ['LOCALAPPDATA'])/'Programs'/'Taraz'
        baseline(install)
    except Exception as exc:
        reasons.append('PACKAGE_OR_BASELINE: '+str(exc)[:240])
    try:
        prove_clone()
        prove_snapshot_matches(source_roots())
    except Exception as exc:
        reasons.append('BACKUP_OR_ROLLBACK: '+str(exc)[:240])
    try:
        if RELEASE_DIR.exists() or not RELEASE_DIR.parent.is_dir():
            raise RuntimeError('Release journal path must be create-only')
        safe_existing(RELEASE_DIR.parent)
        roots=source_roots()
        for role in ROLES:
            safe_existing(roots[role])
            if (roots[role].parent/(roots[role].name+'-legacy-retained-20261116')).exists():
                raise RuntimeError('Existing release archive name collision')
    except Exception as exc:
        reasons.append('RELEASE_PATHS: '+str(exc)[:240])
    return {'status':'BLOCKED' if reasons else 'PASS_PROTECTED_PRODUCTION_PREFLIGHT',
            'issues':reasons,'sourceVersion':'1.0.4','targetVersion':'1.0.6',
            'fullCloneRollbackRequired':True,'realInstallChanged':False,
            'snapshotAtomicVssClaimed':False}


def _create_new(path: Path, payload: bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def _event(directory: Path, seq: int, payload: dict):
    """Create-only durable journal entry; no destructive rewrite/replace."""
    _create_new(directory/f'{seq:03d}.json',
                (json.dumps(payload,sort_keys=True,ensure_ascii=False)+'\n').encode('utf-8'))


def guarded_apply(roots: dict[str,Path],install: Path,journal: Path,
                  *, production: bool):
    """One in-place installation. Caller MUST have passed all preflight gates."""
    baseline(install)
    prove_snapshot_matches(roots)
    exe=pinned_package()
    if production:
        pre=production_preflight()
        if pre['status']!='PASS_PROTECTED_PRODUCTION_PREFLIGHT':
            raise PermissionError('Production release preflight invalid at commit point')
    if journal.exists() or journal.is_symlink():
        raise PermissionError('Transaction journal must be newly created')
    safe_existing(journal.parent)
    journal.mkdir()
    tag='20261116'
    archive={k:roots[k].parent/(roots[k].name+'-legacy-retained-'+tag) for k in ROLES}
    retain={k:roots[k].parent/(roots[k].name+'-new-retained-'+tag) for k in ROLES}
    if any(x.exists() or x.is_symlink() for x in [*archive.values(),*retain.values()]):
        raise PermissionError('Do not overwrite previous archived or fresh data')
    pointer=install/'current-version.txt'
    original=pointer.read_bytes()
    _create_new(journal/'pointer-104.original',original)
    _event(journal,0,{'stage':'PREPARED','production':production,
        'install':str(install),'roots':{k:str(v) for k,v in roots.items()},
        'archive':{k:str(v) for k,v in archive.items()},
        'retain':{k:str(v) for k,v in retain.items()},
        'payloadSha256':EXPECTED_EXE})
    # Each directory is atomically renamed inside its existing parent volume.
    # On a failure, the journal identifies every already renamed root.
    for n,role in enumerate(ROLES,1):
        if production: no_live_writers()
        roots[role].rename(archive[role])
        _event(journal,n,{'stage':'OLD_ROOT_ARCHIVED','role':role,
                          'archive':str(archive[role])})
    fresh=stage_new_empty_root(roots['roaming_taraz'])
    roots['local_taraz'].mkdir()
    roots['local_bridge'].mkdir()
    if fresh['ledgerRevision']!=0 or fresh['windowsPrincipalBound'] is not True:
        raise RuntimeError('Empty Windows-bound fresh book creation failed')
    _event(journal,4,{'stage':'NEW_EMPTY_BOOK','revision':0})
    version=install/'versions'/'1.0.6'
    version.mkdir()
    _create_new(version/'Taraz.exe',exe.read_bytes())
    if sha(version/'Taraz.exe')!=EXPECTED_EXE:
        raise RuntimeError('In-place executable readback hash differs')
    _event(journal,5,{'stage':'EXE_INSTALLED_NOT_ACTIVATED','sha':EXPECTED_EXE})
    pending=install/('current-version-1.0.6-new-'+tag+'.txt')
    _create_new(pending,b'1.0.6\r\n')
    if sha(pending)!='3dd81e3d2bbe930a0c98531afa6c35bd862ee8a08458ec0d7d1b51138d7b3a3c':
        raise RuntimeError('Pending activation pointer mismatch')
    if production: no_live_writers()
    os.replace(pending,pointer)
    if (pointer.read_text(encoding='utf-8-sig').strip()!='1.0.6' or
            inspect_fresh_workspace(roots['roaming_taraz'])['ledgerRevision']!=0):
        raise RuntimeError('Activated installation does not have an empty book')
    _event(journal,6,{'stage':'ACTIVATED_EMPTY_106','pointerSha256':sha(pointer)})
    return {'status':'ACTIVATED_EMPTY_106','journal':str(journal),
            'exeSha256':sha(version/'Taraz.exe'),'newLedgerRevision':0,
            'legacyDataPreserved':True}


def rollback(journal: Path):
    """Recovery of all three original roots and 1.0.4 pointer, never delete."""
    state=json.loads(safe_existing(journal/'000.json',directory=False).read_text(encoding='utf-8'))
    if state.get('stage')!='PREPARED' or state.get('payloadSha256')!=EXPECTED_EXE:
        raise PermissionError('Unrecognized rollback journal')
    install=safe_existing(Path(state['install']))
    roots={k:Path(state['roots'][k]) for k in ROLES}
    archives={k:Path(state['archive'][k]) for k in ROLES}
    retained={k:Path(state['retain'][k]) for k in ROLES}
    if any(not p.is_dir() for p in archives.values()):
        raise RuntimeError('Cannot roll back incomplete archive; inspect journal')
    if any(p.exists() for p in retained.values()):
        raise RuntimeError('Earlier rollback retained new roots; avoid overwrite')
    if any(not p.is_dir() for p in roots.values()):
        raise RuntimeError('Missing active root; must recover incomplete install separately')
    pointer=install/'current-version.txt'
    if pointer.read_text(encoding='utf-8-sig').strip() not in ('1.0.4','1.0.6'):
        raise PermissionError('Unknown installed version; refuse rollback')
    for role in ROLES:
        roots[role].rename(retained[role])
        archives[role].rename(roots[role])
    original=safe_existing(journal/'pointer-104.original',directory=False).read_bytes()
    if hashlib.sha256(original).hexdigest()!=EXPECTED_OLD_POINTER:
        raise RuntimeError('Rollback pointer record invalid')
    pending=install/'current-version-1.0.4-restore-20261116.txt'
    _create_new(pending,original)
    os.replace(pending,pointer)
    if sha(pointer)!=EXPECTED_OLD_POINTER:
        raise RuntimeError('Rollback 1.0.4 pointer mismatch')
    prove_snapshot_matches(roots)
    _event(journal,7,{'stage':'ROLLBACK_COMPLETE','active':'1.0.4',
                      'oldDataRestored':True,'freshDataRetained':True})
    return {'status':'PASS_ROLLBACK_TO_104_WITH_FULL_DATA','freshDataRetained':True}


def recover_incomplete(journal: Path):
    """Recover even if the install stopped between three independent renames.

    Never erase a new profile or overwrite a previous archive. If ownership of
    a path is ambiguous, fail and keep every file where it is.
    """
    state=json.loads(safe_existing(journal/'000.json',directory=False).read_text(encoding='utf-8'))
    if state.get('stage')!='PREPARED' or state.get('payloadSha256')!=EXPECTED_EXE:
        raise PermissionError('Recovery journal identity mismatch')
    install=safe_existing(Path(state['install']))
    roots={k:Path(state['roots'][k]) for k in ROLES}
    archives={k:Path(state['archive'][k]) for k in ROLES}
    retained={k:Path(state['retain'][k]) for k in ROLES}
    if (journal/'900.json').exists() or any(p.exists() for p in retained.values()):
        raise PermissionError('Release already recovered or path collision')
    # Inspect every path before the first recovery mutation.
    for k in ROLES:
        if not roots[k].exists() and not archives[k].exists():
            raise RuntimeError('Both original and archive absent for '+k)
        if roots[k].exists() and not roots[k].is_dir():
            raise RuntimeError('Active root is not a directory: '+k)
        if archives[k].exists() and not archives[k].is_dir():
            raise RuntimeError('Legacy archive is not a directory: '+k)
        for existing in (roots[k],archives[k]):
            if existing.exists(): safe_existing(existing)
    pointer=safe_existing(install/'current-version.txt',directory=False)
    if pointer.read_text(encoding='utf-8-sig').strip() not in ('1.0.4','1.0.6'):
        raise PermissionError('Unexpected version while recovering')
    for role in ROLES:
        if archives[role].exists():
            if roots[role].exists(): roots[role].rename(retained[role])
            archives[role].rename(roots[role])
    original=safe_existing(journal/'pointer-104.original',directory=False).read_bytes()
    if hashlib.sha256(original).hexdigest()!=EXPECTED_OLD_POINTER:
        raise RuntimeError('Original pointer backup changed')
    if sha(pointer)!=EXPECTED_OLD_POINTER:
        target=install/'current-version-1.0.4-recovery-20261116.txt'
        _create_new(target,original)
        os.replace(target,pointer)
    prove_snapshot_matches(roots)
    _event(journal,900,{'stage':'INCOMPLETE_INSTALL_RECOVERED_TO_104',
                         'oldDataRestored':True,'newDataRetainedIfPresent':True})
    return {'status':'PASS_RECOVERED_ORIGINAL_104_DATA','journal':str(journal)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight',action='store_true')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--rollback',action='store_true')
    a=parser.parse_args()
    if sum((a.preflight,a.apply,a.rollback))!=1:
        parser.error('Select exactly one action')
    if a.preflight:
        print(json.dumps(production_preflight(),ensure_ascii=True))
        return 0
    if a.apply:
        check=production_preflight()
        if check['status']!='PASS_PROTECTED_PRODUCTION_PREFLIGHT':
            print(json.dumps(check,ensure_ascii=True))
            return 2
        try:
            release=guarded_apply(source_roots(),
                   Path(os.environ['LOCALAPPDATA'])/'Programs'/'Taraz',
                   RELEASE_DIR,production=True)
        except BaseException:
            # Only this transaction's own create-only journal allows recovery.
            if (RELEASE_DIR/'000.json').is_file():
                no_live_writers()
                recover_incomplete(RELEASE_DIR)
            raise
        print(json.dumps(release,ensure_ascii=True))
        return 0
    no_live_writers()
    result=rollback(RELEASE_DIR)
    print(json.dumps(result,ensure_ascii=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
