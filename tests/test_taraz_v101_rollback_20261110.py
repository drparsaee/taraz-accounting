"""Synthetic Windows roundtrip for a separate, fail-closed Taraz rollback."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import create_taraz_v101_rollback_20261110 as rescue


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(root: Path) -> tuple[Path, Path, dict]:
    local = root / "fake-local"
    target = local / "Programs" / "Taraz"
    old = target / "versions" / "1.0.0" / "Taraz.exe"
    new = target / "versions" / "1.0.1" / "Taraz.exe"
    for file, value in (
        (old, b"synthetic-program-old-1.0.0"),
        (new, b"synthetic-program-new-1.0.1"),
        (target / "Run-Taraz.cmd", b"synthetic versioned launcher"),
        (target / "current-version.txt", b"1.0.1\r\n"),
        (target / "current-version-pre-1.0.1.txt", b"1.0.0\r\n"),
    ):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(value)
    backup = root / "fake-private-backup"
    files = backup / "files"
    entries = {}
    for rel, value in (
        ("roaming/standalone-accounting.sqlite3", b"synthetic test snapshot"),
        ("local/readme.txt", b"synthetic local"),
        ("bridge/empty.json", b"{}"),
    ):
        file = files / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(value)
        entries[rel] = {"bytes": len(value), "mtimeNs": 0, "sha256": sha(file)}
    amount = sum(entry["bytes"] for entry in entries.values())
    manifest = {
        "schemaVersion": 1, "sourceCategory": "offline-Taraz-user-data",
        "fileCount": len(entries), "totalBytes": amount,
        "verifiedNoOverwrite": True, "allFilesIncluded": True,
        "files": entries,
        "sqliteChecks": {"roaming/standalone-accounting.sqlite3": {
            "integrityCheck": "ok", "schemaVersion": 1}},
    }
    m = backup / "snapshot-manifest.json"
    m.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report = backup / "backup-acceptance-report.json"
    report.write_text(json.dumps({
        "status": "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING",
        "installedBefore": "1.0.0",
        "backup": {"independentReadback": True, "fileCount": len(entries),
                   "sqliteValidatedCount": 1}},
        indent=2), encoding="utf-8")
    script = root / "Rollback-Taraz-V101.ps1"
    script.write_text(rescue.render(
        backup_root=backup,
        backup_report_sha=sha(report), backup_manifest_sha=sha(m),
        old_exe_sha=sha(old), new_exe_sha=sha(new),
        launcher_sha=sha(target / "Run-Taraz.cmd"),
        pre_pointer_sha=sha(target / "current-version-pre-1.0.1.txt"),
        file_count=len(entries), total_bytes=amount, sqlite_count=1,
    ), encoding="utf-8")
    return script, backup, {"root": target, "local": local, "old": old, "new": new,
                            "manifest": m, "backup_file": files / "roaming/standalone-accounting.sqlite3"}


def call_script(script: Path, local: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(local)
    return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", str(script), *args], env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=40)


@unittest.skipUnless(os.name == "nt", "Windows file replacement is required")
class RollbackSyntheticWindowsTests(unittest.TestCase):
    def test_stable_dryrun_apply_and_idempotent_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            script, _, paths = make_fixture(Path(temp))
            old_hash, new_hash = sha(paths["old"]), sha(paths["new"])
            backup_hash = sha(paths["backup_file"])
            dry = call_script(script, paths["local"])
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertIn("READY_FOR_ATOMIC_ROLLBACK_TO_1.0.0", dry.stdout)
            self.assertEqual((paths["root"] / "current-version.txt").read_text().strip(), "1.0.1")
            apply = call_script(script, paths["local"], "-Apply")
            self.assertEqual(apply.returncode, 0, apply.stderr)
            self.assertIn("ROLLED_BACK_TO_1.0.0", apply.stdout)
            self.assertEqual((paths["root"] / "current-version.txt").read_bytes(), b"1.0.0\r\n")
            self.assertEqual((paths["root"] / "current-version-1.0.1-before-rollback.txt").read_bytes(),
                             b"1.0.1\r\n")
            again = call_script(script, paths["local"], "-Apply")
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("ALREADY_VERSION_1.0.0_ACTIVE_NO_MUTATION", again.stdout)
            self.assertEqual(sha(paths["old"]), old_hash)
            self.assertEqual(sha(paths["new"]), new_hash)
            self.assertEqual(sha(paths["backup_file"]), backup_hash)

    def test_tampered_backup_and_old_binary_prevent_any_pointer_change(self):
        with tempfile.TemporaryDirectory() as temp:
            script, _, paths = make_fixture(Path(temp))
            pointer = paths["root"] / "current-version.txt"
            paths["backup_file"].write_bytes(b"changed backup!")
            fail = call_script(script, paths["local"], "-Apply")
            self.assertNotEqual(fail.returncode, 0)
            self.assertEqual(pointer.read_bytes(), b"1.0.1\r\n")
        with tempfile.TemporaryDirectory() as temp:
            script, _, paths = make_fixture(Path(temp))
            pointer = paths["root"] / "current-version.txt"
            paths["old"].write_bytes(b"tampered program")
            fail = call_script(script, paths["local"], "-Apply")
            self.assertNotEqual(fail.returncode, 0)
            self.assertEqual(pointer.read_bytes(), b"1.0.1\r\n")

    def test_missing_pre_activation_pointer_prevents_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            script, _, paths = make_fixture(Path(temp))
            (paths["root"] / "current-version-pre-1.0.1.txt").unlink()
            fail = call_script(script, paths["local"], "-Apply")
            self.assertNotEqual(fail.returncode, 0)
            self.assertEqual((paths["root"] / "current-version.txt").read_bytes(), b"1.0.1\r\n")


class RollbackRendererTests(unittest.TestCase):
    def test_invalid_or_relative_provenance_is_rejected(self):
        kwargs = dict(backup_root=Path("relative"), backup_report_sha="a" * 64,
                      backup_manifest_sha="b" * 64, old_exe_sha="c" * 64,
                      new_exe_sha="d" * 64, launcher_sha="e" * 64,
                      pre_pointer_sha="f" * 64, file_count=178,
                      total_bytes=124011301, sqlite_count=67)
        with self.assertRaises(rescue.RescueBlocked):
            rescue.render(**kwargs)
        kwargs["backup_root"] = Path(tempfile.gettempdir()).resolve()
        kwargs["old_exe_sha"] = "not-a-sha"
        with self.assertRaises(rescue.RescueBlocked):
            rescue.render(**kwargs)


if __name__ == "__main__":
    unittest.main()
