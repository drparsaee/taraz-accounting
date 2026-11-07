"""Standalone transactional SQLite snapshots for Madar Desk.

This module does not replace the active JSON host. It accepts an explicit
database path (never implicitly uses APPDATA), keeps complete validated Madar
state snapshots with integer revisions, and supports an optional one-time
bootstrap from a version-1 JSON file after making an immutable verified backup.

Compatibility: Python 3.12 stdlib only. Each write uses BEGIN IMMEDIATE and
compare-and-swap revision checks. The snapshot insert and head update commit
together. WAL + synchronous=FULL are configured for durability on local disks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sqlite3
from contextlib import contextmanager

from data_model import MAX_BYTES, normalize_plus, validate_plus


SCHEMA_VERSION = 1


class RevisionConflict(RuntimeError):
    """A writer based its update on a stale persisted revision."""


class StoreAlreadyInitialized(RuntimeError):
    """Cannot bootstrap JSON into a database already containing a snapshot."""


class MigrationConflict(RuntimeError):
    """A different legacy JSON was supplied after initial migration."""


class UnsupportedSchemaError(RuntimeError):
    """The database is not an empty or supported Madar snapshot schema."""


class SnapshotIntegrityError(RuntimeError):
    """Saved snapshot content disagrees with its recorded SHA-256 checksum."""


@dataclass(frozen=True)
class Snapshot:
    """A detached state view. `revision` increments only for changed writes."""

    revision: int
    state: dict
    sha256: str
    created_at: str
    source: str


def _strict_constant(value):
    raise ValueError(f"Invalid non-JSON numeric constant {value}")


def _decode(raw):
    try:
        result = json.loads(raw.decode("utf-8"), parse_constant=_strict_constant)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ValueError("Expected strictly encoded UTF-8 JSON state") from exc
    return result


def _payload(state):
    normalized = normalize_plus(state)
    validate_plus(normalized)
    raw = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("State exceeds maximum 15 MB JSON limit")
    return raw


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _flush_file(path):
    # Windows os.fsync on a read-only descriptor raises EBADF.
    with open(path, "rb+") as file:
        os.fsync(file.fileno())


def _immutable_file(path, raw):
    """Create an immutable backup without replacing even a racing writer.

    Uses a unique fsynced temporary file and an atomic same-directory hard
    link. The link step fails closed on filesystems that cannot guarantee it.
    Existing matching content is accepted; different bytes fail closed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + "." + secrets.token_hex(12) + ".tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise MigrationConflict(f"Existing backup differs: {path}")
    finally:
        temp.unlink(missing_ok=True)
    return path


class SQLiteSnapshotStore:
    """Versioned, validated, immutable JSON snapshot history in SQLite.

    Constructor: SQLiteSnapshotStore(db_path: Path | str, *, timeout=5.0).
    Creates the local database and initial schema, without importing anything.

    load() -> Snapshot | None. ``None`` means uninitialized (revision 0).
    load_revision(revision) -> Snapshot, including historical revisions.
    save(state, *, expected_revision: int) -> Snapshot. Optimistic CAS write;
      raises RevisionConflict if another writer has advanced the head. An
      identical write at the current revision is a no-op (same revision).
    restore(revision, *, expected_revision: int) -> Snapshot. Appends a new
      revision with the selected older state; never deletes prior snapshots.
    bootstrap_from_json(json_path, *, backup_dir) -> Snapshot. Validates and
      normalizes the legacy JSON, creates an immutable SHA-256-addressed
      original-byte backup, then commits revision 1 and migration provenance in
      one SQLite transaction. Repeated same-file imports return the *current*
      snapshot; different source content raises MigrationConflict.
    backup_database(destination) -> Path. Uses SQLite's online backup API,
      making an immutable, standalone database copy that includes history.
    history(limit=100) -> list[int], newest first.
    integrity_check() -> bool. Runs SQLite integrity_check and verifies every
      snapshot digest and JSON validation.

    The DB file and backup paths must refer to local disks with SQLite-safe
    locking. Do not share a live .sqlite file using Dropbox, SMB or Drive;
    synchronize validated application data at a higher layer instead.
    """

    def __init__(self, db_path, *, timeout=5.0):
        self.path = Path(db_path).expanduser().resolve()
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 120:
            raise ValueError("timeout must be between 0 and 120 seconds")
        self.timeout = float(timeout)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._bootstrap_schema()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.path), timeout=self.timeout, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _begin(conn):
        conn.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _rollback(conn):
        if conn.in_transaction:
            conn.execute("ROLLBACK")

    def _bootstrap_schema(self):
        with self._connection() as conn:
            # Inspect the version and any foreign tables before setting WAL;
            # refusing an unknown database must not reconfigure its journal.
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise UnsupportedSchemaError(f"Unsupported database schema {version}")
            if version == 0:
                present = [row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'")]
                if present:
                    raise UnsupportedSchemaError("Unversioned database is not empty")
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode.lower() != "wal":
                raise UnsupportedSchemaError("Local SQLite WAL support is required")
            self._begin(conn)
            try:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    present = [row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%'")]
                    if present:
                        raise UnsupportedSchemaError("Unversioned database is not empty")
                    conn.execute("CREATE TABLE snapshots ("
                                 "revision INTEGER PRIMARY KEY CHECK(revision > 0), "
                                 "parent_revision INTEGER NOT NULL CHECK(parent_revision >= 0), "
                                 "payload BLOB NOT NULL, digest TEXT NOT NULL, "
                                 "created_at TEXT NOT NULL, source TEXT NOT NULL)")
                    conn.execute("CREATE TABLE head (id INTEGER PRIMARY KEY CHECK(id=1), "
                                 "revision INTEGER NOT NULL CHECK(revision >= 0))")
                    conn.execute("INSERT INTO head(id, revision) VALUES(1, 0)")
                    conn.execute("CREATE TABLE migrations (name TEXT PRIMARY KEY, "
                                 "source_sha256 TEXT NOT NULL, backup_path TEXT NOT NULL, "
                                 "first_revision INTEGER NOT NULL, created_at TEXT NOT NULL)")
                    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                elif version != SCHEMA_VERSION:
                    raise UnsupportedSchemaError(f"Unsupported database schema {version}")
                conn.execute("COMMIT")
            except BaseException:
                self._rollback(conn)
                raise

    @staticmethod
    def _head(conn):
        row = conn.execute("SELECT revision FROM head WHERE id=1").fetchone()
        if row is None:
            raise SnapshotIntegrityError("Missing database head")
        return row[0]

    @staticmethod
    def _read(conn, revision):
        row = conn.execute("SELECT revision,payload,digest,created_at,source "
                           "FROM snapshots WHERE revision=?", (revision,)).fetchone()
        if row is None:
            raise KeyError(f"Snapshot revision not found: {revision}")
        rev, raw, checksum, created_at, source = row
        raw = bytes(raw)
        if sha256(raw).hexdigest() != checksum:
            raise SnapshotIntegrityError(f"Checksum mismatch at revision {rev}")
        try:
            state = _decode(raw)
            validate_plus(state)
        except ValueError as exc:
            raise SnapshotIntegrityError(f"Invalid state at revision {rev}") from exc
        return Snapshot(rev, state, checksum, created_at, source)

    def load(self):
        """Return the latest committed detached snapshot or None."""
        with self._connection() as conn:
            conn.execute("BEGIN")
            try:
                revision = self._head(conn)
                return self._read(conn, revision) if revision else None
            finally:
                conn.execute("ROLLBACK")

    def load_revision(self, revision):
        if type(revision) is not int or revision < 1:
            raise ValueError("revision must be a positive integer")
        with self._connection() as conn:
            return self._read(conn, revision)

    @staticmethod
    def _check_expected(expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a nonnegative integer")

    @staticmethod
    def _insert(conn, raw, current, source):
        revision = current + 1
        checksum = sha256(raw).hexdigest()
        created_at = _utcnow()
        conn.execute("INSERT INTO snapshots(revision,parent_revision,payload,digest,created_at,source) "
                     "VALUES(?,?,?,?,?,?)", (revision, current, raw, checksum, created_at, source))
        changed = conn.execute("UPDATE head SET revision=? WHERE id=1 AND revision=?",
                               (revision, current)).rowcount
        if changed != 1:
            raise RevisionConflict("CONFLICT: database head advanced during write")
        return Snapshot(revision, _decode(raw), checksum, created_at, source)

    def _save_raw(self, conn, raw, expected_revision, source, *, force=False):
        current = self._head(conn)
        if current != expected_revision:
            raise RevisionConflict(f"CONFLICT: expected {expected_revision}, current {current}")
        if current and not force:
            latest = self._read(conn, current)
            if latest.sha256 == sha256(raw).hexdigest():
                return latest
        return self._insert(conn, raw, current, source)

    def save(self, state, *, expected_revision):
        """Atomically append a normalized snapshot using optimistic revision CAS."""
        self._check_expected(expected_revision)
        raw = _payload(state)
        with self._connection() as conn:
            self._begin(conn)
            try:
                snapshot = self._save_raw(conn, raw, expected_revision, "save")
                conn.execute("COMMIT")
                return snapshot
            except BaseException:
                self._rollback(conn)
                raise

    def restore(self, revision, *, expected_revision):
        """Restore a historical revision by appending it as a new head."""
        self._check_expected(expected_revision)
        if type(revision) is not int or revision < 1:
            raise ValueError("revision must be a positive integer")
        with self._connection() as conn:
            self._begin(conn)
            try:
                if self._head(conn) != expected_revision:
                    raise RevisionConflict("CONFLICT: stale head during restore")
                old = self._read(conn, revision)
                raw = _payload(old.state)
                snapshot = self._save_raw(conn, raw, expected_revision,
                                          f"restore:{revision}", force=True)
                conn.execute("COMMIT")
                return snapshot
            except BaseException:
                self._rollback(conn)
                raise

    def bootstrap_from_json(self, json_path, *, backup_dir):
        """One-time backup-first import of source bytes from legacy JSON v1.

        The original file is never renamed or changed. An SHA-256-addressed
        immutable backup of its exact UTF-8 bytes is fsynced and verified before
        the SQL transaction. On a crash before commit, no partial SQL import is
        visible; rerunning with the same source is safe. The backup may remain
        after a failed DB transaction and is deliberately not destroyed.
        """
        source = Path(json_path).expanduser().resolve(strict=True)
        if not source.is_file() or source == self.path:
            raise ValueError("Source must be a different existing JSON file")
        with source.open("rb") as stream:
            raw_legacy = stream.read(MAX_BYTES + 1)
        if len(raw_legacy) > MAX_BYTES:
            raise ValueError("Legacy JSON exceeds 15 MB")
        upgraded = _payload(_decode(raw_legacy))
        source_hash = sha256(raw_legacy).hexdigest()
        backup = Path(backup_dir).expanduser().resolve() / f"legacy-{source_hash}.json"
        if backup == source or backup == self.path:
            raise ValueError("Backup path conflicts with source or database")
        _immutable_file(backup, raw_legacy)
        if backup.read_bytes() != raw_legacy:
            raise SnapshotIntegrityError("Legacy backup verification failed")
        with self._connection() as conn:
            self._begin(conn)
            try:
                migration = conn.execute(
                    "SELECT source_sha256 FROM migrations WHERE name='legacy-json'").fetchone()
                if migration:
                    if migration[0] != source_hash:
                        raise MigrationConflict("Legacy JSON changed since previous import")
                    result = self._read(conn, self._head(conn))
                else:
                    if self._head(conn) != 0:
                        raise StoreAlreadyInitialized("Database already has snapshots")
                    result = self._insert(conn, upgraded, 0, "legacy-json")
                    conn.execute("INSERT INTO migrations(name,source_sha256,backup_path,first_revision,created_at) "
                                 "VALUES(?,?,?,?,?)", ("legacy-json", source_hash, str(backup),
                                                      result.revision, _utcnow()))
                conn.execute("COMMIT")
                return result
            except BaseException:
                self._rollback(conn)
                raise

    def history(self, limit=100):
        """Return committed revision numbers newest first, max 1000."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connection() as conn:
            return [r[0] for r in conn.execute(
                "SELECT revision FROM snapshots ORDER BY revision DESC LIMIT ?", (limit,))]

    def integrity_check(self):
        """Check SQLite structure and every snapshot digest and data schema."""
        with self._connection() as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise SnapshotIntegrityError("SQLite integrity check failed: " + check)
            revisions = [r[0] for r in conn.execute("SELECT revision FROM snapshots")]
            for revision in revisions:
                self._read(conn, revision)
            current = self._head(conn)
            if bool(revisions) != bool(current) or (revisions and max(revisions) != current):
                raise SnapshotIntegrityError("Head does not point to latest snapshot")
        return True

    def backup_database(self, destination):
        """Produce an immutable consistent SQLite backup, including WAL writes.

        Uses SQLite's online backup API rather than copying a live .db file.
        The destination must not exist; the published backup is atomic where
        same-directory hard links are supported. Caller chooses all paths.
        """
        destination = Path(destination).expanduser().resolve()
        if destination == self.path or destination.exists():
            raise FileExistsError(f"Backup destination exists or is source: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name("." + destination.name + "." + secrets.token_hex(12) + ".tmp")
        try:
            with self._connection() as conn:
                backup_conn = sqlite3.connect(str(temp))
                try:
                    conn.backup(backup_conn)
                finally:
                    backup_conn.close()
            _flush_file(temp)
            os.link(temp, destination)
            return destination
        finally:
            temp.unlink(missing_ok=True)
