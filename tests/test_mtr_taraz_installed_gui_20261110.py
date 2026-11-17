"""No installed process, real profile, real network or financial mutations."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "qa_mtr_taraz_installed_gui_20261110.py"
SPEC = importlib.util.spec_from_file_location("mtr_taraz_installed_gui_qa", SCRIPT)
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)
TOOLCHAIN = os.environ.get("MTR_TARAZ_UI_NODE_MODULES")


class TarazInstalledGuiSafetyTests(unittest.TestCase):
    def test_installed_launch_mode_refuses_before_accessing_any_data(self):
        # There is no EXE read/hash/launch or installed-profile inspection.
        done = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--mode", "installed"],
            capture_output=True, text=True, check=False, timeout=15,
        )
        self.assertEqual(done.returncode, 2)
        data = json.loads(done.stdout)
        self.assertEqual(data["decision"], "BLOCKED")
        self.assertIn("revision >=608", data["reason"])
        self.assertIn("Forging historical events", data["reason"])

    def test_direct_installed_refusal_cannot_fall_through_to_run(self):
        with self.assertRaisesRegex(qa.QABlocked, "Installed Taraz.exe not launched"):
            qa.refuse_installed_launch()

    def test_real_unpacked_host_uses_disposable_official_store_only(self):
        report = qa.run_qa()
        self.assertEqual(report["decision"], "INSTALLED_GUI_BLOCKED_UNPACKED_QA_ONLY")
        host = report["syntheticHost"]
        self.assertTrue(host["guardDeniedPersonalHistory"])
        self.assertEqual(host["syntheticLedgerRevision"], 0)
        self.assertEqual(host["inboxPendingBeforeReview"], 1)
        self.assertEqual(host["invalidInboxItemsNotDisplayed"], 1)
        self.assertTrue(host["ledgerSha256Unchanged"])
        self.assertTrue(host["reviewedAsMetadataOnly"])
        self.assertIs(host["financialEventCreated"], False)
        self.assertIs(host["realProfileAccessed"], False)
        self.assertIs(host["installedExeLaunched"], False)
        self.assertEqual(report["compiledUnpackedUI"]["status"],
                         "NOT_RUN_NO_TOOLCHAIN")

    def test_ambient_profile_paths_are_not_used_or_modified(self):
        with tempfile.TemporaryDirectory(dir=qa.SCRATCH_PARENT,
                                         prefix="qa-taraz-sentinel-") as temporary:
            root = Path(temporary)
            roaming = root / "external-roaming"
            local = root / "external-local"
            roaming.mkdir()
            local.mkdir()
            marker = roaming / "sentinel-not-a-ledger.txt"
            marker.write_text("untouched", encoding="utf-8")
            with patch.dict(os.environ, {
                "APPDATA": str(roaming), "LOCALAPPDATA": str(local),
                "TARAZ_QA_DATA_DIR": str(root / "forbidden"),
                "TARAZ_QA_REPORT": str(root / "forbidden-report.json"),
            }):
                report = qa.run_qa()
            self.assertTrue(report["syntheticHost"]["guardDeniedPersonalHistory"])
            self.assertEqual(marker.read_text(encoding="utf-8"), "untouched")
            self.assertFalse((roaming / "Taraz").exists())
            self.assertFalse((local / "Madar-Taraz-Bridge").exists())
            self.assertFalse((root / "forbidden-report.json").exists())

    def test_missing_compiler_fails_closed_never_claims_compiled_gui(self):
        with tempfile.TemporaryDirectory(dir=qa.SCRATCH_PARENT,
                                         prefix="qa-taraz-tools-") as temporary:
            root = Path(temporary)
            modules = root / "node_modules"
            modules.mkdir()
            with self.assertRaisesRegex(qa.QABlocked, "esbuild unavailable"):
                qa.probe_compiled_ui(root, modules)
            self.assertFalse((root / "qa" / "compiled").exists())

    @unittest.skipUnless(TOOLCHAIN, "Explicit read-only Node toolchain not provided")
    def test_compiled_real_jsx_with_react_ssr_opt_in_and_zero_automatic_calls(self):
        report = qa.run_qa(node_modules=Path(TOOLCHAIN))
        result = report["compiledUnpackedUI"]
        self.assertTrue(result["compiledRealJsx"])
        self.assertTrue(result["realReactServerRender"])
        self.assertTrue(result["settingsTabAvailable"])
        self.assertTrue(result["integrationCheckboxDisabledInitially"])
        self.assertTrue(result["collapsedPanelNoAutoLoad"])
        self.assertEqual(result["inboxCalls"], 0)
        self.assertEqual(result["financeCalls"], 0)
        self.assertFalse(result["installedExeLaunched"])
        self.assertFalse(result["browserGuiOpened"])


if __name__ == "__main__":
    unittest.main()
