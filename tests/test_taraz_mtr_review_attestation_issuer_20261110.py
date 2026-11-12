"""Real TarazAPI editor auth + durable synthetic metadata + Madar HMAC vectors.

No real users, installed EXEs, finance ledger, service or network. Read-only
imports of the current Madar proof verifier/signature maker are cross-checks.
"""
from concurrent.futures import ThreadPoolExecutor
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

from standalone_accounting_identity import LocalCompanyIdentity
from taraz_desktop import TarazAPI
from taraz_mtr_peer_registry import PeerConfig, TarazPeerRegistry
from taraz_integration import review_request
from taraz_mtr_review_attestation_issuer import (
    ManualReviewAttestationIssuer, ReviewAttestationDenied,
)

MADAR = Path(r"D:\CoS-Test\000- Madar\madar-p2-gantt-notifications-20261107")


def madar_module(name: str):
    source = MADAR / (name + ".py")
    if not source.is_file() or source.is_symlink():
        raise RuntimeError("Read-only original Madar signing module required")
    spec = importlib.util.spec_from_file_location("qa_readonly_" + name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PEER_ENVELOPE = madar_module("mtr_peer_envelope")
PEER_IDENTITY = madar_module("mtr_taraz_peer_identity")


class VerifiedSyntheticTarazIssuerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="taraz-mtr-review-issuer-qa-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.local = self.root / "Local"
        self.local.mkdir()
        self.bridge = self.local / "Madar-Taraz-Bridge"
        (self.bridge / "pending").mkdir(parents=True)
        self.replay = self.root / "operator-provisioned-replay"
        self.replay.mkdir()
        self.data = self.root / "Taraz-data"
        self.data.mkdir()
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.ident = LocalCompanyIdentity(self.data)
        self.ident.add_user("qaadmin", "Synthetic-Admin-Only!", role="admin")
        self.admin = self.ident.login("qaadmin", "Synthetic-Admin-Only!")
        self.ident.add_user(
            "qaeditor", "Synthetic-Editor-Only!", role="editor",
            administrator=self.admin)
        self.token = self.ident.login("qaeditor", "Synthetic-Editor-Only!")
        self.api = TarazAPI(self.data)
        # Source TarazAPI defaults to local admin; this disposable fixture
        # explicitly attaches a real authenticated LocalCompanyIdentity
        # session. The issuer MUST reject default local fallback.
        self.api._identity_store = self.ident
        self.api._identity_token = self.token
        self.api._actor = "qaeditor"
        self.api._accounts = self.ident.accounting_accounts()
        self.config = PeerConfig(
            organization_id="qa-organization",
            madar_sender_id="qa-madar-host",
            madar_key_id="qa-madar-key",
            taraz_sender_id="qa-taraz-host",
            taraz_key_id="qa-taraz-key",
            madar_secret=secrets.token_bytes(48),
            taraz_secret=secrets.token_bytes(48),
        )
        self.registry = TarazPeerRegistry(self.root / "peer-metadata.sqlite3",
                                          self.config)
        self.id = secrets.token_hex(16)
        self.task = "synthetic-task"
        self.project = "synthetic-project"
        self.source = {
            "schema": 1, "source": "madar", "id": self.id,
            "taskId": self.task, "projectId": self.project,
            "title": "Synthetic-only review (no accounting)",
            "createdUtc": "2026-11-10T08:00:00+00:00",
        }
        (self.bridge / "pending" / (self.id + ".json")).write_text(
            json.dumps(self.source, ensure_ascii=False,
                       separators=(",", ":")), encoding="utf8")
        self.api.tarazIntegrationReview(self.id, "reviewed")
        self.source_path = self.bridge / "reviewed" / (self.id + ".json")
        self.intent_path = self.bridge / "reviewed" / (self.id + ".intent.json")
        self.review_path = self.bridge / "reviewed" / (self.id + ".review.json")
        # Fixed precision tests are timed a second after actual review, so
        # reviewedUtc (with microseconds) is never after proof issuedUtc.
        self.now = datetime.now(timezone.utc).replace(
            microsecond=0) + timedelta(seconds=2)
        self.original = self.make_original()
        self.registry.intake(self.original, now=self.now,
                             verified_transport_peer=True)
        self.challenge_id = secrets.token_hex(16)
        self.query = self.make_query()
        self.issuer = self.new_issuer()

    def new_issuer(self, **overrides):
        opts = {
            "taraz_api": self.api, "peer_registry": self.registry,
            "trusted_config": self.config, "reviewed_root": self.bridge,
            "consumed_challenges_dir": self.replay,
        }
        opts.update(overrides)
        return ManualReviewAttestationIssuer(**opts)

    def make_original(self, **changes):
        source_digest = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        payload = {
            "id": self.id, "taskId": self.task, "projectId": self.project,
            "sourceDigest": source_digest,
        }
        payload.update(changes)
        return PEER_ENVELOPE.sign_request(
            payload, organization_id=self.config.organization_id,
            sender_id=self.config.madar_sender_id, actor_role="editor",
            key_id=self.config.madar_key_id, request_id=self.id,
            purpose="finance_review_request", issued_at=self.now,
            expires_at=self.now + timedelta(seconds=150),
            secret=self.config.madar_secret, authorized=True,
            explicit_manual_action=True)

    def make_query(self, *, original=None, challenge_id=None, **changes):
        original = original if original is not None else self.original
        verified = PEER_ENVELOPE.verify_request(
            original, secret=self.config.madar_secret, now=self.now,
            expected_organization_id=self.config.organization_id,
            expected_sender_id=self.config.madar_sender_id,
            expected_key_id=self.config.madar_key_id,
            purpose="finance_review_request",
            allowed_actor_roles=frozenset({"editor"}))
        params = {
            "query_request_id": challenge_id or self.challenge_id,
            "key_id": self.config.madar_key_id, "issued_at": self.now,
            "expires_at": self.now + timedelta(seconds=150),
            "secret": self.config.madar_secret,
        }
        params.update(changes)
        return PEER_ENVELOPE.sign_receipt_query(verified, **params)

    def issue(self, **changes):
        kwargs = {
            "request_id": self.id, "signed_madar_original": self.original,
            "signed_madar_query_challenge": self.query,
            "explicit_manual_action": True, "now": self.now,
        }
        kwargs.update(changes)
        return self.issuer.issue_manual(**kwargs)

    def validate_with_madar(self, proof, *, consume=None):
        issued = ({(self.config.taraz_sender_id, self.id, self.challenge_id)}
                  if consume is None else consume)

        def one_time(peer, request_id, challenge):
            key = peer, request_id, challenge
            if key not in issued:
                return False
            issued.remove(key)
            return True

        return PEER_IDENTITY.verify_peer_review_attestation(
            wire=proof, source_raw=self.source_path.read_bytes(),
            review_raw=self.review_path.read_bytes(),
            secret=self.config.taraz_secret, now=self.now,
            expected_organization_id=self.config.organization_id,
            expected_peer_id=self.config.taraz_sender_id,
            expected_key_id=self.config.taraz_key_id,
            expected_request_id=self.id, expected_task_id=self.task,
            expected_project_id=self.project,
            expected_challenge=self.challenge_id,
            consume_challenge=one_time)

    def test_exact_madar_maker_wire_and_real_verifier_nonfinancial_only(self):
        raw = self.issue()
        proof = json.loads(raw)
        expected = PEER_IDENTITY.make_peer_review_attestation(
            source_raw=self.source_path.read_bytes(),
            review_raw=self.review_path.read_bytes(),
            organization_id=self.config.organization_id,
            peer_id=self.config.taraz_sender_id,
            key_id=self.config.taraz_key_id,
            challenge=self.challenge_id, issued_at=self.now,
            expires_at=self.now + timedelta(seconds=90),
            secret=self.config.taraz_secret)
        self.assertEqual(raw, expected)
        observed = self.validate_with_madar(raw)
        self.assertTrue(observed["peerVerified"])
        self.assertEqual(observed["reviewState"], "reviewed")
        self.assertFalse(observed["financialEventCreated"])
        self.assertFalse(observed["officialFinancialReceiptVerified"])
        self.assertFalse(observed["postingEnabled"])
        self.assertFalse(observed["ledgerPostingPerformed"])
        self.assertFalse(self.api.path.exists())  # no accounting file created
        self.assertEqual(len(list(self.replay.iterdir())), 1)

    def test_missing_explicit_manual_action_denied_before_nonce_consumption(self):
        with self.assertRaisesRegex(ReviewAttestationDenied, "manual"):
            self.issue(explicit_manual_action=False)
        self.assertEqual(list(self.replay.iterdir()), [])

    def test_default_local_admin_fallback_never_counts_as_authenticated_peer(self):
        self.api._identity_store = None
        self.api._identity_token = None
        self.api._actor = "local"
        self.api._accounts = {"local": {"username": "local", "role": "admin"}}
        with self.assertRaisesRegex(ReviewAttestationDenied, "fallback"):
            self.issue()
        self.assertEqual(list(self.replay.iterdir()), [])

    def test_role_downgrade_or_revoked_session_denied(self):
        self.ident.logout(self.token)
        with self.assertRaises(PermissionError):
            self.issue()
        self.token = self.ident.login("qaeditor", "Synthetic-Editor-Only!")
        self.api._identity_token = self.token
        self.ident.change_role("qaeditor", "viewer", administrator=self.admin)
        with self.assertRaises(PermissionError):
            self.issue()
        self.assertEqual(list(self.replay.iterdir()), [])

    def test_wrong_peer_config_and_fabricated_api_denied(self):
        with self.assertRaises(ReviewAttestationDenied):
            self.new_issuer(trusted_config=PeerConfig(
                "qa-organization", "qa-madar-host", "qa-madar-key",
                "qa-taraz-host", "qa-taraz-key",
                secrets.token_bytes(48), secrets.token_bytes(48)))
        with self.assertRaises(ReviewAttestationDenied):
            self.new_issuer(taraz_api=object())

    def test_tampered_durable_source_after_review_fails_before_signing(self):
        before = self.source_path.read_bytes()
        self.source_path.write_bytes(before.replace(b"Synthetic-only", b"Tampered-only"))
        with self.assertRaises(ReviewAttestationDenied):
            self.issue()
        self.assertFalse(list(self.replay.iterdir()))

    def test_corrupt_intent_digest_or_conflicting_receipt_denied(self):
        intent = json.loads(self.intent_path.read_bytes())
        self.intent_path.write_text(json.dumps({**intent, "sourceDigest": "0" * 64}),
                                    encoding="utf8")
        with self.assertRaises(ReviewAttestationDenied):
            self.issue()
        self.intent_path.write_text(json.dumps(intent), encoding="utf8")
        receipt = json.loads(self.review_path.read_bytes())
        self.review_path.write_text(json.dumps({**receipt, "state": "rejected"}),
                                    encoding="utf8")
        with self.assertRaises(ReviewAttestationDenied):
            self.issue()
        self.assertFalse(list(self.replay.iterdir()))

    def test_missing_durable_intent_even_with_review_receipt_denied(self):
        self.intent_path.unlink()
        with self.assertRaises((FileNotFoundError, ReviewAttestationDenied)):
            self.issue()
        self.assertFalse(list(self.replay.iterdir()))

    def test_spoofed_financial_success_receipt_denied(self):
        receipt = json.loads(self.review_path.read_bytes())
        self.review_path.write_text(
            json.dumps({**receipt, "financialEventCreated": True}), encoding="utf8")
        with self.assertRaises(ReviewAttestationDenied):
            self.issue()
        self.assertFalse(list(self.replay.iterdir()))

    def test_unregistered_original_signed_request_denied(self):
        other_original = self.make_original()
        # A distinct correctly signed source-binding payload (without
        # registry intake) must not acquire authority solely from its MAC.
        self.registry = TarazPeerRegistry(
            self.root / "new-empty-peer.sqlite3", self.config)
        self.issuer = self.new_issuer()
        with self.assertRaises(ReviewAttestationDenied):
            self.issue(signed_madar_original=other_original)
        self.assertFalse(list(self.replay.iterdir()))

    def test_source_digest_not_bound_by_signed_original_denied(self):
        forged_original = self.make_original(sourceDigest="0" * 64)
        other_query = self.make_query(original=forged_original)
        with self.assertRaises(ReviewAttestationDenied):
            self.issue(signed_madar_original=forged_original,
                       signed_madar_query_challenge=other_query)
        self.assertEqual(list(self.replay.iterdir()), [])

    def test_signed_query_tampering_wrong_challenge_or_wrong_original_denied(self):
        query = json.loads(self.query)
        for change in ({"requestId": secrets.token_hex(16)},
                       {"organizationId": "different-company"},
                       {"mac": "0" * 64},
                       {"payload": {**query["payload"],
                                    "originalRequestId": secrets.token_hex(16)}}):
            with self.subTest(change=change):
                encoded = json.dumps({**query, **change}, sort_keys=True,
                                     ensure_ascii=False,
                                     separators=(",", ":")).encode()
                with self.assertRaises(ValueError):
                    self.issue(signed_madar_query_challenge=encoded)
        self.assertFalse(list(self.replay.iterdir()))

    def test_expired_or_future_signed_query_denied(self):
        with self.assertRaises(ReviewAttestationDenied):
            self.issue(now=self.now + timedelta(seconds=151))
        with self.assertRaises(ReviewAttestationDenied):
            self.issue(now=self.now - timedelta(seconds=31))
        expires_too_soon = self.make_query(
            expires_at=self.now + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            self.issue(signed_madar_query_challenge=expires_too_soon,
                       now=self.now + timedelta(seconds=2))
        future_issued = self.make_query(
            issued_at=self.now + timedelta(seconds=32),
            expires_at=self.now + timedelta(seconds=90))
        with self.assertRaises(ValueError):
            self.issue(signed_madar_query_challenge=future_issued)
        self.assertFalse(list(self.replay.iterdir()))

    def test_replay_same_query_denied_across_fresh_issuer_instances(self):
        signed = self.issue()
        self.assertIsInstance(signed, bytes)
        madar_challenges = {
            (self.config.taraz_sender_id, self.id, self.challenge_id),
        }
        self.assertTrue(self.validate_with_madar(
            signed, consume=madar_challenges)["peerVerified"])
        with self.assertRaises(PEER_IDENTITY.PeerIdentityError):
            self.validate_with_madar(signed, consume=madar_challenges)
        with self.assertRaises(ReviewAttestationDenied):
            self.issue()
        self.issuer = self.new_issuer()
        with self.assertRaises(ReviewAttestationDenied):
            self.issue()

    def test_durable_abandoned_claim_blocks_retry_after_simulated_crash(self):
        name = self.replay / ("review-challenge-" + self.challenge_id)
        name.mkdir()  # simulates crash after prior atomic claim, before reply
        with self.assertRaises(ReviewAttestationDenied):
            self.issue()

    def test_concurrent_same_nonce_at_most_one_signature(self):
        def work(_):
            try:
                return self.issue()
            except ReviewAttestationDenied:
                return None

        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(work, range(3)))
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(len(list(self.replay.iterdir())), 1)

    def test_wrong_bridge_replay_directory_or_linked_source_denied(self):
        wrong = self.root / "not-the-local-bridge"
        wrong.mkdir()
        with self.assertRaises(ReviewAttestationDenied):
            self.new_issuer(reviewed_root=wrong)
        with self.assertRaises(ReviewAttestationDenied):
            self.new_issuer(consumed_challenges_dir=self.source_path.parent)

    def test_rejected_manual_review_proves_metadata_only(self):
        # Produce a distinct completed rejected review using the unmodified
        # Taraz helper. The issuer must not turn "rejected" into a ledger event.
        self.review_path.unlink()
        self.intent_path.unlink()
        self.source_path.rename(self.bridge / "pending" / (self.id + ".json"))
        review_request(self.bridge, self.id, "rejected")
        result = self.issue()
        observed = self.validate_with_madar(result)
        self.assertEqual(observed["reviewState"], "rejected")
        self.assertFalse(observed["officialFinancialReceiptVerified"])
        self.assertFalse(self.api.path.exists())


if __name__ == "__main__":
    unittest.main()
