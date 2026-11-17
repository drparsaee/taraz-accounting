"""Synthetic opening-balance contract gate, without posting to any ledger."""
from copy import deepcopy
import unittest

from taraz_opening_contract import inspect_opening_batch


def sample():
    return {
        "type": "opening.balance.post", "eventId": "open-01",
        "sourceId": "parsian-verified-1405", "sourceDigest": "a" * 64,
        "postingDate": "2026-03-21", "fiscalStartDate": "2026-03-21",
        "currency": "RIAL",
        "rows": [
            {"sourceRef": "ar-1", "partyId": "customer-1", "direction": "receivable",
             "amountRial": 1600000},
            {"sourceRef": "ap-1", "partyId": "vendor-1", "direction": "payable",
             "amountRial": 50000}
        ],
        "expectedReceivableRial": 1600000,
        "expectedPayableRial": 50000,
    }


class OpeningContractTests(unittest.TestCase):
    def test_matching_totals_and_immutable_read_only_preview(self):
        command = sample()
        before = deepcopy(command)
        report = inspect_opening_batch(command)
        self.assertEqual(command, before)
        self.assertFalse(report["postingAllowed"])
        self.assertEqual(report["status"], "CONTRACT_ONLY_NOT_POSTED")
        self.assertEqual(report["netRial"], 1550000)

    def test_rejects_implicit_toman(self):
        wrong = sample()
        wrong["currency"] = "TOMAN"
        with self.assertRaisesRegex(ValueError, "RIAL"):
            inspect_opening_batch(wrong)

    def test_rejects_duplicate_source_rows(self):
        wrong = sample()
        wrong["rows"][1]["sourceRef"] = wrong["rows"][0]["sourceRef"]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            inspect_opening_batch(wrong)

    def test_rejects_forged_totals(self):
        wrong = sample()
        wrong["expectedReceivableRial"] += 10
        with self.assertRaisesRegex(ValueError, "reconciliation"):
            inspect_opening_batch(wrong)

    def test_rejects_numeric_strings_boolean_and_nonintegral_money(self):
        for wrong_amount in ("2500", True, False, -1, 0, 1.5, 10**16):
            wrong = sample()
            wrong["rows"][0]["amountRial"] = wrong_amount
            with self.subTest(wrong_amount=wrong_amount), self.assertRaises(ValueError):
                inspect_opening_batch(wrong)

    def test_rejects_unapproved_posting_bypass_field(self):
        wrong = sample()
        wrong["forcePost"] = True
        with self.assertRaisesRegex(ValueError, "exact"):
            inspect_opening_batch(wrong)

    def test_rejects_unknown_direction_and_fields(self):
        wrong = sample()
        wrong["rows"][0]["direction"] = "cash"
        with self.assertRaises(ValueError):
            inspect_opening_batch(wrong)
        wrong = sample()
        wrong["rows"][0]["journalId"] = "J:fake"
        with self.assertRaises(ValueError):
            inspect_opening_batch(wrong)

    def test_rejects_bad_source_digest_and_date(self):
        wrong = sample()
        wrong["sourceDigest"] = "verified"
        with self.assertRaises(ValueError):
            inspect_opening_batch(wrong)
        wrong = sample()
        wrong["postingDate"] = "2026-03-20"
        with self.assertRaisesRegex(ValueError, "precede"):
            inspect_opening_batch(wrong)
        wrong = sample()
        wrong["fiscalStartDate"] = "2026-02-30"
        with self.assertRaises(ValueError):
            inspect_opening_batch(wrong)

    def test_rejects_unbounded_rows(self):
        wrong = sample()
        wrong["rows"] = []
        with self.assertRaises(ValueError):
            inspect_opening_batch(wrong)
        wrong = sample()
        wrong["rows"] *= 2501
        with self.assertRaises(ValueError):
            inspect_opening_batch(wrong)

    def test_missing_counterparty_and_source_ids_fail(self):
        for key in ("partyId", "sourceRef"):
            wrong = sample()
            wrong["rows"][0][key] = "../secrets"
            with self.subTest(key=key), self.assertRaises(ValueError):
                inspect_opening_batch(wrong)


if __name__ == "__main__":
    unittest.main()
