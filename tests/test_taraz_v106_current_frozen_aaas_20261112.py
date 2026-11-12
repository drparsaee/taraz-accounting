"""Independent read-only integrity witness of a specific *uninstalled* Taraz EXE.

Does not call the candidate builder or trust its module-list assertion.
It reopens the packed binary, checks embedded PYZ code and compiled GUI bytes.
No GUI, bank, Taraz ledger, installation, activation or data write.
"""
import hashlib
import json
import os
from pathlib import Path
import types
import unittest
import zipfile

from PyInstaller.archive.readers import CArchiveReader


BUILD = Path("D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/"
             "taraz-v1.0.6-aaas/build-7f17dbf72519")
EXPECTED_EXE = "301dfede5eeaa597f73c03b86d17fcee6f23083ac78e3945b161aef547937ede"
EXPECTED_SOURCE = "23bd9f26a7954220f0e3720483a355a9442f15a0505960968d5a5edd1bd09ff7"
EXPECTED_ZIP = "f6f1ca75bfcdbef0246ee54cf7028a143a4a63b6320bdb94be8c66aaeecb7db9"
MODULES = {
    "taraz_order_store": {"TarazOrderStore", "get", "command"},
    "taraz_aaas_agent": {"CompanyAgentMemory", "review_order_tools",
                          "interpret_natural_order_request", "command"},
    "taraz_madar_order_link": {"MadarOrderLinkStore", "read", "bind",
                               "reconcile_uncertain","mark_sync_transmitting"},
    "taraz_madar_order_sync": {"sync_order_to_madar",
                               "prepare_madar_order_state",
                               "read_madar_order_stage_progress"},
    "taraz_ecosystem_protocol": {"TrustedScope","validate_envelope"},
    "taraz_ecosystem_outbox": {"EcosystemOutbox","enqueue",
                               "reconcile_verified_receipt"},
    "taraz_repository_contracts": {"TarazOrderReadRepository","read_reference"},
    "taraz_ai_provider_status": {"provider_status"},
}
EXE_APIS = {
    "tarazOrderFinanceDraft", "tarazAgentOrderReview", "tarazAgentMemoryList",
    "tarazAgentMemoryCommand", "tarazAgentNaturalRequest",
    "tarazMadarOrderPreview", "tarazMadarOrderCommit",
    "tarazMadarOrderProgress", "tarazMadarOrderSyncHistory",
    "tarazMadarOrderRecover",
    "tarazEcosystemStatus", "tarazAiProviderStatus",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def code_names(code):
    names = {code.co_name}
    for part in code.co_consts:
        if isinstance(part, types.CodeType):
            names.update(code_names(part))
    return names


class FrozenAaasIndependentIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((BUILD / "build-report.json").read_text(encoding="utf-8"))
        cls.exe = BUILD / "binary" / "Taraz.exe"
        cls.archive = CArchiveReader(str(cls.exe))
        cls.pyz = cls.archive.open_embedded_archive("PYZ.pyz")

    def test_executable_zip_manifest_and_installed_pointer(self):
        report = self.report
        self.assertEqual(report["sourceFreezeSha256"], EXPECTED_SOURCE)
        self.assertEqual(report["sourceFilesCount"], 145)
        self.assertEqual(report["status"], "V106_AAAS_NON_QA_BUILT_NOT_INSTALLED")
        self.assertIs(report["installed"], False)
        self.assertIs(report["pointerChanged"], False)
        self.assertIs(report["realLedgerModified"], False)
        self.assertEqual(digest(self.exe.read_bytes()), EXPECTED_EXE)
        archive = BUILD / "Taraz-v1.0.6-AAAS-OFFLINE-UPDATE.zip"
        self.assertEqual(digest(archive.read_bytes()), EXPECTED_ZIP)
        manifest = BUILD / "offline-update" / "update-manifest.json"
        self.assertEqual(digest(manifest.read_bytes()), report["manifestSha256"])
        with zipfile.ZipFile(archive) as data:
            self.assertEqual(digest(data.read("Taraz.exe")), EXPECTED_EXE)
            self.assertIn("Activate-Taraz-V106.ps1", data.namelist())
            self.assertIn("Rollback-Taraz-V106.ps1", data.namelist())
        # Installed pointer is only read, never changed by this QA.
        appdata = os.environ.get("LOCALAPPDATA")
        if appdata:
            pointer = Path(appdata) / "Programs" / "Taraz" / "current-version.txt"
            self.assertTrue(pointer.is_file())
            self.assertEqual(pointer.read_text(encoding="utf-8-sig").strip(), "1.0.4")
            self.assertEqual(digest(pointer.read_bytes()),
                             report["baseline"]["pointerSha256"])

    def test_real_pyz_agent_and_madar_functions_not_just_build_report(self):
        for module, required in MODULES.items():
            with self.subTest(module=module):
                code = self.pyz.extract(module)
                self.assertIsInstance(code, types.CodeType)
                self.assertTrue(required <= code_names(code))
        import marshal
        embedded = self.archive.extract("taraz_desktop")
        self.assertIsInstance(embedded, bytes)
        actual = marshal.loads(embedded)
        self.assertIsInstance(actual, types.CodeType)
        self.assertTrue(EXE_APIS <= code_names(actual))

    def test_real_executable_embedded_ui_exact_byte_parity(self):
        collected = {name.replace("\\", "/"): name for name in self.archive.toc}
        expected = self.report["compiled"]["assetsSha256"]
        self.assertIn("accounting.html", expected)
        scripts = [name for name in expected if name.endswith(".js")]
        self.assertEqual(len(scripts), 1)
        for name, hash_value in expected.items():
            with self.subTest(name=name):
                self.assertIn("dist/" + name, collected)
                actual = self.archive.extract(collected["dist/" + name])
                self.assertIsInstance(actual, bytes)
                self.assertEqual(digest(actual), hash_value)
        script = self.archive.extract(collected["dist/" + scripts[0]])
        for marker in (b"tarazOrderFinanceDraft", b"tarazAgentMemoryCommand",
                       b"tarazAgentNaturalRequest", b"tarazMadarOrderProgress",
                       b"tarazMadarOrderPreview", b"tarazMadarOrderCommit"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)


if __name__ == "__main__":
    unittest.main()
