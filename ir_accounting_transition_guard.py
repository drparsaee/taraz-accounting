"""Safeguard preparatory TOMAN accounting work while RIAL V2 is activated.

This does not grant permissions or mutate storage. Host reducer authenticates
all commands. Persistent storage additionally checks immutable histories and
refuses any unpaired financial posting, including old-client bypass attempts.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

from purchase_intake import (
    apply_intake, empty_intakes, mark_converted, validate_intakes,
)


_NONPOSTING_COMMANDS = frozenset({
    "account.create", "party.register", "item.create", "item.update",
    "invoice.create", "bill.create", "invoice.approve", "bill.approve",
    "invoice.cancel", "bill.cancel",
})
_IMMUTABLE_INTAKE_FIELDS = (
    "id", "projectId", "cardId", "stepId", "description", "quantity",
    "supplier", "createdAt",
)


def _hash(value):
    """Use precisely the canonical encoding used by purchase_intake receipts."""
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False
                             ).encode("utf8")).hexdigest()


def _verify_intake_transition(before, after, added):
    """Reconstruct one allowed intake operation and re-run its pure reducer.

    The persisted receipt is *not* trusted as a proof. Its event ID must bind
    to one deducible operation on the old state, and its fingerprint, result,
    timestamps and complete final intake snapshot must agree with a replay.
    Conversion has no intake receipt; it is instead tied to an appended
    bill.create event and the verified original priced-intake record.

    The enclosing authenticated host must remain responsible for permission
    checks: legacy receipts contain an unkeyed digest, not a signature.
    """
    historic = before.get("purchaseIntakes", empty_intakes())
    candidate = after.get("purchaseIntakes", empty_intakes())
    validate_intakes(historic)
    validate_intakes(candidate)
    if historic == candidate:
        return
    old_records, new_records = historic["records"], candidate["records"]
    old_receipts, new_receipts = historic["receipts"], candidate["receipts"]
    if not set(old_records).issubset(new_records) or not set(old_receipts).issubset(new_receipts):
        raise ValueError("Intake history cannot be deleted")
    if any(new_receipts[eid] != receipt for eid, receipt in old_receipts.items()):
        raise ValueError("Existing intake receipts are immutable")
    changed_existing = [key for key in old_records
                        if new_records[key] != old_records[key]]
    added_records = set(new_records) - set(old_records)
    added_receipts = set(new_receipts) - set(old_receipts)

    if added_receipts:
        if len(added_receipts) != 1:
            raise ValueError("One verified supplier intake command per finance revision")
        event_id = next(iter(added_receipts))
        if added_records:
            if len(added_records) != 1 or changed_existing:
                raise ValueError("Supplier intake create cannot mix existing work changes")
            row = new_records[next(iter(added_records))]
            command = {
                "type": "intake.create", "eventId": event_id,
                "intakeId": row["id"], "projectId": row["projectId"],
                "cardId": row["cardId"], "stepId": row["stepId"],
                "quantity": row["quantity"], "supplier": deepcopy(row["supplier"]),
            }
            # The storage transition is not supplied the task bundle. This
            # local reconstruction only verifies the receipt/transition; host
            # must have validated the real checklist before invoking commit.
            cards = [{"id": row["cardId"], "projectId": row["projectId"],
                      "checklist": [{"id": row["stepId"], "text": row["description"]}]}]
            projects = [{"id": row["projectId"]}]
            stamp = row["createdAt"]
            if row["updatedAt"] != stamp or row["status"] != "unpriced":
                raise ValueError("New supplier intake must start unpriced")
            # A new supplier can register its identity in the old accounting
            # event stream, but no GL posting or unrelated accounting edit.
            if any(e["command"]["type"] != "party.register" for e in added):
                raise ValueError("Supplier creation cannot mix old accounting operations")
            if len(added) > 1:
                raise ValueError("Supplier creation cannot register unrelated parties")
            if added:
                party = added[0]["command"]
                if (party.get("partyId") != row["supplier"]["id"] or
                        party.get("name") != row["supplier"]["name"] or
                        party.get("kind") != "vendor" or
                        party.get("eventId") != event_id + ":party" or
                        added[0]["at"] != stamp):
                    raise ValueError("Supplier registration not bound to intake creation")
        else:
            if len(changed_existing) != 1:
                raise ValueError("Receipt needs exactly one original intake row transition")
            if added:
                raise ValueError("Intake price/cancel cannot modify old accounting history")
            key = changed_existing[0]
            row = new_records[key]
            typ = {"priced": "intake.price",
                   "cancelled": "intake.cancel"}.get(row["status"])
            if typ is None:
                raise ValueError("Intake receipt must represent authorized price or cancellation")
            command = {"type": typ, "eventId": event_id, "intakeId": key}
            if typ == "intake.price":
                command["unitPrice"] = row["unitPrice"]
            stamp = row["updatedAt"]
            cards = []
            projects = []
        if new_receipts[event_id]["fingerprint"] != _hash(command):
            raise ValueError("Intake receipt is not bound to exact original command")
        replay = apply_intake(historic, command, cards=cards, projects=projects, now=stamp)
        if (not replay["changed"] or
                new_receipts[event_id]["result"] != replay["result"] or
                replay["state"] != candidate):
            raise ValueError("Supplier intake receipt/result does not replay to candidate")
        return

    # Conversion does not append an intake receipt. It appends one old TOMAN
    # bill.create, and the priced work's billId and source index must match.
    if added_records or len(changed_existing) != 1 or len(added) != 1:
        raise ValueError("Intake conversion requires exactly one old bill.create event")
    key = changed_existing[0]
    row = new_records[key]
    event = added[0]
    command = event["command"]
    if (old_records[key]["status"] != "priced" or row["status"] != "converted"
            or command.get("type") != "bill.create" or
            command.get("billId") != row["billId"] or
            event.get("at") != row["updatedAt"]):
        raise ValueError("Supplier conversion needs corresponding old bill.create event")
    event_id = command.get("eventId")
    if type(event_id) is not str or not event_id.endswith(":document"):
        raise ValueError("Supplier bill is not bound to a conversion event")
    conversion_id = event_id[:-len(":document")]
    if row["billId"] != "B-" + _hash(conversion_id)[:24]:
        raise ValueError("Converted bill ID does not match its source event")
    expected = mark_converted(historic, key, row["billId"], row["updatedAt"])
    if expected != candidate:
        raise ValueError("Converted work cannot change original monetary/source fields")
    source = row["cardId"] + ":" + row["stepId"]
    total = row["quantity"] * row["unitPrice"]
    if (command.get("partyId") != row["supplier"]["id"] or
            command.get("sourceType") != "task-costs" or
            command.get("sourceId") != "expense:" + _hash([row["stepId"]])[:24] or
            command.get("discount") != 0 or command.get("tax") != 0 or
            command.get("lines") != [{
                "description": row["description"], "quantity": row["quantity"],
                "unitPrice": row["unitPrice"]}] or total <= 0):
        raise ValueError("Supplier conversion bill does not match priced work")
    link = (after.get("accountingSources") or {}).get(row["billId"])
    if (type(link) is not dict or link.get("kind") != "purchase" or
            link.get("projectId") != row["projectId"] or
            link.get("cardIds") != [row["cardId"]] or
            link.get("sourceIds") != [source]):
        raise ValueError("Converted intake lacks exact commercial source link")
    payload = {
        "kind": "purchase", "projectId": row["projectId"],
        "cardId": row["cardId"], "party": row["supplier"],
        "lines": [{"id": row["stepId"], "description": row["description"],
                   "quantity": row["quantity"], "unitPrice": row["unitPrice"]}],
        "discount": 0, "tax": 0, "advance": 0, "subtotal": total,
        "total": total, "sourceId": source,
    }
    if link.get("fingerprint") != _hash(payload):
        raise ValueError("Converted bill source fingerprint differs from priced work")


def inspect_accounting_transition(before: dict, after: dict) -> tuple[dict, ...]:
    """Validate an extension transition and report NEW legacy accounting events.

    Legitimate staging may create intakes, parties and draft bills without GL
    effect. Issuance is allowed only when a caller verifies an accompanying
    RIAL event in the same app revision; other financial postings are denied.
    """
    old_account = before.get("accounting") or {"events": []}
    new_account = after.get("accounting") or {"events": []}
    historic = old_account["events"]
    candidate = new_account["events"]
    if (type(candidate) is not list or type(historic) is not list or
            candidate[:len(historic)] != historic):
        raise ValueError("Historic TOMAN accounting journal is immutable")
    added = tuple(candidate[len(historic):])
    old_links = before.get("accountingSources") or {}
    new_links = after.get("accountingSources") or {}
    if any(key not in new_links or new_links[key] != value
           for key, value in old_links.items()):
        raise ValueError("Existing task/accounting document sources are immutable")
    old_intakes = before.get("purchaseIntakes") or {"records": {}, "receipts": {}}
    new_intakes = after.get("purchaseIntakes") or {"records": {}, "receipts": {}}
    for name in ("records", "receipts"):
        if type(old_intakes[name]) is not dict or type(new_intakes[name]) is not dict:
            raise ValueError("Supplier intake index is invalid")
    for key, previous in old_intakes["receipts"].items():
        if new_intakes["receipts"].get(key) != previous:
            raise ValueError("Historic supplier intake receipts cannot be rewritten")
    for key, previous in old_intakes["records"].items():
        current = new_intakes["records"].get(key)
        if current is None or any(current[field] != previous[field]
                                  for field in _IMMUTABLE_INTAKE_FIELDS):
            raise ValueError("Historic supplier work identity is immutable")
        if previous["status"] == "converted" and current != previous:
            raise ValueError("Already converted supplier work cannot change")
        if previous["status"] == "cancelled" and current != previous:
            raise ValueError("Cancelled supplier work cannot change")
        if previous["status"] == "unpriced" and current["status"] not in (
                "unpriced", "priced", "cancelled"):
            raise ValueError("Supplier work cannot convert without price")
        if previous["status"] == "priced" and current["status"] not in (
                "priced", "converted", "cancelled"):
            raise ValueError("Invalid priced supplier work transition")
    if before.get("accounting") is not None and after.get("accounting") is None:
        raise ValueError("Activated finance cannot erase its TOMAN accounting domain")
    if before.get("purchaseIntakes") is not None and after.get("purchaseIntakes") is None:
        raise ValueError("Activated finance cannot erase its supplier intake index")
    _verify_intake_transition(before, after, added)
    newly_added_links = set(new_links) - set(old_links)
    if newly_added_links and not any(
            event["command"]["type"] in ("bill.create", "invoice.create")
            for event in added):
        raise ValueError("Task/accounting source created without a draft document")
    for event in added:
        typ = event["command"]["type"]
        if typ not in _NONPOSTING_COMMANDS and typ != "bill.issue":
            raise ValueError("TOMAN GL posting needs a reviewed RIAL bridge: " + typ)
    return added


__all__ = ["inspect_accounting_transition"]
