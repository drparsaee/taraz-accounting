"""Registered-company private CDP entitlement is never a production debug port.

All data lives under a disposable QA roaming root; no GUI or EXE is run.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from standalone_accounting_company_registry import StandaloneCompanyRegistry
from taraz_desktop import private_qa_cdp_port


class RegisteredCompanyCdpGateTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(prefix="qa-taraz-registered-cdp-")
        self.addCleanup(tmp.cleanup)
        self.roaming = Path(tmp.name) / "qa" / "qa-runtime" / "roaming"
        self.hub = self.roaming / "Taraz"
        self.hub.mkdir(parents=True)
        self.registry = StandaloneCompanyRegistry(self.hub)
        self.company = self.registry.create_company("QA registered company")
        self.book = self.registry.company_data_directory(self.company["id"])
        self.marker = self.book / ".taraz-private-cdp-qa.json"
        self.marker.write_text(json.dumps({
            "privateQaOnly": True, "profile": str(self.book.resolve())}), encoding="utf-8")
        self.env = {"APPDATA": str(self.roaming),
                    "TARAZ_QA_DATA_DIR": str(self.hub),
                    "TARAZ_QA_MODE": "1", "TARAZ_QA_CDP_PORT": "49152"}

    def test_registered_company_qa_id_and_marker_allowed(self):
        self.assertEqual(private_qa_cdp_port(self.book, self.env), 49152)

    def test_unregistered_company_id_cannot_open_private_debug(self):
        forged = self.hub / "books" / ("f" * 32)
        forged.mkdir()
        (forged / self.marker.name).write_text(json.dumps({
            "privateQaOnly": True, "profile": str(forged.resolve())}), encoding="utf-8")
        with self.assertRaises(PermissionError):
            private_qa_cdp_port(forged, self.env)

    def test_missing_marker_or_forged_roaming_authority_blocked(self):
        self.marker.unlink()
        with self.assertRaises(PermissionError):
            private_qa_cdp_port(self.book, self.env)
        self.marker.write_text(json.dumps({
            "privateQaOnly": True, "profile": str(self.book.resolve())}), encoding="utf-8")
        with self.assertRaises(PermissionError):
            private_qa_cdp_port(self.book, {**self.env, "APPDATA": str(self.roaming.parent)})
        with self.assertRaises(PermissionError):
            private_qa_cdp_port(self.book, {**self.env, "TARAZ_QA_MODE": "0"})


if __name__ == "__main__":
    unittest.main()
