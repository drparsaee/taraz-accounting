"""Synthetic, deterministic 100-passport commercial case acceptance.

No real Taraz company or Madar card is opened and no financial event posted.
"""
from copy import deepcopy
import unittest

from taraz_project_financial_case import FinancialCaseError, build_financial_case


def amount(value, currency="TOMAN"):
    return {"amount": value, "currency": currency}


def stage(ident, operation, description, *, supplier=None, items=None,
          internal=None, expense=None, payment=None):
    return {
        "id": ident, "operation": operation, "description": description,
        "supplierId": supplier, "items": items or [],
        "internalCost": internal, "expense": expense, "payment": payment,
    }


def item(description, quantity, price=None):
    return {"description": description, "quantity": quantity,
            "unit": "sheet" if "چاپ" in description else "piece",
            "unitPrice": price}


def passport_fixture():
    return {
        "schemaVersion": 2,
        "eventId": "a" * 32, "idempotencyKey": "b" * 32,
        "taskId": "card-passport-100", "projectId": "project-passport",
        "sourceRevision": 7, "sourceActorId": "madar-user-01",
        "sourceTimestamp": "2026-11-16T13:30:00+03:30",
        "title": "تولید ۱۰۰ عدد پاسپورت",
        "customerId": "customer-001", "quantity": 100, "unit": "عدد",
        "saleUnitPrice": None, "invoiceProfileId": None,
        "stages": [
            stage("print", "external_service", "خرید خدمات چاپ",
                  supplier="vendor-ramin",
                  items=[item("چاپ یک‌رو", 60), item("چاپ دورو", 120)]),
            stage("fold", "internal_work", "خط تا توسط خود کاربر"),
            stage("cut", "internal_work", "برش توسط خود کاربر"),
            stage("sew", "external_service", "دوخت ۱۲۰ عدد",
                  supplier="vendor-sewing",
                  items=[item("دوخت پاسپورت", 120, amount(20_000))],
                  payment={"method": "card", "accountId": None, "date": None,
                           "receipt": None, "confirmed": False}),
            stage("travel", "additional_expense", "رفت‌وآمد",
                  expense=amount(200_000)),
        ],
    }


class HundredPassportsPurePreviewTests(unittest.TestCase):
    def test_passport_financial_case_preserves_unknowns_and_no_posting(self):
        source = passport_fixture()
        before = deepcopy(source)
        result = build_financial_case(source, expected_revision=7)
        self.assertEqual(source, before)
        self.assertEqual(result["sales"]["line"]["quantity"], 100)
        self.assertIsNone(result["sales"]["line"]["unitPriceRial"])
        self.assertEqual(len(result["purchaseDrafts"]), 2)
        self.assertEqual(len(result["purchaseDrafts"][0]["lines"]), 2)
        self.assertEqual(result["purchaseDrafts"][0]["lines"][0]["quantity"], 60)
        self.assertEqual(result["purchaseDrafts"][0]["lines"][1]["quantity"], 120)
        self.assertIsNone(result["purchaseDrafts"][0]["totalRial"])
        self.assertEqual(result["purchaseDrafts"][1]["totalRial"], 24_000_000)
        self.assertEqual(result["additionalExpenses"][0]["amountRial"], 2_000_000)
        self.assertEqual(result["knownCostsRial"], 26_000_000)
        self.assertEqual(result["internalWork"][0]["internalCostRial"], None)
        self.assertEqual(result["internalWork"][1]["internalCostRial"], None)
        self.assertEqual(result["paymentProposals"][0]["status"], "unverified")
        self.assertEqual(result["paymentProposals"][0]["amountRial"], 24_000_000)
        self.assertEqual(result["paymentProposals"][0]["linkedExpenseStageId"], "sew")
        self.assertIsNone(result["profitRial"])
        self.assertFalse(result["profitComputable"])
        self.assertFalse(result["profitIsFinal"])
        self.assertIn("purchasePrice:print", result["missing"])
        self.assertIn("internalCost:fold", result["missing"])
        self.assertIn("internalCost:cut", result["missing"])
        self.assertIn("paymentAccount:sew", result["missing"])
        self.assertIn("paymentDate:sew", result["missing"])
        self.assertEqual(result["status"], "UNTRUSTED_SOURCE_REVIEW_PREVIEW_ONLY")
        self.assertFalse(result["sourceAuthenticated"])
        self.assertFalse(result["readyToPost"])
        self.assertFalse(result["officialInvoiceCreated"])
        self.assertEqual(result["journalEntriesCreated"], 0)

    def test_complete_price_preview_does_not_approve_or_post(self):
        data = passport_fixture()
        data["saleUnitPrice"] = amount(100_000)
        data["stages"][0]["items"][0]["unitPrice"] = amount(10_000)
        data["stages"][0]["items"][1]["unitPrice"] = amount(15_000)
        data["stages"][1]["internalCost"] = amount(100_000)
        data["stages"][2]["internalCost"] = amount(50_000)
        data["stages"][3]["payment"]["accountId"] = "bank-01"
        data["stages"][3]["payment"]["date"] = "2026-11-16"
        result = build_financial_case(data, expected_revision=7)
        expected_costs = (6_000_000 + 18_000_000 + 1_500_000 +
                          24_000_000 + 2_000_000)
        self.assertEqual(result["knownCostsRial"], expected_costs)
        self.assertEqual(result["sales"]["line"]["subtotalRial"], 100_000_000)
        self.assertEqual(result["profitRial"], 100_000_000-expected_costs)
        self.assertTrue(result["profitComputable"])
        self.assertFalse(result["profitIsFinal"])
        self.assertFalse(result["amountsSourceVerified"])
        self.assertEqual(result["missing"], [])
        self.assertFalse(result["readyToPost"])
        self.assertEqual(result["journalEntriesCreated"], 0)

    def test_revision_and_duplicates_fail_closed(self):
        data = passport_fixture()
        with self.assertRaises(FinancialCaseError):
            build_financial_case(data, expected_revision=8)
        other = deepcopy(data)
        other["stages"][1]["id"] = "print"
        with self.assertRaises(FinancialCaseError):
            build_financial_case(other, expected_revision=7)

    def test_ambiguous_currency_and_overflow_fail_closed(self):
        for bad in ({"amount": 10, "currency": "USD"},
                    {"amount": 10, "currency": []},
                    {"amount": True, "currency": "TOMAN"},
                    {"amount": 10**16, "currency": "RIAL"},
                    {"amount": 9.99, "currency": "TOMAN"}):
            data = passport_fixture()
            data["stages"][3]["items"][0]["unitPrice"] = bad
            with self.subTest(bad=bad), self.assertRaises(FinancialCaseError):
                build_financial_case(data, expected_revision=7)

    def test_untrusted_card_cannot_assert_bank_payment(self):
        data = passport_fixture()
        data["stages"][3]["payment"]["confirmed"] = True
        with self.assertRaises(FinancialCaseError):
            build_financial_case(data, expected_revision=7)

    def test_internal_work_cannot_create_external_expense(self):
        data = passport_fixture()
        data["stages"][1]["supplierId"] = "vendor-fake"
        with self.assertRaises(FinancialCaseError):
            build_financial_case(data, expected_revision=7)

    def test_negative_integer_and_missing_date_rejected(self):
        for new in (0, -1, True, 2.5):
            data = passport_fixture()
            data["quantity"] = new
            with self.subTest(quantity=new), self.assertRaises(FinancialCaseError):
                build_financial_case(data, expected_revision=7)
        data = passport_fixture()
        data["stages"][3]["payment"]["date"] = "2026-02-30"
        with self.assertRaises(FinancialCaseError):
            build_financial_case(data, expected_revision=7)

    def test_unknown_schema_fields_and_spoofed_event_rejected(self):
        data = passport_fixture()
        data["grantAdmin"] = True
        with self.assertRaises(FinancialCaseError):
            build_financial_case(data, expected_revision=7)
        data = passport_fixture()
        data["eventId"] = "synthetic-admin"
        with self.assertRaises(FinancialCaseError):
            build_financial_case(data, expected_revision=7)

    def test_stable_digest_repeat_read_only(self):
        data = passport_fixture()
        a = build_financial_case(data, expected_revision=7)
        b = build_financial_case(deepcopy(data), expected_revision=7)
        self.assertEqual(a, b)
        data["stages"][0]["items"][0]["unitPrice"] = amount(1)
        c = build_financial_case(data, expected_revision=7)
        self.assertNotEqual(a["sourceDigest"], c["sourceDigest"])
        self.assertEqual(c["journalEntriesCreated"], 0)


if __name__ == "__main__":
    unittest.main()
