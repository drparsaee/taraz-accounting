"""Only disposable, synthetic 1.0.4-style unregistered Taraz fixture data."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from standalone_accounting import StandaloneAccountingStore
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_identity import LocalCompanyIdentity
from scripts import taraz_legacy_profile_migration_20261114 as migration
from taraz_desktop import select_existing_taraz_company


def hashes(root):
    return {file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in root.rglob('*') if file.is_file()}


class LegacyMigrationRehearsalTests(unittest.TestCase):
    def setUp(self):
        qa_root = Path(__file__).resolve().parent / 'output'
        self.assertTrue(qa_root.is_dir())
        handle = tempfile.TemporaryDirectory(prefix='taraz-legacy-synthetic-20261114-',
                                             dir=qa_root)
        self.addCleanup(handle.cleanup)
        self.root = Path(handle.name)
        self.source = self.root / 'source-clone'
        self.backup = self.root / 'verified-offline-backup'
        self.authority = self.root / 'existing-company-authority'
        self.dest = self.root / 'create-only-migration-rehearsal'
        self.source.mkdir()
        self.authority.mkdir()
        self.registry = StandaloneCompanyRegistry(self.authority)
        self.company = self.registry.create_company('Synthetic authorized company')
        self.company_id = self.company['id']
        self.book = self.registry.company_data_directory(self.company_id)
        self.identity = LocalCompanyIdentity(self.book)
        self.identity.add_user('qa_admin', 'qa-only-strong-password', 'admin')
        self.token = self.identity.login('qa_admin', 'qa-only-strong-password')
        self.addCleanup(lambda: self.identity.logout(self.token))
        shutil.copyfile(self.identity.path, self.source / 'local-users.json')
        (self.source / migration.SOURCE_MARKER).write_text(json.dumps({
            'format': 'taraz-synthetic-legacy-fixture', 'version': 1,
            'synthetic': True}), encoding='utf-8')
        ledger = self.source / 'standalone-accounting.sqlite3'
        accounting = StandaloneAccountingStore(ledger, default_currency='RIAL')
        accounting.read(actor='qa_admin', accounts=self.identity.accounting_accounts())
        result = accounting.command({
            'type': 'party.register', 'eventId': 'legacy-event-001',
            'partyId': 'legacy-party-001', 'name': 'Synthetic customer',
            'kind': 'customer'}, actor='qa_admin',
            accounts=self.identity.accounting_accounts(), expected_revision=0,
            now='2026-11-14T10:00:00+00:00')
        self.assertEqual(result['revision'], 1)
        # The real store uses WAL. A raw byte-preserving OFFLINE migration must
        # start from a checkpointed single-file synthetic fixture, not a WAL.
        with closing(sqlite3.connect(ledger, isolation_level=None)) as db:
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            self.assertEqual(db.execute('PRAGMA journal_mode=DELETE').fetchone()[0],
                             'delete')
        self.ledger_sha = hashlib.sha256(ledger.read_bytes()).hexdigest()
        (self.source / 'invoice-templates.json').write_text(json.dumps({
            'version': 1, 'templates': [], 'defaults': {}}), encoding='utf-8')
        for name in ('taraz-orders.sqlite3', 'taraz-ecosystem-outbox.sqlite3',
                     'taraz-agent-memory.sqlite3', 'taraz-madar-order-links.sqlite3'):
            with closing(sqlite3.connect(self.source / name)) as db:
                db.execute('CREATE TABLE synthetic_records(id TEXT PRIMARY KEY, payload TEXT)')
                db.execute('INSERT INTO synthetic_records VALUES (?,?)', ('original-id-001', name))
                db.commit()
        archives = self.source / 'standalone-accounting-backups'
        archives.mkdir()
        (archives / 'previous-snapshot.dat').write_bytes(b'synthetic-backup-history\x00')

    def make_backup(self):
        return migration.create_legacy_rehearsal_backup(
            self.source, self.backup, offline_acknowledged=True, synthetic_only=True)

    def rehearse(self, **changes):
        args = dict(company_id=self.company_id, administrator=self.identity,
                    administrator_token=self.token,
                    expected_ledger_sha256=self.ledger_sha,
                    offline_acknowledged=True, synthetic_only=True)
        args.update(changes)
        return migration.rehearse_legacy_migration(
            self.source, self.backup, self.authority, self.dest, **args)

    def test_success_preserves_every_source_byte_and_original_id(self):
        before_source = hashes(self.source)
        before_authority = hashes(self.authority)
        self.make_backup()
        saved = self.rehearse()
        self.assertEqual(saved['status'], 'REHEARSAL_ONLY')
        self.assertEqual(saved['company_id'], self.company_id)
        self.assertEqual(saved['files'], len(before_source) + 1)
        self.assertEqual(hashes(self.source), before_source)
        self.assertEqual(hashes(self.authority), before_authority)
        restored_book = self.dest / 'books' / self.company_id
        self.assertEqual(hashes(restored_book), before_source)
        self.assertEqual((self.dest / 'companies.json').read_bytes(),
                         (self.authority / 'companies.json').read_bytes())
        with closing(sqlite3.connect(restored_book / 'standalone-accounting.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT revision FROM standalone_accounting').fetchone()[0], 1)
        with closing(sqlite3.connect(restored_book / 'taraz-orders.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT id FROM synthetic_records').fetchone()[0],
                             'original-id-001')
        selected = select_existing_taraz_company(self.dest,
                                                 choose=lambda _: self.company_id)
        self.assertEqual(selected[0], restored_book)
        self.assertEqual(selected[2], self.company_id)

    def test_rollback_published_result_preserves_inputs(self):
        self.make_backup()
        source_before, backup_before = hashes(self.source), hashes(self.backup)
        output = self.rehearse()
        result = migration.rollback_rehearsal(
            self.dest, rehearsal_id=output['rehearsal_id'],
            marker_sha256=output['marker_sha256'])
        self.assertEqual(result['status'], 'ROLLED_BACK')
        self.assertFalse(self.dest.exists())
        self.assertEqual(hashes(self.source), source_before)
        self.assertEqual(hashes(self.backup), backup_before)

    def test_unregistered_ledger_missing_identity_is_blocked(self):
        (self.source / 'local-users.json').unlink()
        self.make_backup()
        with self.assertRaisesRegex(migration.MigrationBlocked, 'no attributable existing identity'):
            self.rehearse()
        self.assertFalse(self.dest.exists())

    def test_mismatched_identity_registry_blocks_irreversible_mapping(self):
        data = json.loads((self.source / 'local-users.json').read_text())
        data['users']['qa_admin']['salt'] = 'a' * 64
        (self.source / 'local-users.json').write_text(json.dumps(data))
        self.make_backup()
        with self.assertRaisesRegex(migration.MigrationBlocked, 'does not match'):
            self.rehearse()
        self.assertFalse(self.dest.exists())

    def test_wrong_existing_company_id_and_missing_proof_blocked(self):
        self.make_backup()
        with self.assertRaisesRegex(migration.MigrationBlocked, 'pre-existing'):
            self.rehearse(company_id='f' * 32)
        with self.assertRaisesRegex(migration.MigrationBlocked, 'ledger digest'):
            self.rehearse(expected_ledger_sha256='f' * 64)
        with self.assertRaisesRegex(migration.MigrationBlocked, 'administrator'):
            self.rehearse(administrator_token='fabricated')
        self.assertFalse(self.dest.exists())

    def test_corrupt_ledger_cannot_be_snapshotted(self):
        (self.source / 'standalone-accounting.sqlite3').write_bytes(b'corrupt')
        with self.assertRaises(migration.MigrationBlocked):
            self.make_backup()
        self.assertFalse((self.backup / migration.BACKUP_MARKER).exists())

    def test_corrupt_accounting_event_digest_blocks_rehearsal(self):
        ledger = self.source / 'standalone-accounting.sqlite3'
        with closing(sqlite3.connect(ledger)) as db:
            db.execute('UPDATE standalone_accounting SET digest=? WHERE id=1', ('0' * 64,))
            db.commit()
        with self.assertRaisesRegex(migration.MigrationBlocked, 'history'):
            self.make_backup()
        self.assertFalse(self.dest.exists())

    def test_dpapi_encrypted_ai_chat_requires_separate_authority_gate(self):
        chat = self.source / 'taraz-ai-chat.sqlite3'
        with closing(sqlite3.connect(chat)) as db:
            db.execute('CREATE TABLE conversations(id TEXT PRIMARY KEY, tenant_id TEXT)')
            db.execute('INSERT INTO conversations VALUES (?,?)', ('original-chat', 'legacy-unknown'))
            db.commit()
        self.make_backup()
        with self.assertRaisesRegex(migration.MigrationBlocked, 'DPAPI AI chat'):
            self.rehearse()
        self.assertFalse(self.dest.exists())
        self.assertTrue(chat.is_file())

    def test_viewer_cannot_authorize_existing_identity_migration(self):
        self.identity.add_user('qa_viewer', 'viewer-qa-password', 'viewer',
                               administrator=self.token)
        shutil.copyfile(self.identity.path, self.source / 'local-users.json')
        self.make_backup()
        viewer = self.identity.login('qa_viewer', 'viewer-qa-password')
        try:
            with self.assertRaisesRegex(migration.MigrationBlocked, 'administrator'):
                self.rehearse(administrator_token=viewer)
        finally:
            self.identity.logout(viewer)
        self.assertFalse(self.dest.exists())

    def test_backup_tampering_fails_before_destination_created(self):
        self.make_backup()
        (self.backup / 'taraz-orders.sqlite3').write_bytes(b'database tampering')
        with self.assertRaisesRegex(migration.MigrationBlocked, 'SHA256'):
            self.rehearse()
        self.assertFalse(self.dest.exists())

    def test_source_changed_after_backup_fails(self):
        self.make_backup()
        (self.source / 'invoice-templates.json').write_text('{"tampered":true}')
        with self.assertRaisesRegex(migration.MigrationBlocked, 'SHA256'):
            self.rehearse()

    def test_replay_create_only_does_not_overwrite_prior_output(self):
        self.make_backup()
        self.rehearse()
        before = hashes(self.dest)
        with self.assertRaises(FileExistsError):
            self.rehearse()
        self.assertEqual(hashes(self.dest), before)

    def test_preexisting_destination_is_not_touched(self):
        self.make_backup()
        self.dest.mkdir()
        (self.dest / 'untouched.txt').write_text('original', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            self.rehearse()
        self.assertEqual((self.dest / 'untouched.txt').read_text(), 'original')

    def test_concurrent_write_during_backup_blocks_completion(self):
        original = migration._copy_exact
        invoked = False

        def race(src, target, entry):
            nonlocal invoked
            original(src, target, entry)
            if not invoked:
                invoked = True
                (self.source / 'invoice-templates.json').write_text('{"race":true}')

        with patch.object(migration, '_copy_exact', side_effect=race):
            with self.assertRaisesRegex(migration.MigrationBlocked, 'changed'):
                self.make_backup()
        self.assertFalse((self.backup / migration.BACKUP_MARKER).exists())

    def test_wal_or_sqlite_journal_blocks_raw_byte_copy(self):
        (self.source / 'taraz-orders.sqlite3-wal').write_bytes(b'pending data')
        with self.assertRaisesRegex(migration.MigrationBlocked, 'offline input'):
            self.make_backup()

    def test_failed_copy_can_be_rolled_back_without_touching_source(self):
        self.make_backup()
        prior = hashes(self.source)
        original = migration._copy_exact

        def interrupt(src, target, descriptor):
            if src.name == 'taraz-orders.sqlite3':
                raise OSError('synthetic interruption after partial stage')
            return original(src, target, descriptor)

        with patch.object(migration, '_copy_exact', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'synthetic interruption'):
                self.rehearse()
        staged = list(self.root.glob('.taraz-legacy-rehearsal-stage-*'))
        self.assertEqual(len(staged), 1)
        marker_file = staged[0] / migration.REHEARSAL_MARKER
        marker = json.loads(marker_file.read_text(encoding='utf-8'))
        result = migration.rollback_rehearsal(
            staged[0], rehearsal_id=marker['rehearsal_id'],
            marker_sha256=hashlib.sha256(marker_file.read_bytes()).hexdigest())
        self.assertEqual(result['status'], 'ROLLED_BACK')
        self.assertFalse(staged[0].exists())
        self.assertFalse(self.dest.exists())
        self.assertEqual(hashes(self.source), prior)

    def test_partial_rollback_rejects_unknown_concurrent_contents(self):
        self.make_backup()

        def interrupt(src, target, descriptor):
            raise OSError('synthetic interruption')

        with patch.object(migration, '_copy_exact', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.rehearse()
        staged = next(self.root.glob('.taraz-legacy-rehearsal-stage-*'))
        marker_file = staged / migration.REHEARSAL_MARKER
        marker = json.loads(marker_file.read_text())
        (staged / 'unexpected-user-file.txt').write_text('do not remove')
        with self.assertRaisesRegex(migration.MigrationBlocked, 'unknown or modified'):
            migration.rollback_rehearsal(staged,
                 rehearsal_id=marker['rehearsal_id'],
                 marker_sha256=hashlib.sha256(marker_file.read_bytes()).hexdigest())
        self.assertTrue((staged / 'unexpected-user-file.txt').exists())

    def test_non_temp_paths_and_incorrect_declarations_fail_closed(self):
        with self.assertRaises(migration.MigrationBlocked):
            migration.create_legacy_rehearsal_backup(self.source, self.backup)
        with self.assertRaises(migration.MigrationBlocked):
            migration.create_legacy_rehearsal_backup(Path.cwd(), self.backup,
                                                     offline_acknowledged=True,
                                                     synthetic_only=True)
        self.assertFalse(self.backup.exists())


if __name__ == '__main__':
    unittest.main()
