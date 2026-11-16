"""Non-financial, per-company order desk for Taraz.

Orders are operational promises, never ledger events. The host selects the
company directory and authenticated actor; neither comes from a browser form.
No document is posted and no invoice is created by this module.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import stat


class OrderError(ValueError):
    pass


class OrderConflict(OrderError):
    pass


_HEX = re.compile(r"^[0-9a-f]{32}$")
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}$")
_STATUSES = {"draft", "approved", "in_production", "delivered", "cancelled"}
_STEPS = {
    "draft": {"approved", "cancelled"},
    "approved": {"in_production", "cancelled"},
    "in_production": {"delivered", "cancelled"},
    "delivered": set(),
    "cancelled": set(),
}
_COST_KINDS = {"print", "bindery", "sewing", "laser", "packaging", "shipping", "material", "other"}
_MAX_MONEY = 10**15
_MAX_QUANTITY = 10**7
_SCHEMA_VERSION = 2
_PAYMENT_STATES = {"planned", "recorded", "settled"}


def _path_ok(root: Path) -> None:
    if not root.is_absolute() or not root.is_dir():
        raise OrderError("Existing absolute company directory required")
    for entry in (root, *root.parents):
        if entry.is_symlink() or (
            getattr(entry.lstat(), "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise OrderError("Linked company directory refused")


def _name(value, label: str, limit: int = 200, optional: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (
        not optional and not value.strip()
    ) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise OrderError("Invalid " + label)
    return value.strip()


def _amount(value, label: str, *, optional: bool = False):
    if value is None and optional:
        return None
    if type(value) is not int or value < 0 or value > _MAX_MONEY:
        raise OrderError("Invalid " + label)
    return value


def _quantity(value, label: str):
    if type(value) is not int or not 1 <= value <= _MAX_QUANTITY:
        raise OrderError("Invalid " + label)
    return value


def _measured_quantity(value, label: str):
    """Unknown is different from an explicitly counted zero."""
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= _MAX_QUANTITY:
        raise OrderError("Invalid " + label)
    return value


_MEASURED_KEYS = frozenset({
    "actualProducedQuantity", "scrapQuantity", "healthySurplusQuantity",
})
_SCHEDULING_KEYS = frozenset({
    "projectReference", "scheduleStartDate", "scheduleDueDate", "procurementNotes",
})


def _date(value, label):
    if not isinstance(value, str):
        raise OrderError("Invalid " + label)
    if not value:
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise OrderError("Invalid " + label)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise OrderError("Invalid " + label) from exc
    return value


def _balance(data):
    """Compare accepted output with the quantity promised to the customer.

    The sold quantity is a target, not proof that all units have been produced.
    A negative balance therefore means outstanding production, not bad data.
    """
    values = tuple(data.get(key) for key in (
        "actualProducedQuantity", "scrapQuantity", "healthySurplusQuantity",
    ))
    if all(value is None for value in values):
        state = "not_recorded"
        balance = None
    elif any(value is None for value in values):
        state = "incomplete"
        balance = None
    else:
        actual, scrap, surplus = values
        balance = actual - scrap - surplus - data["quantity"]
        state = "balanced" if balance == 0 else (
            "shortfall" if balance < 0 else "unallocated"
        )
    return {"state": state, "balanceQuantity": balance,
            "missing": [key for key, value in zip((
                "actualProducedQuantity", "scrapQuantity", "healthySurplusQuantity",
            ), values) if value is None]}


def _money_sum(values):
    """Unknown is not zero; never pretend a partial cost list is complete."""
    values = list(values)
    if not values or any(value is None for value in values):
        return None
    result = sum(values)
    return result if result <= _MAX_MONEY else None


def _financial_view(db, row, data):
    try:
        costs = [dict(value) for value in db.execute(
            "SELECT stage_index,actual_cost,cost_date,receipt_reference,status,"
            "recorded_by,approved_by,approved_at FROM order_costs "
            "WHERE order_id=? ORDER BY stage_index", (row["id"],))]
        payments = [dict(value) for value in db.execute(
            "SELECT id,direction,amount,payment_date,party,method,"
            "transaction_reference,status,recorded_by,approved_by,approved_at "
            "FROM order_payments WHERE order_id=? ORDER BY created_at,id", (row["id"],))]
    except sqlite3.OperationalError as exc:
        # Legacy version-0 databases remain readable without an implicit write.
        if "no such table" not in str(exc):
            raise
        costs, payments = [], []
    quote = None if data["unitPrice"] is None else data["unitPrice"] * data["quantity"]
    estimates = [stage["estimatedCost"] for stage in data["costStages"]]
    estimated_cost = _money_sum(estimates)
    approved_by_stage = {entry["stage_index"]: entry["actual_cost"]
                         for entry in costs if entry["status"] == "approved"}
    actual_cost = (_money_sum(approved_by_stage.get(i) for i in range(len(estimates)))
                   if estimates else None)
    recorded_cost = (sum(entry["actual_cost"] for entry in costs)
                     if costs else None)
    settled = sum(item["amount"] for item in payments if item["status"] == "settled")
    pending = sum(item["amount"] for item in payments if item["status"] == "recorded")
    planned = sum(item["amount"] for item in payments if item["status"] == "planned")
    expected_direction = "incoming" if data["kind"] == "sale" else "outgoing"
    valid_settled = all(p["direction"] == expected_direction for p in payments
                        if p["status"] == "settled")
    balance = quote-settled if quote is not None and valid_settled else None
    estimated_profit = (quote-estimated_cost if data["kind"] == "sale" and
                        quote is not None and estimated_cost is not None else None)
    # Recognized/reconciled profit requires delivery, approved costs and full
    # actual settlement. Merely recording a bank reference cannot prove revenue.
    realized_profit = (quote-actual_cost if data["kind"] == "sale" and
                       row["status"] == "delivered" and quote is not None and
                       actual_cost is not None and balance == 0 else None)
    return {
        "costRecords": costs, "payments": payments,
        "estimatedCostTotal": estimated_cost,
        "knownEstimatedCostTotal": sum(v for v in estimates if v is not None),
        "actualCostTotal": actual_cost, "recordedActualCostTotal": recorded_cost,
        "estimatedProfit": estimated_profit, "realizedProfit": realized_profit,
        "plannedPaymentTotal": planned, "recordedPaymentTotal": pending,
        "settledPaymentTotal": settled, "paymentBalance": balance,
        "financialHandoffReady": (row["status"] == "delivered" and
            bool(data["customerId"]) and
            quote is not None and actual_cost is not None and balance == 0),
    }


def _costs(stages):
    if type(stages) is not list or len(stages) > 24:
        raise OrderError("Invalid production costs")
    result = []
    for stage in stages:
        if type(stage) is not dict or set(stage) != {
            "kind", "supplier", "description", "estimatedCost"
        } or stage["kind"] not in _COST_KINDS:
            raise OrderError("Invalid production stage")
        result.append({
            "kind": stage["kind"],
            "supplier": _name(stage["supplier"], "supplier", 120, True),
            "description": _name(stage["description"], "stage description", 300, True),
            "estimatedCost": _amount(stage["estimatedCost"], "stage cost", optional=True),
        })
    return result


def validate_order(data):
    keys = {
        "kind", "customerId", "customerName", "title", "description",
        "unit", "quantity", "productionQuantity", "unitPrice",
        "currency", "costStages", "notes",
    }
    allowed_shapes = (keys, keys | _MEASURED_KEYS,
                      keys | _MEASURED_KEYS | _SCHEDULING_KEYS)
    if type(data) is not dict or set(data) not in allowed_shapes:
        raise OrderError("Invalid order fields")
    if data["kind"] not in ("sale", "purchase"):
        raise OrderError("Invalid order kind")
    customer_id = data["customerId"]
    if not isinstance(customer_id, str) or (
        customer_id and not _ID.fullmatch(customer_id)
    ):
        raise OrderError("Invalid customer reference")
    customer_name = _name(data["customerName"], "customer", 120, True)
    if not (customer_id or customer_name):
        raise OrderError("Customer or supplier is required")
    quantity = _quantity(data["quantity"], "order quantity")
    production = _quantity(data["productionQuantity"], "planned production")
    if data["kind"] == "sale" and production < quantity:
        raise OrderError("Production cannot be less than sold quantity")
    has_measurements = _MEASURED_KEYS.issubset(data)
    if has_measurements:
        actual = _measured_quantity(data["actualProducedQuantity"], "actual production")
        scrap = _measured_quantity(data["scrapQuantity"], "scrap")
        surplus = _measured_quantity(data["healthySurplusQuantity"], "healthy surplus")
        if actual is not None and (
            (scrap is not None and scrap > actual) or
            (surplus is not None and surplus > actual) or
            (scrap is not None and surplus is not None and scrap + surplus > actual)
        ):
            raise OrderError("Scrap and healthy surplus exceed actual production")
    if data["currency"] not in ("RIAL", "TOMAN"):
        raise OrderError("Invalid currency")
    result = {
        "kind": data["kind"], "customerId": customer_id,
        "customerName": customer_name,
        "title": _name(data["title"], "order title"),
        "description": _name(data["description"], "description", 4000, True),
        "unit": _name(data["unit"], "unit", 32),
        "quantity": quantity, "productionQuantity": production,
        "unitPrice": _amount(data["unitPrice"], "unit price", optional=True),
        "currency": data["currency"],
        "costStages": _costs(data["costStages"]),
        "notes": _name(data["notes"], "notes", 4000, True),
    }
    if result["unitPrice"] is not None and (
        result["unitPrice"] * result["quantity"] > _MAX_MONEY
    ):
        raise OrderError("Quoted total exceeds supported accounting range")
    if has_measurements:
        result.update(actualProducedQuantity=actual, scrapQuantity=scrap,
                      healthySurplusQuantity=surplus)
    if _SCHEDULING_KEYS.issubset(data):
        start = _date(data["scheduleStartDate"], "start date")
        due = _date(data["scheduleDueDate"], "due date")
        if start and due and start > due:
            raise OrderError("Start date is after due date")
        result.update(
            projectReference=_name(data["projectReference"], "project reference", 120, True),
            scheduleStartDate=start, scheduleDueDate=due,
            procurementNotes=_name(data["procurementNotes"], "procurement notes", 2000, True),
        )
    return result


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_actor(actor, role):
    if role not in ("admin", "editor") or not isinstance(actor, str) or (
        not _ID.fullmatch(actor)
    ):
        raise PermissionError("Authenticated accounting editor required")


class TarazOrderStore:
    """Isolated SQLite operations; caller must resolve the correct company first."""

    def __init__(self, company_directory):
        self.root = Path(company_directory)
        _path_ok(self.root)
        self.file = self.root / "taraz-orders.sqlite3"

    def _connection(self, *, create=False):
        _path_ok(self.root)
        if self.file.is_symlink() or (
            self.file.exists() and getattr(
                self.file.lstat(), "st_file_attributes", 0
            ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise OrderError("Linked order database refused")
        if not create and not self.file.is_file():
            return None
        if self.file.exists() and not self.file.is_file():
            raise OrderError("Order database is not a file")
        db = sqlite3.connect(self.file, isolation_level=None, timeout=10)
        db.execute("PRAGMA busy_timeout = 10000")
        db.execute("PRAGMA synchronous = FULL")
        if create:
            db.execute("PRAGMA journal_mode = WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, _SCHEMA_VERSION):
                db.close()
                raise OrderError("Unsupported order schema version")
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("""CREATE TABLE IF NOT EXISTS orders(
                id TEXT PRIMARY KEY, status TEXT NOT NULL,
                revision INTEGER NOT NULL, data_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
                db.execute("""CREATE TABLE IF NOT EXISTS actions(
                key TEXT PRIMARY KEY, digest TEXT NOT NULL,
                response_json TEXT NOT NULL)""")
                db.execute("""CREATE TABLE IF NOT EXISTS audit(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL, action TEXT NOT NULL,
                actor TEXT NOT NULL, old_revision INTEGER NOT NULL,
                new_revision INTEGER NOT NULL, digest TEXT NOT NULL,
                created_at TEXT NOT NULL)""")
                # Additive, versioned migration. Legacy rows/data_json are not
                # modified. No guesswork about historic prices or payments.
                db.execute("""CREATE TABLE IF NOT EXISTS order_costs(
                    order_id TEXT NOT NULL, stage_index INTEGER NOT NULL,
                    actual_cost INTEGER NOT NULL, cost_date TEXT NOT NULL,
                    receipt_reference TEXT NOT NULL, status TEXT NOT NULL,
                    recorded_by TEXT NOT NULL, approved_by TEXT,
                    approved_at TEXT, PRIMARY KEY(order_id,stage_index))""")
                db.execute("""CREATE TABLE IF NOT EXISTS order_payments(
                    id TEXT PRIMARY KEY, order_id TEXT NOT NULL,
                    direction TEXT NOT NULL, amount INTEGER NOT NULL,
                    payment_date TEXT NOT NULL, party TEXT NOT NULL,
                    method TEXT NOT NULL, transaction_reference TEXT NOT NULL,
                    status TEXT NOT NULL, recorded_by TEXT NOT NULL,
                    approved_by TEXT, approved_at TEXT,
                    created_at TEXT NOT NULL)""")
                db.execute("""CREATE TABLE IF NOT EXISTS order_finance_handoffs(
                    order_id TEXT PRIMARY KEY, source_revision INTEGER NOT NULL,
                    preview_digest TEXT NOT NULL, prepared_by TEXT NOT NULL,
                    prepared_at TEXT NOT NULL)""")
                db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                db.close()
                raise
        return db

    def rollback_empty_migration(self):
        """Revert only the additive schema when no new financial data exists.

        The version-0 orders/actions/audit tables stay byte-for-byte intact;
        destructive down-migration of populated new tables is refused.
        """
        db = self._connection()
        if db is None:
            return False
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA_VERSION:
                db.execute("ROLLBACK")
                return False
            for table in ("order_costs", "order_payments", "order_finance_handoffs"):
                if db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]:
                    raise OrderConflict("Nonempty extended order data cannot be downgraded")
            for table in ("order_costs", "order_payments", "order_finance_handoffs"):
                db.execute("DROP TABLE " + table)
            db.execute("PRAGMA user_version=0")
            db.execute("COMMIT")
            return True
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @staticmethod
    def _display(row, db=None):
        result = json.loads(row["data_json"])
        has_measurements = _MEASURED_KEYS.issubset(result)
        reconciliation = _balance(result)
        estimated_total = (
            None if result["unitPrice"] is None else
            result["unitPrice"] * result["quantity"]
        )
        if estimated_total is not None and estimated_total > _MAX_MONEY:
            estimated_total = None
        output = {
            "id": row["id"], **result, "status": row["status"],
            "revision": row["revision"],
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
            # Legacy callers historically used this field for planned overage.
            # Retain that value only on old records for API compatibility; new
            # records expose counted scrap, never an invented waste estimate.
            "wasteQuantity": (result.get("scrapQuantity") if has_measurements else
                              max(0, result["productionQuantity"] - result["quantity"])),
            "wasteQuantityIsLegacyEstimate": not has_measurements,
            "actualProducedQuantity": result.get("actualProducedQuantity"),
            "scrapQuantity": result.get("scrapQuantity"),
            "healthySurplusQuantity": result.get("healthySurplusQuantity"),
            "productionOverageQuantity": max(0, result["productionQuantity"] - result["quantity"]),
            "productionReconciliation": reconciliation,
            "projectReference": result.get("projectReference", ""),
            "scheduleStartDate": result.get("scheduleStartDate", ""),
            "scheduleDueDate": result.get("scheduleDueDate", ""),
            "procurementNotes": result.get("procurementNotes", ""),
            "estimatedSalesTotal": estimated_total,
            "financialEventCreated": False,
        }
        if db is not None:
            output.update(_financial_view(db, row, result))
            if output["financialHandoffReady"]:
                output["financialPreview"] = {
                    "orderId":row["id"],"sourceRevision":row["revision"],
                    "customerId":result["customerId"],"currency":result["currency"],
                    "agreedTotal":estimated_total,
                    "approvedActualCost":output["actualCostTotal"],
                    "settledTotal":output["settledPaymentTotal"],
                    "createsAccountingDocument":False,
                    "previewDigest":hashlib.sha256(_json({
                        "orderId":row["id"],"revision":row["revision"],
                        "currency":result["currency"],
                        "total":output["settledPaymentTotal"],
                        "customerId":result["customerId"],
                    }).encode("utf-8")).hexdigest(),
                }
            else:
                output["financialPreview"] = None
            output["auditTrail"] = [dict(event) for event in db.execute(
                "SELECT action,actor,old_revision,new_revision,created_at "
                "FROM audit WHERE order_id=? ORDER BY seq DESC LIMIT 40",
                (row["id"],))]
            try:
                intent = db.execute(
                    "SELECT source_revision,preview_digest,prepared_by,prepared_at "
                    "FROM order_finance_handoffs WHERE order_id=?", (row["id"],)
                ).fetchone()
                output["financeHandoff"] = dict(intent) if intent else None
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
                output["financeHandoff"] = None
        return output

    def list(self, *, offset=0, limit=50):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise OrderError("Invalid page")
        db = self._connection()
        if db is None:
            return {"orders": [], "total": 0, "readOnly": True,
                    "financialEventCreated": False}
        db.row_factory = sqlite3.Row
        try:
            count = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            rows = db.execute(
                "SELECT * FROM orders ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return {
                "orders": [self._display(row, db) for row in rows],
                "total": count, "offset": offset, "limit": limit,
                "financialEventCreated": False,
            }
        finally:
            db.close()

    def customer_order_history(self, party_id, *, offset=0, limit=25):
        """Redacted, exact-party-ID sales history, never a financial ledger read.

        Caller MUST separately authenticate Taraz finance-view permission and
        current project disclosure. No string/name fuzzy matching is permitted.
        The query does not return purchase prices, costs, payments, profits or
        customer notes. This facade is not a remote Madar authorization proof.
        """
        if type(party_id) is not str or not _ID.fullmatch(party_id):
            raise OrderError("Verified counterparty identifier required")
        if (type(offset) is not int or not 0 <= offset <= 100_000 or
                type(limit) is not int or not 1 <= limit <= 50):
            raise OrderError("Bounded order history page required")
        _path_ok(self.root)
        if not self.file.exists():
            return {"partyId": party_id, "orders": [], "total": 0,
                    "offset": offset, "limit": limit, "readOnly": True,
                    "financialEventCreated": False, "financialFieldsOmitted": True}
        if (self.file.is_symlink() or not self.file.is_file() or
                getattr(self.file.lstat(), "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise OrderError("Unsafe order history data file")
        with closing(sqlite3.connect(self.file.as_uri() + "?mode=ro", uri=True,
                             timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            # A persisted opaque party ID, not a user-visible name, is the
            # only binding. json_extract errors fail closed on corrupt rows.
            predicate = ("json_extract(data_json,'$.customerId')=? AND "
                         "json_extract(data_json,'$.kind')='sale'")
            total = db.execute("SELECT COUNT(*) FROM orders WHERE " + predicate,
                               (party_id,)).fetchone()[0]
            source = db.execute(
                "SELECT id,status,revision,data_json,created_at,updated_at "
                "FROM orders WHERE " + predicate +
                " ORDER BY updated_at DESC,id LIMIT ? OFFSET ?",
                (party_id, limit, offset),
            ).fetchall()
            rows = []
            for entry in source:
                item = json.loads(entry["data_json"])
                if (type(item) is not dict or item.get("customerId") != party_id or
                        item.get("kind") != "sale" or
                        type(item.get("title")) is not str or
                        type(item.get("quantity")) is not int):
                    raise OrderError("Corrupt customer order history")
                rows.append({
                    "orderId": entry["id"], "partyId": party_id,
                    "title": item["title"], "quantity": item["quantity"],
                    "unit": item.get("unit", ""),
                    "status": entry["status"], "updatedAt": entry["updated_at"],
                    "revision": entry["revision"],
                    "projectReference": item.get("projectReference", ""),
                    "invoiceNumber": None,  # Not linked to a verified document.
                    "commercialProfileId": None,
                })
        return {"partyId": party_id, "orders": rows, "total": total,
                "offset": offset, "limit": limit, "readOnly": True,
                "financialEventCreated": False, "financialFieldsOmitted": True}

    def get(self, order_id):
        """Read a specific order by its exact ID; no truncated list lookup."""
        if not isinstance(order_id, str) or not _HEX.fullmatch(order_id):
            raise OrderError("Invalid order ID")
        db = self._connection()
        if db is None:
            raise OrderConflict("Order not found")
        db.row_factory = sqlite3.Row
        try:
            row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if row is None:
                raise OrderConflict("Order not found")
            return self._display(row, db)
        finally:
            db.close()

    def command(self, request, *, actor, role):
        _safe_actor(actor, role)
        if type(request) is not dict or set(request) != {
            "action", "idempotencyKey", "orderId", "expectedRevision",
            "data", "nextStatus", "manualConfirmation"
        }:
            raise OrderError("Invalid order command")
        action = request["action"]
        extended = {"cost.record", "cost.approve", "payment.record",
                    "payment.confirm", "payment.settle", "handoff.prepare"}
        if action not in {"create", "update", "transition"} | extended:
            raise OrderError("Unknown order action")
        key = request["idempotencyKey"]
        if not isinstance(key, str) or not _HEX.fullmatch(key):
            raise OrderError("Invalid idempotency key")
        expected = request["expectedRevision"]
        if type(expected) is not int or expected < 0:
            raise OrderError("Invalid expected revision")
        order_id = request["orderId"]
        if not isinstance(order_id, str) or (order_id and not _HEX.fullmatch(order_id)):
            raise OrderError("Invalid order ID")
        if action == "create":
            if expected != 0 or order_id or request["nextStatus"] is not None or request["manualConfirmation"] is not False:
                raise OrderError("Invalid create command")
            data = validate_order(request["data"])
        elif action == "update":
            if not order_id or request["nextStatus"] is not None or type(request["manualConfirmation"]) is not bool:
                raise OrderError("Invalid update command")
            data = validate_order(request["data"])
        elif action == "transition":
            if not order_id or request["data"] is not None or request["manualConfirmation"] is not True or (
                request["nextStatus"] not in _STATUSES
            ):
                raise OrderError("Manual status confirmation required")
            if request["nextStatus"] in {"approved", "delivered"} and role != "admin":
                raise PermissionError("Order approval or delivery requires an administrator")
            data = None
        else:
            if (not order_id or request["nextStatus"] is not None or
                type(request["data"]) is not dict or
                request["manualConfirmation"] is not
                    (action in {"cost.approve", "payment.settle", "handoff.prepare"})):
                raise OrderError("Invalid order financial-control request")
            if action in {"cost.approve", "payment.settle", "handoff.prepare"} and role != "admin":
                raise PermissionError("Authenticated financial administrator required")
            data = dict(request["data"])
            fields = {
                "cost.record": {"stageIndex", "actualCost", "costDate", "receiptReference"},
                "cost.approve": {"stageIndex"},
                "payment.record": {"direction", "amount", "paymentDate", "party",
                                   "method", "transactionReference", "status"},
                "payment.confirm": {"paymentId", "method", "transactionReference"},
                "payment.settle": {"paymentId", "transactionReference"},
                "handoff.prepare": {"previewDigest"},
            }[action]
            if set(data) != fields:
                raise OrderError("Unrecognized order financial-control fields")
            if action.startswith("cost."):
                index = data["stageIndex"]
                if type(index) is not int or index < 0 or index >= 24:
                    raise OrderError("Invalid cost stage index")
                if action == "cost.record":
                    _amount(data["actualCost"], "actual stage cost")
                    if not _date(data["costDate"], "cost date"):
                        raise OrderError("Actual cost date is required")
                    _name(data["receiptReference"], "cost receipt", 120, True)
            elif action == "payment.record":
                if data["direction"] not in ("incoming", "outgoing") or (
                    data["status"] not in ("planned", "recorded")):
                    raise OrderError("Invalid payment direction/status")
                if _amount(data["amount"], "payment amount") == 0:
                    raise OrderError("Zero-value payment cannot be tracked")
                if not _date(data["paymentDate"], "payment date"):
                    raise OrderError("Payment date is required")
                _name(data["party"], "payment party", 120)
                _name(data["method"], "payment method", 80, True)
                _name(data["transactionReference"], "transaction reference", 120, True)
                if data["status"] == "recorded" and not data["method"].strip():
                    raise OrderError("Recorded payment method required")
            elif action.startswith("payment."):
                if not isinstance(data["paymentId"], str) or not _HEX.fullmatch(data["paymentId"]):
                    raise OrderError("Invalid payment ID")
                _name(data["transactionReference"], "transaction reference", 120, True)
                if action == "payment.confirm":
                    _name(data["method"], "payment method", 80)
                elif not data["transactionReference"].strip():
                    raise OrderError("Financial settlement needs transaction evidence")
            elif action == "handoff.prepare":
                if not isinstance(data["previewDigest"], str) or (
                    not re.fullmatch(r"[0-9a-f]{64}", data["previewDigest"])):
                    raise OrderError("Invalid verified preview digest")

        digest = hashlib.sha256(_json({
            "request": request, "actor": actor, "role": role,
        }).encode("utf-8")).hexdigest()
        db = self._connection(create=True)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                "SELECT digest,response_json FROM actions WHERE key=?", (key,)
            ).fetchone()
            if replay:
                if replay["digest"] != digest:
                    raise OrderConflict("Idempotency key already used for another action")
                db.execute("COMMIT")
                return json.loads(replay["response_json"])
            previous = None
            now = datetime.now(timezone.utc).isoformat()
            if action == "create":
                order_id = secrets.token_hex(16)
                state = "draft"
                revision = 1
                db.execute(
                    "INSERT INTO orders VALUES (?,?,?,?,?,?)",
                    (order_id, state, revision, _json(data), now, now),
                )
                old_revision = 0
            else:
                previous = db.execute(
                    "SELECT * FROM orders WHERE id=?", (order_id,)
                ).fetchone()
                if previous is None:
                    raise OrderConflict("Order not found")
                if previous["revision"] != expected:
                    raise OrderConflict("Order changed; reload before saving")
                old_revision = previous["revision"]
                revision = old_revision + 1
                state = previous["status"]
                old_data = json.loads(previous["data_json"])
                if db.execute("SELECT 1 FROM order_finance_handoffs WHERE order_id=?",
                              (order_id,)).fetchone():
                    raise OrderConflict("Prepared financial handoff freezes this order")
                if action == "update":
                    if state not in ("draft", "in_production"):
                        raise OrderConflict("Only drafts and active production counts can be edited")
                    if data["kind"] != old_data["kind"]:
                        raise OrderError("Order type is immutable")
                    if state == "draft":
                        if request["manualConfirmation"] is not False:
                            raise OrderError("Draft update does not use status confirmation")
                        # Stage indexes cannot be silently rebound after actual
                        # costs have been entered against their original stage.
                        linked = db.execute(
                            "SELECT COUNT(*) FROM order_costs WHERE order_id=?",
                            (order_id,)).fetchone()[0]
                        if linked and data["costStages"] != old_data["costStages"]:
                            raise OrderConflict("Recorded stage costs prevent changing stage definitions")
                    else:
                        if request["manualConfirmation"] is not True:
                            raise OrderError("Manual production measurement confirmation required")
                        for field in old_data.keys() | data.keys():
                            old_value = old_data.get(
                                field, "" if field in _SCHEDULING_KEYS else None
                            )
                            if field not in _MEASURED_KEYS and old_value != data.get(field):
                                raise OrderConflict("Production update may change only measured quantities")
                elif action == "transition":
                    if request["nextStatus"] not in _STEPS[state]:
                        raise OrderConflict("Invalid order status transition")
                    data = json.loads(previous["data_json"])
                    if request["nextStatus"] == "delivered" and (
                        data["kind"] == "sale" and _MEASURED_KEYS.issubset(data)
                        and _balance(data)["state"] != "balanced"
                    ):
                        raise OrderConflict("Production must reconcile before delivery")
                    state = request["nextStatus"]
                else:
                    data = old_data
                    if action == "cost.record":
                        index = request["data"]["stageIndex"]
                        if index >= len(data["costStages"]) or state == "cancelled":
                            raise OrderConflict("Unknown or cancelled production stage")
                        existing = db.execute(
                            "SELECT status FROM order_costs WHERE order_id=? AND stage_index=?",
                            (order_id,index)).fetchone()
                        if existing and existing["status"] == "approved":
                            raise OrderConflict("Approved cost cannot be silently replaced")
                        db.execute("""INSERT INTO order_costs(
                            order_id,stage_index,actual_cost,cost_date,receipt_reference,
                            status,recorded_by,approved_by,approved_at)
                            VALUES(?,?,?,?,?,'recorded',?,NULL,NULL)
                            ON CONFLICT(order_id,stage_index) DO UPDATE SET
                            actual_cost=excluded.actual_cost,cost_date=excluded.cost_date,
                            receipt_reference=excluded.receipt_reference,
                            status='recorded',recorded_by=excluded.recorded_by""",
                            (order_id,index,request["data"]["actualCost"],
                             request["data"]["costDate"],request["data"]["receiptReference"].strip(),
                             actor))
                    elif action == "cost.approve":
                        cost = db.execute(
                            "SELECT status FROM order_costs WHERE order_id=? AND stage_index=?",
                            (order_id,request["data"]["stageIndex"])).fetchone()
                        if not cost or cost["status"] != "recorded":
                            raise OrderConflict("Only recorded, unapproved costs can be approved")
                        db.execute("UPDATE order_costs SET status='approved',approved_by=?,"
                                   "approved_at=? WHERE order_id=? AND stage_index=?",
                                   (actor,now,order_id,request["data"]["stageIndex"]))
                    elif action == "payment.record":
                        payment = request["data"]
                        if state == "cancelled" or payment["direction"] != (
                            "incoming" if data["kind"] == "sale" else "outgoing"):
                            raise OrderError("Invalid payment direction for this order")
                        db.execute("""INSERT INTO order_payments(
                            id,order_id,direction,amount,payment_date,party,method,
                            transaction_reference,status,recorded_by,approved_by,
                            approved_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL,?)""",
                            (secrets.token_hex(16),order_id,payment["direction"],
                             payment["amount"],payment["paymentDate"],payment["party"].strip(),
                             payment["method"].strip(),payment["transactionReference"].strip(),
                             payment["status"],actor,now))
                    elif action in ("payment.confirm", "payment.settle"):
                        payment = db.execute("SELECT * FROM order_payments WHERE id=? AND order_id=?",
                            (request["data"]["paymentId"],order_id)).fetchone()
                        if not payment:
                            raise OrderConflict("Payment not found on this order")
                        if action == "payment.confirm":
                            if payment["status"] != "planned":
                                raise OrderConflict("Only planned payments can become recorded")
                            db.execute("UPDATE order_payments SET status='recorded',method=?,"
                                       "transaction_reference=? WHERE id=?",
                                       (request["data"]["method"].strip(),
                                        request["data"]["transactionReference"].strip(),payment["id"]))
                        else:
                            if payment["status"] != "recorded" or state == "cancelled":
                                raise OrderConflict("Only recorded payments can be marked settled")
                            quoted = (None if data["unitPrice"] is None else
                                      data["unitPrice"] * data["quantity"])
                            if quoted is None:
                                raise OrderError("Agreed order amount required for settlement")
                            current_settled = db.execute(
                                "SELECT COALESCE(SUM(amount),0) FROM order_payments "
                                "WHERE order_id=? AND status='settled'", (order_id,)
                            ).fetchone()[0]
                            if current_settled + payment["amount"] > quoted:
                                raise OrderConflict("Settlement exceeds agreed order amount")
                            reference=request["data"]["transactionReference"].strip()
                            duplicate=db.execute("SELECT 1 FROM order_payments WHERE order_id=? "
                                "AND status='settled' AND transaction_reference=?",
                                (order_id,reference)).fetchone()
                            if duplicate:
                                raise OrderConflict("Transaction reference already settled")
                            db.execute("UPDATE order_payments SET status='settled',"
                                "transaction_reference=?,approved_by=?,approved_at=? WHERE id=?",
                                (reference,actor,now,payment["id"]))
                    elif action == "handoff.prepare":
                        if state != "delivered":
                            raise OrderConflict("Deliver order before financial handoff")
                        preview = _financial_view(db, previous, old_data)
                        if not preview["financialHandoffReady"]:
                            raise OrderError("Order incomplete for accounting draft handoff")
                        expected_digest = hashlib.sha256(_json({
                            "orderId":order_id,"revision":old_revision,
                            "currency":old_data["currency"],"total":preview["settledPaymentTotal"],
                            "customerId":old_data["customerId"],
                        }).encode("utf-8")).hexdigest()
                        if request["data"]["previewDigest"] != expected_digest:
                            raise OrderConflict("Financial preview is stale or forged")
                        if db.execute("SELECT 1 FROM order_finance_handoffs WHERE order_id=?",
                                      (order_id,)).fetchone():
                            raise OrderConflict("Order financial handoff already prepared")
                        db.execute("INSERT INTO order_finance_handoffs VALUES (?,?,?,?,?)",
                                   (order_id,old_revision,expected_digest,actor,now))
                db.execute(
                    "UPDATE orders SET status=?,revision=?,data_json=?,updated_at=? WHERE id=?",
                    (state, revision, _json(data), now, order_id),
                )
            row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            output = self._display(row, db)
            db.execute(
                "INSERT INTO actions VALUES (?,?,?)", (key, digest, _json(output)),
            )
            db.execute(
                "INSERT INTO audit(order_id,action,actor,old_revision,new_revision,digest,created_at) VALUES (?,?,?,?,?,?,?)",
                (order_id, action, actor, old_revision, revision, digest, now),
            )
            db.execute("COMMIT")
            return output
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
