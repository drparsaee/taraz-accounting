"""Actual synthetic registered-company Taraz issuer -> independent Madar verifier.

All accounts, invoice.issue commands and keys are disposable. The Taraz issuer
is source-only; even a valid independent Madar verifier result is NOT an
official finance receipt or a production installation.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch

MADAR_ROOT = Path(r"D:\CoS-Test\000- Madar\madar-p2-gantt-notifications-20261107")
if not (MADAR_ROOT / "mtr_peer_envelope.py").is_file():
    raise RuntimeError("independent current Madar HMAC module unavailable")
if not (MADAR_ROOT / "mtr_taraz_finance_witness_verifier.py").is_file():
    raise RuntimeError("independent current Madar witness verifier unavailable")
sys.path.insert(0, str(MADAR_ROOT))

from mtr_peer_envelope import (  # noqa: E402
    sign_request, sign_receipt_query, verify_request,
)
from mtr_taraz_finance_witness_verifier import (  # noqa: E402
    DurableFinanceWitnessChallenges, FinanceWitnessTrust,
    TarazFinanceWitnessVerifier, FinanceWitnessRejected,
)
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_desktop import AccountingDesktopAPI
from standalone_accounting_identity import LocalCompanyIdentity
from taraz_desktop import TarazAPI
from taraz_mtr_peer_registry import PeerConfig, TarazPeerRegistry
from taraz_mtr_external_actor_link import ManualExternalActorLinks
from taraz_mtr_finance_witness_issuer import (
    DurableFinanceWitnessIssuance, FinanceIssuerTrust,
    FinanceWitnessIssueDenied, ManualTarazFinanceWitnessIssuer,
    _read_accounting,
)
from taraz_mtr_official_receipt_gate import _principal, _safe_company


class TarazFinanceWitnessIssuerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="taraz-finance-witness-synthetic-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.local = self.root / "local-appdata"
        self.local.mkdir()
        env = patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)})
        env.start()
        self.addCleanup(env.stop)
        self.bridge = self.local / "Madar-Taraz-Bridge"
        (self.bridge / "pending").mkdir(parents=True)
        self.link_dir = self.root / "private-actor-links"
        self.link_dir.mkdir()
        self.issued_dir = self.root / "private-witness-issuance"
        self.issued_dir.mkdir()
        self.company_root = self.root / "registered-companies"
        self.company_root.mkdir()
        self.companies = StandaloneCompanyRegistry(self.company_root)
        self.company_id = self.companies.create_company("QA DISPOSABLE")["id"]
        self.book = self.companies.company_data_directory(self.company_id)
        self.identity = LocalCompanyIdentity(self.book)
        self.identity.add_user("qaadmin", "test-admin-password", role="admin")
        self.admin_token = self.identity.login("qaadmin", "test-admin-password")
        self.identity.add_user(
            "qaeditor", "test-editor-password", role="editor",
            administrator=self.admin_token)
        self.editor_token = self.identity.login(
            "qaeditor", "test-editor-password")
        self.host = AccountingDesktopAPI(
            self.book, company_workspace_id=self.company_id,
            authenticated_user=self.identity.require_session(self.editor_token),
            identity_store=self.identity, identity_token=self.editor_token)
        self.taraz = TarazAPI(self.book)
        self.taraz._identity_store = self.identity
        self.taraz._identity_token = self.editor_token
        self.taraz._actor = "qaeditor"
        self.taraz._accounts = self.identity.accounting_accounts()
        self.req = secrets.token_hex(16)
        self.challenge_id = secrets.token_hex(16)
        self.actor = "mtr-actor-v1-" + secrets.token_hex(32)
        self.invoice = "qa-witness-invoice"
        self.issue = "qa-witness-issue"
        self.journal = "J:" + self.issue
        self.task = "qa-witness-task"
        self.project = "qa-witness-project"
        self.amount = "1500"
        self.now = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=2)
        self.source = {
            "schema": 1, "source": "madar", "id": self.req,
            "taskId": self.task, "projectId": self.project,
            "title": "QA synthetic source",
            "createdUtc": (self.now - timedelta(minutes=1)).isoformat(),
            "expenseId": "synthetic-expense-1", "amountRial": self.amount,
        }
        self.source_raw = json.dumps(
            self.source, ensure_ascii=False, separators=(",", ":")).encode("utf8")
        (self.bridge / "pending" / (self.req + ".json")).write_bytes(self.source_raw)
        self.assertFalse(self.taraz.tarazIntegrationReview(
            self.req, "reviewed")["financialEventCreated"])
        self.source_file = self.bridge / "reviewed" / (self.req + ".json")
        self.assertEqual(self.source_file.read_bytes(), self.source_raw)
        self.revision = 0
        self.day = self.now.date().isoformat()
        self._cmd({
            "type": "party.register", "eventId": "qa-party",
            "partyId": "qa-customer", "kind": "customer",
            "name": "QA Synthetic Customer",
        })
        self._cmd({
            "type": "invoice.create", "eventId": "qa-create",
            "invoiceId": self.invoice, "partyId": "qa-customer",
            "documentDate": self.day, "sourceType": "madar",
            "sourceId": self.req, "lines": [{
                "description": "QA service", "quantity": 1, "unitPrice": 1500}],
        })
        self._cmd({
            "type": "invoice.approve", "eventId": "qa-approve",
            "invoiceId": self.invoice,
        })
        self._cmd({
            "type": "invoice.issue", "eventId": self.issue,
            "invoiceId": self.invoice, "postingDate": self.day,
        })
        self.assertEqual(self.revision, 4)
        self.peer = PeerConfig(
            organization_id="qa-witness-org", madar_sender_id="qa-madar",
            madar_key_id="qa-madar-key", taraz_sender_id="qa-taraz",
            taraz_key_id="qa-taraz-peer-key",
            madar_secret=secrets.token_bytes(48),
            taraz_secret=secrets.token_bytes(48),
        )
        self.registry = TarazPeerRegistry(self.root / "peer.sqlite3", self.peer)
        self.original_payload = {
            "id": self.req, "taskId": self.task, "projectId": self.project,
            "sourceDigest": hashlib.sha256(self.source_raw).hexdigest(),
            "companyId": self.company_id, "actorId": self.actor,
            "invoiceId": self.invoice, "issueEventId": self.issue,
            "journalId": self.journal,
        }
        self.original = self._original()
        self.registry.intake(self.original, now=self.now, verified_transport_peer=True)
        verified = verify_request(
            self.original, secret=self.peer.madar_secret, now=self.now,
            expected_organization_id=self.peer.organization_id,
            expected_sender_id=self.peer.madar_sender_id,
            expected_key_id=self.peer.madar_key_id,
            purpose="finance_review_request",
            allowed_actor_roles=frozenset({"editor"}),
        )
        self.query = sign_receipt_query(
            verified, query_request_id=self.challenge_id,
            key_id=self.peer.madar_key_id, issued_at=self.now,
            expires_at=self.now + timedelta(seconds=120),
            secret=self.peer.madar_secret,
        )
        self.registry.query_receipt(
            self.query, now=self.now, verified_transport_peer=True)
        self.links = ManualExternalActorLinks(
            accounting_host=self.host, peer_registry=self.registry,
            trusted_config=self.peer, reviewed_root=self.bridge,
            link_db_path=self.link_dir / "external-actor-links.sqlite3",
        )
        self.finance_key = secrets.token_bytes(48)
        self.finance_trust = FinanceIssuerTrust(
            organization_id=self.peer.organization_id,
            finance_issuer_id="qa-taraz-issuer",
            finance_key_id="qa-finance-only-key",
            finance_secret=self.finance_key,
        )
        self.issued_path = (
            self.issued_dir / "mtr-taraz-finance-witness-issued.sqlite3")
        self.issuer = self._make_issuer()

    def _cmd(self, cmd):
        result = self.host.standaloneAccountingCommand({
            "command": cmd, "expectedRevision": self.revision})
        self.revision = result["revision"]
        return result

    def _original(self, *, payload=None, key=None):
        return sign_request(
            self.original_payload if payload is None else payload,
            organization_id=self.peer.organization_id,
            sender_id=self.peer.madar_sender_id, actor_role="editor",
            key_id=self.peer.madar_key_id, request_id=self.req,
            purpose="finance_review_request", issued_at=self.now,
            expires_at=self.now + timedelta(seconds=120),
            secret=self.peer.madar_secret if key is None else key,
            authorized=True, explicit_manual_action=True,
        )

    def _make_issuer(self, **changes):
        options = {
            "accounting_host": self.host, "peer_registry": self.registry,
            "trusted_config": self.peer, "finance_trust": self.finance_trust,
            "external_actor_links": self.links, "reviewed_root": self.bridge,
            "issued_db_path": self.issued_path,
        }
        options.update(changes)
        return ManualTarazFinanceWitnessIssuer(**options)

    def grant(self):
        return self.links.authorize_manual(
            signed_madar_original=self.original,
            signed_madar_query_challenge=self.query,
            company_id=self.company_id, administrator_token=self.admin_token,
            explicit_manual_action=True, now=self.now)

    def issue_witness(self, **changes):
        options = {
            "signed_madar_original": self.original,
            "signed_madar_query_challenge": self.query,
            "company_id": self.company_id,
            "administrator_token": self.admin_token,
            "expected_revision": self.revision,
            "explicit_manual_action": True, "now": self.now,
        }
        options.update(changes)
        return self.issuer.issue_manual(**options)

    def _madar_verify(self, witness):
        config = FinanceWitnessTrust(
            organization_id=self.peer.organization_id,
            madar_sender_id=self.peer.madar_sender_id,
            madar_key_id=self.peer.madar_key_id,
            madar_secret=self.peer.madar_secret,
            taraz_finance_issuer_id=self.finance_trust.finance_issuer_id,
            taraz_finance_key_id=self.finance_trust.finance_key_id,
            taraz_finance_secret=self.finance_key)
        proof_store_path = (
            self.root / "mtr-taraz-finance-witness-queries.sqlite3")
        proof_store = DurableFinanceWitnessChallenges(proof_store_path)
        proof_store.register_manual(
            original_wire=self.original, query_wire=self.query,
            source_raw=witness.source_raw, config=config,
            explicit_manual_action=True, now=self.now)
        return TarazFinanceWitnessVerifier(
            config=config, challenges=proof_store).inspect_and_consume(
                signed_witness=witness.signed_witness,
                original_wire=witness.original_wire,
                query_wire=witness.query_wire,
                source_raw=witness.source_raw,
                journal_raw=witness.journal_raw,
                accounting_event_raw=witness.accounting_event_raw,
                ledger_revision=witness.ledger_revision,
                ledger_state_sha256=witness.ledger_state_sha256,
                now=self.now)

    def test_real_disposable_journal_cross_source_madar_verifier(self):
        self.grant()
        before = self.host.standaloneAccountingRead()["revision"]
        result = self.issue_witness()
        self.assertFalse(result.officialFinanceReceiptVerified)
        self.assertFalse(result.financialEventCreatedByIssuer)
        self.assertFalse(result.safeToRetryFinancialPosting)
        self.assertEqual(result.ledger_revision, before)
        self.assertEqual(self.host.standaloneAccountingRead()["revision"], before)
        observed = self._madar_verify(result)
        self.assertEqual(
            observed.decision,
            "SIGNED_WITNESS_STRUCTURALLY_VERIFIED_OFFICIAL_ISSUER_UNAVAILABLE")
        self.assertTrue(observed.signedFinanceWitnessCryptographyVerified)
        self.assertTrue(observed.signedJournalEventBound)
        self.assertTrue(observed.oneTimeDurableChallengeConsumed)
        self.assertFalse(observed.officialFinanceReceiptVerified)
        self.assertFalse(observed.realTarazIssuerAuthenticated)
        self.assertFalse(observed.independentLiveLedgerReadbackVerified)

    def test_admin_admission_required_no_unsigned_local_alias(self):
        with self.assertRaises((FinanceWitnessIssueDenied, PermissionError)):
            self.issue_witness()
        with self.assertRaises(FinanceWitnessIssueDenied):
            self.issue_witness(explicit_manual_action=False)
        self.grant()
        with self.assertRaises(PermissionError):
            self.issue_witness(administrator_token=self.editor_token)

    def test_wrong_signed_source_and_financial_amount_denied(self):
        self.grant()
        with self.assertRaises((PermissionError, ValueError)):
            self.issue_witness(
                signed_madar_original=self._original(
                    payload={**self.original_payload, "sourceDigest": "f" * 64}))
        self.source_file.write_bytes(
            self.source_file.read_bytes().replace(b"1500", b"1501"))
        with self.assertRaises((PermissionError, ValueError)):
            self.issue_witness()

    def test_actual_ledger_amount_is_independently_compared_to_signed_amount(self):
        identity = _safe_company(self.host, self.company_id)
        accounts = _principal(self.host, identity)
        with self.assertRaisesRegex(FinanceWitnessIssueDenied, "amount"):
            _read_accounting(
                self.host, accounts, self.original_payload,
                amount=1501, expected_revision=self.revision)
        self.assertEqual(self.host.standaloneAccountingRead()["revision"], 4)

    def test_revoked_operator_or_admin_role_and_wrong_company_denied(self):
        self.grant()
        with self.assertRaises(PermissionError):
            self.issue_witness(company_id=secrets.token_hex(16))
        self.identity.change_role(
            "qaeditor", "viewer", administrator=self.admin_token)
        with self.assertRaises(PermissionError):
            self.issue_witness()

    def test_revoked_admin_session_denied(self):
        self.grant()
        self.identity.logout(self.admin_token)
        with self.assertRaises(PermissionError):
            self.issue_witness()

    def test_journal_reversal_and_stale_revision_denied(self):
        self.grant()
        with self.assertRaises((PermissionError, ValueError)):
            self.issue_witness(expected_revision=self.revision - 1)
        self._cmd({
            "type": "journal.reverse", "eventId": "qa-reverse",
            "journalId": self.journal, "postingDate": self.day,
            "reason": "synthetic reversal",
        })
        with self.assertRaises((PermissionError, ValueError)):
            self.issue_witness()

    def test_separate_key_no_replay_after_process_reopen(self):
        self.grant()
        first = self.issue_witness()
        self.assertEqual(first.ledger_revision, 4)
        self.assertNotIn(b"officialFinanceReceiptVerified", first.signed_witness)
        reopened = self._make_issuer()
        with self.assertRaises((FinanceWitnessIssueDenied, PermissionError)):
            reopened.issue_manual(
                signed_madar_original=self.original,
                signed_madar_query_challenge=self.query,
                company_id=self.company_id,
                administrator_token=self.admin_token,
                expected_revision=self.revision,
                explicit_manual_action=True, now=self.now)
        with self.assertRaises(PermissionError):
            self.grant()

    def test_cross_source_wrong_finance_key_fails_madar_verifier(self):
        self.grant()
        self.finance_key = secrets.token_bytes(48)
        first = self.issue_witness()
        with self.assertRaises((FinanceWitnessRejected, PermissionError)):
            self._madar_verify(first)

    def test_ambiguous_crash_before_link_consumption_burns_challenge(self):
        self.grant()
        with patch.object(self.links, "consume_manual",
                          side_effect=RuntimeError("synthetic interruption")):
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                self.issue_witness()
        self.assertTrue(self.links.verify_pending(
            signed_madar_original=self.original,
            signed_madar_query_challenge=self.query,
            company_id=self.company_id, administrator_token=self.admin_token,
            now=self.now))
        with self.assertRaises(FinanceWitnessIssueDenied):
            self.issue_witness()

    def test_provisioning_refuses_same_peer_secret_and_linked_db(self):
        with self.assertRaises(FinanceWitnessIssueDenied):
            self._make_issuer(finance_trust=replace(
                self.finance_trust, finance_secret=self.peer.madar_secret))
        with self.assertRaises(FinanceWitnessIssueDenied):
            self._make_issuer(finance_trust=replace(
                self.finance_trust, finance_secret=b"short"))
        with self.assertRaises(TypeError):
            __import__("pickle").dumps(self.finance_trust)
        linked = self.root / "linked-issuer"
        try:
            linked.symlink_to(self.issued_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass
        else:
            with self.assertRaises(FinanceWitnessIssueDenied):
                DurableFinanceWitnessIssuance(
                    linked / "mtr-taraz-finance-witness-issued.sqlite3")


if __name__ == "__main__":
    unittest.main()
