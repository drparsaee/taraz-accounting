"""Offline-only maintenance CLI for the existing Madar full-recovery API.

Deliberately not a GUI / LAN endpoint. No implicit APPDATA discovery and no
network or cloud uploads. All managed paths are explicitly provided.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

from full_recovery import (RecoveryError, _safe_path, create_full_backup,
                           _journal_path, recover_interrupted_restore,
                           restore_full_backup)

try:
    import psutil
except ImportError:
    psutil = None


class MaintenanceRefused(RecoveryError):
    """Unsafe maintenance precondition (not a bad backup format)."""


_CLOUD_COMPONENTS = frozenset({
    "google drive", "my drive", "shared drives", "google_drive", "gdrive",
    ".shortcut-targets-by-id", "onedrive", "onedrive - personal",
    "onedrive - business", "dropbox", "icloud drive", "icloudrive",
})
_EXE_NAME = re.compile(r"madar[- ]?desk(?:-v[0-9][a-z0-9._-]*)?(?:\.exe)?\Z")
_SQL_DATABASES = ("madar-unified.sqlite3", "attachment-storage/attachments.sqlite3")


def _path(value):
    """Validate the *original* spelling, not a symlink-resolved substitute."""
    result = _safe_path(value)
    if not result.is_absolute() or result == result.parent:
        raise MaintenanceRefused("Provide an absolute, non-filesystem-root path")
    return result


def _sync_path(path):
    """Conservative path-name denylist, not a universal cloud-drive detector."""
    parts = {part.lower().strip() for part in path.parts}
    if parts & _CLOUD_COMPONENTS:
        return True
    # Desktop apps also expose Drive as a virtual Windows volume. Inspect its
    # volume label where possible rather than assuming G: means Google Drive.
    if os.name == "nt" and path.drive:
        import ctypes
        import ctypes.wintypes
        label = ctypes.create_unicode_buffer(256)
        try:
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                path.anchor, label, len(label), None, None, None, None, 0)
            if ok and label.value.lower().strip() in _CLOUD_COMPONENTS:
                return True
        except (AttributeError, OSError, ValueError):
            pass
    return False


def _assert_private_paths(root, archive=None):
    # Restores create pre-restore plaintext ZIP files adjacent to the data
    # root, so also deny a cloud-synced DATA root, not merely the archive.
    if _sync_path(root) or (archive is not None and _sync_path(archive)):
        raise MaintenanceRefused(
            "Refusing cloud/synced paths for unencrypted archives; choose a private local volume")


def _running_madar_processes():
    """Best-effort conservative global process inventory.

    Native EXEs are refused regardless of their data root. Other Python
    scripts are ignored unless they are explicitly running native_app.py.
    """
    if psutil is None:
        raise MaintenanceRefused("Process inspection unavailable (psutil missing); aborting")
    found = []
    try:
        processes = psutil.process_iter(["pid", "name", "cmdline"])
        for proc in processes:
            try:
                if proc.pid == os.getpid():
                    continue
                name = (proc.info.get("name") or "").lower().strip()
                if _EXE_NAME.fullmatch(name):
                    found.append(proc.pid)
                    continue
                if name.startswith(("python", "py.exe")):
                    cmd = proc.info.get("cmdline") or []
                    args = [str(arg).lower() for arg in cmd]
                    script = any(Path(arg).name == "native_app.py" for arg in args)
                    module = any(args[i] == "-m" and args[i + 1] == "native_app"
                                 for i in range(len(args) - 1))
                    if script or module:
                        found.append(proc.pid)
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, psutil.ZombieProcess):
                # If process identity cannot be inspected, maintenance cannot
                # claim the entire machine is offline. Fail closed.
                raise MaintenanceRefused("Cannot inspect all running processes") from None
    except (psutil.AccessDenied, psutil.Error, OSError) as exc:
        raise MaintenanceRefused("Cannot enumerate running writers") from exc
    return found


def _check_sqlite_writer(root):
    """Refuse when a source database currently holds a SQLite write lock."""
    for member in _SQL_DATABASES:
        db = _safe_path(root / member)
        if not db.exists():
            continue
        if not db.is_file():
            raise MaintenanceRefused("Unexpected database path type: " + member)
        conn = None
        try:
            # mode=rw refuses absent/invalid files and never creates a database.
            conn = sqlite3.connect(db.as_uri() + "?mode=rw", uri=True,
                                   timeout=0.0, isolation_level=None)
            conn.execute("PRAGMA busy_timeout=0")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
        except (sqlite3.Error, OSError) as exc:
            raise MaintenanceRefused(
                "SQLite is locked, busy, or unreadable: " + member) from exc
        finally:
            if conn is not None:
                conn.close()


def pending_restore_journal(data_root):
    """Read-only pre-Bridge startup guard: return journal Path or None.

    This detects *any* pending journal, including corrupt ones. The native
    startup must refuse launch if a path is returned; only a separate offline
    CLI invocation may inspect/recover the journal. No APPDATA path is derived,
    no directories are created, and no journal contents are trusted/read.
    """
    root = _path(data_root)
    journal = _safe_path(_journal_path(root))
    return journal if journal.exists() else None


@contextmanager
def _maintenance_lock(root):
    """A nonblocking, process-shared sibling file lock held for the whole run.

    It coordinates multiple maintenance commands, not unmodified app writers.
    Consequently writer inspection and an explicit user offline attestation
    are also mandatory. The one-byte lock file is intentionally persistent
    to avoid unlink/recreate races among separate callers.
    """
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:24]
    lock_path = _safe_path(root.parent / (".madar-maintenance-" + digest + ".lock"))
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            # The lock requires a byte to exist on Windows.
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
                os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise MaintenanceRefused("Another maintenance process holds the lock") from exc
            locked = True
            yield
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError) as exc:
                raise MaintenanceRefused("Another maintenance process holds the lock") from exc
            locked = True
            yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def execute(command, data_root, archive_path=None, *, offline_confirmed=False,
            plaintext_acknowledged=False):
    """Run a guarded offline full-recovery operation.

    No default APPDATA, no archive overwrite, no network and no GUI.
    Invokes only the existing, independently validated full_recovery APIs.
    """
    if command not in ("backup", "restore", "recover"):
        raise MaintenanceRefused("Unknown maintenance command")
    if offline_confirmed is not True:
        raise MaintenanceRefused("Stop Madar/LAN first, then pass --confirm-offline")
    root = _path(data_root)
    if not root.parent.is_dir():
        raise MaintenanceRefused("Parent directory does not exist")
    if command != "recover" and archive_path is None:
        raise MaintenanceRefused("An explicit archive path is required")
    if command == "recover" and archive_path is not None:
        raise MaintenanceRefused("Recover uses only the journal; no archive argument")
    archive = _path(archive_path) if archive_path is not None else None
    _assert_private_paths(root, archive)
    if command in ("backup", "restore") and plaintext_acknowledged is not True:
        raise MaintenanceRefused(
            "Archives contain sensitive plaintext (including LAN password hashes); "
            "pass --acknowledge-plaintext and use protected local storage")

    with _maintenance_lock(root):
        active = _running_madar_processes()
        if active:
            raise MaintenanceRefused("Madar processes are still running (PIDs: " +
                                     ", ".join(str(pid) for pid in active[:8]) + ")")
        _check_sqlite_writer(root)
        if command == "backup":
            return create_full_backup(root, archive, offline=True)
        if command == "restore":
            return restore_full_backup(root, archive, offline=True)
        return recover_interrupted_restore(root, offline=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m maintenance_recovery",
        description="OFFLINE local-only Madar backup/restore; no GUI or cloud transport.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "restore", "recover"):
        sub = commands.add_parser(name)
        sub.add_argument("--data-root", type=Path, required=True,
                         help="explicit absolute Madar data directory (never auto-detected)")
        if name != "recover":
            sub.add_argument("--archive", type=Path, required=True,
                             help="absolute path to a local ZIP (new for backup)")
            sub.add_argument("--acknowledge-plaintext", action="store_true",
                             help="confirm ZIP contains sensitive, unencrypted information")
        sub.add_argument("--confirm-offline", action="store_true",
                         help="confirm all native Madar/LAN processes and writers are stopped")
    args = parser.parse_args(argv)
    try:
        result = execute(args.command, args.data_root,
                         getattr(args, "archive", None),
                         offline_confirmed=args.confirm_offline,
                         plaintext_acknowledged=getattr(args, "acknowledge_plaintext", False))
    except MaintenanceRefused as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        # Never emit a detailed stack trace containing confidential payloads.
        print("FAILED: " + str(exc), file=sys.stderr)
        return 4
    print(json.dumps({"ok": True, "command": args.command, "result": result},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["MaintenanceRefused", "execute", "main", "pending_restore_journal"]
