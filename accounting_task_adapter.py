"""Pure, explicitly approved task/cost -> accounting document drafts.

This module does not issue fiscal documents, persist anything, transfer funds,
or treat entered cost estimates as paid vendor invoices. The host must verify
current project grants and submit drafts to its trusted accounting transaction.
All values are whole tomans, as in finance.py.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re

from finance import amount, card_cost_summary, MAX_TOTAL

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_MAX_ITEMS = 100


def _identifier(value, label):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def _text(value, label, limit=200):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 and c not in "\t\n" for c in value)):
        raise ValueError(f"Invalid {label}")
    return value.strip()


def _document_party(value, expected_kind):
    if not isinstance(value, dict) or set(value) != {"id", "name", "kind", "reference"}:
        raise ValueError("Counterparty must explicitly specify id, name, kind, reference")
    if value["kind"] != expected_kind:
        raise ValueError("Counterparty kind mismatch")
    _identifier(value["id"], "party id")
    _text(value["name"], "party name")
    ref = value["reference"]
    if not isinstance(ref, str) or len(ref) > 100 or any(ord(c) < 32 for c in ref):
        raise ValueError("Invalid party reference")
    return deepcopy(value) | {"name": value["name"].strip()}


def _source_card(card, project_id):
    if not isinstance(card, dict):
        raise ValueError("Task must be an object")
    if card.get("projectId") != project_id:
        raise PermissionError("Task belongs to another project")
    _identifier(card.get("id"), "task id")
    return card


def _project(project_id, projects):
    _identifier(project_id, "project id")
    if not isinstance(projects, list):
        raise ValueError("Projects must be a list")
    matching = [p for p in projects if isinstance(p, dict) and p.get("id") == project_id]
    if len(matching) != 1:
        raise ValueError("Project reference missing or ambiguous")
    return matching[0]


def _trusted_scope(project_id, granted_project_ids):
    if not isinstance(granted_project_ids, (list, tuple, frozenset, set)):
        raise PermissionError("Server-derived project grants required")
    if project_id not in granted_project_ids or any(not isinstance(i, str) for i in granted_project_ids):
        raise PermissionError("No project grant")


def _money(value, label):
    return amount(value, name=label)


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf8")).hexdigest()


def task_sales_draft(*, task, projects, project_id, customer, lines, discount,
                     tax, advance, event_id, granted_project_ids):
    """Prepare explicit sale lines for exactly one task and a named customer.

    Output includes a strictly finance.py-compatible contract.set command and
    extra source metadata for an accounting adapter. Caller submits with an
    authenticated admin session; the pure function's grant is not authentication.
    """
    _trusted_scope(project_id, granted_project_ids)
    _project(project_id, projects)
    _source_card(task, project_id)
    _identifier(event_id, "event id")
    party = _document_party(customer, "customer")
    if not isinstance(lines, list) or not 1 <= len(lines) <= _MAX_ITEMS:
        raise ValueError("At least one explicit sales line is required")
    subtotal, clean, ids = 0, [], set()
    for item in lines:
        if not isinstance(item, dict) or set(item) != {"id", "description", "quantity", "unitPrice"}:
            raise ValueError("Invalid sale line")
        key = _identifier(item["id"], "line id")
        if key in ids:
            raise ValueError("Duplicate sales line")
        ids.add(key)
        quantity = item["quantity"]
        if type(quantity) is not int or not 1 <= quantity <= 100000:
            raise ValueError("Invalid sales quantity")
        price = _money(item["unitPrice"], "sales unit price")
        subtotal += quantity * price
        if subtotal > MAX_TOTAL:
            raise ValueError("Sales subtotal exceeds monetary bounds")
        clean.append({"id": key, "description": _text(item["description"], "line description", 300),
                      "quantity": quantity, "unitPrice": price})
    discount_value = _money(discount, "discount")
    tax_value = _money(tax, "tax")
    advance_value = _money(advance, "advance")
    if discount_value > subtotal:
        raise ValueError("Discount exceeds sales subtotal")
    total = subtotal - discount_value + tax_value
    if total > MAX_TOTAL or advance_value > total:
        raise ValueError("Invalid sales invoice total or advance")
    sale = {"customer": {"name": party["name"], "reference": party["reference"]},
            "lines": clean, "discount": discount_value, "tax": tax_value,
            "advance": advance_value, "autoInvoice": False}
    payload = {"kind": "sales", "projectId": project_id, "cardId": task["id"],
               "party": party, "lines": clean, "discount": discount_value,
               "tax": tax_value, "advance": advance_value, "subtotal": subtotal,
               "total": total, "remaining": total - advance_value,
               "status": "Draft", "sourceType": "task", "sourceId": task["id"]}
    return {"document": payload, "fingerprint": _digest(payload),
            "financeCommand": {"type": "contract.set", "eventId": event_id,
                               "cardId": task["id"], "sale": sale}}


def _source_lines(card, project, override):
    summary = card_cost_summary(card, project, override=override)
    # Legacy or named list is selected in finance.card_cost_summary, never both.
    lines = {"direct": {"sourceId": "direct", "description": card.get("title", "Task cost"),
                        "estimated": summary["estimatedDirect"], "actual": summary["actualDirect"]}}
    for item in summary["checklist"]:
        if item["orphaned"]:
            # Orphaned override amounts remain in historical cost reporting,
            # but cannot silently become a new purchase invoice.
            continue
        source_id = item["id"]
        if source_id in lines:
            raise ValueError("Ambiguous cost source")
        lines[source_id] = {"sourceId": source_id, "description": source_id,
                            "estimated": item["estimated"], "actual": item["actual"]}
    return lines


def task_purchase_draft(*, tasks, projects, finance_state, project_id,
                        supplier, selections, basis, approve_estimate,
                        event_id, granted_project_ids):
    """Turn selected *expense sources* into a supplier bill DRAFT, not payment.

    selections = [{cardId, sourceId}] where sourceId is 'direct' or a stable
    checklist id from finance.card_cost_summary ('group:item' or legacy).
    For estimated costs an explicit acknowledge flag is mandatory. A committed
    invoice would establish a payable only after trusted review/issue.
    """
    _trusted_scope(project_id, granted_project_ids)
    project = _project(project_id, projects)
    party = _document_party(supplier, "supplier")
    _identifier(event_id, "event id")
    if basis not in ("actual", "estimated"):
        raise ValueError("Expense basis must be actual or estimated")
    if type(approve_estimate) is not bool:
        raise ValueError("approve_estimate must be a boolean")
    if basis == "estimated" and not approve_estimate:
        raise ValueError("Explicit confirmation required for estimated expense")
    if not isinstance(tasks, list) or not isinstance(finance_state, dict):
        raise ValueError("Invalid task or finance state")
    if not isinstance(finance_state.get("cardCosts", {}), dict):
        raise ValueError("Invalid card cost state")
    if not isinstance(selections, list) or not 1 <= len(selections) <= _MAX_ITEMS:
        raise ValueError("At least one expense line must be selected")
    card_map = {}
    for task in tasks:
        if not isinstance(task, dict) or "id" not in task:
            raise ValueError("Invalid task data")
        if task["id"] in card_map:
            raise ValueError("Duplicate task ID")
        card_map[task["id"]] = task
    clean, included, subtotal = [], set(), 0
    cache = {}
    for selection in selections:
        if not isinstance(selection, dict) or set(selection) != {"cardId", "sourceId"}:
            raise ValueError("Invalid expense selection")
        card_id, source_id = selection["cardId"], selection["sourceId"]
        _identifier(card_id, "selected card id")
        if not isinstance(source_id, str) or not source_id or len(source_id) > 250:
            raise ValueError("Invalid expense source id")
        pair = (card_id, source_id)
        if pair in included:
            raise ValueError("Same cost line selected more than once")
        included.add(pair)
        task = card_map.get(card_id)
        _source_card(task, project_id)
        if card_id not in cache:
            cache[card_id] = _source_lines(task, project,
                        finance_state.get("cardCosts", {}).get(card_id))
        source = cache[card_id].get(source_id)
        if source is None:
            raise ValueError("Unknown or orphaned cost source")
        value = _money(source[basis], "expense cost")
        if value <= 0:
            raise ValueError("Selected expense amount must be positive")
        subtotal += value
        if subtotal > MAX_TOTAL:
            raise ValueError("Purchase subtotal exceeds monetary bounds")
        clean.append({"id": f"{card_id}:{source_id}", "cardId": card_id,
                      "sourceId": source_id,
                      "description": _text(source["description"], "cost description", 300),
                      "quantity": 1, "unitPrice": value, "total": value})
    draft = {"kind": "purchase", "projectId": project_id,
             "party": party, "lines": clean, "subtotal": subtotal,
             "total": subtotal, "tax": 0, "discount": 0,
             "status": "Draft", "basis": basis, "estimatedApproved": approve_estimate,
             "sourceType": "task-costs"}
    return {"document": deepcopy(draft), "fingerprint": _digest(draft),
            "sourceEventId": event_id}


__all__ = ["task_sales_draft", "task_purchase_draft"]
