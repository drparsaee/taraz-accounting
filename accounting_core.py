"""Deterministic, event-sourced, double-entry accounting for Madar Desk.

The host authenticates actors, supplies its clock, and atomically persists the
entire returned state. No IO, database, filesystem, or implicit tax rules.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re

SCHEMA_VERSION = 1
RIAL_SCHEMA_VERSION = 2
MAX_TOMAN = 10**15
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_KIND = {"asset", "liability", "equity", "revenue", "expense"}
_CREDIT_NORMAL = {"liability", "equity", "revenue"}

_DEFAULT_ACCOUNTS = (
    ("1000", "Cash", "asset", True),
    ("1010", "Bank", "asset", True),
    ("1200", "Accounts receivable", "asset", False),
    ("1300", "Inventory asset", "asset", False),
    ("2000", "Accounts payable", "liability", False),
    ("2200", "Explicit sales tax clearing", "liability", False),
    ("2300", "Payroll payable", "liability", False),
    ("2400", "Payroll withholding payable", "liability", False),
    ("3000", "Owner funding", "equity", False),
    ("3100", "Retained profit and loss", "equity", False),
    ("4000", "Sales", "revenue", False),
    ("4100", "Sales discounts", "expense", False),
    ("5000", "Purchases and expenses", "expense", False),
    ("5100", "Purchase discounts", "revenue", False),
    ("5200", "Purchase tax as expense", "expense", False),
    ("5300", "Inventory cost of sales", "expense", False),
    ("5400", "Payroll gross expense", "expense", False),
)
_NEW_SYSTEM_ACCOUNTS = frozenset({"1300", "2300", "2400", "3100", "5300", "5400"})

# The LAN grants standalone finance mutation to an authenticated editor with
# financeEdit=True. Keep the reducer equally capable for ordinary accounting
# work, but enumerate permissions: an unknown/new operation is never silently
# authorized just because it shares a command prefix.
_EDITOR_FINANCE_COMMANDS = frozenset({
    "proforma.create", "proforma.update", "proforma.send", "proforma.accept",
    "proforma.reject", "proforma.cancel", "proforma.convert",
    "contractor.job.intake", "contractor.job.price", "contractor.job.approve",
    "contractor.bill.create",
    "party.register", "party.update", "item.create", "item.update",
    "invoice.create", "invoice.update", "invoice.reopen", "invoice.approve",
    "invoice.issue", "invoice.cancel", "invoice.return", "invoice.correct",
    "bill.create", "bill.update", "bill.reopen", "bill.approve",
    "bill.issue", "bill.cancel", "bill.return", "bill.correct",
    "receipt.record", "payment.record", "funds.transfer",
    "journal.manual", "journal.reverse",
    "warehouse.create", "item.stock.enable", "inventory.receive",
    "inventory.issue", "inventory.transfer", "inventory.adjust", "inventory.reverse",
    "cheque.register", "cheque.deposit", "cheque.endorse", "cheque.clear",
    "cheque.return", "cheque.redeliver", "cheque.cancel",
    "bank.statement.add", "bank.statement.batch", "bank.statement.match",
    "bank.statement.unmatch", "installments.create", "installments.cancel",
    "payroll.accrue", "payroll.pay", "payroll.remit",
})

# Structural controls, changes to legal/tax identity, owner equity funding,
# opening inventory capital and irreversible period/year closure need admin.
_ADMIN_ONLY_COMMANDS = frozenset({
    "account.create", "company.profile.set", "funds.deposit",
    "inventory.opening", "tax.rule.set", "fiscal.year.close", "period.close",
    "opening.balance.post",
})


def _object(value, required, optional=()):
    if (type(value) is not dict or not set(required) <= set(value)
            or set(value) - set(required) - set(optional)):
        raise ValueError("Missing or unexpected fields")
    return value


def _id(value, field="id"):
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {field}")
    return value


def _text(value, field, *, limit=300):
    if (type(value) is not str or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError(f"Invalid {field}")
    return value.strip()


def _int(value, field, *, positive=False, cap=MAX_TOMAN):
    if type(value) is not int or value < (1 if positive else 0) or value > cap:
        raise ValueError(f"{field} must be an exact integer toman within range")
    return value


def _add(*amounts):
    total = sum(amounts)
    return _int(total, "calculated total")


def _outstanding(document):
    """Posted face value less actual settlements and posted credit notes."""
    return document["total"] - document["allocated"] - document.get("returnedAmount", 0)


def _rounded_share(total, numerator, denominator):
    """Allocate an explicit document amount without floating-point rounding."""
    if denominator <= 0:
        raise ValueError("Partial return requires a positive original subtotal")
    return (total * numerator * 2 + denominator) // (2 * denominator)


def _date(value):
    if type(value) is not str or not _DAY.fullmatch(value):
        raise ValueError("Expected YYYY-MM-DD date")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Noncanonical date")
    except ValueError as error:
        raise ValueError("Invalid calendar date") from error
    return value


def _time(value):
    if type(value) is not str or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", value):
        raise ValueError("Trusted now must include timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("Timezone required")
    except ValueError as error:
        raise ValueError("Invalid trusted timestamp") from error
    return value


def _posting_today(p, now):
    """Convert the trusted instant to the configured company posting day.

    Historical ledgers without a configured offset preserve their existing
    calendar-day behavior. The offset is explicit and fixed, not inferred.
    """
    offset = (p.get("companyProfile") or {}).get("postingUtcOffsetMinutes")
    if offset is None:
        return now[:10]
    instant = datetime.fromisoformat(now.replace("Z", "+00:00"))
    return instant.astimezone(timezone(timedelta(minutes=offset))).date().isoformat()


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Expected JSON-compatible data") from error


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def empty_accounting_state():
    """A portable, versioned JSON snapshot. Events are its only mutable data."""
    return {"schemaVersion": SCHEMA_VERSION, "currency": "TOMAN", "events": []}


def empty_rial_accounting_state():
    """New independent RIAL ledger. Existing TOMAN event chains remain untouched."""
    return {"schemaVersion": RIAL_SCHEMA_VERSION, "currency": "RIAL", "events": []}


def _new_projection(currency="TOMAN", *, preserve_historical_custom_ids=frozenset()):
    return {
        "currency": currency,
        "accounts": {aid: {"id": aid, "name": name, "kind": kind,
                             "liquid": liquid, "system": True,
                             "level": "kol", "parentId": None}
                     for aid, name, kind, liquid in _DEFAULT_ACCOUNTS
                     if aid not in (_NEW_SYSTEM_ACCOUNTS & preserve_historical_custom_ids)},
        "parties": {}, "items": {}, "proformas": {}, "invoices": {}, "bills": {}, "receipts": {},
        "payments": {}, "journals": [], "entries": {}, "balances": {},
        "openingBalances": {}, "openingSources": {},
        "contractorJobs": {},
        "cheques": {}, "bankStatements": {}, "warehouses": {},
        "stock": {}, "stockMovements": {}, "installmentPlans": {},
        "payroll": {}, "fiscalYears": [], "taxRules": {},
        "companyProfile": None,
        "reversed": {}, "closedThrough": None, "returns": {},
        "sequence": {"invoice": 0, "bill": 0},
    }


def _actor_role(actor, accounts):
    _id(actor, "actor")
    if type(accounts) is dict:
        users = list(accounts.values())
        for name, record in accounts.items():
            if type(record) is not dict or record.get("username") != name:
                raise ValueError("Authoritative account index mismatch")
    elif type(accounts) is list:
        users = accounts
    else:
        raise ValueError("Expected authoritative accounts list or map")
    found = {}
    for account in users:
        if type(account) is not dict:
            raise ValueError("Invalid authoritative account")
        name = _id(account.get("username"), "username")
        role = account.get("role")
        if role not in ("admin", "editor", "viewer") or name in found:
            raise ValueError("Invalid or duplicate account role")
        for permission in ("financeView", "financeEdit"):
            if permission in account and type(account[permission]) is not bool:
                raise ValueError("Invalid financial permission flag")
        found[name] = account
    if actor not in found:
        raise PermissionError("Unauthenticated accounting actor")
    return found[actor]


def _require(role, command_type, *, finance_edit=False, finance_view=False):
    if role == "admin":
        return
    if (role == "editor" and finance_edit is True
            and command_type in _EDITOR_FINANCE_COMMANDS):
        return
    raise PermissionError("Accounting operation requires a trusted finance role")


def _require_view(account):
    if (account["role"] != "admin" and account.get("financeView") is not True
            and not (account["role"] == "editor" and account.get("financeEdit") is True)):
        raise PermissionError("Accounting read access denied")


def _account(p, account_id, *, kind=None, liquid=False):
    account = p["accounts"].get(_id(account_id, "accountId"))
    if account is None or (kind is not None and account["kind"] != kind) or (
            liquid and not account["liquid"]):
        raise ValueError("Missing or incompatible ledger account")
    return account


def _party(p, party_id, kind):
    party = p["parties"].get(_id(party_id, "partyId"))
    if party is None or party["kind"] not in (kind, "both"):
        raise ValueError("Missing or incompatible named party")
    return party


def _lines(p, value, *, sales):
    if type(value) is not list or not 1 <= len(value) <= 1000:
        raise ValueError("Document requires 1..1000 explicit lines")
    output = []
    subtotal = 0
    for line in value:
        _object(line, ("description", "quantity", "unitPrice"), ("accountId", "itemId"))
        quantity = _int(line["quantity"], "quantity", positive=True, cap=1000000)
        unit_price = _int(line["unitPrice"], "unitPrice")
        total = _int(quantity * unit_price, "line total")
        account_id = line.get("accountId", "4000" if sales else "5000")
        _account(p, account_id, kind="revenue" if sales else "expense")
        item_id = line.get("itemId")
        if item_id is not None:
            item = p["items"].get(_id(item_id, "itemId"))
            if item is None or not item["active"]:
                raise ValueError("Invoice item missing or inactive")
        output.append({"description": _text(line["description"], "description"),
                       "quantity": quantity, "unitPrice": unit_price,
                       "accountId": account_id, "total": total,
                       **({"itemId": item_id} if item_id is not None else {})})
        subtotal = _add(subtotal, total)
    return output, subtotal


def _make_document(p, command, *, sales, allow_proforma_source=False):
    prefix = "invoice" if sales else "bill"
    key = prefix + "Id"
    _object(command, ("type", "eventId", key, "partyId", "documentDate", "lines"),
            ("discount", "tax", "note", "sourceType", "sourceId", "taxRuleId", "dueDate"))
    identifier = _id(command[key], key)
    collection = p["invoices" if sales else "bills"]
    if identifier in collection:
        raise ValueError("Duplicate document ID")
    if ("sourceType" in command) != ("sourceId" in command):
        raise ValueError("Source type and source ID must be supplied together")
    source_type = _id(command["sourceType"], "sourceType") if "sourceType" in command else None
    source_id = _id(command["sourceId"], "sourceId") if "sourceId" in command else None
    if sales and source_type == "proforma" and not allow_proforma_source:
        raise ValueError("Proforma linkage must use the verified conversion command")
    if source_type is not None and any(d["sourceType"] == source_type and
                                      d["sourceId"] == source_id and d["status"] != "cancelled"
                                      for d in collection.values()):
        raise ValueError("Business source has already been invoiced or billed")
    _party(p, command["partyId"], "customer" if sales else "vendor")
    lines, subtotal = _lines(p, command["lines"], sales=sales)
    discount = _int(command.get("discount", 0), "discount")
    tax = _int(command.get("tax", 0), "explicit tax amount")
    if discount > subtotal:
        raise ValueError("Discount exceeds subtotal")
    total = _add(subtotal - discount, tax)
    due_date = _date(command["dueDate"]) if "dueDate" in command else None
    if due_date is not None and due_date < _date(command["documentDate"]):
        raise ValueError("Document due date cannot precede document date")
    tax_rule_id = command.get("taxRuleId")
    tax_rule_rate = None
    if tax_rule_id is not None:
        rule = p["taxRules"].get(_id(tax_rule_id, "taxRuleId"))
        prior = (max((record for record in rule["history"]
                      if record["effectiveFrom"] <= command["documentDate"]),
                     key=lambda record: record["effectiveFrom"], default=None)
                 if rule is not None else None)
        if prior is None:
            raise ValueError("Missing or not yet effective tax policy")
        tax_rule_rate = prior["rateBasisPoints"]
        expected_tax = ((subtotal - discount) * tax_rule_rate + 5000) // 10000
        if tax != expected_tax:
            raise ValueError("Tax amount does not match configured accounting policy")
    if total == 0:
        raise ValueError("Document amount must be positive")
    document = {"id": identifier, "partyId": command["partyId"],
                "documentDate": _date(command["documentDate"]),
                "lines": lines, "subtotal": subtotal, "discount": discount,
                "tax": tax, "total": total,
                "note": _text(command["note"], "note", limit=1000) if "note" in command else "",
                "sourceType": source_type, "sourceId": source_id,
                "taxRuleId": tax_rule_id, "taxRuleRate": tax_rule_rate,
                "status": "draft", "cancelReason": None, "number": None, "postingDate": None,
                "postedEntryId": None, "allocated": 0, "dueDate": due_date}
    collection[identifier] = document
    return {"documentId": identifier, "total": total, "status": "draft"}


def _proforma_create(p, command, *, update=False):
    """Pre-invoice commercial offer, never a receivable or GL posting."""
    _object(command,
            ("type", "eventId", "proformaId", "partyId", "documentDate", "lines"),
            ("discount", "tax", "note", "validUntil"))
    ident = _id(command["proformaId"], "proformaId")
    old = p["proformas"].get(ident)
    if update:
        if old is None or old["status"] != "draft":
            raise ValueError("Only a draft proforma may be changed")
    elif old is not None:
        raise ValueError("Duplicate proforma ID")
    party_id = _id(command["partyId"], "partyId")
    _party(p, party_id, "customer")
    document_day = _date(command["documentDate"])
    expiry = command.get("validUntil")
    if expiry is not None:
        expiry = _date(expiry)
        if expiry < document_day:
            raise ValueError("Proforma expiration precedes document date")
    lines, subtotal = _lines(p, command["lines"], sales=True)
    discount = _int(command.get("discount", 0), "discount")
    tax = _int(command.get("tax", 0), "explicit tax amount")
    if discount > subtotal:
        raise ValueError("Proforma discount exceeds subtotal")
    total = _add(subtotal - discount, tax)
    if total == 0:
        raise ValueError("Proforma must have a positive amount")
    record = {"id": ident, "partyId": party_id, "documentDate": document_day,
              "validUntil": expiry, "lines": lines, "subtotal": subtotal,
              "discount": discount, "tax": tax, "total": total,
              "note": _text(command["note"], "note", limit=1000)
              if "note" in command else "", "status": "draft",
              "reason": None, "convertedInvoiceId": None}
    p["proformas"][ident] = record
    return {"proformaId": ident, "status": "draft", "total": total,
            "updated": update}


def _proforma_transition(p, command, now):
    kind = command["type"]
    if kind == "proforma.convert":
        _object(command, ("type", "eventId", "proformaId", "invoiceId", "documentDate"))
    elif kind in {"proforma.reject", "proforma.cancel"}:
        _object(command, ("type", "eventId", "proformaId", "reason"))
    else:
        _object(command, ("type", "eventId", "proformaId"))
    ident = _id(command["proformaId"], "proformaId")
    record = p["proformas"].get(ident)
    if record is None:
        raise ValueError("Unknown proforma")
    status = record["status"]
    if kind == "proforma.send":
        if status != "draft":
            raise ValueError("Only a draft proforma may be sent")
        record["status"] = "sent"
    elif kind == "proforma.accept":
        if status != "sent":
            raise ValueError("Only a sent proforma may be accepted")
        if record["validUntil"] is not None and now[:10] > record["validUntil"]:
            raise ValueError("Expired proforma cannot be accepted")
        record["status"] = "accepted"
    elif kind == "proforma.reject":
        if status != "sent":
            raise ValueError("Only a sent proforma may be rejected")
        record["status"] = "rejected"
        record["reason"] = _text(command["reason"], "rejection reason", limit=1000)
    elif kind == "proforma.cancel":
        if status not in ("draft", "sent", "accepted"):
            raise ValueError("Proforma cannot be cancelled after conversion")
        record["status"] = "cancelled"
        record["reason"] = _text(command["reason"], "cancellation reason", limit=1000)
    elif kind == "proforma.convert":
        if status != "accepted":
            raise ValueError("Only an accepted proforma may become an invoice")
        invoice_id = _id(command["invoiceId"], "invoiceId")
        invoice_date = _date(command["documentDate"])
        if invoice_date < record["documentDate"]:
            raise ValueError("Invoice cannot predate its proforma")
        if invoice_date > _posting_today(p, now):
            raise ValueError("Cannot convert proforma into a future-dated invoice")
        invoice_command = {"type": "invoice.create", "eventId": command["eventId"],
                           "invoiceId": invoice_id, "partyId": record["partyId"],
                           "documentDate": invoice_date, "lines": [
                               {k: line[k] for k in ("description", "quantity", "unitPrice", "accountId")}
                               | ({"itemId": line["itemId"]} if "itemId" in line else {})
                               for line in record["lines"]],
                           "discount": record["discount"], "tax": record["tax"],
                           "sourceType": "proforma", "sourceId": ident}
        if record["note"]:
            invoice_command["note"] = record["note"]
        result = _make_document(p, invoice_command, sales=True,
                                allow_proforma_source=True)
        record["status"] = "converted"
        record["convertedInvoiceId"] = invoice_id
        return {"proformaId": ident, "status": "converted", "invoiceId": invoice_id,
                "total": result["total"]}
    else:
        raise ValueError("Unsupported proforma transition")
    return {"proformaId": ident, "status": record["status"]}


def _contractor_job(p, command):
    """Track vendor work without creating accounts payable or a GL entry."""
    _object(command, ("type", "eventId", "jobId", "sourceType", "sourceId",
                      "partyId", "description", "quantity", "currency"),
            ("unitPrice",))
    if command["currency"] != p["currency"]:
        raise ValueError("Contractor job currency must match accounting ledger")
    job_id = _id(command["jobId"], "jobId")
    source_type = _id(command["sourceType"], "sourceType")
    source_id = _id(command["sourceId"], "sourceId")
    _party(p, command["partyId"], "vendor")
    quantity = _int(command["quantity"], "quantity", positive=True, cap=1000000)
    description = _text(command["description"], "description")
    price = command.get("unitPrice")
    if price is not None:
        price = _int(price, "unitPrice", positive=True)
        _int(price * quantity, "job total")
    job = {"id": job_id, "sourceType": source_type, "sourceId": source_id,
           "partyId": command["partyId"], "description": description,
           "quantity": quantity, "currency": p["currency"], "unitPrice": price,
           "confirmedQuantity": None, "status": "unpriced" if price is None else "priced",
           "billedBy": None}
    for existing in p["contractorJobs"].values():
        if existing["id"] == job_id or (existing["sourceType"], existing["sourceId"]) == (source_type, source_id):
            if all(existing[key] == job[key] for key in
                   ("id", "sourceType", "sourceId", "partyId", "description", "quantity",
                    "currency", "unitPrice")):
                return {"jobId": existing["id"], "status": existing["status"]}
            raise ValueError("Contractor commercial source conflicts with existing work")
    p["contractorJobs"][job_id] = job
    return {"jobId": job_id, "status": job["status"]}


def _contractor_price(p, command):
    _object(command, ("type", "eventId", "jobId", "unitPrice", "currency"))
    job = p["contractorJobs"].get(_id(command["jobId"], "jobId"))
    if job is None or job["status"] not in ("unpriced", "priced"):
        raise ValueError("Only unbilled contractor jobs can be priced")
    if command["currency"] != p["currency"] or command["currency"] != job["currency"]:
        raise ValueError("Contractor price currency must match accounting ledger")
    price = _int(command["unitPrice"], "unitPrice", positive=True)
    _int(job["quantity"] * price, "job total")
    job["unitPrice"], job["status"] = price, "priced"
    return {"jobId": job["id"], "status": "priced"}


def _contractor_approve(p, command):
    _object(command, ("type", "eventId", "jobId", "confirmedQuantity"))
    job = p["contractorJobs"].get(_id(command["jobId"], "jobId"))
    if job is None or job["status"] != "priced":
        raise ValueError("A declared contractor price is required")
    quantity = _int(command["confirmedQuantity"], "confirmedQuantity",
                    positive=True, cap=1000000)
    if quantity != job["quantity"]:
        raise ValueError("Supplier quantity differs from assigned quantity")
    job["confirmedQuantity"], job["status"] = quantity, "approved"
    return {"jobId": job["id"], "status": "approved"}


def _contractor_bill(p, command):
    _object(command, ("type", "eventId", "billId", "partyId", "documentDate", "jobIds"))
    job_ids = command["jobIds"]
    if type(job_ids) is not list or not 1 <= len(job_ids) <= 1000:
        raise ValueError("Expected 1..1000 contractor work IDs")
    checked = [_id(job, "jobId") for job in job_ids]
    if len(set(checked)) != len(checked):
        raise ValueError("Repeated contractor work ID")
    jobs = []
    for job_id in checked:
        job = p["contractorJobs"].get(job_id)
        if (job is None or job["status"] != "approved" or
                job["partyId"] != command["partyId"] or job["billedBy"] is not None):
            raise ValueError("Job already billed, unapproved or belongs to another vendor")
        jobs.append(job)
    result = _make_document(p, {
        "type": "bill.create", "eventId": command["eventId"],
        "billId": command["billId"], "partyId": command["partyId"],
        "documentDate": command["documentDate"],
        "sourceType": "contractor.batch", "sourceId": command["billId"],
        "lines": [{"description": j["description"], "quantity": j["confirmedQuantity"],
                   "unitPrice": j["unitPrice"]} for j in jobs],
    }, sales=False)
    p["bills"][command["billId"]]["contractorJobIds"] = checked
    for job in jobs:
        job["status"], job["billedBy"] = "billed", command["billId"]
    return {**result, "jobIds": checked}


def _posting_date(p, posting_date, now):
    day = _date(posting_date)
    if day > _posting_today(p, now):
        raise ValueError("Posting in future is refused")
    if p["closedThrough"] is not None and day <= p["closedThrough"]:
        raise ValueError("Posting in closed period is refused")
    return day


def _line(account_id, *, debit=0, credit=0, party_id=None):
    result = {"accountId": account_id, "debit": debit, "credit": credit}
    if party_id is not None:
        result["partyId"] = party_id
    return result


def _check_liquidity_timeline(p, upcoming):
    """Prevent backdated postings from causing a historical cash overdraft."""
    liquids = {key for key, item in p["accounts"].items() if item["liquid"]}
    running = {key: 0 for key in liquids}
    ordered = sorted(enumerate([*p["journals"], upcoming]),
                     key=lambda pair: (pair[1]["date"], pair[0]))
    for _, entry in ordered:
        for line in entry["lines"]:
            account = line["accountId"]
            if account in liquids:
                running[account] += line["debit"] - line["credit"]
                if running[account] < 0 or running[account] > MAX_TOMAN:
                    raise ValueError("Insufficient historical cash/bank balance")


def _post(p, event_id, source_type, source_id, day, lines, *, reversal_of=None):
    entry_id = "J:" + event_id
    if entry_id in p["entries"]:
        raise ValueError("Duplicate journal entry")
    if type(lines) is not list or len(lines) < 2:
        raise ValueError("Journal requires at least two lines")
    dr = cr = 0
    new_balances = dict(p["balances"])
    for row in lines:
        _object(row, ("accountId", "debit", "credit"), ("partyId",))
        account = _account(p, row["accountId"])
        debit = _int(row["debit"], "debit")
        credit = _int(row["credit"], "credit")
        if (debit > 0) == (credit > 0):
            raise ValueError("Journal line must contain exactly one positive side")
        if "partyId" in row:
            _id(row["partyId"], "partyId")
            if row["partyId"] not in p["parties"]:
                raise ValueError("Unknown journal party")
        dr = _add(dr, debit)
        cr = _add(cr, credit)
        signed = new_balances.get(account["id"], 0) + debit - credit
        if abs(signed) > MAX_TOMAN:
            raise ValueError("Ledger balance exceeds maximum")
        new_balances[account["id"]] = signed
    if dr != cr or dr == 0:
        raise ValueError("Unbalanced journal entry")
    if any(a["liquid"] and new_balances.get(a["id"], 0) < 0
           for a in p["accounts"].values()):
        raise ValueError("Insufficient available cash/bank balance")
    entry = {"id": entry_id, "eventId": event_id, "sourceType": source_type,
             "sourceId": source_id, "date": day, "lines": deepcopy(lines),
             "reversalOf": reversal_of}
    _check_liquidity_timeline(p, entry)
    p["balances"] = new_balances
    p["entries"][entry_id] = entry
    p["journals"].append(entry)
    return entry


def _opening_batch(p, command, now):
    """Post one explicit, admin-only historical opening batch to RIAL ledger.

    An opening is a named party liability/asset, not a manufactured invoice.
    Once financial journals exist, a new opening requires a separately audited
    migration workflow; retroactive imports cannot bypass source reconciliation.
    All rows and the balanced journal are returned in ONE host SQLite revision.
    """
    from taraz_opening_contract import inspect_opening_batch

    preview = inspect_opening_batch(command)
    if p["currency"] != "RIAL":
        raise ValueError("Opening balances require independent RIAL ledger V2")
    if p["journals"] or p["openingSources"]:
        raise ValueError("Opening batch must precede all financial postings")
    if command["sourceId"] in p["openingSources"]:
        raise ValueError("Duplicate opening source")
    day = _posting_date(p, command["postingDate"], now)
    if day != command["fiscalStartDate"]:
        raise ValueError("Initial opening must post on the explicit fiscal start date")
    _account(p, "3000", kind="equity")
    _account(p, "1200", kind="asset")
    _account(p, "2000", kind="liability")
    # Validate every named party BEFORE any in-memory GL change.
    for row in command["rows"]:
        if row["sourceRef"] in p["openingBalances"]:
            raise ValueError("Duplicate opening line source")
        _party(p, row["partyId"],
               "customer" if row["direction"] == "receivable" else "vendor")
    journal_lines = []
    for row in command["rows"]:
        amount = row["amountRial"]
        if row["direction"] == "receivable":
            journal_lines.extend((_line("1200", debit=amount, party_id=row["partyId"]),
                                  _line("3000", credit=amount)))
        else:
            journal_lines.extend((_line("3000", debit=amount),
                                  _line("2000", credit=amount, party_id=row["partyId"])))
    entry = _post(p, command["eventId"], "opening.balance.post",
                  command["sourceId"], day, journal_lines)
    for row in command["rows"]:
        p["openingBalances"][row["sourceRef"]] = {
            "id": row["sourceRef"],
            "sourceId": command["sourceId"],
            "partyId": row["partyId"],
            "direction": row["direction"],
            "total": row["amountRial"],
            "allocated": 0,
            "postingDate": day,
            "journalId": entry["id"],
            "active": True,
        }
    p["openingSources"][command["sourceId"]] = {
        "sourceDigest": command["sourceDigest"], "journalId": entry["id"],
        "fiscalStartDate": command["fiscalStartDate"],
        "rowCount": preview["rowCount"],
        "receivableRial": preview["receivableRial"],
        "payableRial": preview["payableRial"],
        "active": True,
    }
    return {"journalId": entry["id"], "sourceId": command["sourceId"],
            "rowCount": preview["rowCount"], "currency": "RIAL",
            "receivableRial": preview["receivableRial"],
            "payableRial": preview["payableRial"]}


def _issue(p, command, now, *, sales):
    prefix = "invoice" if sales else "bill"
    key = prefix + "Id"
    _object(command, ("type", "eventId", key, "postingDate"))
    doc = p["invoices" if sales else "bills"].get(_id(command[key], key))
    if doc is None or doc["status"] != "approved":
        raise ValueError("Only approved documents may be issued")
    day = _posting_date(p, command["postingDate"], now)
    if day < doc["documentDate"]:
        raise ValueError("Posting precedes document date")
    if sales:
        party = _party(p, doc["partyId"], "customer")
        limit = party.get("creditLimit")
        if limit is not None:
            existing = sum(_outstanding(d) for d in p["invoices"].values()
                           if d["status"] == "issued" and d["partyId"] == doc["partyId"])
            if existing + doc["total"] > limit:
                raise ValueError("Customer credit limit would be exceeded")
    lines = []
    if sales:
        lines.append(_line("1200", debit=doc["total"], party_id=doc["partyId"]))
        for item in doc["lines"]:
            if item["total"]:
                lines.append(_line(item["accountId"], credit=item["total"]))
        if doc["discount"]:
            lines.append(_line("4100", debit=doc["discount"]))
        if doc["tax"]:
            lines.append(_line("2200", credit=doc["tax"]))
    else:
        for item in doc["lines"]:
            if item["total"]:
                lines.append(_line(item["accountId"], debit=item["total"]))
        if doc["tax"]:
            lines.append(_line("5200", debit=doc["tax"]))
        if doc["discount"]:
            lines.append(_line("5100", credit=doc["discount"]))
        lines.append(_line("2000", credit=doc["total"], party_id=doc["partyId"]))
    entry = _post(p, command["eventId"], command["type"], doc["id"], day, lines)
    p["sequence"][prefix] += 1
    doc.update({"status": "issued", "number": p["sequence"][prefix],
                "postingDate": day, "postedEntryId": entry["id"]})
    return {"documentId": doc["id"], "number": doc["number"],
            "journalId": entry["id"], "total": doc["total"]}


def _allocations(p, command, *, sales):
    key = "invoiceId" if sales else "billId"
    collection = p["invoices" if sales else "bills"]
    allocations = command["allocations"]
    if type(allocations) is not list or not 1 <= len(allocations) <= 1000:
        raise ValueError("Explicit allocations required")
    amounts = []
    seen = set()
    total = 0
    for item in allocations:
        if type(item) is not dict:
            raise ValueError("Settlement allocation must be an object")
        if "openingRef" in item:
            _object(item, ("openingRef", "amount"))
            amt = _int(item["amount"], "allocation", positive=True)
            opening_ref = _id(item["openingRef"], "openingRef")
            identity = ("opening", opening_ref)
            target = p["openingBalances"].get(opening_ref)
            if (target is None or not target["active"] or
                    target["partyId"] != command["partyId"] or
                    target["direction"] != ("receivable" if sales else "payable")):
                raise ValueError("Opening allocation must match active named party and direction")
            if command["postingDate"] < target["postingDate"]:
                raise ValueError("Opening settlement cannot precede posting")
            if amt > _outstanding(target):
                raise ValueError("Over-allocation of historical opening")
            amounts.append({"openingRef": opening_ref, "amount": amt})
        else:
            _object(item, (key, "amount"))
            amt = _int(item["amount"], "allocation", positive=True)
            doc_id = _id(item[key], key)
            identity = ("document", doc_id)
            doc = collection.get(doc_id)
            if doc is None or doc["status"] != "issued" or doc["partyId"] != command["partyId"]:
                raise ValueError("Allocation must target issued document for named party")
            if command["postingDate"] < doc["postingDate"]:
                raise ValueError("Settlement cannot precede document posting date")
            if amt > _outstanding(doc):
                raise ValueError("Over-allocation or overpayment")
            amounts.append({key: doc_id, "amount": amt})
        if identity in seen:
            raise ValueError("Duplicate settlement allocation")
        seen.add(identity)
        total = _add(total, amt)
    return amounts, total


def _settle(p, command, now, *, sales):
    prefix = "receipt" if sales else "payment"
    id_key = prefix + "Id"
    _object(command, ("type", "eventId", id_key, "partyId", "accountId",
                      "postingDate", "allocations"))
    ident = _id(command[id_key], id_key)
    collection = p["receipts" if sales else "payments"]
    if ident in collection:
        raise ValueError("Duplicate settlement ID")
    _party(p, command["partyId"], "customer" if sales else "vendor")
    _account(p, command["accountId"], liquid=True)
    day = _posting_date(p, command["postingDate"], now)
    allocations, total = _allocations(p, command, sales=sales)
    if sales:
        lines = [_line(command["accountId"], debit=total),
                 _line("1200", credit=total, party_id=command["partyId"])]
    else:
        lines = [_line("2000", debit=total, party_id=command["partyId"]),
                 _line(command["accountId"], credit=total)]
    entry = _post(p, command["eventId"], command["type"], ident, day, lines)
    for item in allocations:
        if "openingRef" in item:
            doc = p["openingBalances"][item["openingRef"]]
        else:
            doc_id = item["invoiceId" if sales else "billId"]
            doc = p["invoices" if sales else "bills"][doc_id]
        doc["allocated"] += item["amount"]
    collection[ident] = {"id": ident, "partyId": command["partyId"],
                         "accountId": command["accountId"], "date": day,
                         "total": total, "allocations": allocations,
                         "journalId": entry["id"], "reversed": False}
    return {"id": ident, "amount": total, "journalId": entry["id"]}


def _reverse(p, command, now):
    _object(command, ("type", "eventId", "journalId", "postingDate", "reason"))
    journal_id = _id(command["journalId"], "journalId")
    original = p["entries"].get(journal_id)
    if original is None or journal_id in p["reversed"] or original["reversalOf"] is not None:
        raise ValueError("Journal missing or already reversed")
    if any(row["journalId"] == journal_id for row in p["bankStatements"].values()):
        raise ValueError("Unmatch bank statement before reversing this journal")
    source_type = original["sourceType"]
    if source_type not in {"invoice.issue", "bill.issue", "receipt.record",
                           "payment.record", "funds.deposit", "funds.transfer",
                           "journal.manual", "opening.balance.post"}:
        raise ValueError("Journal source cannot be reversed")
    _text(command["reason"], "reversal reason", limit=1000)
    day = _posting_date(p, command["postingDate"], now)
    if day < original["date"]:
        raise ValueError("Reversal must not precede original posting")
    if source_type in {"invoice.issue", "bill.issue"}:
        document = p["invoices" if source_type == "invoice.issue" else "bills"][original["sourceId"]]
        if document.get("returnedAmount", 0):
            raise ValueError("Posted partial credit notes must be resolved before reversing source document")
        if document["allocated"] != 0:
            raise ValueError("Reverse allocated settlements first")
        direction = "receipt" if source_type == "invoice.issue" else "payment"
        if any(ch["documentId"] == document["id"] and
               ch["direction"] == direction and
               ch["status"] not in ("cancelled", "reversed")
               for ch in p["cheques"].values()):
            raise ValueError("Cancel or reverse linked cheques before reversing invoice")
        movement_source = "invoiceId" if source_type == "invoice.issue" else "billId"
        if any(row.get(movement_source) == document["id"]
               and not row.get("reversed") for row in p["stockMovements"].values()):
            raise ValueError("Reverse linked inventory movements before the original invoice")
    if source_type == "opening.balance.post":
        source = p["openingSources"].get(original["sourceId"])
        if source is None or not source["active"]:
            raise ValueError("Opening batch is not active")
        if any(record["sourceId"] == original["sourceId"] and record["allocated"] != 0
               for record in p["openingBalances"].values()):
            raise ValueError("Reverse opening receipts/payments before reversing historical opening")
    lines = []
    for item in original["lines"]:
        lines.append(_line(item["accountId"], debit=item["credit"],
                           credit=item["debit"], party_id=item.get("partyId")))
    entry = _post(p, command["eventId"], "journal.reverse", journal_id,
                  day, lines, reversal_of=journal_id)
    p["reversed"][journal_id] = entry["id"]
    if source_type in {"invoice.issue", "bill.issue"}:
        document["status"] = "reversed"
    if source_type == "opening.balance.post":
        p["openingSources"][original["sourceId"]]["active"] = False
        for record in p["openingBalances"].values():
            if record["sourceId"] == original["sourceId"]:
                record["active"] = False
    if source_type in {"receipt.record", "payment.record"}:
        sales = source_type == "receipt.record"
        settlement = p["receipts" if sales else "payments"][original["sourceId"]]
        settlement["reversed"] = True
        for item in settlement["allocations"]:
            if "openingRef" in item:
                doc = p["openingBalances"][item["openingRef"]]
            else:
                doc = p["invoices" if sales else "bills"][
                    item["invoiceId" if sales else "billId"]]
            doc["allocated"] -= item["amount"]
        for cheque in p["cheques"].values():
            if cheque["journalId"] == journal_id:
                cheque["status"] = "reversed"
                cheque["history"].append({"type": "settlement.reversed",
                                          "eventId": command["eventId"],
                                          "at": now, "reason": command["reason"]})
    return {"reversedJournalId": journal_id, "journalId": entry["id"]}


def _guard_active_installments_on_new_reversal(p, command):
    """Fail closed for NEW reversals; don't invalidate historical event replay.

    Older ledger events are replayed by _project/_run. Rejecting them inside
    _reverse would make any already persisted legacy sequence unreadable.
    Therefore this gate runs only for a new, authenticated host command, after
    idempotent-event lookup and before mutating the in-memory projection.
    """
    kind = command.get("type")
    if kind == "journal.reverse":
        journal_id = command.get("journalId")
        original = (p["entries"].get(journal_id)
                    if type(journal_id) is str else None)
        if original is None:
            return  # Let _run reject the unknown journal normally.
        source_type = original["sourceType"]
        if source_type not in ("invoice.issue", "bill.issue"):
            return
        sales = source_type == "invoice.issue"
        document_id = original["sourceId"]
    elif kind in ("invoice.return", "invoice.correct", "bill.return", "bill.correct"):
        sales = kind.startswith("invoice.")
        document_id = command.get("invoiceId" if sales else "billId")
    else:
        return
    collection = p["invoices"] if sales else p["bills"]
    document = collection.get(document_id) if type(document_id) is str else None
    if document is None:
        return  # Original validation produces the proper missing-doc error.
    direction = "receipt" if sales else "payment"
    if any(plan["active"] and plan["documentId"] == document["id"]
           and plan["direction"] == direction
           for plan in p["installmentPlans"].values()):
        raise ValueError("Cancel active instalment plan before reversing or correcting document")


def _guard_explicit_first_fiscal_start(p, command):
    """A new fiscal-year close cannot silently assume January 1.

    The first fiscal start is a company policy choice, often not Gregorian.
    Existing historical close events remain replayable via _project/_run.
    After an initial close, the reducer already derives the next start date
    from closedThrough, and verifies contiguity; leave that behavior intact.
    """
    if (command.get("type") == "fiscal.year.close"
            and not p["fiscalYears"] and "startDate" not in command):
        raise ValueError("Explicit startDate is required for the first fiscal-year close")
    if command.get("type") == "fiscal.year.close" and not p["fiscalYears"]:
        starts = {source["fiscalStartDate"] for source in p["openingSources"].values()
                  if source["active"]}
        if starts and command.get("startDate") not in starts:
            raise ValueError("Fiscal startDate disagrees with posted opening balances")


def _partial_return(p, command, now, *, sales):
    """Post a linked, quantity-exact credit note; retain the original invoice."""
    doc_key = "invoiceId" if sales else "billId"
    collection = p["invoices" if sales else "bills"]
    document = collection.get(_id(command[doc_key], doc_key))
    return_id = _id(command["returnId"], "returnId")
    if return_id in p["returns"]:
        raise ValueError("Return reference already exists")
    if document is None or document["status"] != "issued":
        raise ValueError("Partial return requires an issued document")
    if document.get("contractorJobIds"):
        raise ValueError("Linked contractor purchases cannot be returned directly")
    reason = _text(command["reason"], "return reason", limit=1000)
    day = _posting_date(p, command["postingDate"], now)
    if day < document["postingDate"]:
        raise ValueError("Credit note cannot precede original posting date")
    raw_lines = command["lines"]
    if type(raw_lines) is not list or not 1 <= len(raw_lines) <= len(document["lines"]):
        raise ValueError("Partial return requires selected document lines")
    if not document["subtotal"]:
        raise ValueError("Partial return requires a positive original subtotal")
    # The inventory module can reverse only whole FIFO movements. Returning a
    # fraction of an active movement would silently falsify layers and COGS.
    if any(row.get(doc_key) == document["id"] and not row.get("reversed")
           for row in p["stockMovements"].values()):
        raise ValueError("Reverse linked inventory movements before a partial return")
    direction = "receipt" if sales else "payment"
    if any(ch["documentId"] == document["id"] and ch["direction"] == direction
           and ch["status"] not in ("cancelled", "reversed", "cleared")
           for ch in p["cheques"].values()):
        raise ValueError("Cancel active linked cheques before partial return")
    if any(plan["documentId"] == document["id"] and plan["direction"] == direction
           and plan["active"] for plan in p["installmentPlans"].values()):
        raise ValueError("Cancel active instalment plan before partial return")

    original_lines = document["lines"]
    quantities = list(document.get("returnedQuantities", [0] * len(original_lines)))
    requested = set()
    accepted = []
    for raw in raw_lines:
        _object(raw, ("lineIndex", "quantity"))
        index = _int(raw["lineIndex"], "lineIndex", cap=len(original_lines) - 1)
        quantity = _int(raw["quantity"], "returned quantity", positive=True,
                        cap=1000000)
        if index in requested:
            raise ValueError("Duplicate return lineIndex")
        requested.add(index)
        source = original_lines[index]
        if quantities[index] + quantity > source["quantity"]:
            raise ValueError("Returned quantity exceeds remaining document line")
        quantities[index] += quantity
        accepted.append({"lineIndex": index, "quantity": quantity,
                         "unitPrice": source["unitPrice"],
                         "amount": source["unitPrice"] * quantity,
                         **({"itemId": source["itemId"]} if "itemId" in source else {})})

    old_gross = sum(line["unitPrice"] * qty for line, qty in zip(
        original_lines, document.get("returnedQuantities", [0] * len(original_lines))))
    new_gross = sum(line["unitPrice"] * qty for line, qty in zip(original_lines, quantities))
    if (not sales and document.get("receiptDiscountAllocation") is not None
            and document["tax"] and
            any(q != row["quantity"] for q, row in zip(quantities, original_lines))):
        # The bill stores document-level tax only. Guessing per-line VAT on a
        # partial vendor credit can misstate 5200; a complete return reverses
        # the original posted tax exactly.
        raise ValueError("Taxed per-line purchase partial return requires source-approved tax allocation")
    # Stock receipts with a recorded per-line allocation cannot use
    # the original invoice-wide gross proration for a later credit note.
    # Reversing stock before the return keeps inventory and this GL correction
    # independent, and cumulative integer shares avoid double rounding.
    line_policy = document.get("receiptDiscountAllocation") if not sales else None
    if line_policy is not None:
        before_quantities = document.get("returnedQuantities", [0] * len(original_lines))
        previous_discount = sum(_rounded_share(share, q, row["quantity"])
                                for share, q, row in zip(line_policy["lineDiscounts"],
                                                         before_quantities, original_lines))
        total_discount_returned = sum(_rounded_share(share, q, row["quantity"])
                                      for share, q, row in zip(line_policy["lineDiscounts"],
                                                               quantities, original_lines))
    else:
        previous_discount = _rounded_share(document["discount"], old_gross, document["subtotal"])
        total_discount_returned = _rounded_share(document["discount"], new_gross, document["subtotal"])
    previous_tax = _rounded_share(document["tax"], old_gross, document["subtotal"])
    gross = new_gross - old_gross
    discount = total_discount_returned - previous_discount
    tax = _rounded_share(document["tax"], new_gross, document["subtotal"]) - previous_tax
    amount = gross - discount + tax
    if amount <= 0:
        raise ValueError("Partial credit note must have a positive financial amount")
    amount = _int(amount, "credit note amount", positive=True)
    if amount > _outstanding(document):
        raise ValueError("Return exceeds unpaid amount; reverse settlement or arrange refund first")

    rows = []
    for row in accepted:
        source = original_lines[row["lineIndex"]]
        if row["amount"]:
            rows.append(_line(source["accountId"], debit=row["amount"] if sales else 0,
                              credit=0 if sales else row["amount"]))
    if discount:
        rows.append(_line("4100" if sales else "5100", debit=0 if sales else discount,
                          credit=discount if sales else 0))
    if tax:
        rows.append(_line("2200" if sales else "5200", debit=tax if sales else 0,
                          credit=0 if sales else tax))
    rows.append(_line("1200" if sales else "2000", debit=0 if sales else amount,
                      credit=amount if sales else 0, party_id=document["partyId"]))
    journal = _post(p, command["eventId"], command["type"], return_id, day, rows)
    document["returnedQuantities"] = quantities
    document["returnedAmount"] = _add(document.get("returnedAmount", 0), amount)
    document.setdefault("returnIds", []).append(return_id)
    note = {"id": return_id, "documentId": document["id"],
            "direction": "sale" if sales else "purchase", "partyId": document["partyId"],
            "amount": amount, "subtotal": gross, "discount": discount, "tax": tax,
            "lines": accepted, "postingDate": day, "reason": reason,
            "journalId": journal["id"], "eventId": command["eventId"],
            "kind": "partial", "status": "posted"}
    p["returns"][return_id] = note
    return {"returnId": return_id, "creditNoteId": return_id,
            "documentId": document["id"], "status": "posted", "amount": amount,
            "subtotal": gross, "discount": discount, "tax": tax,
            "journalId": journal["id"]}


def _run(p, command, role, now, *, finance_edit=False):
    if type(command) is not dict or not {"type", "eventId"} <= set(command):
        raise ValueError("Command requires type and eventId")
    kind = _text(command["type"], "command type", limit=50)
    event_id = _id(command["eventId"], "eventId")
    _require(role, kind, finance_edit=finance_edit)
    if kind == "opening.balance.post":
        return _opening_batch(p, command, now)
    if kind in ("proforma.create", "proforma.update"):
        return _proforma_create(p, command, update=kind == "proforma.update")
    if kind in ("proforma.send", "proforma.accept", "proforma.reject",
                "proforma.cancel", "proforma.convert"):
        return _proforma_transition(p, command, now)
    if kind == "contractor.job.intake":
        return _contractor_job(p, command)
    if kind == "contractor.job.price":
        return _contractor_price(p, command)
    if kind == "contractor.job.approve":
        return _contractor_approve(p, command)
    if kind == "contractor.bill.create":
        return _contractor_bill(p, command)
    if kind == "account.create":
        _object(command, ("type", "eventId", "accountId", "name", "kind", "liquid"),
                ("level", "parentId"))
        account_id = _id(command["accountId"], "accountId")
        if account_id in p["accounts"] or command["kind"] not in _KIND or type(command["liquid"]) is not bool:
            raise ValueError("Invalid or duplicate account")
        if command["liquid"] and command["kind"] != "asset":
            raise ValueError("Only asset accounts can hold liquid funds")
        level = command.get("level", "kol")
        if level not in ("kol", "moein", "tafsili"):
            raise ValueError("Invalid chart account level")
        parent_id = command.get("parentId")
        if level == "kol":
            if parent_id is not None:
                raise ValueError("Kol account cannot have a parent")
        else:
            parent = p["accounts"].get(_id(parent_id, "parentId"))
            expected_level = "kol" if level == "moein" else "moein"
            if (parent is None or parent.get("level", "kol") != expected_level
                    or parent["kind"] != command["kind"]):
                raise ValueError("Invalid parent for hierarchical account")
            if command["liquid"]:
                raise ValueError("Hierarchical posting account must not be liquid")
        p["accounts"][account_id] = {"id": account_id,
                                      "name": _text(command["name"], "account name"),
                                      "kind": command["kind"], "liquid": command["liquid"],
                                      "system": False, "level": level,
                                      "parentId": parent_id}
        return {"accountId": account_id}
    if kind == "company.profile.set":
        _object(command, ("type", "eventId", "legalName", "address", "phone",
                          "nationalId", "economicCode", "postalCode", "reason"),
                ("postingUtcOffsetMinutes",))
        reason = _text(command["reason"], "company edit reason", limit=1000)
        details = {"legalName": _text(command["legalName"], "legal name", limit=300)}
        for field, cap in (("address", 1000), ("phone", 40),
                           ("nationalId", 40), ("economicCode", 60),
                           ("postalCode", 32)):
            val = command[field]
            if type(val) is not str or len(val)>cap or any(ord(ch)<32 or ord(ch)==127 for ch in val):
                raise ValueError("Invalid company profile " + field)
            details[field] = val.strip()
        offset = command.get("postingUtcOffsetMinutes", (p["companyProfile"] or {}).get(
            "postingUtcOffsetMinutes"))
        if offset is not None and (type(offset) is not int or not -720 <= offset <= 840):
            raise ValueError("Company posting UTC offset must be integer minutes within -720..840")
        details["postingUtcOffsetMinutes"] = offset
        history = deepcopy(p["companyProfile"].get("history", [])) if p["companyProfile"] else []
        if p["companyProfile"] and all(p["companyProfile"].get(k) == details[k]
                                       for k in details):
            raise ValueError("Company profile update makes no changes")
        history.append({"eventId": event_id, "at": now, "reason": reason})
        p["companyProfile"] = {**details, "history": history}
        return {"legalName": details["legalName"], "updated": True}
    if kind == "party.register":
        _object(command, ("type", "eventId", "partyId", "name", "kind"),
                ("creditLimit",))
        party_id = _id(command["partyId"], "partyId")
        if party_id in p["parties"] or command["kind"] not in ("customer", "vendor", "both"):
            raise ValueError("Invalid or duplicate party")
        limit = command.get("creditLimit")
        if limit is not None:
            limit = _int(limit, "credit limit")
        p["parties"][party_id] = {"id": party_id,
                                  "name": _text(command["name"], "party name"),
                                  "kind": command["kind"],
                                  "creditLimit": limit}
        return {"partyId": party_id}
    if kind == "party.update":
        _object(command, ("type", "eventId", "partyId"),
                ("name", "kind", "creditLimit", "reason"))
        ident = _id(command["partyId"], "partyId")
        party = p["parties"].get(ident)
        if party is None or set(command) == {"type", "eventId", "partyId"}:
            raise ValueError("Unknown party or empty update")
        reason = _text(command.get("reason"), "party edit reason", limit=1000)
        before = {key: party.get(key) for key in ("name", "kind", "creditLimit")}
        if "kind" in command:
            role = command["kind"]
            if role not in ("customer", "vendor", "both"):
                raise ValueError("Invalid party role")
            if role not in ("customer", "both") and any(
                    d["partyId"] == ident for d in p["invoices"].values()):
                raise ValueError("Cannot remove customer role with invoice history")
            if role not in ("customer", "both") and any(
                    d["partyId"] == ident and d["direction"] == "receivable"
                    for d in p["openingBalances"].values()):
                raise ValueError("Cannot remove customer role with opening history")
            if role not in ("vendor", "both") and any(
                    d["partyId"] == ident for d in p["bills"].values()):
                raise ValueError("Cannot remove vendor role with purchase history")
            if role not in ("vendor", "both") and any(
                    d["partyId"] == ident and d["direction"] == "payable"
                    for d in p["openingBalances"].values()):
                raise ValueError("Cannot remove vendor role with opening history")
            party["kind"] = role
        if "name" in command:
            party["name"] = _text(command["name"], "party name")
        if "creditLimit" in command:
            limit = command["creditLimit"]
            if limit is not None:
                limit = _int(limit, "credit limit")
                outstanding = sum(_outstanding(d) for d in p["invoices"].values()
                                  if d["status"] == "issued" and d["partyId"] == ident)
                outstanding += sum(_outstanding(d) for d in p["openingBalances"].values()
                                   if d["active"] and d["direction"] == "receivable"
                                   and d["partyId"] == ident)
                if outstanding > limit:
                    raise ValueError("Credit limit below current receivable")
            party["creditLimit"] = limit
        after = {key: party.get(key) for key in ("name", "kind", "creditLimit")}
        if before == after:
            raise ValueError("Party update makes no changes")
        history = party.setdefault("changeHistory", [])
        history.append({"eventId": command["eventId"], "at": now,
                        "reason": reason, "before": before, "after": after})
        return {"partyId": ident, "updated": True}
    if kind == "item.create":
        _object(command, ("type", "eventId", "itemId", "sku", "name", "kind", "unit"))
        item_id = _id(command["itemId"], "itemId")
        sku = _text(command["sku"], "item SKU", limit=64)
        if (item_id in p["items"] or command["kind"] not in ("goods", "service")
                or any(item["sku"].casefold() == sku.casefold() for item in p["items"].values())):
            raise ValueError("Invalid item kind, ID or duplicate SKU")
        p["items"][item_id] = {"id": item_id, "sku": sku,
                                "name": _text(command["name"], "item name"),
                                "kind": command["kind"],
                                "unit": _text(command["unit"], "item unit", limit=40),
                                "active": True, "stockTracked": False}
        return {"itemId": item_id}
    if kind == "item.update":
        _object(command, ("type", "eventId", "itemId"), ("name", "unit", "active"))
        item_id = _id(command["itemId"], "itemId")
        item = p["items"].get(item_id)
        if item is None or set(command) == {"type", "eventId", "itemId"}:
            raise ValueError("Missing item or empty update")
        if "name" in command:
            item["name"] = _text(command["name"], "item name")
        if "unit" in command:
            item["unit"] = _text(command["unit"], "item unit", limit=40)
        if "active" in command:
            if type(command["active"]) is not bool:
                raise ValueError("Invalid item active flag")
            item["active"] = command["active"]
        return {"itemId": item_id, "active": item["active"]}
    if kind in {"invoice.create", "bill.create"}:
        return _make_document(p, command, sales=kind == "invoice.create")
    if kind in {"invoice.return", "bill.return"}:
        sales = kind == "invoice.return"
        doc_key = "invoiceId" if sales else "billId"
        _object(command, ("type", "eventId", doc_key, "returnId",
                          "postingDate", "reason"), ("lines",))
        if "lines" in command:
            return _partial_return(p, command, now, sales=sales)
        document = p["invoices" if sales else "bills"].get(
            _id(command[doc_key], doc_key))
        return_id = _id(command["returnId"], "returnId")
        if return_id in p["returns"]:
            raise ValueError("Return reference already exists")
        if (document is None or document["status"] != "issued" or
                document["allocated"] or document.get("returnedAmount", 0)):
            raise ValueError("Full return requires an issued entirely unsettled document")
        if document.get("contractorJobIds"):
            raise ValueError("Linked contractor purchases cannot be returned directly")
        reason = _text(command["reason"], "return reason", limit=1000)
        day = _posting_date(p, command["postingDate"], now)
        reversed_posting = _reverse(p, {
            "type": "journal.reverse", "eventId": command["eventId"],
            "journalId": document["postedEntryId"],
            "postingDate": day, "reason": reason,
        }, now)
        document["returnId"] = return_id
        document["returnReason"] = reason
        p["returns"][return_id] = {
            "id": return_id, "documentId": document["id"],
            "direction": "sale" if sales else "purchase",
            "partyId": document["partyId"], "amount": document["total"],
            "postingDate": day, "reason": reason,
            "reversalJournalId": reversed_posting["journalId"],
            "eventId": command["eventId"],
        }
        return {"returnId": return_id, "documentId": document["id"],
                "status": "reversed",
                "journalId": reversed_posting["journalId"]}
    if kind in {"invoice.correct", "bill.correct"}:
        sales = kind == "invoice.correct"
        old_key = "invoiceId" if sales else "billId"
        _object(command, ("type", "eventId", old_key, "replacementId",
                          "postingDate", "documentDate", "reason", "lines"),
                ("discount", "tax", "note", "taxRuleId", "dueDate"))
        old_id = _id(command[old_key], old_key)
        replacement_id = _id(command["replacementId"], "replacementId")
        collection = p["invoices" if sales else "bills"]
        old = collection.get(old_id)
        if (old is None or old["status"] != "issued" or old["allocated"] != 0 or
                old.get("returnedAmount", 0)):
            raise ValueError("Only issued, wholly unsettled documents can be corrected")
        if old.get("contractorJobIds"):
            raise ValueError("Contractor-linked purchase corrections require separate validation")
        if replacement_id == old_id or replacement_id in collection:
            raise ValueError("Replacement document ID already exists")
        reason = _text(command["reason"], "correction reason", limit=1000)
        replacement_day = _date(command["documentDate"])
        reversal_day = _date(command["postingDate"])
        if replacement_day < old["documentDate"] or replacement_day > now[:10]:
            raise ValueError("Replacement date must be between original date and today")
        if replacement_day > reversal_day:
            raise ValueError("Replacement draft cannot postdate correction")
        # Both the reversing journal and replacement draft are created in the
        # same ephemeral projection; the host commits just one CAS event.
        reversal = _reverse(p, {
            "type": "journal.reverse", "eventId": command["eventId"],
            "journalId": old["postedEntryId"], "postingDate": reversal_day,
            "reason": reason,
        }, now)
        replacement = {
            "type": ("invoice.create" if sales else "bill.create"),
            "eventId": command["eventId"], old_key: replacement_id,
            "partyId": old["partyId"], "documentDate": replacement_day,
            "lines": deepcopy(command["lines"]),
            "sourceType": "correction", "sourceId": old_id,
        }
        for key in ("discount", "tax", "note", "taxRuleId", "dueDate"):
            if key in command:
                replacement[key] = command[key]
        created = _make_document(p, replacement, sales=sales)
        old["correctedBy"] = replacement_id
        old["correctionReason"] = reason
        collection[replacement_id]["correctionOf"] = old_id
        return {"documentId": old_id, "replacementId": replacement_id,
                "reversalJournalId": reversal["journalId"],
                "replacementTotal": created["total"], "status": "reversed"}
    if kind in {"invoice.reopen", "bill.reopen"}:
        key = "invoiceId" if kind == "invoice.reopen" else "billId"
        _object(command, ("type", "eventId", key, "reason"))
        collection = p["invoices" if key == "invoiceId" else "bills"]
        doc = collection.get(_id(command[key], key))
        if (doc is None or doc["status"] != "approved"
                or doc.get("contractorJobIds")):
            raise ValueError("Only approved, unposted ordinary documents may be reopened")
        reason = _text(command["reason"], "reason to reopen", limit=1000)
        doc["status"] = "draft"
        doc["lastReopenReason"] = reason
        doc["reopenCount"] = doc.get("reopenCount", 0) + 1
        return {"documentId": doc["id"], "status": "draft", "reopened": True}
    if kind in {"invoice.update", "bill.update"}:
        key = "invoiceId" if kind == "invoice.update" else "billId"
        _object(command, ("type", "eventId", key, "partyId", "documentDate", "lines"),
                ("discount", "tax", "note"))
        collection = p["invoices" if key == "invoiceId" else "bills"]
        old = collection.get(_id(command[key], key))
        if (old is None or old["status"] != "draft" or old.get("contractorJobIds")):
            raise ValueError("Only ordinary draft documents may be edited")
        source = {k: old[k] for k in ("sourceType", "sourceId")
                  if old[k] is not None}
        if "taxRuleId" not in command and old.get("taxRuleId") is not None:
            source["taxRuleId"] = old["taxRuleId"]
        temp = deepcopy(command)
        temp["type"] = "invoice.create" if key == "invoiceId" else "bill.create"
        temp.update(source)
        del collection[old["id"]]
        # Preserve the original approved quote linkage on edit; the accepted
        # proforma remains immutable and the amended draft is event-audited.
        result = _make_document(p, temp, sales=key == "invoiceId",
                                allow_proforma_source=(old.get("sourceType") == "proforma"))
        # Commercial and audit lineage must survive successive draft edits.
        for audit_field in ("correctionOf", "lastReopenReason", "reopenCount"):
            if audit_field in old:
                collection[old["id"]][audit_field] = deepcopy(old[audit_field])
        result["updated"] = True
        return result
    if kind in {"invoice.approve", "bill.approve"}:
        key = "invoiceId" if kind == "invoice.approve" else "billId"
        _object(command, ("type", "eventId", key))
        doc = p["invoices" if key == "invoiceId" else "bills"].get(_id(command[key], key))
        if doc is None or doc["status"] != "draft":
            raise ValueError("Only drafts can be approved")
        doc["status"] = "approved"
        return {"documentId": doc["id"], "status": "approved"}
    if kind in {"invoice.cancel", "bill.cancel"}:
        key = "invoiceId" if kind == "invoice.cancel" else "billId"
        _object(command, ("type", "eventId", key, "reason"))
        doc = p["invoices" if key == "invoiceId" else "bills"].get(_id(command[key], key))
        if doc is None or doc["status"] not in {"draft", "approved"}:
            raise ValueError("Only unissued documents can be cancelled directly")
        doc["status"] = "cancelled"
        doc["cancelReason"] = _text(command["reason"], "cancellation reason", limit=1000)
        if key == "billId":
            for job_id in doc.get("contractorJobIds", []):
                job = p["contractorJobs"][job_id]
                if job["status"] != "billed" or job["billedBy"] != doc["id"]:
                    raise ValueError("Inconsistent contractor bill linkage")
                job["status"], job["billedBy"] = "approved", None
        return {"documentId": doc["id"], "status": "cancelled"}
    if kind in {"invoice.issue", "bill.issue"}:
        return _issue(p, command, now, sales=kind == "invoice.issue")
    if kind in {"receipt.record", "payment.record"}:
        return _settle(p, command, now, sales=kind == "receipt.record")
    if kind == "funds.deposit":
        _object(command, ("type", "eventId", "accountId", "amount", "postingDate", "note"))
        _account(p, command["accountId"], liquid=True)
        amount = _int(command["amount"], "funding amount", positive=True)
        day = _posting_date(p, command["postingDate"], now)
        _text(command["note"], "funding note", limit=1000)
        journal = _post(p, event_id, kind, event_id, day,
                        [_line(command["accountId"], debit=amount),
                         _line("3000", credit=amount)])
        return {"amount": amount, "journalId": journal["id"]}
    if kind == "funds.transfer":
        _object(command, ("type", "eventId", "fromAccountId", "toAccountId",
                          "amount", "postingDate", "note"))
        from_id, to_id = command["fromAccountId"], command["toAccountId"]
        _account(p, from_id, liquid=True)
        _account(p, to_id, liquid=True)
        if from_id == to_id:
            raise ValueError("Transfer requires different cash/bank accounts")
        amount = _int(command["amount"], "transfer amount", positive=True)
        day = _posting_date(p, command["postingDate"], now)
        _text(command["note"], "transfer note", limit=1000)
        journal = _post(p, event_id, kind, event_id, day,
                        [_line(to_id, debit=amount), _line(from_id, credit=amount)])
        return {"amount": amount, "journalId": journal["id"]}
    if kind == "journal.manual":
        _object(command, ("type", "eventId", "postingDate", "note", "lines"))
        _text(command["note"], "manual entry note", limit=1000)
        day = _posting_date(p, command["postingDate"], now)
        raw_lines = command["lines"]
        if type(raw_lines) is not list or not 2 <= len(raw_lines) <= 100:
            raise ValueError("Manual journal requires 2..100 explicit lines")
        rows = []
        for line in raw_lines:
            _object(line, ("accountId", "debit", "credit"))
            aid = _id(line["accountId"], "accountId")
            if role != "admin" and _account(p, aid)["kind"] == "equity":
                raise PermissionError("Owner equity postings require administrator")
            if aid in ("1200", "2000") or (
                aid in _NEW_SYSTEM_ACCOUNTS and
                    p["accounts"].get(aid, {}).get("system") is True):
                raise ValueError("Manual journal cannot bypass AR/AP, stock or payroll subledger")
            rows.append(_line(aid, debit=line["debit"], credit=line["credit"]))
        journal = _post(p, event_id, kind, event_id, day, rows)
        return {"journalId": journal["id"]}
    if kind == "journal.reverse":
        original_id = command.get("journalId")
        prior = (p["entries"].get(original_id)
                 if type(original_id) is str else None)
        if (role != "admin" and prior is not None and
                (prior["sourceType"] == "funds.deposit" or
                 any(_account(p, row["accountId"])["kind"] == "equity"
                     for row in prior["lines"]))):
            raise PermissionError("Reversing owner equity requires administrator")
        return _reverse(p, command, now)
    if kind.startswith(("cheque.", "bank.statement.", "warehouse.",
                        "inventory.", "item.stock.", "installments.",
                        "payroll.", "fiscal.", "tax.rule.")):
        # The older operational adapter uses face value for eligibility.
        # Keep its historical events replayable while applying credit-note
        # limits at the domain boundary for every new commitment or movement.
        installment_doc = None
        if kind in ("cheque.register", "installments.create"):
            direction = command.get("direction")
            collection = p["invoices"] if direction == "receipt" else p["bills"]
            doc_id = command.get("documentId")
            document = collection.get(doc_id) if type(doc_id) is str else None
            if document is not None and document.get("returnedAmount", 0):
                if kind == "cheque.register":
                    if _int(command.get("amount"), "cheque amount", positive=True) > _outstanding(document):
                        raise ValueError("Cheque exceeds document balance after credit notes")
                else:
                    schedule = command.get("schedule")
                    if (type(schedule) is not list or any(type(row) is not dict for row in schedule)
                            or sum(_int(row.get("amount"), "instalment amount", positive=True)
                                   for row in schedule) != _outstanding(document)):
                        raise ValueError("Instalment schedule must match outstanding credit-note balance")
                    installment_doc = document
        if kind in ("inventory.receive", "inventory.issue"):
            sales = kind == "inventory.issue"
            key = "invoiceId" if sales else "billId"
            doc_id = command.get(key)
            document = (p["invoices" if sales else "bills"].get(doc_id)
                        if type(doc_id) is str else None)
            if document is not None and document.get("returnedAmount", 0):
                item_id = command.get("itemId")
                matches = [i for i, line in enumerate(document["lines"])
                           if line.get("itemId") == item_id]
                if len(matches) == 1:
                    index = matches[0]
                    prior = sum(row["quantity"] for row in p["stockMovements"].values()
                                if row["type"] == kind and not row.get("reversed")
                                and row.get(key) == document["id"] and row["itemId"] == item_id)
                    available = (document["lines"][index]["quantity"] -
                                 document["returnedQuantities"][index])
                    quantity = _int(command.get("quantity"), "inventory quantity", positive=True)
                    if prior + quantity > available:
                        raise ValueError("Inventory movement exceeds unreturned document quantity")
        if (kind == "inventory.receive" and
                command.get("discountAllocation") == "per-line-exact" and role != "admin"):
            raise PermissionError("Exact purchase discount allocation requires administrator")
        if kind == "inventory.reverse" and role != "admin":
            movement_id = command.get("movementId")
            movement = (p["stockMovements"].get(movement_id)
                        if type(movement_id) is str else None)
            if movement is not None and movement["type"] == "inventory.opening":
                raise PermissionError("Reversing owner opening inventory requires administrator")
        from accounting_operational_extensions import apply_extended
        # Compatibility with the extension's face-value-only instalment check:
        # present the remaining value during validation and restore immediately.
        if installment_doc is not None:
            installment_doc["total"] -= installment_doc["returnedAmount"]
        try:
            return apply_extended(p, command, now, helpers={
                "object": _object, "id": _id, "text": _text, "int": _int,
                "date": _date, "posting_date": _posting_date, "account": _account,
                "party": _party, "post": _post, "line": _line,
                "settle": _settle, "add": _add, "max": MAX_TOMAN,
                "posting_today": _posting_today,
            })
        finally:
            if installment_doc is not None:
                installment_doc["total"] += installment_doc["returnedAmount"]
    if kind == "period.close":
        _object(command, ("type", "eventId", "throughDate"))
        day = _date(command["throughDate"])
        if day > _posting_today(p, now) or (p["closedThrough"] is not None and day <= p["closedThrough"]):
            raise ValueError("Invalid period close boundary")
        from accounting_operational_extensions import pending_goods_issues
        pending = pending_goods_issues(p, through_date=day)
        if pending:
            first_issue = pending[0]
            raise ValueError("Period close requires inventory.issue/COGS for invoice " +
                             first_issue["invoiceId"] + " item " + first_issue["itemId"])
        p["closedThrough"] = day
        return {"closedThrough": day}
    raise ValueError("Unknown accounting command")


def _project(state):
    _object(state, ("schemaVersion", "currency", "events"))
    if (type(state["schemaVersion"]) is not int or
            (state["schemaVersion"], state["currency"]) not in
            ((SCHEMA_VERSION, "TOMAN"), (RIAL_SCHEMA_VERSION, "RIAL")) or
            type(state["events"]) is not list):
        raise ValueError("Unsupported accounting state schema")
    # Never reinterpret a previously user-created ledger account as a newly
    # introduced system account. The old event chain must remain replayable.
    legacy_ids = frozenset(
        ev["command"].get("accountId") for ev in state["events"]
        if type(ev) is dict and type(ev.get("command")) is dict and
        ev["command"].get("type") == "account.create" and
        type(ev["command"].get("accountId")) is str)
    p = _new_projection(state["currency"],
                        preserve_historical_custom_ids=legacy_ids)
    prev = "0" * 64
    seen = set()
    for event in state["events"]:
        _object(event, ("eventId", "actor", "role", "financeEdit", "at", "command",
                        "fingerprint", "result", "previousHash", "hash"))
        event_id = _id(event["eventId"], "eventId")
        _id(event["actor"], "actor")
        if (event_id in seen or event["role"] not in ("admin", "editor") or
                type(event["financeEdit"]) is not bool or event["previousHash"] != prev or
                type(event["fingerprint"]) is not str or not _DIGEST.fullmatch(event["fingerprint"])):
            raise ValueError("Invalid event chain")
        seen.add(event_id)
        now = _time(event["at"])
        if type(event["command"]) is not dict or event["command"].get("eventId") != event_id:
            raise ValueError("Event/command mismatch")
        if event["fingerprint"] != _hash({"actor": event["actor"], "command": event["command"]}):
            raise ValueError("Event fingerprint mismatch")
        expected = _hash({k: v for k, v in event.items() if k != "hash"})
        if event["hash"] != expected:
            raise ValueError("Event hash mismatch")
        result = _run(p, event["command"], event["role"], now,
                      finance_edit=event["financeEdit"])
        if result != event["result"]:
            raise ValueError("Event result mismatch")
        prev = event["hash"]
    _check_party_balances(p)
    _check_operational_balances(p)
    return p


def _check_party_balances(p):
    """Cross-check AR/AP subledgers against the general ledger by named party."""
    for account_id, collection, first in (("1200", "invoices", "debit"),
                                          ("2000", "bills", "credit")):
        expected = {}
        for doc in p[collection].values():
            if doc["status"] == "issued":
                expected[doc["partyId"]] = expected.get(doc["partyId"], 0) + (
                    _outstanding(doc))
        direction = "receivable" if account_id == "1200" else "payable"
        for item in p["openingBalances"].values():
            if item["active"] and item["direction"] == direction:
                expected[item["partyId"]] = expected.get(item["partyId"], 0) + (
                    _outstanding(item))
        actual = {}
        for journal in p["journals"]:
            for line in journal["lines"]:
                if line["accountId"] == account_id:
                    if "partyId" not in line:
                        raise ValueError("AR/AP journal without explicit party")
                    sign = 1 if first == "debit" else -1
                    actual[line["partyId"]] = actual.get(line["partyId"], 0) + sign * (
                        line["debit"] - line["credit"])
        if any(amount < 0 or amount > MAX_TOMAN for amount in expected.values()):
            raise ValueError("Invalid party outstanding amount")
        if {key: val for key, val in expected.items() if val} != {
                key: val for key, val in actual.items() if val}:
            raise ValueError("General ledger and party subledger disagree")


def _check_operational_balances(p):
    """Never trust a detached inventory, cheque or bank projection over GL."""
    if p["stockMovements"]:
        total_stock_value = 0
        for warehouse_id, items in p["stock"].items():
            if warehouse_id not in p["warehouses"]:
                raise ValueError("Unknown stock warehouse")
            for item_id, bucket in items.items():
                if item_id not in p["items"] or not p["items"][item_id]["stockTracked"]:
                    raise ValueError("Inventory lacks a tracked item")
                if (type(bucket["quantity"]) is not int or
                        type(bucket["value"]) is not int or
                        bucket["quantity"] < 0 or bucket["value"] < 0 or
                        sum(row["quantity"] for row in bucket["layers"]) != bucket["quantity"] or
                        sum(row["quantity"] * row["unitCost"] for row in bucket["layers"]) != bucket["value"]):
                    raise ValueError("Warehouse layers do not reconcile")
                total_stock_value += bucket["value"]
        if total_stock_value != p["balances"].get("1300", 0):
            raise ValueError("Inventory subledger does not reconcile with the general ledger")
    for ch in p["cheques"].values():
        if ch["status"] == "cleared":
            if (ch["journalId"] is None or ch["journalId"] in p["reversed"]
                    or ch["journalId"] not in p["entries"]):
                raise ValueError("Cleared cheque lacks active bank settlement")
        if ch["status"] == "reversed" and (
                ch["journalId"] is None or ch["journalId"] not in p["reversed"]):
            raise ValueError("Reversed cheque must have a reversed settlement journal")
    linked = set()
    for row in p["bankStatements"].values():
        if row["journalId"] is None:
            continue
        entry = p["entries"].get(row["journalId"])
        key = (row["accountId"], row["journalId"])
        if (key in linked or entry is None or
                entry["id"] in p["reversed"] or entry["reversalOf"] is not None or
                sum(x["debit"] - x["credit"] for x in entry["lines"]
                    if x["accountId"] == row["accountId"]) != row["amount"]):
            raise ValueError("Bank statement and matched journal no longer reconcile")
        linked.add(key)
    if p["payroll"]:
        due = sum(r["net"] for r in p["payroll"].values()
                  if r["status"] == "accrued")
        held = sum(r["withholding"] for r in p["payroll"].values()
                   if not r["remittanceJournalId"])
        if (p["balances"].get("2300", 0) != -due or
                p["balances"].get("2400", 0) != -held):
            raise ValueError("Payroll liabilities and subledger do not reconcile")


def validate_accounting_state(state):
    """Replay every event, verify hash chain, postings, roles, and subledgers."""
    _project(state)
    return True


def apply_accounting_command(state, command, *, actor, accounts, now):
    """Return {state,changed,result}; input snapshots are never modified.

    `accounts` and `actor` MUST come from a trusted authenticated host. Commit
    all events within one host transaction using a version/CAS check.
    """
    account = _actor_role(actor, accounts)
    timestamp = _time(now)
    if type(command) is not dict or not {"type", "eventId"} <= set(command):
        raise ValueError("Command requires type and eventId")
    event_id = _id(command["eventId"], "eventId")
    role = account["role"]
    finance_edit = account.get("financeEdit") is True
    _require(role, command["type"], finance_edit=finance_edit)
    fingerprint = _hash({"actor": actor, "command": command})
    p = _project(state)
    for event in state["events"]:
        if event["eventId"] == event_id:
            if fingerprint != event["fingerprint"]:
                raise ValueError("Event ID reused with different actor or payload")
            return {"state": deepcopy(state), "changed": False,
                    "result": deepcopy(event["result"])}
    _guard_active_installments_on_new_reversal(p, command)
    _guard_explicit_first_fiscal_start(p, command)
    result = _run(p, command, role, timestamp, finance_edit=finance_edit)
    _check_party_balances(p)
    _check_operational_balances(p)
    last_hash = state["events"][-1]["hash"] if state["events"] else "0" * 64
    event = {"eventId": event_id, "actor": actor, "role": role,
             "financeEdit": finance_edit, "at": timestamp, "command": deepcopy(command),
             "fingerprint": fingerprint, "result": deepcopy(result), "previousHash": last_hash}
    event["hash"] = _hash(event)
    new_state = deepcopy(state)
    new_state["events"].append(event)
    return {"state": new_state, "changed": True, "result": deepcopy(result)}


def accounting_view(state, *, actor, accounts):
    """Materialized, independent JSON view. Restrict access in the host too."""
    account = _actor_role(actor, accounts)
    _require_view(account)
    p = _project(state)
    balance_rows = {}
    for account_id, record in p["accounts"].items():
        signed = p["balances"].get(account_id, 0)
        normal = -signed if record["kind"] in _CREDIT_NORMAL else signed
        balance_rows[account_id] = {**deepcopy(record), "debitMinusCredit": signed,
                                    "normalBalance": normal}
    parties = {}
    for party_id, item in p["parties"].items():
        customer = sum(_outstanding(d) for d in p["invoices"].values()
                       if d["partyId"] == party_id and d["status"] == "issued")
        vendor = sum(_outstanding(d) for d in p["bills"].values()
                     if d["partyId"] == party_id and d["status"] == "issued")
        customer += sum(_outstanding(o) for o in p["openingBalances"].values()
                        if o["active"] and o["partyId"] == party_id
                        and o["direction"] == "receivable")
        vendor += sum(_outstanding(o) for o in p["openingBalances"].values()
                      if o["active"] and o["partyId"] == party_id
                      and o["direction"] == "payable")
        party_view = {**deepcopy(item), "receivable": customer, "payable": vendor,
                      "netReceivable": customer - vendor}
        # The native party is linked to the actual imported tafsili GL account.
        # Historical balances must not be re-issued as new invoices.
        prefix = "ps.parsian.1405.party."
        if party_id.startswith(prefix):
            code = party_id[len(prefix):]
            if re.fullmatch(r"12\.2\.[0-9]+", code):
                gl_id = "ps.parsian.account.t." + code
                historical = balance_rows.get(gl_id, {}).get("debitMinusCredit", 0)
                party_view.update({
                    "sourceLedgerAccountId": gl_id,
                    "historicalBalanceRial": historical,
                    "historicalReceivableRial": max(0, historical),
                    "historicalPayableRial": max(0, -historical),
                })
        parties[party_id] = party_view
    return deepcopy({"currency": p["currency"], "accounts": balance_rows,
                     "items": p["items"],
                     "parties": parties, "proformas": p["proformas"],
                     "invoices": p["invoices"], "bills": p["bills"],
                     "openingBalances": p["openingBalances"],
                     "openingSources": p["openingSources"],
                     "contractorJobs": p["contractorJobs"],
                     "receipts": p["receipts"], "payments": p["payments"],
                     "returns": p["returns"],
                     "journals": p["journals"], "reversed": p["reversed"],
                     "sequence": p["sequence"], "closedThrough": p["closedThrough"],
                     "cheques": p["cheques"], "bankStatements": p["bankStatements"],
                     "warehouses": p["warehouses"], "stock": p["stock"],
                     "stockMovements": p["stockMovements"],
                     "installmentPlans": p["installmentPlans"],
                     "payroll": p["payroll"], "fiscalYears": p["fiscalYears"],
                     "taxRules": p["taxRules"], "companyProfile": p["companyProfile"]})
