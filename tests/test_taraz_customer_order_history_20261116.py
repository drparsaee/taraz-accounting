"""Exact-party, per-ledger and ACL-scoped synthetic order history acceptance."""
from pathlib import Path
import tempfile
import unittest

from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_identity import LocalCompanyIdentity
from taraz_desktop import TarazAPI
from taraz_order_store import OrderError, TarazOrderStore
from tests.test_taraz_order_store_20261111 import fixture, request


class CustomerOrderHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qa-taraz-history-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = StandaloneCompanyRegistry(self.root)
        self.company = self.registry.create_company("History QA Company")
        self.book = self.registry.company_data_directory(self.company["id"])
        self.identity = LocalCompanyIdentity(self.book)
        self.identity.add_user("admin", "qa-only-test-secret", role="admin")
        self.token = self.identity.login("admin", "qa-only-test-secret")
        self.user = self.identity.require_session(self.token)
        self.api = TarazAPI(self.book,
                            company_name="History QA Company",
                            company_workspace_id=self.company["id"],
                            identity_store=self.identity, identity_token=self.token,
                            authenticated_user=self.user)
        for index in (1, 2):
            result = self.api.standaloneAccountingCommand({
                "expectedRevision": index-1,
                "command": {"type": "party.register",
                            "eventId": "history-party-" + str(index),
                            "partyId": "party-" + str(index),
                            "name": "مشتری هم‌نام", "kind": "customer",
                            "creditLimit": 9_999_999}})
            self.assertEqual(result["revision"], index)
        self.orders = TarazOrderStore(self.book)

    def add_order(self, party_id="party-1", kind="sale"):
        data = fixture()
        data["customerId"] = party_id
        data["customerName"] = "مشتری هم‌نام"
        data["kind"] = kind
        data["unitPrice"] = 9_999
        data["costStages"][1]["estimatedCost"] = 5_000
        return self.orders.command(request(data=data),actor="admin",role="admin")

    def test_customer_only_history_redacts_financial_fields(self):
        sales = [self.add_order(), self.add_order("party-2"),
                 self.add_order("party-1","purchase")]
        rows = self.api.tarazCustomerOrderHistory("party-1")
        self.assertEqual(rows["total"], 1)
        self.assertEqual(rows["orders"][0]["orderId"], sales[0]["id"])
        self.assertEqual(rows["orders"][0]["partyId"], "party-1")
        self.assertEqual(rows["orders"][0]["quantity"], 100)
        self.assertTrue(rows["financialFieldsOmitted"])
        self.assertFalse(rows["financialEventCreated"])
        serialized = repr(rows)
        for secret in ("unitPrice", "costStages", "estimatedSalesTotal",
                       "payment", "creditLimit", "receivable", "9999", "5000"):
            self.assertNotIn(secret, serialized)

    def test_pagination_and_restart_preserves_stable_party_binding(self):
        one = self.add_order()
        two = self.add_order()
        page1 = self.api.tarazCustomerOrderHistory("party-1", 0, 1)
        page2 = self.api.tarazCustomerOrderHistory("party-1", 1, 1)
        self.assertEqual(page1["total"], 2)
        self.assertEqual(page2["total"], 2)
        self.assertEqual({page1["orders"][0]["orderId"], page2["orders"][0]["orderId"]},
                         {one["id"], two["id"]})
        reopened = TarazAPI(self.book,
                            company_name="History QA Company",
                            company_workspace_id=self.company["id"],
                            identity_store=self.identity, identity_token=self.token,
                            authenticated_user=self.user)
        self.assertEqual(reopened.tarazCustomerOrderHistory("party-1")["total"], 2)

    def test_unknown_party_and_malformed_paging_refused(self):
        with self.assertRaises(PermissionError):
            self.api.tarazCustomerOrderHistory("not-in-company")
        for value in ("", None, [], {"x": 1}, "party/../other"):
            with self.subTest(party=value), self.assertRaises(PermissionError):
                self.api.tarazCustomerOrderHistory(value)
        for offset, limit in ((-1, 10), (0, 51), (True, 10), (0, 0)):
            with self.subTest(offset=offset, limit=limit), self.assertRaises(OrderError):
                self.api.tarazCustomerOrderHistory("party-1", offset, limit)

    def test_revoked_identity_denied_after_data_saved(self):
        self.add_order()
        self.identity.logout(self.token)
        with self.assertRaises(PermissionError):
            self.api.tarazCustomerOrderHistory("party-1")

    def test_no_unregistered_local_admin_bypass(self):
        # The ordinary isolated TarazAPI fixture has no authenticated company.
        unauthenticated = TarazAPI(self.book)
        with self.assertRaises(PermissionError):
            unauthenticated.tarazCustomerOrderHistory("party-1")

    def test_missing_order_file_does_not_create_one(self):
        self.assertFalse((self.book / "taraz-orders.sqlite3").exists())
        result = self.api.tarazCustomerOrderHistory("party-1")
        self.assertEqual(result["total"], 0)
        self.assertFalse((self.book / "taraz-orders.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
