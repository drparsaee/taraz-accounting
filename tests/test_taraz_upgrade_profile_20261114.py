"""Synthetic-only adversarial tests for independent Taraz 1.0.4→1.0.6 gate."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import taraz_upgrade_profile_safety_20261114 as safety


PRIVATE_QA = ROOT / "tests" / "output" / "taraz-upgrade-private-20261114"


class SyntheticBackupGate(unittest.TestCase):
    def setUp(self):
        PRIVATE_QA.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix="qa-case-", dir=PRIVATE_QA))
        self.roots = {label: self.work / "source" / label for label in safety.LABELS}
        for path in self.roots.values():
            path.mkdir(parents=True)
        self.ledger = self.roots["roaming"] / "standalone-accounting.sqlite3"
        with closing(sqlite3.connect(self.ledger)) as connection:
            connection.execute("CREATE TABLE synthetic_book (id INTEGER PRIMARY KEY, payload TEXT)")
            connection.execute("INSERT INTO synthetic_book VALUES (1, 'qa-only-synthetic')")
            connection.execute("PRAGMA user_version=7")
            connection.commit()
        self.orders = self.roots["roaming"] / "taraz-orders.sqlite3"
        with closing(sqlite3.connect(self.orders)) as connection:
            connection.execute("CREATE TABLE synthetic_orders (id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO synthetic_orders VALUES (8)")
            connection.commit()
        (self.roots["roaming"] / "invoice-templates.json").write_text(
            '{"qa":"template"}', encoding="utf-8")
        (self.roots["local"] / "Parsian-Migration-qa").mkdir()
        (self.roots["local"] / "Parsian-Migration-qa" / "migration.json").write_text(
            '{"qa":"migration"}', encoding="utf-8")
        (self.roots["bridge"] / "pending").mkdir()
        (self.roots["bridge"] / "reviewed").mkdir()
        (self.roots["bridge"] / "pending" / "message.json").write_text(
            '{"qa":"queued"}', encoding="utf-8")
        self.backup = self.work / "qa-snapshot"
        self.restore = self.work / "qa-restore"

    def tearDown(self):
        # Only a test-created, uniquely named synthetic QA fixture is removed.
        shutil.rmtree(self.work)

    def snapshot(self):
        return safety.make_synthetic_snapshot(self.roots, self.backup)

    def test_complete_roundtrip_preserves_sqlite_and_sidecar_data(self):
        created = self.snapshot()
        self.assertEqual(created["status"], "VERIFIED_QA_SNAPSHOT")
        self.assertEqual(created["sqliteCount"], 2)
        self.assertEqual(created["fileCount"], 5)
        self.assertEqual(len(created["manifestSha256"]), 64)
        result = safety.restore_isolated(
            self.backup, self.restore, expected_sha=created["manifestSha256"])
        self.assertEqual(result["status"], "RESTORED_ISOLATED_QA")
        with closing(sqlite3.connect(self.restore / "roaming" / self.ledger.name)) as connection:
            self.assertEqual(connection.execute(
                "SELECT payload FROM synthetic_book").fetchone(), ("qa-only-synthetic",))
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 7)
        with closing(sqlite3.connect(self.restore / "roaming" / self.orders.name)) as connection:
            self.assertEqual(connection.execute(
                "SELECT id FROM synthetic_orders").fetchone(), (8,))
        self.assertEqual((self.restore / "roaming" / "invoice-templates.json").read_bytes(),
                         (self.roots["roaming"] / "invoice-templates.json").read_bytes())
        self.assertTrue((self.restore / "bridge" / "reviewed").is_dir())
        self.assertEqual(safety.verify_snapshot(self.backup), created)

    def test_tampered_snapshot_member_is_rejected(self):
        created = self.snapshot()
        target = self.backup / "files" / "bridge" / "pending" / "message.json"
        target.write_text('{"qa":"tampered"}', encoding="utf-8")
        with self.assertRaises(safety.UpgradeBlocked):
            safety.restore_isolated(self.backup, self.restore,
                                    expected_sha=created["manifestSha256"])
        self.assertFalse(self.restore.exists())

    def test_modified_manifest_even_with_valid_json_is_rejected(self):
        created = self.snapshot()
        manifest = self.backup / "snapshot-manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["complete"] = False
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(safety.UpgradeBlocked):
            safety.restore_isolated(self.backup, self.restore,
                                    expected_sha=created["manifestSha256"])

    def test_snapshot_must_be_create_only(self):
        self.snapshot()
        with self.assertRaises(safety.UpgradeBlocked):
            self.snapshot()
        self.assertTrue((self.backup / "snapshot-manifest.json").is_file())

    def test_restore_must_be_create_only(self):
        created = self.snapshot()
        safety.restore_isolated(self.backup, self.restore,
                                expected_sha=created["manifestSha256"])
        with self.assertRaises(safety.UpgradeBlocked):
            safety.restore_isolated(self.backup, self.restore,
                                    expected_sha=created["manifestSha256"])

    def test_nonempty_wal_fails_before_any_snapshot_output(self):
        (self.roots["roaming"] / (self.ledger.name + "-wal")).write_bytes(b"ACTIVE_WAL")
        with self.assertRaisesRegex(safety.UpgradeBlocked, "WAL/SHM/journal"):
            self.snapshot()
        self.assertFalse(self.backup.exists())

    def test_nonempty_shm_fails_before_any_snapshot_output(self):
        (self.roots["roaming"] / (self.ledger.name + "-shm")).write_bytes(b"ACTIVE_SHM")
        with self.assertRaisesRegex(safety.UpgradeBlocked, "WAL/SHM/journal"):
            self.snapshot()
        self.assertFalse(self.backup.exists())

    def test_corrupt_database_does_not_publish_manifest(self):
        self.orders.write_bytes(b"This isn't a SQLite database")
        with self.assertRaises((safety.UpgradeBlocked, sqlite3.DatabaseError)):
            self.snapshot()
        self.assertFalse((self.backup / "snapshot-manifest.sha256").exists())

    def test_source_change_during_backup_blocks_completion(self):
        original = safety._backup_sqlite
        changed = [False]

        def mutate_once(source, target):
            original(source, target)
            if not changed[0]:
                changed[0] = True
                with closing(sqlite3.connect(self.ledger)) as connection:
                    connection.execute("INSERT INTO synthetic_book VALUES (2, 'late')")
                    connection.commit()

        with patch.object(safety, "_backup_sqlite", mutate_once):
            with self.assertRaisesRegex(safety.UpgradeBlocked, "Source changed"):
                self.snapshot()
        self.assertFalse((self.backup / "snapshot-manifest.sha256").exists())

    def test_new_unlisted_file_blocks_verification(self):
        self.snapshot()
        (self.backup / "files" / "local" / "extra.json").write_text("unexpected", encoding="utf-8")
        with self.assertRaises(safety.UpgradeBlocked):
            safety.verify_snapshot(self.backup)

    def test_inplace_restore_inside_snapshot_forbidden(self):
        created = self.snapshot()
        with self.assertRaises(safety.UpgradeBlocked):
            safety.restore_isolated(self.backup, self.backup / "files" / "qa-restore",
                                    expected_sha=created["manifestSha256"])

    def test_symlink_source_refused_if_platform_supports_it(self):
        source = self.roots["local"] / "shortcut.json"
        try:
            source.symlink_to(self.roots["roaming"] / "invoice-templates.json")
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation is not available for this Windows account")
        with self.assertRaises(safety.UpgradeBlocked):
            self.snapshot()
        self.assertFalse(self.backup.exists())

    def test_missing_root_is_fail_closed(self):
        self.roots["bridge"].rename(self.roots["bridge"].with_name("bridge-missing"))
        with self.assertRaises(safety.UpgradeBlocked):
            self.snapshot()
        self.assertFalse(self.backup.exists())


if __name__ == "__main__":
    unittest.main()
