"""Isolated Taraz-side MTR v2 *metadata* peer registry.

NO HTTP listener, finance posting, invoice, payment, ledger or official receipt.
This accepts HMAC envelopes only when an independent caller has already
authenticated the transport peer and provisioned the correct directional keys.
It must NOT be confused with Taraz's official finance authority.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile


_DOMAIN = b"MTR-peer-envelope-v2\x00"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_UTC = "%Y-%m-%dT%H:%M:%SZ"
_FIELDS = frozenset({
    "protocol", "version", "algorithm", "kind", "purpose", "organizationId",
    "senderId", "senderRole", "actorRole", "audience", "keyId", "requestId",
    "issuedUtc", "expiresUtc", "payloadSha256", "payload",
})
_ROLES = frozenset({"admin", "editor", "finance_submitter"})
_QUERY_CAPACITY = 10000
_QUERY_ARCHIVE_WARNING_AT = 9000


class PeerDenied(ValueError):
    """Invalid trust, envelope, identity, replay or stored registry state."""


class PeerConflict(PeerDenied):
    """Original request identity disagrees with durable metadata."""


def _canonical(value):
    def walk(node, depth=0, count=None):
        if count is None:
            count = [0]
        count[0] += 1
        if depth > 8 or count[0] > 512:
            raise PeerDenied("JSON complexity exceeded")
        if node is None or type(node) is bool:
            return
        if type(node) is int and abs(node) <= 2**53 - 1:
            return
        if type(node) is str and len(node) <= 4096:
            return
        if type(node) is list and len(node) <= 64:
            for item in node:
                walk(item, depth + 1, count)
            return
        if type(node) is dict and len(node) <= 64:
            for k, v in node.items():
                if type(k) is not str or not k or len(k) > 128:
                    raise PeerDenied("invalid property")
                walk(v, depth + 1, count)
            return
        raise PeerDenied("invalid JSON field")

    walk(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _unique(pairs):
    result = {}
    for key, val in pairs:
        if key in result:
            raise PeerDenied("duplicate JSON field")
        result[key] = val
    return result


def _bad_constant(_):
    raise PeerDenied("invalid JSON constant")


def _read(wire):
    if type(wire) is not bytes or not wire or len(wire) > 32768:
        raise PeerDenied("invalid envelope size/type")
    try:
        record = json.loads(wire.decode("utf-8"), object_pairs_hook=_unique,
                            parse_constant=_bad_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PeerDenied("invalid envelope encoding") from exc
    if type(record) is not dict or _canonical(record) != wire:
        raise PeerDenied("noncanonical envelope")
    return record


def _stamp(text, now):
    if type(text) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", text):
        raise PeerDenied("invalid timestamp")
    try:
        return datetime.strptime(text, _UTC).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PeerDenied("invalid timestamp") from exc


def _time_now(now):
    if (type(now) is not datetime or now.tzinfo is None or
            now.utcoffset() is None or now.microsecond):
        raise PeerDenied("explicit UTC second-precision clock required")
    return now.astimezone(timezone.utc)


def _token(value):
    if type(value) is not str or not _TOKEN.fullmatch(value):
        raise PeerDenied("invalid peer token")
    return value


def _sha(value):
    if type(value) is not str or not _SHA.fullmatch(value):
        raise PeerDenied("invalid digest")
    return value


def _id(value):
    if type(value) is not str or not _ID.fullmatch(value):
        raise PeerDenied("invalid request ID")
    return value


@dataclass(frozen=True)
class PeerConfig:
    """Trusted runtime config; never accept it from a request JSON payload."""

    organization_id: str
    madar_sender_id: str
    madar_key_id: str
    taraz_sender_id: str
    taraz_key_id: str
    madar_secret: bytes
    taraz_secret: bytes

    def __post_init__(self):
        for value in (self.organization_id, self.madar_sender_id, self.madar_key_id,
                      self.taraz_sender_id, self.taraz_key_id):
            _token(value)
        for name in ("madar_secret", "taraz_secret"):
            secret = getattr(self, name)
            if type(secret) is not bytes or not 32 <= len(secret) <= 4096:
                raise PeerDenied("invalid directional secret")
        if hmac.compare_digest(self.madar_secret, self.taraz_secret):
            raise PeerDenied("peer direction keys must be distinct")


def _verify(wire, *, config, now, expected_kind, purpose):
    if type(config) is not PeerConfig:
        raise PeerDenied("trusted peer configuration required")
    record = _read(wire)
    if set(record) != _FIELDS | {"mac"}:
        raise PeerDenied("missing/unknown peer field")
    if (type(record["version"]) is not int or record["version"] != 2 or
            record["protocol"] != "mtr-peer" or record["algorithm"] != "HMAC-SHA256" or
            record["kind"] != expected_kind or record["purpose"] != purpose or
            record["senderRole"] != "madar_sender" or
            record["audience"] != "taraz_peer" or
            type(record["actorRole"]) is not str or record["actorRole"] not in _ROLES):
        raise PeerDenied("invalid protocol purpose or role")
    if (record["organizationId"] != config.organization_id or
            record["senderId"] != config.madar_sender_id or
            record["keyId"] != config.madar_key_id):
        raise PeerDenied("wrong peer organization/sender/key")
    for name in ("organizationId", "senderId", "keyId"):
        _token(record[name])
    _id(record["requestId"])
    issued = _stamp(record["issuedUtc"], now)
    expires = _stamp(record["expiresUtc"], now)
    current = _time_now(now)
    if (expires <= issued or (expires - issued).total_seconds() > 300
            or issued > current + timedelta(seconds=30) or current >= expires):
        raise PeerDenied("expired/future/oversized lifetime")
    if type(record["payload"]) is not dict:
        raise PeerDenied("object payload required")
    raw = _canonical(record["payload"])
    if len(raw) > 16384:
        raise PeerDenied("payload too large")
    digest = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(_sha(record["payloadSha256"]), digest):
        raise PeerDenied("payload digest mismatch")
    supplied = _sha(record["mac"])
    body = {key: record[key] for key in _FIELDS}
    mac = hmac.new(config.madar_secret, _DOMAIN + _canonical(body),
                   hashlib.sha256).hexdigest()
    if not hmac.compare_digest(bytes.fromhex(supplied), bytes.fromhex(mac)):
        raise PeerDenied("invalid peer MAC")
    if expected_kind == "query":
        payload = record["payload"]
        if (set(payload) != {"originalRequestId", "originalPayloadSha256", "originalPurpose"}
                or payload["originalPurpose"] != "finance_review_request"):
            raise PeerDenied("invalid query subject")
        _id(payload["originalRequestId"])
        _sha(payload["originalPayloadSha256"])
        if payload["originalRequestId"] == record["requestId"]:
            raise PeerDenied("query cannot reuse original request ID")
    return record


def _receipt(query, *, status, config, now):
    if status not in {"received", "unknown"}:
        raise PeerDenied("unproven negative receipt is forbidden")
    payload = {
        **query["payload"], "queryRequestId": query["requestId"],
        "queryPayloadSha256": query["payloadSha256"], "lookupStatus": status,
    }
    now = _time_now(now)
    issued = now.strftime(_UTC)
    expires = (now + timedelta(seconds=60)).strftime(_UTC)
    body = {
        "protocol": "mtr-peer", "version": 2, "algorithm": "HMAC-SHA256",
        "kind": "receipt", "purpose": "receipt_lookup_result",
        "organizationId": config.organization_id,
        "senderId": config.taraz_sender_id, "senderRole": "taraz_peer",
        "actorRole": "peer", "audience": "madar_sender",
        "keyId": config.taraz_key_id, "requestId": query["requestId"],
        "issuedUtc": issued, "expiresUtc": expires,
        "payloadSha256": hashlib.sha256(_canonical(payload)).hexdigest(),
        "payload": payload,
    }
    body["mac"] = hmac.new(config.taraz_secret, _DOMAIN + _canonical(body),
                           hashlib.sha256).hexdigest()
    return _canonical(body)


class TarazPeerRegistry:
    """Durable metadata intake/query; the caller enforces external TLS identity."""

    def __init__(self, path: Path, config: PeerConfig):
        if (not isinstance(path, Path) or not path.is_absolute() or
                path.suffix != ".sqlite3" or not path.parent.is_dir() or
                path.is_symlink()):
            raise PeerDenied("host-selected absolute SQLite file required")
        if path.exists():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PeerDenied("unsafe linked/nonregular peer metadata database")
        if type(config) is not PeerConfig:
            raise PeerDenied("trusted peer config required")
        self.path = path
        self.config = config
        new = not path.exists()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if new and version == 0:
                    conn.execute("CREATE TABLE requests (org TEXT NOT NULL, request_id TEXT PRIMARY KEY,"
                                 "sender TEXT NOT NULL, key_id TEXT NOT NULL, actor_role TEXT NOT NULL,"
                                 "payload_sha TEXT NOT NULL, wire_sha TEXT NOT NULL, received_utc TEXT NOT NULL)")
                    conn.execute("CREATE TABLE audit (seq INTEGER PRIMARY KEY AUTOINCREMENT,"
                                 "request_id TEXT NOT NULL, kind TEXT NOT NULL, wire_sha TEXT NOT NULL,"
                                 "created_utc TEXT NOT NULL)")
                    conn.execute("CREATE TABLE queries (query_id TEXT PRIMARY KEY,"
                                 "org TEXT NOT NULL, original_id TEXT NOT NULL,"
                                 "original_sha TEXT NOT NULL, query_sha TEXT NOT NULL,"
                                 "actor_role TEXT NOT NULL)")
                    for table in ("requests", "queries"):
                        conn.execute(
                            f"CREATE TRIGGER deny_{table}_update BEFORE UPDATE ON {table} "
                            "BEGIN SELECT RAISE(ABORT,'immutable'); END"
                        )
                        conn.execute(
                            f"CREATE TRIGGER deny_{table}_delete BEFORE DELETE ON {table} "
                            "BEGIN SELECT RAISE(ABORT,'immutable'); END"
                        )
                    conn.execute("CREATE TRIGGER deny_audit_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'immutable'); END")
                    conn.execute("CREATE TRIGGER deny_audit_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'immutable'); END")
                    conn.execute("PRAGMA user_version=1")
                elif version != 1:
                    raise PeerDenied("unsupported peer registry schema")
                for name in ("requests", "queries", "audit"):
                    row = conn.execute("SELECT type FROM sqlite_master WHERE name=?", (name,)).fetchone()
                    if row is None or row[0] != "table":
                        raise PeerDenied("missing peer metadata table")
                if conn.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                    raise PeerDenied("damaged peer registry")
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @contextmanager
    def _connect(self):
        if self.path.is_symlink() or not self.path.parent.is_dir():
            raise PeerDenied("unsafe peer metadata path")
        if self.path.exists():
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PeerDenied("unsafe linked metadata file")
        conn = sqlite3.connect(self.path, timeout=8, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA busy_timeout=8000")
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _transport(verified_transport_peer):
        # This boolean is ONLY a testable API boundary; a real integration must
        # obtain it from independently validated TLS identity, never from JSON.
        if verified_transport_peer is not True:
            raise PermissionError("authenticated peer transport required")

    def query_capacity_status(self) -> dict:
        """Read-only operational signal. A full registry still accepts exact replays.

        No truncation/retention is safe here: dropping an old query ID permits
        a conflicting, newly HMAC-signed query to claim that same identity.
        The source DB stays the sole replay authority until a separately
        approved epoch-and-archive protocol is implemented.
        """
        with self._connect() as conn:
            conn.execute("BEGIN")
            used = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
            if not 0 <= used <= _QUERY_CAPACITY:
                raise PeerDenied("peer query registry capacity invariant violated")
            return {
                "used": used,
                "limit": _QUERY_CAPACITY,
                "remaining": _QUERY_CAPACITY - used,
                "archiveRecommended": used >= _QUERY_ARCHIVE_WARNING_AT,
                "newQueryIdsAllowed": used < _QUERY_CAPACITY,
                "existingQueryIdReplayAllowed": True,
                "automaticPruningAllowed": False,
            }

    def archive_to(self, destination: Path) -> dict:
        """Create-only offline snapshot for operator review, *not* capacity reset.

        Safe capacity rollover needs both persistent replay bindings and an
        independently reviewed new epoch. Archiving alone never releases the
        live registry's 10k limit and never destroys audit or query evidence.
        """
        if (not isinstance(destination, Path) or not destination.is_absolute()
                or destination.suffix != ".sqlite3" or destination == self.path):
            raise PeerDenied("distinct absolute .sqlite3 archive path required")
        for ancestor in (destination.parent, *destination.parent.parents):
            if (ancestor.is_symlink()
                    or getattr(ancestor, "is_junction", lambda: False)()
                    or not ancestor.is_dir()):
                raise PeerDenied("trusted existing archive directory required")
            info = ancestor.lstat()
            if getattr(info, "st_file_attributes", 0) & getattr(
                    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise PeerDenied("archive directory reparse point forbidden")
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("peer archive already exists")
        fd, filename = tempfile.mkstemp(
            prefix=".mtr-peer-archive-", suffix=".sqlite3",
            dir=destination.parent,
        )
        os.close(fd)
        temp_path = Path(filename)
        try:
            with self._connect() as source:
                with closing(sqlite3.connect(temp_path)) as archive:
                    source.backup(archive)
            with closing(sqlite3.connect(temp_path)) as archive:
                archive.execute("PRAGMA query_only=ON")
                if (archive.execute("PRAGMA user_version").fetchone()[0] != 1
                        or archive.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok"):
                    raise PeerDenied("peer archive readback failed")
                counts = {}
                for table in ("requests", "queries", "audit"):
                    if archive.execute(
                        "SELECT type FROM sqlite_master WHERE name=?", (table,),
                    ).fetchone() != ("table",):
                        raise PeerDenied("peer archive table missing")
                    counts[table] = archive.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                for table in ("requests", "queries", "audit"):
                    for action in ("update", "delete"):
                        name = f"deny_{table}_{action}"
                        if archive.execute(
                            "SELECT type FROM sqlite_master WHERE name=?", (name,),
                        ).fetchone() != ("trigger",):
                            raise PeerDenied("peer archive immutability trigger missing")
                if counts["queries"] > _QUERY_CAPACITY:
                    raise PeerDenied("peer archive query capacity invariant violated")
            with open(temp_path, "r+b") as copied:
                os.fsync(copied.fileno())
            digest = hashlib.sha256()
            with open(temp_path, "rb") as copied:
                while chunk := copied.read(64 * 1024):
                    digest.update(chunk)
            # Atomic create-if-absent; no existing file can be overwritten.
            os.link(temp_path, destination)
            return {
                "created": True,
                "archiveSha256": digest.hexdigest(),
                "queries": counts["queries"],
                "requests": counts["requests"],
                "auditEvents": counts["audit"],
                "liveQueryCapacityReleased": False,
            }
        finally:
            temp_path.unlink(missing_ok=True)

    def intake(self, wire: bytes, *, now: datetime, verified_transport_peer: bool):
        """Record verified *metadata* arrival; never review or post a document."""
        self._transport(verified_transport_peer)
        request = _verify(wire, config=self.config, now=now,
                          expected_kind="request", purpose="finance_review_request")
        _id(request["requestId"])
        digest = _sha(request["payloadSha256"])
        wire_sha = hashlib.sha256(wire).hexdigest()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT org,sender,key_id,actor_role,payload_sha,wire_sha FROM requests WHERE request_id=?",
                    (request["requestId"],),
                ).fetchone()
                binding = (self.config.organization_id, self.config.madar_sender_id,
                           self.config.madar_key_id, request["actorRole"], digest)
                if row is not None:
                    if row[:5] != binding:
                        raise PeerConflict("request ID reused with incompatible metadata")
                    # Identical content with a new expiring HMAC envelope is a
                    # duplicate of one accepted original, not a second send.
                    conn.commit()
                    return {"requestId": request["requestId"], "received": True,
                            "idempotent": True, "financialEventCreated": False}
                conn.execute(
                    "INSERT INTO requests VALUES(?,?,?,?,?,?,?,?)",
                    (*binding[:1], request["requestId"], *binding[1:], wire_sha,
                     _time_now(now).isoformat()),
                )
                conn.execute("INSERT INTO audit(request_id,kind,wire_sha,created_utc) VALUES(?,?,?,?)",
                             (request["requestId"], "metadata_arrived", wire_sha,
                              _time_now(now).isoformat()))
                conn.commit()
                return {"requestId": request["requestId"], "received": True,
                        "idempotent": False, "financialEventCreated": False}
            except Exception:
                conn.rollback()
                raise

    def query_receipt(self, wire: bytes, *, now: datetime,
                      verified_transport_peer: bool) -> bytes:
        """HMAC-signed metadata lookup: received or UNKNOWN, never fake nonreceipt."""
        self._transport(verified_transport_peer)
        query = _verify(wire, config=self.config, now=now,
                        expected_kind="query", purpose="receipt_lookup")
        original_id = query["payload"]["originalRequestId"]
        digest = query["payload"]["originalPayloadSha256"]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                prior = conn.execute(
                    "SELECT org,original_id,original_sha,query_sha,actor_role "
                    "FROM queries WHERE query_id=?", (query["requestId"],),
                ).fetchone()
                binding = (self.config.organization_id, original_id, digest,
                           query["payloadSha256"], query["actorRole"])
                if prior is not None and prior != binding:
                    raise PeerConflict("query ID already belongs to another subject/actor")
                if prior is None:
                    count = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
                    if count >= _QUERY_CAPACITY:
                        raise PeerDenied(
                            "peer query registry capacity reached; "
                            "existing query ID replay only, verified archive and "
                            "new protocol epoch required"
                        )
                    conn.execute("INSERT INTO queries VALUES(?,?,?,?,?,?)",
                                 (query["requestId"], *binding))
                row = conn.execute(
                    "SELECT org,sender,key_id,actor_role,payload_sha "
                    "FROM requests WHERE request_id=?",
                    (original_id,),
                ).fetchone()
                if row is not None and (
                    row[:3] != (self.config.organization_id, self.config.madar_sender_id,
                                self.config.madar_key_id)
                    or row[3] != query["actorRole"]
                    or row[4] != digest
                ):
                    # No independently authenticated actor delegation exists.
                    # A signed same-tenant query cannot change the original
                    # request role; rollback also discards its query-ID insert.
                    raise PeerConflict("query original digest/identity/actor role mismatch")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        if row is None:
            status = "unknown"
        else:
            status = "received"
        return _receipt(query, status=status, config=self.config, now=now)


__all__ = ["PeerConfig", "PeerDenied", "PeerConflict", "TarazPeerRegistry"]
