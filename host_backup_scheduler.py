"""Periodic, host-owned snapshots of Madar task data.

Integration (native_app.py intentionally remains unchanged)::

    scheduler = HostBackupScheduler(bridge)
    scheduler.start()       # host/solo only; immediately checks and backs up
    scheduler.status()      # safe to expose through a future native bridge
    scheduler.stop()        # during orderly host shutdown

Only `Bridge.createLocalBackup()` produces a snapshot. Its partial-backup
scope is preserved; neither this scheduler nor its small index contains the
Planner, attachments, LAN accounts, or a full recovery archive.

The index identifies *only* snapshots owned by this scheduler, so retention
cannot delete manually created or the host's daily pre-edit backups. A crash
between publishing a backup and indexing it can leave one unindexed, preserved
backup. Do not put this folder on a network/cloud-synced filesystem.
"""

from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import threading
import time


INTERVAL_SECONDS = 30
MAX_BACKUPS = 120
INDEX_NAME = ".host-periodic-backups.json"
LOCK_NAME = ".host-periodic-backups.lock"
_NAME = re.compile(
    r"madar-(?:unified-)?\d{8}-\d{6}-\d{6}\.(?:json|sqlite3)\Z"
)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_LOG = logging.getLogger(__name__)
_OMITTED = {
    "task-state-only": {
        "finance", "collaboration", "attachment-binaries",
        "planner-local-storage", "lan-accounts", "login-credentials",
    },
    "sqlite-domains-only": {
        "attachment-binaries", "planner-local-storage",
        "lan-accounts", "login-credentials",
    },
}


class HostBackupError(RuntimeError):
    """A scheduled backup or its retention safety checks failed."""


def _fingerprint(payload):
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_name(name, kind):
    if type(name) is not str or not _NAME.fullmatch(name):
        raise HostBackupError("Invalid scheduled backup filename")
    expected = "sqlite3" if kind == "sqlite" else "json"
    if kind not in ("sqlite", "json") or not name.endswith("." + expected):
        raise HostBackupError("Scheduled backup filename/storage mismatch")
    if (name.startswith("madar-unified-")) != (kind == "sqlite"):
        raise HostBackupError("Scheduled backup filename/storage mismatch")


def _regular_file(path):
    if _linked(path) or not path.is_file():
        raise HostBackupError("Scheduled backup path is absent, linked or not a file: " +
                              path.name)


def _linked(path):
    # Python 3.12 exposes Windows junctions separately from symlinks.
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


@contextmanager
def _process_lock(path, timeout=3):
    """Cross-process exclusion for one host backup folder, also on Windows."""
    if _linked(path) or (path.exists() and not path.is_file()):
        raise HostBackupError("Unsafe periodic backup lock file")
    with path.open("a+b") as stream:
        deadline = time.monotonic() + timeout
        if os.name == "nt":
            import msvcrt

            def acquire():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

        while True:
            try:
                acquire()
                break
            except (OSError, PermissionError) as error:
                if time.monotonic() >= deadline:
                    raise HostBackupError("Timed out acquiring backup folder lock") from error
                time.sleep(0.05)
        try:
            yield
        finally:
            release()


class HostBackupScheduler:
    """Every 30 seconds, back up a changed host revision; retain 120 copies.

    Requires the native Bridge's `_lock`, `_load`, `_unified_store`,
    `backups_dir`, `path`, `connection` and `createLocalBackup()` contracts.
    The first successful `start()` tick occurs immediately. No threads, folders,
    APPDATA access or backup writes are performed by construction.
    """

    def __init__(self, bridge, *, interval_seconds=INTERVAL_SECONDS,
                 max_backups=MAX_BACKUPS):
        if type(interval_seconds) not in (int, float) or not 0 < interval_seconds:
            raise ValueError("interval_seconds must be positive")
        if type(max_backups) is not int or not 1 <= max_backups <= 1000:
            raise ValueError("max_backups must be between 1 and 1000")
        self.bridge = bridge
        self.interval_seconds = interval_seconds
        self.max_backups = max_backups
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._last_success = None
        self._last_error = None
        self._last_checked = None
        self._last_scope = None
        self._backup_count = 0
        self._failure_count = 0

    def _check_host(self):
        mode = self.bridge.connection.get("mode", "solo")
        if mode not in ("solo", "server"):
            raise PermissionError("Periodic backups are host-only")

    def _folder(self):
        folder = Path(self.bridge.backups_dir).absolute()
        data_root = Path(self.bridge.path).absolute().parent
        if (folder.parent != data_root or
                any(_linked(component) for component in (data_root, *data_root.parents)) or
                not data_root.is_dir()):
            raise HostBackupError("Backup folder must be directly inside the host data root")
        if _linked(folder) or (folder.exists() and not folder.is_dir()):
            raise HostBackupError("Backup folder is not a safe local directory")
        if not folder.exists():
            folder.mkdir()
        if _linked(folder) or not folder.is_dir():
            raise HostBackupError("Backup folder became unsafe")
        return folder

    @staticmethod
    def _index(folder):
        path = folder / INDEX_NAME
        if _linked(path) or (path.exists() and not path.is_file()):
            raise HostBackupError("Unsafe scheduled backup index")
        if not path.exists():
            return []
        try:
            raw = path.read_bytes()
            if len(raw) > 512_000:
                raise ValueError("Index exceeds 512 KB")
            doc = json.loads(raw)
            if (type(doc) is not dict or set(doc) != {"schema", "entries"}
                    or type(doc["schema"]) is not int or doc["schema"] != 1
                    or type(doc["entries"]) is not list
                    or len(doc["entries"]) > 2000):
                raise ValueError("Invalid index schema")
            seen = set()
            for entry in doc["entries"]:
                if (type(entry) is not dict or
                        set(entry) != {
                            "name", "kind", "fingerprint", "scope",
                            "size", "mtimeNs",
                        }):
                    raise ValueError("Invalid index entry")
                _validate_name(entry["name"], entry["kind"])
                if (entry["name"] in seen or
                        type(entry["fingerprint"]) is not str or
                        not _DIGEST.fullmatch(entry["fingerprint"]) or
                        type(entry["size"]) is not int or entry["size"] <= 0 or
                        type(entry["mtimeNs"]) is not int or entry["mtimeNs"] < 0 or
                        entry["scope"] not in _OMITTED or
                        (entry["kind"] == "sqlite") !=
                        (entry["scope"] == "sqlite-domains-only")):
                    raise ValueError("Invalid index entry content")
                seen.add(entry["name"])
            return doc["entries"]
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise HostBackupError("Scheduled backup index is invalid; no rotation performed") from error

    @staticmethod
    def _publish_index(folder, entries):
        destination = folder / INDEX_NAME
        if _linked(destination):
            raise HostBackupError("Unsafe scheduled backup index")
        temporary = folder / ("." + INDEX_NAME + "." + secrets.token_hex(8) + ".tmp")
        try:
            data = json.dumps({"schema": 1, "entries": entries}, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _revision(self):
        if self.bridge._unified_store is not None:
            snapshot = self.bridge._unified_store.load()
            if snapshot is None or type(snapshot.sha256) is not str or not _DIGEST.fullmatch(snapshot.sha256):
                raise HostBackupError("Unified storage has no valid revision digest")
            return "sqlite", snapshot.sha256
        # Read committed state under the host lock; hashing canonical JSON
        # avoids mistaking whitespace/format migration for a changed task.
        return "json", _fingerprint(self.bridge._load())

    @staticmethod
    def _verify_output(folder, saved, kind, fingerprint):
        if type(saved) is not dict or saved.get("complete") is not False:
            raise HostBackupError("Native backup must explicitly report partial scope")
        scope = "sqlite-domains-only" if kind == "sqlite" else "task-state-only"
        if saved.get("scope") != scope or not isinstance(saved.get("omitted"), list):
            raise HostBackupError("Native backup scope is missing or incorrect")
        if not _OMITTED[scope].issubset(set(saved["omitted"])):
            raise HostBackupError("Native backup omissions are incomplete")
        name = saved.get("name")
        _validate_name(name, kind)
        path = folder / name
        if (type(saved.get("path")) is not str or
                Path(saved["path"]).absolute() != path):
            raise HostBackupError("Native backup escaped the designated host directory")
        _regular_file(path)
        if path.stat().st_size == 0:
            raise HostBackupError("Empty native backup file")
        if kind == "json":
            try:
                with path.open(encoding="utf-8") as stream:
                    actual = _fingerprint(json.load(stream))
            except (OSError, ValueError, TypeError) as error:
                raise HostBackupError("Native JSON backup is invalid") from error
            if actual != fingerprint:
                raise HostBackupError("Native JSON backup disagrees with host revision")
        else:
            # The SQLite native backup API copies a consistent WAL snapshot;
            # no second copy is made here. Check the published head/digest.
            import sqlite3
            try:
                with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                    check = db.execute("PRAGMA quick_check").fetchone()
                    head = db.execute(
                        "SELECT digest FROM app_revisions "
                        "WHERE revision=(SELECT revision FROM app_head WHERE id=1)"
                    ).fetchone()
                if check != ("ok",) or head != (fingerprint,):
                    raise HostBackupError("Published SQLite backup failed validation")
            except sqlite3.Error as error:
                raise HostBackupError("Published SQLite backup cannot be validated") from error
        metadata = path.stat()
        return {
            "name": name, "kind": kind, "fingerprint": fingerprint,
            "scope": scope, "size": metadata.st_size,
            "mtimeNs": metadata.st_mtime_ns,
        }

    @staticmethod
    def _exists_safe(folder, entry):
        path = folder / entry["name"]
        if _linked(path):
            raise HostBackupError("Linked scheduled backup file")
        if not path.exists():
            return False
        if not path.is_file():
            raise HostBackupError("Indexed scheduled backup is no longer a file")
        metadata = path.stat()
        if (metadata.st_size != entry["size"] or
                metadata.st_mtime_ns != entry["mtimeNs"]):
            raise HostBackupError("Indexed scheduled backup changed on disk; no rotation")
        return True

    def _rotate(self, folder, entries):
        if len(entries) <= self.max_backups:
            return entries
        retired = entries[:-self.max_backups]
        for entry in retired:
            _validate_name(entry["name"], entry["kind"])
            self._exists_safe(folder, entry)
        kept = entries[-self.max_backups:]
        # Publish the new ownership set before removing any old snapshot.
        # A failed index write must not delete bytes still named by the index.
        self._publish_index(folder, kept)
        for entry in retired:
            (folder / entry["name"]).unlink(missing_ok=True)
        return kept

    def run_once(self):
        """Synchronous tick for production or isolated tests; raises on error."""
        with self._lock:
            try:
                with self.bridge._lock:
                    self._check_host()
                    folder = self._folder()
                    with _process_lock(folder / LOCK_NAME):
                        entries = self._index(folder)
                        kind, fingerprint = self._revision()
                        latest = entries[-1] if entries else None
                        if (latest and latest["kind"] == kind and
                                latest["fingerprint"] == fingerprint and
                                self._exists_safe(folder, latest)):
                            entries = self._rotate(folder, entries)
                            self._backup_count = len(entries)
                            self._last_checked = datetime.now(timezone.utc).isoformat()
                            self._last_error = None
                            return False
                        saved = self.bridge.createLocalBackup()
                        entry = self._verify_output(folder, saved, kind, fingerprint)
                        entries.append(entry)
                        # Publish new ownership before removing any old copy.
                        self._publish_index(folder, entries)
                        entries = self._rotate(folder, entries)
                        self._backup_count = len(entries)
                        self._last_scope = entry["scope"]
                        self._last_success = datetime.now(timezone.utc).isoformat()
                        self._last_checked = self._last_success
                        self._last_error = None
                        return True
            except Exception as error:
                self._failure_count += 1
                self._last_error = str(error)
                self._last_checked = datetime.now(timezone.utc).isoformat()
                raise

    def _run(self):
        deadline = time.monotonic() + self.interval_seconds
        while not self._stop.wait(max(0, deadline - time.monotonic())):
            try:
                self.run_once()
            except PermissionError:
                _LOG.warning("Scheduled host backup stopped after entering client mode")
                break
            except Exception:
                _LOG.exception("Scheduled Madar host backup failed")
            deadline += self.interval_seconds
            if deadline <= time.monotonic():
                deadline = time.monotonic() + self.interval_seconds

    def start(self):
        """Immediate validated snapshot/check, then 30-second background ticks."""
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("Host backup scheduler already started")
            self.run_once()  # Fail before starting a thread if folder/index unsafe.
            self._stop.clear()
            self._thread = threading.Thread(target=self._run,
                                            name="madar-host-periodic-backups", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self):
        self._stop.set()
        with self._lock:
            worker = self._thread
            if worker is None:
                return
            if worker is threading.current_thread():
                raise RuntimeError("Backup worker cannot join itself")
        # Never hold the scheduler lock while joining: the worker may have
        # awakened and be waiting to acquire it for its final tick.
        worker.join(timeout=10)
        if worker.is_alive():
            raise TimeoutError("Backup worker has not stopped")
        with self._lock:
            if self._thread is worker:
                self._thread = None

    def status(self):
        with self._lock:
            return {
                "running": self._thread is not None and self._thread.is_alive(),
                "intervalSeconds": self.interval_seconds,
                "maxBackups": self.max_backups,
                "backupCount": self._backup_count,
                "lastSuccess": self._last_success,
                "lastChecked": self._last_checked,
                "lastError": self._last_error,
                "failureCount": self._failure_count,
                "scope": self._last_scope,
                "complete": False,
            }


__all__ = ["HostBackupScheduler", "HostBackupError", "INTERVAL_SECONDS",
           "MAX_BACKUPS", "INDEX_NAME"]
