"""Isolated failure and SHA readback tests for the actual Taraz upgrade gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as qa


class UpgradeAcceptanceTests(unittest.TestCase):
    def test_launcher_and_baseline_binary_must_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp)
            root = local / "Programs" / "Taraz"
            exe = root / "versions" / "1.0.0" / "Taraz.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"synthetic-taraz-1.0.0")
            (root / "current-version.txt").write_text("1.0.0\n", encoding="utf-8")
            (root / "Run-Taraz.cmd").write_text('for /f %%v in ("current-version.txt") do start versions\\%TARAZ_VERSION%\\Taraz.exe', encoding="utf-8")
            digest = hashlib.sha256(exe.read_bytes()).hexdigest()
            self.assertEqual(qa.installed_baseline(local, expected_sha=digest)["version"], "1.0.0")
            (root / "current-version.txt").write_text("1.0.1\n", encoding="utf-8")
            with self.assertRaises(qa.AcceptanceBlocked):
                qa.installed_baseline(local, expected_sha=digest)

    def test_inventory_rejects_nonempty_wal_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "qa-roaming"
            root.mkdir()
            (root / "standalone-accounting.sqlite3").write_bytes(b"synthetic")
            wal = root / "standalone-accounting.sqlite3-wal"
            wal.write_bytes(b"nonempty")
            with self.assertRaisesRegex(qa.AcceptanceBlocked, "Nonempty WAL"):
                qa.inventory({"roaming": root})
            wal.unlink()
            other = Path(tmp) / "external"
            other.write_bytes(b"external")
            linked = root / "linked"
            try:
                linked.symlink_to(other)
            except (OSError, NotImplementedError):
                self.skipTest("User cannot make a synthetic symlink")
            with self.assertRaises(qa.AcceptanceBlocked):
                qa.inventory({"roaming": root})

    def test_complete_profile_backup_has_independent_file_and_sqlite_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "qa-roaming"
            root.mkdir()
            db = root / "standalone-accounting.sqlite3"
            conn = sqlite3.connect(db)
            try:
                conn.execute("CREATE TABLE synthetic (id INTEGER PRIMARY KEY, label TEXT)")
                conn.execute("INSERT INTO synthetic VALUES (1,'test-only')")
                conn.commit()
            finally:
                conn.close()
            (root / "local-users.json").write_text('{"version":1,"users":{}}', encoding="utf-8")
            backup = Path(tmp) / "private-backup"
            details = qa.verified_backup({"roaming": root}, backup)
            self.assertEqual(details["fileCount"], 2)
            self.assertTrue(details["independentReadback"])
            qa.independently_verify_backup(backup, {"roaming": root})
            copied = backup / "files" / "roaming" / "local-users.json"
            copied.write_bytes(b"corrupt-copy")
            with self.assertRaisesRegex(qa.AcceptanceBlocked, "SHA/size"):
                qa.independently_verify_backup(backup)

    def test_extra_backup_file_or_changed_live_source_blocks_independent_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "qa-roaming"
            root.mkdir()
            db = root / "standalone-accounting.sqlite3"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE synthetic (k TEXT)")
            conn.close()
            backup = Path(tmp) / "private-backup"
            qa.verified_backup({"roaming": root}, backup)
            db.write_bytes(b"corrupted-real-source-synthetic")
            with self.assertRaisesRegex(qa.AcceptanceBlocked, "Source changed"):
                qa.independently_verify_backup(backup, {"roaming": root})
            (backup / "files" / "roaming" / "unexpected.dat").write_bytes(b"injected")
            with self.assertRaisesRegex(qa.AcceptanceBlocked, "file set"):
                qa.independently_verify_backup(backup)

    def test_disposable_installer_rejects_missing_or_changed_pinned_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            with self.assertRaises(qa.AcceptanceBlocked):
                qa.sandbox_install(output=path / "sandbox", installer_run=path / "nonexistent")


if __name__ == "__main__":
    unittest.main()
