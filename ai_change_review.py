"""Pure M-10 AI task-change preflight and human review.

No file/database/network/clock access. All identities, role/project grants,
revisions, budgets, timestamps, and committed receipts belong to the host.
The functions return inspectable candidate data and *commit intents*, never
durably apply a change or claim that audit/charging occurred.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re


SCHEMA_VERSION = 1
MAX_CHANGES = 3
MAX_TASK_BYTES = 131_072
MAX_PROPOSAL_BYTES = 16_384
MAX_EVIDENCE = 8
MAX_TOTAL_TOKENS = 100_000
MAX_CREDITS = 10**9
MAX_REVIEW_AGE = timedelta(hours=24)
# Completion/status transitions can trigger billing/automation in the host.
# Explicitly exclude them until side-effect isolation is independently verified.
EDITABLE_FIELDS = frozenset(("title", "priority", "dueDate"))
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_SHA = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
_BIDI = frozenset(("\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
                   "\u2066", "\u2067", "\u2068", "\u2069"))


class ReviewError(ValueError):
    """Fail-closed, stable error code for a rejected proposal or approval."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _check(condition, code):
    if not condition:
        raise ReviewError(code)


def _id(value):
    _check(type(value) is str and _ID.fullmatch(value) is not None, "invalid_id")
    return value


def _sha(value):
    _check(type(value) is str and _SHA.fullmatch(value) is not None, "invalid_digest")
    return value


def _exact(record, keys, code):
    _check(type(record) is dict and set(record) == set(keys), code)
    return record


def _safe_text(value, max_length, *, allow_empty=False):
    _check(type(value) is str and len(value) <= max_length, "invalid_text")
    _check(allow_empty or bool(value.strip()), "invalid_text")
    _check(not any(ord(c) < 32 or ord(c) == 127 or c in _BIDI for c in value),
           "invalid_text")
    return value


def _timestamp(value):
    _check(type(value) is str and len(value) <= 40 and ("T" in value), "invalid_time")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewError("invalid_time") from exc
    _check(dt.tzinfo is not None and dt.utcoffset() is not None, "invalid_time")
    return dt.astimezone(timezone.utc)


def _date_or_empty(value):
    _safe_text(value, 10, allow_empty=True)
    if value == "":
        return value
    _check(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None, "invalid_date")
    try:
        _check(datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") == value,
               "invalid_date")
    except ValueError as exc:
        raise ReviewError("invalid_date") from exc
    return value


def _canonical(value, limit, code):
    try:
        content = json.dumps(value, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ReviewError(code) from exc
    _check(len(content) <= limit, code)
    return content


def decode_proposal_json(raw):
    """Strict, size-bounded UTF-8 JSON decoder with duplicate-key rejection."""
    _check(type(raw) in (str, bytes), "invalid_json")
    try:
        source = raw.encode("utf-8") if type(raw) is str else raw
        _check(len(source) <= MAX_PROPOSAL_BYTES, "proposal_too_large")
        text = source.decode("utf-8")
    except UnicodeError as exc:
        raise ReviewError("invalid_json") from exc

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            _check(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    def no_constant(_value):
        raise ReviewError("invalid_json")

    try:
        result = json.loads(text, object_pairs_hook=unique_pairs,
                            parse_constant=no_constant)
    except ReviewError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise ReviewError("invalid_json") from exc
    _check(type(result) is dict, "invalid_json")
    return result


def _digest(value, limit=MAX_PROPOSAL_BYTES):
    return hashlib.sha256(_canonical(value, limit, "invalid_payload")).hexdigest()


def _task_digest(task):
    _check(type(task) is dict, "invalid_task")
    return hashlib.sha256(_canonical(task, MAX_TASK_BYTES, "invalid_task")).hexdigest()


def _task(task, task_id, project_id):
    _check(type(task) is dict and task.get("id") == task_id
           and task.get("projectId") == project_id, "task_mismatch")
    _check(task.get("deleted", False) is False and
           task.get("archived", False) is False,
           "inactive_task")
    for field in EDITABLE_FIELDS:
        if field in task:
            _check(type(task[field]) is str, "invalid_task")
    _check(bool(task.get("title", "").strip()), "invalid_task")
    _task_digest(task)


def _granted(project_id, *, opt_in, can_edit, project_grants):
    _check(opt_in is True, "opt_in_required")
    _check(can_edit is True, "permission_denied")
    _check(type(project_grants) in (tuple, list, set, frozenset)
           and len(project_grants) <= 2000
           and all(type(g) is str and _ID.fullmatch(g) is not None for g in project_grants)
           and project_id in project_grants, "project_denied")


def _budget(budget, usage):
    _exact(budget, ("perProposalMaxCredits", "remainingCredits", "maxTotalTokens"),
           "invalid_budget")
    _exact(usage, ("inputTokens", "outputTokens", "estimatedCredits"), "invalid_usage")
    for value in budget.values():
        _check(type(value) is int and 0 <= value <= MAX_CREDITS, "invalid_budget")
    _check(budget["maxTotalTokens"] <= MAX_TOTAL_TOKENS, "invalid_budget")
    for name, value in usage.items():
        upper = MAX_CREDITS if name == "estimatedCredits" else MAX_TOTAL_TOKENS
        _check(type(value) is int and 0 <= value <= upper, "invalid_usage")
    _check(usage["inputTokens"] + usage["outputTokens"] > 0, "invalid_usage")
    _check(usage["inputTokens"] + usage["outputTokens"] <= budget["maxTotalTokens"],
           "token_cap_exceeded")
    _check(usage["estimatedCredits"] <= budget["perProposalMaxCredits"]
           and usage["estimatedCredits"] <= budget["remainingCredits"],
           "budget_exceeded")


def _provenance(value, now):
    _exact(value, ("source", "provider", "model", "inputSha256",
                   "evidenceIds", "generatedAt"), "invalid_provenance")
    _check(value["source"] == "ai", "invalid_provenance")
    provider = _safe_text(value["provider"], 80)
    model = _safe_text(value["model"], 120)
    prompt_hash = _sha(value["inputSha256"])
    evidence = value["evidenceIds"]
    _check(type(evidence) is list and len(evidence) <= MAX_EVIDENCE,
           "invalid_provenance")
    evidence_ids = tuple(_id(item) for item in evidence)
    _check(len(evidence_ids) == len(set(evidence_ids)), "invalid_provenance")
    generated = _timestamp(value["generatedAt"])
    _check(timedelta(0) <= now - generated <= MAX_REVIEW_AGE, "stale_proposal")
    return Provenance(provider, model, prompt_hash, evidence_ids, value["generatedAt"])


def _field(field, value, *, priorities):
    _check(field in EDITABLE_FIELDS and type(value) is str, "disallowed_field")
    if field == "title":
        return _safe_text(value, 160).strip()
    if field == "dueDate":
        return _date_or_empty(value)
    if field == "priority":
        _check(value in priorities, "invalid_priority")
    return _safe_text(value, 100)


def _allowed_values(values, label):
    _check(type(values) in (tuple, list, frozenset, set)
           and 1 <= len(values) <= 200 and all(type(v) is str
           and 1 <= len(v) <= 100 for v in values), "invalid_" + label)
    return frozenset(values)


@dataclass(frozen=True, slots=True)
class Provenance:
    provider: str
    model: str
    input_sha256: str
    evidence_ids: tuple[str, ...]
    generated_at: str


@dataclass(frozen=True, slots=True)
class FieldDiff:
    field: str
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class ChangePlan:
    proposal_id: str
    task_id: str
    project_id: str
    revision: str
    task_sha256: str
    changes: tuple[FieldDiff, ...]
    provenance: Provenance
    input_tokens: int
    output_tokens: int
    estimated_credits: int
    digest: str


@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    approval_id: str
    proposal_id: str
    task_id: str
    project_id: str
    reviewer: str
    source_revision: str
    source_task_sha256: str
    planned_task_sha256: str
    approved_at: str
    plan_digest: str
    changes: tuple[FieldDiff, ...]
    charged_credits: int


@dataclass(frozen=True, slots=True)
class ApprovalIntent:
    """Host must commit candidate task + receipt + audit + budget atomically."""
    candidate_task: dict
    receipt: ApprovalReceipt
    budget_remaining_credits: int
    audit: dict


@dataclass(frozen=True, slots=True)
class UndoPlan:
    """No mutation: requires another authenticated approval and CAS in host."""
    receipt_id: str
    task_id: str
    project_id: str
    expected_revision: str
    current_task_sha256: str
    changes: tuple[FieldDiff, ...]
    digest: str


def _plan_payload(plan):
    return {
        "proposalId": plan.proposal_id, "taskId": plan.task_id,
        "projectId": plan.project_id, "revision": plan.revision,
        "taskSha256": plan.task_sha256,
        "changes": [(d.field, d.before, d.after) for d in plan.changes],
        "provenance": [plan.provenance.provider, plan.provenance.model,
                       plan.provenance.input_sha256, plan.provenance.evidence_ids,
                       plan.provenance.generated_at],
        "usage": [plan.input_tokens, plan.output_tokens, plan.estimated_credits],
    }


def validate_proposal(proposal, *, task, revision, opt_in, can_edit,
                      project_grants, priorities, budget, now):
    """Create an immutable, inspectable plan for up to three safe task fields."""
    _exact(proposal, ("schemaVersion", "proposalId", "taskId", "projectId",
                      "expectedRevision", "changes", "provenance", "usage"),
           "invalid_proposal")
    _canonical(proposal, MAX_PROPOSAL_BYTES, "proposal_too_large")
    _check(type(proposal["schemaVersion"]) is int
           and proposal["schemaVersion"] == SCHEMA_VERSION, "invalid_proposal")
    pid, tid, proj = (_id(proposal[k]) for k in
                      ("proposalId", "taskId", "projectId"))
    source_rev = _sha(proposal["expectedRevision"])
    _check(_sha(revision) == source_rev, "revision_conflict")
    _granted(proj, opt_in=opt_in, can_edit=can_edit, project_grants=project_grants)
    _task(task, tid, proj)
    priority_ids = _allowed_values(priorities, "priorities")
    clock = _timestamp(now)
    provenance = _provenance(proposal["provenance"], clock)
    _budget(budget, proposal["usage"])
    edits = proposal["changes"]
    _check(type(edits) is dict and 1 <= len(edits) <= MAX_CHANGES
           and set(edits).issubset(EDITABLE_FIELDS), "disallowed_field")
    changes = []
    for field in sorted(edits):
        before = task.get(field, "" if field == "dueDate" else None)
        _check(type(before) is str, "invalid_task")
        after = _field(field, edits[field], priorities=priority_ids)
        _check(before != after, "no_effect")
        changes.append(FieldDiff(field, before, after))
    usage = proposal["usage"]
    raw = ChangePlan(pid, tid, proj, source_rev, _task_digest(task),
                     tuple(changes), provenance, usage["inputTokens"],
                     usage["outputTokens"], usage["estimatedCredits"], "")
    return ChangePlan(pid, tid, proj, source_rev, raw.task_sha256,
                      raw.changes, provenance, raw.input_tokens,
                      raw.output_tokens, raw.estimated_credits,
                      _digest(_plan_payload(raw)))


def _check_plan(plan):
    _check(type(plan) is ChangePlan, "invalid_plan")
    _check(type(plan.provenance) is Provenance and type(plan.changes) is tuple
           and all(type(c) is FieldDiff for c in plan.changes)
           and type(plan.input_tokens) is int and type(plan.output_tokens) is int
           and type(plan.estimated_credits) is int, "invalid_plan")
    _check(1 <= len(plan.changes) <= MAX_CHANGES
           and len({c.field for c in plan.changes}) == len(plan.changes)
           and all(c.field in EDITABLE_FIELDS and type(c.before) is str
                   and type(c.after) is str for c in plan.changes), "invalid_plan")
    _check(_sha(plan.digest) == _digest(_plan_payload(plan)), "plan_tampered")


def approve_plan(plan, *, task, revision, approval, reviewer, opt_in, can_edit,
                 project_grants, budget, now):
    """Return candidate task and ledger/audit intents, never perform a write."""
    _check_plan(plan)
    _granted(plan.project_id, opt_in=opt_in, can_edit=can_edit,
             project_grants=project_grants)
    _task(task, plan.task_id, plan.project_id)
    _check(_sha(revision) == plan.revision, "revision_conflict")
    _check(_task_digest(task) == plan.task_sha256, "task_conflict")
    _check(timedelta(0) <= _timestamp(now) - _timestamp(plan.provenance.generated_at)
           <= MAX_REVIEW_AGE, "stale_proposal")
    _check(type(approval) is dict and set(approval) ==
           {"decision", "planDigest", "reviewer", "approvalId"}, "approval_required")
    _check(approval["decision"] == "approve" and type(reviewer) is str,
           "approval_required")
    _id(reviewer)
    _check(approval["reviewer"] == reviewer, "approval_identity_mismatch")
    _id(approval["approvalId"])
    _check(approval["planDigest"] == plan.digest, "approval_plan_mismatch")
    _budget(budget, {"inputTokens": plan.input_tokens,
                     "outputTokens": plan.output_tokens,
                     "estimatedCredits": plan.estimated_credits})
    candidate = deepcopy(task)
    for change in plan.changes:
        _check(task.get(change.field, "" if change.field == "dueDate" else None)
               == change.before, "task_conflict")
        candidate[change.field] = change.after
    next_task_digest = _task_digest(candidate)
    receipt = ApprovalReceipt(approval["approvalId"], plan.proposal_id,
                              plan.task_id, plan.project_id, reviewer,
                              plan.revision, plan.task_sha256, next_task_digest,
                              now, plan.digest, plan.changes, plan.estimated_credits)
    audit = {
        "kind": "ai.task.change.approved.intent", "approvalId": receipt.approval_id,
        "proposalId": receipt.proposal_id, "taskId": receipt.task_id,
        "projectId": receipt.project_id, "reviewer": reviewer,
        "sourceRevision": plan.revision, "planDigest": plan.digest,
        "changedFields": [change.field for change in plan.changes],
        "inputSha256": plan.provenance.input_sha256,
        "provider": plan.provenance.provider, "model": plan.provenance.model,
        "evidenceIds": list(plan.provenance.evidence_ids),
        "estimatedCredits": plan.estimated_credits, "at": now,
    }
    return ApprovalIntent(candidate, receipt,
                          budget["remainingCredits"] - plan.estimated_credits,
                          audit)


def plan_undo(receipt, *, committed_revision, task, revision, persisted,
              opt_in, can_edit, project_grants):
    """Plan a compensating edit only for an already-persisted approved receipt.

    The returned UndoPlan is *not* executable authorization. Host must confirm
    receipt durability/identity, reauthenticate human, obtain a NEW approval,
    and CAS-commit reversal with a separate audit/idempotency receipt.
    """
    _check(type(receipt) is ApprovalReceipt, "invalid_receipt")
    _check(persisted is True, "uncommitted_approval")
    _id(receipt.approval_id)
    _id(receipt.proposal_id)
    _id(receipt.task_id)
    _id(receipt.project_id)
    _id(receipt.reviewer)
    _sha(receipt.source_revision)
    _sha(receipt.source_task_sha256)
    _sha(receipt.planned_task_sha256)
    _sha(receipt.plan_digest)
    _timestamp(receipt.approved_at)
    _check(type(receipt.charged_credits) is int
           and 0 <= receipt.charged_credits <= MAX_CREDITS,
           "invalid_receipt")
    _granted(receipt.project_id, opt_in=opt_in, can_edit=can_edit,
             project_grants=project_grants)
    _task(task, receipt.task_id, receipt.project_id)
    _check(_sha(revision) == _sha(committed_revision), "revision_conflict")
    _check(_task_digest(task) == receipt.planned_task_sha256, "task_conflict")
    _check(type(receipt.changes) is tuple and
           1 <= len(receipt.changes) <= MAX_CHANGES and
           len({c.field for c in receipt.changes if type(c) is FieldDiff})
           == len(receipt.changes) and
           all(type(c) is FieldDiff and c.field in EDITABLE_FIELDS
               and type(c.before) is str and type(c.after) is str
               for c in receipt.changes), "invalid_receipt")
    changes = tuple(FieldDiff(c.field, c.after, c.before) for c in receipt.changes)
    for change in changes:
        _check(task.get(change.field) == change.before, "task_conflict")
    payload = [receipt.approval_id, receipt.plan_digest, revision,
               _task_digest(task), [(c.field, c.before, c.after) for c in changes]]
    return UndoPlan(receipt.approval_id, receipt.task_id, receipt.project_id,
                    revision, _task_digest(task), changes, _digest(payload))


__all__ = ["SCHEMA_VERSION", "EDITABLE_FIELDS", "ReviewError", "FieldDiff",
           "Provenance", "ChangePlan", "ApprovalReceipt", "ApprovalIntent",
           "UndoPlan", "decode_proposal_json", "validate_proposal",
           "approve_plan", "plan_undo"]
