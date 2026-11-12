"""Real Taraz native API -> disposable SQLite, reopen and CAS, no issuance.

This exercises the same authenticated host methods exposed to WebView2, not
browser mock persistence. It is NOT a native GUI clickthrough or a live ledger.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from standalone_accounting import AccountingRevisionConflict
from standalone_accounting_desktop import AccountingDesktopAPI
from tests.test_taraz_invoice_template_bridge_20261110 import SyntheticIdentity


LINES = [
    {"description": "چاپ ۱۰۰ کارت نمونه", "quantity": 100, "unitPrice": 1250},
    {"description": "برش نمونه", "quantity": 1, "unitPrice": 10000},
]


class TarazInvoiceNativeBridgeVertical(unittest.TestCase):
    def setUp(self):
        repo = Path(__file__).resolve().parents[1]
        self.temp = TemporaryDirectory(prefix="qa-taraz-invoice-bridge-", dir=repo.parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = SyntheticIdentity("accountant-test", "editor")
        # Accounting domain permissions are separate from desktop session role.
        self.identity.user["financeView"] = True
        self.identity.user["financeEdit"] = True

    def api(self, identity=None):
        checked = identity or self.identity
        return AccountingDesktopAPI(self.root, identity_store=checked,
                                    identity_token="synthetic-token", authenticated_user=checked.user)

    def write(self, api, command, *, revision):
        return api.standaloneAccountingCommand({"command": command, "expectedRevision": revision})

    def test_draft_multirow_reopen_edit_and_actual_sqlite_readback_without_journal(self):
        api = self.api()
        initial = api.standaloneAccountingRead()
        self.assertEqual(initial["revision"], 0)
        first = self.write(api, {"type": "party.register", "eventId": "qa-party-1",
                                 "partyId": "qa-customer-1", "name": "مشتری آزمون",
                                 "kind": "customer"}, revision=0)
        created = self.write(api, {"type": "invoice.create", "eventId": "qa-invoice-create",
                                   "invoiceId": "qa-invoice-1", "partyId": "qa-customer-1",
                                   "documentDate": "2026-11-12", "lines": LINES,
                                   "discount": 5000, "tax": 6500,
                                   "note": "شرح تست اولیه"}, revision=first["revision"])
        self.assertEqual(created["revision"], 2)
        self.assertEqual(created["result"]["status"], "draft")
        self.assertTrue((self.root / "standalone-accounting.sqlite3").is_file())

        # A NEW native API instance reads disk, rather than reusing stale JS state.
        reopened = self.api()
        state = reopened.standaloneAccountingRead()
        invoice = state["view"]["invoices"]["qa-invoice-1"]
        self.assertEqual(invoice["total"], 136500)
        self.assertEqual(invoice["lines"][0]["quantity"], 100)
        self.assertEqual(invoice["note"], "شرح تست اولیه")
        self.assertEqual((invoice["number"], invoice["postedEntryId"]), (None, None))
        self.assertEqual(state["view"]["journals"], [])

        revised_lines = [dict(row) for row in LINES]
        revised_lines[0]["quantity"] = 110
        changed = self.write(reopened, {"type": "invoice.update", "eventId": "qa-invoice-edit",
                                        "invoiceId": "qa-invoice-1", "partyId": "qa-customer-1",
                                        "documentDate": "2026-11-12", "lines": revised_lines,
                                        "discount": 5000, "tax": 6500,
                                        "note": "اصلاح توسط حسابدار"}, revision=state["revision"])
        self.assertEqual(changed["revision"], 3)
        final = self.api().standaloneAccountingRead()["view"]
        actual = final["invoices"]["qa-invoice-1"]
        self.assertEqual(actual["total"], 149000)
        self.assertEqual(actual["note"], "اصلاح توسط حسابدار")
        self.assertEqual(actual["status"], "draft")
        self.assertEqual(actual["createdBy"], "accountant-test")
        self.assertEqual(actual["editedBy"], "accountant-test")
        self.assertEqual(final["journals"], [])

    def test_cas_rejects_stale_write_and_draft_cannot_issue(self):
        api = self.api()
        starting = api.standaloneAccountingRead()["revision"]
        self.write(api, {"type": "party.register", "eventId": "qa-party-2",
                         "partyId": "qa-customer-2", "name": "مشتری دوم",
                         "kind": "customer"}, revision=starting)
        with self.assertRaises(AccountingRevisionConflict):
            self.write(self.api(), {"type": "party.register", "eventId": "qa-stale",
                                    "partyId": "qa-wrong", "name": "ثبت قدیمی",
                                    "kind": "customer"}, revision=starting)
        invoice = self.write(api, {"type": "invoice.create", "eventId": "qa-invoice-2",
                                   "invoiceId": "qa-invoice-2", "partyId": "qa-customer-2",
                                   "documentDate": "2026-11-12", "lines": LINES}, revision=1)
        with self.assertRaisesRegex(ValueError, "Only approved documents may be issued"):
            self.write(api, {"type": "invoice.issue", "eventId": "qa-issue-blocked",
                             "invoiceId": "qa-invoice-2", "postingDate": "2026-11-12"},
                       revision=invoice["revision"])
        after = self.api().standaloneAccountingRead()
        self.assertEqual(after["revision"], 2)
        self.assertEqual(after["view"]["journals"], [])
        self.assertNotIn("qa-wrong", after["view"]["parties"])

    def test_viewer_cannot_write_into_real_ephemeral_ledger(self):
        editor = self.api()
        editor.standaloneAccountingRead()
        viewer = SyntheticIdentity("reader-test", "viewer")
        viewer.user["financeView"] = True
        view = self.api(identity=viewer)
        self.assertEqual(view.standaloneAccountingRead()["revision"], 0)
        with self.assertRaises(PermissionError):
            self.write(view, {"type": "party.register", "eventId": "qa-denied",
                              "partyId": "qa-denied-party", "name": "ممنوع",
                              "kind": "customer"}, revision=0)
        self.assertEqual(self.api().standaloneAccountingRead()["revision"], 0)


if __name__ == "__main__":
    unittest.main()
