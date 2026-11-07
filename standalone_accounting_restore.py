"""Explicit-path, OFFLINE-only, no-clobber standalone-accounting SQLite restore.

Restore NEVER detects APPDATA, initializes a missing DB, overwrites a target,
migrates other ledgers or invokes the native/LAN host. It creates a *new* DB
only after verifying the plaintext backup and a temporary, consistent copy.
Operator confirmations are declarations, not checks that the app is stopped.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys

from standalone_accounting import StandaloneAccountingError
from standalone_accounting_backup import (
    SOURCE_FILENAME, StandaloneBackupError, _absolute_path, _check_snapshot,
    _readonly_sqlite, _sqlite_backup, _sync_directory, _sync_file,
    _validate_backup,
)
from standalone_accounting_backup_manifest import (
    BackupManifestError, verify_completion_manifest,
)


class StandaloneRestoreError(RuntimeError):
    """Source rejected or a safe offline restore could not be published."""


_SIDECARS = ("-wal", "-shm", "-journal")
_STAGE_NAME = ".standalone-accounting.sqlite3.restore-pending"
_STAGE_FILES = {"sqlite": "ledger.sqlite3", "templates": "templates.json",
                "users": "users.json"}
_FINAL_FILES = {"sqlite": SOURCE_FILENAME, "templates": "invoice-templates.json",
                "users": "local-users.json"}


def _fingerprint(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def _locked_restore_stage(stage: Path):
    """One destination-side transaction, with a lock released on process death."""
    created = False
    try:
        stage.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        if _is_link_or_junction(stage) or not stage.is_dir():
            raise StandaloneRestoreError("Untrusted restore staging path")
        if not (stage / "lock").is_file():
            raise FileExistsError("Another restore is preparing this destination")
    lock_path = stage / "lock"
    if _is_link_or_junction(lock_path):
        raise StandaloneRestoreError("Untrusted restore lock")
    with lock_path.open("a+b" if created else "r+b") as stream:
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, PermissionError) as exc:
            raise FileExistsError("Another restore owns this destination") from exc
        try:
            yield created
        finally:
            stream.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _remove_owned_stage(stage: Path) -> None:
    """Never recursively delete an unrecognized or foreign staging entry."""
    known = {"lock", "ready.json", *_STAGE_FILES.values(),
             *("ledger.sqlite3" + suffix for suffix in _SIDECARS)}
    if set(p.name for p in stage.iterdir()) - known:
        raise StandaloneRestoreError("Unknown restore staging members need manual review")
    for name in known - {"lock"}:
        (stage / name).unlink(missing_ok=True)
    (stage / "lock").unlink(missing_ok=True)
    stage.rmdir()


def _check_stage_data(stage: Path, metadata: dict, source: Path,
                      destination: Path, completion: bytes | None,
                      original_head: tuple[int, str | None],
                      templates: dict, identity: dict) -> None:
    expected = {"sqlite"}
    if templates["present"]:
        expected.add("templates")
    if identity["present"]:
        expected.add("users")
    if (type(metadata) is not dict or set(metadata) !=
            {"format", "version", "source", "destination", "source_hash",
             "completion_hash", "files"} or
            metadata["format"] != "madar-accounting-restore" or
            metadata["version"] != 1 or
            metadata["source"] != str(source) or
            metadata["destination"] != str(destination) or
            type(metadata["files"]) is not dict or set(metadata["files"]) != expected or
            metadata["completion_hash"] != (sha256(completion).hexdigest() if
                                            completion is not None else None) or
            metadata["source_hash"] != _fingerprint(source)):
        raise StandaloneRestoreError("Restore transaction/source mismatch")
    for kind in expected:
        member = stage / _STAGE_FILES[kind]
        _check_path_components(member)
        if not member.is_file() or not stat.S_ISREG(member.lstat().st_mode):
            raise StandaloneRestoreError("Missing staged restore member")
        if metadata["files"][kind] != _fingerprint(member):
            raise StandaloneRestoreError("Staged restore member checksum mismatch: " + kind)
    for kind, companion in (("templates", templates), ("users", identity)):
        if companion["present"] and sha256(companion["bytes"]).hexdigest() != metadata["files"][kind]:
            raise StandaloneRestoreError("Backup companion changed since restore staging")
    with closing(_readonly_sqlite(stage / _STAGE_FILES["sqlite"])) as reader:
        if _checked_head(reader) != original_head:
            raise StandaloneRestoreError("Staged restore ledger head mismatch")
    # _validate_backup changes SQLite's journal mode, so running it *after*
    # recording the staged SHA would invalidate our crash-recovery fingerprint.
    # The initial copy passed that validator; recovery does immutable replay here.


def _owned_link(member: Path, target: Path) -> bool:
    if not os.path.lexists(target):
        return False
    _check_path_components(target)
    return os.path.samefile(member, target)


def preview_template_companion(source: Path, destination: Path | None = None) -> dict:
    """Read-only, schema-checked companion inspection for explicit SQLite backup.

    An absent companion means a legacy SQLite-only snapshot. A damaged one
    must fail closed, rather than silently restoring finance without layouts.
    """
    from standalone_accounting_template_store import validate_library_document
    companion = source.with_suffix('.templates.json')
    _check_path_components(companion)
    if not companion.exists() and not companion.is_symlink():
        return {"present": False, "count": 0, "source": companion}
    if companion.is_symlink() or not stat.S_ISREG(companion.lstat().st_mode):
        raise StandaloneRestoreError("Template backup companion is not a regular file")
    if companion.stat().st_size > 2 * 1024 * 1024:
        raise StandaloneRestoreError("Template backup companion exceeds size limit")
    try:
        content = companion.read_bytes()
        document = validate_library_document(json.loads(content.decode('utf-8')))
    except (OSError, ValueError, UnicodeDecodeError, TypeError) as exc:
        raise StandaloneRestoreError("Template backup companion is damaged") from exc
    if destination is not None:
        target = destination.parent / 'invoice-templates.json'
        _check_path_components(target)
        if os.path.lexists(target):
            raise FileExistsError('Template restore destination already exists')
    return {"present": True, "count": len(document['templates']),
            "source": companion, "bytes": content}


def preview_identity_companion(source: Path, destination: Path | None = None) -> dict:
    """Require a valid isolated user registry before restoring it with a book."""
    from standalone_accounting_identity import validate_identity_document
    companion=source.with_suffix('.users.json')
    _check_path_components(companion)
    if not companion.exists() and not companion.is_symlink():
        return {"present":False,"count":0,"source":companion}
    if companion.is_symlink() or not stat.S_ISREG(companion.lstat().st_mode):
        raise StandaloneRestoreError('Invalid user backup companion file')
    if companion.stat().st_size > 1024*1024:
        raise StandaloneRestoreError('User backup companion too large')
    try:
        raw=companion.read_bytes()
        users=validate_identity_document(json.loads(raw.decode('utf-8')))['users']
    except (OSError,ValueError,UnicodeDecodeError,TypeError,PermissionError) as exc:
        raise StandaloneRestoreError('User backup companion damaged') from exc
    if not users:
        raise StandaloneRestoreError('Protected user backup has no accounts')
    if destination is not None:
        target=destination.parent/'local-users.json'
        _check_path_components(target)
        if os.path.lexists(target):
            raise FileExistsError('User restore destination already exists')
    return {"present":True,"count":len(users),"source":companion,"bytes":raw}


def _is_link_or_junction(path: Path) -> bool:
    """Reject existing symlinks, Windows junctions and their ancestors."""
    return path.is_symlink() or (
        hasattr(path, "is_junction") and path.is_junction()
    )


def _check_path_components(path: Path) -> None:
    for component in (path, *path.parents):
        if _is_link_or_junction(component):
            raise ValueError("Symlink/junction paths are not allowed for offline restore")


def _refuse_sidecars(path: Path, *, destination: bool) -> None:
    # A missing destination with stale -wal/-shm is NOT safe to restore into.
    # A backup with sidecars is not a standalone, offline, one-file backup.
    for suffix in _SIDECARS:
        entry = Path(str(path) + suffix)
        if os.path.lexists(entry):
            what = "destination" if destination else "source"
            raise StandaloneRestoreError(
                f"Unexpected {what} SQLite companion file: {entry.name}")


def _checked_head(connection: sqlite3.Connection) -> tuple[int, str | None]:
    revision = _check_snapshot(connection)
    if revision == 0:
        return 0, None
    digest = connection.execute(
        "SELECT digest FROM standalone_accounting WHERE id=1").fetchone()[0]
    return revision, digest


def _check_input(source: Path) -> tuple[int, str | None]:
    _check_path_components(source)
    try:
        mode = source.lstat().st_mode
    except FileNotFoundError as exc:
        raise FileNotFoundError("Explicit standalone backup source is missing") from exc
    if not stat.S_ISREG(mode):
        raise ValueError("Source must be an existing regular SQLite backup file")
    _refuse_sidecars(source, destination=False)
    # No StandaloneAccountingStore(source): its constructor can create/migrate.
    with closing(_readonly_sqlite(source)) as reader:
        reader.execute("BEGIN")
        try:
            return _checked_head(reader)
        finally:
            reader.execute("ROLLBACK")


def _check_new_destination(source: Path, destination: Path) -> None:
    if destination.name != SOURCE_FILENAME:
        raise ValueError("Restore destination must be named standalone-accounting.sqlite3")
    _check_path_components(destination)
    if not destination.parent.is_dir():
        raise FileNotFoundError("Restore destination directory must already exist")
    if source == destination or source.resolve() == destination.resolve(strict=False):
        raise ValueError("Backup source and destination must not be identical")
    if os.path.lexists(destination):
        # Includes existing hard link aliases and dangling symbolic links.
        try:
            if os.path.samefile(source, destination):
                raise ValueError("Source and destination refer to the same inode")
        except (FileNotFoundError, OSError):
            pass
        raise FileExistsError("Restore destination already exists; never overwrite")
    _refuse_sidecars(destination, destination=True)


def restore_standalone_accounting(
    source: Path, destination: Path, *,
    plaintext_acknowledged: bool,
    offline_acknowledged: bool,
) -> Path:
    """Restore a validated portable standalone TOMAN DB to a NONEXISTENT path.

    The host MUST be stopped, including other processes that could start it.
    Assertions do not make stopping the host detectable/enforceable here.
    """
    if plaintext_acknowledged is not True:
        raise PermissionError("Explicit plaintext accounting acknowledgement required")
    if offline_acknowledged is not True:
        raise PermissionError("Explicit OFFLINE operator acknowledgement required")
    source = _absolute_path(source, "backup source")
    destination = _absolute_path(destination, "restore destination")
    if destination.name != SOURCE_FILENAME:
        raise ValueError("Restore destination must be named standalone-accounting.sqlite3")
    _check_path_components(destination)
    if not destination.parent.is_dir():
        raise FileNotFoundError("Restore destination directory must already exist")
    if source == destination or source.resolve() == destination.resolve(strict=False):
        raise ValueError("Backup source and destination must not be identical")
    _refuse_sidecars(destination, destination=True)
    stage = destination.parent / _STAGE_NAME
    _check_path_components(stage)
    if not os.path.lexists(stage):
        _check_new_destination(source, destination)
    try:
        completion = verify_completion_manifest(source)
    except BackupManifestError as exc:
        raise StandaloneRestoreError(str(exc)) from exc
    original_head = _check_input(source)
    template_companion = preview_template_companion(source)
    identity_companion = preview_identity_companion(source)
    cleanup_stage = False
    try:
        with _locked_restore_stage(stage) as created:
            staged_files = stage / _STAGE_FILES["sqlite"]
            if created:
                cleanup_stage = True
                _check_new_destination(source, destination)
                preview_template_companion(source, destination)
                preview_identity_companion(source, destination)
                # Verify an offline snapshot before any visible destination link.
                _sqlite_backup(source, staged_files)
                snapshot_revision = _validate_backup(staged_files)
                with closing(_readonly_sqlite(staged_files)) as reader:
                    restored_head = _checked_head(reader)
                if restored_head != original_head or snapshot_revision != original_head[0]:
                    raise StandaloneRestoreError(
                        "Backup snapshot head changed during OFFLINE restore verification")
                _sync_file(staged_files)
                _check_new_destination(source, destination)
                _refuse_sidecars(source, destination=False)
                current_template = preview_template_companion(source, destination)
                current_identity = preview_identity_companion(source, destination)
                if (current_template['present'] != template_companion['present'] or
                    current_template.get('bytes') != template_companion.get('bytes') or
                    current_identity['present'] != identity_companion['present'] or
                    current_identity.get('bytes') != identity_companion.get('bytes')):
                    raise StandaloneRestoreError('Backup companion changed during restore')
                try:
                    if verify_completion_manifest(source) != completion:
                        raise StandaloneRestoreError('Backup completion manifest changed during restore')
                except BackupManifestError as exc:
                    raise StandaloneRestoreError(str(exc)) from exc
                files = {"sqlite": _fingerprint(staged_files)}
                for kind, companion in (("templates", template_companion),
                                        ("users", identity_companion)):
                    if companion['present']:
                        staged = stage / _STAGE_FILES[kind]
                        with staged.open('xb') as stream:
                            stream.write(companion['bytes'])
                            stream.flush()
                            os.fsync(stream.fileno())
                        files[kind] = _fingerprint(staged)
                metadata = {
                    "format": "madar-accounting-restore", "version": 1,
                    "source": str(source), "destination": str(destination),
                    "source_hash": _fingerprint(source),
                    "completion_hash": (sha256(completion).hexdigest() if completion is not None else None),
                    "files": files,
                }
                with (stage / "ready.json").open('xb') as stream:
                    stream.write(json.dumps(metadata, sort_keys=True).encode('utf-8'))
                    stream.flush()
                    os.fsync(stream.fileno())
            else:
                ready = stage / "ready.json"
                _check_path_components(ready)
                if not ready.is_file() or ready.stat().st_size > 4096:
                    raise StandaloneRestoreError("Interrupted restore has no valid ready record")
                try:
                    metadata = json.loads(ready.read_text(encoding='utf-8'))
                except (OSError, ValueError, UnicodeDecodeError) as exc:
                    raise StandaloneRestoreError("Interrupted restore ready record is damaged") from exc
            _check_stage_data(stage, metadata, source, destination, completion,
                              original_head, template_companion, identity_companion)
            cleanup_stage = True
            members = [kind for kind in ("templates", "users", "sqlite")
                       if kind in metadata["files"]]
            try:
                for kind in members:
                    staged = stage / _STAGE_FILES[kind]
                    target = destination.parent / _FINAL_FILES[kind]
                    if _owned_link(staged, target):
                        continue  # The same transaction published this link before a crash.
                    if os.path.lexists(target):
                        raise FileExistsError("Restore destination member already exists: " + target.name)
                    # Hard link is atomic no-clobber; SQLite is *always* the last link.
                    os.link(str(staged), str(target))
                _sync_directory(destination.parent)
                return destination
            except BaseException as exc:
                for kind in reversed(members):
                    target = destination.parent / _FINAL_FILES[kind]
                    try:
                        if _owned_link(stage / _STAGE_FILES[kind], target):
                            target.unlink()
                    except (OSError, ValueError) as cleanup_exc:
                        exc.add_note("Could not revoke owned restore link: " + str(cleanup_exc))
                        cleanup_stage = False
                raise
    finally:
        if cleanup_stage and stage.is_dir():
            _remove_owned_stage(stage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit OFFLINE standalone TOMAN accounting restore, "
                    "only to a NEW database file; never overwrite")
    parser.add_argument("--source", type=Path, required=True,
                        help="Absolute path to one-file, validated SQLite backup")
    parser.add_argument("--destination", type=Path, required=True,
                        help="Absolute NONEXISTENT .../standalone-accounting.sqlite3")
    parser.add_argument("--acknowledge-plaintext", action="store_true",
                        help="Accept unencrypted financial data at the destination")
    parser.add_argument("--offline", action="store_true",
                        help="Operator confirms all Madar hosts/processes are stopped")
    options = parser.parse_args(argv)
    try:
        published = restore_standalone_accounting(
            options.source, options.destination,
            plaintext_acknowledged=options.acknowledge_plaintext,
            offline_acknowledged=options.offline)
    except (PermissionError, ValueError, FileNotFoundError, FileExistsError,
            StandaloneRestoreError, StandaloneBackupError,
            StandaloneAccountingError, OSError, sqlite3.Error) as exc:
        print("Offline restore refused: " + str(exc), file=sys.stderr)
        return 1
    print("Standalone accounting OFFLINE plaintext restore created: " +
          str(published))
    return 0


if __name__ == "__main__":
    sys.exit(main())
