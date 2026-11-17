"""Independent process-restart evidence on synthetic Madar metadata only.

Never starts the installed Taraz, imports taraz_desktop, or opens a ledger.
Every filesystem mutation here is under a fresh TemporaryDirectory.
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

import taraz_integration as integration


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "qa_mtr_taraz_durable_recovery_20261110.py"
SPEC = importlib.util.spec_from_file_location("mtr_taraz_durable_qa", SCRIPT)
assert SPEC and SPEC.loader
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class DurableReviewRecovery(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mtr-taraz-recovery-qa-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "qa-madar-taraz-inbox"
        self.root.mkdir()
        (self.root / "pending").mkdir()
        (self.root / qa.QA_OWNER_MARKER).write_bytes(qa.QA_OWNER_VALUE.encode("ascii"))
        self.ident = uuid.uuid4().hex
        self.key = self.create_request(self.ident)

    def create_request(self, request_id: str) -> str:
        proposal = {
            "schema": 1, "id": request_id, "source": "madar",
            "taskId": "qa-task", "projectId": "qa-project",
            "createdUtc": "2026-11-10T11:00:00+00:00",
            "title": "QA synthetic packaging line", "amountRial": "1200",
            "partyId": "untrusted-synthetic-extras",
        }
        (self.root / "pending" / (request_id + ".json")).write_text(
            json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
        return request_id

    def paths(self, request_id: str | None = None):
        request_id = request_id or self.key
        return (
            self.root / "pending" / (request_id + ".json"),
            self.root / "reviewed" / (request_id + ".json"),
            self.root / "reviewed" / (request_id + ".intent.json"),
            self.root / "reviewed" / (request_id + ".review.json"),
        )

    def child_env(self):
        sandbox = self.root / "qa-environment"
        env = os.environ.copy()
        for name, part in (("APPDATA", "roaming"), ("LOCALAPPDATA", "local"),
                           ("USERPROFILE", "user"), ("HOME", "home"),
                           ("TEMP", "temp"), ("TMP", "temp")):
            directory = sandbox / part
            directory.mkdir(parents=True, exist_ok=True)
            env[name] = str(directory)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        return env

    def child(self, decision: str, *, request_id: str | None = None,
              root: Path | None = None) -> subprocess.CompletedProcess:
        command = [sys.executable, "-B", str(SCRIPT), "recover",
                   "--root", str(root or self.root), "--id", request_id or self.key,
                   "--decision", decision]
        return subprocess.run(command, cwd=self.temporary.name,
                              env=self.child_env(), capture_output=True,
                              encoding="utf-8", errors="replace", timeout=20)

    def ok(self, result: subprocess.CompletedProcess, state="reviewed"):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "id": self.key, "state": state, "financialEventCreated": False,
        })

    def failure(self, result: subprocess.CompletedProcess, error_class: str):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        outcome = json.loads(result.stderr)
        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["errorClass"], error_class)
        return outcome

    def test_pinned_installed_v100_bytecode_is_not_current_durable_source(self):
        manifest = qa.installed_packed_manifest(qa.installed_path())
        source = qa.source_manifest()
        self.assertRegex(source["sourceSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(manifest["installedExecutableSha256"], qa.PINNED_INSTALLED_SHA256)
        self.assertEqual(manifest["installedVersionFolder"], "1.0.0")
        self.assertTrue(all(manifest["installedTarazApiMethods"].values()))
        self.assertTrue(source["sourceHasDurableIntent"])
        self.assertFalse(manifest["installedHasPreMoveIntent"])
        self.assertFalse(manifest["installedHasPerRequestLock"])
        self.assertTrue(manifest["installedReviewHasRenameThenDirectReceiptWritePattern"])
        self.assertEqual(manifest["installedDurableFunctionNames"],
                         ["list_requests", "review_request"])
        self.assertFalse(manifest["installedExecutableLaunched"])
        self.assertFalse(manifest["packedCodeExecuted"])

    def test_wrong_binary_pin_fails_before_unpacking(self):
        fake = self.root / "fake.exe"
        fake.write_bytes(b"not an executable")
        with self.assertRaisesRegex(qa.QABlocked, "SHA-256"):
            qa.installed_packed_manifest(fake)

    def test_child_recovery_requires_explicit_qa_marker(self):
        bad = Path(self.temporary.name) / "qa-unmarked"
        bad.mkdir()
        self.failure(self.child("reviewed", root=bad), "QABlocked")
        self.assertEqual(list(bad.iterdir()), [])

    def test_process_restart_normal_idempotent_and_conflict(self):
        self.ok(self.child("reviewed"))
        pending, dest, intent, receipt = self.paths()
        self.assertFalse(pending.exists())
        self.assertTrue(dest.is_file() and intent.is_file() and receipt.is_file())
        original = (dest.read_bytes(), intent.read_bytes(), receipt.read_bytes())
        self.ok(self.child("reviewed"))
        self.failure(self.child("rejected"), "ValueError")
        self.assertEqual((dest.read_bytes(), intent.read_bytes(), receipt.read_bytes()), original)
        self.assertEqual(json.loads(intent.read_text(encoding="utf8"))["sourceDigest"],
                         hashlib.sha256(dest.read_bytes()).hexdigest())

    def test_process_restart_recovers_before_intent_write(self):
        pending, dest, intent, receipt = self.paths()
        original_link = os.link

        def fail_intent(source, target):
            if str(target) == str(intent):
                raise OSError("synthetic pre-intent interruption")
            return original_link(source, target)

        with patch.object(integration.os, "link", side_effect=fail_intent):
            with self.assertRaisesRegex(OSError, "pre-intent"):
                integration.review_request(self.root, self.key, "reviewed")
        self.assertTrue(pending.exists())
        self.assertFalse(dest.exists() or intent.exists() or receipt.exists())
        self.ok(self.child("reviewed"))

    def test_process_restart_finishes_pre_move_intent_but_rejects_change(self):
        pending, dest, intent, receipt = self.paths()
        real_rename = os.rename

        def fail_move(source, target):
            if str(source) == str(pending):
                raise OSError("synthetic stopped before move")
            return real_rename(source, target)

        with patch.object(integration.os, "rename", side_effect=fail_move):
            with self.assertRaisesRegex(OSError, "before move"):
                integration.review_request(self.root, self.key, "rejected")
        intent_before = intent.read_bytes()
        self.assertTrue(pending.is_file())
        self.assertFalse(dest.exists() or receipt.exists())
        self.failure(self.child("reviewed"), "ValueError")
        self.assertEqual(intent.read_bytes(), intent_before)
        self.ok(self.child("rejected"), state="rejected")
        self.assertEqual(intent.read_bytes(), intent_before)

    def test_process_restart_recovers_missing_receipt_after_move(self):
        pending, dest, intent, receipt = self.paths()
        original = integration._atomic_json

        def fail_receipt(path, payload):
            if path == receipt:
                raise OSError("synthetic missing receipt")
            return original(path, payload)

        with patch.object(integration, "_atomic_json", side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, "missing receipt"):
                integration.review_request(self.root, self.key, "reviewed")
        self.assertFalse(pending.exists())
        self.assertTrue(dest.is_file() and intent.is_file())
        self.assertFalse(receipt.exists())
        old_intent = intent.read_bytes()
        self.ok(self.child("reviewed"))
        self.assertEqual(intent.read_bytes(), old_intent)

    def test_process_restart_after_receipt_write_does_not_duplicate(self):
        _, dest, intent, receipt = self.paths()
        original = integration._atomic_json

        def crash_after_write(path, payload):
            original(path, payload)
            if path == receipt:
                raise OSError("synthetic post-receipt crash")

        with patch.object(integration, "_atomic_json", side_effect=crash_after_write):
            with self.assertRaisesRegex(OSError, "post-receipt crash"):
                integration.review_request(self.root, self.key, "reviewed")
        before = (dest.read_bytes(), intent.read_bytes(), receipt.read_bytes())
        self.ok(self.child("reviewed"))
        self.assertEqual(before, (dest.read_bytes(), intent.read_bytes(), receipt.read_bytes()))

    def test_corrupt_intent_and_exact_source_digest_block_recovery(self):
        pending, dest, intent, receipt = self.paths()
        real_rename = os.rename

        def interrupt(source, target):
            if str(source) == str(pending):
                raise OSError("interrupt")
            return real_rename(source, target)

        with patch.object(integration.os, "rename", side_effect=interrupt):
            with self.assertRaises(OSError):
                integration.review_request(self.root, self.key, "reviewed")
        valid_intent = intent.read_bytes()
        for corruption in (b"{broken", b"" , json.dumps({
            **json.loads(valid_intent), "sourceDigest": "0" * 64,
        }).encode("utf8"), json.dumps({
            **json.loads(valid_intent), "financialEventCreated": True,
        }).encode("utf8")):
            with self.subTest(corruption=repr(corruption[:24])):
                intent.write_bytes(corruption)
                outcome = self.child("reviewed")
                self.assertEqual(outcome.returncode, 2, outcome.stdout)
                self.assertTrue(pending.exists())
                self.assertFalse(dest.exists() or receipt.exists())
        intent.write_bytes(valid_intent)
        source_bytes = pending.read_bytes()
        pending.write_bytes(source_bytes + b" ")
        self.failure(self.child("reviewed"), "ValueError")
        self.assertFalse(receipt.exists() or dest.exists())
        pending.write_bytes(source_bytes)
        self.ok(self.child("reviewed"))

    def test_replayed_other_receipt_is_rejected_without_rewriting(self):
        self.ok(self.child("reviewed"))
        _, _, _, receipt_a = self.paths()
        saved_a = receipt_a.read_bytes()
        key_b = uuid.uuid4().hex
        self.create_request(key_b)
        self.assertEqual(integration.review_request(self.root, key_b, "reviewed")["state"],
                         "reviewed")
        _, dest_b, intent_b, receipt_b = self.paths(key_b)
        receipt_b.write_bytes(saved_a)
        before = (dest_b.read_bytes(), intent_b.read_bytes(), receipt_b.read_bytes())
        self.failure(self.child("reviewed", request_id=key_b), "ValueError")
        self.assertEqual(before, (dest_b.read_bytes(), intent_b.read_bytes(), receipt_b.read_bytes()))

    def test_corrupt_or_forged_receipt_never_claims_posted_finance(self):
        self.ok(self.child("rejected"), state="rejected")
        _, dest, intent, receipt = self.paths()
        valid = json.loads(receipt.read_text(encoding="utf8"))
        for change in ({"state": "reviewed"}, {"financialEventCreated": True},
                       {"source": "madar"}, {"id": uuid.uuid4().hex},
                       {"extra": "forged"}):
            altered = {**valid, **change}
            receipt.write_text(json.dumps(altered), encoding="utf8")
            before = receipt.read_bytes()
            with self.subTest(change=change):
                self.failure(self.child("rejected"), "ValueError")
                self.assertEqual(receipt.read_bytes(), before)
                self.assertTrue(dest.is_file() and intent.is_file())
        receipt.write_text(json.dumps(valid), encoding="utf8")
        self.ok(self.child("rejected"), state="rejected")

    def test_ambiguous_existing_review_or_orphan_receipt_fails_closed(self):
        pending, dest, intent, receipt = self.paths()
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(pending.read_bytes())
        self.failure(self.child("reviewed"), "FileExistsError")
        pending.unlink()
        self.failure(self.child("reviewed"), "ValueError")
        self.assertFalse(intent.exists() or receipt.exists())
        dest.unlink()
        receipt.write_text('{"claim":"reviewed","financialEventCreated":true}', encoding="utf8")
        self.failure(self.child("reviewed"), "ValueError")
        self.assertFalse(intent.exists())

    def test_disappearance_after_durable_intent_is_not_silent_success(self):
        pending, dest, intent, receipt = self.paths()
        real_rename = os.rename

        def halt(source, target):
            if str(source) == str(pending):
                raise OSError("halt")
            return real_rename(source, target)

        with patch.object(integration.os, "rename", side_effect=halt):
            with self.assertRaises(OSError):
                integration.review_request(self.root, self.key, "reviewed")
        pending.unlink()
        self.failure(self.child("reviewed"), "FileNotFoundError")
        self.assertTrue(intent.is_file())
        self.assertFalse(dest.exists() or receipt.exists())

    def test_replayed_pending_after_final_review_is_not_moved(self):
        self.ok(self.child("reviewed"))
        pending, dest, intent, receipt = self.paths()
        original = (dest.read_bytes(), intent.read_bytes(), receipt.read_bytes())
        pending.write_bytes(dest.read_bytes())
        self.failure(self.child("reviewed"), "FileExistsError")
        self.assertEqual((dest.read_bytes(), intent.read_bytes(), receipt.read_bytes()), original)
        self.assertTrue(pending.is_file())

    def test_competing_fresh_process_decisions_have_one_durable_winner(self):
        """The current-source per-request lock excludes contradictory outcomes."""
        environment = self.child_env()
        processes = []
        for decision in ("reviewed", "rejected"):
            command = [sys.executable, "-B", str(SCRIPT), "recover",
                       "--root", str(self.root), "--id", self.key,
                       "--decision", decision]
            processes.append(subprocess.Popen(
                command, cwd=self.temporary.name, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", errors="replace"))
        results = []
        for child in processes:
            stdout, stderr = child.communicate(timeout=20)
            results.append((child.returncode, stdout, stderr))
        self.assertEqual(sorted(result[0] for result in results), [0, 2], results)
        successes = [json.loads(stdout) for code, stdout, _ in results if code == 0]
        failures = [json.loads(stderr) for code, _, stderr in results if code == 2]
        self.assertEqual(failures[0]["errorClass"], "ValueError")
        winner = successes[0]["state"]
        pending, dest, intent, receipt = self.paths()
        self.assertFalse(pending.exists())
        self.assertTrue(dest.is_file())
        self.assertEqual(json.loads(intent.read_text(encoding="utf8"))["state"], winner)
        self.assertEqual(json.loads(receipt.read_text(encoding="utf8"))["state"], winner)
        self.assertIs(json.loads(receipt.read_text(encoding="utf8"))["financialEventCreated"], False)

    def test_atomic_marker_publication_never_overwrites_competing_decision(self):
        """Atomic link must refuse a marker created after the preflight check."""
        pending, dest, intent, receipt = self.paths()
        actual_link = os.link
        competitor = b"synthetic-competing-decision-do-not-overwrite"

        def inject_competing_marker(source, target):
            if str(target) == str(intent):
                self.assertFalse(intent.exists())
                intent.write_bytes(competitor)
            return actual_link(source, target)

        with patch.object(integration.os, "link", side_effect=inject_competing_marker):
            with self.assertRaises(FileExistsError):
                integration.review_request(self.root, self.key, "reviewed")
        self.assertEqual(intent.read_bytes(), competitor)
        self.assertTrue(pending.is_file())
        self.assertFalse(dest.exists() or receipt.exists())
        self.assertEqual(list(intent.parent.glob("*.tmp")), [])
        self.failure(self.child("reviewed"), "JSONDecodeError")
        self.assertEqual(intent.read_bytes(), competitor)


if __name__ == "__main__":
    unittest.main()
