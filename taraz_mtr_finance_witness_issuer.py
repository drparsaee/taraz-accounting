"""Manual, source-only Taraz finance journal witness issuer (QA contract).

Independent registered-company accounting replay, current editor and Taraz
administrator sessions, real Madar v2 HMAC, durable reviewed source and a
separately authorized external-actor admission are mandatory. This produces
evidence of an existing journal, not accounting commands or an official receipt.

The operator provisions the finance-direction key out of band. A private
create-only reservation is COMMITTED BEFORE any HMAC bytes are returned.
After an ambiguous crash a challenge is burnt; it cannot be recovered by
retrying. Never auto-provision, queue, transmit or install this source module.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import sqlite3
import stat
from threading import RLock
from types import SimpleNamespace
from urllib.parse import quote

from accounting_core import accounting_view
from standalone_accounting import StandaloneAccountingStore, _canonical
from standalone_accounting_desktop import AccountingDesktopAPI
from taraz_desktop import bridge_root
from taraz_mtr_external_actor_link import ManualExternalActorLinks
from taraz_mtr_official_receipt_gate import (
    _principal, _safe_company, assess_official_receipt,
)
from taraz_mtr_peer_registry import (
    PeerConfig, TarazPeerRegistry, _canonical as peer_canonical,
    _verify as verify_peer,
)
from taraz_mtr_review_attestation_issuer import (
    _directory, _read_review, _registry_original_binding,
)

_DOMAIN = b"MTR-Taraz-finance-journal-witness-v1\x00"
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_HEX32 = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
_ACTOR = re.compile(r"mtr-actor-v1-[0-9a-f]{64}\Z", re.ASCII)
_ORIGINAL_FIELDS = frozenset({
    "id", "taskId", "projectId", "sourceDigest", "companyId", "actorId",
    "invoiceId", "issueEventId", "journalId",
})
_SOURCE_FIELDS = frozenset({
    "schema", "source", "id", "taskId", "projectId", "title",
    "createdUtc", "expenseId", "amountRial",
})
_WITNESS_FIELDS = frozenset({
    "protocol", "version", "algorithm", "purpose", "audience",
    "organizationId", "issuerId", "keyId", "requestId",
    "originalWireSha256", "originalPayloadSha256", "queryRequestId",
    "queryWireSha256", "sourceDigest", "taskId", "projectId",
    "madarActorId", "companyId", "invoiceId", "issueEventId",
    "journalId", "currency", "amountRial", "ledgerRevision",
    "ledgerStateSha256", "journalEventSha256", "accountingEventSha256",
    "journalEventType", "journalStatus", "issuedUtc", "expiresUtc",
})
_MAX_JOURNAL = 16384
_MAX_STATE = 15_000_000
_MAX_DB = 8 * 1024 * 1024
_MAX_CLAIMS = 10000


class FinanceWitnessIssueDenied(PermissionError):
    """No live, manual, single-use authenticated journal witness available."""


def _deny(message: str):
    raise FinanceWitnessIssueDenied(message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _clock(value: datetime | None):
    actual = datetime.now(timezone.utc)
    if value is None:
        return actual.replace(microsecond=0)
    if (type(value) is not datetime or value.tzinfo is None
            or value.utcoffset() is None or value.microsecond):
        _deny("explicit second-precision UTC time required")
    stamp = value.astimezone(timezone.utc)
    if abs((stamp - actual).total_seconds()) > 5:
        _deny("provided witness time not from trusted clock")
    return stamp


def _stamp(value: str) -> datetime:
    if (type(value) is not str or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value)):
        _deny("invalid peer UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError as exc:
        raise FinanceWitnessIssueDenied("invalid peer UTC calendar date") from exc


@dataclass(frozen=True, slots=True, repr=False)
class FinanceIssuerTrust:
    """Independent out-of-band finance-direction HMAC credentials."""
    organization_id: str
    finance_issuer_id: str
    finance_key_id: str
    finance_secret: bytes

    def __post_init__(self):
        for value in (self.organization_id, self.finance_issuer_id,
                      self.finance_key_id):
            if type(value) is not str or not _TOKEN.fullmatch(value):
                _deny("invalid independently provisioned finance issuer identity")
        if (type(self.finance_secret) is not bytes
                or not 32 <= len(self.finance_secret) <= 4096):
            _deny("finance-direction secret must be 32+ bytes")

    def __repr__(self):
        return "<FinanceIssuerTrust secret redacted>"

    def __reduce__(self):
        raise TypeError("private finance issuer trust cannot be serialized")


@dataclass(frozen=True, slots=True)
class IssuedFinanceWitness:
    signed_witness: bytes
    original_wire: bytes
    query_wire: bytes
    source_raw: bytes
    journal_raw: bytes
    accounting_event_raw: bytes
    ledger_revision: int
    ledger_state_sha256: str
    officialFinanceReceiptVerified: bool = False
    financialEventCreatedByIssuer: bool = False
    safeToRetryFinancialPosting: bool = False


def _safe_issuance_path(path: Path):
    if (not isinstance(path, Path) or not path.is_absolute()
            or path.name != "mtr-taraz-finance-witness-issued.sqlite3"):
        _deny("explicit private finance witness issuance DB required")
    for parent in (path.parent, *path.parent.parents):
        try:
            info = parent.lstat()
        except (OSError, ValueError) as exc:
            raise FinanceWitnessIssueDenied("missing private issuer directory") from exc
        if (not stat.S_ISDIR(info.st_mode) or parent.is_symlink()
                or getattr(parent, "is_junction", lambda: False)()
                or (getattr(info, "st_file_attributes", 0) &
                    getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))):
            _deny("linked/reparse private issuer directory rejected")
    if os.path.lexists(path):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or path.is_symlink() or info.st_size > _MAX_DB
                or (getattr(info, "st_file_attributes", 0) &
                    getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))):
            _deny("unsafe existing finance witness database")
    return path


class DurableFinanceWitnessIssuance:
    """Never releases an ambiguous/crashed original or one-time query ID."""

    def __init__(self, path: Path):
        self.path = _safe_issuance_path(path)
        self._lock = RLock()
        fresh = not path.exists()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if fresh and db.execute("PRAGMA user_version").fetchone()[0] == 0:
                    db.execute(
                        "CREATE TABLE claims ("
                        "original_id TEXT PRIMARY KEY,"
                        "query_id TEXT NOT NULL UNIQUE,"
                        "original_sha TEXT NOT NULL,"
                        "query_sha TEXT NOT NULL,"
                        "company_id TEXT NOT NULL,"
                        "ledger_sha TEXT NOT NULL,"
                        "revision INTEGER NOT NULL,"
                        "witness_sha TEXT NOT NULL,"
                        "reserved_utc TEXT NOT NULL)"
                    )
                    db.execute(
                        "CREATE TRIGGER claims_no_update BEFORE UPDATE ON claims "
                        "BEGIN SELECT RAISE(ABORT,'immutable'); END"
                    )
                    db.execute(
                        "CREATE TRIGGER claims_no_delete BEFORE DELETE ON claims "
                        "BEGIN SELECT RAISE(ABORT,'immutable'); END"
                    )
                    db.execute("PRAGMA user_version=1")
                if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                    _deny("unsupported issuance schema")
                kinds = dict(db.execute(
                    "SELECT name,type FROM sqlite_master WHERE name IN "
                    "('claims','claims_no_update','claims_no_delete')"
                ).fetchall())
                if kinds != {
                    "claims": "table",
                    "claims_no_update": "trigger",
                    "claims_no_delete": "trigger",
                } or db.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                    _deny("issuance schema/triggers/integrity invalid")
                db.execute("COMMIT")
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    @contextmanager
    def _connect(self):
        _safe_issuance_path(self.path)
        db = sqlite3.connect(self.path, timeout=8, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA busy_timeout=8000")
            yield db
        finally:
            db.close()

    def reserve_once(self, *, request_id: str, query_id: str,
                     original_sha: str, query_sha: str, company_id: str,
                     ledger_sha: str, revision: int,
                     witness_sha: str, now: datetime):
        for token in (request_id, query_id, company_id):
            if type(token) is not str or not _HEX32.fullmatch(token):
                _deny("invalid immutable issuance identifier")
        for token in (original_sha, query_sha, ledger_sha, witness_sha):
            if type(token) is not str or not _SHA.fullmatch(token):
                _deny("invalid immutable issuance digest")
        if type(revision) is not int or revision < 1:
            _deny("invalid positive journal revision")
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] >= _MAX_CLAIMS:
                    _deny("issuance registry full, no pruning/replay")
                db.execute(
                    "INSERT INTO claims VALUES(?,?,?,?,?,?,?,?,?)",
                    (request_id, query_id, original_sha, query_sha, company_id,
                     ledger_sha, revision, witness_sha, now.isoformat()),
                )
                db.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise FinanceWitnessIssueDenied(
                    "original or challenge already reserved, no issuance retry"
                ) from exc
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise


def _read_accounting(host, accounts, payload: dict, amount: int,
                     expected_revision: int):
    """Independent read-only transaction with canonical digest/replay validation."""
    db_path = Path(host.path)
    if (not db_path.is_file() or db_path.is_symlink()
            or getattr(db_path, "is_junction", lambda: False)()):
        _deny("registered-company accounting source missing/linked")
    uri = "file:" + quote(db_path.as_posix(), safe="/:") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5,
                                 isolation_level=None)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        try:
            if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                _deny("independent accounting schema mismatch")
            tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'")
            }
            if tables != {"standalone_accounting"}:
                _deny("foreign accounting table detected")
            revision, state = StandaloneAccountingStore._current(
                SimpleNamespace(default_currency="RIAL"), db)
            if (revision != expected_revision or revision != len(state["events"])
                    or not 1 <= revision <= 9007199254740991):
                _deny("journal revision stale or inconsistent")
            canonical_state = _canonical(state)
            if len(canonical_state) > _MAX_STATE:
                _deny("accounting state too large")
            view = accounting_view(state, actor=host._actor, accounts=accounts)
            invoice = view.get("invoices", {}).get(payload["invoiceId"])
            if (view.get("currency") != "RIAL" or type(invoice) is not dict
                    or invoice.get("status") != "issued"
                    or invoice.get("sourceType") != "madar"
                    or invoice.get("sourceId") != payload["id"]
                    or invoice.get("postedEntryId") != payload["journalId"]
                    or type(invoice.get("total")) is not int
                    or invoice["total"] != amount):
                _deny("invoice state/amount/currency/source not issued as signed")
            duplicates = [
                i for i in view.get("invoices", {}).values()
                if type(i) is dict and i.get("sourceType") == "madar"
                and i.get("sourceId") == payload["id"]
            ]
            if len(duplicates) != 1:
                _deny("duplicate/ambiguous signed invoice source")
            if payload["journalId"] in view.get("reversed", {}):
                _deny("reversed journal cannot be witnessed")
            journals = [
                j for j in view.get("journals", []) if type(j) is dict
                and j.get("id") == payload["journalId"]
            ]
            events = [
                e for e in state["events"] if type(e) is dict
                and e.get("eventId") == payload["issueEventId"]
            ]
            if len(journals) != 1 or len(events) != 1:
                _deny("journal/event missing or ambiguous")
            journal, event = journals[0], events[0]
            if (journal.get("eventId") != payload["issueEventId"]
                    or journal.get("sourceType") != "invoice.issue"
                    or journal.get("sourceId") != payload["invoiceId"]
                    or journal.get("reversalOf") is not None
                    or event.get("actor") != host._actor
                    or type(event.get("command")) is not dict
                    or event["command"].get("type") != "invoice.issue"
                    or event["command"].get("invoiceId") != payload["invoiceId"]
                    or event["command"].get("eventId") != payload["issueEventId"]
                    or event["command"].get("postingDate") != journal.get("date")
                    or type(event.get("result")) is not dict
                    or event["result"].get("documentId") != payload["invoiceId"]
                    or event["result"].get("journalId") != payload["journalId"]
                    or type(event["result"].get("total")) is not int
                    or event["result"]["total"] != amount):
                _deny("persisted issue event differs from signed invoice")
            lines = journal.get("lines")
            if type(lines) is not list or not 2 <= len(lines) <= 128:
                _deny("journal line count unsupported")
            dr = cr = 0
            for row in lines:
                if (type(row) is not dict or not {
                        "accountId", "debit", "credit"} <= set(row)
                        or set(row) - {
                            "accountId", "debit", "credit", "partyId"}
                        or type(row["debit"]) is not int
                        or type(row["credit"]) is not int
                        or (row["debit"] > 0) == (row["credit"] > 0)):
                    _deny("invalid persisted journal row")
                dr += row["debit"]
                cr += row["credit"]
            if dr != cr or dr < amount:
                _deny("unbalanced or underfunded issue")
            journal_raw = peer_canonical(journal)
            event_raw = peer_canonical(event)
            if len(journal_raw) > _MAX_JOURNAL or len(event_raw) > _MAX_JOURNAL:
                _deny("oversized journal/event evidence")
            return (
                revision, _sha(canonical_state), journal_raw, event_raw,
            )
        finally:
            if db.in_transaction:
                db.execute("ROLLBACK")


class ManualTarazFinanceWitnessIssuer:
    """Manual attestation of an ALREADY issued finance journal, source-only."""

    def __init__(self, *, accounting_host: AccountingDesktopAPI,
                 peer_registry: TarazPeerRegistry, trusted_config: PeerConfig,
                 finance_trust: FinanceIssuerTrust,
                 external_actor_links: ManualExternalActorLinks,
                 reviewed_root: Path,
                 issued_db_path: Path):
        if (type(accounting_host) is not AccountingDesktopAPI
                or type(peer_registry) is not TarazPeerRegistry
                or type(trusted_config) is not PeerConfig
                or type(finance_trust) is not FinanceIssuerTrust
                or type(external_actor_links) is not ManualExternalActorLinks
                or peer_registry.config is not trusted_config
                or external_actor_links._host is not accounting_host
                or external_actor_links._registry is not peer_registry
                or external_actor_links._config is not trusted_config):
            _deny("actual company, operator external-link and live peer objects required")
        if (finance_trust.organization_id != trusted_config.organization_id
                or any(hmac.compare_digest(finance_trust.finance_secret, key)
                       for key in (
                           trusted_config.madar_secret, trusted_config.taraz_secret))):
            _deny("independent finance-direction key and same organization required")
        self._host = accounting_host
        self._registry = peer_registry
        self._config = trusted_config
        self._trust = finance_trust
        self._links = external_actor_links
        self._reviewed = _directory(reviewed_root)
        self._issued = DurableFinanceWitnessIssuance(issued_db_path)
        accounting_folder = Path(accounting_host.path).parent
        if (self._reviewed != _directory(bridge_root())
                or external_actor_links._reviewed != self._reviewed
                or self._issued.path.parent.is_relative_to(accounting_folder)
                or self._issued.path.parent.is_relative_to(self._reviewed)
                or self._issued.path.parent == peer_registry.path.parent
                or self._issued.path.parent == external_actor_links.path.parent
                or self._reviewed.is_relative_to(self._issued.path.parent)
                or accounting_folder.is_relative_to(self._issued.path.parent)):
            _deny("issuance journal must be independent and privately provisioned")
        self._lock = RLock()

    def issue_manual(self, *, signed_madar_original: bytes,
                     signed_madar_query_challenge: bytes,
                     company_id: str, administrator_token: str,
                     expected_revision: int, explicit_manual_action: bool,
                     now: datetime | None = None) -> IssuedFinanceWitness:
        if explicit_manual_action is not True:
            _deny("explicit manual operator action required")
        if (type(company_id) is not str or not _HEX32.fullmatch(company_id)
                or type(administrator_token) is not str or not administrator_token
                or type(expected_revision) is not int or expected_revision < 1):
            _deny("company, administrator and exact ledger revision required")
        stamp = _clock(now)
        with self._lock, self._host._lock:
            identity = _safe_company(self._host, company_id)
            accounts = _principal(self._host, identity)
            editor = identity.require_session(self._host._identity_token, "editor")
            admin = identity.require_session(administrator_token, "admin")
            if (editor["username"] != self._host._actor
                    or editor["role"] not in ("admin", "editor")
                    or admin["role"] != "admin"
                    or self._registry.config is not self._config):
                _deny("current operator/admin/peer security context changed")
            original = verify_peer(
                signed_madar_original, config=self._config, now=stamp,
                expected_kind="request", purpose="finance_review_request")
            query = verify_peer(
                signed_madar_query_challenge, config=self._config, now=stamp,
                expected_kind="query", purpose="receipt_lookup")
            payload = original["payload"]
            if (type(payload) is not dict
                    or set(payload) != _ORIGINAL_FIELDS
                    or original["actorRole"] != editor["role"]
                    or query["actorRole"] != original["actorRole"]
                    or query["organizationId"] != original["organizationId"]
                    or query["senderId"] != original["senderId"]
                    or query["keyId"] != original["keyId"]
                    or query["payload"] != {
                        "originalRequestId": original["requestId"],
                        "originalPayloadSha256": original["payloadSha256"],
                        "originalPurpose": "finance_review_request"}
                    or query["requestId"] == original["requestId"]
                    or payload["id"] != original["requestId"]
                    or payload["companyId"] != company_id
                    or type(payload["actorId"]) is not str
                    or not _ACTOR.fullmatch(payload["actorId"])):
                _deny("Madar signed external principal/request/query mismatch")
            from taraz_mtr_external_actor_link import _registered_query
            _registry_original_binding(self._registry, original)
            _registered_query(self._registry, original, query)
            source_raw, review_raw, source, review = _read_review(
                self._reviewed, original["requestId"])
            if (review["state"] != "reviewed"
                    or set(source) != _SOURCE_FIELDS
                    or source.get("expenseId") is None
                    or type(source["expenseId"]) is not str
                    or not 1 <= len(source["expenseId"]) <= 180
                    or payload["taskId"] != source["taskId"]
                    or payload["projectId"] != source["projectId"]
                    or payload["sourceDigest"] != _sha(source_raw)
                    or type(source["amountRial"]) is not str
                    or not source["amountRial"].isascii()
                    or not source["amountRial"].isdecimal()
                    or len(source["amountRial"]) > 16
                    or source["amountRial"].startswith("0")
                    or not 0 < int(source["amountRial"]) <= 9007199254740991):
                _deny("durable source/review/digest/RIAL amount mismatch")
            amount = int(source["amountRial"])
            self._links.verify_pending(
                signed_madar_original=signed_madar_original,
                signed_madar_query_challenge=signed_madar_query_challenge,
                company_id=company_id, administrator_token=administrator_token,
                now=stamp)
            revision, state_sha, journal_raw, event_raw = _read_accounting(
                self._host, accounts, payload, amount, expected_revision)
            inspection = assess_official_receipt(
                host=self._host, company_id=company_id,
                madar_request_id=original["requestId"],
                invoice_id=payload["invoiceId"],
                issue_event_id=payload["issueEventId"],
                journal_id=payload["journalId"], expected_revision=revision,
                review_marker=review)
            if inspection["decision"] != "PERSISTED_INVOICE_JOURNAL_OBSERVED_UNBOUND":
                _deny("independent journal assessment denied: " +
                      inspection["decision"])
            issued_at = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
            expiry = min(
                stamp + timedelta(seconds=60),
                _stamp(query["expiresUtc"]),
            )
            if (expiry <= stamp
                    or stamp < _stamp(query["issuedUtc"])
                    or expiry > _stamp(original["expiresUtc"])):
                _deny("witness outside authenticated query lifetime")
            body = {
                "protocol": "mtr-taraz-journal-witness",
                "version": 1, "algorithm": "HMAC-SHA256",
                "purpose": "invoice-issue-readback",
                "audience": "madar.finance",
                "organizationId": self._trust.organization_id,
                "issuerId": self._trust.finance_issuer_id,
                "keyId": self._trust.finance_key_id,
                "requestId": original["requestId"],
                "originalWireSha256": _sha(signed_madar_original),
                "originalPayloadSha256": original["payloadSha256"],
                "queryRequestId": query["requestId"],
                "queryWireSha256": _sha(signed_madar_query_challenge),
                "sourceDigest": payload["sourceDigest"],
                "taskId": payload["taskId"],
                "projectId": payload["projectId"],
                "madarActorId": payload["actorId"],
                "companyId": company_id,
                "invoiceId": payload["invoiceId"],
                "issueEventId": payload["issueEventId"],
                "journalId": payload["journalId"],
                "currency": "RIAL", "amountRial": str(amount),
                "ledgerRevision": revision,
                "ledgerStateSha256": state_sha,
                "journalEventSha256": _sha(journal_raw),
                "accountingEventSha256": _sha(event_raw),
                "journalEventType": "invoice.issue", "journalStatus": "posted",
                "issuedUtc": issued_at,
                "expiresUtc": expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            if set(body) != _WITNESS_FIELDS:
                _deny("finance witness schema mismatch")
            # Canonical wire HMAC is not revealed until the durable claim and
            # external actor admission have BOTH been consumed. A crash stops
            # issuance, even if no bytes reached the external verifier.
            mac = hmac.new(self._trust.finance_secret,
                           _DOMAIN + peer_canonical(body),
                           hashlib.sha256).hexdigest()
            wire = peer_canonical({**body, "mac": mac})
            if len(wire) > 16384:
                _deny("oversized finance witness wire")
            self._issued.reserve_once(
                request_id=original["requestId"], query_id=query["requestId"],
                original_sha=_sha(signed_madar_original),
                query_sha=_sha(signed_madar_query_challenge),
                company_id=company_id, ledger_sha=state_sha,
                revision=revision, witness_sha=_sha(wire), now=stamp)
            self._links.consume_manual(
                signed_madar_original=signed_madar_original,
                signed_madar_query_challenge=signed_madar_query_challenge,
                company_id=company_id, administrator_token=administrator_token,
                explicit_manual_action=True, now=stamp)
            _principal(self._host, identity)
            identity.require_session(administrator_token, "admin")
            if (_read_review(self._reviewed, original["requestId"])[:2]
                    != (source_raw, review_raw)):
                _deny("review changed after witness reserved")
            if (_read_accounting(
                    self._host, _principal(self._host, identity), payload,
                    amount, revision) !=
                    (revision, state_sha, journal_raw, event_raw)):
                _deny("accounting changed after witness reservation")
            return IssuedFinanceWitness(
                signed_witness=wire, original_wire=signed_madar_original,
                query_wire=signed_madar_query_challenge, source_raw=source_raw,
                journal_raw=journal_raw, accounting_event_raw=event_raw,
                ledger_revision=revision, ledger_state_sha256=state_sha)


__all__ = (
    "ManualTarazFinanceWitnessIssuer",
    "FinanceIssuerTrust", "FinanceWitnessIssueDenied",
    "IssuedFinanceWitness", "DurableFinanceWitnessIssuance",
)
