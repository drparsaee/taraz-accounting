"""Read-only company/chart/V2-scope preflight for issued business sources.

This is a pure check, never an authorization token or a journal writer.
Authenticated hosts MUST construct VerifiedRegistryAuthority and VerifiedScopes
from authoritative records. Client-created objects do not prove their origin.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ir_chart_model import (
    ChartSnapshot, PostingReference, validate_chart,
    validate_external_references, validate_posting_reference,
)
from ir_company_registry import (
    CompanyRegistry, CompanyPartyRef, VerifiedRegistryAuthority,
    replay_registry, resolve_project_company, verify_sale_purchase_gl_gate,
)
from ir_inventory_rial import InventoryState, PostedMovement, replay_inventory
from ir_journal_v2 import (
    JournalSource, JournalState, PostedJournal, VerifiedScopes, replay_journal,
)


class CompanyChartGatewayError(ValueError):
    """Mismatched source, registry, chart, scopes, period or account."""


@dataclass(frozen=True, slots=True)
class CompanyChartPreflight:
    """Read-only result for one checked request; MUST NOT authorize a commit."""

    company_id: str
    project_id: str
    fiscal_year_id: str
    fiscal_period_id: str
    posting_date: str
    actor_id: str
    source_kind: str
    journal_source: JournalSource
    registry_revision: str
    journal_revision: str
    inventory_revision: str = ""


def _calendar_day(value: str) -> str:
    if type(value) is not str or len(value) != 10:
        raise CompanyChartGatewayError("Explicit canonical Gregorian ISO date required")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CompanyChartGatewayError("Invalid Gregorian posting date") from error
    if parsed.isoformat() != value:
        raise CompanyChartGatewayError("Posting date is not canonical YYYY-MM-DD")
    return value


def _registered_scope(registry: CompanyRegistry, authority: VerifiedRegistryAuthority,
                      company_id: str, actor_id: str, project_id: str,
                      chart: ChartSnapshot, scopes: VerifiedScopes):
    if (type(registry) is not CompanyRegistry or
            type(authority) is not VerifiedRegistryAuthority or
            type(chart) is not ChartSnapshot or
            type(scopes) is not VerifiedScopes):
        raise CompanyChartGatewayError("Typed registry, host authority, chart and V2 scopes required")
    if not authority.authenticated or authority.actor_id != actor_id:
        raise PermissionError("Authenticated host actor does not match requesting actor")
    if chart.company_id != company_id:
        raise CompanyChartGatewayError("Chart belongs to another company")
    projection = replay_registry(registry)
    company = next((row for row in projection.companies
                    if row.company_id == company_id), None)
    if company is None or company.currency != "RIAL":
        raise CompanyChartGatewayError("Registered canonical-RIAL company required")
    role = next((grant.role for grant in projection.grants
                 if grant.company_id == company_id and
                 grant.principal_id == actor_id), None)
    if role not in ("finance_admin", "finance_issuer"):
        raise PermissionError("Company finance issuer/admin role required")
    if (resolve_project_company(
            registry, project_id, verified_project_company_pairs=
            authority.project_company_pairs) != company_id):
        raise CompanyChartGatewayError("Project belongs to a different company")
    validate_chart(chart)
    registered = {a.project_id for a in projection.assignments
                  if a.company_id == company_id}
    host_pairs = authority.project_company_pairs
    authorized_projects = {
        project for project, owner in host_pairs
        if owner == company_id and sum(1 for p, _ in host_pairs if p == project) == 1
    }
    project_ids = (
        set(chart.project_ids) | set(scopes.project_ids) |
        {p for p, _ in scopes.task_scopes} |
        {p for p, _, _ in scopes.checklist_scopes} |
        {p for p, _ in scopes.independent_source_scopes}
    )
    if "" in project_ids or not project_ids.issubset(registered & authorized_projects):
        raise CompanyChartGatewayError("Unassigned/ambiguous/cross-company source projects")
    if any((project, task) not in scopes.task_scopes
           for project, task, _ in scopes.checklist_scopes):
        raise CompanyChartGatewayError("Verified checklist scope lacks verified owning task")
    if project_id not in chart.project_ids or project_id not in scopes.project_ids:
        raise CompanyChartGatewayError("Source project missing in chart or V2 scopes")
    registered_parties = {p.party_id for p in projection.parties
                          if p.company_id == company_id}
    host_parties = {party for owner, party in authority.parties
                    if owner == company_id}
    parties = set(scopes.party_ids) | {row.party_id for row in chart.party_links}
    if not parties.issubset(registered_parties & host_parties):
        raise CompanyChartGatewayError("Foreign/unregistered party in chart or V2 scope")
    # Assert validity even for unused chart mappings, jobs, and cost centers.
    validate_external_references(
        chart, verified_party_ids=frozenset(registered_parties & host_parties),
        verified_project_ids=frozenset(registered & authorized_projects),
        verified_task_scopes=scopes.task_scopes)
    return projection, company


def _period(journal: JournalState, company, company_id: str,
            fiscal_year_id: str, fiscal_period_id: str,
            posting_date: str, today: str) -> None:
    if type(journal) is not JournalState or journal.company_id != company_id:
        raise CompanyChartGatewayError("Company journal state mismatch")
    if journal.currency != "RIAL":
        raise CompanyChartGatewayError("V2 journal must be canonical RIAL")
    if _calendar_day(posting_date) > _calendar_day(today):
        raise CompanyChartGatewayError("Future accounting date forbidden")
    year = next((y for y in company.fiscal_years
                 if y.fiscal_year_id == fiscal_year_id), None)
    if year is None or not year.start_date <= posting_date <= year.end_date:
        raise CompanyChartGatewayError("Posting date outside registered fiscal year")
    period = next((p for p in journal.periods
                   if p.fiscal_period_id == fiscal_period_id), None)
    if (period is None or period.company_id != company_id or
            not year.start_date <= period.start_date <=
            posting_date <= period.end_date <= year.end_date):
        raise CompanyChartGatewayError("Fiscal period is unknown or outside fiscal year")
    if fiscal_period_id in replay_journal(journal).closed_period_ids:
        raise CompanyChartGatewayError("Closed fiscal period cannot accept a new posting")


def _source_unused(projection, journal: JournalState, company_id: str,
                   source: JournalSource) -> None:
    if any(type(item) is PostedJournal and
           item.source.source_id == source.source_id
           for item in journal.events):
        raise CompanyChartGatewayError("Commercial source already posted under an event ID")
    if any(lock.company_id == company_id and
           lock.business_source_id == source.source_id
           for lock in projection.posted_locks):
        raise CompanyChartGatewayError("Company registry source already locked as posted")


def _references(chart: ChartSnapshot, scopes: VerifiedScopes, source: JournalSource,
                references: tuple[PostingReference, ...], party_id: str,
                *, inventory_job_id: str | None = None,
                inventory_cost_center: str | None = None) -> None:
    if type(references) is not tuple or len(references) < 2 or len(references) > 100:
        raise CompanyChartGatewayError("At least two typed posting references are required")
    if source.kind != "independent" or not source.project_id:
        raise CompanyChartGatewayError("Only project-bound independent GL sources supported")
    if (source.project_id, source.source_id) not in scopes.independent_source_scopes:
        raise CompanyChartGatewayError("Source not verified in V2 project/document scopes")
    seen_party = not party_id
    for reference in references:
        if type(reference) is not PostingReference:
            raise CompanyChartGatewayError("Untyped journal account reference")
        if reference.project_id != source.project_id:
            raise CompanyChartGatewayError("Journal reference project differs from business source")
        if (inventory_job_id is not None and
                reference.job_id != inventory_job_id):
            raise CompanyChartGatewayError("Inventory source job differs from journal line")
        if (inventory_cost_center is not None and
                reference.cost_center_code != inventory_cost_center):
            raise CompanyChartGatewayError("Inventory source cost center differs from journal line")
        validate_posting_reference(
            chart, reference, verified_party_ids=scopes.party_ids,
            verified_project_ids=scopes.project_ids,
            verified_task_scopes=scopes.task_scopes)
        if party_id and reference.party_id == party_id:
            seen_party = True
        elif party_id and reference.party_id and reference.party_id != party_id:
            raise CompanyChartGatewayError("Posting references another business party")
    if not seen_party:
        raise CompanyChartGatewayError("Source party missing on journal references")


def preflight_company_chart_source(
    registry: CompanyRegistry, *, authority: VerifiedRegistryAuthority,
    company_id: str, actor_id: str, project_id: str,
    fiscal_year_id: str, fiscal_period_id: str, posting_date: str, today: str,
    chart: ChartSnapshot, scopes: VerifiedScopes, journal_state: JournalState,
    source_kind: str, references: tuple[PostingReference, ...],
    document_id: str = "", party_id: str = "",
    inventory_state: InventoryState | None = None, inventory_event_id: str = "",
) -> CompanyChartPreflight:
    """Strict preflight; caller must still prove input provenance and post atomically.

    sale/purchase delegates to registry's existing GL gate. Inventory uses
    replay-verified posted stock movement and the same company ownership/role
    policy; the inventory journal adapter still decides its accounting lines.
    """
    if type(source_kind) is not str or source_kind not in (
            "sale", "purchase", "inventory"):
        raise CompanyChartGatewayError("Only sale, purchase or inventory supported")
    projection, company = _registered_scope(
        registry, authority, company_id, actor_id, project_id, chart, scopes)
    _period(journal_state, company, company_id, fiscal_year_id,
            fiscal_period_id, posting_date, today)
    if source_kind in ("sale", "purchase"):
        if inventory_state is not None or inventory_event_id:
            raise CompanyChartGatewayError("Invoice source cannot include stock evidence")
        gate = verify_sale_purchase_gl_gate(
            registry, company_id=company_id, project_id=project_id,
            fiscal_year_id=fiscal_year_id, fiscal_period_id=fiscal_period_id,
            posting_date=posting_date, actor_id=actor_id, kind=source_kind,
            document_id=document_id, authority=authority, journal_state=journal_state,
            chart=chart, scopes=scopes, party_id=party_id)
        if CompanyPartyRef(company_id, party_id) not in projection.parties or (
                company_id, party_id) not in authority.parties:
            raise CompanyChartGatewayError("Document party not verified for company")
        source, inventory_revision = gate.journal_source, ""
        inventory_job_id = inventory_center_id = None
    else:
        if document_id or party_id:
            raise CompanyChartGatewayError("Inventory source must use recorded stock provenance")
        if type(inventory_state) is not InventoryState:
            raise CompanyChartGatewayError("Verified recorded inventory state required")
        inventory_replay = replay_inventory(inventory_state)
        if inventory_state.company_id != company_id:
            raise CompanyChartGatewayError("Inventory state belongs to another company")
        movements = [row for row in inventory_state.events
                     if type(row) is PostedMovement and
                     row.event.event_id == inventory_event_id]
        if len(movements) != 1:
            raise CompanyChartGatewayError("Inventory source requires a uniquely recorded movement")
        movement = movements[0]
        event = movement.event
        if (event.company_id != company_id or event.project_id != project_id or
                movement.authority.company_id != company_id or
                (event.source.kind, event.source.source_id)
                not in movement.authority.source_scopes):
            raise CompanyChartGatewayError("Stock event/company/project source mismatch")
        if event.actor_id != actor_id:
            raise CompanyChartGatewayError(
                "Inventory GL bridge requires the original verified movement actor")
        if event.project_id not in movement.authority.project_ids:
            raise CompanyChartGatewayError("Stock source lacks original verified project")
        if (event.job_id or event.cost_center_id) and (
                event.project_id, event.job_id, event.cost_center_id
                ) not in movement.authority.work_scopes:
            raise CompanyChartGatewayError("Stock work dimension lacks original host proof")
        if event.kind not in ("RECEIPT", "PRICE", "ISSUE", "RETURN", "REVERSAL"):
            raise CompanyChartGatewayError("Inventory movement has no supported financial posting")
        if event.kind == "RECEIPT" and event.cost_rial is None:
            raise CompanyChartGatewayError("Unpriced stock receipt has no financial posting")
        # Reuse the exact recorded commercial source ID; never take an arbitrary
        # client document ID or derive ownership from an event ID.
        source = JournalSource("independent", event.source.source_id,
                               project_id=project_id)
        inventory_revision = inventory_replay.revision
        inventory_job_id, inventory_center_id = event.job_id, event.cost_center_id
    _source_unused(projection, journal_state, company_id, source)
    _references(chart, scopes, source, references, party_id,
                inventory_job_id=inventory_job_id,
                inventory_cost_center=inventory_center_id)
    return CompanyChartPreflight(
        company_id, project_id, fiscal_year_id, fiscal_period_id,
        posting_date, actor_id, source_kind, source,
        projection.revision, journal_state.revision, inventory_revision)


__all__ = ["CompanyChartGatewayError", "CompanyChartPreflight",
           "preflight_company_chart_source"]
