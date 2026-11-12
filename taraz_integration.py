"""Consent-based local Madar->Taraz metadata exchange.

Only the explicit user's metadata decision is persisted. No Taraz accounting
ledger, invoice, payable, party, payment or financial receipt is created.

The reviewed/<id>.intent.json file is the durable decision record. It is
fsynced to a temporary file and published via an atomic no-clobber hard link
BEFORE the pending request is moved. Subsequent calls finish an interrupted transition,
but never reinterpret a persisted decision or a changed source payload.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

_ID = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_BYTES = 32768
_MAX_MARKER_BYTES = 4096
_INTENT_KEYS = frozenset((
    "schema", "id", "source", "state", "sourceDigest", "taskId",
    "reviewedUtc", "financialEventCreated",
))
_RECEIPT_KEYS = frozenset((
    "schema", "id", "source", "state", "taskId",
    "reviewedUtc", "financialEventCreated",
))


def _exists(path: Path) -> bool:
    # Also detects dangling symlinks; Path.exists() alone does not.
    return os.path.lexists(path)


def _unsafe(path: Path) -> bool:
    if not _exists(path):
        return False
    info = path.lstat()
    return (
        stat.S_ISLNK(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        or bool(getattr(path, "is_junction", lambda: False)())
    )


def _safe_dir(path: Path, *, required: bool = True) -> bool:
    if _unsafe(path):
        raise PermissionError("Unsafe integration directory")
    if not _exists(path):
        if required:
            raise FileNotFoundError("Integration directory unavailable")
        return False
    if not path.is_dir():
        raise PermissionError("Integration path is not a directory")
    return True


def _read_file(path: Path, maximum: int) -> bytes:
    if _unsafe(path):
        raise PermissionError("Unsafe integration file")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise ValueError("Unsafe or oversized integration file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise PermissionError("Unsafe linked integration file")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise PermissionError("Integration file changed while opening")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(fd)
        current = path.lstat()
        if (
            _unsafe(path)
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
            or (after.st_size, after.st_mtime_ns) !=
               (opened.st_size, opened.st_mtime_ns)
            or len(raw) > maximum
        ):
            raise ValueError("Integration file changed or exceeded size limit")
        return raw
    finally:
        os.close(fd)


def _read_record(file: Path):
    raw = _read_file(file, _MAX_BYTES)
    def unique(pairs):
        record = {}
        for key, value in pairs:
            if key in record:
                raise ValueError("Duplicate integration proposal field")
            record[key] = value
        return record
    obj = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    if (type(obj) is not dict or type(obj.get("schema")) is not int
            or obj.get("schema") != 1 or obj.get("source") != "madar"):
        raise ValueError("Unexpected integration source or schema")
    if not _ID.fullmatch(str(obj.get("id", ""))) or file.stem != obj["id"]:
        raise ValueError("Invalid request identifier")
    for key, limit in (("taskId", 180), ("projectId", 180), ("title", 300)):
        value = obj.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError("Invalid request " + key)
    if obj.get("expenseId") is not None and (
        not isinstance(obj["expenseId"], str) or len(obj["expenseId"]) > 180
    ):
        raise ValueError("Invalid expense identifier")
    amount = obj.get("amountRial")
    if amount is not None:
        # Madar serializes exact RIAL amounts as decimal strings.
        if (type(amount) is str and 1 <= len(amount) <= 16 and amount.isascii()
                and amount.isdigit()):
            amount = int(amount)
        if type(amount) is not int or not 0 <= amount <= 9007199254740991:
            raise ValueError("Invalid optional amount")
    created = obj.get("createdUtc")
    if not isinstance(created, str) or len(created) > 40 or "T" not in created:
        raise ValueError("Invalid creation timestamp")
    result = {k: obj.get(k) for k in (
        "id", "schema", "source", "taskId",
        "expenseId", "title", "projectId", "createdUtc",
    )}
    result["amountRial"] = amount
    return result, hashlib.sha256(raw).hexdigest()


def _safe_record(file: Path):
    return _read_record(file)[0]


def _sync_dir(directory: Path):
    # POSIX can fsync directory entries. CPython on Windows usually cannot;
    # the file itself is always fsynced before its atomic replacement.
    try:
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        try:
            os.fsync(fd)
        except OSError:
            if os.name != "nt":
                raise
    finally:
        os.close(fd)


def _atomic_json(path: Path, payload: dict):
    """Create a marker atomically without EVER replacing a competing marker.

    An existence check followed by os.replace is not exclusive: a second
    process can create a marker between the check and the replace. Hard-link
    publication of an fsynced same-directory temporary file is no-clobber on
    supported filesystems. Unsupported filesystems must fail closed.
    """
    _safe_dir(path.parent)
    if _exists(path):
        raise FileExistsError("Existing integration marker cannot be replaced")
    body = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n").encode("utf-8")
    if len(body) > _MAX_MARKER_BYTES:
        raise ValueError("Integration marker exceeds size limit")
    fd, temporary = tempfile.mkstemp(prefix="." + path.stem + ".", suffix=".tmp",
                                    dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        _safe_dir(path.parent)
        if _exists(path):
            raise FileExistsError("Integration marker appeared during write")
        # os.link is an atomic create-if-absent operation (unlike os.replace).
        # Both names live in one directory/filesystem; a conflicting decision
        # or receipt is preserved and never silently overwritten.
        os.link(temporary, path)
        _sync_dir(path.parent)
    finally:
        if _exists(Path(temporary)):
            os.unlink(temporary)


def _read_marker(path: Path, expected_keys: frozenset) -> dict:
    def unique(pairs):
        record = {}
        for key, value in pairs:
            if key in record:
                raise ValueError("Duplicate integration marker field")
            record[key] = value
        return record
    marker = json.loads(_read_file(path, _MAX_MARKER_BYTES).decode("utf-8"),
                        object_pairs_hook=unique)
    if not isinstance(marker, dict) or frozenset(marker) != expected_keys:
        raise ValueError("Corrupt or unsupported integration marker")
    return marker


def _valid_time(value) -> bool:
    if not isinstance(value, str) or len(value) > 40:
        return False
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def _validate_intent(intent: dict, request_id: str, decision: str):
    if (
        intent["schema"] != 1 or type(intent["schema"]) is not int
        or intent["id"] != request_id or intent["source"] != "taraz"
        or intent["state"] not in ("reviewed", "rejected")
        or not isinstance(intent["state"], str)
        or not isinstance(intent["sourceDigest"], str)
        or not _SHA256.fullmatch(intent["sourceDigest"])
        or not isinstance(intent["taskId"], str)
        or not 1 <= len(intent["taskId"]) <= 180
        or not _valid_time(intent["reviewedUtc"])
        or intent["financialEventCreated"] is not False
    ):
        raise ValueError("Corrupt integration intent")
    if intent["state"] != decision:
        raise ValueError("Conflicting integration decision")


def _receipt(intent: dict) -> dict:
    return {k: v for k, v in intent.items() if k != "sourceDigest"}


@contextmanager
def _request_lock(directory: Path, request_id: str):
    """An OS-released per-ID lock serializes cooperating Taraz processes."""
    lock_path = directory / (request_id + ".lock")
    if _unsafe(lock_path):
        raise PermissionError("Unsafe integration lock")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    locked = False
    try:
        info = os.fstat(fd)
        current = lock_path.lstat()
        if (
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or _unsafe(lock_path)
            or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)
            or info.st_size > 1
        ):
            raise PermissionError("Unsafe integration lock")
        if info.st_size == 0:
            os.write(fd, b"\0")
            os.fsync(fd)
        if os.name == "nt":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        locked = True
        _safe_dir(directory)
        if _unsafe(lock_path):
            raise PermissionError("Integration lock replaced")
        current = lock_path.lstat()
        if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
            raise PermissionError("Integration lock replaced")
        yield
    finally:
        if locked:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def list_requests(root: Path):
    _safe_dir(root, required=False)
    pending = root / "pending"
    if not _safe_dir(pending, required=False):
        return {"connected": False, "requests": [], "invalidCount": 0,
                "pendingTruncated": False}
    reviewed = root / "reviewed"
    _safe_dir(reviewed, required=False)
    proposals = []
    invalid = 0
    candidates = sorted(pending.glob("*.json"))[:201]
    # The source intentionally displays at most 100 candidates per read.
    # Never silently report that truncated inbox as a complete set.
    truncated = len(candidates) > 100
    for file in candidates:
        try:
            if len(proposals) >= 100:
                break
            # A persisted intent already owns this decision, even if the
            # process crashed before moving the pending proposal. Do not
            # offer a conflicting fresh review button alongside recovery.
            if _exists(reviewed / (file.stem + ".intent.json")):
                continue
            proposals.append(_safe_record(file))
        except (ValueError, OSError, KeyError, TypeError, UnicodeError, PermissionError):
            invalid += 1
    proposals.sort(key=lambda p: p["createdUtc"], reverse=True)
    return {"connected": True, "requests": proposals, "invalidCount": invalid,
            "pendingTruncated": truncated}


def list_recoverable_reviews(root: Path):
    """Offer explicit manual recovery of durable but incomplete decisions.

    Only the intent produced by the newer source is authoritative for a
    restart. Neither a legacy review marker nor an absent pending file proves
    a decision. This bounded read never performs the recovery itself.
    """
    if not _safe_dir(root, required=False):
        return {"recovery": [], "recoveryInvalidCount": 0}
    reviewed = root / "reviewed"
    pending = root / "pending"
    if not _safe_dir(reviewed, required=False):
        return {"recovery": [], "recoveryInvalidCount": 0}
    _safe_dir(pending, required=False)
    found = []
    invalid = 0
    # Never enumerate unbounded inputs. An overflow is surfaced, not ignored.
    candidates = sorted(reviewed.glob("*.intent.json"))[:201]
    if len(candidates) > 200:
        return {"recovery": [], "recoveryInvalidCount": 201,
                "recoveryTruncated": True}
    for intent_path in candidates:
        if len(found) >= 100:
            break
        try:
            name = intent_path.name
            request_id = name[:-12]
            if not _ID.fullmatch(request_id):
                raise ValueError("Invalid recovery request ID")
            intent = _read_marker(intent_path, _INTENT_KEYS)
            _validate_intent(intent, request_id, intent.get("state"))
            first = pending / (request_id + ".json")
            second = reviewed / (request_id + ".json")
            if _exists(first) == _exists(second):
                raise ValueError("Missing or duplicated proposal for recovery")
            proposal, digest = _read_record(first if _exists(first) else second)
            if (digest != intent["sourceDigest"] or
                    proposal["taskId"] != intent["taskId"]):
                raise ValueError("Recovery source digest/actor mismatch")
            receipt = reviewed / (request_id + ".review.json")
            # Even a syntactically valid completed receipt must be checked
            # against its actual source; tampered or replayed bytes are an
            # operator-visible incident, never a silently completed review.
            if _exists(receipt):
                existing_receipt = _read_marker(receipt, _RECEIPT_KEYS)
                if existing_receipt != _receipt(intent) or _exists(first):
                    raise ValueError("Receipt conflicts with persisted decision")
                continue
            found.append({"id": request_id, "taskId": intent["taskId"],
                          "title": proposal["title"], "state": intent["state"],
                          "financialEventCreated": False})
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            invalid += 1
    return {"recovery": found, "recoveryInvalidCount": invalid,
            "recoveryTruncated": len(candidates) > 100}


def recover_review(root: Path, request_id: str):
    """Explicit operator action: finish the SAME persisted decision, never change it."""
    if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
        raise ValueError("Invalid recovery request ID")
    _safe_dir(root)
    reviewed = root / "reviewed"
    _safe_dir(reviewed)
    intent = _read_marker(reviewed / (request_id + ".intent.json"), _INTENT_KEYS)
    _validate_intent(intent, request_id, intent.get("state"))
    return review_request(root, request_id, intent["state"])


def review_request(root: Path, request_id: str, decision: str):
    if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
        raise ValueError("Invalid request ID")
    if decision not in ("reviewed", "rejected"):
        raise ValueError("Unknown integration decision")

    _safe_dir(root)
    pending = root / "pending"
    reviewed = root / "reviewed"
    _safe_dir(pending, required=False)
    source_path = pending / (request_id + ".json")
    dest = reviewed / (request_id + ".json")
    intent_path = reviewed / (request_id + ".intent.json")
    receipt_path = reviewed / (request_id + ".review.json")
    existing_reviewed = _safe_dir(reviewed, required=False)
    if not _exists(source_path) and not (
        existing_reviewed and any(_exists(path) for path in (
            dest, intent_path, receipt_path,
        ))
    ):
        raise FileNotFoundError("Request already processed or not found")
    if not existing_reviewed:
        # Another reviewing process may have created it after the first check.
        reviewed.mkdir(exist_ok=True)  # Never follow/permit a link; checked below.
        _safe_dir(reviewed)

    with _request_lock(reviewed, request_id):
        _safe_dir(root)
        _safe_dir(pending, required=False)
        _safe_dir(reviewed)
        src_present = _exists(source_path)
        dest_present = _exists(dest)
        intent_present = _exists(intent_path)
        receipt_present = _exists(receipt_path)
        if src_present and dest_present:
            raise FileExistsError("Request exists in pending and reviewed")
        if not intent_present:
            if dest_present or receipt_present:
                raise ValueError("Existing review without durable decision intent")
            if not src_present:
                raise FileNotFoundError("Request already processed or not found")
            source, digest = _read_record(source_path)
            intent = {
                "schema": 1,
                "id": request_id,
                "source": "taraz",
                "state": decision,
                "sourceDigest": digest,
                "taskId": source["taskId"],
                "reviewedUtc": datetime.now(timezone.utc).isoformat(),
                "financialEventCreated": False,
            }
            # Crash point 1: a decision now exists even if the move never runs.
            _atomic_json(intent_path, intent)
        else:
            intent = _read_marker(intent_path, _INTENT_KEYS)
            _validate_intent(intent, request_id, decision)

        # Verify data at its actual location, not just untrusted marker fields.
        if src_present:
            if receipt_present:
                raise ValueError("Receipt exists before the pending request moved")
            source, digest = _read_record(source_path)
        elif dest_present:
            source, digest = _read_record(dest)
        else:
            raise FileNotFoundError("Request missing after persisted decision")
        if digest != intent["sourceDigest"] or source["taskId"] != intent["taskId"]:
            raise ValueError("Integration source changed after decision")

        if src_present:
            # Detect in-place payload replacement between the first check and move.
            source_again, digest_again = _read_record(source_path)
            if source_again != source or digest_again != digest or _exists(dest):
                raise ValueError("Integration source changed before moving")
            _safe_dir(pending)
            _safe_dir(reviewed)
            # Windows os.rename refuses to overwrite an existing destination.
            # The per-ID lock is still required to coordinate cooperating peers.
            os.rename(source_path, dest)
            _sync_dir(pending)
            _sync_dir(reviewed)

        # Crash point 2: destination is present, intent is authoritative.
        source, digest = _read_record(dest)
        if digest != intent["sourceDigest"] or source["taskId"] != intent["taskId"]:
            raise ValueError("Reviewed integration source changed")
        expected_receipt = _receipt(intent)
        if _exists(receipt_path):
            actual = _read_marker(receipt_path, _RECEIPT_KEYS)
            if actual != expected_receipt:
                raise ValueError("Conflicting or corrupt integration receipt")
        else:
            # Crash point 3: missing receipt can be reproduced from the intent.
            _atomic_json(receipt_path, expected_receipt)
        return {
            "id": request_id,
            "state": decision,
            "financialEventCreated": False,
        }
