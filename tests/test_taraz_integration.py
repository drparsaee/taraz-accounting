import json
import hashlib
import os
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import taraz_integration
from taraz_integration import list_requests, review_request


class TarazIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "pending").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def put_request(self, *, key=None, title="Saved task"):
        key = key or uuid.uuid4().hex
        item = {
            "schema": 1, "source": "madar", "id": key,
            "taskId": "saved.task", "title": title, "projectId": "saved.project",
            "createdUtc": "2026-11-07T08:00:00+00:00", "amountRial": "12340",
        }
        source = self.root / "pending" / (key + ".json")
        source.write_text(json.dumps(item), encoding="utf8")
        return key, source

    def paths(self, key):
        reviewed = self.root / "reviewed"
        return (
            reviewed / (key + ".json"),
            reviewed / (key + ".intent.json"),
            reviewed / (key + ".review.json"),
        )

    def test_read_and_review_does_not_post(self):
        key = uuid.uuid4().hex
        item = {
            "schema": 1, "source": "madar", "id": key,
            "taskId": "saved.task", "title": "Saved task", "projectId": "saved.project",
            "createdUtc": "2026-11-07T08:00:00+00:00", "amountRial": "12340",
        }
        (self.root / "pending" / (key + ".json")).write_text(json.dumps(item), encoding="utf8")
        before = list_requests(self.root)
        self.assertTrue(before["connected"])
        self.assertEqual(len(before["requests"]), 1)
        self.assertEqual(before["requests"][0]["amountRial"], 12340)
        receipt = review_request(self.root, key, "reviewed")
        self.assertFalse(receipt["financialEventCreated"])
        self.assertEqual(list_requests(self.root)["requests"], [])
        self.assertTrue((self.root / "reviewed" / (key + ".review.json")).is_file())

    def test_reject_path_traversal(self):
        with self.assertRaises(ValueError):
            review_request(self.root, "../outside", "rejected")

    def test_invalid_monetary_amount_hidden(self):
        key = uuid.uuid4().hex
        item = {
            "schema": 1, "source": "madar", "id": key,
            "taskId": "t", "title": "Task", "projectId": "p",
            "createdUtc": "2026-11-07T08:00:00+00:00", "amountRial": "3.14",
        }
        (self.root / "pending" / (key + ".json")).write_text(json.dumps(item), encoding="utf8")
        outcome = list_requests(self.root)
        self.assertEqual(outcome["requests"], [])
        self.assertEqual(outcome["invalidCount"], 1)

    def test_durable_intent_matches_exact_source_and_replay_is_idempotent(self):
        key, source = self.put_request()
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        moves = []
        original_link = os.link
        original_rename = os.rename

        def track_link(src, dest):
            moves.append(str(dest))
            return original_link(src, dest)

        def track_rename(src, dest):
            moves.append(str(dest))
            return original_rename(src, dest)

        with patch.object(taraz_integration.os, "link", side_effect=track_link), \
                patch.object(taraz_integration.os, "rename", side_effect=track_rename):
            first = review_request(self.root, key, "reviewed")
        dest, intent_path, receipt_path = self.paths(key)
        self.assertEqual(first, {
            "id": key, "state": "reviewed", "financialEventCreated": False,
        })
        self.assertEqual(len(moves), 3)
        self.assertEqual(
            [intent_path.name, dest.name, receipt_path.name],
            [Path(name).name for name in moves],
        )
        intent = json.loads(intent_path.read_text(encoding="utf8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf8"))
        self.assertEqual(intent["sourceDigest"], digest)
        self.assertEqual(intent["state"], "reviewed")
        self.assertEqual(intent["taskId"], "saved.task")
        self.assertEqual(
            {k: v for k, v in intent.items() if k != "sourceDigest"}, receipt,
        )
        saved = (
            dest.read_bytes(), intent_path.read_bytes(), receipt_path.read_bytes(),
        )
        self.assertEqual(review_request(self.root, key, "reviewed"), first)
        self.assertEqual(
            (dest.read_bytes(), intent_path.read_bytes(), receipt_path.read_bytes()),
            saved,
        )
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            review_request(self.root, key, "rejected")
        self.assertEqual(receipt_path.read_bytes(), saved[2])

    def test_failure_before_intent_publish_leaves_pending_retryable(self):
        key, source = self.put_request()
        dest, intent_path, receipt_path = self.paths(key)
        original_link = os.link

        def fail_intent(src, target):
            if str(target) == str(intent_path):
                raise OSError("intent publish fault")
            return original_link(src, target)

        with patch.object(taraz_integration.os, "link", side_effect=fail_intent):
            with self.assertRaisesRegex(OSError, "intent publish fault"):
                review_request(self.root, key, "rejected")
        self.assertTrue(source.is_file())
        self.assertFalse(intent_path.exists())
        self.assertFalse(dest.exists())
        self.assertFalse(receipt_path.exists())
        self.assertEqual(list(self.root.joinpath("reviewed").glob("*.tmp")), [])
        self.assertEqual(review_request(self.root, key, "rejected")["state"], "rejected")

    def test_competing_intent_is_never_clobbered_during_publication(self):
        key, pending = self.put_request()
        dest, intent, receipt = self.paths(key)
        original_link = os.link
        injected = b'{"not":"a-valid-intent"}'

        def create_competing_intent(source, target):
            if str(target) == str(intent):
                intent.write_bytes(injected)
            return original_link(source, target)

        with patch.object(taraz_integration.os, "link", side_effect=create_competing_intent):
            with self.assertRaises(FileExistsError):
                review_request(self.root, key, "reviewed")
        self.assertEqual(intent.read_bytes(), injected)
        self.assertTrue(pending.is_file())
        self.assertFalse(dest.exists() or receipt.exists())
        with self.assertRaises(ValueError):
            review_request(self.root, key, "reviewed")

    def test_competing_receipt_is_never_clobbered_during_publication(self):
        key, pending = self.put_request()
        dest, intent, receipt = self.paths(key)
        original_link = os.link
        injected = b'{"not":"a-valid-receipt"}'

        def create_competing_receipt(source, target):
            if str(target) == str(receipt):
                receipt.write_bytes(injected)
            return original_link(source, target)

        with patch.object(taraz_integration.os, "link", side_effect=create_competing_receipt):
            with self.assertRaises(FileExistsError):
                review_request(self.root, key, "reviewed")
        self.assertEqual(receipt.read_bytes(), injected)
        self.assertFalse(pending.exists())
        self.assertTrue(dest.is_file() and intent.is_file())
        with self.assertRaises(ValueError):
            review_request(self.root, key, "reviewed")

    def test_missing_id_does_not_create_review_folder_or_lock(self):
        with self.assertRaises(FileNotFoundError):
            review_request(self.root, uuid.uuid4().hex, "reviewed")
        self.assertFalse((self.root / "reviewed").exists())

    def test_crash_after_durable_intent_before_move_replays_only_same_decision(self):
        key, source = self.put_request()
        dest, intent_path, receipt_path = self.paths(key)
        original_rename = os.rename

        def fail_move(src, target):
            if str(src) == str(source):
                raise OSError("move fault")
            return original_rename(src, target)

        with patch.object(taraz_integration.os, "rename", side_effect=fail_move):
            with self.assertRaisesRegex(OSError, "move fault"):
                review_request(self.root, key, "reviewed")
        self.assertTrue(intent_path.is_file())
        self.assertTrue(source.is_file())
        self.assertFalse(dest.exists())
        self.assertFalse(receipt_path.exists())
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            review_request(self.root, key, "rejected")
        self.assertTrue(source.is_file())
        self.assertEqual(review_request(self.root, key, "reviewed")["state"], "reviewed")
        self.assertFalse(source.exists())
        self.assertTrue(receipt_path.is_file())

    def test_crash_after_move_before_receipt_reconstructs_from_intent(self):
        key, source = self.put_request()
        dest, intent_path, receipt_path = self.paths(key)
        original_atomic = taraz_integration._atomic_json

        def fail_receipt(path, payload):
            if path == receipt_path:
                raise OSError("receipt fault")
            return original_atomic(path, payload)

        with patch.object(taraz_integration, "_atomic_json", side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, "receipt fault"):
                review_request(self.root, key, "rejected")
        self.assertTrue(dest.is_file())
        self.assertTrue(intent_path.is_file())
        self.assertFalse(source.exists())
        self.assertFalse(receipt_path.exists())
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            review_request(self.root, key, "reviewed")
        self.assertEqual(review_request(self.root, key, "rejected")["state"], "rejected")
        self.assertTrue(receipt_path.is_file())

    def test_receipt_atomic_publish_failure_retries_without_tmp_debris(self):
        key, _ = self.put_request()
        dest, intent_path, receipt_path = self.paths(key)
        original_link = os.link

        def fail_receipt_publish(src, target):
            if str(target) == str(receipt_path):
                raise OSError("receipt publish fault")
            return original_link(src, target)

        with patch.object(taraz_integration.os, "link",
                          side_effect=fail_receipt_publish):
            with self.assertRaisesRegex(OSError, "receipt publish fault"):
                review_request(self.root, key, "reviewed")
        self.assertTrue(dest.is_file())
        self.assertTrue(intent_path.is_file())
        self.assertFalse(receipt_path.exists())
        self.assertEqual(list(self.root.joinpath("reviewed").glob("*.tmp")), [])
        self.assertEqual(review_request(self.root, key, "reviewed")["state"], "reviewed")

    def test_crash_after_receipt_replace_replays_existing_receipt(self):
        key, _ = self.put_request()
        _, intent_path, receipt_path = self.paths(key)
        original_atomic = taraz_integration._atomic_json

        def fail_after_receipt(path, payload):
            original_atomic(path, payload)
            if path == receipt_path:
                raise OSError("post-receipt fault")

        with patch.object(taraz_integration, "_atomic_json", side_effect=fail_after_receipt):
            with self.assertRaisesRegex(OSError, "post-receipt fault"):
                review_request(self.root, key, "reviewed")
        self.assertTrue(intent_path.is_file())
        saved = receipt_path.read_bytes()
        self.assertEqual(review_request(self.root, key, "reviewed")["state"], "reviewed")
        self.assertEqual(receipt_path.read_bytes(), saved)

    def test_pending_digest_mutated_after_intent_fails_closed(self):
        key, source = self.put_request()
        dest, intent_path, receipt_path = self.paths(key)
        original_rename = os.rename
        with patch.object(
            taraz_integration.os, "rename",
            side_effect=lambda src, target:
                (_ for _ in ()).throw(OSError("move fault"))
                if str(src) == str(source) else original_rename(src, target),
        ):
            with self.assertRaisesRegex(OSError, "move fault"):
                review_request(self.root, key, "reviewed")
        # Equivalent parsed metadata but different exact source bytes.
        original = json.loads(source.read_text(encoding="utf8"))
        source.write_text(json.dumps(original, indent=2), encoding="utf8")
        with self.assertRaisesRegex(ValueError, "source changed"):
            review_request(self.root, key, "reviewed")
        self.assertTrue(intent_path.is_file())
        self.assertTrue(source.is_file())
        self.assertFalse(dest.exists())
        self.assertFalse(receipt_path.exists())

    def test_intent_corruption_or_replaced_marker_refused(self):
        key, source = self.put_request()
        _, intent_path, receipt_path = self.paths(key)
        original_rename = os.rename
        with patch.object(
            taraz_integration.os, "rename",
            side_effect=lambda src, target:
                (_ for _ in ()).throw(OSError("move fault"))
                if str(src) == str(source) else original_rename(src, target),
        ):
            with self.assertRaises(OSError):
                review_request(self.root, key, "reviewed")
        expected = intent_path.read_bytes()
        for damaged in (
            b"{broken",
            json.dumps({**json.loads(expected), "sourceDigest": "0" * 64}).encode(),
            json.dumps({**json.loads(expected), "id": "f" * 32}).encode(),
            json.dumps({**json.loads(expected), "state": "unknown"}).encode(),
            json.dumps({**json.loads(expected), "financialEventCreated": True}).encode(),
        ):
            with self.subTest(damaged=damaged[:40]):
                intent_path.write_bytes(damaged)
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    review_request(self.root, key, "reviewed")
                self.assertTrue(source.is_file())
                self.assertFalse(receipt_path.exists())
        intent_path.write_bytes(expected)
        self.assertEqual(review_request(self.root, key, "reviewed")["state"], "reviewed")

    def test_replaced_reviewed_payload_or_receipt_refused(self):
        key, _ = self.put_request()
        review_request(self.root, key, "reviewed")
        dest, intent_path, receipt_path = self.paths(key)
        original_payload = dest.read_bytes()
        dest.write_bytes(original_payload + b" ")
        with self.assertRaisesRegex(ValueError, "source changed"):
            review_request(self.root, key, "reviewed")
        dest.write_bytes(original_payload)
        receipt = json.loads(receipt_path.read_text(encoding="utf8"))
        receipt["state"] = "rejected"
        receipt_path.write_text(json.dumps(receipt), encoding="utf8")
        with self.assertRaisesRegex(ValueError, "receipt"):
            review_request(self.root, key, "reviewed")
        self.assertTrue(intent_path.is_file())

    def test_existing_reviewed_without_intent_never_overwritten(self):
        key, source = self.put_request()
        reviewed = self.root / "reviewed"
        reviewed.mkdir()
        dest, intent, receipt = self.paths(key)
        dest.write_bytes(source.read_bytes())
        with self.assertRaises(FileExistsError):
            review_request(self.root, key, "reviewed")
        self.assertFalse(intent.exists())
        self.assertFalse(receipt.exists())
        self.assertTrue(source.is_file())
        source.unlink()
        with self.assertRaisesRegex(ValueError, "without durable"):
            review_request(self.root, key, "reviewed")
        self.assertTrue(dest.is_file())

    @unittest.skipUnless(os.name == "nt", "Windows non-overwriting rename guarantee")
    def test_destination_appearing_during_move_is_not_overwritten(self):
        key, source = self.put_request()
        dest, intent, receipt = self.paths(key)
        original_rename = os.rename

        def inject_destination(src, target):
            if str(src) == str(source):
                dest.write_bytes(b"unrelated-existing-metadata")
            return original_rename(src, target)

        with patch.object(taraz_integration.os, "rename",
                          side_effect=inject_destination):
            with self.assertRaises(FileExistsError):
                review_request(self.root, key, "reviewed")
        self.assertEqual(dest.read_bytes(), b"unrelated-existing-metadata")
        self.assertTrue(source.is_file())
        self.assertTrue(intent.is_file())
        self.assertFalse(receipt.exists())
        with self.assertRaises(FileExistsError):
            review_request(self.root, key, "reviewed")

    def test_missing_request_with_durable_intent_refuses_receipt(self):
        key, source = self.put_request()
        dest, intent, receipt = self.paths(key)
        original_rename = os.rename
        with patch.object(
            taraz_integration.os, "rename",
            side_effect=lambda src, target:
                (_ for _ in ()).throw(OSError("move fault"))
                if str(src) == str(source) else original_rename(src, target),
        ):
            with self.assertRaises(OSError):
                review_request(self.root, key, "reviewed")
        source.unlink()
        with self.assertRaisesRegex(FileNotFoundError, "missing"):
            review_request(self.root, key, "reviewed")
        self.assertTrue(intent.is_file())
        self.assertFalse(dest.exists())
        self.assertFalse(receipt.exists())

    def test_symlinked_paths_and_receipt_rejected(self):
        key, source = self.put_request()
        external = self.root / "outside.txt"
        external.write_text("not metadata", encoding="utf8")
        source.unlink()
        try:
            source.symlink_to(external)
        except (OSError, NotImplementedError) as error:
            self.skipTest("Symlink creation unavailable: " + str(error))
        with self.assertRaises((PermissionError, ValueError)):
            review_request(self.root, key, "reviewed")
        source.unlink()
        _, source = self.put_request(key=key)
        review_request(self.root, key, "reviewed")
        _, _, receipt = self.paths(key)
        receipt.unlink()
        receipt.symlink_to(external)
        with self.assertRaises((PermissionError, ValueError)):
            review_request(self.root, key, "reviewed")
        self.assertEqual(external.read_text(encoding="utf8"), "not metadata")

    def test_symlinked_reviewed_directory_cannot_escape_bridge(self):
        key, source = self.put_request()
        outside = self.root / "unrelated"
        outside.mkdir()
        try:
            (self.root / "reviewed").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest("Directory symlink unavailable: " + str(error))
        with self.assertRaises(PermissionError):
            review_request(self.root, key, "reviewed")
        self.assertTrue(source.is_file())
        self.assertEqual(list(outside.iterdir()), [])

    def test_replay_after_pending_directory_removed(self):
        key, _ = self.put_request()
        review_request(self.root, key, "reviewed")
        (self.root / "pending").rmdir()
        self.assertEqual(review_request(self.root, key, "reviewed")["state"], "reviewed")

    def test_concurrent_conflicting_reviews_are_serialized(self):
        key, _ = self.put_request()
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs = [
                executor.submit(review_request, self.root, key, decision)
                for decision in ("reviewed", "rejected")
            ]
            outcomes = []
            for job in jobs:
                try:
                    outcomes.append(job.result(timeout=15)["state"])
                except ValueError as error:
                    outcomes.append(str(error))
        self.assertEqual(sum(item in ("reviewed", "rejected") for item in outcomes), 1)
        self.assertEqual(sum("Conflicting" in item for item in outcomes), 1)
        _, intent_path, receipt_path = self.paths(key)
        self.assertEqual(
            json.loads(intent_path.read_text(encoding="utf8"))["state"],
            json.loads(receipt_path.read_text(encoding="utf8"))["state"],
        )

if __name__ == "__main__":
    unittest.main()
