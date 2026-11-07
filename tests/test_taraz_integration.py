import json
import tempfile
import unittest
import uuid
from pathlib import Path

from taraz_integration import list_requests, review_request


class TarazIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "pending").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_and_review_does_not_post(self):
        key = uuid.uuid4().hex
        item = {
            "schema": 1, "source": "madar", "id": key,
            "taskId": "saved.task", "title": "Saved task", "projectId": "saved.project",
            "createdUtc": "2026-11-07T08:00:00+00:00", "amountRial": "12340",
        }
        (self.root / "pending" / (key + ".json")).write_text(json.dumps(item), encoding="utf8")
        before = list_requests(self.root)
        self.assertTrue(before["connected"])
        self.assertEqual(len(before["requests"]), 1)
        self.assertEqual(before["requests"][0]["amountRial"], 12340)
        receipt = review_request(self.root, key, "reviewed")
        self.assertFalse(receipt["financialEventCreated"])
        self.assertEqual(list_requests(self.root)["requests"], [])
        self.assertTrue((self.root / "reviewed" / (key + ".review.json")).is_file())

    def test_reject_path_traversal(self):
        with self.assertRaises(ValueError):
            review_request(self.root, "../outside", "rejected")

    def test_invalid_monetary_amount_hidden(self):
        key = uuid.uuid4().hex
        item = {
            "schema": 1, "source": "madar", "id": key,
            "taskId": "t", "title": "Task", "projectId": "p",
            "createdUtc": "2026-11-07T08:00:00+00:00", "amountRial": "3.14",
        }
        (self.root / "pending" / (key + ".json")).write_text(json.dumps(item), encoding="utf8")
        outcome = list_requests(self.root)
        self.assertEqual(outcome["requests"], [])
        self.assertEqual(outcome["invalidCount"], 1)

if __name__ == "__main__":
    unittest.main()
