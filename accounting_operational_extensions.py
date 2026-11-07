"""Deterministic, event-replayed operational domains for standalone Madar.

No SQL/filesystem access. The verified accounting host persists one CAS event
containing all financial and operational effects. Dates here are ISO Gregorian;
Persian display is a UI concern. Bank evidence and statutory rates are entered
explicitly, never invented by the software.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta


def _amount(h, n, field="amount", *, positive=True):
    return h["int"](n, field, positive=positive)


def _required_reason(h, c):
    return h["text"](c["reason"], "auditable reason", limit=1000)


def _doc(p, kind, doc_id, h):
    is_sales = kind == "receipt"
    key = "invoices" if is_sales else "bills"
    doc = p[key].get(h["id"](doc_id, "documentId"))
    if doc is None or doc["status"] != "issued":
        raise ValueError("Operational document must be issued and active")
    return doc


def _amount_due(d):
    return d["total"] - d["allocated"]


def _requires_system_accounts(p, account_ids):
    for account_id in account_ids:
        if not p["accounts"].get(account_id, {}).get("system"):
            raise ValueError(
                "Operational control account was historically user-owned; "
                "migrate accounting schema explicitly before using this module")


def _stock_bucket(p, warehouse_id, item_id):
    return p["stock"].setdefault(warehouse_id, {}).setdefault(item_id, {
        "quantity": 0, "value": 0, "layers": [],
    })


def _take_fifo(bucket, quantity):
    """Take exact whole-unit FIFO without floats; mutate a CAS projection only."""
    if quantity > bucket["quantity"]:
        raise ValueError("Insufficient available warehouse quantity")
    remain, value, taken = quantity, 0, []
    for layer in bucket["layers"]:
        if not remain:
            break
        take = min(layer["quantity"], remain)
        if take:
            part = take * layer["unitCost"]
            layer["quantity"] -= take
            remain -= take
            value += part
            taken.append({"source": layer["source"], "quantity": take,
                          "unitCost": layer["unitCost"]})
    if remain:
        raise ValueError("Inventory layer corruption")
    bucket["layers"] = [layer for layer in bucket["layers"] if layer["quantity"]]
    bucket["quantity"] -= quantity
    bucket["value"] -= value
    if bucket["quantity"] < 0 or bucket["value"] < 0:
        raise ValueError("Invalid stock balance")
    return value, taken


def _put_fifo(bucket, source, quantity, unit_cost, h):
    amount = h["int"](quantity * unit_cost, "inventory inventory value")
    new_qty = h["int"](bucket["quantity"] + quantity, "warehouse units")
    new_value = h["int"](bucket["value"] + amount, "warehouse carrying value")
    bucket["layers"].append({"source": source, "quantity": quantity,
                             "unitCost": unit_cost})
    bucket["quantity"], bucket["value"] = new_qty, new_value
    return amount


def _explicit_bill_line_discounts(bill, command, h):
    """Accept only the operator's complete indexed allocation, never guess one."""
    declared = command.get("lineDiscounts")
    if type(declared) is not list or len(declared) != len(bill["lines"]):
        raise ValueError("Exact discount allocation requires every purchase line")
    allocation = []
    for index, (entry, source_line) in enumerate(zip(declared, bill["lines"])):
        h["object"](entry, ("lineIndex", "amount"))
        if type(entry["lineIndex"]) is not int or entry["lineIndex"] != index:
            raise ValueError("Discount allocations must use ordered unique lineIndex values")
        amount = h["int"](entry["amount"], "line discount")
        if amount > source_line["total"]:
            raise ValueError("Line discount exceeds purchase line amount")
        allocation.append(amount)
    if sum(allocation) != bill["discount"]:
        raise ValueError("Line discounts must equal the posted purchase discount")
    policy = {"lineDiscounts": allocation,
              "allocationReference": h["id"](command.get("allocationReference"),
                                                "allocationReference"),
              "allocationReason": h["text"](command.get("allocationReason"),
                                               "allocationReason", limit=1000)}
    existing = bill.get("receiptDiscountAllocation")
    if existing is not None and policy != existing:
        raise ValueError("Purchase discount allocation differs from prior receipt")
    return policy


def _put_exact_discounted_fifo(bucket, source, *, first_unit, quantity,
                               full_quantity, gross_unit_price, discount, helpers):
    """Allocate total integer net cost with deterministic high-unit-first FIFO.

    Works across multiple partial receipts, with the same first-unit index
    independent of warehouse. Every unit remains integer and all costs sum to
    full_quantity * gross_unit_price - discount without floating point.
    """
    if full_quantity <= 0 or not 0 <= first_unit < full_quantity or first_unit + quantity > full_quantity:
        raise ValueError("Invalid remaining inventory allocation interval")
    net = full_quantity * gross_unit_price - discount
    base, high_count = divmod(net, full_quantity)
    if base <= 0:
        raise ValueError("Zero-cost units require separate reviewed valuation policy")
    higher = max(0, min(first_unit + quantity, high_count) - first_unit)
    batches = []
    if higher:
        batches.append({"quantity": higher, "unitCost": base + 1})
    if quantity - higher:
        batches.append({"quantity": quantity - higher, "unitCost": base})
    value = sum(_put_fifo(bucket, source, part["quantity"], part["unitCost"], helpers)
                for part in batches)
    if value <= 0:
        raise ValueError("Inventory receipt has no positive carrying value")
    return value, batches


def pending_goods_issues(projection, *, through_date=None):
    """Outstanding stock-tracked sales quantity before a financial cutoff.

    Date-scoped counts include credit notes and movement reversals effective at
    the cutoff. This is a completeness control, not a COGS estimate.
    """
    movements = projection.get("stockMovements", {})
    reversals = {move["sourceMovementId"] for move in movements.values()
                 if move["type"] == "inventory.reverse" and
                 (through_date is None or move["postingDate"] <= through_date)}
    issued_quantities = {}
    for move in movements.values():
        if (move["type"] != "inventory.issue" or move["id"] in reversals or
                (through_date is not None and move["postingDate"] > through_date)):
            continue
        key = (move["invoiceId"], move["itemId"])
        issued_quantities[key] = issued_quantities.get(key, 0) + move["quantity"]
    returned_quantities = {}
    for note in projection.get("returns", {}).values():
        if (note.get("direction") != "sale" or
                (through_date is not None and note["postingDate"] > through_date)):
            continue
        for detail in note["lines"]:
            key = (note["documentId"], detail["lineIndex"])
            returned_quantities[key] = returned_quantities.get(key, 0) + detail["quantity"]
    active_invoices_at_cutoff = None
    if through_date is not None:
        at_cutoff = [journal for journal in projection.get("journals", [])
                     if journal["date"] <= through_date]
        reversed_issue_entries = {journal["reversalOf"] for journal in at_cutoff
                                  if journal.get("reversalOf")}
        active_invoices_at_cutoff = {
            journal["sourceId"] for journal in at_cutoff
            if journal["sourceType"] == "invoice.issue" and
            journal["id"] not in reversed_issue_entries}
    result = []
    for invoice in projection.get("invoices", {}).values():
        if ((active_invoices_at_cutoff is None and invoice["status"] != "issued") or
                (active_invoices_at_cutoff is not None and
                 invoice["id"] not in active_invoices_at_cutoff)):
            continue
        for index, row in enumerate(invoice["lines"]):
            item_id = row.get("itemId")
            if not item_id or not projection.get("items", {}).get(item_id, {}).get("stockTracked"):
                continue
            returned = returned_quantities.get((invoice["id"], index), 0)
            issued = issued_quantities.get((invoice["id"], item_id), 0)
            missing = row["quantity"] - returned - issued
            if missing > 0:
                result.append({"invoiceId": invoice["id"], "itemId": item_id,
                               "lineIndex": index, "missingQuantity": missing})
    return result


def apply_extended(p, c, now, *, helpers):
    h = helpers
    t = c["type"]
    event_id = h["id"](c["eventId"], "eventId")
    object_ = h["object"]
    ident = h["id"]
    date_ = h["date"]
    text = h["text"]
    posting = h["posting_date"]
    line = h["line"]
    post = h["post"]

    if t == "warehouse.create":
        object_(c, ("type", "eventId", "warehouseId", "name"))
        wid = ident(c["warehouseId"], "warehouseId")
        if wid in p["warehouses"]:
            raise ValueError("Duplicate warehouse")
        p["warehouses"][wid] = {"id": wid, "name": text(c["name"], "warehouse name"),
                                "createdAt": now}
        return {"warehouseId": wid}

    if t == "item.stock.enable":
        object_(c, ("type", "eventId", "itemId"))
        iid = ident(c["itemId"], "itemId")
        item = p["items"].get(iid)
        if item is None or item["kind"] != "goods" or not item["active"] or item["stockTracked"]:
            raise ValueError("Only active untracked goods can enable warehouse control")
        if any(iid in row for row in p["stock"].values()):
            raise ValueError("Stock already exists")
        item["stockTracked"] = True
        return {"itemId": iid, "stockTracked": True}

    if t == "inventory.reverse":
        object_(c, ("type", "eventId", "movementId", "reason", "postingDate"))
        source_id = ident(c["movementId"], "movementId")
        move = p["stockMovements"].get(source_id)
        if (move is None or move.get("reversed") or
                move["type"] not in {"inventory.receive", "inventory.issue",
                                     "inventory.opening", "inventory.adjust",
                                     "inventory.transfer"}):
            raise ValueError("Movement missing, already reversed or unsupported")
        _required_reason(h, c)
        day = posting(p, c["postingDate"], now)
        if day < move["postingDate"]:
            raise ValueError("Inventory reversal cannot predate movement")
        wid, item_id = move["warehouseId"], move["itemId"]
        movements = list(p["stockMovements"].values())
        later = movements[movements.index(move)+1:]
        if any(x["itemId"] == item_id and not x.get("reversed") and
               x["type"] != "inventory.reverse" for x in later):
            # A conservative mutation ordering guard. No silent FIFO rewrite
            # of already-issued goods or downstream warehouse transfers.
            raise ValueError("Reverse subsequent item movements first")
        bucket = _stock_bucket(p, wid, item_id)
        moved = move["value"]
        if move["type"] in ("inventory.receive", "inventory.opening"):
            source_label = move.get("fifoSource", move.get("billId", source_id))
            available = sum(x["quantity"] for x in bucket["layers"]
                            if x["source"] == source_label)
            if available < move["quantity"]:
                raise ValueError("Received stock was consumed; reverse subsequent issues first")
            if move.get("fifoSource") is not None:
                exact_value = sum(x["quantity"] * x["unitCost"] for x in bucket["layers"]
                                  if x["source"] == source_label)
                if available != move["quantity"] or exact_value != moved:
                    raise ValueError("Receipt FIFO layer values differ from movement; reversal denied")
            remaining = move["quantity"]
            for layer in bucket["layers"]:
                if layer["source"] == source_label and remaining:
                    take = min(remaining, layer["quantity"])
                    layer["quantity"] -= take
                    remaining -= take
            bucket["layers"] = [x for x in bucket["layers"] if x["quantity"]]
            bucket["quantity"] -= move["quantity"]
            bucket["value"] -= moved
        elif move["type"] == "inventory.transfer":
            dest = _stock_bucket(p, move["toWarehouseId"], item_id)
            for x in move["taken"]:
                available = sum(y["quantity"] for y in dest["layers"]
                                if y["source"] == x["source"] and
                                y["unitCost"] == x["unitCost"])
                if available < x["quantity"]:
                    raise ValueError("Transferred stock was consumed")
            for x in move["taken"]:
                need = x["quantity"]
                for layer in dest["layers"]:
                    if (layer["source"] == x["source"] and
                            layer["unitCost"] == x["unitCost"] and need):
                        take = min(layer["quantity"], need)
                        layer["quantity"] -= take
                        need -= take
                dest["quantity"] -= x["quantity"]
                dest["value"] -= x["quantity"] * x["unitCost"]
                _put_fifo(bucket, x["source"], x["quantity"], x["unitCost"], h)
            dest["layers"] = [x for x in dest["layers"] if x["quantity"]]
        else:
            new_layers = []
            for x in move["taken"]:
                new_layers.append({"source": x["source"], "quantity": x["quantity"],
                                   "unitCost": x["unitCost"]})
            bucket["layers"] = [*new_layers, *bucket["layers"]]
            bucket["quantity"] += move["quantity"]
            bucket["value"] += moved
        journal_id = move["journalId"]
        reverse_journal = None
        if journal_id:
            prior = p["entries"][journal_id]
            rows = [line(x["accountId"], debit=x["credit"], credit=x["debit"],
                         party_id=x.get("partyId")) for x in prior["lines"]]
            reverse_journal = post(p, event_id, t, source_id, day, rows,
                                   reversal_of=journal_id)["id"]
            p["reversed"][journal_id] = reverse_journal
        move["reversed"] = True
        p["stockMovements"][event_id] = {
            "id": event_id, "type": t, "sourceMovementId": source_id,
            "itemId": item_id, "warehouseId": wid, "quantity": move["quantity"],
            "value": moved, "postingDate": day, "journalId": reverse_journal,
            "reason": c["reason"], "reversed": False,
        }
        return {"movementId": source_id, "reversalId": event_id,
                "journalId": reverse_journal}

    if t in ("inventory.receive", "inventory.issue", "inventory.opening",
             "inventory.transfer", "inventory.adjust"):
        common = ("type", "eventId", "warehouseId", "itemId",
                  "quantity", "postingDate")
        extra = {
            "inventory.receive": ("billId",),
            "inventory.issue": ("invoiceId",),
            "inventory.opening": ("unitCost", "reason"),
            "inventory.transfer": ("toWarehouseId", "reason"),
            "inventory.adjust": ("reason",),
        }[t]
        object_(c, (*common, *extra),
                ("taxTreatment", "discountAllocation", "lineDiscounts",
                 "allocationReference", "allocationReason") if t == "inventory.receive" else ())
        if t in ("inventory.receive", "inventory.issue",
                 "inventory.opening", "inventory.adjust"):
            _requires_system_accounts(p, ("1300", "5300"))
        wid = ident(c["warehouseId"], "warehouseId")
        iid = ident(c["itemId"], "itemId")
        if wid not in p["warehouses"]:
            raise ValueError("Unknown warehouse")
        item = p["items"].get(iid)
        if item is None or not item["stockTracked"] or not item["active"]:
            raise ValueError("Item must be active and inventory-tracked")
        day = posting(p, c["postingDate"], now)
        qty = _amount(h, c["quantity"], "exact inventory quantity")
        bucket = _stock_bucket(p, wid, iid)
        gl = None
        moved_value = 0
        if t == "inventory.receive":
            bill_id = ident(c["billId"], "billId")
            bill = p["bills"].get(bill_id)
            if bill is None or bill["status"] != "issued" or bill["postingDate"] > day:
                raise ValueError("Stock receipt requires a previously issued purchase bill")
            if bill["tax"] and c.get("taxTreatment") != "expense":
                raise ValueError("Taxed purchase receipt requires explicit taxTreatment='expense' (5200); recoverable input tax is not configured")
            if "taxTreatment" in c and c["taxTreatment"] not in ("none", "expense"):
                raise ValueError("Unsupported tax treatment for warehouse receipt")
            if bill["tax"]:
                _requires_system_accounts(p, ("5200",))
            matching = [row for row in bill["lines"] if row.get("itemId") == iid]
            if len(matching) != 1:
                raise ValueError("Purchase bill must contain one matching stock line")
            source_line = matching[0]
            line_index = next(index for index, row in enumerate(bill["lines"])
                              if row is source_line)
            existing_receipts = [x for x in p["stockMovements"].values()
                                 if x["type"] == "inventory.receive" and
                                 x.get("billId") == bill_id]
            prior = sum(x["quantity"] for x in p["stockMovements"].values()
                        if x["type"] == "inventory.receive" and not x.get("reversed") and
                        x.get("billId") == bill_id and x["itemId"] == iid)
            returned = bill.get("returnedQuantities", [0] * len(bill["lines"]))[line_index]
            remaining_quantity = source_line["quantity"] - returned
            if qty + prior > remaining_quantity:
                raise ValueError("Warehouse receipt exceeds bill quantity")
            # Existing bill posting expenses input tax in account 5200. Do not
            # silently capitalize or call that tax recoverable. A document
            # discount on a single stock line can be allocated exactly only
            # when every purchased unit has the same integral net cost.
            discount_per_unit = 0
            allocation_mode = c.get("discountAllocation")
            if bill["discount"]:
                if allocation_mode not in ("single-line-uniform", "per-line-exact"):
                    raise ValueError("Discounted purchase receipt requires explicit discountAllocation policy")
                _requires_system_accounts(p, ("5100",))
                if allocation_mode == "single-line-uniform":
                    if bill.get("receiptDiscountAllocation") is not None:
                        raise ValueError("Cannot change an established receipt discount allocation")
                    if any(k in c for k in ("lineDiscounts", "allocationReason", "allocationReference")):
                        raise ValueError("Line discounts require per-line-exact policy")
                    if len(bill["lines"]) != 1:
                        raise ValueError("Allocate multi-line purchase discount per item before warehouse receipt")
                    if bill["discount"] % source_line["quantity"]:
                        raise ValueError("Purchase discount per unit is fractional; verified valuation allocation required")
                    discount_per_unit = bill["discount"] // source_line["quantity"]
                    if existing_receipts and any(x.get("discountAllocation") == "per-line-exact"
                                                 for x in existing_receipts):
                        raise ValueError("Cannot change established receipt discount policy")
                else:
                    policy = _explicit_bill_line_discounts(bill, c, h)
                    if any(x.get("discountAllocation") != "per-line-exact"
                           for x in existing_receipts):
                        raise ValueError("Existing stock receipts use a different discount policy")
                    if bill.get("receiptDiscountAllocation") is None:
                        if any(note["direction"] == "purchase" and
                               note["documentId"] == bill_id for note in p["returns"].values()):
                            raise ValueError("Allocate line discounts before partial purchase returns")
                        bill["receiptDiscountAllocation"] = policy
            elif ("discountAllocation" in c and c["discountAllocation"] != "none") or any(
                    k in c for k in ("lineDiscounts", "allocationReason", "allocationReference")):
                raise ValueError("Unsupported discount allocation for undiscounted purchase")
            metadata = {}
            if allocation_mode == "per-line-exact":
                full_line_discount = policy["lineDiscounts"][line_index]
                previously_returned_discount = (full_line_discount * returned * 2 +
                                                source_line["quantity"]) // (2 * source_line["quantity"])
                current_discount = full_line_discount - previously_returned_discount
                # '@' cannot occur in a public bill/event ID; distinguish new
                # receipt layers from historical billId-labelled FIFO layers.
                fifo_source = "@receipt:" + event_id
                moved_value, received_layers = _put_exact_discounted_fifo(
                    bucket, fifo_source, first_unit=prior, quantity=qty,
                    full_quantity=remaining_quantity,
                    gross_unit_price=source_line["unitPrice"], discount=current_discount,
                    helpers=h)
                allocated_discount = source_line["unitPrice"] * qty - moved_value
                metadata = {"fifoSource": fifo_source, "receivedLayers": received_layers,
                            "discountAllocation": "per-line-exact", "lineIndex": line_index,
                            "allocationReference": policy["allocationReference"]}
            else:
                unit_cost = source_line["unitPrice"] - discount_per_unit
                if not unit_cost:
                    raise ValueError("Zero-cost stock must use explicit opening provenance")
                if unit_cost < 0:
                    raise ValueError("Purchase discount exceeds inventory gross value")
                moved_value = _put_fifo(bucket, bill_id, qty, unit_cost, h)
                allocated_discount = discount_per_unit * qty
            gross = source_line["unitPrice"] * qty
            rows = [line("1300", debit=moved_value)]
            if allocated_discount:
                rows.append(line("5100", debit=allocated_discount))
            rows.append(line(source_line["accountId"], credit=gross))
            gl = post(p, event_id, t, event_id, day,
                      rows)["id"]
            metadata.update({"billId": bill_id, "allocatedDiscount": allocated_discount,
                             "taxTreatment": "expense-account-5200" if bill["tax"] else "none"})
        elif t == "inventory.issue":
            inv_id = ident(c["invoiceId"], "invoiceId")
            inv = p["invoices"].get(inv_id)
            if inv is None or inv["status"] != "issued" or inv["postingDate"] > day:
                raise ValueError("Stock issue requires a posted sale invoice")
            matching = [r for r in inv["lines"] if r.get("itemId") == iid]
            if len(matching) != 1:
                raise ValueError("Sale must contain exactly one matching stock line")
            prior = sum(x["quantity"] for x in p["stockMovements"].values()
                        if x["type"] == "inventory.issue" and not x.get("reversed") and
                        x.get("invoiceId") == inv_id and x["itemId"] == iid)
            if qty + prior > matching[0]["quantity"]:
                raise ValueError("Inventory issue exceeds invoiced quantity")
            moved_value, taken = _take_fifo(bucket, qty)
            if moved_value <= 0:
                raise ValueError("Zero-valued cost of goods requires explicit policy")
            gl = post(p, event_id, t, event_id, day,
                      [line("5300", debit=moved_value),
                       line("1300", credit=moved_value)])["id"]
            metadata = {"invoiceId": inv_id, "taken": taken}
        elif t == "inventory.opening":
            _required_reason(h, c)
            if p["closedThrough"]:
                raise ValueError("Opening stock forbidden after closed period")
            # Explicitly funded opening stock is not a claim that historic
            # Parsian inventory was reconciled. Recorded as owner's equity.
            unit_cost = _amount(h, c["unitCost"], "inventory opening cost")
            moved_value = _put_fifo(bucket, event_id, qty, unit_cost, h)
            gl = post(p, event_id, t, event_id, day,
                      [line("1300", debit=moved_value),
                       line("3000", credit=moved_value)])["id"]
            metadata = {"reason": c["reason"]}
        elif t == "inventory.transfer":
            _required_reason(h, c)
            destination = ident(c["toWarehouseId"], "toWarehouseId")
            if destination == wid or destination not in p["warehouses"]:
                raise ValueError("Invalid destination warehouse")
            moved_value, taken = _take_fifo(bucket, qty)
            dest_bucket = _stock_bucket(p, destination, iid)
            for layer in taken:
                _put_fifo(dest_bucket, layer["source"], layer["quantity"],
                          layer["unitCost"], h)
            metadata = {"toWarehouseId": destination, "taken": taken,
                        "reason": c["reason"]}
        else:  # negative stocktake variance, conservatively expensed
            _required_reason(h, c)
            moved_value, taken = _take_fifo(bucket, qty)
            gl = post(p, event_id, t, event_id, day,
                      [line("5300", debit=moved_value),
                       line("1300", credit=moved_value)])["id"]
            metadata = {"reason": c["reason"], "taken": taken}
        p["stockMovements"][event_id] = {
            "id": event_id, "type": t, "itemId": iid,
            "warehouseId": wid, "quantity": qty, "value": moved_value,
            "postingDate": day, "journalId": gl, **metadata,
        }
        return {"movementId": event_id, "quantity": qty,
                "value": moved_value, "journalId": gl}

    # Operational cheques are commitments. No cash is recorded at issue,
    # presentation, endorsement or deposit. Only verified clearance settles.
    if t == "cheque.register":
        object_(c, ("type", "eventId", "chequeId", "direction", "documentId",
                    "bankAccountId", "dueDate", "amount", "reference"))
        ch_id = ident(c["chequeId"], "chequeId")
        direction = c["direction"]
        if direction not in ("receipt", "payment") or ch_id in p["cheques"]:
            raise ValueError("Invalid or duplicate cheque")
        linked = _doc(p, direction, c["documentId"], h)
        _account = h["account"]
        _account(p, c["bankAccountId"], liquid=True)
        due = date_(c["dueDate"])
        amt = _amount(h, c["amount"], "cheque amount")
        if amt > _amount_due(linked):
            raise ValueError("Cheque commitment exceeds document outstanding amount")
        ref = text(c["reference"], "bank reference", limit=100)
        if any(x["reference"] == ref and x["bankAccountId"] == c["bankAccountId"]
               and x["direction"] == direction for x in p["cheques"].values()):
            raise ValueError("Bank and direction already contain this cheque reference")
        p["cheques"][ch_id] = {
            "id": ch_id, "direction": direction, "documentId": linked["id"],
            "partyId": linked["partyId"], "bankAccountId": c["bankAccountId"],
            "dueDate": due, "amount": amt, "reference": ref,
            "status": "received" if direction == "receipt" else "issued",
            "endorseeId": None, "journalId": None, "history": [
                {"type": "register", "eventId": event_id, "at": now}],
        }
        return {"chequeId": ch_id, "status": p["cheques"][ch_id]["status"]}

    if t in ("cheque.deposit", "cheque.endorse", "cheque.clear",
             "cheque.return", "cheque.redeliver", "cheque.cancel"):
        fields = ("type", "eventId", "chequeId")
        optional = ()
        if t == "cheque.endorse":
            fields += ("endorseeId", "reason")
        if t == "cheque.clear":
            fields += ("postingDate",)
        if t in ("cheque.return", "cheque.redeliver", "cheque.cancel"):
            fields += ("reason",)
        object_(c, fields, optional)
        ch_id = ident(c["chequeId"], "chequeId")
        ch = p["cheques"].get(ch_id)
        if ch is None:
            raise ValueError("Unknown cheque")
        status = ch["status"]
        if t == "cheque.deposit":
            if ch["direction"] != "receipt" or status != "received":
                raise ValueError("Only a received unpresented cheque can be deposited")
            ch["status"] = "deposited"
        elif t == "cheque.endorse":
            if ch["direction"] != "receipt" or status != "received":
                raise ValueError("Only received cheques can be endorsed")
            # Endorsement does not recognize cash or settle an invoice. The
            # commercial receivable remains until an externally verified close.
            target = ident(c["endorseeId"], "endorseeId")
            if target not in p["parties"] or target == ch["partyId"]:
                raise ValueError("Invalid endorsee")
            _required_reason(h, c)
            ch["endorseeId"], ch["status"] = target, "endorsed"
        elif t == "cheque.return":
            if status not in ("issued", "received", "deposited", "endorsed"):
                raise ValueError("Cheque cannot be returned after clearance")
            _required_reason(h, c)
            ch["status"] = "returned"
        elif t == "cheque.cancel":
            if status not in ("issued", "received", "deposited", "endorsed",
                              "returned"):
                raise ValueError("Only noncleared cheque commitments can be cancelled")
            _required_reason(h, c)
            ch["status"] = "cancelled"
        elif t == "cheque.redeliver":
            if status != "returned":
                raise ValueError("Only returned cheques can be redelivered")
            _required_reason(h, c)
            ch["status"] = "received" if ch["direction"] == "receipt" else "issued"
        elif t == "cheque.clear":
            if not ((ch["direction"] == "receipt" and status == "deposited") or
                    (ch["direction"] == "payment" and status == "issued")):
                raise ValueError("Cheque must be duly presented before clearance")
            day = posting(p, c["postingDate"], now)
            if day < ch["dueDate"]:
                raise ValueError("Cheque cannot be recognized before its maturity")
            doc = _doc(p, ch["direction"], ch["documentId"], h)
            if _amount_due(doc) < ch["amount"]:
                raise ValueError("Document balance changed; cheque overpayment blocked")
            sales = ch["direction"] == "receipt"
            settled = h["settle"](p, {
                "type": "receipt.record" if sales else "payment.record",
                "eventId": event_id,
                "receiptId" if sales else "paymentId": "CHQ:" + ch_id,
                "partyId": ch["partyId"], "accountId": ch["bankAccountId"],
                "postingDate": day,
                "allocations": [{
                    "invoiceId" if sales else "billId": ch["documentId"],
                    "amount": ch["amount"],
                }],
            }, now, sales=sales)
            ch["status"] = "cleared"
            ch["journalId"] = settled["journalId"]
        item = {"type": t, "eventId": event_id, "at": now}
        if "reason" in c:
            item["reason"] = _required_reason(h, c)
        if "postingDate" in c:
            item["postingDate"] = date_(c["postingDate"])
        ch["history"].append(item)
        return {"chequeId": ch_id, "status": ch["status"],
                "journalId": ch["journalId"]}

    # Imported bank statement rows are not postings. Journal matching requires
    # exact account and exact net amount; duplicates are rejected.
    if t == "bank.statement.add":
        object_(c, ("type", "eventId", "statementId", "accountId",
                    "date", "amount", "reference"))
        statement_id = ident(c["statementId"], "statementId")
        if statement_id in p["bankStatements"]:
            raise ValueError("Duplicate bank statement row")
        account = h["account"](p, c["accountId"], liquid=True)
        if account["kind"] != "asset":
            raise ValueError("Statement must belong to a liquid asset")
        day = date_(c["date"])
        # Signed bank movement (negative outflow) without floats.
        amount = c["amount"]
        if type(amount) is not int or not -h["max"] <= amount <= h["max"] or amount == 0:
            raise ValueError("Invalid signed statement movement")
        reference = text(c["reference"], "statement reference", limit=100)
        if any(row["accountId"] == account["id"] and row["reference"] == reference
               for row in p["bankStatements"].values()):
            raise ValueError("Duplicate bank reference within account")
        p["bankStatements"][statement_id] = {
            "id": statement_id, "accountId": account["id"], "date": day,
            "amount": amount, "reference": reference,
            "journalId": None, "history": [{"eventId": event_id, "type": t, "at": now}],
        }
        return {"statementId": statement_id, "matched": False}

    if t == "bank.statement.batch":
        object_(c, ("type", "eventId", "rows"))
        raw = c["rows"]
        if type(raw) is not list or not 1 <= len(raw) <= 500:
            raise ValueError("Bank import batch must contain 1..500 verified rows")
        recorded = []
        for row in raw:
            object_(row, ("statementId", "accountId", "date", "amount", "reference"))
            added = apply_extended(p, {
                "type": "bank.statement.add", "eventId": event_id, **row},
                now, helpers=h)
            recorded.append(added["statementId"])
        return {"imported": len(recorded), "statementIds": recorded}

    if t in ("bank.statement.match", "bank.statement.unmatch"):
        fields = ("type", "eventId", "statementId", "reason")
        if t.endswith(".match"):
            fields += ("journalId",)
        object_(c, fields)
        row = p["bankStatements"].get(ident(c["statementId"], "statementId"))
        if row is None:
            raise ValueError("Unknown statement row")
        _required_reason(h, c)
        if t.endswith(".match"):
            jid = ident(c["journalId"], "journalId")
            if row["journalId"] is not None:
                raise ValueError("Bank row already matched")
            journal = p["entries"].get(jid)
            if journal is None or journal["reversalOf"] is not None:
                raise ValueError("Unknown or reversal journal")
            if jid in p["reversed"]:
                raise ValueError("Reversed journal cannot be matched")
            if any(x["journalId"] == jid and x["accountId"] == row["accountId"]
                   for x in p["bankStatements"].values()):
                raise ValueError("Journal already bank matched")
            balance = sum(x["debit"] - x["credit"] for x in journal["lines"]
                          if x["accountId"] == row["accountId"])
            if balance != row["amount"]:
                raise ValueError("Bank statement and ledger net amount disagree")
            row["journalId"] = jid
        else:
            if row["journalId"] is None:
                raise ValueError("Bank statement is not matched")
            row["journalId"] = None
        row["history"].append({"eventId": event_id, "type": t, "at": now,
                               "reason": c["reason"]})
        return {"statementId": row["id"], "journalId": row["journalId"]}

    # Instalment schedules are an auditable allocation plan only: they never
    # create extra AR/AP or substitute for actual settlement.
    if t == "installments.create":
        object_(c, ("type", "eventId", "planId", "direction",
                    "documentId", "schedule"))
        key = ident(c["planId"], "planId")
        if key in p["installmentPlans"]:
            raise ValueError("Duplicate instalment plan")
        direction = c["direction"]
        if direction not in ("receipt", "payment"):
            raise ValueError("Invalid instalment direction")
        doc = _doc(p, direction, c["documentId"], h)
        if any(x["direction"] == direction and x["documentId"] == doc["id"]
               and x["active"] for x in p["installmentPlans"].values()):
            raise ValueError("Document already has an active instalment plan")
        parts = c["schedule"]
        if type(parts) is not list or not 1 <= len(parts) <= 120:
            raise ValueError("Expected one to 120 instalment dates")
        rows = []
        prev = ""
        total = 0
        for item in parts:
            object_(item, ("dueDate", "amount"))
            day = date_(item["dueDate"])
            if day <= prev:
                raise ValueError("Instalment dates must increase strictly")
            prev = day
            amount = _amount(h, item["amount"], "instalment amount")
            total = h["add"](total, amount)
            rows.append({"dueDate": day, "amount": amount})
        if total != _amount_due(doc):
            raise ValueError("Instalment total must equal current unpaid document")
        p["installmentPlans"][key] = {
            "id": key, "documentId": doc["id"], "direction": direction,
            "partyId": doc["partyId"], "schedule": rows,
            "active": True, "initialAllocated": doc["allocated"],
            "events": [{"eventId": event_id, "type": t, "at": now}],
        }
        return {"planId": key, "amount": total}

    if t == "installments.cancel":
        object_(c, ("type", "eventId", "planId", "reason"))
        plan = p["installmentPlans"].get(ident(c["planId"], "planId"))
        if plan is None or not plan["active"]:
            raise ValueError("Instalment plan not active")
        _required_reason(h, c)
        plan["active"] = False
        plan["events"].append({"eventId": event_id, "type": t,
                               "reason": c["reason"], "at": now})
        return {"planId": plan["id"], "active": False}

    # Explicit configuration only, never pretend a configured rate has
    # official legal validity. The issuing user remains responsible.
    if t == "tax.rule.set":
        object_(c, ("type", "eventId", "ruleId", "name",
                    "rateBasisPoints", "effectiveFrom", "reason"))
        ident_ = ident(c["ruleId"], "ruleId")
        basis = c["rateBasisPoints"]
        if type(basis) is not int or not 0 <= basis <= 10000:
            raise ValueError("Tax basis points must be within 0..10000")
        effective = date_(c["effectiveFrom"])
        _required_reason(h, c)
        previous = p["taxRules"].get(ident_)
        if previous and effective <= previous["effectiveFrom"]:
            raise ValueError("New tax rule must supersede effective date")
        record = {"id": ident_, "name": text(c["name"], "tax rule name"),
                  "rateBasisPoints": basis, "effectiveFrom": effective,
                  "history": (deepcopy(previous["history"]) if previous else [])}
        record["history"].append({"eventId": event_id, "at": now,
                                  "effectiveFrom": effective,
                                  "rateBasisPoints": basis,
                                  "reason": c["reason"]})
        p["taxRules"][ident_] = record
        return {"ruleId": ident_, "rateBasisPoints": basis}

    if t == "fiscal.year.close":
        _requires_system_accounts(p, ("3100",))
        object_(c, ("type", "eventId", "throughDate", "reason"),
                ("startDate", "periodId"))
        close_day = date_(c["throughDate"])
        if close_day > h["posting_today"](p, now) or (p["closedThrough"] and close_day <= p["closedThrough"]):
            raise ValueError("Invalid or already closed fiscal year")
        if "startDate" in c:
            start = date_(c["startDate"])
        elif p["closedThrough"]:
            start = (date.fromisoformat(p["closedThrough"])+timedelta(days=1)).isoformat()
        else:
            start = close_day[:4] + "-01-01"
        days = (date.fromisoformat(close_day)-date.fromisoformat(start)).days
        if days<0 or days>370:
            raise ValueError("Fiscal period needs a valid start and end within one year")
        if p["closedThrough"]:
            next_day = (date.fromisoformat(p["closedThrough"])+timedelta(days=1)).isoformat()
            if start != next_day:
                raise ValueError("Fiscal periods must be contiguous with previous close")
        elif any(j["date"]<start for j in p["journals"]):
            raise ValueError("Earlier unclosed journal would be omitted from fiscal year")
        period_id = ident(c["periodId"], "periodId") if "periodId" in c else (
            "FY:"+start+":"+close_day)
        if any(r["periodId"]==period_id for r in p["fiscalYears"]):
            raise ValueError("Duplicate fiscal year identifier")
        _required_reason(h, c)
        if any(j["date"] > close_day for j in p["journals"]):
            raise ValueError("Cannot close prior year while later journals exist")
        pending = pending_goods_issues(p, through_date=close_day)
        if pending:
            first_issue = pending[0]
            raise ValueError(
                "Fiscal close requires inventory.issue/COGS for invoice " +
                first_issue["invoiceId"] + " item " + first_issue["itemId"] +
                " (missing quantity " + str(first_issue["missingQuantity"]) + ")")
        # Revenue is credit-normal, expenses debit-normal. Close to retained
        # earnings, preserving the existing posted journals and audit trail.
        rows = []
        earnings = 0
        for account_id, account in sorted(p["accounts"].items()):
            if account["kind"] not in ("revenue", "expense"):
                continue
            bal = p["balances"].get(account_id, 0)
            if bal > 0:
                rows.append(line(account_id, credit=bal))
            elif bal < 0:
                rows.append(line(account_id, debit=-bal))
            earnings += bal
        if earnings > 0:
            rows.append(line("3100", debit=earnings))
        elif earnings < 0:
            rows.append(line("3100", credit=-earnings))
        entry = None
        if rows:
            entry = post(p, event_id, t, close_day, close_day, rows)["id"]
        p["closedThrough"] = close_day
        p["fiscalYears"].append({"startDate": start, "throughDate": close_day,
                                  "periodId": period_id, "eventId": event_id,
                                  "journalId": entry, "reason": c["reason"],
                                  "closedAt": now})
        return {"closedThrough": close_day, "journalId": entry}

    if t in ("payroll.accrue", "payroll.pay", "payroll.remit"):
        _requires_system_accounts(p, ("2300", "2400", "5400"))
        if t == "payroll.accrue":
            object_(c, ("type", "eventId", "payrollId", "employeeId",
                        "period", "gross", "withholding", "reason"))
            payroll_id = ident(c["payrollId"], "payrollId")
            employee = ident(c["employeeId"], "employeeId")
            if payroll_id in p["payroll"]:
                raise ValueError("Duplicate payroll ID")
            period = date_(c["period"])
            # A Persian month's first day generally is *not* Gregorian day 01.
            # The host/UI supply the exact ISO date of the selected payroll
            # period start, without reinterpreting it as a Gregorian month.
            if any(r["employeeId"] == employee and r["period"] == period
                   for r in p["payroll"].values()):
                raise ValueError("Duplicate employee payroll period")
            gross = _amount(h, c["gross"], "gross payroll")
            held = _amount(h, c["withholding"], "withholding", positive=False)
            if held >= gross:
                raise ValueError("Withholding cannot consume all gross payroll")
            _required_reason(h, c)
            day = posting(p, now[:10], now)
            lines = [line("5400", debit=gross),
                     line("2300", credit=gross-held)]
            if held:
                lines.append(line("2400", credit=held))
            entry = post(p, event_id, t, payroll_id, day, lines)
            p["payroll"][payroll_id] = {
                "id": payroll_id, "employeeId": employee, "period": period,
                "gross": gross, "withholding": held, "net": gross-held,
                "status": "accrued", "postingDate": day, "journalId": entry["id"],
                "paymentJournalId": None, "remittanceJournalId": None,
                "reason": c["reason"],
            }
            return {"payrollId": payroll_id, "status": "accrued"}
        object_(c, ("type", "eventId", "payrollId", "accountId", "postingDate"))
        r = p["payroll"].get(ident(c["payrollId"], "payrollId"))
        if r is None:
            raise ValueError("Unknown payroll record")
        h["account"](p, c["accountId"], liquid=True)
        day = posting(p, c["postingDate"], now)
        if day < r["postingDate"]:
            raise ValueError("Payment cannot precede payroll accrual")
        if t == "payroll.pay":
            if r["status"] != "accrued":
                raise ValueError("Only accrued payroll may be paid")
            entry = post(p, event_id, t, r["id"], day,
                         [line("2300", debit=r["net"]),
                          line(c["accountId"], credit=r["net"])])
            r["status"], r["paymentJournalId"] = "paid", entry["id"]
            return {"payrollId": r["id"], "status": "paid", "journalId": entry["id"]}
        if r["status"] != "paid" or not r["withholding"] or r["remittanceJournalId"]:
            raise ValueError("Only paid payroll with unpaid withholding may be remitted")
        entry = post(p, event_id, t, r["id"], day,
                     [line("2400", debit=r["withholding"]),
                      line(c["accountId"], credit=r["withholding"])])
        r["remittanceJournalId"] = entry["id"]
        return {"payrollId": r["id"], "status": "paid",
                "remitted": r["withholding"], "journalId": entry["id"]}

    raise ValueError("Unsupported operational accounting command")
