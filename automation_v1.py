"""Offline-capable, bounded orchestration for Madar's existing collaboration rules.

This is a pure, opt-in engine: no filesystem, network, clock, threads or APPDATA.
The trusted host owns authentication, caller-provided time, and durable commits.
The only executable operation is collab.apply_command(event.publish).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re

import collab
from automation_due import due_events


SCHEMA_VERSION = 1
MAX_PENDING = 1000
MAX_AUDIT = 10000
MAX_RECEIPTS = 10000
MAX_BATCH = 100
MAX_ATTEMPTS = 8
MAX_ENQUEUE = 500
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)\Z")
_STATES = frozenset({"ready", "retry", "dead"})
_OUTCOMES = frozenset({"queued", "applied", "replayed", "retry", "dead", "requeued"})
_ERRORS = frozenset({"", "permission_denied", "invalid_event", "transient_failure", "project_changed"})


def _stamp(value):
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        raise ValueError("Expected timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp must have timezone")
    return parsed


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _id(value, label="id"):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid " + label)
    return value


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"))
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("Invalid JSON data") from exc


def _fingerprint(actor, command):
    return hashlib.sha256(_json([actor, command]).encode("utf-8")).hexdigest()


def _command(command):
    if not isinstance(command, dict) or set(command) != {
        "type", "eventId", "cardId", "trigger", "data"
    } or command["type"] != "event.publish":
        raise ValueError("Only event.publish commands are allowlisted")
    _id(command["eventId"], "eventId")
    _id(command["cardId"], "cardId")
    if not isinstance(command["trigger"], str) or command["trigger"] not in collab.TRIGGERS:
        raise ValueError("Invalid event trigger")
    data = command["data"]
    if not isinstance(data, dict) or len(data) > len(collab.CONDITION_FIELDS) or (
        set(data) - collab.CONDITION_FIELDS
    ):
        raise ValueError("Invalid event data")
    if any(type(value) not in (str, int, bool) or
           (type(value) is str and len(value) > 100) for value in data.values()):
        raise ValueError("Invalid event data values")
    return command


def empty_state():
    """JSON serializable engine journal; persist it alongside collaboration data."""
    return {"schemaVersion": SCHEMA_VERSION, "jobs": [], "audit": [],
            "receipts": {}, "nextAudit": 1}


def validate_state(state):
    """Strict journal validation before processing/replaying untrusted disk data."""
    if not isinstance(state, dict) or set(state) != {
        "schemaVersion", "jobs", "audit", "receipts", "nextAudit"
    } or type(state["schemaVersion"]) is not int or state["schemaVersion"] != SCHEMA_VERSION:
        raise ValueError("Invalid automation state schema")
    if type(state["nextAudit"]) is not int or not 1 <= state["nextAudit"] <= 2**63:
        raise ValueError("Invalid audit sequence")
    jobs, audit, receipts = state["jobs"], state["audit"], state["receipts"]
    if not isinstance(jobs, list) or len(jobs) > MAX_PENDING:
        raise ValueError("Job queue limit exceeded")
    if not isinstance(audit, list) or len(audit) > MAX_AUDIT:
        raise ValueError("Audit limit exceeded")
    if not isinstance(receipts, dict) or len(receipts) > MAX_RECEIPTS:
        raise ValueError("Receipt limit exceeded")
    seen = set()
    for job in jobs:
        if not isinstance(job, dict) or set(job) != {
            "eventId", "actor", "projectId", "command", "fingerprint", "status", "attempts",
            "queuedAt", "nextAttemptAt", "lastError"
        }:
            raise ValueError("Invalid queued automation job")
        eid = _id(job["eventId"], "eventId")
        _id(job["projectId"], "projectId")
        if eid in seen or eid in receipts:
            raise ValueError("Duplicate job or receipt")
        seen.add(eid)
        if not isinstance(job["actor"], str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{2,39}", job["actor"]
        ):
            raise ValueError("Invalid queued actor")
        _command(job["command"])
        if job["command"]["eventId"] != eid or (
            job["fingerprint"] != _fingerprint(job["actor"], job["command"])
        ):
            raise ValueError("Queue event identity mismatch")
        if not isinstance(job["status"], str) or job["status"] not in _STATES or type(job["attempts"]) is not int or (
            not 0 <= job["attempts"] <= MAX_ATTEMPTS
        ):
            raise ValueError("Invalid job state")
        _stamp(job["queuedAt"])
        _stamp(job["nextAttemptAt"])
        if not isinstance(job["lastError"], str) or job["lastError"] not in _ERRORS:
            raise ValueError("Invalid job error code")
        if job["status"] == "dead" and job["attempts"] == 0:
            raise ValueError("Dead job without attempts")
    for event_id, receipt in receipts.items():
        _id(event_id, "receiptId")
        if not isinstance(receipt, dict) or set(receipt) != {"fingerprint", "at", "status"}:
            raise ValueError("Invalid automation receipt")
        if not isinstance(receipt["status"], str) or receipt["status"] not in {"applied", "replayed"} or not re.fullmatch(
            r"[0-9a-f]{64}", str(receipt["fingerprint"])
        ):
            raise ValueError("Invalid receipt fingerprint")
        _stamp(receipt["at"])
    audit_ids = set()
    highest = 0
    for entry in audit:
        if not isinstance(entry, dict) or set(entry) != {
            "sequence", "eventId", "outcome", "attempt", "error", "at"
        }:
            raise ValueError("Invalid audit entry")
        sequence = entry["sequence"]
        if type(sequence) is not int or sequence <= highest or sequence in audit_ids:
            raise ValueError("Audit is not strictly ordered")
        highest = sequence
        audit_ids.add(sequence)
        _id(entry["eventId"], "audit eventId")
        if not isinstance(entry["outcome"], str) or entry["outcome"] not in _OUTCOMES or type(entry["attempt"]) is not int or (
            not 0 <= entry["attempt"] <= MAX_ATTEMPTS
        ) or not isinstance(entry["error"], str) or entry["error"] not in _ERRORS:
            raise ValueError("Invalid audit result")
        _stamp(entry["at"])
    if highest >= state["nextAudit"]:
        raise ValueError("Audit sequence has regressed")
    if len(_json(state).encode("utf-8")) > 15_000_000:
        raise ValueError("Automation state exceeds 15 MB")
    return True


def _audit(state, event_id, outcome, attempt, now, error=""):
    if len(state["audit"]) >= MAX_AUDIT:
        raise ValueError("Audit capacity exhausted; explicit maintenance required")
    state["audit"].append({"sequence": state["nextAudit"], "eventId": event_id,
                           "outcome": outcome, "attempt": attempt,
                           "error": error, "at": now})
    state["nextAudit"] += 1


def _account_context(actor, accounts, cards, projects, event):
    # Reuse exactly the collaboration domain's authoritative project-role
    # validation. Host must pass session-derived actor, never an event actor.
    users, indexed_cards, _ = collab._context(actor, accounts, cards, projects)
    card = collab._card(indexed_cards, event["cardId"])
    collab._require(users[actor], card["projectId"], write=True)
    return card["projectId"]


def enqueue_events(state, events, *, actor, accounts, cards, projects, now):
    """Enqueue authorized, schema-validated events atomically in a cloned journal.

    Event IDs are stable deduplication keys, including after serialized restart.
    An ID cannot be reused for another actor or payload. No job executes here.
    """
    validate_state(state)
    _stamp(now)
    if not isinstance(events, list) or len(events) > MAX_ENQUEUE:
        raise ValueError("Too many automation events in one enqueue")
    updated = deepcopy(state)
    existing = {job["eventId"]: job["fingerprint"] for job in updated["jobs"]}
    existing.update({key: value["fingerprint"] for key, value in updated["receipts"].items()})
    added = 0
    for event in events:
        _command(event)
        project_id = _account_context(actor, accounts, cards, projects, event)
        event_id = event["eventId"]
        fingerprint = _fingerprint(actor, event)
        if event_id in existing:
            if existing[event_id] != fingerprint:
                raise ValueError("Idempotency key reused for a different automation event")
            continue
        if len(updated["jobs"]) >= MAX_PENDING:
            raise ValueError("Automation pending-job capacity exhausted")
        updated["jobs"].append({
            "eventId": event_id, "actor": actor, "projectId": project_id,
            "command": deepcopy(event),
            "fingerprint": fingerprint, "status": "ready", "attempts": 0,
            "queuedAt": now, "nextAttemptAt": now, "lastError": ""
        })
        _audit(updated, event_id, "queued", 0, now)
        existing[event_id] = fingerprint
        added += 1
    validate_state(updated)
    return {"state": updated, "added": added, "duplicates": len(events) - added}


def enqueue_due(state, cards, *, today, actor, accounts, projects, now, horizon_days=7):
    """Generate today's due events; caller chooses the local date explicitly."""
    events = due_events(cards, today=today, horizon_days=horizon_days)
    return enqueue_events(state, events, actor=actor, accounts=accounts, cards=cards,
                          projects=projects, now=now)


def run_batch(state, collab_state, *, accounts, cards, projects, now,
              limit=25, max_attempts=5, offline=False):
    """Apply due jobs through collab.allowlist with detachable atomic outputs.

    Persist collaboration state first, then the journal if separate stores are
    unavoidable: its durable collab receipt prevents duplicate effects on replay.
    The preferred host commits BOTH states in one transaction and CAS revision.
    offline=True performs zero work, including zero retry-budget consumption.
    """
    validate_state(state)
    collab.validate_state(collab_state)
    clock = _stamp(now)
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
        raise ValueError("Invalid batch limit")
    if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise ValueError("Invalid retry budget")
    if type(offline) is not bool:
        raise ValueError("Offline flag must be boolean")
    updated = deepcopy(state)
    current = deepcopy(collab_state)
    counts = {"applied": 0, "replayed": 0, "retried": 0, "dead": 0, "processed": 0}
    if offline:
        return {"state": updated, "collab": current, **counts}

    due_jobs = [job for job in updated["jobs"] if job["status"] in {"ready", "retry"}
                and _stamp(job["nextAttemptAt"]) <= clock]
    due_jobs = sorted(due_jobs, key=lambda job: (job["nextAttemptAt"], job["queuedAt"], job["eventId"]))
    current_cards = cards.values() if isinstance(cards, dict) else cards
    project_by_card = {card["id"]: card.get("projectId") for card in current_cards
                       if isinstance(card, dict) and isinstance(card.get("id"), str)}
    for due in due_jobs[:limit]:
        job = next(item for item in updated["jobs"] if item["eventId"] == due["eventId"])
        counts["processed"] += 1
        if job["command"]["cardId"] in project_by_card and (
            project_by_card[job["command"]["cardId"]] != job["projectId"]
        ):
            job.update(status="dead", attempts=job["attempts"] + 1,
                       nextAttemptAt=now, lastError="project_changed")
            _audit(updated, job["eventId"], "dead", job["attempts"], now, "project_changed")
            counts["dead"] += 1
            continue
        if job["attempts"] >= max_attempts:
            job.update(status="dead", nextAttemptAt=now)
            _audit(updated, job["eventId"], "dead", job["attempts"], now, "transient_failure")
            counts["dead"] += 1
            continue
        attempt = job["attempts"] + 1
        was_present = job["eventId"] in current["receipts"]
        try:
            outcome = collab.apply_command(
                current, job["command"], actor=job["actor"], accounts=accounts,
                cards=cards, projects=projects, now=now,
            )
        except (PermissionError, ValueError) as exc:
            error = "permission_denied" if isinstance(exc, PermissionError) else "invalid_event"
            job.update(status="dead", attempts=attempt, lastError=error, nextAttemptAt=now)
            _audit(updated, job["eventId"], "dead", attempt, now, error)
            counts["dead"] += 1
        except RuntimeError:
            job["attempts"] = attempt
            job["lastError"] = "transient_failure"
            if attempt >= max_attempts:
                job.update(status="dead", nextAttemptAt=now)
                _audit(updated, job["eventId"], "dead", attempt, now, "transient_failure")
                counts["dead"] += 1
            else:
                delay = min(3600, 60 * (2 ** (attempt - 1)))
                job.update(status="retry", nextAttemptAt=_iso(clock + timedelta(seconds=delay)))
                _audit(updated, job["eventId"], "retry", attempt, now, "transient_failure")
                counts["retried"] += 1
        else:
            current = outcome["state"]
            status = "replayed" if was_present else "applied"
            if len(updated["receipts"]) >= MAX_RECEIPTS:
                raise ValueError("Automation receipts capacity exhausted")
            updated["receipts"][job["eventId"]] = {
                "fingerprint": job["fingerprint"], "at": now, "status": status
            }
            updated["jobs"].remove(job)
            _audit(updated, due["eventId"], status, attempt, now)
            counts[status] += 1
    validate_state(updated)
    collab.validate_state(current)
    return {"state": updated, "collab": current, **counts}


def retry_dead(state, event_id, *, now):
    """Explicit admin-side journal operation; host MUST authorize before calling."""
    validate_state(state)
    _stamp(now)
    _id(event_id, "eventId")
    updated = deepcopy(state)
    job = next((job for job in updated["jobs"] if job["eventId"] == event_id), None)
    if job is None or job["status"] != "dead":
        raise ValueError("Dead-letter event not found")
    job.update(status="ready", attempts=0, nextAttemptAt=now, lastError="")
    _audit(updated, event_id, "requeued", 0, now)
    validate_state(updated)
    return updated


__all__ = ["empty_state", "validate_state", "enqueue_events",
           "enqueue_due", "run_batch", "retry_dead"]
