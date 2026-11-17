"""RC2/RC3 fail-closed builder verification; only disposable fixture writes.

RC2's analytics-host-key disclosure was independently reproduced. Never
build the old RC2 source. This suite accepts the follow-on RC3 repaired stage
only after worker29's new exact 131-file freeze and independent worker27 Edge
proof of all 10 initial masking tests plus the three residual scenarios.
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

from scripts import build_taraz_v104_p1_secure_rc2_20261111 as rc


def write(path: Path, contents: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents.encode("utf-8") if isinstance(contents, str) else contents)
    return path


def write_json(path: Path, obj: dict) -> Path:
    return write(path, json.dumps(obj, ensure_ascii=True, sort_keys=True, indent=2) + "\n")


class SecureRC2GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="taraz-v104-rc3-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_rc1_immutable_reference_exact(self):
        ref = rc.fixed_rc1_preflight()
        self.assertEqual(ref["exeSha256"], rc.RC1_EXE_SHA)
        self.assertEqual(ref["sourceSha256"], rc.BASE_SHA)
        self.assertEqual(len(ref["inventory"]), 131)

    def test_failed_rc2_baseline_actually_proven(self):
        self.assertEqual(
            rc._sha(rc.FAILED_RC2_STAGE / "patched-source-sha256.json"),
            rc.FAILED_RC2_MANIFEST_SHA)
        self.assertEqual(
            rc._sha(rc.FAILED_RC2_STAGE / "stage-report.json"), rc.FAILED_RC2_REPORT_SHA)
        original = rc._json(rc.FAILED_RC2_STAGE / "patched-source-sha256.json")
        self.assertEqual(rc.rc1.inventory_sha(original), rc.FAILED_RC2_SHA)

    def test_failed_rc2_stage_is_not_build_eligible(self):
        with self.assertRaisesRegex(rc.BuildBlocked, "Only SHA-pinned RC3"):
            rc.source_preflight(
                rc.FAILED_RC2_STAGE, source_sha=rc.FAILED_RC2_SHA,
                inventory_sha=rc.FAILED_RC2_MANIFEST_SHA,
                stage_report_sha=rc.FAILED_RC2_REPORT_SHA,
                inventory_name="patched-source-sha256.json")

    def test_actual_rc3_source_all_131_sha_and_only_one_incremental_patch(self):
        proof = rc.source_preflight(
            rc.RC3_STAGE, source_sha=rc.RC3_SOURCE_SHA,
            inventory_sha=rc.RC3_MANIFEST_SHA,
            stage_report_sha=rc.RC3_STAGE_REPORT_SHA,
            inventory_name="patched-source-sha256.json",
        )
        self.assertEqual(proof["sourceCount"], 131)
        self.assertEqual(proof["sourceSha256"], rc.RC3_SOURCE_SHA)
        self.assertEqual(set(proof["additionalFiles"]), rc.EXTRA_PATHS)
        self.assertEqual(proof["incrementalFiles"],
                         ["src/accounting_management_dashboard.jsx"])

    def test_actual_rc3_vite_html_css_js_are_new_and_pinned(self):
        proof = rc.source_preflight(
            rc.RC3_STAGE, source_sha=rc.RC3_SOURCE_SHA,
            inventory_sha=rc.RC3_MANIFEST_SHA,
            stage_report_sha=rc.RC3_STAGE_REPORT_SHA,
            inventory_name="patched-source-sha256.json",
        )
        evidence = rc.vite_preflight(
            proof, vite_dir=rc.RC3_VITE,
            vite_js_sha=rc.RC3_VITE_JS_SHA,
            vite_report_sha=rc.RC3_VITE_REPORT_SHA)
        self.assertEqual(evidence["jsSha256"], rc.RC3_VITE_JS_SHA)
        self.assertNotEqual(evidence["jsSha256"], rc.RC1_JS_SHA)
        self.assertNotEqual(evidence["jsSha256"], rc.FAILED_RC2_JS_SHA)
        self.assertEqual(set(evidence["ui"]), {
            "htmlRelativePath", "cssRelativePath", "jsRelativePath"})

    def test_rc3_wrong_source_pin_refused_even_if_past_stage_exists(self):
        with self.assertRaisesRegex(rc.BuildBlocked, "Exact independently observed"):
            rc.source_preflight(
                rc.RC3_STAGE, source_sha=rc.FAILED_RC2_SHA,
                inventory_sha=rc.RC3_MANIFEST_SHA,
                stage_report_sha=rc.RC3_STAGE_REPORT_SHA,
                inventory_name="patched-source-sha256.json")

    def test_rc1_stage_is_not_build_eligible(self):
        with self.assertRaisesRegex(rc.BuildBlocked, "Only SHA-pinned RC3"):
            rc.source_preflight(
                rc.BASE_STAGE, source_sha=rc.BASE_SHA,
                inventory_sha=rc.BASE_MANIFEST_SHA,
                stage_report_sha="0" * 64,
                inventory_name="patched-source-sha256.json")

    def test_wrong_or_missing_explicit_sha_rejected(self):
        for candidate in ("", "fake", "A" * 64, "g" * 64):
            with self.subTest(candidate=candidate), self.assertRaises(rc.BuildBlocked):
                rc._pin(candidate, "RC3 source")

    def test_missing_qa_groups_failclosed(self):
        fake_proof = {"sourceSha256": "a" * 64, "stage": str(self.root)}
        fake_vite = {"root": str(self.root / "vite"), "jsSha256": "b" * 64}
        with self.assertRaisesRegex(rc.BuildBlocked, "Three separate"):
            rc.qa_preflight(fake_proof, fake_vite, witnesses={})

    def test_source_qa_witness_checksum_and_fail_cases(self):
        proof = {"sourceSha256": "a" * 64, "stage": str(self.root / "source"),
                 "sourceCount": 131}
        vite = {"root": str(self.root / "vite"), "jsSha256": "b" * 64}
        paths = {}
        for kind, minimum in rc.EXPECTED_QA.items():
            data = {
                "kind": kind, "status": "PASS",
                "sourceStage": proof["stage"], "sourceSha256": proof["sourceSha256"],
                "sourceCount": 131, "failures": 0, "skipped": 0, "exitCode": 0,
                "checksPassed": minimum, "command": "native independently executed command",
                "verifiedMode": "STAGE_UI_ONLY", "viteQaRoot": vite["root"],
                "viteJsSha256": vite["jsSha256"], "financialCommands": 0,
                "compiledNativeExeTested": False,
            }
            name = kind + ".json"
            file = write_json(self.root / name, data)
            paths[kind] = (file, rc._sha(file))
        accepted = rc.qa_preflight(proof, vite, witnesses=paths)
        self.assertEqual(set(accepted), set(rc.EXPECTED_QA))
        wrong = dict(paths)
        wrong["rc2-residual-three-edge"] = (
            wrong["rc2-residual-three-edge"][0], "0" * 64)
        with self.assertRaisesRegex(rc.BuildBlocked, "SHA|bytes"):
            rc.qa_preflight(proof, vite, witnesses=wrong)
        bad = rc._json(paths["rc2-residual-three-edge"][0])
        bad["failures"] = 1
        file = write_json(paths["rc2-residual-three-edge"][0], bad)
        wrong["rc2-residual-three-edge"] = (file, rc._sha(file))
        with self.assertRaisesRegex(rc.BuildBlocked, "PASS"):
            rc.qa_preflight(proof, vite, witnesses=wrong)

    def test_hardened_scripts_use_new_source_and_binary_sha(self):
        exe_sha, src_sha, inv_sha = ("2" * 64, "3" * 64, "4" * 64)
        values = rc.secure_scripts(exe_sha, src_sha, inv_sha)
        self.assertEqual(set(values), {"Install-Taraz-V104.ps1", "Activate-Taraz-V104.ps1"})
        for name, value in values.items():
            with self.subTest(script=name):
                self.assertEqual(value.count(exe_sha), 4)
                self.assertIn(src_sha, value)
                self.assertIn(inv_sha, value)
                self.assertIn(rc.rc1.BASE_SHA, value)
                self.assertNotIn(rc.BASE_SHA, value)
                self.assertNotIn(rc.BASE_MANIFEST_SHA, value)
                self.assertNotIn(rc.RC1_EXE_SHA, value)
                self.assertNotIn("1.0.3", value)
                self.assertIn("TarazV104SecureLinkInfo", value)
                self.assertIn("$parent=$item.Directory", value)
                self.assertIn("GetFileInformationByHandle", value)
                self.assertNotIn("$item=$item.Parent", value)
        self.assertIn("Run-Taraz-pre-1.0.4.cmd", values["Activate-Taraz-V104.ps1"])
        self.assertIn("[IO.File]::Replace($pending,$pointer,$oldPointer,$true)",
                      values["Activate-Taraz-V104.ps1"])

    def test_refuses_reused_rc1_exe_and_source(self):
        with self.assertRaisesRegex(rc.BuildBlocked, "recycled"):
            rc.secure_scripts(rc.RC1_EXE_SHA, "3" * 64, "4" * 64)
        with self.assertRaisesRegex(rc.BuildBlocked, "recycled"):
            rc.secure_scripts("2" * 64, rc.BASE_SHA, "4" * 64)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"),
                         "Native Windows PowerShell required")
    def test_both_retargeted_ps51_templates_parse(self):
        scripts = rc.secure_scripts("2" * 64, "3" * 64, "4" * 64)
        paths = [write(self.root / name, text) for name, text in scripts.items()]
        safe_paths = ",".join("'" + str(p).replace("'", "''") + "'" for p in paths)
        script = (
            "$ErrorActionPreference='Stop';foreach($f in @(" + safe_paths +
            ")){$tok=$null;$errors=$null;"
            "$a=[Management.Automation.Language.Parser]::ParseFile($f,[ref]$tok,[ref]$errors);"
            "if(@($errors).Count -ne 0){throw ($errors|Out-String)}};"
            "Write-Output 'RC3_PS51_PARSE_OK'"
        )
        output = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=18)
        self.assertEqual(output.returncode, 0, output.stdout + output.stderr)
        self.assertIn("RC3_PS51_PARSE_OK", output.stdout)

    def test_synthetic_seven_member_packaging_does_not_reuse_rollback(self):
        root = self.root / "output"
        root.mkdir()
        (root / "source").mkdir()
        write_json(root / "source" / "package.json",
                   {"name": "taraz-accounting", "version": "1.0.4"})
        write_json(root / "source" / "package-lock.json",
                   {"name": "taraz-accounting", "version": "1.0.4",
                    "packages": {"": {"version": "1.0.4"}}})
        fake_exe = write(root / "dummy-Taraz.exe", b"MZ\0RC3-SYNTHETIC-ONLY")
        source_sha = "3" * 64
        proof = {"sourceSha256": source_sha, "inventorySha256": "4" * 64,
                 "stageReportSha256": "5" * 64, "stage": str(self.root / "stage")}
        report = rc.package(
            root, fake_exe, {"accounting.html": "6" * 64},
            {"sourceMarker": "7" * 64}, {"peVersion": "1.0.4.0",
                                       "pyzVersion": "1.0.4"},
            {"version": "1.0.2"}, proof, {"jsSha256": "8" * 64},
            {"rc2-source-stage": {"sha256": "9" * 64}})
        self.assertEqual(report["exeSha256"], rc._sha(fake_exe))
        with zipfile.ZipFile(report["zip"]) as archive:
            self.assertEqual(len(archive.infolist()), 7)
            self.assertIn("Install-Taraz-V104.ps1", archive.namelist())
            self.assertNotIn("Rollback-Taraz-V103-To-V102.ps1", archive.namelist())
        manifest = rc._json(Path(report["manifest"]))
        self.assertEqual(manifest["targetVersion"], "1.0.4")
        self.assertFalse(manifest["secureRepackage"]["productionApproved"])
        self.assertFalse(manifest["secureRepackage"]["rollbackIncluded"])
        self.assertEqual(manifest["sourceSnapshotSha256"], source_sha)

    def test_real_build_not_started_without_complete_evidence(self):
        current = set(x.name for x in rc.OUTPUT.iterdir())
        with patch.object(rc.rc1.base, "run_command") as runner:
            with self.assertRaises((rc.BuildBlocked, TypeError)):
                rc.build(
                    stage=rc.FAILED_RC2_STAGE, source_sha=rc.FAILED_RC2_SHA,
                    inventory_sha=rc.FAILED_RC2_MANIFEST_SHA,
                    stage_report_sha=rc.FAILED_RC2_REPORT_SHA,
                    inventory_name="patched-source-sha256.json",
                    vite_dir=rc.OUTPUT / "vite-qa-899a40d30820",
                    vite_js_sha="39295ea85bf2d6ee9fd94fce862c2bc505d4ac6ce01153fbc7ef9d8eea0b5b79",
                    vite_report_sha="0" * 64, witnesses={},
                )
            runner.assert_not_called()
        self.assertEqual(current, set(x.name for x in rc.OUTPUT.iterdir()))


@unittest.skipUnless(
    os.name == "nt" and bool(os.environ.get("TARAZ_V104_RC3_BUILD_DIR")),
    "Explicitly pinned genuine RC3 build required for disposable PS5.1 acceptance")
class NativeRealRC3Disposable(unittest.TestCase):
    """Only enabled with actual post-build immutable RC3 hash pins from owner."""

    @classmethod
    def setUpClass(cls):
        cls.build = Path(os.environ["TARAZ_V104_RC3_BUILD_DIR"]).absolute()
        if (cls.build.parent != rc.OUTPUT or
                cls.build == rc.RC1_RUN or
                not cls.build.name.startswith("build-")):
            raise AssertionError("RC3 must be a distinct direct create-only build-* child")
        cls.exe = cls.build / "binary" / "Taraz.exe"
        cls.zip = cls.build / "Taraz-v1.0.4-P1-RC3-SECURE-OFFLINE-UPDATE.zip"
        cls.manifest = cls.build / "offline-update" / "update-manifest.json"
        cls.report = cls.build / "build-report.json"
        for path, env in [
            (cls.exe, "TARAZ_V104_RC3_EXE_SHA"),
            (cls.zip, "TARAZ_V104_RC3_ZIP_SHA"),
            (cls.manifest, "TARAZ_V104_RC3_MANIFEST_SHA"),
            (cls.report, "TARAZ_V104_RC3_REPORT_SHA"),
        ]:
            pin = rc._pin(os.environ.get(env, ""), env)
            if rc._sha(path, cap=rc.rc1.MAX_EXE_BYTES) != pin:
                raise AssertionError("Genuine RC3 build bytes changed: " + str(path))
        meta = rc._json(cls.manifest)
        if (meta.get("sourceSnapshotSha256") != rc.RC3_SOURCE_SHA
                or meta.get("releaseCandidateRevision") != "RC3"
                or meta.get("exeSha256") != os.environ["TARAZ_V104_RC3_EXE_SHA"]):
            raise AssertionError("RC3 source/exe/version provenance invalid")
        cls.installed = rc.rc1.installed_preflight()
        cls.old = Path(cls.installed["root"]) / "versions" / "1.0.2" / "Taraz.exe"
        cls.launcher = Path(cls.installed["root"]) / "Run-Taraz.cmd"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="taraz-rc3-ps51-", dir=self.build)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.offline = self.root / "offline"
        shutil.copytree(self.build / "offline-update", self.offline)
        self.local = self.root / "local"
        self.roaming = self.root / "roaming"
        self.roaming.mkdir()
        self.product = self.local / "Programs" / "Taraz"
        self.safe_root = self.product
        old_dir = self.product / "versions" / "1.0.2"
        old_dir.mkdir(parents=True)
        shutil.copyfile(self.old, old_dir / "Taraz.exe")
        shutil.copyfile(self.launcher, self.product / "Run-Taraz.cmd")
        write(self.product / "current-version.txt", b"1.0.2\r\n")
        self.launcher_sha = rc._sha(self.product / "Run-Taraz.cmd")
        self.finance = write(self.roaming / "Taraz" / "synthetic-canary.txt",
                             "FAKE-FINANCE-NEVER-REAL-DATA")
        self.finance_sha = rc._sha(self.finance)

    def tearDown(self):
        self.assertEqual(rc._sha(self.safe_root / "versions" / "1.0.2" / "Taraz.exe",
                                 cap=rc.rc1.MAX_EXE_BYTES), rc.rc1.BASE_SHA)
        self.assertEqual(rc._sha(self.safe_root / "Run-Taraz.cmd"), self.launcher_sha)
        self.assertEqual(rc._sha(self.finance), self.finance_sha)

    def ps(self, name: str, *opts: str):
        env = dict(os.environ)
        env.update({
            "LOCALAPPDATA": str(self.local), "APPDATA": str(self.roaming),
            "USERPROFILE": str(self.root),
            "TMP": str(self.root), "TEMP": str(self.root),
        })
        return subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(self.offline / name),
             *opts, "-BackupRoot", str(rc.rc1.BACKUP),
             "-BackupManifestSha256", rc.rc1.BACKUP_MANIFEST_SHA,
             "-BackupReportSha256", rc.rc1.BACKUP_REPORT_SHA],
            cwd=str(self.root), env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=170)

    def test_real_ps51_install_then_activate_with_backups(self):
        install = self.ps("Install-Taraz-V104.ps1", "-Apply")
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        self.assertIn("INSTALLED_SIDE_BY_SIDE_1.0.4", install.stdout)
        self.assertEqual(
            rc._sha(self.product / "versions" / "1.0.4" / "Taraz.exe",
                    cap=rc.rc1.MAX_EXE_BYTES),
            os.environ["TARAZ_V104_RC3_EXE_SHA"])
        activate = self.ps("Activate-Taraz-V104.ps1", "-Apply")
        self.assertEqual(activate.returncode, 0, activate.stdout + activate.stderr)
        self.assertEqual((self.product / "current-version.txt").read_text().strip(), "1.0.4")
        self.assertEqual((self.product / "current-version-pre-1.0.4.txt").read_text().strip(),
                         "1.0.2")
        self.assertEqual(rc._sha(self.product / "Run-Taraz-pre-1.0.4.cmd"),
                         self.launcher_sha)
        self.assertNotEqual(self.ps("Activate-Taraz-V104.ps1", "-Apply").returncode, 0)

    def test_hardlinked_pointer_rejected_before_install(self):
        try:
            os.link(self.product / "current-version.txt", self.root / "extra-pointer.txt")
        except OSError as exc:
            self.skipTest("NTFS hardlink unavailable: " + str(exc))
        result = self.ps("Install-Taraz-V104.ps1", "-Apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hardlinked", (result.stderr + result.stdout).lower())
        self.assertFalse((self.product / "versions" / "1.0.4").exists())

    def test_hardlinked_new_exe_rejected_during_activation(self):
        installed = self.ps("Install-Taraz-V104.ps1", "-Apply")
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        exe = self.product / "versions" / "1.0.4" / "Taraz.exe"
        self.assertEqual(rc._sha(exe, cap=rc.rc1.MAX_EXE_BYTES),
                         os.environ["TARAZ_V104_RC3_EXE_SHA"])
        try:
            os.link(exe, self.root / "extra-new-exe-hardlink.exe")
        except OSError as exc:
            self.skipTest("NTFS hardlink unavailable: " + str(exc))
        refusal = self.ps("Activate-Taraz-V104.ps1", "-Apply")
        self.assertNotEqual(refusal.returncode, 0)
        self.assertIn("hardlinked", (refusal.stdout + refusal.stderr).lower())
        self.assertEqual((self.product / "current-version.txt").read_text().strip(), "1.0.2")
        self.assertFalse((self.product / "current-version-pre-1.0.4.txt").exists())

    def test_hardlinked_packed_exe_rejected_before_install(self):
        try:
            os.link(self.offline / "Taraz.exe", self.root / "extra-payload-exe.exe")
        except OSError as exc:
            self.skipTest("NTFS hardlink unavailable: " + str(exc))
        refusal = self.ps("Install-Taraz-V104.ps1", "-Apply")
        self.assertNotEqual(refusal.returncode, 0)
        self.assertIn("hardlinked", (refusal.stdout + refusal.stderr).lower())
        self.assertFalse((self.product / "versions" / "1.0.4").exists())

    def test_nested_install_junction_rejected(self):
        existing = self.local / "Programs"
        real = self.local / "Programs-physical"
        existing.rename(real)
        self.safe_root = real / "Taraz"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(existing), str(real)],
                                capture_output=True, text=True, timeout=12)
        if result.returncode:
            self.skipTest("Private junction unavailable")
        refusal = self.ps("Install-Taraz-V104.ps1", "-Apply")
        self.assertNotEqual(refusal.returncode, 0)
        self.assertIn("junction", (refusal.stderr + refusal.stdout).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
