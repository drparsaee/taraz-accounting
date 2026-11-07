"""M-05 least-privilege finance projection for ordinary LAN task views.

No finance domain records are copied to clients. Existing task legacy cost
fields are sanitized for non-admins. On editor writes, restore host-authority
financial properties and refuse non-admin attempts to mutate paid line IDs.
This is not an accounting authorization substitute for finance.py.
"""
from copy import deepcopy

TASK_COST_FIELDS = ("cost", "costEnabled", "costCategory", "costDate",
                    "saleQuantity", "saleUnitPrice", "saleCurrency", "salePartyId")
ITEM_COST_FIELDS = ("cost", "costCategory", "costDate", "expenseItems")


def _blank(field):
    if field == "saleQuantity":
        # The persisted task schema requires a positive integer, and the
        # standalone preparation defaults to one for older task records.
        return 1
    if field == "saleCurrency":
        # A redacted editor projection still needs to pass task schema checks.
        return "TOMAN"
    if field in ("cost", "saleUnitPrice"):
        return 0
    if field == "costEnabled":
        return None
    if field == "expenseItems":
        return []
    return ""


def _redact_cost(record, fields):
    for key in fields:
        if key in record:
            record[key] = _blank(key)


def redact_card(task):
    result = deepcopy(task)
    _redact_cost(result, TASK_COST_FIELDS)
    for item in result.get("checklist", []):
        _redact_cost(item, ITEM_COST_FIELDS)
    for group in result.get("checklists", []):
        for item in group.get("items", []):
            _redact_cost(item, ITEM_COST_FIELDS)
    return result


def _restore_costs(original, posted, fields):
    for key in fields:
        redacted = _blank(key)
        if key in posted and posted[key] != redacted:
            raise PermissionError("ویرایش اطلاعات مالی از این نقش مجاز نیست.")
        if key in original:
            posted[key] = deepcopy(original[key])
        # A new card/step may explicitly carry a zero/None financial default.
        # Keeping that harmless default preserves the host's normalized shape.


def _restore_items(old_items, incoming, *, label):
    # Legacy flat checklist entries predate IDs. They cannot be matched safely
    # after a move, so preserve paid legacy entries at their original positions.
    # Normal identified items remain free to reorder.
    for index, item in enumerate(old_items):
        if item.get("id") is None and _has_money(item):
            if index >= len(incoming) or incoming[index].get("id") is not None or incoming[index].get("text") != item.get("text"):
                raise PermissionError("جابجایی یا حذف مرحله قدیمی هزینه‌دار فقط با نقش مدیر مجاز است.")
    original = {item.get("id", ("legacy", index)): item for index, item in enumerate(old_items)}
    submitted = {item.get("id", ("legacy", index)): item for index, item in enumerate(incoming)}
    if len(original) != len(old_items) or len(submitted) != len(incoming):
        raise ValueError("Duplicate checklist ID")
    for iid, item in original.items():
        if iid not in submitted and _has_money(item):
            raise PermissionError("حذف مرحله دارای اطلاعات مالی فقط با نقش مدیر مجاز است.")
    for index, item in enumerate(incoming):
        _restore_costs(original.get(item.get("id", ("legacy", index)), {}), item, ITEM_COST_FIELDS)


def _has_money(record, fields=ITEM_COST_FIELDS):
    return any(record.get(field) not in (None, 0, "", [], {}) for field in fields)


def _contains_finance(card):
    return (_has_money(card, TASK_COST_FIELDS)
            or any(_has_money(item) for item in card.get("checklist", []))
            or any(_has_money(item) for group in card.get("checklists", [])
                   for item in group.get("items", [])))


def preserve_editor_finance(old_tasks, submitted_tasks):
    """Mutates only an editor candidate copy, not the authoritative host state."""
    originals = {t["id"]: t for t in old_tasks}
    submitted_ids = {t["id"] for t in submitted_tasks}
    for original in old_tasks:
        if original["id"] not in submitted_ids:
            # An apparently cost-free card may still be linked to invoices,
            # comments or attachment storage outside the task JSON document.
            # Editors may soft-delete, but never physically drop host records.
            raise PermissionError("حذف فیزیکی کارت از نقش ویرایشگر مجاز نیست؛ از زباله‌دان استفاده کنید.")
    for card in submitted_tasks:
        old = originals.get(card["id"], {})
        _restore_costs(old, card, TASK_COST_FIELDS)
        _restore_items(old.get("checklist", []), card.get("checklist", []), label="checklist")
        old_groups = {g["id"]: g for g in old.get("checklists", [])}
        current_groups = {g["id"]: g for g in card.get("checklists", [])}
        for group in old.get("checklists", []):
            if group["id"] not in current_groups and any(
                _has_money(item) for item in group.get("items", [])
            ):
                raise PermissionError("حذف چک‌لیست هزینه‌دار فقط با نقش مدیر مجاز است.")
        for group in card.get("checklists", []):
            _restore_items(old_groups.get(group["id"], {}).get("items", []),
                           group.get("items", []), label="named checklist")
