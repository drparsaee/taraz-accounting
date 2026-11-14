"""Harness-only QA. No frozen EXE or native GUI is ever launched here."""
from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import os
import unittest

from scripts import qa_taraz_ai_frozen_real_auth_20261114 as qa


class FrozenAiAuthenticatedHarnessContract(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="qa-only-frozen-auth-harness-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.artifacts = self.root / "candidate-artifacts"
        self.artifacts.mkdir()

    def candidate(self, *, fake_hash=None, fake_source=None, installed=False):
        binary = self.artifacts / "build-1234abcd9876" / "binary"
        binary.mkdir(parents=True)
        exe = binary / "Taraz.exe"
        exe.write_bytes(b"SYNTHETIC_NOT_A_REAL_EXE")
        sha = qa.digest(exe)
        source = "a" * 64
        (binary.parent / "build-report.json").write_text(json.dumps({
            "exeSha256": fake_hash or sha, "sourceFreezeSha256": fake_source or source,
            "installed": installed, "syntheticForUnitTest": True,
        }), encoding="utf-8")
        return exe, sha, source

    def test_explicit_sha_and_source_pins_accept_only_matching_uninstalled_manifest(self):
        exe, sha, source = self.candidate()
        info = qa.validate_candidate(exe, sha, source, artifact_root=self.artifacts)
        self.assertEqual(info["exeSha256"], sha)
        self.assertEqual(info["sourceFreezeSha256"], source)
        self.assertTrue(info["uninstalledManifest"])

    def test_wrong_hash_or_changed_binary_fails_closed(self):
        exe, sha, source = self.candidate()
        with self.assertRaises(qa.FrozenAuthBlocked):
            qa.validate_candidate(exe, "b" * 64, source, artifact_root=self.artifacts)
        exe.write_bytes(b"SYNTHETIC_TAMPER")
        with self.assertRaises(qa.FrozenAuthBlocked):
            qa.validate_candidate(exe, sha, source, artifact_root=self.artifacts)

    def test_mismatched_frozen_source_pin_fails_closed(self):
        exe, sha, source = self.candidate(fake_source="b" * 64)
        with self.assertRaisesRegex(qa.FrozenAuthBlocked, "pins"):
            qa.validate_candidate(exe, sha, source, artifact_root=self.artifacts)

    def test_installed_or_untrusted_candidate_path_fails_closed(self):
        exe, sha, source = self.candidate(installed=True)
        with self.assertRaisesRegex(qa.FrozenAuthBlocked, "uninstalled"):
            qa.validate_candidate(exe, sha, source, artifact_root=self.artifacts)
        report = exe.parent.parent / "build-report.json"
        data = json.loads(report.read_text())
        data["installed"] = False
        report.write_text(json.dumps(data))
        with self.assertRaisesRegex(qa.FrozenAuthBlocked, "uninstalled QA build"):
            qa.validate_candidate(exe, sha, source,
                                  artifact_root=self.root / "another-artifacts")

    def test_no_candidate_preflight_never_launches_any_process_or_creates_profile(self):
        output = io.StringIO()
        with (patch.object(qa, "run_private", side_effect=AssertionError("RUN_FORBIDDEN")),
              redirect_stdout(output)):
            code = qa.main(["--preflight"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"],
                         "BLOCKED_CANDIDATE_NOT_READY")
        self.assertEqual(list(self.root.iterdir()), [self.artifacts])

    def test_run_private_missing_candidate_is_blocked_before_spawn(self):
        output = io.StringIO()
        with patch.object(qa, "run_private", side_effect=AssertionError("RUN_FORBIDDEN")):
            with redirect_stdout(output):
                code = qa.main(["--run-private"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output.getvalue())["frozenExeTested"])

    def test_resource_gate_rejects_insufficient_ram_before_any_spawn(self):
        with patch("os.cpu_count", return_value=8), patch(
                "psutil.virtual_memory", return_value=SimpleNamespace(available=128 * 1024**2)):
            with self.assertRaisesRegex(qa.FrozenAuthBlocked, "RAM"):
                qa._resources_available(self.artifacts)

    def test_missing_playwright_node_refuses_to_run_cdp_before_file_creation(self):
        with patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(qa.FrozenAuthBlocked, "Node"):
                qa._execute_private_cdp(49152, self.root, {}, "create", 6, 1)
        self.assertFalse((self.root / "private-frozen-cdp-1.cjs").exists())

    def test_native_stages_are_owner_scoped_without_global_mouse_or_forced_kill(self):
        script = qa.AUTH_UIA_PS
        self.assertIn("$OwnerIds", script)
        self.assertIn("$owned -contains $_.Current.ProcessId", script)
        self.assertIn("GetCurrentPattern", script)
        self.assertIn("'QA_COMPANY_SELECTION_NOT_ACCESSIBLE'", script)
        self.assertIn("'NATIVE_LOGIN_VALUE_PATTERN_UNAVAILABLE'", script)
        self.assertIn("SINGLE_REGISTERED_PRESELECTED_TK", script)
        self.assertIn("$result.errorCode", script)
        self.assertIn("$known -ccontains $message", script)
        self.assertNotIn("$result.errorMessage", script)
        self.assertIn("$result.verifiedTransition=$true", script)
        self.assertIn("GetGUIThreadInfo", script)
        self.assertIn("GetAncestor($info.hwndFocus,2) -ne $hwnd", script)
        self.assertIn("PostMessageW($target", script)
        self.assertIn("0x0100,[IntPtr]::new(13)", script)
        self.assertIn("PRIVATE_TK_ENTER_DID_NOT_OPEN_LOGIN", script)
        self.assertIn("PRIVATE_TK_LOGIN_DID_NOT_OPEN_ACCOUNTING", script)
        self.assertIn("PrivateTkEnterRealQaCredentials", script)
        self.assertIn("TARAZ_QA_SINGLE_ADMIN", script)
        self.assertIn("PrivateTkPostAsciiOnly", script)
        self.assertNotIn("SendKeys", script)
        self.assertNotIn("SendInput", script)
        self.assertNotIn("SetCursorPos", script)
        self.assertNotIn("SwitchDesktop", script)

    def test_known_native_error_is_reportable_but_secrets_are_never_reflected(self):
        self.assertEqual(qa.safe_native_uia_error_code("PRIVATE_TK_GUI_THREAD_UNAVAILABLE"),
                         "PRIVATE_TK_GUI_THREAD_UNAVAILABLE")
        self.assertEqual(qa.safe_native_uia_error_code("EXACT_NATIVE_BUTTON_UNAVAILABLE"),
                         "EXACT_NATIVE_BUTTON_UNAVAILABLE")
        self.assertEqual(qa.safe_native_uia_error_code("password=QA-secret-private"),
                         "UNKNOWN_NATIVE_UIA_ERROR")
        self.assertEqual(qa.safe_native_uia_error_code("D:\\private\\user-data"),
                         "UNKNOWN_NATIVE_UIA_ERROR")
        self.assertEqual(qa.safe_native_uia_error_code(None), "UNKNOWN_NATIVE_UIA_ERROR")

    def test_cdp_contract_uses_existing_browser_and_visible_ui_not_bridge_mutations(self):
        source = qa.CDP_TEST
        self.assertIn("connectOverCDP", source)
        self.assertNotIn("chromium.launch", source)
        self.assertIn(".taraz-ai-chat", source)
        self.assertIn("getByRole('button'", source)
        self.assertIn("await approve.click()", source)
        self.assertIn("after.view.journals.length", source)
        self.assertIn("RESTART_MESSAGES_MISSING", source)
        self.assertNotIn("window.madar.tarazAiChatCommand(", source)
        self.assertNotIn("window.madar.standaloneAccountingCommand(", source)

    @unittest.skipUnless(os.name == "nt", "Real LocalCompanyIdentity fixture is Windows-only QA")
    def test_fixture_contains_real_identity_and_issued_price_in_qa_only(self):
        from standalone_accounting_company_registry import StandaloneCompanyRegistry
        from standalone_accounting_identity import LocalCompanyIdentity
        from standalone_accounting import StandaloneAccountingStore

        runtime = self.root / "qa" / "qa-runtime"
        runtime.mkdir(parents=True)
        fixture = qa.create_private_fixture(runtime)
        book = fixture["book"]
        self.assertTrue(book.is_relative_to(runtime))
        registry = StandaloneCompanyRegistry(fixture["profile"])
        self.assertEqual(registry.company_data_directory(fixture["companyId"]), book)
        identity = LocalCompanyIdentity(book)
        self.assertTrue(identity.initialized())
        token = identity.login(qa.QA_USER, fixture["password"])
        self.assertEqual(identity.require_session(token, "admin")["username"], qa.QA_USER)
        identity.logout(token)
        state = StandaloneAccountingStore(book / "standalone-accounting.sqlite3",
                                          default_currency="RIAL").read(
              actor=qa.QA_USER, accounts=identity.accounting_accounts())
        self.assertEqual(state["revision"], 6)
        self.assertEqual(state["view"]["invoices"][qa.QA_SOURCE]["status"], "issued")
        self.assertEqual(len(state["view"]["journals"]), 1)
        self.assertFalse((book / "taraz-ai-chat.sqlite3").exists())

    @unittest.skipUnless(os.name == "nt", "Private CDP entitlement is Windows-specific")
    def test_private_cdp_entitlement_matches_actual_taraz_marker_contract(self):
        from scripts import qa_taraz_v103_native_gui_20261111 as native

        runtime = self.root / "qa" / "qa-runtime"
        runtime.mkdir(parents=True)
        fixture = qa.create_private_fixture(runtime)
        profile = fixture["profile"]
        roots = {"roaming": profile, "local": runtime / "localappdata",
                 "bridge": runtime / "localappdata"}
        env = native.isolated_env(runtime, roots, self.root / "synthetic-native-report.json",
                                  49152)
        env["TARAZ_QA_DATA_DIR"] = str(profile)
        env["TARAZ_QA_CDP_PORT"] = "49152"
        env["TARAZ_QA_SINGLE_COMPANY"] = "1"
        env["TARAZ_QA_SINGLE_ADMIN"] = "1"
        qa._guard_private_paths(runtime, profile, fixture["book"], env)
        altered = dict(env)
        altered["APPDATA"] = str(self.root)
        with self.assertRaises(qa.FrozenAuthBlocked):
            qa._guard_private_paths(runtime, profile, fixture["book"], altered)
        altered = dict(env)
        altered["TARAZ_QA_CDP_PORT"] = "1"
        with patch("taraz_desktop.private_qa_cdp_port", side_effect=PermissionError):
            with self.assertRaises((qa.FrozenAuthBlocked, PermissionError)):
                qa._guard_private_paths(runtime, profile, fixture["book"], altered)
        marker = fixture["book"] / ".taraz-private-cdp-qa.json"
        self.assertEqual(json.loads(marker.read_text()), {
            "privateQaOnly": True, "profile": str(fixture["book"].resolve())})
        marker.write_text(json.dumps({"privateQaOnly": True, "profile": "forged"}))
        with self.assertRaises(qa.FrozenAuthBlocked):
            qa._guard_private_paths(runtime, profile, fixture["book"], env)

    def test_unsafe_multi_company_tk_preselection_cannot_be_assumed(self):
        from scripts import qa_taraz_v103_native_gui_20261111 as native
        from standalone_accounting_company_registry import StandaloneCompanyRegistry
        runtime = self.root / "qa" / "qa-runtime"
        runtime.mkdir(parents=True)
        fixture = qa.create_private_fixture(runtime)
        profile = fixture["profile"]
        env = native.isolated_env(runtime, {
            "roaming": profile, "local": runtime / "localappdata",
            "bridge": runtime / "localappdata",
        }, self.root / "report.json", 49152)
        env.update(TARAZ_QA_DATA_DIR=str(profile), TARAZ_QA_CDP_PORT="49152",
                   TARAZ_QA_SINGLE_COMPANY="1", TARAZ_QA_SINGLE_ADMIN="1")
        StandaloneCompanyRegistry(profile).create_company("DO_NOT_SELECT")
        with self.assertRaisesRegex(qa.FrozenAuthBlocked, "Exactly one"):
            qa._guard_private_paths(runtime, profile, fixture["book"], env)


if __name__ == "__main__":
    unittest.main()
