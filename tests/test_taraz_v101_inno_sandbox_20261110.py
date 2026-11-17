"""Negative safety checks and artifact readback for compile-only Taraz QA Inno."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import qa_taraz_v101_inno_sandbox_20261110 as qa


class TarazInnoSandboxTests(unittest.TestCase):
    def test_baseline_is_attested_with_unchanged_version(self):
        evidence = qa.baseline_report()
        self.assertEqual(evidence["report"]["status"], "QA_BUNDLE_VERIFIED")
        self.assertEqual(evidence["fingerprint"], evidence["report"]["sourceSnapshotSha256"])

    def test_versioning_modifies_only_synthetic_snapshot_and_inserts_fail_closed_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp)
            (stage / "package.json").write_text('{"version":"1.0.0","dependencies":{"sileo":"0.1.6"}}', encoding="utf-8")
            (stage / "package-lock.json").write_text('{"version":"1.0.0","packages":{"":{"version":"1.0.0"}}}', encoding="utf-8")
            (stage / "taraz_desktop.py").write_text('"""synthetic"""\nfrom __future__ import annotations\nprint("dummy")\n', encoding="utf-8")
            exe = stage / "disposable" / "Taraz-v1.0.1-SANDBOX-QA.exe"
            result = qa.stage_real_version(stage, exe)
            self.assertEqual([result[x] for x in ("packageVersion", "lockVersion", "lockRootVersion")],
                             ["1.0.1", "1.0.1", "1.0.1"])
            compiled = compile((stage / "taraz_desktop.py").read_text(encoding="utf-8"), "synthetic", "exec")
            self.assertIsNotNone(compiled)
            script = (stage / "taraz_desktop.py").read_text(encoding="utf-8")
            self.assertIn("_taraz_qa_launch_gate()", script)
            self.assertIn('"TARAZ_QA_RUN_ROOT"', script)
            self.assertIn('"TARAZ_QA_DATA_DIR"', script)
            env = os.environ.copy()
            env.pop("TARAZ_QA_MODE", None)
            rejected = subprocess.run([sys.executable, "-B", str(stage / "taraz_desktop.py")],
                                      cwd=str(stage), env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=10)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("requires explicit QA mode", rejected.stderr)
            env["TARAZ_QA_MODE"] = "1"
            env["TARAZ_QA_RUN_ROOT"] = str(stage / "qa-runtime")
            rejected = subprocess.run([sys.executable, "-B", str(stage / "taraz_desktop.py")],
                                      cwd=str(stage), env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=10)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("outside the disposable install path", rejected.stderr)
            with self.assertRaises(qa.SandboxBuildBlocked):
                qa.stage_real_version(stage, exe)

    def test_inno_script_guards_disposable_dir_and_has_no_system_hooks(self):
        dest = qa.OUTPUT / "unit-test" / "disposable-side-by-side-install"
        script = qa.inno_script(qa.OUTPUT / "unit-test" / "binary.exe",
                                qa.OUTPUT / "unit-test" / "qa-manifest.json", dest,
                                qa.OUTPUT / "unit-test" / "inno")
        self.assertIn("AppVersion=1.0.1", script)
        self.assertIn("PrivilegesRequired=lowest", script)
        self.assertIn("Uninstallable=no", script)
        self.assertIn("DisableDirPage=yes", script)
        self.assertIn("function PrepareToInstall", script)
        self.assertIn("CompareText(Requested", script)
        for forbidden in ("[Run]", "[Registry]", "[Icons]", "[Tasks]", "[UninstallRun]", "PrivilegesRequired=admin"):
            self.assertNotIn(forbidden, script)

    def test_inno_rejects_destination_outside_owned_output(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(qa.SandboxBuildBlocked):
                qa.inno_script(qa.OUTPUT / "binary.exe", qa.OUTPUT / "qa.json",
                               Path(temp) / "outside", qa.OUTPUT / "inno")

    def test_compiled_artifact_if_present_is_versioned_and_hash_pinned(self):
        if not qa.OUTPUT.is_dir():
            self.skipTest("QA compile not yet run")
        completed = []
        for run_dir in qa.OUTPUT.glob("compile-*"):
            report = run_dir / "compile-report.json"
            if report.is_file():
                verdict = json.loads(report.read_text(encoding="utf-8"))
                if verdict.get("status") == "COMPILED_QA_SETUP_NOT_EXECUTED":
                    completed.append((run_dir, verdict))
        if not completed:
            self.skipTest("QA compile has no completed success artifact")
        run_dir, verdict = sorted(completed, key=lambda pair: pair[0].name)[-1]
        setup = Path(verdict["setupExe"])
        binary = Path(verdict["tarazExe"])
        manifest = json.loads((run_dir / "sandbox-qa-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(qa.sha(setup), verdict["setupSha256"])
        self.assertEqual(qa.sha(binary), verdict["tarazExeSha256"])
        self.assertEqual(manifest["compiledExeSha256"], verdict["tarazExeSha256"])
        self.assertEqual(qa.pe_product_version(binary), "1.0.1.0")
        self.assertEqual(manifest["stagedPackageVersion"], "1.0.1")
        self.assertEqual(manifest["stagedLockVersion"], "1.0.1")
        self.assertEqual(manifest["stagedLockRootVersion"], "1.0.1")
        self.assertTrue(manifest["installerNotExecuted"])
        self.assertFalse(manifest["releaseApproved"])


if __name__ == "__main__":
    unittest.main()
