"""Independent source-side product QA, not a frozen EXE acceptance certificate.

Fresh scenarios, independent raw SQLite assertions and synthetic-only books.
The 5 acceptance axes are evaluated without relying on implementer test claims.
Host deployment, model autonomy, print hardware and frozen UI are intentionally
NOT marked PASS by this module.
"""
from copy import deepcopy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from standalone_accounting import AccountingRevisionConflict
from taraz_aaas_agent import CompanyAgentMemory
from taraz_madar_order_sync import (
    prepare_madar_order_state, extract_madar_order_stage_progress,
)
from taraz_order_store import TarazOrderStore, OrderConflict
from tests.taraz_p1_real_backend_http_fixture_20261112 import (
    AuthenticatedQaTarazAPI, Identity,
)


STAGES = (
    ('print', 210000), ('bindery', 115000), ('sewing', 95000),
    ('laser', 80000), ('packaging', 90000), ('shipping', 75000),
)


def synthetic_order():
    return {
        'kind':'sale','customerId':'QA-FINAL-CUSTOMER',
        'customerName':'مشتری کنترل نهایی','title':'دفترچه ۱۰۰ عددی آزمایشی',
        'description':'فقط داده ساختگی و غیرعملیاتی','unit':'عدد',
        'quantity':100,'productionQuantity':120,
        'actualProducedQuantity':None,'scrapQuantity':None,
        'healthySurplusQuantity':None,'unitPrice':25000,'currency':'RIAL',
        'costStages':[{'kind':kind,'supplier':'پیمانکار ساختگی',
                       'description':kind,'estimatedCost':actual+1000}
                      for kind,actual in STAGES],
        'notes':'INDEPENDENT_QA_ONLY','projectReference':'QA-PRJ-A',
        'scheduleStartDate':'2026-11-12','scheduleDueDate':'2026-11-19',
        'procurementNotes':'',
    }


class IndependentProductAcceptance(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory(prefix='qa-independent-taraz-final-')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.one=self.root/'companyA'
        self.other=self.root/'companyB'
        self.one.mkdir();self.other.mkdir()
        self.api=AuthenticatedQaTarazAPI(self.one,Identity())
        self.store=TarazOrderStore(self.one)
        self.row=None
        self.ledger=self.one/'standalone-accounting.sqlite3'

    def cmd(self,action,data=None,*,confirm=False,status=None,role='admin'):
        request={'action':action,'idempotencyKey':secrets.token_hex(16),
                 'orderId':self.row['id'] if self.row else '',
                 'expectedRevision':self.row['revision'] if self.row else 0,
                 'data':data,'nextStatus':status,'manualConfirmation':confirm}
        self.row=self.store.command(
            request,actor='qa-final-reviewer',role=role)
        return self.row

    def accounting(self,command,revision=None):
        if revision is None:
            revision=self.api.standaloneAccountingRead()['revision']
        return self.api.standaloneAccountingCommand({
            'expectedRevision':revision,'command':command})

    def create_order(self):
        self.cmd('create',synthetic_order())
        return self.row

    def test_axis_one_invoice_and_proforma_create_edit_reopen_without_posting(self):
        self.accounting({'type':'party.register','eventId':'qa-independent-party',
                         'partyId':'QA-FINAL-CUSTOMER','name':'مشتری آزمون',
                         'kind':'customer'})
        invoice={'type':'invoice.create','eventId':'qa-independent-invoice',
                 'invoiceId':'QA-INV-FINAL','partyId':'QA-FINAL-CUSTOMER',
                 'documentDate':'2026-11-12',
                 'lines':[{'description':'چاپ نمونه','quantity':100,'unitPrice':1600}]}
        self.accounting(invoice)
        proforma={'type':'proforma.create','eventId':'qa-independent-proforma',
                  'proformaId':'QA-PRO-FINAL','partyId':'QA-FINAL-CUSTOMER',
                  'documentDate':'2026-11-12',
                  'lines':[{'description':'بسته بندی نمونه',
                            'quantity':20,'unitPrice':500}]}
        self.accounting(proforma)
        reopened=AuthenticatedQaTarazAPI(self.one,Identity())
        before=reopened.standaloneAccountingRead()
        self.assertEqual(set(before['view']['invoices']),{'QA-INV-FINAL'})
        self.assertEqual(set(before['view']['proformas']),{'QA-PRO-FINAL'})
        revised=deepcopy(invoice)
        revised.update(type='invoice.update',eventId='qa-independent-invoice-edit')
        revised['lines'][0]['quantity']=110
        reopened.standaloneAccountingCommand({
            'expectedRevision':before['revision'],'command':revised})
        after=AuthenticatedQaTarazAPI(self.one,Identity()).standaloneAccountingRead()
        record=after['view']['invoices']['QA-INV-FINAL']
        self.assertEqual(record['lines'][0]['quantity'],110)
        self.assertEqual(record['total'],176000)
        self.assertEqual(record['status'],'draft')
        self.assertIsNone(record['number'])
        self.assertIsNone(record['postedEntryId'])
        self.assertEqual(after['view']['proformas']['QA-PRO-FINAL']['status'],'draft')
        self.assertEqual(after['view']['journals'],[])
        with self.assertRaises(AccountingRevisionConflict):
            self.accounting({'type':'party.register','eventId':'qa-stale-write',
                             'partyId':'QA-STALE','name':'نباید ثبت شود',
                             'kind':'customer'},revision=0)
        self.assertNotIn('QA-STALE',
            AuthenticatedQaTarazAPI(self.one,Identity()).standaloneAccountingRead()['view']['parties'])

    def test_axis_two_real_six_stage_cost_partial_settlement_reopen_and_draft(self):
        self.accounting({'type':'party.register','eventId':'qa-order-party',
                         'partyId':'QA-FINAL-CUSTOMER','name':'مشتری آزمون',
                         'kind':'customer'})
        self.create_order()
        initial_id=self.row['id']
        for index,(_,actual) in enumerate(STAGES):
            self.cmd('cost.record',{'stageIndex':index,'actualCost':actual,
                'costDate':'2026-11-12','receiptReference':'QA-COST-'+str(index)})
            self.cmd('cost.approve',{'stageIndex':index},confirm=True)
        self.assertEqual(self.row['actualCostTotal'],sum(x[1] for x in STAGES))
        for index,amount in enumerate((500000,2000000)):
            self.cmd('payment.record',{'direction':'incoming','amount':amount,
                'paymentDate':'2026-11-12','party':'مشتری آزمون',
                'method':'manual-confirmed','transactionReference':'',
                'status':'recorded'})
            self.cmd('payment.settle',{
                'paymentId':self.row['payments'][index]['id'],
                'transactionReference':'QA-FAKE-SETTLEMENT-'+str(index)},confirm=True)
        self.cmd('transition',confirm=True,status='approved')
        self.cmd('transition',confirm=True,status='in_production')
        measurements=synthetic_order()
        measurements.update(actualProducedQuantity=120,scrapQuantity=5,
                            healthySurplusQuantity=15)
        self.cmd('update',measurements,confirm=True)
        self.cmd('transition',confirm=True,status='delivered')
        self.assertEqual(self.row['paymentBalance'],0)
        self.assertEqual(self.row['productionReconciliation']['state'],'balanced')
        self.cmd('handoff.prepare',{'previewDigest':
            self.row['financialPreview']['previewDigest']},confirm=True)
        state=self.api.standaloneAccountingRead()
        finance=self.api.tarazOrderFinanceDraft({
            'orderId':initial_id,'expectedOrderRevision':self.row['revision'],
            'expectedAccountingRevision':state['revision'],
            'previewDigest':self.row['financeHandoff']['preview_digest'],
            'documentDate':'2026-11-12','explicitConfirmation':True})
        self.assertEqual(finance['status'],'DRAFT_CREATED')
        # Independent raw SQLite examination does NOT use the domain display.
        with closing(sqlite3.connect(str(self.store.file))) as db:
            row=db.execute('select id,revision,status from orders').fetchone()
            costs=db.execute('select count(*),sum(actual_cost) from order_costs').fetchone()
            payments=db.execute('select count(*),sum(amount) from order_payments'
                                ' where status=?',('settled',)).fetchone()
            trail=db.execute('select count(*) from audit').fetchone()[0]
        self.assertEqual((row[0],row[1],row[2]),
                         (initial_id,self.row['revision'],'delivered'))
        self.assertEqual(costs,(6,sum(x[1] for x in STAGES)))
        self.assertEqual(payments,(2,2500000))
        self.assertEqual(trail,self.row['revision'])
        disk=TarazOrderStore(self.one).get(initial_id)
        self.assertEqual((disk['quantity'],disk['productionQuantity'],
                          disk['actualProducedQuantity'],disk['scrapQuantity'],
                          disk['healthySurplusQuantity']), (100,120,120,5,15))
        final=AuthenticatedQaTarazAPI(self.one,Identity()).standaloneAccountingRead()
        self.assertEqual(final['view']['journals'],[])
        self.assertEqual(final['view']['invoices'][finance['documentId']]['status'],'draft')
        self.assertIsNone(final['view']['invoices'][finance['documentId']]['postedEntryId'])

    def test_axis_three_natural_request_memory_review_and_company_acl(self):
        self.create_order()
        first=self.api.tarazAgentNaturalRequest(
            self.row['id'],'در مورد پرت واقعی و مازاد تولید این سفارش گزارش بده')
        self.assertEqual(first['sourceRevision'],1)
        self.assertEqual(first['inference'],'RULE_BASED_FALLBACK')
        self.assertFalse(first['modelRan'])
        self.assertFalse(first['financialEventCreated'])
        self.assertTrue(first['editableProposal'])
        proposed=self.api.tarazAgentMemoryCommand({
            'action':'propose','orderId':self.row['id'],
            'sourceRevision':1,'expectedMemoryRevision':0,
            'text':first['editableProposal'],'entryId':None,
            'idempotencyKey':secrets.token_hex(16),'manualConfirmation':False})
        with self.assertRaises(PermissionError):
            CompanyAgentMemory(self.one).command({
                'action':'accept','orderId':self.row['id'],
                'sourceRevision':1,'expectedMemoryRevision':1,
                'text':None,'entryId':proposed['id'],
                'idempotencyKey':secrets.token_hex(16),
                'manualConfirmation':True
            },actor='qa-unprivileged',role='viewer')
        approved=self.api.tarazAgentMemoryCommand({
            'action':'accept','orderId':self.row['id'],
            'sourceRevision':1,'expectedMemoryRevision':1,
            'text':None,'entryId':proposed['id'],
            'idempotencyKey':secrets.token_hex(16),'manualConfirmation':True})
        self.assertEqual(approved['status'],'accepted')
        self.assertEqual(CompanyAgentMemory(self.one).list(
            self.row['id'])['revision'],2)
        self.assertEqual(TarazOrderStore(self.one).get(self.row['id'])['revision'],1)
        with self.assertRaises(OrderConflict):
            AuthenticatedQaTarazAPI(self.other,Identity()).tarazAgentNaturalRequest(
                self.row['id'],'همین سفارش را نشان بده')

    def test_axis_four_madar_source_identity_manual_edit_and_duplicate_barriers(self):
        self.create_order()
        madar={'version':1,'projects':[{'id':'QA-PRJ-A','name':'Test project'}],
               'tasks':[],'stages':[{'id':'planned','label':'Backlog'}],
               'settings':{'priorityDefinitions':[{'id':'medium'}]},
               'handWritten':'do not overwrite'}
        original=json.dumps(madar,ensure_ascii=False,sort_keys=True)
        candidate,task,status=prepare_madar_order_state(
            madar,order=self.row,project_id='QA-PRJ-A')
        self.assertEqual(status,'NEW_TASK')
        self.assertEqual(json.dumps(madar,ensure_ascii=False,sort_keys=True),original)
        task['checklist'][0]['done']=True
        task['title']='مدیر مدار دستی ویرایش کرده'
        candidate['tasks'][0]['description']='Manual Madar description'
        progress=extract_madar_order_stage_progress(
            candidate,order=self.row,project_id='QA-PRJ-A')
        self.assertEqual(progress['completedStages'],1)
        self.assertTrue(progress['readOnly'])
        self.assertFalse(progress['financialEventCreated'])
        self.assertEqual(candidate['tasks'][0]['description'],'Manual Madar description')
        self.assertEqual(candidate['handWritten'],'do not overwrite')
        # Same source revision must be a no-op: manual fields remain intact.
        before_replay=json.dumps(candidate,ensure_ascii=False,sort_keys=True)
        next_state,existing,again=prepare_madar_order_state(
            candidate,order=self.row,project_id='QA-PRJ-A')
        self.assertEqual(again,'ALREADY_SYNCED')
        self.assertIsNone(next_state)
        self.assertEqual(existing['description'],'Manual Madar description')
        self.assertEqual(json.dumps(candidate,ensure_ascii=False,sort_keys=True),
                         before_replay)
        # Source changes are not auto-reconciled over a human-edited task.
        changed=deepcopy(self.row)
        changed['revision']+=1
        from taraz_madar_data_reader import MadarReadError
        with self.assertRaises(MadarReadError):
            prepare_madar_order_state(
                candidate,order=changed,project_id='QA-PRJ-A')
        self.assertFalse((self.one/'taraz-madar-order-links.sqlite3').exists())

    def test_axis_five_access_boundaries_restart_and_no_implicit_finance(self):
        row=self.create_order()
        before=self.api.standaloneAccountingRead()
        self.assertEqual(before['view']['journals'],[])
        with self.assertRaises(PermissionError):
            self.store.command({
                'action':'cost.approve','idempotencyKey':secrets.token_hex(16),
                'orderId':row['id'],'expectedRevision':row['revision'],
                'data':{'stageIndex':0},'nextStatus':None,
                'manualConfirmation':True,
            },actor='qa-viewer',role='viewer')
        with self.assertRaises(OrderConflict):
            self.store.command({
                'action':'update','idempotencyKey':secrets.token_hex(16),
                'orderId':row['id'],'expectedRevision':99,
                'data':synthetic_order(),'nextStatus':None,
                'manualConfirmation':False,
            },actor='qa-editor',role='editor')
        fresh=AuthenticatedQaTarazAPI(self.one,Identity())
        self.assertEqual(fresh.tarazOrderList(0,10)['total'],1)
        self.assertFalse(TarazOrderStore(self.other).list()['orders'])
        after=fresh.standaloneAccountingRead()
        self.assertEqual((after['revision'],after['view']['journals']),
                         (before['revision'],[]))
        self.assertEqual(TarazOrderStore(self.one).get(
            row['id'])['revision'],row['revision'])


if __name__=='__main__':
    unittest.main()
