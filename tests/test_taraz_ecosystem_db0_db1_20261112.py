"""DB0/DB1: actual disposable SQLite schemas and source-backed read contract.

This intentionally does not import or start PostgreSQL, or change live books.
"""
import hashlib
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from taraz_order_store import TarazOrderStore
from taraz_aaas_agent import CompanyAgentMemory
from taraz_madar_order_link import MadarOrderLinkStore
from taraz_ecosystem_protocol import TrustedScope
from taraz_ecosystem_outbox import EcosystemOutbox
from taraz_repository_contracts import (
    TarazOrderReadRepository, RadarRepositoryNotAvailable, VersionedReference,
)
from tests.test_taraz_order_finance_20261112 import passport
from tests.taraz_p1_real_backend_http_fixture_20261112 import (
    AuthenticatedQaTarazAPI, Identity,
)


class DB0DB1ContractTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(prefix='qa-taraz-db0-db1-')
        self.addCleanup(temp.cleanup)
        self.company=Path(temp.name)/'companyA'
        self.company.mkdir()
        self.api=AuthenticatedQaTarazAPI(self.company,Identity())
        self.order_store=TarazOrderStore(self.company)
        self.data=passport()
        self.data['projectReference']='QA-DB1-PROJECT'
        self.order=self.order_store.command({
            'action':'create','idempotencyKey':secrets.token_hex(16),
            'orderId':'','expectedRevision':0,'data':self.data,
            'nextStatus':None,'manualConfirmation':False},
            actor='qa-invoice-operator',role='admin')

    def test_db0_five_real_source_store_schemas_and_isolation(self):
        self.api.standaloneAccountingCommand({'expectedRevision':0,'command':{
            'type':'party.register','eventId':'QA-DB0-PARTY',
            'partyId':'QA-CUSTOMER','name':'مشتری نمونه','kind':'customer'}})
        memory=CompanyAgentMemory(self.company)
        memory.command({
            'action':'propose','orderId':self.order['id'],'entryId':None,
            'sourceRevision':1,'expectedMemoryRevision':0,
            'idempotencyKey':secrets.token_hex(16),
            'text':'بررسی تامین‌کننده بر اساس سند آزمایشی',
            'manualConfirmation':False},
            actor='qa-invoice-operator',role='admin')
        link=MadarOrderLinkStore(self.company)
        link.begin_sync_attempt(order_id=self.order['id'],order_revision=1,
            project_id='QA-DB1-PROJECT',actor='qa-invoice-operator',
            preview_digest='a'*64,host_revision='b'*64)
        repo=TarazOrderReadRepository(self.company)
        reference=repo.read_reference(self.order['id'])
        envelope={
            'schemaVersion':1,'eventId':secrets.token_hex(16),
            'idempotencyKey':secrets.token_hex(16),
            'sourceSystem':'TARAZ','targetSystem':'MADAR',
            'companyId':'QA-COMPANY-A','actorId':'qa-invoice-operator',
            'entityType':'order','entityId':self.order['id'],
            'sourceRevision':reference.source_revision,
            'sourceDigest':reference.source_digest,
            'eventType':'order.project_link_proposed',
            'payload':{'projectId':'QA-DB1-PROJECT'}}
        EcosystemOutbox(self.company).enqueue(envelope,
            scope=TrustedScope('QA-COMPANY-A','qa-invoice-operator',
                               'admin','TARAZ'),
            source_witness=lambda:repo.witness(self.order['id']))
        expected={
            'standalone-accounting.sqlite3':(1,{'standalone_accounting'}),
            'taraz-orders.sqlite3':(2,{'orders','actions','audit',
                'order_costs','order_payments','order_finance_handoffs'}),
            'taraz-agent-memory.sqlite3':(1,{'entries','commands','revisions','audit'}),
            'taraz-madar-order-links.sqlite3':(1,{'links','commands','audit',
                                                    'sync_attempts'}),
            'taraz-ecosystem-outbox.sqlite3':(1,{'event_outbox','sync_receipts'}),
        }
        for filename,(version,tables) in expected.items():
            with self.subTest(database=filename):
                file=self.company/filename
                self.assertTrue(file.is_file())
                db=sqlite3.connect(file.as_uri()+'?mode=ro',uri=True)
                try:
                    self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],
                                     version)
                    actual={row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")}
                    self.assertTrue(tables <= actual,(filename,tables-actual))
                finally:db.close()
        other=self.company.parent/'companyB'
        other.mkdir()
        self.assertFalse((other/'taraz-orders.sqlite3').exists())
        self.assertFalse((other/'taraz-ecosystem-outbox.sqlite3').exists())

    def test_db1_order_read_adapter_preserves_source_revision_and_digest(self):
        repo=TarazOrderReadRepository(self.company)
        first=repo.read_reference(self.order['id'])
        self.assertIsInstance(first,VersionedReference)
        self.assertEqual((first.source_system,first.entity_type),
                         ('TARAZ','order'))
        self.assertEqual(first.source_revision,1)
        self.assertEqual(repo.witness(self.order['id']),
                         (first.source_revision,first.source_digest))
        changed=dict(self.data,projectReference='QA-DB1-NEW-PROJECT')
        updated=self.order_store.command({
            'action':'update','idempotencyKey':secrets.token_hex(16),
            'orderId':self.order['id'],'expectedRevision':1,
            'data':changed,'nextStatus':None,'manualConfirmation':False,
        },actor='qa-invoice-operator',role='editor')
        self.assertEqual(updated['revision'],2)
        latest=TarazOrderReadRepository(self.company).read_reference(
            self.order['id'])
        self.assertEqual(latest.entity_id,first.entity_id)
        self.assertEqual(latest.source_revision,2)
        self.assertNotEqual(latest.source_digest,first.source_digest)

    def test_radar_adapter_is_explicitly_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            RadarRepositoryNotAvailable().read_reference('QA-EXTERNAL-ENTITY')


if __name__=='__main__':
    unittest.main()
