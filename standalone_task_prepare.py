"""Trusted administrative task-to-standalone-accounting preparation.

Only task/expense IDs come from the client. Host reads authoritative saved task
state and independently authenticates an admin. Financial data never originates
from an untrusted browser payload. Atomic CAS belongs to the standalone store.
"""
from datetime import datetime, timezone
import uuid

from accounting_core import _id, _int, _text, MAX_TOMAN
from standalone_accounting import AccountingRevisionConflict


def _toman(value, currency, *, positive=True):
    _int(value, "unit price", positive=positive)
    if currency == "TOMAN":
        return value
    if currency == "RIAL":
        if value % 10:
            raise ValueError("RIAL unit price cannot be represented as exact TOMAN")
        result = value // 10
        if positive and result == 0:
            raise ValueError("Zero TOMAN unit price is not supported")
        return result
    raise ValueError("Unknown order currency")


def _ledger_amount(value, currency, ledger_currency):
    """Exact conversion at the trusted host; never round a RIAL value."""
    if type(value) is not int or value <= 0:
        raise ValueError("Expected positive exact integer unit price")
    if currency not in ("TOMAN", "RIAL") or ledger_currency not in ("TOMAN", "RIAL"):
        raise ValueError("Unknown financial currency")
    if currency == ledger_currency:
        result = value
    elif currency == "TOMAN":
        result = value * 10
    else:
        if value % 10:
            raise ValueError("Cannot convert an indivisible RIAL amount into TOMAN")
        result = value // 10
    return _int(result, "unit price", positive=True)


def _task_record(tasks, task_id):
    if type(tasks) is not list:
        raise ValueError("Expected authoritative task collection")
    _id(task_id, "taskId")
    matches = [t for t in tasks if type(t) is dict and t.get("id") == task_id]
    if len(matches) != 1 or matches[0].get("deleted") is True:
        raise ValueError("No unique active saved task with this ID")
    return matches[0]


def _source_document(view, kind, source_id):
    collection = view["contractorJobs"] if kind == "expense" else view["invoices"]
    source_type = "task.expense" if kind == "expense" else "task.sale"
    return next((x for x in collection.values() if x["sourceType"] == source_type
                 and x["sourceId"] == source_id and
                 (kind == "expense" or x["status"] != "cancelled")), None)


def prepare_from_saved_task(store, request, *, tasks, actor, accounts, now=None):
    """Prepare one draft/contractor work, never approve, issue, post or settle.

    Host supplies verified actor/account registry, canonical saved tasks and clock.
    No task DB writes or combined transaction; retry resolves by commercial source.
    """
    if type(request) is not dict or set(request) != {"taskId", "expenseId"}:
        raise ValueError("Only taskId and expenseId are accepted from task UI")
    if (type(accounts) is not dict or type(accounts.get(actor)) is not dict
            or accounts[actor].get("username") != actor
            or accounts[actor].get("role") != "admin"):
        raise PermissionError("Only trusted administrator may prepare task accounting")
    t = _task_record(tasks, request["taskId"])
    expense_id = request["expenseId"]
    if expense_id is not None:
        _id(expense_id, "expenseId")
        # Named checklist expenses are first-class work items. Ignore the
        # compatibility mirror, otherwise one legacy expense looks duplicated.
        steps = [s for s in t.get("checklist", []) if type(s) is dict]
        steps.extend(item for group in t.get("checklists", [])
                     if type(group) is dict and group.get("id") != "checklist-legacy"
                     for item in group.get("items", []) if type(item) is dict)
        matches = [x for step in steps for x in step.get("expenseItems", [])
                   if type(x) is dict and x.get("id") == expense_id]
        if len(matches) != 1:
            raise ValueError("Expense ID must identify exactly one saved work item")
        expense = matches[0]
        source_id = expense_id
        kind = "expense"
    else:
        expense = None
        source_id = _id(t["id"], "taskId")
        kind = "sale"
    at = now or datetime.now(timezone.utc).isoformat()
    if type(at) is not str or len(at) < 10:
        raise ValueError("Trusted timestamp required")
    for _ in range(3):
        head = store.read(actor=actor, accounts=accounts)
        view = head["view"]
        ledger_currency = view["currency"]
        found = _source_document(view, kind, source_id)
        if found:
            return {"id": found["id"], "existing": True}
        event_id = "evt." + uuid.uuid4().hex
        if kind == "sale":
            party_id = _id(t.get("salePartyId"), "salePartyId")
            party = view["parties"].get(party_id)
            if party is None or party["kind"] not in ("customer", "both"):
                raise ValueError("Saved task customer not registered in accounting")
            quantity = _int(t.get("saleQuantity", 1), "saleQuantity", positive=True,
                            cap=1000000)
            unit = _ledger_amount(t.get("saleUnitPrice"),
                                  t.get("saleCurrency", "TOMAN"), ledger_currency)
            _int(quantity * unit, "sale total", positive=True)
            command = {"type": "invoice.create", "eventId": event_id,
                       "invoiceId": "sale." + uuid.uuid4().hex,
                       "partyId": party_id, "documentDate": at[:10],
                       "sourceType": "task.sale", "sourceId": source_id,
                       "lines": [{"description": _text(t.get("title"), "title"),
                                  "quantity": quantity, "unitPrice": unit}]}
        else:
            party_id = _id(expense.get("partyId"), "partyId")
            party = view["parties"].get(party_id)
            if party is None or party["kind"] not in ("vendor", "both"):
                raise ValueError("Saved supplier not registered in accounting")
            quantity = _int(expense.get("quantity"), "quantity", positive=True,
                            cap=1000000)
            raw_price = expense.get("unitPrice")
            price = None if raw_price is None else _ledger_amount(
                raw_price, expense.get("currency"), ledger_currency)
            if price is not None:
                _int(price * quantity, "contractor work total", positive=True)
            command = {"type": "contractor.job.intake", "eventId": event_id,
                       "jobId": source_id, "sourceType": "task.expense",
                       "sourceId": source_id, "partyId": party_id,
                       "description": _text(expense.get("description"), "description"),
                       "quantity": quantity, "currency": ledger_currency,
                       "unitPrice": price}
        try:
            output = store.command(command, actor=actor, accounts=accounts,
                                   expected_revision=head["revision"], now=at)
            return {"id": output["result"]["jobId" if expense else "documentId"],
                    "existing": False}
        except (AccountingRevisionConflict, ValueError) as err:
            # A concurrent click can win a different eventId. Read back the
            # commercial source; never swallow unrelated validation errors.
            refreshed = store.read(actor=actor, accounts=accounts)
            found = _source_document(refreshed["view"], kind, source_id)
            if found:
                return {"id": found["id"], "existing": True}
            if not isinstance(err, AccountingRevisionConflict):
                raise
    raise AccountingRevisionConflict("Task preparation encountered repeated CAS races")
