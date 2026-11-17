"""V1.0.3 release builder and fully disposable PowerShell upgrade contract tests.

Tests never execute a real Taraz binary, read finance data, or change the
installed Taraz version pointer. The live installation is never a test target.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import types
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import build_taraz_v103_p1_release_20261111 as candidate


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReleaseSourceTests(unittest.TestCase):
    def test_version_staging_uses_103_consistently(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "package.json").write_text(json.dumps({"name": "taraz-accounting", "version": "1.0.0"}))
            (folder / "package-lock.json").write_text(json.dumps({
                "name": "taraz-accounting", "version": "1.0.0",
                "packages": {"": {"version": "1.0.0"}}}))
            (folder / "taraz_desktop.py").write_text("from __future__ import annotations\nclass Taraz: pass\n")
            hashes = candidate.stage_version(folder)
            p = json.loads((folder / "package.json").read_text())
            l = json.loads((folder / "package-lock.json").read_text())
            self.assertEqual([p["version"], l["version"], l["packages"][""]["version"]],
                             [candidate.VERSION] * 3)
            source = (folder / "taraz_release_version.py").read_text()
            self.assertIn('APP_VERSION = "1.0.3"', source)
            self.assertIn("QA_ONLY = False", source)
            self.assertIn('if _taraz_app_version != "1.0.3":',
                          (folder / "taraz_desktop.py").read_text())
            self.assertEqual(len(hashes), 4)

    def test_rejects_unknown_source_package_version(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "package.json").write_text(json.dumps({"name": "taraz-accounting", "version": "1.0.2"}))
            (folder / "package-lock.json").write_text(json.dumps({
                "name": "taraz-accounting", "version": "1.0.0",
                "packages": {"": {"version": "1.0.0"}}}))
            (folder / "taraz_desktop.py").write_text("from __future__ import annotations\n")
            with self.assertRaisesRegex(candidate.BuildBlocked, "package/lock"):
                candidate.stage_version(folder)

    def test_pe_resource_has_only_103_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pe.txt"
            candidate.pe_resource(path)
            value = path.read_text()
            self.assertEqual(value.count("1,0,3,0"), 2)
            self.assertEqual(value.count("1.0.3.0"), 2)
            self.assertNotIn("1.0.2.0", value)
            self.assertNotIn("1.0.1.0", value)

    def test_invalid_or_unapproved_fingerprint_fails_without_output(self):
        before = set(candidate.OUTPUT.iterdir()) if candidate.OUTPUT.exists() else set()
        with self.assertRaisesRegex(candidate.BuildBlocked, "approved lowercase"):
            candidate.build("")
        with self.assertRaisesRegex(candidate.BuildBlocked, "approved lowercase"):
            candidate.build("A" * 64)
        after = set(candidate.OUTPUT.iterdir()) if candidate.OUTPUT.exists() else set()
        self.assertEqual(before, after)

    def test_both_scripts_require_fresh_102_witness_and_create_only_copy(self):
        baseline = candidate.BASE_SHA256
        payload = "e" * 64
        install, activate = candidate.installation_scripts(payload)
        for text in (install, activate):
            self.assertIn(baseline, text)
            self.assertIn(payload, text)
            self.assertIn("CheckBackup $BackupRoot $BackupManifestSha256 $BackupReportSha256", text)
            self.assertIn("'1.0.2'", text)
            self.assertIn("versions\\1.0.3", text)
            self.assertIn("$Apply", text)
            self.assertNotIn("__BASE_SHA__", text)
            self.assertNotIn("__NEW_EXE_SHA__", text)
        self.assertIn("[IO.FileMode]::CreateNew", install)
        self.assertIn("if(Test-Path -LiteralPath $destination){Deny", install)
        self.assertNotIn("[IO.File]::Replace", install)
        self.assertIn("[IO.File]::Replace($temp,$pointer,$oldPointer,$true)", activate)
        self.assertIn("if(Test-Path -LiteralPath $oldPointer){Deny", activate)


@unittest.skipUnless(os.environ.get("TARAZ_V103_BUILD_REPORT"),
                     "Set TARAZ_V103_BUILD_REPORT to inspect a real completed build")
class FrozenCandidateTests(unittest.TestCase):
    def test_packed_candidate_source_bindings_and_complete_zip(self):
        """Read the actual PE/PYZ/archive bytes without running executable code."""
        from PyInstaller.archive.readers import CArchiveReader
        from scripts.qa_mtr_taraz_build_20261110 import _code_strings

        report_file = Path(os.environ["TARAZ_V103_BUILD_REPORT"])
        report = json.loads(report_file.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "PRODUCTION_V103_P1_CANDIDATE_BUILT_NOT_INSTALLED")
        self.assertEqual(report["sourceFreezeSha256"], candidate.fingerprint())
        self.assertEqual(report["sourceFileCount"], 131)
        self.assertFalse(report["installed"])
        self.assertFalse(report["pointerChanged"])
        folder = report_file.parent / "offline-update"
        manifest_file = folder / "update-manifest.json"
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(sha(manifest_file.read_bytes()), report["manifestSha256"])
        self.assertEqual(manifest["targetVersion"], "1.0.3")
        self.assertEqual(manifest["peVersion"], "1.0.3.0")
        self.assertEqual(manifest["pyzVersion"], "1.0.3")
        self.assertEqual(manifest["sourceSnapshotSha256"], report["sourceFreezeSha256"])
        self.assertTrue(manifest["freshIndependentBackupRequired"])
        self.assertFalse(manifest["freshIndependentBackupVerified"])
        self.assertFalse(manifest["installed"])
        executable = folder / "Taraz.exe"
        self.assertEqual(sha(executable.read_bytes()), report["exeSha256"])
        self.assertEqual(executable.stat().st_size, manifest["exeBytes"])
        self.assertEqual(candidate.pe_version(executable), "1.0.3.0")
        zip_path = Path(report["zip"])
        self.assertEqual(sha(zip_path.read_bytes()), report["zipSha256"])
        with zipfile.ZipFile(zip_path) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()), {p.name for p in folder.iterdir()})
            for file in folder.iterdir():
                self.assertEqual(sha(archive.read(file.name)), sha(file.read_bytes()), file.name)
        native_archive = CArchiveReader(str(executable))
        pyz = native_archive.open_embedded_archive("PYZ.pyz")
        integration = pyz.extract("taraz_integration")
        self.assertIsInstance(integration, types.CodeType)
        self.assertIn("pendingTruncated", _code_strings(integration))
        self.assertIn("recoveryTruncated", _code_strings(integration))
        ui_names = [name for name in native_archive.toc
                    if name.replace("\\", "/").startswith("dist/assets/")
                    and name.endswith(".js")]
        self.assertGreater(len(ui_names), 0)
        js = b" ".join(native_archive.extract(name) for name in ui_names)
        for token in (b"pendingTruncated", b"recoveryTruncated",
                      b"invoiceDesign", b"taraz-context-help-trigger"):
            self.assertIn(token, js)


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Needs Windows PowerShell 5.1")
class DisposablePowerShellUpgradeTests(unittest.TestCase):
    """Uses short synthetic bytes and temporary LOCALAPPDATA only."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.local = self.root / "sandbox-localappdata"
        self.install_root = self.local / "Programs" / "Taraz"
        old = self.install_root / "versions" / "1.0.2"
        old.mkdir(parents=True)
        self.old_bytes = b"FAKE-TARAZ-BASELINE-1.0.2-TEST-ONLY"
        (old / "Taraz.exe").write_bytes(self.old_bytes)
        (self.install_root / "current-version.txt").write_text("1.0.2\r\n", encoding="utf-8")
        (self.install_root / "Run-Taraz.cmd").write_text(
            "@echo off\n\"%~dp0versions\\%TARAZ_VERSION%\\Taraz.exe\"\n", encoding="utf-8")
        self.package = self.root / "candidate"
        self.package.mkdir()
        self.new_bytes = b"FAKE-TARAZ-PAYLOAD-1.0.3-TEST-ONLY"
        (self.package / "Taraz.exe").write_bytes(self.new_bytes)
        (self.package / "update-manifest.json").write_text(json.dumps({
            "targetVersion": "1.0.3", "installedBaselineVersion": "1.0.2",
            "qaOnly": False, "productionCandidate": True,
            "exeSha256": sha(self.new_bytes)}), encoding="utf-8")

        # The backup is synthetic and not a statement about real-accounting safety.
        self.backup = self.root / "synthetic-cold-backup"
        file = self.backup / "files" / "roaming" / "fixture.db"
        file.parent.mkdir(parents=True)
        file.write_bytes(b"synthetic fixture only")
        manifest = {"schemaVersion": 1, "verifiedNoOverwrite": True,
                    "allFilesIncluded": True, "fileCount": 1,
                    "totalBytes": file.stat().st_size,
                    "files": {"roaming/fixture.db": {"bytes": file.stat().st_size,
                                                     "sha256": sha(file.read_bytes())}},
                    "sqliteChecks": {"fixture": {"ok": True}}}
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        (self.backup / "snapshot-manifest.json").write_bytes(manifest_bytes)
        self.manifest_sha = sha(manifest_bytes)
        report = {"status": "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING",
                  "installedBefore": "1.0.2", "installedAfter": "1.0.2",
                  "backup": {"backupRoot": str(self.backup), "independentReadback": True,
                             "manifestSha256": self.manifest_sha, "fileCount": 1,
                             "totalBytes": file.stat().st_size, "sqliteValidatedCount": 1}}
        report_bytes = json.dumps(report).encode("utf-8")
        (self.backup / "backup-acceptance-report.json").write_bytes(report_bytes)
        self.report_sha = sha(report_bytes)
        install, activate = candidate.installation_scripts(sha(self.new_bytes))
        # Only the test copies substitute the installed EXE SHA and process
        # checker; release scripts preserve both the pinned SHA and real gate.
        self.scripts = []
        for name, text in (("Install-Taraz-V103.ps1", install), ("Activate-Taraz-V103.ps1", activate)):
            text = text.replace(candidate.BASE_SHA256, sha(self.old_bytes))
            start = text.index("function CheckNoTaraz {")
            end = text.index("function CheckBackup([string]", start)
            text = text[:start] + "function CheckNoTaraz {}\n" + text[end:]
            path = self.package / name
            path.write_text(text, encoding="utf-8")
            self.scripts.append(path)

    def run_script(self, script: Path, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(self.local)
        env["APPDATA"] = str(self.root / "sandbox-roaming")
        return subprocess.run([shutil.which("powershell.exe"), "-NoProfile", "-NonInteractive",
                               "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=25, check=False)

    def backup_args(self) -> tuple[str, ...]:
        return ("-BackupRoot", str(self.backup),
                "-BackupManifestSha256", self.manifest_sha,
                "-BackupReportSha256", self.report_sha)

    def test_fail_closed_without_independent_backup_attestation(self):
        for script in self.scripts:
            result = self.run_script(script)
            self.assertNotEqual(result.returncode, 0, (script.name, result.stdout, result.stderr))
            self.assertIn("cold-backup", result.stderr.lower())
        self.assertEqual((self.install_root / "current-version.txt").read_text().strip(), "1.0.2")
        self.assertFalse((self.install_root / "versions" / "1.0.3").exists())

    def test_dryrun_install_verify_activate_then_create_only(self):
        install, activate = self.scripts
        r = self.run_script(install, *self.backup_args())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("READY_FOR_CREATE_ONLY_1.0.3_INSTALL", r.stdout)
        self.assertFalse((self.install_root / "versions" / "1.0.3").exists())
        r = self.run_script(install, "-Apply", *self.backup_args())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.install_root / "versions" / "1.0.3" / "Taraz.exe").read_bytes(),
                         self.new_bytes)
        self.assertEqual((self.install_root / "current-version.txt").read_text().strip(), "1.0.2")
        r = self.run_script(install, "-Apply", *self.backup_args())
        self.assertNotEqual(r.returncode, 0, "Second install must refuse overwrite")
        r = self.run_script(install, "-VerifyExisting", *self.backup_args())
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_script(activate, *self.backup_args())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("READY_TO_ACTIVATE_1.0.3", r.stdout)
        self.assertEqual((self.install_root / "current-version.txt").read_text().strip(), "1.0.2")
        r = self.run_script(activate, "-Apply", *self.backup_args())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.install_root / "current-version.txt").read_text().strip(), "1.0.3")
        self.assertEqual((self.install_root / "current-version-pre-1.0.3.txt").read_text().strip(),
                         "1.0.2")
        self.assertEqual((self.install_root / "versions" / "1.0.2" / "Taraz.exe").read_bytes(),
                         self.old_bytes)
        r = self.run_script(activate, "-Apply", *self.backup_args())
        self.assertNotEqual(r.returncode, 0, "Second activation must refuse overwrite")


if __name__ == "__main__":
    unittest.main()
