"""Actual disposable SQLite order financial-control regression; no bank or ledger."""
import hashlib
import json
import secrets
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from taraz_order_store import OrderConflict, OrderError, TarazOrderStore


STAGES = [
    ("print", 200_000, 220_000),
    ("bindery", 100_000, 110_000),
    ("sewing", 100_000, 90_000),
    ("laser", 80_000, 85_000),
    ("packaging", 90_000, 95_000),
    ("shipping", 60_000, 65_000),
]


def passport():
    return {
        "kind": "sale", "customerId": "QA-CUSTOMER-1",
        "customerName": "مشتری آزمایشی", "title": "پاسپورت چاپی",
        "description": "نمونه غیرواقعی", "unit": "عدد",
        "quantity": 100, "productionQuantity": 120,
        "actualProducedQuantity": None, "scrapQuantity": None,
        "healthySurplusQuantity": None, "unitPrice": 25_000, "currency": "RIAL",
        "costStages": [{"kind": name, "supplier": "تأمین‌کننده آزمایشی",
                        "description": name, "estimatedCost": estimated}
                       for name, estimated, _ in STAGES],
        "notes": "QA only", "projectReference": "MADAR-QA-1",
        "scheduleStartDate": "2026-11-12",
        "scheduleDueDate": "2026-11-19", "procurementNotes": "",
    }


class RealOrderFinanceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="taraz-orders-real-sqlite-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "company").mkdir()
        self.company = self.root / "company"
        self.book = self.company / "standalone-accounting.sqlite3"
        self.book.write_bytes(b"QA-NO-FINANCIAL-LEDGER-CONTENT")
        self.baseline = hashlib.sha256(self.book.read_bytes()).hexdigest()
        self.store = TarazOrderStore(self.company)

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.book.read_bytes()).hexdigest(), self.baseline)

    def call(self, action, order=None, data=None, role="editor", confirm=False,
             key=None, revision=None, status=None):
        return self.store.command({
            "action": action, "idempotencyKey": key or secrets.token_hex(16),
            "orderId": order["id"] if order else "",
            "expectedRevision": (order["revision"] if revision is None else revision)
                               if order else 0,
            "data": data, "nextStatus": status, "manualConfirmation": confirm,
        }, actor="qa-finance", role=role)

    def test_passport_all_stages_partial_settlement_and_human_handoff(self):
        order = self.call("create", data=passport())
        self.assertEqual(order["status"], "draft")
        self.assertIsNone(order["actualCostTotal"])
        self.assertEqual(order["estimatedCostTotal"], 630_000)
        self.assertEqual(order["paymentBalance"], 2_500_000)
        for i, (_, _, actual) in enumerate(STAGES):
            order = self.call("cost.record", order, {
                "stageIndex": i, "actualCost": actual,
                "costDate": "2026-11-12", "receiptReference": "QA-COST-" + str(i),
            })
            self.assertIsNone(order["actualCostTotal"])
            with self.assertRaises(PermissionError):
                self.call("cost.approve", order, {"stageIndex": i}, confirm=True)
            order = self.call("cost.approve", order, {"stageIndex": i},
                              role="admin", confirm=True)
        actual_total = sum(stage[2] for stage in STAGES)
        self.assertEqual(order["actualCostTotal"], actual_total)
        self.assertIsNone(order["realizedProfit"])
        first = self.call("payment.record", order, {
            "direction": "incoming", "amount": 500_000, "paymentDate": "2026-11-12",
            "party": "مشتری آزمایشی", "method": "bank-transfer",
            "transactionReference": "", "status": "recorded",
        })
        first_payment = first["payments"][0]["id"]
        self.assertEqual(first["paymentBalance"], 2_500_000)
        with self.assertRaises(PermissionError):
            self.call("payment.settle", first, {
                "paymentId": first_payment, "transactionReference": "QA-TRX-1",
            }, confirm=True)
        order = self.call("payment.settle", first, {
            "paymentId": first_payment, "transactionReference": "QA-TRX-1",
        }, role="admin", confirm=True)
        self.assertEqual(order["paymentBalance"], 2_000_000)
        second = self.call("payment.record", order, {
            "direction": "incoming", "amount": 2_000_000, "paymentDate": "2026-11-13",
            "party": "مشتری آزمایشی", "method": "",
            "transactionReference": "", "status": "planned",
        })
        second_payment = second["payments"][1]["id"]
        with self.assertRaises(OrderConflict):
            self.call("payment.settle", second, {
                "paymentId": second_payment, "transactionReference": "QA-TRX-2",
            }, role="admin", confirm=True)
        order = self.call("payment.confirm", second, {
            "paymentId": second_payment, "method": "bank-transfer",
            "transactionReference": "",
        })
        order = self.call("payment.settle", order, {
            "paymentId": second_payment, "transactionReference": "QA-TRX-2",
        }, role="admin", confirm=True)
        self.assertEqual((order["settledPaymentTotal"], order["paymentBalance"]),
                         (2_500_000, 0))
        with self.assertRaises(PermissionError):
            self.call("transition", order, status="approved", confirm=True)
        order = self.call("transition", order, status="approved",
                          confirm=True, role="admin")
        order = self.call("transition", order, status="in_production", confirm=True)
        measured = passport()
        measured.update(actualProducedQuantity=120, scrapQuantity=5,
                        healthySurplusQuantity=15)
        order = self.call("update", order, data=measured, confirm=True)
        self.assertEqual(order["productionReconciliation"]["state"], "balanced")
        order = self.call("transition", order, status="delivered", confirm=True,
                          role="admin")
        self.assertEqual(order["realizedProfit"], 2_500_000 - actual_total)
        self.assertTrue(order["financialHandoffReady"])
        self.assertFalse(order["financialPreview"]["createsAccountingDocument"])
        with self.assertRaises(PermissionError):
            self.call("handoff.prepare", order,
                      {"previewDigest": order["financialPreview"]["previewDigest"]},
                      confirm=True)
        key = secrets.token_hex(16)
        payload = {"previewDigest":order["financialPreview"]["previewDigest"]}
        prepared = self.call("handoff.prepare", order, payload, role="admin",
                             confirm=True, key=key)
        self.assertTrue(prepared["financeHandoff"])
        self.assertFalse(prepared["financialEventCreated"])
        self.assertEqual(len(TarazOrderStore(self.company).list()["orders"]), 1)
        latest = TarazOrderStore(self.company).list()["orders"][0]
        self.assertEqual(latest["productionReconciliation"]["balanceQuantity"], 0)
        self.assertEqual(len(latest["auditTrail"]), latest["revision"])
        self.assertEqual(latest["financeHandoff"]["prepared_by"], "qa-finance")
        self.assertEqual(latest["status"], "delivered")
        self.assertFalse(latest["financialEventCreated"])

    def test_migration_old_records_and_safe_rollback(self):
        initial = self.call("create", data=passport())
        conn = sqlite3.connect(self.store.file)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
        finally:
            conn.close()
        self.assertTrue(self.store.rollback_empty_migration())
        conn = sqlite3.connect(self.store.file)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
        finally:
            conn.close()
        legacy = TarazOrderStore(self.company).list()["orders"][0]
        self.assertEqual(legacy["quantity"], 100)
        self.assertEqual(legacy["financialEventCreated"], False)
        self.assertIsNone(legacy["actualCostTotal"])
        updated = self.call("cost.record", legacy, {
            "stageIndex":0, "actualCost":200_000, "costDate":"2026-11-12",
            "receiptReference":"QA-COST-0"})
        self.assertEqual(updated["costRecords"][0]["actual_cost"], 200_000)
        with self.assertRaises(OrderConflict):
            self.store.rollback_empty_migration()
        self.assertEqual(TarazOrderStore(self.company).list()["orders"][0]["id"],
                         initial["id"])

    def test_invalid_money_stale_revision_and_idempotent_payment(self):
        order = self.call("create", data=passport())
        with self.assertRaises(OrderError):
            self.call("cost.record", order, {
                "stageIndex":0, "actualCost":-1, "costDate":"2026-11-12",
                "receiptReference":""})
        with self.assertRaises(OrderError):
            self.call("payment.record", order, {
                "direction":"outgoing", "amount":1000, "paymentDate":"2026-11-12",
                "party":"QA", "method":"", "transactionReference":"", "status":"planned"})
        data = {"direction":"incoming", "amount":1000, "paymentDate":"2026-11-12",
                "party":"QA", "method":"", "transactionReference":"", "status":"planned"}
        key = secrets.token_hex(16)
        first = self.call("payment.record", order, data, key=key)
        self.assertEqual(len(first["payments"]), 1)
        replay = self.call("payment.record", order, data, key=key)
        self.assertEqual(first, replay)
        with self.assertRaises(OrderConflict):
            self.call("payment.record", order, data)
        with self.assertRaises(OrderConflict):
            self.call("payment.record", order, {**data,"amount":2000}, key=key)
        self.assertEqual(TarazOrderStore(self.company).list()["orders"][0]["revision"], 2)


if __name__ == "__main__":
    unittest.main()
