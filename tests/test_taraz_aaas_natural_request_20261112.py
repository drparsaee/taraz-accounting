"""Operational Persian natural request to real tool/memory with human gating.

Every company is disposable. Model output is never assumed or forged.
"""
import hashlib
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from taraz_order_store import TarazOrderStore, OrderConflict
from taraz_aaas_agent import AgentMemoryError, CompanyAgentMemory
from tests.test_taraz_order_finance_20261112 import passport
from tests.taraz_p1_real_backend_http_fixture_20261112 import (
    AuthenticatedQaTarazAPI,Identity,
)


class NaturalRequestToolTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='qa-farsi-operational-agent-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'company-one'
        self.other=Path(self.temp.name)/'company-two'
        self.root.mkdir();self.other.mkdir()
        self.ledger=self.root/'standalone-accounting.sqlite3'
        self.ledger.write_bytes(b'QA-ACCOUNTING-IMMUTABLE')
        self.digest=hashlib.sha256(self.ledger.read_bytes()).hexdigest()
        self.api=AuthenticatedQaTarazAPI(self.root,Identity())
        self.order=TarazOrderStore(self.root).command({
            'action':'create','idempotencyKey':secrets.token_hex(16),
            'orderId':'','expectedRevision':0,'data':passport(),
            'nextStatus':None,'manualConfirmation':False,
        },actor='qa-invoice-operator',role='admin')

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.ledger.read_bytes()).hexdigest(),
                         self.digest)

    def test_persian_request_uses_real_sqlite_unknowns_and_no_model_claim(self):
        with patch('taraz_llm_order_suggest.suggest_order',
                   side_effect=AssertionError('Model must not be called')):
            result=self.api.tarazAgentNaturalRequest(
                self.order['id'],'پرت واقعی و مازاد سالم سفارش پاسپورت را بررسی کن')
        self.assertEqual(result['source'],'REAL_SQLITE_TOOLS')
        self.assertEqual(result['inference'],'RULE_BASED_FALLBACK')
        self.assertEqual(result['intent'],'request_measured_quantities')
        self.assertIn('request_measured_quantities',result['missingInformation'])
        self.assertTrue(result['editableProposal'])
        self.assertEqual(result['sourceRevision'],1)
        self.assertFalse(result['modelRan'])
        self.assertFalse(result['autoActionPerformed'])
        self.assertFalse(result['financialEventCreated'])
        self.assertFalse(CompanyAgentMemory(self.root).path.exists())
        self.assertEqual(TarazOrderStore(self.root).get(self.order['id'])['revision'],1)

    def test_human_rejected_proposal_does_not_return_after_reload(self):
        result=self.api.tarazAgentNaturalRequest(
            self.order['id'],'هزینه و رسید تمام مراحل را پیگیری کن')
        proposal=self.api.tarazAgentMemoryCommand({
            'action':'propose','orderId':self.order['id'],'entryId':None,
            'text':result['editableProposal'],'sourceRevision':1,
            'expectedMemoryRevision':0,'idempotencyKey':secrets.token_hex(16),
            'manualConfirmation':False,
        })
        self.assertEqual(proposal['status'],'proposed')
        rejected=self.api.tarazAgentMemoryCommand({
            'action':'reject','orderId':self.order['id'],'entryId':proposal['id'],
            'text':None,'sourceRevision':1,'expectedMemoryRevision':1,
            'idempotencyKey':secrets.token_hex(16),'manualConfirmation':True,
        })
        self.assertEqual(rejected['status'],'rejected')
        reopened=AuthenticatedQaTarazAPI(self.root,Identity())
        after=reopened.tarazAgentNaturalRequest(
            self.order['id'],'هزینه و رسید تمام مراحل را پیگیری کن')
        self.assertTrue(after['previouslyRejected'])
        self.assertEqual(after['editableProposal'],'')
        self.assertEqual(after['memoryRevision'],2)
        self.assertEqual(len(CompanyAgentMemory(self.root).list(
            self.order['id'])['entries']),1)
        self.assertEqual(TarazOrderStore(self.root).get(self.order['id'])['revision'],1)

    def test_company_boundary_and_invalid_request_fail_closed(self):
        other=AuthenticatedQaTarazAPI(self.other,Identity())
        with self.assertRaises(OrderConflict):
            other.tarazAgentNaturalRequest(
                self.order['id'],'مانده تسویه این سفارش چقدر است')
        for text in ('','\x00فرمان جعلی','a'*1201):
            with self.subTest(text_size=len(text)):
                with self.assertRaises(AgentMemoryError):
                    self.api.tarazAgentNaturalRequest(self.order['id'],text)
        self.assertFalse((self.other/'taraz-agent-memory.sqlite3').exists())


if __name__=='__main__':
    unittest.main()
