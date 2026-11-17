"""Secure Taraz v103 offline ZIP: immutable byte pins + native PS5.1 acceptance.

Only a newly created disposable localappdata and a COPY of the secure
offline package are changed. The installed baseline EXE and cold backup are
read without changes. No actual user installed folder or ledger is opened
for mutation. All PowerShell test invocations use Windows PowerShell 5.1.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import taraz_v103_secure_repackage_20261111 as secure

BACKUP = secure.PARENT / "MTR-REAL-UPGRADE-BACKUPS-20261110" / "taraz-v103-cold-20261111"
BACKUP_MANIFEST_SHA = "8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d"
BACKUP_REPORT_SHA = "68bb6e26b9a9a10818e6752a7cc1475a3861c5f380f2021eb5c112a74cd7d2c9"
INSTALLED_V102 = Path(os.environ.get("LOCALAPPDATA", "C:/unknown")) / "Programs" / "Taraz"
DEFAULT_SECURE = secure.OUTPUT_PARENT / "secure-repackage-be460926d766"


def chosen() -> Path:
    return Path(os.environ.get("TARAZ_V103_SECURE_REPACKAGE", str(DEFAULT_SECURE)))


def shas(folder: Path) -> dict[str, str]:
    return {item.relative_to(folder).as_posix(): secure.sha(item)
            for item in folder.rglob("*") if item.is_file()}


class StaticRepackageContracts(unittest.TestCase):
    def test_exact_original_source_pins(self):
        attested = secure.frozen_preflight()
        self.assertEqual(attested["buildReportSha256"], secure.FROZEN_REPORT_SHA)
        self.assertEqual(attested["manifest"]["exeSha256"], secure.FROZEN_EXE_SHA)

    def test_new_manifest_and_seven_zip_members(self):
        result = secure.verify_secure_output(chosen())
        self.assertEqual(result["status"], "SECURE_REPACKAGE_BYTE_PINS_VERIFIED")
        self.assertEqual(result["exeSha256"], secure.FROZEN_EXE_SHA)
        self.assertEqual(result["zipEntriesVerified"], 7)

    def test_secure_script_contains_complete_ancestor_and_hardlink_guards(self):
        values = secure.secure_ps_scripts()
        for name, script in values.items():
            with self.subTest(name=name):
                self.assertIn("$parent=$item.Directory", script)
                self.assertIn("$parent=$item.Parent", script)
                self.assertIn("GetFileInformationByHandle", script)
                self.assertIn("HardlinkCount", script)
                self.assertIn("if($links -ne 1)", script)
                self.assertIn("CheckNoTaraz", script)
                self.assertIn("SafePath $PSCommandPath", script)
                self.assertIn("RequireAbsent", script)
                self.assertNotIn("$item=$item.Parent", script)
        self.assertIn("[IO.File]::Replace($pending,$pointer,$oldPointer,$true)",
                      values["Activate-Taraz-V103.ps1"])
        self.assertIn("$launcherBackup", values["Activate-Taraz-V103.ps1"])
        self.assertIn("[IO.FileMode]::CreateNew", values["Install-Taraz-V103.ps1"])

    def test_changed_payload_detected_on_disposable_copy(self):
        with tempfile.TemporaryDirectory(prefix="taraz-secure-tamper-",
                                         dir=secure.OUTPUT_PARENT) as tmp:
            dest = Path(tmp)
            copy = dest / "secure-repackage-unit"
            shutil.copytree(chosen(), copy)
            (copy / "offline-update" / "package.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(secure.SecurePackageBlocked, "SHA mismatch"):
                secure.same_sha(copy / "offline-update" / "package.json",
                                secure.ORIGINAL_HASHES["package.json"], "tampered staged package")

    def test_release_files_are_distinct_and_original_manifest_unchanged(self):
        secure_manifest = secure.load_json(chosen() / "offline-update" / "update-manifest.json")
        original = secure.load_json(secure.FROZEN_OFFLINE / "update-manifest.json")
        self.assertNotEqual(secure_manifest["installScriptSha256"], original["installScriptSha256"])
        self.assertNotEqual(secure_manifest["activationScriptSha256"], original["activationScriptSha256"])
        self.assertEqual(secure.sha(secure.FROZEN_OFFLINE / "update-manifest.json"),
                         secure.FROZEN_MANIFEST_SHA)
        self.assertFalse(secure_manifest["secureRepackage"]["productionApproved"])


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"),
                     "Windows PowerShell 5.1 is required")
class NativeDisposableSecurePS51(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        info = secure.verify_secure_output(chosen())
        cls.secure = Path(info["folder"])
        cls.source_package = cls.secure / "offline-update"
        cls.v102 = secure.regular(INSTALLED_V102 / "versions" / "1.0.2" / "Taraz.exe")
        if secure.sha(cls.v102) != secure.V102_EXE_SHA:
            raise AssertionError("installed v102 baseline SHA differs")
        for path, expected in ((BACKUP / "snapshot-manifest.json", BACKUP_MANIFEST_SHA),
                               (BACKUP / "backup-acceptance-report.json", BACKUP_REPORT_SHA)):
            if secure.sha(path) != expected:
                raise AssertionError("fresh cold backup witness has changed")
        # Pin exact PS5.1 engine, not PowerShell 7's different interpretation.
        outcome = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "$PSVersionTable.PSVersion.ToString()"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12)
        if outcome.returncode or not outcome.stdout.strip().startswith("5.1."):
            raise AssertionError("Native Windows PowerShell 5.1 unavailable")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="taraz-secure-ps51-",
                                                dir=self.secure)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.offline = self.root / "offline"
        shutil.copytree(self.source_package, self.offline)
        self.local = self.root / "localappdata"
        self.app = self.root / "roaming"
        self.app.mkdir()
        self.product = self.local / "Programs" / "Taraz"
        self.safe_product = self.product
        old = self.product / "versions" / "1.0.2"
        old.mkdir(parents=True)
        shutil.copyfile(self.v102, old / "Taraz.exe")
        launcher = INSTALLED_V102 / "Run-Taraz.cmd"
        shutil.copyfile(launcher, self.product / "Run-Taraz.cmd")
        (self.product / "current-version.txt").write_bytes(b"1.0.2\r\n")
        self.finance = self.app / "Taraz" / "synthetic-finance-canary.bin"
        self.finance.parent.mkdir()
        self.finance.write_bytes(b"FAKE-SYNTHETIC-CANARY-NOT-REAL-FINANCE")
        self.original_finance_sha = secure.sha(self.finance)
        self.before = {
            "v102": secure.sha(old / "Taraz.exe"),
            "pointer": secure.sha(self.product / "current-version.txt"),
            "launcher": secure.sha(self.product / "Run-Taraz.cmd"),
        }

    def tearDown(self):
        self.assertEqual(secure.sha(self.finance), self.original_finance_sha)
        self.assertEqual(secure.sha(self.safe_product / "versions" / "1.0.2" / "Taraz.exe"),
                         self.before["v102"])
        self.assertEqual(secure.sha(self.safe_product / "Run-Taraz.cmd"), self.before["launcher"])

    def env(self):
        values = dict(os.environ)
        values["LOCALAPPDATA"] = str(self.local)
        values["APPDATA"] = str(self.app)
        values["USERPROFILE"] = str(self.root)
        values["TEMP"] = str(self.root / "temp")
        values["TMP"] = values["TEMP"]
        (self.root / "temp").mkdir(exist_ok=True)
        return values

    def invoke(self, name: str, *options: str, backup_root: Path = BACKUP):
        return subprocess.run([
            "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(self.offline / name), *options,
            "-BackupRoot", str(backup_root), "-BackupManifestSha256", BACKUP_MANIFEST_SHA,
            "-BackupReportSha256", BACKUP_REPORT_SHA,
        ], cwd=str(self.root), env=self.env(), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=180)

    def assert_pass(self, result, marker):
        self.assertEqual(result.returncode, 0, result.stdout[-750:] + "\n" + result.stderr[-1500:])
        self.assertIn(marker, result.stdout)

    def assert_refusal(self, result, token):
        self.assertNotEqual(result.returncode, 0,
                            "Unsafe command unexpectedly accepted: " + result.stdout)
        self.assertIn(token.lower(), (result.stdout + result.stderr).lower())
        self.assertEqual((self.product / "current-version.txt").read_text(encoding="utf-8").strip(),
                         "1.0.2")
        self.assertFalse((self.product / "versions" / "1.0.3").exists())

    def test_00_ps51_parse_both_scripts_with_zero_ast_errors(self):
        paths = [self.offline / "Install-Taraz-V103.ps1", self.offline / "Activate-Taraz-V103.ps1"]
        literals = ",".join("'" + str(path).replace("'", "''") + "'" for path in paths)
        code = r'''$ErrorActionPreference='Stop'
$errors=$null
foreach($path in @(''' + literals + r''')) {
  $tokens=$null; $errors=$null
  $ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
  if($null -eq $ast -or @($errors).Count -gt 0) { throw ($errors | Out-String) }
}
Write-Output 'PS51_AST_PARSE_OK'
'''
        command = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                   "-Command", code]
        outcome = subprocess.run(command, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=25)
        self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
        self.assertIn("PS51_AST_PARSE_OK", outcome.stdout)

    def test_10_install_dryrun_apply_activate_and_backup(self):
        dry = self.invoke("Install-Taraz-V103.ps1")
        self.assert_pass(dry, "READY_FOR_CREATE_ONLY_1.0.3_INSTALL")
        self.assertEqual(secure.sha(self.product / "current-version.txt"), self.before["pointer"])
        self.assertFalse((self.product / "versions" / "1.0.3").exists())
        applied = self.invoke("Install-Taraz-V103.ps1", "-Apply")
        self.assert_pass(applied, "INSTALLED_SIDE_BY_SIDE_1.0.3_POINTER_REMAINS_1.0.2")
        new = self.product / "versions" / "1.0.3" / "Taraz.exe"
        self.assertEqual(secure.sha(new), secure.FROZEN_EXE_SHA)
        self.assertEqual(secure.sha(self.product / "current-version.txt"), self.before["pointer"])
        active_dry = self.invoke("Activate-Taraz-V103.ps1")
        self.assert_pass(active_dry, "READY_TO_ACTIVATE_1.0.3_OLD_VERSION_RETAINED")
        self.assertFalse((self.product / "current-version-pre-1.0.3.txt").exists())
        active = self.invoke("Activate-Taraz-V103.ps1", "-Apply")
        self.assert_pass(active, "ACTIVATED_1.0.3_VERSION_1.0.2_RETAINED")
        self.assertEqual((self.product / "current-version.txt").read_text(encoding="utf-8").strip(), "1.0.3")
        self.assertEqual((self.product / "current-version-pre-1.0.3.txt").read_text(encoding="utf-8").strip(), "1.0.2")
        backup = self.product / "Run-Taraz-pre-1.0.3.cmd"
        self.assertEqual(secure.sha(backup), self.before["launcher"])
        self.assertEqual(secure.sha(new), secure.FROZEN_EXE_SHA)

    def test_20_nested_junction_in_install_root_rejected_before_write(self):
        # Rename our own disposable Programs directory, then point to it
        # through an NTFS junction. Never create a junction in production.
        programs = self.local / "Programs"
        real = self.local / "ordinary-programs-real"
        programs.rename(real)
        self.safe_product = real / "Taraz"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(programs), str(real)],
                                capture_output=True, text=True, errors="replace", timeout=12)
        if result.returncode:
            self.skipTest("junction creation unavailable in this Windows environment")
        self.assert_refusal(self.invoke("Install-Taraz-V103.ps1", "-Apply"), "junction")

    def test_21_hardlinked_pointer_rejected_before_write(self):
        pointer = self.product / "current-version.txt"
        alias = self.product / "linked-pointer-copy.txt"
        try:
            os.link(pointer, alias)
        except OSError as exc:
            self.skipTest("hardlinks unavailable: " + str(exc))
        self.assert_refusal(self.invoke("Install-Taraz-V103.ps1", "-Apply"), "hardlinked")

    def test_22_hardlinked_old_exe_rejected_before_write(self):
        old = self.product / "versions" / "1.0.2" / "Taraz.exe"
        alias = self.root / "hardlinked-old-Taraz.exe"
        try:
            os.link(old, alias)
        except OSError as exc:
            self.skipTest("hardlinks unavailable: " + str(exc))
        self.assert_refusal(self.invoke("Install-Taraz-V103.ps1", "-Apply"), "hardlinked")

    def test_23_hardlinked_payload_rejected_before_write(self):
        payload = self.offline / "Taraz.exe"
        alias = self.root / "hardlinked-payload.exe"
        try:
            os.link(payload, alias)
        except OSError as exc:
            self.skipTest("hardlinks unavailable: " + str(exc))
        self.assert_refusal(self.invoke("Install-Taraz-V103.ps1", "-Apply"), "hardlinked")

    def test_24_nested_junction_under_offline_package_rejected(self):
        original = self.root / "physical-offline"
        self.offline.rename(original)
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(self.offline), str(original)],
                                capture_output=True, text=True, errors="replace", timeout=12)
        if result.returncode:
            self.skipTest("junction creation unavailable")
        self.assert_refusal(self.invoke("Install-Taraz-V103.ps1", "-Apply"), "junction")

    def test_25_hardlinked_launcher_rejected(self):
        launcher = self.product / "Run-Taraz.cmd"
        alias = self.root / "shared-launcher.cmd"
        try:
            os.link(launcher, alias)
        except OSError as exc:
            self.skipTest("hardlinks unavailable: " + str(exc))
        self.assert_refusal(self.invoke("Install-Taraz-V103.ps1", "-Apply"), "hardlinked")

    def test_26_bogus_backup_path_rejected(self):
        result = self.invoke("Install-Taraz-V103.ps1", "-Apply",
                             backup_root=self.root / "missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.product / "versions" / "1.0.3").exists())

    def safe_install_before_negative_activation(self):
        installed = self.invoke("Install-Taraz-V103.ps1", "-Apply")
        self.assert_pass(installed, "INSTALLED_SIDE_BY_SIDE_1.0.3_POINTER_REMAINS_1.0.2")
        self.assertEqual(secure.sha(self.product / "versions" / "1.0.3" / "Taraz.exe"),
                         secure.FROZEN_EXE_SHA)

    def assert_activation_blocked(self, expected: str):
        output = self.invoke("Activate-Taraz-V103.ps1", "-Apply")
        self.assertNotEqual(output.returncode, 0, output.stdout)
        self.assertIn(expected.lower(), (output.stdout + output.stderr).lower())
        self.assertEqual((self.product / "current-version.txt").read_text(encoding="utf-8").strip(), "1.0.2")
        self.assertFalse((self.product / "current-version-pre-1.0.3.txt").exists())
        self.assertFalse((self.product / "Run-Taraz-pre-1.0.3.cmd").exists())

    def test_30_activation_rejects_hardlinked_pointer(self):
        self.safe_install_before_negative_activation()
        pointer = self.product / "current-version.txt"
        try:
            os.link(pointer, self.root / "activation-pointer-hardlink.txt")
        except OSError as exc:
            self.skipTest("hardlink not supported: " + str(exc))
        self.assert_activation_blocked("hardlinked")

    def test_31_activation_rejects_hardlinked_candidate_exe(self):
        self.safe_install_before_negative_activation()
        new = self.product / "versions" / "1.0.3" / "Taraz.exe"
        try:
            os.link(new, self.root / "activation-exe-hardlink.exe")
        except OSError as exc:
            self.skipTest("hardlink not supported: " + str(exc))
        self.assert_activation_blocked("hardlinked")

    def test_32_activation_rejects_nested_junction_to_new_exe(self):
        self.safe_install_before_negative_activation()
        versions = self.product / "versions"
        child = versions / "1.0.3"
        real = versions / "1.0.3-physical"
        child.rename(real)
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(child), str(real)],
                                capture_output=True, text=True, errors="replace", timeout=12)
        if result.returncode:
            self.skipTest("junction not supported")
        self.assert_activation_blocked("junction")


if __name__ == "__main__":
    unittest.main(verbosity=2)
