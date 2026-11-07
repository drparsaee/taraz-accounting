"""Isolated contract tests for opt-in-gated metadata-only local bridge status."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
import uuid

from taraz_link_status import inspect_local_link_status
from taraz_integration import list_requests, review_request


class LinkStatusTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="taraz-link-status-qa-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "Madar-Taraz-Bridge"

    def status(self, app="madar", opted_in=True):
        return inspect_local_link_status(self.root, app=app, opted_in=opted_in)

    def test_opted_out_does_not_create_or_inspect_inbox(self):
        result = self.status(opted_in=False)
        self.assertEqual(result["state"], "disabled")
        self.assertFalse(result["optedIn"])
        self.assertFalse(result["localInboxPresent"])
        self.assertEqual(result["pendingCandidates"], 0)
        self.assertFalse(self.root.exists())
        # Disabled mode must not even require a filesystem path argument.
        result = inspect_local_link_status(None, app="taraz", opted_in=False)
        self.assertEqual(result["state"], "disabled")

    def test_status_never_claims_peer_identity_or_financial_posting(self):
        self.assertEqual(self.status()["state"], "not-created")
        self.assertFalse(self.root.exists())
        inbox = self.root / "pending"
        inbox.mkdir(parents=True)
        result = self.status(app="taraz")
        self.assertEqual(result["state"], "empty")
        self.assertTrue(result["localInboxPresent"])
        self.assertFalse(result["peerVerified"])
        self.assertFalse(result["postingEnabled"])
        self.assertTrue(result["readOnly"])
        self.assertFalse(result["candidateContentValidated"])

    def test_counts_only_plausible_names_and_sizes_without_parsing_payload(self):
        inbox = self.root / "pending"
        inbox.mkdir(parents=True)
        # Invalid JSON is intentionally only a *candidate*. Parsing belongs
        # to taraz_integration._safe_record after authenticated opt-in.
        source = inbox / ("a" * 32 + ".json")
        source.write_text("{not-valid-json", encoding="utf8")
        (inbox / "malformed.json").write_text("{}", encoding="utf8")
        (inbox / ("b" * 32 + ".json")).write_bytes(b"x" * 32769)
        (inbox / ("c" * 32 + ".tmp")).write_text("inflight", encoding="utf8")
        expected = source.read_bytes()
        result = self.status()
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["pendingCandidates"], 1)
        self.assertEqual(result["invalidEntries"], 2)
        self.assertFalse(result["scanTruncated"])
        self.assertFalse(result["candidateContentValidated"])
        self.assertEqual(source.read_bytes(), expected)

    def test_bounded_scan_reports_incomplete_count(self):
        inbox = self.root / "pending"
        inbox.mkdir(parents=True)
        for index in range(250):
            (inbox / (f"{index:032x}.json")).write_bytes(b"{}")
        result = self.status()
        self.assertTrue(result["scanTruncated"])
        self.assertEqual(result["pendingCandidates"], 100)
        self.assertEqual(result["state"], "pending")
        self.assertEqual(len(list(inbox.iterdir())), 250)

    def test_strict_app_and_consent_values(self):
        with self.assertRaises(ValueError):
            self.status(app="untrusted")
        for value in (1, "yes", None):
            with self.subTest(value=value), self.assertRaises(TypeError):
                inspect_local_link_status(self.root, app="madar", opted_in=value)

    def test_existing_authenticated_inbox_review_contract_unchanged(self):
        inbox = self.root / "pending"
        inbox.mkdir(parents=True)
        ident = uuid.uuid4().hex
        (inbox / (ident + ".json")).write_text(
            '{"schema":1,"source":"madar","id":"' + ident +
            '","taskId":"task-x","title":"Explicit proposal",'
            '"projectId":"project-x","createdUtc":"2026-11-07T08:00:00Z"}',
            encoding="utf8",
        )
        self.assertEqual(self.status(app="taraz", opted_in=False)["pendingCandidates"], 0)
        self.assertEqual(self.status(app="taraz")["pendingCandidates"], 1)
        current = list_requests(self.root)
        self.assertEqual(len(current["requests"]), 1)
        receipt = review_request(self.root, ident, "reviewed")
        self.assertFalse(receipt["financialEventCreated"])
        self.assertEqual(list_requests(self.root)["requests"], [])
        self.assertEqual(self.status(app="taraz")["pendingCandidates"], 0)

    def test_refuses_symlinked_inbox(self):
        with tempfile.TemporaryDirectory(prefix="taraz-link-other-qa-") as other:
            self.root.mkdir()
            try:
                (self.root / "pending").symlink_to(Path(other), target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest("Windows symlink privilege unavailable: " + str(error))
            result = self.status(app="taraz")
            self.assertEqual(result["state"], "unavailable")
            self.assertEqual(result["pendingCandidates"], 0)
            self.assertFalse(result["localInboxPresent"])

    def test_refuses_symlinked_file(self):
        inbox = self.root / "pending"
        inbox.mkdir(parents=True)
        real = self.root / "private.txt"
        real.write_text("private")
        try:
            (inbox / ("d" * 32 + ".json")).symlink_to(real)
        except (OSError, NotImplementedError) as error:
            self.skipTest("Windows symlink privilege unavailable: " + str(error))
        result = self.status()
        self.assertEqual(result["pendingCandidates"], 0)
        self.assertEqual(result["invalidEntries"], 1)
        self.assertEqual(result["state"], "needs-review")


if __name__ == "__main__":
    unittest.main()
