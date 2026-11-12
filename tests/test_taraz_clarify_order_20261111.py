"""Clarified manufacturing quantities, safe status flow, and legacy SQLite support."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from taraz_order_store import OrderConflict, OrderError, TarazOrderStore, validate_order


def order():
    return {
        "kind": "sale", "customerId": "", "customerName": "Customer sample",
        "title": "Printed cases", "description": "", "unit": "pieces",
        "quantity": 100, "productionQuantity": 120,
        "actualProducedQuantity": None, "scrapQuantity": None,
        "healthySurplusQuantity": None,
        "unitPrice": None, "currency": "RIAL",
        "costStages": [{"kind": "print", "supplier": "", "description": "",
                        "estimatedCost": None}], "notes": "",
        "projectReference": "PROJECT-22", "scheduleStartDate": "2026-11-11",
        "scheduleDueDate": "2026-11-18", "procurementNotes": "Check cardboard availability",
    }


def command(action, data=None, oid="", revision=0, status=None, confirmed=False):
    return {"action": action, "idempotencyKey": secrets.token_hex(16),
            "orderId": oid, "expectedRevision": revision, "data": data,
            "nextStatus": status, "manualConfirmation": confirmed}


class ClarifiedOrderTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="taraz-clarify-order-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / "standalone-accounting.sqlite3"
        self.ledger.write_bytes(b"synthetic ledger should remain unchanged")
        self.original = hashlib.sha256(self.ledger.read_bytes()).hexdigest()
        self.store = TarazOrderStore(self.root)

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.ledger.read_bytes()).hexdigest(), self.original)

    def invoke(self, request, *, role="editor"):
        return self.store.command(request, actor="operator", role=role)

    def test_unknowns_do_not_become_waste_and_project_metadata_is_retained(self):
        saved = self.invoke(command("create", order()))
        self.assertEqual((saved["quantity"], saved["productionQuantity"]), (100, 120))
        self.assertEqual(saved["productionOverageQuantity"], 20)
        self.assertIsNone(saved["wasteQuantity"])
        self.assertFalse(saved["wasteQuantityIsLegacyEstimate"])
        self.assertEqual(saved["productionReconciliation"]["state"], "not_recorded")
        self.assertEqual(saved["projectReference"], "PROJECT-22")
        self.assertEqual(saved["procurementNotes"], "Check cardboard availability")
        self.assertEqual(saved["scheduleDueDate"], "2026-11-18")
        self.assertIsNone(saved["costStages"][0]["estimatedCost"])
        self.assertFalse(saved["financialEventCreated"])
        self.assertEqual(self.store.list()["orders"][0]["id"], saved["id"])

    def test_counted_zero_is_distinct_from_unknown_and_scrap_is_separate(self):
        data = order()
        data.update(actualProducedQuantity=100, scrapQuantity=0, healthySurplusQuantity=0)
        saved = self.invoke(command("create", data))
        self.assertEqual(saved["productionReconciliation"], {
            "state": "balanced", "balanceQuantity": 0, "missing": []})
        self.assertEqual(saved["wasteQuantity"], 0)
        data.update(actualProducedQuantity=120, scrapQuantity=5,
                    healthySurplusQuantity=15)
        saved2 = self.invoke(command("create", data))
        self.assertEqual(saved2["wasteQuantity"], 5)
        self.assertEqual(saved2["healthySurplusQuantity"], 15)
        self.assertEqual(saved2["productionReconciliation"]["state"], "balanced")

    def test_actual_count_may_be_below_sold_until_completed(self):
        data = order()
        data.update(actualProducedQuantity=60, scrapQuantity=3,
                    healthySurplusQuantity=2)
        saved = self.invoke(command("create", data))
        self.assertEqual(saved["productionReconciliation"]["state"], "shortfall")
        self.assertEqual(saved["productionReconciliation"]["balanceQuantity"], -45)
        data.update(actualProducedQuantity=130, scrapQuantity=5,
                    healthySurplusQuantity=10)
        second = self.invoke(command("create", data))
        self.assertEqual(second["productionReconciliation"]["state"], "unallocated")
        self.assertEqual(second["productionReconciliation"]["balanceQuantity"], 15)

    def test_invalid_counts_dates_and_extra_keys_fail_closed(self):
        for changes in (
            {"actualProducedQuantity": -1},
            {"scrapQuantity": True},
            {"healthySurplusQuantity": "5"},
            {"actualProducedQuantity": 10, "scrapQuantity": 6,
             "healthySurplusQuantity": 5},
            {"scheduleStartDate": "2026-02-30"},
            {"scheduleDueDate": "2026-11-10"},
            {"secretAutoPosting": True},
        ):
            with self.subTest(changes=changes):
                data = order()
                data.update(changes)
                with self.assertRaises(OrderError):
                    validate_order(data)

    def test_in_progress_counts_require_human_confirmation_and_no_other_edit(self):
        saved = self.invoke(command("create", order()))
        with self.assertRaises(PermissionError):
            self.invoke(command("transition", oid=saved["id"],
                revision=saved["revision"], status="approved", confirmed=True))
        approved = self.invoke(command("transition", oid=saved["id"],
            revision=saved["revision"], status="approved", confirmed=True),
            role="admin")
        started = self.invoke(command("transition", oid=saved["id"],
            revision=approved["revision"], status="in_production", confirmed=True))
        data = order()
        data.update(actualProducedQuantity=120, scrapQuantity=5,
                    healthySurplusQuantity=15)
        with self.assertRaises(OrderError):
            self.invoke(command("update", data, saved["id"], started["revision"]))
        with self.assertRaises(OrderConflict):
            edited = {**data, "unitPrice": 100}
            self.invoke(command("update", edited, saved["id"],
                                started["revision"], confirmed=True))
        measured = self.invoke(command("update", data, saved["id"],
                                       started["revision"], confirmed=True))
        self.assertEqual(measured["status"], "in_production")
        self.assertEqual(measured["productionReconciliation"]["state"], "balanced")
        self.assertEqual(measured["revision"], started["revision"] + 1)
        with self.assertRaises(OrderConflict):
            self.invoke(command("update", data, saved["id"],
                                started["revision"], confirmed=True))
        delivered = self.invoke(command("transition", oid=saved["id"],
            revision=measured["revision"], status="delivered", confirmed=True),
            role="admin")
        self.assertEqual(delivered["status"], "delivered")
        self.assertFalse(delivered["financialEventCreated"])

    def test_delivery_rejects_missing_or_unbalanced_counts(self):
        saved = self.invoke(command("create", order()))
        approved = self.invoke(command("transition", oid=saved["id"],
            revision=saved["revision"], status="approved", confirmed=True),
            role="admin")
        started = self.invoke(command("transition", oid=saved["id"],
            revision=approved["revision"], status="in_production", confirmed=True))
        with self.assertRaises(OrderConflict):
            self.invoke(command("transition", oid=saved["id"],
                revision=started["revision"], status="delivered", confirmed=True),
                role="admin")
        data = order()
        data.update(actualProducedQuantity=120, scrapQuantity=10,
                    healthySurplusQuantity=0)
        measured = self.invoke(command("update", data, saved["id"],
            started["revision"], confirmed=True))
        self.assertEqual(measured["productionReconciliation"]["balanceQuantity"], 10)
        with self.assertRaises(OrderConflict):
            self.invoke(command("transition", oid=saved["id"],
                revision=measured["revision"], status="delivered", confirmed=True),
                role="admin")

    def test_legacy_record_uses_same_db_without_schema_migration(self):
        legacy = order()
        for key in ("actualProducedQuantity", "scrapQuantity", "healthySurplusQuantity",
                    "projectReference", "scheduleStartDate", "scheduleDueDate",
                    "procurementNotes"):
            legacy.pop(key)
        saved = self.invoke(command("create", legacy))
        self.assertTrue(saved["wasteQuantityIsLegacyEstimate"])
        self.assertEqual(saved["wasteQuantity"], 20)
        self.assertIsNone(saved["scrapQuantity"])
        with closing(sqlite3.connect(self.store.file)) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(orders)")]
            stored = json.loads(db.execute("SELECT data_json FROM orders").fetchone()[0])
        self.assertEqual(columns, ["id", "status", "revision", "data_json",
                                   "created_at", "updated_at"])
        self.assertNotIn("scrapQuantity", stored)
        self.assertEqual(self.store.list()["orders"][0]["id"], saved["id"])

    def test_legacy_active_order_can_adopt_explicit_measurements(self):
        legacy = order()
        for key in ("actualProducedQuantity", "scrapQuantity", "healthySurplusQuantity",
                    "projectReference", "scheduleStartDate", "scheduleDueDate",
                    "procurementNotes"):
            legacy.pop(key)
        saved = self.invoke(command("create", legacy))
        approved = self.invoke(command("transition", oid=saved["id"],
            revision=saved["revision"], status="approved", confirmed=True),
            role="admin")
        started = self.invoke(command("transition", oid=saved["id"],
            revision=approved["revision"], status="in_production", confirmed=True))
        new_data = {**legacy, "actualProducedQuantity": 120,
                    "scrapQuantity": 5, "healthySurplusQuantity": 15,
                    "projectReference": "", "scheduleStartDate": "",
                    "scheduleDueDate": "", "procurementNotes": ""}
        counted = self.invoke(command("update", new_data, saved["id"],
            started["revision"], confirmed=True))
        self.assertEqual(counted["productionReconciliation"]["state"], "balanced")
        self.assertEqual(counted["wasteQuantity"], 5)
        self.assertFalse(counted["wasteQuantityIsLegacyEstimate"])


if __name__ == "__main__":
    unittest.main()
