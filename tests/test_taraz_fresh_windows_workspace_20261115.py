"""Fresh local-account startup only, never touching any user's Taraz profile."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from taraz_fresh_windows_workspace import (
    MARKER, FreshStartBlocked, inspect_fresh_workspace,
    open_fresh_company, stage_new_empty_root,
)
from standalone_accounting_company_registry import StandaloneCompanyRegistry


@unittest.skipUnless(os.name == "nt", "Windows DPAPI principal required")
class NewLocalBookTests(unittest.TestCase):
    def setUp(self):
        output = Path(__file__).resolve().parents[1] / "tests" / "output"
        output.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=output, prefix="qa-fresh-user-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Taraz"

    def test_first_run_starts_empty_with_windows_admin(self):
        setup = stage_new_empty_root(self.root)
        self.assertEqual(setup["ledgerRevision"], 0)
        self.assertEqual(setup["role"], "admin")
        self.assertEqual(setup["mode"], "windows-local-fresh")
        info = inspect_fresh_workspace(self.root)
        self.assertEqual(info["companyId"], setup["companyId"])
        api, identity, token = open_fresh_company(self.root)
        try:
            read = api.standaloneAccountingRead()
            self.assertEqual(read["revision"], 0)
            self.assertFalse(read["view"]["invoices"])
            self.assertFalse(read["view"]["journals"])
            self.assertIs(read["view"].get("freshWindowsWorkspace"), True)
            # Frontend must avoid invoking the legacy endpoint. The actual
            # personal-ledger guard must remain CLOSED for a new book.
            with self.assertRaisesRegex(PermissionError, "Unverified personal accounting ledger"):
                api.standaloneAccountingParsianHistory()
        finally:
            identity.logout(token)

    def test_refuses_to_overwrite_existing_legacy_data(self):
        self.root.mkdir()
        (self.root / "standalone-accounting.sqlite3").write_bytes(b"legacy")
        with self.assertRaises(FreshStartBlocked):
            stage_new_empty_root(self.root)
        self.assertEqual((self.root / "standalone-accounting.sqlite3").read_bytes(), b"legacy")

    def test_refuses_windows_binding_tampering(self):
        setup = stage_new_empty_root(self.root)
        reg = StandaloneCompanyRegistry(self.root)
        book = reg.company_data_directory(setup["companyId"])
        marker = book / MARKER
        doc = json.loads(marker.read_text(encoding="utf-8"))
        doc["windowsSid"] = "S-1-5-21-0-0-0-1234"
        marker.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(FreshStartBlocked):
            inspect_fresh_workspace(self.root)

    def test_does_not_recreate_missing_existing_ledger(self):
        result = stage_new_empty_root(self.root)
        book = StandaloneCompanyRegistry(self.root).company_data_directory(
            result["companyId"])
        (book / "standalone-accounting.sqlite3").unlink()
        with self.assertRaises(FreshStartBlocked):
            inspect_fresh_workspace(self.root)
        self.assertFalse((book / "standalone-accounting.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
