"""Independent fail-closed QA for pinned v104 candidate and disposable scripts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v104_independent_acceptance_20261111 as qa


class V104IndependentAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="synthetic-v104-independent-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_exact_pinset_and_seven_member_contract(self):
        self.assertEqual(len(qa.ZIP_NAMES), 7)
        self.assertEqual(qa.COUNT, 131)
        self.assertEqual(qa.STAGE_SOURCE_SHA, "6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1")
        self.assertEqual(qa.VITE_JS_SHA, "b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453")
        self.assertEqual(qa.V102_SHA, "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52")
        self.assertIn("Install-Taraz-V104.ps1", qa.ZIP_NAMES)
        self.assertIn("Activate-Taraz-V104.ps1", qa.ZIP_NAMES)

    def test_real_stage_file_bytes_rehashed(self):
        result = qa.verify_stage()
        self.assertEqual(result["sourceCount"], 131)
        self.assertEqual(result["sha256"], qa.STAGE_SOURCE_SHA)
        self.assertEqual(len(result["inventory"]), 131)
        self.assertTrue(qa.sha_ok(result["stageReportSha256"]))

    def test_real_detached_edge_vite_asset_sha_rehashed(self):
        result = qa.verify_vite(qa.verify_stage())
        self.assertEqual(result["sha256"], qa.VITE_JS_SHA)
        self.assertEqual(len(result["assetPins"]), 3)
        self.assertIn("accounting.html", result["assetPins"])

    def test_real_installed_baseline_is_read_only_and_pinned(self):
        if os.name != "nt":
            self.skipTest("Real original installed v102 only exists on Windows")
        before = qa.installed_baseline()
        self.assertEqual(before["pointerVersion"], "1.0.2")
        self.assertEqual(before["baselineExeSha256"], qa.V102_SHA)
        self.assertTrue(before["installedV104Absent"])
        self.assertEqual(before, qa.installed_baseline())

    def test_real_offline_181_file_backup_hashes_read_only(self):
        result = qa.backup_readback()
        self.assertEqual(result["filesRehashed"], 181)
        self.assertEqual(result["bytesRehashed"], 124011875)
        self.assertEqual(result["sqliteValidatedByPriorWitnessOnly"], 67)
        self.assertEqual(result["manifestSha256"], qa.BACKUP_MANIFEST_SHA)

    def test_source_inventory_tamper_fails(self):
        pinned = {"src/a.jsx": "a" * 64, "src/b.jsx": "b" * 64}
        digest = qa.fingerprint(pinned)
        self.assertEqual(len(digest), 64)
        self.assertNotEqual(digest, qa.fingerprint(dict(pinned, **{"src/a.jsx": "c" * 64})))
        for bad in ("../evil", "src/../evil", "C:\\tmp", "/absolute", "src//bad", "src/hi*.jsx"):
            with self.subTest(bad=bad), self.assertRaises(qa.Blocked):
                qa.relative(bad)
        with self.assertRaisesRegex(qa.Blocked, "Case-fold"):
            qa.fingerprint({"src/Test.jsx": "a" * 64, "src/test.jsx": "b" * 64})

    def test_source_member_extra_missing_changed_blocks(self):
        tree = self.root / "source"
        (tree / "src").mkdir(parents=True)
        file = tree / "src" / "one.jsx"
        file.write_text("synthetic", encoding="utf-8")
        pins = {"src/one.jsx": qa.hash_file(file)}
        self.assertEqual(qa.check_source_tree(tree, pins), 1)
        file.write_text("tampered", encoding="utf-8")
        with self.assertRaises(qa.Blocked):
            qa.check_source_tree(tree, pins)
        file.write_text("synthetic", encoding="utf-8")
        extra = tree / "src" / "extra.txt"
        extra.write_text("unlisted", encoding="utf-8")
        with self.assertRaisesRegex(qa.Blocked, "Unlisted"):
            qa.check_source_tree(tree, pins)
        extra.unlink()
        file.unlink()
        with self.assertRaisesRegex(qa.Blocked, "Missing"):
            qa.check_source_tree(tree, pins)

    def test_native_release_bytecode_assignments_are_checked_without_execution(self):
        code = compile("APP_VERSION='1.0.4'\nQA_ONLY=False\nBUILD_CHANNEL='offline-production-candidate'\n",
                       "<synthetic>", "exec")
        self.assertIsInstance(code, types.CodeType)
        self.assertEqual(qa.assigned(code, "APP_VERSION"), "1.0.4")
        self.assertIs(qa.assigned(code, "QA_ONLY"), False)
        self.assertEqual(qa.assigned(code, "BUILD_CHANNEL"), "offline-production-candidate")
        with self.assertRaises(qa.Blocked):
            qa.assigned(code, "DOES_NOT_EXIST")

    def test_release_manifest_tampering_rejected(self):
        positive = {
            "status": "PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED",
            "version": "1.0.4", "sourceFreezeSha256": qa.STAGE_SOURCE_SHA,
            "sourceFileCount": 131, "installed": False, "pointerChanged": False,
            "releaseApproved": False,
        }
        manifest = {
            "targetVersion": "1.0.4", "sourceSnapshotSha256": qa.STAGE_SOURCE_SHA,
            "sourceFilesCount": 131, "installedBaselineVersion": "1.0.2",
            "installedBaselineSha256": qa.V102_SHA, "peVersion": "1.0.4.0",
            "pyzVersion": "1.0.4", "qaOnly": False, "productionCandidate": True,
            "unsigned": True, "installed": False, "pointerActivated": False,
            "activationApprovalGranted": False, "financePostingProven": False,
            "compiledEdgeRedactionApproved": False,
        }
        qa.check_release_metadata(positive, manifest, {"sha256": qa.STAGE_SOURCE_SHA})
        for key, value in (("qaOnly", True), ("peVersion", "1.0.3.0"),
                           ("pointerActivated", True), ("financePostingProven", True),
                           ("compiledEdgeRedactionApproved", True)):
            with self.subTest(key=key), self.assertRaises(qa.Blocked):
                qa.check_release_metadata(positive, dict(manifest, **{key: value}),
                                          {"sha256": qa.STAGE_SOURCE_SHA})
        with self.assertRaises(qa.Blocked):
            qa.check_release_metadata(dict(positive, releaseApproved=True), manifest,
                                      {"sha256": qa.STAGE_SOURCE_SHA})

    def test_installer_guard_requires_fileinfo_directory_and_pointer(self):
        good = "\n".join([
            "param([switch]$Apply)", "Set-StrictMode -Version Latest",
            "function SafePath", "function CanonicalLocal", "function CheckPackagePins",
            "function CheckBackup", "function CheckNoTaraz", "HardlinkCount",
            "$parent=$item.Directory", "RequireAbsent", "Get-CimInstance",
            "TarazV104SecureLinkInfo", "1.0.4", "1.0.2",
        ])
        install = good + "\nINSTALLED_SIDE_BY_SIDE_1.0.4_POINTER_REMAINS_1.0.2"
        activate = (good + "\n[IO.File]::Replace($pending,$pointer,$oldPointer,$true)\n"
                    "Run-Taraz-pre-1.0.4.cmd\ncurrent-version-pre-1.0.4.txt\n"
                    "current-version-1.0.4-pending.txt")
        self.assertTrue(qa.secure_installer_static(install, activate)["fileInfoDirectoryAncestry"])
        with self.assertRaisesRegex(qa.Blocked, "guard"):
            qa.secure_installer_static(install.replace("$parent=$item.Directory", ""), activate)
        with self.assertRaisesRegex(qa.Blocked, "unsafe|Unsafe"):
            qa.secure_installer_static(install + "\n$item=$item.Parent", activate)
        with self.assertRaisesRegex(qa.Blocked, "pointer"):
            qa.secure_installer_static(install, activate.replace("current-version-pre-1.0.4.txt", "wrong.txt"))

    def _zip_fixture(self):
        offline = self.root / "offline"
        offline.mkdir()
        entries = {}
        for name in qa.ZIP_NAMES:
            file = offline / name
            file.write_bytes(("synthetic:" + name).encode("utf-8"))
            entries[name] = file
        zip_path = self.root / "synthetic.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, path in sorted(entries.items()):
                z.write(path, arcname=name)
        return entries, zip_path

    def test_synthetic_zip_seven_members_and_byte_tamper(self):
        files, archive = self._zip_fixture()
        self.assertEqual(qa.verify_zip_members(archive, files)["zipMembersRehashed"], 7)
        files["package.json"].write_bytes(b"changed byte")
        with self.assertRaisesRegex(qa.Blocked, "differ"):
            qa.verify_zip_members(archive, files)
        files["package.json"].write_bytes(b"synthetic:package.json")
        with zipfile.ZipFile(archive, "a") as z:
            z.writestr("package.json", "duplicate malicious content")
        with self.assertRaisesRegex(qa.Blocked, "duplicate"):
            qa.verify_zip_members(archive, files)

    def test_disposable_witness_must_be_independently_sha_pinned_and_prior(self):
        fake_build = self.root / "build-fake"
        fake_build.mkdir()
        report = self.root / "worker26-qa.json"
        report.write_text(json.dumps({
            "status": "PASS", "buildDirectory": str(fake_build),
            "testsFailed": 0, "testsPassed": 12,
            "installedProfileChanged": False, "financePosted": False,
        }), encoding="utf-8")
        pinned = qa.hash_file(report)
        self.assertEqual(qa.independent_worker26_witness(report, pinned, fake_build)["worker26TestsPassed"], 12)
        with self.assertRaises(qa.Blocked):
            qa.independent_worker26_witness(report, "0" * 64, fake_build)
        with self.assertRaises(qa.Blocked):
            qa.independent_worker26_witness(report, pinned, self.root / "another-build")
        report.write_text(json.dumps({"status": "PASS", "buildDirectory": str(fake_build),
                                      "testsFailed": 1, "testsPassed": 12,
                                      "installedProfileChanged": False, "financePosted": False}))
        with self.assertRaises(qa.Blocked):
            qa.independent_worker26_witness(report, qa.hash_file(report), fake_build)

    def test_nonexistent_or_ambiguous_candidate_failclosed(self):
        selected = qa.OUTPUT / "build-000000000000"
        with self.assertRaises(qa.Blocked):
            qa.inspect_candidate(selected, {}, {})
        with patch.object(qa, "OUTPUT", self.root):
            with self.assertRaisesRegex(qa.Blocked, "ONE completed"):
                qa.discover_build()

    def test_fixture_never_accesses_real_finance_source_in_its_synthetic_layout(self):
        names = set(qa.ZIP_NAMES)
        self.assertEqual(len(names), 7)
        code = Path(qa.__file__).read_text(encoding="utf-8")
        self.assertIn("TemporaryDirectory(prefix=\"qa-v104-install-\"", code)
        self.assertIn("shutil.copyfile(original, old)", code)
        self.assertIn("QA synthetic CIM failure", code)
        self.assertIn("READY_FOR_CREATE_ONLY_1.0.4_INSTALL", code)
        self.assertIn("ACTIVATED_1.0.4_VERSION_1.0.2_RETAINED", code)
        self.assertIn("ancestor junction", code)
        self.assertNotIn("subprocess.Popen(", code)
        self.assertNotIn("os.startfile(", code)

    @unittest.skipUnless(os.environ.get("TARAZ_V104_BUILD_DIR"),
                         "Real v104 native artifact not yet provided")
    def test_real_native_candidate_static_inspection(self):
        source = qa.verify_stage()
        vite = qa.verify_vite(source)
        build = Path(os.environ["TARAZ_V104_BUILD_DIR"])
        result = qa.inspect_candidate(build, source, vite)
        self.assertEqual(result["status"], "STATIC_V104_BINARY_ZIP_AND_SOURCE_PASSED_NO_GO")
        self.assertEqual(result["sourceFilesRehashed"], 131)
        self.assertEqual(result["zipMemberCount"], 7)
        self.assertEqual(result["compiled"]["embeddedJsSha256"], qa.VITE_JS_SHA)
        self.assertFalse(result["nativeExecuted"])
        self.assertFalse(result["financePostingProven"])


if __name__ == "__main__":
    unittest.main()
