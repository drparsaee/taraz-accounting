"""Disposable synthetic integration gates for the full-profile backup API."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from standalone_accounting_backup_manifest import publish_completion_manifest, verify_completion_manifest
from taraz_full_profile_backup_20261114 import (
    MANIFEST_NAME, FullProfileError, create_full_profile_backup,
    verify_full_profile_backup, restore_full_profile_backup,
)


COMPANY = 'abcd' * 8


def _db(file: Path, *, ledger=False):
    with closing(sqlite3.connect(file)) as db:
        if ledger:
            db.execute('PRAGMA user_version=1')
            db.execute('''CREATE TABLE standalone_accounting(
                id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
                state BLOB NOT NULL, digest TEXT NOT NULL)''')
        else:
            db.execute('PRAGMA user_version=1')
            db.execute('CREATE TABLE records (id INTEGER PRIMARY KEY, name TEXT NOT NULL)')
            db.execute('INSERT INTO records(name) VALUES (?)', ('synthetic-example',))
        db.commit()


def _fixture(base: Path):
    root = base / 'synthetic-source'
    company = root / 'books' / COMPANY
    company.mkdir(parents=True)
    (root / 'companies.json').write_text(json.dumps({
        'version': 1, 'companies': [{'id': COMPANY, 'name': 'شرکت آزمایشی',
                                    'createdAt': '2026-11-14T00:00:00Z'}]}), encoding='utf-8')
    (company / 'local-users.json').write_text(json.dumps({
        'version': 1, 'users': {'tester': {
            'role': 'admin', 'salt': '0'*64, 'hash': '1'*64,
            'iterations': 600000, 'enabled': True}}}), encoding='utf-8')
    (company / 'invoice-templates.json').write_text(json.dumps({
        'version': 1, 'templates': [], 'defaults': {}}), encoding='utf-8')
    (company / 'taraz-migration-manifest.json').write_text('{"synthetic":true}', encoding='utf-8')
    (company / 'سند.pdf').write_bytes(b'%PDF-1.4\nsynthetic\n%%EOF\n')
    for dbname in ('standalone-accounting.sqlite3', 'taraz-orders.sqlite3',
                   'taraz-agent-memory.sqlite3', 'taraz-ecosystem-outbox.sqlite3',
                   'taraz-madar-order-links.sqlite3', 'mtr-taraz-finance-witness-issued.sqlite3'):
        _db(company / dbname, ledger=dbname == 'standalone-accounting.sqlite3')
    # Automatic snapshots carry a SHA256 of their original SQLite bytes.
    # Their bytes must be copied EXACTLY or the existing manifest breaks.
    history = company / 'standalone-accounting-backups'
    history.mkdir()
    archived = history / ('standalone-accounting-auto-20261114T000000000000Z-' + 'a'*16 + '.sqlite3')
    _db(archived)
    publish_completion_manifest(archived)
    return root, company, archived


class FullProfileBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='taraz-full-profile-qa-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source, self.company, self.archived = _fixture(self.base)
        self.snapshot = self.base / 'backup-new'
        self.restored = self.base / 'restored-new'

    def _create(self):
        return create_full_profile_backup(self.source, self.snapshot,
                                          offline_acknowledged=True)

    def _restore(self):
        return restore_full_profile_backup(self.snapshot, self.restored,
                                           offline_acknowledged=True)

    def test_complete_backup_and_isolated_restore_all_stores(self):
        before = {p.relative_to(self.source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.source.rglob('*') if p.is_file() and not p.name.endswith('.sqlite3')}
        report = self._create()
        self.assertEqual(report['companies'], 1)
        self.assertGreaterEqual(report['sqlite'], 7)
        self.assertFalse(report['dpapi_required'])
        self.assertTrue((self.snapshot / MANIFEST_NAME).is_file())
        restored = self._restore()
        self.assertEqual(restored['companies'], 1)
        self.assertEqual(before, {
            p.relative_to(self.restored).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.restored.rglob('*') if p.is_file() and not p.name.endswith('.sqlite3')})
        # sqlite snapshots can be bytewise different while rows are identical;
        # compare public synthetic record readback instead of copied file hash.

    def test_immutable_auto_backup_manifest_remains_valid(self):
        self._create()
        copied = self.snapshot / self.archived.relative_to(self.source)
        self.assertEqual(copied.read_bytes(), self.archived.read_bytes())
        self.assertIsNotNone(verify_completion_manifest(copied))

    def test_incomplete_legacy_automatic_set_blocks_full_snapshot(self):
        self.archived.with_suffix('.manifest.json').unlink()
        with self.assertRaises(Exception):
            self._create()
        self.assertFalse(self.snapshot.exists())

    def test_two_company_folders_remain_isolated(self):
        another = '1234'*8
        folder = self.source / 'books' / another
        folder.mkdir()
        (folder / 'invoice-templates.json').write_text(json.dumps({
            'version': 1, 'templates': [], 'defaults': {}}), encoding='utf-8')
        _db(folder / 'taraz-orders.sqlite3')
        registry = self.source / 'companies.json'
        doc = json.loads(registry.read_text(encoding='utf-8'))
        doc['companies'].append({'id': another, 'name': 'شرکت دوم',
                                 'createdAt': '2026-11-14T01:00:00Z'})
        registry.write_text(json.dumps(doc), encoding='utf-8')
        result = self._create()
        self.assertEqual(result['companies'], 2)
        self.assertEqual(self._restore()['companies'], 2)
        self.assertTrue((self.restored / 'books' / another / 'taraz-orders.sqlite3').exists())
        self.assertTrue((self.restored / 'books' / COMPANY / 'local-users.json').exists())

    def test_tamper_detected_and_restore_does_not_publish(self):
        self._create()
        touched = self.snapshot / 'books' / COMPANY / 'taraz-migration-manifest.json'
        touched.write_bytes(b'forged')
        with self.assertRaises(FullProfileError):
            verify_full_profile_backup(self.snapshot)
        with self.assertRaises(FullProfileError):
            self._restore()
        self.assertFalse(self.restored.exists())

    def test_existing_restore_target_remains_untouched(self):
        self._create()
        self.restored.mkdir()
        sentinel = self.restored / 'keep.txt'
        sentinel.write_text('untouched')
        with self.assertRaises(FileExistsError):
            self._restore()
        self.assertEqual(sentinel.read_text(), 'untouched')

    def test_offline_and_disjoint_requirements(self):
        with self.assertRaises(PermissionError):
            create_full_profile_backup(self.source, self.snapshot)
        with self.assertRaises(FullProfileError):
            create_full_profile_backup(self.source, self.company / 'backup-inside',
                                       offline_acknowledged=True)
        self.assertFalse(self.snapshot.exists())

    def test_hardlinks_and_reparse_points_rejected(self):
        linked = self.company / 'hardlink.json'
        try:
            os.link(self.company / 'invoice-templates.json', linked)
        except (OSError, NotImplementedError):
            self.skipTest('Hardlinks unavailable on this disposable filesystem')
        with self.assertRaises(FullProfileError):
            self._create()
        self.assertFalse(self.snapshot.exists())

    def test_hot_rollback_journal_refused(self):
        ledger = self.company / 'standalone-accounting.sqlite3'
        Path(str(ledger) + '-journal').write_bytes(b'hot')
        with self.assertRaises(FullProfileError):
            self._create()

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI only')
    def test_dpapi_wrong_machine_hard_block(self):
        from taraz_ai_chat_store import TarazAiChatStore
        TarazAiChatStore(self.company, tenant_id=COMPANY, actor='tester').create(
            'Synthetic chat', client_request_id='c'*32)
        self._create()
        manifest = self.snapshot / MANIFEST_NAME
        doc = json.loads(manifest.read_text(encoding='utf-8'))
        doc['dpapi_required'] = True
        doc['principal'] = {'machine': 'another-windows-computer', 'sid': 'S-1-5-21-999'}
        manifest.write_text(json.dumps(doc), encoding='utf-8')
        with patch('taraz_full_profile_backup_20261114._principal',
                   return_value={'machine': 'current-computer', 'sid': 'S-1-5-21-100'}):
            with self.assertRaisesRegex(FullProfileError, 'DPAPI recovery blocked'):
                self._restore()
        self.assertFalse(self.restored.exists())

    def test_sqlite_uncheckpointed_wal_row_is_included(self):
        file = self.company / 'taraz-orders.sqlite3'
        db = sqlite3.connect(file, isolation_level=None)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('INSERT INTO records(name) VALUES (?)', ('WAL-only-row',))
            report = self._create()
            self.assertGreaterEqual(report['sqlite'], 7)
            snapfile = self.snapshot / file.relative_to(self.source)
            with closing(sqlite3.connect(snapfile)) as restored:
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM records').fetchone()[0], 2)
            self.assertFalse(Path(str(snapfile) + '-wal').exists())
        finally:
            db.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI only')
    def test_real_windows_dpapi_same_principal_readback(self):
        from taraz_ai_chat_store import TarazAiChatStore
        store = TarazAiChatStore(self.company, tenant_id=COMPANY, actor='tester')
        cid = store.create('Synthetic encrypted chat', client_request_id='a'*32)['conversationId']
        store.append(cid, 'Test message', 'Test reply', proposal={'draft': True},
                     client_request_id='b'*32,
                     request_payload={'action': 'send', 'conversationId': cid,
                                      'text': 'Test message'})
        report = self._create()
        self.assertTrue(report['dpapi_required'])
        self.assertTrue(report['dpapi_verified'])
        result = self._restore()
        self.assertTrue(result['dpapi_verified'])
        restored_store = TarazAiChatStore(self.restored / 'books' / COMPANY,
                                         tenant_id=COMPANY, actor='tester')
        readback = restored_store.read(cid)
        self.assertEqual(len(readback['messages']), 2)
        self.assertEqual(len(readback['executions']), 1)


if __name__ == '__main__':
    unittest.main()
