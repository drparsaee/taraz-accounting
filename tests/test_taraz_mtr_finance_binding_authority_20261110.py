"""Synthetic-only Madar HMAC + actual Taraz company journal authority tests.

Only TemporaryDirectory accounting company/bridge/metadata. Madar signing
implementation is loaded read-only, no real app profiles or finance commands.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch

from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_desktop import AccountingDesktopAPI
from standalone_accounting_identity import LocalCompanyIdentity
from taraz_desktop import TarazAPI
from taraz_mtr_peer_registry import PeerConfig, TarazPeerRegistry
from taraz_mtr_finance_binding_authority import (
    FinanceBindingDenied, ManualFinanceBindingAuthority,
)


MADAR_MODULE = Path(
    r"D:\CoS-Test\000- Madar\madar-p2-gantt-notifications-20261107"
) / "mtr_peer_envelope.py"


def _madar_envelope():
    if not MADAR_MODULE.is_file() or MADAR_MODULE.is_symlink():
        raise RuntimeError("real read-only Madar mtr_peer_envelope.py required")
    spec = importlib.util.spec_from_file_location("qa_madar_finance_binding_envelope", MADAR_MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PEER_ENVELOPE = _madar_envelope()


class FinanceBindingAuthorityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="mtr-finance-binding-synthetic-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.local = self.root / "local-appdata"
        self.local.mkdir()
        self.environ = patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)})
        self.environ.start()
        self.addCleanup(self.environ.stop)
        self.bridge = self.local / "Madar-Taraz-Bridge"
        (self.bridge / "pending").mkdir(parents=True)
        self.consumed = self.root / "operator-private-one-time"
        self.consumed.mkdir()

        hub = self.root / "registered-companies"
        hub.mkdir()
        self.company_registry = StandaloneCompanyRegistry(hub)
        self.company_id = self.company_registry.create_company("SYNTHETIC, NO REAL ACCOUNT")["id"]
        self.book = self.company_registry.company_data_directory(self.company_id)
        self.identity = LocalCompanyIdentity(self.book)
        self.identity.add_user("qaadmin", "test-only-password-1", role="admin")
        self.admin_token = self.identity.login("qaadmin", "test-only-password-1")
        self.identity.add_user("qaeditor", "test-only-password-2", role="editor",
                               administrator=self.admin_token)
        self.editor_token = self.identity.login("qaeditor", "test-only-password-2")
        self.host = AccountingDesktopAPI(
            self.book, company_workspace_id=self.company_id,
            authenticated_user=self.identity.require_session(self.editor_token),
            identity_store=self.identity, identity_token=self.editor_token)
        # The real Taraz desktop review method is tested under a manually
        # attached synthetic company session; constructor alone uses fallback.
        self.taraz = TarazAPI(self.book)
        self.taraz._identity_store = self.identity
        self.taraz._identity_token = self.editor_token
        self.taraz._actor = "qaeditor"
        self.taraz._accounts = self.identity.accounting_accounts()
        self.id = secrets.token_hex(16)
        self.invoice_id = "synthetic-invoice-qa"
        self.issue_id = "synthetic-issue-qa"
        self.journal_id = "J:" + self.issue_id
        self.task = "qa-task"
        self.project = "qa-project"
        proposal = {
            "schema": 1, "source": "madar", "id": self.id,
            "taskId": self.task, "projectId": self.project,
            "title": "Synthetic invoice request only",
            "createdUtc": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "amountRial": "1000",
        }
        (self.bridge / "pending" / (self.id + ".json")).write_text(
            json.dumps(proposal, ensure_ascii=False), encoding="utf8")
        review = self.taraz.tarazIntegrationReview(self.id, "reviewed")
        self.assertFalse(review["financialEventCreated"])
        self.source_file = self.bridge / "reviewed" / (self.id + ".json")
        self.source_digest = hashlib.sha256(self.source_file.read_bytes()).hexdigest()

        self.revision = 0
        self.date = datetime.now(timezone.utc).date().isoformat()
        self._cmd({"type": "party.register", "eventId": "party-qa", "partyId": "customer-qa",
                   "kind": "customer", "name": "Synthetic customer"})
        self._cmd({"type": "invoice.create", "eventId": "create-qa",
                   "invoiceId": self.invoice_id, "partyId": "customer-qa",
                   "documentDate": self.date, "sourceType": "madar", "sourceId": self.id,
                   "lines": [{"description": "Synthetic service", "quantity": 1,
                              "unitPrice": 1000}]})
        self._cmd({"type": "invoice.approve", "eventId": "approve-qa",
                   "invoiceId": self.invoice_id})
        self._cmd({"type": "invoice.issue", "eventId": self.issue_id,
                   "invoiceId": self.invoice_id, "postingDate": self.date})
        self.assertEqual(self.revision, 4)
        self.config = PeerConfig(
            organization_id="synthetic-org", madar_sender_id="synthetic-madar",
            madar_key_id="synthetic-madar-key", taraz_sender_id="synthetic-taraz",
            taraz_key_id="synthetic-taraz-key", madar_secret=secrets.token_bytes(48),
            taraz_secret=secrets.token_bytes(48))
        self.registry = TarazPeerRegistry(self.root / "peer.sqlite3", self.config)
        self.now = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=2)
        self.payload = {
            "id": self.id, "taskId": self.task, "projectId": self.project,
            "sourceDigest": self.source_digest, "companyId": self.company_id,
            "actorId": "qaeditor", "invoiceId": self.invoice_id,
            "issueEventId": self.issue_id, "journalId": self.journal_id,
        }
        self.original = self._original()
        self.registry.intake(self.original, now=self.now, verified_transport_peer=True)
        self.challenge_id = secrets.token_hex(16)
        self.query = self._query(self.original)
        self.registry.query_receipt(self.query, now=self.now,
                                    verified_transport_peer=True)
        self.authority = self._authority()

    def _cmd(self, event):
        posted = self.host.standaloneAccountingCommand({
            "command": event, "expectedRevision": self.revision})
        self.revision = posted["revision"]
        return posted

    def _original(self, *, payload=None):
        return PEER_ENVELOPE.sign_request(
            self.payload if payload is None else payload,
            organization_id=self.config.organization_id,
            sender_id=self.config.madar_sender_id,
            actor_role="editor", key_id=self.config.madar_key_id,
            request_id=self.id, purpose="finance_review_request",
            issued_at=self.now, expires_at=self.now + timedelta(seconds=120),
            secret=self.config.madar_secret, authorized=True,
            explicit_manual_action=True)

    def _query(self, original):
        verified = PEER_ENVELOPE.verify_request(
            original, secret=self.config.madar_secret, now=self.now,
            expected_organization_id=self.config.organization_id,
            expected_sender_id=self.config.madar_sender_id,
            expected_key_id=self.config.madar_key_id,
            purpose="finance_review_request",
            allowed_actor_roles=frozenset({"editor"}))
        return PEER_ENVELOPE.sign_receipt_query(
            verified, query_request_id=self.challenge_id,
            key_id=self.config.madar_key_id, issued_at=self.now,
            expires_at=self.now + timedelta(seconds=120),
            secret=self.config.madar_secret)

    def _authority(self, **changes):
        params = dict(accounting_host=self.host, peer_registry=self.registry,
                      trusted_config=self.config, reviewed_root=self.bridge,
                      consumed_bindings_dir=self.consumed)
        params.update(changes)
        return ManualFinanceBindingAuthority(**params)

    def bind(self, **changes):
        params = dict(signed_madar_original=self.original,
                      signed_madar_query_challenge=self.query,
                      madar_request_id=self.id, company_id=self.company_id,
                      invoice_id=self.invoice_id, issue_event_id=self.issue_id,
                      journal_id=self.journal_id, expected_revision=self.revision,
                      explicit_manual_action=True, now=self.now)
        params.update(changes)
        return self.authority.bind_preexisting_manual(**params)

    def assert_unclaimed(self):
        self.assertEqual(list(self.consumed.iterdir()), [])

    def test_preexisting_real_journal_binds_once_as_nonofficial_evidence_only(self):
        before = self.host.standaloneAccountingRead()["revision"]
        result = self.bind()
        self.assertEqual(result["decision"],
                         "SIGNED_BINDING_TO_EXISTING_JOURNAL_OBSERVED_NOT_OFFICIAL")
        self.assertTrue(result["madarHmacRequestAndQueryVerified"])
        self.assertTrue(result["persistedInvoiceJournalVerified"])
        self.assertTrue(result["oneTimeManualEvidenceConsumed"])
        self.assertEqual(result["sourceAmountRial"], 1000)
        for key in ("officialFinanceReceiptVerified", "trustedMadarInvoiceBindingVerified",
                    "independentlyAuthenticatedMadarActorVerified",
                    "signedTarazFinanceReceiptPresent", "safeToRetryFinancialPosting",
                    "financialEventCreatedByThisOperation"):
            self.assertFalse(result[key], key)
        self.assertEqual(self.host.standaloneAccountingRead()["revision"], before)
        self.assertEqual(len(list(self.consumed.iterdir())), 1)
        with self.assertRaisesRegex(FinanceBindingDenied, "consumed"):
            self.bind()
        with self.assertRaisesRegex(FinanceBindingDenied, "consumed"):
            self._authority().bind_preexisting_manual(
                signed_madar_original=self.original,
                signed_madar_query_challenge=self.query,
                madar_request_id=self.id, company_id=self.company_id,
                invoice_id=self.invoice_id, issue_event_id=self.issue_id,
                journal_id=self.journal_id, expected_revision=self.revision,
                explicit_manual_action=True, now=self.now)

    def test_manual_confirmation_required_and_no_claim(self):
        with self.assertRaisesRegex(FinanceBindingDenied, "manual|operator"):
            self.bind(explicit_manual_action=False)
        self.assert_unclaimed()

    def test_bad_hmac_and_actor_company_project_digest_are_denied(self):
        tampered = self.original.replace(b"synthetic-org", b"synthetic-org-spoof")
        with self.assertRaises(ValueError):
            self.bind(signed_madar_original=tampered)
        for change in ({"actorId": "another"}, {"companyId": "b" * 32},
                       {"projectId": "other-project"}, {"sourceDigest": "a" * 64},
                       {"issueEventId": "other-event"}):
            payload = {**self.payload, **change}
            with self.assertRaises((ValueError, PermissionError)):
                self.bind(signed_madar_original=self._original(payload=payload))
        self.assert_unclaimed()

    def test_unsigned_missing_specific_binding_cannot_upgrade_old_metadata_request(self):
        old = {key: self.payload[key] for key in (
            "id", "taskId", "projectId", "sourceDigest")}
        with self.assertRaisesRegex(FinanceBindingDenied, "specific"):
            self.bind(signed_madar_original=self._original(payload=old),
                      signed_madar_query_challenge=self._query(self._original(payload=old)))
        self.assert_unclaimed()

    def test_unreceived_original_or_unregistered_query_rejected(self):
        fresh = TarazPeerRegistry(self.root / "unreceived.sqlite3", self.config)
        denied = self._authority(peer_registry=fresh)
        with self.assertRaises(PermissionError):
            denied.bind_preexisting_manual(
                signed_madar_original=self.original,
                signed_madar_query_challenge=self.query,
                madar_request_id=self.id, company_id=self.company_id,
                invoice_id=self.invoice_id, issue_event_id=self.issue_id,
                journal_id=self.journal_id, expected_revision=self.revision,
                explicit_manual_action=True, now=self.now)
        self.assert_unclaimed()
        self.challenge_id = secrets.token_hex(16)
        not_received_query = self._query(self.original)
        with self.assertRaisesRegex(FinanceBindingDenied, "not recorded"):
            self.bind(signed_madar_query_challenge=not_received_query)
        self.assert_unclaimed()

    def test_role_revocation_company_substitution_and_fallback_denied(self):
        with self.assertRaises(PermissionError):
            self.bind(company_id="b" * 32)
        self.identity.logout(self.editor_token)
        with self.assertRaises(PermissionError):
            self.bind()
        self.assert_unclaimed()
        fallback = AccountingDesktopAPI(self.book, company_workspace_id=self.company_id)
        self.assertIs(type(fallback), AccountingDesktopAPI)
        with self.assertRaises(PermissionError):
            self._authority(accounting_host=fallback).bind_preexisting_manual(
                signed_madar_original=self.original,
                signed_madar_query_challenge=self.query,
                madar_request_id=self.id, company_id=self.company_id,
                invoice_id=self.invoice_id, issue_event_id=self.issue_id,
                journal_id=self.journal_id, expected_revision=self.revision,
                explicit_manual_action=True, now=self.now)
        self.assert_unclaimed()

    def test_wrong_session_role_or_exiting_company_denied(self):
        self.identity.change_role("qaeditor", "viewer", administrator=self.admin_token)
        with self.assertRaises(PermissionError):
            self.bind()
        self.assert_unclaimed()

    def test_stale_revision_and_reversed_invoice_cannot_be_bound(self):
        with self.assertRaisesRegex(FinanceBindingDenied, "STALE_REVISION"):
            self.bind(expected_revision=self.revision - 1)
        self.assert_unclaimed()
        self._cmd({"type": "journal.reverse", "eventId": "reverse-qa",
                   "journalId": self.journal_id, "postingDate": self.date,
                   "reason": "synthetic reversal"})
        with self.assertRaisesRegex(FinanceBindingDenied, "INVOICE_NOT_ISSUED|REVERSED"):
            self.bind()
        self.assert_unclaimed()

    def test_changed_source_is_denied(self):
        self.source_file.write_bytes(self.source_file.read_bytes() + b" ")
        with self.assertRaises((PermissionError, ValueError)):
            self.bind()
        self.assert_unclaimed()

    def test_symlinked_replay_directory_or_wrong_broker_config_denied(self):
        with self.assertRaises(PermissionError):
            self._authority(consumed_bindings_dir=self.bridge / "pending")
        with self.assertRaises(PermissionError):
            self._authority(trusted_config=PeerConfig(
                "synthetic-org", "synthetic-madar", "synthetic-madar-key",
                "synthetic-taraz", "synthetic-taraz-key",
                secrets.token_bytes(48), secrets.token_bytes(48)))
        linked = self.root / "linked-one-time"
        try:
            linked.symlink_to(self.consumed, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaises(PermissionError):
                self._authority(consumed_bindings_dir=linked)
        self.assert_unclaimed()


if __name__ == "__main__":
    unittest.main()
