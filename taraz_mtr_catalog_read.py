"""Isolated, read-only E2/E4 local Taraz catalog boundary, never a LAN route.

The host supplies an initialized standalone company registry, identity,
accounting store and scoped policy. Client JSON never supplies actor, grants,
company identity, candidate IDs or proof flags. A checked LOCAL company is
not an authenticated REMOTE Taraz peer or official party certification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import stat

from standalone_accounting import StandaloneAccountingStore
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_identity import LocalCompanyIdentity

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)
_PARTY_FIELDS = frozenset({"id", "name", "kind"})
_ITEM_FIELDS = frozenset({"id", "sku", "name", "kind", "unit", "active"})
_ROLES = frozenset({"admin", "editor", "viewer"})
MAX_QUERY_BYTES = 1024
MAX_PAGE_SIZE = 50
MAX_CATALOG_ROWS = 8192
MAX_RESPONSE_BYTES = 65536
MAX_SOURCE_AGE_SECONDS = 300
MAX_CLOCK_SKEW_SECONDS = 30


class CatalogReadError(ValueError):
    """Malformed or conflicting local catalog projection."""


class CatalogStale(CatalogReadError):
    """Source generation or host authorization observation is stale."""


def _id(value, field):
    if type(value) is not str or not _ID.fullmatch(value):
        raise CatalogReadError("invalid " + field)
    return value


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise CatalogReadError("duplicate JSON key")
        out[key] = value
    return out


def _nonfinite(_):
    raise CatalogReadError("nonfinite JSON")


def _canonical(value, limit):
    try:
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf8")
    except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
        raise CatalogReadError("invalid JSON data") from exc
    if len(raw) > limit:
        raise CatalogReadError("bounded JSON exceeded")
    return raw


def _query(value):
    if type(value) is not str:
        raise CatalogReadError("strict query_json string required")
    try:
        size = len(value.encode("utf8"))
    except UnicodeError as exc:
        raise CatalogReadError("invalid query encoding") from exc
    if size > MAX_QUERY_BYTES:
        raise CatalogReadError("query too large")
    try:
        obj = json.loads(value, object_pairs_hook=_unique, parse_constant=_nonfinite)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CatalogReadError("invalid query JSON") from exc
    if type(obj) is not dict or set(obj) != {
        "kind", "offset", "limit", "expectedRevision"
    }:
        raise CatalogReadError("unrecognized query scope")
    if type(obj["kind"]) is not str or obj["kind"] not in ("parties", "items"):
        raise CatalogReadError("unknown catalog")
    if (type(obj["offset"]) is not int or
            not 0 <= obj["offset"] <= MAX_CATALOG_ROWS or
            type(obj["limit"]) is not int or not 1 <= obj["limit"] <= MAX_PAGE_SIZE or
            type(obj["expectedRevision"]) is not int or
            not 0 <= obj["expectedRevision"] < 2**31):
        raise CatalogReadError("invalid page or source revision")
    return obj


def _utc(value, name):
    if (type(value) is not datetime or value.tzinfo is None or
            value.utcoffset() is None):
        raise CatalogReadError("trusted host " + name + " timestamp required")
    return value.astimezone(timezone.utc)


def _granted_rows(values):
    if values is None:
        return
    if (type(values) is not frozenset or len(values) > MAX_CATALOG_ROWS or
            any(type(v) is not str or not _ID.fullmatch(v) for v in values)):
        raise PermissionError("invalid host row authorization")


@dataclass(frozen=True, slots=True)
class HostCatalogScope:
    """Host-only operator scope. Standalone accounting has NO project ACL.

    Project grants and row/field visibility must be independently authenticated
    in the host. Neither this object nor its revision is a signature.
    """

    company_id: str
    org_id: str
    project_id: str
    project_grants: frozenset[str]
    role_grants: frozenset[str]
    party_fields: frozenset[str]
    item_fields: frozenset[str]
    party_ids: frozenset[str] | None
    item_ids: frozenset[str] | None
    source_revision: int
    observed_at: datetime

    def __post_init__(self):
        if (type(self.company_id) is not str or
                re.fullmatch(r"[a-f0-9]{32}\Z", self.company_id) is None):
            raise CatalogReadError("registry-issued local company ID required")
        _id(self.org_id, "org")
        if self.org_id != self.company_id:
            raise PermissionError("organization must be the registered local company")
        _id(self.project_id, "project")
        if (type(self.project_grants) is not frozenset or
                self.project_id not in self.project_grants or
                len(self.project_grants) > 256 or
                any(type(p) is not str or not _ID.fullmatch(p)
                    for p in self.project_grants)):
            raise PermissionError("host project scope denied")
        if (type(self.role_grants) is not frozenset or not self.role_grants or
                not self.role_grants <= _ROLES):
            raise PermissionError("host role visibility required")
        for visible, allowed in (
            (self.party_fields, _PARTY_FIELDS), (self.item_fields, _ITEM_FIELDS)
        ):
            if (type(visible) is not frozenset or "id" not in visible or
                    not visible <= allowed):
                raise PermissionError("explicit safe field visibility required")
        _granted_rows(self.party_ids)
        _granted_rows(self.item_ids)
        if (type(self.source_revision) is not int or
                not 0 <= self.source_revision < 2**31):
            raise CatalogReadError("host source revision required")
        _utc(self.observed_at, "observation")


def _path_check(path):
    if not isinstance(path, Path) or not path.is_absolute():
        raise PermissionError("absolute book path required")
    for part in (path, *path.parents):
        if (part.is_symlink() or getattr(part, "is_junction", lambda: False)() or
                part.exists() and
                getattr(part.lstat(), "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise PermissionError("linked book path denied")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise PermissionError("one regular local accounting book required")


def _text(value, label, limit=300):
    if (type(value) is not str or not value.strip() or len(value) > limit or
            any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise CatalogReadError("invalid catalog " + label)
    return value


def _safe_rows(records, kind, visible):
    if type(records) is not dict or len(records) > MAX_CATALOG_ROWS:
        raise CatalogReadError("oversized or malformed catalog")
    result = []
    for key, record in records.items():
        _id(key, "record ID")
        if type(record) is not dict or record.get("id") != key:
            raise CatalogReadError("record identity mismatch")
        if kind == "parties":
            if record.get("kind") not in ("customer", "vendor", "both"):
                raise CatalogReadError("invalid party kind")
            _text(record.get("name"), "party name")
        else:
            if record.get("kind") not in ("goods", "service"):
                raise CatalogReadError("invalid item kind")
            _text(record.get("name"), "item name")
            _text(record.get("sku"), "SKU", limit=64)
            _text(record.get("unit"), "unit", limit=40)
            if type(record.get("active")) is not bool:
                raise CatalogReadError("invalid item active flag")
        # Explicit ALLOWLIST; never forward creditLimit, receivable, payable,
        # historic balances, customer history, stock, documents or ledger.
        result.append({field: record[field] for field in visible})
    return sorted(result, key=lambda item: item["id"])


class TarazCatalogRead:
    """Local authenticated read facade around actual AccountingStore.read."""

    def __init__(self, *, registry, identity, store, host_scope):
        if (not isinstance(registry, StandaloneCompanyRegistry) or
                not isinstance(identity, LocalCompanyIdentity) or
                not isinstance(store, StandaloneAccountingStore) or
                type(host_scope) is not HostCatalogScope):
            raise PermissionError("real local registry, identity and store required")
        self.registry = registry
        self.identity = identity
        self.store = store
        self.scope = host_scope

    def read(self, *, session_token, query_json, trusted_now):
        query = _query(query_json)
        if (type(session_token) is not str or
                not 32 <= len(session_token) <= 256 or
                not session_token.isascii()):
            raise PermissionError("valid local company session token required")
        now = _utc(trusted_now, "now")
        age = (now - _utc(self.scope.observed_at, "observation")).total_seconds()
        if age < -MAX_CLOCK_SKEW_SECONDS or age > MAX_SOURCE_AGE_SECONDS:
            raise CatalogStale("host source observation expired")
        # Actual registered company identity and current ledger file, not
        # client-selected paths or an inferred company label.
        book = self.registry.company_data_directory(self.scope.company_id)
        if (self.identity.root != book or self.store.path.parent != book or
                self.store.path.name != "standalone-accounting.sqlite3"):
            raise PermissionError("local company/identity/book mismatch")
        _path_check(self.store.path)
        session = self.identity.require_session(session_token, "viewer")
        actor = session["username"]
        accounts = self.identity.accounting_accounts()
        account = accounts.get(actor)
        if (type(account) is not dict or account.get("role") != session["role"] or
                session["role"] not in self.scope.role_grants or
                account.get("financeView") is not True):
            raise PermissionError("local finance-view/role scope denied")
        # accounting_view inside store.read *fully replays* events and includes
        # ledger/docs. Never forward that view; project only safe catalog keys.
        result = self.store.read(actor=actor, accounts=accounts)
        if (type(result) is not dict or set(result) != {"revision", "view"} or
                type(result["revision"]) is not int or
                type(result["view"]) is not dict):
            raise CatalogReadError("unexpected accounting view schema")
        revision = result["revision"]
        if (revision != query["expectedRevision"] or
                revision != self.scope.source_revision):
            raise CatalogStale("catalog source revision changed")
        view = result["view"]
        if (type(view.get("parties")) is not dict or
                type(view.get("items")) is not dict or
                view.get("currency") not in ("TOMAN", "RIAL")):
            raise CatalogReadError("incompatible catalog view schema")
        kind = query["kind"]
        visible = self.scope.party_fields if kind == "parties" else self.scope.item_fields
        row_ids = self.scope.party_ids if kind == "parties" else self.scope.item_ids
        if row_ids is not None and not row_ids.issubset(view[kind]):
            raise CatalogStale("host catalog row grant no longer matches source")
        # Preserve ALL authorized rows, including duplicate/conflicting names.
        rows = [row for row in _safe_rows(view[kind], kind, visible)
                if row_ids is None or row["id"] in row_ids]
        offset, limit = query["offset"], query["limit"]
        page = rows[offset:offset + limit]
        response = {
            "version": 1, "kind": "party" if kind == "parties" else "item",
            "companyId": self.scope.company_id,
            "orgId": self.scope.org_id, "projectId": self.scope.project_id,
            "revision": revision, "authorizedCount": len(rows),
            "offset": offset, "limit": limit,
            "nextOffset": offset + len(page) if offset + len(page) < len(rows) else None,
            "visibleFields": sorted(visible), "rows": page,
            "authenticatedLocalCompany": True,
            "source": "StandaloneAccountingStore.read/accounting_view",
            "remoteTarazPeerAuthenticated": False,
            "importedIdentityOfficiallyVerified": False,
            "officialPartyLinkCreated": False, "financialPostingPerformed": False,
            "networkUsed": False,
        }
        _canonical(response, MAX_RESPONSE_BYTES)
        final = self.identity.require_session(session_token, "viewer")
        if (final["username"] != actor or final["role"] != session["role"]):
            raise PermissionError("session changed during read")
        return response
