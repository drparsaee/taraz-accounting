"""Trusted accounting orchestration inside Madar's existing finance domain.

The host commits this *entire* updated finance snapshot with its existing
atomic SQLite CAS or atomic JSON operation. No side database or direct file IO.
Only an authenticated admin may issue, settle or read this first-phase ledger.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import re

from accounting_core import (apply_accounting_command, accounting_view,
                             empty_accounting_state, validate_accounting_state)
from accounting_task_adapter import task_purchase_draft, task_sales_draft
from accounting_reporting import ledger_reports
from purchase_intake import empty_intakes, validate_intakes, apply_intake, mark_converted
from finance import card_cost_summary, invoice_status

_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")


def _id(value, field):
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise ValueError("Invalid " + field)
    return value


def _admin(actor, accounts):
    if not isinstance(accounts, dict) or actor not in accounts:
        raise PermissionError("No authenticated accounting actor")
    account = accounts[actor]
    if not isinstance(account, dict) or account.get("username") != actor or account.get("role") != "admin":
        raise PermissionError("Only an authenticated finance administrator may perform this operation")


def _pure_fingerprint(payload):
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _project(project_id, projects):
    if not isinstance(projects, list):
        raise ValueError("Invalid project catalog")
    _id(project_id, "projectId")
    matches = [project for project in projects if isinstance(project, dict) and project.get("id") == project_id]
    if len(matches) != 1:
        raise ValueError("Unknown or duplicate project")
    return matches[0]


def _source(finance_state):
    if not isinstance(finance_state, dict):
        raise ValueError("Invalid finance state")
    accounting = finance_state.get("accounting", empty_accounting_state())
    links = finance_state.get("accountingSources", {})
    validate_accounting_state(accounting)
    if not isinstance(links, dict):
        raise ValueError("Invalid source index")
    return accounting, links


def validate_accounting_extension(finance_state):
    """Strictly validate the *optional* extension without migrating old data."""
    accounting, links = _source(finance_state)
    internal = {"local": {"username": "local", "role": "admin", "projects": None}}
    projection = accounting_view(accounting, actor="local", accounts=internal)
    ids = set(projection["invoices"]) | set(projection["bills"])
    for ident, record in links.items():
        _id(ident, "document index")
        if ident not in ids or not isinstance(record, dict) or set(record) != {
                "projectId", "cardIds", "sourceIds", "fingerprint", "kind"}:
            raise ValueError("Invalid task/document accounting link")
        _id(record["projectId"], "link project")
        if record["kind"] not in ("sales", "purchase"):
            raise ValueError("Invalid source document kind")
        if (record["kind"] == "sales") != (ident in projection["invoices"]):
            raise ValueError("Accounting document/link kind mismatch")
        if not isinstance(record["cardIds"], list) or not isinstance(record["sourceIds"], list):
            raise ValueError("Invalid source references")
        if any(_id(i, "card id") != i for i in record["cardIds"]):
            raise ValueError("Invalid task references")
        if any(not isinstance(i, str) or not i or len(i) > 350 for i in record["sourceIds"]):
            raise ValueError("Invalid expense sources")
        if not isinstance(record["fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", record["fingerprint"]):
            raise ValueError("Invalid source fingerprint")
    return True


def _apply(state, command, *, actor, accounts, now):
    out = apply_accounting_command(state, command, actor=actor, accounts=accounts, now=now)
    return out["state"], out["result"]


def _party(state, party, *, actor, accounts, now, event_id):
    if not isinstance(party, dict) or set(party) != {"id", "name", "kind", "reference"}:
        raise ValueError("Explicit named party required")
    kind = "vendor" if party["kind"] == "supplier" else party["kind"]
    if kind not in ("customer", "vendor"):
        raise ValueError("Invalid accounting party kind")
    current = accounting_view(state, actor=actor, accounts=accounts)["parties"].get(party["id"])
    if current:
        if current["name"] != party["name"] or current["kind"] not in (kind, "both"):
            raise ValueError("Conflicting identity for existing named party")
        return state
    next_state, _ = _apply(state, {"type": "party.register", "eventId": event_id + ":party",
                                   "partyId": party["id"], "name": party["name"], "kind": kind},
                           actor=actor, accounts=accounts, now=now)
    return next_state


def _document(state, draft, *, event_id, now, actor, accounts):
    is_sales = draft["kind"] == "sales"
    doc_id = ("S" if is_sales else "B") + "-" + _pure_fingerprint(event_id)[:24]
    lines = [{"description": line["description"], "quantity": line["quantity"],
              "unitPrice": line["unitPrice"]} for line in draft["lines"]]
    command = {"type": "invoice.create" if is_sales else "bill.create",
               "eventId": event_id + ":document",
               "invoiceId" if is_sales else "billId": doc_id,
               "partyId": draft["party"]["id"], "documentDate": now[:10],
               "lines": lines, "discount": draft["discount"], "tax": draft["tax"],
               "sourceType": "task" if is_sales else "task-costs",
               "sourceId": draft["sourceId"] if is_sales else (
                   "expense:" + _pure_fingerprint(
                       sorted(line["id"] for line in draft["lines"]))[:24])}
    next_state, result = _apply(state, command, actor=actor, accounts=accounts, now=now)
    return next_state, doc_id, result


def _core_command(command, links):
    typ = command["type"]
    if typ in ("document.review", "document.issue", "document.cancel"):
        expected = ({"type", "eventId", "documentId", "projectId"} |
                    ({"postingDate"} if typ == "document.issue" else
                     {"reason"} if typ == "document.cancel" else set()))
        if set(command) != expected:
            raise ValueError("Invalid document review/issue command")
        record = links.get(_id(command.get("documentId"), "documentId"))
        if not record:
            raise ValueError("Document not in task accounting index")
        is_sales = record["kind"] == "sales"
        suffix = ".approve" if typ == "document.review" else (
            ".cancel" if typ == "document.cancel" else ".issue")
        actual = ("invoice" if is_sales else "bill") + suffix
        out = {"type": actual, "eventId": command["eventId"],
               "invoiceId" if is_sales else "billId": command["documentId"]}
        if typ.endswith(".issue"):
            out["postingDate"] = command["postingDate"]
        if typ.endswith(".cancel"):
            out["reason"] = command["reason"]
        return out
    if typ in ("receipt.record", "payment.record"):
        # Allocations are identified by invoice/bill IDs held in the core.
        return {key: deepcopy(value) for key, value in command.items()}
    if typ in ("funds.deposit", "funds.transfer", "journal.manual",
               "journal.reverse", "period.close", "account.create",
               "party.register", "item.create", "item.update"):
        return deepcopy(command)
    raise ValueError("Unsupported accounting command")


def apply_madar_accounting(finance_state, command, *, actor, accounts, cards,
                           projects, now):
    """Pure transactional reducer; the host MUST CAS-commit returned finance data."""
    _admin(actor, accounts)
    if not isinstance(command, dict) or not isinstance(command.get("type"), str):
        raise ValueError("Invalid accounting command")
    event_id = _id(command.get("eventId"), "eventId")
    if (not isinstance(now, str) or len(now) > 64 or
            datetime.fromisoformat(now.replace("Z", "+00:00")).utcoffset() is None):
        raise ValueError("Trusted timezone-aware timestamp required")
    existing, links = _source(finance_state)
    new_state = deepcopy(existing)
    new_links = deepcopy(links)
    kind = command["type"]
    if kind in ("intake.create", "intake.price", "intake.cancel"):
        saved_intakes = finance_state.get("purchaseIntakes", empty_intakes())
        intake = apply_intake(saved_intakes, command, cards=cards,
                              projects=projects, now=now)
        clone = deepcopy(finance_state)
        clone["purchaseIntakes"] = intake["state"]
        if kind == "intake.create":
            # Register the named supplier immediately, with ZERO payable.
            # Merely accepting unpriced work must never create a journal.
            clone["accounting"] = _party(
                deepcopy(existing), command["supplier"], actor=actor,
                accounts=accounts, now=now, event_id=event_id)
            clone["accountingSources"] = deepcopy(links)
        from finance import validate_finance_state
        validate_finance_state(clone)
        return {"state": clone, "changed": intake["changed"], "result": intake["result"]}
    if kind == "intake.convert":
        if set(command) != {"type", "eventId", "intakeId"}:
            raise ValueError("Invalid supplier intake conversion command")
        intakes = finance_state.get("purchaseIntakes", empty_intakes())
        validate_intakes(intakes)
        intake_id = _id(command["intakeId"], "intakeId")
        row = intakes["records"].get(intake_id)
        if row is None:
            raise ValueError("Unrecognized supplier intake")
        intended_id = "B-" + _pure_fingerprint(event_id)[:24]
        if row["status"] == "converted" and row["billId"] == intended_id:
            return {"state": deepcopy(finance_state), "changed": False,
                    "result": {"documentId": intended_id, "kind": "purchase",
                               "intakeId": intake_id, "status": "draft"}}
        if row["status"] != "priced":
            raise ValueError("Add supplier unit price before creating purchase bill")
        _project(row["projectId"], projects)
        source = row["cardId"] + ":" + row["stepId"]
        documents = accounting_view(new_state, actor=actor, accounts=accounts)["bills"]
        for existing_id, link in links.items():
            if (link["kind"] == "purchase" and source in link["sourceIds"] and
                    documents.get(existing_id, {}).get("status") != "cancelled"):
                raise ValueError("Work step is already part of another supplier bill")
        total = row["quantity"] * row["unitPrice"]
        payload = {"kind": "purchase", "projectId": row["projectId"],
                   "cardId": row["cardId"], "party": row["supplier"],
                   "lines": [{"id": row["stepId"], "description": row["description"],
                              "quantity": row["quantity"], "unitPrice": row["unitPrice"]}],
                   "discount": 0, "tax": 0, "advance": 0, "subtotal": total,
                   "total": total, "sourceId": source}
        new_state = _party(new_state, payload["party"], actor=actor, accounts=accounts,
                           now=now, event_id=event_id)
        new_state, doc_id, result = _document(
            new_state, payload, event_id=event_id, actor=actor, accounts=accounts, now=now)
        new_links[doc_id] = {"projectId": row["projectId"], "cardIds": [row["cardId"]],
                             "sourceIds": [source], "fingerprint": _pure_fingerprint(payload),
                             "kind": "purchase"}
        clone = deepcopy(finance_state)
        clone["accounting"] = new_state
        clone["accountingSources"] = new_links
        clone["purchaseIntakes"] = mark_converted(intakes, intake_id, doc_id, now)
        from finance import validate_finance_state
        validate_finance_state(clone)
        return {"state": clone, "changed": clone != finance_state,
                "result": {**result, "kind": "purchase", "intakeId": intake_id}}
    if kind == "document.create":
        required = {"type", "eventId", "projectId", "kind", "documentId", "partyId",
                    "documentDate", "lines"}
        if not required <= set(command) or set(command) - required - {"discount", "tax", "note"}:
            raise ValueError("Invalid standalone accounting document")
        project_id = _id(command["projectId"], "projectId")
        _project(project_id, projects)
        if command["kind"] not in ("sales", "purchase"):
            raise ValueError("Invalid standalone document kind")
        doc_id = _id(command["documentId"], "documentId")
        new_link = {"projectId": project_id, "cardIds": [], "sourceIds": [],
                    "fingerprint": _pure_fingerprint(command),
                    "kind": command["kind"]}
        if doc_id in new_links and new_links[doc_id] != new_link:
            raise ValueError("Duplicate or conflicting standalone document ID")
        inner = {"type": "invoice.create" if command["kind"] == "sales" else "bill.create",
                 "eventId": event_id,
                 "invoiceId" if command["kind"] == "sales" else "billId": doc_id,
                 "partyId": command["partyId"], "documentDate": command["documentDate"],
                 "lines": deepcopy(command["lines"]),
                 "discount": command.get("discount", 0), "tax": command.get("tax", 0)}
        if "note" in command:
            inner["note"] = command["note"]
        new_state, result = _apply(new_state, inner, actor=actor, accounts=accounts, now=now)
        new_links[doc_id] = new_link
        outcome = {**result, "kind": command["kind"], "sourceCardIds": []}
    if kind in ("draft.sales.fromTask", "draft.purchase.fromCosts"):
        allowed = ({"type", "eventId", "projectId", "cardId", "party", "lines",
                    "discount", "tax", "advance"} if kind == "draft.sales.fromTask"
                   else {"type", "eventId", "projectId", "party", "selections",
                         "basis", "approveEstimate"})
        if set(command) != allowed:
            raise ValueError("Invalid task accounting draft command")
        project_id = command.get("projectId")
        _project(project_id, projects)
        grants = [project_id]  # server checks role + selected project; never accept client grants
        if kind == "draft.sales.fromTask":
            card_id = _id(command.get("cardId"), "cardId")
            matches = [item for item in cards if isinstance(item, dict) and item.get("id") == card_id]
            if len(matches) != 1:
                raise ValueError("Card missing or duplicate")
            # Old finance.py issues an independent local invoice sequence.
            # It must not be counted as another sale in this new general ledger
            # before a deliberate reconciliation/migration has been performed.
            for legacy in finance_state.get("invoices", []):
                if legacy["cardId"] == card_id and invoice_status(
                        finance_state, legacy["id"])["status"] in {"Issued", "Paid"}:
                    raise ValueError(
                        "Task already has an issued legacy sales invoice; "
                        "reconcile it before creating another accounting invoice")
            drafted = task_sales_draft(
                task=matches[0], projects=projects, project_id=project_id,
                customer=command["party"], lines=command["lines"],
                discount=command["discount"], tax=command["tax"], advance=command["advance"],
                event_id=event_id, granted_project_ids=grants)
            references = [card_id]
            sources = ["task:" + card_id]
        else:
            drafted = task_purchase_draft(
                tasks=cards, projects=projects, finance_state=finance_state,
                project_id=project_id, supplier=command["party"],
                selections=command["selections"], basis=command["basis"],
                approve_estimate=command["approveEstimate"],
                event_id=event_id, granted_project_ids=grants)
            references = [s["cardId"] for s in command["selections"]]
            sources = [s["cardId"] + ":" + s["sourceId"] for s in command["selections"]]
            # Another event must not invoice the same expense source again.
            intended_id = "B-" + _pure_fingerprint(event_id)[:24]
            existing_bills = accounting_view(
                new_state, actor=actor, accounts=accounts)["bills"]
            for existing_id, link in new_links.items():
                if link["kind"] == "purchase" and set(link["sourceIds"]) & set(sources):
                    if (existing_id != intended_id and
                            existing_bills.get(existing_id, {}).get("status") != "cancelled"):
                        raise ValueError("Cost source already included in another purchase bill")
        payload = drafted["document"]
        new_state = _party(new_state, payload["party"], actor=actor, accounts=accounts,
                           now=now, event_id=event_id)
        new_state, doc_id, result = _document(new_state, payload, event_id=event_id,
                                               actor=actor, accounts=accounts, now=now)
        link = {"projectId": project_id, "cardIds": sorted(set(references)),
                "sourceIds": sorted(set(sources)), "fingerprint": drafted["fingerprint"],
                "kind": payload["kind"]}
        if doc_id in new_links and new_links[doc_id] != link:
            raise ValueError("Document ID/source mismatch")
        new_links[doc_id] = link
        outcome = {**result, "kind": payload["kind"], "sourceCardIds": link["cardIds"]}
    elif kind != "document.create":
        inner = _core_command(command, new_links)
        doc_id = command.get("documentId")
        if doc_id:
            project_id = _id(command.get("projectId"), "projectId")
            if new_links[doc_id]["projectId"] != project_id:
                raise PermissionError("Document project mismatch")
        new_state, outcome = _apply(new_state, inner, actor=actor, accounts=accounts, now=now)
    clone = deepcopy(finance_state)
    clone["accounting"] = new_state
    clone["accountingSources"] = new_links
    validate_accounting_extension(clone)
    changed = clone != finance_state
    return {"state": clone, "changed": changed, "result": outcome}


def read_madar_accounting(finance_state, *, actor, accounts, project_id="",
                          cards=None, projects=None):
    """Admin-only view, optionally filtered by source project (never task payload)."""
    _admin(actor, accounts)
    accounting, links = _source(finance_state)
    view = accounting_view(accounting, actor=actor, accounts=accounts)
    if project_id:
        _id(project_id, "projectId")
    joined = []
    for kind, source in (("sales", view["invoices"]), ("purchase", view["bills"])):
        for key, document in source.items():
            link = links.get(key)
            if not link or (project_id and link["projectId"] != project_id):
                continue
            party = view["parties"].get(document["partyId"], {})
            status = {"draft": "Draft", "approved": "Review", "issued": "Issued",
                      "reversed": "Reversed", "cancelled": "Cancelled"}[document["status"]]
            joined.append({**deepcopy(document), "kind": kind, "party": deepcopy(party),
                           "status": status, "projectId": link["projectId"],
                           "sourceCardIds": deepcopy(link["cardIds"])})
    balances = [{"partyId": pid, "name": party["name"],
                 "receivable": party["receivable"], "payable": party["payable"],
                 "netReceivable": party["netReceivable"]}
                for pid, party in view["parties"].items()]
    # Per-project view of party totals must not imply project-specific balances.
    if project_id:
        involved = {d["party"]["id"] for d in joined}
        # A supplier with an unpriced intake already exists as a named account,
        # even though no payable and no GL posting exists yet.
        involved.update(row["supplier"]["id"] for row in finance_state.get(
            "purchaseIntakes", empty_intakes())["records"].values()
            if row["projectId"] == project_id)
        balances = [b for b in balances if b["partyId"] in involved]
    expense_sources = []
    if cards is not None and projects is not None and project_id:
        project = _project(project_id, projects)
        for card in cards:
            if card.get("projectId") != project_id or card.get("deleted") is True:
                continue
            summary = card_cost_summary(card, project,
                       override=finance_state.get("cardCosts", {}).get(card["id"]))
            expense_sources.append({
                "cardId": card["id"], "sourceId": "direct", "description": card.get("title", ""),
                "estimated": summary["estimatedDirect"], "actual": summary["actualDirect"]})
            for row in summary["checklist"]:
                if not row["orphaned"]:
                    expense_sources.append({
                        "cardId": card["id"], "sourceId": row["id"],
                        "description": row["id"], "estimated": row["estimated"],
                        "actual": row["actual"]})
    return {"documents": joined, "balances": balances,
            "items": deepcopy(view["items"]), "parties": deepcopy(view["parties"]),
            "reports": ledger_reports(view) if not project_id else None,
            "reportsScope": "all-projects",
            "purchaseIntakes": [deepcopy(row) for row in finance_state.get(
                "purchaseIntakes", empty_intakes())["records"].values()
                if not project_id or row["projectId"] == project_id],
            "expenseSources": expense_sources,
            "trialBalance": deepcopy(view["accounts"]),
            "trialBalanceScope": "all-projects",
            "partyBalancesScope": "all-projects",
            "journals": deepcopy(view["journals"]) if not project_id else [],
            "journalsScope": "all-projects",
            "receipts": deepcopy(view["receipts"]) if not project_id else {},
            "payments": deepcopy(view["payments"]) if not project_id else {},
            "settlementScope": "all-projects",
            "closedThrough": view["closedThrough"], "currency": "TOMAN"}


__all__ = ["apply_madar_accounting", "read_madar_accounting",
           "validate_accounting_extension"]
