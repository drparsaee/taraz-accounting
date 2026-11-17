"""No private files used. Inspect only synthetic source-metadata summaries."""
from copy import deepcopy
import unittest

from taraz_parsian_coverage import inspect_parsian_coverage


def synthetic_manifest():
    return {
        "schemaVersion": 1,
        "sourceSystem": "parsian",
        "currency": "RIAL",
        "expectedYears": ["1404", "1405"],
        "expectedModules": ["parties", "accounts", "invoices", "journals", "settlements"],
        "observedYears": [
            {"year": year, "modules": [
                {"module": module, "rows": 3, "sha256": ("a" if year == "1404" else "b") * 64}
                for module in ("parties", "accounts", "invoices", "journals", "settlements")
            ]} for year in ("1404", "1405")
        ],
    }


class ParsianCoverageTests(unittest.TestCase):
    def test_complete_metadata_is_still_not_authenticated_or_importable(self):
        manifest = synthetic_manifest()
        before = deepcopy(manifest)
        report = inspect_parsian_coverage(manifest)
        self.assertEqual(manifest, before)
        self.assertTrue(report["structurallyComplete"])
        self.assertFalse(report["readyForMigration"])
        self.assertFalse(report["postingAllowed"])
        self.assertFalse(report["sourceAuthenticated"])
        self.assertEqual(report["status"], "SOURCE_EVIDENCE_REQUIRED")

    def test_missing_year_is_explicit_not_invented(self):
        manifest = synthetic_manifest()
        manifest["observedYears"].pop()
        report = inspect_parsian_coverage(manifest)
        self.assertEqual(report["missing"], ["1405:*"])
        self.assertEqual(report["coverage"][-1]["status"], "MISSING_YEAR")

    def test_missing_module_is_reported_without_guessing_amounts(self):
        manifest = synthetic_manifest()
        manifest["observedYears"][0]["modules"].pop()
        report = inspect_parsian_coverage(manifest)
        self.assertIn("1404:settlements", report["missing"])
        self.assertNotIn("amount", str(report).lower())

    def test_unexpected_year_does_not_silently_count_as_complete(self):
        manifest = synthetic_manifest()
        manifest["observedYears"].append({
            "year": "1403", "modules": [{"module": "parties", "rows": 0, "sha256": "c" * 64}]})
        report = inspect_parsian_coverage(manifest)
        self.assertEqual(report["unexpectedYears"], ["1403"])
        self.assertFalse(report["structurallyComplete"])

    def test_no_implicit_toman_or_missing_authoritative_year_list(self):
        manifest = synthetic_manifest()
        manifest["currency"] = "TOMAN"
        with self.assertRaises(ValueError):
            inspect_parsian_coverage(manifest)
        manifest = synthetic_manifest()
        manifest["expectedYears"] = []
        with self.assertRaises(ValueError):
            inspect_parsian_coverage(manifest)

    def test_duplicate_year_and_module_fail_closed(self):
        manifest = synthetic_manifest()
        manifest["observedYears"].append(deepcopy(manifest["observedYears"][0]))
        with self.assertRaises(ValueError):
            inspect_parsian_coverage(manifest)
        manifest = synthetic_manifest()
        manifest["observedYears"][0]["modules"].append(
            deepcopy(manifest["observedYears"][0]["modules"][0]))
        with self.assertRaises(ValueError):
            inspect_parsian_coverage(manifest)

    def test_malformed_digest_and_negative_rows_rejected(self):
        manifest = synthetic_manifest()
        manifest["observedYears"][0]["modules"][0]["sha256"] = "unverified"
        with self.assertRaises(ValueError):
            inspect_parsian_coverage(manifest)
        manifest = synthetic_manifest()
        manifest["observedYears"][0]["modules"][0]["rows"] = -1
        with self.assertRaises(ValueError):
            inspect_parsian_coverage(manifest)
        manifest = synthetic_manifest()
        manifest["observedYears"][0]["modules"][0]["rows"] = True
        with self.assertRaises(ValueError):
            inspect_parsian_coverage(manifest)

    def test_raw_rows_private_names_and_paths_forbidden(self):
        for unwanted_field in ("customerName", "rawRows", "sourcePath", "accountBalance"):
            manifest = synthetic_manifest()
            manifest["observedYears"][0]["modules"][0][unwanted_field] = "private data"
            with self.subTest(field=unwanted_field), self.assertRaises(ValueError):
                inspect_parsian_coverage(manifest)

    def test_bounded_input_no_raw_dataset_dump(self):
        manifest = synthetic_manifest()
        manifest["expectedYears"] = [f"{i:04d}" for i in range(101)]
        with self.assertRaises(ValueError):
            inspect_parsian_coverage(manifest)
        manifest = synthetic_manifest()
        manifest["observedYears"][0]["modules"][0]["rows"] = 100_000_001
        with self.assertRaises(ValueError):
            inspect_parsian_coverage(manifest)


if __name__ == "__main__":
    unittest.main()
