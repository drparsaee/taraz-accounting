"""RC3 actual binary/source/backup acceptance with synthetic negative cases.

No production writes. Does not run RC3 PS1 -Apply; requires a separately
verified prior worker26 native QA report before that optional operation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v104_rc3_independent_acceptance_20261111 as qa


class V104RC3IndependentQA(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v104rc3-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_actual_new_RC3_candidate_subgate_passes_only_static(self):
        result = qa.inspect(qa.BUILD)
        self.assertEqual(result["subgate"], "RC3_STATIC_BINARY_SOURCE_BACKUP_ZIP_GO")
        self.assertEqual(result["exeSha256"], qa.EXE_SHA)
        self.assertEqual(result["zipSha256"], qa.ZIP_SHA)
        self.assertEqual(result["sourceFilesRehashed"], 131)
        self.assertEqual(result["zipMembersRehashed"], 7)
        self.assertEqual(result["embedded"]["uiAssetsRehashedInsideExe"], 15)
        self.assertEqual(result["embedded"]["peVersion"], "1.0.4.0")
        self.assertEqual(result["embedded"]["pyzVersion"], "1.0.4")
        self.assertEqual(result["embedded"]["jsSha256"], qa.VITE_JS_SHA)
        self.assertFalse(result["productionReleaseApproved"])
        self.assertFalse(result["installerSyntheticRun"])
        self.assertFalse(result["financePostingVerified"])
        self.assertFalse(result["embedded"]["realExeLaunched"])

    def test_direct_real_source_131_exact_sha_and_rc3(self):
        result = qa.source_authority()
        self.assertEqual(result["sourceCount"], 131)
        self.assertEqual(result["sourceSha256"], qa.SOURCE_SHA)
        self.assertEqual(len(result["files"]), 131)
        self.assertEqual(qa.digest(qa.SOURCE_STAGE / "patched-source-sha256.json"),
                         qa.SOURCE_MAP_SHA)
        self.assertEqual(qa.digest(qa.SOURCE_STAGE / "stage-report.json"),
                         qa.SOURCE_REPORT_SHA)

    def test_real_compiled_vite_js_css_html_pins(self):
        result = qa.vite_authority()
        self.assertEqual(result["viteJsSha256"], qa.VITE_JS_SHA)
        self.assertIn("accounting.html", result["assetPins"])
        self.assertEqual(len(result["assetPins"]), 3)

    def test_real_compiled_pe_pyz_and_all_15_embedded_asset_sha(self):
        root = qa.BUILD
        manifest = qa.read_obj(root / "offline-update" / "update-manifest.json")
        result = qa.inspect_native_binary(
            root / "binary" / "Taraz.exe",
            root / "web" / "dist",
            manifest["compiledEvidence"]["uiAssetsSha256"],
        )
        self.assertEqual(result["uiAssetsRehashedInsideExe"], 15)
        self.assertEqual(result["nativeMethodCount"], 5)
        self.assertEqual(result["pyzModulesCount"], 5)
        self.assertEqual(result["jsSha256"], qa.VITE_JS_SHA)
        self.assertFalse(result["realExeLaunched"])

    def test_real_7_zip_members_byte_for_byte(self):
        result = qa.verify_offline_zip(
            qa.BUILD / "Taraz-v1.0.4-P1-RC3-SECURE-OFFLINE-UPDATE.zip",
            qa.BUILD / "offline-update")
        self.assertEqual(result["zipSha256"], qa.ZIP_SHA)
        self.assertEqual(result["membersRehashed"], 7)
        self.assertEqual(result["memberSha256"]["Taraz.exe"], qa.EXE_SHA)

    def test_original_installed_v102_unchanged_with_absent_v104_folder(self):
        if os.name != "nt":
            self.skipTest("Native v102 installed only on Windows")
        before = qa.installed_authority()
        self.assertEqual(before["pointer"], "1.0.2")
        self.assertEqual(before["baselineBinarySha256"], qa.V102_SHA)
        self.assertFalse(before["version104Installed"])
        self.assertEqual(before, qa.installed_authority())

    def test_real_cold_backup_rehashes_181_files_67_sqlite_only_prior_witness(self):
        report = qa.backup_authority()
        self.assertEqual(report["rehashedFiles"], 181)
        self.assertEqual(report["rehashedBytes"], 124011875)
        self.assertEqual(report["sqliteChecksFromPriorWitnessNotRerun"], 67)
        self.assertEqual(report["manifestSha256"], qa.BACKUP_MAP_SHA)

    def test_real_external_qa_witnesses_source_and_14_inverse_stage_cases(self):
        build_report = qa.read_obj(qa.BUILD / "build-report.json")
        package = qa.read_obj(qa.BUILD / "offline-update" / "update-manifest.json")
        all_qa = qa.qa_witnesses(build_report, package)
        self.assertEqual(set(all_qa), set(qa.EXTERNAL_QA))
        self.assertEqual(all_qa["rc2-source-stage"]["checksPassed"], 10)
        self.assertGreaterEqual(all_qa["rc2-original-seven-edge"]["checksPassed"], 7)
        self.assertGreaterEqual(all_qa["rc2-residual-three-edge"]["checksPassed"], 3)
        for row in all_qa.values():
            self.assertRegex(row["sha256"], r"^[a-f0-9]{64}$")

    def test_real_install_and_activation_static_contract(self):
        directory = qa.BUILD / "offline-update"
        metadata = qa.read_obj(directory / "update-manifest.json")
        result = qa.installer_contract(directory, metadata)
        self.assertEqual(result["pointerBackupName"], "current-version-pre-1.0.4.txt")
        self.assertEqual(result["launcherBackupName"], "Run-Taraz-pre-1.0.4.cmd")
        self.assertTrue(result["atomicPointerReplaceDeclared"])
        self.assertFalse(result["executedOnRealProfile"])

    def test_source_fingerprint_tampered_or_traversal_refused(self):
        good = {f"src/m{i:03}.jsx": "a" * 64 for i in range(131)}
        baseline = qa.source_fingerprint(good)
        self.assertEqual(len(baseline), 64)
        bad = dict(good, **{"src/m004.jsx": "b" * 64})
        self.assertNotEqual(qa.source_fingerprint(bad), baseline)
        with self.assertRaisesRegex(qa.NoGo, "131"):
            qa.source_fingerprint({"src/only-one.jsx": "a" * 64})
        for bad_name in ("../evil", "src/../../evil", "C:/tmp", "/absolute",
                         "bad//component", "src/u*.jsx", "src/../evil"):
            with self.subTest(path=bad_name), self.assertRaises(qa.NoGo):
                qa.safe_name(bad_name)

    def test_source_tree_missing_extra_or_tampered_file_refused(self):
        root = self.root / "source"
        root.mkdir()
        first = root / "hello.txt"
        first.write_bytes(b"synthetic")
        wanted = {"hello.txt": qa.digest(first)}
        self.assertEqual(qa.entire_tree_matches(root, wanted), 1)
        first.write_bytes(b"tampered")
        with self.assertRaises(qa.NoGo):
            qa.entire_tree_matches(root, wanted)
        first.write_bytes(b"synthetic")
        extra = root / "extra.txt"
        extra.write_bytes(b"not listed")
        with self.assertRaisesRegex(qa.NoGo, "Unlisted"):
            qa.entire_tree_matches(root, wanted)
        extra.unlink()
        first.unlink()
        with self.assertRaisesRegex(qa.NoGo, "missing"):
            qa.entire_tree_matches(root, wanted)

    def test_rejected_RC1_build_does_not_impersonate_RC3(self):
        with self.assertRaisesRegex(qa.NoGo, "Only observed"):
            qa.inspect(qa.RC1_REJECTED)
        with self.assertRaisesRegex(qa.NoGo, "Only observed"):
            qa.inspect(self.root)

    def test_tampered_exe_pin_denied_before_subgate(self):
        with patch.object(qa, "EXE_SHA", "0" * 64):
            with self.assertRaises(qa.NoGo):
                qa.inspect(qa.BUILD)

    def test_untrusted_or_incorrect_qa_report_rejected(self):
        built = qa.read_obj(qa.BUILD / "build-report.json")
        published = qa.read_obj(qa.BUILD / "offline-update" / "update-manifest.json")
        forged = dict(built, qaBeforeBuild={})
        with self.assertRaisesRegex(qa.NoGo, "witness"):
            qa.qa_witnesses(forged, published)
        with self.assertRaises(qa.NoGo):
            qa.qa_witnesses(dict(built, qa=dict(built["qa"], **{
                "rc2-original-seven-edge": {}})), published)

    def test_all_seven_member_sha_validation_fails_on_zip_data_tamper(self):
        offline = self.root / "offline"
        offline.mkdir()
        for name in qa.ZIP_NAMES:
            (offline / name).write_bytes(("test-" + name).encode())
        bundle = self.root / "synthetic.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in offline.iterdir():
                archive.write(item, item.name)
        baseline = qa.digest(bundle)
        with patch.object(qa, "ZIP_SHA", baseline):
            self.assertEqual(qa.verify_offline_zip(bundle, offline)["membersRehashed"], 7)
            (offline / "package.json").write_bytes(b"tamper")
            with self.assertRaisesRegex(qa.NoGo, "ZIP member"):
                qa.verify_offline_zip(bundle, offline)
            (offline / "package.json").write_bytes(b"test-package.json")
            with zipfile.ZipFile(bundle, "a") as archive:
                archive.writestr("package.json", b"duplicate")
            with patch.object(qa, "ZIP_SHA", qa.digest(bundle)):
                with self.assertRaisesRegex(qa.NoGo, "duplicate"):
                    qa.verify_offline_zip(bundle, offline)

    def test_disposable_gate_rejects_missing_worker26_prior_native_qa(self):
        with self.assertRaisesRegex(qa.NoGo, "not supplied"):
            qa.prior_worker26_qa(None, "", qa.BUILD)
        with self.assertRaises(qa.NoGo):
            qa.prior_worker26_qa(self.root / "absent.json", "0" * 64, qa.BUILD)

    def test_real_worker26_prior_native_ps51_document_is_sha_pinned(self):
        proof = qa.prior_worker26_pinned_document()
        self.assertEqual(proof["documentSha256"], qa.WORKER26_DOCUMENT_SHA)
        self.assertEqual(proof["priorWindowsPS51TestsReportedPass"], 20)
        self.assertEqual(proof["compiledBinary"], qa.EXE_SHA)
        self.assertFalse(proof["productionReleaseApproved"])
        with patch.object(qa, "WORKER26_DOCUMENT_SHA", "0" * 64):
            with self.assertRaises(qa.NoGo):
                qa.prior_worker26_pinned_document()

    def test_disposable_prior_fake_pass_does_not_override_wrong_pin_or_build(self):
        fake = self.root / "prior-worker-26.json"
        content = {
            "status": "PASS", "candidate": str(qa.BUILD),
            "candidateExeSha256": qa.EXE_SHA, "testsFailed": 0, "testsPassed": 6,
            "actualWindowsPS51Tested": True, "installedProfileChanged": False,
            "financePosted": False,
        }
        fake.write_text(json.dumps(content), encoding="utf-8")
        pinned = qa.digest(fake)
        self.assertEqual(qa.prior_worker26_qa(fake, pinned, qa.BUILD)["worker26NativeTests"], 6)
        with self.assertRaises(qa.NoGo):
            qa.prior_worker26_qa(fake, "0" * 64, qa.BUILD)
        with self.assertRaises(qa.NoGo):
            qa.prior_worker26_qa(fake, pinned, qa.RC1_REJECTED)
        fake.write_text(json.dumps(dict(content, testsFailed=1)), encoding="utf-8")
        with self.assertRaises(qa.NoGo):
            qa.prior_worker26_qa(fake, qa.digest(fake), qa.BUILD)

    def test_unconnected_actual_native_execution_and_production_signoff_not_claimed(self):
        src = Path(qa.__file__).read_text(encoding="utf-8")
        self.assertIn("TemporaryDirectory(prefix=\"taraz-rc3-accept-\"", src)
        self.assertIn("b\"NO_REAL_RECORDS_OR_ACCOUNTING\"", src)
        self.assertIn("current-version-pre-1.0.4.txt", src)
        self.assertIn("mklink", src)
        self.assertIn("HardlinkCount", src)
        self.assertIn("prior_worker26_qa", src)
        self.assertNotIn("subprocess.Popen(", src)
        self.assertNotIn("os.startfile(", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
