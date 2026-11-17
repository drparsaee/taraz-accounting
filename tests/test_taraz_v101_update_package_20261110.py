"""Disposable synthetic packaging and fail-closed validation tests.

No installed Taraz EXE is opened, no ledger/user profile and no network.
All synthetic outputs are confined to a temporary folder under D:/CoS-Test.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qa_taraz_v101_update_package_20261110",
    PROJECT / "scripts" / "qa_taraz_v101_update_package_20261110.py",
)
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


def dump_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf8")


def doc_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


class OfflineCandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            prefix="qa-taraz-v101-synth-", dir=PROJECT.parents[1]
        )
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.qa_report = self.root / "qa-build-report.json"
        self.installed = self.root / "synthetic-installed.exe"
        self.qa = self.root / package.PAYLOAD_BASENAME
        self.installed.write_bytes(b"installed-version-1.0.0-synthetic")
        self.payload = b"MZ\x00 QA synthetic payload: not an installer" * 13
        self.qa.write_bytes(self.payload)
        self.qa_sha = hashlib.sha256(self.payload).hexdigest()
        self.installed_sha = hashlib.sha256(self.installed.read_bytes()).hexdigest()
        self.source_sha = "a" * 64
        dump_json(self.source / "package.json", {"version": "1.0.0"})
        dump_json(self.source / "package-lock.json", {
            "version": "1.0.0", "packages": {"": {"version": "1.0.0"}}
        })
        self.evidence = {
            "qaBinaryPath": str(self.qa),
            "qaBinarySha256": self.qa_sha,
            "qaBinaryBytes": len(self.payload),
            "sourcePackageVersion": "1.0.0",
            "sourceSnapshotSha256": self.source_sha,
            "sourceInputCount": 128,
            "installedBaselineFolderVersion": "1.0.0",
            "installedBaselineSha256": self.installed_sha,
            "installedBaselineBytes": len(self.installed.read_bytes()),
            "packedFeaturePresence": {
                "taraz_mtr_review_attestation_issuer": False,
                "taraz_mtr_finance_witness_issuer": False,
                "taraz_mtr_finance_binding_authority": False,
                "taraz_mtr_peer_registry": False,
                "taraz_mtr_peer_http": False,
            },
        }

    def patched_payload_size(self):
        return patch.object(package, "QA_BYTES", len(self.payload))

    def make_archive(self, *, destination=None):
        destination = destination or self.root / "out"
        with patch.object(package, "validate_evidence", return_value=self.evidence):
            with self.patched_payload_size():
                report = package.build(
                    source=self.source, qa_report=self.qa_report,
                    installed_exe=self.installed, output=destination,
                    expected_qa_sha=self.qa_sha,
                    source_snapshot=lambda _: (self.source_sha, 128),
                )
        return report

    def test_create_only_valid_zip_manifest_and_separate_outer_sha(self):
        output = self.make_archive()
        archive = Path(output["zip"])
        self.assertTrue(archive.is_file())
        self.assertFalse(output["installable"])
        self.assertEqual(output["payloadSourceVersion"], "1.0.0")
        self.assertEqual(output["targetLabelOnly"], "1.0.1")
        with zipfile.ZipFile(archive) as zf:
            self.assertEqual(set(zf.namelist()), set(package.EXPECTED_MEMBERS))
            self.assertEqual(zf.read(package.EXPECTED_MEMBERS[0]), self.payload)
            embedded = json.loads(zf.read("manifest.json"))
            self.assertEqual(embedded["packageTargetLabel"], "1.0.1")
            self.assertEqual(embedded["payloadSourcePackageVersion"], "1.0.0")
            self.assertIsNone(embedded["payloadEmbeddedBinaryVersion"])
            self.assertFalse(embedded["payloadEmbeddedBinaryVersionVerified"])
            self.assertFalse(embedded["realInstaller"])
            self.assertFalse(embedded["safeToInstall"])
            self.assertEqual(embedded["releaseDecision"], "NO_GO")
            self.assertIn("Taraz-MTR-QA", embedded["payload"]["path"])
            self.assertIn("BLOCKED", zf.read("INSTALL_BLOCKED.md").decode())
            self.assertIn("create-only", zf.read("ROLLBACK_PRECONDITIONS.md").decode())
        outer = json.loads(Path(output["outerManifest"]).read_text(encoding="utf8"))
        self.assertEqual(outer["zipSha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(outer["zipBytes"], archive.stat().st_size)
        self.assertFalse(outer["safeToInstall"])
        self.assertEqual(outer["releaseDecision"], "NO_GO")
        with self.patched_payload_size():
            readback = package.verify_zip(archive, expected_qa_sha=self.qa_sha)
        self.assertEqual(readback["status"], "VERIFIED_QA_ARCHIVE_NOT_INSTALLABLE")

    def test_repeated_build_fails_without_overwriting_any_evidence(self):
        first = self.make_archive()
        before = Path(first["zip"]).read_bytes()
        with self.assertRaisesRegex(package.CandidateBlocked, "already contains files"):
            self.make_archive()
        self.assertEqual(Path(first["zip"]).read_bytes(), before)

    def test_existing_unrelated_output_is_never_overwritten(self):
        dest = self.root / "out"
        dest.mkdir()
        existing = dest / "important.txt"
        existing.write_text("existing", encoding="utf8")
        with self.assertRaisesRegex(package.CandidateBlocked, "already contains files"):
            self.make_archive(destination=dest)
        self.assertEqual(existing.read_text(encoding="utf8"), "existing")
        self.assertFalse((dest / package.ZIP_BASENAME).exists())

    def test_manifest_fraud_becomes_no_go(self):
        inner = package.manifest_from(self.evidence)
        inner["safeToInstall"] = True
        self.assertTrue(inner["safeToInstall"])
        fake = self.root / "fraud.zip"
        with zipfile.ZipFile(fake, "w") as archive:
            for member in package.EXPECTED_MEMBERS:
                content = (self.payload if member == package.EXPECTED_MEMBERS[0] else
                           package.canonical_json(inner) if member == "manifest.json" else b"txt")
                archive.writestr(member, content)
        with self.patched_payload_size():
            with self.assertRaisesRegex(package.CandidateBlocked, "falsely claims"):
                package.verify_zip(fake, expected_qa_sha=self.qa_sha)

    def test_package_payload_mismatch_is_detected(self):
        inner = package.manifest_from(self.evidence)
        fake = self.root / "wrong_payload.zip"
        with zipfile.ZipFile(fake, "w") as archive:
            for member in package.EXPECTED_MEMBERS:
                content = (
                    self.payload + b"tamper" if member == package.EXPECTED_MEMBERS[0] else
                    package.canonical_json(inner) if member == "manifest.json" else b"txt"
                )
                archive.writestr(member, content)
        with self.patched_payload_size():
            with self.assertRaisesRegex(package.CandidateBlocked, "inconsistent"):
                package.verify_zip(fake, expected_qa_sha=self.qa_sha)

    def test_archive_traversal_and_extra_member_fail_closed(self):
        fake = self.root / "zip-slip.zip"
        inner = package.manifest_from(self.evidence)
        with zipfile.ZipFile(fake, "w") as archive:
            for member in package.EXPECTED_MEMBERS:
                archive.writestr(
                    member, self.payload if member == package.EXPECTED_MEMBERS[0]
                    else package.canonical_json(inner) if member == "manifest.json" else b"txt"
                )
            archive.writestr("../escape.txt", b"not executed")
        with self.patched_payload_size():
            with self.assertRaisesRegex(package.CandidateBlocked, "Unexpected, duplicate"):
                package.verify_zip(fake, expected_qa_sha=self.qa_sha)
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_symlinked_output_refused_without_writes(self):
        destination = self.root / "linked"
        real = self.root / "other-folder"
        real.mkdir()
        try:
            destination.symlink_to(real, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink privilege unavailable")
        with self.assertRaisesRegex(package.CandidateBlocked, "Symlink"):
            self.make_archive(destination=destination)
        self.assertEqual(list(real.iterdir()), [])

    def test_untrusted_source_or_lock_version_rejected(self):
        invalid = self.source / "package-lock.json"
        dump_json(invalid, {"version": "1.0.1",
                            "packages": {"": {"version": "1.0.1"}}})
        with self.assertRaisesRegex(package.CandidateBlocked, "version mismatch"):
            package.validate_evidence(
                source=self.source, qa_report=self.qa_report,
                installed_exe=self.installed, pinned_qa_sha=self.qa_sha,
                pinned_source_sha=self.source_sha,
                source_snapshot=lambda _: (self.source_sha, 128),
            )

    def test_report_missing_never_creates_output(self):
        out = self.root / "out"
        with self.assertRaises(package.CandidateBlocked):
            package.build(source=self.source, qa_report=self.qa_report,
                          installed_exe=self.installed, output=out,
                          expected_qa_sha=self.qa_sha,
                          source_snapshot=lambda _: (self.source_sha, 128))
        self.assertFalse(out.exists())

    def test_corrupt_archives_fail_without_extraction(self):
        bogus = self.root / "corrupt.zip"
        bogus.write_bytes(b"not-a-zip")
        with self.assertRaises(zipfile.BadZipFile):
            package.verify_zip(bogus, expected_qa_sha=self.qa_sha)
        self.assertEqual(list(self.root.glob("payload")), [])

    def test_no_update_install_or_profile_mutation_apis(self):
        path = PROJECT / "scripts" / "qa_taraz_v101_update_package_20261110.py"
        content = path.read_text(encoding="utf8")
        for forbidden in (
            "subprocess.run", "Popen(", "sqlite3.connect(", "urllib.request",
            "requests.get(", "requests.post(", "os.system(", "Start-Process",
            "releaseInstall(", "TarazAPI(", "shutil.copytree(",
        ):
            self.assertNotIn(forbidden, content)
        self.assertIn('safeToInstall": False', content)
        self.assertIn('releaseDecision": "NO_GO"', content)


if __name__ == "__main__":
    unittest.main()
