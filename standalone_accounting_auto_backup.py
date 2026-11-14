"""Automatic, validated, rotating backups for the isolated accounting desktop.

Only a caller-specified absolute data directory is used. Never discovers APPDATA,
reads task/finance data, or treats a failed backup as permission to purge history.
Backups are plaintext portable SQLite files, restorable with the OFFLINE tool.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import threading
import time

from standalone_accounting_backup import (
    SOURCE_FILENAME, _absolute_path, _refuse_symlinks,
    backup_standalone_accounting,
)
from standalone_accounting_restore import _check_input
from standalone_accounting_backup_manifest import (
    publish_completion_manifest, verify_completion_manifest,
)


BACKUP_FOLDER = "standalone-accounting-backups"
BACKUP_INTERVAL_SECONDS = 5 * 60
MAX_BACKUPS = 60
_NAME = re.compile(
    r"standalone-accounting-auto-\d{8}T\d{12}Z-[a-f0-9]{16}\.sqlite3\Z"
)
_LOG = logging.getLogger(__name__)


class AutomaticBackupError(RuntimeError):
    """A verified backup could not be completed, retained or verified."""


@contextmanager
def _directory_lock(folder: Path, *, timeout: float = 30.0):
    """Cross-process rotation lock; one persistent file, never auto-deleted.

    Windows uses msvcrt byte locks. POSIX uses flock. The per-process RLock
    additionally serializes periodic and closing handlers in a single desktop.
    """
    lock_path = folder / ".standalone-accounting-auto.lock"
    _refuse_symlinks(lock_path)
    with lock_path.open("a+b") as handle:
        handle.seek(0)
        deadline = time.monotonic() + timeout
        if sys.platform == "win32":
            import msvcrt
            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def acquire():
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        while True:
            try:
                acquire()
                break
            except (OSError, PermissionError) as exc:
                if time.monotonic() >= deadline:
                    raise AutomaticBackupError(
                        "Could not acquire exclusive accounting backup rotation lock"
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            release()


class AutomaticStandaloneBackups:
    """Manage periodic and mandatory-on-exit snapshots for one private folder.

    Source is initialized by the desktop's *normal* accounting read. Backups
    never implicitly create or migrate the accounting source. Each rotation
    first publishes AND validates a new portable backup, then removes only
    recognizable old automatic backups until at most max_backups remain.
    """

    def __init__(self, explicit_data_root: Path, *,
                 interval_seconds: float = BACKUP_INTERVAL_SECONDS,
                 max_backups: int = MAX_BACKUPS,
                 plaintext_acknowledged: bool = False,
                 preserve_existing: bool = False):
        root = _absolute_path(Path(explicit_data_root), "accounting data root")
        if plaintext_acknowledged is not True:
            raise PermissionError("Automatic plaintext financial backups require explicit acknowledgement")
        if type(interval_seconds) not in (float, int) or not 0 < interval_seconds:
            raise ValueError("Backup interval must be positive")
        if type(max_backups) is not int or not 1 <= max_backups <= MAX_BACKUPS:
            raise ValueError("Backup retention must be between 1 and 60")
        if type(preserve_existing) is not bool:
            raise ValueError("Backup preservation must be explicit boolean")
        self.root = root
        self.source = root / SOURCE_FILENAME
        self.folder = root / BACKUP_FOLDER
        self.interval_seconds = interval_seconds
        self.max_backups = max_backups
        # An unclaimed migrated legacy profile must not silently retire any
        # historical backup on launch/exit while ownership remains unresolved.
        self.preserve_existing = preserve_existing
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_success: Path | None = None
        self.last_error: Exception | None = None

    def _ensure_folder(self) -> None:
        _refuse_symlinks(self.source)
        _refuse_symlinks(self.folder)
        if not self.root.is_dir():
            raise FileNotFoundError("Explicit standalone accounting directory is missing")
        self.folder.mkdir(exist_ok=True)
        if not self.folder.is_dir():
            raise ValueError("Accounting backup folder is not a directory")

    def _managed_files(self) -> list[Path]:
        result = []
        for entry in self.folder.iterdir():
            if not _NAME.fullmatch(entry.name):
                continue
            entry_stat = entry.lstat()
            if entry.is_symlink() or not stat.S_ISREG(entry_stat.st_mode):
                raise AutomaticBackupError(
                    "An automatic accounting backup path is not a regular file"
                )
            result.append(entry)
        return sorted(result, key=lambda path: (path.stat().st_mtime_ns, path.name))

    def backup_now(self) -> Path:
        """Take one validated WAL-consistent snapshot and safely rotate."""
        with self._lock:
            try:
                self._ensure_folder()
                with _directory_lock(self.folder):
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                    destination = self.folder / (
                        "standalone-accounting-auto-" + stamp + "-" +
                        secrets.token_hex(8) + ".sqlite3"
                    )
                    created = backup_standalone_accounting(
                        self.source, destination, plaintext_acknowledged=True)
                    # Verify the *published file*, including no sidecars and
                    # full event replay. Purge cannot occur until this passes.
                    try:
                        _check_input(created)
                    except BaseException:
                        # No failed candidate must masquerade as a restoreable
                        # snapshot. This name was exclusively generated here.
                        created.unlink(missing_ok=True)
                        raise
                    # Print/entry template libraries live OUTSIDE the event
                    # ledger. Keep a matching, separately verifiable companion
                    # when the operator has saved templates. Never pretend the
                    # SQLite-only backup covers this sidecar.
                    from standalone_accounting_template_store import StandaloneAccountingTemplateStore
                    from standalone_accounting_identity import LocalCompanyIdentity
                    templates = StandaloneAccountingTemplateStore(self.root)
                    companion = created.with_suffix('.templates.json')
                    user_companion = created.with_suffix('.users.json')
                    try:
                        if templates.path.exists() or templates.path.is_symlink():
                            document = templates._read()
                            content = json.dumps(document, ensure_ascii=False,
                                                 separators=(',', ':')).encode('utf-8')
                            with companion.open('xb') as stream:
                                stream.write(content)
                                stream.flush()
                                os.fsync(stream.fileno())
                            if json.loads(companion.read_text(encoding='utf-8')) != document:
                                raise AutomaticBackupError('Template companion validation failed')
                        identities=LocalCompanyIdentity(self.root)
                        if identities.path.exists() or identities.path.is_symlink():
                            identity_document=identities._read()
                            if not identity_document['users']:
                                raise AutomaticBackupError('Protected identity registry has no users')
                            identity_bytes=json.dumps(identity_document,ensure_ascii=False,
                                separators=(',',':')).encode('utf-8')
                            with user_companion.open('xb') as stream:
                                stream.write(identity_bytes)
                                stream.flush()
                                os.fsync(stream.fileno())
                            if user_companion.read_bytes()!=identity_bytes:
                                raise AutomaticBackupError('User registry backup verification failed')
                    except BaseException:
                        companion.unlink(missing_ok=True)
                        user_companion.unlink(missing_ok=True)
                        created.unlink(missing_ok=True)
                        raise
                    # The manifest is the completion gate. An interrupted
                    # automatic snapshot must never pass as SQLite-only legacy.
                    try:
                        publish_completion_manifest(created)
                    except BaseException:
                        created.with_suffix('.manifest.json').unlink(missing_ok=True)
                        companion.unlink(missing_ok=True)
                        user_companion.unlink(missing_ok=True)
                        created.unlink(missing_ok=True)
                        raise
                    candidates = self._managed_files()
                    if created not in candidates:
                        raise AutomaticBackupError("Published backup disappeared before rotation")
                    # The new set may have changed since its completion marker
                    # was first published. Never retire the last good copy if
                    # the replacement has become incomplete in the meantime.
                    verify_completion_manifest(created)
                    # The validated new copy must not be selected for deletion,
                    # even after a clock adjustment or older timestamp.
                    obsolete_files = ([] if self.preserve_existing else
                        [p for p in candidates if p != created][
                            :max(0, len(candidates) - self.max_backups)])
                    for obsolete in obsolete_files:
                        # Only companion names derived from our own strict
                        # managed filename are eligible for rotation. Retire
                        # SQLite first: if it is locked or unlink fails, its
                        # identity/template companions must remain intact.
                        # Orphan companions after a later failure are safer
                        # than stripping a still-restorable SQLite snapshot.
                        obsolete.unlink()
                        obsolete.with_suffix('.manifest.json').unlink(missing_ok=True)
                        obsolete.with_suffix('.templates.json').unlink(missing_ok=True)
                        obsolete.with_suffix('.users.json').unlink(missing_ok=True)
                self.last_success = created
                self.last_error = None
                return created
            except Exception as exc:
                self.last_error = exc
                raise

    def _run(self):
        deadline = time.monotonic() + self.interval_seconds
        while not self._stop.wait(max(0.0, deadline - time.monotonic())):
            try:
                self.backup_now()
            except Exception:
                # Fail visibly in logs, keep old backups, and retry next tick.
                _LOG.exception("Scheduled standalone accounting backup failed")
            # Clock-anchored cadence. A slow snapshot never triggers a burst
            # of catch-up copies, nor overlaps with itself.
            deadline += self.interval_seconds
            if deadline <= time.monotonic():
                deadline = time.monotonic() + self.interval_seconds

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("Accounting backup scheduler already started")
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="madar-standalone-backups", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None


__all__ = [
    "AutomaticStandaloneBackups", "AutomaticBackupError", "BACKUP_INTERVAL_SECONDS",
    "MAX_BACKUPS", "BACKUP_FOLDER",
]
