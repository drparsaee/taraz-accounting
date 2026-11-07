"""M07 safety preflight for Madar automation, entirely read-only.

This module NEVER invokes collab.apply_command, automation_v1.run_batch,
retry_dead, callbacks, network, clock, filesystem or user code. The trusted
host authenticates the actor and owns commit, CAS, audit persistence, and
provenance across causally chained events.

Its decisions are advisory until the trusted host enforces them atomically.
No event payload, finance value, comment text, recipient or executable action
is returned in the audit preview.
"""

from __future__ import annotations

from collections import Counter
from datetime import timezone
import hashlib
import json
import re

import automation_v1
import collab


DEFAULT_POLICY = {
    "maxEvents": 25,                # requested batch size
    "maxActions": 40,               # total estimated comment/notify actions
    "maxChainDepth": 4,             # current event is one level
    "maxRepeatedSignature": 2,     # distinct eventIds cannot evade cutout
    "maxAttempts": 3,               # never more than engine's 8
    "maxRetriesPerBatch": 8,
    "maxConsecutiveFailures": 4,   # retry/dead outcome streak
    "maxAuditPreview": 100,
}
_POLICY_RANGES = {
    "maxEvents": (1, automation_v1.MAX_BATCH),
    "maxActions": (1, 500),
    "maxChainDepth": (1, 16),
    "maxRepeatedSignature": (1, 16),
    "maxAttempts": (1, automation_v1.MAX_ATTEMPTS),
    "maxRetriesPerBatch": (0, automation_v1.MAX_BATCH),
    "maxConsecutiveFailures": (1, 100),
    "maxAuditPreview": (1, 100),
}
_ALLOWED_REASONS = frozenset({
    "ok", "already_queued", "already_applied", "collab_committed",
    "chain_depth", "repeated_signature", "batch_loop",
    "action_budget", "rule_budget", "project_changed",
    "retry_exhausted", "retry_budget", "stop_loss", "audit_exhausted",
    "permission_denied",
})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_OUTCOMES = frozenset({"allow", "duplicate", "block"})
_INPUT_LIMITS = {"accounts": 1000, "cards": 20_000, "projects": 2_000}
_MAX_RULES = 2_000


def _bounds(collab_state, *, accounts=None, cards=None, projects=None):
    if not isinstance(collab_state, dict) or not isinstance(
            collab_state.get("rules"), list) or len(collab_state["rules"]) > _MAX_RULES:
        raise ValueError("Safety rules capacity exceeded")
    for name, items in (("accounts", accounts), ("cards", cards),
                        ("projects", projects)):
        if items is None:
            continue
        if not isinstance(items, (dict, list)) or len(items) > _INPUT_LIMITS[name]:
            raise ValueError("Safety " + name + " capacity exceeded")


def validate_safety_policy(policy=None):
    """Return a new strict policy dictionary; bools are never integers."""
    if policy is None:
        return dict(DEFAULT_POLICY)
    if not isinstance(policy, dict) or set(policy) != set(DEFAULT_POLICY):
        raise ValueError("Invalid safety policy fields")
    for key, (minimum, maximum) in _POLICY_RANGES.items():
        value = policy[key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("Invalid safety policy " + key)
    return dict(policy)


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("Invalid canonical safety input") from exc


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _context(actor, accounts, cards, projects):
    # Reuse the exact existing user/role/project validation, but no reducer.
    users, indexed_cards, _ = collab._context(actor, accounts, cards, projects)
    return users, indexed_cards


def event_signature(command, project_id):
    """Stable causal signature EXCLUDING eventId to catch regenerated IDs."""
    automation_v1._command(command)
    collab._identifier(project_id, "projectId")
    return _digest([project_id, command["cardId"],
                    command["trigger"], command["data"]])


def _ancestry(history, event_id, policy):
    if history is None:
        return ()
    if not isinstance(history, dict) or len(history) > policy["maxEvents"]:
        raise ValueError("Invalid bounded causal ancestry map")
    for key, trail in history.items():
        automation_v1._id(key, "eventId")
        if not isinstance(trail, (list, tuple)) or len(trail) > 16:
            raise ValueError("Invalid causal ancestry depth")
        if any(not isinstance(sig, str) or not _SHA256.fullmatch(sig)
               for sig in trail):
            raise ValueError("Invalid causal ancestry fingerprint")
    return tuple(history.get(event_id, ()))


def inspect_replay(engine_state, collab_state, command, *, actor):
    """Inspect ONLY durable job/receipt IDs and hashes, never execute.

    A collab-only receipt is the documented crash gap after collab commit but
    before journal commit. Fingerprint collision fails closed.
    """
    automation_v1.validate_state(engine_state)
    _bounds(collab_state)
    collab.validate_state(collab_state)
    automation_v1._command(command)
    collab._username(actor)
    event_id = command["eventId"]
    fingerprint = automation_v1._fingerprint(actor, command)
    job = next((j for j in engine_state["jobs"] if j["eventId"] == event_id), None)
    receipt = engine_state["receipts"].get(event_id)
    collab_receipt = collab_state["receipts"].get(event_id)
    if any(item is not None and item["fingerprint"] != fingerprint
           for item in (job, receipt, collab_receipt)):
        raise ValueError("Automation replay fingerprint collision")
    if receipt is not None:
        disposition = "already_applied"
    elif collab_receipt is not None:
        disposition = "collab_committed"
    elif job is not None:
        disposition = "already_queued"
    else:
        disposition = "new"
    return {"eventId": event_id, "fingerprint": fingerprint,
            "disposition": disposition}


def _rule_preview(collab_state, command, users, project_id):
    """Mirror collab._execute_rules condition/owner predicate without effects."""
    matched = [rule for rule in collab_state["rules"]
               if rule["enabled"] and rule["projectId"] == project_id
               and rule["trigger"] == command["trigger"]
               and all(condition["field"] in command["data"]
                       and type(command["data"][condition["field"]])
                       is type(condition["equals"])
                       and command["data"][condition["field"]] == condition["equals"]
                       for condition in rule["conditions"])]
    # Use the same hard limits as the authoritative reducer.
    if len(matched) > 20 or sum(len(rule["actions"]) for rule in matched) > 50:
        raise ValueError("Collaboration automation execution limit exceeded")
    eligible = 0
    skipped = 0
    actions = 0
    comment_actions = 0
    notify_actions = 0
    for rule in sorted(matched, key=lambda item: item["id"]):
        owner = users.get(rule["owner"])
        if owner is None or owner["role"] != "admin" or not collab._permitted(
                owner, project_id, write=True):
            skipped += 1
            continue
        eligible += 1
        for action in rule["actions"]:
            # validate_state already rejected arbitrary types/payload keys.
            actions += 1
            if action["type"] == "comment":
                comment_actions += 1
            else:
                notify_actions += 1
    return {"matchedRules": len(matched), "eligibleRules": eligible,
            "skippedScopeRules": skipped, "actions": actions,
            "commentActions": comment_actions, "notifyActions": notify_actions}


def _decision(event_id, signature, outcome, reason, preview):
    return {"eventId": event_id, "signature": signature,
            "outcome": outcome, "reason": reason,
            "matchedRules": preview["matchedRules"],
            "eligibleRules": preview["eligibleRules"],
            "skippedScopeRules": preview["skippedScopeRules"],
            "actions": preview["actions"],
            "commentActions": preview["commentActions"],
            "notifyActions": preview["notifyActions"]}


def _empty_preview():
    return {"matchedRules": 0, "eligibleRules": 0, "skippedScopeRules": 0,
            "actions": 0, "commentActions": 0, "notifyActions": 0}


def _safety_for_event(command, actor, engine_state, collab_state,
                      users, cards, policy, ancestry):
    automation_v1._command(command)
    event_id = command["eventId"]
    card = collab._card(cards, command["cardId"])
    collab._require(users[actor], card["projectId"], write=True)
    signature = event_signature(command, card["projectId"])
    # Revalidate role/project on replay, not just enqueue.
    replay = inspect_replay(engine_state, collab_state, command, actor=actor)
    if replay["disposition"] != "new":
        # Duplicate has zero *new* actions. An already committed collab
        # receipt is recorded separately from a new executable event.
        return _decision(event_id, signature, "duplicate",
                         replay["disposition"], _empty_preview())
    trail = _ancestry(ancestry, event_id, policy)
    if len(trail) + 1 > policy["maxChainDepth"]:
        return _decision(event_id, signature, "block",
                         "chain_depth", _empty_preview())
    if trail.count(signature) + 1 > policy["maxRepeatedSignature"]:
        return _decision(event_id, signature, "block",
                         "repeated_signature", _empty_preview())
    return _decision(event_id, signature, "allow", "ok",
                     _rule_preview(collab_state, command, users, card["projectId"]))


def _failure_streak(journal):
    count = 0
    for item in reversed(journal["audit"]):
        if item["outcome"] in ("retry", "dead"):
            count += 1
        elif item["outcome"] in ("applied", "replayed", "requeued"):
            break
        # 'queued' is neither a success nor a reset of the failure streak.
    return count


def _apply_budgets(decisions, policy, *, failure_streak=0):
    by_signature = Counter()
    actions = 0
    accepted = []
    for decision in decisions:
        if decision["outcome"] != "allow":
            accepted.append(decision)
            continue
        outcome = dict(decision)
        if failure_streak >= policy["maxConsecutiveFailures"]:
            outcome.update(outcome="block", reason="stop_loss")
        elif by_signature[outcome["signature"]] >= policy["maxRepeatedSignature"]:
            outcome.update(outcome="block", reason="batch_loop")
        elif actions + outcome["actions"] > policy["maxActions"]:
            outcome.update(outcome="block", reason="action_budget")
        else:
            by_signature[outcome["signature"]] += 1
            actions += outcome["actions"]
        if outcome["outcome"] == "block":
            # A denied event produces no actions, even in hypothetical totals.
            for field in ("actions", "commentActions", "notifyActions"):
                outcome[field] = 0
        accepted.append(outcome)
    return accepted


def _result(decisions, *, deferred=0):
    counts = Counter(item["outcome"] for item in decisions)
    return {"safeToExecute": counts["block"] == 0,
            "decisions": decisions, "allowed": counts["allow"],
            "duplicates": counts["duplicate"], "blocked": counts["block"],
            "deferred": deferred,
            "estimatedActions": sum(item["actions"] for item in decisions
                                    if item["outcome"] == "allow")}


def dry_run_events(engine_state, collab_state, events, *,
                   actor, accounts, cards, projects, now,
                   policy=None, ancestry=None):
    """Bounded NEW-event preview, no enqueue, no execution and no mutation.

    Returns an all-or-nothing gate. The host must reject the entire batch if
    safeToExecute is false; this does not change the automation journal.
    """
    config = validate_safety_policy(policy)
    automation_v1.validate_state(engine_state)
    _bounds(collab_state, accounts=accounts, cards=cards, projects=projects)
    collab.validate_state(collab_state)
    automation_v1._stamp(now)
    users, indexed_cards = _context(actor, accounts, cards, projects)
    if not isinstance(events, list) or len(events) > config["maxEvents"]:
        raise ValueError("Dry-run event batch limit exceeded")
    seen = set()
    decisions = []
    for event in events:
        automation_v1._command(event)
        if event["eventId"] in seen:
            raise ValueError("Duplicate eventId within dry-run batch")
        seen.add(event["eventId"])
        decisions.append(_safety_for_event(
            event, actor, engine_state, collab_state, users,
            indexed_cards, config, ancestry))
    return _result(_apply_budgets(decisions, config,
                                 failure_streak=_failure_streak(engine_state)))


def preflight_due_batch(engine_state, collab_state, *,
                        accounts, cards, projects, now,
                        policy=None, ancestry=None, offline=False):
    """Inspect the SAME deterministic due ordering as automation_v1.run_batch.

    There is deliberately NO run/apply/commit. safeToExecute False means the
    host must withhold the entire run and require a reviewed safe disposition.
    """
    config = validate_safety_policy(policy)
    automation_v1.validate_state(engine_state)
    _bounds(collab_state, accounts=accounts, cards=cards, projects=projects)
    collab.validate_state(collab_state)
    clock = automation_v1._stamp(now)
    if type(offline) is not bool:
        raise ValueError("offline must be a boolean")
    if offline:
        return {**_result([]), "offline": True, "safeLimit": 0,
                "failureStreak": _failure_streak(engine_state)}
    users, indexed_cards = _context_from_jobs(accounts, cards, projects)
    due = sorted(
        (job for job in engine_state["jobs"]
         if job["status"] in ("ready", "retry")
         and automation_v1._stamp(job["nextAttemptAt"]) <= clock),
        key=lambda job: (job["nextAttemptAt"], job["queuedAt"], job["eventId"]))
    failures = _failure_streak(engine_state)
    selected = due[:config["maxEvents"]]
    retries = 0
    decisions = []
    for job in selected:
        event = job["command"]
        ident = event["eventId"]
        project_id = job["projectId"]
        signature = event_signature(event, project_id)
        blocked = None
        if event["cardId"] not in indexed_cards or (
                indexed_cards[event["cardId"]]["projectId"] != project_id):
            blocked = "project_changed"
        elif job["attempts"] >= config["maxAttempts"]:
            blocked = "retry_exhausted"
        elif job["status"] == "retry":
            retries += 1
            if retries > config["maxRetriesPerBatch"]:
                blocked = "retry_budget"
        if blocked is not None:
            decisions.append(_decision(ident, signature, "block",
                                       blocked, _empty_preview()))
            continue
        actor = job["actor"]
        if actor not in users or not collab._permitted(
                users[actor], project_id, write=True):
            decisions.append(_decision(ident, signature, "block",
                                       "permission_denied", _empty_preview()))
            continue
        # The job is ALREADY in the journal. For in-flight queued jobs check
        # collaboration receipts only; queue receipt is not a duplicate.
        receipt = collab_state["receipts"].get(ident)
        if receipt is not None:
            if receipt["fingerprint"] != job["fingerprint"]:
                raise ValueError("Automation replay fingerprint collision")
            decisions.append(_decision(ident, signature, "duplicate",
                                       "collab_committed", _empty_preview()))
            continue
        trail = _ancestry(ancestry, ident, config)
        if len(trail) + 1 > config["maxChainDepth"]:
            decisions.append(_decision(ident, signature, "block",
                                       "chain_depth", _empty_preview()))
        elif trail.count(signature) + 1 > config["maxRepeatedSignature"]:
            decisions.append(_decision(ident, signature, "block",
                                       "repeated_signature", _empty_preview()))
        else:
            decisions.append(_decision(
                ident, signature, "allow", "ok",
                _rule_preview(collab_state, event, users, project_id)))
    bounded = _apply_budgets(decisions, config, failure_streak=failures)
    outcome = _result(bounded, deferred=len(due) - len(selected))
    # Dispositions generated here are for audit/inspection only; run_batch
    # must be coordinated by host in the SAME read/CAS lock.
    return {**outcome, "offline": False,
            "safeLimit": len(selected) if outcome["safeToExecute"] else 0,
            "failureStreak": failures}


def _context_from_jobs(accounts, cards, projects):
    # Let collab._context validate EVERY account/project/card against the
    # current host snapshot even when no queued actor remains available.
    users = collab._index(accounts, "username")
    if not users:
        raise ValueError("No accounts for preflight")
    actor = next(iter(users))
    return _context(actor, accounts, cards, projects)


def make_safety_audit(preflight, *, now, first_sequence=1,
                      previous_hash="0" * 64, policy=None):
    """Deterministic redacted tamper-*evident* hash chain (not a signed log).

    Never persist this independently of the host's durable audit/CAS.
    """
    config = validate_safety_policy(policy)
    stamp = automation_v1._iso(automation_v1._stamp(now).astimezone(timezone.utc))
    if type(first_sequence) is not int or not 1 <= first_sequence <= 2**63:
        raise ValueError("Invalid audit sequence")
    if not isinstance(previous_hash, str) or not _SHA256.fullmatch(previous_hash):
        raise ValueError("Invalid previous safety audit hash")
    if not isinstance(preflight, dict) or not isinstance(preflight.get("decisions"), list):
        raise ValueError("Invalid preflight input")
    decisions = preflight["decisions"]
    if len(decisions) > config["maxAuditPreview"]:
        raise ValueError("Safety audit preview limit exceeded")
    chain = []
    previous = previous_hash
    for index, entry in enumerate(decisions):
        if not isinstance(entry, dict) or (
                set(entry) != {"eventId", "signature", "outcome", "reason",
                               "matchedRules", "eligibleRules", "skippedScopeRules",
                               "actions", "commentActions", "notifyActions"}):
            raise ValueError("Invalid safety audit decision shape")
        automation_v1._id(entry["eventId"], "eventId")
        if not isinstance(entry["signature"], str) or not _SHA256.fullmatch(
                entry["signature"]):
            raise ValueError("Invalid safety audit signature")
        if (not isinstance(entry["outcome"], str) or
                entry["outcome"] not in _OUTCOMES or
                not isinstance(entry["reason"], str) or
                entry["reason"] not in _ALLOWED_REASONS):
            raise ValueError("Invalid safety audit decision")
        for field in ("matchedRules", "eligibleRules", "skippedScopeRules",
                      "actions", "commentActions", "notifyActions"):
            if type(entry[field]) is not int or not 0 <= entry[field] <= 500:
                raise ValueError("Invalid safety audit counts")
        sequence = first_sequence + index
        if sequence > 2**63:
            raise ValueError("Safety audit sequence exhausted")
        record = {"sequence": sequence, "at": stamp,
                  "eventId": entry["eventId"], "signature": entry["signature"],
                  "outcome": entry["outcome"], "reason": entry["reason"],
                  "matchedRules": entry["matchedRules"],
                  "eligibleRules": entry["eligibleRules"],
                  "skippedScopeRules": entry["skippedScopeRules"],
                  "actions": entry["actions"],
                  "commentActions": entry["commentActions"],
                  "notifyActions": entry["notifyActions"],
                  "previousHash": previous}
        record["hash"] = _digest(record)
        previous = record["hash"]
        chain.append(record)
    return {"records": chain, "nextSequence": first_sequence + len(chain),
            "lastHash": previous}


def verify_safety_audit(records, *, first_sequence=1,
                        previous_hash="0" * 64, expected_final_hash=None):
    """Validate a persisted bounded hash chain without executing anything.

    A hash chain detects accidental edits/reordering GIVEN a trusted expected
    head. An attacker who can rewrite both records and head can forge it:
    host must protect/sign the head and apply CAS/transactional persistence.
    """
    if not isinstance(records, list) or len(records) > automation_v1.MAX_AUDIT:
        raise ValueError("Invalid bounded safety audit records")
    if type(first_sequence) is not int or not 1 <= first_sequence <= 2**63:
        raise ValueError("Invalid first safety audit sequence")
    for name, value in (("previous_hash", previous_hash),
                        ("expected_final_hash", expected_final_hash)):
        if (value is not None and
                (not isinstance(value, str) or not _SHA256.fullmatch(value))):
            raise ValueError("Invalid " + name)
    previous = previous_hash
    known_keys = {
        "sequence", "at", "eventId", "signature", "outcome", "reason",
        "matchedRules", "eligibleRules", "skippedScopeRules",
        "actions", "commentActions", "notifyActions", "previousHash", "hash",
    }
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != known_keys:
            raise ValueError("Invalid safety audit record schema")
        if type(record["sequence"]) is not int or (
                record["sequence"] != first_sequence + index or
                record["sequence"] > 2**63):
            raise ValueError("Safety audit sequence mismatch")
        automation_v1._stamp(record["at"])
        automation_v1._id(record["eventId"], "eventId")
        if not isinstance(record["signature"], str) or not _SHA256.fullmatch(
                record["signature"]):
            raise ValueError("Invalid safety audit signature")
        if (not isinstance(record["outcome"], str) or
                record["outcome"] not in _OUTCOMES or
                not isinstance(record["reason"], str) or
                record["reason"] not in _ALLOWED_REASONS):
            raise ValueError("Invalid safety audit disposition")
        for field in ("matchedRules", "eligibleRules", "skippedScopeRules",
                      "actions", "commentActions", "notifyActions"):
            if type(record[field]) is not int or not 0 <= record[field] <= 500:
                raise ValueError("Invalid safety audit counts")
        if record["previousHash"] != previous or not isinstance(
                record["hash"], str) or not _SHA256.fullmatch(record["hash"]):
            raise ValueError("Safety audit chain link mismatch")
        content = {key: value for key, value in record.items() if key != "hash"}
        if _digest(content) != record["hash"]:
            raise ValueError("Safety audit digest mismatch")
        previous = record["hash"]
    if expected_final_hash is not None and previous != expected_final_hash:
        raise ValueError("Safety audit trusted head mismatch")
    return {"valid": True, "lastHash": previous,
            "nextSequence": first_sequence + len(records),
            "count": len(records)}


__all__ = [
    "DEFAULT_POLICY", "validate_safety_policy", "event_signature",
    "inspect_replay", "dry_run_events", "preflight_due_batch",
    "make_safety_audit", "verify_safety_audit",
]
