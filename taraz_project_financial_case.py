"""Pure, non-posting project-finance preview contract for Madar task snapshots.

This is NOT a trusted transport, an accounting command, or a verified source
signature. A future authenticated Taraz host must independently attest the
Madar origin, actor/project grants, counterparty IDs, source CAS and receipt
before it can save a real draft. Unknown amounts always remain None.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re


class FinancialCaseError(ValueError):
    pass


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z", re.ASCII)
_HEX = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_STAGES = {"external_service", "internal_work", "additional_expense"}
_CURRENCIES = {"RIAL": 1, "TOMAN": 10}
_MAX_RIAL = 10**15


def _id(value, name):
    if type(value) is not str or not _ID.fullmatch(value):
        raise FinancialCaseError("Invalid " + name)
    return value


def _text(value, name, limit=300):
    if (type(value) is not str or not value.strip() or len(value) > limit or
            any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise FinancialCaseError("Invalid " + name)
    return value.strip()


def _amount_rial(value, label):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {"amount", "currency"}:
        raise FinancialCaseError("Explicit amount and currency required: " + label)
    amount = value["amount"]
    currency = value["currency"]
    factor = _CURRENCIES.get(currency) if type(currency) is str else None
    if (type(amount) is not int or amount < 0 or factor is None or
            amount * factor > _MAX_RIAL):
        raise FinancialCaseError("Invalid amount or currency: " + label)
    return amount * factor


def _quantity(value, label):
    if type(value) is not int or not 1 <= value <= 10_000_000:
        raise FinancialCaseError("Invalid quantity: " + label)
    return value


def _optional_id(value, name):
    return None if value is None else _id(value, name)


def _date(value):
    if value is None:
        return None
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise FinancialCaseError("Invalid payment date")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise FinancialCaseError("Invalid payment date") from exc
    return value


def _stage(value):
    if type(value) is not dict or set(value) != {
        "id", "operation", "description", "supplierId", "items",
        "internalCost", "expense", "payment"
    }:
        raise FinancialCaseError("Unexpected stage fields")
    ident = _id(value["id"], "stageId")
    operation = value["operation"]
    if type(operation) is not str or operation not in _STAGES:
        raise FinancialCaseError("Unsupported project activity")
    description = _text(value["description"], "stage description")
    supplier = _optional_id(value["supplierId"], "supplierId")
    items = value["items"]
    if type(items) is not list or len(items) > 100:
        raise FinancialCaseError("Invalid purchase line list")
    entries = []
    for line in items:
        if type(line) is not dict or set(line) != {
            "description", "quantity", "unit", "unitPrice"
        }:
            raise FinancialCaseError("Unexpected purchase line fields")
        q = _quantity(line["quantity"], "purchase quantity")
        price = _amount_rial(line["unitPrice"], "unitPrice")
        entries.append({
            "description": _text(line["description"], "line description"),
            "quantity": q, "unit": _text(line["unit"], "unit", 40),
            "unitPriceRial": price,
            "subtotalRial": None if price is None else q * price,
        })
        if entries[-1]["subtotalRial"] is not None and entries[-1]["subtotalRial"] > _MAX_RIAL:
            raise FinancialCaseError("Purchase subtotal exceeds safe limit")
    internal = _amount_rial(value["internalCost"], "internalCost")
    expense = _amount_rial(value["expense"], "expense")
    payment = value["payment"]
    if operation == "external_service":
        if not entries or internal is not None or expense is not None:
            raise FinancialCaseError("External service requires purchase lines only")
        if payment is not None:
            if type(payment) is not dict or set(payment) != {
                "method", "accountId", "date", "receipt", "confirmed"
            } or type(payment["method"]) is not str or payment["method"] not in (
                "card", "cash", "bank_transfer") or (
                type(payment["confirmed"]) is not bool):
                raise FinancialCaseError("Invalid payment proposal")
            if payment["confirmed"]:
                raise FinancialCaseError("Task text cannot certify a bank payment")
            payment = {
                "method": payment["method"],
                "accountId": _optional_id(payment["accountId"], "paying account"),
                "date": _date(payment["date"]),
                "receipt": (None if payment["receipt"] is None else
                            _text(payment["receipt"], "receipt", 100)),
                "status": "unverified",
            }
    elif operation == "internal_work":
        if entries or supplier is not None or expense is not None or payment is not None:
            raise FinancialCaseError("Internal work cannot make external vendor expense")
    else:
        if entries or supplier is not None or internal is not None or payment is not None:
            raise FinancialCaseError("Additional expense is not a purchase invoice")
    return {
        "id": ident, "operation": operation, "description": description,
        "supplierId": supplier, "items": entries,
        "internalCostRial": internal, "expenseRial": expense, "payment": payment,
    }


def build_financial_case(snapshot: dict, *, expected_revision: int):
    """Construct review-only proposals from a revision-pinned saved task.

    Neither the task's actor nor its party IDs are authentication evidence.
    Callers MUST NOT convert these proposals into official ledger commands
    without a separate authenticated Taraz finance authorization.
    """
    required = {
        "schemaVersion", "eventId", "idempotencyKey", "taskId", "projectId",
        "sourceRevision", "sourceActorId", "sourceTimestamp", "title",
        "customerId", "quantity", "unit", "saleUnitPrice",
        "invoiceProfileId", "stages"
    }
    if type(snapshot) is not dict or set(snapshot) != required or (
        type(snapshot["schemaVersion"]) is not int or snapshot["schemaVersion"] != 2):
        raise FinancialCaseError("Unsupported verified task snapshot schema")
    for field in ("eventId", "idempotencyKey"):
        if type(snapshot[field]) is not str or not _HEX.fullmatch(snapshot[field]):
            raise FinancialCaseError("Invalid idempotent event identity")
    if (type(expected_revision) is not int or expected_revision < 1 or
            type(snapshot["sourceRevision"]) is not int or
            snapshot["sourceRevision"] != expected_revision):
        raise FinancialCaseError("Stale source task revision")
    for field in ("taskId", "projectId", "sourceActorId"):
        _id(snapshot[field], field)
    timestamp = snapshot["sourceTimestamp"]
    try:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinancialCaseError("Valid source-declared timestamp required") from exc
    title = _text(snapshot["title"], "project title")
    customer = _optional_id(snapshot["customerId"], "customerId")
    quantity = _quantity(snapshot["quantity"], "sales quantity")
    unit = _text(snapshot["unit"], "sales unit", 40)
    sale = _amount_rial(snapshot["saleUnitPrice"], "saleUnitPrice")
    if sale is not None and sale * quantity > _MAX_RIAL:
        raise FinancialCaseError("Sales amount exceeds supported accounting range")
    issuer = _optional_id(snapshot["invoiceProfileId"], "invoiceProfileId")
    stages = snapshot["stages"]
    if type(stages) is not list or not 1 <= len(stages) <= 64:
        raise FinancialCaseError("Project activities required")
    parsed = [_stage(step) for step in stages]
    ids = [step["id"] for step in parsed]
    if len(ids) != len(set(ids)):
        raise FinancialCaseError("Repeated stage identity")
    sales = {
        "type": "sales_draft_proposal", "projectId": snapshot["projectId"],
        "customerId": customer, "invoiceProfileId": issuer,
        "line": {"description": title, "quantity": quantity, "unit": unit,
                 "unitPriceRial": sale,
                 "subtotalRial": None if sale is None else sale * quantity},
        "status": "review_only",
    }
    purchases, payments, internal, extras, missing = [], [], [], [], []
    known_expenses = 0
    if customer is None:
        missing.append("customerId")
    if sale is None:
        missing.append("saleUnitPrice")
    for step in parsed:
        if step["operation"] == "external_service":
            total = (sum(line["subtotalRial"] for line in step["items"])
                     if all(line["subtotalRial"] is not None for line in step["items"])
                     else None)
            purchase = {"stageId": step["id"], "supplierId": step["supplierId"],
                        "description": step["description"], "lines": step["items"],
                        "totalRial": total, "status": "review_only"}
            purchases.append(purchase)
            if total is not None:
                known_expenses += total
            else:
                missing.append("purchasePrice:" + step["id"])
            if step["supplierId"] is None:
                missing.append("supplierId:" + step["id"])
            if step["payment"] is not None:
                payments.append({
                    "stageId": step["id"], "supplierId": step["supplierId"],
                    "amountRial": total, "linkedExpenseStageId": step["id"],
                    **step["payment"],
                })
                if step["payment"]["accountId"] is None:
                    missing.append("paymentAccount:" + step["id"])
                if step["payment"]["date"] is None:
                    missing.append("paymentDate:" + step["id"])
                # Payments settle debt; NEVER add them a second time to costs.
        elif step["operation"] == "internal_work":
            internal.append({"stageId": step["id"],
                             "description": step["description"],
                             "internalCostRial": step["internalCostRial"]})
            if step["internalCostRial"] is None:
                missing.append("internalCost:" + step["id"])
            else:
                known_expenses += step["internalCostRial"]
        else:
            extras.append({"stageId": step["id"],
                           "description": step["description"],
                           "amountRial": step["expenseRial"]})
            if step["expenseRial"] is None:
                missing.append("expense:" + step["id"])
            else:
                known_expenses += step["expenseRial"]
    if known_expenses > _MAX_RIAL:
        raise FinancialCaseError("Project costs exceed supported accounting range")
    # All amounts being present makes the arithmetic COMPUTABLE, never a
    # validated/final project profit. Source records are still untrusted and
    # not reconciled to issued ledger documents or verified bank payments.
    known_sales = sales["line"]["subtotalRial"]
    profit = None if missing else known_sales - known_expenses
    try:
        canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise FinancialCaseError("Unserializable or unsafe financial snapshot") from exc
    if len(canonical) > 256 * 1024:
        raise FinancialCaseError("Oversized task financial snapshot")
    return {
        "caseId": snapshot["projectId"] + ":" + snapshot["taskId"],
        "sourceRevision": expected_revision,
        "sourceDigest": hashlib.sha256(canonical).hexdigest(),
        "eventId": snapshot["eventId"], "idempotencyKey": snapshot["idempotencyKey"],
        "sales": sales, "purchaseDrafts": purchases,
        "paymentProposals": payments, "internalWork": internal,
        "additionalExpenses": extras, "knownCostsRial": known_expenses,
        "profitRial": profit, "profitComputable": profit is not None,
        "profitIsFinal": False, "amountsSourceVerified": False,
        "missing": missing, "currency": "RIAL",
        "sourceAuthenticated": False, "readyToPost": False,
        "officialInvoiceCreated": False, "journalEntriesCreated": 0,
        "status": "UNTRUSTED_SOURCE_REVIEW_PREVIEW_ONLY",
    }
