"""Synthetic offline epoch proof and fail-closed transition regression tests.

No listener, finance data, installed service, real profiles, or external I/O.
Only disposable temporary SQLite and create-only evidence files.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from taraz_mtr_epoch_rollover import (
    EpochEvidenceInvalid, EpochRolloverBlocked, _approval_payload,
    _publish_create_only_json,
    activate_epoch, prepare_offline_epoch_evidence,
)
from taraz_mtr_peer_registry import (
    PeerConfig, PeerConflict, PeerDenied, TarazPeerRegistry,
)
from tests.test_taraz_mtr_peer_registry import NOW, _subject, _wire


class OfflineEpochRolloverTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(prefix="taraz-epoch-offline-")
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.config = PeerConfig(
            "office-one", "madar-host-1", "madar-key",
            "taraz-peer-1", "taraz-key", b"m" * 32, b"t" * 32,
        )
        self.proposed = PeerConfig(
            "office-one", "madar-host-1", "madar-next",
            "taraz-peer-1", "taraz-next", b"n" * 32, b"u" * 32,
        )
        self.original_path = self.root / "active.sqlite3"
        self.registry = TarazPeerRegistry(self.original_path, self.config)
        self.archive = self.root / "original-evidence.sqlite3"
        self.receipt = self.root / "offline-intent.json"
        self.original_id = "a" * 32
        self.query_id = "b" * 32
        self.original_request = _wire(
            "request", {"schema": 1, "title": "synthetic request"},
            self.original_id,
        )
        self.subject = _subject(json.loads(self.original_request))
        self.original_query = _wire("query", self.subject, self.query_id)

    def approval(self, *, config=None, new=None, archive=None, receipt=None):
        config = self.config if config is None else config
        new = self.proposed if new is None else new
        return hmac.new(
            config.taraz_secret,
            _approval_payload(
                self.registry, new, archive or self.archive,
                receipt or self.receipt,
            ),
            hashlib.sha256,
        ).digest()

    def prepare(self, **overrides):
        arguments = dict(
            registry=self.registry, host_config=self.config,
            proposed_config=self.proposed,
            archive_path=self.archive, receipt_path=self.receipt,
            approval_mac=self.approval(),
        )
        arguments.update(overrides)
        return prepare_offline_epoch_evidence(**arguments)

    def intake_query(self):
        self.registry.intake(
            self.original_request, now=NOW, verified_transport_peer=True)
        self.registry.query_receipt(
            self.original_query, now=NOW, verified_transport_peer=True)

    def fill_to_10k(self):
        self.intake_query()
        with closing(sqlite3.connect(self.original_path)) as db:
            db.executemany(
                "INSERT INTO queries(query_id,org,original_id,original_sha,"
                "query_sha,actor_role) VALUES(?,?,?,?,?,?)",
                ((f"{i:032x}", "office-one", "f" * 32,
                  "e" * 64, "d" * 64, "editor") for i in range(9999)),
            )
            db.commit()
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM queries").fetchone()[0], 10000)

    def test_evidence_preserves_every_binding_and_both_origins_without_activation(self):
        self.fill_to_10k()
        result = self.prepare()
        self.assertEqual(result["status"], "BLOCKED_PENDING_EPOCH_AWARE_REGISTRY")
        self.assertFalse(result["activationAuthorized"])
        self.assertFalse(result["liveQueryCapacityReleased"])
        self.assertEqual(result["historicalQueryCount"], 10000)
        self.assertTrue(self.archive.is_file())
        self.assertTrue(self.receipt.is_file())
        manifest = json.loads(self.receipt.read_text(encoding="utf-8"))
        self.assertEqual(manifest["queryBindingsSha256"], result["queryBindingsSha256"])
        self.assertEqual(result["archiveSha256"],
                         hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertEqual(result["receiptSha256"],
                         hashlib.sha256(self.receipt.read_bytes()).hexdigest())
        self.assertEqual(manifest["historicalAuditCount"], 1)
        self.assertEqual(manifest["historicalRequestCount"], 1)
        self.assertEqual(manifest["historicalQueryCount"], 10000)
        self.assertTrue(manifest["noAutoResend"])
        self.assertNotIn(self.config.taraz_secret.hex(), self.receipt.read_text())
        self.assertNotIn(self.proposed.taraz_secret.hex(), self.receipt.read_text())
        with closing(sqlite3.connect(f"{self.archive.as_uri()}?mode=ro",
                                    uri=True)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM queries").fetchone()[0],
                             10000)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
                             1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 1)
            self.assertEqual(db.execute(
                "SELECT original_id FROM queries WHERE query_id=?",
                (self.query_id,)).fetchone()[0], self.original_id)
        self.assertEqual(self.registry.query_capacity_status()["remaining"], 0)
        self.assertEqual(json.loads(self.registry.query_receipt(
            self.original_query, now=NOW,
            verified_transport_peer=True))["payload"]["lookupStatus"], "received")
        with self.assertRaisesRegex(PeerDenied, "capacity reached"):
            self.registry.query_receipt(
                _wire("query", self.subject, "c" * 32),
                now=NOW, verified_transport_peer=True)
        with self.assertRaises(EpochRolloverBlocked):
            activate_epoch(self.registry, self.proposed)

    def test_conflicting_old_id_reuse_fails_with_old_registry_after_evidence(self):
        self.intake_query()
        self.prepare()
        changed = _wire("query", {
            "originalRequestId": "f" * 32,
            "originalPayloadSha256": "e" * 64,
            "originalPurpose": "finance_review_request",
        }, self.query_id)
        reopened = TarazPeerRegistry(self.original_path, self.config)
        with self.assertRaises(PeerConflict):
            reopened.query_receipt(
                changed, now=NOW, verified_transport_peer=True)
        with closing(sqlite3.connect(self.original_path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM queries").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 1)

    def test_new_empty_registry_is_unprotected_against_historical_reuse(self):
        """Demonstrate why activation MUST be blocked until old IDs are consulted."""
        self.intake_query()
        self.prepare()
        candidate = TarazPeerRegistry(
            self.root / "unsafe-new-epoch-fixture.sqlite3", self.proposed)
        wrong_subject = {
            "originalRequestId": "f" * 32,
            "originalPayloadSha256": "e" * 64,
            "originalPurpose": "finance_review_request",
        }
        new_signed_wire = _wire(
            "query", wrong_subject, self.query_id,
            secret=self.proposed.madar_secret, key=self.proposed.madar_key_id,
        )
        # Existing registry checks only its own empty queries table; this is
        # synthetic evidence of the missing cross-epoch guarantee, not a fix.
        result = json.loads(candidate.query_receipt(
            new_signed_wire, now=NOW, verified_transport_peer=True))
        self.assertEqual(result["payload"]["lookupStatus"], "unknown")
        self.assertEqual(candidate.query_capacity_status()["used"], 1)
        with self.assertRaisesRegex(EpochRolloverBlocked, "cross-epoch replay"):
            activate_epoch(candidate)

    def test_wrong_or_forged_host_approval_denied_before_archive(self):
        for approval in (None, True, b"", b"\x00" * 32, b"n" * 32):
            with self.subTest(approval=repr(approval)):
                with self.assertRaises(EpochRolloverBlocked):
                    self.prepare(approval_mac=approval)
                self.assertFalse(self.archive.exists())
                self.assertFalse(self.receipt.exists())
        clone_config = PeerConfig(
            "office-one", "madar-host-1", "madar-key",
            "taraz-peer-1", "taraz-key", b"m" * 32, b"t" * 32,
        )
        with self.assertRaises(EpochRolloverBlocked):
            self.prepare(host_config=clone_config)
        self.assertFalse(self.archive.exists())

    def test_rotated_keys_identity_and_intent_binding_fail_closed(self):
        altered = (
            PeerConfig("other", "madar-host-1", "madar-next",
                       "taraz-peer-1", "taraz-next", b"n"*32, b"u"*32),
            PeerConfig("office-one", "madar-host-1", "madar-key",
                       "taraz-peer-1", "taraz-next", b"n"*32, b"u"*32),
            PeerConfig("office-one", "madar-host-1", "madar-next",
                       "taraz-peer-1", "taraz-next", b"m"*32, b"u"*32),
        )
        for proposed in altered:
            with self.subTest(proposed=proposed.madar_key_id):
                with self.assertRaises(EpochRolloverBlocked):
                    self.prepare(proposed_config=proposed)
        self.assertFalse(self.archive.exists())
        with self.assertRaises(EpochRolloverBlocked):
            self.prepare(approval_mac=self.approval(
                receipt=self.root / "different-receipt.json"))
        self.assertFalse(self.archive.exists())

    def test_create_only_no_overwrite_and_unsafe_targets_blocked(self):
        self.intake_query()
        self.archive.write_bytes(b"unrelated existing evidence")
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(self.archive.read_bytes(), b"unrelated existing evidence")
        self.archive.unlink()
        self.receipt.write_text("existing evidence", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertFalse(self.archive.exists())
        self.receipt.unlink()
        for destination in (
            Path("relative.sqlite3"), self.original_path,
            self.root / "not-there" / "archive.sqlite3",
        ):
            with self.subTest(destination=destination):
                # Signed approval is for exactly the requested destination,
                # not merely for an arbitrary archive name.
                with self.assertRaises((EpochEvidenceInvalid, FileExistsError)):
                    self.prepare(
                        archive_path=destination,
                        approval_mac=self.approval(archive=destination),
                    )
                self.assertFalse(self.receipt.exists())

    def test_archive_corrupt_readback_or_missing_binding_refuses_receipt(self):
        self.intake_query()
        real_archive = self.registry.archive_to

        def corrupted_return(destination):
            result = real_archive(destination)
            return {**result, "archiveSha256": "0" * 64}

        with patch.object(self.registry, "archive_to", side_effect=corrupted_return):
            with self.assertRaisesRegex(EpochEvidenceInvalid, "SHA-256 mismatch"):
                self.prepare()
        self.assertTrue(self.archive.is_file())  # Preserve evidence for review.
        self.assertFalse(self.receipt.exists())

    def test_source_query_changes_during_archive_blocks_stage_without_activation(self):
        self.intake_query()
        real_archive = self.registry.archive_to

        def race_after_snapshot(destination):
            result = real_archive(destination)
            with closing(sqlite3.connect(self.original_path)) as db:
                db.execute(
                    "INSERT INTO queries(query_id,org,original_id,original_sha,"
                    "query_sha,actor_role) VALUES(?,?,?,?,?,?)",
                    ("d" * 32, "office-one", "f" * 32,
                     "e" * 64, "d" * 64, "editor"),
                )
                db.commit()
            return result

        with patch.object(self.registry, "archive_to", side_effect=race_after_snapshot):
            with self.assertRaisesRegex(EpochRolloverBlocked, "source replay set changed"):
                self.prepare()
        self.assertTrue(self.archive.exists())
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.registry.query_capacity_status()["used"], 2)

    def test_malformed_historical_query_binding_rejected_before_receipt(self):
        self.intake_query()
        with closing(sqlite3.connect(self.original_path)) as db:
            db.execute(
                "INSERT INTO queries(query_id,org,original_id,original_sha,"
                "query_sha,actor_role) VALUES(?,?,?,?,?,?)",
                ("d" * 32, "other-tenant", "f" * 32,
                 "e" * 64, "d" * 64, "editor"),
            )
            db.commit()
        with self.assertRaisesRegex(EpochEvidenceInvalid, "historical query binding"):
            self.prepare()
        self.assertTrue(self.archive.exists())
        self.assertFalse(self.receipt.exists())

    def test_receipt_readback_mismatch_fails_closed(self):
        self.intake_query()
        real_read = Path.read_bytes

        def synthetic_mismatch(path):
            if path == self.receipt:
                return b"corrupt receipt"
            return real_read(path)

        with patch.object(Path, "read_bytes", autospec=True,
                          side_effect=synthetic_mismatch):
            with self.assertRaisesRegex(EpochEvidenceInvalid, "receipt readback"):
                self.prepare()
        self.assertTrue(self.archive.exists())
        self.assertTrue(self.receipt.exists())
        self.assertEqual(self.registry.query_capacity_status()["used"], 1)

    def test_receipt_postpublish_error_never_changes_active_source(self):
        self.intake_query()
        def failed_after_receipt_fsync(path, payload):
            _publish_create_only_json(path, payload)
            raise OSError("synthetic error after receipt fsync")

        with patch("taraz_mtr_epoch_rollover._publish_create_only_json",
                   side_effect=failed_after_receipt_fsync):
            with self.assertRaisesRegex(OSError, "after receipt fsync"):
                self.prepare()
        self.assertTrue(self.archive.exists())
        self.assertTrue(self.receipt.exists())  # Not trusted until readback/custody.
        self.assertEqual(self.registry.query_capacity_status()["used"], 1)
        with self.assertRaises(EpochRolloverBlocked):
            activate_epoch()

    def test_no_implicit_transition_even_without_a_full_registry(self):
        self.assertEqual(self.registry.query_capacity_status()["used"], 0)
        result = self.prepare()
        self.assertEqual(result["historicalQueryCount"], 0)
        self.assertFalse(result["activationAuthorized"])
        with self.assertRaises(EpochRolloverBlocked):
            activate_epoch()
        self.assertEqual(self.registry.query_capacity_status()["used"], 0)


if __name__ == "__main__":
    unittest.main()
