"""Explicit offline/manual PLAINTEXT SQLite backup for standalone TOMAN accounting.

Never chooses an APPDATA location, initializes a missing source, restores a
database, or copies task/unified finance. A verified SQLite backup is published
with a same-directory hard link (atomic create-if-absent, no overwrite).
"""
from __future__ import annotations

import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile

from standalone_accounting import (
    StandaloneAccountingStore, StandaloneAccountingError, _decode_checked,
)


SOURCE_FILENAME = "standalone-accounting.sqlite3"
_SCHEMA_VERSION = 1
_AUDITOR = "offline-backup-internal"
_AUDITOR_ACCOUNTS = {
    _AUDITOR: {"username": _AUDITOR, "role": "admin"}
}


class StandaloneBackupError(RuntimeError):
    """Backup was not published; the source database remains unchanged."""


def _absolute_path(value, label: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise ValueError(label + " must be an explicitly supplied absolute Path")
    if not value.name or value.name in (".", ".."):
        raise ValueError("Invalid " + label)
    return value


def _refuse_symlinks(path: Path) -> None:
    """Fail closed for symlinks and Windows junctions in any path component."""
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError("Symlink/junction paths are prohibited for accounting backups")


def _existing_source(source: Path) -> None:
    if source.name != SOURCE_FILENAME:
        raise ValueError("Only standalone-accounting.sqlite3 is an allowed source")
    _refuse_symlinks(source)
    try:
        entry = source.lstat()
    except FileNotFoundError as exc:
        raise FileNotFoundError("Standalone accounting source does not exist") from exc
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError("Standalone source must be a regular SQLite file")


def _destination_target(source: Path, destination: Path) -> None:
    _refuse_symlinks(destination)
    if not destination.parent.is_dir():
        raise FileNotFoundError("Destination parent directory must already exist")
    if destination == source or destination.resolve(strict=False) == source.resolve():
        raise ValueError("Source and destination must differ")
    # lexists also detects dangling symlinks. Never remove or overwrite a target.
    if os.path.lexists(destination):
        raise FileExistsError("Backup destination already exists; refusing overwrite")


def _readonly_sqlite(path: Path) -> sqlite3.Connection:
    # Path.as_uri() percent-encodes non-ASCII/spaces and Windows drive paths.
    # ro refuses missing files; query_only prevents accidental INSERT/DDL.
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5.0,
                           isolation_level=None)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _check_snapshot(connection: sqlite3.Connection) -> int:
    if connection.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA_VERSION:
        raise StandaloneBackupError("Unknown standalone accounting schema version")
    schema_objects = {(row[0], row[1]) for row in connection.execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    if schema_objects != {("table", "standalone_accounting")}:
        raise StandaloneBackupError("Source/backup is not an isolated accounting database")
    columns = [(row[1], row[2].upper()) for row in connection.execute(
        "PRAGMA table_info(standalone_accounting)")]
    if columns != [("id", "INTEGER"), ("revision", "INTEGER"),
                   ("state", "BLOB"), ("digest", "TEXT")]:
        raise StandaloneBackupError("Unexpected accounting table layout")
    result = connection.execute("PRAGMA integrity_check").fetchall()
    if result != [("ok",)]:
        raise StandaloneBackupError("SQLite integrity_check failed")
    rows = connection.execute(
        "SELECT id, revision, state, digest FROM standalone_accounting").fetchall()
    if not rows:
        return 0  # valid pristine store, revision zero, not implicit migration
    if (len(rows) != 1 or type(rows[0][0]) is not int or rows[0][0] != 1
            or type(rows[0][1]) is not int or rows[0][1] < 1):
        raise StandaloneBackupError("Invalid accounting revision row")
    _, revision, state, digest = rows[0]
    # Full immutable history replay, including hash chain and command semantics.
    _decode_checked(state, digest)
    return revision


def _sqlite_backup(source: Path, temporary: Path) -> None:
    with closing(_readonly_sqlite(source)) as src:
        # Opening destination only after the exclusive temp name was created.
        with closing(sqlite3.connect(str(temporary), timeout=5.0)) as target:
            src.backup(target, pages=128, sleep=0.025)


def _validate_backup(temporary: Path) -> int:
    # First reject a foreign/corrupt DB before invoking Store constructor, since
    # the Store initializes virgin files. This temp is never an original DB.
    with closing(_readonly_sqlite(temporary)) as connection:
        revision = _check_snapshot(connection)

    # Independently call the unchanged Store public reader under a tiny,
    # trusted INTERNAL synthetic principal: no task accounts/passwords involved.
    verified = StandaloneAccountingStore(temporary).read(
        actor=_AUDITOR, accounts=_AUDITOR_ACCOUNTS)
    if (verified["revision"] != revision or
            verified["view"]["currency"] not in ("TOMAN", "RIAL")):
        raise StandaloneBackupError("Store replay view/revision mismatch")

    # Store opens WAL to satisfy its own contract. For a standalone, portable
    # one-file backup checkpoint all data and switch back to DELETE mode. This
    # touches the TEMP COPY only, never the original source.
    with closing(sqlite3.connect(str(temporary), timeout=5.0, isolation_level=None)) as conn:
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and checkpoint[0]:
            raise StandaloneBackupError("Could not checkpoint backed-up SQLite")
        if conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() != "delete":
            raise StandaloneBackupError("Backup cannot be made portable as a single file")

    with closing(_readonly_sqlite(temporary)) as connection:
        if _check_snapshot(connection) != revision:
            raise StandaloneBackupError("Backup changed during post-checkpoint validation")
    return revision


def _sync_file(path: Path) -> None:
    # On Windows CRT, os.fsync requires a descriptor opened with write access.
    # Only the validated temporary COPY is opened read/write here.
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _sync_directory(path: Path) -> None:
    """Best-effort directory metadata sync; Windows may refuse directory fd."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        try:
            os.fsync(fd)
        except OSError:
            pass
    finally:
        os.close(fd)


def backup_standalone_accounting(
    source: Path, destination: Path, *, plaintext_acknowledged: bool
) -> Path:
    """Create a consistent standalone snapshot; NEVER overwrite any destination.

    An explicit acknowledgement is mandatory because this is unencrypted
    personal/commercial financial information. Caller must protect/distribute
    it; this tool never restores, uploads or schedules backups.
    """
    if plaintext_acknowledged is not True:
        raise PermissionError("Explicit plaintext backup acknowledgement is required")
    source = _absolute_path(source, "source")
    destination = _absolute_path(destination, "destination")
    _existing_source(source)
    _destination_target(source, destination)

    temporary = None
    published = False
    prior_error = None
    try:
        fd, filename = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix="." + destination.name + ".partial-",
            suffix=".sqlite3")
        temporary = Path(filename)
        os.close(fd)
        _sqlite_backup(source, temporary)
        _validate_backup(temporary)
        _sync_file(temporary)
        # Same-directory hard-link is an atomic *no-overwrite* publish. os.replace
        # is forbidden: it would destroy an existing unrelated backup on a race.
        # Do not use copyfile fallback, which breaks our atomic/no-clobber claim.
        os.link(str(temporary), str(destination))
        published = True
        _sync_directory(destination.parent)
        return destination
    except BaseException as exc:
        prior_error = exc
        # If a post-publication step failed, revoke only our own hard link.
        # Another process may have replaced the destination in the meantime.
        if published and temporary is not None:
            try:
                if os.path.samefile(temporary, destination):
                    destination.unlink()
            except OSError as cleanup_exc:
                exc.add_note("Could not revoke failed backup publication: " +
                             str(cleanup_exc))
        raise
    finally:
        if temporary is not None:
            # Only delete names we created, never an existing destination. SQLite
            # may have produced temporary -wal/-shm journals under that prefix.
            cleanup_errors = []
            for suffix in ("-wal", "-shm", "-journal", ""):
                candidate = Path(str(temporary) + suffix)
                try:
                    candidate.unlink(missing_ok=True)
                except OSError as exc:
                    cleanup_errors.append(exc)
            if cleanup_errors:
                if prior_error is not None:
                    prior_error.add_note(
                        "Could not remove all temporary plaintext backup files: " +
                        "; ".join(str(error) for error in cleanup_errors))
                else:
                    raise StandaloneBackupError(
                        "Backup file published, but temporary plaintext cleanup failed"
                    ) from cleanup_errors[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manual PLAINTEXT standalone-accounting SQLite backup; no restore")
    parser.add_argument("--source", type=Path, required=True,
                        help="Absolute path to existing standalone-accounting.sqlite3")
    parser.add_argument("--destination", type=Path, required=True,
                        help="Absolute unused backup filename in existing directory")
    parser.add_argument("--acknowledge-plaintext", action="store_true",
                        help="Explicitly accept unencrypted financial data at destination")
    args = parser.parse_args(argv)
    try:
        result = backup_standalone_accounting(
            args.source, args.destination,
            plaintext_acknowledged=args.acknowledge_plaintext)
    except (ValueError, PermissionError, FileNotFoundError, FileExistsError,
            StandaloneBackupError, StandaloneAccountingError, sqlite3.Error,
            OSError) as exc:
        print("Backup refused: " + str(exc), file=sys.stderr)
        return 1
    print("Standalone accounting plaintext backup created: " + str(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
