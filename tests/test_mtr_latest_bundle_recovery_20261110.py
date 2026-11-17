"""Latest SHA-pinned PYZ recovery, tested only with disposable local metadata.

The tests do not launch Taraz.exe, connect to any service or use accounting.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qa_mtr_latest_bundle_recovery_20261110.py"
SPEC = importlib.util.spec_from_file_location("mtr_latest_packed_recovery_qa", SCRIPT)
assert SPEC and SPEC.loader
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class LatestPinnedTarazPackedRecoveryQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.manifest = qa.verify_latest_bundle()
        cls.helper = qa.previous_runner()

    def setUp(self):
        temporary = self.helper.sandbox()
        self.root = temporary.__enter__()
        self.addCleanup(temporary.__exit__, None, None, None)
        self.identifier = uuid.uuid4().hex
        self.source = self.helper.write_proposal(self.root, self.identifier)
        self.original_source = self.source.read_bytes()

    def paths(self):
        reviewed = self.root / "reviewed"
        return (reviewed / (self.identifier + ".json"),
                reviewed / (self.identifier + ".intent.json"),
                reviewed / (self.identifier + ".review.json"))

    def call(self, action, decision="", fault="", manual_action=False):
        return qa.spawn_child(self.root, action, self.identifier
                              if action != "list-recoverable" else "",
                              decision, fault=fault, manual_action=manual_action)

    def accepted(self, action, decision="", fault="", manual_action=False):
        outcome = self.call(action, decision, fault, manual_action)
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        answer = qa.parse_child(outcome, success=True)
        self.assertEqual(answer["provenance"]["packedModuleSha256"],
                         qa.PYZ_MODULE_SHA256)
        self.assertFalse(answer["provenance"]["exeLaunched"])
        return answer

    def blocked(self, action, decision="", fault="", manual_action=False, error=None):
        outcome = self.call(action, decision, fault, manual_action)
        self.assertEqual(outcome.returncode, 2, outcome.stdout + outcome.stderr)
        answer = qa.parse_child(outcome, success=False)
        if error:
            self.assertEqual(answer["exception"], error)
        return answer

    def crash_after_move(self, decision):
        self.blocked("review", decision, "before-receipt", error="OSError")
        dest, intent, receipt = self.paths()
        self.assertFalse(self.source.exists())
        self.assertEqual(dest.read_bytes(), self.original_source)
        self.assertTrue(intent.is_file())
        self.assertFalse(receipt.exists())
        intent_data = json.loads(intent.read_text(encoding="utf-8"))
        self.assertEqual(intent_data["state"], decision)
        self.assertEqual(intent_data["sourceDigest"],
                         hashlib.sha256(self.original_source).hexdigest())
        self.assertIs(intent_data["financialEventCreated"], False)
        return intent_data

    def listing(self):
        answer = self.accepted("list-recoverable")["listing"]
        # The source returns a compact two-field response when no reviewed
        # directory exists; the truncation flag appears for enumerated roots.
        self.assertEqual(answer.get("recoveryTruncated", False), False)
        return answer

    def test_exact_latest_exe_sha_and_120_source_snapshot_verified(self):
        self.assertEqual(self.manifest["exeSha256"], qa.EXE_SHA256)
        self.assertEqual(self.manifest["sourceSnapshotSha256"], qa.SNAPSHOT_SHA256)
        self.assertEqual(self.manifest["packedModuleSha256"], qa.PYZ_MODULE_SHA256)
        self.assertEqual(self.manifest["sourceInputCount"], 120)
        self.assertEqual(qa.previous_runner().digest(qa.EXE), qa.EXE_SHA256)
        self.assertTrue(self.manifest["qaOnly"])
        self.assertFalse(self.manifest["installed"])
        self.assertFalse(self.manifest["exeLaunched"])
        self.assertEqual(set(self.manifest["packedDesktopMethods"]),
                         qa.EXPECTED_NATIVE_METHODS)

    def test_real_packed_PYZ_code_object_is_used_not_current_source_import(self):
        helper = qa.previous_runner()
        existing = {name: sys.modules.get(name) for name in
                    ("taraz_integration", "taraz_desktop")}
        integration = helper.load_packed_module(self.code)
        self.assertEqual(integration.recover_review.__code__.co_filename,
                         "taraz_integration.py")
        self.assertEqual(integration.list_recoverable_reviews.__code__.co_filename,
                         "taraz_integration.py")
        self.assertIn("review_request", integration.recover_review.__code__.co_names)
        self.assertIn("link", integration._atomic_json.__code__.co_names)
        self.listing()
        for name, obj in existing.items():
            self.assertIs(sys.modules.get(name), obj)

    def test_initial_recovery_listing_is_empty_and_read_only(self):
        self.assertEqual(self.listing()["recovery"], [])
        self.assertEqual(self.source.read_bytes(), self.original_source)
        self.assertFalse(self.root.joinpath("reviewed").exists())

    def test_reviewed_after_move_crash_manual_listing_recovery_and_empty_readback(self):
        durable = self.crash_after_move("reviewed")
        observed = self.listing()
        self.assertEqual(observed["recoveryInvalidCount"], 0)
        self.assertEqual(observed["recovery"], [{
            "id": self.identifier, "taskId": durable["taskId"],
            "title": "QA-only packaging service", "state": "reviewed",
            "financialEventCreated": False,
        }])
        _, intent, receipt = self.paths()
        original_intent = intent.read_bytes()
        answer = self.accepted("recover", manual_action=True)
        self.assertEqual(answer["receipt"], {
            "id": self.identifier, "state": "reviewed",
            "financialEventCreated": False,
        })
        self.assertEqual(intent.read_bytes(), original_intent)
        self.assertTrue(receipt.is_file())
        expected_receipt = {
            key: value for key, value in durable.items() if key != "sourceDigest"
        }
        self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")),
                         expected_receipt)
        self.assertEqual(self.listing()["recovery"], [])

    def test_rejected_after_move_crash_can_only_complete_original_rejection(self):
        durable = self.crash_after_move("rejected")
        self.assertEqual(self.listing()["recovery"][0]["state"], "rejected")
        self.blocked("review", decision="reviewed", error="ValueError")
        result = self.accepted("recover", manual_action=True)["receipt"]
        self.assertEqual(result["state"], "rejected")
        self.assertIs(result["financialEventCreated"], False)
        _, intent, receipt = self.paths()
        self.assertEqual(json.loads(intent.read_text(encoding="utf-8"))["state"],
                         durable["state"])
        self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["state"],
                         "rejected")
        self.assertEqual(self.listing()["recovery"], [])

    def test_recovery_requires_explicit_manual_action_not_background(self):
        self.crash_after_move("reviewed")
        self.blocked("recover", error="QABlocked")
        self.assertFalse(self.paths()[2].exists())
        self.assertEqual(len(self.listing()["recovery"]), 1)
        self.accepted("recover", manual_action=True)

    def test_post_recovery_replay_is_idempotent_and_receipt_not_rewritten(self):
        self.crash_after_move("reviewed")
        self.accepted("recover", manual_action=True)
        original = tuple(path.read_bytes() for path in self.paths())
        self.accepted("recover", manual_action=True)
        self.assertEqual(tuple(path.read_bytes() for path in self.paths()), original)
        self.assertEqual(self.listing()["recovery"], [])

    def test_completed_review_is_not_offered_as_manual_recovery(self):
        self.accepted("review", decision="reviewed")
        self.assertEqual(self.listing()["recovery"], [])
        _, _, receipt = self.paths()
        self.assertTrue(receipt.is_file())

    def test_legacy_receipt_without_intent_is_not_recoverable(self):
        reviewed = self.root / "reviewed"
        reviewed.mkdir()
        legacy_receipt = reviewed / (self.identifier + ".review.json")
        legacy_receipt.write_text(json.dumps({
            "schema": 1, "id": self.identifier, "state": "reviewed",
            "financialEventCreated": False,
        }), encoding="utf-8")
        old_receipt = legacy_receipt.read_bytes()
        self.assertEqual(self.listing()["recovery"], [])
        self.blocked("recover", manual_action=True, error="FileNotFoundError")
        self.assertEqual(legacy_receipt.read_bytes(), old_receipt)
        self.assertEqual(self.source.read_bytes(), self.original_source)
        self.assertFalse((reviewed / (self.identifier + ".intent.json")).exists())

    def test_legacy_reviewed_payload_without_intent_is_not_recoverable(self):
        reviewed = self.root / "reviewed"
        reviewed.mkdir()
        moved = reviewed / (self.identifier + ".json")
        self.source.rename(moved)
        self.assertEqual(self.listing()["recovery"], [])
        self.blocked("recover", manual_action=True, error="FileNotFoundError")
        self.assertEqual(moved.read_bytes(), self.original_source)

    def test_changed_reviewed_source_digest_fails_closed(self):
        self.crash_after_move("reviewed")
        dest, intent, receipt = self.paths()
        original_intent = intent.read_bytes()
        dest.write_bytes(self.original_source + b" ")
        found = self.listing()
        self.assertEqual(found["recovery"], [])
        self.assertEqual(found["recoveryInvalidCount"], 1)
        self.blocked("recover", manual_action=True, error="ValueError")
        self.assertEqual(intent.read_bytes(), original_intent)
        self.assertFalse(receipt.exists())

    def test_forged_financial_intent_is_invalid_and_never_recovered(self):
        self.crash_after_move("reviewed")
        _, intent, receipt = self.paths()
        content = json.loads(intent.read_text(encoding="utf-8"))
        content["financialEventCreated"] = True
        intent.write_text(json.dumps(content), encoding="utf-8")
        self.assertEqual(self.listing()["recovery"], [])
        self.assertEqual(self.listing()["recoveryInvalidCount"], 1)
        self.blocked("recover", manual_action=True, error="ValueError")
        self.assertFalse(receipt.exists())

    def test_missing_or_ambiguous_metadata_payload_cannot_be_recovered(self):
        self.crash_after_move("rejected")
        dest, _, receipt = self.paths()
        dest.unlink()
        self.assertEqual(self.listing()["recovery"], [])
        self.blocked("recover", manual_action=True, error="FileNotFoundError")
        self.assertFalse(receipt.exists())

    def test_untrusted_second_pending_copy_does_not_clear_recovery(self):
        self.crash_after_move("reviewed")
        self.source.write_bytes(self.original_source)
        state = self.listing()
        self.assertEqual(state["recovery"], [])
        self.assertEqual(state["recoveryInvalidCount"], 1)
        self.blocked("recover", manual_action=True, error="FileExistsError")
        self.assertFalse(self.paths()[2].exists())

    def test_manifest_mismatch_fails_closed(self):
        manifest = json.loads(qa.MANIFEST.read_text(encoding="utf-8"))
        bad = self.root / "bad-build-report.json"
        bad.write_text(json.dumps({**manifest, "releaseReady": True}),
                       encoding="utf-8")
        with patch.object(qa, "MANIFEST", bad):
            with self.assertRaisesRegex(qa.QABlocked, "manifest pin"):
                qa.verify_latest_bundle()

    def test_bundle_wrong_sha_or_snapshot_pin_fails_closed(self):
        with patch.object(qa, "EXE_SHA256", "0" * 64):
            with self.assertRaises(qa.QABlocked):
                qa.verify_latest_bundle()
        with patch.object(qa, "SNAPSHOT_SHA256", "f" * 64):
            with self.assertRaises(qa.QABlocked):
                qa.verify_latest_bundle()
        with patch.object(qa, "PYZ_MODULE_SHA256", "0" * 64):
            with self.assertRaisesRegex(qa.QABlocked, "PYZ"):
                qa.verify_latest_bundle()

    def test_unmarked_or_nested_non_QA_directory_not_accepted(self):
        bad = self.root / "not-an-authorized-QA-root"
        bad.mkdir()
        # The helper is dynamically loaded separately for each invocation, so
        # its QABlocked class identity differs despite the same safe contract.
        with self.assertRaisesRegex(RuntimeError, "direct, existing QA scratch"):
            qa.spawn_child(bad, "list-recoverable")

    def test_full_smoke_actually_uses_packed_current_recovery_code(self):
        result = qa.smoke()
        self.assertEqual(result["status"], "LATEST_PACKED_OPERATOR_RECOVERY_QA_PASS")
        for name in ("reviewedAfterMoveRecovered", "rejectedAfterMoveRecovered",
                     "postRecoveryListingEmpty", "legacyNoIntentRefused",
                     "manualOnly"):
            self.assertIs(result[name], True)
        self.assertIs(result["actualTarazExeLaunched"], False)
        self.assertIs(result["ledgerAccessed"], False)


if __name__ == "__main__":
    unittest.main()
