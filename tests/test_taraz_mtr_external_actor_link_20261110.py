"""Synthetic current-company/admin proof for 77-character Madar principal IDs.

Reuses the existing disposable registered-company/ledger fixture. No installed
profile, real accounting journal, transport, or production finance posting.
"""
from __future__ import annotations

from datetime import timedelta
import secrets
import unittest
from unittest.mock import patch

from tests import test_taraz_mtr_finance_binding_authority_20261110 as fixture
from taraz_mtr_external_actor_link import (
    ExternalActorLinkDenied, ManualExternalActorLinks,
)
from taraz_mtr_peer_registry import PeerConfig, TarazPeerRegistry


class ExternalActorLinkTests(unittest.TestCase):
    # Reuse the exact synthetic, registered Taraz company and recorded invoice
    # from the finance binding authority test without importing any actual user
    # profile. Rebuild only the disposable peer intake for an external actor.
    def _cmd(self, event):
        return fixture.FinanceBindingAuthorityTests._cmd(self, event)

    def _original(self, *, payload=None):
        return fixture.FinanceBindingAuthorityTests._original(self, payload=payload)

    def _query(self, original):
        return fixture.FinanceBindingAuthorityTests._query(self, original)

    def _authority(self, **changes):
        return fixture.FinanceBindingAuthorityTests._authority(self, **changes)

    def setUp(self):
        fixture.FinanceBindingAuthorityTests.setUp(self)
        self.external_actor = "mtr-actor-v1-" + secrets.token_hex(32)
        self.assertEqual(len(self.external_actor), 77)
        self.payload["actorId"] = self.external_actor
        self.original = self._original()
        self.registry = TarazPeerRegistry(self.root / "peer-external.sqlite3", self.config)
        self.registry.intake(self.original, now=self.now, verified_transport_peer=True)
        self.query = self._query(self.original)
        self.registry.query_receipt(self.query, now=self.now, verified_transport_peer=True)
        self.link_dir = self.root / "operator-private-links"
        self.link_dir.mkdir()
        self.links = ManualExternalActorLinks(
            accounting_host=self.host, peer_registry=self.registry,
            trusted_config=self.config, reviewed_root=self.bridge,
            link_db_path=self.link_dir / "external-actor-links.sqlite3",
        )
        self.authority = self._authority(external_actor_links=self.links)

    def grant(self, **changes):
        params = dict(
            signed_madar_original=self.original,
            signed_madar_query_challenge=self.query,
            company_id=self.company_id,
            administrator_token=self.admin_token,
            explicit_manual_action=True, now=self.now,
        )
        params.update(changes)
        return self.links.authorize_manual(**params)

    def bind(self, **changes):
        params = dict(
            signed_madar_original=self.original,
            signed_madar_query_challenge=self.query,
            madar_request_id=self.id, company_id=self.company_id,
            invoice_id=self.invoice_id, issue_event_id=self.issue_id,
            journal_id=self.journal_id, expected_revision=self.revision,
            explicit_manual_action=True, now=self.now,
            external_link_admin_token=self.admin_token,
        )
        params.update(changes)
        return self.authority.bind_preexisting_manual(**params)

    def assert_unclaimed(self):
        self.assertEqual(list(self.consumed.iterdir()), [])

    def test_77_char_actor_requires_live_admin_grant_and_consumes_once(self):
        with self.assertRaisesRegex(PermissionError, "admission|link"):
            self.bind()
        self.assert_unclaimed()
        grant = self.grant()
        self.assertEqual(grant["decision"], "EXTERNAL_ACTOR_LINK_ADMITTED_ONCE")
        self.assertEqual(grant["tarazOperator"], "qaeditor")
        self.assertFalse(grant["independentlyAuthenticatedMadarActorVerified"])
        self.assertFalse(grant["trustedMadarInvoiceBindingVerified"])
        self.assertFalse(grant["officialFinanceReceiptVerified"])
        before = self.host.standaloneAccountingRead()["revision"]
        result = self.bind()
        self.assertEqual(
            result["decision"],
            "SIGNED_BINDING_TO_EXISTING_JOURNAL_OBSERVED_NOT_OFFICIAL",
        )
        self.assertTrue(result["oneTimeAdminExternalActorLinkConsumed"])
        self.assertTrue(result["madarHmacRequestAndQueryVerified"])
        self.assertTrue(result["persistedInvoiceJournalVerified"])
        for flag in ("independentlyAuthenticatedMadarActorVerified",
                     "trustedMadarInvoiceBindingVerified",
                     "officialFinanceReceiptVerified",
                     "financialEventCreatedByThisOperation"):
            self.assertFalse(result[flag], flag)
        self.assertEqual(before, self.host.standaloneAccountingRead()["revision"])
        with self.assertRaises(PermissionError):
            self.bind()
        with self.assertRaises(ExternalActorLinkDenied):
            self.grant()
        with self.assertRaises(ExternalActorLinkDenied):
            self.links.consume_manual(
                signed_madar_original=self.original,
                signed_madar_query_challenge=self.query,
                company_id=self.company_id, administrator_token=self.admin_token,
                explicit_manual_action=True, now=self.now)

    def test_no_unsigned_mapping_or_fake_admin_or_generic_boolean(self):
        with self.assertRaises(PermissionError):
            self.grant(administrator_token=self.editor_token)
        with self.assertRaises(ExternalActorLinkDenied):
            self.grant(explicit_manual_action=1)
        with self.assertRaises(PermissionError):
            self.bind(external_link_admin_token=self.editor_token)
        with self.assertRaises(PermissionError):
            self.bind(external_link_admin_token=None)
        self.assert_unclaimed()

    def test_authenticated_peer_hmac_and_exact_query_not_optional(self):
        forged = self.original.replace(b"mtr-actor-v1-", b"mtr-actor-v2-")
        with self.assertRaises(ValueError):
            self.grant(signed_madar_original=forged)
        with self.assertRaises((ValueError, PermissionError)):
            self.grant(signed_madar_original=self._original(
                payload={**self.payload, "actorId":
                         "mtr-actor-v1-" + secrets.token_hex(32)}))
        with self.assertRaises((ValueError, PermissionError)):
            self.grant(signed_madar_original=self._original(
                payload={**self.payload, "projectId": "wrong-project"}))
        with self.assertRaises((ValueError, PermissionError)):
            self.grant(signed_madar_original=self._original(
                payload={**self.payload, "companyId": "b" * 32}))
        unregistered = fixture.PEER_ENVELOPE.sign_receipt_query(
            fixture.PEER_ENVELOPE.verify_request(
                self.original, secret=self.config.madar_secret,
                now=self.now, expected_organization_id=self.config.organization_id,
                expected_sender_id=self.config.madar_sender_id,
                expected_key_id=self.config.madar_key_id,
                purpose="finance_review_request",
                allowed_actor_roles=frozenset({"editor"}),
            ),
            query_request_id=secrets.token_hex(16),
            key_id=self.config.madar_key_id, issued_at=self.now,
            expires_at=self.now + timedelta(seconds=120),
            secret=self.config.madar_secret,
        )
        with self.assertRaises(PermissionError):
            self.grant(signed_madar_query_challenge=unregistered)
        self.assert_unclaimed()

    def test_wrong_peer_secret_organization_and_signed_role_denied(self):
        def signed_override(*, organization=None, role="editor", secret=None):
            return fixture.PEER_ENVELOPE.sign_request(
                self.payload,
                organization_id=organization or self.config.organization_id,
                sender_id=self.config.madar_sender_id, actor_role=role,
                key_id=self.config.madar_key_id, request_id=self.id,
                purpose="finance_review_request", issued_at=self.now,
                expires_at=self.now + timedelta(seconds=120),
                secret=secret or self.config.madar_secret, authorized=True,
                explicit_manual_action=True,
            )

        for forged in (
            signed_override(organization="another-org"),
            signed_override(role="admin"),
            signed_override(secret=secrets.token_bytes(48)),
        ):
            with self.subTest(forged=forged[:30]):
                with self.assertRaises((ValueError, PermissionError)):
                    self.grant(signed_madar_original=forged)
        self.assert_unclaimed()

    def test_revocation_and_admin_role_revocation(self):
        self.grant()
        denied = self.links.revoke_manual(
            madar_request_id=self.id, company_id=self.company_id,
            administrator_token=self.admin_token,
            explicit_manual_action=True,
        )
        self.assertEqual(denied["decision"], "EXTERNAL_ACTOR_LINK_REVOKED")
        with self.assertRaises(ExternalActorLinkDenied):
            self.bind()
        with self.assertRaises(ExternalActorLinkDenied):
            self.grant()
        self.assert_unclaimed()

    def test_revoked_admin_session_or_operator_role_cannot_consume(self):
        self.grant()
        self.identity.logout(self.admin_token)
        with self.assertRaises(PermissionError):
            self.bind()
        self.assert_unclaimed()

    def test_revoked_editor_role_cannot_consume(self):
        self.grant()
        self.identity.change_role("qaeditor", "viewer",
                                  administrator=self.admin_token)
        with self.assertRaises(PermissionError):
            self.bind()
        self.assert_unclaimed()

    def test_company_org_key_source_role_and_project_bound_at_redeem(self):
        self.grant()
        for kwargs in (
            {"company_id": "b" * 32},
            {"signed_madar_original": self._original(
                payload={**self.payload, "projectId": "different"})},
            {"signed_madar_original": self._original(
                payload={**self.payload, "actorId":
                         "mtr-actor-v1-" + secrets.token_hex(32)})},
            {"signed_madar_original": self._original(
                payload={**self.payload, "sourceDigest": "a" * 64})},
        ):
            with self.assertRaises((PermissionError, ValueError)):
                self.bind(**kwargs)
        forged_config = PeerConfig(
            "other-org", self.config.madar_sender_id,
            self.config.madar_key_id, self.config.taraz_sender_id,
            self.config.taraz_key_id, secrets.token_bytes(48),
            secrets.token_bytes(48),
        )
        with self.assertRaises(PermissionError):
            ManualExternalActorLinks(
                accounting_host=self.host, peer_registry=self.registry,
                trusted_config=forged_config, reviewed_root=self.bridge,
                link_db_path=self.link_dir / "external-actor-links.sqlite3",
            )
        self.assert_unclaimed()
        self.assertTrue(self.links.verify_pending(
            signed_madar_original=self.original,
            signed_madar_query_challenge=self.query,
            company_id=self.company_id, administrator_token=self.admin_token,
            now=self.now,
        ))

    def test_admission_expires_independently_before_peer_envelope(self):
        self.grant()
        with patch("taraz_mtr_external_actor_link._trusted_now",
                   return_value=self.now + timedelta(seconds=91)):
            with self.assertRaises(ExternalActorLinkDenied):
                self.links.verify_pending(
                    signed_madar_original=self.original,
                    signed_madar_query_challenge=self.query,
                    company_id=self.company_id,
                    administrator_token=self.admin_token,
                    now=self.now + timedelta(seconds=91),
                )
        self.assert_unclaimed()

    def test_durable_consumption_and_mutated_review_fail_closed(self):
        self.grant()
        self.links.consume_manual(
            signed_madar_original=self.original,
            signed_madar_query_challenge=self.query,
            company_id=self.company_id, administrator_token=self.admin_token,
            explicit_manual_action=True, now=self.now,
        )
        reopened = ManualExternalActorLinks(
            accounting_host=self.host, peer_registry=self.registry,
            trusted_config=self.config, reviewed_root=self.bridge,
            link_db_path=self.link_dir / "external-actor-links.sqlite3",
        )
        with self.assertRaises(ExternalActorLinkDenied):
            reopened.verify_pending(
                signed_madar_original=self.original,
                signed_madar_query_challenge=self.query,
                company_id=self.company_id, administrator_token=self.admin_token,
                now=self.now,
            )
        self.assert_unclaimed()

    def test_source_change_after_grant_prevents_admission_consumption(self):
        self.grant()
        self.source_file.write_bytes(self.source_file.read_bytes() + b" ")
        with self.assertRaises((PermissionError, ValueError)):
            self.bind()
        self.assert_unclaimed()


if __name__ == "__main__":
    unittest.main()
