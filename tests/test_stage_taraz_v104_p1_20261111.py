"""Source-only v1.0.4 detached stage: pinned snapshot and reviewed patch tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import stage_taraz_v104_p1_20261111 as stage


class V104SourceStageTests(unittest.TestCase):
    def test_frozen_starting_inventory_is_complete(self):
        values = stage.checked_inventory()
        self.assertEqual(len(values), 131)
        self.assertEqual(stage.v103.fingerprint(values), stage.START_SHA)
        self.assertIn("src/personal_parsian_company.jsx", values)
        self.assertIn("src/provider_csv_migration.jsx", values)

    def test_freeze_drift_is_blocked(self):
        clean = stage.checked_inventory()
        drift = dict(clean)
        drift["src/personal_parsian_company.jsx"] = "0" * 64
        with patch.object(stage.v103, "inventory", return_value=drift):
            with self.assertRaisesRegex(stage.StageBlocked, "changed"):
                stage.checked_inventory()
        with patch.object(stage.v103, "inventory", return_value={"package.json": "f" * 64}):
            with self.assertRaisesRegex(stage.StageBlocked, "131"):
                stage.checked_inventory()

    def test_path_escape_and_duplicate_handler_anchor_block(self):
        for value in ("../escape", "src/../escape", "/etc/shadow",
                      "C:\\windows\\system.ini", "src//evil", "src\\file.jsx"):
            with self.subTest(value=value), self.assertRaises(stage.StageBlocked):
                stage._relative(value)
        name = "src/personal_parsian_company.jsx"
        anchor = stage.PROPOSALS[name][0][0]
        with self.assertRaisesRegex(stage.StageBlocked, "handler anchor"):
            stage.changed_text(name, anchor * 2)

    def test_all_local_transformations_preserve_authored_validation(self):
        values = stage.checked_inventory()
        checked = {}
        for rel in stage.PROPOSALS:
            self.assertIn(rel, values)
            source = (stage.ROOT / rel).read_bytes().decode("utf-8")
            proposed, edits = stage.changed_text(rel, source)
            self.assertNotEqual(source, proposed, rel)
            self.assertEqual(len(edits), len(stage.PROPOSALS[rel]))
            self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), values[rel])
            for old, new, _purpose in stage.PROPOSALS[rel]:
                self.assertNotIn(old, proposed.replace("\r\n", "\n"), rel)
                self.assertIn(new, proposed.replace("\r\n", "\n"), rel)
            checked[rel] = proposed
        self.assertEqual(len(checked), 9)
        self.assertIn("اطلاعات معتبر ۱۹۵ فاکتور پارسیان دریافت نشد.",
                      checked["src/personal_parsian_invoices.jsx"])
        self.assertIn("مرورگر آرشیو کامل در میزبان فعال نیست.",
                      checked["src/parsian_raw_archive_explorer.jsx"])
        self.assertIn("انتخاب فایل در نسخه میزبان فعال نیست.",
                      checked["src/provider_csv_migration.jsx"])
        self.assertIn("پیش‌نمایش در نسخه میزبان فعال نیست.",
                      checked["src/provider_csv_migration.jsx"])
        self.assertIn("request=buildProviderCsvRequest(", checked["src/provider_csv_migration.jsx"])
        self.assertIn("exc instanceof Error?exc.message", checked["src/provider_csv_migration.jsx"])
        self.assertIn("}catch(_error){setError('خواندن پیش‌نمایش CSV",
                      checked["src/provider_csv_migration.jsx"])

    def test_seven_edge_proven_host_secret_paths_are_masked_in_proposal(self):
        targets = {
            "src/personal_parsian_company.jsx",
            "src/taraz_home_command.jsx",
            "src/personal_parsian_extended.jsx",
            "src/personal_parsian_invoices.jsx",
            "src/personal_parsian_bank_movements.jsx",
            "src/parsian_raw_archive_explorer.jsx",
            "src/provider_csv_migration.jsx",
        }
        self.assertTrue(targets <= set(stage.PROPOSALS))
        self.assertEqual(stage.CONFIRMED_DYNAMIC, targets)
        for relative in targets:
            before = (stage.ROOT / relative).read_bytes().decode("utf-8")
            after, _edits = stage.changed_text(relative, before)
            self.assertNotIn(stage.RAW_HOST_SENTINEL, after)
            self.assertNotEqual(before, after)
        self.assertIn("setError('خواندن سطرهای آرشیوی ناموفق بود.')",
                      stage.changed_text("src/parsian_raw_archive_explorer.jsx",
                                         (stage.ROOT / "src/parsian_raw_archive_explorer.jsx").read_bytes().decode("utf-8"))[0])

    def test_v104_package_and_lock_proposals_do_not_write_source(self):
        values = stage.checked_inventory()
        before = {name: stage._sha(stage.ROOT / name)
                  for name in ("package.json", "package-lock.json")}
        proposals = stage.version_proposals(values)
        for name, value in proposals.items():
            self.assertEqual(json.loads(value)["version"], "1.0.4")
            if name == "package-lock.json":
                self.assertEqual(json.loads(value)["packages"][""]["version"], "1.0.4")
        self.assertEqual(before, {name: stage._sha(stage.ROOT / name) for name in before})

    def test_proposals_parse_as_jsx_without_writing_source(self):
        if not (stage.ROOT / "node_modules" / "@babel" / "parser").is_dir():
            self.skipTest("@babel/parser dependency absent")
        js = (
            "const fs=require('fs');"
            "const p=require('@babel/parser');"
            "const source=fs.readFileSync(0,'utf8');"
            "p.parse(source,{sourceType:'module',plugins:['jsx']});"
        )
        for rel in stage.PROPOSALS:
            text = (stage.ROOT / rel).read_bytes().decode("utf-8")
            proposed, _ = stage.changed_text(rel, text)
            result = subprocess.run(
                ["node", "-e", js], input=proposed, text=True, capture_output=True,
                encoding="utf-8", errors="replace", cwd=stage.ROOT, timeout=12, check=False)
            self.assertEqual(result.returncode, 0, rel + ": " + result.stderr[-350:])

    @unittest.skipUnless(os.environ.get("TARAZ_V104_SOURCE_STAGE"),
                         "Set TARAZ_V104_SOURCE_STAGE for artifact checks")
    def test_actual_created_stage_is_exact_131_file_snapshot(self):
        stage_root = Path(os.environ["TARAZ_V104_SOURCE_STAGE"])
        self.assertEqual(stage_root.parent.resolve(), stage.OUTPUT.resolve())
        self.assertTrue(stage_root.name.startswith("source-stage-"))
        report = json.loads((stage_root / "stage-report.json").read_text(encoding="utf-8"))
        index = json.loads((stage_root / "proposal-index.json").read_text(encoding="utf-8"))
        inventory = json.loads((stage_root / "starting-source-sha256.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "V104_SOURCE_STAGE_ONLY_PATCHES_PENDING_REVIEW")
        self.assertEqual(report["frozenStartingSha256"], stage.START_SHA)
        self.assertFalse(report["executableBuilt"])
        self.assertFalse(report["productionInstalled"])
        self.assertFalse(report["runtimeReleaseAuthorized"])
        self.assertFalse(report["sourceSnapshotModified"])
        self.assertEqual(stage.v103.fingerprint(inventory), stage.START_SHA)
        self.assertEqual(len(inventory), 131)
        self.assertEqual(len(index), 11)
        self.assertEqual(report["proposedPatchFileCount"], len(index))
        stage.verify_snapshot(stage_root / "source", inventory)
        self.assertEqual(stage._sha(stage_root / "proposal-index.json"),
                         report["proposalsIndexSha256"])
        for relative, metadata in index.items():
            self.assertFalse(metadata["appliedToSnapshot"])
            self.assertEqual(metadata["startingSha256"], inventory[relative])
            patch_path = stage_root / "proposals" / metadata["patchName"]
            self.assertEqual(stage._sha(patch_path), metadata["patchSha256"])
            patch_text = patch_path.read_text(encoding="utf-8")
            self.assertIn("--- a/" + relative, patch_text)
            self.assertIn("+++ b/" + relative, patch_text)
        self.assertEqual(len(list((stage_root / "proposals").glob("*.patch"))), 11)

    @unittest.skipUnless(os.environ.get("TARAZ_V104_PATCHED_STAGE"),
                         "Set TARAZ_V104_PATCHED_STAGE for separate materialized-stage checks")
    def test_second_stage_contains_only_reviewed_masking_changes(self):
        second = Path(os.environ["TARAZ_V104_PATCHED_STAGE"])
        self.assertEqual(second.parent.resolve(), stage.OUTPUT.resolve())
        report = json.loads((second / "stage-report.json").read_text(encoding="utf-8"))
        manifest = json.loads((second / "patched-source-sha256.json").read_text(encoding="utf-8"))
        original = stage.checked_inventory()
        self.assertEqual(report["status"], "V104_PATCHED_SOURCE_FROZEN_QA_PENDING_NO_EXE")
        self.assertFalse(report["executableBuilt"])
        self.assertFalse(report["runtimeReleaseAuthorized"])
        self.assertEqual(len(manifest), 131)
        self.assertEqual(len(report["editedSourceFiles"]), 9)
        self.assertEqual(set(report["editedSourceFiles"]), set(stage.PROPOSALS))
        self.assertEqual({k for k in original if manifest[k] != original[k]},
                         set(stage.PROPOSALS))
        self.assertEqual(manifest["package.json"], original["package.json"])
        self.assertEqual(manifest["package-lock.json"], original["package-lock.json"])
        self.assertEqual(stage.v103.fingerprint(manifest), report["patchedSourceSha256"])
        self.assertEqual(stage._sha(second / "patched-source-sha256.json"),
                         report["patchedInventoryFileSha256"])
        stage.verify_snapshot(second / "source", manifest)
        self.assertNotEqual(report["patchedSourceSha256"], stage.START_SHA)
        for relative in stage.PROPOSALS:
            proposed, _ = stage.changed_text(
                relative, (stage.ROOT / relative).read_bytes().decode("utf-8"))
            self.assertEqual((second / "source" / relative).read_bytes(),
                             proposed.encode("utf-8"))
        original_stage = Path(report["fromStage"])
        stage.verify_snapshot(original_stage / "source", original)

    def test_materialize_rejects_unknown_parent_stage(self):
        with self.assertRaisesRegex(stage.StageBlocked, "not trusted"):
            stage.materialize_reviewed(stage.ROOT)

    @unittest.skipUnless(os.environ.get("TARAZ_V104_VITE_QA_STAGE"),
                         "Set TARAZ_V104_VITE_QA_STAGE for compiled frontend checks")
    def test_detached_vite_bundle_pins_source_and_assets(self):
        qa = Path(os.environ["TARAZ_V104_VITE_QA_STAGE"])
        self.assertEqual(qa.parent.resolve(), stage.OUTPUT.resolve())
        self.assertTrue(qa.name.startswith("vite-qa-"))
        report = json.loads((qa / "vite-qa-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "STAGE_UI_ONLY")
        self.assertTrue(report["compiledFrontend"])
        self.assertFalse(report["compiledExeBuilt"])
        self.assertFalse(report["compiledBundleReleaseReady"])
        self.assertFalse(report["installedTarazTouched"])
        self.assertFalse(report["browserQaVerified"])
        self.assertTrue(report["sourceShaBeforeAfterIdentical"])
        second = Path(report["sourceStagePath"])
        second_report = json.loads((second / "stage-report.json").read_text(encoding="utf-8"))
        self.assertEqual(second_report["patchedSourceSha256"], report["patchedSourceSha256"])
        pins = json.loads((second / "patched-source-sha256.json").read_text(encoding="utf-8"))
        stage.verify_snapshot(second / "source", pins)
        self.assertEqual(stage.v103.fingerprint(pins), report["patchedSourceSha256"])
        for suffix, name, hash_name in (
            (".js", "jsRelativePath", "viteJsSha256"),
            (".css", "cssRelativePath", "viteCssSha256"),
            (".html", "htmlRelativePath", "viteHtmlSha256"),
        ):
            path = qa / report[name]
            self.assertTrue(path.is_file())
            self.assertTrue(path.suffix == suffix)
            self.assertEqual(stage._sha(path), report[hash_name])
        self.assertFalse(list(qa.rglob("Taraz.exe")))


if __name__ == "__main__":
    unittest.main()
