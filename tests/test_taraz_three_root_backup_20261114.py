"""Three-root offline snapshot rehearsal using disposable synthetic data only."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import taraz_three_root_backup_20261114 as backup
from taraz_full_profile_backup_20261114 import FullProfileError


COMPANY = 'a1b2' * 8


def _sqlite(path: Path, *, ledger=False, wal=False):
    with closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute('PRAGMA user_version=1')
        if ledger:
            conn.execute('''CREATE TABLE standalone_accounting(
                id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL,
                state BLOB NOT NULL, digest TEXT NOT NULL)''')
        else:
            conn.execute('CREATE TABLE events(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            conn.execute('INSERT INTO events(payload) VALUES (?)', ('synthetic',))
        if wal:
            conn.execute('PRAGMA journal_mode=WAL')


def _fixture(parent: Path, *, legacy=False):
    roaming = parent / 'source-roaming'
    local = parent / 'source-local'
    bridge = parent / 'source-bridge'
    for path in (roaming, local, bridge):
        path.mkdir()
    if legacy:
        company_dir = roaming
    else:
        company_dir = roaming / 'books' / COMPANY
        company_dir.mkdir(parents=True)
        (roaming / 'companies.json').write_text(json.dumps({
            'version': 1, 'companies': [{
                'id': COMPANY, 'name': 'آزمایش', 'createdAt': '2026-11-14T00:00:00Z'}]}),
            encoding='utf-8')
    _sqlite(company_dir / 'standalone-accounting.sqlite3', ledger=True)
    _sqlite(company_dir / 'taraz-orders.sqlite3')
    _sqlite(company_dir / 'taraz-agent-memory.sqlite3')
    (company_dir / 'invoice-templates.json').write_text(json.dumps({
        'version': 1, 'templates': [], 'defaults': {}}), encoding='utf-8')
    (company_dir / 'local-users.json').write_text(json.dumps({
        'version': 1, 'users': {'tester': {
            'role': 'admin', 'enabled': True, 'salt': '0' * 64,
            'hash': '1' * 64, 'iterations': 600000}}}), encoding='utf-8')
    (local / 'year-archives').mkdir()
    (local / 'year-archives' / '1404.json').write_text('{"synthetic":true}', encoding='utf-8')
    _sqlite(local / 'taraz-local-state.sqlite3')
    (bridge / 'pending').mkdir()
    (bridge / 'reviewed').mkdir()
    (bridge / 'pending' / 'event.json').write_text(
        '{"id":"synthetic-event","financialEventCreated":false}', encoding='utf-8')
    (bridge / 'reviewed' / 'receipt.bin').write_bytes(b'\x00synthetic-bridge\x01')
    _sqlite(bridge / 'taraz-bridge-sync.sqlite3')
    return roaming, local, bridge


class ThreeRootBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='taraz-three-roots-synthetic-')
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.roaming, self.local, self.bridge = _fixture(self.parent)
        self.bundle = self.parent / 'bundle'
        self.destinations = (self.parent / 'rollback-roaming',
                             self.parent / 'rollback-local',
                             self.parent / 'rollback-bridge')

    def create(self):
        return backup.create_three_root_backup(self.roaming, self.local,
                                               self.bridge, self.bundle,
                                               offline_acknowledged=True)

    def restore(self):
        return backup.restore_three_root_backup(self.bundle, *self.destinations,
                                                offline_acknowledged=True)

    def test_all_three_sources_clone_and_bridge_retained(self):
        originals = {
            role: {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in source.rglob('*') if p.is_file() and not p.name.endswith('.sqlite3')}
            for role, source in zip(backup.ROLES, (self.roaming, self.local, self.bridge))}
        report = self.create()
        self.assertEqual(report['mode'], 'registered')
        self.assertEqual(report['roots'], list(backup.ROLES))
        self.assertGreaterEqual(report['sqlite'], 5)
        result = self.restore()
        self.assertEqual(set(result['roots']), set(backup.ROLES))
        for role, dest in zip(backup.ROLES, self.destinations):
            actual = {p.relative_to(dest).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in dest.rglob('*') if p.is_file() and not p.name.endswith('.sqlite3')}
            self.assertEqual(actual, originals[role])
        self.assertEqual((self.destinations[2] / 'reviewed' / 'receipt.bin').read_bytes(),
                         b'\x00synthetic-bridge\x01')
        self.assertEqual(backup.verify_three_root_backup(self.bundle)['files'], report['files'])

    def test_legacy_unregistered_roaming_source(self):
        # Entirely new three roots in the same disposable parent.
        parent = self.parent / 'legacy'
        parent.mkdir()
        roaming, local, bridge = _fixture(parent, legacy=True)
        result = backup.create_three_root_backup(roaming, local, bridge,
                                                 parent / 'snapshot', offline_acknowledged=True)
        self.assertEqual(result['mode'], 'legacy')
        self.assertEqual(result['companies'], 0)
        rollback = [parent / ('restored-' + item) for item in backup.ROLES]
        restored = backup.restore_three_root_backup(parent / 'snapshot', *rollback,
                                                    offline_acknowledged=True)
        self.assertEqual(restored['mode'], 'legacy')
        self.assertTrue((rollback[0] / 'standalone-accounting.sqlite3').is_file())

    def test_missing_root_blocks_before_any_write(self):
        missing = self.parent / 'missing-local-bridge'
        with self.assertRaises((FileNotFoundError, FullProfileError)):
            backup.create_three_root_backup(self.roaming, self.local, missing,
                                            self.bundle, offline_acknowledged=True)
        self.assertFalse(self.bundle.exists())

    def test_tamper_blocks_restore_without_publication(self):
        self.create()
        file = self.bundle / 'local_bridge' / 'reviewed' / 'receipt.bin'
        file.write_bytes(b'changed')
        with self.assertRaises(backup.ThreeRootBackupError):
            backup.verify_three_root_backup(self.bundle)
        with self.assertRaises(backup.ThreeRootBackupError):
            self.restore()
        self.assertTrue(all(not dest.exists() for dest in self.destinations))

    def test_unmanifested_extra_member_blocks(self):
        self.create()
        (self.bundle / 'local_bridge' / 'extra.txt').write_text('unlisted')
        with self.assertRaises(backup.ThreeRootBackupError):
            backup.verify_three_root_backup(self.bundle)

    def test_interrupted_snapshot_does_not_publish_marker(self):
        copy = backup._stable_file_copy
        calls = 0
        def interrupted(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('Synthetic copy interruption')
            return copy(*args, **kwargs)
        with patch.object(backup, '_stable_file_copy', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.create()
        self.assertTrue(self.bundle.is_dir())
        self.assertFalse((self.bundle / backup.MANIFEST_NAME).exists())

    def test_source_mutation_during_copy_blocks_completion(self):
        original = backup._stable_file_copy
        changed = False
        def mutate(*args, **kwargs):
            nonlocal changed
            original(*args, **kwargs)
            if not changed:
                changed = True
                (self.bridge / 'pending' / 'event.json').write_text('{"mutated":true}')
        with patch.object(backup, '_stable_file_copy', side_effect=mutate):
            with self.assertRaises(backup.ThreeRootBackupError):
                self.create()
        self.assertFalse((self.bundle / backup.MANIFEST_NAME).exists())

    def test_live_sqlite_wal_rows_captured(self):
        file = self.bridge / 'taraz-bridge-sync.sqlite3'
        db = sqlite3.connect(file, isolation_level=None)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('INSERT INTO events(payload) VALUES (?)', ('uncheckpointed-row',))
            self.create()
            with closing(sqlite3.connect(self.bundle / 'local_bridge' / file.name)) as copied:
                self.assertEqual(copied.execute('SELECT COUNT(*) FROM events').fetchone()[0], 2)
        finally:
            db.close()

    def test_cross_machine_principal_blocks_verify_and_restore(self):
        self.create()
        with patch.object(backup, '_principal', return_value={
                'machine': 'other-pc', 'sid': 'S-1-5-21-999'}):
            with self.assertRaisesRegex(backup.ThreeRootBackupError, 'DPAPI recovery BLOCKED'):
                backup.verify_three_root_backup(self.bundle)
            with self.assertRaisesRegex(backup.ThreeRootBackupError, 'DPAPI recovery BLOCKED'):
                self.restore()
        self.assertTrue(all(not dest.exists() for dest in self.destinations))

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI only')
    def test_same_principal_real_dpapi_chat_restore(self):
        from taraz_ai_chat_store import TarazAiChatStore
        company = self.roaming / 'books' / COMPANY
        chat = TarazAiChatStore(company, tenant_id=COMPANY, actor='tester')
        created = chat.create('Synthetic DPAPI conversation', client_request_id='1' * 32)
        cid = created['conversationId']
        chat.append(cid, 'Synthetic question', 'Synthetic answer',
                    proposal={'approved': False}, client_request_id='2' * 32,
                    request_payload={'action': 'send', 'conversationId': cid,
                                     'text': 'Synthetic question'})
        self.create()
        self.restore()
        restored = TarazAiChatStore(self.destinations[0] / 'books' / COMPANY,
                                    tenant_id=COMPANY, actor='tester').read(cid)
        self.assertEqual(len(restored['messages']), 2)
        self.assertEqual(len(restored['executions']), 1)

    def test_hardlinks_refused(self):
        try:
            os.link(self.bridge / 'reviewed' / 'receipt.bin', self.bridge / 'reviewed' / 'alias.bin')
        except OSError:
            self.skipTest('Hardlinks unavailable on synthetic filesystem')
        with self.assertRaises(FullProfileError):
            self.create()
        self.assertFalse(self.bundle.exists())

    def test_symlinks_refused(self):
        try:
            os.symlink(self.local / 'year-archives', self.bridge / 'linked', target_is_directory=True)
        except OSError:
            self.skipTest('Symlinks unavailable under current Windows permissions')
        with self.assertRaises(FullProfileError):
            self.create()
        self.assertFalse(self.bundle.exists())

    def test_rollback_destination_existing_does_not_overwrite(self):
        self.create()
        self.destinations[1].mkdir()
        (self.destinations[1] / 'operator-file.txt').write_text('keep')
        with self.assertRaises(FileExistsError):
            self.restore()
        self.assertEqual((self.destinations[1] / 'operator-file.txt').read_text(), 'keep')
        self.assertFalse(self.destinations[0].exists())

    def test_interrupted_restore_does_not_publish_any_target(self):
        self.create()
        copied = backup._stable_file_copy
        calls = 0
        def interrupt(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('Synthetic restore interruption')
            return copied(*args, **kwargs)
        with patch.object(backup, '_stable_file_copy', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.restore()
        self.assertTrue(all(not dest.exists() for dest in self.destinations))

    def test_partial_publication_never_overwrites_or_erases_owned_clones(self):
        self.create()
        real = backup._publish_new_directory
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('Synthetic second publication failure')
            return real(*args, **kwargs)
        with patch.object(backup, '_publish_new_directory', side_effect=fail_second):
            with self.assertRaises(backup.PartialThreeRootRestoreError) as failed:
                self.restore()
        self.assertEqual(failed.exception.published, ('roaming_taraz',))
        self.assertTrue(self.destinations[0].is_dir())
        self.assertFalse(self.destinations[1].exists())
        self.assertFalse(self.destinations[2].exists())
        self.assertTrue((self.destinations[0] / 'books' / COMPANY / 'local-users.json').exists())

    def test_offline_is_explicit_not_inferred(self):
        with self.assertRaises(PermissionError):
            backup.create_three_root_backup(self.roaming, self.local, self.bridge, self.bundle)
        self.create()
        with self.assertRaises(PermissionError):
            backup.restore_three_root_backup(self.bundle, *self.destinations)


if __name__ == '__main__':
    unittest.main()
