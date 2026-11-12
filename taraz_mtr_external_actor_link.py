"""Operator-authorized, one-time *external* Madar actor mapping.

The Madar actor ID is a 77-character opaque principal ID, deliberately distinct
from Taraz's 40-character local username. A valid peer HMAC authenticates the
configured Madar peer, but does NOT independently prove the named Madar human.
This bounded operator-approved link records only local consent to inspect an
already posted accounting journal. It never establishes finance authorization,
independent Madar human identity or an official receipt.

Operator provisions a private SQLite path, live registered-company
AccountingDesktopAPI, a TarazPeerRegistry with independently provisioned keys,
and a current LocalCompanyIdentity administrator session. No JSON boolean,
caller-supplied identity dictionary, or unsigned actor alias is an admission.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
from threading import RLock
from urllib.parse import quote

from standalone_accounting_desktop import AccountingDesktopAPI
from taraz_desktop import bridge_root
from taraz_mtr_official_receipt_gate import _principal, _safe_company
from taraz_mtr_peer_registry import PeerConfig, TarazPeerRegistry, _verify
from taraz_mtr_review_attestation_issuer import (
    _directory, _read_review, _registry_original_binding,
)

_HEX32 = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_EXTERNAL_ACTOR = re.compile(r"mtr-actor-v1-[0-9a-f]{64}\Z", re.ASCII)
_SIGNED_BINDING = frozenset({
    "id", "taskId", "projectId", "sourceDigest", "companyId", "actorId",
    "invoiceId", "issueEventId", "journalId",
})
_TTL = timedelta(seconds=90)
_SCHEMA = 1


class ExternalActorLinkDenied(PermissionError):
    """The operator has not authorized this exact external actor binding."""


def _deny(message):
    raise ExternalActorLinkDenied(message)


def _trusted_now(now):
    actual = datetime.now(timezone.utc)
    if now is None:
        return actual.replace(microsecond=0) + timedelta(seconds=bool(actual.microsecond))
    if (type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None
            or now.microsecond):
        _deny("trusted second-precision UTC clock required")
    stamp = now.astimezone(timezone.utc)
    if abs((stamp - actual).total_seconds()) > 5:
        _deny("injected UTC time differs from trusted clock")
    return stamp


def _safe_db(path):
    if (not isinstance(path, Path) or not path.is_absolute()
            or path.name != "external-actor-links.sqlite3"):
        _deny("operator-provisioned private external actor link DB required")
    _directory(path.parent)
    if path.exists() or os.path.lexists(path):
        if path.is_symlink() or not path.is_file():
            _deny("linked/nonregular external actor link DB")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _deny("hardlinked external actor DB forbidden")
        if info.st_size > 16 * 1024 * 1024:
            _deny("oversized external actor DB")
    return path


def _registered_query(registry, original, query):
    path = registry.path
    _directory(path.parent)
    if (not path.is_file() or path.is_symlink()
            or getattr(path, "is_junction", lambda: False)()):
        _deny("trusted peer query registry unavailable")
    uri = "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
                _deny("trusted peer query schema changed")
            rows = conn.execute(
                "SELECT org,original_id,original_sha,query_sha,actor_role "
                "FROM queries WHERE query_id=?", (query["requestId"],),
            ).fetchall()
            expected = (
                registry.config.organization_id, original["requestId"],
                original["payloadSha256"], query["payloadSha256"],
                original["actorRole"],
            )
            if len(rows) != 1 or tuple(rows[0]) != expected:
                _deny("Madar query not present in trusted peer registry")
        finally:
            if conn.in_transaction:
                conn.execute("ROLLBACK")


class ManualExternalActorLinks:
    """Private, one-time admin-approved request -> local finance operator link."""

    def __init__(self, *, accounting_host: AccountingDesktopAPI,
                 peer_registry: TarazPeerRegistry, trusted_config: PeerConfig,
                 reviewed_root: Path, link_db_path: Path):
        if (type(accounting_host) is not AccountingDesktopAPI
                or type(peer_registry) is not TarazPeerRegistry
                or type(trusted_config) is not PeerConfig
                or peer_registry.config is not trusted_config):
            _deny("actual company host and trusted peer objects required")
        self._host = accounting_host
        self._registry = peer_registry
        self._config = trusted_config
        self._reviewed = _directory(reviewed_root)
        self.path = _safe_db(link_db_path)
        accounting_dir = Path(accounting_host.path).parent
        if (self._reviewed != _directory(bridge_root())
                or self.path.parent.is_relative_to(accounting_dir)
                or self.path.parent.is_relative_to(self._reviewed)
                or accounting_dir.is_relative_to(self.path.parent)
                or self._reviewed.is_relative_to(self.path.parent)
                or self.path == peer_registry.path):
            _deny("private link journal must be independent of ledger/bridge/peer")
        self._lock = RLock()
        new = not self.path.exists()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if new and version == 0:
                    conn.execute(
                        "CREATE TABLE links ("
                        "request_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL,"
                        "company_id TEXT NOT NULL, operator TEXT NOT NULL,"
                        "operator_role TEXT NOT NULL, admin TEXT NOT NULL,"
                        "organization TEXT NOT NULL, sender TEXT NOT NULL,"
                        "key_id TEXT NOT NULL, taraz_key_id TEXT NOT NULL,"
                        "original_wire_sha TEXT NOT NULL, query_id TEXT NOT NULL,"
                        "query_wire_sha TEXT NOT NULL, task_id TEXT NOT NULL,"
                        "project_id TEXT NOT NULL, source_digest TEXT NOT NULL,"
                        "expires_utc TEXT NOT NULL, status TEXT NOT NULL"
                        " CHECK(status IN ('pending','revoked','consumed')))"
                    )
                    conn.execute(
                        "CREATE TRIGGER links_no_delete BEFORE DELETE ON links "
                        "BEGIN SELECT RAISE(ABORT,'immutable'); END"
                    )
                    conn.execute(
                        "CREATE TRIGGER links_immutable_fields BEFORE UPDATE ON links "
                        "WHEN NEW.request_id!=OLD.request_id OR NEW.actor_id!=OLD.actor_id "
                        "OR NEW.company_id!=OLD.company_id OR NEW.operator!=OLD.operator "
                        "OR NEW.operator_role!=OLD.operator_role OR NEW.admin!=OLD.admin "
                        "OR NEW.organization!=OLD.organization OR NEW.sender!=OLD.sender "
                        "OR NEW.key_id!=OLD.key_id OR NEW.taraz_key_id!=OLD.taraz_key_id "
                        "OR NEW.original_wire_sha!=OLD.original_wire_sha "
                        "OR NEW.query_id!=OLD.query_id OR NEW.query_wire_sha!=OLD.query_wire_sha "
                        "OR NEW.task_id!=OLD.task_id OR NEW.project_id!=OLD.project_id "
                        "OR NEW.source_digest!=OLD.source_digest "
                        "OR NEW.expires_utc!=OLD.expires_utc "
                        "OR OLD.status!='pending' OR NEW.status='pending' "
                        "BEGIN SELECT RAISE(ABORT,'immutable'); END"
                    )
                    conn.execute("PRAGMA user_version=1")
                elif version != _SCHEMA:
                    _deny("unsupported external actor link schema")
                if (conn.execute("PRAGMA quick_check(1)").fetchone() != ("ok",)
                        or conn.execute(
                            "SELECT type FROM sqlite_master WHERE name='links'"
                        ).fetchone() != ("table",)):
                    _deny("corrupt or missing external actor link table")
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _connect(self):
        from contextlib import contextmanager

        @contextmanager
        def connect():
            _safe_db(self.path)
            conn = sqlite3.connect(self.path, isolation_level=None, timeout=5)
            try:
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("PRAGMA synchronous=FULL")
                yield conn
            finally:
                conn.close()

        return connect()

    def _verified_context(self, *, signed_madar_original: bytes,
                          signed_madar_query_challenge: bytes,
                          company_id: str, administrator_token: str,
                          now: datetime | None):
        stamp = _trusted_now(now)
        if (type(company_id) is not str or not _HEX32.fullmatch(company_id)
                or type(administrator_token) is not str or not administrator_token):
            _deny("company and current administrator session required")
        if (self._registry.config is not self._config
                or self._reviewed != _directory(bridge_root())):
            _deny("trusted peer or reviewed source changed")
        identity = _safe_company(self._host, company_id)
        _principal(self._host, identity)
        operator = identity.require_session(self._host._identity_token, "editor")
        administrator = identity.require_session(administrator_token, "admin")
        if (operator["username"] != self._host._actor
                or operator["role"] not in ("editor", "admin")
                or administrator["role"] != "admin"):
            _deny("current local operator or administrator invalid")
        original = _verify(
            signed_madar_original, config=self._config, now=stamp,
            expected_kind="request", purpose="finance_review_request",
        )
        query = _verify(
            signed_madar_query_challenge, config=self._config, now=stamp,
            expected_kind="query", purpose="receipt_lookup",
        )
        if (original["actorRole"] != operator["role"]
                or original["actorRole"] not in ("editor", "admin")
                or query["requestId"] == original["requestId"]
                or query["organizationId"] != original["organizationId"]
                or query["senderId"] != original["senderId"]
                or query["keyId"] != original["keyId"]
                or query["actorRole"] != original["actorRole"]
                or query["payload"]["originalRequestId"] != original["requestId"]
                or query["payload"]["originalPayloadSha256"] != original["payloadSha256"]):
            _deny("signed request/query/role mismatch")
        requested = original["payload"]
        if type(requested) is not dict or set(requested) != _SIGNED_BINDING:
            _deny("exact signed financial binding required")
        actor = requested["actorId"]
        if (type(actor) is not str or not _EXTERNAL_ACTOR.fullmatch(actor)
                or requested["id"] != original["requestId"]
                or requested["companyId"] != company_id):
            _deny("wrong company or invalid external actor ID")
        raw, _, source, review = _read_review(self._reviewed, original["requestId"])
        if (review["state"] != "reviewed"
                or requested["taskId"] != source["taskId"]
                or requested["projectId"] != source["projectId"]
                or requested["sourceDigest"] != hashlib.sha256(raw).hexdigest()):
            _deny("independent durable source differs from signed request")
        amount = source.get("amountRial")
        if (type(amount) is not str or not amount.isascii()
                or not amount.isdecimal() or not 1 <= len(amount) <= 16
                or not 0 < int(amount) <= 9007199254740991):
            _deny("durable source has no eligible exact finance amount")
        _registry_original_binding(self._registry, original)
        _registered_query(self._registry, original, query)
        return stamp, original, query, requested, operator, administrator

    def _record(self, *, signed_madar_original, signed_madar_query_challenge,
                company_id, administrator_token, now):
        stamp, original, query, requested, operator, admin = self._verified_context(
            signed_madar_original=signed_madar_original,
            signed_madar_query_challenge=signed_madar_query_challenge,
            company_id=company_id, administrator_token=administrator_token, now=now,
        )
        return stamp, (
            original["requestId"], requested["actorId"], company_id,
            operator["username"], operator["role"], admin["username"],
            self._config.organization_id, self._config.madar_sender_id,
            self._config.madar_key_id, self._config.taraz_key_id,
            hashlib.sha256(signed_madar_original).hexdigest(), query["requestId"],
            hashlib.sha256(signed_madar_query_challenge).hexdigest(),
            requested["taskId"], requested["projectId"], requested["sourceDigest"],
        ), original, query

    def authorize_manual(self, *, signed_madar_original: bytes,
                         signed_madar_query_challenge: bytes,
                         company_id: str, administrator_token: str,
                         explicit_manual_action: bool, now: datetime | None = None):
        """Admin grants this one signed actor/request to the live Taraz operator."""
        if explicit_manual_action is not True:
            _deny("manual administrator authorization required")
        with self._lock, self._host._lock:
            stamp, binding, original, query = self._record(
                signed_madar_original=signed_madar_original,
                signed_madar_query_challenge=signed_madar_query_challenge,
                company_id=company_id, administrator_token=administrator_token,
                now=now,
            )
            expires = min(
                stamp + _TTL,
                datetime.strptime(original["expiresUtc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc),
                datetime.strptime(query["expiresUtc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc),
            )
            if expires <= stamp:
                _deny("signed external actor admission expired")
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(
                        "INSERT INTO links VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (*binding, expires.isoformat(), "pending"),
                    )
                    conn.commit()
                except sqlite3.IntegrityError as exc:
                    conn.rollback()
                    raise ExternalActorLinkDenied(
                        "external actor request already admitted, used or revoked"
                    ) from exc
                except Exception:
                    conn.rollback()
                    raise
        return {
            "schemaVersion": 1, "decision": "EXTERNAL_ACTOR_LINK_ADMITTED_ONCE",
            "madarRequestId": binding[0], "companyId": binding[2],
            "tarazOperator": binding[3], "expiresUtc": expires.isoformat(),
            "independentlyAuthenticatedMadarActorVerified": False,
            "trustedMadarInvoiceBindingVerified": False,
            "officialFinanceReceiptVerified": False,
        }

    def _evaluate(self, *, signed_madar_original, signed_madar_query_challenge,
                  company_id, administrator_token, now, consume):
        stamp, binding, _, _ = self._record(
            signed_madar_original=signed_madar_original,
            signed_madar_query_challenge=signed_madar_query_challenge,
            company_id=company_id, administrator_token=administrator_token,
            now=now,
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE" if consume else "BEGIN")
            try:
                row = conn.execute(
                    "SELECT actor_id,company_id,operator,operator_role,admin,"
                    "organization,sender,key_id,taraz_key_id,original_wire_sha,"
                    "query_id,query_wire_sha,task_id,project_id,source_digest,"
                    "expires_utc,status FROM links WHERE request_id=?",
                    (binding[0],),
                ).fetchall()
                if (len(row) != 1 or tuple(row[0][:15]) != binding[1:]
                        or row[0][16] != "pending"
                        or datetime.fromisoformat(row[0][15]) <= stamp):
                    _deny("external actor admission missing, changed, expired or consumed")
                if consume:
                    updated = conn.execute(
                        "UPDATE links SET status='consumed' WHERE request_id=? AND status='pending'",
                        (binding[0],),
                    )
                    if updated.rowcount != 1:
                        _deny("external actor admission already consumed")
                    conn.commit()
                else:
                    conn.execute("ROLLBACK")
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
        return True

    def verify_pending(self, *, signed_madar_original: bytes,
                       signed_madar_query_challenge: bytes,
                       company_id: str, administrator_token: str,
                       now: datetime | None = None):
        with self._lock, self._host._lock:
            return self._evaluate(
                signed_madar_original=signed_madar_original,
                signed_madar_query_challenge=signed_madar_query_challenge,
                company_id=company_id, administrator_token=administrator_token,
                now=now, consume=False,
            )

    def consume_manual(self, *, signed_madar_original: bytes,
                       signed_madar_query_challenge: bytes,
                       company_id: str, administrator_token: str,
                       explicit_manual_action: bool, now: datetime | None = None):
        if explicit_manual_action is not True:
            _deny("explicit one-time operator action required")
        with self._lock, self._host._lock:
            return self._evaluate(
                signed_madar_original=signed_madar_original,
                signed_madar_query_challenge=signed_madar_query_challenge,
                company_id=company_id, administrator_token=administrator_token,
                now=now, consume=True,
            )

    def revoke_manual(self, *, madar_request_id: str, company_id: str,
                      administrator_token: str, explicit_manual_action: bool):
        if explicit_manual_action is not True:
            _deny("explicit administrator revocation required")
        if (type(madar_request_id) is not str or not _HEX32.fullmatch(madar_request_id)
                or type(company_id) is not str or not _HEX32.fullmatch(company_id)):
            _deny("invalid revocation identifiers")
        with self._lock, self._host._lock:
            identity = _safe_company(self._host, company_id)
            _principal(self._host, identity)
            admin = identity.require_session(administrator_token, "admin")
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    row = conn.execute(
                        "SELECT company_id,admin,status FROM links WHERE request_id=?",
                        (madar_request_id,),
                    ).fetchone()
                    if (row is None or row != (company_id, admin["username"], "pending")):
                        _deny("pending admission not owned by this administrator/company")
                    conn.execute(
                        "UPDATE links SET status='revoked' WHERE request_id=? AND status='pending'",
                        (madar_request_id,),
                    )
                    conn.commit()
                except Exception:
                    if conn.in_transaction:
                        conn.rollback()
                    raise
        return {"schemaVersion": 1, "decision": "EXTERNAL_ACTOR_LINK_REVOKED"}


__all__ = ("ManualExternalActorLinks", "ExternalActorLinkDenied")
