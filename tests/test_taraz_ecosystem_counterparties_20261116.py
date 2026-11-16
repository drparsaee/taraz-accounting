"""Counterparties v1: disposable registered books only, no live data or LAN."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from accounting_core import apply_accounting_command, empty_rial_accounting_state
from standalone_accounting import _canonical
from taraz_ecosystem_counterparties import (
    CounterpartiesCursorError, CounterpartiesUnavailable,
    TarazCounterpartiesDirectory,
)


COMPANY_A = "a" * 32
COMPANY_B = "b" * 32
HISTORIC = "ps.parsian.1405.party.12.2.19"
SECRET = "SECRET-PRIVATE-CREDIT-AND-HISTORY"
ACTOR = "qa-admin"
ACCOUNTS = {ACTOR: {"username": ACTOR, "role": "admin",
                    "financeView": True, "financeEdit": True}}
WHEN = "2026-11-16T11:20:00+00:00"


def registered_book(hub: Path, company: str) -> Path:
    path = hub / "books" / company
    path.mkdir(parents=True, exist_ok=True)
    registry = hub / "companies.json"
    if registry.is_file():
        source = json.loads(registry.read_text(encoding="utf-8"))
    else:
        source = {"version": 1, "companies": []}
    source["companies"].append({"id": company, "name": "QA synthetic " + company[:1],
                                "createdAt": WHEN})
    registry.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    return path


def make_state(parties):
    state = empty_rial_accounting_state()
    for index, (party_id, name, kind) in enumerate(parties):
        state = apply_accounting_command(
            state, {"type": "party.register", "eventId": "QA-EVENT-" + str(index),
                    "partyId": party_id, "name": name, "kind": kind,
                    "creditLimit": 25000},
            actor=ACTOR, accounts=ACCOUNTS, now=WHEN)["state"]
    if parties:
        first = parties[0]
        state = apply_accounting_command(
            state, {"type": "party.update", "eventId": "QA-SECRET-UPDATE",
                    "partyId": first[0], "name": first[1] + " به‌روز",
                    "reason": SECRET},
            actor=ACTOR, accounts=ACCOUNTS, now=WHEN)["state"]
    return state


def seed_db(book: Path, state, *, schema_version=1, digest_override=None):
    file = book / "standalone-accounting.sqlite3"
    raw = _canonical(state) if state is not None else None
    with closing(sqlite3.connect(file)) as db:
        with db:
            db.execute("""CREATE TABLE standalone_accounting(
                id INTEGER PRIMARY KEY CHECK(id=1),
                revision INTEGER NOT NULL CHECK(revision>=1),
                state BLOB NOT NULL, digest TEXT NOT NULL)""")
            db.execute(f"PRAGMA user_version={schema_version}")
            if raw is not None:
                db.execute("INSERT INTO standalone_accounting VALUES(1,?,?,?)",
                           (len(state["events"]), raw,
                            digest_override if digest_override is not None
                            else sha256(raw).hexdigest()))
    return file


def file_evidence(path: Path):
    return {str(file.relative_to(path)): sha256(file.read_bytes()).hexdigest()
            for file in path.rglob("*") if file.is_file()}


class CounterpartiesDirectoryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="taraz-counterparties-synthetic-")
        self.addCleanup(temporary.cleanup)
        self.hub = Path(temporary.name) / "hub"
        self.hub.mkdir()
        self.a = registered_book(self.hub, COMPANY_A)
        self.b = registered_book(self.hub, COMPANY_B)
        self.ledger = seed_db(self.a, make_state([
            ("TARAZ-A01", "مشتري شركت آریا", "customer"),
            ("TARAZ-A02", "تامین‌کننده تهران", "vendor"),
            ("TARAZ-A03", "همکار مشترک", "both"),
            (HISTORIC, "طرف حساب تاریخی محرمانه", "customer"),
        ]))
        seed_db(self.b, make_state([("TARAZ-B01", "شرکت دوم", "customer")]))
        self.calls = []

        def authorize(*, company_id, operation, party_id):
            self.calls.append((company_id, operation, party_id))
            return company_id == COMPANY_A

        self.authorize = authorize
        self.directory = TarazCounterpartiesDirectory(
            self.a, company_id=COMPANY_A, authorizer=authorize)

    def test_verified_rial_schema_and_projection_are_minimal_and_persian(self):
        prior = file_evidence(self.hub)
        result = self.directory.search("مشتری شرکت آریا")
        self.assertEqual((result["schemaVersion"], result["companyId"],
                          result["source"], result["revision"]),
                         (1, COMPANY_A, "TARAZ", 5))
        self.assertEqual(result["counterparties"], [{
            "partyId": "TARAZ-A01", "name": "مشتري شركت آریا به‌روز",
            "kind": "customer"}])
        self.assertFalse(result["hasMore"])
        self.assertIsNone(result["nextCursor"])
        self.assertEqual(file_evidence(self.hub), prior)
        self.assertTrue(self.calls)
        self.assertTrue(all(call[0] == COMPANY_A for call in self.calls))
        self.assertIn((COMPANY_A, "search", "TARAZ-A01"), self.calls)

    def test_get_is_scoped_and_does_not_export_money_phone_history_or_legacy(self):
        found = self.directory.get("TARAZ-A01")
        self.assertEqual(set(found), {"schemaVersion", "source", "companyId",
                                     "revision", "counterparty"})
        self.assertEqual(set(found["counterparty"]), {"partyId", "name", "kind"})
        self.assertNotIn(SECRET, json.dumps(found, ensure_ascii=False))
        self.assertNotIn("25000", json.dumps(found))
        self.assertIsNone(self.directory.get("MISSING-PARTY"))
        self.assertIsNone(self.directory.get(HISTORIC))
        self.assertEqual(self.directory.search("تاریخی")["counterparties"], [])
        self.assertNotIn("displayCode", found["counterparty"])

    def test_kind_filters_keep_dual_role_visible_with_exact_both_option(self):
        ids = lambda kind: {p["partyId"] for p in self.directory.search(
            kind=kind)["counterparties"]}
        self.assertEqual(ids("customer"), {"TARAZ-A01", "TARAZ-A03"})
        self.assertEqual(ids("vendor"), {"TARAZ-A02", "TARAZ-A03"})
        self.assertEqual(ids("both"), {"TARAZ-A03"})
        self.assertEqual(ids("all"), {"TARAZ-A01", "TARAZ-A02", "TARAZ-A03"})

    def test_pagination_is_deterministic_and_stale_cursor_fails_closed(self):
        items = [(f"TARAZ-A{i:03d}", f"همکار {i:03d}", "customer")
                 for i in range(57)]
        seed_book = self.hub / "books" / COMPANY_A
        self.ledger.unlink()  # Only this disposable fixture is changed.
        seed_db(seed_book, make_state(items))
        prior = file_evidence(self.hub)
        first = self.directory.search("همکار", limit=50)
        self.assertTrue(first["hasMore"])
        self.assertEqual(len(first["counterparties"]), 50)
        second = self.directory.search("همکار", limit=50,
                                       cursor=first["nextCursor"])
        self.assertEqual(len(second["counterparties"]), 7)
        self.assertFalse(second["hasMore"])
        self.assertIsNone(second["nextCursor"])
        self.assertEqual(len({item["partyId"] for item in
                              first["counterparties"]+second["counterparties"]}), 57)
        self.assertEqual(file_evidence(self.hub), prior)
        for args in ({"query": "wrong", "cursor": first["nextCursor"]},
                     {"query": "همکار", "kind": "vendor",
                      "cursor": first["nextCursor"]},
                     {"query": "همکار", "cursor": "ZmFrZQ"},
                     {"query": "همکار", "cursor": first["nextCursor"] + "*"}):
            with self.subTest(args=args), self.assertRaises(
                    CounterpartiesCursorError):
                self.directory.search(**args)
        # Revision and source digest both bind a page to the old snapshot.
        self.ledger.unlink()
        seed_db(seed_book, make_state(items[:52]))
        with self.assertRaises(CounterpartiesCursorError):
            self.directory.search("همکار", cursor=first["nextCursor"])

    def test_authentication_and_row_acl_are_live_and_fail_closed(self):
        def scoped(*, company_id, operation, party_id):
            return company_id == COMPANY_A and party_id != "TARAZ-A02"
        directory = TarazCounterpartiesDirectory(
            self.a, company_id=COMPANY_A, authorizer=scoped)
        self.assertNotIn("TARAZ-A02", [p["partyId"] for p in
                                      directory.search()["counterparties"]])
        self.assertIsNone(directory.get("TARAZ-A02"))
        self.assertIsNone(directory.get("DOES-NOT-EXIST"))
        denied = TarazCounterpartiesDirectory(
            self.a, company_id=COMPANY_A,
            authorizer=lambda **_: False)
        with self.assertRaisesRegex(PermissionError, "access denied"):
            denied.search()
        with self.assertRaises(PermissionError):
            denied.get("TARAZ-A01")
        with self.assertRaises(PermissionError):
            TarazCounterpartiesDirectory(
                self.b, company_id=COMPANY_B,
                authorizer=self.authorize).search()
        with self.assertRaises(CounterpartiesUnavailable):
            TarazCounterpartiesDirectory(
                self.b, company_id=COMPANY_A,
                authorizer=self.authorize).search()
        revoked = {"enabled": True}

        def dynamic(**_):
            return revoked["enabled"]
        current = TarazCounterpartiesDirectory(
            self.a, company_id=COMPANY_A, authorizer=dynamic)
        self.assertIsNotNone(current.get("TARAZ-A01"))
        revoked["enabled"] = False
        with self.assertRaises(PermissionError):
            current.search()

    def test_row_authorization_errors_fail_entire_call_instead_of_hiding_failures(self):
        def broken(*, company_id, operation, party_id):
            if party_id == "TARAZ-A02":
                raise RuntimeError("SECRET-PRIVATE-PROVIDER-FAILURE")
            return True
        reader = TarazCounterpartiesDirectory(
            self.a, company_id=COMPANY_A, authorizer=broken)
        with self.assertRaises(PermissionError) as search_error:
            reader.search()
        with self.assertRaises(PermissionError) as get_error:
            reader.get("TARAZ-A02")
        for caught in (search_error, get_error):
            self.assertEqual(str(caught.exception), "Counterparties access denied")
            self.assertNotIn("SECRET", str(caught.exception))

    def test_midread_acl_revocation_does_not_return_stale_authorized_party(self):
        state = {"row": True}

        def authorize(*, company_id, operation, party_id):
            return party_id is None or state["row"]
        reader = TarazCounterpartiesDirectory(
            self.a, company_id=COMPANY_A, authorizer=authorize)
        original = reader._snapshot

        def revoke_during_read():
            snapshot = original()
            state["row"] = False
            return snapshot
        with patch.object(reader, "_snapshot", side_effect=revoke_during_read):
            self.assertIsNone(reader.get("TARAZ-A01"))
        checks = {"row": 0}

        def revoke_after_match(*, company_id, operation, party_id):
            if party_id == "TARAZ-A01":
                checks["row"] += 1
                return checks["row"] == 1
            return True
        searched = TarazCounterpartiesDirectory(
            self.a, company_id=COMPANY_A, authorizer=revoke_after_match)
        # First row check passes, final authorization before return fails.
        with self.assertRaises(PermissionError):
            searched.search(query="آریا")

    def test_bad_authorization_predicate_never_opens_ledger(self):
        for invalid in (None, True, {"financeView": True}, "admin"):
            with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                TarazCounterpartiesDirectory(
                    self.a, company_id=COMPANY_A, authorizer=invalid)
        with patch("taraz_ecosystem_counterparties.sqlite3.connect",
                   side_effect=AssertionError("ledger must not be opened")):
            with self.assertRaises(PermissionError):
                TarazCounterpartiesDirectory(
                    self.a, company_id=COMPANY_A,
                    authorizer=lambda **_: 1).search()

    def test_input_validation_and_disjoint_registered_companies(self):
        invalid = [None, True, 5, "x" * 121, "bad\x00query", "\ud800"]
        for query in invalid:
            with self.subTest(query=repr(query)), self.assertRaises(ValueError):
                self.directory.search(query=query)
        for kind in (None, True, "CUSTOMER", "credit"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.directory.search(kind=kind)
        for limit in (0, 51, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.directory.search(limit=limit)
        for pid in (None, True, "bad/../../ledger", "", "x" * 97):
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                self.directory.get(pid)
        with self.assertRaises(ValueError):
            TarazCounterpartiesDirectory(
                self.a, company_id="bad", authorizer=self.authorize)
        with self.assertRaises(CounterpartiesUnavailable):
            TarazCounterpartiesDirectory(
                "relative/books/" + COMPANY_A, company_id=COMPANY_A,
                authorizer=self.authorize)

    def test_missing_malformed_tampered_schema_and_no_creation(self):
        ledger = self.ledger
        ledger.unlink()
        before = file_evidence(self.hub)
        with self.assertRaises(CounterpartiesUnavailable):
            self.directory.search()
        self.assertEqual(file_evidence(self.hub), before)
        ledger.write_bytes(b"NOT AN SQLITE DB; SECRET-PAYLOAD")
        with self.assertRaises(CounterpartiesUnavailable) as failure:
            self.directory.search()
        self.assertNotIn("SECRET-PAYLOAD", str(failure.exception))
        ledger.unlink()
        seed_db(self.a, make_state([("TARAZ-X", "مشتری آزمایشی", "customer")]),
                digest_override="0" * 64)
        with self.assertRaises(CounterpartiesUnavailable):
            self.directory.get("TARAZ-X")
        ledger.unlink()
        seed_db(self.a, make_state([("TARAZ-X", "مشتری آزمایشی", "customer")]),
                schema_version=7)
        with self.assertRaises(CounterpartiesUnavailable):
            self.directory.search()
        with closing(sqlite3.connect(ledger)) as conn:
            with conn:
                conn.execute("PRAGMA user_version=1")
                conn.execute("CREATE TABLE leaked_financial_records(secret TEXT)")
        with self.assertRaises(CounterpartiesUnavailable):
            self.directory.search()
        ledger.unlink()
        with closing(sqlite3.connect(ledger)) as conn:
            with conn:
                conn.execute("CREATE TABLE standalone_accounting(id INTEGER)")
                conn.execute("PRAGMA user_version=1")
        with self.assertRaises(CounterpartiesUnavailable):
            self.directory.search()

    def test_real_empty_v1_book_is_not_mistaken_for_a_missing_book(self):
        self.ledger.unlink()
        seed_db(self.a, None)
        before = file_evidence(self.hub)
        result = self.directory.search()
        self.assertEqual(result["revision"], 0)
        self.assertEqual(result["counterparties"], [])
        self.assertFalse(result["hasMore"])
        self.assertIsNone(self.directory.get("TARAZ-A01"))
        self.assertEqual(file_evidence(self.hub), before)

    def test_wal_book_reads_visible_committed_data_without_ledger_writes(self):
        # The real Taraz writer uses WAL. Keep a synthetic writer connection
        # open so the WAL/shm companions exist while our reader runs.
        with closing(sqlite3.connect(self.ledger)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("UPDATE standalone_accounting SET revision=revision")
            writer.commit()
            self.assertTrue(Path(str(self.ledger)+"-wal").exists())
            before = file_evidence(self.hub)
            result = self.directory.get("TARAZ-A03")
            self.assertEqual(result["counterparty"]["kind"], "both")
            self.assertEqual(file_evidence(self.hub), before)

    def test_read_only_uri_and_zero_write_on_existing_book(self):
        prior = file_evidence(self.hub)
        original_connect = sqlite3.connect
        opens = []

        def guard(target, **kwargs):
            self.assertTrue(str(target).endswith("?mode=ro"))
            self.assertIs(kwargs.get("uri"), True)
            self.assertIsNone(kwargs.get("isolation_level"))
            opens.append(str(target))
            return original_connect(target, **kwargs)
        with patch("taraz_ecosystem_counterparties.sqlite3.connect",
                   side_effect=guard):
            with patch("standalone_accounting.StandaloneAccountingStore.__init__",
                       side_effect=AssertionError("Store constructor forbidden")):
                self.assertEqual(self.directory.get("TARAZ-A01")["revision"], 5)
                self.assertEqual(len(self.directory.search()["counterparties"]), 3)
        self.assertEqual(len(opens), 2)
        self.assertEqual(file_evidence(self.hub), prior)


if __name__ == "__main__":
    unittest.main()
