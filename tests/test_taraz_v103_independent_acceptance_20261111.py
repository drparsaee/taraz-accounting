"""Deterministic evidence-tamper tests for the independent v1.0.3 gate.

Fixtures use fake EXE bytes and injected PE/PYZ inspectors. Actual native
binary/resource/archive inspection occurs in the separate real gate run.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from scripts import qa_taraz_v103_independent_acceptance_20261111 as gate


def put(path: Path, contents: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents.encode("utf-8") if isinstance(contents, str) else contents)
    return path


def put_json(path: Path, obj: dict) -> Path:
    return put(path, json.dumps(obj, sort_keys=True, indent=2) + "\n")


class IndependentContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="taraz-v103-independent-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fixture(self) -> tuple[Path, dict, str]:
        build = self.root / "candidate" / "build-fixture"
        offline = build / "offline-update"
        source = build / "source"
        frozen_file = put(source / "src" / "example.js", "frozen-variable")
        frozen = {"src/example.js": gate._digest(frozen_file)}
        frozen_sha = gate._fp(frozen)
        frozen_manifest = put_json(offline / "source-sha256.json", frozen)
        package = put_json(offline / "package.json",
                           {"name": "taraz-accounting", "version": "1.0.3"})
        lock = put_json(offline / "package-lock.json",
                        {"name": "taraz-accounting", "version": "1.0.3",
                         "packages": {"": {"version": "1.0.3"}}})
        put(source / "package.json", package.read_bytes())
        put(source / "package-lock.json", lock.read_bytes())
        stage_module = put(source / "taraz_release_version.py",
                           'APP_VERSION="1.0.3"\nQA_ONLY=False\n')
        stage_native = put(source / "taraz_desktop.py", "def sample(): return 103\n")
        ui_file = put(build / "web" / "dist" / "accounting.html", "<html>test</html>")
        ui_sha = gate._digest(ui_file)
        exe = put(build / "binary" / "Taraz.exe", b"MZ-FAKE-UNIT-TEST-ONLY")
        copied_exe = put(offline / "Taraz.exe", exe.read_bytes())
        install = put(offline / "Install-Taraz-V103.ps1", "param()\n")
        activate = put(offline / "Activate-Taraz-V103.ps1", "param()\n")
        manifest = {
            "application": "Taraz", "targetVersion": "1.0.3",
            "installedBaselineVersion": "1.0.2", "installedBaselineSha256": gate.INSTALLED_V102_SHA,
            "qaOnly": False, "productionCandidate": True, "exeSha256": gate._digest(exe),
            "exeBytes": exe.stat().st_size, "sourceSnapshotSha256": frozen_sha,
            "sourceFilesCount": len(frozen), "sourceFileManifestSha256": gate._digest(frozen_manifest),
            "peVersion": "1.0.3.0",
            "stagedPackageSha256": gate._digest(package),
            "stagedLockSha256": gate._digest(lock),
            "stagedVersionSourceSha256": {
                "versionModuleSha256": gate._digest(stage_module),
                "nativeEntrySha256": gate._digest(stage_native),
            },
            "installScriptSha256": gate._digest(install),
            "activationScriptSha256": gate._digest(activate),
            "compiledEvidence": {"uiAssetsSha256": {"accounting.html": ui_sha}},
        }
        manifest_file = put_json(offline / "update-manifest.json", manifest)
        archive = build / "Taraz-v1.0.3-P1-OFFLINE-SIDE-BY-SIDE-UPDATE.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name in sorted(gate.EXPECTED_BUNDLE_FILES):
                z.write(offline / name, name)
        report = {
            "status": "PRODUCTION_V103_P1_CANDIDATE_BUILT_NOT_INSTALLED",
            "version": "1.0.3", "sourceFreezeSha256": frozen_sha,
            "sourceFileCount": len(frozen), "output": str(build),
            "compiled": {"peVersion": "1.0.3.0", "uiAssetsSha256": {"accounting.html": ui_sha}},
            "exe": str(exe), "exeSha256": gate._digest(exe),
            "zip": str(archive), "zipSha256": gate._digest(archive),
        }
        for name, file in (("manifest", manifest_file), ("installScript", install),
                           ("activationScript", activate)):
            report[name] = str(file)
            report[name + "Sha256"] = gate._digest(file)
        put_json(build / "build-report.json", report)
        self.assertEqual(gate._digest(copied_exe), gate._digest(exe))
        return build, report, frozen_sha

    @staticmethod
    def fake_pyz(*args):
        return {"status": "FIXTURE_ONLY"}

    def _validate(self, build: Path, frozen_sha: str, *, pe="1.0.3.0", pyz=None):
        with patch.object(gate, "FROZEN_SHA", frozen_sha):
            return gate.verify_candidate(
                build, pe_reader=lambda _: pe,
                pyz_reader=self.fake_pyz if pyz is None else pyz)

    def test_untampered_synthetic_artifact_parity(self):
        build, report, freeze = self.fixture()
        result = self._validate(build, freeze)
        self.assertEqual(result["status"], "ARTIFACT_PINS_PE_PYZ_ZIP_VERIFIED")
        self.assertEqual(result["zipMembersRehashed"], 7)
        self.assertEqual(result["snapshotUnstagedInputsRehashed"], 1)

    def test_wrong_real_pe_resource_fails_despite_manifest_claim(self):
        build, report, freeze = self.fixture()
        with self.assertRaisesRegex(gate.Rejected, "actual PE"):
            self._validate(build, freeze, pe="1.0.2.0")

    def test_missing_frozen_module_rejected(self):
        build, report, freeze = self.fixture()
        def missing(*args):
            raise gate.Rejected("frozen PYZ module absent")
        with self.assertRaisesRegex(gate.Rejected, "PYZ module absent"):
            self._validate(build, freeze, pyz=missing)

    def test_frozen_snapshot_byte_tampering_is_detected(self):
        build, report, freeze = self.fixture()
        put(build / "source" / "src" / "example.js", "tampered")
        with self.assertRaisesRegex(gate.Rejected, "frozen source"):
            self._validate(build, freeze)

    def test_source_freeze_mismatch_rejected_even_with_report(self):
        build, report, freeze = self.fixture()
        with self.assertRaisesRegex(gate.Rejected, "source freeze"):
            self._validate(build, "0" * 64)

    def test_broken_package_version_rejected(self):
        build, report, freeze = self.fixture()
        offline = build / "offline-update"
        put_json(offline / "package.json", {"version": "1.0.2"})
        with self.assertRaises(gate.Rejected):
            self._validate(build, freeze)

    def test_zip_duplicate_detected_even_when_hash_pin_is_updated(self):
        build, report, freeze = self.fixture()
        zip_path = Path(report["zip"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(zip_path, "a") as z:
                z.writestr("Taraz.exe", b"evil")
        report["zipSha256"] = gate._digest(zip_path)
        put_json(build / "build-report.json", report)
        with self.assertRaisesRegex(gate.Rejected, "ZIP file inventory"):
            self._validate(build, freeze)

    def test_disposable_execution_refuses_unreviewed_script_sha(self):
        build, report, freeze = self.fixture()
        with self.assertRaisesRegex(gate.Rejected, "independently reviewed"):
            gate.disposable_install(build, self.root, self.root, {
                "installScriptSha256": "0" * 64, "activationScriptSha256": "0" * 64})

    def test_rejects_traversal_and_symlink(self):
        for text in ("../../Windows", "bridge/../secret", "C:/Users", "/root", "bridge\\file"):
            with self.subTest(value=text), self.assertRaises(gate.Rejected):
                gate._safe_rel(text)
        real = put(self.root / "real.txt", "text")
        alias = self.root / "alias"
        try:
            alias.symlink_to(real)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(gate.Rejected):
            gate._digest(alias)

    def backup_fixture(self) -> Path:
        backup = self.root / "cold"
        files = {}
        for i in range(181):
            name = f"roaming/file-{i:03d}.txt"
            path = put(backup / "files" / name, f"content-{i:03d}")
            files[name] = {"bytes": path.stat().st_size, "sha256": gate._digest(path)}
        total = sum(item["bytes"] for item in files.values())
        manifest = {"schemaVersion": 1, "files": files, "fileCount": len(files),
                    "totalBytes": total, "verifiedNoOverwrite": True,
                    "allFilesIncluded": True, "sqliteChecks": {str(i): True for i in range(67)}}
        file_manifest = put_json(backup / "snapshot-manifest.json", manifest)
        report = {"status": "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING",
                  "installedBefore": "1.0.2", "installedAfter": "1.0.2",
                  "installedExeSha256": gate.INSTALLED_V102_SHA,
                  "backup": {"backupRoot": str(backup), "fileCount": len(files),
                             "totalBytes": total, "sqliteValidatedCount": 67,
                             "manifestSha256": gate._digest(file_manifest),
                             "independentReadback": True}}
        report_file = put_json(backup / "backup-acceptance-report.json", report)
        self.manifest_sha = gate._digest(file_manifest)
        self.report_sha = gate._digest(report_file)
        return backup

    def _verify_backup(self, backup: Path):
        with (patch.object(gate, "BACKUP_MANIFEST_SHA", self.manifest_sha),
              patch.object(gate, "BACKUP_REPORT_SHA", self.report_sha)):
            return gate.verify_backup(backup)

    def test_fresh_backup_all_file_sha_match(self):
        backup = self.backup_fixture()
        report = self._verify_backup(backup)
        self.assertEqual(report["filesRehashed"], 181)
        self.assertEqual(report["sqliteChecksReportedNotRerun"], 67)

    def test_backup_modified_or_extra_entry_fails_closed(self):
        backup = self.backup_fixture()
        put(backup / "files" / "roaming" / "file-000.txt", "changed")
        with self.assertRaises(gate.Rejected):
            self._verify_backup(backup)
        backup = self.backup_fixture()
        put(backup / "files" / "bridge" / "unlisted.json", "{}")
        with self.assertRaisesRegex(gate.Rejected, "file list"):
            self._verify_backup(backup)

    def test_module_literal_checker_handles_python_dict_key_tuples(self):
        def sample():
            return {"pendingTruncated": len(range(201)) > 100}
        self.assertTrue(gate._contains_literal(sample.__code__.co_consts, "pendingTruncated"))
        self.assertFalse(gate._contains_literal(sample.__code__.co_consts, "missingFlag"))

    def test_private_gui_refuses_unpinned_binary_before_creating_desktop(self):
        build, _report, _freeze = self.fixture()
        with self.assertRaisesRegex(gate.Rejected, "SHA mismatch"):
            gate.private_desktop_gui_smoke(
                build, self.root, {"exeSha256": "0" * 64})

    def test_rollback_ps1_rejects_single_trailing_regex_escape(self):
        broken = "if($env:LOCALAPPDATA -notmatch '^[a-zA-Z]:\\') { throw 'bad' }"
        with self.assertRaisesRegex(gate.Rejected, "invalid trailing escape"):
            gate.verify_windows_drive_regex(broken)
        correct = "if($env:LOCALAPPDATA -notmatch '^[a-zA-Z]:\\\\') { throw 'bad' }"
        gate.verify_windows_drive_regex(correct)


if __name__ == "__main__":
    unittest.main()
