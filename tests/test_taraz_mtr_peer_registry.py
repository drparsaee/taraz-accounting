"""Taraz v2 metadata-only peer registry with disposable synthetic SQLite data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from taraz_mtr_peer_registry import (
    PeerConfig, PeerConflict, PeerDenied, TarazPeerRegistry,
)


_DOMAIN = b"MTR-peer-envelope-v2\x00"
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)


def _raw(obj):
    return json.dumps(obj, separators=(",", ":"), sort_keys=True,
                      ensure_ascii=False).encode("utf-8")


def _wire(kind, payload, request_id, *, secret=b"m" * 32, org="office-one",
          actor="editor", key="madar-key", clock=NOW, expires=60):
    body = {
        "protocol": "mtr-peer", "version": 2, "algorithm": "HMAC-SHA256",
        "kind": kind,
        "purpose": "receipt_lookup" if kind == "query" else "finance_review_request",
        "organizationId": org, "senderId": "madar-host-1",
        "senderRole": "madar_sender", "actorRole": actor,
        "audience": "taraz_peer", "keyId": key, "requestId": request_id,
        "issuedUtc": clock.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresUtc": (clock + timedelta(seconds=expires)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "payloadSha256": hashlib.sha256(_raw(payload)).hexdigest(),
        "payload": payload,
    }
    body["mac"] = hmac.new(secret, _DOMAIN + _raw(body), hashlib.sha256).hexdigest()
    return _raw(body)


def _subject(original):
    return {"originalRequestId": original["requestId"],
            "originalPayloadSha256": original["payloadSha256"],
            "originalPurpose": "finance_review_request"}


class TarazPeerRegistryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="taraz-peer-pilot-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "metadata.sqlite3"
        self.config = PeerConfig("office-one", "madar-host-1", "madar-key",
                                 "taraz-peer-1", "taraz-key",
                                 b"m" * 32, b"t" * 32)
        self.store = TarazPeerRegistry(self.path, self.config)
        self.payload = {"schema": 1, "source": "madar", "taskId": "example-2",
                        "projectId": "p-sample", "title": "synthetic card"}
        self.request_id = "a" * 32
        self.request = _wire("request", self.payload, self.request_id)

    def intake(self, wire=None, verified=True):
        return self.store.intake(self.request if wire is None else wire,
                                 now=NOW, verified_transport_peer=verified)

    def query(self, original=None, request_id="b" * 32, verified=True):
        original = original or json.loads(self.request)
        wire = _wire("query", _subject(original), request_id)
        return self.store.query_receipt(wire, now=NOW,
                                        verified_transport_peer=verified)

    def fill_queries_to(self, count):
        """Synthetic direct fixture for capacity; no real transport or sender."""
        with closing(sqlite3.connect(self.path)) as conn:
            existing = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
            self.assertLessEqual(existing, count)
            # One real HMAC query uses "b"*32; all other IDs are fixture rows.
            ids = ((f"{i:032x}", self.config.organization_id,
                    "f" * 32, "e" * 64, "d" * 64, "editor")
                   for i in range(count - 1))
            conn.executemany(
                "INSERT OR IGNORE INTO queries"
                "(query_id,org,original_id,original_sha,query_sha,actor_role)"
                " VALUES(?,?,?,?,?,?)", ids,
            )
            conn.commit()
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0],
                count,
            )

    def test_intake_is_metadata_only_idempotent_and_restart_safe(self):
        one = self.intake()
        self.assertFalse(one["idempotent"])
        self.assertFalse(one["financialEventCreated"])
        self.assertTrue(self.intake()["idempotent"])
        reopened = TarazPeerRegistry(self.path, self.config)
        self.assertTrue(reopened.intake(self.request, now=NOW,
                                       verified_transport_peer=True)["idempotent"])
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_signed_query_receipt_distinguishes_arrival_from_unknown(self):
        unknown = json.loads(self.query())
        self.assertEqual(unknown["payload"]["lookupStatus"], "unknown")
        self.assertEqual(unknown["senderRole"], "taraz_peer")
        self.assertEqual(unknown["audience"], "madar_sender")
        mac = unknown.pop("mac")
        self.assertEqual(mac, hmac.new(b"t" * 32, _DOMAIN + _raw(unknown),
                                       hashlib.sha256).hexdigest())
        self.intake()
        received = json.loads(self.query(request_id="c" * 32))
        self.assertEqual(received["payload"]["lookupStatus"], "received")
        self.assertEqual(received["payload"]["originalRequestId"], self.request_id)
        self.assertEqual(received["payload"]["originalPayloadSha256"],
                         hashlib.sha256(_raw(self.payload)).hexdigest())

    def test_no_transport_identity_no_request_or_receipt(self):
        with self.assertRaises(PermissionError):
            self.intake(verified=False)
        with self.assertRaises(PermissionError):
            self.query(verified=False)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 0)

    def test_wrong_sender_org_key_role_and_expiry_fail_closed(self):
        candidates = [
            _wire("request", self.payload, self.request_id, org="other"),
            _wire("request", self.payload, self.request_id, key="rotated"),
            _wire("request", self.payload, self.request_id, actor="viewer"),
            _wire("request", self.payload, self.request_id, clock=NOW-timedelta(hours=1)),
            _wire("request", self.payload, self.request_id, secret=b"x" * 32),
        ]
        for wire in candidates:
            with self.subTest(wire=wire[:30]):
                with self.assertRaises(PeerDenied):
                    self.intake(wire)
        malformed = json.loads(self.request)
        malformed["actorRole"] = {"role": "admin"}
        with self.assertRaises(PeerDenied):
            self.intake(_raw(malformed))

    def test_tampered_noncanonical_duplicate_json_rejected(self):
        forged = json.loads(self.request)
        forged["payload"]["title"] = "modified without updating MAC"
        with self.assertRaises(PeerDenied):
            self.intake(_raw(forged))
        with self.assertRaises(PeerDenied):
            self.intake(self.request.replace(b'"kind":"request",',
                                             b'"kind":"query","kind":"request",'))
        with self.assertRaises(PeerDenied):
            self.intake(self.request + b" ")

    def test_conflicting_request_identity_never_replaces_original(self):
        self.intake()
        changed = _wire("request", {**self.payload, "title": "different"}, self.request_id)
        with self.assertRaises(PeerConflict):
            self.intake(changed)
        original = json.loads(self.query())
        self.assertEqual(original["payload"]["lookupStatus"], "received")
        wrong = json.loads(self.request)
        wrong["payloadSha256"] = "0" * 64
        with self.assertRaises(PeerConflict):
            self.query(wrong)

    def test_signed_query_requires_original_actor_role_without_delegation(self):
        """A valid same-tenant HMAC cannot silently change the original actor."""
        self.intake()  # Original request was signed as editor.
        subject = _subject(json.loads(self.request))
        for actor, query_id in (("admin", "c" * 32),
                                ("finance_submitter", "d" * 32)):
            with self.subTest(actor=actor):
                valid_mac_wrong_actor = _wire(
                    "query", subject, query_id, actor=actor,
                )
                with self.assertRaises(PeerConflict):
                    self.store.query_receipt(
                        valid_mac_wrong_actor, now=NOW,
                        verified_transport_peer=True,
                    )
        # Invalid queries must not consume query IDs or alter the original.
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT actor_role FROM requests").fetchone()[0],
                             "editor")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 1)

        # The originally authorized role remains permitted, including after restart.
        self.store = TarazPeerRegistry(self.path, self.config)
        correct = _wire("query", subject, "c" * 32, actor="editor")
        first = json.loads(self.store.query_receipt(
            correct, now=NOW, verified_transport_peer=True))
        again = json.loads(self.store.query_receipt(
            correct, now=NOW, verified_transport_peer=True))
        self.assertEqual(first["payload"]["lookupStatus"], "received")
        self.assertEqual(again["payload"]["lookupStatus"], "received")
        self.assertEqual(first, again)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 1)

    def test_parallel_intake_has_one_metadata_arrival_and_no_double_audit(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.intake(), range(12)))
        self.assertEqual(sum(not item["idempotent"] for item in results), 1)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 1)

    def test_audit_is_append_only_under_normal_sql_dml(self):
        self.intake()
        with closing(sqlite3.connect(self.path)) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM audit")
            conn.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE audit SET kind='forged'")
            conn.rollback()

    def test_distinct_directional_keys_required(self):
        with self.assertRaises(PeerDenied):
            PeerConfig("office-one", "madar-host-1", "madar-key",
                       "taraz-peer-1", "taraz-key", b"m" * 32, b"m" * 32)

    def test_query_request_id_conflict_and_restart_is_durable(self):
        first = json.loads(self.query())
        self.assertEqual(first["payload"]["lookupStatus"], "unknown")
        self.store = TarazPeerRegistry(self.path, self.config)
        different_subject = {
            "originalRequestId": "d" * 32,
            "originalPayloadSha256": "e" * 64,
            "originalPurpose": "finance_review_request",
        }
        altered = _wire("query", different_subject, "b" * 32)
        with self.assertRaises(PeerConflict):
            self.store.query_receipt(altered, now=NOW, verified_transport_peer=True)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0], 1)

    def test_query_capacity_bounds_warning_and_existing_replay_survives_full(self):
        self.intake()
        original = json.loads(self.request)
        subject = _subject(original)
        first_wire = _wire("query", subject, "b" * 32)
        first = json.loads(self.store.query_receipt(
            first_wire, now=NOW, verified_transport_peer=True))
        self.assertEqual(first["payload"]["lookupStatus"], "received")
        status = self.store.query_capacity_status()
        self.assertEqual((status["used"], status["limit"], status["remaining"]),
                         (1, 10000, 9999))
        self.assertFalse(status["archiveRecommended"])
        self.fill_queries_to(9000)
        self.assertTrue(self.store.query_capacity_status()["archiveRecommended"])
        self.assertTrue(self.store.query_capacity_status()["newQueryIdsAllowed"])
        self.fill_queries_to(9999)
        last_wire = _wire("query", subject, "c" * 32)
        self.assertEqual(json.loads(self.store.query_receipt(
            last_wire, now=NOW, verified_transport_peer=True)
        )["payload"]["lookupStatus"], "received")
        full = self.store.query_capacity_status()
        self.assertEqual((full["used"], full["remaining"]), (10000, 0))
        self.assertFalse(full["newQueryIdsAllowed"])
        self.assertTrue(full["existingQueryIdReplayAllowed"])
        self.assertFalse(full["automaticPruningAllowed"])
        # Existing IDs keep their saved subject/role. The registry cannot
        # silently discard one to make space for an unrelated signed query.
        reopened = TarazPeerRegistry(self.path, self.config)
        self.assertEqual(json.loads(reopened.query_receipt(
            first_wire, now=NOW, verified_transport_peer=True)), first)
        conflicting = _wire("query", {
            "originalRequestId": "e" * 32,
            "originalPayloadSha256": "e" * 64,
            "originalPurpose": "finance_review_request",
        }, "b" * 32)
        with self.assertRaises(PeerConflict):
            reopened.query_receipt(
                conflicting, now=NOW, verified_transport_peer=True)
        with self.assertRaisesRegex(PeerDenied, "capacity reached"):
            reopened.query_receipt(
                _wire("query", subject, "d" * 32),
                now=NOW, verified_transport_peer=True)
        # Intake remains exactly-once and independent of query capacity.
        self.assertTrue(reopened.intake(
            self.request, now=NOW, verified_transport_peer=True)["idempotent"])
        fresh_intake = _wire(
            "request", {"schema": 1, "source": "madar", "taskId": "t2",
                        "projectId": "p2", "title": "second"},
            "f" * 32,
        )
        self.assertFalse(reopened.intake(
            fresh_intake, now=NOW, verified_transport_peer=True)["idempotent"])
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0],
                             10000)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
                             2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 2)

    def test_create_only_verified_archive_retains_evidence_and_does_not_reset(self):
        self.intake()
        self.query()
        target = self.path.with_name("offline-evidence.sqlite3")
        result = self.store.archive_to(target)
        self.assertTrue(result["created"])
        self.assertFalse(result["liveQueryCapacityReleased"])
        self.assertEqual((result["requests"], result["queries"], result["auditEvents"]),
                         (1, 1, 1))
        self.assertTrue(target.is_file())
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        self.assertEqual(result["archiveSha256"], actual)
        with closing(sqlite3.connect(f"{target.as_uri()}?mode=ro", uri=True)) as backup:
            self.assertEqual(backup.execute("PRAGMA quick_check(1)").fetchone()[0], "ok")
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM queries").fetchone()[0], 1)
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                backup.execute("DELETE FROM queries")
        with self.assertRaises(FileExistsError):
            self.store.archive_to(target)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), actual)
        with self.assertRaises(PeerDenied):
            self.store.archive_to(Path("relative-evidence.sqlite3"))
        with self.assertRaises(PeerDenied):
            self.store.archive_to(self.path)
        with self.assertRaises(PeerDenied):
            self.store.archive_to(self.path.parent / "missing" / "offline.sqlite3")
        # Archive is evidence only: new live queries still use the same authority.
        self.query(request_id="c" * 32)
        self.assertEqual(self.store.query_capacity_status()["used"], 2)
        with closing(sqlite3.connect(f"{target.as_uri()}?mode=ro", uri=True)) as backup:
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM queries").fetchone()[0], 1)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), actual)

    def test_archive_of_full_registry_does_not_reopen_consumed_query_ids(self):
        self.intake()
        self.query()
        self.fill_queries_to(10000)
        target = self.path.with_name("full-offline-evidence.sqlite3")
        evidence = self.store.archive_to(target)
        self.assertEqual(evidence["queries"], 10000)
        self.assertFalse(evidence["liveQueryCapacityReleased"])
        self.store = TarazPeerRegistry(self.path, self.config)
        self.assertEqual(self.store.query_capacity_status()["remaining"], 0)
        self.assertEqual(json.loads(self.query())["payload"]["lookupStatus"],
                         "received")
        with self.assertRaisesRegex(PeerDenied, "capacity reached"):
            self.query(request_id="d" * 32)
        with closing(sqlite3.connect(f"{target.as_uri()}?mode=ro", uri=True)) as backup:
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM queries").fetchone()[0],
                             10000)

    def test_racing_new_query_ids_at_last_slot_never_exceed_bound(self):
        self.intake()
        self.query()
        self.fill_queries_to(9999)
        subject = _subject(json.loads(self.request))

        def attempt(index):
            wire = _wire("query", subject, f"{12000 + index:032x}")
            try:
                receipt = self.store.query_receipt(
                    wire, now=NOW, verified_transport_peer=True)
                self.assertEqual(json.loads(receipt)["payload"]["lookupStatus"],
                                 "received")
                return "accepted"
            except PeerDenied as error:
                if "capacity reached" not in str(error):
                    raise
                return "full"

        with ThreadPoolExecutor(max_workers=8) as workers:
            outcomes = list(workers.map(attempt, range(8)))
        self.assertEqual(outcomes.count("accepted"), 1)
        self.assertEqual(outcomes.count("full"), 7)
        self.assertEqual(self.store.query_capacity_status()["used"], 10000)

        # A bad HMAC cannot take advantage of exhaustion to mutate the index.
        invalid = _wire("query", subject, "e" * 32, secret=b"x" * 32)
        with self.assertRaises(PeerDenied):
            self.store.query_receipt(
                invalid, now=NOW, verified_transport_peer=True)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0],
                             10000)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0], 1)

    def test_database_path_rejects_hardlinked_metadata_file(self):
        alias = self.path.with_name("copy.sqlite3")
        import os
        os.link(self.path, alias)
        with self.assertRaises(PeerDenied):
            TarazPeerRegistry(alias, self.config)


if __name__ == "__main__":
    unittest.main()
