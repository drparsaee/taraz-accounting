"""Pure, conservative cheque -> immutable RIAL journal bridge.

Host MUST verify dates, cheque identity/ownership, accrual provenance, and
commit the combined cheque+finance snapshots atomically. No IO is performed.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from ir_chart_model import ChartSnapshot, PostingReference, validate_chart, validate_posting_reference
from ir_journal_v2 import (
    JournalLine, JournalSource, JournalState, PostedJournal, VerifiedScopes,
    post_journal, replay_journal,
)
from ir_treasury_cheques import ChequeCommand, ChequePosition, ChequeState, replay_cheques
from money_policy import CompanyMoneyPolicy, require_rial_amount, snapshot_sha256


class ChequeGLError(ValueError):
    """Mapping, historical provenance, period or scope has not been established."""


class ChequeGLConflict(ChequeGLError):
    """Duplicate source, contradictory previously posted stage or stale revision."""


_ASSET = "asset"
_LIABILITY = "liability"
_ROLE_KINDS = {
    "in_hand": _ASSET, "transferred": _ASSET, "deposited": _ASSET,
    "bank": _ASSET, "ar": _ASSET, "ap": _LIABILITY,
    "returned": _ASSET, "payable": _LIABILITY,
}
_MEMO = frozenset({"PRESENT", "REPRESENT"})


@dataclass(frozen=True, slots=True)
class ChequeGLAccounts:
    """Explicit company/cheque-specific references; no fallback account lookup.

    The bank mapping is pinned to one specific verified *company* bank account.
    Optional references are allowed only when not required for a given action.
    """

    company_id: str
    cheque_id: str
    party_id: str
    bank_id: str
    bank_account_id: str
    in_hand: PostingReference | None = None
    transferred: PostingReference | None = None
    deposited: PostingReference | None = None
    bank: PostingReference | None = None
    ar: PostingReference | None = None
    ap: PostingReference | None = None
    returned: PostingReference | None = None
    payable: PostingReference | None = None
    supplier_party_id: str = ""


@dataclass(frozen=True, slots=True)
class VerifiedChequeGLContext:
    """Host attestation input, NOT proof by itself.

    The host must confirm this date pair, instrument, bank account, ownership,
    original AR/AP accrual, fiscal period and ledger recording stage.
    """

    company_id: str
    cheque_id: str
    cheque_event_id: str
    jalali_event_date: str
    gregorian_posting_date: str
    fiscal_period_id: str
    actor_id: str
    prior_ar_ap_accrued: bool
    transfer_policy: str = "UNSPECIFIED"


@dataclass(frozen=True, slots=True)
class ChequeJournalProposal:
    company_id: str
    cheque_id: str
    cheque_event_id: str
    cheque_event_hash: str
    cheque_revision: str
    journal_revision: str
    fiscal_period_id: str
    actor_id: str
    posting_date: str
    action: str
    source: JournalSource
    event_id: str
    lines: tuple[JournalLine, JournalLine]
    amount_rial: int
    cash_effect: str


def _ids(company_id: str, cheque_id: str, cheque_event_id: str) -> tuple[str, str]:
    """Stable business and journal IDs, unaffected by party labels or event payload."""
    for value in (company_id, cheque_id, cheque_event_id):
        if type(value) is not str or not value:
            raise ChequeGLError("Explicit cheque business identity required")
    digest = snapshot_sha256({
        "domain": "madar.cheque.gl.v1",
        "companyId": company_id,
        "chequeId": cheque_id,
        "chequeEventId": cheque_event_id,
    })
    return "chq." + digest, "chqsrc." + digest


def cheque_journal_source_id(company_id: str, cheque_id: str,
                             cheque_event_id: str) -> str:
    return _ids(company_id, cheque_id, cheque_event_id)[1]


def _event(state: ChequeState, event_id: str):
    if type(state) is not ChequeState or type(event_id) is not str:
        raise ChequeGLError("Immutable cheque snapshot and event ID required")
    replay_cheques(state)
    for index, entry in enumerate(state.events):
        if entry.command.event_id == event_id:
            return index, entry
    raise ChequeGLError("Cheque event does not exist in verified history")


def _prior_position(state: ChequeState, index: int) -> ChequePosition | None:
    if index == 0:
        return None
    replay = replay_cheques(replace(state, events=state.events[:index]))
    target = state.events[index].command.cheque_id
    return next((p for p in replay.positions if p.instrument.cheque_id == target), None)


def _stage_roles(command: ChequeCommand, prior: ChequePosition | None,
                 *, transfer_policy: str) -> tuple[str, str] | None:
    """Return debit role, credit role. Unknown or ambiguous stages fail shut."""
    action = command.action
    if action in ("RECEIVE", "ISSUE"):
        if prior is not None:
            raise ChequeGLError("Repeated instrument creation")
        if action == "RECEIVE":
            return "in_hand", "ar"
        return "ap", "payable"
    if prior is None:
        raise ChequeGLError("Missing previously registered cheque")
    direction = prior.instrument.direction
    status = prior.status
    if direction == "RECEIVABLE":
        stages = {
            ("RECEIVED", "DEPOSIT"): ("deposited", "in_hand"),
            ("DEPOSITED", "CLEAR"): ("bank", "deposited"),
            ("DEPOSITED", "BOUNCE"): ("returned", "deposited"),
            ("BOUNCED", "REDEPOSIT"): ("deposited", "returned"),
            ("RECEIVED", "RETURN"): ("ar", "in_hand"),
            ("BOUNCED", "RETURN"): ("ar", "returned"),
        }
        if action == "ENDORSE" and status == "RECEIVED":
            if transfer_policy != "PENDING_TRANSFER_ONLY":
                raise ChequeGLError("No explicit pending endorsement GL policy")
            return "transferred", "in_hand"
        if action == "RETURN" and status == "ENDORSED":
            raise ChequeGLError("Endorsed return requires a new settlement/ownership workflow")
        if action == "REVERSE":
            return _reverse_roles(prior, "RECEIVABLE", command)
    elif direction == "PAYABLE":
        stages = {
            ("ISSUED", "PRESENT"): None,
            ("PRESENTED", "CLEAR"): ("payable", "bank"),
            ("PRESENTED", "BOUNCE"): None,
            ("BOUNCED", "REPRESENT"): None,
            ("ISSUED", "RETURN"): ("payable", "ap"),
            ("BOUNCED", "RETURN"): ("payable", "ap"),
            ("ISSUED", "CANCEL"): ("payable", "ap"),
        }
        if action == "REVERSE":
            return _reverse_roles(prior, "PAYABLE", command)
    else:
        raise ChequeGLError("Unknown cheque direction")
    key = status, action
    if key not in stages:
        raise ChequeGLError("No approved accounting treatment for transition")
    return stages[key]


def _reverse_roles(prior: ChequePosition, direction: str,
                   command: ChequeCommand) -> tuple[str, str] | None:
    if command.reverses_event_id != prior.active_event_id:
        raise ChequeGLError("Reversal target does not match latest active action")
    action = prior.active_action
    if direction == "RECEIVABLE":
        return {
            "DEPOSIT": ("in_hand", "deposited"),
            "BOUNCE": ("deposited", "returned"),
            "REDEPOSIT": ("returned", "deposited"),
        }.get(action) or _raise_unknown_reversal()
    if action in ("PRESENT", "REPRESENT", "BOUNCE"):
        return None
    raise ChequeGLError("Payable reversal has no approved treatment")


def _raise_unknown_reversal():
    raise ChequeGLError("Unrecognized reversible cheque accounting stage")


def _reference_map(mapping: ChequeGLAccounts, role: str, *,
                   command: ChequeCommand, chart: ChartSnapshot,
                   scopes: VerifiedScopes) -> PostingReference:
    ref = getattr(mapping, role)
    if type(ref) is not PostingReference:
        raise ChequeGLError("Missing explicit " + role + " account reference")
    if ref.company_id != command.company_id or ref.account_code is None:
        raise ChequeGLError("Cross-company/missing GL account reference")
    account = next((a for a in chart.accounts if a.code == ref.account_code), None)
    if account is None or account.kind != _ROLE_KINDS[role]:
        raise ChequeGLError("GL account kind missing or unsuitable for " + role)
    # AR/AP must identify the original cheque counterparty. A supplier
    # endorsement is tracked in pending-transferred suspense, not AP settlement.
    if role in ("ar", "ap") and ref.party_id != mapping.party_id:
        raise ChequeGLError("AR/AP posting must identify original verified party")
    if role == "bank" and ref.party_id:
        raise ChequeGLError("Bank GL account may not masquerade as customer AR/AP")
    try:
        return validate_posting_reference(
            chart, ref,
            verified_party_ids=scopes.party_ids,
            verified_project_ids=scopes.project_ids,
            verified_task_scopes=scopes.task_scopes,
        )
    except ValueError as exc:
        raise ChequeGLError("Missing/locked/unverified GL posting reference") from exc


def _mapping_matches(instrument, mapping: ChequeGLAccounts, command: ChequeCommand,
                     scopes: VerifiedScopes, chart: ChartSnapshot,
                     policy: CompanyMoneyPolicy) -> None:
    if (type(mapping) is not ChequeGLAccounts or mapping.company_id != command.company_id
            or mapping.cheque_id != command.cheque_id
            or mapping.party_id != instrument.party_id
            or type(chart) is not ChartSnapshot or chart.company_id != command.company_id
            or type(scopes) is not VerifiedScopes
            or type(policy) is not CompanyMoneyPolicy
            or policy.company_id != command.company_id
            or policy.accounting_currency != "RIAL"):
        raise ChequeGLError("Cross-company/chart/policy/party mapping mismatch")
    if instrument.party_id not in scopes.party_ids:
        raise ChequeGLError("Original cheque party not verified by host")
    if instrument.direction == "PAYABLE":
        if (mapping.bank_id, mapping.bank_account_id) != (
                instrument.bank_id, instrument.drawer_account_id):
            raise ChequeGLError("Payable bank mapping differs from issued cheque")
    elif not mapping.bank_id or not mapping.bank_account_id:
        raise ChequeGLError("Receivable settlement bank account must be explicit")
    validate_chart(chart)
    require_rial_amount(instrument.amount_rial, max_abs_rial=policy.max_abs_rial,
                        allow_zero=False)


def _postings_by_source(journal_state: JournalState) -> dict[str, PostedJournal]:
    indexed = {}
    for event in journal_state.events:
        if type(event) is PostedJournal and event.source.kind == "independent":
            if event.source.source_id in indexed:
                raise ChequeGLConflict("Repeated independent journal business source")
            indexed[event.source.source_id] = event
    return indexed


def _check_prior_posting(state: ChequeState, journal: JournalState, index: int,
                         mapping: ChequeGLAccounts, chart: ChartSnapshot,
                         scopes: VerifiedScopes, posted_by_source: dict,
                         *, posting_date: str) -> None:
    """Require all prior financially material stages on THIS cheque to be recorded.

    Exact amounts, role codes and fiscal periods are checked, but archived
    historical charts may differ. Host must additionally validate provenance
    against immutable original journal evidence and enforce a linked source table.
    """
    for i in range(index):
        old = state.events[i].command
        if old.cheque_id != mapping.cheque_id:
            continue
        before = _prior_position(state, i)
        roles = _stage_roles(old, before, transfer_policy="PENDING_TRANSFER_ONLY")
        journal_id, source_id = _ids(old.company_id, old.cheque_id, old.event_id)
        existing = posted_by_source.get(source_id)
        if roles is None:
            if existing is not None:
                raise ChequeGLConflict("Memo-only cheque stage has a forged GL posting")
            continue
        if existing is None or existing.event_id != journal_id or existing.reversal_of:
            raise ChequeGLConflict("Earlier material cheque stage has no exact journal")
        original = old.instrument or before.instrument
        if (existing.company_id != old.company_id or
                existing.fiscal_period_id != old.fiscal_period_id or
                len(existing.lines) != 2 or existing.actor_id != old.actor_id or
                existing.posting_date > posting_date):
            raise ChequeGLConflict("Older cheque posting mismatches instrument stage")
        for line, role, side in zip(existing.lines, roles, ("debit", "credit")):
            reference = getattr(mapping, role)
            if type(reference) is not PostingReference or line.reference != reference:
                raise ChequeGLConflict("Older cheque posting differs from account mapping")
            if (line.debit_rial, line.credit_rial) != (
                    (original.amount_rial, 0) if side == "debit"
                    else (0, original.amount_rial)):
                raise ChequeGLConflict("Previously posted cheque RIAL amount differs")


def propose_cheque_journal(
    cheque_state: ChequeState, journal_state: JournalState, *,
    cheque_event_id: str, mapping: ChequeGLAccounts,
    chart: ChartSnapshot, scopes: VerifiedScopes, money_policy: CompanyMoneyPolicy,
    context: VerifiedChequeGLContext, today: str,
) -> ChequeJournalProposal | None:
    """Produce exactly two balanced lines, or None for an authorized GL-free memo.

    No journal or cheque state is mutated; caller must verify host attestation.
    """
    replay_cheques(cheque_state)
    replay_journal(journal_state)
    index, entry = _event(cheque_state, cheque_event_id)
    command = entry.command
    if (type(context) is not VerifiedChequeGLContext
            or context.company_id != cheque_state.company_id
            or command.company_id != journal_state.company_id
            or context.cheque_id != command.cheque_id
            or context.cheque_event_id != command.event_id
            or context.jalali_event_date != command.event_date
            or context.fiscal_period_id != command.fiscal_period_id
            or context.actor_id != command.actor_id
            or type(context.prior_ar_ap_accrued) is not bool
            or not context.prior_ar_ap_accrued):
        raise ChequeGLError("Missing/mismatched verified cheque accrual and date context")
    if type(today) is not str or not context.gregorian_posting_date:
        raise ChequeGLError("Trusted journal date/today required")
    try:
        converted = date.fromisoformat(context.gregorian_posting_date)
        today_date = date.fromisoformat(today)
        if converted.isoformat() != context.gregorian_posting_date or converted > today_date:
            raise ValueError
    except ValueError as exc:
        raise ChequeGLError("Invalid/future trusted Gregorian posting date") from exc
    period = next((p for p in journal_state.periods
                   if p.fiscal_period_id == command.fiscal_period_id), None)
    if period is None or not period.start_date <= context.gregorian_posting_date <= period.end_date:
        raise ChequeGLError("Cheque event has no in-range matching Gregorian fiscal period")
    if command.fiscal_period_id in replay_journal(journal_state).closed_period_ids:
        raise ChequeGLError("Fiscal period closed to cheque GL posting")
    prior = _prior_position(cheque_state, index)
    instrument = command.instrument if command.instrument is not None else (
        prior.instrument if prior is not None else None)
    if instrument is None:
        raise ChequeGLError("Cheque instrument absent")
    _mapping_matches(instrument, mapping, command, scopes, chart, money_policy)
    if (instrument.direction == "RECEIVABLE" and prior is not None and
            command.action in ("CLEAR", "BOUNCE", "REVERSE") and
            prior.status == "DEPOSITED" and
            (mapping.bank_id, mapping.bank_account_id) !=
            (prior.receiving_bank_id, prior.receiving_account_id)):
        raise ChequeGLError("GL bank differs from recorded deposit bank/account")
    if (command.action in ("DEPOSIT", "REDEPOSIT") and
            (mapping.bank_id, mapping.bank_account_id) !=
            (command.bank_id, command.bank_account_id)):
        raise ChequeGLError("Bank mapping differs from deposit instruction")
    if command.action == "ENDORSE":
        if mapping.supplier_party_id != command.supplier_party_id or (
                mapping.supplier_party_id not in scopes.party_ids):
            raise ChequeGLError("Endorsement supplier not verified in GL mapping")
    roles = _stage_roles(command, prior, transfer_policy=context.transfer_policy)
    journal_id, source_id = _ids(command.company_id, command.cheque_id, command.event_id)
    if ("", source_id) not in scopes.independent_source_scopes:
        raise ChequeGLError("Independent cheque GL business source not host-verified")
    posted_by_source = _postings_by_source(journal_state)
    _check_prior_posting(cheque_state, journal_state, index, mapping, chart,
                         scopes, posted_by_source,
                         posting_date=context.gregorian_posting_date)
    existing = posted_by_source.get(source_id)
    if roles is None:
        if existing is not None:
            raise ChequeGLConflict("Non-posting cheque event already occupies ledger")
        return None
    if existing is not None and existing.event_id != journal_id:
        raise ChequeGLConflict("Cheque business source already posted by another event")
    debit = _reference_map(mapping, roles[0], command=command, chart=chart, scopes=scopes)
    credit = _reference_map(mapping, roles[1], command=command, chart=chart, scopes=scopes)
    if debit.account_code == credit.account_code and debit == credit:
        raise ChequeGLError("Self-offset account mapping hides an absent transfer")
    amount = instrument.amount_rial
    lines = (JournalLine(debit, debit_rial=amount),
             JournalLine(credit, credit_rial=amount))
    effect = ("DEBIT_BANK" if command.action == "CLEAR" and
              instrument.direction == "RECEIVABLE" else
              "CREDIT_BANK" if command.action == "CLEAR" else "NONE")
    return ChequeJournalProposal(
        command.company_id, command.cheque_id, command.event_id,
        entry.event_hash, cheque_state.revision, journal_state.revision,
        command.fiscal_period_id, command.actor_id, context.gregorian_posting_date,
        command.action, JournalSource("independent", source_id),
        journal_id, lines, amount, effect,
    )


def post_cheque_journal(
    cheque_state: ChequeState, journal_state: JournalState, *,
    proposal: ChequeJournalProposal, mapping: ChequeGLAccounts,
    chart: ChartSnapshot, scopes: VerifiedScopes, money_policy: CompanyMoneyPolicy,
    context: VerifiedChequeGLContext, today: str,
    expected_journal_revision: str,
) -> JournalState:
    """Pass checked immutable proposal into existing post_journal, with no IO."""
    if type(proposal) is not ChequeJournalProposal:
        raise ChequeGLError("Explicit two-line journal proposal required")
    if expected_journal_revision != journal_state.revision:
        raise ChequeGLConflict("Stale journal CAS revision")
    rechecked = propose_cheque_journal(
        cheque_state, journal_state, cheque_event_id=proposal.cheque_event_id,
        mapping=mapping, chart=chart, scopes=scopes, money_policy=money_policy,
        context=context, today=today)
    if rechecked != proposal:
        raise ChequeGLConflict("Cheque proposal/state/chart context is stale or altered")
    return post_journal(
        journal_state, company_id=proposal.company_id,
        fiscal_period_id=proposal.fiscal_period_id, event_id=proposal.event_id,
        actor_id=proposal.actor_id, posting_date=proposal.posting_date,
        source=proposal.source, lines=proposal.lines, chart=chart, scopes=scopes,
        money_policy=money_policy, expected_revision=expected_journal_revision,
        today=today,
    )


__all__ = [
    "ChequeGLError", "ChequeGLConflict", "ChequeGLAccounts",
    "VerifiedChequeGLContext", "ChequeJournalProposal",
    "cheque_journal_source_id", "propose_cheque_journal", "post_cheque_journal",
]
