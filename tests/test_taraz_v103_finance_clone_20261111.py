"""Fail-closed finance clone contract tests; all writes use synthetic temp data."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v103_finance_clone_20261111 as qa
from standalone_accounting import StandaloneAccountingStore


class FinanceCloneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-finance-clone-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self):
        source = self.root / "offline-synthetic" / "files"
        finance = source / "roaming" / "standalone-accounting.sqlite3"
        finance.parent.mkdir(parents=True)
        StandaloneAccountingStore(finance, default_currency="RIAL")
        other = source / "local" / "synthetic-setting.txt"
        other.parent.mkdir(parents=True)
        other.write_text("invented test-only content", encoding="utf-8")
        manifest = {"files": {}, "sqliteChecks": {
            qa.FINANCE: {"integrityCheck": "ok", "schemaVersion": 1}}}
        for path in (finance, other):
            rel = path.relative_to(source).as_posix()
            manifest["files"][rel] = {"bytes": path.stat().st_size,
                                      "sha256": qa.sha(path)}
        return source, manifest

    def test_traversal_and_noncanonical_member_paths_refused(self):
        bad = ("../roaming/db", "roaming/../db", "/roaming/db",
               "roaming\\finance", "roaming//db", "C:/private",
               "shared/db", "roaming/evil*.sqlite3", "roaming/folder./db")
        for member in bad:
            with self.subTest(member=member), self.assertRaises(qa.FinanceCloneBlocked):
                qa.safe_relative(member)
        self.assertEqual(str(qa.safe_relative(qa.FINANCE)).replace("\\", "/"), qa.FINANCE)

    def test_pinned_candidate_and_backup_attestation(self):
        # No real finance rows are read. Both SHA pins and backup metadata
        # are verified as immutable evidence.
        self.assertEqual(qa.candidate_pin(), qa.EXPECTED_CANDIDATE_SHA)
        manifest, report = qa.attestation()
        self.assertEqual(manifest["fileCount"], qa.EXPECTED_FILE_COUNT)
        self.assertEqual(len(manifest["sqliteChecks"]), qa.EXPECTED_SQLITE_COUNT)
        self.assertTrue(report["backup"]["independentReadback"])

    def test_missing_unpinned_backup_fails_before_any_clone(self):
        missing = self.root / "no-backup"
        with self.assertRaises(qa.FinanceCloneBlocked):
            qa.attestation(missing)

    def test_forged_backup_json_not_trusted_even_with_plausible_metadata(self):
        fake = self.root / "untrusted-backup"
        (fake / "files").mkdir(parents=True)
        (fake / "snapshot-manifest.json").write_text(json.dumps({
            "schemaVersion": 1, "fileCount": 181, "totalBytes": 124011875,
            "sqliteChecks": {}, "files": {}}), encoding="utf-8")
        (fake / "backup-acceptance-report.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(qa.FinanceCloneBlocked, "pin mismatch"):
            qa.attestation(fake)

    def test_tamper_and_extra_clone_file_rejected(self):
        source, manifest = self.fixture()
        entries = manifest["files"]
        before = qa.inventory_files(source, entries)
        self.assertEqual(len(before), 2)
        extra = source / "roaming" / "unexpected.txt"
        extra.write_text("synthetic unexpected", encoding="utf-8")
        with self.assertRaisesRegex(qa.FinanceCloneBlocked, "Undeclared"):
            qa.inventory_files(source, entries)
        extra.unlink()
        target = source / "local" / "synthetic-setting.txt"
        target.write_bytes(b"TAMPER")
        with self.assertRaisesRegex(qa.FinanceCloneBlocked, "SHA/length"):
            qa.inventory_files(source, entries)

    def test_copy_immutable_read_only_schema_revision_and_digest(self):
        source, manifest = self.fixture()
        dst = self.root / "disposable"
        qa.clone_snapshot(source, dst, manifest["files"])
        first = qa.inventory_files(dst, manifest["files"])
        with patch.object(qa, "EXPECTED_SQLITE_COUNT", 1):
            observed = qa.finance_sqlite_invariants(dst, manifest)
        self.assertEqual(len(observed), 1)
        with closing(qa._open_readonly_sqlite(dst / qa.FINANCE)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (1,))
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("CREATE TABLE impossible_write (x INTEGER)")
        self.assertEqual(first, qa.inventory_files(dst, manifest["files"]))
        self.assertEqual({k: v[:2] for k, v in first.items()},
                         {k: v[:2] for k, v in qa.inventory_files(source, manifest["files"]).items()})

    def test_corrupted_sqlite_and_false_schema_witness_fail_closed(self):
        source, manifest = self.fixture()
        dst = self.root / "disposable"
        qa.clone_snapshot(source, dst, manifest["files"])
        bad_manifest = json.loads(json.dumps(manifest))
        bad_manifest["sqliteChecks"][qa.FINANCE]["schemaVersion"] = 999
        with patch.object(qa, "EXPECTED_SQLITE_COUNT", 1):
            with self.assertRaisesRegex(qa.FinanceCloneBlocked, "schema version"):
                qa.finance_sqlite_invariants(dst, bad_manifest)
        (dst / qa.FINANCE).write_bytes(b"NOT-SQLITE-SYNTHETIC")
        with patch.object(qa, "EXPECTED_SQLITE_COUNT", 1):
            with self.assertRaises(qa.FinanceCloneBlocked):
                qa.finance_sqlite_invariants(dst, manifest)

    def test_only_invented_synthetic_ledger_posting(self):
        source, manifest = self.fixture()
        before = qa.inventory_files(source, manifest["files"])
        result = qa.synthetic_transaction_test(self.root)
        self.assertTrue(result["transactionsOnSyntheticLedgerOnly"])
        self.assertEqual(result["newRevisions"], 4)
        self.assertTrue(result["idempotentReplayStable"])
        self.assertTrue(result["staleRevisionRejected"])
        self.assertEqual(before, qa.inventory_files(source, manifest["files"]))

    def test_offline_clone_only_and_report_excludes_private_content(self):
        source = Path(qa.__file__).read_text(encoding="utf-8")
        self.assertIn("mode=ro&immutable=1", source)
        self.assertIn("PRAGMA query_only=ON", source)
        self.assertIn("shutil.rmtree(clone)", source)
        self.assertNotIn("os.startfile(", source)
        self.assertNotIn("subprocess.Popen(", source)
        self.assertNotIn("source_records", source)
        self.assertFalse(any(arg in source for arg in (
            'os.environ["APPDATA"]', 'os.environ["LOCALAPPDATA"]',
            "Start-Process", "SwitchDesktop(", "registry.SetValue")))

    def test_audit_blocks_unpinned_source_before_creating_output(self):
        out = self.root / "not-created"
        with self.assertRaises(qa.FinanceCloneBlocked):
            qa.audit(backup=self.root / "absent", destination=out)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
