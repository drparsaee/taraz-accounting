"""Independent, local SQLite persistence for Madar's legacy TOMAN accounting core.

No task-manager, unified-finance, LAN, GUI or APPDATA dependency. The host
authenticates the actor, supplies accounts and now; this storage never trusts
identities or proof supplied inside a command. Event history is immutable;
all reads strictly replay it through accounting_core before returning a view.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from accounting_core import (
    accounting_view, apply_accounting_command, empty_accounting_state,
    empty_rial_accounting_state,
    validate_accounting_state,
)


MAX_STATE_BYTES = 15_000_000
MAX_EVENT_COUNT = 20_000
_SCHEMA_VERSION = 1


class StandaloneAccountingError(RuntimeError):
    """Standalone storage integrity or schema error."""


class AccountingRevisionConflict(StandaloneAccountingError):
    """The expected accounting revision is no longer the current revision."""


class AccountingIntegrityError(StandaloneAccountingError):
    """The stored checksum, JSON, schema or event history cannot be trusted."""


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object key: " + key)
        value[key] = item
    return value


def _reject_numeric_constant(value):
    raise ValueError("Invalid JSON numeric constant: " + value)


def _canonical(value):
    if (type(value) is not dict or type(value.get("events")) is not list
            or len(value["events"]) > MAX_EVENT_COUNT):
        raise ValueError("Standalone accounting state must have a bounded event list")
    try:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("Accounting state must be strict canonical JSON") from exc
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("Accounting snapshot exceeds size limit")
    return raw


def _decode_checked(payload, digest):
    if (type(payload) is not bytes or len(payload) > MAX_STATE_BYTES
            or type(digest) is not str or len(digest) != 64
            or sha256(payload).hexdigest() != digest):
        raise AccountingIntegrityError("Standalone accounting checksum or size mismatch")
    try:
        state = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_numeric_constant,
        )
        if _canonical(state) != payload:
            raise ValueError("Noncanonical accounting snapshot")
        validate_accounting_state(state)
    except (TypeError, ValueError, UnicodeError, RecursionError, KeyError) as exc:
        raise AccountingIntegrityError("Corrupt accounting state or invalid event replay") from exc
    return state


def _attach_record_audit(view, state):
    """Expose immutable event attribution without changing journal snapshots.

    Document dates are commercial fields; creation, draft edits and subsequent
    transitions use the authenticated actor and trusted clock in the events.
    This projection is deliberately never written back into the event chain.
    """
    edited = {"party.update", "invoice.update", "bill.update", "proforma.update"}
    for event in state["events"]:
        command = event["command"]
        kind = command["type"]
        targets = []
        if kind in ("party.register", "party.update"):
            targets.append(("parties", command["partyId"], kind == "party.register"))
        elif kind.startswith("invoice.") and "invoiceId" in command:
            targets.append(("invoices", command["invoiceId"], kind == "invoice.create"))
        elif kind.startswith("proforma.") and "proformaId" in command:
            targets.append(("proformas", command["proformaId"], kind == "proforma.create"))
        elif kind.startswith("bill.") and "billId" in command:
            targets.append(("bills", command["billId"], kind == "bill.create"))
        elif kind == "proforma.convert":
            targets.append(("invoices", command["invoiceId"], True))
        elif kind == "contractor.bill.create":
            targets.append(("bills", command["billId"], True))
        if kind in ("invoice.correct", "bill.correct"):
            collection = "invoices" if kind.startswith("invoice.") else "bills"
            targets.append((collection, command["replacementId"], True))
        for collection, identifier, is_creation in targets:
            record = view[collection].get(identifier)
            if record is None:
                continue
            if is_creation:
                record["createdAt"] = event["at"]
                record["createdBy"] = event["actor"]
            if kind in edited:
                record["editedAt"] = event["at"]
                record["editedBy"] = event["actor"]
            record["lastChangedAt"] = event["at"]
            record["lastChangedBy"] = event["actor"]
            record["lastChangedEventId"] = event["eventId"]
    return view


class StandaloneAccountingStore:
    """One independently versioned accounting journal in a dedicated SQLite file.

    Public contract:
      read(*, actor, accounts) -> {revision, view}
      command(command, *, actor, accounts, expected_revision, now)
          -> {revision, result, view}

    First read: revision 0, empty core state, no persisted event row. Each
    successful NEW event advances the integer revision once. Exact replay of
    the same eventId + actor + payload, when permitted by CURRENT trusted
    actor/role, returns the saved result and view with no new revision.

    Both fresh commands and replays REQUIRE expected_revision == current;
    stale clients get AccountingRevisionConflict even on exact replay. Refresh
    the revision and retry the original command for idempotent recovery.
    """

    def __init__(self, db_path, *, default_currency="TOMAN"):
        if default_currency not in ("TOMAN", "RIAL"):
            raise ValueError("Unsupported accounting currency")
        self.default_currency = default_currency
        self.path = Path(db_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=5.0,
                                     isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
        finally:
            connection.close()

    def _init_schema(self):
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, _SCHEMA_VERSION):
                raise StandaloneAccountingError("Unsupported accounting SQLite schema")
            names = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'")
            }
            expected = {"standalone_accounting"}
            if version == 0 and names:
                raise StandaloneAccountingError(
                    "Existing unmanaged database cannot be implicitly migrated")
            if version == _SCHEMA_VERSION and names != expected:
                raise StandaloneAccountingError("Missing or foreign accounting tables")
            if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
                raise StandaloneAccountingError("SQLite WAL is required")
            connection.execute("BEGIN IMMEDIATE")
            try:
                if version == 0:
                    connection.execute(
                        "CREATE TABLE standalone_accounting ("
                        "id INTEGER PRIMARY KEY CHECK(id=1), "
                        "revision INTEGER NOT NULL CHECK(revision>=1), "
                        "state BLOB NOT NULL, digest TEXT NOT NULL)")
                    connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def _current(self, connection):
        rows = connection.execute(
            "SELECT revision,state,digest FROM standalone_accounting").fetchall()
        if not rows:
            return 0, (empty_rial_accounting_state() if self.default_currency == "RIAL"
                       else empty_accounting_state())
        if (len(rows) != 1 or type(rows[0][0]) is not int
                or rows[0][0] < 1):
            raise AccountingIntegrityError("Invalid standalone accounting revision head")
        revision, payload, digest = rows[0]
        return revision, _decode_checked(payload, digest)

    @staticmethod
    def _ensure_expected(expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be an exact nonnegative integer")

    @staticmethod
    def _write(connection, expected_revision, revision, raw):
        """Single SQL mutation; caller owns BEGIN IMMEDIATE and rollback."""
        digest = sha256(raw).hexdigest()
        if expected_revision == 0:
            connection.execute(
                "INSERT INTO standalone_accounting(id,revision,state,digest) "
                "VALUES(1,?,?,?)", (revision, raw, digest))
            return
        updated = connection.execute(
            "UPDATE standalone_accounting SET revision=?, state=?, digest=? "
            "WHERE id=1 AND revision=?",
            (revision, raw, digest, expected_revision),
        ).rowcount
        if updated != 1:
            raise AccountingRevisionConflict("CONFLICT: stale accounting revision")

    def read(self, *, actor, accounts):
        with self._connect() as connection:
            connection.execute("BEGIN")
            try:
                revision, state = self._current(connection)
                view = _attach_record_audit(
                    accounting_view(state, actor=actor, accounts=accounts), state)
                return {"revision": revision, "view": view}
            finally:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")

    def command(self, command, *, actor, accounts, expected_revision, now):
        self._ensure_expected(expected_revision)
        if type(command) is not dict:
            raise ValueError("Accounting command must be an object")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                revision, state = self._current(connection)
                if revision != expected_revision:
                    raise AccountingRevisionConflict(
                        f"CONFLICT: expected {expected_revision}, current {revision}")
                output = apply_accounting_command(
                    state, command, actor=actor, accounts=accounts, now=now)
                updated_state = output["state"]
                # Validate the WHOLE chain and semantic posting result on
                # every accepted command, including an idempotent replay.
                validate_accounting_state(updated_state)
                view = _attach_record_audit(
                    accounting_view(updated_state, actor=actor, accounts=accounts),
                    updated_state)
                if not output["changed"]:
                    connection.execute("COMMIT")
                    return {"revision": revision, "result": output["result"],
                            "view": view}
                raw = _canonical(updated_state)
                target_revision = revision + 1
                self._write(connection, revision, target_revision, raw)
                connection.execute("COMMIT")
                return {"revision": target_revision, "result": output["result"],
                        "view": view}
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise


__all__ = [
    "StandaloneAccountingStore", "StandaloneAccountingError",
    "AccountingRevisionConflict", "AccountingIntegrityError",
    "MAX_STATE_BYTES", "MAX_EVENT_COUNT",
]
