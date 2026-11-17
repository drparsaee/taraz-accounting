"""Regression test: the delivery board must not turn aspirations into PASS."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts.validate_taraz_phase_board import BoardError, validate


BOARD = Path(__file__).resolve().parents[1] / "docs/ops/taraz-phase-board.json"


class PhaseBoardTests(unittest.TestCase):
    def setUp(self):
        self.board = json.loads(BOARD.read_text(encoding="utf-8"))

    def check_invalid(self, mutate, message=None):
        sample = deepcopy(self.board)
        mutate(sample)
        with self.assertRaises(BoardError) as err:
            validate(sample)
        if message:
            self.assertIn(message, str(err.exception))

    def test_board_is_valid_and_not_release_ready(self):
        result = validate(self.board)
        self.assertEqual(result["active"], "TAR-10")
        self.assertEqual(result["verified"], 5)
        self.assertEqual(result["blocked"], 2)
        self.assertEqual(result["release"], "NO-GO")
        self.assertEqual(result["tasks"], 16)

    def test_second_active_task_fails_closed(self):
        self.check_invalid(lambda b: b["tasks"][10].update(status="active"), "one matching active")

    def test_fake_pass_without_evidence_is_refused(self):
        self.check_invalid(lambda b: b["tasks"][10].update(status="source_verified"),
                           "no exact commit proof")

    def test_fake_pass_with_fake_test_is_refused(self):
        self.check_invalid(lambda b: b["tasks"][10].update(
            status="source_verified", evidence=["commit:" + "a" * 40]),
            "no passing test proof")

    def test_ready_for_release_while_open_is_refused(self):
        self.check_invalid(lambda b: b["execution"].update(releaseStatus="READY"), "release gate")

    def test_active_task_cannot_skip_dependency(self):
        self.check_invalid(lambda b: b["tasks"][3].update(dependsOn=["TAR-05"]),
                           "Dependency cycle")

    def test_unknown_and_duplicate_dependency_rejected(self):
        self.check_invalid(lambda b: b["tasks"][3].update(dependsOn=["TAR-99"]),
                           "Unknown dependency")
        self.check_invalid(lambda b: b["tasks"][3].update(dependsOn=["TAR-01", "TAR-01"]),
                           "Invalid dependencies")

    def test_unsafe_runtime_authorization_rejected(self):
        self.check_invalid(lambda b: b["execution"].update(productionDataAuthorized=True),
                           "Unsafe authorization")

    def test_duplicate_task_ids_are_invalid(self):
        self.check_invalid(lambda b: b["tasks"][4].update(id="TAR-04"),
                           "Duplicate or invalid")

    def test_cycle_in_queued_tasks_rejected(self):
        self.check_invalid(lambda b: b["tasks"][4].update(dependsOn=["TAR-06"]),
                           "Dependency cycle")

    def test_verified_task_cannot_depend_on_queued_work(self):
        self.check_invalid(
            lambda b: b["tasks"][-1].update(
                status="source_verified",
                evidence=["commit:" + "a" * 40, "synthetic-review:1/1 PASS"]),
            "unmet dependencies")


if __name__ == "__main__":
    unittest.main()
