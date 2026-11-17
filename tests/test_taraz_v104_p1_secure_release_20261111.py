"""Deterministic fail-closed tests for the unexecuted v104 secure builder.

All synthetic writes happen under TemporaryDirectory. No installed Taraz
files, real source stages, frozen v103 output, or user profiles are modified.
Real compiled PE/PYZ and compiled Edge assertions are separate release gates.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import build_taraz_v104_p1_secure_release_20261111 as v104

BUILT_V104 = v104.OUTPUT / "build-6d851f756264"
PINNED_V104_EXE = "8e2a8026b48e278df95693d9349f5a566df9b75c12497882b3bebca96679adc6"
PINNED_V104_ZIP = "721bbf8d6fd461fb1317fb1394b26d0ad67237d4fbc8f3d9cbfc8442b5f79777"
PINNED_V104_MANIFEST = "116f325052c8db7b5386e0eae937d45db809760fbac42780d3e0d62657b32c75"
PINNED_V104_REPORT = "c2f3ed699c679098e158f8dff619fc440abaf180089ea30a4e5796139bb8027b"


def file(path: Path, value: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value.encode("utf-8") if isinstance(value, str) else value)
    return path


def json_file(path: Path, data: dict) -> Path:
    return file(path, json.dumps(data, sort_keys=True, ensure_ascii=True, indent=2) + "\n")


class SecureV104BuilderContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="taraz-v104-builder-unit-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_actual_source_stage_file_bytes_independently_match_fingerprint(self):
        actual = v104.source_preflight()
        self.assertEqual(actual["sourceSha256"], v104.STAGE_SHA)
        self.assertEqual(actual["sourceCount"], 131)
        self.assertEqual(set(actual["editedSourceFiles"]), v104.PATCHED)
        self.assertEqual(actual["status"], "V104_PATCHED_SOURCE_FROZEN_QA_PENDING_NO_EXE")
        self.assertFalse(actual["compiledExecutableExists"])

    def test_pinned_vite_stage_is_source_provenance_and_actual_assets(self):
        actual = v104.source_preflight()
        vite = v104.stage_vite_preflight(
            actual,
            vite_dir=v104.OUTPUT / "vite-qa-1ff6df468d81",
            expected_js_sha="b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453",
        )
        self.assertEqual(vite["jsSha256"],
                         "b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453")
        self.assertEqual(set(vite["ui"]), {"htmlRelativePath", "cssRelativePath", "jsRelativePath"})

    def test_unpinned_qa_never_enters_compiler_or_creates_build_folder(self):
        before = {item.name for item in v104.OUTPUT.iterdir()}
        with patch.object(v104.base, "run_command") as runner:
            with self.assertRaisesRegex(v104.BuildBlocked, "SHA-pinned.*QA"):
                v104.build(expected_sha=v104.STAGE_SHA, stage_qa=None, stage_qa_sha="",
                           edge_qa=None, edge_qa_sha="",
                           vite_dir=v104.OUTPUT / "vite-qa-1ff6df468d81",
                           vite_js_sha="b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453")
            runner.assert_not_called()
        after = {item.name for item in v104.OUTPUT.iterdir()}
        self.assertEqual(before, after)

    def test_mismatched_approved_source_sha_denied(self):
        with self.assertRaisesRegex(v104.BuildBlocked, "Prime-approved"):
            v104.approved_build_inputs(
                v104.STAGE, "0" * 64, self.root / "stage.json", "1" * 64,
                self.root / "edge.json", "1" * 64)

    def test_snapshot_relative_name_traversal_refused(self):
        for item in ("../foo", "src/../../foo", "/root", "C:/bad", "x\\bad", "a//b", "a:b"):
            with self.subTest(item=item), self.assertRaises(v104.BuildBlocked):
                v104._rel(item)

    def test_modified_manifest_digest_refused(self):
        original = v104._json(v104.STAGE / "patched-source-sha256.json")
        fake = dict(original)
        fake["src/personal_parsian_company.jsx"] = "0" * 64
        real_json = v104._json
        def replaced(path: Path, *args, **kwargs):
            if Path(path).name == "patched-source-sha256.json":
                return fake
            return real_json(path, *args, **kwargs)
        with patch.object(v104, "_json", side_effect=replaced):
            with self.assertRaisesRegex(v104.BuildBlocked, "fingerprint"):
                v104.source_preflight()

    def test_equal_wrong_package_names_are_not_accidentally_accepted(self):
        original = v104._json
        def fake(path: Path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if Path(path).name in ("package.json", "package-lock.json"):
                value["name"] = "not-taraz"
            return value
        with patch.object(v104, "_json", side_effect=fake):
            with self.assertRaisesRegex(v104.BuildBlocked, "package name"):
                v104.source_preflight()

    def test_independent_qa_evidence_requires_exact_pinned_sha(self):
        stage = v104.source_preflight()
        evidence = json_file(self.root / "qa.json", {
            "kind": "applied-source-stage", "status": "PASS",
            "sourceStage": stage["stage"], "sourceSha256": stage["sourceSha256"],
            "sourceCount": 131, "failures": 0, "checksPassed": 10,
        })
        digest = v104._sha(evidence)
        result = v104._approved_qa_report(evidence, digest, "applied-source-stage", stage)
        self.assertEqual(result["checksPassed"], 10)
        with self.assertRaisesRegex(v104.BuildBlocked, "SHA"):
            v104._approved_qa_report(evidence, "0" * 64, "applied-source-stage", stage)
        with self.assertRaisesRegex(v104.BuildBlocked, "PASS"):
            v104._approved_qa_report(evidence, digest, "staged-edge-redaction", stage)

    def test_qa_evidence_report_with_failure_never_approves_build(self):
        stage = v104.source_preflight()
        evidence = json_file(self.root / "failed.json", {
            "kind": "staged-edge-redaction", "status": "PASS",
            "sourceStage": stage["stage"], "sourceSha256": stage["sourceSha256"],
            "sourceCount": 131, "failures": 1, "checksPassed": 7,
        })
        with self.assertRaises(v104.BuildBlocked):
            v104._approved_qa_report(
                evidence, v104._sha(evidence), "staged-edge-redaction", stage)

    def fixture_snapshot(self, bad_name: bool = False) -> Path:
        snapshot = self.root / "source"
        snapshot.mkdir()
        json_file(snapshot / "package.json", {
            "name": "taraz-accounting" if not bad_name else "other-app", "version": "1.0.0"})
        json_file(snapshot / "package-lock.json", {
            "name": "taraz-accounting", "version": "1.0.0",
            "packages": {"": {"version": "1.0.0"}}})
        file(snapshot / "taraz_desktop.py", "from __future__ import annotations\n\ndef run(): return 2\n")
        return snapshot

    def test_detached_v104_version_staging_stamps_nonqa_only(self):
        snapshot = self.fixture_snapshot()
        result = v104.stage_version(snapshot)
        self.assertEqual(v104._json(snapshot / "package.json")["version"], "1.0.4")
        self.assertEqual(v104._json(snapshot / "package-lock.json")["version"], "1.0.4")
        self.assertEqual(v104._json(snapshot / "package-lock.json")["packages"][""]["version"], "1.0.4")
        self.assertIn('QA_ONLY = False', (snapshot / "taraz_release_version.py").read_text())
        self.assertIn('_taraz_app_version != "1.0.4"', (snapshot / "taraz_desktop.py").read_text())
        self.assertEqual(set(result), {"packageSha256", "lockSha256",
                                      "versionModuleSha256", "nativeEntrySha256"})

    def test_staging_wrong_package_identity_fails(self):
        snapshot = self.fixture_snapshot(bad_name=True)
        with self.assertRaisesRegex(v104.BuildBlocked, "package version"):
            v104.stage_version(snapshot)

    def test_staging_overwrite_existing_release_module_fails(self):
        snapshot = self.fixture_snapshot()
        file(snapshot / "taraz_release_version.py", "QA_ONLY=True")
        with self.assertRaisesRegex(v104.BuildBlocked, "Refuse overwrite"):
            v104.stage_version(snapshot)

    def test_pe_version_source_template_is_104_only(self):
        output = self.root / "pe-resource.txt"
        v104.pe_resource(output)
        value = output.read_text(encoding="utf-8")
        self.assertEqual(value.count("1,0,4,0"), 2)
        self.assertEqual(value.count("1.0.4.0"), 2)
        self.assertNotIn("1.0.2.0", value)

    def test_hardened_install_scripts_retarget_every_v103_path_and_hash(self):
        fresh = "1" * 64
        result = v104.secure_installation_scripts(fresh)
        self.assertEqual(set(result), {"Install-Taraz-V104.ps1", "Activate-Taraz-V104.ps1"})
        for name, script in result.items():
            with self.subTest(name=name):
                self.assertNotIn("1.0.3", script)
                self.assertNotIn("V103", script)
                self.assertNotIn(v104.V103_EXE_SHA, script)
                self.assertIn(fresh, script)
                self.assertIn(v104.BASE_SHA, script)
                self.assertIn("TarazV104SecureLinkInfo", script)
                self.assertIn("$parent=$item.Directory", script)
                self.assertIn("GetFileInformationByHandle", script)
                self.assertIn("sourceStageInventorySha256", script)
        self.assertIn("Run-Taraz-pre-1.0.4.cmd", result["Activate-Taraz-V104.ps1"])
        self.assertIn("[IO.File]::Replace($pending,$pointer,$oldPointer,$true)",
                      result["Activate-Taraz-V104.ps1"])

    def test_scripts_refuse_reused_v103_binary_sha(self):
        with self.assertRaisesRegex(v104.BuildBlocked, "new pinned"):
            v104.secure_installation_scripts(v104.V103_EXE_SHA)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"),
                         "Native Windows PowerShell 5.1 required")
    def test_v104_templates_parse_in_actual_ps51(self):
        scripts = v104.secure_installation_scripts("1" * 64)
        destinations = []
        for name, content in scripts.items():
            destinations.append(file(self.root / name, content))
        literals = ",".join("'" + str(path).replace("'", "''") + "'" for path in destinations)
        cmd = (
            "$ErrorActionPreference='Stop';foreach($f in @(" + literals +
            ")){ $tok=$null;$err=$null;"
            "$ast=[Management.Automation.Language.Parser]::ParseFile($f,[ref]$tok,[ref]$err);"
            "if(@($err).Count -gt 0){throw ($err|Out-String)} };"
            "Write-Output 'PS51_V104_PARSE_OK'")
        output = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        self.assertEqual(output.returncode, 0, output.stdout + output.stderr)
        self.assertIn("PS51_V104_PARSE_OK", output.stdout)

    def test_create_only_package_has_seven_new_members_without_old_rollback(self):
        run = self.root / "run"
        run.mkdir()
        (run / "source").mkdir()
        json_file(run / "source" / "package.json",
                  {"name": "taraz-accounting", "version": "1.0.4"})
        json_file(run / "source" / "package-lock.json",
                  {"name": "taraz-accounting", "version": "1.0.4",
                   "packages": {"": {"version": "1.0.4"}}})
        bin_file = file(run / "mock-Taraz.exe", b"MZ\x00TEST-BINARY-V104-NOT-A-REAL-EXE")
        source_proof = v104.source_preflight()
        fake_qa = {
            "stageQA": {"kind": "applied-source-stage", "reportSha256": "1" * 64},
            "stagedEdgeQA": {"kind": "staged-edge-redaction", "reportSha256": "2" * 64},
        }
        output = v104.package_secure_update(
            run, bin_file, source_proof["snapshot"],
            {"packageSha256": "a" * 64}, {"peVersion": "1.0.4.0", "pyzVersion": "1.0.4"},
            {"version": "1.0.2"}, source_proof, fake_qa,
            {"jsSha256": "b" * 64})
        self.assertEqual(output["exeSha256"], v104._sha(bin_file))
        archive = Path(output["zip"])
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(len(z.namelist()), 7)
            self.assertIn("Install-Taraz-V104.ps1", z.namelist())
            self.assertIn("Activate-Taraz-V104.ps1", z.namelist())
            self.assertNotIn("Rollback-Taraz-V103-To-V102.ps1", z.namelist())
        manifest = v104._json(Path(output["manifest"]))
        self.assertEqual(manifest["targetVersion"], "1.0.4")
        self.assertFalse(manifest["secureRepackage"]["productionApproved"])
        self.assertFalse(manifest["secureRepackage"]["rollbackIncluded"])
        self.assertEqual(manifest["secureRepackage"]["sourceStageInventorySha256"],
                         v104.STAGE_INVENTORY_FILE_SHA)


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"),
                     "Windows native PowerShell 5.1 is required")
class RealV104DisposablePowerShell(unittest.TestCase):
    """Test actual pinned v104 installer/activator on synthetic private roots.

    The real installed binary is READ ONLY; only disposable copies are
    executed through package PowerShell scripts. The EXE is never launched.
    """

    @classmethod
    def setUpClass(cls):
        cls.build = v104._regular(BUILT_V104, folder=True)
        cls.offline_source = v104._regular(cls.build / "offline-update", folder=True)
        cls.installed = v104._regular(
            Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz", folder=True)
        cls.old_bin = cls.installed / "versions" / "1.0.2" / "Taraz.exe"
        expected = {
            cls.build / "binary" / "Taraz.exe": PINNED_V104_EXE,
            cls.build / "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip": PINNED_V104_ZIP,
            cls.build / "offline-update" / "update-manifest.json": PINNED_V104_MANIFEST,
            cls.build / "build-report.json": PINNED_V104_REPORT,
            cls.old_bin: v104.BASE_SHA,
            v104.BACKUP / "snapshot-manifest.json": v104.BACKUP_MANIFEST_SHA,
            v104.BACKUP / "backup-acceptance-report.json": v104.BACKUP_REPORT_SHA,
        }
        for path, digest in expected.items():
            if v104._sha(path, cap=v104.MAX_EXE_BYTES) != digest:
                raise AssertionError("Pinned installed/backup/build evidence changed: " + str(path))
        if (cls.installed / "current-version.txt").read_text(encoding="utf-8").strip() != "1.0.2":
            raise AssertionError("Real installed version pointer is not v1.0.2; fail closed")
        if (cls.installed / "versions" / "1.0.4").exists():
            raise AssertionError("Production v104 already exists; cannot test as uninstalled")
        version = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "$PSVersionTable.PSVersion.ToString()"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        if version.returncode != 0 or not version.stdout.strip().startswith("5.1."):
            raise AssertionError("Requires native PowerShell 5.1")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            prefix="qa-v104-native-", dir=self.build)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.offline = self.root / "offline"
        shutil.copytree(self.offline_source, self.offline)
        self.local = self.root / "local"
        self.roaming = self.root / "roaming"
        self.roaming.mkdir()
        self.product = self.local / "Programs" / "Taraz"
        self.safe_product = self.product
        old_dir = self.product / "versions" / "1.0.2"
        old_dir.mkdir(parents=True)
        shutil.copyfile(self.old_bin, old_dir / "Taraz.exe")
        shutil.copyfile(self.installed / "Run-Taraz.cmd", self.product / "Run-Taraz.cmd")
        (self.product / "current-version.txt").write_bytes(b"1.0.2\r\n")
        self.pointer_sha = v104._sha(self.product / "current-version.txt")
        self.launcher_sha = v104._sha(self.product / "Run-Taraz.cmd")
        self.ledger = self.roaming / "Taraz" / "synthetic-finance-canary.txt"
        self.ledger.parent.mkdir()
        self.ledger.write_bytes(b"SYNTHETIC_CANARY_NOT_USER_FINANCE")
        self.ledger_sha = v104._sha(self.ledger)

    def tearDown(self):
        self.assertEqual(v104._sha(self.safe_product / "versions" / "1.0.2" / "Taraz.exe"),
                         v104.BASE_SHA)
        self.assertEqual(v104._sha(self.safe_product / "Run-Taraz.cmd"), self.launcher_sha)
        self.assertEqual(v104._sha(self.ledger), self.ledger_sha)

    def invoke(self, name: str, *args: str, backup: Path = v104.BACKUP):
        env = dict(os.environ)
        env["LOCALAPPDATA"] = str(self.local)
        env["APPDATA"] = str(self.roaming)
        env["USERPROFILE"] = str(self.root)
        env["TEMP"] = str(self.root / "temp")
        env["TMP"] = env["TEMP"]
        (self.root / "temp").mkdir(exist_ok=True)
        return subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(self.offline / name),
             *args, "-BackupRoot", str(backup),
             "-BackupManifestSha256", v104.BACKUP_MANIFEST_SHA,
             "-BackupReportSha256", v104.BACKUP_REPORT_SHA],
            cwd=str(self.root), env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120)

    def succeeded(self, result, marker):
        self.assertEqual(result.returncode, 0, result.stdout[-500:] + result.stderr[-750:])
        self.assertIn(marker, result.stdout)

    def fails_closed(self, result, keyword: str, *, after_install: bool = False):
        self.assertNotEqual(result.returncode, 0,
                            "Unsafe script returned success: " + result.stdout)
        self.assertIn(keyword.casefold(), (result.stdout + result.stderr).casefold())
        self.assertEqual((self.product / "current-version.txt").read_text(
            encoding="utf-8").strip(), "1.0.2")
        if not after_install:
            self.assertFalse((self.product / "versions" / "1.0.4").exists())
        self.assertFalse((self.product / "current-version-pre-1.0.4.txt").exists())

    def installed_v104_in_private_root(self):
        self.succeeded(self.invoke("Install-Taraz-V104.ps1", "-Apply"),
                       "INSTALLED_SIDE_BY_SIDE_1.0.4_POINTER_REMAINS_1.0.2")
        self.assertEqual(v104._sha(self.product / "versions" / "1.0.4" / "Taraz.exe",
                                   cap=v104.MAX_EXE_BYTES), PINNED_V104_EXE)

    def test_actual_ps51_dryrun_install_activate_and_pointer_launcher_backups(self):
        self.succeeded(self.invoke("Install-Taraz-V104.ps1"),
                       "READY_FOR_CREATE_ONLY_1.0.4_INSTALL")
        self.assertFalse((self.product / "versions" / "1.0.4").exists())
        self.installed_v104_in_private_root()
        self.assertEqual(v104._sha(self.product / "current-version.txt"), self.pointer_sha)
        self.succeeded(self.invoke("Activate-Taraz-V104.ps1"),
                       "READY_TO_ACTIVATE_1.0.4_OLD_VERSION_RETAINED")
        self.assertFalse((self.product / "current-version-pre-1.0.4.txt").exists())
        self.succeeded(self.invoke("Activate-Taraz-V104.ps1", "-Apply"),
                       "ACTIVATED_1.0.4_VERSION_1.0.2_RETAINED")
        self.assertEqual((self.product / "current-version.txt").read_text().strip(), "1.0.4")
        self.assertEqual((self.product / "current-version-pre-1.0.4.txt").read_text().strip(), "1.0.2")
        self.assertEqual(v104._sha(self.product / "Run-Taraz-pre-1.0.4.cmd"), self.launcher_sha)
        self.assertEqual(v104._sha(self.product / "Run-Taraz.cmd"), self.launcher_sha)
        again = self.invoke("Activate-Taraz-V104.ps1", "-Apply")
        self.assertNotEqual(again.returncode, 0, "Repeated activation must fail")
        self.assertEqual((self.product / "current-version.txt").read_text().strip(), "1.0.4")

    def test_actual_ps51_rejects_hardlinked_v102_exe(self):
        old = self.product / "versions" / "1.0.2" / "Taraz.exe"
        try:
            os.link(old, self.root / "extra-old-Taraz.exe")
        except OSError as exc:
            self.skipTest("NTFS hardlink unavailable: " + str(exc))
        self.fails_closed(self.invoke("Install-Taraz-V104.ps1", "-Apply"), "Hardlinked")

    def test_actual_ps51_rejects_hardlinked_installed_pointer(self):
        try:
            os.link(self.product / "current-version.txt", self.root / "extra-pointer.txt")
        except OSError as exc:
            self.skipTest("NTFS hardlink unavailable: " + str(exc))
        self.fails_closed(self.invoke("Install-Taraz-V104.ps1", "-Apply"), "Hardlinked")

    def test_actual_ps51_rejects_hardlinked_new_exe_during_activation(self):
        self.installed_v104_in_private_root()
        new = self.product / "versions" / "1.0.4" / "Taraz.exe"
        try:
            os.link(new, self.root / "extra-v104-Taraz.exe")
        except OSError as exc:
            self.skipTest("NTFS hardlink unavailable: " + str(exc))
        self.fails_closed(self.invoke("Activate-Taraz-V104.ps1", "-Apply"),
                          "Hardlinked", after_install=True)

    def test_actual_ps51_rejects_nested_junction_in_install_path(self):
        path = self.local / "Programs"
        real = self.local / "physical-Programs"
        path.rename(real)
        self.safe_product = real / "Taraz"
        link = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(path), str(real)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=12)
        if link.returncode:
            self.skipTest("Private NTFS junction creation unavailable")
        self.fails_closed(self.invoke("Install-Taraz-V104.ps1", "-Apply"), "junction")

    def test_actual_ps51_rejects_nested_junction_in_new_exe_path(self):
        self.installed_v104_in_private_root()
        versions = self.product / "versions"
        path = versions / "1.0.4"
        real = versions / "physical-1.0.4"
        path.rename(real)
        link = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(path), str(real)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=12)
        if link.returncode:
            self.skipTest("Private NTFS junction creation unavailable")
        self.fails_closed(self.invoke("Activate-Taraz-V104.ps1", "-Apply"),
                          "junction", after_install=True)

    def test_actual_ps51_refuses_invalid_backup_before_creating_new_version(self):
        self.fails_closed(
            self.invoke("Install-Taraz-V104.ps1", "-Apply", backup=self.root / "missing-backup"),
            "missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
