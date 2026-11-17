"""Independent synthetic contract tests; never open a live accounting profile."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts import taraz_p0_release_inventory_20261111 as audit


def write(path: Path, content: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def write_json(path: Path, data: dict) -> Path:
    return write(path, json.dumps(data, sort_keys=True, indent=2) + "\n")


class AuditContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="taraz-p0-inventory-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_runtime_fingerprint_matches_builder_json_byte_contract(self) -> None:
        root = self.root / "source"
        write(root / "package.json", '{"version":"1.0.0"}')
        write(root / "src" / "app.jsx", "OLD")
        write(root / "dist" / "ignored.js", "OUT")
        write(root / "scripts" / "ignored.py", "OUT")
        write(root / "node_modules" / "ignored.py", "OUT")
        values = audit.runtime_inventory(root)
        self.assertEqual(sorted(values), ["package.json", "src/app.jsx"])
        self.assertEqual(audit.fingerprint(values), hashlib.sha256(
            json.dumps(values, sort_keys=True).encode("utf-8")).hexdigest())

    def test_source_delta_has_exact_added_modified_and_removed(self) -> None:
        frozen = {key: audit.digest(write(self.root / key, key))
                  for key in ("same", "modified", "removed")}
        current = {"same": frozen["same"], "modified": audit.digest(write(self.root / "mod2", "different")),
                   "added": audit.digest(write(self.root / "add2", "new"))}
        observed = audit.compare_frozen(current, frozen)
        self.assertEqual(observed, {"identical": ["same"], "changed": ["modified"],
                                    "added": ["added"], "removed": ["removed"]})

    def test_source_rejects_linked_runtime_file(self) -> None:
        root = self.root / "source"
        write(root / "package.json", "{}")
        target = write(self.root / "secret.txt", "sample")
        alias = root / "src" / "alias.txt"
        alias.parent.mkdir()
        try:
            alias.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable on this platform")
        with self.assertRaises(audit.AuditError):
            audit.runtime_inventory(root)

    def test_relative_path_rejects_traversal_and_absolute_path(self) -> None:
        for name in ("../escape", "bridge/../../escape", "/root/out", "C:/system", "bridge\\a"):
            with self.subTest(name=name), self.assertRaises(audit.AuditError):
                audit.safe_relative(name, ("roaming", "local", "bridge"))

    def candidate_fixture(self) -> tuple[Path, dict]:
        build = self.root / "build"
        offline = build / "offline-update"
        frozen = {"src/app.js": hashlib.sha256(b"dashboard").hexdigest()}
        manifest_source = write_json(offline / "source-sha256.json", frozen)
        exe = write(build / "binary" / "Taraz.exe", b"MZ-example-binary")
        copied_exe = write(offline / "Taraz.exe", exe.read_bytes())
        install = write(offline / "Install-Taraz-V102.ps1", "# test-only installer fixture\n")
        activate = write(offline / "Activate-Taraz-V102.ps1", "# test-only activation fixture\n")
        exe_hash = audit.digest(exe)
        manifest = {
            "exeSha256": exe_hash, "exeBytes": exe.stat().st_size,
            "sourceFileManifestSha256": audit.digest(manifest_source),
            "sourceSnapshotSha256": audit.fingerprint(frozen), "sourceFilesCount": 1,
            "targetVersion": "1.0.2", "peVersion": "1.0.2.0", "unsigned": True,
        }
        manifest_file = write_json(offline / "update-manifest.json", manifest)
        zip_path = build / "Taraz-v1.0.2-MADAR-DASHBOARD-OFFLINE-UPDATE.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file in (copied_exe, install, activate, manifest_source, manifest_file):
                zip_file.write(file, file.name)
        report = {
            "version": "1.0.2", "exeSha256": exe_hash, "sourceInputCount": 1,
            "sourceFreezeSha256": audit.fingerprint(frozen), "compiled": {"peVersion": "1.0.2.0"},
            "zip": str(zip_path), "zipSha256": audit.digest(zip_path),
        }
        for name, file in (("exe", exe), ("manifest", manifest_file),
                           ("installScript", install), ("activationScript", activate)):
            report[name] = str(file)
            report[name + "Sha256"] = audit.digest(file)
        return build, report

    def test_candidate_checks_all_archive_entry_bytes(self) -> None:
        build, report = self.candidate_fixture()
        observed = audit.verify_candidate(build, report)
        self.assertEqual(observed["status"], "HASH_PARITY_VERIFIED")
        self.assertEqual(observed["zipMembersVerified"], 5)
        self.assertEqual(observed["sourceFreezeSha256"], report["sourceFreezeSha256"])

    def test_candidate_fails_closed_if_manifest_or_zip_changes(self) -> None:
        build, report = self.candidate_fixture()
        manifest_file = build / "offline-update" / "update-manifest.json"
        write(manifest_file, manifest_file.read_bytes() + b" ")
        with self.assertRaises(audit.AuditError):
            audit.verify_candidate(build, report)
        build, report = self.candidate_fixture()
        archive_file = Path(report["zip"])
        write(archive_file, archive_file.read_bytes() + b"tamper")
        with self.assertRaises(audit.AuditError):
            audit.verify_candidate(build, report)

    def test_installed_pointer_and_executable_parity(self) -> None:
        installed = self.root / "Installed"
        write(installed / "current-version.txt", "1.0.2\n")
        write(installed / "Run-Taraz.cmd", "versions\\%TARAZ_VERSION%\\Taraz.exe\n")
        exe = write(installed / "versions" / "1.0.2" / "Taraz.exe", b"MZexample")
        state = audit.installed_state(installed, audit.digest(exe))
        self.assertTrue(state["matchesCandidate"])
        self.assertTrue(state["launcherVersioned"])
        self.assertEqual(state["version"], "1.0.2")
        self.assertFalse(audit.installed_state(installed, "0" * 64)["matchesCandidate"])

    def backup_fixture(self) -> tuple[Path, dict]:
        root = self.root / "backup"
        manifest_files = {}
        for relative in ("roaming/book.sqlite3", "bridge/pending/doc.json"):
            target = write(root / "files" / relative, relative)
            manifest_files[relative] = {"bytes": target.stat().st_size, "sha256": audit.digest(target)}
        total = sum(value["bytes"] for value in manifest_files.values())
        manifest = {"fileCount": len(manifest_files), "totalBytes": total,
                    "verifiedNoOverwrite": True, "allFilesIncluded": True,
                    "files": manifest_files, "sqliteChecks": {}}
        mf = write_json(root / "snapshot-manifest.json", manifest)
        report = {"status": "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING",
                  "installedBefore": "1.0.1", "installedAfter": "1.0.1",
                  "backup": {"independentReadback": True, "manifestSha256": audit.digest(mf),
                             "fileCount": len(manifest_files), "totalBytes": total, "sqliteValidatedCount": 0}}
        rf = write_json(root / "backup-acceptance-report.json", report)
        return root, {"manifestSha256": audit.digest(mf), "reportSha256": audit.digest(rf),
                      "fileCount": len(manifest_files), "totalBytes": total, "sqliteValidatedCount": 0}

    def test_backup_rehashes_every_copied_file(self) -> None:
        root, reported = self.backup_fixture()
        observed = audit.verify_backup(root, reported)
        self.assertEqual(observed["filesHashed"], 2)
        self.assertFalse(observed["sqliteIntegrityRerun"])
        self.assertEqual(observed["backupCapturedToVersion"], "1.0.1")

    def test_backup_detects_added_or_modified_data(self) -> None:
        root, reported = self.backup_fixture()
        write(root / "files" / "bridge" / "pending" / "extra.json", "new")
        with self.assertRaises(audit.AuditError):
            audit.verify_backup(root, reported)
        (root / "files" / "bridge" / "pending" / "extra.json").unlink()
        write(root / "files" / "roaming" / "book.sqlite3", "changed")
        with self.assertRaises(audit.AuditError):
            audit.verify_backup(root, reported)


if __name__ == "__main__":
    unittest.main()
