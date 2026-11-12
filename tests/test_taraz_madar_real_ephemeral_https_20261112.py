"""Real TARAZ -> ephemeral REAL MADAR LAN HTTPS, not mocked network.

The independently owned MADAR v126 source is IMPORTED without modification.
TLS cert is its own public disposable test certificate. Both data folders are
temporary; no installed MadarHost, 48370, office LAN or finance is touched.
This establishes test-host interoperability, NOT multi-product release.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import secrets
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from taraz_order_store import TarazOrderStore
from taraz_madar_order_sync import _source_digest
from tests.test_taraz_order_finance_20261112 import passport
from tests.taraz_p1_real_backend_http_fixture_20261112 import (
    AuthenticatedQaTarazAPI, Identity,
)

MADAR_ROOT = Path('D:/CoS-Test/000- Madar/madar-mtr-v126-integration-20261110')


def public_test_certificate_fixture():
    """Read already-public synthetic certificate source without executing it."""
    tree = ast.parse((MADAR_ROOT / 'tests/test_lan_tls.py').read_text(
        encoding='utf-8'))
    literals = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets)==1:
            target=stmt.targets[0]
            if isinstance(target,ast.Name) and target.id in ('_CERT','_KEY'):
                literals[target.id]=ast.literal_eval(stmt.value)
    if set(literals)!= {'_CERT','_KEY'}:
        raise unittest.SkipTest('Public Madar TLS QA fixture unavailable')
    return literals['_CERT'],literals['_KEY']


class RealEphemeralMadarHttpsAcceptance(unittest.TestCase):
    def setUp(self):
        if not (MADAR_ROOT / 'lan.py').is_file():
            self.skipTest('Actual Madar source not present at verified path')
        temporary=TemporaryDirectory(prefix='qa-ecosystem-madar-loopback-')
        self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name)
        self.madar_data=self.base/'madar-qa'
        self.madar_data.mkdir()
        self.taraz_data=self.base/'taraz-qa'
        self.taraz_data.mkdir()
        cert,key=public_test_certificate_fixture()
        certfile=self.base/'test.crt'
        keyfile=self.base/'test.key'
        certfile.write_text(cert,encoding='ascii')
        keyfile.write_text(key,encoding='ascii')

        # Imported source runs only inside our temporary profile, not the
        # user's real APPDATA or installed LAN service.
        if str(MADAR_ROOT) not in sys.path:
            sys.path.insert(0,str(MADAR_ROOT))
        import native_app
        from lan import LanService, certificate_fingerprint
        self.datadir_patch=patch.object(
            native_app,'datadir',return_value=self.madar_data)
        self.datadir_patch.start()
        self.addCleanup(self.datadir_patch.stop)
        bridge=native_app.Bridge()
        state=native_app.initial_state()
        # Initial demo data includes unrelated example tasks. Our temporary
        # server must start empty, with exactly one synthetic project.
        state['tasks']=[]
        state['projects']=[{
            'id':'test-p1','name':'QA-Taraz Project','price':0,
            'costEnabled':False,'fileLinks':[]}]
        bridge.saveState(state)
        self.service=LanService(bridge,self.madar_data/'users.json',
                                bind='127.0.0.1',port=0,
                                certfile=certfile,keyfile=keyfile)
        self.service.setup_owner('qa-admin','qa-only-private-password')
        port=self.service.start()
        self.addCleanup(self.service.stop)
        self.connection={
            'url':f'https://127.0.0.1:{port}',
            'fingerprint':certificate_fingerprint(certfile),
            'username':'qa-admin','password':'qa-only-private-password'}

        self.accounting=self.taraz_data/'standalone-accounting.sqlite3'
        self.accounting.write_bytes(b'QA ONLY: DO NOT POST')
        self.original_digest=hashlib.sha256(self.accounting.read_bytes()).hexdigest()
        self.api=AuthenticatedQaTarazAPI(self.taraz_data,Identity())
        self.orders=TarazOrderStore(self.taraz_data)
        source=passport()
        source['projectReference']='test-p1'
        self.order=self.orders.command({
            'action':'create','idempotencyKey':secrets.token_hex(16),
            'orderId':'','expectedRevision':0,'data':source,
            'nextStatus':None,'manualConfirmation':False
        },actor='qa-invoice-operator',role='admin')

    def tearDown(self):
        if hasattr(self,'accounting'):
            self.assertEqual(hashlib.sha256(self.accounting.read_bytes()).hexdigest(),
                             self.original_digest)

    def _link(self):
        result=self.api.tarazOrderMadarLink({
            'orderId':self.order['id'],
            'expectedOrderRevision':self.order['revision'],
            'projectId':'test-p1','pageOffset':0,
            'expectedLinkRevision':0,'connection':self.connection,
            'explicitConsent':True,'idempotencyKey':secrets.token_hex(16),
        })
        self.assertEqual(result['status'],'VERIFIED_READ_ONLY_MADAR_LINK')
        return result

    def test_real_pinned_tls_login_project_task_sync_progress_and_no_duplicate(self):
        self._link()
        preview=self.api.tarazMadarOrderPreview(
            self.order['id'],'test-p1',self.connection,True)
        self.assertEqual(preview['status'],'PREVIEW_ONLY')
        self.assertEqual(len(self.service.bridge.getState()['tasks']),0)
        # Explicit admin approval is sent ONLY to the own temporary MADAR
        # HTTP host, not a real company or user-approved operational host.
        payload={
            'orderId':self.order['id'],
            'expectedOrderRevision':self.order['revision'],
            'projectId':'test-p1',
            'expectedMadarRevision':preview['sourceRevision'],
            'previewDigest':preview['previewDigest'],
            'explicitConsent':True,'manualConfirmation':True,
        }
        created=self.api.tarazMadarOrderCommit(payload,self.connection)
        self.assertEqual(created['status'],'SYNCHRONIZED')
        self.assertTrue(created['wroteMadarState'])
        state=self.service.bridge.getState()
        self.assertEqual(len(state['tasks']),1)
        task=state['tasks'][0]
        self.assertEqual(task['tarazOrderSourceId'],self.order['id'])
        self.assertEqual(task['tarazOrderSourceSha256'],_source_digest(self.order))
        self.assertEqual(task['projectId'],'test-p1')
        self.assertEqual(len(task['checklist']),len(self.order['costStages']))
        self.assertFalse(any(item['done'] for item in task['checklist']))
        progress=self.api.tarazMadarOrderProgress(
            self.order['id'],'test-p1',self.connection,True)
        self.assertEqual(progress['status'],'CURRENT_SOURCE')
        self.assertEqual(progress['completedStages'],0)
        self.assertFalse(progress['financialEventCreated'])
        history=self.api.tarazMadarOrderSyncHistory(self.order['id'])
        self.assertEqual(history['entries'][0]['status'],'SYNCHRONIZED')
        replay=self.api.tarazMadarOrderRecover(
            self.order['id'],'test-p1',self.connection,True)
        self.assertEqual(replay['status'],'RECOVERED_CONFIRMED')
        self.assertFalse(replay['wroteMadarState'])
        self.assertEqual(len(self.service.bridge.getState()['tasks']),1)
        self.assertEqual(self.orders.get(self.order['id'])['revision'],1)

    def test_bad_tls_pin_refused_before_login_and_no_host_change(self):
        self._link()
        tampered=dict(self.connection,fingerprint='0'*64)
        with self.assertRaises(Exception):
            self.api.tarazMadarOrderPreview(
                self.order['id'],'test-p1',tampered,True)
        self.assertEqual(len(self.service.bridge.getState()['tasks']),0)
        self.assertEqual(len(self.service.sessions),1)
        self.assertFalse((self.taraz_data/'taraz-ecosystem-outbox.sqlite3').exists())

    def test_actual_host_manual_task_progress_is_observed_without_overwrite(self):
        self._link()
        preview=self.api.tarazMadarOrderPreview(
            self.order['id'],'test-p1',self.connection,True)
        self.api.tarazMadarOrderCommit({
            'orderId':self.order['id'],
            'expectedOrderRevision':1,
            'projectId':'test-p1',
            'expectedMadarRevision':preview['sourceRevision'],
            'previewDigest':preview['previewDigest'],
            'explicitConsent':True,'manualConfirmation':True},
            self.connection)
        # An actual MADAR admin session, not TARAZ, updates the real
        # ephemeral host's source task and its human-authored description.
        token=self.service.authenticate(
            'qa-admin','qa-only-private-password','127.0.0.1')['token']
        snapshot=self.service.read_state(token)
        changed=snapshot['state']
        changed['tasks'][0]['checklist'][0]['done']=True
        changed['tasks'][0]['description']='QA MANUAL MADAR NOTE'
        self.service.write_state(token,changed,snapshot['revision'])
        progress=self.api.tarazMadarOrderProgress(
            self.order['id'],'test-p1',self.connection,True)
        self.assertEqual(progress['completedStages'],1)
        self.assertEqual(progress['stages'][0]['state'],'done')
        again=self.api.tarazMadarOrderPreview(
            self.order['id'],'test-p1',self.connection,True)
        self.assertEqual(again['status'],'ALREADY_SYNCED')
        self.assertEqual(self.service.bridge.getState()['tasks'][0]['description'],
                         'QA MANUAL MADAR NOTE')
        self.assertEqual(len(self.service.bridge.getState()['tasks']),1)
        self.assertEqual(self.orders.get(self.order['id'])['revision'],1)

    def test_changed_actual_madar_revision_refuses_stale_taraz_commit(self):
        self._link()
        preview=self.api.tarazMadarOrderPreview(
            self.order['id'],'test-p1',self.connection,True)
        token=self.service.authenticate(
            'qa-admin','qa-only-private-password','127.0.0.1')['token']
        current=self.service.read_state(token)
        changed=current['state']
        changed['settings']['theme']='dark'
        self.service.write_state(token,changed,current['revision'])
        with self.assertRaises(Exception):
            self.api.tarazMadarOrderCommit({
                'orderId':self.order['id'],
                'expectedOrderRevision':1,
                'projectId':'test-p1',
                'expectedMadarRevision':preview['sourceRevision'],
                'previewDigest':preview['previewDigest'],
                'explicitConsent':True,'manualConfirmation':True},
                self.connection)
        self.assertEqual(self.service.bridge.getState()['tasks'],[])
        entry=self.api.tarazMadarOrderSyncHistory(self.order['id'])['entries'][0]
        self.assertEqual(entry['status'],'REJECTED')
        self.assertFalse(entry['remote_write_attempted'])


if __name__=='__main__':
    unittest.main()
