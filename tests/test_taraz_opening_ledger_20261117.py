"""Red-to-green synthetic RIAL opening subledger/settlement/rollback gates.

No real accounts, imported Parsian data, installed EXEs or production paths.
"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from standalone_accounting import StandaloneAccountingStore
from accounting_core import validate_accounting_state


DAY = "2026-03-21"
NEXT = "2026-03-22"
NOW = "2026-11-17T18:00:00+03:30"
ADMIN = {"admin": {"username": "admin", "role": "admin"}}
EDITOR = {"editor": {"username": "editor", "role": "editor", "financeEdit": True}}


def opening():
    return {
        "type": "opening.balance.post",
        "sourceId": "synthetic-source-1405",
        "sourceDigest": "a" * 64,
        "postingDate": DAY,
        "fiscalStartDate": DAY,
        "currency": "RIAL",
        "rows": [
            {"sourceRef": "ar-old-1", "partyId": "buyer-1", "direction": "receivable",
             "amountRial": 1600000},
            {"sourceRef": "ap-old-1", "partyId": "vendor-1", "direction": "payable",
             "amountRial": 500000}
        ],
        "expectedReceivableRial": 1600000,
        "expectedPayableRial": 500000,
    }


class OpeningLedgerTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="taraz-only-opening-synthetic-")
        self.addCleanup(temp.cleanup)
        self.book = Path(temp.name) / "qa-ledger.sqlite3"
        self.store = StandaloneAccountingStore(self.book, default_currency="RIAL")
        self.rev = 0
        self.seq = 0
        self.command({"type": "party.register", "partyId": "buyer-1",
                      "name": "Synthetic Customer", "kind": "customer"})
        self.command({"type": "party.register", "partyId": "vendor-1",
                      "name": "Synthetic Supplier", "kind": "vendor"})

    def command(self, command, *, actor="admin", accounts=None, event_id=None):
        self.seq += 1
        payload = {"eventId": event_id or f"qa-{self.seq}", **command}
        result = self.store.command(payload, actor=actor,
                                    accounts=accounts if accounts is not None else ADMIN,
                                    expected_revision=self.rev, now=NOW)
        self.rev = result["revision"]
        return result

    def view(self):
        return self.store.read(actor="admin", accounts=ADMIN)["view"]

    def post(self):
        return self.command(opening())

    def check_rejected(self, command, exception=ValueError, *, actor="admin", accounts=None):
        state_before = self.store.read(actor="admin", accounts=ADMIN)
        with self.assertRaises(exception):
            self.command(command, actor=actor, accounts=accounts)
        self.assertEqual(self.store.read(actor="admin", accounts=ADMIN), state_before)

    def test_opening_journal_balanced_no_fake_invoices(self):
        posted = self.post()
        view = self.view()
        self.assertEqual(view["currency"], "RIAL")
        self.assertEqual(view["accounts"]["1200"]["normalBalance"], 1600000)
        self.assertEqual(view["accounts"]["2000"]["normalBalance"], 500000)
        self.assertEqual(view["accounts"]["3000"]["normalBalance"], 1100000)
        self.assertEqual(view["parties"]["buyer-1"]["receivable"], 1600000)
        self.assertEqual(view["parties"]["vendor-1"]["payable"], 500000)
        self.assertEqual(view["invoices"], {})
        self.assertEqual(view["bills"], {})
        self.assertEqual(view["openingBalances"]["ar-old-1"]["allocated"], 0)
        self.assertEqual(view["openingBalances"]["ap-old-1"]["allocated"], 0)
        self.assertEqual(posted["result"]["journalId"], "J:qa-3")
        with self.store._connect() as connection:
            _, state = self.store._current(connection)
        self.assertTrue(validate_accounting_state(state))

    def test_real_settlement_allocates_opening_receivable_and_payable(self):
        self.post()
        receipt = self.command({"type": "receipt.record", "receiptId": "rec-1",
                                "partyId": "buyer-1", "accountId": "1010",
                                "postingDate": NEXT,
                                "allocations": [{"openingRef": "ar-old-1", "amount": 1000000}]})
        self.assertEqual(receipt["result"]["amount"], 1000000)
        payment = self.command({"type": "payment.record", "paymentId": "pay-1",
                                "partyId": "vendor-1", "accountId": "1010",
                                "postingDate": NEXT,
                                "allocations": [{"openingRef": "ap-old-1", "amount": 200000}]})
        self.assertEqual(payment["result"]["amount"], 200000)
        view = self.view()
        self.assertEqual(view["parties"]["buyer-1"]["receivable"], 600000)
        self.assertEqual(view["parties"]["vendor-1"]["payable"], 300000)
        self.assertEqual(view["accounts"]["1010"]["normalBalance"], 800000)
        self.assertEqual(view["openingBalances"]["ar-old-1"]["allocated"], 1000000)
        self.assertEqual(view["openingBalances"]["ap-old-1"]["allocated"], 200000)

    def test_overpayment_wrong_party_or_direction_rejected_without_mutation(self):
        self.post()
        for cmd in (
            {"type": "receipt.record", "receiptId": "bad-over", "partyId": "buyer-1",
             "accountId": "1010", "postingDate": NEXT,
             "allocations": [{"openingRef": "ar-old-1", "amount": 1600001}]},
            {"type": "receipt.record", "receiptId": "bad-party", "partyId": "buyer-1",
             "accountId": "1010", "postingDate": NEXT,
             "allocations": [{"openingRef": "ap-old-1", "amount": 100}]},
            {"type": "payment.record", "paymentId": "bad-type", "partyId": "vendor-1",
             "accountId": "1010", "postingDate": NEXT,
             "allocations": [{"openingRef": "ar-old-1", "amount": 100}]},
        ):
            with self.subTest(cmd=cmd["receiptId"] if "receiptId" in cmd else cmd["paymentId"]):
                self.check_rejected(cmd)

    def test_duplicate_source_even_with_different_event_id_rejected(self):
        self.post()
        second = opening()
        second["rows"] = [{
            "sourceRef": "ar-other", "partyId": "buyer-1",
            "direction": "receivable", "amountRial": 5}]
        second["expectedReceivableRial"] = 5
        second["expectedPayableRial"] = 0
        self.check_rejected(second)

    def test_idempotent_same_event_does_not_append_a_second_opening(self):
        self.post()
        prior = self.rev
        identical = self.command(opening(), event_id="qa-3")
        self.assertEqual(identical["revision"], prior)
        self.assertEqual(len(self.view()["openingSources"]), 1)
        self.assertEqual(len(self.view()["journals"]), 1)

    def test_receipt_allocates_mixed_opening_and_real_invoice(self):
        self.post()
        self.command({
            "type": "invoice.create", "invoiceId": "real-draft-1",
            "partyId": "buyer-1", "documentDate": DAY,
            "lines": [{"description": "Synthetic inventory", "quantity": 1, "unitPrice": 1000}]})
        self.command({"type": "invoice.approve", "invoiceId": "real-draft-1"})
        self.command({"type": "invoice.issue", "invoiceId": "real-draft-1",
                      "postingDate": NEXT})
        self.command({
            "type": "receipt.record", "receiptId": "mixed-rec-1", "partyId": "buyer-1",
            "accountId": "1010", "postingDate": NEXT,
            "allocations": [{"openingRef": "ar-old-1", "amount": 1000},
                            {"invoiceId": "real-draft-1", "amount": 1000}]})
        view = self.view()
        self.assertEqual(view["openingBalances"]["ar-old-1"]["allocated"], 1000)
        self.assertEqual(view["invoices"]["real-draft-1"]["allocated"], 1000)
        self.assertEqual(view["parties"]["buyer-1"]["receivable"], 1599000)

    def test_party_kind_and_credit_limit_cannot_invalidate_opening(self):
        self.post()
        self.check_rejected({"type": "party.update", "partyId": "buyer-1",
                             "kind": "vendor", "reason": "Synthetic role change"})
        self.check_rejected({"type": "party.update", "partyId": "vendor-1",
                             "kind": "customer", "reason": "Synthetic role change"})
        self.check_rejected({"type": "party.update", "partyId": "buyer-1",
                             "creditLimit": 500, "reason": "Synthetic low credit limit"})

    def test_no_opening_after_existing_financial_activity(self):
        self.command({"type": "funds.deposit", "accountId": "1010", "amount": 100,
                      "postingDate": DAY, "note": "Synthetic initial funding"})
        self.check_rejected(opening())

    def test_opening_must_have_exact_fiscal_start(self):
        wrong = opening()
        wrong["fiscalStartDate"] = "2026-01-01"
        self.check_rejected(wrong)

    def test_first_year_close_must_match_opening_fiscal_start(self):
        self.post()
        self.check_rejected({"type": "fiscal.year.close", "startDate": "2026-01-01",
                             "throughDate": "2026-11-16"})

    def test_editor_and_wrong_currency_or_party_rejected(self):
        self.check_rejected(opening(), PermissionError, actor="editor", accounts=EDITOR)
        bad_currency = opening()
        bad_currency["currency"] = "TOMAN"
        self.check_rejected(bad_currency)
        missing = opening()
        missing["rows"][0]["partyId"] = "not-registered"
        self.check_rejected(missing)

    def test_bad_totals_do_not_modify_sqlite_even_after_restart(self):
        wrong = opening()
        wrong["expectedReceivableRial"] += 1
        self.check_rejected(wrong)
        fresh = StandaloneAccountingStore(self.book, default_currency="RIAL")
        self.assertEqual(fresh.read(actor="admin", accounts=ADMIN)["revision"], self.rev)
        self.assertEqual(fresh.read(actor="admin", accounts=ADMIN)["view"]["openingBalances"], {})

    def test_reversal_requires_reversing_settlement_first(self):
        self.post()
        self.command({"type": "receipt.record", "receiptId": "rec-1",
                      "partyId": "buyer-1", "accountId": "1010", "postingDate": NEXT,
                      "allocations": [{"openingRef": "ar-old-1", "amount": 1000000}]})
        self.check_rejected({"type": "journal.reverse", "journalId": "J:qa-3",
                             "postingDate": NEXT, "reason": "Reverse synthetic opening"})
        self.command({"type": "journal.reverse", "journalId": "J:qa-4",
                      "postingDate": NEXT, "reason": "Reverse synthetic receipt"})
        self.command({"type": "journal.reverse", "journalId": "J:qa-3",
                      "postingDate": NEXT, "reason": "Reverse synthetic opening"})
        view = self.view()
        self.assertEqual(view["parties"]["buyer-1"]["receivable"], 0)
        self.assertEqual(view["parties"]["vendor-1"]["payable"], 0)
        self.assertEqual(view["accounts"]["1200"]["normalBalance"], 0)
        self.assertEqual(view["accounts"]["2000"]["normalBalance"], 0)
        self.assertEqual(view["accounts"]["1010"]["normalBalance"], 0)


if __name__ == "__main__":
    unittest.main()
