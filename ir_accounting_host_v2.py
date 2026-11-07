"""Authenticated RIAL-only journal host boundary for Madar Desk.

This module does not issue invoices in the legacy TOMAN finance system. The
authority is a SERVER-SIDE resolver, never a copy of client-provided grants,
charts, business amounts or invoice status. Legacy cross-database issuance is
intentionally refused until a shared atomic transaction exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ir_chart_model import ChartSnapshot, validate_external_references
from ir_journal_sqlite import RIALJournalStorage
from ir_journal_v2 import (
    JournalLine, JournalSource, PostedJournal, VerifiedScopes,
    close_fiscal_period, post_journal, replay_journal, reverse_journal,
)
from money_policy import CompanyMoneyPolicy, require_rial_amount, snapshot_sha256


class RIALHostRefusal(ValueError):
    """A financial operation lacks authoritative evidence or a safe commit path."""


@dataclass(frozen=True, slots=True)
class TrustedAccountingPrincipal:
    """Resolved for the current session by the host, never deserialized from UI."""

    actor_id: str
    company_id: str
    authenticated: bool
    permissions: frozenset[str]
    project_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class VerifiedIssuedDocument:
    """Verified, committed, immutable RIAL-only source snapshot from host.

    'issued' means that the authoritative RIAL-only document was already
    issued; this journal adapter never changes invoice status. An invoice that
    needs a TOMAN posting or a second database write is NOT eligible.
    """

    company_id: str
    document_id: str
    kind: str  # sales | purchase
    status: str
    currency: str
    amount_rial: int
    party_id: str
    project_id: str
    source: JournalSource
    lines: tuple[JournalLine, ...]
    source_verified: bool
    legacy_finance_status: str  # none_verified | linked | unknown
    ledger_origin: str  # rial_v2_only | legacy_toman | unknown


class RIALHostAuthority(Protocol):
    """Server-side authoritative accessors; no method may trust UI-sent ACL."""

    def authenticate(self, session: object) -> TrustedAccountingPrincipal: ...

    def resolve_document(self, company_id: str, document_id: str) -> VerifiedIssuedDocument: ...

    def resolve_chart(self, company_id: str) -> ChartSnapshot: ...

    def resolve_scopes(self, company_id: str) -> VerifiedScopes: ...

    def resolve_money_policy(self, company_id: str) -> CompanyMoneyPolicy: ...


_PERMISSIONS = frozenset({"rial.read", "rial.read_all", "rial.post",
                          "rial.post_all", "rial.reverse", "rial.close_all"})


def _identifier(value: Any, label: str) -> str:
    from re import fullmatch
    if type(value) is not str or fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", value) is None:
        raise RIALHostRefusal("Invalid " + label)
    return value


def _principal(authority: RIALHostAuthority, session: object, company_id: str,
               permission: str) -> TrustedAccountingPrincipal:
    actor = authority.authenticate(session)
    if type(actor) is not TrustedAccountingPrincipal:
        raise PermissionError("Host authentication did not return a trusted principal")
    _identifier(actor.actor_id, "authenticated actor")
    _identifier(actor.company_id, "authenticated company")
    if (actor.authenticated is not True or actor.company_id != company_id
            or type(actor.permissions) is not frozenset
            or not actor.permissions <= _PERMISSIONS
            or type(actor.project_ids) is not frozenset
            or permission not in actor.permissions):
        raise PermissionError("Actor/company/finance permission denied")
    for project_id in actor.project_ids:
        _identifier(project_id, "authorized project")
    return actor


def _project_access(principal: TrustedAccountingPrincipal, project_id: str,
                    *, broad_permission: str) -> None:
    if project_id:
        _identifier(project_id, "document project")
    if not project_id or (project_id not in principal.project_ids and
                          broad_permission not in principal.permissions):
        raise PermissionError("Company-wide or project scope not authorized")


def _fields(command: object, fields: frozenset[str]) -> dict:
    if type(command) is not dict or set(command) != fields:
        raise RIALHostRefusal("Unexpected or missing RIAL command fields")
    for key, val in command.items():
        if type(val) is not str or not val or len(val) > 1100:
            raise RIALHostRefusal("Invalid RIAL command field: " + key)
    return command


def _event_id(company_id: str, action: str, immutable_identity: str) -> str:
    # Document identity, not UI retry/event IDs, owns deduplication.
    return "rv2." + action + "." + snapshot_sha256({
        "companyId": company_id, "action": action, "identity": immutable_identity,
    })[:48]


def _validate_document(doc: VerifiedIssuedDocument, company_id: str,
                       chart: ChartSnapshot, scopes: VerifiedScopes,
                       policy: CompanyMoneyPolicy) -> None:
    if type(doc) is not VerifiedIssuedDocument:
        raise RIALHostRefusal("Only server-resolved issued documents may post")
    _identifier(doc.document_id, "document ID")
    _identifier(doc.party_id, "document party")
    _identifier(doc.project_id, "document project")
    if doc.company_id != company_id or doc.kind not in ("sales", "purchase"):
        raise RIALHostRefusal("Document kind/company mismatch")
    if doc.status != "issued" or doc.currency != "RIAL":
        raise RIALHostRefusal("Only immutable issued canonical-RIAL documents may post")
    if (doc.ledger_origin != "rial_v2_only" or
            doc.legacy_finance_status != "none_verified"):
        raise RIALHostRefusal("Legacy TOMAN ledger requires a shared atomic issuance path")
    if doc.source_verified is not True:
        raise RIALHostRefusal("Document source has not been independently verified")
    if (type(chart) is not ChartSnapshot or type(scopes) is not VerifiedScopes
            or type(policy) is not CompanyMoneyPolicy
            or chart.company_id != company_id or policy.company_id != company_id):
        raise RIALHostRefusal("Company chart, policy or verified scopes mismatch")
    validate_external_references(
        chart, verified_party_ids=scopes.party_ids,
        verified_project_ids=scopes.project_ids,
        verified_task_scopes=scopes.task_scopes)
    if (doc.party_id not in scopes.party_ids or
            doc.project_id not in scopes.project_ids or
            type(doc.source) is not JournalSource or
            doc.source.project_id != doc.project_id or
            doc.source.kind == "card"):
        # Card and task are aliases for the same source in some clients.
        # Require the canonical 'task' source to prevent type-based dedupe bypass.
        raise RIALHostRefusal("Unverified business source/party/project or alias kind")
    require_rial_amount(doc.amount_rial, max_abs_rial=policy.max_abs_rial,
                        allow_zero=False)
    if type(doc.lines) is not tuple or not 2 <= len(doc.lines) <= 100:
        raise RIALHostRefusal("Verified document requires immutable journal lines")
    accounts = {a.code: a for a in chart.accounts}
    debit = credit = 0
    party_side = 0
    business_side = 0
    for line in doc.lines:
        if type(line) is not JournalLine:
            raise RIALHostRefusal("Unverified financial line")
        if line.reference.company_id != company_id:
            raise RIALHostRefusal("Cross-company document line")
        if line.reference.project_id != doc.project_id:
            raise RIALHostRefusal("Document lines must share verified project")
        if line.reference.party_id and line.reference.party_id != doc.party_id:
            raise RIALHostRefusal("Third-party receivable/payable on document")
        debit += line.debit_rial
        credit += line.credit_rial
        account = accounts.get(line.reference.account_code)
        if account is None:
            raise RIALHostRefusal("Missing document account")
        if doc.kind == "sales" and account.kind == "revenue":
            business_side += line.credit_rial - line.debit_rial
        elif doc.kind == "purchase" and account.kind in ("asset", "expense"):
            business_side += line.debit_rial - line.credit_rial
        if line.reference.party_id == doc.party_id:
            if doc.kind == "sales" and account.kind == "asset":
                party_side += line.debit_rial - line.credit_rial
            elif doc.kind == "purchase" and account.kind == "liability":
                party_side += line.credit_rial - line.debit_rial
    if (debit != doc.amount_rial or credit != doc.amount_rial
            or party_side != doc.amount_rial or business_side <= 0):
        raise RIALHostRefusal("Invoice amount does not equal balanced AR/AP journal")


class RIALAccountingHost:
    """Read / command bridge with mandatory authoritative identity resolution."""

    def __init__(self, storage: RIALJournalStorage, authority: RIALHostAuthority) -> None:
        if type(storage) is not RIALJournalStorage or authority is None:
            raise RIALHostRefusal("Dedicated journal storage and authority are required")
        for name in ("authenticate", "resolve_document", "resolve_chart",
                     "resolve_scopes", "resolve_money_policy"):
            if not callable(getattr(authority, name, None)):
                raise RIALHostRefusal("Missing server-side authority resolver: " + name)
        self._storage = storage
        self._authority = authority

    def read(self, session: object, *, company_id: str,
             project_id: str = "") -> dict:
        """Bridge.rialJournalRead; returns filtered, integer-RIAL evidence."""
        _identifier(company_id, "requested company")
        actor = _principal(self._authority, session, company_id, "rial.read")
        if project_id:
            _project_access(actor, project_id, broad_permission="rial.read_all")
        elif "rial.read_all" not in actor.permissions:
            raise PermissionError("Company-wide financial read is privileged")
        state = self._storage.read(company_id)
        if state is None:
            raise RIALHostRefusal("Company RIAL journal is not initialized")
        replay = replay_journal(state)
        rows = []
        totals: dict[str, list[int]] = {}
        for event in state.events:
            if type(event) is not PostedJournal:
                continue
            if project_id and event.source.project_id != project_id:
                continue
            journal_lines = []
            for line in event.lines:
                debit, credit = line.debit_rial, line.credit_rial
                item = totals.setdefault(line.reference.account_code, [0, 0])
                item[0] += debit
                item[1] += credit
                require_rial_amount(item[0])
                require_rial_amount(item[1])
                journal_lines.append({
                    "accountCode": line.reference.account_code,
                    "projectId": line.reference.project_id,
                    "taskId": line.reference.task_id,
                    "costCenterCode": line.reference.cost_center_code,
                    "partyId": line.reference.party_id,
                    "debitRial": debit, "creditRial": credit,
                })
            rows.append({
                "eventId": event.event_id, "fiscalPeriodId": event.fiscal_period_id,
                "postingDate": event.posting_date, "actorId": event.actor_id,
                "source": {"kind": event.source.kind,
                           "sourceId": event.source.source_id,
                           "projectId": event.source.project_id,
                           "taskId": event.source.task_id,
                           "checklistId": event.source.checklist_id},
                "reversalOf": event.reversal_of,
                "lines": journal_lines,
            })
        return {
            "companyId": company_id, "projectId": project_id,
            "currency": "RIAL", "revision": replay.revision,
            "postingCount": len(rows),
            "closedFiscalPeriodIds": sorted(replay.closed_period_ids),
            "positions": [{"accountCode": code, "debitRial": values[0],
                           "creditRial": values[1],
                           "balanceRial": values[0] - values[1]}
                          for code, values in sorted(totals.items())],
            "entries": rows,
        }

    def command(self, session: object, command: dict,
                *, today: str) -> dict:
        """Bridge.rialJournalCommand; never accepts caller-supplied monetary data."""
        if type(command) is not dict:
            raise RIALHostRefusal("Command must be an object")
        command_type = command.get("type")
        required = {"type", "companyId", "fiscalPeriodId", "expectedRevision"}
        if command_type == "document.post":
            required |= {"documentId", "postingDate"}
            permission = "rial.post"
        elif command_type == "journal.reverse":
            required |= {"originalEventId", "postingDate", "reason"}
            permission = "rial.reverse"
        elif command_type == "period.close":
            required |= {"closingDate"}
            permission = "rial.close_all"
        else:
            raise RIALHostRefusal("Unsupported RIAL journal command")
        payload = _fields(command, frozenset(required))
        company_id = _identifier(payload["companyId"], "company")
        _identifier(payload["fiscalPeriodId"], "fiscal period")
        actor = _principal(self._authority, session, company_id, permission)
        if command_type == "document.post":
            doc_id = _identifier(payload["documentId"], "issued document")
            document = self._authority.resolve_document(company_id, doc_id)
            if type(document) is not VerifiedIssuedDocument or document.document_id != doc_id:
                raise RIALHostRefusal("Authoritative document identity mismatch")
            _project_access(actor, document.project_id, broad_permission="rial.post_all")
            chart = self._authority.resolve_chart(company_id)
            scopes = self._authority.resolve_scopes(company_id)
            money_policy = self._authority.resolve_money_policy(company_id)
            _validate_document(document, company_id, chart, scopes, money_policy)
            event_id = _event_id(company_id, "doc", doc_id)

            def operation(old):
                return post_journal(
                    old, company_id=company_id,
                    fiscal_period_id=payload["fiscalPeriodId"],
                    event_id=event_id, actor_id=actor.actor_id,
                    posting_date=payload["postingDate"],
                    source=document.source, lines=document.lines,
                    chart=chart, scopes=scopes, money_policy=money_policy,
                    expected_revision=old.revision, today=today)

        elif command_type == "journal.reverse":
            original_id = _identifier(payload["originalEventId"], "original event")
            event_id = _event_id(company_id, "reverse", original_id)

            def operation(old):
                origin = next((row for row in old.events
                               if type(row) is PostedJournal and row.event_id == original_id
                               and not row.reversal_of), None)
                if origin is None:
                    raise RIALHostRefusal("Original journal is not a posted original")
                _project_access(actor, origin.source.project_id,
                                broad_permission="rial.post_all")
                return reverse_journal(
                    old, company_id=company_id, original_event_id=original_id,
                    event_id=event_id, actor_id=actor.actor_id,
                    fiscal_period_id=payload["fiscalPeriodId"],
                    posting_date=payload["postingDate"],
                    reason=payload["reason"], expected_revision=old.revision,
                    today=today)

        else:
            event_id = _event_id(company_id, "close", payload["fiscalPeriodId"])

            def operation(old):
                return close_fiscal_period(
                    old, company_id=company_id, fiscal_period_id=payload["fiscalPeriodId"],
                    event_id=event_id, actor_id=actor.actor_id,
                    closing_date=payload["closingDate"],
                    expected_revision=old.revision, today=today)

        previous_revision = payload["expectedRevision"]
        _identifier(previous_revision, "expected revision")
        result = self._storage.mutate(company_id, previous_revision, operation)
        return {"companyId": company_id, "currency": "RIAL", "type": command_type,
                "eventId": event_id, "revision": result.revision,
                "changed": result.revision != previous_revision}


__all__ = ["RIALHostRefusal", "TrustedAccountingPrincipal",
           "VerifiedIssuedDocument", "RIALHostAuthority", "RIALAccountingHost"]
