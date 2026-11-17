"""True native TarazAPI entry, synthetic isolated company, no accounting write."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import secrets
import unittest

from taraz_desktop import TarazAPI
from standalone_accounting_desktop import JS_BRIDGE


def draft():
    return {
        "kind": "sale",
        "customerId": "",
        "customerName": "مشتری نمونه",
        "title": "پاسپورت",
        "description": "",
        "unit": "عدد",
        "quantity": 100,
        "productionQuantity": 120,
        "unitPrice": None,
        "currency": "RIAL",
        "costStages": [],
        "notes": "",
    }


class TarazOrderBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix="taraz-order-native-qa-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.accounting=self.root/"standalone-accounting.sqlite3"
        self.accounting.write_bytes(b"synthetic ledger marker untouched")
        self.sha=hashlib.sha256(self.accounting.read_bytes()).hexdigest()
        self.api=TarazAPI(self.root)

    def tearDown(self):
        self.assertEqual(
            hashlib.sha256(self.accounting.read_bytes()).hexdigest(),self.sha,
            "Order operations must never mutate the ledger",
        )

    def test_bridge_forwarder_is_present(self):
        self.assertIn("'tarazOrderList'",JS_BRIDGE)
        self.assertIn("'tarazOrderCommand'",JS_BRIDGE)
        self.assertEqual(self.api.tarazOrderList()["total"],0)

    def test_real_host_method_creates_reloads_and_approves(self):
        payload={
            "action":"create",
            "idempotencyKey":secrets.token_hex(16),
            "orderId":"",
            "expectedRevision":0,
            "data":draft(),
            "nextStatus":None,
            "manualConfirmation":False,
        }
        saved=self.api.tarazOrderCommand(payload)
        self.assertEqual(saved["status"],"draft")
        self.assertEqual(saved["wasteQuantity"],20)
        self.assertFalse(saved["financialEventCreated"])
        self.assertEqual(self.api.tarazOrderList()["total"],1)
        approval={
            "action":"transition",
            "idempotencyKey":secrets.token_hex(16),
            "orderId":saved["id"],
            "expectedRevision":saved["revision"],
            "data":None,
            "nextStatus":"approved",
            "manualConfirmation":True,
        }
        approved=self.api.tarazOrderCommand(approval)
        self.assertEqual(approved["status"],"approved")
        self.assertEqual(self.api.tarazOrderList()["orders"][0]["status"],"approved")


if __name__=="__main__":
    unittest.main()
