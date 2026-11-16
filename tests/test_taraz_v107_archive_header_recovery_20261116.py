"""Pure-fixture tests for the v1.0.7 one-time archive recovery guard.

Never reads or writes the actual Windows accounting profile.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import taraz_v107_archive_header_recovery_20261116 as recovery


class ArchiveRecoveryGuardTests(unittest.TestCase):
    def make_rescue(self, folder: Path):
        folder.mkdir()
        for name, content in {
            "original-damaged.sqlite3": b"corrupt-but-preserved",
            "original-completion-manifest.json": b"pinned-marker",
            "reference-intact.sqlite3": b"known-good",
        }.items():
            (folder / name).write_bytes(content)
        (folder / "rescue-evidence.json").write_text(
            json.dumps({
                "status": "PRESERVED_BEFORE_REPAIR",
                "damagedSha256": recovery.BAD_SHA,
                "manifestExpectedSha256": recovery.EXPECTED_SHA,
                "originalPreserved": True,
            }), encoding="utf-8")

    def test_preserved_original_pins_must_match(self):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "rescue"
            self.make_rescue(dest)
            with patch.object(recovery, "RESCUE", dest):
                recovery.verify_existing_rescue(
                    b"corrupt-but-preserved", b"pinned-marker", b"known-good")

    def test_tampered_rescue_is_rejected(self):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "rescue"
            self.make_rescue(dest)
            (dest / "original-damaged.sqlite3").write_bytes(b"changed")
            with patch.object(recovery, "RESCUE", dest):
                with self.assertRaises(recovery.update.ReleaseBlocked):
                    recovery.verify_existing_rescue(
                        b"corrupt-but-preserved", b"pinned-marker", b"known-good")

    def test_preservation_never_overwrites(self):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "copy.sqlite3"
            recovery.preserve_new(dest, b"original")
            with self.assertRaises(FileExistsError):
                recovery.preserve_new(dest, b"overwriting")
            self.assertEqual(dest.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
