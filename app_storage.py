"""Opt-in unified, transactional persistence for Madar's JSON domains.

This module is intentionally disconnected from the active Windows host. The
caller supplies explicit *local* SQLite, import and backup paths. It never
consults APPDATA, instantiates native_app.Bridge, or touches live data itself.

Legacy revisions contain four domains. New opt-in revisions can additionally
contain the automation journal in that SAME checksummed bundle and SQLite
transaction. No schema-table migration or implicit journal creation is needed.
Every update and historic restore is protected by the same integer revision CAS.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3

import collab
import finance
import automation_v1
from data_model import MAX_BYTES as TASK_MAX_BYTES, normalize_plus, validate_plus


SCHEMA_VERSION = 1
DOMAINS = frozenset(("tasks", "collab", "finance", "completion_outbox"))
AUTOMATION_DOMAIN = "automation"
AUTOMATION_DOMAINS = DOMAINS | {AUTOMATION_DOMAIN}
MAX_DOMAIN_BYTES = 15_000_000
MAX_BUNDLE_BYTES = 45_000_000
MAX_AUTOMATION_BUNDLE_BYTES = 60_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")


def _protect_rial_finance_history(previous_bundle, next_bundle):
    """Reject missing/mismatched RIAL counterpart to an issued TOMAN invoice.

    Called under the SAME unified SQLite transaction as app revision CAS.
    The trusted host constructs the RIAL counterpart; storage checks the
    relationship AGAIN under the same SQLite revision-CAS transaction.
    """
    prior = previous_bundle["finance"]
    updated = next_bundle["finance"]
    if "rialJournalV2" not in prior:
        if "rialJournalV2" not in updated:
            return
        # An activation is strictly an EMPTY company ledger attachment to a
        # clean finance snapshot, never a combined import/posting/alteration.
        from ir_finance_v2_extension import load_finance_rial_journal
        from ir_journal_v2 import new_journal_state
        from copy import deepcopy
        untouched = deepcopy(updated)
        del untouched["rialJournalV2"]
        if untouched != prior:
            raise ValueError("RIAL activation must not mutate any old finance data")
        if any(prior.get(field) for field in (
                "invoices", "ledger", "contracts", "cardCosts", "receipts",
                "completionIds", "accounting", "purchaseIntakes")):
            raise ValueError("Live legacy finance requires reviewed RIAL migration")
        activated = updated["rialJournalV2"]["companies"]
        if len(activated) != 1:
            raise ValueError("Legacy finance has no multiple-company mapping")
        for company_id in activated:
            state = load_finance_rial_journal(updated, company_id)
            if state != new_journal_state(company_id, state.periods):
                raise ValueError("RIAL activation must start with no journal history")
        return
    if "rialJournalV2" not in updated:
        raise ValueError("Active RIAL V2 finance history cannot be dropped")
    from ir_finance_v2_extension import (
        load_finance_rial_journal, _preserve_issued_history,
    )
    from ir_journal_sqlite import _validate_append_only
    previous_companies = prior["rialJournalV2"]["companies"]
    new_companies = updated["rialJournalV2"]["companies"]
    if not set(previous_companies).issubset(new_companies):
        raise ValueError("Active RIAL company journal cannot be deleted")
    # Adding a second legal entity requires an authenticated registry/project
    # mapping and a separately audited multi-company migration. Neither is
    # provided by the current legacy finance snapshot/commit API. An untrusted
    # whole-bundle writer must not silently attach another company ledger.
    if set(new_companies) != set(previous_companies):
        raise ValueError("RIAL company mapping migration is not yet authorized")
    for company_id in previous_companies:
        historic = load_finance_rial_journal(prior, company_id)
        candidate = load_finance_rial_journal(updated, company_id)
        _validate_append_only(historic, candidate)
    from ir_accounting_transition_guard import inspect_accounting_transition
    appended_accounting = inspect_accounting_transition(prior, updated)
    _preserve_issued_history(prior, updated, allow_accounting_transition=True)
    # An older host can form a valid TOMAN invoice.issue without RIAL. Each
    # increment of either side must have a precisely matching counterpart.
    new_legacy = updated["ledger"][len(prior["ledger"]):]
    if any(item.get("action") in ("invoice.payment", "project.receipt", "invoice.cancel")
           for item in new_legacy):
        raise ValueError("RIAL-activated finance needs reviewed treasury/reversal bridge")
    issued = [item for item in new_legacy if item.get("action") == "invoice.issue"]
    purchase_issues = [item for item in appended_accounting
                       if item["command"]["type"] == "bill.issue"]
    event_deltas = [
        (company_id,
         load_finance_rial_journal(updated, company_id).events[
             len(load_finance_rial_journal(prior, company_id).events):])
        for company_id in previous_companies
    ]
    new_rial = [(company_id, event) for company_id, delta in event_deltas for event in delta]
    if not issued and not purchase_issues and not new_rial:
        return
    if len(new_rial) != 1:
        raise ValueError("Unpaired issue denied: exactly one verified TOMAN/RIAL joint issue is required")
    if len(purchase_issues) == 1 and not issued:
        if len(appended_accounting) != 1 or new_legacy or (
                prior.get("accountingSources") != updated.get("accountingSources") or
                prior.get("purchaseIntakes") != updated.get("purchaseIntakes")):
            raise ValueError("Supplier issuance cannot mix source edits or other transactions")
        from copy import deepcopy
        from ir_purchase_joint_issue import compose_purchase_issue_with_rial
        from money_policy import snapshot_sha256
        document_event = purchase_issues[0]
        command = document_event["command"]
        bill_id = command["billId"]
        sources = prior.get("accountingSources") or {}
        link = sources.get(bill_id)
        if type(link) is not dict:
            raise ValueError("Purchase bill has no immutable task accounting source")
        company_id, _ = new_rial[0]
        if len(previous_companies) != 1 or set(new_companies) != set(previous_companies):
            raise ValueError("Legacy purchase company mapping is not established")
        legacy_after = deepcopy(updated)
        legacy_after["rialJournalV2"] = deepcopy(prior["rialJournalV2"])
        actor = document_event["actor"]
        # Only a consistency replay. Authentication MUST have occurred in host.
        accounts = {actor: {"username": actor,
                            "role": document_event["role"],
                            "financeEdit": document_event["financeEdit"],
                            "projects": None}}
        intent = {"type": "document.issue", "eventId": command["eventId"],
                  "documentId": bill_id, "projectId": link["projectId"],
                  "postingDate": command["postingDate"]}
        matched = compose_purchase_issue_with_rial(
            prior, legacy_after, intent, actor=actor, accounts=accounts,
            cards=next_bundle["tasks"]["tasks"],
            projects=next_bundle["tasks"]["projects"],
            now=document_event["at"], expected_finance_sha256=snapshot_sha256(prior),
            expected_journal_revision=load_finance_rial_journal(
                prior, company_id).revision)
        if matched["state"] != updated:
            raise ValueError("Supplier RIAL counterpart differs from verified issue")
        return
    if len(issued) != 1 or purchase_issues or len(new_legacy) != 1 or appended_accounting:
        raise ValueError("Only one verified TOMAN/RIAL sales issue per transaction")
    from copy import deepcopy
    from ir_finance_v2_extension import (
        VerifiedInvoiceSourceProof, compose_finance_rial_snapshot,
    )
    from money_policy import snapshot_sha256
    entry = issued[0]
    company_id, _ = new_rial[0]
    if len(previous_companies) != 1 or set(new_companies) != set(previous_companies):
        raise ValueError("Legacy finance company mapping is not established")
    invoice_id = entry["invoiceId"]
    candidates = [invoice for invoice in updated["invoices"] if invoice["id"] == invoice_id]
    if len(candidates) != 1:
        raise ValueError("Missing joint-issued legacy invoice")
    invoice = candidates[0]
    # Strip ONLY the new V2 event from the legacy reducer result. This
    # reconstruction is validated by the same pure composer used by the host.
    before_rial = load_finance_rial_journal(prior, company_id)
    after_rial = load_finance_rial_journal(updated, company_id)
    legacy_after = deepcopy(updated)
    legacy_after["rialJournalV2"] = deepcopy(prior["rialJournalV2"])
    proof = VerifiedInvoiceSourceProof(
        company_id, entry["actor"], invoice_id, entry["projectId"],
        entry["cardId"], invoice["snapshotHash"], invoice["sale"]["total"],
        snapshot_sha256(prior), snapshot_sha256(legacy_after),
    )
    expected = compose_finance_rial_snapshot(
        prior, legacy_after, after_rial,
        expected_journal_revision=before_rial.revision, proof=proof,
    )
    if expected != updated:
        raise ValueError("TOMAN/RIAL joint finance snapshot does not match verified issue")


class AppStorageError(RuntimeError):
    """Persistence-specific failure, independent of the active host."""


class RevisionConflict(AppStorageError):
    """The writer's expected revision is no longer current."""


class ImportConflict(AppStorageError):
    """A completed initial import has different source files/fingerprints."""


class AlreadyInitialized(AppStorageError):
    """An initialized database cannot be overwritten by a legacy import."""


class UnsupportedSchema(AppStorageError):
    """Unknown SQLite database, schema version, or layout."""


class IntegrityError(AppStorageError):
    """A persisted hash, snapshot shape, or referential invariant failed."""


@dataclass(frozen=True)
class UnifiedSnapshot:
    """Detached snapshot; the `bundle` dict may be edited without mutating SQL.

    `revision` is a local monotonically increasing integer (not the LAN hash).
    `sha256` fingerprints the complete serialized four- or five-domain bundle.
    """

    revision: int
    bundle: dict
    sha256: str
    created_at: str
    source: str


def _json_constant(value):
    raise ValueError("Non-JSON numeric constant: " + value)


def _decode(blob):
    try:
        return json.loads(blob.decode("utf-8"), parse_constant=_json_constant,
                          object_pairs_hook=_strict_object)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid strict UTF-8 JSON") from exc


def _strict_object(pairs):
    """Reject duplicate keys rather than silently replacing finance records."""
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _encode(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("State must contain only JSON values") from exc


def _now():
    return datetime.now(timezone.utc).isoformat()


def _check_outbox(value):
    """Validate exact persisted host completion-outbox entry shape.

    A pending card may already be deleted or reopened, so outbox records are
    schema-validated without requiring an existing/done card; the host's
    finance domain must decide whether and when an event can be replayed.
    """
    if not isinstance(value, list) or len(value) > 10000:
        raise ValueError("completion_outbox must be a list of <=10000 entries")
    events, completions = set(), set()
    fields = {"eventId", "completionId", "cardId", "projectId", "actor", "at"}
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or set(entry) != fields:
            raise ValueError(f"completion_outbox[{index}]: invalid event fields")
        for field in ("eventId", "completionId", "cardId", "projectId", "actor"):
            data = entry[field]
            if not isinstance(data, str) or not _ID.fullmatch(data):
                raise ValueError(f"completion_outbox[{index}].{field}: invalid identifier")
        for key, taken in (("eventId", events), ("completionId", completions)):
            if entry[key] in taken:
                raise ValueError(f"completion_outbox[{index}].{key}: duplicate identifier")
            taken.add(entry[key])
        when = entry["at"]
        if not isinstance(when, str) or len(when) > 64:
            raise ValueError(f"completion_outbox[{index}].at: timestamp required")
        try:
            parsed = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"completion_outbox[{index}].at: invalid timestamp") from exc
        if parsed.utcoffset() is None:
            raise ValueError(f"completion_outbox[{index}].at: timezone required")
    return True


def validated_bundle(bundle):
    """Return a JSON-deep-copied, validated four- or five-domain bundle.

    The fifth domain is explicitly opt-in, never silently synthesized.
    In either mode all other four domains are mandatory. Tasks are normalized
    before validation and the automation journal gets its own strict validator.
    The function is pure and does not access any filesystem or network.
    """
    if not isinstance(bundle, dict) or set(bundle) not in (DOMAINS, AUTOMATION_DOMAINS):
        raise ValueError("bundle must have four legacy domains, optionally plus automation")
    cloned = _decode(_encode(bundle))
    cloned["tasks"] = normalize_plus(cloned["tasks"])
    validate_plus(cloned["tasks"])
    collab.validate_state(cloned["collab"])
    finance.validate_finance_state(cloned["finance"])
    _check_outbox(cloned["completion_outbox"])
    if AUTOMATION_DOMAIN in cloned:
        automation_v1.validate_state(cloned[AUTOMATION_DOMAIN])
    for key in cloned:
        limit = TASK_MAX_BYTES if key == "tasks" else MAX_DOMAIN_BYTES
        if len(_encode(cloned[key])) > limit:
            raise ValueError(f"{key}: exceeds {limit} bytes")
    max_bytes = (MAX_AUTOMATION_BUNDLE_BYTES if AUTOMATION_DOMAIN in cloned
                 else MAX_BUNDLE_BYTES)
    if len(_encode(cloned)) > max_bytes:
        raise ValueError("Unified snapshot too large")
    return cloned


def with_automation(bundle, journal=None):
    """Explicitly activate the fifth domain on a detached legacy snapshot.

    This helper changes no database. Call `commit` with its returned bundle
    under the latest CAS revision to activate durable automation storage.
    """
    checked = validated_bundle(bundle)
    if AUTOMATION_DOMAIN in checked:
        raise ValueError("Automation journal is already present")
    checked[AUTOMATION_DOMAIN] = (automation_v1.empty_state() if journal is None
                                  else journal)
    return validated_bundle(checked)


def _backup_source(path, raw):
    """Immutable publication with fsync and atomic hard link, never replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(12) + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ImportConflict("Existing backup has mismatched bytes: " + str(path))
        if path.read_bytes() != raw:
            raise IntegrityError("Backup verification failed: " + str(path))
    finally:
        temporary.unlink(missing_ok=True)
    return path


class UnifiedAppStorage:
    """Unified append-only four-/five-domain snapshots with one CAS revision.

    Public API:
        UnifiedAppStorage(db_path, *, timeout=5.0)
        load() -> UnifiedSnapshot | None
        load_revision(revision) -> UnifiedSnapshot
        commit(bundle, *, expected_revision) -> UnifiedSnapshot
        commit_authenticated_intake(command, *, actor, accounts, now,
                                    expected_revision, expected_finance_sha256)
            -> {result, state, changed, revision} (trusted host ONLY)
        restore(revision, *, expected_revision) -> UnifiedSnapshot
        import_legacy(task_json, *, collab_json=None, finance_json=None,
                      outbox_json=None, backup_dir) -> UnifiedSnapshot
        backup_database(destination) -> pathlib.Path
        history(limit=100) -> list[int]
        integrity_check() -> bool

    All paths explicit; missing optional source files use the corresponding
    domain's validated empty default. A supplied path MUST exist. Migrations
    preserve exact original file bytes in SHA-256-named verified backups before
    any database transaction. No background synchronization is performed.
    Adding automation uses the existing revision BLOB layout and requires an
    explicit five-domain commit. Old four-domain snapshots remain unchanged.
    Active supplier intake state is deliberately never mutable through commit
    or restore: only the trusted native/LAN command path uses the reducer-backed
    authenticated intake CAS. This is not an OS or cryptographic security
    boundary against arbitrary Python execution in the host process.
    """

    def __init__(self, db_path, *, timeout=5.0):
        self.path = Path(db_path).expanduser().resolve()
        if type(timeout) not in (int, float) or not 0 < timeout <= 120:
            raise ValueError("timeout must be between 0 and 120 seconds")
        self.timeout = float(timeout)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=self.timeout, isolation_level=None)
        try:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
            yield conn
        finally:
            conn.close()

    def _schema(self):
        with self._connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise UnsupportedSchema("Unsupported app storage schema version")
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            required = {"app_revisions", "app_head", "app_imports"}
            if version == 0 and tables:
                raise UnsupportedSchema("Unversioned database has pre-existing tables")
            if version == SCHEMA_VERSION and tables != required:
                raise UnsupportedSchema("Schema tables missing or unexpected")
            if conn.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
                raise UnsupportedSchema("SQLite WAL is required on the local filesystem")
            conn.execute("BEGIN IMMEDIATE")
            try:
                if version == 0:
                    conn.execute("CREATE TABLE app_revisions (revision INTEGER PRIMARY KEY CHECK(revision>0), "
                                 "parent INTEGER NOT NULL CHECK(parent>=0), bundle BLOB NOT NULL, "
                                 "digest TEXT NOT NULL, created_at TEXT NOT NULL, source TEXT NOT NULL)")
                    conn.execute("CREATE TABLE app_head (id INTEGER PRIMARY KEY CHECK(id=1), "
                                 "revision INTEGER NOT NULL CHECK(revision>=0))")
                    conn.execute("INSERT INTO app_head(id,revision) VALUES(1,0)")
                    conn.execute("CREATE TABLE app_imports (name TEXT PRIMARY KEY, "
                                 "fingerprint TEXT NOT NULL, manifest BLOB NOT NULL, "
                                 "revision INTEGER NOT NULL CHECK(revision>0), created_at TEXT NOT NULL)")
                    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _head(conn):
        row = conn.execute("SELECT revision FROM app_head WHERE id=1").fetchone()
        if row is None or type(row[0]) is not int or row[0] < 0:
            raise IntegrityError("App head is missing or malformed")
        return row[0]

    @staticmethod
    def _read(conn, revision):
        row = conn.execute("SELECT revision,bundle,digest,created_at,source "
                           "FROM app_revisions WHERE revision=?", (revision,)).fetchone()
        if row is None:
            raise KeyError("Revision does not exist: " + str(revision))
        rev, payload, digest, created_at, source = row
        if sha256(payload).hexdigest() != digest:
            raise IntegrityError("Unified snapshot SHA-256 mismatch at revision " + str(rev))
        try:
            decoded = _decode(payload)
            checked = validated_bundle(decoded)
        except (ValueError, TypeError, KeyError) as exc:
            raise IntegrityError("Corrupt app snapshot at revision " + str(rev)) from exc
        if checked != decoded:
            raise IntegrityError("Noncanonical app snapshot at revision " + str(rev))
        return UnifiedSnapshot(rev, decoded, digest, created_at, source)

    @staticmethod
    def _expected(value):
        if type(value) is not int or value < 0:
            raise ValueError("expected_revision must be a nonnegative integer")

    @classmethod
    def _insert(cls, conn, raw, current, source):
        target = current + 1
        checksum, stamp = sha256(raw).hexdigest(), _now()
        conn.execute("INSERT INTO app_revisions(revision,parent,bundle,digest,created_at,source) "
                     "VALUES(?,?,?,?,?,?)", (target, current, raw, checksum, stamp, source))
        count = conn.execute("UPDATE app_head SET revision=? WHERE id=1 AND revision=?",
                             (target, current)).rowcount
        if count != 1:
            raise RevisionConflict("CONFLICT: concurrent app revision update")
        return UnifiedSnapshot(target, _decode(raw), checksum, stamp, source)

    def load(self):
        with self._connect() as conn:
            conn.execute("BEGIN")
            try:
                current = self._head(conn)
                return self._read(conn, current) if current else None
            finally:
                conn.execute("ROLLBACK")

    def load_revision(self, revision):
        if type(revision) is not int or revision < 1:
            raise ValueError("revision must be positive integer")
        with self._connect() as conn:
            return self._read(conn, revision)

    def commit(self, bundle, *, expected_revision):
        """CAS commit for snapshots; NEVER authorize new intake transitions.

        A complete snapshot and a plain SHA256 receipt are caller-controlled.
        Once RIAL is active, intake changes require the separate host command
        transaction, which runs the real reducer against the current SQL head.
        """
        self._expected(expected_revision)
        raw = _encode(validated_bundle(bundle))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = self._head(conn)
                if current != expected_revision:
                    raise RevisionConflict(f"CONFLICT: expected {expected_revision}, current {current}")
                if current:
                    old = self._read(conn, current)
                    # A four-domain caller from an older host must NOT be able
                    # to drop a live automation journal on its next save.
                    if (AUTOMATION_DOMAIN in old.bundle and
                            AUTOMATION_DOMAIN not in bundle):
                        raise ValueError("Five-domain storage requires automation journal on every commit")
                    if ("rialJournalV2" in old.bundle["finance"] and
                            old.bundle["finance"].get("purchaseIntakes") !=
                            bundle["finance"].get("purchaseIntakes")):
                        raise PermissionError(
                            "Intake mutation requires authenticated host command CAS")
                    _protect_rial_finance_history(old.bundle, bundle)
                    if old.sha256 == sha256(raw).hexdigest():
                        conn.execute("COMMIT")
                        return old
                result = self._insert(conn, raw, current, "commit")
                conn.execute("COMMIT")
                return result
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def commit_authenticated_intake(
        self, command, *, actor, accounts, now, expected_revision,
        expected_finance_sha256,
    ):
        """Internal host-to-storage command CAS for active RIAL supplier staging.

        This does NOT accept a candidate finance bundle, proof flag, chart,
        scope, or company ID. The authenticated native/LAN host supplies its
        resolved actor and account catalog; the storage transaction loads the
        authoritative prior finance and tasks/project membership itself, runs
        the audited reducer, checks transition invariants, and inserts exactly
        one complete bundle revision before COMMIT.

        This is an *in-process trust boundary*, not protection against Python
        code executing with the host process's own permissions.
        """
        import re
        from money_policy import snapshot_sha256
        from accounting_service import apply_madar_accounting

        if (type(command) is not dict or command.get("type") not in {
                "intake.create", "intake.price", "intake.cancel",
                "intake.convert"}):
            raise ValueError("Only supplier intake staging commands may use this CAS")
        self._expected(expected_revision)
        if (type(expected_finance_sha256) is not str or
                not re.fullmatch(r"[a-f0-9]{64}", expected_finance_sha256)):
            raise ValueError("Expected authoritative finance digest required")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = self._head(conn)
                if current != expected_revision:
                    raise RevisionConflict(
                        f"CONFLICT: expected {expected_revision}, current {current}")
                if not current:
                    raise ValueError("Intake staging requires an initialized unified SQLite")
                old = self._read(conn, current)
                if snapshot_sha256(old.bundle["finance"]) != expected_finance_sha256:
                    raise RevisionConflict("CONFLICT: authoritative finance changed")
                if "rialJournalV2" not in old.bundle["finance"]:
                    raise ValueError("Host intake CAS requires active RIAL V2 finance")
                task_state = old.bundle["tasks"]
                reduced = apply_madar_accounting(
                    old.bundle["finance"], command, actor=actor, accounts=accounts,
                    cards=task_state["tasks"], projects=task_state["projects"],
                    now=now)
                if not reduced["changed"]:
                    conn.execute("COMMIT")
                    return {"result": reduced["result"], "state": reduced["state"],
                            "changed": False, "revision": old.revision}
                candidate = {**old.bundle, "finance": reduced["state"]}
                _protect_rial_finance_history(old.bundle, candidate)
                raw = _encode(validated_bundle(candidate))
                result = self._insert(conn, raw, current, "authenticated-intake")
                conn.execute("COMMIT")
                return {"result": reduced["result"], "state": reduced["state"],
                        "changed": True, "revision": result.revision}
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def restore(self, revision, *, expected_revision):
        """Append an auditable revision, refusing fifth-domain data loss."""
        self._expected(expected_revision)
        if type(revision) is not int or revision < 1:
            raise ValueError("revision must be positive integer")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = self._head(conn)
                if current != expected_revision:
                    raise RevisionConflict(f"CONFLICT: expected {expected_revision}, current {current}")
                old = self._read(conn, revision)
                if current:
                    head = self._read(conn, current)
                    if (AUTOMATION_DOMAIN in head.bundle and
                            AUTOMATION_DOMAIN not in old.bundle):
                        raise ValueError("Cannot restore four-domain history over active automation journal")
                    if ("rialJournalV2" in head.bundle["finance"] and
                            head.bundle["finance"].get("purchaseIntakes") !=
                            old.bundle["finance"].get("purchaseIntakes")):
                        raise PermissionError(
                            "Cannot restore unauthenticated supplier intake history")
                    _protect_rial_finance_history(head.bundle, old.bundle)
                result = self._insert(conn, _encode(old.bundle), current, f"restore:{revision}")
                conn.execute("COMMIT")
                return result
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def import_legacy(self, task_json, *, backup_dir, collab_json=None,
                      finance_json=None, outbox_json=None):
        """Backup-first atomic import from up to four existing JSON files.

        Only `task_json` is mandatory. Optional None values mean that domain's
        empty default, *not* a missing file with its source silently ignored.
        Validates every source before backup creation. Publishes exact source
        bytes as immutable SHA-named files, then commits all four states and the
        fingerprint manifest in ONE SQL transaction. A retry of the same source
        bytes returns the current head, never overwriting later writes.
        """
        specified = {"tasks": task_json, "collab": collab_json,
                     "finance": finance_json, "completion_outbox": outbox_json}
        read_bytes, paths, manifest = {}, {}, {}
        for name, original in specified.items():
            if original is None:
                if name == "tasks":
                    raise ValueError("task_json is required")
                manifest[name] = None
                continue
            path = Path(original).expanduser().resolve(strict=True)
            if not path.is_file() or path == self.path:
                raise ValueError(f"{name}: expected a different existing JSON file")
            with path.open("rb") as stream:
                raw = stream.read(MAX_DOMAIN_BYTES + 1)
            if len(raw) > MAX_DOMAIN_BYTES:
                raise ValueError(f"{name}: source exceeds 15 MB")
            paths[name], read_bytes[name] = path, raw
            manifest[name] = sha256(raw).hexdigest()
        defaults = {"collab": collab.empty_state(), "finance": finance.empty_finance_state(),
                    "completion_outbox": []}
        bundle = {name: _decode(read_bytes[name]) if name in read_bytes else defaults[name]
                  for name in ("tasks", "collab", "finance", "completion_outbox")}
        raw_bundle = _encode(validated_bundle(bundle))
        manifest_fingerprint = sha256(_encode(manifest)).hexdigest()
        directory = Path(backup_dir).expanduser().resolve()
        for name, digest in manifest.items():
            if digest is None:
                continue
            backup = directory / f"{name}-{digest}.json"
            if backup == paths[name] or backup == self.path:
                raise ValueError("Backup location may not overwrite source or database")
        # Validation succeeded for ALL files. Preserve EACH source before SQL.
        for name, digest in manifest.items():
            if digest is not None:
                _backup_source(directory / f"{name}-{digest}.json", read_bytes[name])
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                previous = conn.execute("SELECT fingerprint,manifest FROM app_imports "
                                        "WHERE name='legacy-four-domain'").fetchone()
                if previous:
                    if previous[0] != manifest_fingerprint or _decode(previous[1]) != manifest:
                        raise ImportConflict("Source files differ from completed initial import")
                    current = self._head(conn)
                    if current == 0:
                        raise IntegrityError("Import metadata exists without snapshot")
                    result = self._read(conn, current)
                else:
                    if self._head(conn):
                        raise AlreadyInitialized("Cannot import over an initialized SQLite database")
                    result = self._insert(conn, raw_bundle, 0, "legacy-four-domain")
                    conn.execute("INSERT INTO app_imports(name,fingerprint,manifest,revision,created_at) "
                                 "VALUES(?,?,?,?,?)", ("legacy-four-domain", manifest_fingerprint,
                                                      _encode(manifest), result.revision, _now()))
                conn.execute("COMMIT")
                return result
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise

    def history(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as conn:
            return [row[0] for row in conn.execute(
                "SELECT revision FROM app_revisions ORDER BY revision DESC LIMIT ?", (limit,))]

    def integrity_check(self):
        """Inspect SQLite and verify every saved four-/five-domain revision."""
        with self._connect() as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise IntegrityError("SQLite integrity_check failed")
            rows = conn.execute("SELECT revision,parent FROM app_revisions ORDER BY revision").fetchall()
            for index, (revision, parent) in enumerate(rows, 1):
                if revision != index or parent != index - 1:
                    raise IntegrityError("Broken revision continuity")
                self._read(conn, revision)
            if self._head(conn) != len(rows):
                raise IntegrityError("Head diverges from latest revision")
            migrations = conn.execute("SELECT fingerprint,manifest,revision FROM app_imports").fetchall()
            for fingerprint, manifest, revision in migrations:
                try:
                    loaded = _decode(manifest)
                except ValueError as exc:
                    raise IntegrityError("Invalid import manifest") from exc
                if sha256(_encode(loaded)).hexdigest() != fingerprint or revision not in range(1, len(rows) + 1):
                    raise IntegrityError("Corrupt import manifest or revision")
        return True

    def backup_database(self, destination):
        """Online SQLite backup (WAL-aware) atomically published, never replaces."""
        destination = Path(destination).expanduser().resolve()
        if destination == self.path or destination.exists():
            raise FileExistsError("Backup target already exists or equals source")
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_name("." + destination.name + "." + secrets.token_hex(12) + ".tmp")
        try:
            with self._connect() as conn:
                target = sqlite3.connect(str(tmp))
                try:
                    conn.backup(target)
                finally:
                    target.close()
            with tmp.open("rb+") as stream:
                os.fsync(stream.fileno())
            os.link(tmp, destination)
            return destination
        finally:
            tmp.unlink(missing_ok=True)


__all__ = ["SCHEMA_VERSION", "UnifiedSnapshot", "UnifiedAppStorage", "validated_bundle",
           "DOMAINS", "AUTOMATION_DOMAINS", "with_automation",
           "RevisionConflict", "ImportConflict", "AlreadyInitialized", "UnsupportedSchema", "IntegrityError"]
