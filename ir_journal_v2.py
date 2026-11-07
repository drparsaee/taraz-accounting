"""Pure immutable multi-company RIAL journal/replay candidate, never host IO.

This does NOT alter the existing TOMAN ledger. Host authentication, atomic CAS,
durable append-only storage and verified external IDs are integration duties.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
import re

from ir_chart_model import (
    ChartSnapshot, PostingReference, validate_chart, validate_posting_reference,
)
from money_policy import (
    ACCOUNTING_CURRENCY, CompanyMoneyPolicy, MAX_RIAL, require_rial_amount,
    snapshot_sha256,
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_SHA = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
_ORIGIN = frozenset({"task", "card", "checklist", "independent"})
_GENESIS = "0" * 64
MAX_EVENTS = 20_000
MAX_CHART_EVIDENCE = 2_000
MAX_LINES = 100


class JournalV2Error(ValueError):
    """Rejected financial event or corrupt/unverifiable journal history."""


class JournalV2Conflict(JournalV2Error):
    """Stale CAS, reused event ID with another payload, or duplicate reversal."""


def _id(value: str, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise JournalV2Error("Invalid " + field)
    return value


def _date(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise JournalV2Error("Expected YYYY-MM-DD posting date")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise JournalV2Error("Invalid calendar posting date") from exc
    return value


def _sha(value: str, field: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise JournalV2Error("Invalid " + field)
    return value


@dataclass(frozen=True, slots=True)
class FiscalPeriod:
    company_id: str
    fiscal_period_id: str
    start_date: str
    end_date: str

    def __post_init__(self) -> None:
        _id(self.company_id, "period company")
        _id(self.fiscal_period_id, "period ID")
        _date(self.start_date)
        _date(self.end_date)
        if self.start_date > self.end_date:
            raise JournalV2Error("Fiscal period ends before it starts")


@dataclass(frozen=True, slots=True)
class JournalSource:
    """Business provenance, NOT proof of ownership without VerifiedScopes."""

    kind: str
    source_id: str
    project_id: str = ""
    task_id: str = ""
    checklist_id: str = ""

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in _ORIGIN:
            raise JournalV2Error("Unsupported business source kind")
        _id(self.source_id, "source ID")
        for field in ("project_id", "task_id", "checklist_id"):
            val = getattr(self, field)
            if type(val) is not str:
                raise JournalV2Error("Invalid source " + field)
            if val:
                _id(val, "source " + field)
        if self.kind in ("task", "card"):
            if not self.project_id or self.task_id != self.source_id or self.checklist_id:
                raise JournalV2Error("Task/card source requires explicit matching project and task IDs")
        elif self.kind == "checklist":
            if (not self.project_id or not self.task_id
                    or self.checklist_id != self.source_id):
                raise JournalV2Error("Checklist source requires matching checklist, task and project")
        elif self.task_id or self.checklist_id:
            raise JournalV2Error("Independent source cannot impersonate a task/checklist")


@dataclass(frozen=True, slots=True)
class VerifiedScopes:
    """Trusted host MUST supply verified membership, never client-selected sets."""

    party_ids: frozenset[str] = frozenset()
    project_ids: frozenset[str] = frozenset()
    task_scopes: frozenset[tuple[str, str]] = frozenset()
    checklist_scopes: frozenset[tuple[str, str, str]] = frozenset()
    # (project_id, document_id); empty project is an explicitly verified
    # unassigned company-wide document, NOT a wildcard for any project.
    independent_source_scopes: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self) -> None:
        for field in ("party_ids", "project_ids", "task_scopes",
                      "checklist_scopes", "independent_source_scopes"):
            if type(getattr(self, field)) is not frozenset:
                raise JournalV2Error("Verified scopes must be immutable frozensets")
        for field in ("party_ids", "project_ids"):
            for value in getattr(self, field):
                _id(value, field)
        for field, width in (("task_scopes", 2), ("checklist_scopes", 3)):
            for item in getattr(self, field):
                if type(item) is not tuple or len(item) != width:
                    raise JournalV2Error("Invalid verified tuple scope")
                for value in item:
                    _id(value, field)
        for row in self.independent_source_scopes:
            if type(row) is not tuple or len(row) != 2:
                raise JournalV2Error("Invalid independent project/document scope")
            project_id, document_id = row
            if project_id:
                _id(project_id, "independent project")
            elif type(project_id) is not str:
                raise JournalV2Error("Invalid independent project scope type")
            _id(document_id, "independent document")


def _scope_payload(scope: VerifiedScopes) -> dict:
    return {
        "party_ids": sorted(scope.party_ids),
        "project_ids": sorted(scope.project_ids),
        "task_scopes": sorted([list(item) for item in scope.task_scopes]),
        "checklist_scopes": sorted([list(item) for item in scope.checklist_scopes]),
        "independent_source_scopes": sorted(
            [list(item) for item in scope.independent_source_scopes]),
    }


def _lists(value):
    """JSON-safe representation of immutable chart tuples, never float coercion."""
    if type(value) is tuple:
        return [_lists(v) for v in value]
    if type(value) is list:
        return [_lists(v) for v in value]
    if type(value) is dict:
        return {k: _lists(v) for k, v in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class ChartEvidence:
    """Snapshot of chart and host attestation context retained for replay."""

    company_id: str
    chart: ChartSnapshot
    scopes: VerifiedScopes
    max_abs_rial: int
    evidence_digest: str


def _evidence(chart: ChartSnapshot, scopes: VerifiedScopes, company_id: str,
              max_abs_rial: int) -> ChartEvidence:
    if type(chart) is not ChartSnapshot or type(scopes) is not VerifiedScopes:
        raise JournalV2Error("Verified ChartSnapshot and VerifiedScopes are mandatory")
    if chart.company_id != company_id:
        raise JournalV2Error("Posting chart/company mismatch")
    if (type(max_abs_rial) is not int or
            not 1 <= max_abs_rial <= MAX_RIAL):
        raise JournalV2Error("Invalid authoritative RIAL policy ceiling")
    validate_chart(chart)
    content = {"companyId": company_id, "chart": _lists(asdict(chart)),
               "trustedScopes": _scope_payload(scopes), "maxAbsRial": max_abs_rial}
    return ChartEvidence(company_id, chart, scopes, max_abs_rial,
                         snapshot_sha256(content))


@dataclass(frozen=True, slots=True)
class JournalLine:
    reference: PostingReference
    debit_rial: int = 0
    credit_rial: int = 0

    def __post_init__(self) -> None:
        if type(self.reference) is not PostingReference:
            raise JournalV2Error("A full PostingReference is required for every line")
        require_rial_amount(self.debit_rial)
        require_rial_amount(self.credit_rial)
        if (self.debit_rial > 0) == (self.credit_rial > 0):
            raise JournalV2Error("Exactly one positive debit or credit per line")


@dataclass(frozen=True, slots=True)
class PostedJournal:
    event_id: str
    company_id: str
    fiscal_period_id: str
    actor_id: str
    posting_date: str
    source: JournalSource
    lines: tuple[JournalLine, ...]
    evidence_digest: str
    command_digest: str
    previous_hash: str
    event_hash: str
    reversal_of: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ClosedPeriod:
    event_id: str
    company_id: str
    fiscal_period_id: str
    actor_id: str
    closing_date: str
    command_digest: str
    previous_hash: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class JournalState:
    company_id: str
    currency: str
    periods: tuple[FiscalPeriod, ...]
    evidence: tuple[ChartEvidence, ...] = ()
    events: tuple[PostedJournal | ClosedPeriod, ...] = ()

    @property
    def revision(self) -> str:
        # A hash-linked event stream is summarized by its committed head.
        # Avoid a growing >1MB JSON list at 20,000 events; replay verifies
        # every predecessor and command before any operation accepts the state.
        return snapshot_sha256({
            "schema": "IR-JOURNAL-V2.1", "companyId": self.company_id,
            "currency": self.currency,
            "periods": [asdict(period) for period in self.periods],
            "evidence": [e.evidence_digest for e in self.evidence],
            "eventCount": len(self.events),
            "lastEventHash": self.events[-1].event_hash if self.events else _GENESIS,
        })


@dataclass(frozen=True, slots=True)
class AccountPosition:
    account_code: str
    debit_rial: int
    credit_rial: int
    debit_minus_credit_rial: int


@dataclass(frozen=True, slots=True)
class ReplayResult:
    company_id: str
    currency: str
    revision: str
    posted_count: int
    closed_period_ids: frozenset[str]
    reversed_event_ids: frozenset[str]
    positions: tuple[AccountPosition, ...]


def new_journal_state(company_id: str, periods: tuple[FiscalPeriod, ...]) -> JournalState:
    _id(company_id, "company")
    if type(periods) is not tuple or not periods or len(periods) > 1000:
        raise JournalV2Error("Explicit immutable fiscal periods required")
    periods = tuple(sorted(periods, key=lambda p: (p.start_date, p.fiscal_period_id)))
    ids = set()
    previous_end = None
    for period in periods:
        if type(period) is not FiscalPeriod or period.company_id != company_id:
            raise JournalV2Error("Foreign/malformed fiscal period")
        if period.fiscal_period_id in ids or (
                previous_end is not None and period.start_date <= previous_end):
            raise JournalV2Error("Duplicate or overlapping fiscal periods")
        ids.add(period.fiscal_period_id)
        previous_end = period.end_date
    return JournalState(company_id, ACCOUNTING_CURRENCY, periods)


def _source_allowed(source: JournalSource, scopes: VerifiedScopes) -> None:
    if type(source) is not JournalSource:
        raise JournalV2Error("Structured journal business source required")
    if source.project_id and source.project_id not in scopes.project_ids:
        raise JournalV2Error("Source project not host verified")
    if source.kind in ("task", "card") and (
            (source.project_id, source.task_id) not in scopes.task_scopes):
        raise JournalV2Error("Task/card source scope not host verified")
    if source.kind == "checklist" and (
            (source.project_id, source.task_id, source.checklist_id)
            not in scopes.checklist_scopes or
            (source.project_id, source.task_id) not in scopes.task_scopes):
        raise JournalV2Error("Checklist and owning task must be host verified")
    if source.kind == "independent" and (
            (source.project_id, source.source_id)
            not in scopes.independent_source_scopes):
        raise JournalV2Error("Independent document/project source not host verified")


def _validate_lines(lines: tuple[JournalLine, ...], source: JournalSource,
                    evidence: ChartEvidence, company_id: str,
                    max_rial: int) -> None:
    if type(lines) is not tuple or not 2 <= len(lines) <= MAX_LINES:
        raise JournalV2Error("Posting requires 2..100 immutable journal lines")
    _source_allowed(source, evidence.scopes)
    debit = credit = 0
    for line in lines:
        if type(line) is not JournalLine:
            raise JournalV2Error("Malformed journal line")
        if line.reference.company_id != company_id:
            raise JournalV2Error("Cross-company journal line")
        if source.project_id and line.reference.project_id != source.project_id:
            raise JournalV2Error("Line/project conflicts with source")
        if not source.project_id and line.reference.project_id:
            raise JournalV2Error("Project-tagged line requires matching source project")
        if source.kind in ("task", "card", "checklist"):
            if line.reference.task_id != source.task_id:
                raise JournalV2Error("Line task differs from referenced business source")
        # Chart validates account active/accountable/non-group, detail/party,
        # project/job/task scope and cost-center ownership with trusted IDs.
        validate_posting_reference(
            evidence.chart, line.reference,
            verified_party_ids=evidence.scopes.party_ids,
            verified_project_ids=evidence.scopes.project_ids,
            verified_task_scopes=evidence.scopes.task_scopes)
        debit += require_rial_amount(line.debit_rial, max_abs_rial=max_rial)
        credit += require_rial_amount(line.credit_rial, max_abs_rial=max_rial)
        require_rial_amount(debit, max_abs_rial=max_rial)
        require_rial_amount(credit, max_abs_rial=max_rial)
    if debit == 0 or debit != credit:
        raise JournalV2Error("Journal debit and credit totals must match and be positive")


def _journal_command(entry: PostedJournal) -> dict:
    return {
        "type": "journal.post", "eventId": entry.event_id,
        "companyId": entry.company_id, "fiscalPeriodId": entry.fiscal_period_id,
        "actorId": entry.actor_id, "postingDate": entry.posting_date,
        "source": asdict(entry.source),
        "lines": [asdict(line) for line in entry.lines],
        "evidenceDigest": entry.evidence_digest,
        "reversalOf": entry.reversal_of, "reason": entry.reason,
    }


def _closed_command(entry: ClosedPeriod) -> dict:
    return {
        "type": "period.close", "eventId": entry.event_id,
        "companyId": entry.company_id, "fiscalPeriodId": entry.fiscal_period_id,
        "actorId": entry.actor_id, "closingDate": entry.closing_date,
    }


def _event_hash(command: dict, previous_hash: str) -> str:
    return snapshot_sha256({
        "command": command, "previousHash": previous_hash,
        "commandDigest": snapshot_sha256(command),
    })


def replay_journal(state: JournalState) -> ReplayResult:
    """Recompute history. No cached balances trusted. Verify every chart context."""
    if type(state) is not JournalState:
        raise JournalV2Error("Invalid journal state type")
    baseline = new_journal_state(state.company_id, state.periods)
    if state.currency != "RIAL" or type(state.evidence) is not tuple or type(state.events) is not tuple:
        raise JournalV2Error("Malformed/foreign currency journal")
    if len(state.events) > MAX_EVENTS or len(state.evidence) > MAX_CHART_EVIDENCE:
        raise JournalV2Error("Journal replay bound exceeded")
    contexts = {}
    for item in state.evidence:
        if type(item) is not ChartEvidence or item.company_id != state.company_id:
            raise JournalV2Error("Corrupt or foreign historical chart evidence")
        rebuilt = _evidence(item.chart, item.scopes, state.company_id,
                            item.max_abs_rial)
        if item != rebuilt or item.evidence_digest in contexts:
            raise JournalV2Error("Modified/duplicated historical validation evidence")
        contexts[item.evidence_digest] = item
    period_by_id = {p.fiscal_period_id: p for p in state.periods}
    closed = set()
    seen = {}
    originals = {}
    reversed_ids = set()
    running = {}
    debit_totals = {}
    credit_totals = {}
    prev_hash = _GENESIS
    count = 0
    for event in state.events:
        if type(event) not in (PostedJournal, ClosedPeriod):
            raise JournalV2Error("Malformed historic event")
        if (event.company_id != state.company_id or
                event.fiscal_period_id not in period_by_id):
            raise JournalV2Error("Cross-company/unknown-period historic event")
        _id(event.event_id, "historic event ID")
        _id(event.actor_id, "historic actor ID")
        if event.event_id in seen:
            raise JournalV2Error("Duplicate historic journal event ID")
        if event.previous_hash != prev_hash:
            raise JournalV2Error("Journal hash chain predecessor mismatch")
        command = _journal_command(event) if type(event) is PostedJournal else _closed_command(event)
        if snapshot_sha256(command) != event.command_digest:
            raise JournalV2Error("Journal command digest mismatch")
        if _event_hash(command, event.previous_hash) != event.event_hash:
            raise JournalV2Error("Journal event hash mismatch")
        period = period_by_id[event.fiscal_period_id]
        if type(event) is ClosedPeriod:
            _date(event.closing_date)
            if event.fiscal_period_id in closed or event.closing_date < period.end_date:
                raise JournalV2Error("Invalid period-close event")
            if any(p.start_date < period.start_date and p.fiscal_period_id not in closed
                   for p in state.periods):
                raise JournalV2Error("Periods must close oldest open first")
            closed.add(period.fiscal_period_id)
        else:
            _date(event.posting_date)
            if (event.fiscal_period_id in closed or
                    not period.start_date <= event.posting_date <= period.end_date):
                raise JournalV2Error("Posting in closed/out-of-range fiscal period")
            evidence = contexts.get(event.evidence_digest)
            if evidence is None:
                raise JournalV2Error("Historic posting lost its verified chart evidence")
            _validate_lines(event.lines, event.source, evidence, state.company_id,
                            evidence.max_abs_rial)
            if event.reversal_of:
                _id(event.reversal_of, "reversal target")
                original = originals.get(event.reversal_of)
                if (original is None or original.reversal_of or
                        event.reversal_of in reversed_ids):
                    raise JournalV2Error("Missing or already reversed source posting")
                if (event.posting_date < original.posting_date or
                        event.source != original.source or
                        event.evidence_digest != original.evidence_digest or
                        event.lines != tuple(JournalLine(line.reference, line.credit_rial,
                                                         line.debit_rial)
                                            for line in original.lines) or
                        not event.reason.strip()):
                    raise JournalV2Error("Reversal must preserve source and invert original lines")
                reversed_ids.add(event.reversal_of)
            elif event.reason:
                raise JournalV2Error("Ordinary journal may not masquerade as a reversal")
            for line in event.lines:
                key = line.reference.account_code
                total = running.get(key, 0) + line.debit_rial - line.credit_rial
                require_rial_amount(total, allow_negative=True)
                running[key] = total
                d = debit_totals.get(key, 0) + line.debit_rial
                c = credit_totals.get(key, 0) + line.credit_rial
                require_rial_amount(d)
                require_rial_amount(c)
                debit_totals[key], credit_totals[key] = d, c
            count += 1
            originals[event.event_id] = event
        seen[event.event_id] = event
        prev_hash = event.event_hash
    # No mutable balance cache is embedded in the event stream.
    positions = tuple(AccountPosition(account, debit_totals[account],
                                      credit_totals[account], running[account])
                      for account in sorted(running))
    total_debit = sum(p.debit_rial for p in positions)
    total_credit = sum(p.credit_rial for p in positions)
    require_rial_amount(total_debit)
    require_rial_amount(total_credit)
    if total_debit != total_credit:
        raise JournalV2Error("Global double-entry invariant broken")
    return ReplayResult(baseline.company_id, "RIAL", state.revision, count,
                        frozenset(closed), frozenset(reversed_ids), positions)


def _cas(state: JournalState, expected_revision: str) -> None:
    _sha(expected_revision, "expected revision")
    if state.revision != expected_revision:
        raise JournalV2Conflict("Journal revision changed; refresh before posting")


def _existing(state: JournalState, event_id: str, command_digest: str) -> bool:
    for event in state.events:
        if event.event_id == event_id:
            if event.command_digest == command_digest:
                return True
            raise JournalV2Conflict("Same event ID reused with a conflicting payload")
    return False


def post_journal(
    state: JournalState, *, company_id: str, fiscal_period_id: str, event_id: str,
    actor_id: str, posting_date: str, source: JournalSource,
    lines: tuple[JournalLine, ...], chart: ChartSnapshot, scopes: VerifiedScopes,
    money_policy: CompanyMoneyPolicy, expected_revision: str, today: str,
) -> JournalState:
    """Exact idempotent post with chart & scopes and optimistic CAS; no IO."""
    replay_journal(state)
    _cas(state, expected_revision)
    _id(company_id, "company")
    _id(event_id, "event")
    _id(actor_id, "actor")
    _id(fiscal_period_id, "period")
    _date(posting_date)
    _date(today)
    if company_id != state.company_id or type(money_policy) is not CompanyMoneyPolicy:
        raise JournalV2Error("Foreign company/missing RIAL money policy")
    if money_policy.company_id != company_id or money_policy.accounting_currency != "RIAL":
        raise JournalV2Error("Posting requires matching canonical RIAL policy")
    evidence = _evidence(chart, scopes, company_id, money_policy.max_abs_rial)
    entry = PostedJournal(event_id, company_id, fiscal_period_id, actor_id,
                          posting_date, source, lines, evidence.evidence_digest,
                          "", "", "")
    command = _journal_command(entry)
    digest = snapshot_sha256(command)
    if _existing(state, event_id, digest):
        return state
    if len(state.events) >= MAX_EVENTS:
        raise JournalV2Error("Journal event capacity exceeded")
    if posting_date > today:
        raise JournalV2Error("Future posting forbidden")
    period = next((p for p in state.periods if p.fiscal_period_id == fiscal_period_id), None)
    if period is None or not period.start_date <= posting_date <= period.end_date:
        raise JournalV2Error("Posting date outside selected fiscal period")
    if fiscal_period_id in replay_journal(state).closed_period_ids:
        raise JournalV2Error("Cannot post into a closed period")
    _validate_lines(lines, source, evidence, company_id, money_policy.max_abs_rial)
    retained = next((e for e in state.evidence if e.evidence_digest == evidence.evidence_digest), None)
    if retained is None and len(state.evidence) >= MAX_CHART_EVIDENCE:
        raise JournalV2Error("Historic chart evidence capacity exceeded")
    previous = state.events[-1].event_hash if state.events else _GENESIS
    posted = replace(entry, command_digest=digest, previous_hash=previous,
                     event_hash=_event_hash(command, previous))
    result = replace(state, evidence=state.evidence if retained else
                     state.evidence + (evidence,), events=state.events + (posted,))
    replay_journal(result)
    return result


def close_fiscal_period(
    state: JournalState, *, company_id: str, fiscal_period_id: str,
    event_id: str, actor_id: str, closing_date: str,
    expected_revision: str, today: str,
) -> JournalState:
    prior = replay_journal(state)
    _cas(state, expected_revision)
    _id(event_id, "close event")
    _id(actor_id, "closer")
    _id(fiscal_period_id, "closed period")
    _date(closing_date)
    _date(today)
    if company_id != state.company_id:
        raise JournalV2Error("Cannot close another company's period")
    event = ClosedPeriod(event_id, company_id, fiscal_period_id, actor_id,
                         closing_date, "", "", "")
    command = _closed_command(event)
    digest = snapshot_sha256(command)
    if _existing(state, event_id, digest):
        return state
    period = next((p for p in state.periods if p.fiscal_period_id == fiscal_period_id), None)
    if period is None or period.fiscal_period_id in prior.closed_period_ids:
        raise JournalV2Error("Period is missing or already closed")
    if (closing_date < period.end_date or closing_date > today or
            any(p.start_date < period.start_date and
                p.fiscal_period_id not in prior.closed_period_ids for p in state.periods)):
        raise JournalV2Error("Close entire finished period in chronological order")
    if len(state.events) >= MAX_EVENTS:
        raise JournalV2Error("Journal event capacity exceeded")
    previous = state.events[-1].event_hash if state.events else _GENESIS
    closed = replace(event, command_digest=digest, previous_hash=previous,
                     event_hash=_event_hash(command, previous))
    result = replace(state, events=state.events + (closed,))
    replay_journal(result)
    return result


def reverse_journal(
    state: JournalState, *, company_id: str, original_event_id: str,
    event_id: str, actor_id: str, fiscal_period_id: str,
    posting_date: str, reason: str, expected_revision: str, today: str,
) -> JournalState:
    """Append exact inverse as a NEW event, including for historic archived accounts."""
    prior = replay_journal(state)
    _cas(state, expected_revision)
    _id(original_event_id, "original event")
    _id(event_id, "reversal event")
    _id(actor_id, "reverser")
    _id(fiscal_period_id, "reversal period")
    _date(posting_date)
    _date(today)
    if company_id != state.company_id:
        raise JournalV2Error("Cross-company reversal forbidden")
    if type(reason) is not str or not reason.strip() or len(reason) > 1000 or (
            any(ord(char) < 32 or ord(char) == 127 for char in reason)):
        raise JournalV2Error("Reversal reason must be explicit readable text")
    original = next((e for e in state.events if type(e) is PostedJournal and
                     e.event_id == original_event_id), None)
    if original is None or original.reversal_of:
        raise JournalV2Error("Original posting absent or reversal-of-reversal forbidden")
    inverted = tuple(JournalLine(line.reference, line.credit_rial, line.debit_rial)
                     for line in original.lines)
    command_entry = PostedJournal(event_id, company_id, fiscal_period_id,
                                  actor_id, posting_date, original.source, inverted,
                                  original.evidence_digest, "", "", "",
                                  reversal_of=original_event_id, reason=reason)
    command = _journal_command(command_entry)
    digest = snapshot_sha256(command)
    if _existing(state, event_id, digest):
        return state
    if original_event_id in prior.reversed_event_ids:
        raise JournalV2Conflict("Original journal was already reversed")
    if posting_date < original.posting_date or posting_date > today:
        raise JournalV2Error("Reversal may not be backdated before original/future")
    period = next((p for p in state.periods if p.fiscal_period_id == fiscal_period_id), None)
    if period is None or fiscal_period_id in prior.closed_period_ids or (
            not period.start_date <= posting_date <= period.end_date):
        raise JournalV2Error("Reversal requires an open and in-range fiscal period")
    if len(state.events) >= MAX_EVENTS:
        raise JournalV2Error("Journal event capacity exceeded")
    previous = state.events[-1].event_hash if state.events else _GENESIS
    reversal = replace(command_entry, command_digest=digest, previous_hash=previous,
                       event_hash=_event_hash(command, previous))
    result = replace(state, events=state.events + (reversal,))
    replay_journal(result)
    return result


__all__ = [
    "JournalV2Error", "JournalV2Conflict", "FiscalPeriod", "JournalSource",
    "VerifiedScopes", "ChartEvidence", "JournalLine", "PostedJournal",
    "ClosedPeriod", "JournalState", "AccountPosition", "ReplayResult",
    "new_journal_state", "replay_journal", "post_journal",
    "close_fiscal_period", "reverse_journal",
]
