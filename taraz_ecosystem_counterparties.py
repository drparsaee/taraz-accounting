"""Taraz-owned, company-scoped directory projection for a future trusted peer.

No socket, WebView bridge, account creation, finance view, or ledger mutation.
The native caller must supply its *verified* company book and a live Python
authorizer that checks actor, peer, and company grants on EVERY invocation.
No JSON/boolean supplied by a browser constitutes a credential.

Only current native party IDs are exposed. Imported Parsian identifiers have
no new Taraz party ID yet and are intentionally excluded until re-keyed by an
explicit, reviewed migration. The current accounting schema contains no
separate customer display code, so none is invented.
"""
from __future__ import annotations

import base64
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import stat
import unicodedata

from accounting_core import _project
from standalone_accounting import (
    AccountingIntegrityError, MAX_STATE_BYTES, _decode_checked,
)
from standalone_accounting_company_registry import (
    CompanyRegistryError, StandaloneCompanyRegistry,
)


_COMPANY = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_PARTY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_CURSOR = re.compile(r"[A-Za-z0-9_-]{1,2048}\Z", re.ASCII)
_KINDS = frozenset(("all", "customer", "vendor", "both"))
_LEGACY_PREFIX = "ps.parsian."
_SQLITE_FILE = "standalone-accounting.sqlite3"
_MAX_QUERY = 120
_MAX_CURSOR_BYTES = 1536
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_TABLE_COLUMNS = (
    ("id", "INTEGER", 0, 1),
    ("revision", "INTEGER", 1, 0),
    ("state", "BLOB", 1, 0),
    ("digest", "TEXT", 1, 0),
)


class CounterpartiesUnavailable(RuntimeError):
    """Missing, unsafe, unavailable, or invalid company accounting snapshot."""


class CounterpartiesCursorError(ValueError):
    """Search cursor was malformed or the source revision/filter changed."""


class _RowDenied(PermissionError):
    """A verified company-wide grant excluded one particular party."""


def _normalize(value: str) -> str:
    return (unicodedata.normalize("NFKC", value).casefold()
            .replace("ي", "ی").replace("ى", "ی").replace("ك", "ک"))


def _query(value: str) -> str:
    if (type(value) is not str or len(value) > _MAX_QUERY
            or any(ord(c) < 32 or ord(c) == 127
                   or (unicodedata.category(c) == "Cf" and c != "\u200c")
                   for c in value)):
        raise ValueError("Invalid counterparties query")
    try:
        value.encode("utf-8", "strict")
    except UnicodeError as exc:
        raise ValueError("Invalid counterparties query") from exc
    return _normalize(value.strip())


def _cursor_decode(value):
    if type(value) is not str or not _CURSOR.fullmatch(value):
        raise CounterpartiesCursorError("Invalid or stale search cursor")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        if len(raw) > _MAX_CURSOR_BYTES:
            raise ValueError("Oversized cursor")

        def unique(pairs):
            item = {}
            for key, entry in pairs:
                if key in item:
                    raise ValueError("Duplicate cursor key")
                item[key] = entry
            return item

        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(
                                ValueError("Invalid cursor constant")))
        if (type(result) is not dict or set(result) !=
                {"v", "companyId", "revision", "digest", "query", "kind", "after"}
                or result["v"] != 1
                or type(result["revision"]) is not int
                or type(result["companyId"]) is not str
                or type(result["digest"]) is not str
                or type(result["query"]) is not str
                or type(result["kind"]) is not str
                or type(result["after"]) is not str
                or not _PARTY.fullmatch(result["after"])):
            raise ValueError("Invalid cursor payload")
        return result
    except (ValueError, UnicodeError, TypeError, OverflowError):
        raise CounterpartiesCursorError("Invalid or stale search cursor") from None


def _cursor_encode(*, company_id, revision, digest, query, kind, after):
    raw = json.dumps({"v": 1, "companyId": company_id,
                      "revision": revision, "digest": digest,
                      "query": query, "kind": kind, "after": after},
                     sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    if len(raw) > _MAX_CURSOR_BYTES:
        raise CounterpartiesCursorError("Invalid or stale search cursor")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class TarazCounterpartiesDirectory:
    """Only a trusted Python/native host can construct an authorized reader.

    authorizer(company_id=..., operation='search'|'get', party_id=None|str)
    must return the exact singleton True. It is rechecked before and after
    reading, and for each individual visible party. It must derive live
    identity/peer/company grants itself, never trust the caller's JSON fields.
    """

    def __init__(self, book_directory, *, company_id, authorizer):
        if type(company_id) is not str or not _COMPANY.fullmatch(company_id):
            raise ValueError("Invalid company identifier")
        if not callable(authorizer):
            raise TypeError("Native authorization predicate required")
        if not isinstance(book_directory, (str, Path)):
            raise TypeError("Explicit company directory required")
        book = Path(book_directory)
        if (not book.is_absolute() or book.name != company_id
                or book.parent.name != "books"):
            raise CounterpartiesUnavailable("Registered accounting book required")
        self.company_id = company_id
        self._book = book
        self._authorizer = authorizer

    def _authorize(self, operation, party_id=None):
        try:
            allowed = self._authorizer(company_id=self.company_id,
                                       operation=operation, party_id=party_id)
        except Exception:
            raise PermissionError("Counterparties access denied") from None
        if allowed is not True:
            raise _RowDenied("Counterparties access denied")

    def _verified_ledger(self) -> Path:
        try:
            registered = StandaloneCompanyRegistry(
                self._book.parent.parent).company_data_directory(self.company_id)
            if registered != self._book:
                raise CounterpartiesUnavailable("Registered accounting book required")
            ledger = registered / _SQLITE_FILE
            info = ledger.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or ledger.is_symlink()
                    or getattr(info, "st_file_attributes", 0) & _REPARSE):
                raise CounterpartiesUnavailable("Accounting book unavailable")
            return ledger
        except (OSError, ValueError, CompanyRegistryError):
            raise CounterpartiesUnavailable("Accounting book unavailable") from None

    def _snapshot(self):
        ledger = self._verified_ledger()
        try:
            # mode=ro prevents writes and refuses to create an absent DB.
            # query_only additionally blocks accidental SQL writes on this
            # connection. No StandaloneAccountingStore constructor is used.
            with closing(sqlite3.connect(ledger.as_uri() + "?mode=ro",
                                         uri=True, isolation_level=None,
                                         timeout=5)) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                if db.execute("PRAGMA user_version").fetchone() != (1,):
                    raise CounterpartiesUnavailable("Invalid accounting book")
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'")}
                if tables != {"standalone_accounting"}:
                    raise CounterpartiesUnavailable("Invalid accounting book")
                columns = tuple(
                    (row[1], row[2].upper(), row[3], row[5])
                    for row in db.execute("PRAGMA table_info(standalone_accounting)"))
                if columns != _TABLE_COLUMNS:
                    raise CounterpartiesUnavailable("Invalid accounting book")
                rows = db.execute(
                    "SELECT id,revision,length(state),digest "
                    "FROM standalone_accounting LIMIT 2").fetchall()
                if not rows:
                    return 0, "0" * 64, {}
                if (len(rows) != 1 or type(rows[0][0]) is not int
                        or rows[0][0] != 1 or type(rows[0][1]) is not int
                        or rows[0][1] < 1 or type(rows[0][2]) is not int
                        or not 1 <= rows[0][2] <= MAX_STATE_BYTES):
                    raise CounterpartiesUnavailable("Invalid accounting book")
                revision = rows[0][1]
                digest = rows[0][3]
                raw = db.execute(
                    "SELECT state FROM standalone_accounting WHERE id=1").fetchone()[0]
                state = _decode_checked(raw, digest)
                projection = _project(state)
                parties = projection["parties"]
                if type(parties) is not dict:
                    raise CounterpartiesUnavailable("Invalid accounting book")
                # Store only the minimal native fields while this function
                # still holds a consistent SQLite read snapshot.
                visible = {}
                for pid, party in parties.items():
                    if (not isinstance(pid, str) or not _PARTY.fullmatch(pid)
                            or type(party) is not dict or party.get("id") != pid
                            or type(party.get("name")) is not str
                            or type(party.get("kind")) is not str
                            or party["kind"] not in ("customer", "vendor", "both")):
                        raise CounterpartiesUnavailable("Invalid accounting book")
                    if pid.startswith(_LEGACY_PREFIX):
                        continue
                    visible[pid] = {"partyId": pid, "name": party["name"],
                                    "kind": party["kind"]}
                return revision, digest, visible
        except CounterpartiesUnavailable:
            raise
        except (sqlite3.Error, AccountingIntegrityError, ValueError,
                TypeError, KeyError, OverflowError):
            raise CounterpartiesUnavailable("Invalid accounting book") from None

    def search(self, query="", kind="all", limit=50, cursor=None):
        normalized = _query(query)
        if type(kind) is not str or kind not in _KINDS:
            raise ValueError("Invalid counterparty kind")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid counterparty page size")
        decoded = _cursor_decode(cursor) if cursor is not None else None
        self._authorize("search")
        revision, digest, parties = self._snapshot()
        if decoded is not None and (
                decoded["companyId"] != self.company_id
                or decoded["revision"] != revision
                or decoded["digest"] != digest
                or decoded["query"] != normalized
                or decoded["kind"] != kind):
            raise CounterpartiesCursorError("Invalid or stale search cursor")
        start = decoded["after"] if decoded is not None else ""
        found = []
        has_more = False
        for pid in sorted(parties):
            if pid <= start:
                continue
            # A narrow per-party permission can only omit records; it cannot
            # widen company access. Check it BEFORE reading even safe fields
            # for filtering; do not reveal denied counts or IDs.
            try:
                self._authorize("search", pid)
            except _RowDenied:
                continue
            entry = parties[pid]
            if (kind != "all" and entry["kind"] != kind
                    and not (entry["kind"] == "both"
                             and kind in ("customer", "vendor"))):
                continue
            if normalized and normalized not in _normalize(entry["name"]):
                continue
            if len(found) == limit:
                has_more = True
                break
            found.append(entry)
        self._authorize("search")
        # A role, external peer grant or row ACL may change during the read.
        # Never return a row whose authorization was revoked mid-operation.
        for item in found:
            self._authorize("search", item["partyId"])
        return {"schemaVersion": 1, "companyId": self.company_id,
                "source": "TARAZ", "revision": revision,
                "counterparties": found, "hasMore": has_more,
                "nextCursor": _cursor_encode(
                    company_id=self.company_id, revision=revision, digest=digest,
                    query=normalized, kind=kind, after=found[-1]["partyId"])
                if has_more else None}

    def get(self, party_id):
        if type(party_id) is not str or not _PARTY.fullmatch(party_id):
            raise ValueError("Invalid counterparty identifier")
        self._authorize("get")
        # Never disclose legacy references or distinguish a denied row from
        # an unknown ID. The host must authenticate before calling this API.
        if party_id.startswith(_LEGACY_PREFIX):
            self._authorize("get")
            return None
        try:
            self._authorize("get", party_id)
        except _RowDenied:
            self._authorize("get")
            return None
        revision, _digest, parties = self._snapshot()
        result = parties.get(party_id)
        self._authorize("get")
        if result is not None:
            try:
                self._authorize("get", party_id)
            except _RowDenied:
                return None
        return ({"schemaVersion": 1, "companyId": self.company_id,
                 "source": "TARAZ", "revision": revision,
                 "counterparty": result} if result is not None else None)


__all__ = ["TarazCounterpartiesDirectory", "CounterpartiesUnavailable",
           "CounterpartiesCursorError"]
