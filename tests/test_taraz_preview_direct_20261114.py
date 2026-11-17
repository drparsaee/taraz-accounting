"""Ensure user-visible QA preview skips Tk login without weakening production."""
from __future__ import annotations

from contextlib import nullcontext
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from scripts import run_taraz_preview_20261114 as demo


@unittest.skipUnless(os.name == "nt", "Windows-only preview")
class DirectTarazPreviewTests(unittest.TestCase):
    def test_existing_private_fixture_is_pinned_and_usable(self):
        info = demo.verify()
        self.assertEqual(info["status"], "READY_SOURCE_PREVIEW_NOT_INSTALLED")
        self.assertTrue(info["syntheticOnly"])
        self.assertTrue(info["sourceHosted"])
        self.assertFalse(info["installedVersionChanged"])
        self.assertEqual(info["ledgerRevision"], 6)
        self.assertEqual(demo.PROFILE, demo.RUNTIME / "roaming" / "Taraz")

    def test_launch_runs_only_pinned_demo_child_without_native_tk_entrypoint(self):
        sentinel = SimpleNamespace(returncode=0)
        with patch.object(demo, "prepare", return_value={"syntheticOnly": True}), \
             patch.object(demo, "isolated_environment", return_value={"TARAZ_QA_MODE": "1"}), \
             patch.object(demo, "preview_lock", return_value=nullcontext()), \
             patch.object(demo.subprocess, "run", return_value=sentinel) as spawn:
            self.assertEqual(demo.launch(), 0)
        command = spawn.call_args.args[0]
        self.assertEqual(command[-1], "--demo-child")
        self.assertEqual(Path(command[2]), Path(demo.__file__).resolve())
        self.assertNotIn("taraz_desktop.py", " ".join(command))

    def test_child_cannot_run_with_missing_or_ambient_profile(self):
        with patch.dict(os.environ, {
            "TARAZ_QA_MODE": "0",
            "TARAZ_QA_DATA_DIR": str(demo.PROFILE),
            "APPDATA": str(demo.RUNTIME / "roaming"),
            "LOCALAPPDATA": str(demo.RUNTIME / "localappdata"),
        }):
            with self.assertRaises(demo.PreviewBlocked):
                demo.run_synthetic_demo_child()


if __name__ == "__main__":
    unittest.main()
