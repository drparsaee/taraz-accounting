"""Pure validated FIFO-inventory -> RIAL V2 journal bridge.

The host constructs authoritative mappings, proof and VerifiedScopes and must
commit inventory + returned journal snapshot in ONE durable CAS transaction.
No database access or side effects occur here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import re

from ir_chart_model import (
    ChartSnapshot, PostingReference, validate_chart, validate_posting_reference,
)
from ir_inventory_rial import (
    InventoryAccountMapping, InventoryState, InventoryJournalProposal,
    propose_inventory_journal, replay_inventory,
)
from ir_journal_v2 import (
    JournalLine, JournalSource, JournalState, PostedJournal, VerifiedScopes,
    post_journal, replay_journal, reverse_journal,
)
from money_policy import CompanyMoneyPolicy, require_rial_amount, snapshot_sha256

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class InventoryBridgeError(ValueError):
    """Missing or contradictory trusted proof, unsupported policy or mapping."""


class InventoryBridgeConflict(InventoryBridgeError):
    """Stale CAS, changed source contents or financial source reuse."""


def _id(value: str, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise InventoryBridgeError("Invalid " + label)
    return value


@dataclass(frozen=True, slots=True)
class VerifiedInventoryAccounts:
    """Explicit account roles supplied by an authoritative company chart mapper."""
    base: InventoryAccountMapping
    payable_account: str
    work_in_progress_account: str

    def __post_init__(self) -> None:
        if type(self.base) is not InventoryAccountMapping:
            raise InventoryBridgeError("InventoryAccountMapping required")
        _id(self.payable_account, "AP chart account")
        _id(self.work_in_progress_account, "WIP chart account")
        supported = (self.base.inventory_asset, self.base.receipt_clearing,
                     self.base.issue_expense, self.base.pricing_clearing,
                     self.payable_account, self.work_in_progress_account)
        if len(set(supported)) != len(supported):
            raise InventoryBridgeError("GL account roles must be distinct")


@dataclass(frozen=True, slots=True)
class VerifiedReceiptSettlement:
    """Host-verified invoice/GRNI evidence, strictly bound to one stock movement."""
    company_id: str
    inventory_event_id: str
    commercial_source_id: str
    mode: Literal["GRNI", "AP"]
    exact_amount_rial: int
    supplier_invoice_id: str = ""
    supplier_party_id: str = ""

    def __post_init__(self) -> None:
        for label in ("company_id", "inventory_event_id", "commercial_source_id"):
            _id(getattr(self, label), label)
        if self.mode not in ("GRNI", "AP"):
            raise InventoryBridgeError("Only independently verified GRNI or AP permitted")
        try:
            require_rial_amount(self.exact_amount_rial)
        except ValueError as exc:
            raise InventoryBridgeError("Settlement amount must be exact RIAL") from exc
        if self.mode == "AP":
            _id(self.supplier_invoice_id, "supplier invoice ID")
            _id(self.supplier_party_id, "supplier party ID")
        elif self.supplier_invoice_id or self.supplier_party_id:
            raise InventoryBridgeError("GRNI cannot imply verified AP invoice/party")


@dataclass(frozen=True, slots=True)
class VerifiedGLPosting:
    """A host-attested posting context, including exact snapshot CAS inputs."""
    company_id: str
    actor_id: str
    fiscal_period_id: str
    posting_date: str
    today: str
    expected_inventory_revision: str
    expected_journal_revision: str
    issue_destination: Literal["COGS", "WIP"] = "COGS"

    def __post_init__(self) -> None:
        for label in ("company_id", "actor_id", "fiscal_period_id"):
            _id(getattr(self, label), label)
        if self.issue_destination not in ("COGS", "WIP"):
            raise InventoryBridgeError("Issue destination must be explicit COGS or WIP")
        for field in ("expected_inventory_revision", "expected_journal_revision"):
            value = getattr(self, field)
            if type(value) is not str or _SHA.fullmatch(value) is None:
                raise InventoryBridgeError("Expected immutable SHA256 revision")
        # V2 owns authoritative date parsing and future/period validation.
        for field in ("posting_date", "today"):
            value = getattr(self, field)
            if type(value) is not str or len(value) != 10:
                raise InventoryBridgeError("Explicit ISO calendar day required")


@dataclass(frozen=True, slots=True)
class InventoryGLBridgeResult:
    company_id: str
    inventory_event_id: str
    commercial_source_id: str
    stock_revision: str
    journal: JournalState
    journal_event_id: str
    status: Literal["POSTED", "REVERSED", "IDEMPOTENT", "NO_GL"]
    related_inventory_event_id: str
    amount_rial: int
    receipt_invoice_id: str
    evidence_digest: str


def _journal_id(company: str, source_id: str) -> str:
    """Stable across stock event IDs; cannot double-post by changing event ID."""
    return "INVGL-" + snapshot_sha256({
        "schema": "RIAL-INVENTORY-SOURCE-1",
        "company": company, "commercialSourceId": source_id})[:40]


def _find_stock(stock: InventoryState, event_id: str):
    _id(event_id, "inventory event ID")
    found = next((posted for posted in stock.events
                  if posted.event.event_id == event_id), None)
    if found is None:
        raise InventoryBridgeError("Only replayed, recorded inventory events can be posted")
    return found


def _validated_account(chart: ChartSnapshot, code: str, kind: str) -> None:
    account = next((a for a in chart.accounts if a.code == code), None)
    if account is None or account.kind != kind:
        raise InventoryBridgeError("Selected account is absent or wrong chart kind: " + code)
    if not account.active or account.archived or account.frozen or not account.accountable:
        raise InventoryBridgeError("Selected account cannot receive a new posting: " + code)


def _mapping_check(chart: ChartSnapshot, mapping: VerifiedInventoryAccounts,
                   company: str, *, historical_reversal: bool = False) -> None:
    if type(mapping) is not VerifiedInventoryAccounts or mapping.base.company_id != company:
        raise InventoryBridgeError("Company-verified inventory GL roles required")
    if type(chart) is not ChartSnapshot or chart.company_id != company:
        raise InventoryBridgeError("Chart is outside inventory company")
    validate_chart(chart)
    if historical_reversal:
        # V2 reverse_journal inverts the original posted, audited chart lines.
        # A later chart archive may disable NEW posting but must not prevent
        # an exact legally traceable reversal of the historical event.
        return
    for code, kind in (
        (mapping.base.inventory_asset, "asset"),
        (mapping.base.receipt_clearing, "liability"),
        (mapping.base.pricing_clearing, "liability"),
        (mapping.base.issue_expense, "expense"),
        (mapping.payable_account, "liability"),
        (mapping.work_in_progress_account, "asset"),
    ):
        _validated_account(chart, code, kind)


def _posting_reference(company: str, code: str, event, chart: ChartSnapshot,
                       scopes: VerifiedScopes, party_id: str = "") -> PostingReference:
    if party_id:
        if party_id not in scopes.party_ids:
            raise InventoryBridgeError("Supplier identity not verified for this company")
        party = next((p for p in chart.party_links if p.party_id == party_id), None)
        if party is None:
            raise InventoryBridgeError("Supplier needs an explicit party-detail link")
        detail = party.detail_code
    else:
        detail = ""
    job = next((j for j in chart.jobs if j.job_id == event.job_id), None) if event.job_id else None
    if event.job_id and (job is None or job.project_id != event.project_id):
        raise InventoryBridgeError("Inventory job does not belong to chart project")
    task_id = job.task_id if job is not None else ""
    ref = PostingReference(
        company, code, detail_code=detail, party_id=party_id,
        project_id=event.project_id, cost_center_code=event.cost_center_id,
        job_id=event.job_id, task_id=task_id,
    )
    validate_posting_reference(
        chart, ref, verified_party_ids=scopes.party_ids,
        verified_project_ids=scopes.project_ids,
        verified_task_scopes=scopes.task_scopes,
    )
    return ref


def _period_check(journal: JournalState, context: VerifiedGLPosting) -> None:
    # replay_journal has been called. Reject even a no-op in a closed period.
    from datetime import date
    try:
        issued = date.fromisoformat(context.posting_date)
        today = date.fromisoformat(context.today)
        if issued.isoformat() != context.posting_date or today.isoformat() != context.today:
            raise ValueError
    except ValueError as exc:
        raise InventoryBridgeError("Invalid verified calendar posting date") from exc
    period = next((p for p in journal.periods
                   if p.fiscal_period_id == context.fiscal_period_id), None)
    if period is None or not period.start_date <= context.posting_date <= period.end_date:
        raise InventoryBridgeError("Posting date lies outside selected fiscal period")
    if issued > today:
        raise InventoryBridgeError("Posting date cannot be in the future")
    if context.fiscal_period_id in replay_journal(journal).closed_period_ids:
        raise InventoryBridgeError("Closed fiscal period cannot accept inventory GL")


def _stock_proposal(stock: InventoryState, event_id: str,
                    mapping: VerifiedInventoryAccounts) -> InventoryJournalProposal | None:
    return propose_inventory_journal(stock, event_id, mapping.base)


def _original_journal(journal: JournalState, original_stock,
                      company: str) -> PostedJournal:
    event_id = _journal_id(company, original_stock.event.source.source_id)
    original = next((item for item in journal.events
                     if type(item) is PostedJournal and item.event_id == event_id), None)
    if (original is None or original.reversal_of or
            original.source.kind != "independent" or
            original.source.source_id != original_stock.event.source.source_id or
            original.source.project_id != original_stock.event.project_id):
        raise InventoryBridgeError("Verified original inventory GL entry is required")
    return original


def _expected_financial_lines(event, proposal, mapping: VerifiedInventoryAccounts,
                              settlement: VerifiedReceiptSettlement | None,
                              context: VerifiedGLPosting):
    if proposal is None:
        return (), "", ""
    amount = abs(sum(x.debit_rial - x.credit_rial
                     for x in proposal.lines if x.account_code == mapping.base.inventory_asset))
    if amount == 0:
        raise InventoryBridgeError("Stock proposal missing nonzero inventory asset movement")
    if event.kind in ("RECEIPT", "PRICE"):
        if type(settlement) is not VerifiedReceiptSettlement:
            raise InventoryBridgeError("Receipt/pricing requires verified GRNI or supplier invoice")
        if (settlement.company_id != event.company_id or
                settlement.inventory_event_id != event.event_id or
                settlement.commercial_source_id != event.source.source_id or
                settlement.exact_amount_rial != amount):
            raise InventoryBridgeError("Invoice proof is not bound to stock event and exact RIAL")
        if (settlement.mode == "AP" and
                settlement.supplier_invoice_id != event.source.source_id):
            raise InventoryBridgeError(
                "AP invoice ID must equal globally unique stock business source ID")
        contra = (mapping.base.receipt_clearing if settlement.mode == "GRNI"
                  else mapping.payable_account)
        return amount, contra, settlement.supplier_party_id
    if settlement is not None:
        raise InventoryBridgeError("Supplier settlement proof on non-receipt stock movement")
    if event.kind == "ISSUE":
        if context.issue_destination == "WIP":
            if not event.project_id or not event.job_id:
                raise InventoryBridgeError("WIP issue requires mapped project and job")
            return amount, mapping.work_in_progress_account, ""
        if event.job_id:
            raise InventoryBridgeError("Job-backed issues must use explicit WIP policy")
        return amount, mapping.base.issue_expense, ""
    raise InventoryBridgeError("Unsupported normal posting classification")


def apply_inventory_gl(
    stock: InventoryState, journal: JournalState, inventory_event_id: str, *,
    chart: ChartSnapshot, scopes: VerifiedScopes, accounts: VerifiedInventoryAccounts,
    context: VerifiedGLPosting, money_policy: CompanyMoneyPolicy,
    settlement: VerifiedReceiptSettlement | None = None,
) -> InventoryGLBridgeResult:
    """Return a new immutable RIAL journal state, or explicit NO_GL; never persist.

    Required scope, chart and settlement evidence must originate with the
    authenticated host. The host MUST persist returned journal and stock in
    one authoritative transaction with source uniqueness and CAS.
    """
    if (type(stock) is not InventoryState or type(journal) is not JournalState or
            type(scopes) is not VerifiedScopes or
            type(context) is not VerifiedGLPosting or
            type(money_policy) is not CompanyMoneyPolicy):
        raise InventoryBridgeError("Typed host-verified stock/journal/scopes/context/policy required")
    stock_check = replay_inventory(stock)
    journal_check = replay_journal(journal)
    company = context.company_id
    if (stock.company_id != company or journal.company_id != company or
            chart.company_id != company or money_policy.company_id != company or
            money_policy.accounting_currency != "RIAL" or journal.currency != "RIAL"):
        raise InventoryBridgeError("Cross-company or non-RIAL bridge request")
    if stock_check.revision != context.expected_inventory_revision:
        raise InventoryBridgeConflict("Inventory CAS differs from supplied host revision")
    if journal_check.revision != context.expected_journal_revision:
        raise InventoryBridgeConflict("Financial CAS differs from supplied host revision")
    posted = _find_stock(stock, inventory_event_id)
    event = posted.event
    if event.actor_id != context.actor_id or posted.authority.company_id != company:
        raise InventoryBridgeError("Bridge actor/stock authority mismatch")
    if event.project_id and event.project_id not in scopes.project_ids:
        raise InventoryBridgeError("Stock project not host verified for V2 GL")
    if event.job_id:
        if (event.project_id, event.job_id, event.cost_center_id) not in posted.authority.work_scopes:
            raise InventoryBridgeError("Stock job/cost-center proof does not match original")
    _mapping_check(chart, accounts, company,
                   historical_reversal=event.kind in ("RETURN", "REVERSAL"))
    _period_check(journal, context)
    if (event.project_id, event.source.source_id) not in scopes.independent_source_scopes:
        raise InventoryBridgeError("Inventory commercial source not journal-host-verified")
    financial_id = _journal_id(company, event.source.source_id)
    related = event.related_event_id
    proof_digest = snapshot_sha256({
        "schema": "RIAL-INVENTORY-GL-BRIDGE-1",
        "stockEventHash": posted.event_hash, "company": company,
        "financialEventId": financial_id,
        "settlement": ({
            "mode": settlement.mode, "company": settlement.company_id,
            "stockEvent": settlement.inventory_event_id,
            "commercialSource": settlement.commercial_source_id,
            "amount": settlement.exact_amount_rial,
            "invoiceId": settlement.supplier_invoice_id,
            "partyId": settlement.supplier_party_id,
        } if type(settlement) is VerifiedReceiptSettlement else None),
    })
    if settlement is not None and type(settlement) is not VerifiedReceiptSettlement:
        raise InventoryBridgeError("Supplier settlement evidence must be typed")
    if event.kind == "ADJUSTMENT":
        raise InventoryBridgeError("Cycle-count GL policy is not supported by this bridge")
    proposal = _stock_proposal(stock, inventory_event_id, accounts)
    if event.kind == "TRANSFER" or proposal is None:
        if any(type(item) is PostedJournal and (
                item.source.source_id == event.source.source_id or
                item.event_id == financial_id) for item in journal.events):
            raise InventoryBridgeConflict(
                "A nonposting stock source already has a financial journal")
        if event.kind in ("RETURN", "REVERSAL") and proposal is None:
            # Zero-cost exact reversals cannot recognize value; original may
            # still be financially posted under a false/changed value.
            original_stock = _find_stock(stock, related)
            if any(type(j) is PostedJournal and
                   j.event_id == _journal_id(company, original_stock.event.source.source_id)
                   for j in journal.events):
                raise InventoryBridgeConflict("Zero-cost reverse of existing financial posting")
        if settlement is not None:
            raise InventoryBridgeError("Nonposting movement cannot create payable/AP liability")
        if event.kind not in ("TRANSFER", "RECEIPT", "ISSUE", "RETURN", "REVERSAL"):
            raise InventoryBridgeError("Unpriced/unsupported movement cannot be silently ignored")
        if event.kind == "TRANSFER" and posted.effects.asset_delta_rial != 0:
            raise InventoryBridgeError("Transfer must conserve exact FIFO valuation")
        return InventoryGLBridgeResult(
            company, event.event_id, event.source.source_id, stock.revision,
            journal, "", "NO_GL", related, 0, "", proof_digest,
        )
    if event.kind in ("RETURN", "REVERSAL"):
        if settlement is not None:
            raise InventoryBridgeError("Return/reversal uses the original GL, not a new invoice")
        if any(type(item) is PostedJournal and
               item.source.source_id == event.source.source_id
               for item in journal.events):
            raise InventoryBridgeConflict("Return/reversal commercial source already posted elsewhere")
        original_stock = _find_stock(stock, related)
        original = _original_journal(journal, original_stock, company)
        source_effect = original_stock.effects.asset_delta_rial
        if (source_effect == 0 or posted.effects.asset_delta_rial != -source_effect
                or original.company_id != company or len(original.lines) != 2):
            raise InventoryBridgeError("Stock return must invert exact original financial amount")
        # V2 reverses original lines verbatim, retaining historical chart evidence.
        if not any(line.reference.account_code == accounts.base.inventory_asset and (
                line.debit_rial - line.credit_rial == source_effect)
                for line in original.lines):
            raise InventoryBridgeError("Original journal/stock inventory valuation mismatch")
        for item in journal.events:
            if item.event_id == financial_id:
                if (type(item) is PostedJournal and item.reversal_of == original.event_id
                        and item.reason == event.reason
                        and item.actor_id == context.actor_id
                        and item.fiscal_period_id == context.fiscal_period_id
                        and item.posting_date == context.posting_date):
                    return InventoryGLBridgeResult(
                        company, event.event_id, event.source.source_id, stock.revision,
                        journal, financial_id, "IDEMPOTENT", related,
                        abs(source_effect), "", proof_digest,
                    )
                raise InventoryBridgeConflict("Financial event ID reused with changed source")
            if type(item) is PostedJournal and item.reversal_of == original.event_id:
                raise InventoryBridgeConflict("Original GL already reversed by different event")
        new_state = reverse_journal(
            journal, company_id=company, original_event_id=original.event_id,
            event_id=financial_id, actor_id=context.actor_id,
            fiscal_period_id=context.fiscal_period_id,
            posting_date=context.posting_date, reason=event.reason,
            expected_revision=journal.revision, today=context.today,
        )
        return InventoryGLBridgeResult(
            company, event.event_id, event.source.source_id, stock.revision,
            new_state, financial_id, "REVERSED", related,
            abs(source_effect), "", proof_digest,
        )
    if event.kind not in ("RECEIPT", "PRICE", "ISSUE"):
        raise InventoryBridgeError("Unsupported valued movement policy")
    amount, contra, supplier = _expected_financial_lines(
        event, proposal, accounts, settlement, context)
    try:
        require_rial_amount(amount, max_abs_rial=money_policy.max_abs_rial,
                            allow_zero=False)
    except ValueError as exc:
        raise InventoryBridgeError("Stock valuation exceeds canonical company money policy") from exc
    inventory_ref = _posting_reference(company, accounts.base.inventory_asset,
                                       event, chart, scopes)
    contra_ref = _posting_reference(company, contra, event, chart, scopes,
                                    party_id=supplier)
    delta = posted.effects.asset_delta_rial
    if delta > 0:
        lines = (JournalLine(inventory_ref, debit_rial=amount),
                 JournalLine(contra_ref, credit_rial=amount))
    else:
        lines = (JournalLine(contra_ref, debit_rial=amount),
                 JournalLine(inventory_ref, credit_rial=amount))
    if (abs(delta) != amount or
            sum(line.debit_rial for line in lines) !=
            sum(line.credit_rial for line in lines)):
        raise InventoryBridgeError("GL amount differs from exact FIFO valuation")
    source = JournalSource("independent", event.source.source_id,
                           project_id=event.project_id)
    # Journal V2 itself does not enforce unique source IDs under DIFFERENT event
    # IDs. Scan the entire validated stream; never assume the event ID is proof.
    for prior in journal.events:
        if type(prior) is PostedJournal and (
                prior.source.source_id == event.source.source_id or
                prior.event_id == financial_id):
            if (prior.event_id == financial_id and not prior.reversal_of
                    and not prior.reason and prior.source == source
                    and prior.actor_id == context.actor_id
                    and prior.fiscal_period_id == context.fiscal_period_id
                    and prior.posting_date == context.posting_date
                    and prior.lines == lines):
                # Let V2 itself check exact historical chart/scopes/policy
                # evidence digest; superficially identical lines are not
                # enough for an "identical" financially authorized retry.
                try:
                    unchanged = post_journal(
                        journal, company_id=company,
                        fiscal_period_id=context.fiscal_period_id,
                        event_id=financial_id, actor_id=context.actor_id,
                        posting_date=context.posting_date, source=source,
                        lines=lines, chart=chart, scopes=scopes,
                        money_policy=money_policy,
                        expected_revision=journal.revision, today=context.today)
                except ValueError as exc:
                    raise InventoryBridgeConflict(
                        "Retry differs from historic V2 posting evidence") from exc
                if unchanged is not journal:
                    raise InventoryBridgeConflict("Unexpected mutation on V2 retry")
                return InventoryGLBridgeResult(
                    company, event.event_id, event.source.source_id,
                    stock.revision, journal, financial_id, "IDEMPOTENT",
                    related, amount,
                    settlement.supplier_invoice_id if settlement else "",
                    proof_digest,
                )
            raise InventoryBridgeConflict("GL commercial source already used under another event ID")
        if prior.event_id == financial_id:
            raise InventoryBridgeConflict("GL derived event ID already belongs to other entry")
    if any(p.event.related_event_id == event.event_id
           and p.event.kind in ("RETURN", "REVERSAL") for p in stock.events):
        raise InventoryBridgeConflict(
            "Original stock event already returned/reversed before first financial posting")
    new_state = post_journal(
        journal, company_id=company, fiscal_period_id=context.fiscal_period_id,
        event_id=financial_id, actor_id=context.actor_id,
        posting_date=context.posting_date, source=source, lines=lines,
        chart=chart, scopes=scopes, money_policy=money_policy,
        expected_revision=journal.revision, today=context.today,
    )
    return InventoryGLBridgeResult(
        company, event.event_id, event.source.source_id, stock.revision,
        new_state, financial_id, "POSTED", related, amount,
        settlement.supplier_invoice_id if settlement else "", proof_digest,
    )


__all__ = [
    "InventoryBridgeError", "InventoryBridgeConflict",
    "VerifiedInventoryAccounts", "VerifiedReceiptSettlement", "VerifiedGLPosting",
    "InventoryGLBridgeResult", "apply_inventory_gl",
]
