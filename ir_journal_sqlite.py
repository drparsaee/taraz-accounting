"""Isolated opt-in SQLite persistence for the RIAL V2 journal.

Never opens legacy Madar state or parses TOMAN data. Host supplies a dedicated
DB path and authenticates actor/project/chart inputs before calling mutate().
"""
from __future__ import annotations

from dataclasses import asdict
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from ir_chart_model import (
    ChartSnapshot, ChartAccount, FloatingDetail, DetailBinding, PartyDetailLink,
    CostCenter, JobReference, LegacyAccountLink, PostingReference,
)
from ir_journal_v2 import (
    JournalState, FiscalPeriod, VerifiedScopes, ChartEvidence, JournalSource,
    JournalLine, PostedJournal, ClosedPeriod, replay_journal, JournalV2Conflict,
    new_journal_state,
)
from money_policy import snapshot_sha256


_CHART_FIELDS = {
    "accounts": ChartAccount, "details": FloatingDetail,
    "bindings": DetailBinding, "party_links": PartyDetailLink,
    "cost_centers": CostCenter, "jobs": JobReference,
    "legacy_links": LegacyAccountLink,
}


def _serialize(state: JournalState) -> bytes:
    replay_journal(state)
    _unique_business_sources(state)
    payload = {
        "company_id": state.company_id, "currency": state.currency,
        "periods": [asdict(p) for p in state.periods],
        "evidence": [
            {"company_id": e.company_id, "evidence_digest": e.evidence_digest,
             "max_abs_rial": e.max_abs_rial, "chart": asdict(e.chart),
             "scopes": {
                 name: sorted([list(x) if type(x) is tuple else x for x in getattr(e.scopes, name)])
                 for name in ("party_ids", "project_ids", "task_scopes",
                              "checklist_scopes", "independent_source_scopes")
             }} for e in state.evidence
        ],
        "events": [{"event_type": "post" if type(ev) is PostedJournal else "close",
                    "body": asdict(ev)} for ev in state.events],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _unique_business_sources(state: JournalState) -> None:
    """Deny same business source posted again under a different event ID.

    Reversal is explicitly exempt and leaves original source reserved until
    a future version introduces reviewed replacement/supersession policy.
    """
    seen = set()
    for event in state.events:
        if type(event) is not PostedJournal or event.reversal_of:
            continue
        key = (event.company_id, event.source.kind,
               event.source.project_id, event.source.source_id)
        if key in seen:
            raise JournalV2Conflict("Business source already posted under another event")
        seen.add(key)


def _validate_append_only(previous: JournalState, candidate: JournalState) -> None:
    """SQL boundary disallows deleting/editing/reordering committed RIAL history."""
    if previous.company_id != candidate.company_id or (
            previous.currency != candidate.currency or
            previous.periods != candidate.periods):
        raise ValueError("Company/currency/fiscal calendar cannot be rewritten")
    if candidate.events[:len(previous.events)] != previous.events:
        raise ValueError("Posted journal history is append-only")
    if candidate.evidence[:len(previous.evidence)] != previous.evidence:
        raise ValueError("Historical chart/permission evidence is immutable")
    _unique_business_sources(candidate)


def _deserialize(data: bytes) -> JournalState:
    def required(data, keys):
        if type(data) is not dict or set(data) != set(keys):
            raise ValueError("Invalid RIAL V2 snapshot schema")
        return data

    payload = json.loads(data.decode("utf-8"), parse_float=lambda _: (_ for _ in ()).throw(
        ValueError("Floating point money values forbidden")))
    required(payload, ("company_id", "currency", "periods", "evidence", "events"))
    periods = tuple(FiscalPeriod(**p) for p in payload["periods"])
    original = new_journal_state(payload["company_id"], periods)
    evidence = []
    for raw in payload["evidence"]:
        c = raw["chart"]
        chart = ChartSnapshot(
            company_id=c["company_id"],
            project_ids=tuple(c["project_ids"]),
            **{name: tuple(typ(**row) for row in c[name])
               for name, typ in _CHART_FIELDS.items()},
        )
        s = raw["scopes"]
        scopes = VerifiedScopes(
            party_ids=frozenset(s["party_ids"]),
            project_ids=frozenset(s["project_ids"]),
            task_scopes=frozenset(tuple(x) for x in s["task_scopes"]),
            checklist_scopes=frozenset(tuple(x) for x in s["checklist_scopes"]),
            independent_source_scopes=frozenset(
                tuple(x) for x in s["independent_source_scopes"]),
        )
        evidence.append(ChartEvidence(raw["company_id"], chart, scopes,
                                      raw["max_abs_rial"], raw["evidence_digest"]))
    events = []
    for raw in payload["events"]:
        body = raw["body"]
        if raw["event_type"] == "close":
            events.append(ClosedPeriod(**body))
        elif raw["event_type"] == "post":
            lines = tuple(JournalLine(PostingReference(**line["reference"]),
                                      line["debit_rial"], line["credit_rial"])
                          for line in body["lines"])
            events.append(PostedJournal(**{
                **body, "source": JournalSource(**body["source"]),
                "lines": lines,
            }))
        else:
            raise ValueError("Unknown RIAL event type")
    result = JournalState(original.company_id, payload["currency"], periods,
                          tuple(evidence), tuple(events))
    replay_journal(result)
    _unique_business_sources(result)
    return result


class RIALJournalStorage:
    """One dedicated SQLite database; BEGIN IMMEDIATE plus revision CAS."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.parent.is_dir():
            raise ValueError("Dedicated RIAL journal directory must already exist")
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS rial_journal_v2 ("
                       "company_id TEXT PRIMARY KEY, revision TEXT NOT NULL,"
                       "payload BLOB NOT NULL, digest TEXT NOT NULL)")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            yield db
        finally:
            db.close()

    def read(self, company_id: str) -> JournalState | None:
        with self._db() as db:
            row = db.execute("SELECT revision,payload,digest FROM rial_journal_v2 "
                             "WHERE company_id=?", (company_id,)).fetchone()
        if row is None:
            return None
        revision, payload, digest = row
        if snapshot_sha256(json.loads(payload)) != digest:
            raise ValueError("RIAL persistent snapshot digest changed")
        state = _deserialize(payload)
        if state.company_id != company_id or state.revision != revision:
            raise ValueError("RIAL persistent snapshot revision/company mismatch")
        return state

    def commit(self, candidate: JournalState, *, expected_revision: str | None) -> str:
        payload = _serialize(candidate)
        digest = snapshot_sha256(json.loads(payload))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                previous = db.execute(
                    "SELECT revision,payload,digest FROM rial_journal_v2 WHERE company_id=?",
                    (candidate.company_id,)).fetchone()
                actual = previous[0] if previous else None
                if actual != expected_revision:
                    raise JournalV2Conflict("RIAL SQLite CAS conflict")
                if previous:
                    if snapshot_sha256(json.loads(previous[1])) != previous[2]:
                        raise ValueError("Previously persisted RIAL data was altered")
                    before = _deserialize(previous[1])
                    if before.revision != actual:
                        raise ValueError("Previously persisted revision changed")
                    _validate_append_only(before, candidate)
                db.execute(
                    "INSERT INTO rial_journal_v2(company_id,revision,payload,digest) "
                    "VALUES(?,?,?,?) ON CONFLICT(company_id) DO UPDATE SET "
                    "revision=excluded.revision,payload=excluded.payload,digest=excluded.digest",
                    (candidate.company_id, candidate.revision, payload, digest))
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        return candidate.revision

    def mutate(self, company_id: str, expected_revision: str,
               operation) -> JournalState:
        """Authenticated host passes an operation; lock persists across read/write."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT revision,payload,digest FROM rial_journal_v2 "
                    "WHERE company_id=?", (company_id,)).fetchone()
                if row is None:
                    raise ValueError("Uninitialized company journal")
                revision, payload, digest = row
                if revision != expected_revision:
                    raise JournalV2Conflict("RIAL concurrent update")
                if snapshot_sha256(json.loads(payload)) != digest:
                    raise ValueError("Corrupt journal snapshot")
                current = _deserialize(payload)
                if current.revision != revision or current.company_id != company_id:
                    raise ValueError("Mismatched company journal revision")
                next_state = operation(current)
                if type(next_state) is not JournalState or next_state.company_id != company_id:
                    raise ValueError("Operation must return matching company JournalState")
                _validate_append_only(current, next_state)
                next_payload = _serialize(next_state)
                db.execute(
                    "UPDATE rial_journal_v2 SET revision=?,payload=?,digest=? "
                    "WHERE company_id=? AND revision=?",
                    (next_state.revision, next_payload,
                     snapshot_sha256(json.loads(next_payload)),
                     company_id, revision))
                if db.execute("SELECT changes()").fetchone()[0] != 1:
                    raise JournalV2Conflict("Lost SQL CAS")
                db.execute("COMMIT")
                return next_state
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
