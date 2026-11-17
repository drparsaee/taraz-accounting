"""Source key structural audit: no private data or live database."""
from copy import deepcopy
import unittest

from taraz_journal_source_audit import inspect_source_uniqueness


def journal(id_, source_type, source_id):
    return {"id": id_, "eventId": "event-" + id_, "sourceType": source_type,
            "sourceId": source_id, "lines": [
                {"accountId": "1200", "debit": 300, "credit": 0},
                {"accountId": "4000", "debit": 0, "credit": 300}]}


class SourceUniquenessAuditTests(unittest.TestCase):
    def test_distinct_sources_structurally_accepted_but_not_authenticated(self):
        rows = [journal("J1", "invoice.issue", "s-1"),
                journal("J2", "invoice.issue", "s-2")]
        original = deepcopy(rows)
        report = inspect_source_uniqueness(rows)
        self.assertEqual(rows, original)
        self.assertEqual(report["duplicateSourceOccurrences"], 0)
        self.assertFalse(report["sourceAuthenticated"])
        self.assertFalse(report["tamperProof"])

    def test_duplicate_business_source_detected_with_different_event_id(self):
        report = inspect_source_uniqueness([
            journal("J1", "invoice.issue", "s-1"),
            journal("J2", "invoice.issue", "s-1")])
        self.assertEqual(report["duplicateSourceOccurrences"], 1)
        self.assertTrue(report["blocking"])
        self.assertNotIn("s-1", str(report))

    def test_same_source_id_across_different_types_not_claimed_duplicate(self):
        report = inspect_source_uniqueness([
            journal("J1", "invoice.issue", "s-1"),
            journal("J2", "bill.issue", "s-1")])
        self.assertEqual(report["duplicateSourceOccurrences"], 0)

    def test_duplicate_journal_id_is_rejected_even_with_different_sources(self):
        with self.assertRaises(ValueError):
            inspect_source_uniqueness([
                journal("J1", "bill.issue", "s-1"),
                journal("J1", "bill.issue", "s-2")])

    def test_missing_or_nonstring_source_rejected(self):
        for bad in ({}, {"sourceType": None}, {"sourceId": 4}):
            row = journal("J1", "invoice.issue", "s-1")
            row.update(bad)
            if bad == {}:
                del row["sourceId"]
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                inspect_source_uniqueness([row])

    def test_unbalanced_journal_is_not_claimed_valid_by_source_audit(self):
        row = journal("J1", "invoice.issue", "s-1")
        row["lines"][1]["credit"] = 2
        report = inspect_source_uniqueness([row])
        self.assertFalse(report["tamperProof"])
        self.assertEqual(report["status"], "STRUCTURAL_ONLY")

    def test_limit_and_bad_shape_rejected(self):
        with self.assertRaises(ValueError):
            inspect_source_uniqueness("not a list")
        with self.assertRaises(ValueError):
            inspect_source_uniqueness([None])
        with self.assertRaises(ValueError):
            inspect_source_uniqueness([journal("J1", "x", "y")] * 100001)


if __name__ == "__main__":
    unittest.main()
