"""Madar's side-effect-free, host-authorized financial domain service.

All monetary values are exact integer tomans. The caller supplies authenticated
identity, current authoritative cards/projects, and a verified completion event.
No files, network, tax rules, clocks, or invoice issuance integrations are used.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

SCHEMA_VERSION = 1
MAX_MONEY = 10**15
MAX_TOTAL = 10**15
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_MONEY = re.compile(r"(?:0|[1-9][0-9]{0,15})(?:\.0{1,2})?\Z")
_DATE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def amount(value, *, name="amount"):
    """Normalize a nonnegative whole-toman integer or canonical decimal string.

    Floats (including NaN), booleans, scientific notation, grouped amounts and
    fractional tomans are intentionally forbidden.
    """
    if type(value) is int:
        parsed = value
    elif isinstance(value, str) and _MONEY.fullmatch(value):
        try:
            dec = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid {name}") from exc
        if dec != dec.to_integral_value():
            raise ValueError(f"Invalid {name}")
        parsed = int(dec)
    else:
        raise ValueError(f"Invalid {name}: whole tomans required")
    if parsed < 0 or parsed > MAX_MONEY:
        raise ValueError(f"Invalid {name}: out of range")
    return parsed


def _id(value, name="id"):
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    return value


def _text(value, name, max_len, *, empty=False):
    if not isinstance(value, str) or len(value) > max_len or "\x00" in value or (not empty and not value.strip()):
        raise ValueError(f"Invalid {name}")
    return value.strip()


def _bool(value):
    if type(value) is not bool:
        raise ValueError("Expected boolean")
    return value


def _date(value):
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError("Timestamp requires explicit timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("Timezone required")
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    return value


def _calendar_date(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", value):
        raise ValueError("Expected YYYY-MM-DD calendar date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid calendar date") from exc
    if parsed.isoformat() != value:
        raise ValueError("Noncanonical calendar date")
    return parsed


def _category(value):
    if (not isinstance(value, str) or len(value) > 80
            or not all(c.isprintable() or c == "\u200c" for c in value)):
        raise ValueError("Invalid cost category")
    return value.strip() or "بدون دسته‌بندی"


def _schema(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError("Unexpected or missing object fields")
    return value


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                          separators=(",", ":")).encode("utf8")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Payload must be valid JSON") from exc


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _derived(prefix, *parts):
    return prefix + "-" + _digest(parts)[:24]


def _index(value, field):
    if isinstance(value, dict):
        records = list(value.values())
        for key, record in value.items():
            if not isinstance(record, dict) or record.get(field) != key:
                raise ValueError("Index key/record mismatch")
    elif isinstance(value, list):
        records = value
    else:
        raise ValueError("Expected list or mapping")
    indexed = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Invalid authoritative record")
        ident = _id(record.get(field), field)
        if ident in indexed:
            raise ValueError("Duplicate authoritative ID")
        indexed[ident] = record
    return indexed


def _context(actor, accounts, cards, projects):
    users = _index(accounts, "username")
    tasks = _index(cards, "id")
    prjs = _index(projects, "id")
    _id(actor, "actor")
    if actor not in users:
        raise PermissionError("Unauthenticated actor")
    for user in users.values():
        if user.get("role") not in {"admin", "editor", "viewer"}:
            raise ValueError("Invalid account role")
        scope = user.get("projects")
        if scope is not None and (not isinstance(scope, list) or not all(
            isinstance(i, str) and i in prjs for i in scope)):
            raise ValueError("Invalid account project scope")
        for flag in ("financeView", "financeEdit"):
            if flag in user and type(user[flag]) is not bool:
                raise ValueError("Invalid finance permission")
    for card in tasks.values():
        if card.get("projectId") not in prjs:
            raise ValueError("Card references unknown project")
    return users, tasks, prjs


def _can(account, project_id, *, permission="view"):
    role = account["role"]
    if role != "admin" and account.get("projects") is not None and project_id not in account["projects"]:
        return False
    if permission == "task":
        return role in {"admin", "editor"}
    if permission == "view":
        return role == "admin" or account.get("financeView") is True or account.get("financeEdit") is True
    if permission == "edit":
        return role == "admin" or (role == "editor" and account.get("financeEdit") is True)
    if permission == "admin":
        return role == "admin"
    raise ValueError("Unknown permission")


def _require(account, project_id, permission):
    if not _can(account, project_id, permission=permission):
        raise PermissionError("Financial/project access denied")


def _card(tasks, card_id):
    card = tasks.get(_id(card_id, "cardId"))
    if card is None:
        raise ValueError("Card not found")
    return card


def _source_item_costs(card):
    """Avoid summing both migrated named and duplicated legacy checklist items."""
    groups = card.get("checklists")
    if groups is not None and not isinstance(groups, list):
        raise ValueError("Invalid named checklists")
    if groups:
        result = {}
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("items"), list):
                raise ValueError("Invalid checklist group")
            group_id = _id(group.get("id"), "checklist id")
            for item in group["items"]:
                if not isinstance(item, dict):
                    raise ValueError("Invalid checklist item")
                key = group_id + ":" + _id(item.get("id"), "item id")
                if key in result:
                    raise ValueError("Duplicate checklist item")
                result[key] = amount(item.get("cost", 0), name="checklist cost")
        return result
    items = card.get("checklist", [])
    if not isinstance(items, list):
        raise ValueError("Invalid checklist")
    result = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("Invalid checklist item")
        raw_id = item.get("id", f"legacy-{index}")
        key = "checklist-legacy:" + _id(raw_id, "item id")
        if key in result:
            raise ValueError("Duplicate checklist item")
        result[key] = amount(item.get("cost", 0), name="checklist cost")
    return result


def _cost_record(value):
    _schema(value, {"cardId", "costEnabled", "estimatedDirect", "actualDirect", "items"})
    card_id = _id(value["cardId"], "cardId")
    flag = value["costEnabled"]
    if flag is not None:
        _bool(flag)
    items = value["items"]
    if not isinstance(items, list) or len(items) > 3000:
        raise ValueError("Invalid cost items")
    found = set()
    normalized = []
    for item in items:
        _schema(item, {"id", "estimated", "actual"})
        item_id = _id(item["id"], "checklist cost id")
        if item_id in found:
            raise ValueError("Duplicate checklist cost ID")
        found.add(item_id)
        normalized.append({"id": item_id,
                           "estimated": amount(item["estimated"], name="estimated checklist cost"),
                           "actual": amount(item["actual"], name="actual checklist cost")})
    return {"cardId": card_id, "costEnabled": flag,
            "estimatedDirect": amount(value["estimatedDirect"], name="estimated direct cost"),
            "actualDirect": amount(value["actualDirect"], name="actual direct cost"),
            "items": sorted(normalized, key=lambda i: i["id"])}


def card_cost_summary(card, project, *, override=None):
    """Cost visibility and exact estimates/actuals; disabled cards retain data."""
    if not isinstance(card, dict) or not isinstance(project, dict) or card.get("projectId") != project.get("id"):
        raise ValueError("Card/project mismatch")
    _id(card.get("id"), "cardId")
    legacy_flag = card.get("costEnabled")
    if legacy_flag is not None:
        _bool(legacy_flag)
    _bool(project.get("costEnabled", False))
    source = _source_item_costs(card)
    base = amount(card.get("cost", 0), name="direct cost")
    if override is not None:
        config = _cost_record(override)
        if config["cardId"] != card["id"]:
            raise ValueError("Cost record targets wrong card")
        flag = config["costEnabled"]
        direct_estimated, direct_actual = config["estimatedDirect"], config["actualDirect"]
        overrides = {item["id"]: item for item in config["items"]}
    else:
        flag = legacy_flag
        direct_estimated, direct_actual = base, 0
        overrides = {}
    enabled = project.get("costEnabled", False) if flag is None else flag
    details = [{"id": key, "estimated": overrides[key]["estimated"] if key in overrides else cost,
                "actual": overrides[key]["actual"] if key in overrides else 0,
                "orphaned": False}
               for key, cost in sorted(source.items())]
    # Keep previously recorded amounts when a checklist item is later deleted.
    # Historical cost does not silently disappear from financial reports.
    details.extend({"id": key, "estimated": item["estimated"],
                    "actual": item["actual"], "orphaned": True}
                   for key, item in sorted(overrides.items()) if key not in source)
    estimated = direct_estimated + sum(item["estimated"] for item in details)
    actual = direct_actual + sum(item["actual"] for item in details)
    if estimated > MAX_TOTAL or actual > MAX_TOTAL:
        raise ValueError("Cost sum exceeds limit")
    return {"cardId": card["id"], "enabled": enabled, "costEnabled": flag,
            "estimatedDirect": direct_estimated, "actualDirect": direct_actual,
            "checklist": details, "estimatedTotal": estimated, "actualTotal": actual,
            "includedEstimated": estimated if enabled else 0,
            "includedActual": actual if enabled else 0}


def project_cost_summary(state, project_id, *, actor, accounts, cards, projects):
    validate_finance_state(state)
    users, tasks, prjs = _context(actor, accounts, cards, projects)
    project = prjs.get(_id(project_id, "projectId"))
    if project is None:
        raise ValueError("Project not found")
    _require(users[actor], project_id, "view")
    results = [card_cost_summary(card, project, override=state["cardCosts"].get(card["id"]))
               for card in tasks.values() if card["projectId"] == project_id]
    estimated = sum(item["includedEstimated"] for item in results)
    actual = sum(item["includedActual"] for item in results)
    if estimated > MAX_TOTAL or actual > MAX_TOTAL:
        raise ValueError("Project costs exceed limit")
    return {"projectId": project_id, "estimatedTotal": estimated,
            "actualTotal": actual, "cards": deepcopy(results)}


def _sale(payload):
    _schema(payload, {"customer", "lines", "discount", "tax", "advance", "autoInvoice"})
    customer = payload["customer"]
    _schema(customer, {"name", "reference"})
    name = _text(customer["name"], "customer name", 200)
    reference = _text(customer["reference"], "customer reference", 100, empty=True)
    lines = payload["lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
        raise ValueError("An explicit sale line is required")
    checked = set()
    clean = []
    subtotal = 0
    for line in lines:
        _schema(line, {"id", "description", "quantity", "unitPrice"})
        line_id = _id(line["id"], "line id")
        if line_id in checked:
            raise ValueError("Duplicate sale line")
        checked.add(line_id)
        description = _text(line["description"], "sale description", 300)
        if type(line["quantity"]) is not int or not 1 <= line["quantity"] <= 100000:
            raise ValueError("Invalid sale quantity")
        unit_price = amount(line["unitPrice"], name="unit price")
        subtotal += unit_price * line["quantity"]
        if subtotal > MAX_TOTAL:
            raise ValueError("Sale exceeds limit")
        clean.append({"id": line_id, "description": description,
                      "quantity": line["quantity"], "unitPrice": unit_price,
                      "total": unit_price * line["quantity"]})
    discount = amount(payload["discount"], name="discount")
    tax = amount(payload["tax"], name="tax amount")
    advance = amount(payload["advance"], name="advance payment")
    if discount > subtotal:
        raise ValueError("Discount exceeds subtotal")
    total = subtotal - discount + tax
    if total > MAX_TOTAL or advance > total:
        raise ValueError("Invalid total or advance")
    return {"customer": {"name": name, "reference": reference},
            "lines": sorted(clean, key=lambda item: item["id"]),
            "subtotal": subtotal, "discount": discount, "tax": tax,
            "total": total, "advance": advance, "due": total - advance,
            "autoInvoice": _bool(payload["autoInvoice"])}


def _raw_sale(sale):
    _schema(sale, {"customer", "lines", "subtotal", "discount", "tax",
                   "total", "advance", "due", "autoInvoice"})
    if not isinstance(sale["lines"], list):
        raise ValueError("Invalid invoice lines")
    for line in sale["lines"]:
        _schema(line, {"id", "description", "quantity", "unitPrice", "total"})
    return {"customer": deepcopy(sale["customer"]),
            "lines": [{k: line[k] for k in ("id", "description", "quantity", "unitPrice")}
                      for line in sale["lines"]],
            "discount": sale["discount"], "tax": sale["tax"],
            "advance": sale["advance"], "autoInvoice": sale["autoInvoice"]}


def empty_finance_state():
    return {"schemaVersion": SCHEMA_VERSION, "cardCosts": {}, "contracts": [],
            "activeContracts": {}, "invoices": [], "ledger": [], "receipts": {},
            "completionIds": {}, "nextInvoiceNumber": 1}


def _ledger(state, *, event_id, actor, action, project_id, card_id, invoice_id, payload, at):
    previous = state["ledger"][-1]["hash"] if state["ledger"] else "0" * 64
    body = {"id": _derived("ledger", event_id), "eventId": event_id, "actor": actor,
            "action": action, "projectId": project_id, "cardId": card_id,
            "invoiceId": invoice_id, "payload": deepcopy(payload), "at": at,
            "prevHash": previous}
    body["hash"] = _digest(body)
    state["ledger"].append(body)


def invoice_status(state, invoice_id):
    """Derive invoice lifecycle and payments from append-only ledger entries."""
    _id(invoice_id, "invoiceId")
    record = next((entry for entry in state["invoices"] if entry["id"] == invoice_id), None)
    if record is None:
        raise ValueError("Invoice not found")
    status = "Draft"
    number = None
    paid = 0
    for item in state["ledger"]:
        if item["invoiceId"] != invoice_id:
            continue
        action = item["action"]
        if action == "invoice.review":
            status = "Review"
        elif action == "invoice.issue":
            status = "Issued"
            number = item["payload"]["number"]
        elif action == "invoice.payment":
            paid += item["payload"]["amount"]
            if paid == record["sale"]["due"]:
                status = "Paid"
        elif action == "invoice.cancel":
            status = "Cancelled"
        elif action == "invoice.replaced":
            status = "Superseded"
    return {"invoiceId": invoice_id, "status": status, "number": number,
            "paidAfterAdvance": paid, "remaining": record["sale"]["due"] - paid}


def validate_finance_state(state):
    # The independently verified double-entry accounting extension is opt-in.
    # Keep the historical v1 snapshot byte-for-byte compatible until an
    # authorized accounting command is committed by the existing finance CAS.
    required = {"schemaVersion", "cardCosts", "contracts", "activeContracts", "invoices",
                "ledger", "receipts", "completionIds", "nextInvoiceNumber"}
    optional = {"accounting", "accountingSources", "purchaseIntakes", "rialJournalV2"}
    if (not isinstance(state, dict) or not required.issubset(state)
            or set(state) - required - optional):
        raise ValueError("Unexpected or missing finance state fields")
    if ("accounting" in state) != ("accountingSources" in state):
        raise ValueError("Accounting snapshot and source index must be atomic")
    if "accounting" in state:
        from accounting_service import validate_accounting_extension
        validate_accounting_extension(state)
    if "purchaseIntakes" in state:
        from purchase_intake import validate_intakes
        validate_intakes(state["purchaseIntakes"])
    if "rialJournalV2" in state:
        from ir_finance_v2_extension import validate_rial_finance_extension
        validate_rial_finance_extension(state)
    if type(state["schemaVersion"]) is not int or state["schemaVersion"] != SCHEMA_VERSION:
        raise ValueError("Unknown finance schema")
    if type(state["nextInvoiceNumber"]) is not int or not 1 <= state["nextInvoiceNumber"] <= 10**12:
        raise ValueError("Invalid next invoice number")
    if not isinstance(state["cardCosts"], dict):
        raise ValueError("Invalid costs map")
    for card_id, record in state["cardCosts"].items():
        if _cost_record(record)["cardId"] != card_id:
            raise ValueError("Invalid card cost index")
        if record != _cost_record(record):
            raise ValueError("Noncanonical card cost record")
    if not isinstance(state["contracts"], list) or not isinstance(state["invoices"], list) or not isinstance(state["ledger"], list):
        raise ValueError("Invalid financial collections")
    contract_ids = set()
    for contract in state["contracts"]:
        _schema(contract, {"id", "cardId", "projectId", "sale", "actor", "at"})
        if _id(contract["id"]) in contract_ids:
            raise ValueError("Duplicate contract")
        contract_ids.add(contract["id"])
        for name in ("cardId", "projectId", "actor"):
            _id(contract[name], name)
        _date(contract["at"])
        if contract["sale"] != _sale(_raw_sale(contract["sale"])):
            raise ValueError("Corrupt contract sale snapshot")
    if not isinstance(state["activeContracts"], dict):
        raise ValueError("Invalid active contracts")
    for card_id, contract_id in state["activeContracts"].items():
        _id(card_id, "cardId")
        if not any(c["id"] == contract_id and c["cardId"] == card_id for c in state["contracts"]):
            raise ValueError("Active contract reference missing")
    invoice_ids = set()
    completion_refs = set()
    for invoice in state["invoices"]:
        _schema(invoice, {"id", "projectId", "cardId", "contractId", "completionId",
                          "createdAt", "createdBy", "supersedesId", "sale", "snapshotHash"})
        if _id(invoice["id"]) in invoice_ids:
            raise ValueError("Duplicate invoice")
        invoice_ids.add(invoice["id"])
        for name in ("projectId", "cardId", "createdBy"):
            _id(invoice[name], name)
        for name in ("contractId", "completionId", "supersedesId"):
            if invoice[name] is not None:
                _id(invoice[name], name)
        _date(invoice["createdAt"])
        if invoice["sale"] != _sale(_raw_sale(invoice["sale"])):
            raise ValueError("Corrupt invoice sale snapshot")
        if not isinstance(invoice["snapshotHash"], str) or not _HASH.fullmatch(invoice["snapshotHash"]):
            raise ValueError("Missing invoice integrity hash")
        if invoice["snapshotHash"] != _digest({k: v for k, v in invoice.items() if k != "snapshotHash"}):
            raise ValueError("Invoice snapshot has changed")
        if invoice["supersedesId"] == invoice["id"]:
            raise ValueError("Invoice cannot supersede itself")
        if invoice["completionId"] is not None:
            completion_refs.add(invoice["completionId"])
    for invoice in state["invoices"]:
        if invoice["supersedesId"] is not None and invoice["supersedesId"] not in invoice_ids:
            raise ValueError("Missing superseded invoice")
    prev = "0" * 64
    ledger_ids = set()
    numbers = set()
    allowed = {"cost.set", "cost.toggle", "contract.set", "completion.record", "invoice.create",
               "invoice.review", "invoice.issue", "invoice.payment", "invoice.cancel",
               "invoice.revise", "invoice.replaced", "project.receipt"}
    for entry in state["ledger"]:
        _schema(entry, {"id", "eventId", "actor", "action", "projectId", "cardId",
                        "invoiceId", "payload", "at", "prevHash", "hash"})
        if _id(entry["id"]) in ledger_ids:
            raise ValueError("Duplicate ledger ID")
        ledger_ids.add(entry["id"])
        for name in ("eventId", "actor", "projectId"):
            _id(entry[name], name)
        if entry["action"] == "project.receipt":
            if entry["cardId"] is not None or entry["invoiceId"] is not None:
                raise ValueError("Project receipt must not reference a card or invoice")
            _schema(entry["payload"], {"amount", "receivedAt", "description"})
            if amount(entry["payload"]["amount"], name="receipt") == 0:
                raise ValueError("Zero project receipt")
            _date(entry["payload"]["receivedAt"])
            _text(entry["payload"]["description"], "description", 500, empty=True)
        else:
            _id(entry["cardId"], "cardId")
        if entry["invoiceId"] is not None:
            _id(entry["invoiceId"], "invoiceId")
            if entry["invoiceId"] not in invoice_ids:
                raise ValueError("Ledger references unknown invoice")
        if entry["action"] not in allowed or not isinstance(entry["payload"], dict):
            raise ValueError("Invalid ledger action/payload")
        _date(entry["at"])
        if entry["prevHash"] != prev or entry["hash"] != _digest({k: v for k, v in entry.items() if k != "hash"}):
            raise ValueError("Ledger hash chain mismatch")
        prev = entry["hash"]
        if entry["action"] == "invoice.issue":
            number = entry["payload"].get("number")
            if type(number) is not int or number < 1 or number in numbers:
                raise ValueError("Duplicate/invalid invoice number")
            numbers.add(number)
        if entry["action"] == "invoice.payment":
            if amount(entry["payload"].get("amount"), name="payment") == 0:
                raise ValueError("Zero payment")
    if numbers != set(range(1, state["nextInvoiceNumber"])):
        raise ValueError("Invoice number sequence contains gaps or duplicates")
    if not isinstance(state["completionIds"], dict):
        raise ValueError("Invalid completion map")
    for completion, reference in state["completionIds"].items():
        _id(completion, "completionId")
        _schema(reference, {"cardId", "invoiceId"})
        _id(reference["cardId"], "cardId")
        if reference["invoiceId"] is not None and reference["invoiceId"] not in invoice_ids:
            raise ValueError("Unknown completion invoice")
    if not isinstance(state["receipts"], dict):
        raise ValueError("Invalid receipts")
    for event_id, receipt in state["receipts"].items():
        _id(event_id, "eventId")
        _schema(receipt, {"fingerprint", "projectId", "permission", "result"})
        if not isinstance(receipt["fingerprint"], str) or not _HASH.fullmatch(receipt["fingerprint"]):
            raise ValueError("Invalid command fingerprint")
        _id(receipt["projectId"], "projectId")
        if receipt["permission"] not in {"task", "view", "edit", "admin"} or not isinstance(receipt["result"], dict):
            raise ValueError("Invalid receipt")
    for invoice_id in invoice_ids:
        current = invoice_status(state, invoice_id)
        if current["remaining"] < 0:
            raise ValueError("Payments exceed invoiced balance")
    return True


def _invoice(state, invoice_id):
    _id(invoice_id, "invoiceId")
    record = next((i for i in state["invoices"] if i["id"] == invoice_id), None)
    if record is None:
        raise ValueError("Invoice not found")
    return record


def _make_invoice(state, *, idempotency, project_id, card_id, contract_id,
                  completion_id, supersedes, sale, actor, now):
    invoice = {"id": _derived("invoice", idempotency), "projectId": project_id,
               "cardId": card_id, "contractId": contract_id,
               "completionId": completion_id, "createdAt": now, "createdBy": actor,
               "supersedesId": supersedes, "sale": deepcopy(sale)}
    invoice["snapshotHash"] = _digest(invoice)
    state["invoices"].append(invoice)
    return invoice["id"]


def _valid_completion(card):
    """Require an actual completed card snapshot; host also checks the transition."""
    if card.get("completed") is True:
        return True
    return card.get("status") == "done"


def apply_finance_command(state, command, *, actor, accounts, cards, projects, now):
    """Pure reducer: returns {state, changed, result}, safe under a host transaction.

    The host MUST verify card incomplete->complete transitions, authenticate the
    actor, and atomically persist all state/ledger/receipts and task changes.
    """
    validate_finance_state(state)
    users, tasks, prjs = _context(actor, accounts, cards, projects)
    _date(now)
    if not isinstance(command, dict):
        raise ValueError("Invalid command")
    types = {
        "cost.set": {"cardId", "value"},
        "cost.toggle": {"cardId", "costEnabled"},
        "contract.set": {"cardId", "sale"},
        "completion.record": {"cardId", "completionId"},
        "invoice.review": {"invoiceId"},
        "invoice.issue": {"invoiceId"},
        "invoice.payment": {"invoiceId", "amount"},
        "invoice.cancel": {"invoiceId", "reason"},
        "invoice.revise": {"invoiceId", "sale", "reason"},
        "project.receipt": {"projectId", "amount", "receivedAt", "description"},
    }
    kind = command.get("type")
    if kind not in types or set(command) != {"type", "eventId"} | types[kind]:
        raise ValueError("Invalid finance command fields")
    event_id = _id(command["eventId"], "eventId")
    fingerprint = _digest([actor, command])
    previous = state["receipts"].get(event_id)
    if previous:
        if previous["fingerprint"] != fingerprint:
            raise ValueError("Idempotency key reused for a different command")
        _require(users[actor], previous["projectId"], previous["permission"])
        return {"state": deepcopy(state), "changed": False, "result": deepcopy(previous["result"])}
    next_state = deepcopy(state)
    if kind == "project.receipt":
        project_id = _id(command["projectId"], "projectId")
        if project_id not in prjs:
            raise ValueError("Project not found")
        card_id = None
    elif kind in {"cost.set", "cost.toggle", "contract.set", "completion.record"}:
        card = _card(tasks, command["cardId"])
        project_id, card_id = card["projectId"], card["id"]
    else:
        invoice = _invoice(next_state, command["invoiceId"])
        project_id, card_id = invoice["projectId"], invoice["cardId"]
        if card_id not in tasks or tasks[card_id]["projectId"] != project_id:
            raise ValueError("Invoice card/project not found")
    if kind == "project.receipt":
        permission = "admin"
        _require(users[actor], project_id, permission)
        received = amount(command["amount"], name="received amount")
        if received == 0:
            raise ValueError("Received amount must be positive")
        received_at = _date(command["receivedAt"])
        description = _text(command["description"], "description", 500, empty=True)
        _ledger(next_state, event_id=event_id, actor=actor, action=kind,
                project_id=project_id, card_id=None, invoice_id=None,
                payload={"amount": received, "receivedAt": received_at,
                         "description": description}, at=now)
        result = {"eventId": event_id, "projectId": project_id, "amount": received,
                  "receivedAt": received_at, "description": description}
    elif kind in {"cost.set", "cost.toggle"}:
        permission = "edit"
        _require(users[actor], project_id, permission)
        project = prjs[project_id]
        baseline = card_cost_summary(card, project, override=next_state["cardCosts"].get(card_id))
        if kind == "cost.set":
            value = _cost_record(command["value"])
            known_cost_ids = set(_source_item_costs(card))
            if any(item["id"] not in known_cost_ids for item in value["items"]):
                raise ValueError("Unknown checklist item cost ID")
            card_cost_summary(card, project, override=value)
        else:
            flag = command["costEnabled"]
            if flag is not None:
                _bool(flag)
            current = next_state["cardCosts"].get(card_id)
            value = deepcopy(current) if current is not None else {
                "cardId": card_id, "costEnabled": baseline["costEnabled"],
                "estimatedDirect": baseline["estimatedDirect"], "actualDirect": baseline["actualDirect"],
                "items": [{"id": item["id"], "estimated": item["estimated"], "actual": item["actual"]}
                          for item in baseline["checklist"]]}
            value["costEnabled"] = flag
        if value["cardId"] != card_id:
            raise ValueError("Cannot edit another card's costs")
        before = deepcopy(next_state["cardCosts"].get(card_id))
        next_state["cardCosts"][card_id] = value
        after = card_cost_summary(card, project, override=value)
        _ledger(next_state, event_id=event_id, actor=actor, action=kind,
                project_id=project_id, card_id=card_id, invoice_id=None,
                payload={"before": before, "after": value}, at=now)
        result = {"cardId": card_id, "enabled": after["enabled"],
                  "estimatedTotal": after["estimatedTotal"], "actualTotal": after["actualTotal"]}
    elif kind == "contract.set":
        permission = "admin"
        _require(users[actor], project_id, permission)
        sale = _sale(command["sale"])
        contract_id = _derived("contract", event_id)
        next_state["contracts"].append({"id": contract_id, "cardId": card_id,
                                         "projectId": project_id, "sale": sale,
                                         "actor": actor, "at": now})
        next_state["activeContracts"][card_id] = contract_id
        _ledger(next_state, event_id=event_id, actor=actor, action=kind,
                project_id=project_id, card_id=card_id, invoice_id=None,
                payload={"contractId": contract_id}, at=now)
        result = {"contractId": contract_id, "total": sale["total"], "due": sale["due"]}
    elif kind == "completion.record":
        permission = "task"
        _require(users[actor], project_id, permission)
        if not _valid_completion(card):
            raise ValueError("Card is not completed")
        completion_id = _id(command["completionId"], "completionId")
        if completion_id in next_state["completionIds"]:
            if next_state["completionIds"][completion_id]["cardId"] != card_id:
                raise ValueError("Completion ID already belongs to another card")
            result = {"invoiceCreated": False, "duplicateCompletion": True}
        else:
            contract_id = next_state["activeContracts"].get(card_id)
            contract = next((c for c in next_state["contracts"] if c["id"] == contract_id), None)
            created = False
            invoice_id = None
            if contract is not None and contract["sale"]["autoInvoice"]:
                # One automatic draft per card + contract version, even if reopened.
                existing = next((i for i in next_state["invoices"]
                                 if i["cardId"] == card_id and i["contractId"] == contract_id
                                 and i["completionId"] is not None), None)
                if existing is None:
                    invoice_id = _make_invoice(next_state, idempotency="auto:" + completion_id,
                                               project_id=project_id, card_id=card_id,
                                               contract_id=contract_id, completion_id=completion_id,
                                               supersedes=None, sale=contract["sale"], actor=actor, now=now)
                    created = True
                    _ledger(next_state, event_id=_derived("invoice-event", event_id), actor=actor,
                            action="invoice.create", project_id=project_id, card_id=card_id,
                            invoice_id=invoice_id, payload={"contractId": contract_id,
                                                             "completionId": completion_id}, at=now)
                else:
                    invoice_id = existing["id"]
            next_state["completionIds"][completion_id] = {"cardId": card_id, "invoiceId": invoice_id}
            result = {"invoiceCreated": created, "duplicateCompletion": False}
        _ledger(next_state, event_id=event_id, actor=actor, action=kind,
                project_id=project_id, card_id=card_id, invoice_id=None,
                payload={"completionId": completion_id, **result}, at=now)
    else:
        permission = "admin"
        _require(users[actor], project_id, permission)
        info = invoice_status(next_state, invoice["id"])
        status = info["status"]
        if kind == "invoice.review":
            if status != "Draft":
                raise ValueError("Only a draft can enter review")
            payload = {}
            result = {"invoiceId": invoice["id"], "status": "Review"}
        elif kind == "invoice.issue":
            if status != "Review":
                raise ValueError("Invoice requires review before issuance")
            number = next_state["nextInvoiceNumber"]
            next_state["nextInvoiceNumber"] += 1
            payload = {"number": number}
            result = {"invoiceId": invoice["id"], "status": "Issued", "number": number}
        elif kind == "invoice.payment":
            if status not in {"Issued"}:
                raise ValueError("Payment requires issued invoice")
            payment = amount(command["amount"], name="payment")
            if payment == 0 or payment > info["remaining"]:
                raise ValueError("Payment must be positive and within outstanding balance")
            payload = {"amount": payment}
            result = {"invoiceId": invoice["id"], "remaining": info["remaining"] - payment,
                      "status": "Paid" if payment == info["remaining"] else "Issued"}
        elif kind == "invoice.cancel":
            if status not in {"Draft", "Review", "Issued"} or info["paidAfterAdvance"]:
                raise ValueError("Cannot cancel paid/superseded/cancelled invoice")
            payload = {"reason": _text(command["reason"], "cancellation reason", 500)}
            result = {"invoiceId": invoice["id"], "status": "Cancelled"}
        else:
            if status not in {"Draft", "Review"}:
                raise ValueError("Issued/paid/cancelled invoices cannot be revised")
            reason = _text(command["reason"], "revision reason", 500)
            sale = _sale(command["sale"])
            replacement_id = _make_invoice(next_state, idempotency=event_id,
                                           project_id=project_id, card_id=card_id,
                                           contract_id=invoice["contractId"],
                                           completion_id=None, supersedes=invoice["id"],
                                           sale=sale, actor=actor, now=now)
            _ledger(next_state, event_id=_derived("replaced-event", event_id), actor=actor,
                    action="invoice.replaced", project_id=project_id, card_id=card_id,
                    invoice_id=invoice["id"], payload={"replacementId": replacement_id}, at=now)
            payload = {"reason": reason, "replacementId": replacement_id}
            result = {"invoiceId": replacement_id, "replaces": invoice["id"], "status": "Draft"}
        _ledger(next_state, event_id=event_id, actor=actor, action=kind,
                project_id=project_id, card_id=card_id, invoice_id=invoice["id"],
                payload=payload, at=now)
    next_state["receipts"][event_id] = {"fingerprint": fingerprint, "projectId": project_id,
                                        "permission": permission, "result": deepcopy(result)}
    validate_finance_state(next_state)
    return {"state": next_state, "changed": True, "result": result}


def list_invoices(state, *, actor, accounts, cards, projects, project_id=None):
    """Financially authorized, detached invoice snapshots with ledger-derived status."""
    validate_finance_state(state)
    users, _, prjs = _context(actor, accounts, cards, projects)
    if project_id is not None and _id(project_id, "projectId") not in prjs:
        raise ValueError("Project not found")
    if project_id is not None:
        _require(users[actor], project_id, "view")
    return [{**deepcopy(invoice), **invoice_status(state, invoice["id"])}
            for invoice in state["invoices"]
            if (project_id is None or invoice["projectId"] == project_id)
            and _can(users[actor], invoice["projectId"], permission="view")]


def list_finance_ledger(state, *, actor, accounts, cards, projects, project_id=None):
    """Authorized audit events; no full ledger/receipts exposure to LAN clients."""
    validate_finance_state(state)
    users, _, prjs = _context(actor, accounts, cards, projects)
    if project_id is not None and _id(project_id, "projectId") not in prjs:
        raise ValueError("Project not found")
    if project_id is not None:
        _require(users[actor], project_id, "view")
    return deepcopy([entry for entry in state["ledger"]
                     if (project_id is None or entry["projectId"] == project_id)
                     and _can(users[actor], entry["projectId"], permission="view")])


def financial_overview(state, *, actor, accounts, cards, projects,
                       project_id="", start_date="", end_date=""):
    """Admin-only cash received minus recorded task/checklist costs.

    Task costs are entered values (estimates, unless separately adjusted in
    cardCosts). Explicit costDate fields take priority; historical entries
    without dates fall back to the task's last update date. These dates do not
    prove an expense was paid.
    Explicit project receipts and invoice.payment ledger actions represent
    incoming cash. Sale prices and invoice advances are never treated as cash.
    """
    validate_finance_state(state)
    users, tasks, prjs = _context(actor, accounts, cards, projects)
    if users[actor]["role"] != "admin":
        raise PermissionError("Financial overview requires administrator")
    if not isinstance(project_id, str):
        raise ValueError("Invalid project filter")
    selected = _id(project_id, "projectId") if project_id else None
    if selected and selected not in prjs:
        raise ValueError("Project not found")
    start, end = _calendar_date(start_date), _calendar_date(end_date)
    if start and end and start > end:
        raise ValueError("Start date is after end date")

    selected_projects = {pid: project for pid, project in prjs.items()
                         if selected is None or pid == selected}
    rows = {pid: {"projectId": pid, "name": project.get("name", ""),
                  "receivedTotal": 0, "expenseTotal": 0, "actualTotal": 0,
                  "profit": 0} for pid, project in selected_projects.items()}
    received_entries = []

    def in_range(calendar_day):
        return calendar_day is not None and (start is None or calendar_day >= start) and (
            end is None or calendar_day <= end)

    for entry in state["ledger"]:
        if entry["projectId"] not in rows or entry["action"] not in ("project.receipt", "invoice.payment"):
            continue
        payload = entry["payload"]
        at = payload["receivedAt"] if entry["action"] == "project.receipt" else entry["at"]
        if not in_range(_calendar_date(at[:10])):
            continue
        cash = amount(payload["amount"], name="received payment")
        rows[entry["projectId"]]["receivedTotal"] += cash
        received_entries.append({"eventId": entry["eventId"], "projectId": entry["projectId"],
                                 "amount": cash, "receivedAt": at,
                                 "description": payload.get("description", ""),
                                 "type": entry["action"]})

    expenses = []
    groups = {}
    for card in tasks.values():
        pid = card["projectId"]
        if pid not in rows:
            continue
        stamp = card.get("updatedAt") or card.get("createdAt") or ""
        try:
            day = _calendar_date(stamp[:10]) if isinstance(stamp, str) else None
        except ValueError:
            day = None
        task_cost_date = _calendar_date(card.get("costDate", "")) or day
        summary = card_cost_summary(card, selected_projects[pid],
                                    override=state["cardCosts"].get(card["id"]))
        named = {}
        checklist_groups = card.get("checklists") or []
        if checklist_groups:
            for group in checklist_groups:
                for item in group["items"]:
                    named[group["id"] + ":" + item["id"]] = item
        else:
            for index, item in enumerate(card.get("checklist", [])):
                named["checklist-legacy:" + item.get("id", f"legacy-{index}")] = item

        def add_line(category, estimated, actual, item_id=None, expense_day=None):
            if (start is not None or end is not None) and not in_range(expense_day):
                return
            estimated = amount(estimated, name="recorded expense")
            actual = amount(actual, name="actual expense")
            if estimated == 0 and actual == 0:
                return
            category = _category(category)
            record = {"projectId": pid, "cardId": card["id"], "itemId": item_id,
                      "category": category, "amount": estimated,
                      "actualAmount": actual, "date": expense_day.isoformat() if expense_day else ""}
            expenses.append(record)
            rows[pid]["expenseTotal"] += estimated
            rows[pid]["actualTotal"] += actual
            bucket = groups.setdefault(category, {"category": category, "total": 0,
                                                  "actualTotal": 0, "count": 0})
            bucket["total"] += estimated
            bucket["actualTotal"] += actual
            bucket["count"] += 1

        add_line(card.get("costCategory", ""), summary["estimatedDirect"],
                 summary["actualDirect"], expense_day=task_cost_date)
        for item in summary["checklist"]:
            source = named.get(item["id"], {})
            cost_day = _calendar_date(source.get("costDate", "")) or task_cost_date
            add_line(source.get("costCategory", ""), item["estimated"], item["actual"],
                     item["id"], cost_day)

    for row in rows.values():
        for name in ("receivedTotal", "expenseTotal", "actualTotal"):
            if row[name] > MAX_TOTAL:
                raise ValueError("Financial overview exceeds supported amount")
        row["profit"] = row["receivedTotal"] - row["expenseTotal"]
    received_total = sum(row["receivedTotal"] for row in rows.values())
    expense_total = sum(row["expenseTotal"] for row in rows.values())
    actual_total = sum(row["actualTotal"] for row in rows.values())
    if any(x > MAX_TOTAL for x in (received_total, expense_total, actual_total)):
        raise ValueError("Financial overview exceeds supported amount")
    return {"projectId": project_id, "startDate": start_date or "", "endDate": end_date or "",
            "receivedTotal": received_total, "expenseTotal": expense_total,
            "actualTotal": actual_total, "profit": received_total - expense_total,
            "categories": sorted(groups.values(), key=lambda entry: entry["category"]),
            "projects": sorted(rows.values(), key=lambda entry: entry["name"]),
            "receipts": sorted(received_entries, key=lambda entry: entry["receivedAt"]),
            "expenses": expenses,
            "costDateBasis": "costDate (fallback task.updatedAt/task.createdAt)",
            "expenseBasis": "recorded_estimates", "receiptsBasis": "explicit_received_payments"}


__all__ = ["SCHEMA_VERSION", "MAX_MONEY", "amount", "empty_finance_state",
           "validate_finance_state", "card_cost_summary", "project_cost_summary",
           "invoice_status", "apply_finance_command", "list_invoices", "list_finance_ledger",
           "financial_overview"]
