"""Synthetic Madar operational write plan: source preserved, no ledger or LAN.

The actual pinned transport is tested separately from this pure state adapter.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, main, mock
import secrets

from taraz_madar_data_reader import MadarReadError
from taraz_madar_order_sync import (
    _canonical, _source_digest, prepare_madar_order_state, sync_order_to_madar,
    extract_madar_order_stage_progress,
)
from taraz_order_store import TarazOrderStore
from tests.test_taraz_order_finance_20261112 import passport


def madar_state():
    return {'version':1,'projects':[{'id':'test-p1','name':'Project QA',
        'color':'#336699','costEnabled':False,'price':0,'fileLinks':[]}],
        'tasks':[],
        'stages':[{'id':'planned','label':'Planned','subtitle':'',
                   'color':'#557799'}],
        'settings':{'theme':'light','themeForAllUsers':False,'costDefault':False,
                    'priorityDefinitions':[{'id':'medium','label':'Normal','color':'#667788'}]},
        }


class MadarOrderSyncTests(TestCase):
    def setUp(self):
        temp=TemporaryDirectory(prefix='taraz-madar-sync-qa-')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/'company'
        self.root.mkdir()
        self.ledger=self.root/'standalone-accounting.sqlite3'
        self.ledger.write_bytes(b'NO-REAL-LEDGER')
        self.ledger_before=hashlib.sha256(self.ledger.read_bytes()).hexdigest()
        self.store=TarazOrderStore(self.root)
        self.row=self.store.command({
            'action':'create','idempotencyKey':secrets.token_hex(16),'orderId':'',
            'expectedRevision':0,'nextStatus':None,'manualConfirmation':False,
            'data':passport(),
        },actor='qa-operator',role='editor')
        self.state=madar_state()

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.ledger.read_bytes()).hexdigest(),
                         self.ledger_before)

    def test_source_preserved_one_task_and_true_unknowns(self):
        original=_canonical(self.state)
        candidate,task,status=prepare_madar_order_state(
            self.state,order=self.row,project_id='test-p1')
        self.assertEqual(status,'NEW_TASK')
        self.assertEqual(_canonical(self.state),original)
        self.assertEqual(candidate['projects'],self.state['projects'])
        self.assertEqual(candidate['settings'],self.state['settings'])
        self.assertEqual(len(candidate['tasks']),1)
        self.assertEqual(task['id'],'taraz-order-'+self.row['id'])
        self.assertEqual(task['projectId'],'test-p1')
        self.assertFalse(task['costEnabled'])
        self.assertEqual(task['cost'],0)  # Madar schema default, not an order amount
        self.assertEqual(len(task['checklist']),6)
        self.assertTrue(all(not stage['done'] for stage in task['checklist']))
        self.assertIn('نامشخص',task['description'])
        self.assertNotIn('transactionReference',_canonical(task))
        self.assertEqual(task['tarazOrderSourceSha256'],_source_digest(self.row))

    def test_no_duplicate_and_manual_foreign_edit_is_not_overwritten(self):
        candidate,task,_=prepare_madar_order_state(
            self.state,order=self.row,project_id='test-p1')
        again,_,status=prepare_madar_order_state(
            candidate,order=self.row,project_id='test-p1')
        self.assertIsNone(again)
        self.assertEqual(status,'ALREADY_SYNCED')
        other=deepcopy(candidate)
        other['tasks'][0]['tarazOrderSourceRevision']=5
        with self.assertRaises(MadarReadError):
            prepare_madar_order_state(other,order=self.row,project_id='test-p1')
        with self.assertRaises(MadarReadError):
            prepare_madar_order_state(candidate,order=self.row,project_id='different')

    def test_stage_completion_is_read_from_existing_host_checklist_only(self):
        candidate,task,_=prepare_madar_order_state(
            self.state,order=self.row,project_id='test-p1')
        task['checklist'][0]['done']=True
        task['checklist'][1]['done']=True
        task['checklist'].append({'id':'manual-local','text':'یادداشت مستقل مدار',
                                  'done':True})
        original=_canonical(candidate)
        status=extract_madar_order_stage_progress(
            candidate,order=self.row,project_id='test-p1')
        self.assertEqual(status['status'],'CURRENT_SOURCE')
        self.assertEqual((status['completedStages'],status['unknownStages']),(2,0))
        self.assertEqual([step['state'] for step in status['stages']],
                         ['done','done','pending','pending','pending','pending'])
        self.assertEqual(_canonical(candidate),original)
        # Human deletion or malformed completion must never be guessed done.
        candidate['tasks'][0]['checklist'].pop(3)
        status=extract_madar_order_stage_progress(
            candidate,order=self.row,project_id='test-p1')
        self.assertEqual(status['unknownStages'],1)
        candidate['tasks'][0]['tarazOrderSourceRevision']=900
        status=extract_madar_order_stage_progress(
            candidate,order=self.row,project_id='test-p1')
        self.assertEqual(status['status'],'SOURCE_CHANGED')
        self.assertFalse(status['sourceMatchesCurrent'])

    def test_progress_rejects_duplicate_or_reassigned_host_identity(self):
        candidate,task,_=prepare_madar_order_state(
            self.state,order=self.row,project_id='test-p1')
        duplicate=deepcopy(candidate)
        duplicate['tasks'].append(deepcopy(task))
        with self.assertRaises(MadarReadError):
            extract_madar_order_stage_progress(
                duplicate,order=self.row,project_id='test-p1')
        modified=deepcopy(candidate)
        modified['tasks'][0]['projectId']='wrong-project'
        with self.assertRaises(MadarReadError):
            extract_madar_order_stage_progress(
                modified,order=self.row,project_id='test-p1')
        modified=deepcopy(candidate)
        modified['tasks'][0]['checklist'][0]['done']='true'
        output=extract_madar_order_stage_progress(
            modified,order=self.row,project_id='test-p1')
        self.assertEqual(output['stages'][0]['state'],'unknown')

    def test_forged_project_and_corrupt_states_rejected(self):
        for state,project in [(self.state,'absent'),({},'test-p1'),
                              ({'version':1,'tasks':{}},'test-p1')]:
            with self.subTest(project=project):
                with self.assertRaises(MadarReadError):
                    prepare_madar_order_state(state,order=self.row,
                                              project_id=project)

    def test_preview_uses_authenticated_madar_projection_and_write_gate(self):
        connection={'url':'https://127.0.0.1:48370',
                    'fingerprint':'a'*64,'username':'qa-user',
                    'password':'synthetic-only-password'}
        login={'token':'Q'*32,'user':{'username':'qa-user',
                                    'role':'admin','projects':None}}
        state=self.state
        read={'state':state,'revision':hashlib.sha256(_canonical(state).encode()).hexdigest(),
              'user':login['user']}
        with mock.patch('taraz_madar_order_sync._pinned_json',
                        side_effect=[login,read]) as reader, mock.patch(
                            'taraz_madar_order_sync._write_pinned_state') as writer:
            preview=sync_order_to_madar(order=self.row,project_id='test-p1',
                connection=connection,reviewed_revision=None,preview_digest=None)
            self.assertEqual(preview['status'],'PREVIEW_ONLY')
            self.assertFalse(preview['wroteMadarState'])
            self.assertFalse(preview['financialEventCreated'])
            self.assertEqual(reader.call_count,2)
            writer.assert_not_called()

    def test_post_path_matches_actual_verified_madar_state_contract_on_synthetic_host(self):
        connection={'url':'https://127.0.0.1:48370',
                    'fingerprint':'a'*64,'username':'qa-user',
                    'password':'synthetic-only-password'}
        login={'token':'Q'*32,'user':{'username':'qa-user',
                                    'role':'admin','projects':None}}
        state=self.state
        read={'state':state,'revision':hashlib.sha256(_canonical(state).encode()).hexdigest(),
              'user':login['user']}
        with mock.patch('taraz_madar_order_sync._pinned_json',
                        side_effect=[login,read]):
            preview=sync_order_to_madar(order=self.row,project_id='test-p1',
                connection=connection,reviewed_revision=None,preview_digest=None)
        captures={}
        def write(host,port,pin,token,next_state,expected):
            captures.update(host=host,port=port,pin=pin,token=token,
                            state=next_state,expected=expected)
            return {'state':next_state,'user':login['user'],
                    'revision':hashlib.sha256(_canonical(next_state).encode()).hexdigest()}
        with mock.patch('taraz_madar_order_sync._pinned_json',
                        side_effect=[login,read]), mock.patch(
                            'taraz_madar_order_sync._write_pinned_state',
                            side_effect=write) as writer:
            outcome=sync_order_to_madar(order=self.row,project_id='test-p1',
                connection=connection,reviewed_revision=preview['sourceRevision'],
                preview_digest=preview['previewDigest'],dry_run=False,
                manual_confirmation=True,source_store=self.store)
            self.assertEqual(writer.call_count,1)
        self.assertEqual(outcome['status'],'SYNCHRONIZED')
        self.assertTrue(outcome['wroteMadarState'])
        self.assertFalse(outcome['financialEventCreated'])
        self.assertEqual(captures['expected'],preview['sourceRevision'])
        self.assertEqual(captures['host'],'127.0.0.1')
        self.assertEqual(len(captures['state']['tasks']),1)
        self.assertEqual(captures['state']['projects'],self.state['projects'])
        self.assertEqual(captures['state']['tasks'][0]['tarazOrderSourceId'],self.row['id'])
        # Do not confuse the patched transport with a real remote write.
        with self.assertRaises(PermissionError):
            sync_order_to_madar(order=self.row,project_id='test-p1',
                connection=connection,reviewed_revision=preview['sourceRevision'],
                preview_digest=preview['previewDigest'],
                dry_run=False,manual_confirmation=False)
        with mock.patch('taraz_madar_order_sync._pinned_json',
                        side_effect=[login,read]), mock.patch(
                            'taraz_madar_order_sync._write_pinned_state') as writer:
            with self.assertRaises(PermissionError):
                sync_order_to_madar(order=self.row,project_id='test-p1',
                    connection=connection,reviewed_revision=preview['sourceRevision'],
                    preview_digest=preview['previewDigest'],dry_run=False,
                    manual_confirmation=True,source_store=None)
            writer.assert_not_called()
        with mock.patch('taraz_madar_order_sync._pinned_json',
                        side_effect=[login,read]), mock.patch(
                            'taraz_madar_order_sync._write_pinned_state') as writer:
            with self.assertRaises(MadarReadError):
                sync_order_to_madar(order=self.row,project_id='test-p1',
                    connection=connection,reviewed_revision='1'*64,
                    preview_digest=preview['previewDigest'],dry_run=False,
                    manual_confirmation=True,source_store=self.store)
            writer.assert_not_called()

    def test_actual_madar_native_validator_accepts_derived_card_when_available(self):
        # This is a real cross-repository schema check, not a recreated mock
        # of Madar's validator. No application data file is opened or changed.
        madar=Path(__file__).resolve().parents[2].parent / '000- Madar' / (
            'madar-mtr-v126-integration-20261110')
        if not (madar/'native_app.py').is_file():
            self.skipTest('Madar source validator not present in this workspace')
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
        source=subprocess.run(
            [sys.executable,'-B','-c',
             'import json,native_app;print(json.dumps(native_app.empty_initial_state()))'],
            cwd=madar,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,timeout=20)
        self.assertEqual(source.returncode,0,source.stderr[-800:])
        state=json.loads(source.stdout.strip().splitlines()[-1])
        # Actual first-run state is intentionally empty. Add only one synthetic
        # project, not the historical demo data that must not reach customers.
        project_id='qa-order-integration-project'
        state['projects'].append({'id':project_id,'name':'QA only project',
                                  'color':'#557799','costEnabled':False,
                                  'price':0,'fileLinks':[]})
        candidate,task,_=prepare_madar_order_state(state,order=self.row,
                                                    project_id=project_id)
        self.assertIsNotNone(task)
        validation=subprocess.run(
            [sys.executable,'-B','-c',
             'import json,sys,native_app;'
             's=json.loads(sys.stdin.read());'
             'native_app.is_valid(native_app.normalize_state(s));print("MADAR_SCHEMA_VALID")'],
            cwd=madar,env=env,input=json.dumps(candidate,ensure_ascii=False),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
            encoding='utf-8',timeout=20)
        self.assertEqual(validation.returncode,0,validation.stderr[-1600:])
        self.assertIn('MADAR_SCHEMA_VALID',validation.stdout)


if __name__=='__main__':
    main()
