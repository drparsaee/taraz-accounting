"""Synthetic purchase-tax classification tests; no financial ledger mutation."""
from copy import deepcopy
import unittest

from taraz_purchase_tax_contract import inspect_purchase_tax


def sample(treatment="recoverable", tax=900, reviewed=True):
    return {"type": "purchase.tax.preview", "invoiceId": "synthetic-bill",
            "currency": "RIAL", "documentDate": "2026-11-16",
            "taxPolicyId": "synthetic-policy", "policyEffectiveFrom": "2026-10-01",
            "netAmountRial": 10000, "taxAmountRial": tax,
            "treatment": treatment, "eligibilityVerified": reviewed}


class TaxContractTests(unittest.TestCase):
    def test_recoverable_treatment_only_previews_asset_classification(self):
        source = sample()
        prior = deepcopy(source)
        result = inspect_purchase_tax(source)
        self.assertEqual(prior, source)
        self.assertEqual(result["candidateTaxDebitAccount"], "1250")
        self.assertEqual(result["grossAmountRial"], 10900)
        self.assertFalse(result["postingAllowed"])
        self.assertFalse(result["taxPolicyAuthenticated"])
        self.assertFalse(result["humanApproved"])

    def test_expense_treatment_separate_from_input_tax(self):
        result = inspect_purchase_tax(sample("expense", 900, False))
        self.assertEqual(result["candidateTaxDebitAccount"], "5200")
        self.assertEqual(result["classification"], "expense")

    def test_exempt_requires_zero_tax(self):
        self.assertIsNone(inspect_purchase_tax(sample("exempt", 0, False))[
            "candidateTaxDebitAccount"])
        with self.assertRaises(ValueError):
            inspect_purchase_tax(sample("exempt", 900, False))

    def test_recoverable_requires_positive_tax_and_review(self):
        with self.assertRaises(ValueError):
            inspect_purchase_tax(sample("recoverable", 900, False))
        with self.assertRaises(ValueError):
            inspect_purchase_tax(sample("recoverable", 0, True))

    def test_expense_cannot_claim_recoverability(self):
        with self.assertRaises(ValueError):
            inspect_purchase_tax(sample("expense", 900, True))

    def test_unknown_treatment_and_posting_bypass_rejected(self):
        for value in ("automatic", "posted", "", None, 1):
            source = sample()
            source["treatment"] = value
            with self.subTest(treatment=value), self.assertRaises(ValueError):
                inspect_purchase_tax(source)
        source = sample()
        source["approveAndPost"] = True
        with self.assertRaises(ValueError):
            inspect_purchase_tax(source)

    def test_bad_currency_and_money_fail_closed(self):
        for currency in ("TOMAN", "", None):
            source = sample()
            source["currency"] = currency
            with self.subTest(currency=currency), self.assertRaises(ValueError):
                inspect_purchase_tax(source)
        for amount in (True, False, -1, "900", 1.5, 10**16):
            source = sample()
            source["taxAmountRial"] = amount
            with self.subTest(tax=amount), self.assertRaises(ValueError):
                inspect_purchase_tax(source)

    def test_future_policy_or_invalid_date_rejected(self):
        source = sample()
        source["policyEffectiveFrom"] = "2026-12-01"
        with self.assertRaises(ValueError):
            inspect_purchase_tax(source)
        source = sample()
        source["documentDate"] = "2026-02-30"
        with self.assertRaises(ValueError):
            inspect_purchase_tax(source)

    def test_policy_name_does_not_prove_source_authenticity(self):
        source = sample()
        source["taxPolicyId"] = "verified-official"
        report = inspect_purchase_tax(source)
        self.assertFalse(report["taxPolicyAuthenticated"])
        self.assertFalse(report["postingAllowed"])


if __name__ == "__main__":
    unittest.main()
