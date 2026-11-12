"""Real native template API against disposable company folders, never user books."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from standalone_accounting_desktop import AccountingDesktopAPI, JS_BRIDGE
from standalone_accounting_template_store import (
    StandaloneAccountingTemplateStore, TemplateStoreError,
)
from taraz_desktop import TarazAPI


REPO = Path(__file__).resolve().parents[1]
QA_PARENT = REPO.parent


def print_design(title="فاکتور قابل ویرایش"):
    ids = ("title", "seller", "buyer", "number", "date", "note")
    return {
        "format": "madar-print-layout-v1", "version": 1, "title": title,
        "page": "A4", "orientation": "portrait", "margin": 10,
        "font": "Vazirmatn", "color": "#203239", "logo": "",
        "fields": [{"id": ident, "label": ident, "visible": True,
                    "x": 100, "y": 40, "size": 12} for ident in ids],
        "table": {"y": 96, "showQuantity": True, "showPrice": True,
                  "showTotal": True},
        "totalsY": 273, "signature": "مهر و امضا",
    }


class SyntheticIdentity:
    _levels = {"viewer": 0, "editor": 1, "admin": 2}

    def __init__(self, username, role):
        self.user = {"username": username, "role": role, "jobTitle": ""}
        self.revoked = False

    def require_session(self, token, required="viewer"):
        if (self.revoked or token != "synthetic-token" or
                self._levels[self.user["role"]] < self._levels[required]):
            raise PermissionError("Synthetic identity denied")
        return dict(self.user)

    def accounting_accounts(self):
        return {self.user["username"]: dict(self.user)}


class TarazInvoiceTemplateBridgeTests(unittest.TestCase):
    def setUp(self):
        self.qa = tempfile.TemporaryDirectory(prefix="qa-taraz-print-", dir=QA_PARENT)
        self.addCleanup(self.qa.cleanup)
        self.root = Path(self.qa.name)
        self.company_a = self.root / "Company-A"
        self.company_b = self.root / "Company-B"
        self.company_a.mkdir()
        self.company_b.mkdir()

    def test_real_taraz_api_print_crud_survives_reload_per_company(self):
        api = TarazAPI(self.company_a)
        self.assertEqual(api.standaloneAccountingTemplateList("print"),
                         {"templates": [], "defaultId": ""})
        record = api.standaloneAccountingTemplateSave(
            "print", "چاپ رسمی", print_design())
        self.assertRegex(record["id"], r"^[a-f0-9]{32}$")
        initial_id = record["id"]
        self.assertEqual(api.standaloneAccountingTemplateList("print")["defaultId"],
                         initial_id)
        revised = print_design("چاپ رسمی - اصلاح شده")
        revised["fields"][0]["x"] = 165
        revised["table"]["showPrice"] = False
        api.standaloneAccountingTemplateSave("print", "چاپ ویرایش شده", revised,
                                            initial_id)
        reopened = TarazAPI(self.company_a)
        library = reopened.standaloneAccountingTemplateList("print")
        self.assertEqual(len(library["templates"]), 1)
        self.assertEqual(library["templates"][0]["data"], revised)
        self.assertEqual(library["templates"][0]["title"], "چاپ ویرایش شده")
        duplicate = reopened.standaloneAccountingTemplateDuplicate("print", initial_id)
        self.assertNotEqual(duplicate["id"], initial_id)
        reopened.standaloneAccountingTemplateDefault("print", duplicate["id"])
        self.assertEqual(reopened.standaloneAccountingTemplateList("print")["defaultId"],
                         duplicate["id"])
        reopened.standaloneAccountingTemplateDelete("print", duplicate["id"])
        self.assertEqual(reopened.standaloneAccountingTemplateList("print")["defaultId"],
                         initial_id)
        self.assertEqual(TarazAPI(self.company_b).standaloneAccountingTemplateList("print"),
                         {"templates": [], "defaultId": ""})
        with self.assertRaises(TemplateStoreError):
            TarazAPI(self.company_b).standaloneAccountingTemplateSave(
                "print", "سرقت قالب", revised, initial_id)
        self.assertFalse(list(self.root.rglob("*.sqlite3")),
                         "Template CRUD must not create accounting ledger events")
        self.assertIn("standaloneAccountingTemplateSave", JS_BRIDGE)

    def test_viewer_can_list_but_cannot_change_templates(self):
        template_id = TarazAPI(self.company_a).standaloneAccountingTemplateSave(
            "print", "پایه", print_design())["id"]
        store_file = self.company_a / "invoice-templates.json"
        baseline = store_file.read_bytes()
        identity = SyntheticIdentity("viewer-a", "viewer")
        api = AccountingDesktopAPI(
            self.company_a, identity_store=identity,
            identity_token="synthetic-token", authenticated_user=identity.user)
        self.assertEqual(api.standaloneAccountingTemplateList("print")["defaultId"],
                         template_id)
        with self.assertRaises(PermissionError):
            api.standaloneAccountingTemplateSave("print", "ممنوع", print_design())
        with self.assertRaises(PermissionError):
            api.standaloneAccountingTemplateDelete("print", template_id)
        with self.assertRaises(PermissionError):
            api.standaloneAccountingTemplateDefault("print", template_id)
        with self.assertRaises(PermissionError):
            api.standaloneAccountingTemplateDuplicate("print", template_id)
        self.assertEqual(store_file.read_bytes(), baseline)
        identity.revoked = True
        with self.assertRaises(PermissionError):
            api.standaloneAccountingTemplateList("print")

    def test_editor_writes_and_close_guard_rejects_late_changes(self):
        identity = SyntheticIdentity("editor-b", "editor")
        api = AccountingDesktopAPI(
            self.company_b, identity_store=identity,
            identity_token="synthetic-token", authenticated_user=identity.user)
        item = api.standaloneAccountingTemplateSave("print", "طراح", print_design())
        self.assertEqual(api.standaloneAccountingTemplateList("print")["defaultId"],
                         item["id"])
        api._exit_backed_up = True
        before = (self.company_b / "invoice-templates.json").read_bytes()
        with self.assertRaises(RuntimeError):
            api.standaloneAccountingTemplateSave("print", "ویرایش دیرهنگام",
                                                 print_design(), item["id"])
        with self.assertRaises(RuntimeError):
            api.standaloneAccountingTemplateDuplicate("print", item["id"])
        self.assertEqual((self.company_b / "invoice-templates.json").read_bytes(),
                         before)

    def test_invalid_designer_payload_cannot_damage_saved_library(self):
        store = StandaloneAccountingTemplateStore(self.company_a)
        saved = store.save("print", "طرح اصلی", print_design())
        before = (self.company_a / "invoice-templates.json").read_bytes()
        defects = (
            ("no_table", lambda x: x.pop("table")),
            ("bad_font", lambda x: x.update(font=["Arial"])),
            ("bad_color", lambda x: x.update(color="red")),
            ("bad_margin", lambda x: x.update(margin=True)),
            ("bad_coordinate", lambda x: x["fields"][0].update(x=-1)),
            ("duplicate_field", lambda x: x["fields"][1].update(id="title")),
            ("bad_visibility", lambda x: x["fields"][0].update(visible="yes")),
            ("bad_table", lambda x: x["table"].update(y=float("nan"))),
            ("missing_signature", lambda x: x.pop("signature")),
            ("bad_logo", lambda x: x.update(logo="file:///secret")),
        )
        for label, change in defects:
            with self.subTest(label=label):
                invalid = deepcopy(print_design())
                change(invalid)
                with self.assertRaises(TemplateStoreError):
                    store.save("print", "نباید ذخیره شود", invalid, saved["id"])
                self.assertEqual((self.company_a / "invoice-templates.json").read_bytes(),
                                 before)
        self.assertEqual(store.list("print")["templates"][0]["id"], saved["id"])

    def test_corrupt_existing_file_blocks_reads_without_reset(self):
        source = StandaloneAccountingTemplateStore(self.company_a)
        source.save("print", "قبلی", print_design())
        path = self.company_a / "invoice-templates.json"
        obj = json.loads(path.read_text(encoding="utf-8"))
        obj["templates"][0]["data"]["fields"][0]["size"] = 5000
        corrupted = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        path.write_bytes(corrupted)
        with self.assertRaises(TemplateStoreError):
            source.list("print")
        with self.assertRaises(TemplateStoreError):
            source.save("print", "جدید", print_design())
        self.assertEqual(path.read_bytes(), corrupted)


if __name__ == "__main__":
    unittest.main()
