"""RC3 native non-input desktop safety gates, no implicit GUI launch."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import qa_taraz_v104_rc3_private_native_gui_20261111 as native


class NativeRc3PrivateGuiQA(unittest.TestCase):
    def test_real_exact_rc3_exe_provenance_and_cold_backup(self):
        actual = native.baseline()
        self.assertEqual(native.digest(native.EXE), native.EXE_SHA)
        self.assertEqual(actual["installed"]["version"], "1.0.2")
        self.assertEqual(actual["backup"]["filesRehashed"], 181)
        self.assertTrue(actual["installed"]["futureFolderAbsent"])

    def test_old_v103_harness_import_is_read_only_and_paths_are_new(self):
        self.assertIn("build-0bde36e11d99", str(native.EXE))
        self.assertNotIn("build-eb9d4f2ab076", str(native.EXE))
        self.assertNotEqual(native.EXE, native.legacy.EXE)
        self.assertNotEqual(native.OUTPUT, native.legacy.OUTPUT)
        self.assertEqual(native.BACKUP, native.legacy.BACKUP)

    def test_no_input_desktop_switch_cursor_keyboard_registry_or_service_operations(self):
        source = Path(native.__file__).read_text(encoding="utf-8")
        ast.parse(source)
        for banned in ("SwitchDesktop(", "SetForegroundWindow(", "SetCursorPos(",
                       "SendInput(", "SetThreadDesktop(", "mouse_event(",
                       "keybd_event(", "winreg.SetValue", "winreg.CreateKey",
                       "sc.exe", "netsh", "schtasks", "Set-ItemProperty"):
            self.assertNotIn(banned, source)
        self.assertIn("legacy.PrivateDesktop()", source)
        self.assertIn("desktop.spawn(EXE, work, env)", source)
        self.assertIn("private_acl.secure_private_directory(work)", source)

    def test_readonly_uia_no_implicit_financial_or_madar_navigation(self):
        script = native.PRIVATE_READONLY_UIA_PS
        self.assertIn("navigationPerformed=$false", script)
        self.assertIn("madarServiceActionAttempted=$false", script)
        self.assertIn("financeActionAttempted=$false", script)
        self.assertIn("RootElement.FindAll", script)
        for forbidden in (".Invoke(", ".DoDefaultAction(", "SendInput(",
                          "SwitchDesktop(", "SetForegroundWindow(", ".Click("):
            self.assertNotIn(forbidden, script)

    def test_profile_environment_restricts_runtime_and_network(self):
        with tempfile.TemporaryDirectory(prefix="qa-rc3-env-") as temp:
            runtime = Path(temp) / "qa" / "qa-runtime"
            roots = {"roaming": runtime / "roaming" / "Taraz"}
            env = native.legacy.isolated_env(runtime, roots, runtime / "private-report.json", 45981)
            for name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP", "TMP",
                         "WEBVIEW2_USER_DATA_FOLDER"):
                self.assertTrue(Path(env[name]).is_relative_to(runtime), name)
                self.assertNotEqual(Path(env[name]).resolve(), Path(os.environ.get(name, ".")).resolve())
            self.assertEqual(env["TARAZ_QA_MODE"], "1")
            self.assertIn("--disable-background-networking", env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"])
            self.assertIn("--proxy-server=http://127.0.0.1:9", env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"])

    def test_sha_tamper_fails_prelaunch(self):
        with patch.object(native, "EXE_SHA", "0" * 64):
            with self.assertRaisesRegex(native.NativeBlocked, "SHA mismatch"):
                native.baseline()

    def test_failed_preflight_never_launches_desktop(self):
        with patch.object(native, "baseline", side_effect=native.NativeBlocked("denied")):
            with patch.object(native.legacy, "PrivateDesktop") as desktop:
                with self.assertRaisesRegex(native.NativeBlocked, "denied"):
                    native.run()
                desktop.assert_not_called()

    def test_exact_created_pid_and_creation_time_guard_cleanup(self):
        source = Path(native.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {x.name for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)}
        self.assertTrue({"capture_owned", "stop_owned", "live_process_facts",
                         "visible_window_facts", "cloned_ledger_head"}.issubset(names))
        self.assertIn("process.create_time() == created", source)
        self.assertIn("item.create_time() == created", source)
        self.assertIn("originalVisibleWindowsStillOwned", source)
        self.assertIn("privateLedgerUnchanged", source)

    def test_static_only_is_not_gui_approval(self):
        command = [sys.executable, "-B", str(native.__file__), "--static-only"]
        result = subprocess.run(command, check=False, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(result.returncode, 0, msg=result.stderr[-400:])
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["status"], "STATIC_ONLY_NATIVE_NOT_LAUNCHED")
        self.assertEqual(parsed["installedVersion"], "1.0.2")
        self.assertEqual(parsed["coldBackupFilesVerified"], 181)
        self.assertEqual(parsed["exeSha256"], native.EXE_SHA)

    def test_private_launcher_explicit_flag_not_default(self):
        source = Path(native.__file__).read_text(encoding="utf-8")
        self.assertIn('add_mutually_exclusive_group(required=True)', source)
        self.assertIn('"--run-private-native"', source)
        self.assertIn('"--static-only"', source)
        self.assertIn("PASS_REAL_RC3_PRIVATE_NATIVE_STARTUP_VIEW_ONLY", source)
        self.assertIn("BLOCKED_OR_INCOMPLETE_RC3_NATIVE_GUI", source)


if __name__ == "__main__":
    unittest.main()
