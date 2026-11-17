"""Synthetic financial regression gates. Never touches an installed ledger."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from standalone_accounting import StandaloneAccountingStore


ACCOUNTS = {"qa_admin": {"username": "qa_admin", "role": "admin"}}
NOW = "2026-11-17T10:00:00+03:30"
DAY = "2026-11-16"
LINES = [{"description": "Synthetic goods", "quantity": 2, "unitPrice": 300}]


class ReversalWithInstallmentsTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="taraz-p0-accounting-synthetic-")
        self.addCleanup(temp.cleanup)
        self.store = StandaloneAccountingStore(
            Path(temp.name) / "synthetic-only.sqlite3", default_currency="RIAL")
        self.revision = 0
        self.counter = 0

    def command(self, payload):
        self.counter += 1
        payload = {"eventId": f"qa-{self.counter}", **payload}
        result = self.store.command(
            payload, actor="qa_admin", accounts=ACCOUNTS,
            expected_revision=self.revision, now=NOW)
        self.revision = result["revision"]
        return result

    def open_document(self, kind):
        is_sale = kind == "invoice"
        doc_id = kind + "-1"
        party = "customer" if is_sale else "vendor"
        self.command({"type": "party.register", "partyId": party,
                      "name": "Synthetic Counterparty", "kind": party})
        self.command({"type": kind + ".create", kind + "Id": doc_id,
                      "partyId": party, "documentDate": DAY, "lines": LINES})
        self.command({"type": kind + ".approve", kind + "Id": doc_id})
        issued = self.command({"type": kind + ".issue", kind + "Id": doc_id,
                               "postingDate": DAY})
        direction = "receipt" if is_sale else "payment"
        self.command({"type": "installments.create", "planId": "plan-1",
                      "direction": direction, "documentId": doc_id,
                      "schedule": [{"dueDate": "2026-12-01", "amount": 600}]})
        return doc_id, issued["result"]["journalId"]

    def assert_rejected_and_unchanged(self, operation, *, kind):
        prior = self.store.read(actor="qa_admin", accounts=ACCOUNTS)
        with self.assertRaisesRegex(ValueError, "(?i)instalment|installment"):
            self.command(operation)
        afterward = self.store.read(actor="qa_admin", accounts=ACCOUNTS)
        self.assertEqual(self.revision, prior["revision"])
        self.assertEqual(afterward, prior)
        self.assertTrue(afterward["view"]["installmentPlans"]["plan-1"]["active"])
        self.assertEqual(afterward["view"][kind + "s"][kind + "-1"]["status"], "issued")

    def test_invoice_full_return_and_journal_reversal_rejected_when_plan_active(self):
        doc_id, journal_id = self.open_document("invoice")
        self.assert_rejected_and_unchanged({
            "type": "invoice.return", "invoiceId": doc_id,
            "returnId": "return-1", "postingDate": DAY,
            "reason": "Synthetic return"}, kind="invoice")
        self.assert_rejected_and_unchanged({
            "type": "journal.reverse", "journalId": journal_id,
            "postingDate": DAY, "reason": "Synthetic reversal"}, kind="invoice")

    def test_invoice_correction_rejected_when_plan_active(self):
        doc_id, _ = self.open_document("invoice")
        self.assert_rejected_and_unchanged({
            "type": "invoice.correct", "invoiceId": doc_id,
            "replacementId": "replacement-1", "postingDate": DAY,
            "documentDate": DAY, "reason": "Synthetic correction",
            "lines": LINES}, kind="invoice")

    def test_bill_return_rejected_when_plan_active(self):
        doc_id, journal_id = self.open_document("bill")
        self.assert_rejected_and_unchanged({
            "type": "bill.return", "billId": doc_id,
            "returnId": "return-1", "postingDate": DAY,
            "reason": "Synthetic return"}, kind="bill")
        self.assert_rejected_and_unchanged({
            "type": "journal.reverse", "journalId": journal_id,
            "postingDate": DAY, "reason": "Synthetic reversal"}, kind="bill")

    def test_bill_correction_rejected_when_plan_active(self):
        doc_id, _ = self.open_document("bill")
        self.assert_rejected_and_unchanged({
            "type": "bill.correct", "billId": doc_id,
            "replacementId": "replacement-1", "postingDate": DAY,
            "documentDate": DAY, "reason": "Synthetic correction",
            "lines": LINES}, kind="bill")

    def test_legacy_pre_fix_reversal_replays_without_truncation_or_rewrite(self):
        _, journal_id = self.open_document("invoice")
        # Create a previously allowed but now forbidden historical event in a
        # disposable DB. The new guard is deliberately bypassed ONLY while
        # constructing this synthetic legacy witness, never on real data.
        old_command = {"type": "journal.reverse", "journalId": journal_id,
                       "postingDate": DAY, "reason": "Legacy synthetic reversal"}
        with patch("accounting_core._guard_active_installments_on_new_reversal"):
            legacy = self.command(old_command)
        self.assertEqual(legacy["revision"], self.revision)
        observed = self.store.read(actor="qa_admin", accounts=ACCOUNTS)
        self.assertEqual(observed["revision"], legacy["revision"])
        self.assertTrue(observed["view"]["installmentPlans"]["plan-1"]["active"])
        # An idempotent request using the same authorized command remains safe
        # and does not append or revise the legacy chain.
        prior = observed["revision"]
        duplicated = self.store.command(
            {"eventId": f"qa-{self.counter}", **old_command},
            actor="qa_admin", accounts=ACCOUNTS,
            expected_revision=prior, now=NOW)
        self.assertEqual(duplicated["revision"], prior)

    def test_reversal_permitted_after_explicit_plan_cancellation(self):
        doc_id, _ = self.open_document("invoice")
        self.command({"type": "installments.cancel", "planId": "plan-1",
                      "reason": "Explicit synthetic cancellation"})
        returned = self.command({"type": "invoice.return", "invoiceId": doc_id,
                                 "returnId": "return-1", "postingDate": DAY,
                                 "reason": "Synthetic return"})
        self.assertEqual(returned["result"]["status"], "reversed")
        view = self.store.read(actor="qa_admin", accounts=ACCOUNTS)["view"]
        self.assertFalse(view["installmentPlans"]["plan-1"]["active"])
        self.assertEqual(view["invoices"][doc_id]["status"], "reversed")

    def test_first_fiscal_close_never_assumes_january_first(self):
        initial = self.store.read(actor="qa_admin", accounts=ACCOUNTS)
        with self.assertRaisesRegex(ValueError, "(?i)explicit.*startDate"):
            self.command({"type": "fiscal.year.close", "throughDate": DAY,
                          "reason": "Synthetic period close"})
        self.assertEqual(self.store.read(actor="qa_admin", accounts=ACCOUNTS), initial)
        first = self.command({"type": "fiscal.year.close", "startDate": "2026-03-21",
                              "throughDate": DAY, "reason": "Explicit synthetic financial period"})
        self.assertEqual(first["result"]["closedThrough"], DAY)
        observed = self.store.read(actor="qa_admin", accounts=ACCOUNTS)
        self.assertEqual(observed["view"]["fiscalYears"][0]["startDate"], "2026-03-21")

    def test_legacy_first_fiscal_close_without_start_replays_without_rewrite(self):
        legacy = {"type": "fiscal.year.close", "throughDate": DAY,
                  "reason": "Old synthetic Gregorian default"}
        with patch("accounting_core._guard_explicit_first_fiscal_start"):
            result = self.command(legacy)
        observed = self.store.read(actor="qa_admin", accounts=ACCOUNTS)
        self.assertEqual(observed["revision"], result["revision"])
        self.assertEqual(observed["view"]["fiscalYears"][0]["startDate"], "2026-01-01")
        replay = self.store.command(
            {"eventId": f"qa-{self.counter}", **legacy}, actor="qa_admin",
            accounts=ACCOUNTS, expected_revision=self.revision, now=NOW)
        self.assertEqual(replay["revision"], self.revision)


if __name__ == "__main__":
    unittest.main()
