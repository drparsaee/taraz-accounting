"""Headless, fake-transport QA of the real native-consent boundary.

The affirmative callback in these tests is a Python-only STUB of an OS dialog;
it is not a claim that a human clicked a Frozen WebView2 dialog. No LAN host,
browser, production ledger, installer or external provider is contacted.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from taraz_ecosystem_client import MadarPinnedClient, EcosystemConnectionError
from taraz_ecosystem_credentials import TarazEcosystemCredentialVault
from taraz_ecosystem_mailbox_consent import (
    NativeMailboxBatchConsent, NativeMailboxConsentDenied,
)
from taraz_ecosystem_mailbox_peer import TarazMailboxPeer, _SealedReplyCache


COMPANY = "a" * 32
WORKSPACE = "b" * 32
REQUEST = "c" * 32
PIN = "d" * 64


def sample_envelope(installation, *, request_id=REQUEST):
    return {
        "workspaceId": WORKSPACE, "companyId": COMPANY,
        "installationId": installation, "requestId": request_id,
        "requestedActor": "madar-qa-reader",
        "requestedGrant": "counterparties.read",
        "operation": "Counterparties.Search",
        "parameters": {"query": "مشتری آزمون", "kind": "customer",
                       "limit": 5, "cursor": None},
    }


class FakeMailboxTransport:
    def __init__(self, requests):
        self.requests = deepcopy(requests)
        self.paths = []
        self.replies = []
        self.fail_reply = False

    def call(self, method, path, *, payload=None, token=None):
        self.paths.append(path)
        if path.endswith("/mailbox/poll"):
            return 200, {"version": 1, "requests": deepcopy(self.requests)}
        if path.endswith("/mailbox/reply"):
            if self.fail_reply:
                raise EcosystemConnectionError("synthetic lost ACK")
            self.replies.append(deepcopy(payload))
            return 200, {"version": 1, "requestId": payload["requestId"],
                         "status": "completed"}
        raise AssertionError("Fake transport must not access other endpoints")


class NativeMailboxConsentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="taraz-mailbox-consent-qa-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        vault_root = self.root / "synthetic-vault"
        vault_root.mkdir()
        self.vault = TarazEcosystemCredentialVault(vault_root)
        self.installation = self.vault.initialize()
        self.vault.pair(workspace_id=WORKSPACE, peer_id="MADAR", cert_sha256=PIN)
        self.client = MadarPinnedClient(
            self.vault, endpoint="https://127.0.0.1:48888", cert_sha256=PIN)
        self.book = self.root / "synthetic-company-book"
        self.book.mkdir()
        self.envelope = sample_envelope(self.installation)
        self.transport = FakeMailboxTransport([self.envelope])
        self.client._request = self.transport.call
        self.authorized = True
        self.guard = lambda: self.authorized
        self.consent = NativeMailboxBatchConsent(
            None, actor="qa-local-admin", company_id=COMPANY,
            workspace_id=WORKSPACE, installation_id=self.installation,
            session_verified=self.guard)
        self.peer = TarazMailboxPeer(
            self.client, workspace_id=WORKSPACE, company_id=COMPANY,
            company_book=self.book,
            authorizer=lambda **kw: self.authorized,
            native_consent=self.consent)

    def _result(self, envelope):
        self.assertEqual(envelope, self.envelope)
        return {"parties": [{"partyId": "qa-1", "name": "مشتری آزمون",
                             "kind": "customer"}],
                "hasMore": False, "nextCursor": None}

    def test_browser_boolean_or_headless_process_cannot_reply_or_read(self):
        # A Python HTTP peer alone does NOT turn renderer manualConsent into
        # an operator approval: this native window is intentionally absent.
        with patch.object(self.peer, "_result", side_effect=AssertionError(
                "No ledger read without a native dialog")):
            with self.assertRaises(NativeMailboxConsentDenied):
                self.peer.run_once(limit=5)
        self.assertEqual(self.transport.replies, [])
        self.assertFalse(self.peer.cache.root.exists())

    def test_cancel_non_boolean_approval_and_dialog_exception_are_all_denied(self):
        for result in (False, None, 1, RuntimeError("no desktop")):
            with self.subTest(result=str(result)):
                with patch.object(
                        self.consent, "_native_prompt",
                        side_effect=result if isinstance(result, Exception) else None,
                        return_value=None if isinstance(result, Exception) else result):
                    with self.assertRaises(NativeMailboxConsentDenied):
                        self.peer.run_once()
        self.assertEqual(self.transport.replies, [])
        self.assertFalse(self.peer.cache.root.exists())

    def test_exact_preview_shown_before_read_and_one_valid_reply(self):
        observed = []
        def approved(title, body):
            observed.append((title, body))
            self.assertIn(REQUEST, body)
            self.assertIn(WORKSPACE, body)
            self.assertIn(COMPANY, body)
            self.assertIn(self.installation, body)
            self.assertIn("qa-local-admin", body)
            self.assertIn("madar-qa-reader", body)
            self.assertIn("Counterparties.Search", body)
            self.assertIn("مشتری آزمون", body)
            self.assertEqual(self.transport.replies, [])
            return True
        with patch.object(self.consent, "_native_prompt", side_effect=approved):
            with patch.object(self.peer, "_result", side_effect=self._result) as read:
                outcome = self.peer.run_once()
                read.assert_called_once()
        self.assertEqual(outcome["completed"], 1)
        self.assertEqual(len(observed), 1)
        self.assertEqual(len(self.transport.replies), 1)
        self.assertEqual(set(self.transport.replies[0]["result"]["parties"][0]),
                         {"partyId", "name", "kind"})

    def test_identical_replay_after_lost_ack_requires_new_native_consent(self):
        self.transport.fail_reply = True
        with patch.object(self.consent, "_native_prompt", return_value=True):
            with patch.object(self.peer, "_result", side_effect=self._result) as read:
                with self.assertRaises(EcosystemConnectionError):
                    self.peer.run_once()
                read.assert_called_once()
        self.transport.fail_reply = False
        # Simulate process restart: no decrypted process-local hot entries.
        # Only the archived DPAPI snapshot may satisfy the lost-ACK replay.
        self.peer.cache = _SealedReplyCache(self.book)
        with patch.object(self.peer, "_result", side_effect=AssertionError(
                "Replayed request must reuse sealed immutable DPAPI response")):
            with self.assertRaises(NativeMailboxConsentDenied):
                self.peer.run_once()
            with patch.object(self.consent, "_native_prompt", return_value=True):
                self.assertEqual(self.peer.run_once()["completed"], 1)
        self.assertEqual(len(self.transport.replies), 1)

    def test_foreign_company_duplicate_and_malformed_late_envelope_fail_before_dialog(self):
        for second in (
                sample_envelope(self.installation, request_id=REQUEST),
                {**sample_envelope(self.installation, request_id="e"*32),
                 "companyId": "f"*32},
                {**sample_envelope(self.installation, request_id="e"*32),
                 "requestedGrant": "finances.write"}):
            with self.subTest(second=str(second)[:80]):
                self.transport.requests = [self.envelope, second]
                with patch.object(self.consent, "_native_prompt",
                                  side_effect=AssertionError("No prompt")):
                    with self.assertRaises((NativeMailboxConsentDenied,
                                            PermissionError)):
                        self.peer.run_once()
        self.assertEqual(self.transport.replies, [])
        self.assertFalse(self.peer.cache.root.exists())

    def test_live_admin_revocation_during_dialog_denies_outbound_replies(self):
        def revoke(*_):
            self.authorized = False
            return True
        with patch.object(self.consent, "_native_prompt", side_effect=revoke):
            with self.assertRaises(NativeMailboxConsentDenied):
                self.peer.run_once()
        self.assertEqual(self.transport.replies, [])
        self.assertFalse(self.peer.cache.root.exists())

    def test_ticket_one_use_exact_request_hash_company_and_expiry(self):
        scope = dict(self.consent.scope)
        with patch.object(self.consent, "_native_prompt", return_value=True):
            ticket = self.consent.approve([self.envelope], scope=scope)
        other = {**self.envelope, "parameters":
                 {**self.envelope["parameters"], "query": "تغییرکرده"}}
        with self.assertRaises(NativeMailboxConsentDenied):
            ticket.check(other, scope=scope, consume=True)
        with self.assertRaises(NativeMailboxConsentDenied):
            ticket.check(self.envelope,
                         scope={**scope, "companyId": "0"*32}, consume=True)
        ticket.check(self.envelope, scope=scope, consume=True)
        ticket.check(self.envelope, scope=scope)
        with self.assertRaises(NativeMailboxConsentDenied):
            ticket.check(self.envelope, scope=scope, consume=True)
        ticket._expiry = ticket._now() - 1
        with self.assertRaises(NativeMailboxConsentDenied):
            ticket.check(self.envelope, scope=scope)
        self.authorized = False
        with self.assertRaises(NativeMailboxConsentDenied):
            ticket.check(self.envelope, scope=scope)

    def test_oversized_or_bidi_spoofed_preview_denies_before_native_prompt(self):
        for envelope in (
                {**self.envelope, "requestedActor": "qa\u202eother"},
                {**self.envelope, "parameters": {"query": "x"*6000}}):
            with self.subTest(envelope=str(envelope)[:60]):
                with patch.object(self.consent, "_native_prompt",
                                  side_effect=AssertionError("No prompt")):
                    with self.assertRaises(NativeMailboxConsentDenied):
                        self.consent.approve([envelope], scope=self.consent.scope)

    def test_empty_queue_makes_no_dialog_no_reply(self):
        self.transport.requests = []
        with patch.object(self.consent, "_native_prompt",
                          side_effect=AssertionError("No prompt for empty queue")):
            outcome = self.peer.run_once()
        self.assertEqual(outcome["received"], 0)
        self.assertEqual(self.transport.replies, [])


if __name__ == "__main__":
    unittest.main()
