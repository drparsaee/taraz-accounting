"""Origin-independent, per-account persistence for the device-local Planner.

Integration: `PlannerPersistence(explicit_madar_data_root).read(account_id)`
returns a Planner v1 dict or None when never saved. `write(account_id, state)`
validates the same logical shape as src/planner.js and returns the saved dict.

The active file and its immediately preceding valid revision are kept in the
same local folder. This is not a whole-profile backup, encryption, an import
from a previous WebView origin, or a concurrency-aware edit merge. The caller
must perform migration of existing browser-local Planner data separately.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import time


SCHEMA_VERSION = 1
MAX_STATE_BYTES = 32 * 1024 * 1024
MAX_ACCOUNT_CHARS = 120
MAX_STRUCTURED_ACCOUNT_CHARS = 4096
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,120}\Z")
_PLANNER_URL = re.compile(r"https?://[^\s]+\Z", flags=re.IGNORECASE)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
_FREQUENCIES = frozenset(("none", "daily", "weekly", "monthly"))
_CALENDARS = frozenset(("gregorian", "jalali"))


class PlannerPersistenceError(RuntimeError):
    """An on-disk Planner copy cannot be safely read or replaced."""


def _linked(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _safe_path(path: Path) -> None:
    for parent in (path, *path.parents):
        if _linked(parent):
            raise PlannerPersistenceError("Planner storage cannot follow a link or junction")


def _account(account_id: str) -> str:
    if not isinstance(account_id, str):
        raise ValueError("Planner account ID must be a string")
    identity = account_id.strip()
    # Preserve *all* pre-existing valid plain names, including legacy names
    # beginning with '['. JSON.stringify namespaces contain quoted strings,
    # which the legacy validator never accepted, so the formats cannot clash.
    legacy = (bool(identity) and len(identity) <= MAX_ACCOUNT_CHARS and
              identity not in (".", "..") and ".." not in identity and
              not any(char in identity for char in "/\\<>|\x00\"?*") and
              not any(ord(char) < 32 or ord(char) == 127 for char in identity))
    if legacy:
        try:
            identity.encode("utf8")
        except UnicodeEncodeError:
            raise ValueError("Invalid Planner account ID") from None
        return identity
    # The React UI has always sent JSON.stringify(['solo'|'server', user])
    # or JSON.stringify(['client', hostUrl, tlsFingerprint, user]). The native
    # store hashes the complete namespace into a filename; it does NOT place
    # any of these characters in an OS path. Accept only those structured
    # forms without renaming them, preserving existing browser storage keys.
    if identity.startswith("["):
        if len(identity) > MAX_STRUCTURED_ACCOUNT_CHARS:
            raise ValueError("Invalid Planner account ID")
        try:
            parts = json.loads(identity, parse_constant=lambda _: None)
        except (ValueError, TypeError):
            raise ValueError("Invalid Planner account ID") from None
        if not isinstance(parts, list) or len(parts) not in (2, 4) or any(
                not isinstance(part, str) for part in parts):
            raise ValueError("Invalid Planner account ID")
        if len(parts) == 2:
            mode, username = parts
            valid = (mode in ("solo", "server") and bool(username.strip()) and
                     len(username) <= MAX_ACCOUNT_CHARS)
        else:
            mode, url, fingerprint, username = parts
            valid = (mode == "client" and 0 < len(url) <= 3072 and
                     _PLANNER_URL.fullmatch(url) is not None and
                     len(fingerprint) <= 256 and bool(username.strip()) and
                     len(username) <= MAX_ACCOUNT_CHARS)
        if not valid:
            raise ValueError("Invalid Planner account ID")
        try:
            for index, part in enumerate(parts):
                if (not part and not (len(parts) == 4 and index == 2)) or any(
                        ord(char) < 32 or ord(char) == 127 for char in part):
                    raise ValueError("Invalid Planner account ID")
                part.encode("utf8")
            identity.encode("utf8")
        except UnicodeEncodeError:
            raise ValueError("Invalid Planner account ID") from None
        return identity
    raise ValueError("Invalid Planner account ID")


def _valid_date(value: object, *, optional: bool = False) -> bool:
    if optional and value == "":
        return True
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _text(value: object, limit: int, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValueError("Invalid Planner text")
    value = value.strip()
    if required and not value:
        raise ValueError("Planner item title is required")
    return value


def _repeat(value: object) -> dict:
    if value is None:
        value = "none"
    if isinstance(value, str):
        frequency, interval, calendar = value, 1, "gregorian"
    elif isinstance(value, dict):
        if set(value) - {"frequency", "interval", "calendar"}:
            raise ValueError("Unknown Planner repetition fields")
        frequency = value.get("frequency") or "none"
        interval = value.get("interval")
        if interval is None:
            interval = 1
        calendar = value.get("calendar")
        if calendar is None:
            calendar = "gregorian"
    else:
        raise ValueError("Invalid Planner repetition")
    if (not isinstance(frequency, str) or frequency not in _FREQUENCIES or
            type(interval) is not int or not 1 <= interval <= 12 or
            not isinstance(calendar, str) or calendar not in _CALENDARS):
        raise ValueError("Invalid Planner repetition")
    return {"frequency": frequency, "interval": interval, "calendar": calendar}


def _planner(value: object) -> dict:
    """Validate before any write; never truncate or discard unknown user data."""
    if (not isinstance(value, dict) or type(value.get("version")) is not int or
            value["version"] != SCHEMA_VERSION or
            set(value) != {"version", "inbox", "entries"} or
            not isinstance(value["inbox"], list) or
            not isinstance(value["entries"], list) or
            len(value["inbox"]) > 5000 or len(value["entries"]) > 15000):
        raise ValueError("Invalid or unsupported Planner version/shape")
    inbox, entries = [], []
    inbox_ids, entry_ids = set(), set()
    for item in value["inbox"]:
        expected = {"id", "title", "notes", "createdDate", "dueDate", "doneAt",
                    "repeatAnchor", "remindTime", "dismissedFor", "repeat"}
        required = {"id", "title", "createdDate", "dueDate", "doneAt"}
        if not isinstance(item, dict) or not required <= set(item) or set(item) - expected:
            raise ValueError("Invalid Planner item fields")
        ident = item["id"]
        if not isinstance(ident, str) or not _ID.fullmatch(ident) or ident in inbox_ids:
            raise ValueError("Invalid or duplicate Planner inbox ID")
        inbox_ids.add(ident)
        due = item["dueDate"]
        done = item["doneAt"]
        created = item["createdDate"]
        anchor = item.get("repeatAnchor")
        if anchor is None:
            anchor = due
        reminder = item.get("remindTime")
        if reminder is None:
            reminder = ""
        dismissed = item.get("dismissedFor")
        if dismissed is None:
            dismissed = ""
        rule = _repeat(item.get("repeat"))
        if (not _valid_date(created) or not _valid_date(due, optional=True) or
                not _valid_date(done, optional=True) or
                not _valid_date(anchor, optional=True) or
                not _valid_date(dismissed, optional=True) or
                not isinstance(reminder, str) or
                (reminder != "" and not _TIME.fullmatch(reminder)) or
                ((rule["frequency"] != "none" or reminder) and not due)):
            raise ValueError("Invalid Planner dates or reminder")
        inbox.append({
            "id": ident, "title": _text(item["title"], 240, required=True),
            "notes": _text(item.get("notes", ""), 3000),
            "createdDate": created, "dueDate": due, "doneAt": done,
            "repeatAnchor": anchor, "remindTime": reminder,
            "dismissedFor": dismissed, "repeat": rule,
        })
    for item in value["entries"]:
        if not isinstance(item, dict) or set(item) != {"id", "source", "refId", "date"}:
            raise ValueError("Invalid Planner entry fields")
        ident, source, reference, when = (
            item["id"], item["source"], item["refId"], item["date"])
        if (not isinstance(ident, str) or not _ID.fullmatch(ident) or
                ident in entry_ids or source not in ("personal", "task") or
                not isinstance(reference, str) or not _ID.fullmatch(reference) or
                not _valid_date(when)):
            raise ValueError("Invalid or duplicate Planner entry")
        entry_ids.add(ident)
        entries.append({"id": ident, "source": source, "refId": reference, "date": when})
    return {"version": SCHEMA_VERSION, "inbox": inbox, "entries": entries}


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Planner JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Invalid JSON number: " + value)


def _encode(state) -> bytes:
    normalized = _planner(state)
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf8")
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("Planner data exceeds safe storage limit")
    return raw


def _read_file(path: Path) -> tuple[dict, bytes] | None:
    _safe_path(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise PlannerPersistenceError("Planner storage is not a regular file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_STATE_BYTES + 1)
    if len(raw) > MAX_STATE_BYTES:
        raise PlannerPersistenceError("Planner storage exceeds supported size")
    try:
        parsed = json.loads(raw.decode("utf8"), object_pairs_hook=_strict_object,
                            parse_constant=_reject_constant)
        normalized = _planner(parsed)
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise PlannerPersistenceError("Saved Planner data is invalid; original preserved") from error
    return normalized, raw


def _sync_folder(folder: Path):
    # Windows has no portable Python directory-fsync; file fsync + atomic
    # rename are still used there, with power-loss guarantees unproven.
    if os.name != "nt":
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _publish(destination: Path, data: bytes):
    _safe_path(destination)
    temp = destination.with_name("." + destination.name + "." +
                                 secrets.token_hex(12) + ".tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _safe_path(destination)
        os.replace(temp, destination)
        _sync_folder(destination.parent)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def _writer_lock(path: Path):
    _safe_path(path)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\x00")
            stream.flush()
        deadline = time.monotonic() + 5.0
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
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise PlannerPersistenceError("Planner is being written by another process") from error
                time.sleep(0.025)
        try:
            yield
        finally:
            release()


class PlannerPersistence:
    """Device-local Planner v1 store rooted at an explicit existing data path."""

    def __init__(self, root: str | Path):
        if not root:
            raise ValueError("Planner storage requires an explicit data directory")
        self.root = Path(root).expanduser().absolute()
        _safe_path(self.root)
        self.folder = self.root / "planner-private-v1"

    def _paths(self, account_id: str) -> tuple[Path, Path, Path]:
        identity = _account(account_id)
        digest = sha256(identity.encode("utf8")).hexdigest()
        active = self.folder / (digest + ".json")
        previous = self.folder / (digest + ".previous.json")
        lock = self.folder / (digest + ".lock")
        return active, previous, lock

    def read(self, account_id: str) -> dict | None:
        active, previous, _ = self._paths(account_id)
        _safe_path(self.root)
        if not self.root.is_dir():
            raise PlannerPersistenceError("Planner data root does not exist")
        _safe_path(self.folder)
        if not self.folder.exists():
            return None
        if not self.folder.is_dir():
            raise PlannerPersistenceError("Planner directory is not a directory")
        saved = _read_file(active)
        if saved is not None:
            return saved[0]
        if previous.exists() or _linked(previous):
            raise PlannerPersistenceError("Planner primary is missing; previous copy preserved")
        return None

    def write(self, account_id: str, state: dict) -> dict:
        # All input validation precedes any mkdir or lock-file write.
        normalized = _planner(state)
        encoded = _encode(normalized)
        active, previous, lock = self._paths(account_id)
        _safe_path(self.root)
        if not self.root.is_dir():
            raise PlannerPersistenceError("Planner data root does not exist")
        _safe_path(self.folder)
        self.folder.mkdir(exist_ok=True)
        _safe_path(self.folder)
        with _writer_lock(lock):
            old = _read_file(active)
            if old is None and (previous.exists() or _linked(previous)):
                raise PlannerPersistenceError("Planner primary missing; manual recovery required")
            if old is not None:
                old_state, old_raw = old
                if old_state == normalized:
                    return normalized
                # Keep the previous *validated* state before changing primary.
                _publish(previous, old_raw)
            _publish(active, encoded)
        return normalized


__all__ = ["PlannerPersistence", "PlannerPersistenceError", "SCHEMA_VERSION"]
