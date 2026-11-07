"""Pure, narrowly scoped supplier-intake bill -> RIAL journal mirror.

The caller MUST be an authenticated host holding the finance write lock. This
module never accesses a database, authenticates a network principal, or grants
permission based on a client-supplied certificate. The host must obtain the
before snapshot, actor/accounts, cards/projects and clock itself and verify an
unchanged finance CAS before committing.

IMPORTANT: current app_storage's RIAL history guard rejects accounting.events
mutations. The result is a *candidate*, not presently a committable host flow.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json

from accounting_core import accounting_view
from accounting_service import apply_madar_accounting
from finance import validate_finance_state
from ir_chart_model import ChartAccount, ChartSnapshot, JobReference, PostingReference
from ir_finance_v2_extension import _entry, load_finance_rial_journal
from ir_journal_sqlite import _validate_append_only
from ir_journal_v2 import JournalLine, JournalSource, VerifiedScopes, post_journal
from money_policy import CompanyMoneyPolicy, require_rial_amount, snapshot_sha256
from purchase_intake import selected_step, validate_intakes


@dataclass(frozen=True, slots=True)
class PurchaseSourceAttestation:
    """Auditable digest of host-reconstructed values, NOT a cryptographic signature."""

    company_id: str
    project_id: str
    card_id: str
    step_id: str
    intake_id: str
    bill_id: str
    supplier_id: str
    supplier_name: str
    quantity: int
    unit_price_toman: int
    total_toman: int
    total_rial: int
    issue_event_id: str
    rial_event_id: str
    finance_before_sha256: str
    reducer_after_sha256: str
    expected_journal_revision: str
    source_fingerprint: str
    attestation_sha256: str


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _unique_company(before):
    extension = before.get("rialJournalV2")
    if type(extension) is not dict or type(extension.get("companies")) is not dict:
        raise ValueError("Host must activate unified RIAL finance before purchase issue")
    companies = extension["companies"]
    if len(companies) != 1:
        raise PermissionError("Purchase requires an explicitly mapped single RIAL company")
    return next(iter(companies))


def _restricted_purchase_chart(company_id, project_id, card_id, bill_id, supplier_id):
    """Temporary shadow chart for intake costs; NOT authoritative company COA."""
    job_id = "purchase-" + sha256(
        (company_id + "\x00" + project_id + "\x00" + card_id).encode("utf-8")
    ).hexdigest()[:24]
    chart = ChartSnapshot(company_id, accounts=(
        ChartAccount(company_id, "20", "KOL", None, "Liabilities", "liability"),
        ChartAccount(company_id, "2001", "MOEIN", "20", "Suppliers", "liability"),
        ChartAccount(company_id, "200101", "TAFSILI", "2001", "Supplier payable",
                     "liability", accountable=True),
        ChartAccount(company_id, "50", "KOL", None, "Expenses", "expense"),
        ChartAccount(company_id, "5001", "MOEIN", "50", "Supplier services", "expense"),
        ChartAccount(company_id, "500101", "TAFSILI", "5001", "Purchase expense",
                     "expense", accountable=True),
    ), project_ids=(project_id,),
        jobs=(JobReference(company_id, job_id, project_id, card_id),))
    scopes = VerifiedScopes(
        party_ids=frozenset({supplier_id}),
        project_ids=frozenset({project_id}),
        task_scopes=frozenset({(project_id, card_id)}),
        independent_source_scopes=frozenset({(project_id, bill_id)}),
    )
    return chart, scopes, job_id


def _verified_converted_intake(before, bill, bill_id, cards, projects):
    """Rebuild the exact intake.convert source projection; reject ambiguous links."""
    if type(before.get("purchaseIntakes")) is not dict:
        raise ValueError("Verified converted supplier intake required")
    intakes = before["purchaseIntakes"]
    validate_intakes(intakes)
    rows = [row for row in intakes["records"].values()
            if row["status"] == "converted" and row["billId"] == bill_id]
    if len(rows) != 1:
        raise ValueError("Purchase bill requires exactly one converted priced intake")
    row = rows[0]
    project_id, card_id, step_id = (row[k] for k in ("projectId", "cardId", "stepId"))
    source_id = card_id + ":" + step_id
    matching_cards = [card for card in cards if type(card) is dict and
                      card.get("id") == card_id and card.get("projectId") == project_id
                      and card.get("deleted") is not True]
    if len(matching_cards) != 1 or len(
            [project for project in projects
             if type(project) is dict and project.get("id") == project_id]) != 1:
        raise PermissionError("Supplier intake task/project no longer host verified")
    if selected_step(matching_cards[0], step_id) != row["description"]:
        raise PermissionError("Supplier intake step differs from authoritative task")
    if type(row["quantity"]) is not int or row["quantity"] <= 0 or (
            type(row["unitPrice"]) is not int or row["unitPrice"] <= 0):
        raise ValueError("Unpriced, fractional, or zero-price intake cannot be posted")
    supplier = row["supplier"]
    if type(supplier) is not dict or supplier.get("kind") != "supplier" or (
            type(supplier.get("name")) is not str or not supplier["name"].strip()):
        raise ValueError("Named supplier is mandatory")
    total_toman = row["quantity"] * row["unitPrice"]
    if total_toman <= 0:
        raise ValueError("Invalid supplier intake total")
    links = before.get("accountingSources")
    if type(links) is not dict:
        raise ValueError("Task accounting source index is required")
    link = links.get(bill_id)
    if (type(link) is not dict or link.get("kind") != "purchase" or
            link.get("projectId") != project_id or
            link.get("cardIds") != [card_id] or link.get("sourceIds") != [source_id]):
        raise PermissionError("Purchase source does not identify the original task step")
    # Never allow a second bill for the same commercial work, even with a new
    # eventId and a different bill ID.
    for other_bill_id, other in links.items():
        if other_bill_id != bill_id and type(other) is dict and (
                other.get("kind") == "purchase" and
                source_id in other.get("sourceIds", ())):
            raise ValueError("Business work step already belongs to another purchase bill")
    expected_payload = {
        "kind": "purchase", "projectId": project_id, "cardId": card_id,
        "party": supplier,
        "lines": [{"id": step_id, "description": row["description"],
                   "quantity": row["quantity"], "unitPrice": row["unitPrice"]}],
        "discount": 0, "tax": 0, "advance": 0,
        "subtotal": total_toman, "total": total_toman, "sourceId": source_id,
    }
    source_fingerprint = _digest(expected_payload)
    if link["fingerprint"] != source_fingerprint:
        raise PermissionError("Purchase source fingerprint differs from converted intake")
    if (bill.get("partyId") != supplier["id"] or
            bill.get("sourceType") != "task-costs" or
            bill.get("sourceId") != "expense:" + _digest([step_id])[:24] or
            bill.get("discount") != 0 or bill.get("tax") != 0 or
            bill.get("total") != total_toman or bill.get("subtotal") != total_toman or
            type(bill.get("lines")) is not list or len(bill["lines"]) != 1):
        raise ValueError("Supplier bill is not the priced intake's exact purchase document")
    line = bill["lines"][0]
    if (line.get("quantity") != row["quantity"] or
            line.get("unitPrice") != row["unitPrice"] or
            line.get("total") != total_toman or
            line.get("description") != row["description"] or
            line.get("accountId") != "5000"):
        raise ValueError("Purchase bill line differs from original quantity and TOMAN unit price")
    return row, source_fingerprint, total_toman


def compose_purchase_issue_with_rial(
    finance_before, finance_after, command, *,
    actor, accounts, cards, projects, now,
    expected_finance_sha256, expected_journal_revision,
):
    """Return pure {state,result,sourceContract}; never perform a host commit.

    All keyword inputs must be derived under the authenticated host lock from
    its own current state, rather than from a client payload. The reducer is
    executed again and must reproduce finance_after exactly. The host must
    enforce the expected snapshot SHA/CAS against current authoritative state
    immediately before using the candidate. Legacy app_storage presently
    rejects accounting journal changes, so this is NOT integration-ready.
    """
    validate_finance_state(finance_before)
    validate_finance_state(finance_after)
    if type(command) is not dict or set(command) != {
            "type", "eventId", "documentId", "projectId", "postingDate"} or (
            command["type"] != "document.issue"):
        raise ValueError("Only an explicit task-linked purchase document.issue is supported")
    if (type(expected_finance_sha256) is not str or
            snapshot_sha256(finance_before) != expected_finance_sha256):
        raise PermissionError("Authoritative finance snapshot proof mismatch")
    if type(expected_journal_revision) is not str:
        raise ValueError("Expected RIAL journal revision required")
    company_id = _unique_company(finance_before)
    prior = load_finance_rial_journal(finance_before, company_id)
    if prior.revision != expected_journal_revision:
        raise ValueError("Stale RIAL journal revision")
    if finance_after["rialJournalV2"] != finance_before["rialJournalV2"]:
        raise ValueError("Old accounting reducer must not modify RIAL extension")
    # Re-run the actual authorized host reducer; exact equivalence catches
    # arbitrary unrelated mutations to accounting history, receipts and links.
    produced = apply_madar_accounting(
        finance_before, command, actor=actor, accounts=accounts,
        cards=cards, projects=projects, now=now,
    )
    if not produced["changed"] or produced["state"] != finance_after:
        raise ValueError("Expected exactly one new authorized supplier bill issue")
    if (finance_before.get("accountingSources") != finance_after.get("accountingSources")
            or finance_before.get("purchaseIntakes") != finance_after.get("purchaseIntakes")):
        raise ValueError("Issuance cannot silently rewrite source or supplier intake")
    prior_events = finance_before["accounting"]["events"]
    next_events = finance_after["accounting"]["events"]
    if len(next_events) != len(prior_events) + 1 or next_events[:-1] != prior_events:
        raise ValueError("Exactly one append-only legacy accounting event is required")
    historic = next_events[-1]
    core_command = historic["command"]
    if (core_command != {"type": "bill.issue", "eventId": command["eventId"],
                         "billId": command["documentId"],
                         "postingDate": command["postingDate"]} or
            historic["actor"] != actor):
        raise PermissionError("Legacy journal event not bound to authorized bill issue")
    # A validated accounting projection checks the TOMAN event's hash chain,
    # approved -> issued transition and balanced AP/expense postings.
    before_projection = accounting_view(
        finance_before["accounting"], actor=actor, accounts=accounts)
    after_projection = accounting_view(
        finance_after["accounting"], actor=actor, accounts=accounts)
    bill_id = command["documentId"]
    bill_before = before_projection["bills"].get(bill_id)
    bill_after = after_projection["bills"].get(bill_id)
    if (bill_before is None or bill_before["status"] != "approved" or
            bill_after is None or bill_after["status"] != "issued" or
            bill_after["partyId"] != bill_before["partyId"] or
            bill_after["postingDate"] != command["postingDate"] or
            bill_after["postedEntryId"] != "J:" + command["eventId"] or
            before_projection["parties"].get(bill_before["partyId"], {}).get("kind")
            not in ("vendor", "both")):
        raise ValueError("Purchase bill must move from approved to issued with named vendor")
    # The old core's source link, price and intake form the business identity.
    row, source_fingerprint, total_toman = _verified_converted_intake(
        finance_before, bill_before, bill_id, cards, projects)
    if (bill_after["total"] != total_toman or
            bill_after["number"] != before_projection["sequence"]["bill"] + 1 or
            command["projectId"] != row["projectId"]):
        raise ValueError("Purchase issue number, project or amount differs")
    party_record = before_projection["parties"].get(row["supplier"]["id"])
    if (type(party_record) is not dict or
            party_record.get("name") != row["supplier"]["name"] or
            party_record.get("kind") not in ("vendor", "both")):
        raise PermissionError("Named supplier identity differs from authoritative party registry")
    old_entry = after_projection["journals"][-1]
    if (old_entry["id"] != "J:" + command["eventId"] or
            old_entry["sourceType"] != "bill.issue" or
            old_entry["sourceId"] != bill_id or
            old_entry["date"] != command["postingDate"] or
            sum(x["debit"] for x in old_entry["lines"]) != total_toman or
            sum(x["credit"] for x in old_entry["lines"]) != total_toman or
            not any(x["accountId"] == "2000" and x.get("partyId") == row["supplier"]["id"]
                    and x["credit"] == total_toman for x in old_entry["lines"])):
        raise ValueError("Legacy purchase posting does not recognize exact supplier payable")
    amount_rial = require_rial_amount(total_toman * 10, allow_zero=False)
    day = command["postingDate"]
    if now[:10] < day:
        raise ValueError("Future RIAL purchase issue is forbidden")
    periods = [p for p in prior.periods if p.start_date <= day <= p.end_date]
    if len(periods) != 1:
        raise ValueError("No unique fiscal period for verified purchase issue")
    if any(event.source.kind == "independent" and
           event.source.source_id == bill_id and
           event.source.project_id == row["projectId"] and
           not event.reversal_of for event in prior.events if hasattr(event, "source")):
        raise ValueError("Purchase bill already has a RIAL mirror with another event ID")
    event_id = "purchase-" + sha256(json.dumps(
        [command["eventId"], bill_id], separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    chart, scopes, job_id = _restricted_purchase_chart(
        company_id, row["projectId"], row["cardId"], bill_id, row["supplier"]["id"])
    ref = {"project_id": row["projectId"], "job_id": job_id, "task_id": row["cardId"]}
    candidate = post_journal(
        prior, company_id=company_id, fiscal_period_id=periods[0].fiscal_period_id,
        event_id=event_id, actor_id=actor, posting_date=day,
        source=JournalSource("independent", bill_id, row["projectId"]),
        lines=(
            JournalLine(PostingReference(company_id, "500101", **ref),
                        debit_rial=amount_rial),
            JournalLine(PostingReference(company_id, "200101",
                                         party_id=row["supplier"]["id"], **ref),
                        credit_rial=amount_rial),
        ), chart=chart, scopes=scopes, money_policy=CompanyMoneyPolicy(company_id),
        expected_revision=expected_journal_revision, today=now[:10],
    )
    _validate_append_only(prior, candidate)
    if len(candidate.events) != len(prior.events) + 1:
        raise ValueError("Expected exactly one RIAL purchase mirror")
    output = deepcopy(finance_after)
    output["rialJournalV2"]["companies"][company_id] = _entry(candidate)
    validate_finance_state(output)
    facts = {
        "company_id": company_id, "project_id": row["projectId"],
        "card_id": row["cardId"], "step_id": row["stepId"],
        "intake_id": row["id"], "bill_id": bill_id,
        "supplier_id": row["supplier"]["id"], "supplier_name": row["supplier"]["name"],
        "quantity": row["quantity"], "unit_price_toman": row["unitPrice"],
        "total_toman": total_toman, "total_rial": amount_rial,
        "issue_event_id": command["eventId"], "rial_event_id": event_id,
        "finance_before_sha256": expected_finance_sha256,
        "reducer_after_sha256": snapshot_sha256(finance_after),
        "expected_journal_revision": expected_journal_revision,
        "source_fingerprint": source_fingerprint,
    }
    contract = PurchaseSourceAttestation(**facts, attestation_sha256=_digest(facts))
    return {"state": output, "changed": True, "result": {
        **deepcopy(produced["result"]), "rialJournalEventId": event_id,
        "rialCompanyId": company_id, "rialAmount": str(amount_rial),
        "postingMode": "verified-intake-purchase-shadow",
    }, "sourceContract": asdict(contract)}


__all__ = ["PurchaseSourceAttestation", "compose_purchase_issue_with_rial"]
