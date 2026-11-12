"""Fail-closed, manual-only NONFINANCIAL Madar review attestation issuer.

Not integrated into Taraz's installed GUI/server. A host operator must inject
the LIVE TarazAPI with a genuinely authenticated company session, trusted
in-process TarazPeerRegistry/PeerConfig (keys never from a request), a selected
local reviewed-metadata root, and a durable one-time issuer journal.

The challenge is the requestId of an independently HMAC-verified Madar v2
receipt_lookup *query*, referencing an already accepted, signed Madar original
request whose payload binds SHA-256 of the EXACT local reviewed proposal.
This is a bounded, opt-in use of an existing Madar-issued query; a bare nonce
or local JSON cannot authorize signing. The response wire matches
mtr_taraz_peer_identity.make_peer_review_attestation byte-for-byte.

No invoices, finance receipt, ledger, network, background task, retry,
transport, secrets-on-disk, or official Taraz posting authority are created.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from threading import RLock
from urllib.parse import quote

import taraz_integration as integration
from standalone_accounting_identity import LocalCompanyIdentity
from taraz_desktop import TarazAPI, bridge_root
from taraz_mtr_peer_registry import (
    PeerConfig, TarazPeerRegistry, _verify as verify_madar_v2,
)

_HEX32 = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
_DOMAIN = b"MTR-Taraz-peer-review-v1\x00"
_PROPOSAL_FIELDS = frozenset({
    "schema", "source", "id", "taskId", "projectId", "title", "createdUtc",
})
_REVIEW_FIELDS = frozenset({
    "schema", "source", "id", "taskId", "state", "reviewedUtc",
    "financialEventCreated",
})
_INTENT_FIELDS = _REVIEW_FIELDS | {"sourceDigest"}
_ORIGINAL_BINDING = frozenset({"id", "taskId", "projectId", "sourceDigest"})
_USED_PREFIX = "review-challenge-"
MAX_ATTESTATION_BYTES = 4096


class ReviewAttestationDenied(PermissionError):
    """No authenticated peer review proof was issued."""


def _deny(message: str):
    raise ReviewAttestationDenied(message)


def _strict_json(raw: bytes, *, maximum: int):
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        _deny("missing or oversized durable review record")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _deny("duplicate durable JSON field")
            result[key] = value
        return result

    def reject_constant(_):
        _deny("nonfinite JSON field")

    try:
        value = json.loads(raw.decode("utf8"), object_pairs_hook=unique,
                           parse_constant=reject_constant)
    except (UnicodeError, TypeError, ValueError, RecursionError) as exc:
        raise ReviewAttestationDenied("malformed durable JSON") from exc
    if type(value) is not dict:
        _deny("durable record must be an object")
    return value


def _canonical(record):
    if type(record) is not dict:
        _deny("proof must contain an object")
    try:
        return json.dumps(record, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf8")
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ReviewAttestationDenied("noncanonical proof payload") from exc


def _utc(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _deny("trusted current UTC time required")
    result = value.astimezone(timezone.utc)
    if result.microsecond:
        _deny("second-precision UTC required")
    return result


def _parse_review_time(value):
    if type(value) is not str or not 1 <= len(value) <= 50:
        _deny("invalid durable review time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewAttestationDenied("invalid durable review time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        _deny("durable review timestamp must be UTC")
    return parsed.astimezone(timezone.utc)


def _directory(path: Path):
    if (not isinstance(path, Path) or not path.is_absolute()
            or path.is_symlink() or getattr(path, "is_junction", lambda: False)()
            or not path.is_dir()
            or path.resolve(strict=True) != path.absolute()):
        _deny("operator-approved nonlinked directory required")
    info = path.lstat()
    if getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        _deny("operator directory is a reparse point")
    return path


def _read_review(root: Path, request_id: str):
    """Only fully completed durable review triples; never repair/review here."""
    _directory(root)
    reviewed = _directory(root / "reviewed")
    pending = root / "pending" / (request_id + ".json")
    if os.path.lexists(pending):
        _deny("review request remains pending or duplicated")
    src_path = reviewed / (request_id + ".json")
    intent_path = reviewed / (request_id + ".intent.json")
    receipt_path = reviewed / (request_id + ".review.json")
    source_raw = integration._read_file(src_path, integration._MAX_BYTES)
    intent_raw = integration._read_file(intent_path, integration._MAX_MARKER_BYTES)
    review_raw = integration._read_file(receipt_path, integration._MAX_MARKER_BYTES)
    source = _strict_json(source_raw, maximum=integration._MAX_BYTES)
    intent = _strict_json(intent_raw, maximum=integration._MAX_MARKER_BYTES)
    review = _strict_json(review_raw, maximum=integration._MAX_MARKER_BYTES)
    if (not _PROPOSAL_FIELDS <= set(source)
            or not set(source) <= _PROPOSAL_FIELDS | {"amountRial", "expenseId"}
            or set(intent) != _INTENT_FIELDS
            or set(review) != _REVIEW_FIELDS
            or type(source.get("schema")) is not int or source["schema"] != 1
            or source.get("source") != "madar"
            or source.get("id") != request_id
            or type(intent.get("schema")) is not int or intent["schema"] != 1
            or intent.get("source") != "taraz" or intent.get("id") != request_id
            or intent.get("state") not in ("reviewed", "rejected")
            or intent.get("financialEventCreated") is not False
            or review != {key: intent[key] for key in _REVIEW_FIELDS}
            or intent.get("taskId") != source.get("taskId")):
        _deny("durable source/intention/review identity mismatch")
    # Reuse the unmodified source reader's bounded schema checks.
    parsed_source, digest = integration._read_record(src_path)
    if (parsed_source["id"] != request_id
            or parsed_source["taskId"] != source["taskId"]
            or parsed_source["projectId"] != source["projectId"]
            or digest != hashlib.sha256(source_raw).hexdigest()
            or type(intent.get("sourceDigest")) is not str
            or not _HEX64.fullmatch(intent["sourceDigest"])
            or not hmac.compare_digest(intent["sourceDigest"], digest)):
        _deny("durable source digest/identity changed")
    integration._validate_intent(intent, request_id, intent["state"])
    if (_parse_review_time(intent["reviewedUtc"])
            < _parse_review_time(source["createdUtc"])):
        _deny("review precedes source proposal")
    return source_raw, review_raw, source, review


def _require_live_editor(api: TarazAPI):
    """An actual trusted company session; local-admin fallback is NOT identity."""
    if type(api) is not TarazAPI:
        _deny("real active TarazAPI required")
    identity = api._identity_store
    if type(identity) is not LocalCompanyIdentity or not api._identity_token:
        _deny("Taraz local fallback cannot attest an authenticated editor")
    if identity.root.resolve(strict=True) != api.path.parent.resolve(strict=True):
        _deny("Taraz identity and current company directory diverge")
    checked = api._require_authenticated("editor")
    latest = identity.require_session(api._identity_token, "editor")
    if (type(checked) is not dict or checked != latest
            or checked.get("username") != api._actor
            or checked.get("role") not in ("admin", "editor")
            or type(api._accounts) is not dict
            or api._accounts.get(api._actor, {}).get("role") != checked["role"]):
        _deny("Taraz editor is not the current authenticated actor")
    if api._exit_backed_up:
        _deny("Taraz company session is closing")


def _registry_original_binding(registry: TarazPeerRegistry, original):
    """Read-only peer registry check, no metadata mutation or network."""
    path = registry.path
    if (not path.is_file() or path.is_symlink()
            or getattr(path, "is_junction", lambda: False)()):
        _deny("trusted peer registry unavailable")
    uri = "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5,
                                 isolation_level=None)) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
                _deny("peer registry schema changed")
            rows = conn.execute(
                "SELECT org,sender,key_id,actor_role,payload_sha "
                "FROM requests WHERE request_id=?", (original["requestId"],)
            ).fetchall()
            expected = (
                registry.config.organization_id, registry.config.madar_sender_id,
                registry.config.madar_key_id, original["actorRole"],
                original["payloadSha256"],
            )
            if len(rows) != 1 or tuple(rows[0]) != expected:
                _deny("signed original request not present in trusted peer registry")
        finally:
            if conn.in_transaction:
                conn.execute("ROLLBACK")


def _sign_compatible(source_raw: bytes, review_raw: bytes, *, config: PeerConfig,
                     challenge: str, issued_at: datetime, expires_at: datetime,
                     source: dict, review: dict):
    """Independent portable exact Madar make_peer_review_attestation wire."""
    body = {
        "protocol": "mtr-taraz-review-proof", "version": 1,
        "algorithm": "HMAC-SHA256", "purpose": "metadata-review",
        "audience": "madar", "peerId": config.taraz_sender_id,
        "keyId": config.taraz_key_id, "organizationId": config.organization_id,
        "requestId": source["id"], "taskId": source["taskId"],
        "projectId": source["projectId"],
        "challenge": challenge,
        "issuedUtc": _utc(issued_at).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresUtc": _utc(expires_at).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sourceDigest": hashlib.sha256(source_raw).hexdigest(),
        "reviewDigest": hashlib.sha256(review_raw).hexdigest(),
        "reviewState": review["state"], "reviewedUtc": review["reviewedUtc"],
        "financialEventCreated": False,
    }
    ttl = (expires_at - issued_at).total_seconds()
    if not 0 < ttl <= 300 or issued_at < _parse_review_time(review["reviewedUtc"]):
        _deny("invalid attestation time window")
    mac = hmac.new(config.taraz_secret, _DOMAIN + _canonical(body),
                   hashlib.sha256).hexdigest()
    wire = _canonical({**body, "mac": mac})
    if len(wire) > MAX_ATTESTATION_BYTES:
        _deny("oversized peer review attestation")
    return wire


class ManualReviewAttestationIssuer:
    """Operator-wired only. No automatic sends, GUI hooks or IO on construct."""

    def __init__(self, *, taraz_api: TarazAPI,
                 peer_registry: TarazPeerRegistry,
                 trusted_config: PeerConfig,
                 reviewed_root: Path,
                 consumed_challenges_dir: Path):
        if (type(taraz_api) is not TarazAPI
                or type(peer_registry) is not TarazPeerRegistry
                or type(trusted_config) is not PeerConfig
                or peer_registry.config is not trusted_config):
            _deny("live operator-provisioned Taraz peer configuration required")
        if (not isinstance(reviewed_root, Path)
                or not isinstance(consumed_challenges_dir, Path)):
            _deny("operator-selected absolute directories required")
        self._api = taraz_api
        self._registry = peer_registry
        self._config = trusted_config
        self._root = _directory(reviewed_root)
        self._consumed = _directory(consumed_challenges_dir)
        if (self._root != _directory(bridge_root())
                or self._consumed == self._root
                or self._consumed == self._root / "reviewed"):
            _deny("review source must be live Taraz bridge; replay journal independent")
        self._lock = RLock()

    def issue_manual(self, *, request_id: str,
                     signed_madar_original: bytes,
                     signed_madar_query_challenge: bytes,
                     explicit_manual_action: bool, now: datetime | None = None):
        """Sign only after explicit operator action and real session check.

        The Madar-issued v2 receipt-lookup query ID is the single-use nonce.
        The verifier independently pins expected nonce and atomically consumes
        it; the issuer separately uses a durable create-only tombstone.
        """
        if explicit_manual_action is not True:
            _deny("explicit operator manual action required; no background signing")
        if type(request_id) is not str or not _HEX32.fullmatch(request_id):
            _deny("invalid reviewed request ID")
        actual_clock = datetime.now(timezone.utc)
        if now is None:
            # The existing review can have fractional seconds. Ceil to the
            # next UTC second to avoid claiming a signature predates a
            # same-second manual review. Madar permits 30s verifier skew.
            now = actual_clock.replace(microsecond=0)
            if actual_clock.microsecond:
                now += timedelta(seconds=1)
        else:
            now = _utc(now)
            # Explicit clock is for synthetic deterministic testing only,
            # never an arbitrary remote caller-controlled way to revive a
            # stale or future Madar challenge.
            if abs((now - actual_clock).total_seconds()) > 5:
                _deny("supplied clock is not current trusted UTC")
        now = _utc(now)
        with self._lock, self._api._lock:
            _require_live_editor(self._api)
            if (self._registry.config is not self._config
                    or self._root != _directory(bridge_root())
                    or self._consumed != _directory(self._consumed)):
                _deny("live operator peer or bridge configuration changed")

            original = verify_madar_v2(
                signed_madar_original, config=self._config, now=now,
                expected_kind="request", purpose="finance_review_request")
            query = verify_madar_v2(
                signed_madar_query_challenge, config=self._config, now=now,
                expected_kind="query", purpose="receipt_lookup")
            bound = query["payload"]
            if (original["requestId"] != request_id
                    or original["organizationId"] != query["organizationId"]
                    or original["senderId"] != query["senderId"]
                    or original["keyId"] != query["keyId"]
                    or original["actorRole"] != query["actorRole"]
                    or bound["originalRequestId"] != request_id
                    or bound["originalPayloadSha256"] != original["payloadSha256"]
                    or not _HEX32.fullmatch(query["requestId"])
                    or query["requestId"] == request_id):
                _deny("Madar challenge does not match original request/actor")
            source_raw, review_raw, source, review = _read_review(self._root, request_id)
            signed_binding = original["payload"]
            expected_binding = {
                "id": request_id, "taskId": source["taskId"],
                "projectId": source["projectId"],
                "sourceDigest": hashlib.sha256(source_raw).hexdigest(),
            }
            if (set(signed_binding) != _ORIGINAL_BINDING
                    or signed_binding != expected_binding):
                _deny("Madar signed request not bound to exact durable source bytes")
            _registry_original_binding(self._registry, original)
            expiry = datetime.strptime(
                query["expiresUtc"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc)
            response_expiry = min(expiry, now + timedelta(seconds=90))
            wire = _sign_compatible(
                source_raw, review_raw, config=self._config,
                challenge=query["requestId"], issued_at=now,
                expires_at=response_expiry, source=source, review=review)
            # A second read rules out ordinary file mutation between initial
            # validation and signing. The proof commits to exact file bytes;
            # a later source mutation is independently rejected by Madar.
            again_source, again_review, _, _ = _read_review(self._root, request_id)
            if (not hmac.compare_digest(source_raw, again_source)
                    or not hmac.compare_digest(review_raw, again_review)):
                _deny("durable metadata changed while attesting")
            _require_live_editor(self._api)
            if datetime.now(timezone.utc) >= response_expiry:
                _deny("Madar challenge expired before issuing proof")
            marker = self._consumed / (_USED_PREFIX + query["requestId"])
            if os.path.lexists(marker):
                _deny("Madar-issued challenge already used")
            try:
                os.mkdir(marker, 0o700)  # atomic create-only across processes
            except FileExistsError as exc:
                raise ReviewAttestationDenied("Madar challenge replay") from exc
            # Tombstone is never removed/repaired by this issuer. A crash
            # after the claim fails CLOSED, not a second signature attempt.
            if os.name != "nt":
                fd = os.open(self._consumed, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            return wire


__all__ = ("ManualReviewAttestationIssuer", "ReviewAttestationDenied")
