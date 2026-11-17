"""Actual React Chromium UI -> SHA-pinned packed PYZ metadata recovery QA.

Everything mutable is under fresh marked QA-only TemporaryDirectory instances.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "qa_mtr_packed_browser_recovery_20261110.py"
)
SPEC = importlib.util.spec_from_file_location("mtr_packed_browser_recovery_qa", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class PackedBrowserRecoverySecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.latest = qa._load_existing_runner()
        cls.helper = cls.latest.previous_runner()
        cls.packed_code, cls.manifest = cls.latest.verify_latest_bundle()

    def setUp(self):
        temp = self.helper.sandbox()
        self.root = temp.__enter__()
        self.addCleanup(temp.__exit__, None, None, None)
        self.id = uuid.uuid4().hex
        self.source = self.helper.write_proposal(self.root, self.id)
        self.initial_sha = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def _child(self, action, identifier="", *, manual=False):
        args = [
            sys.executable, "-I", "-B", str(SCRIPT),
            "--child", "--root", str(self.root),
            "--shim-action", action, "--request-id", identifier,
        ]
        if manual:
            args.append("--manual-action")
        return subprocess.run(
            args, cwd=self.root, env=self.helper.sandbox_env(self.root),
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)

    def _success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["backend"], "EXACT_PINNED_TARAZ_PYZ_ONLY")
        self.assertEqual(data["exeSha256"], self.latest.EXE_SHA256)
        self.assertEqual(data["packedModuleSha256"],
                         self.latest.PYZ_MODULE_SHA256)
        self.assertIs(data["financialEventCreated"], False)
        self.assertIs(data["installedExeLaunched"], False)
        self.assertIs(data["qaOnly"], True)
        return data

    def _blocked(self, result):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        data = json.loads(result.stderr)
        self.assertEqual(data["status"], "BLOCKED")
        return data

    def _crash_after_move(self, decision="reviewed"):
        result = self.latest.spawn_child(
            self.root, "review", self.id, decision, fault="before-receipt")
        error = self.latest.parse_child(result, success=False)
        self.assertEqual(error["exception"], "OSError")
        destination = self.root / "reviewed" / (self.id + ".json")
        intent = self.root / "reviewed" / (self.id + ".intent.json")
        receipt = self.root / "reviewed" / (self.id + ".review.json")
        self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest(),
                         self.initial_sha)
        self.assertEqual(json.loads(intent.read_text(encoding="utf-8"))["state"],
                         decision)
        self.assertFalse(receipt.exists())
        self.assertFalse(self.source.exists())
        return destination, intent, receipt

    def test_latest_qa_only_binary_and_snapshot_are_exactly_pinned(self):
        self.assertEqual(self.helper.digest(self.latest.EXE),
                         "f3c4d65418d8f9d80a40618c01bb1534841ca18bf863fd9d09d5ca0fb8449662")
        self.assertEqual(self.manifest["sourceSnapshotSha256"],
                         "cedd3c8cc51802afe0270cbd08971a1f67347ed3a269d7ec5908fe4c62b6f0cc")
        self.assertEqual(self.manifest["packedModuleSha256"],
                         "e2c12afc893dff7ab04ba090266e15172309ba4a2e90a6869106fe974e7a457e")
        self.assertTrue(self.manifest["qaOnly"])
        self.assertFalse(self.manifest["exeLaunched"])
        self.assertFalse(self.manifest["installed"])
        self.assertEqual(self.manifest["sourceInputCount"], 120)
        self.assertIn("tarazIntegrationRecover",
                      self.manifest["packedDesktopMethods"])

    def test_combined_real_pyz_list_is_read_only_without_intent(self):
        result = self._success(self._child("combined-list"))
        self.assertEqual(len(result["data"]["requests"]), 1)
        self.assertEqual(result["data"]["recovery"], [])
        self.assertEqual(result["data"]["requests"][0]["id"], self.id)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),
                         self.initial_sha)
        self.assertFalse(self.root.joinpath("reviewed").exists())

    def test_after_move_reviewed_listing_preserves_decision_without_recovering(self):
        _, intent, receipt = self._crash_after_move("reviewed")
        intent_bytes = intent.read_bytes()
        listed = self._success(self._child("combined-list"))["data"]
        self.assertEqual(listed["requests"], [])
        self.assertEqual(len(listed["recovery"]), 1)
        self.assertEqual(listed["recovery"][0]["id"], self.id)
        self.assertEqual(listed["recovery"][0]["state"], "reviewed")
        self.assertEqual(listed["recovery"][0]["financialEventCreated"], False)
        self.assertFalse(receipt.exists())
        self.assertEqual(intent.read_bytes(), intent_bytes)

    def test_packed_recover_requires_manual_confirmation_then_readback(self):
        _, intent, receipt = self._crash_after_move("rejected")
        intent_bytes = intent.read_bytes()
        self._blocked(self._child("recover", self.id))
        self.assertFalse(receipt.exists())
        self.assertEqual(intent.read_bytes(), intent_bytes)
        result = self._success(self._child("recover", self.id, manual=True))
        self.assertEqual(result["data"], {
            "id": self.id, "state": "rejected", "financialEventCreated": False,
        })
        self.assertEqual(intent.read_bytes(), intent_bytes)
        data = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(data["state"], "rejected")
        self.assertEqual(self._success(self._child("combined-list"))[
            "data"]["recovery"], [])

    def test_second_manual_recovery_is_idempotent_with_zero_financial_writes(self):
        _, intent, receipt = self._crash_after_move("reviewed")
        self._success(self._child("recover", self.id, manual=True))
        before = (intent.read_bytes(), receipt.read_bytes())
        result = self._success(self._child("recover", self.id, manual=True))
        self.assertEqual(result["data"]["state"], "reviewed")
        self.assertEqual(before, (intent.read_bytes(), receipt.read_bytes()))

    def test_old_legacy_receipt_without_intent_is_never_presented(self):
        reviewed = self.root / "reviewed"
        reviewed.mkdir()
        marker = reviewed / (self.id + ".review.json")
        marker.write_text(json.dumps({
            "schema": 1, "id": self.id, "state": "reviewed",
            "financialEventCreated": False,
        }), encoding="utf-8")
        legacy = marker.read_bytes()
        state = self._success(self._child("combined-list"))["data"]
        self.assertEqual(state["recovery"], [])
        self._blocked(self._child("recover", self.id, manual=True))
        self.assertEqual(marker.read_bytes(), legacy)
        self.assertFalse((reviewed / (self.id + ".intent.json")).exists())

    def test_corrupt_after_move_payload_cannot_be_offered_for_recovery(self):
        destination, intent, receipt = self._crash_after_move("reviewed")
        intent_before = intent.read_bytes()
        destination.write_bytes(destination.read_bytes() + b" ")
        state = self._success(self._child("combined-list"))["data"]
        self.assertEqual(state["recovery"], [])
        self.assertEqual(state["recoveryInvalidCount"], 1)
        self._blocked(self._child("recover", self.id, manual=True))
        self.assertEqual(intent.read_bytes(), intent_before)
        self.assertFalse(receipt.exists())

    def test_wrong_or_unsupported_browser_shim_operation_is_refused(self):
        for action, identifier, manual in (
            ("review", self.id, False), ("recover", "", True),
            ("combined-list", self.id, False),
            ("combined-list", "", True),
        ):
            with self.subTest(action=action, id=identifier, manual=manual):
                self._blocked(self._child(action, identifier, manual=manual))
        self.assertTrue(self.source.exists())

    def test_unmarked_root_is_refused_before_packed_execution(self):
        fake = self.root / "not-authorized-QA-root"
        fake.mkdir()
        argv = [
            sys.executable, "-I", "-B", str(SCRIPT),
            "--child", "--root", str(fake), "--shim-action", "combined-list"
        ]
        result = subprocess.run(
            argv, cwd=self.root, env=self.helper.sandbox_env(self.root),
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        self._blocked(result)
        self.assertEqual(list(fake.iterdir()), [])

    def test_altered_latest_manifest_and_module_pin_fail_closed(self):
        with patch.object(self.latest, "EXE_SHA256", "0" * 64):
            with self.assertRaises(self.latest.QABlocked):
                self.latest.verify_latest_bundle()
        with patch.object(self.latest, "PYZ_MODULE_SHA256", "0" * 64):
            with self.assertRaises(self.latest.QABlocked):
                self.latest.verify_latest_bundle()

    def test_browser_dependency_blocker_does_not_touch_synthetic_payload(self):
        with patch.object(qa, "_system_browser",
                          side_effect=qa.QARefused("No system browser")):
            with self.assertRaisesRegex(qa.QARefused, "No system browser"):
                qa.run_browser()
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),
                         self.initial_sha)

    def test_real_react_chromium_manual_recovery_click_to_actual_shapinned_pyz(self):
        # One actual Chromium instance reused for reviewed and rejected cases.
        report = qa.run_browser()
        self.assertEqual(report["status"],
                         "CURRENT_REACT_CHROMIUM_TO_PINNED_PYZ_RECOVERY_PASS")
        self.assertEqual(report["exeSha256"], self.latest.EXE_SHA256)
        self.assertEqual(report["packedModuleSha256"],
                         self.latest.PYZ_MODULE_SHA256)
        self.assertEqual({entry["decision"] for entry in report["reports"]},
                         {"reviewed", "rejected"})
        self.assertEqual([event["action"] for event in report["invocations"]],
                         ["combined-list", "recover", "combined-list"] * 2)
        for sample in report["reports"]:
            self.assertEqual(sample["packedRecoveryCalls"], 1)
            self.assertEqual(sample["normalReviewCalls"], 0)
            self.assertEqual(sample["financialCalls"], 0)
            self.assertTrue(sample["secondConfirmation"])
            self.assertTrue(sample["cancellationNoSideEffect"])
            self.assertTrue(sample["browserActuallyClicked"])
        self.assertTrue(all(item["receiptPersisted"] for item
                            in report["durableVerification"]))
        self.assertFalse(report["installedProgramLaunched"])
        self.assertFalse(report["realLedgerAccessed"])


if __name__ == "__main__":
    unittest.main()
