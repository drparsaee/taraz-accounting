"""Windows DPAPI sealed immutable archive: synthetic-only load and crash QA.

No real Taraz ledger, configured peer, installed app, or HTTP transport is
opened. Files are created exclusively in fresh TemporaryDirectory fixtures.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from taraz_ecosystem_credentials import (
    _create_secure_file, _principal_sid,
)
from taraz_ecosystem_mailbox_peer import (
    _MAX_HOT_RESULTS, _SealedReplyCache, _seal_scope, MailboxPeerDenied,
)
from taraz_ai_chat_store import _protect
from tests.test_taraz_ecosystem_private_acl_20261117 import (
    _add_everyone_read, _assert_private,
)


def request(number):
    return {"requestId": format(number, "032x"),
            "companyId": "a"*32, "workspaceId": "b"*32,
            "installationId": "c"*32,
            "requestedActor": "synthetic-madar-reader",
            "operation": "Counterparties.Get",
            "requestedGrant": "counterparties.read",
            "parameters": {"partyId": "qa-party-" + str(number)}}


def reply(number):
    return {"party": {"partyId": "qa-party-" + str(number),
                      "name": "Synthetic Test Party " + str(number),
                      "kind": "customer"}}


@unittest.skipUnless(os.name == "nt", "Real current-user Windows DPAPI required")
class TarazImmutableArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="taraz-sealed-archive-qa-")
        self.addCleanup(self.temp.cleanup)
        self.book = Path(self.temp.name) / "synthetic-book"
        self.book.mkdir()
        self.cache = _SealedReplyCache(self.book)

    def test_1009_distinct_immutable_replies_cross_lifetime_cap_and_restart(self):
        # Avoid 4,000 redundant whoami subprocesses while retaining the actual
        # Windows Win32 protected-DACL enforcement on every new directory/file.
        sid = _principal_sid()
        with patch("taraz_ecosystem_credentials._principal_sid",
                   return_value=sid):
            for n in range(1009):
                value = self.cache.get_or_create(request(n), lambda i=n: reply(i))
                self.assertEqual(value, reply(n))
                self.assertLessEqual(len(self.cache._hot), _MAX_HOT_RESULTS)
            archive_files = list(self.cache.archive.glob("*/*.dpapi"))
            self.assertEqual(len(archive_files), 1009)
            self.assertFalse(list(self.cache.root.glob("*.dpapi")))
            self.assertEqual(len(self.cache._hot), _MAX_HOT_RESULTS)
            self.assertEqual(len(set(p.name for p in archive_files)), 1009)
            self.assertEqual(len(list(self.cache.archive.iterdir())) <= 256, True)
            for n in (0, 1, 63, 64, 255, 999, 1008):
                original = self.cache._archive_file(format(n, "032x"))
                raw = original.read_bytes()
                self.assertNotIn(b"Synthetic Test Party", raw)
                self.assertNotIn(b"qa-party-", raw)
                self.assertGreater(len(raw), 48)
                before_hash = hashlib.sha256(raw).hexdigest()
                restarted = _SealedReplyCache(self.book)
                result = restarted.get_or_create(
                    request(n), lambda: self.fail(
                        "A replayed receipt must never reopen the company ledger"))
                self.assertEqual(result, reply(n))
                self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),
                                 before_hash)
            self.assertEqual(len(list(self.cache.archive.glob("*/*.dpapi"))), 1009)

    def test_duplicate_id_or_changed_envelope_fails_closed_after_restart(self):
        first = request(23)
        stored = reply(23)
        self.cache.get_or_create(first, lambda: stored)
        restarted = _SealedReplyCache(self.book)
        mutated = {**first, "parameters": {"partyId": "qa-party-24"}}
        with self.assertRaisesRegex(MailboxPeerDenied, "Corrupt or conflicting"):
            restarted.get_or_create(mutated, lambda: self.fail("No fresh ledger read"))
        with self.assertRaisesRegex(MailboxPeerDenied, "Corrupt or conflicting"):
            self.cache.get_or_create(mutated, lambda: self.fail("No fresh ledger read"))
        original = restarted.get_or_create(
            first, lambda: self.fail("Read-only immutable retry"))
        original["party"]["name"] = "Mutated in-memory value"
        self.assertEqual(self.cache.get_or_create(first, lambda: None), stored)

    def test_crash_between_stage_and_commit_recovers_without_reopening_ledger(self):
        envelope = request(9911)
        expected = reply(9911)
        with patch("taraz_ecosystem_mailbox_peer.os.rename",
                   side_effect=OSError("synthetic power-loss before publish")):
            with self.assertRaisesRegex(OSError, "synthetic power-loss"):
                self.cache.get_or_create(envelope, lambda: deepcopy(expected))
        target = self.cache._archive_file(envelope["requestId"])
        self.assertFalse(target.exists())
        staged = list(target.parent.glob(
            ".pending-" + envelope["requestId"] + ".*"))
        self.assertEqual(len(staged), 1)
        self.assertNotIn(b"Synthetic Test Party", staged[0].read_bytes())
        restart = _SealedReplyCache(self.book)
        returned = restart.get_or_create(
            envelope, lambda: self.fail(
                "A committed-but-unpublished encrypted stage must be replayed"))
        self.assertEqual(returned, expected)
        self.assertTrue(target.exists())
        self.assertFalse(staged[0].exists())
        self.assertEqual(restart.get_or_create(envelope, lambda: None), expected)

    def test_legacy_root_receipt_is_resealed_into_archive_without_any_deletion(self):
        req = request(321)
        answer = reply(321)
        self.cache.root.mkdir()
        _create_secure_file(self.cache.root / ".lock", b"0")
        legacy = self.cache.root / (req["requestId"] + ".dpapi")
        digest = hashlib.sha256(json.dumps(
            req, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        payload = json.dumps(
            {"envelopeSha256": digest, "reply": answer},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        _create_secure_file(legacy, _protect(payload, _seal_scope(legacy)))
        original_hash = hashlib.sha256(legacy.read_bytes()).hexdigest()
        migrated = self.cache.get_or_create(
            req, lambda: self.fail("Existing legacy cannot reread ledger"))
        self.assertEqual(migrated, answer)
        target = self.cache._archive_file(req["requestId"])
        self.assertTrue(target.is_file())
        self.assertTrue(legacy.is_file())
        self.assertNotEqual(target.read_bytes(), legacy.read_bytes(),
                            "Path-bound DPAPI encryption must change at archive")
        self.assertEqual(hashlib.sha256(legacy.read_bytes()).hexdigest(),
                         original_hash)
        self.assertEqual(_SealedReplyCache(self.book).get_or_create(
            req, lambda: self.fail("Durable archived replay only")), answer)

    def test_archive_corruption_or_tampered_stage_fails_closed_even_when_hot(self):
        envelope = request(800)
        self.cache.get_or_create(envelope, lambda: reply(800))
        file = self.cache._archive_file(envelope["requestId"])
        file.write_bytes(b"corrupt-archive-test")
        for cache in (self.cache, _SealedReplyCache(self.book)):
            with self.assertRaises(MailboxPeerDenied):
                cache.get_or_create(
                    envelope, lambda: self.fail("No re-read on corrupted record"))
        # A corrupted pre-publish stage likewise cannot be silently dropped.
        second = request(801)
        with patch("taraz_ecosystem_mailbox_peer.os.rename",
                   side_effect=OSError("synthetic interrupted rename")):
            with self.assertRaises(OSError):
                self.cache.get_or_create(second, lambda: reply(801))
        stage = next(self.cache._archive_file(second["requestId"]).parent.glob(
            ".pending-" + second["requestId"] + ".*"))
        stage.write_bytes(b"bad-stage")
        with self.assertRaises(MailboxPeerDenied):
            _SealedReplyCache(self.book).get_or_create(
                second, lambda: self.fail("Never refresh after corrupted stage"))

    def test_private_acl_is_reenforced_for_archived_file_and_parent_directories(self):
        envelope = request(450)
        self.cache.get_or_create(envelope, lambda: reply(450))
        target = self.cache._archive_file(envelope["requestId"])
        original_cipher = target.read_bytes()
        observed = (self.cache.root, self.cache.archive,
                    target.parent, target)
        for path in observed:
            _add_everyone_read(path)
        replay = _SealedReplyCache(self.book).get_or_create(
            envelope, lambda: self.fail("Never reread finance"))
        self.assertEqual(replay, reply(450))
        self.assertEqual(target.read_bytes(), original_cipher)
        for path in observed:
            _assert_private(self, path)

    def test_archive_symlink_hardlink_and_unexpected_file_fail_closed(self):
        envelope = request(245)
        self.cache.get_or_create(envelope, lambda: reply(245))
        target = self.cache._archive_file(envelope["requestId"])
        link = self.book / "external-synthetic-hardlink"
        try:
            os.link(target, link)
        except OSError:
            self.skipTest("Hardlink unavailable")
        with self.assertRaises((MailboxPeerDenied, PermissionError)):
            _SealedReplyCache(self.book).get_or_create(
                envelope, lambda: self.fail("Unsafe linked record"))
        link.unlink()
        unknown = self.cache.archive / "unexpected-data.txt"
        unknown.write_text("synthetic unrelated", encoding="utf-8")
        with self.assertRaises(MailboxPeerDenied):
            self.cache.get_or_create(
                envelope, lambda: self.fail("Unexpected archive member"))
        self.assertEqual(unknown.read_text(encoding="utf-8"), "synthetic unrelated")

    def test_archive_directory_symlink_refused_without_following_target(self):
        envelope = request(4455)
        self.cache.get_or_create(envelope, lambda: reply(4455))
        archive = self.cache.archive
        backing = self.book / "synthetic-archive-retained"
        archive.rename(backing)
        marker = backing / "test-marker.txt"
        marker.write_text("synthetic-original", encoding="utf-8")
        try:
            os.symlink(backing, archive, target_is_directory=True)
        except OSError:
            self.skipTest("Windows symlink privilege unavailable")
        with self.assertRaises(MailboxPeerDenied):
            _SealedReplyCache(self.book).get_or_create(
                envelope, lambda: self.fail("Must refuse reparse point"))
        self.assertEqual(marker.read_text(encoding="utf-8"), "synthetic-original")


if __name__ == "__main__":
    unittest.main()
