"""Independent offline nonfinancial contract and SQLite crash/replay acceptance.

No RADAR endpoint, live Madar, network, finance posting or local model required.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import secrets
from tempfile import TemporaryDirectory
import unittest

from taraz_ecosystem_protocol import (
    ProtocolError, TrustedScope, canonical, digest, validate_envelope,
)
from taraz_ecosystem_outbox import EcosystemOutbox, SyncConflict, VerifiedReceipt
from taraz_order_store import TarazOrderStore
from tests.test_taraz_order_finance_20261112 import passport


class OfflineInteropTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(prefix='qa-taraz-ecosystem-')
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.company=self.base/'QA-company-A'
        self.other=self.base/'QA-company-B'
        self.company.mkdir()
        self.other.mkdir()
        self.ledger=self.company/'standalone-accounting.sqlite3'
        self.ledger.write_bytes(b'UNCHANGED SYNTHETIC FINANCIAL BOOK')
        self.ledger_sha=hashlib.sha256(self.ledger.read_bytes()).hexdigest()
        self.scope=TrustedScope('COMPANY-A','qa-agent','admin','TARAZ')
        self.foreign=TrustedScope('COMPANY-B','qa-agent','admin','TARAZ')
        self.store=EcosystemOutbox(self.company)
        self.order=TarazOrderStore(self.company).command({
            'action':'create','idempotencyKey':secrets.token_hex(16),
            'orderId':'','expectedRevision':0,'data':{
                **passport(),'projectReference':'QA-MADAR-PROJECT'},
            'nextStatus':None,'manualConfirmation':False,
        },actor='qa-agent',role='admin')

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.ledger.read_bytes()).hexdigest(),
                         self.ledger_sha)

    def witness(self):
        order=TarazOrderStore(self.company).get(self.order['id'])
        fact={'id':order['id'],'revision':order['revision'],
              'project':order['projectReference']}
        return order['revision'],digest(fact)

    def message(self,*,revision=None,signature=None,source=None,key=None,event=None):
        rev,source_hash=self.witness()
        return {
            'schemaVersion':1,'eventId':event or secrets.token_hex(16),
            'idempotencyKey':key or secrets.token_hex(16),
            'sourceSystem':'TARAZ','targetSystem':'MADAR',
            'companyId':'COMPANY-A','actorId':'qa-agent','entityType':'order',
            'entityId':self.order['id'],
            'sourceRevision':rev if revision is None else revision,
            'sourceDigest':source_hash if signature is None else signature,
            'eventType':'order.project_link_proposed',
            'payload':{'projectId':'QA-MADAR-PROJECT'},
        }

    def test_reads_do_not_create_database_or_finance_side_effects(self):
        self.assertFalse(self.store.path.exists())
        self.assertEqual(self.store.list(company_id='COMPANY-A')['total'],0)
        self.assertFalse(self.store.path.exists())

    def test_durable_enqueue_reopen_idempotent_receipt_and_no_second_post(self):
        packet=self.message()
        first=self.store.enqueue(packet,scope=self.scope,source_witness=self.witness)
        self.assertEqual(first['state'],'PENDING')
        other_instance=EcosystemOutbox(self.company)
        self.assertEqual(other_instance.list(company_id='COMPANY-A')['total'],1)
        self.assertEqual(other_instance.enqueue(
            packet,scope=self.scope,source_witness=self.witness),first)
        other_instance.mark_possibly_sent(packet['eventId'],scope=self.scope,
                                          source_witness=self.witness)
        self.assertEqual(other_instance.get(
            packet['eventId'],company_id='COMPANY-A')['state'],'OUTCOME_UNKNOWN')
        with self.assertRaises(SyncConflict):
            other_instance.mark_possibly_sent(packet['eventId'],scope=self.scope,
                                              source_witness=self.witness)
        receipt=VerifiedReceipt('COMPANY-A','MADAR',packet['eventId'],
                                packet['sourceDigest'],'APPLIED','madar-revision-one')
        finished=other_instance.reconcile_verified_receipt(receipt,scope=self.scope)
        self.assertEqual(finished['state'],'ACKNOWLEDGED')
        self.assertEqual(EcosystemOutbox(self.company).reconcile_verified_receipt(
            receipt,scope=self.scope),finished)
        with self.assertRaises(SyncConflict):
            other_instance.reconcile_verified_receipt(
                VerifiedReceipt('COMPANY-A','MADAR',packet['eventId'],
                                packet['sourceDigest'],'DUPLICATE','different'),
                scope=self.scope)

    def test_trusted_company_isolation_and_role_rejection(self):
        packet=self.message()
        with self.assertRaises(PermissionError):
            self.store.enqueue(packet,scope=self.foreign,source_witness=self.witness)
        with self.assertRaises(PermissionError):
            self.store.enqueue(packet,scope=TrustedScope(
                'COMPANY-A','qa-agent','viewer','TARAZ'),
                source_witness=self.witness)
        self.store.enqueue(packet,scope=self.scope,source_witness=self.witness)
        self.assertIsNone(self.store.get(packet['eventId'],company_id='COMPANY-B'))
        self.assertEqual(self.store.list(company_id='COMPANY-B')['total'],0)
        self.assertFalse(EcosystemOutbox(self.other).path.exists())
        with self.assertRaises(SyncConflict):
            self.store.mark_possibly_sent(packet['eventId'],scope=self.foreign,
                                          source_witness=self.witness)

    def test_model_and_finance_payloads_are_refused_with_strict_schema(self):
        original=self.message()
        attacks=[
            {**original,'eventType':'invoice.issue'},
            {**original,'payload':{'projectId':'QA-MADAR-PROJECT','amount':2500000}},
            {**original,'payload':{'projectId':'QA-MADAR-PROJECT','modelToken':'secret'}},
            {**original,'targetSystem':'TARAZ'},
            {**original,'sourceSystem':'RADAR'},
            {**original,'schemaVersion':True},
            {**original,'sourceRevision':True},
            {**original,'eventId':'../unsafe'},
            {**original,'payload':{'projectId':'QA/../../x'}},
            {**original,'targetSystem':'NO-SUCH-PRODUCT'},
        ]
        for message in attacks:
            with self.subTest(event=message.get('eventType'),
                              keys=tuple(message['payload'])):
                with self.assertRaises((ProtocolError,PermissionError)):
                    self.store.enqueue(message,scope=self.scope,
                                       source_witness=self.witness)
        self.assertFalse(self.store.path.exists())

    def test_stale_forged_witness_key_reuse_and_order_gap_fail_closed(self):
        old=self.message(signature='0'*64)
        with self.assertRaises(SyncConflict):
            self.store.enqueue(old,scope=self.scope,source_witness=self.witness)
        packet=self.message()
        self.store.enqueue(packet,scope=self.scope,source_witness=self.witness)
        changed={**packet,'eventId':secrets.token_hex(16)}
        with self.assertRaises(SyncConflict):
            self.store.enqueue(changed,scope=self.scope,source_witness=self.witness)
        stale=self.message(key=packet['idempotencyKey'])
        with self.assertRaises(SyncConflict):
            self.store.enqueue(stale,scope=self.scope,source_witness=self.witness)
        future=self.message(revision=3)
        with self.assertRaises(SyncConflict):
            self.store.enqueue(future,scope=self.scope,
                               source_witness=lambda:(3,future['sourceDigest']))

    def test_receipt_does_not_accept_wrong_company_source_or_unstaged_send(self):
        packet=self.message()
        self.store.enqueue(packet,scope=self.scope,source_witness=self.witness)
        forged=VerifiedReceipt('COMPANY-B','MADAR',packet['eventId'],
                               packet['sourceDigest'],'APPLIED','rev-1')
        with self.assertRaises(PermissionError):
            self.store.reconcile_verified_receipt(forged,scope=self.scope)
        forged=VerifiedReceipt('COMPANY-A','MADAR',packet['eventId'],
                               'a'*64,'APPLIED','rev-1')
        with self.assertRaises(SyncConflict):
            self.store.reconcile_verified_receipt(forged,scope=self.scope)
        good=VerifiedReceipt('COMPANY-A','MADAR',packet['eventId'],
                             packet['sourceDigest'],'APPLIED','rev-1')
        with self.assertRaises(SyncConflict):
            self.store.reconcile_verified_receipt(good,scope=self.scope)
        self.assertEqual(self.store.get(packet['eventId'],
                                       company_id='COMPANY-A')['state'],'PENDING')

    def test_target_conflict_requires_human_review_no_last_write_wins(self):
        packet=self.message()
        self.store.enqueue(packet,scope=self.scope,source_witness=self.witness)
        self.store.mark_possibly_sent(packet['eventId'],scope=self.scope,
                                      source_witness=self.witness)
        receipt=VerifiedReceipt('COMPANY-A','MADAR',packet['eventId'],
                                packet['sourceDigest'],'CONFLICT','remote-stale')
        result=self.store.reconcile_verified_receipt(receipt,scope=self.scope)
        self.assertEqual(result['state'],'REVIEW_REQUIRED')
        with self.assertRaises(SyncConflict):
            self.store.mark_possibly_sent(packet['eventId'],scope=self.scope,
                                          source_witness=self.witness)
        self.assertFalse(result['financialEventCreated'])

    def test_dispatch_refuses_missing_witness_and_real_source_revision_change(self):
        packet=self.message()
        self.store.enqueue(packet,scope=self.scope,source_witness=self.witness)
        with self.assertRaises(PermissionError):
            self.store.mark_possibly_sent(packet['eventId'],scope=self.scope,
                                          source_witness=None)
        changed=dict(passport(),projectReference='QA-MADAR-NEW-PROJECT')
        updated=TarazOrderStore(self.company).command({
            'action':'update','idempotencyKey':secrets.token_hex(16),
            'orderId':self.order['id'],'expectedRevision':1,
            'data':changed,'nextStatus':None,'manualConfirmation':False,
        },actor='qa-agent',role='editor')
        self.assertEqual(updated['revision'],2)
        with self.assertRaises(SyncConflict):
            self.store.mark_possibly_sent(packet['eventId'],scope=self.scope,
                                          source_witness=self.witness)
        self.assertEqual(self.store.get(packet['eventId'],
                         company_id='COMPANY-A')['state'],'PENDING')
        # A later source revision must not silently overtake an unresolved one.
        with self.assertRaises(SyncConflict):
            self.store.enqueue(self.message(),scope=self.scope,
                               source_witness=self.witness)
        self.assertEqual(self.store.list(company_id='COMPANY-A')['total'],1)

    def test_following_revision_can_stage_only_after_prior_acknowledgment(self):
        first=self.message()
        self.store.enqueue(first,scope=self.scope,source_witness=self.witness)
        self.store.mark_possibly_sent(first['eventId'],scope=self.scope,
                                      source_witness=self.witness)
        changed=dict(passport(),projectReference='QA-MADAR-NEW-PROJECT')
        update=TarazOrderStore(self.company).command({
            'action':'update','idempotencyKey':secrets.token_hex(16),
            'orderId':self.order['id'],'expectedRevision':1,
            'data':changed,'nextStatus':None,'manualConfirmation':False,
        },actor='qa-agent',role='editor')
        self.assertEqual(update['revision'],2)
        with self.assertRaises(SyncConflict):
            self.store.enqueue(self.message(),scope=self.scope,
                               source_witness=self.witness)
        self.store.reconcile_verified_receipt(VerifiedReceipt(
            'COMPANY-A','MADAR',first['eventId'],first['sourceDigest'],
            'APPLIED','madar-revision-one'),scope=self.scope)
        second=self.message()
        staged=self.store.enqueue(second,scope=self.scope,
                                  source_witness=self.witness)
        self.assertEqual(staged['state'],'PENDING')
        self.assertEqual(staged['source_revision'],2)
        self.assertEqual(self.store.list(company_id='COMPANY-A')['total'],2)

    def test_many_concurrent_idempotent_retries_write_exactly_one(self):
        packet=self.message()
        def worker(_):
            return EcosystemOutbox(self.company).enqueue(
                packet,scope=self.scope,source_witness=self.witness)
        with ThreadPoolExecutor(max_workers=5) as pool:
            results=list(pool.map(worker,range(10)))
        self.assertTrue(all(r['event_id']==packet['eventId'] for r in results))
        self.assertEqual(self.store.list(company_id='COMPANY-A')['total'],1)
        self.assertTrue(all(r['state']=='PENDING' for r in results))

    def test_crash_reopening_uncertain_without_network_auto_retry(self):
        packet=self.message()
        self.store.enqueue(packet,scope=self.scope,source_witness=self.witness)
        self.store.mark_possibly_sent(packet['eventId'],scope=self.scope,
                                      source_witness=self.witness)
        recovered=EcosystemOutbox(self.company)
        snapshot=recovered.list(company_id='COMPANY-A')
        self.assertEqual(snapshot['entries'][0]['state'],'OUTCOME_UNKNOWN')
        self.assertTrue(snapshot['entries'][0]['remoteMayHaveChanged'])
        self.assertFalse(snapshot['networkSenderAvailable'])
        self.assertTrue(snapshot['readOnly'])
        self.assertEqual(recovered.list(company_id='COMPANY-A'),snapshot)


if __name__=='__main__':
    unittest.main()
