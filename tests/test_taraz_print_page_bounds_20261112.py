"""UI/backend parity for physical print bounds; ephemeral company data only."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from standalone_accounting_template_store import StandaloneAccountingTemplateStore, TemplateStoreError
from tests.test_taraz_invoice_template_bridge_20261110 import print_design


class PrintPageBoundsAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="qa-taraz-paper-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = StandaloneAccountingTemplateStore(self.path)

    def test_reject_print_table_outside_A5_page_without_mutating_saved_template(self):
        baseline = self.store.save("print", "valid", print_design())
        original = (self.path / "invoice-templates.json").read_bytes()
        wrong = deepcopy(print_design())
        wrong.update(page="A5", margin=7)
        wrong["table"].update(y=205, rowHeight=8.5)
        with self.assertRaises(TemplateStoreError):
            self.store.save("print", "off paper", wrong, baseline["id"])
        self.assertEqual((self.path / "invoice-templates.json").read_bytes(), original)

    def test_landscape_A5_rejects_overflow_but_accepts_printable_table(self):
        candidate = deepcopy(print_design())
        candidate.update(page="A5", orientation="landscape", margin=7)
        candidate["table"].update(y=110, rowHeight=8.5)
        with self.assertRaises(TemplateStoreError):
            self.store.save("print", "out of page", candidate)
        candidate["table"]["y"] = 68
        saved = self.store.save("print", "inside page", candidate)
        self.assertEqual(self.store.list("print")["templates"][0]["id"], saved["id"])

    def test_reject_unsupported_row_heights_and_legacy_A4_still_works(self):
        self.assertTrue(self.store.save("print", "legacy", print_design())["id"])
        for value in (0, 100, True, "8.5", float("nan")):
            with self.subTest(value=str(value)):
                candidate = deepcopy(print_design())
                candidate["table"]["rowHeight"] = value
                with self.assertRaises(TemplateStoreError):
                    self.store.save("print", "invalid row height", candidate)

    def test_reject_invalid_canvas_columns_logo_and_company_metadata_before_write(self):
        saved = self.store.save("print", "baseline", print_design())
        original = (self.path / "invoice-templates.json").read_bytes()
        changes = [
            ("duplicate_columns", lambda d: d["table"].update(columns=["description", "description"])),
            ("unknown_column", lambda d: d["table"].update(columns=["description", "privateSecret"])),
            ("missing_description", lambda d: d["table"].update(columns=["unit", "total"])),
            ("invalid_column_labels", lambda d: d["table"].update(labels={"description": ""})),
            ("off_page_logo", lambda d: d.update(logoLayout={
                "x": 204, "y": 15, "width": 36, "height": 23})),
            ("bad_company_header", lambda d: d.update(companyHeader=["company"])),
        ]
        for label, mutate in changes:
            with self.subTest(label=label):
                candidate = deepcopy(print_design())
                mutate(candidate)
                with self.assertRaises(TemplateStoreError):
                    self.store.save("print", "invalid designer data", candidate, saved["id"])
                self.assertEqual((self.path / "invoice-templates.json").read_bytes(), original)
        valid = deepcopy(print_design())
        valid["table"].update(columns=["description", "unit", "total"],
                              labels={"description": "شرح", "quantity": "تعداد",
                                      "price": "فی", "total": "جمع"})
        valid.update(companyHeader="شرکت نمونه", companySubtitle="آدرس نمونه", footerText="پاورقی",
                     logoLayout={"x": 12, "y": 12, "width": 36, "height": 23})
        self.store.save("print", "valid extended", valid, saved["id"])
        self.assertEqual(self.store.list("print")["templates"][0]["data"], valid)

    def test_custom_column_persists_across_reopen_and_forged_sources_fail_closed(self):
        template = deepcopy(print_design())
        template["table"]["customColumns"] = [{
            "id": "custom_1", "label": "واحد سفارشی", "source": "unit"}]
        template["table"]["columns"] = ["description", "custom_1", "quantity", "total"]
        saved = self.store.save("print", "user-defined column", template)
        self.assertEqual(self.store.list("print")["templates"][0]["data"], template)
        # New store instance must reload the real company-scoped JSON file.
        reopened = StandaloneAccountingTemplateStore(self.path)
        self.assertEqual(reopened.list("print")["templates"][0]["id"], saved["id"])
        self.assertEqual(reopened.list("print")["templates"][0]["data"], template)
        original = (self.path / "invoice-templates.json").read_bytes()
        bad_cases = [
            lambda t: t["table"]["customColumns"][0].update(source="__import__"),
            lambda t: t["table"]["customColumns"][0].update(id="custom_9"),
            lambda t: t["table"]["customColumns"][0].update(label="🎁" * 13),
            lambda t: t["table"]["customColumns"].append(
                {"id": "custom_1", "label": "تکراری", "source": "unit"}),
            lambda t: t["table"]["customColumns"][0].update(script="evaluate()"),
            lambda t: t["table"]["columns"].append("not_defined"),
        ]
        for change in bad_cases:
            with self.subTest(index=bad_cases.index(change)):
                forged = deepcopy(template)
                change(forged)
                with self.assertRaises(TemplateStoreError):
                    self.store.save("print", "invalid custom", forged, saved["id"])
                self.assertEqual((self.path / "invoice-templates.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
