"""Regression for preservation of pre-upgrade automatic backup history.

The real 1.0.4 clone lost old SQLite+manifest pairs during frozen startup.
These tests only create disposable synthetic books and never inspect APPDATA.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import unittest

from standalone_accounting import StandaloneAccountingStore
from standalone_accounting_auto_backup import AutomaticStandaloneBackups
from standalone_accounting_backup_manifest import verify_completion_manifest


class LegacyBackupRetentionTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='qa-legacy-backup-retention-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'qa' / 'Taraz'
        self.root.mkdir(parents=True)
        book = StandaloneAccountingStore(
            self.root / 'standalone-accounting.sqlite3', default_currency='RIAL')
        book.command({'type': 'party.register', 'eventId': 'qa-retention-1',
                      'partyId': 'qa-party-1', 'kind': 'customer', 'name': 'Synthetic'},
                     actor='qa', accounts={'qa': {'username': 'qa', 'role': 'admin'}},
                     expected_revision=0, now='2026-11-14T00:00:00Z')

    def test_pending_legacy_must_preserve_every_existing_backup(self):
        previous = AutomaticStandaloneBackups(self.root, max_backups=60,
                                              plaintext_acknowledged=True)
        first, second = previous.backup_now(), previous.backup_now()
        old = {p: (hashlib.sha256(p.read_bytes()).hexdigest(),
                   hashlib.sha256(p.with_suffix('.manifest.json').read_bytes()).hexdigest())
               for p in (first, second)}
        pending = AutomaticStandaloneBackups(self.root, max_backups=1,
            plaintext_acknowledged=True, preserve_existing=True)
        third, fourth = pending.backup_now(), pending.backup_now()
        self.assertEqual(len(pending._managed_files()), 4)
        for path, (data_sha, manifest_sha) in old.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), data_sha)
            self.assertEqual(hashlib.sha256(path.with_suffix('.manifest.json').read_bytes()).hexdigest(),
                             manifest_sha)
            verify_completion_manifest(path)
        self.assertTrue(third.exists() and fourth.exists())

    def test_default_retention_still_rotates_only_managed_backups(self):
        normal = AutomaticStandaloneBackups(self.root, max_backups=1,
                                            plaintext_acknowledged=True)
        first, second = normal.backup_now(), normal.backup_now()
        self.assertFalse(first.exists())
        self.assertFalse(first.with_suffix('.manifest.json').exists())
        self.assertTrue(second.is_file())
        verify_completion_manifest(second)


if __name__ == '__main__':
    unittest.main()
