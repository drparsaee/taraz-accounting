"""One-time enrollment only on synthetic three-root restored fixtures."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import unittest
from unittest.mock import patch

from standalone_accounting import StandaloneAccountingStore
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from taraz_desktop import open_authenticated_taraz_company
from taraz_legacy_workspace_bridge import migrate_restored_clone
from taraz_legacy_ownership_enrollment import (
    EnrollmentBlocked, CONSENT, BOOK_PROVENANCE, DECLARATION,
    pending_company, stage_legacy_company, approve_declaration,
)
from taraz_three_root_backup_20261114 import (
    create_three_root_backup, restore_three_root_backup,
)


class LegacyEnrollmentTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='qa-enrollment-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.roaming, self.local, self.bridge = [
            self.base / x for x in ('source-roaming', 'source-local', 'source-bridge')]
        for part in (self.roaming, self.local, self.bridge):
            part.mkdir()
        original = StandaloneAccountingStore(
            self.roaming / 'standalone-accounting.sqlite3', default_currency='RIAL')
        original.command({'type': 'party.register', 'eventId': 'qa-enrollment-event-1',
            'partyId': 'qa-client', 'name': 'Synthetic client', 'kind': 'customer'},
            actor='qa', accounts={'qa': {'username': 'qa', 'role': 'admin'}},
            expected_revision=0, now='2026-11-15T00:00:00Z')
        (self.roaming / 'accounting-print.json').write_text('{"old":true}', encoding='utf-8')
        (self.local / 'settings.txt').write_text('Local synthetic')
        (self.bridge / 'outbox.txt').write_text('No production data')
        self.snapshot = self.base / 'snapshot'
        create_three_root_backup(self.roaming, self.local, self.bridge,
                                 self.snapshot, offline_acknowledged=True)
        self.clone = self.base / 'qa-clone'
        self.clone.mkdir()
        self.roots = [
            self.clone / x for x in ('roaming_taraz', 'local_taraz', 'local_bridge')]
        restore_three_root_backup(self.snapshot, *self.roots, offline_acknowledged=True)
        self.manifest = self.snapshot / 'TARAZ_THREE_ROOT_MANIFEST.json'
        migrate_restored_clone(*self.roots, original_snapshot_manifest=self.manifest)
        self.old = self.roots[0] / 'standalone-accounting.sqlite3'
        self.old_digest = hashlib.sha256(self.old.read_bytes()).hexdigest()

    def stage(self):
        return stage_legacy_company(*self.roots,
                                    original_snapshot_manifest=self.manifest)

    def test_stage_is_idempotent_and_has_no_legal_name_or_granted_admin(self):
        first = self.stage()
        self.assertEqual(first['status'], 'STAGED_OWNERLESS')
        second = self.stage()
        self.assertEqual(second['status'], 'ALREADY_STAGED_OWNERLESS')
        self.assertEqual(first['companyId'], second['companyId'])
        self.assertEqual(first['roleGrants'], [])
        self.assertFalse(first['ownerVerified'])
        book = StandaloneCompanyRegistry(self.roots[0]).company_data_directory(
            first['companyId'])
        proof = json.loads((book / BOOK_PROVENANCE).read_text(encoding='utf-8'))
        self.assertIsNone(proof['legalCompanyName'])
        self.assertFalse(proof['principalProvesLegalOwnership'])
        self.assertFalse((book / 'local-users.json').exists())
        self.assertFalse((book / DECLARATION).exists())
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_digest)
        self.assertEqual(book.joinpath('accounting-print.json').read_text(),
                         '{"old":true}')
        self.assertEqual(pending_company(self.roots[0])['status'],
                         'WAITING_USER_DECLARATION')

    def test_declaration_needs_real_explicit_text_and_valid_credentials(self):
        stage = self.stage()
        params = dict(company_id=stage['companyId'], username='qa_admin',
                      password='QA_Strong_13579', confirmation=CONSENT)
        for override in (
            {'consent_checked': False},
            {'consent_checked': True, 'confirmation': 'I own the company'},
            {'consent_checked': True, 'username': ''},
        ):
            with self.subTest(override=override), self.assertRaises(EnrollmentBlocked):
                approve_declaration(self.roots[0], **{**params, 'consent_checked': True,
                                                    **override})
        pending = pending_company(self.roots[0])
        self.assertIsNotNone(pending)
        self.assertFalse((pending['book'] / 'local-users.json').exists())
        self.assertFalse((pending['book'] / DECLARATION).exists())
        enrolled = approve_declaration(self.roots[0], **params, consent_checked=True)
        self.assertEqual(enrolled['status'], 'LOCAL_ADMIN_CREATED_FROM_EXPLICIT_DECLARATION')
        self.assertFalse(enrolled['legalOwnershipIndependentlyVerified'])
        self.assertIsNone(pending_company(self.roots[0]))
        with patch('taraz_desktop.taraz_data_root', return_value=self.roots[0]):
            session = open_authenticated_taraz_company(
                self.roots[0], login=lambda store: (
                    store.require_session(token := store.login('qa_admin',
                        'QA_Strong_13579')), token))
        api, identity, token = session
        try:
            read = api.standaloneAccountingRead()
            self.assertEqual(read['revision'], 1)
            self.assertEqual(read['currentUser']['role'], 'admin')
            self.assertEqual(read['view']['parties']['qa-client']['name'],
                             'Synthetic client')
        finally:
            identity.logout(token)
        receipt = json.loads((pending['book'] / DECLARATION).read_text(encoding='utf-8'))
        self.assertEqual(receipt['authorizationBasis'],
                         'explicit_local_user_declaration')
        self.assertFalse(receipt['legalOwnershipIndependentlyVerified'])
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_digest)

    def test_multi_company_conflict_blocks_claim_and_preserves_legacy(self):
        staged = self.stage()
        StandaloneCompanyRegistry(self.roots[0]).create_company('Separate synthetic company')
        with self.assertRaisesRegex(EnrollmentBlocked, 'Multi-company'):
            pending_company(self.roots[0])
        with self.assertRaises(EnrollmentBlocked):
            self.stage()
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_digest)

    def test_interrupted_declaration_resumes_only_with_same_explicit_user(self):
        stage = self.stage()
        request = dict(company_id=stage['companyId'], username='qa_admin',
            password='QA_Strong_24680', confirmation=CONSENT, consent_checked=True)
        with patch('taraz_legacy_ownership_enrollment.LocalCompanyIdentity.add_user',
                   side_effect=OSError('synthetic interrupted creation')):
            with self.assertRaises(OSError):
                approve_declaration(self.roots[0], **request)
        pending = pending_company(self.roots[0])
        self.assertIsNotNone(pending)
        self.assertTrue((pending['book'] / DECLARATION).exists())
        self.assertFalse((pending['book'] / 'local-users.json').exists())
        with self.assertRaisesRegex(EnrollmentBlocked, 'conflicts'):
            approve_declaration(self.roots[0], **{**request, 'username': 'other_admin'})
        success = approve_declaration(self.roots[0], **request)
        self.assertEqual(success['status'], 'LOCAL_ADMIN_CREATED_FROM_EXPLICIT_DECLARATION')
        self.assertIsNone(pending_company(self.roots[0]))
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_digest)

    def test_staged_copy_tamper_fails_closed(self):
        stage = self.stage()
        book = StandaloneCompanyRegistry(self.roots[0]).company_data_directory(stage['companyId'])
        (book / 'accounting-print.json').write_text('{"tampered":true}')
        with self.assertRaisesRegex(EnrollmentBlocked, 'staged company member'):
            self.stage()
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(), self.old_digest)


if __name__ == '__main__':
    unittest.main()
