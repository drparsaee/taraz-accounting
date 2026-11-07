"""Derive safe, repeatable collaboration events from authorized card changes."""
from __future__ import annotations

import hashlib
import json


def _digest(*parts):
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf8")
    return "card-" + hashlib.sha256(raw).hexdigest()[:32]


def card_change_events(before_state, after_state):
    """Pure diff; executor must enforce actor ACL and persist receipts atomically.

    Only supported card events are emitted. No event executes scripts or shells.
    """
    before = {card["id"]: card for card in before_state["tasks"]}
    after = {card["id"]: card for card in after_state["tasks"]}
    result = []
    for card_id, current in after.items():
        previous = before.get(card_id)
        events = []
        if previous is None:
            events.append(("card_created", {"toColumnId": current.get("listId") or current.get("status") or ""}, "created"))
        else:
            old_column = previous.get("listId") or previous.get("status")
            new_column = current.get("listId") or current.get("status")
            # The native legacy editor may change status without updating the
            # newer board-specific listId. Preserve lifecycle automation in
            # that case rather than silently losing a completed/moved event.
            status_changed = previous.get("status") != current.get("status")
            if old_column != new_column or status_changed:
                from_column = old_column if old_column != new_column else previous.get("status")
                to_column = new_column if old_column != new_column else current.get("status")
                events.append(("card_moved", {"fromColumnId": str(from_column),
                                              "toColumnId": str(to_column)}, "moved"))
            old_labels = set(previous.get("labelIds") or previous.get("labels") or [])
            new_labels = set(current.get("labelIds") or current.get("labels") or [])
            for label in sorted(old_labels ^ new_labels):
                if isinstance(label, str):
                    events.append(("label_changed", {"labelId": label}, label))
            prev_groups = {g["id"]: g for g in previous.get("checklists", [])}
            for group in current.get("checklists", []):
                group_id = group["id"]
                items = group.get("items", [])
                if not items or not all(item.get("done") is True for item in items):
                    continue
                older = prev_groups.get(group_id, {}).get("items", [])
                if older and all(item.get("done") is True for item in older):
                    continue
                events.append(("checklist_completed", {"checklistId": group_id}, group_id))
            old_values = previous.get("customFieldValues", {})
            new_values = current.get("customFieldValues", {})
            for field in sorted(set(old_values) | set(new_values)):
                if old_values.get(field) != new_values.get(field):
                    events.append(("custom_field_changed", {"fieldId": field}, field))
        for trigger, data, key in events:
            result.append({"type": "event.publish", "eventId": _digest(card_id, trigger, key, previous, current),
                           "cardId": card_id, "trigger": trigger, "data": data})
            if len(result) > 3000:
                raise ValueError("Too many card events in one save")
    return result
