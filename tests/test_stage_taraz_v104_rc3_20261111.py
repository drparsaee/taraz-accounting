"""Source-only RC3 acceptance. All real installed/profile files remain read-only."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v104_independent_acceptance_20261111 as qa
from scripts import stage_taraz_v104_rc2_20261111 as rc2
from scripts import stage_taraz_v104_rc3_20261111 as rc3

STAGE = qa.OUTPUT / "source-stage-ca9761aa43d8"
VITE = qa.OUTPUT / "vite-qa-72ee216638e4"
SOURCE_SHA = "e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de"
JS_SHA = "3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9"


class RC3SourceOnly(unittest.TestCase):
    def test_full_131_source_hashes_exactly_one_new_change(self):
        previous = rc2.verify_rc2(rc3.RC2_STAGE)
        newer = rc3.verify_rc3(STAGE)
        self.assertEqual(previous["sourceSha256"], rc3.RC2_SOURCE_SHA)
        self.assertEqual(newer["sourceSha256"], SOURCE_SHA)
        self.assertEqual(newer["sourceCount"], 131)
        self.assertEqual(set(newer["sourceFiles"]), set(previous["sourceFiles"]))
        self.assertEqual(
            {key for key in newer["sourceFiles"]
             if newer["sourceFiles"][key] != previous["sourceFiles"][key]},
            {rc3.TARGET})

    def test_locally_authored_range_validation_preserved_raw_analytics_result_masked(self):
        before = (rc3.RC2_STAGE / "source" / rc3.TARGET).read_bytes().decode("utf-8")
        after = (STAGE / "source" / rc3.TARGET).read_bytes().decode("utf-8")
        self.assertEqual(after, rc3.change_text(before))
        self.assertNotIn("{error||analytics.error}", after)
        self.assertIn("(error||analytics?.error)&&", after)
        self.assertIn(
            "{error||'محاسبه شاخص‌های مدیریتی ناموفق بود؛ داده‌های منبع را بررسی کنید.'}",
            after)
        self.assertIn(
            "if(!validRange)return {analytics:null,error:'بازهٔ زمانی باید معتبر",
            after)
        self.assertIn(
            "catch(_error){return {analytics:null,error:'محاسبه شاخص‌های مدیریتی ناموفق بود؛",
            after)

    def test_unexpected_anchors_rejected(self):
        with self.assertRaises(rc3.RC3Blocked):
            rc3.change_text("not matching")
        with self.assertRaises(rc3.RC3Blocked):
            rc3.change_text(rc3.OLD * 2)

    def test_babel_can_parse_changed_component(self):
        node = (
            "const fs=require('fs');const babel=require('@babel/parser');"
            "babel.parse(fs.readFileSync(0,'utf8'),"
            "{sourceType:'module',plugins:['jsx']});")
        content = (STAGE / "source" / rc3.TARGET).read_bytes().decode("utf-8")
        result = subprocess.run(["node", "-e", node], input=content, cwd=ROOT,
                                text=True, encoding="utf-8", errors="replace",
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])

    def test_patch_reverse_applies_only_to_rc3_snapshot(self):
        patches = sorted((STAGE / "reviewed-patches").glob("*.patch"))
        self.assertEqual(len(patches), 1)
        result = subprocess.run(
            ["git", "-C", str(STAGE), "apply", "--check", "--reverse",
             "--directory=source", "-p1", "--", str(patches[0])],
            text=True, encoding="utf-8", errors="replace", capture_output=True,
            timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])

    def test_stage_metadata_no_release_or_native_binary(self):
        report = qa.load_json(STAGE / "stage-report.json")
        self.assertEqual(report["status"], "V104_RC3_SOURCE_ONLY_EDGE_QA_PENDING")
        self.assertEqual(report["sourceSha256"], SOURCE_SHA)
        self.assertEqual(report["changedSourceFiles"], [rc3.TARGET])
        self.assertTrue(report["originalRC2StageUnchanged"])
        self.assertTrue(report["originalV104CandidateUnchanged"])
        self.assertFalse(report["executableBuilt"])
        self.assertFalse(report["releaseApproved"])
        self.assertFalse(report["dynamicEdgeApproved"])
        self.assertFalse(list(STAGE.rglob("Taraz.exe")))

    def test_package_lock_unchanged_and_old_rc2_pinned(self):
        previous = rc2.verify_rc2(rc3.RC2_STAGE)
        current = rc3.verify_rc3(STAGE)
        for name in ("package.json", "package-lock.json"):
            self.assertEqual(current["sourceFiles"][name], previous["sourceFiles"][name])
        self.assertEqual(previous["sourceSha256"], rc3.RC2_SOURCE_SHA)
        self.assertEqual(qa.verify_stage()["sha256"], qa.STAGE_SOURCE_SHA)

    def test_vite_rc3_js_css_html_sha_and_stage_provenance(self):
        report = qa.load_json(VITE / "rc3-vite-qa-report.json")
        stage = rc3.verify_rc3(STAGE)
        self.assertEqual(report["status"], "V104_RC3_STAGE_UI_ONLY_EDGE_QA_PENDING")
        self.assertEqual(report["stage"], str(STAGE))
        self.assertEqual(report["sourceSha256"], SOURCE_SHA)
        self.assertEqual(report["sourceStageReportSha256"], stage["stageReportSha256"])
        self.assertEqual(report["sourceInventoryFileSha256"], stage["sourceManifestSha256"])
        self.assertEqual(report["sourceCount"], 131)
        self.assertFalse(report["compiledExe"])
        self.assertFalse(report["dynamicEdgeApproved"])
        self.assertFalse(report["releaseApproved"])
        self.assertEqual(report["jsSha256"], JS_SHA)
        self.assertNotEqual(report["jsSha256"], qa.VITE_JS_SHA)
        for field, digest in (("jsRelativePath", "jsSha256"),
                              ("cssRelativePath", "cssSha256"),
                              ("htmlRelativePath", "htmlSha256")):
            self.assertEqual(
                qa.hash_file(VITE / report[field], max_bytes=qa.MAX_SOURCE),
                report[digest])
        self.assertFalse(list(VITE.rglob("Taraz.exe")))

    def test_rejected_original_v104_candidate_remains_byte_identical(self):
        self.assertEqual(
            qa.hash_file(qa.REJECTED_V104_BUILD / "binary" / "Taraz.exe"),
            qa.REJECTED_V104_EXE_SHA)
        self.assertEqual(
            qa.hash_file(qa.REJECTED_V104_BUILD /
                         "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip",
                         max_bytes=qa.MAX_ARCHIVE), qa.REJECTED_V104_ZIP_SHA)

    def test_other_stage_cannot_impersonate_rc3(self):
        for candidate in (qa.STAGE, rc3.RC2_STAGE):
            with self.subTest(candidate=candidate.name), self.assertRaises(qa.Blocked):
                rc3.verify_rc3(candidate)


if __name__ == "__main__":
    unittest.main()
