"""M07 opt-in SQLite host automation preflight.

Pure orchestrator only. The caller supplies an authoritative already-locked
single-revision bundle and must CAS-commit its result. No database, clock,
filesystem, network, finance or arbitrary code side effects.

This layer does not yet persist independent causal ancestry or signed audit.
It is a bounded fail-closed gate, not full M07 acceptance.
"""
from __future__ import annotations

from datetime import date

import automation_v1
from rule_safety import (
    DEFAULT_POLICY, dry_run_events, preflight_due_batch,
)


class SafetyHold(RuntimeError):
    """No mutation is returned when a reviewed automation batch is unsafe."""


def _guard(preflight):
    if not preflight["safeToExecute"]:
        reasons = sorted({
            item["reason"] for item in preflight["decisions"]
            if item["outcome"] == "block"
        })
        # Only allowlisted reason codes, never card data or financial amounts.
        raise SafetyHold("AUTOMATION_SAFETY_HOLD:" + ",".join(reasons))


def _execute(queued_engine, collaboration, *, accounts, cards, projects, now):
    preflight = preflight_due_batch(
        queued_engine, collaboration, accounts=accounts, cards=cards,
        projects=projects, now=now, policy=DEFAULT_POLICY)
    _guard(preflight)
    if not preflight["safeLimit"]:
        return {
            "state": queued_engine, "collab": collaboration,
            "processed": 0, "applied": 0, "replayed": 0,
            "retried": 0, "dead": 0,
        }
    return automation_v1.run_batch(
        queued_engine, collaboration,
        accounts=accounts, cards=cards, projects=projects, now=now,
        limit=preflight["safeLimit"],
        max_attempts=DEFAULT_POLICY["maxAttempts"],
    )


def safe_card_events(bundle, events, *, actor, accounts, cards, projects, now):
    """Preview incoming card events, enqueue and execute within one host CAS."""
    if not isinstance(events, list):
        raise ValueError("Invalid automation events batch")
    if not events:
        return {"bundle": bundle, "added": 0, "processed": 0}
    preview = dry_run_events(
        bundle["automation"], bundle["collab"], events,
        actor=actor, accounts=accounts, cards=cards,
        projects=projects, now=now, policy=DEFAULT_POLICY,
    )
    _guard(preview)
    queued = automation_v1.enqueue_events(
        bundle["automation"], events, actor=actor, accounts=accounts,
        cards=cards, projects=projects, now=now,
    )
    batch = _execute(
        queued["state"], bundle["collab"], accounts=accounts,
        cards=cards, projects=projects, now=now)
    return {
        "bundle": {**bundle, "automation": batch["state"],
                   "collab": batch["collab"]},
        "added": queued["added"], "processed": batch["processed"],
    }


def safe_due_tick(bundle, *, actor, accounts, cards, projects, today, now):
    """Generate the same due events as legacy; dry run before any dispatch."""
    if not isinstance(today, date):
        raise ValueError("Invalid trusted today")
    events = automation_v1.due_events(cards, today=today)
    preview = dry_run_events(
        bundle["automation"], bundle["collab"], events,
        actor=actor, accounts=accounts, cards=cards,
        projects=projects, now=now, policy=DEFAULT_POLICY,
    )
    _guard(preview)
    queued = automation_v1.enqueue_events(
        bundle["automation"], events, actor=actor, accounts=accounts,
        cards=cards, projects=projects, now=now,
    )
    batch = _execute(
        queued["state"], bundle["collab"], accounts=accounts,
        cards=cards, projects=projects, now=now,
    )
    return {
        "bundle": {**bundle, "automation": batch["state"],
                   "collab": batch["collab"]},
        "added": queued["added"],
        "processed": batch["processed"],
        "applied": batch["applied"], "replayed": batch["replayed"],
        "retried": batch["retried"], "dead": batch["dead"],
        "pending": len(batch["state"]["jobs"]),
    }
