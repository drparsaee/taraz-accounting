"""Synthetic-only acceptance for the independent operational order desk."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest

from taraz_order_store import OrderConflict, OrderError, TarazOrderStore, validate_order


def fixture():
    return {
        "kind": "sale", "customerId": "", "customerName": "مشتری حضوری",
        "title": "پاسپورت تبلیغاتی", "description": "چاپ و صحافی سفارشی",
        "unit": "عدد", "quantity": 100, "productionQuantity": 120,
        "unitPrice": None, "currency": "RIAL", "costStages": [
            {"kind": "print", "supplier": "چاپخانه", "description": "چاپ",
             "estimatedCost": None},
            {"kind": "bindery", "supplier": "", "description": "صحافی",
             "estimatedCost": 120000},
            {"kind": "shipping", "supplier": "", "description": "",
             "estimatedCost": None},
        ], "notes": "",
    }


def request(action="create", *, key=None, order_id="", rev=0, data=None,
            next_status=None, confirmation=False):
    return {
        "action": action,
        "idempotencyKey": key or secrets.token_hex(16),
        "orderId": order_id,
        "expectedRevision": rev,
        "data": fixture() if data is None and action != "transition" else data,
        "nextStatus": next_status, "manualConfirmation": confirmation,
    }


class TarazOrderStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="taraz-orders-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.one = self.root / "company-one"
        self.two = self.root / "company-two"
        self.one.mkdir()
        self.two.mkdir()
        self.ledger = self.one / "standalone-accounting.sqlite3"
        self.ledger.write_bytes(b"synthetic-ledger-marker")
        self.original_hash = hashlib.sha256(self.ledger.read_bytes()).hexdigest()
        self.store = TarazOrderStore(self.one)

    def tearDown(self):
        self.assertEqual(
            hashlib.sha256(self.ledger.read_bytes()).hexdigest(),
            self.original_hash, "Real accounting book must never be used",
        )

    def create(self):
        return self.store.command(request(), actor="operator", role="editor")

    def test_no_data_created_on_read(self):
        self.assertEqual(self.store.list()["total"], 0)
        self.assertFalse((self.one / "taraz-orders.sqlite3").exists())

    def test_separate_sale_and_production_quantities(self):
        order = self.create()
        self.assertEqual((order["quantity"], order["productionQuantity"],
                          order["wasteQuantity"]), (100, 120, 20))
        self.assertIsNone(order["estimatedSalesTotal"])
        self.assertFalse(order["financialEventCreated"])
        self.assertEqual(order["status"], "draft")
        self.assertEqual(self.store.list()["orders"][0]["id"], order["id"])

    def test_real_quote_price_is_optional_not_invented(self):
        data = fixture()
        data["unitPrice"] = 25000
        order = self.store.command(request(data=data), actor="operator", role="editor")
        self.assertEqual(order["estimatedSalesTotal"], 2500000)
        self.assertEqual(order["costStages"][0]["estimatedCost"], None)

    def test_purchase_type_with_supplier_and_no_production_required(self):
        data = fixture()
        data.update(kind="purchase", customerName="تامین کننده",
                    quantity=30, productionQuantity=20)
        order = self.store.command(request(data=data), actor="operator", role="editor")
        self.assertEqual(order["kind"], "purchase")

    def test_requires_identity_and_permission(self):
        for actor, role in [("", "admin"), ("operator", "viewer"),
                            ("operator", "fake"), ("../user", "admin")]:
            with self.assertRaises(PermissionError):
                self.store.command(request(), actor=actor, role=role)
        self.assertEqual(self.store.list()["total"], 0)

    def test_bad_quantities_and_money_rejected(self):
        for field, value in [
            ("quantity", 0), ("quantity", True), ("quantity", "100"),
            ("productionQuantity", 99), ("unitPrice", -1),
            ("unitPrice", 2**53), ("currency", "USD"),
        ]:
            with self.subTest(field=field, value=value):
                data = fixture()
                data[field] = value
                with self.assertRaises(OrderError):
                    validate_order(data)

    def test_extra_client_authority_is_refused(self):
        command = request()
        command["isAdmin"] = True
        with self.assertRaises(OrderError):
            self.store.command(command, actor="operator", role="editor")

    def test_idempotent_identical_retry_and_conflict(self):
        first = request(key=secrets.token_hex(16))
        order = self.store.command(first, actor="operator", role="admin")
        again = self.store.command(first, actor="operator", role="admin")
        self.assertEqual(again, order)
        first["data"]["quantity"] = 101
        with self.assertRaises(OrderConflict):
            self.store.command(first, actor="operator", role="admin")
        self.assertEqual(self.store.list()["total"], 1)

    def test_restart_persists_and_isolates_companies(self):
        order = self.create()
        other = TarazOrderStore(self.two)
        self.assertEqual(other.list()["total"], 0)
        reread = TarazOrderStore(self.one).list()
        self.assertEqual(reread["orders"][0]["id"], order["id"])

    def test_edit_draft_with_compare_and_swap(self):
        order = self.create()
        data = fixture()
        data["notes"] = "فایل از مشتری دریافت شود"
        changed = self.store.command(request("update", order_id=order["id"],
                                             rev=1, data=data),
                                     actor="operator", role="editor")
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(changed["notes"], data["notes"])
        with self.assertRaises(OrderConflict):
            self.store.command(request("update", order_id=order["id"],
                                       rev=1, data=data),
                               actor="operator", role="editor")

    def test_status_explicit_and_one_directional(self):
        order = self.create()
        with self.assertRaises(OrderError):
            self.store.command(request("transition", order_id=order["id"],
                                       rev=1, next_status="approved"),
                               actor="operator", role="admin")
        approval = self.store.command(
            request("transition", order_id=order["id"], rev=1,
                    next_status="approved", confirmation=True),
            actor="operator", role="admin")
        self.assertEqual(approval["status"], "approved")
        with self.assertRaises(OrderConflict):
            self.store.command(
                request("transition", order_id=order["id"], rev=2,
                        next_status="delivered", confirmation=True),
                actor="operator", role="admin")
        with self.assertRaises(OrderConflict):
            self.store.command(request("update", order_id=order["id"],
                                       rev=2, data=fixture()),
                               actor="operator", role="admin")

    def test_negative_symlink_refused(self):
        alias = self.root / "linked"
        try:
            alias.symlink_to(self.one, target_is_directory=True)
        except (NotImplementedError, OSError):
            self.skipTest("Symlink privilege unavailable")
        with self.assertRaises(OrderError):
            TarazOrderStore(alias)

    def test_racing_cas_allows_one_writer(self):
        order = self.create()
        def attempt(i):
            data = fixture()
            data["notes"] = str(i)
            try:
                return self.store.command(
                    request("update", order_id=order["id"], rev=1, data=data),
                    actor="operator", role="editor")
            except OrderConflict:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(4)))
        self.assertEqual(sum(x is not None for x in results), 1)
        self.assertEqual(self.store.list()["orders"][0]["revision"], 2)

    def test_actual_taraz_api_methods_bind_order_to_selected_directory(self):
        from taraz_desktop import TarazAPI
        api = TarazAPI(self.one)
        first = api.tarazOrderList()
        self.assertEqual(first["orders"], [])
        created = api.tarazOrderCommand(request())
        self.assertEqual(api.tarazOrderList()["orders"][0]["id"], created["id"])
        another_api = TarazAPI(self.two)
        self.assertEqual(another_api.tarazOrderList()["orders"], [])
        api._exit_backed_up = True
        with self.assertRaises(RuntimeError):
            api.tarazOrderCommand(request())


if __name__ == "__main__":
    unittest.main()
