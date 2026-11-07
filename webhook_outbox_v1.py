"""Bounded, signed, host-operated webhook OUTBOX. No network, disk or clock I/O.

External delivery is at-least-once, NOT exactly-once: after a transport accepts
a message but before the host commits the returned journal, it can be sent
again. Consumers must deduplicate the stable X-Madar-Delivery-Id.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import re

SCHEMA_VERSION = 1
MAX_QUEUE = 500
MAX_ENQUEUE = 100
MAX_BATCH = 25
MAX_AUDIT = 5000
MAX_RECEIPTS = 5000
MAX_ATTEMPTS = 8
MAX_JOURNAL_BYTES = 4_000_000
MAX_BODY_BYTES = 2048
ALLOWED_KINDS = frozenset({
    "card_created", "card_moved", "label_changed", "checklist_completed",
})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_TARGET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z", re.ASCII)
_STAMP = re.compile(
    r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)\Z"
)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_DELIVERY = re.compile(r"wh-[0-9a-f]{40}\Z", re.ASCII)
_STATUSES = frozenset({"ready", "retry", "dead"})
_OUTCOMES = frozenset({"queued", "delivered", "retry", "dead", "requeued"})
_ERROR_CODES = frozenset({
    "", "transport_error", "retryable_status", "rejected_status",
    "destination_revoked", "secret_unavailable", "unexpected_status",
})
_HMAC_CONTEXT = b"madar.webhook.v1\n"
_PAYLOAD_FIELDS = frozenset({"eventId", "projectId", "cardId", "kind", "occurredAt"})


def _identifier(value, name):
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError("Invalid " + name)
    return value


def _target(value):
    # No schemes, dots, colons, IP addresses or paths. Only host-owned lookup
    # keys; never interpret these identifiers as user-controlled URLs.
    if not isinstance(value, str) or _TARGET_ID.fullmatch(value) is None:
        raise ValueError("Invalid opaque destination ID")
    return value


def _date(value):
    if not isinstance(value, str) or _STAMP.fullmatch(value) is None:
        raise ValueError("Expected timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValueError("Expected timezone offset")
    return parsed


def _utc(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_bytes(data):
    try:
        return json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("Invalid JSON") from exc


def _strict_json(data):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_):
        raise ValueError("Forbidden JSON numeric constant")

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs,
                          parse_constant=reject_constant)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid JSON bytes") from exc


def _event(value):
    if not isinstance(value, dict) or set(value) != _PAYLOAD_FIELDS:
        raise ValueError("Only minimal lifecycle webhook fields are allowed")
    for key in ("eventId", "projectId", "cardId"):
        _identifier(value[key], key)
    if not isinstance(value["kind"], str) or value["kind"] not in ALLOWED_KINDS:
        raise ValueError("Unsupported lifecycle event kind")
    _date(value["occurredAt"])
    if len(_json_bytes(value)) > MAX_BODY_BYTES:
        raise ValueError("Event payload too large")
    return value


def _delivery_id(target_id, event_id):
    value = _json_bytes([target_id, event_id])
    return "wh-" + sha256(value).hexdigest()[:40]


def _fingerprint(target_id, event):
    return sha256(_json_bytes([target_id, event])).hexdigest()


def _secret(value):
    if not isinstance(value, bytes) or not 32 <= len(value) <= 256:
        raise ValueError("Signing secret must be 32 to 256 bytes in memory")
    return value


def canonical_body(event, delivery_id, sent_at):
    """Canonical UTF-8 JSON for exactly one delivery attempt; no URL or secrets."""
    _event(event)
    if not isinstance(delivery_id, str) or _DELIVERY.fullmatch(delivery_id) is None:
        raise ValueError("Invalid deliveryId")
    _date(sent_at)
    body = _json_bytes({"schemaVersion": 1, "deliveryId": delivery_id,
                        "sentAt": sent_at, "event": event})
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("Delivery body too large")
    return body


def _validate_body(body):
    obj = _strict_json(body)
    if (not isinstance(obj, dict) or set(obj) !=
            {"schemaVersion", "deliveryId", "sentAt", "event"} or
            type(obj["schemaVersion"]) is not int or obj["schemaVersion"] != 1):
        raise ValueError("Malformed signed webhook body")
    _event(obj["event"])
    _date(obj["sentAt"])
    if not isinstance(obj["deliveryId"], str) or not _DELIVERY.fullmatch(obj["deliveryId"]):
        raise ValueError("Malformed delivery identifier")
    if body != _json_bytes(obj):
        raise ValueError("Noncanonical webhook body")
    return obj


def sign_body(body, secret):
    """v1= lowercase HMAC-SHA256 hex over domain-separated exact JSON bytes."""
    _secret(secret)
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BODY_BYTES:
        raise ValueError("Invalid canonical delivery bytes")
    _validate_body(body)
    return "v1=" + hmac.new(secret, _HMAC_CONTEXT + body, "sha256").hexdigest()


def verify_signature(body, signature, secret, *, now=None, max_age_seconds=300):
    """Verify canonical JSON and HMAC with optional replay time-window check.

    Receiver ALSO needs deliveryId dedupe, ingress authentication and scope ACL.
    """
    _secret(secret)
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 86400:
        raise ValueError("Invalid freshness window")
    if (not isinstance(body, bytes) or not 0 < len(body) <= MAX_BODY_BYTES or
            not isinstance(signature, str) or not re.fullmatch(r"v1=[0-9a-f]{64}", signature)):
        return False
    try:
        obj = _validate_body(body)
    except ValueError:
        return False
    if now is not None:
        try:
            age = abs((_date(now) - _date(obj["sentAt"])).total_seconds())
        except ValueError:
            return False
        if age > max_age_seconds:
            return False
    expected = hmac.new(secret, _HMAC_CONTEXT + body, "sha256").hexdigest()
    return hmac.compare_digest(signature[3:], expected)


def empty_state():
    return {"schemaVersion": SCHEMA_VERSION, "jobs": [], "receipts": {},
            "audit": [], "nextAudit": 1}


def validate_state(state):
    """Strict schema, identities and fingerprints of a detached JSON journal."""
    if (not isinstance(state, dict) or set(state) !=
            {"schemaVersion", "jobs", "receipts", "audit", "nextAudit"} or
            type(state["schemaVersion"]) is not int or state["schemaVersion"] != SCHEMA_VERSION or
            type(state["nextAudit"]) is not int or not 1 <= state["nextAudit"] < 2**63):
        raise ValueError("Invalid webhook journal schema")
    jobs, receipts, audit = state["jobs"], state["receipts"], state["audit"]
    if (not isinstance(jobs, list) or len(jobs) > MAX_QUEUE or
            not isinstance(receipts, dict) or len(receipts) > MAX_RECEIPTS or
            not isinstance(audit, list) or len(audit) > MAX_AUDIT):
        raise ValueError("Webhook journal capacity exceeded")
    seen = set()
    for job in jobs:
        if not isinstance(job, dict) or set(job) != {
            "deliveryId", "targetId", "event", "fingerprint", "status",
            "attempts", "queuedAt", "nextAttemptAt", "lastError"
        }:
            raise ValueError("Malformed webhook job")
        _target(job["targetId"])
        _event(job["event"])
        ident = _delivery_id(job["targetId"], job["event"]["eventId"])
        if job["deliveryId"] != ident or ident in seen or ident in receipts:
            raise ValueError("Webhook job identity collision")
        seen.add(ident)
        if job["fingerprint"] != _fingerprint(job["targetId"], job["event"]):
            raise ValueError("Webhook job payload mismatch")
        if (not isinstance(job["status"], str) or job["status"] not in _STATUSES or
                type(job["attempts"]) is not int or not 0 <= job["attempts"] <= MAX_ATTEMPTS or
                not isinstance(job["lastError"], str) or job["lastError"] not in _ERROR_CODES):
            raise ValueError("Invalid webhook attempt state")
        _date(job["queuedAt"])
        _date(job["nextAttemptAt"])
        if job["status"] == "dead" and job["attempts"] < 1:
            raise ValueError("Dead-letter missing attempts")
    for ident, receipt in receipts.items():
        if not isinstance(ident, str) or not _DELIVERY.fullmatch(ident):
            raise ValueError("Invalid receipt identifier")
        if (not isinstance(receipt, dict) or set(receipt) !=
                {"fingerprint", "at", "statusCode"} or
                not isinstance(receipt["fingerprint"], str) or
                not _DIGEST.fullmatch(receipt["fingerprint"]) or
                type(receipt["statusCode"]) is not int or
                not 200 <= receipt["statusCode"] <= 299):
            raise ValueError("Invalid webhook receipt")
        _date(receipt["at"])
    previous = 0
    for record in audit:
        if not isinstance(record, dict) or set(record) != {
            "sequence", "deliveryId", "outcome", "attempt", "errorCode", "at"
        }:
            raise ValueError("Malformed webhook audit")
        if (type(record["sequence"]) is not int or record["sequence"] <= previous or
                not isinstance(record["deliveryId"], str) or
                not _DELIVERY.fullmatch(record["deliveryId"]) or
                not isinstance(record["outcome"], str) or record["outcome"] not in _OUTCOMES or
                type(record["attempt"]) is not int or not 0 <= record["attempt"] <= MAX_ATTEMPTS or
                not isinstance(record["errorCode"], str) or record["errorCode"] not in _ERROR_CODES):
            raise ValueError("Invalid webhook audit entry")
        _date(record["at"])
        previous = record["sequence"]
    if previous >= state["nextAudit"]:
        raise ValueError("Audit sequence regression")
    if len(_json_bytes(state)) > MAX_JOURNAL_BYTES:
        raise ValueError("Webhook journal byte limit exceeded")
    return True


def _audit(state, job, outcome, attempt, now, error_code=""):
    if len(state["audit"]) >= MAX_AUDIT or state["nextAudit"] >= 2**63 - 1:
        raise ValueError("Webhook audit capacity exhausted")
    state["audit"].append({
        "sequence": state["nextAudit"], "deliveryId": job["deliveryId"],
        "outcome": outcome, "attempt": attempt, "errorCode": error_code, "at": now,
    })
    state["nextAudit"] += 1


def _authorized(authorize, target_id, project_id):
    if not callable(authorize):
        raise TypeError("Host authorization callback required")
    result = authorize(target_id, project_id)
    if type(result) is not bool:
        raise ValueError("Host authorization callback must return bool")
    return result


def enqueue(state, events, *, target_id, authorize, now):
    """Validate events and enqueue with host-owned target/project ACL."""
    validate_state(state)
    _target(target_id)
    _date(now)
    if not isinstance(events, list) or len(events) > MAX_ENQUEUE:
        raise ValueError("Webhook enqueue batch limit exceeded")
    result = deepcopy(state)
    known = {j["deliveryId"]: j["fingerprint"] for j in result["jobs"]}
    known.update({ident: item["fingerprint"] for ident, item in result["receipts"].items()})
    added = 0
    for source in events:
        _event(source)
        if not _authorized(authorize, target_id, source["projectId"]):
            raise PermissionError("Webhook destination or project is not authorized")
        delivery_id = _delivery_id(target_id, source["eventId"])
        fingerprint = _fingerprint(target_id, source)
        if delivery_id in known:
            if known[delivery_id] != fingerprint:
                raise ValueError("Webhook event ID reused with different payload")
            continue
        if len(result["jobs"]) >= MAX_QUEUE:
            raise ValueError("Webhook queue is full")
        job = {
            "deliveryId": delivery_id, "targetId": target_id,
            "event": deepcopy(source), "fingerprint": fingerprint,
            "status": "ready", "attempts": 0, "queuedAt": now,
            "nextAttemptAt": now, "lastError": "",
        }
        result["jobs"].append(job)
        _audit(result, job, "queued", 0, now)
        known[delivery_id] = fingerprint
        added += 1
    validate_state(result)
    return {"state": result, "added": added, "duplicates": len(events) - added}


def run_batch(state, *, now, authorize, secret_provider, transport,
              limit=10, max_attempts=5, offline=False):
    """Host-supplied transport(target_id, body_bytes, headers) -> int status.

    Only host maps opaque target_id to an approved HTTPS endpoint. This code
    NEVER opens URLs or sockets. Host persists returned journal with CAS.
    """
    validate_state(state)
    clock = _date(now)
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
        raise ValueError("Invalid webhook batch size")
    if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise ValueError("Invalid retry budget")
    if type(offline) is not bool:
        raise ValueError("offline must be boolean")
    if not callable(authorize) or not callable(secret_provider) or not callable(transport):
        raise TypeError("Host authorization, secret provider and transport callbacks required")
    updated = deepcopy(state)
    counts = {"processed": 0, "delivered": 0, "retried": 0, "dead": 0}
    if offline:
        return {"state": updated, **counts}
    selected = sorted(
        (j for j in updated["jobs"] if j["status"] in {"ready", "retry"} and
         _date(j["nextAttemptAt"]) <= clock),
        key=lambda j: (_date(j["nextAttemptAt"]), _date(j["queuedAt"]), j["deliveryId"]),
    )[:limit]
    if len(updated["audit"]) + len(selected) > MAX_AUDIT:
        raise ValueError("Webhook audit capacity exhausted")
    # Even a successful outgoing HTTP call MUST have space for its durable
    # receipt. Fail before touching transport rather than sending an event
    # and then discovering that the journal cannot record the result.
    if len(updated["receipts"]) + len(selected) > MAX_RECEIPTS:
        raise ValueError("Webhook receipt capacity exhausted")
    for job in selected:
        counts["processed"] += 1
        attempt = job["attempts"] + 1
        status, error_code = None, ""
        if not _authorized(authorize, job["targetId"], job["event"]["projectId"]):
            error_code = "destination_revoked"
        elif job["attempts"] >= max_attempts:
            error_code = "transport_error"
            attempt = job["attempts"]
        else:
            try:
                secret = _secret(secret_provider(job["targetId"]))
            except (ValueError, LookupError, PermissionError):
                error_code = "secret_unavailable"
            else:
                body = canonical_body(job["event"], job["deliveryId"], now)
                signature = sign_body(body, secret)
                headers = {
                    "Content-Type": "application/json",
                    "X-Madar-Signature": signature,
                    "X-Madar-Delivery-Id": job["deliveryId"],
                    "X-Madar-Sent-At": now,
                }
                try:
                    status = transport(job["targetId"], body, headers)
                except (OSError, TimeoutError, ConnectionError):
                    error_code = "transport_error"
                else:
                    if type(status) is not int or not 100 <= status <= 599:
                        error_code = "unexpected_status"
                    elif status in {408, 425, 429} or status >= 500:
                        error_code = "retryable_status"
                    elif not 200 <= status < 300:
                        error_code = "rejected_status"
        if status is not None and type(status) is int and 200 <= status < 300:
            if len(updated["receipts"]) >= MAX_RECEIPTS:
                raise ValueError("Webhook receipt capacity exhausted")
            updated["receipts"][job["deliveryId"]] = {
                "fingerprint": job["fingerprint"], "at": now, "statusCode": status,
            }
            updated["jobs"].remove(job)
            _audit(updated, job, "delivered", attempt, now)
            counts["delivered"] += 1
        else:
            job["attempts"] = attempt
            job["lastError"] = error_code
            permanent = error_code in {"destination_revoked", "rejected_status", "secret_unavailable"}
            if permanent or attempt >= max_attempts:
                job.update(status="dead", nextAttemptAt=now)
                _audit(updated, job, "dead", attempt, now, error_code)
                counts["dead"] += 1
            else:
                delay = min(3600, 60 * 2 ** (attempt - 1))
                job.update(status="retry", nextAttemptAt=_utc(clock + timedelta(seconds=delay)))
                _audit(updated, job, "retry", attempt, now, error_code)
                counts["retried"] += 1
    validate_state(updated)
    return {"state": updated, **counts}


def requeue_dead(state, delivery_id, *, now):
    """Pure journal edit; host MUST require admin before calling."""
    validate_state(state)
    _date(now)
    if not isinstance(delivery_id, str) or not _DELIVERY.fullmatch(delivery_id):
        raise ValueError("Invalid delivery ID")
    result = deepcopy(state)
    job = next((j for j in result["jobs"] if j["deliveryId"] == delivery_id), None)
    if job is None or job["status"] != "dead":
        raise ValueError("Dead-letter not found")
    job.update(status="ready", attempts=0, nextAttemptAt=now, lastError="")
    _audit(result, job, "requeued", 0, now)
    validate_state(result)
    return result


__all__ = [
    "SCHEMA_VERSION", "ALLOWED_KINDS", "MAX_QUEUE", "empty_state", "validate_state",
    "canonical_body", "sign_body", "verify_signature",
    "enqueue", "run_batch", "requeue_dead",
]
