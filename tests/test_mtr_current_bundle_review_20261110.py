"""Only SHA-pinned current QA PYZ bytecode + disposable synthetic bridge data."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qa_mtr_current_bundle_review_20261110.py"
SPEC = importlib.util.spec_from_file_location("qa_mtr_current_packed_review", SCRIPT)
assert SPEC and SPEC.loader
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class CurrentPackedBundleReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verified_code, cls.provenance = qa.verify_bundle()

    def setUp(self):
        self.sandbox = qa.sandbox()
        self.root = self.sandbox.__enter__()
        self.addCleanup(lambda: self.sandbox.__exit__(None, None, None))
        self.request_id = uuid.uuid4().hex
        self.pending = qa.write_proposal(self.root, self.request_id)
        self.reviewed_dir = self.root / "reviewed"
        self.saved_source = self.pending.read_bytes()

    def paths(self, request_id=None):
        request_id = request_id or self.request_id
        return (
            self.root / "pending" / (request_id + ".json"),
            self.reviewed_dir / (request_id + ".json"),
            self.reviewed_dir / (request_id + ".intent.json"),
            self.reviewed_dir / (request_id + ".review.json"),
        )

    def call(self, decision="reviewed", *, request_id=None, fault=""):
        return qa.spawn_packed(self.root, "review", request_id or self.request_id, decision, fault)

    def accepted(self, decision="reviewed", *, request_id=None, fault=""):
        answer = self.call(decision, request_id=request_id, fault=fault)
        self.assertEqual(answer.returncode, 0, answer.stderr)
        result = qa.assert_child(answer, success=True)
        self.assertEqual(result["review"], {
            "id": request_id or self.request_id,
            "state": decision,
            "financialEventCreated": False,
        })
        self.assertEqual(result["provenance"]["packedModuleSha256"],
                         qa.PINNED_MODULE_SHA256)
        self.assertFalse(result["provenance"]["exeLaunched"])
        return result

    def denied(self, *, decision="reviewed", request_id=None, fault="", exception=None):
        result = self.call(decision, request_id=request_id, fault=fault)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        answer = qa.assert_child(result, success=False)
        if exception:
            self.assertEqual(answer["exception"], exception, answer)
        return answer

    def saved(self):
        _, dest, intent, receipt = self.paths()
        return (dest.read_bytes(), intent.read_bytes(), receipt.read_bytes())

    def test_bundle_sha_manifest_snapshot_and_real_pyz_module_are_pinned(self):
        self.assertEqual(qa.digest(qa.EXE), qa.PINNED_EXE_SHA256)
        self.assertEqual(self.provenance["snapshotSha256"], qa.PINNED_SNAPSHOT_SHA256)
        self.assertEqual(self.provenance["packedModuleSha256"], qa.PINNED_MODULE_SHA256)
        self.assertEqual(self.provenance["bundle"], "QA_ONLY")
        self.assertFalse(self.provenance["installed"])
        self.assertFalse(self.provenance["exeLaunched"])
        module = qa.load_packed_module(self.verified_code)
        self.assertEqual(module.review_request.__module__,
                         "mtr_qa_packed_taraz_integration")
        self.assertEqual(module.review_request.__code__.co_filename, "taraz_integration.py")
        self.assertEqual(module._atomic_json.__code__.co_filename, "taraz_integration.py")
        self.assertIn("link", module._atomic_json.__code__.co_names)
        self.assertIn("_request_lock", module.review_request.__code__.co_names)

    def test_tampered_manifest_is_rejected_before_bytecode_execution(self):
        original = json.loads(qa.BUILD_MANIFEST.read_text(encoding="utf-8"))
        fake = self.root / "synthetic-bad-manifest.json"
        fake.write_text(json.dumps({**original, "releaseReady": True}), encoding="utf-8")
        with patch.object(qa, "BUILD_MANIFEST", fake):
            with self.assertRaisesRegex(qa.QABlocked, "manifest"):
                qa.verify_bundle()
        self.assertEqual(qa.digest(qa.EXE), qa.PINNED_EXE_SHA256)

    def test_wrong_executable_pin_is_rejected(self):
        with patch.object(qa, "PINNED_EXE_SHA256", "0" * 64):
            with self.assertRaisesRegex(qa.QABlocked, "manifest"):
                qa.verify_bundle()

    def test_wrong_packed_module_code_pin_is_rejected(self):
        with patch.object(qa, "PINNED_MODULE_SHA256", "0" * 64):
            with self.assertRaisesRegex(qa.QABlocked, "PYZ"):
                qa.verify_bundle()

    def test_wrong_source_snapshot_fingerprint_is_rejected(self):
        with patch.object(qa, "PINNED_SNAPSHOT_SHA256", "0" * 64):
            with self.assertRaisesRegex(qa.QABlocked, "manifest"):
                qa.verify_bundle()

    def test_unpackaged_script_is_not_imported_from_worktree(self):
        names = ("taraz_integration", "taraz_desktop", "standalone_accounting")
        preexisting = {name: sys.modules.get(name) for name in names}
        self.accepted()
        for name in names:
            self.assertIs(sys.modules.get(name), preexisting[name])

    def test_packed_list_rejects_no_proposals_and_reads_disposable_only(self):
        response = qa.spawn_packed(self.root, "list")
        self.assertEqual(response.returncode, 0, response.stderr)
        data = qa.assert_child(response, success=True)
        self.assertEqual(data["list"]["invalidCount"], 0)
        self.assertTrue(data["list"]["connected"])
        self.assertEqual(len(data["list"]["requests"]), 1)
        item = data["list"]["requests"][0]
        self.assertEqual(item["id"], self.request_id)
        self.assertEqual(item["taskId"], "qa.task." + self.request_id[:8])
        self.assertEqual(item["amountRial"], 1500)
        self.assertEqual(self.pending.read_bytes(), self.saved_source)
        self.assertFalse(self.reviewed_dir.exists())

    def test_packed_review_stores_source_bound_intent_and_metadata_receipt(self):
        self.accepted()
        pending, dest, intent, receipt = self.paths()
        self.assertFalse(pending.exists())
        self.assertEqual(dest.read_bytes(), self.saved_source)
        intent_data = json.loads(intent.read_text(encoding="utf-8"))
        receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(intent_data["sourceDigest"],
                         hashlib.sha256(self.saved_source).hexdigest())
        self.assertEqual(intent_data["id"], self.request_id)
        self.assertEqual(intent_data["taskId"], "qa.task." + self.request_id[:8])
        self.assertEqual(intent_data["source"], "taraz")
        self.assertEqual(intent_data["state"], "reviewed")
        self.assertIs(intent_data["financialEventCreated"], False)
        self.assertEqual({key: value for key, value in intent_data.items()
                          if key != "sourceDigest"}, receipt_data)
        for record in (intent_data, receipt_data):
            self.assertNotIn("amountRial", record)
            self.assertNotIn("partyId", record)
            self.assertNotIn("ledger", record)

    def test_packed_rejected_state_persists_and_restart_readback(self):
        self.accepted("rejected")
        original = self.saved()
        self.accepted("rejected")
        self.assertEqual(original, self.saved())
        _, _, intent, receipt = self.paths()
        self.assertEqual(json.loads(intent.read_text(encoding="utf-8"))["state"], "rejected")
        self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["state"], "rejected")
        self.denied(decision="reviewed", exception="ValueError")
        self.assertEqual(original, self.saved())

    def test_packed_review_state_idempotent_across_process_restart(self):
        self.accepted()
        original = self.saved()
        self.accepted()
        self.denied(decision="rejected", exception="ValueError")
        self.assertEqual(original, self.saved())
        readback = qa.assert_child(qa.spawn_packed(self.root, "list"), success=True)
        self.assertEqual(readback["list"]["requests"], [])

    def test_process_crash_before_intent_keeps_pending_for_manual_retry(self):
        self.denied(fault="before-intent", exception="OSError")
        pending, dest, intent, receipt = self.paths()
        self.assertEqual(pending.read_bytes(), self.saved_source)
        self.assertFalse(dest.exists() or intent.exists() or receipt.exists())
        self.accepted()

    def test_process_crash_after_intent_before_move_is_decision_pinned(self):
        self.denied(decision="rejected", fault="before-move", exception="OSError")
        pending, dest, intent, receipt = self.paths()
        self.assertTrue(pending.exists() and intent.exists())
        self.assertFalse(dest.exists() or receipt.exists())
        old_intent = intent.read_bytes()
        self.denied(decision="reviewed", exception="ValueError")
        self.assertEqual(intent.read_bytes(), old_intent)
        self.accepted("rejected")
        self.assertEqual(intent.read_bytes(), old_intent)

    def test_process_crash_after_move_before_receipt_repairs_only_metadata(self):
        self.denied(fault="before-receipt", exception="OSError")
        pending, dest, intent, receipt = self.paths()
        self.assertFalse(pending.exists())
        self.assertEqual(dest.read_bytes(), self.saved_source)
        self.assertTrue(intent.exists())
        self.assertFalse(receipt.exists())
        saved_intent = intent.read_bytes()
        self.denied(decision="rejected", exception="ValueError")
        self.accepted()
        self.assertEqual(intent.read_bytes(), saved_intent)
        self.assertIs(json.loads(receipt.read_text(encoding="utf-8"))[
            "financialEventCreated"], False)

    def test_process_crash_after_receipt_link_keeps_same_record_bytes(self):
        self.denied(fault="after-receipt", exception="OSError")
        original = self.saved()
        self.accepted()
        self.assertEqual(original, self.saved())

    def test_corrupted_intent_blocks_replay_without_republishing_receipt(self):
        self.denied(fault="before-move", exception="OSError")
        pending, dest, intent, receipt = self.paths()
        original = json.loads(intent.read_text(encoding="utf-8"))
        for altered in (
            {"sourceDigest": "0" * 64},
            {"financialEventCreated": True},
            {"state": "rejected"},
            {"id": uuid.uuid4().hex},
            {"extra": "forged"},
        ):
            with self.subTest(change=altered):
                intent.write_text(json.dumps({**original, **altered}), encoding="utf-8")
                self.denied()
                self.assertTrue(pending.exists())
                self.assertFalse(dest.exists() or receipt.exists())
        intent.write_text(json.dumps(original), encoding="utf-8")
        self.accepted()

    def test_exact_source_digest_mismatch_is_not_repaired(self):
        self.denied(fault="before-move", exception="OSError")
        pending, dest, intent, receipt = self.paths()
        saved_intent = intent.read_bytes()
        pending.write_bytes(self.saved_source + b" ")
        self.denied(exception="ValueError")
        self.assertFalse(dest.exists() or receipt.exists())
        self.assertEqual(intent.read_bytes(), saved_intent)
        pending.write_bytes(self.saved_source)
        self.accepted()

    def test_forged_financial_receipt_does_not_become_valid(self):
        self.accepted()
        pending, dest, intent, receipt = self.paths()
        good_receipt = receipt.read_bytes()
        for update in ({"financialEventCreated": True}, {"state": "rejected"},
                       {"source": "madar"}, {"id": uuid.uuid4().hex},
                       {"unexpected": "value"}):
            with self.subTest(update=update):
                data = json.loads(good_receipt)
                receipt.write_text(json.dumps({**data, **update}), encoding="utf-8")
                bad = receipt.read_bytes()
                self.denied(exception="ValueError")
                self.assertEqual(receipt.read_bytes(), bad)
                self.assertEqual(dest.read_bytes(), self.saved_source)
                self.assertTrue(intent.exists())
        receipt.write_bytes(good_receipt)
        self.accepted()

    def test_old_legacy_receipt_without_durable_intent_is_refused(self):
        self.reviewed_dir.mkdir()
        pending, dest, intent, receipt = self.paths()
        receipt.write_text(json.dumps({
            "schema": 1, "id": self.request_id, "state": "reviewed",
            "financialEventCreated": False,
        }), encoding="utf-8")
        original = receipt.read_bytes()
        self.denied(exception="ValueError")
        self.assertEqual(receipt.read_bytes(), original)
        self.assertEqual(pending.read_bytes(), self.saved_source)
        self.assertFalse(intent.exists() or dest.exists())

    def test_ambiguous_reviewed_without_intent_is_refused(self):
        self.reviewed_dir.mkdir()
        pending, dest, intent, receipt = self.paths()
        dest.write_bytes(self.saved_source)
        self.denied(exception="FileExistsError")
        pending.unlink()
        self.denied(exception="ValueError")
        self.assertFalse(intent.exists() or receipt.exists())
        self.assertEqual(dest.read_bytes(), self.saved_source)

    def test_duplicate_pending_after_final_review_is_not_accepted(self):
        self.accepted()
        pending, dest, intent, receipt = self.paths()
        original = self.saved()
        pending.write_bytes(self.saved_source)
        self.denied(exception="FileExistsError")
        self.assertEqual(original, self.saved())
        self.assertEqual(pending.read_bytes(), self.saved_source)

    def test_competing_intent_publication_is_atomic_no_clobber(self):
        self.denied(fault="competing-intent", exception="FileExistsError")
        pending, dest, intent, receipt = self.paths()
        self.assertEqual(intent.read_bytes(), b"QA competing untrusted marker; must survive")
        self.assertEqual(pending.read_bytes(), self.saved_source)
        self.assertFalse(dest.exists() or receipt.exists())
        self.denied(exception="JSONDecodeError")
        self.assertEqual(intent.read_bytes(), b"QA competing untrusted marker; must survive")

    def test_unmarked_external_path_is_refused_before_subprocess_spawning(self):
        fake = self.root / "qa-unmarked"
        fake.mkdir()
        with self.assertRaisesRegex(qa.QABlocked, "QA scratch"):
            qa.spawn_packed(fake, "list")

    def test_invalid_packed_review_request_id_rejected_before_disk_touch(self):
        answer = qa.spawn_packed(self.root, "review", "../outside", "reviewed")
        self.assertEqual(answer.returncode, 2, answer.stdout + answer.stderr)
        self.assertEqual(qa.assert_child(answer, success=False)["exception"], "QABlocked")
        self.assertEqual(self.pending.read_bytes(), self.saved_source)

    def test_complete_postbuild_packed_smoke(self):
        evidence = qa.smoke()
        self.assertEqual(evidence["status"], "PACKED_DURABLE_SYNTHETIC_QA_PASS")
        for key in ("reviewed", "rejected", "restartMetadataReadback",
                    "faultRecovery", "legacyMarkerRefused"):
            self.assertIs(evidence[key], True)
        self.assertIs(evidence["financialPostingTested"], False)
        self.assertIs(evidence["realLedgerAccessed"], False)
        self.assertIs(evidence["installedTarazLaunched"], False)


if __name__ == "__main__":
    unittest.main()
