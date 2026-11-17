"""QA-only native startup denial, no real user ledger, GUI or signed actor.

Exactly one SHA-pinned QA EXE may be launched by the bounded negative test.
Never call an installed executable, actual company profile or finance API.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch


SCRIPT = (Path(__file__).resolve().parents[1] / "scripts" /
          "qa_mtr_taraz_qa_gui_recovery_20261110.py")
SPEC = importlib.util.spec_from_file_location("mtr_gui_negative_qa", SCRIPT)
assert SPEC and SPEC.loader
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class NativeTarazGuiRecoveryGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packed = qa.prior_runner()
        cls.helper = cls.packed.previous_runner()
        cls.static = qa.inspect_native_qa_gate()

    def setUp(self):
        manager = self.helper.sandbox()
        self.root = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)

    def test_exact_windowed_qa_exe_is_pinned_and_not_installed(self):
        self.assertEqual(self.static["qaExeSha256"], qa.EXPECTED_EXE_SHA)
        self.assertEqual(self.static["packedIntegrationPyzSha256"], qa.EXPECTED_PYZ_SHA)
        self.assertEqual(self.static["sourceSnapshotSha256"],
                         "cedd3c8cc51802afe0270cbd08971a1f67347ed3a269d7ec5908fe4c62b6f0cc")
        self.assertEqual(self.helper.digest(self.packed.EXE), qa.EXPECTED_EXE_SHA)
        self.assertNotIn("versions", str(self.packed.EXE).lower())
        self.assertIn("qa-52f6b2776362", str(self.packed.EXE).lower())

    def test_packaged_native_bridge_recovery_is_missing(self):
        # This is a real code/HTML-bridge packaging bug, not a simulated deny.
        self.assertTrue(self.static["packedNativeRecoverMethodPresent"])
        self.assertTrue(self.static["packedReactExpectsRecover"])
        self.assertTrue(self.static["packedHtmlBridgeHasList"])
        self.assertTrue(self.static["packedHtmlBridgeHasReview"])
        self.assertFalse(self.static["packedHtmlBridgeHasRecover"])
        self.assertTrue(self.static["nativeJsBridgeMissingRecoverBug"])
        self.assertFalse(self.static["nativeFullRecoveryUiPossibleWithCurrentBridge"])

    def test_native_window_requires_verified_personal_source_guard(self):
        self.assertTrue(self.static["noLedgerGateBeforeNativeWindow"])
        self.assertTrue(self.static["nativeHistoryGuardRequiresRevisionAtLeast608"])
        self.assertTrue(self.static["nativeHistoryGuardRequiresActualNamedPersonalEvents"])
        self.assertFalse(self.static["nativeFullRecoveryUiPossibleWithoutLedger"])
        self.assertFalse(self.static["financialPostingTested"])

    def test_sandbox_env_cannot_use_real_roaming_or_local_profile(self):
        with tempfile.TemporaryDirectory(prefix="qa-ambient-sentinel-", dir=self.root) as temp:
            sentinel = Path(temp)
            roaming = sentinel / "untrusted-roaming"
            local = sentinel / "untrusted-local"
            roaming.mkdir()
            local.mkdir()
            original = roaming / "sentinel.txt"
            original.write_bytes(b"must-not-touch-real-accounting")
            with patch.dict(os.environ, {
                "APPDATA": str(roaming), "LOCALAPPDATA": str(local),
                "TARAZ_DATA_DIR": str(sentinel),
                "TARAZ_QA_DATA_DIR": str(sentinel),
                "TARAZ_QA_MODE": "0",
            }):
                env, book = qa._isolated_env(self.root)
            self.assertEqual(original.read_bytes(), b"must-not-touch-real-accounting")
            self.assertNotEqual(env["APPDATA"], str(roaming))
            self.assertNotEqual(env["LOCALAPPDATA"], str(local))
            self.assertNotEqual(env["TARAZ_QA_DATA_DIR"], str(sentinel))
            self.assertNotIn("TARAZ_DATA_DIR", env)
            self.assertEqual(env["TARAZ_QA_MODE"], "1")
            self.assertTrue(book.is_relative_to(self.root))
            self.assertFalse((book / qa.NO_LEDGER).exists())

    def test_synthetic_packed_review_interruption_is_real_and_receipt_absent(self):
        env, book = qa._isolated_env(self.root)
        key = uuid.uuid4().hex
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(SCRIPT), "--prepare-child",
             "--root", str(self.root), "--request-id", key],
            cwd=self.root, env=env, capture_output=True, encoding="utf-8",
            errors="replace", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "PINNED_SYNTHETIC_CRASH_FIXTURE_CREATED")
        self.assertTrue(data["receiptAbsent"])
        self.assertIs(data["financialEventCreated"], False)
        bridge = Path(env["LOCALAPPDATA"]) / "Madar-Taraz-Bridge"
        intent = bridge / "reviewed" / (key + ".intent.json")
        receipt = bridge / "reviewed" / (key + ".review.json")
        source = bridge / "reviewed" / (key + ".json")
        self.assertEqual(data["intentSha256"], hashlib.sha256(intent.read_bytes()).hexdigest())
        self.assertEqual(data["fixtureSourceSha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertFalse(receipt.exists())
        self.assertFalse((book / qa.NO_LEDGER).exists())

    def test_unmarked_qa_root_and_ambient_directories_are_rejected(self):
        unmarked = self.root / "qa-fake"
        unmarked.mkdir()
        with self.assertRaises(Exception):
            qa._isolated_env(unmarked)
        with self.assertRaises(Exception):
            qa._create_synthetic_interrupted_review(unmarked, uuid.uuid4().hex)
        self.assertEqual(list(unmarked.iterdir()), [])

    def test_reject_tampered_exe_sha_before_any_native_launch(self):
        previous = self.packed.EXE_SHA256
        with patch.object(self.packed, "EXE_SHA256", "0" * 64):
            with self.assertRaises(self.packed.QABlocked):
                self.packed.verify_latest_bundle()
        self.assertEqual(self.packed.EXE_SHA256, previous)

    def test_cli_prohibits_user_supplied_real_profile_path(self):
        call = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--root", str(self.root)],
            cwd=self.root, capture_output=True, encoding="utf-8",
            errors="replace", timeout=10, check=False)
        self.assertEqual(call.returncode, 2, call.stdout)
        data = json.loads(call.stderr)
        self.assertEqual(data["status"], "BLOCKED")

    def test_static_cli_does_not_launch_any_executable(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--static-only"],
            cwd=self.root, capture_output=True, encoding="utf-8",
            errors="replace", timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertFalse(state["launchPerformed"])
        self.assertFalse(state["nativeFullRecoveryUiPossibleWithoutLedger"])

    def test_pre_bridge_fix_latest_qa_raw_pyz_sha_stable_across_interpreters(self):
        # Newer 121-file artifact is PRE-HTML-BRIDGE-FIX; distinct from the
        # pinned f3c4 GUI probe. Hash raw compressed archive bytes rather than
        # nondeterministic marshal.dumps(code) across Python hash seeds.
        observed = []
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), "--post-fix-static-only"],
                cwd=self.root, capture_output=True, encoding="utf-8",
                errors="replace", timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value["status"], "POST_FIX_QA_PYZ_RAW_MEMBER_PIN_VERIFIED")
            self.assertEqual(value["postFixQaExeSha256"], qa.NEWEST_QA_EXE_SHA)
            self.assertEqual(value["postFixSource121SnapshotSha256"], qa.NEWEST_SNAPSHOT_SHA)
            self.assertFalse(value["packedJsBridgeExposesRecover"])
            self.assertFalse(value["exeLaunched"])
            observed.append(value["stableRawCompressedPyzMemberSha256"])
        self.assertEqual(observed, [qa.NEWEST_RAW_PYZ_MEMBER_SHA] * 2)

    def test_pre_bridge_fix_latest_packed_synthetic_recovery(self):
        value = qa.verify_newest_synthetic_recovery()
        self.assertEqual(value["status"], "POST_FIX_QA_PYZ_SYNTHETIC_RECOVERY_PASS")
        self.assertTrue(value["packedModuleExecuted"])
        self.assertTrue(value["preMoveIntentSuppressesDuplicatePending"])
        self.assertTrue(value["completedReceiptSourceTamperFlagged"])
        self.assertTrue(value["manualRecoveryNonfinancial"])
        self.assertFalse(value["qaExeLaunched"])
        self.assertFalse(value["packedJsBridgeExposesRecover"])

    def test_raw_compressed_pyz_member_pin_mismatch_fails_closed(self):
        with patch.object(qa, "NEWEST_RAW_PYZ_MEMBER_SHA", "0" * 64):
            with self.assertRaisesRegex(qa.QABlocked, "compressed PYZ member hash"):
                qa.verify_newest_packed_raw_member()
        with patch.object(qa, "NEWEST_QA_EXE_SHA", "0" * 64):
            with self.assertRaisesRegex(qa.QABlocked, "manifest"):
                qa.verify_newest_packed_raw_member()

    def test_real_pinned_qa_exe_launch_fails_closed_with_no_ledger(self):
        # This actually launches only the SHA-pinned QA-only EXE; no GUI or
        # financial success is expected. Owned process tree is always killed.
        result = qa.run_probe(launch=True)
        self.assertTrue(result["qaExecutableWasActuallyLaunched"])
        self.assertTrue(result["launchPerformed"])
        self.assertIn(result["status"], (
            "GUI_STARTUP_BLOCKED_NO_AUTHENTICATED_LEDGER",
            "GUI_STARTUP_BLOCKED_WINDOWED_ERROR_DIALOG_OR_TIMEOUT",
        ))
        self.assertNotEqual(result["qaExecutableExitCode"], 0)
        self.assertFalse(result["webView2DescendantObserved"])
        self.assertFalse(result["actualNativeWebView2RecoveryGuiVerified"])
        self.assertFalse(result["realAuthenticatedRecoveryVerified"])
        self.assertFalse(result["installedTarazExeLaunched"])
        self.assertFalse(result["sourceGuardBypassed"])
        self.assertTrue(result["syntheticSourceAndIntentUnchanged"])
        self.assertTrue(result["syntheticReceiptStillAbsent"])
        self.assertFalse(result["syntheticLedgerCreated"])
        self.assertFalse(result["realFinancialOperationsExecuted"])


if __name__ == "__main__":
    unittest.main()
