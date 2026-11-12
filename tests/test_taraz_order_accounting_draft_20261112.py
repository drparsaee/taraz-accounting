"""Real authenticated TarazAPI → operational order SQLite → accounting DRAFT SQLite.

Disposable company only. Official issue, journal posting and bank APIs forbidden.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import secrets
import subprocess
import sys
import unittest

from tests.taraz_p1_real_backend_http_fixture_20261112 import (
    AuthenticatedQaTarazAPI, Identity,
)
from tests.test_taraz_order_finance_20261112 import passport, STAGES
from taraz_order_store import TarazOrderStore, OrderConflict


class OrderToAccountingDraftTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(prefix="qa-order-draft-ledger-")
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/"company"
        self.root.mkdir()
        self.identity=Identity()
        self.api=AuthenticatedQaTarazAPI(self.root,self.identity)
        self.store=TarazOrderStore(self.root)

    def cmd(self, action, row=None, data=None, confirm=False, status=None,role="admin"):
        return self.store.command({
            "action":action,"idempotencyKey":secrets.token_hex(16),
            "orderId":row["id"] if row else "",
            "expectedRevision":row["revision"] if row else 0,
            "data":data,"nextStatus":status,"manualConfirmation":confirm,
        },actor="qa-invoice-operator",role=role)

    def prepared(self, currency="RIAL", register=True):
        initial=self.api.standaloneAccountingRead()
        self.assertEqual(initial["revision"],0)
        if register:
            self.api.standaloneAccountingCommand({
                "expectedRevision":0,
                "command":{"type":"party.register","eventId":"QA-PARTY-BRIDGE",
                           "partyId":"QA-CUSTOMER-1","name":"مشتری آزمایشی",
                           "kind":"customer"}})
        data=passport()
        data["currency"]=currency
        data["costStages"]=data["costStages"][:1]
        row=self.cmd("create",data=data)
        row=self.cmd("cost.record",row,{
            "stageIndex":0,"actualCost":200000,"costDate":"2026-11-12",
            "receiptReference":"QA-COST-01"})
        row=self.cmd("cost.approve",row,{"stageIndex":0},confirm=True)
        row=self.cmd("payment.record",row,{
            "direction":"incoming","amount":2500000,"paymentDate":"2026-11-12",
            "party":"مشتری آزمایشی","method":"manual-confirmed",
            "transactionReference":"","status":"recorded"})
        row=self.cmd("payment.settle",row,{
            "paymentId":row["payments"][0]["id"],
            "transactionReference":"QA-BANK-WITNESS"},confirm=True)
        row=self.cmd("transition",row,confirm=True,status="approved")
        row=self.cmd("transition",row,confirm=True,status="in_production")
        measured=dict(data,actualProducedQuantity=120,scrapQuantity=5,
                      healthySurplusQuantity=15)
        row=self.cmd("update",row,data=measured,confirm=True)
        row=self.cmd("transition",row,confirm=True,status="delivered")
        self.assertTrue(row["financialHandoffReady"])
        row=self.cmd("handoff.prepare",row,{
            "previewDigest":row["financialPreview"]["previewDigest"]},confirm=True)
        self.assertIsNotNone(row["financeHandoff"])
        return row

    def payload(self,row,expected_accounting_revision):
        return {"orderId":row["id"],"expectedOrderRevision":row["revision"],
                "expectedAccountingRevision":expected_accounting_revision,
                "previewDigest":row["financeHandoff"]["preview_digest"],
                "documentDate":"2026-11-12","explicitConfirmation":True}

    def test_real_draft_created_no_journal_then_idempotent_reread(self):
        row=self.prepared()
        before=self.api.standaloneAccountingRead()
        self.assertEqual(len(before["view"]["journals"]),0)
        produced=self.api.tarazOrderFinanceDraft(self.payload(row,before["revision"]))
        self.assertEqual(produced["status"],"DRAFT_CREATED")
        self.assertFalse(produced["financialDocumentIssued"])
        new_api=AuthenticatedQaTarazAPI(self.root,Identity())
        state=new_api.standaloneAccountingRead()
        invoice=state["view"]["invoices"][produced["documentId"]]
        self.assertEqual(invoice["status"],"draft")
        self.assertEqual(invoice["total"],2500000)
        self.assertEqual(invoice["sourceType"],"taraz.order")
        self.assertEqual(invoice["sourceId"],row["id"])
        self.assertEqual(invoice["number"],None)
        self.assertEqual(invoice["postedEntryId"],None)
        self.assertEqual(state["view"]["journals"],[])
        again=new_api.tarazOrderFinanceDraft(self.payload(row,before["revision"]))
        self.assertEqual(again["status"],"ALREADY_DRAFT")
        self.assertEqual(new_api.standaloneAccountingRead()["revision"],state["revision"])
        with self.assertRaises(OrderConflict):
            self.cmd("cost.record",row,{
                "stageIndex":0,"actualCost":300000,"costDate":"2026-11-12",
                "receiptReference":"QA-MUTATION-AFTER-FREEZE"})

    def test_missing_actual_customer_refuses_accounting_write(self):
        row=self.prepared(register=False)
        with self.assertRaises(ValueError):
            self.api.tarazOrderFinanceDraft(self.payload(row,0))
        self.assertEqual(self.api.standaloneAccountingRead()["revision"],0)

    def test_currency_mismatch_and_fake_confirmation_fail_closed(self):
        row=self.prepared(currency="TOMAN")
        request=self.payload(row,1)
        with self.assertRaises(ValueError):
            self.api.tarazOrderFinanceDraft(request)
        self.assertEqual(self.api.standaloneAccountingRead()["revision"],1)
        request["explicitConfirmation"]=False
        with self.assertRaises(PermissionError):
            self.api.tarazOrderFinanceDraft(request)
        self.assertEqual(self.api.standaloneAccountingRead()["view"]["journals"],[])

    def test_purchase_vendor_creates_only_idempotent_expense_bill_draft(self):
        self.api.standaloneAccountingCommand({
            "expectedRevision":0,
            "command":{"type":"party.register","eventId":"QA-VENDOR-REGISTER",
                       "partyId":"QA-VENDOR-1","name":"تأمین‌کننده آزمایشی",
                       "kind":"vendor"}})
        data=passport()
        data.update(kind="purchase", customerId="QA-VENDOR-1",
                    customerName="تأمین‌کننده آزمایشی",
                    costStages=data["costStages"][:1])
        row=self.cmd("create",data=data)
        row=self.cmd("cost.record",row,{
            "stageIndex":0,"actualCost":220000,"costDate":"2026-11-12",
            "receiptReference":"QA-VENDOR-COST-01"})
        row=self.cmd("cost.approve",row,{"stageIndex":0},confirm=True)
        row=self.cmd("payment.record",row,{
            "direction":"outgoing","amount":2500000,"paymentDate":"2026-11-12",
            "party":"تأمین‌کننده آزمایشی","method":"manual-confirmed",
            "transactionReference":"","status":"recorded"})
        row=self.cmd("payment.settle",row,{
            "paymentId":row["payments"][0]["id"],
            "transactionReference":"QA-VENDOR-WITNESS"},confirm=True)
        row=self.cmd("transition",row,status="approved",confirm=True)
        row=self.cmd("transition",row,status="in_production",confirm=True)
        row=self.cmd("update",row,data=dict(data,actualProducedQuantity=120,
                                           scrapQuantity=5,healthySurplusQuantity=15),
                     confirm=True)
        row=self.cmd("transition",row,status="delivered",confirm=True)
        self.assertEqual(row["paymentBalance"],0)
        self.assertIsNone(row["realizedProfit"])
        self.assertTrue(row["financialHandoffReady"])
        row=self.cmd("handoff.prepare",row,{
            "previewDigest":row["financialPreview"]["previewDigest"]},
            confirm=True)
        before=self.api.standaloneAccountingRead()
        made=self.api.tarazOrderFinanceDraft(self.payload(row,before["revision"]))
        self.assertEqual(made["status"],"DRAFT_CREATED")
        reloaded=AuthenticatedQaTarazAPI(self.root,Identity())
        state=reloaded.standaloneAccountingRead()
        bill=state["view"]["bills"][made["documentId"]]
        self.assertEqual(bill["status"],"draft")
        self.assertEqual(bill["total"],2500000)
        self.assertEqual(bill["partyId"],"QA-VENDOR-1")
        self.assertEqual(bill["sourceType"],"taraz.order")
        self.assertEqual(bill["sourceId"],row["id"])
        self.assertEqual(bill["lines"][0]["accountId"],"5000")
        self.assertIsNone(bill["postedEntryId"])
        self.assertEqual(state["view"]["invoices"],{})
        self.assertEqual(state["view"]["journals"],[])
        replay=reloaded.tarazOrderFinanceDraft(self.payload(row,before["revision"]))
        self.assertEqual(replay["status"],"ALREADY_DRAFT")
        self.assertEqual(reloaded.standaloneAccountingRead()["revision"],
                         state["revision"])

    def test_six_stage_passport_full_settlement_survives_new_process(self):
        self.api.standaloneAccountingCommand({
            'expectedRevision':0,
            'command':{'type':'party.register','eventId':'QA-PASSPORT-6-STAGES',
                       'partyId':'QA-CUSTOMER-1','name':'مشتری آزمایشی',
                       'kind':'customer'}})
        data=passport()
        row=self.cmd('create',data=data)
        self.assertIsNone(row['actualCostTotal'])
        for index,(_,_,actual) in enumerate(STAGES):
            row=self.cmd('cost.record',row,{
                'stageIndex':index,'actualCost':actual,
                'costDate':'2026-11-12','receiptReference':f'QA-RECEIPT-{index}'})
            row=self.cmd('cost.approve',row,{'stageIndex':index},confirm=True)
        self.assertEqual(row['actualCostTotal'],665000)
        for index,amount in enumerate((500000,2000000)):
            row=self.cmd('payment.record',row,{
                'direction':'incoming','amount':amount,
                'paymentDate':'2026-11-12','party':'مشتری آزمایشی',
                'method':'manual-confirmed','transactionReference':'',
                'status':'recorded'})
            row=self.cmd('payment.settle',row,{
                'paymentId':row['payments'][index]['id'],
                'transactionReference':f'QA-NONBANK-{index}'},confirm=True)
        self.assertEqual(row['paymentBalance'],0)
        row=self.cmd('transition',row,confirm=True,status='approved')
        row=self.cmd('transition',row,confirm=True,status='in_production')
        row=self.cmd('update',row,confirm=True,data=dict(
            data,actualProducedQuantity=120,scrapQuantity=5,
            healthySurplusQuantity=15))
        row=self.cmd('transition',row,confirm=True,status='delivered')
        self.assertEqual(row['productionReconciliation']['state'],'balanced')
        self.assertEqual(row['realizedProfit'],1835000)
        row=self.cmd('handoff.prepare',row,{
            'previewDigest':row['financialPreview']['previewDigest']},confirm=True)
        accounting_before=self.api.standaloneAccountingRead()
        saved=self.api.tarazOrderFinanceDraft(
            self.payload(row,accounting_before['revision']))
        self.assertEqual(saved['status'],'DRAFT_CREATED')
        # Separate Python process is a real SQLite reopen, not an in-memory
        # mock or a new object that accidentally shares the original handle.
        script="""
import json,sys
from pathlib import Path
from taraz_order_store import TarazOrderStore
from tests.taraz_p1_real_backend_http_fixture_20261112 import AuthenticatedQaTarazAPI,Identity
root=Path(sys.argv[1]); order=TarazOrderStore(root).get(sys.argv[2])
state=AuthenticatedQaTarazAPI(root,Identity()).standaloneAccountingRead()
invoice=state['view']['invoices'][sys.argv[3]]
print(json.dumps({'id':order['id'],'revision':order['revision'],
  'costCount':len(order['costRecords']),'actual':order['actualCostTotal'],
  'settled':order['settledPaymentTotal'],'balance':order['paymentBalance'],
  'scrap':order['scrapQuantity'],'surplus':order['healthySurplusQuantity'],
  'auditCount':len(order['auditTrail']),'status':order['status'],
  'invoiceStatus':invoice['status'],'invoiceSourceId':invoice['sourceId'],
  'invoicePostedEntry':invoice['postedEntryId'],'journalCount':len(state['view']['journals'])}))
"""
        output=subprocess.run([
            sys.executable,'-B','-c',script,str(self.root),row['id'],
            saved['documentId']],cwd=str(Path(__file__).resolve().parents[1]),
            check=False,capture_output=True,text=True)
        self.assertEqual(output.returncode,0,output.stderr[:250])
        persisted=json.loads(output.stdout)
        self.assertEqual((persisted['id'],persisted['revision']),
                         (row['id'],row['revision']))
        self.assertEqual((persisted['costCount'],persisted['actual']), (6,665000))
        self.assertEqual((persisted['settled'],persisted['balance']),
                         (2500000,0))
        self.assertEqual((persisted['scrap'],persisted['surplus']),(5,15))
        self.assertEqual(persisted['auditCount'],row['revision'])
        self.assertEqual((persisted['invoiceStatus'],persisted['invoiceSourceId']),
                         ('draft',row['id']))
        self.assertIsNone(persisted['invoicePostedEntry'])
        self.assertEqual(persisted['journalCount'],0)


if __name__ == "__main__":
    unittest.main()
