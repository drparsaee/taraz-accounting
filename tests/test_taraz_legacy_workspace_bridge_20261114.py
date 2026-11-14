"""Focused identity-pending migration/ACL tests; only disposable fake finance."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from contextlib import closing
import hashlib
import json
import os
import sqlite3
import unittest

from standalone_accounting import StandaloneAccountingStore
from taraz_legacy_workspace_bridge import (
    LegacyBridgeBlocked, LegacyLocalViewerIdentity, inspect_legacy_book,
    migrate_restored_clone, verify_workspace, MARKER,
)
from taraz_desktop import open_identity_pending_legacy_workspace, run
from taraz_three_root_backup_20261114 import (
    create_three_root_backup, restore_three_root_backup,
)


class LegacyWorkspaceBridgeTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(prefix='qa-legacy-taraz-')
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.roaming = self.home / 'qa-roaming'
        self.local = self.home / 'qa-local'
        self.bridge = self.home / 'qa-bridge'
        for root in (self.roaming, self.local, self.bridge):
            root.mkdir()
        (self.local / 'settings.json').write_text('{"source":"synthetic"}', encoding='utf-8')
        (self.bridge / 'pending.json').write_text('{"queued":true}', encoding='utf-8')
        self.ledger = self.roaming / 'standalone-accounting.sqlite3'
        store = StandaloneAccountingStore(self.ledger, default_currency='RIAL')
        self.accounts = {'qa_admin': {'username': 'qa_admin', 'role': 'admin',
                                      'financeView': True, 'financeEdit': True}}
        store.command({'type': 'party.register', 'eventId': 'qa-legacy-event-1',
                       'partyId': 'qa-customer', 'name': 'Synthetic', 'kind': 'customer'},
                      actor='qa_admin', accounts=self.accounts,
                      expected_revision=0, now='2026-11-14T08:00:00Z')
        self.bundle = self.home / 'snapshot'
        create_three_root_backup(self.roaming, self.local, self.bridge,
                                 self.bundle, offline_acknowledged=True)
        self.clone = self.home / 'qa-clone'
        self.clone.mkdir()
        self.roots = [self.clone / part for part in ('roaming_taraz', 'local_taraz', 'local_bridge')]
        restore_three_root_backup(self.bundle, *self.roots,
                                  offline_acknowledged=True)
        self.manifest = self.bundle / 'TARAZ_THREE_ROOT_MANIFEST.json'

    def migrate(self):
        return migrate_restored_clone(*self.roots,
                                      original_snapshot_manifest=self.manifest)

    def test_versioned_workspace_only_adds_one_provenance_sidecar_and_is_idempotent(self):
        original = self.ledger.read_bytes()
        restored = self.roots[0] / self.ledger.name
        before = hashlib.sha256(restored.read_bytes()).hexdigest()
        result = self.migrate()
        self.assertEqual(result['status'], 'MIGRATED_IDENTITY_PENDING')
        self.assertEqual(result['ledgerRevision'], 1)
        self.assertEqual(result['eventCount'], 1)
        self.assertEqual(result['roleGrants'], [])
        self.assertEqual(result['identityStatus'], 'identity_pending')
        self.assertEqual(result['ownershipStatus'], 'ownership_unclaimed')
        self.assertFalse((self.roots[0] / 'local-users.json').exists())
        self.assertFalse((self.roots[0] / 'companies.json').exists())
        marker = self.roots[0] / MARKER
        digest = hashlib.sha256(marker.read_bytes()).hexdigest()
        again = self.migrate()
        self.assertEqual(again['status'], 'ALREADY_MIGRATED')
        self.assertEqual(again['workspaceId'], result['workspaceId'])
        self.assertEqual(hashlib.sha256(marker.read_bytes()).hexdigest(), digest)
        self.assertEqual(hashlib.sha256(restored.read_bytes()).hexdigest(), before)
        self.assertEqual(self.ledger.read_bytes(), original)
        self.assertEqual((self.roots[2] / 'pending.json').read_text(), '{"queued":true}')

    def test_unrelated_restore_change_refused_without_stamp(self):
        (self.roots[2] / 'pending.json').write_text('{"queued":false}', encoding='utf-8')
        with self.assertRaisesRegex(LegacyBridgeBlocked, 'do not match'):
            self.migrate()
        self.assertFalse((self.roots[0] / MARKER).exists())

    def test_existing_registered_company_cannot_be_relabelled_legacy(self):
        (self.roots[0] / 'companies.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(LegacyBridgeBlocked):
            inspect_legacy_book(self.roots[0])

    def test_invoice_issuer_candidates_do_not_override_ledger_state_digest(self):
        with closing(sqlite3.connect(self.roots[0] / 'standalone-accounting.sqlite3')) as connection:
            expected = connection.execute('SELECT digest FROM standalone_accounting').fetchone()[0]
        # Inject only the decoded return in a disposable fixture, not the database.
        fake = {'events': [{'eventId': 'synthetic-1', 'actor': 'qa',
                            'command': {'type': 'party.register'}}],
                'invoices': {'test': {'issuerName': 'Synthetic issuer'}}}
        with patch('taraz_legacy_workspace_bridge._decode_checked', return_value=fake):
            result = inspect_legacy_book(self.roots[0])
        self.assertEqual(result['ledgerStateSha256'], expected)
        self.assertEqual(result['eventCount'], 1)

    def test_local_viewer_opens_old_finance_and_cannot_post_or_claim_admin(self):
        self.migrate()
        root = self.roots[0]
        with patch('taraz_desktop.taraz_data_root', return_value=root):
            api, identity, token = open_identity_pending_legacy_workspace(root)
        try:
            snapshot = api.standaloneAccountingRead()
            self.assertEqual(snapshot['revision'], 1)
            self.assertEqual(snapshot['capabilities'], {
                'canView': True, 'canManage': False, 'canDraft': False, 'canAdmin': False})
            self.assertEqual(snapshot['view']['legacyWorkspaceState']['ownershipStatus'],
                             'ownership_unclaimed')
            self.assertEqual(snapshot['view']['companyWorkspaceId'], verify_workspace(root)['workspaceId'])
            with self.assertRaises(PermissionError):
                identity.require_session(token, 'admin')
            with self.assertRaises(PermissionError):
                api.standaloneAccountingCommand({'command': {
                    'type': 'party.register', 'eventId': 'qa-should-not-save',
                    'partyId': 'qa-denied', 'kind': 'customer', 'name': 'Denied'},
                    'expectedRevision': 1})
            self.assertEqual(api.standaloneAccountingRead()['revision'], 1)
        finally:
            identity.logout(token)
        with self.assertRaises(PermissionError):
            api.standaloneAccountingRead()

    def test_run_routes_only_proven_legacy_to_local_viewer_not_native_login(self):
        self.migrate()
        with patch('taraz_desktop.taraz_data_root', return_value=self.roots[0]), patch(
                'taraz_desktop.open_authenticated_taraz_company',
                side_effect=AssertionError('Native login must not run')) as login, patch(
                'taraz_desktop._run_authenticated_taraz_api') as launch:
            run()
        login.assert_not_called()
        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[0]._actor, LegacyLocalViewerIdentity.USER)

    @unittest.skipUnless(os.name == 'nt', 'Legacy encrypted chat requires Windows DPAPI')
    def test_local_unclaimed_chat_survives_session_restart_without_finance_approval(self):
        self.migrate()
        root = self.roots[0]
        with patch('taraz_desktop.taraz_data_root', return_value=root):
            first, identity, token = open_identity_pending_legacy_workspace(root)
            try:
                created = first.tarazAiChatCommand({'action': 'create',
                    'title': 'QA private legacy chat'})
                conversation_id = created['conversationId']
                sent = first.tarazAiChatCommand({'action': 'send',
                    'conversationId': conversation_id,
                    'text': 'سلام. این پیام فقط آزمایش محلی است.'})
                self.assertFalse(sent.get('journalPosted', False))
                with self.assertRaises(PermissionError):
                    first.tarazAiChatCommand({'action': 'approve',
                        'conversationId': conversation_id,
                        'actionId': 'a' * 32, 'manualConfirmation': True})
            finally:
                identity.logout(token)
            restarted, restarted_identity, restarted_token = open_identity_pending_legacy_workspace(root)
            try:
                history = restarted.tarazAiChatRead(conversation_id)
                self.assertGreaterEqual(len(history['messages']), 2)
                self.assertEqual(restarted.standaloneAccountingRead()['revision'], 1)
            finally:
                restarted_identity.logout(restarted_token)


if __name__ == '__main__':
    unittest.main()
