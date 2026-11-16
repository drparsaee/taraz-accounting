"""Commercial InvoiceProfile foundation, on real template API in disposable books.

The legal issuer and the accounting ledger are deliberately not mutated.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from standalone_accounting_desktop import AccountingDesktopAPI
from standalone_accounting_template_store import TemplateStoreError
from taraz_desktop import TarazAPI
from tests.test_taraz_invoice_template_bridge_20261110 import (
    SyntheticIdentity, print_design,
)


def brand(name: str = "کارما", print_id: str = "") -> dict:
    return {
        "format": "taraz-commercial-invoice-profile-v1",
        "profile": {
            "displayName": name, "header": "چاپ و تبلیغات",
            "contact": "تلفن تست", "logo": "", "printTemplateId": print_id,
        },
    }


class InvoiceProfileFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qa-taraz-profile-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a = self.root / "company-a"
        self.b = self.root / "company-b"
        self.a.mkdir()
        self.b.mkdir()

    def test_two_commercial_brands_single_company_single_ledger(self):
        api = TarazAPI(self.a)
        print_template = api.standaloneAccountingTemplateSave(
            "print", "چاپ تجاری", print_design())["id"]
        first = api.standaloneAccountingTemplateSave(
            "brand", "کارما", brand("کارما", print_template))
        second = api.standaloneAccountingTemplateSave(
            "brand", "بارنگ", brand("بارنگ"))
        self.assertNotEqual(first["id"], second["id"])
        result = TarazAPI(self.a).standaloneAccountingTemplateList("brand")
        self.assertEqual(len(result["templates"]), 2)
        self.assertEqual(result["defaultId"], first["id"])
        self.assertEqual(
            result["templates"][0]["data"]["profile"]["printTemplateId"], print_template)
        self.assertFalse(list(self.root.rglob("*.sqlite3")), "No accounting ledger writes")
        self.assertEqual(TarazAPI(self.b).standaloneAccountingTemplateList("brand"),
                         {"templates": [], "defaultId": ""})

    def test_duplicate_display_name_and_tax_identity_fields_forbidden(self):
        api = TarazAPI(self.a)
        first = api.standaloneAccountingTemplateSave("brand", "کارما", brand())
        before = (self.a / "invoice-templates.json").read_bytes()
        with self.assertRaises(TemplateStoreError):
            api.standaloneAccountingTemplateSave("brand", "نام دوم", brand("  کـارما  "))
        # Literal name match is checked when identical Unicode is provided.
        with self.assertRaises(TemplateStoreError):
            api.standaloneAccountingTemplateSave("brand", "نام دوم", brand("کارما"))
        with self.assertRaises(TemplateStoreError):
            bad = brand()
            bad["profile"]["nationalId"] = "fake-tax-identity"
            api.standaloneAccountingTemplateSave("brand", "غیرمجاز", bad, first["id"])
        self.assertEqual((self.a / "invoice-templates.json").read_bytes(), before)

    def test_invalid_references_cannot_orphan_brand(self):
        api = TarazAPI(self.a)
        with self.assertRaises(TemplateStoreError):
            api.standaloneAccountingTemplateSave("brand", "پیوند ساختگی",
                                                 brand("کارما", "a"*32))
        print_id = api.standaloneAccountingTemplateSave(
            "print", "چاپ", print_design())["id"]
        api.standaloneAccountingTemplateSave("brand", "کارما", brand("کارما", print_id))
        with self.assertRaises(TemplateStoreError):
            api.standaloneAccountingTemplateDelete("print", print_id)
        self.assertEqual(
            len(TarazAPI(self.a).standaloneAccountingTemplateList("brand")["templates"]), 1)

    def test_read_only_access_and_revoked_session(self):
        api = TarazAPI(self.a)
        record = api.standaloneAccountingTemplateSave("brand", "کارما", brand())
        identity = SyntheticIdentity("viewer", "viewer")
        viewer = AccountingDesktopAPI(
            self.a, identity_store=identity,
            identity_token="synthetic-token", authenticated_user=identity.user)
        self.assertEqual(viewer.standaloneAccountingTemplateList("brand")["defaultId"],
                         record["id"])
        with self.assertRaises(PermissionError):
            viewer.standaloneAccountingTemplateSave("brand", "بارنگ", brand("بارنگ"))
        with self.assertRaises(PermissionError):
            viewer.standaloneAccountingTemplateDelete("brand", record["id"])
        identity.revoked = True
        with self.assertRaises(PermissionError):
            viewer.standaloneAccountingTemplateList("brand")

    def test_malformed_logo_and_disallowed_url_fail_closed(self):
        api = TarazAPI(self.a)
        for invalid in ("https://example.com/logo.png", "file:///secret.png",
                        "data:image/svg+xml;base64,AAAA", "x"*300001):
            with self.subTest(invalid=invalid[:30]):
                broken = brand()
                broken["profile"]["logo"] = invalid
                with self.assertRaises(TemplateStoreError):
                    api.standaloneAccountingTemplateSave("brand", "کارما", broken)
        self.assertFalse((self.a / "invoice-templates.json").exists())

    def test_brand_contact_cannot_exceed_print_footer_capacity(self):
        api = TarazAPI(self.a)
        invalid = brand()
        invalid["profile"]["contact"] = "x" * 71
        with self.assertRaises(TemplateStoreError):
            api.standaloneAccountingTemplateSave("brand", "کارما", invalid)
        self.assertFalse((self.a / "invoice-templates.json").exists())

    def test_preexisting_issuer_stays_separate_after_new_brand(self):
        api = TarazAPI(self.a)
        legal = {"format": "madar-issuer-profile-v1", "profile": {
            "legalName": "شخص حقوقی ثبت‌شده", "nationalId": "1234567890"}}
        api.standaloneAccountingTemplateSave("issuer", "هویت رسمی", legal)
        before = deepcopy(api.standaloneAccountingTemplateList("issuer"))
        api.standaloneAccountingTemplateSave("brand", "کارما", brand())
        self.assertEqual(TarazAPI(self.a).standaloneAccountingTemplateList("issuer"), before)
        self.assertFalse(list(self.root.rglob("*.sqlite3")))


if __name__ == "__main__":
    unittest.main()
