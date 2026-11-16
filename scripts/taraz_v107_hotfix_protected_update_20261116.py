from __future__ import annotations
import argparse,hashlib,json,os,psutil,uuid
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import taraz_live_three_root_backup_v106_20261116 as backup
from taraz_three_root_backup_20261114 import ROLES,_scan,_secure_digest,verify_three_root_backup

BUILD=Path('D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261116/taraz-v1.0.7-hotfix/build-46580a06da05')
PACKAGE=BUILD/'offline-update';EXE=BUILD/'binary'/'Taraz.exe'
# The original A destination contains immutable evidence of a preflight failure.
# Never overwrite it; the verified post-recovery snapshot uses a fresh folder.
BACKUP=Path('D:/CoS-Test/TARAZ-V107-HOTFIX-BACKUP-20261116-B')
JOURNAL=Path('D:/CoS-Test/TARAZ-V107-HOTFIX-PRODUCTION-20261116-A')
BASE_VERSION='1.0.6';TARGET_VERSION='1.0.7'
BASE_EXE_SHA='d0dd7bace4039688cc18768b232bc36bccd5aa1933f4d59bcb253b352b2ac3f2'
BASE_POINTER_SHA='3dd81e3d2bbe930a0c98531afa6c35bd862ee8a08458ec0d7d1b51138d7b3a3c'
LAUNCHER_SHA='93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21'
TARGET_EXE_SHA='83a47d228d111b7ac8c4eff73ce0948a8b8517ae5e95bf0646bb5969fed0ba9b'
TARGET_POINTER_SHA=hashlib.sha256(b'1.0.7\r\n').hexdigest()
POINTER_BACKUP='current-version-pre-1.0.7.txt'
PENDING='current-version-1.0.7-pending.txt'

class ReleaseBlocked(RuntimeError):pass
def sha_bytes(data):return hashlib.sha256(data).hexdigest()
def sha(path):return sha_bytes(Path(path).read_bytes())
def safe(path,*,directory=True,exists=True):
 p=Path(path).absolute()
 for item in (p,*p.parents):
  if item.exists():
   st=item.stat(follow_symlinks=False)
   if item.is_symlink() or (st.st_file_attributes&0x400):
    raise ReleaseBlocked('Symlink/reparse point refused: '+str(item))
 if exists and directory and not p.is_dir():raise FileNotFoundError(str(p))
 if exists and not directory and not p.is_file():raise FileNotFoundError(str(p))
 if not exists and os.path.lexists(p):raise FileExistsError(str(p))
 return p
def create_new(path:Path,payload:bytes):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('xb') as out:
  out.write(payload);out.flush();os.fsync(out.fileno())
def event(folder:Path,seq:int,payload:dict):
 create_new(folder/f'{seq:03d}.json',(json.dumps(payload,sort_keys=True,ensure_ascii=False)+'\n').encode('utf-8'))
def no_live_writers():
 backup._no_installed_taraz_process()
 return True
def installed_paths():
 app=Path(os.environ['LOCALAPPDATA'])/'Programs'/'Taraz'
 return app,app/'current-version.txt',app/'Run-Taraz.cmd',app/'versions'/'1.0.6'/'Taraz.exe'
def pinned_package():
 safe(EXE,directory=False);safe(PACKAGE)
 manifest_path=safe(PACKAGE/'update-manifest.json',directory=False)
 manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
 report=json.loads((BUILD/'build-report.json').read_text(encoding='utf-8'))
 if (manifest.get('targetVersion')!=TARGET_VERSION or manifest.get('exeSha256')!=TARGET_EXE_SHA or
  manifest.get('installedBaselineVersion')!=BASE_VERSION or
  manifest.get('installedBaselineSha256')!=BASE_EXE_SHA or
  manifest.get('qaOnly') is not False or manifest.get('installApplyAllowed') is not False or
  manifest.get('activateApplyAllowed') is not False or sha(EXE)!=TARGET_EXE_SHA or
  report.get('status')!='V107_AAAS_NON_QA_BUILT_NOT_INSTALLED' or
  report.get('sourceFreezeSha256')!='30ce5e8418c385f3f89ed77ef679101400643b8ec950190fd8d0eb6d3d211722' or
  report.get('compiled',{}).get('qaOnly') is not False or
  report.get('compiled',{}).get('compiledByteParity') is not True):
  raise ReleaseBlocked('Candidate/manifest/source/build evidence pin mismatch')
 return manifest
def baseline():
 app,pointer,launcher,old=installed_paths()
 safe(app);safe(pointer,directory=False);safe(launcher,directory=False);safe(old,directory=False)
 if (pointer.read_text(encoding='utf-8-sig').strip()!=BASE_VERSION or
  sha(pointer)!=BASE_POINTER_SHA or sha(launcher)!=LAUNCHER_SHA or sha(old)!=BASE_EXE_SHA):
  raise ReleaseBlocked('Installed 1.0.6 baseline fingerprint mismatch')
 target=app/'versions'/'1.0.7'
 safe(target,exists=False)
 for name in (POINTER_BACKUP,PENDING,'current-version-1.0.7-rollback-pending.txt'):
  safe(app/name,exists=False)
 return app,pointer,launcher,old,target
def prove_snapshot_matches(folder=BACKUP):
 evidence_path=folder/'verification.json';snapshot=folder/'snapshot'
 safe(folder);safe(evidence_path,directory=False);safe(snapshot)
 evidence=json.loads(evidence_path.read_text(encoding='utf-8'))
 verified=verify_three_root_backup(snapshot)
 if (evidence.get('status')!='VERIFIED_SAME_PRINCIPAL_SNAPSHOT_AND_ISOLATED_RESTORE' or
  evidence.get('dpapiSamePrincipalReadback') is not True or
  evidence.get('sourceWriteDenialHeldForAllDataFiles') is not True or
  verified.get('dpapi_same_principal_verified') is not True):
  raise ReleaseBlocked('Fresh hotfix backup/restore evidence not accepted')
 roots=backup.source_roots()
 comparisons={'files':verified['files'],'sqlite':verified['sqlite'],'databases':0,'tables':0,'rows':0}
 for role in ROLES:
  active=safe(roots[role]);saved=safe(snapshot/role)
  ad,af,_aside=_scan(active);bd,bf,_bside=_scan(saved)
  if ad!=bd or set(af)!=set(bf):raise ReleaseBlocked('Live data inventory differs from backup: '+role)
  for name in af:
   a,b=active/name,saved/name
   if name.lower().endswith(('.sqlite3','.sqlite','.db')):
    left=backup._db_rows_digest(a);right=backup._db_rows_digest(b)
    if left!=right:raise ReleaseBlocked('SQLite content differs from backup: '+role+'/'+name)
    comparisons['databases']+=1;comparisons['tables']+=left[1];comparisons['rows']+=left[2]
   elif _secure_digest(a)!=_secure_digest(b):
    raise ReleaseBlocked('Data file differs from backup: '+role+'/'+name)
 return {'backup':str(folder),'verification':evidence,'comparison':comparisons}
def production_preflight():
 issues=[];proof=None
 try:
  if os.name!='nt' or os.environ.get('TARAZ_QA_MODE'):raise ReleaseBlocked('Real Windows profile required')
  no_live_writers()
 except Exception as e:issues.append('WRITERS: '+str(e)[:220])
 try:pinned_package();baseline()
 except Exception as e:issues.append('PACKAGE_OR_BASELINE: '+str(e)[:220])
 try:proof=prove_snapshot_matches()
 except Exception as e:issues.append('BACKUP_OR_DATA: '+str(e)[:220])
 try:
  safe(JOURNAL,exists=False);safe(JOURNAL.parent)
 except Exception as e:issues.append('JOURNAL: '+str(e)[:220])
 return {'status':'PASS_PROTECTED_V107_PREFLIGHT' if not issues else 'BLOCKED',
  'issues':issues,'sourceVersion':BASE_VERSION,'targetVersion':TARGET_VERSION,
  'candidateSha256':TARGET_EXE_SHA,'dataMigration':False,'dataRootsModified':False,
  'backupEvidence':proof,'productionChanged':False}
def apply():
 check=production_preflight()
 if check['status']!='PASS_PROTECTED_V107_PREFLIGHT':return check
 no_live_writers();pinned_package();app,pointer,launcher,old,target=baseline()
 data_proof=prove_snapshot_matches();original=pointer.read_bytes()
 JOURNAL.mkdir()
 event(JOURNAL,0,{'stage':'PREPARED','from':BASE_VERSION,'to':TARGET_VERSION,
  'install':str(app),'baseExeSha256':BASE_EXE_SHA,'targetExeSha256':TARGET_EXE_SHA,
  'backup':str(BACKUP),'dataMigration':False})
 stage=app/'versions'/('.1.0.7-stage-'+uuid.uuid4().hex)
 try:
  stage.mkdir();create_new(stage/'Taraz.exe',EXE.read_bytes())
  if sha(stage/'Taraz.exe')!=TARGET_EXE_SHA:raise ReleaseBlocked('Staged EXE hash mismatch')
  stage.rename(target)
  event(JOURNAL,1,{'stage':'EXE_INSTALLED_NOT_ACTIVATED','path':str(target),'sha256':TARGET_EXE_SHA})
  create_new(app/POINTER_BACKUP,original)
  if sha(app/POINTER_BACKUP)!=BASE_POINTER_SHA:raise ReleaseBlocked('Pointer backup hash mismatch')
  create_new(app/PENDING,b'1.0.7\r\n')
  if sha(app/PENDING)!=TARGET_POINTER_SHA:raise ReleaseBlocked('Pending pointer hash mismatch')
  no_live_writers()
  if sha(pointer)!=BASE_POINTER_SHA:raise ReleaseBlocked('Current pointer changed before activation')
  os.replace(app/PENDING,pointer)
  if pointer.read_text(encoding='utf-8-sig').strip()!=TARGET_VERSION or sha(pointer)!=TARGET_POINTER_SHA:
   raise ReleaseBlocked('Activated pointer readback mismatch')
  event(JOURNAL,2,{'stage':'ACTIVATED','pointerSha256':sha(pointer)})
  no_live_writers();after=prove_snapshot_matches()
  if after['comparison']!=data_proof['comparison']:
   raise ReleaseBlocked('Data verification changed across binary-only update')
  event(JOURNAL,3,{'stage':'DATA_UNCHANGED','comparison':after['comparison']})
  return {'status':'PASS_V107_PRODUCTION_BINARY_ONLY_UPDATE','version':TARGET_VERSION,
   'exeSha256':TARGET_EXE_SHA,'pointerSha256':sha(pointer),'dataMigration':False,
   'dataRootsUnchanged':True,'backup':str(BACKUP),'journal':str(JOURNAL)}
 except BaseException:
  try:
   if pointer.exists() and pointer.read_text(encoding='utf-8-sig').strip()==TARGET_VERSION:
    no_live_writers();recovery=app/('current-version-1.0.6-recovery-'+uuid.uuid4().hex+'.txt')
    create_new(recovery,original);os.replace(recovery,pointer)
    if sha(pointer)==BASE_POINTER_SHA:event(JOURNAL,900,{'stage':'POINTER_RECOVERED_TO_106'})
  except Exception:pass
  raise
def rollback():
 no_live_writers()
 state=json.loads(safe(JOURNAL/'000.json',directory=False).read_text(encoding='utf-8'))
 if (state.get('stage')!='PREPARED' or state.get('targetExeSha256')!=TARGET_EXE_SHA or
  state.get('baseExeSha256')!=BASE_EXE_SHA or
  state.get('backup')!=str(BACKUP)):raise ReleaseBlocked('Release journal identity mismatch')
 app,pointer,launcher,old,target=baseline_for_rollback()
 # A normal v1.0.7 startup creates additional automatic backups. Thus the
 # original pre-upgrade snapshot MUST NOT be used as a condition requiring
 # live roots to be identical, and MUST NEVER be restored over newer data.
 original_evidence=json.loads(safe(BACKUP/'verification.json',directory=False).read_text())
 if (original_evidence.get('status')!='VERIFIED_SAME_PRINCIPAL_SNAPSHOT_AND_ISOLATED_RESTORE' or
  original_evidence.get('dpapiSamePrincipalReadback') is not True or
  verify_three_root_backup(safe(BACKUP/'snapshot')).get('dpapi_same_principal_verified') is not True):
  raise ReleaseBlocked('Original pre-upgrade recovery backup no longer verified')
 backup_pointer=safe(app/POINTER_BACKUP,directory=False)
 if sha(backup_pointer)!=BASE_POINTER_SHA or backup_pointer.read_bytes()!=b'1.0.6\r\n':
  raise ReleaseBlocked('Original pointer backup invalid')
 if pointer.read_text(encoding='utf-8-sig').strip()!=TARGET_VERSION or sha(pointer)!=TARGET_POINTER_SHA:
  raise ReleaseBlocked('Only exact active 1.0.7 can roll back')
 # Fresh, create-only three-root Backup + independent Restore is REQUIRED
 # before a rollback. This retains all post-upgrade invoices, chat and orders.
 current_snapshot=JOURNAL/'rollback-current-data-backup'
 safe(current_snapshot,exists=False)
 backed=backup.run(current_snapshot,expected_version=TARGET_VERSION,
  expected_exe_sha=TARGET_EXE_SHA,expected_pointer_sha=TARGET_POINTER_SHA)
 if backed.get('status')!='VERIFIED_SAME_PRINCIPAL_SNAPSHOT_AND_ISOLATED_RESTORE':
  raise ReleaseBlocked('Current data recovery snapshot was not accepted')
 before=prove_snapshot_matches(current_snapshot)
 pending=app/'current-version-1.0.6-rollback-pending.txt';safe(pending,exists=False)
 create_new(pending,backup_pointer.read_bytes());no_live_writers();os.replace(pending,pointer)
 if pointer.read_text(encoding='utf-8-sig').strip()!=BASE_VERSION or sha(pointer)!=BASE_POINTER_SHA:
  raise ReleaseBlocked('Rollback pointer readback mismatch')
 after=prove_snapshot_matches(current_snapshot)
 if after['comparison']!=before['comparison']:
  raise ReleaseBlocked('Current data differs from fresh rollback backup')
 event(JOURNAL,4,{'stage':'ROLLED_BACK_TO_106','pointerSha256':sha(pointer),
  'newExeRetained':True,'dataRootsModified':False,
  'currentDataBackup':str(current_snapshot)})
 return {'status':'PASS_V107_ROLLBACK_TO_106','pointerSha256':sha(pointer),
  'oldExeSha256':sha(old),'newExeSha256':sha(target/'Taraz.exe'),
  'currentDataBackup':str(current_snapshot),'dataRootsModified':False}
def baseline_for_rollback():
 app=Path(os.environ['LOCALAPPDATA'])/'Programs'/'Taraz'
 pointer=safe(app/'current-version.txt',directory=False)
 launcher=safe(app/'Run-Taraz.cmd',directory=False)
 old=safe(app/'versions'/'1.0.6'/'Taraz.exe',directory=False)
 target=safe(app/'versions'/'1.0.7')
 if sha(launcher)!=LAUNCHER_SHA or sha(old)!=BASE_EXE_SHA or sha(target/'Taraz.exe')!=TARGET_EXE_SHA:
  raise ReleaseBlocked('Retained 1.0.6/1.0.7 executable mismatch')
 return app,pointer,launcher,old,target
def main():
 parser=argparse.ArgumentParser()
 group=parser.add_mutually_exclusive_group(required=True)
 group.add_argument('--backup',action='store_true');group.add_argument('--preflight',action='store_true')
 group.add_argument('--apply',action='store_true');group.add_argument('--rollback',action='store_true')
 a=parser.parse_args()
 if a.backup:result=backup.run(BACKUP)
 elif a.preflight:result=production_preflight()
 elif a.apply:result=apply()
 else:result=rollback()
 print(json.dumps(result,ensure_ascii=True))
 return 0 if (result.get('status','').startswith('PASS_') or
              result.get('status')=='VERIFIED_SAME_PRINCIPAL_SNAPSHOT_AND_ISOLATED_RESTORE') else 2
if __name__=='__main__':raise SystemExit(main())
