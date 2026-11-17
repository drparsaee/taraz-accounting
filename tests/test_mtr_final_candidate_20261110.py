"""Exact 3e467d QA package, real packed PYZ and actual packed HTML bridge.

All filesystem mutations confined to disposable marked QA-only roots. Never
starts Taraz.exe, authenticates a company, opens ledgers or performs finance.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qa_mtr_final_candidate_20261110.py"
SPEC = importlib.util.spec_from_file_location("qa_mtr_final_candidate", SCRIPT)
assert SPEC and SPEC.loader
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class FinalCandidateQA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.provenance = qa.verify()
        cls.helper = qa.helper()

    def setUp(self):
        disposable = self.helper.sandbox()
        self.root = disposable.__enter__()
        self.addCleanup(disposable.__exit__, None, None, None)
        self.request_id = uuid.uuid4().hex

    def test_exe_121_snapshot_and_raw_pyz_member_exact_pins(self):
        self.assertEqual(self.provenance["exeSha256"], qa.EXE_SHA)
        self.assertEqual(self.provenance["source121SnapshotSha256"], qa.SNAPSHOT_SHA)
        self.assertEqual(self.provenance["stableRawCompressedPyzMemberSha256"],
                         qa.RAW_PYZ_SHA)
        self.assertEqual(self.helper.digest(qa.EXE), qa.EXE_SHA)
        self.assertTrue(self.provenance["qaOnly"])
        self.assertFalse(self.provenance["installed"])
        self.assertFalse(self.provenance["exeLaunched"])
        self.assertFalse(self.provenance["currentWorkingTreeParityAttested"])

    def test_actual_packed_html_js_bridge_three_method_forwarder(self):
        self.assertEqual(set(self.provenance["packedNativeMethods"]), set(qa.METHODS))
        self.assertEqual(set(self.provenance["packedHtmlJsBridgeMethods"]), set(qa.METHODS))
        self.assertTrue(self.provenance["packedReactRecoveryReference"])

    def test_two_independent_python_processes_same_raw_archive_digest(self):
        values = []
        for _ in range(2):
            result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT),
                                     "--manifest-only"], cwd=self.root,
                                    env=self.helper.sandbox_env(self.root),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    encoding="utf8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            values.append(json.loads(result.stdout)["stableRawCompressedPyzMemberSha256"])
        self.assertEqual(values, [qa.RAW_PYZ_SHA, qa.RAW_PYZ_SHA])

    def test_packed_integration_code_is_from_verified_pyz_not_worktree(self):
        preexisting = sys.modules.get("taraz_integration")
        module = self.helper.load_packed_module(self.code)
        self.assertTrue(callable(module.list_requests))
        self.assertTrue(callable(module.list_recoverable_reviews))
        self.assertTrue(callable(module.recover_review))
        self.assertIn("link", module._atomic_json.__code__.co_names)
        self.assertIs(sys.modules.get("taraz_integration"), preexisting)
        self.assertNotIn("taraz_desktop", sys.modules)

    def test_negative_tampered_exe_and_snapshot_pins_fail_closed(self):
        with patch.object(qa, "EXE_SHA", "0" * 64):
            with self.assertRaisesRegex(qa.QABlocked, "manifest"):
                qa.verify()
        with patch.object(qa, "SNAPSHOT_SHA", "f" * 64):
            with self.assertRaisesRegex(qa.QABlocked, "manifest"):
                qa.verify()
        with patch.object(qa, "RAW_PYZ_SHA", "1" * 64):
            with self.assertRaisesRegex(qa.QABlocked, "Raw compressed PYZ"):
                qa.verify()

    def test_tampered_manifest_bridging_claim_cannot_pass(self):
        original = json.loads(qa.MANIFEST.read_text(encoding="utf8"))
        forged = self.root / "forged-manifest.json"
        forged.write_text(json.dumps({**original, "packedHtmlBridgeForwarderPresent": False}),
                          encoding="utf8")
        with patch.object(qa, "MANIFEST", forged):
            with self.assertRaisesRegex(qa.QABlocked, "manifest"):
                qa.verify()
        self.assertEqual(self.helper.digest(qa.EXE), qa.EXE_SHA)

    def test_manual_recovery_requires_confirmation_and_persists_receipt(self):
        stage = qa.spawn(self.root, "stage", self.request_id, decision="reviewed")
        self.assertTrue(stage["ok"])
        self.assertTrue(stage["data"]["receiptAbsent"])
        first = qa.spawn(self.root, "list")
        self.assertTrue(first["ok"])
        self.assertEqual(first["data"]["pending"]["requests"], [])
        self.assertEqual(first["data"]["recovery"]["recovery"][0]["state"], "reviewed")
        denied = qa.spawn(self.root, "recover", self.request_id)
        self.assertFalse(denied["ok"])
        receipt = self.root / "reviewed" / (self.request_id + ".review.json")
        self.assertFalse(receipt.exists())
        allowed = qa.spawn(self.root, "recover", self.request_id, manual=True)
        self.assertTrue(allowed["ok"])
        self.assertEqual(allowed["data"], {
            "id": self.request_id, "state": "reviewed", "financialEventCreated": False,
        })
        self.assertTrue(receipt.is_file())
        after = qa.spawn(self.root, "list")
        self.assertEqual(after["data"]["recovery"]["recovery"], [])

    def test_rejected_recovery_cannot_change_persisted_decision(self):
        self.assertTrue(qa.spawn(self.root, "stage", self.request_id,
                                 decision="rejected")["ok"])
        recovered = qa.spawn(self.root, "recover", self.request_id, manual=True)
        self.assertTrue(recovered["ok"])
        self.assertEqual(recovered["data"]["state"], "rejected")
        receipt = self.root / "reviewed" / (self.request_id + ".review.json")
        original = receipt.read_bytes()
        self.assertTrue(qa.spawn(self.root, "recover", self.request_id, manual=True)["ok"])
        self.assertEqual(receipt.read_bytes(), original)

    def test_legacy_receipt_without_durable_intent_cannot_be_recovered(self):
        review = self.root / "reviewed"
        review.mkdir()
        old = review / (self.request_id + ".review.json")
        old.write_text(json.dumps({"schema": 1, "id": self.request_id,
                                   "state": "reviewed", "financialEventCreated": False}),
                       encoding="utf8")
        listing = qa.spawn(self.root, "list")
        self.assertTrue(listing["ok"])
        self.assertEqual(listing["data"]["recovery"]["recovery"], [])
        rejected = qa.spawn(self.root, "recover", self.request_id, manual=True)
        self.assertFalse(rejected["ok"])
        self.assertFalse((review / (self.request_id + ".intent.json")).exists())

    def test_corrupted_reviewed_payload_is_not_offered_as_recoverable(self):
        self.assertTrue(qa.spawn(self.root, "stage", self.request_id,
                                 decision="reviewed")["ok"])
        moved = self.root / "reviewed" / (self.request_id + ".json")
        moved.write_bytes(moved.read_bytes() + b" ")
        listed = qa.spawn(self.root, "list")
        self.assertEqual(listed["data"]["recovery"]["recovery"], [])
        self.assertEqual(listed["data"]["recovery"]["recoveryInvalidCount"], 1)
        denied = qa.spawn(self.root, "recover", self.request_id, manual=True)
        self.assertFalse(denied["ok"])
        self.assertFalse((self.root / "reviewed" /
                         (self.request_id + ".review.json")).exists())

    def test_unmarked_root_and_invalid_manual_id_are_rejected(self):
        unmarked = self.root / "qa-untrusted"
        unmarked.mkdir()
        with self.assertRaisesRegex(RuntimeError, "QA scratch"):
            qa.spawn(unmarked, "list")
        denied = qa.spawn(self.root, "recover", "../forged-id", manual=True)
        self.assertFalse(denied["ok"])
        self.assertEqual(list((self.root / "reviewed").glob("*.review.json"))
                         if (self.root / "reviewed").exists() else [], [])

    def test_end_to_end_packed_restart_smoke_both_decisions(self):
        output = qa.smoke()
        self.assertEqual(output["status"], "FINAL_CANDIDATE_PACKED_SYNTHETIC_QA_PASS")
        self.assertEqual({x["decision"] for x in output["cases"]},
                         {"reviewed", "rejected"})
        self.assertTrue(all(x["manualOnly"] and x["idempotent"]
                            and x["financialEventCreated"] is False
                            for x in output["cases"]))
        self.assertFalse(output["exeLaunched"])
        self.assertFalse(output["realLedgerOpened"])
        self.assertFalse(output["currentWorkingTreeParityAttested"])


if __name__ == "__main__":
    unittest.main()
