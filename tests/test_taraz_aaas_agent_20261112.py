"""Live SQLite agent/memory contract tests against a disposable company."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import secrets
import unittest

from taraz_aaas_agent import CompanyAgentMemory, AgentMemoryError, review_order_tools
from taraz_order_store import TarazOrderStore, OrderConflict
from tests.test_taraz_order_finance_20261112 import passport
from tests.taraz_p1_real_backend_http_fixture_20261112 import (
    AuthenticatedQaTarazAPI, Identity,
)


class AgentMemoryContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(prefix='qa-aaas-agent-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'company'
        self.root.mkdir()
        self.book=self.root/'standalone-accounting.sqlite3'
        self.book.write_bytes(b'QA-LEDGER-READONLY-CANARY')
        self.before=hashlib.sha256(self.book.read_bytes()).hexdigest()
        self.orders=TarazOrderStore(self.root)
        self.memory=CompanyAgentMemory(self.root)
        self.api=AuthenticatedQaTarazAPI(self.root,Identity())
        self.order=self.orders.command({
            'action':'create','idempotencyKey':secrets.token_hex(16),
            'orderId':'','expectedRevision':0,'data':passport(),
            'nextStatus':None,'manualConfirmation':False,
        },actor='qa-invoice-operator',role='admin')

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.book.read_bytes()).hexdigest(),self.before)

    def req(self,action,text=None,entry_id=None,expected=0,key=None,
            confirmation=None,source_revision=None):
        return {'action':action,'text':text,'entryId':entry_id,
            'orderId':self.order['id'],
            'sourceRevision':self.order['revision'] if source_revision is None else source_revision,
            'expectedMemoryRevision':expected,
            'idempotencyKey':key or secrets.token_hex(16),
            'manualConfirmation':action!='propose' if confirmation is None else confirmation}

    def test_tool_review_has_real_source_revision_and_no_memory_file_on_read(self):
        review=self.api.tarazAgentOrderReview(self.order['id'])
        self.assertEqual(review['source'],'REAL_SQLITE_TOOLS')
        self.assertEqual([t['tool'] for t in review['toolTrace']],
                         ['order.get','memory.list'])
        self.assertFalse(review['modelRan'])
        self.assertEqual(review['facts']['quantity'],100)
        self.assertIsNone(review['facts']['approvedActualCostTotal'])
        self.assertIn('review_actual_costs',
                      [a['action'] for a in review['recommendations']])
        self.assertFalse(self.memory.path.exists())
        self.assertFalse(review['financialEventCreated'])

    def test_human_review_is_persistent_versioned_rejectable_and_idempotent(self):
        key=secrets.token_hex(16)
        cmd=self.req('propose',text='هزینه واقعی چاپ را از رسید بررسی کنید',
                     key=key)
        proposal=self.api.tarazAgentMemoryCommand(cmd)
        self.assertEqual(proposal['status'],'proposed')
        self.assertEqual(self.api.tarazAgentMemoryCommand(cmd),proposal)
        with self.assertRaises(AgentMemoryError):
            self.api.tarazAgentMemoryCommand(self.req('propose',text=cmd['text'],
                expected=1))
        memory=self.api.tarazAgentMemoryList(self.order['id'])
        self.assertEqual(memory['revision'],1)
        self.assertEqual(memory['entries'][0]['created_by'],'qa-invoice-operator')
        checked=self.api.tarazAgentMemoryCommand(self.req(
            'accept',entry_id=proposal['id'],expected=1))
        self.assertEqual(checked['status'],'accepted')
        again=CompanyAgentMemory(self.root).list(self.order['id'])
        self.assertEqual(again['entries'][0]['status'],'accepted')
        self.assertEqual(again['entries'][0]['reviewed_by'],'qa-invoice-operator')
        review=review_order_tools(self.root,self.order['id'])
        self.assertEqual(len(review['acceptedMemory']),1)
        self.assertTrue(review['requiresHumanApproval'])
        self.assertEqual(self.orders.get(self.order['id'])['revision'],1)
        self.assertFalse(review['financialEventCreated'])
        with self.assertRaises(AgentMemoryError):
            self.api.tarazAgentMemoryCommand(self.req(
                'reject',entry_id=proposal['id'],expected=2))

    def test_forged_confirmation_stale_revision_and_roles_fail_closed(self):
        proposal=self.memory.command(self.req('propose',text='پیگیری تأمین'),
                                     actor='qa-operator',role='editor')
        for role in ('viewer','fake','editor'):
            with self.assertRaises(PermissionError):
                self.memory.command(self.req('accept',entry_id=proposal['id'],
                     expected=1),actor='qa-operator',role=role)
        with self.assertRaises(PermissionError):
            self.memory.command(self.req('accept',entry_id=proposal['id'],
                 expected=1,confirmation=False),actor='qa-admin',role='admin')
        with self.assertRaises(AgentMemoryError):
            self.memory.command(self.req('accept',entry_id=proposal['id'],
                 expected=0),actor='qa-admin',role='admin')
        changed=passport()
        changed['notes']='after recommendation'
        self.order=self.orders.command({
            'action':'update','idempotencyKey':secrets.token_hex(16),
            'orderId':self.order['id'],'expectedRevision':1,'data':changed,
            'nextStatus':None,'manualConfirmation':False,
        },actor='qa-admin',role='admin')
        with self.assertRaises(OrderConflict):
            self.memory.command(self.req('accept',entry_id=proposal['id'],
                 expected=1),actor='qa-admin',role='admin')
        self.assertEqual(self.memory.list(self.order['id'])['entries'][0]['status'],
                         'proposed')
        self.assertEqual(review_order_tools(self.root,self.order['id'])['acceptedMemory'],[])


if __name__=='__main__':
    unittest.main()
