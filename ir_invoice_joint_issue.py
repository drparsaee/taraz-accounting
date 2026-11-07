"""Narrow host-side legacy sale -> RIAL V2 atomic finance-snapshot adapter.

Only for already opted-in EMPTY-history (or subsequent) company journals.
This is a bridge for the old task invoice flow, not an arbitrary posting API.
No IO; caller must obtain authenticated actor, current cards/projects and
commit the returned WHOLE finance domain under UnifiedAppStorage CAS.
"""
from __future__ import annotations

from hashlib import sha256
import json

from finance import apply_finance_command
from ir_chart_model import ChartAccount, ChartSnapshot, JobReference, PostingReference
from ir_finance_v2_extension import (
    VerifiedInvoiceSourceProof, compose_finance_rial_snapshot,
    load_finance_rial_journal,
)
from ir_journal_v2 import JournalLine, JournalSource, VerifiedScopes, post_journal
from money_policy import CompanyMoneyPolicy, snapshot_sha256


def _unique_company(finance_before: dict) -> str:
    extension = finance_before.get("rialJournalV2")
    if extension is None:
        raise ValueError("RIAL opt-in is not activated")
    companies = extension["companies"]
    if len(companies) != 1:
        raise ValueError("Unmapped multi-company legacy invoices are not authorized")
    return next(iter(companies))


def _restricted_sales_chart(company_id: str, project_id: str, card_id: str,
                            invoice_id: str):
    """Minimum fixed shadow COA. Never pretend to be the user's real COA."""
    job_id = "task-" + sha256((project_id + "\x00" + card_id).encode()).hexdigest()[:24]
    chart = ChartSnapshot(company_id, accounts=(
        ChartAccount(company_id, "10", "KOL", None, "دارایی", "asset"),
        ChartAccount(company_id, "1001", "MOEIN", "10", "دریافتنی تجاری", "asset"),
        ChartAccount(company_id, "100101", "TAFSILI", "1001", "حساب دریافتنی موقت", "asset",
                     accountable=True),
        ChartAccount(company_id, "20", "KOL", None, "بدهی", "liability"),
        ChartAccount(company_id, "2001", "MOEIN", "20", "مالیات دریافت شده", "liability"),
        ChartAccount(company_id, "200101", "TAFSILI", "2001", "مالیات فروش پرداختنی", "liability",
                     accountable=True),
        ChartAccount(company_id, "40", "KOL", None, "درآمد", "revenue"),
        ChartAccount(company_id, "4001", "MOEIN", "40", "فروش خدمات", "revenue"),
        ChartAccount(company_id, "400101", "TAFSILI", "4001", "درآمد فروش موقت", "revenue",
                     accountable=True),
    ), project_ids=(project_id,),
        jobs=(JobReference(company_id, job_id, project_id, card_id),))
    scopes = VerifiedScopes(project_ids=frozenset({project_id}),
                            task_scopes=frozenset({(project_id, card_id)}),
                            independent_source_scopes=frozenset({(project_id, invoice_id)}))
    return chart, scopes, job_id


def issue_legacy_sales_with_rial(
    finance_before: dict, command: dict, *, actor: str,
    accounts: dict, cards: list, projects: list, now: str,
) -> dict:
    """Produce one exactly balanced TOMAN/RIAL finance state.

    MUST be invoked inside authenticated host lock. Client must supply only a
    normal `invoice.issue` intent; no chart, scopes, company ID or proof from UI.
    """
    if type(command) is not dict or command.get("type") != "invoice.issue":
        raise ValueError("Only legacy invoice.issue is supported by the RIAL bridge")
    if type(now) is not str or len(now) < 10:
        raise ValueError("Host timestamp required")
    company_id = _unique_company(finance_before)
    prior = load_finance_rial_journal(finance_before, company_id)
    result = apply_finance_command(
        finance_before, command, actor=actor, accounts=accounts,
        cards=cards, projects=projects, now=now,
    )
    if not result["changed"]:
        # V1 idempotency is insufficient alone: a historical issue may have
        # bypassed RIAL posting, therefore reject unless the V2 source exists.
        invoice_id = command["invoiceId"]
        invoice = next((i for i in finance_before["invoices"] if i["id"] == invoice_id), None)
        expected_event = "mirror-" + sha256(
            json.dumps([command["eventId"], invoice_id], separators=(",", ":")).encode()
        ).hexdigest()[:32]
        if invoice is None or not any(
                e.event_id == expected_event and e.actor_id == actor
                and e.source.project_id == invoice["projectId"]
                and ((e.source.kind == "independent"
                      and e.source.source_id == invoice_id)
                     or (e.source.kind in ("task", "card")
                         and e.source.task_id == invoice["cardId"]
                         and e.source.source_id == invoice["cardId"]))
                and all(line.reference.task_id == invoice["cardId"] for line in e.lines)
                and not e.reversal_of
                and sum(line.debit_rial for line in e.lines) == invoice["sale"]["total"] * 10
                for e in prior.events if hasattr(e, "source")):
            raise ValueError("Legacy receipt has no matching verified RIAL posting")
        return {"state": result["state"], "changed": False,
                "result": {**result["result"], "rialJournalEventId": expected_event,
                           "rialCompanyId": company_id,
                           "rialAmount": str(invoice["sale"]["total"] * 10),
                           "postingMode": "legacy-task-sales-shadow"}}
    finance_after = result["state"]
    invoice_id = command["invoiceId"]
    invoice = next((i for i in finance_after["invoices"] if i["id"] == invoice_id), None)
    if invoice is None:
        raise ValueError("Issued invoice missing from host reducer")
    project_id, card_id = invoice["projectId"], invoice["cardId"]
    if not any(t.get("id") == card_id and t.get("projectId") == project_id for t in cards):
        raise PermissionError("Original invoice task/project no longer exists")
    if not any(p.get("id") == project_id for p in projects):
        raise PermissionError("Original invoice project no longer exists")
    total_toman = invoice["sale"]["total"]
    if type(total_toman) is not int or total_toman <= 0:
        raise ValueError("Positive exact legacy TOMAN invoice required")
    if invoice["sale"]["advance"] != 0:
        raise ValueError("Advance payment needs its own reviewed bank/AR bridge")
    # Zero loss, no float. The journal domain will enforce MAX_RIAL ceiling.
    total_rial = total_toman * 10
    today = now[:10]
    periods = [p for p in prior.periods if p.start_date <= today <= p.end_date]
    if len(periods) != 1:
        raise ValueError("No unique open company fiscal period for invoice issuance")
    chart, scopes, job_id = _restricted_sales_chart(
        company_id, project_id, card_id, invoice_id)
    net_revenue_rial = (
        invoice["sale"]["subtotal"] - invoice["sale"]["discount"]) * 10
    tax_rial = invoice["sale"]["tax"] * 10
    credit_lines = []
    if net_revenue_rial:
        credit_lines.append(JournalLine(
            PostingReference(company_id, "400101", project_id=project_id,
                             job_id=job_id, task_id=card_id),
            credit_rial=net_revenue_rial))
    if tax_rial:
        credit_lines.append(JournalLine(
            PostingReference(company_id, "200101", project_id=project_id,
                             job_id=job_id, task_id=card_id),
            credit_rial=tax_rial))
    event_id = "mirror-" + sha256(
        json.dumps([command["eventId"], invoice_id], separators=(",", ":")).encode()
    ).hexdigest()[:32]
    candidate = post_journal(
        prior, company_id=company_id, fiscal_period_id=periods[0].fiscal_period_id,
        event_id=event_id, actor_id=actor, posting_date=today,
        source=JournalSource("independent", invoice_id, project_id),
        lines=(JournalLine(
            PostingReference(company_id, "100101", project_id=project_id,
                             job_id=job_id, task_id=card_id), debit_rial=total_rial),
               *credit_lines),
        chart=chart, scopes=scopes, money_policy=CompanyMoneyPolicy(company_id),
        expected_revision=prior.revision, today=today,
    )
    proof = VerifiedInvoiceSourceProof(
        company_id, actor, invoice_id, project_id, card_id,
        invoice["snapshotHash"], total_toman,
        snapshot_sha256(finance_before), snapshot_sha256(finance_after),
    )
    combined = compose_finance_rial_snapshot(
        finance_before, finance_after, candidate,
        expected_journal_revision=prior.revision, proof=proof,
    )
    return {"state": combined, "changed": True,
            "result": {**result["result"], "rialJournalEventId": event_id,
                       "rialCompanyId": company_id, "rialAmount": str(total_rial),
                       "postingMode": "legacy-task-sales-shadow"}}
