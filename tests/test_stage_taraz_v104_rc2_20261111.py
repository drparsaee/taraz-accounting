"""Strict source-only RC2 tests. Never launch native Taraz or edit old stages."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v104_independent_acceptance_20261111 as qa
from scripts import stage_taraz_v104_rc2_20261111 as stage

RC2 = qa.OUTPUT / "source-stage-146b4c62e3f8"
VITE = qa.OUTPUT / "vite-qa-899a40d30820"
RC2_SOURCE_PIN = "aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8"
RC2_JS_PIN = "39295ea85bf2d6ee9fd94fce862c2bc505d4ac6ce01153fbc7ef9d8eea0b5b79"


class RC2SourceSafetyTests(unittest.TestCase):
    def test_exact_two_source_freezes_and_three_changes(self):
        first = qa.verify_stage()
        newer = stage.verify_rc2(RC2)
        self.assertEqual(first["sha256"], qa.STAGE_SOURCE_SHA)
        self.assertEqual(newer["sourceSha256"], RC2_SOURCE_PIN)
        self.assertEqual(newer["sourceCount"], 131)
        self.assertEqual(set(newer["sourceFiles"]), set(first["inventory"]))
        self.assertEqual({k for k in newer["sourceFiles"]
                          if newer["sourceFiles"][k] != first["inventory"][k]},
                         qa.RC2_TARGETS)
        self.assertEqual(len(qa.RC2_TARGETS), 3)

    def test_rc2_is_new_create_only_stage_with_no_binary_or_source_merge(self):
        report = qa.load_json(RC2 / "stage-report.json")
        self.assertEqual(report["status"], "V104_RC2_SOURCE_ONLY_DYNAMIC_QA_PENDING")
        self.assertEqual(report["parentStage"], str(qa.STAGE))
        self.assertEqual(report["changedFileCount"], 3)
        self.assertFalse(report["executableBuilt"])
        self.assertFalse(report["releaseApproved"])
        self.assertFalse(report["dynamicRC2EdgeVerified"])
        self.assertTrue(report["originalStageRehashedAndUnchanged"])
        self.assertTrue(report["originalCandidateRehashedAndUnchanged"])
        self.assertEqual(report["stagedPackageVersionUntouched"], "1.0.0")
        self.assertFalse(list(RC2.rglob("Taraz.exe")))

    def test_earlier_rejected_v104_binary_and_zip_unchanged(self):
        self.assertEqual(qa.hash_file(qa.REJECTED_V104_BUILD / "binary" / "Taraz.exe"),
                         qa.REJECTED_V104_EXE_SHA)
        self.assertEqual(qa.hash_file(
            qa.REJECTED_V104_BUILD / "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip",
            max_bytes=qa.MAX_ARCHIVE), qa.REJECTED_V104_ZIP_SHA)

    def test_only_three_source_patches_match_reviewed_exact_anchors(self):
        before = qa.verify_stage()
        after = stage.verify_rc2(RC2)
        for name in qa.RC2_TARGETS:
            raw = (qa.STAGE / "source" / name).read_bytes().decode("utf-8")
            transformed = qa.propose_rc2_text(name, raw)
            self.assertNotEqual(raw, transformed, name)
            self.assertEqual((RC2 / "source" / name).read_bytes(), transformed.encode("utf-8"))
            self.assertNotEqual(before["inventory"][name], after["sourceFiles"][name])
        self.assertEqual(after["sourceFiles"]["package.json"],
                         before["inventory"]["package.json"])
        self.assertEqual(after["sourceFiles"]["package-lock.json"],
                         before["inventory"]["package-lock.json"])

    def test_duplicate_anchor_or_wrong_target_fails_closed(self):
        source_file = "src/accounting_print_designer.jsx"
        old, _ = qa.RC2_PATCHES[source_file]
        with self.assertRaisesRegex(qa.Blocked, "unique|drift"):
            qa.propose_rc2_text(source_file, old * 2)
        with self.assertRaisesRegex(qa.Blocked, "ownership"):
            qa.propose_rc2_text("src/not-allowed.jsx", old)
        with self.assertRaisesRegex(qa.Blocked, "unique|drift"):
            qa.propose_rc2_text(source_file, "no source match")

    def test_print_canvas_fallback_and_local_template_validation_are_separate(self):
        content = (RC2 / "source" / "src" / "accounting_print_designer.jsx").read_bytes().decode("utf-8")
        self.assertIn("setError('پیش‌نمایش ناموفق بود؛ قالب چاپ و تصویر را بررسی کنید.')", content)
        self.assertNotIn("setError(e.message||'پیش‌نمایش ناموفق بود.')", content)
        self.assertIn("validatePrintTemplate(next)", content)
        self.assertIn("فقط لوگوی PNG/JPEG کوچک‌تر از ۱۸۰ کیلوبایت مجاز است.", content)

    def test_management_bad_host_record_id_is_not_exposed_by_catch(self):
        content = (RC2 / "source" / "src" / "accounting_management_dashboard.jsx").read_bytes().decode("utf-8")
        self.assertIn("catch(_error){return {analytics:null,error:'محاسبه شاخص‌های مدیریتی ناموفق بود؛", content)
        self.assertNotIn("err?.message||'محاسبه شاخص‌های مدیریتی ناموفق بود.'", content)
        self.assertIn("if(!validRange)return {analytics:null,error:'بازهٔ زمانی باید معتبر", content)

    def test_bank_csv_file_read_errors_masked_and_authored_parser_messages_preserved(self):
        content = (RC2 / "source" / "src" / "accounting_operational_panels.jsx").read_bytes().decode("utf-8")
        self.assertIn("try{value=await file.text();}", content)
        self.assertIn("catch(_error){", content)
        self.assertIn("setImportError('خواندن فایل CSV بانک ناموفق بود.');return;", content)
        self.assertIn("const rowError=/^", content)
        self.assertIn("عنوان ستون‌های CSV باید دقیقاً مطابق قالب اعلام‌شده باشد.", content)
        self.assertIn("مبلغ ردیف [0-9]{1,3} باید عدد صحیح علامت‌دار باشد", content)
        self.assertIn("setImportError(authored.has(message)||rowError.test(message)", content)
        self.assertNotIn("}catch(err){setImportError(err.message||'خواندن فایل معتبر نبود.');}", content)

    def test_all_three_rc2_jsx_files_parse_as_real_babel_modules(self):
        self.assertTrue((ROOT / "node_modules" / "@babel" / "parser").is_dir())
        script = (
            "const fs=require('fs');const babel=require('@babel/parser');"
            "babel.parse(fs.readFileSync(0,'utf8'),"
            "{sourceType:'module',plugins:['jsx']});"
        )
        for relative in sorted(qa.RC2_TARGETS):
            content = (RC2 / "source" / relative).read_bytes().decode("utf-8")
            result = subprocess.run(["node", "-e", script], input=content,
                                    cwd=ROOT, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=20)
            self.assertEqual(result.returncode, 0, relative + ": " + result.stderr[-400:])

    def test_reviewed_patch_hunks_apply_to_old_source_without_writing(self):
        patches = sorted(str(path) for path in (RC2 / "reviewed-patches").glob("*.patch"))
        self.assertEqual(len(patches), 3)
        result = subprocess.run(
            ["git", "-C", str(RC2), "apply", "--check", "--directory=source",
             "-p1", "--reverse", "--", *patches],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_vite_rc2_is_qa_only_and_asset_shas_match(self):
        report = qa.load_json(VITE / "rc2-vite-qa-report.json")
        self.assertEqual(report["status"], "V104_RC2_STAGE_UI_ONLY_EDGE_QA_PENDING")
        self.assertEqual(report["sourceSha256"], RC2_SOURCE_PIN)
        self.assertEqual(report["sourceCount"], 131)
        self.assertFalse(report["nativeExeBuilt"])
        self.assertFalse(report["dynamicEdgeApproved"])
        self.assertFalse(report["releaseApproved"])
        self.assertTrue(report["sourceRehashedBeforeAfter"])
        self.assertEqual(report["jsSha256"], RC2_JS_PIN)
        self.assertNotEqual(RC2_JS_PIN, qa.VITE_JS_SHA)
        for field, digest_key in (
            ("jsRelativePath", "jsSha256"),
            ("cssRelativePath", "cssSha256"),
            ("htmlRelativePath", "htmlSha256"),
        ):
            self.assertEqual(qa.hash_file(VITE / report[field],
                                          max_bytes=qa.MAX_SOURCE), report[digest_key])
        self.assertFalse(list(VITE.rglob("Taraz.exe")))

    def test_attempt_to_use_untrusted_old_stage_as_rc2_is_rejected(self):
        with self.assertRaises(stage.StageRC2Blocked):
            stage.verify_rc2(qa.STAGE)
        with self.assertRaises(qa.Blocked):
            stage.verify_rc2(qa.OUTPUT / "source-stage-does-not-exist")


if __name__ == "__main__":
    unittest.main()
