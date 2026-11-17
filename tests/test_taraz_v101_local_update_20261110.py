"""Safety regressions for create-only non-QA Taraz 1.0.1 offline package."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import build_taraz_v101_local_update_20261110 as build


def fixture(path: Path, *, native: str = 'from __future__ import annotations\nVALUE = 1\n') -> None:
    (path / "package.json").write_text(
        json.dumps({"name": "taraz-accounting", "version": "1.0.0"}), encoding="utf-8")
    (path / "package-lock.json").write_text(json.dumps({
        "name": "taraz-accounting", "version": "1.0.0", "packages": {"": {
            "version": "1.0.0"}}}), encoding="utf-8")
    (path / "taraz_desktop.py").write_text(native, encoding="utf-8")


class TarazV101LocalUpdateTests(unittest.TestCase):
    def test_stage_creates_real_nonqa_version_without_changing_input_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            output = build.stage_version(root)
            self.assertEqual(json.loads((root / "package.json").read_text())["version"], "1.0.1")
            self.assertEqual(json.loads((root / "package-lock.json").read_text())["version"], "1.0.1")
            self.assertEqual(json.loads((root / "package-lock.json").read_text())["packages"][""]["version"], "1.0.1")
            entry = (root / "taraz_desktop.py").read_text()
            self.assertIn("from taraz_release_version import APP_VERSION", entry)
            self.assertNotIn("_taraz_qa_launch_gate", entry)
            self.assertIn("QA_ONLY = False", (root / "taraz_release_version.py").read_text())
            self.assertEqual(output["nativeEntry"], build.sha(root / "taraz_desktop.py"))

    def test_version_mismatch_and_qa_entry_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            data = json.loads((root / "package-lock.json").read_text())
            data["version"] = "0.9.9"
            (root / "package-lock.json").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(build.BuildBlocked):
                build.stage_version(root)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root, native="from __future__ import annotations\n_taraz_qa_launch_gate()\n")
            with self.assertRaises(build.BuildBlocked):
                build.stage_version(root)

    def test_invalid_backup_digest_is_rejected_before_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "backup-acceptance-report.json").write_text("{}", encoding="utf-8")
            (root / "snapshot-manifest.json").write_text("{}", encoding="utf-8")
            with patch.object(build, "BACKUP", root):
                with self.assertRaisesRegex(build.BuildBlocked, "attestation changed"):
                    build.require_backup()

    def test_uses_distinct_install_and_activation_gates(self):
        install, activate = build.staged_scripts("a" * 64)
        self.assertIn("CheckBackup $BackupRoot", install)
        self.assertIn("CheckNoTaraz", install)
        self.assertIn("[IO.FileMode]::CreateNew", install)
        self.assertIn("Version 1.0.1 already exists; never overwrite", install)
        self.assertIn("READY_FOR_CREATE_ONLY_SIDE_BY_SIDE_INSTALL", install)
        self.assertIn("INSTALLED_SIDE_BY_SIDE_1.0.1_POINTER_STILL_1.0.0", install)
        self.assertIn("EXISTING_SIDE_BY_SIDE_1.0.1_VERIFIED", install)
        self.assertIn("Get-CimInstance Win32_Process", install)
        self.assertIn("[IO.File]::Replace", activate)
        self.assertIn("-VerifyExisting", activate)
        self.assertIn("READY_TO_ACTIVATE_1.0.1_OLD_VERSION_PRESERVED", activate)
        self.assertNotIn("Remove-Item", install + activate)
        self.assertNotIn("Move-Item -Force", install + activate)
        self.assertNotIn("TARAZ_QA_MODE", install + activate)
        self.assertNotIn("__NEW_EXE_SHA__", install + activate)

    def test_existing_build_artifact_if_present_has_reproducible_pins(self):
        if not build.OUTPUT.is_dir():
            self.skipTest("No production candidate build output yet")
        found = []
        for root in build.OUTPUT.glob("build-*"):
            report_file = root / "build-report.json"
            if report_file.is_file():
                doc = json.loads(report_file.read_text(encoding="utf-8"))
                if doc.get("status") == "PRODUCTION_CANDIDATE_BUILT_NOT_INSTALLED":
                    found.append((root, doc))
        if not found:
            self.skipTest("No successfully compiled production EXE yet")
        root, doc = found[-1]
        exe = root / "binary" / "Taraz.exe"
        self.assertEqual(build.sha(exe), doc["exeSha256"])
        self.assertEqual(build.pe_version(exe), "1.0.1.0")
        archive_path = Path(doc["zip"])
        self.assertEqual(build.sha(archive_path), doc["zipSha256"])
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("Taraz.exe", archive.namelist())
            self.assertIn("Install-Taraz-V101.ps1", archive.namelist())
            self.assertIn("Activate-Taraz-V101.ps1", archive.namelist())
            manifest = json.loads(archive.read("update-manifest.json"))
        self.assertFalse(manifest["qaOnly"])
        self.assertTrue(manifest["invoiceDesignerCompiled"])
        self.assertEqual(manifest["targetVersion"], "1.0.1")
        self.assertEqual(manifest["exeSha256"], doc["exeSha256"])
        self.assertEqual(manifest["defaultDataRoot"], r"%APPDATA%\Taraz")
        self.assertFalse(manifest["installerExecuted"])
        self.assertFalse(manifest["pointerActivated"])


if __name__ == "__main__":
    unittest.main()
