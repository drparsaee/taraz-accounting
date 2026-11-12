"""Synthetic accounting Clarify acceptance: provenance, explicit issue and parties."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from standalone_accounting import StandaloneAccountingStore
from standalone_accounting_desktop import JS_BRIDGE
from taraz_llm_order_suggest import MODEL, SuggestionUnavailable, suggest_order


ACCOUNTS = {
    "creator": {"username": "creator", "role": "admin"},
    "reviser": {"username": "reviser", "role": "editor", "financeEdit": True},
    "reader": {"username": "reader", "role": "viewer", "financeView": True},
}
CREATED = "2026-11-11T08:00:00+00:00"
EDITED = "2026-11-11T09:00:00+00:00"
ISSUED = "2026-11-11T10:00:00+00:00"
LINES = [{"description": "Synthetic packaging service", "quantity": 2,
          "unitPrice": 300}]


class ClarifyAccountingContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="taraz-clarify-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.sqlite3"
        self.store = StandaloneAccountingStore(self.path, default_currency="RIAL")
        self.revision = 0

    def commit(self, command, *, actor="creator", now=CREATED):
        result = self.store.command(command, actor=actor, accounts=ACCOUNTS,
                                    expected_revision=self.revision, now=now)
        self.revision = result["revision"]
        return result

    def read(self, actor="reader"):
        return self.store.read(actor=actor, accounts=ACCOUNTS)

    def register(self):
        return self.commit({"type": "party.register", "eventId": "create-party-1",
                            "partyId": "customer-1", "name": "Synthetic buyer",
                            "kind": "customer"})

    def create_invoice(self):
        return self.commit({"type": "invoice.create", "eventId": "create-invoice-1",
                            "invoiceId": "invoice-1", "partyId": "customer-1",
                            "documentDate": "2026-11-10", "lines": LINES})

    def test_missing_party_cannot_be_created_by_invoice_and_error_does_not_post(self):
        with self.assertRaisesRegex(ValueError, "Missing or incompatible named party"):
            self.create_invoice()
        self.assertEqual(self.read()["revision"], 0)
        self.assertEqual(self.read()["view"]["parties"], {})
        self.assertEqual(self.read()["view"]["invoices"], {})

    def test_creation_edit_timestamps_stay_separate_from_invoice_date_and_reader(self):
        self.register()
        self.create_invoice()
        self.commit({"type": "party.update", "eventId": "edit-party-1",
                     "partyId": "customer-1", "name": "Corrected buyer",
                     "reason": "Correct spelling"}, actor="reviser", now=EDITED)
        self.commit({"type": "invoice.update", "eventId": "edit-invoice-1",
                     "invoiceId": "invoice-1", "partyId": "customer-1",
                     "documentDate": "2026-11-10", "lines": LINES,
                     "note": "Corrected commercial note"}, actor="reviser", now=EDITED)
        view = self.read(actor="reader")["view"]
        party = view["parties"]["customer-1"]
        invoice = view["invoices"]["invoice-1"]
        for record in (party, invoice):
            self.assertEqual((record["createdAt"], record["createdBy"]),
                             (CREATED, "creator"))
            self.assertEqual((record["editedAt"], record["editedBy"]),
                             (EDITED, "reviser"))
            self.assertEqual((record["lastChangedAt"], record["lastChangedBy"]),
                             (EDITED, "reviser"))
        self.assertEqual(invoice["documentDate"], "2026-11-10")
        self.assertEqual(party["name"], "Corrected buyer")
        # Changing the signed-in reader never rewrites event attribution.
        self.assertEqual(self.read(actor="creator")["view"]["invoices"]["invoice-1"]["createdBy"], "creator")

    def test_draft_preview_does_not_issue_or_post_and_issue_has_one_number(self):
        self.register()
        created = self.create_invoice()
        self.assertEqual(created["result"]["status"], "draft")
        snapshot = self.read()["view"]
        invoice = snapshot["invoices"]["invoice-1"]
        self.assertIsNone(invoice["number"])
        self.assertIsNone(invoice["postedEntryId"])
        self.assertEqual(snapshot["journals"], [])
        with self.assertRaisesRegex(ValueError, "Only approved documents may be issued"):
            self.commit({"type": "invoice.issue", "eventId": "premature-issue",
                         "invoiceId": "invoice-1", "postingDate": "2026-11-11"})
        self.assertEqual(self.revision, 2)
        self.commit({"type": "invoice.approve", "eventId": "approve-invoice-1",
                     "invoiceId": "invoice-1"}, actor="reviser", now=EDITED)
        issued = self.commit({"type": "invoice.issue", "eventId": "issue-invoice-1",
                              "invoiceId": "invoice-1", "postingDate": "2026-11-11"},
                             actor="reviser", now=ISSUED)
        final = self.read()["view"]["invoices"]["invoice-1"]
        self.assertEqual(issued["result"]["number"], 1)
        self.assertEqual((final["status"], final["number"]), ("issued", 1))
        self.assertEqual((final["createdAt"], final["createdBy"]), (CREATED, "creator"))
        self.assertNotIn("editedAt", final)
        self.assertEqual((final["lastChangedAt"], final["lastChangedBy"]),
                         (ISSUED, "reviser"))
        replay = self.commit({"type": "invoice.issue", "eventId": "issue-invoice-1",
                              "invoiceId": "invoice-1", "postingDate": "2026-11-11"},
                             actor="reviser", now="2026-11-11T11:00:00+00:00")
        self.assertEqual(replay["revision"], 4)
        self.assertEqual(self.read()["view"]["invoices"]["invoice-1"]["number"], 1)

    def test_read_only_projection_does_not_change_persisted_journal(self):
        self.register()
        self.create_invoice()
        digest_before = sha256(self.path.read_bytes()).hexdigest()
        for actor in ("creator", "reader", "reviser", "reader"):
            self.read(actor=actor)
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), digest_before)


class LocalOllamaSuggestionTests(unittest.TestCase):
    def setUp(self):
        self.answer = {
            "fields": {"customerName": "آزمایش", "title": "جعبه چاپی",
                       "quantity": "200", "productionQuantity": "220", "unit": "عدد"},
            "suggestedStages": ["print", "packaging"],
            "warnings": ["اندازه جعبه مشخص نیست"],
        }
        self.conn = Mock()
        self.response = Mock()
        self.response.status = 200
        self.response.getheader.return_value = "application/json; charset=utf-8"
        self.conn.getresponse.return_value = self.response
        self.repack()

    def repack(self, *, model=MODEL, content=None):
        if content is None:
            content = json.dumps(self.answer, ensure_ascii=False)
        self.response.read.return_value = json.dumps({
            "model": model, "response": content, "done": True,
        }, ensure_ascii=False).encode("utf-8")

    def call(self, text):
        with patch("taraz_llm_order_suggest.http.client.HTTPConnection",
                   return_value=self.conn) as factory:
            result = suggest_order(text)
        factory.assert_called_once_with("127.0.0.1", 11434, timeout=45)
        return result

    def test_user_initiated_suggestion_calls_only_loopback_and_cannot_post(self):
        self.assertIn("'tarazOrderSuggest'", JS_BRIDGE)
        result = self.call("مشتری: آزمایش\nشرح سفارش: جعبه چاپی\n200 عدد\nتولید 220\nبسته بندی")
        self.assertEqual(result["source"], "LOCAL_OLLAMA")
        self.assertTrue(result["modelRan"])
        self.assertFalse(result["financialEventCreated"])
        self.assertFalse(result["externalModelCalled"])
        self.assertEqual(result["fields"]["quantity"], "200")
        self.assertEqual(result["suggestedStages"], ["print", "packaging"])
        args, kwargs = self.conn.request.call_args
        self.assertEqual(args, ("POST", "/api/generate"))
        payload = json.loads(kwargs["body"])
        self.assertEqual(payload["model"], "qwen3:4b")
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"], {
            "temperature": 0, "num_predict": 80, "num_ctx": 512,
        })
        self.assertIn("مشتری: آزمایش", payload["prompt"])
        self.assertNotIn("messages", payload)
        self.conn.close.assert_called_once()

    def test_redacts_credentials_contacts_and_rejects_outbound_redirect(self):
        result = self.call("مشتری: آزمایش\nچاپ جعبه چاپی، 200 عدد، بسته بندی\nرمز: 123-SENSITIVE\nEmail: owner@example.com")
        payload = self.conn.request.call_args.kwargs["body"].decode("utf-8")
        self.assertNotIn("123-SENSITIVE", payload)
        self.assertNotIn("owner@example.com", payload)
        self.assertEqual(result["fields"]["quantity"], "200")
        self.response.status = 302
        with patch("taraz_llm_order_suggest.http.client.HTTPConnection",
                   return_value=self.conn):
            with self.assertRaises(SuggestionUnavailable):
                suggest_order("200 عدد")

    def test_rejects_untrusted_json_model_and_unbounded_response(self):
        cases = [
            ("other-model", None),
            (MODEL, "not-json"),
            (MODEL, '{"fields":{},"fields":{},"suggestedStages":[],"warnings":[]}'),
            (MODEL, json.dumps({**self.answer, "issueInvoice": True})),
            (MODEL, json.dumps({**self.answer, "suggestedStages": ["illegal"]})),
        ]
        for model, content in cases:
            with self.subTest(content=content, model=model):
                self.repack(model=model, content=content)
                with patch("taraz_llm_order_suggest.http.client.HTTPConnection",
                           return_value=self.conn):
                    with self.assertRaises(SuggestionUnavailable):
                        suggest_order("200 عدد")
        self.repack()
        self.response.read.return_value = b"x" * 24001
        with patch("taraz_llm_order_suggest.http.client.HTTPConnection",
                   return_value=self.conn):
            with self.assertRaises(SuggestionUnavailable):
                suggest_order("200 عدد")

    def test_no_invented_quantities_and_no_fake_model_on_connection_error(self):
        result = self.call("درخواست چاپ بسته بندی")
        self.assertEqual(result["fields"]["quantity"], "")
        self.assertEqual(result["fields"]["productionQuantity"], "")
        self.assertIn("تعداد سفارش", result["missing"])
        self.assertIn("تعداد تولید برنامه‌ای", result["missing"])
        with patch("taraz_llm_order_suggest.http.client.HTTPConnection",
                   side_effect=OSError("local model offline")):
            with self.assertRaises(SuggestionUnavailable):
                suggest_order("200 عدد")
        with self.assertRaises(ValueError):
            suggest_order("-----BEGIN PRIVATE KEY----- secret")
        with self.assertRaises(ValueError):
            suggest_order(" " * 10)

    def test_ungrounded_identity_title_unit_and_price_are_not_filled(self):
        self.answer["suggestedStages"] = []
        self.repack()
        result = self.call("قیمت 200 تومان؛ تولید 220")
        self.assertEqual(result["fields"]["quantity"], "")
        self.assertEqual(result["fields"]["productionQuantity"], "220")
        self.assertEqual(result["fields"]["customerName"], "")
        self.assertEqual(result["fields"]["title"], "")
        self.assertEqual(result["fields"]["unit"], "")
        self.assertIn("نام مشتری", result["missing"])
        self.assertIn("تعداد سفارش", result["missing"])

    def test_fabricated_allowed_stage_fails_closed_even_if_one_stage_is_real(self):
        self.answer["fields"] = {
            "customerName": "", "title": "", "quantity": "200",
            "productionQuantity": "", "unit": "",
        }
        self.answer["suggestedStages"] = [
            "print", "bindery", "laser", "packaging", "shipping", "material", "other",
        ]
        self.repack()
        with patch("taraz_llm_order_suggest.http.client.HTTPConnection",
                   return_value=self.conn):
            with self.assertRaisesRegex(SuggestionUnavailable, "ungrounded stages"):
                suggest_order("چاپ 200 عدد بروشور")

    def test_empty_model_response_with_all_missing_fields_fails_closed(self):
        self.answer["fields"] = {
            "customerName": "", "title": "", "quantity": "",
            "productionQuantity": "", "unit": "",
        }
        self.answer["suggestedStages"] = []
        self.answer["warnings"] = []
        self.repack()
        with patch("taraz_llm_order_suggest.http.client.HTTPConnection",
                   return_value=self.conn):
            with self.assertRaisesRegex(SuggestionUnavailable, "no grounded order information"):
                suggest_order("چاپ 200 عدد بروشور")

    def test_short_realistic_order_never_invents_party_or_production(self):
        self.answer["fields"] = {
            "customerName": "کارخانه ساختگی", "title": "بروشور",
            "quantity": "200", "productionQuantity": "240", "unit": "عدد",
        }
        self.answer["suggestedStages"] = ["print"]
        self.answer["warnings"] = []
        self.repack()
        result = self.call("چاپ 200 عدد بروشور")
        self.assertEqual(result["fields"], {
            "customerName": "", "title": "بروشور",
            "quantity": "200", "productionQuantity": "", "unit": "عدد",
        })
        self.assertEqual(result["suggestedStages"], ["print"])
        self.assertIn("نام مشتری", result["missing"])
        self.assertIn("تعداد تولید برنامه‌ای", result["missing"])

    def test_incomplete_generate_response_never_claims_model_success(self):
        self.repack()
        self.response.read.return_value = json.dumps({
            "model": MODEL, "response": json.dumps(self.answer),
            "done": False,
        }).encode("utf-8")
        with patch("taraz_llm_order_suggest.http.client.HTTPConnection",
                   return_value=self.conn):
            with self.assertRaises(SuggestionUnavailable):
                suggest_order("200 عدد")


if __name__ == "__main__":
    unittest.main()
