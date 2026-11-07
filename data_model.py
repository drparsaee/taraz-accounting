"""Additive v0.3 data model for Madar Desk's JSON version-1 records.

``projects`` and ``tasks`` remain the persistence and LAN permission model.
Each legacy project has a board, and a task (card) references that board with
``boardId`` and its board-local column with ``listId``. ``status`` remains the
legacy global stage reference until the application explicitly migrates its
older consumers. Board columns live in ``boards[].stages`` (the board's lists).

The v0.3 additions are intentionally separate from native_app: no pywebview,
network, filesystem or mutation of the supplied state is required. Call
``normalize_plus`` at a controlled migration boundary and ``validate_plus``
before accepting/storing the result. Unknown JSON properties are preserved.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date


DEFAULT_STAGES = [
    {"id": "inbox", "label": "صندوق ورودی", "subtitle": "ایده‌ها و کارهای جدید", "color": "#9ca3af"},
    {"id": "planned", "label": "برنامه‌ریزی", "subtitle": "آماده شروع", "color": "#6785d8"},
    {"id": "active", "label": "در حال انجام", "subtitle": "در جریان کار", "color": "#c89141"},
    {"id": "review", "label": "در انتظار بررسی", "subtitle": "نیاز به تصمیم", "color": "#a37be1"},
    {"id": "done", "label": "تکمیل‌شده", "subtitle": "کارهای تمام‌شده", "color": "#3ca789"},
]

DEFAULT_WORKSPACE_ID = "workspace-legacy"
DEFAULT_CHECKLIST_ID = "checklist-legacy"
CUSTOM_FIELD_TYPES = {"text", "number", "date", "checkbox", "select"}
COVER_SIZES = frozenset({"strip", "full"})
MAX_BYTES = 15_000_000  # native_app's existing state file limit
DEFAULT_PRIORITY_DEFINITIONS = [
    {"id": "low", "label": "کم", "color": "#94a3b8", "effect": "none"},
    {"id": "medium", "label": "متوسط", "color": "#628dde", "effect": "none"},
    {"id": "high", "label": "بالا", "color": "#eb6976", "effect": "none"},
]
PRIORITY_EFFECTS = frozenset({"none", "neon", "shimmer", "pulse", "glow", "solid"})
_PRIORITY_ID = re.compile(r"(?:low|medium|high|p-[a-z0-9]{3,32})\Z", re.ASCII)
_HEX_COLOR = re.compile(r"#[a-fA-F0-9]{6}\Z", re.ASCII)


def priority_definition_ids(settings):
    """Validate the full user-defined priority list, retaining legacy defaults.

    The same pure function is used by native validation and the additive model.
    No CSS fragments or script-bearing values can enter a priority definition.
    """
    if not isinstance(settings, dict):
        _error("settings", "expected object")
    values = settings.get("priorityDefinitions", DEFAULT_PRIORITY_DEFINITIONS)
    if not isinstance(values, list) or not 3 <= len(values) <= 30:
        _error("settings.priorityDefinitions", "expected 3 to 30 priorities")
    ids = set()
    for index, definition in enumerate(values):
        path = f"settings.priorityDefinitions[{index}]"
        if not isinstance(definition, dict) or set(definition) != {"id", "label", "color", "effect"}:
            _error(path, "expected only id, label, color and effect")
        identifier = definition["id"]
        if not isinstance(identifier, str) or not _PRIORITY_ID.fullmatch(identifier):
            _error(path + ".id", "expected low/medium/high or p- followed by 3 to 32 lowercase alphanumerics")
        _unique(identifier, ids, path + ".id")
        label = definition["label"]
        if (not isinstance(label, str) or not label.strip() or len(label) > 60
                or not all(c.isprintable() or c == "\u200c" for c in label)):
            _error(path + ".label", "expected printable label up to 60 characters")
        color = definition["color"]
        if not isinstance(color, str) or not _HEX_COLOR.fullmatch(color):
            _error(path + ".color", "expected strict #RRGGBB color")
        if not isinstance(definition["effect"], str) or definition["effect"] not in PRIORITY_EFFECTS:
            _error(path + ".effect", "unsupported visual effect")
    if not {"low", "medium", "high"}.issubset(ids):
        _error("settings.priorityDefinitions", "low, medium, high are required")
    return ids


def _error(path: str, problem: str) -> None:
    raise ValueError(f"{path}: {problem}")


def _object(value, path):
    if not isinstance(value, dict):
        _error(path, "expected object")
    return value


def _array(value, path, limit):
    if not isinstance(value, list) or len(value) > limit:
        _error(path, f"expected array with at most {limit} items")
    return value


def _string(value, path, *, limit=300, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        _error(path, f"expected {'possibly empty ' if empty else ''}string up to {limit} characters")
    return value


def _boolean(value, path):
    if type(value) is not bool:
        _error(path, "expected boolean")


def _unique(value, seen, path):
    if value in seen:
        _error(path, f"duplicate id: {value!r}")
    seen.add(value)


def _amount(value, path):
    if type(value) is not int or not 0 <= value <= 10**15:
        _error(path, "expected nonnegative integer amount in tomans")


def _share_links(links, path):
    """Match native_app's current UNC-only file-link data constraints."""
    seen = set()
    for i, link in enumerate(_array(links, path, 200)):
        here = f"{path}[{i}]"
        _object(link, here)
        identifier = _string(link.get("id"), here + ".id", limit=MAX_BYTES, empty=True)
        _unique(identifier, seen, here + ".id")
        _string(link.get("name"), here + ".name", limit=180)
        value = link.get("path")
        if not isinstance(value, str) or len(value) > 2048:
            _error(here + ".path", "expected Windows UNC share path")
        normalized = value.replace("/", "\\")
        parts = normalized[2:].split("\\")
        if (not normalized.startswith("\\\\")
                or normalized.startswith("\\\\?\\") or normalized.startswith("\\\\.\\")
                or len(parts) < 3 or not all(parts[:3])
                or any(part in (".", "..") for part in parts)
                or any(ord(char) < 32 or char in '<>:"|?*' for char in normalized[2:])
                or normalized.endswith("\\")):
            _error(here + ".path", "expected Windows UNC share path")


def _records(items, path, limit, *, legacy_ids=False):
    seen = set()
    for i, item in enumerate(_array(items, path, limit)):
        here = f"{path}[{i}]"
        _object(item, here)
        identifier = _string(item.get("id"), here + ".id",
                             limit=MAX_BYTES if legacy_ids else 100,
                             empty=legacy_ids)
        _unique(identifier, seen, here + ".id")
        yield item, here


def _digest(prefix, *parts):
    """Stable, bounded legacy ID independent of array order or JSON formatting."""
    data = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return prefix + hashlib.sha256(data.encode("utf-8")).hexdigest()[:24]


def _check_list(stage_records, path):
    items = list(_records(stage_records, path, 40))
    if not items:
        _error(path, "a board must have at least one column")
    if not any(item.get("archived") is not True for item, _ in items):
        _error(path, "at least one active column is required")
    for item, here in items:
        _string(item.get("label"), here + ".label", limit=100)
        if "archived" in item:
            _boolean(item["archived"], here + ".archived")
        # The native v1 validator permits arbitrarily long string metadata.
        # Preserve it rather than rejecting legitimate old backups here.
        _string(item.get("subtitle", ""), here + ".subtitle", limit=MAX_BYTES, empty=True)
        _string(item.get("color", ""), here + ".color", limit=MAX_BYTES, empty=True)
    return {item["id"] for item, _ in items}


def _check_labels(definitions, path):
    identifiers, names = set(), set()
    for i, label in enumerate(_array(definitions, path, 200)):
        here = f"{path}[{i}]"
        _object(label, here)
        identifier = _string(label.get("id"), here + ".id", limit=100)
        _unique(identifier, identifiers, here + ".id")
        name = _string(label.get("name"), here + ".name", limit=100)
        _unique(name, names, here + ".name")
        _string(label.get("color", "#64748b"), here + ".color", limit=80)
    return identifiers


def _check_fields(definitions, path):
    fields = {}
    for field, here in _records(definitions, path, 50):
        _string(field.get("name"), here + ".name", limit=100)
        field_type = field.get("type")
        if not isinstance(field_type, str) or field_type not in CUSTOM_FIELD_TYPES:
            _error(here + ".type", "unsupported custom field type")
        options = _array(field.get("options", []), here + ".options", 100)
        if field_type != "select" and options:
            _error(here + ".options", "only select fields may have options")
        choices = set()
        for j, option in enumerate(options):
            option_path = f"{here}.options[{j}]"
            _object(option, option_path)
            option_id = _string(option.get("id"), option_path + ".id", limit=100)
            _unique(option_id, choices, option_path + ".id")
            _string(option.get("label"), option_path + ".label", limit=100)
        fields[field["id"]] = (field_type, choices)
    return fields


def _check_field_values(values, fields, path):
    _object(values, path)
    if len(values) > 50:
        _error(path, "too many custom values")
    for key, value in values.items():
        here = f"{path}[{key!r}]"
        if key not in fields:
            _error(here, "field is not defined for this board")
        if value is None:  # no value assigned
            continue
        field_type, choices = fields[key]
        if field_type == "text":
            _string(value, here, limit=5000, empty=True)
        elif field_type == "number":
            if type(value) not in (int, float) or (
                type(value) is float and not math.isfinite(value)
            ):
                _error(here, "expected finite number")
        elif field_type == "checkbox":
            _boolean(value, here)
        elif field_type == "date":
            _string(value, here, limit=10)
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                _error(here, "expected ISO calendar date YYYY-MM-DD")
        elif field_type == "select" and (not isinstance(value, str) or value not in choices):
            _error(here, "option is not defined for this field")


def _check_expense_items(item, item_path, financial_source_ids):
    for k, expense in enumerate(_array(item.get("expenseItems", []),
                                       item_path + ".expenseItems", 50)):
        path = f"{item_path}.expenseItems[{k}]"
        if not isinstance(expense, dict) or set(expense) != {
                "id", "description", "partyId", "quantity", "currency", "unitPrice"}:
            _error(path, "unexpected financial work-item fields")
        _string(expense["id"], path + ".id", limit=96)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", expense["id"]):
            _error(path + ".id", "invalid commercial source ID")
        _unique(expense["id"], financial_source_ids, path + ".id")
        _string(expense["description"], path + ".description", limit=300)
        _string(expense["partyId"], path + ".partyId", limit=96)
        if expense["currency"] not in ("TOMAN", "RIAL"):
            _error(path + ".currency", "expected TOMAN or RIAL")
        if type(expense["quantity"]) is not int or not 1 <= expense["quantity"] <= 1000000:
            _error(path + ".quantity", "expected integer 1..1000000")
        price = expense["unitPrice"]
        if price is not None and (type(price) is not int or not 0 < price <= 10**15):
            _error(path + ".unitPrice", "expected null or exact positive integer")


def _check_checklists(groups, path, financial_source_ids=None):
    if financial_source_ids is None:
        financial_source_ids = set()
    for group, here in _records(groups, path, 30):
        _string(group.get("name"), here + ".name", limit=180)
        item_ids = set()
        # Legacy named group is a compatibility copy of the flat checklist.
        # Validate its shape without double-counting its expense source IDs.
        source_ids = set() if group["id"] == DEFAULT_CHECKLIST_ID else financial_source_ids
        for i, item in enumerate(_array(group.get("items"), here + ".items", 300)):
            item_path = f"{here}.items[{i}]"
            _object(item, item_path)
            identifier = _string(item.get("id"), item_path + ".id", limit=100)
            _unique(identifier, item_ids, item_path + ".id")
            _string(item.get("text"), item_path + ".text", limit=MAX_BYTES, empty=True)
            _boolean(item.get("done"), item_path + ".done")
            _amount(item.get("cost", 0), item_path + ".cost")
            _check_expense_items(item, item_path, source_ids)


def _check_cover(cover, path):
    """Color-only cover; URLs, HTML and arbitrary CSS are deliberately unsupported."""
    if cover is None:
        return
    _object(cover, path)
    if set(cover) != {"type", "color", "size"}:
        _error(path, "expected only type, color and size (no URLs or CSS)")
    if cover["type"] != "color":
        _error(path + ".type", "only color covers are supported")
    if not isinstance(cover["color"], str) or not _HEX_COLOR.fullmatch(cover["color"]):
        _error(path + ".color", "expected strict #RRGGBB color")
    if not isinstance(cover["size"], str) or cover["size"] not in COVER_SIZES:
        _error(path + ".size", "expected strip or full")


def _check_base(state):
    """Check the legacy references independently of the Windows-only host."""
    _object(state, "state")
    if type(state.get("version")) is not int or state["version"] != 1:
        _error("version", "expected legacy JSON version 1")
    projects = list(_records(state.get("projects"), "projects", 2000, legacy_ids=True))
    project_ids = {project["id"] for project, _ in projects}
    for project, here in projects:
        _string(project.get("name"), here + ".name", limit=180, empty=True)
        _boolean(project.get("costEnabled", False), here + ".costEnabled")
        _amount(project.get("price", 0), here + ".price")
        _share_links(project.get("fileLinks", []), here + ".fileLinks")
    stage_ids = _check_list(state.get("stages", DEFAULT_STAGES), "stages")
    settings = _object(state.get("settings", {}), "settings")
    if settings.get("theme", "light") not in ("light", "dark"):
        _error("settings.theme", "expected light or dark")
    _boolean(settings.get("themeForAllUsers", False), "settings.themeForAllUsers")
    _boolean(settings.get("costDefault", False), "settings.costDefault")
    priority_ids = priority_definition_ids(settings)
    if "labelLibrary" in settings:
        _check_labels(settings["labelLibrary"], "settings.labelLibrary")
        for index, label in enumerate(settings["labelLibrary"]):
            if set(label) != {"id", "name", "color"}:
                _error(f"settings.labelLibrary[{index}]", "expected id, name and color only")
            if not isinstance(label["color"], str) or not _HEX_COLOR.fullmatch(label["color"]):
                _error(f"settings.labelLibrary[{index}].color", "expected strict #RRGGBB")
    tasks = list(_records(state.get("tasks"), "tasks", 20000, legacy_ids=True))
    financial_source_ids = set()
    for task, here in tasks:
        if not isinstance(task.get("projectId"), str) or task["projectId"] not in project_ids:
            _error(here + ".projectId", "unknown legacy project")
        _string(task.get("title"), here + ".title", limit=300, empty=True)
        if not isinstance(task.get("status"), str) or task["status"] not in stage_ids:
            _error(here + ".status", "unknown legacy column")
        if not isinstance(task.get("priority"), str) or task["priority"] not in priority_ids:
            _error(here + ".priority", "unknown priority definition")
        # Visual card completion is independent of workflow status: a `done`
        # status transition may create durable finance completion events.
        if "completed" in task:
            _boolean(task["completed"], here + ".completed")
        _amount(task.get("cost", 0), here + ".cost")
        if "orderCustomerName" in task:
            _string(task["orderCustomerName"], here + ".orderCustomerName",
                    limit=300, empty=True)
        if "salePartyId" in task and task["salePartyId"] != "":
            _string(task["salePartyId"], here + ".salePartyId", limit=96)
        if "saleCurrency" in task and task["saleCurrency"] not in ("TOMAN", "RIAL"):
            _error(here + ".saleCurrency", "expected TOMAN or RIAL")
        if "saleUnitPrice" in task and (type(task["saleUnitPrice"]) is not int
                or not 0 <= task["saleUnitPrice"] <= 10**15):
            _error(here + ".saleUnitPrice", "expected exact integer price")
        if "saleQuantity" in task and (type(task["saleQuantity"]) is not int
                or not 1 <= task["saleQuantity"] <= 1000000):
            _error(here + ".saleQuantity", "expected integer 1..1000000")
        if task.get("costEnabled") is not None:
            _boolean(task["costEnabled"], here + ".costEnabled")
        for field in ("estimatedMinutes", "actualMinutes"):
            minutes = task.get(field, 0)
            if type(minutes) is not int or not 0 <= minutes <= 5_256_000:
                _error(here + "." + field, "expected nonnegative minutes")
        assignees = _array(task.get("assignees", []), here + ".assignees", 30)
        if (any(not isinstance(name, str) or len(name) > 40 for name in assignees)
                or len(set(assignees)) != len(assignees)):
            _error(here + ".assignees", "invalid or repeated assignee")
        _share_links(task.get("fileLinks", []), here + ".fileLinks")
        for j, item in enumerate(_array(task.get("checklist", []), here + ".checklist", 300)):
            item_path = f"{here}.checklist[{j}]"
            _object(item, item_path)
            _string(item.get("text"), item_path + ".text", limit=MAX_BYTES, empty=True)
            _boolean(item.get("done"), item_path + ".done")
            _amount(item.get("cost", 0), item_path + ".cost")
            _check_expense_items(item, item_path, financial_source_ids)
        _array(task.get("reports", []), here + ".reports", 500)
        for j, label in enumerate(_array(task.get("labels", []), here + ".labels", 200)):
            _string(label, f"{here}.labels[{j}]", limit=100)
    return projects, tasks, financial_source_ids


def validate_plus(state):
    """Validate a version-1 state with optional v0.3 workspace/board/card data.

    Returns ``True`` when references, types and limits are valid, otherwise
    raises ``ValueError`` with a JSON-like path. Validates legacy states *before*
    migration as well as normalized states; it never edits ``state``. Unknown
    extension keys are retained and are outside this schema's validation scope.

    Legacy ``status`` is a global-column key. ``listId`` is a board-local key;
    applications should maintain both during a staged UI/host migration.
    A board without ``projectId`` is allowed for future board ownership models,
    while legacy tasks must continue to reference an existing ``projectId``.
    This validator is for data-model structure, not permissions or cloud sync.
    """
    try:
        serialized = json.dumps(state, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("state: expected JSON-serializable data") from exc
    if len(serialized.encode("utf-8")) > MAX_BYTES:
        _error("state", "JSON exceeds 15 MB")

    projects, tasks, financial_source_ids = _check_base(state)
    project_ids = {p["id"] for p, _ in projects}
    workspaces = {}
    for workspace, here in _records(state.get("workspaces", []), "workspaces", 100):
        _string(workspace.get("name"), here + ".name", limit=180)
        _boolean(workspace.get("archived", False), here + ".archived")
        workspaces[workspace["id"]] = workspace

    boards = {}
    board_legacy_project = {}
    for board, here in _records(state.get("boards", []), "boards", 2000):
        _string(board.get("name"), here + ".name", limit=180)
        if not isinstance(board.get("workspaceId"), str) or board["workspaceId"] not in workspaces:
            _error(here + ".workspaceId", "unknown workspace")
        if board.get("projectId") is not None and (
            not isinstance(board["projectId"], str) or board["projectId"] not in project_ids
        ):
            _error(here + ".projectId", "unknown legacy project")
        _boolean(board.get("archived", False), here + ".archived")
        list_ids = _check_list(board.get("stages"), here + ".stages")
        label_ids = _check_labels(board.get("labelDefinitions", []), here + ".labelDefinitions")
        fields = _check_fields(board.get("customFields", []), here + ".customFields")
        boards[board["id"]] = (list_ids, label_ids, fields)
        board_legacy_project[board["id"]] = board.get("projectId")

    for task, here in tasks:
        if "deleted" in task:
            _boolean(task["deleted"], here + ".deleted")
        if "cardOrder" in task:
            order = task["cardOrder"]
            if type(order) is not int or not 0 <= order <= 1_000_000:
                _error(here + ".cardOrder", "expected integer between 0 and 1000000")
        if "boardId" in task or "listId" in task:
            if not isinstance(task.get("boardId"), str) or task["boardId"] not in boards:
                _error(here + ".boardId", "unknown board")
            if not isinstance(task.get("listId"), str) or task["listId"] not in boards[task["boardId"]][0]:
                _error(here + ".listId", "column is not in this board")
            linked_project = board_legacy_project[task["boardId"]]
            if linked_project is not None and task["projectId"] != linked_project:
                _error(here + ".projectId", "legacy project does not match board")
        if "archived" in task:
            _boolean(task["archived"], here + ".archived")
        if "labelIds" in task:
            seen = set()
            for i, label_id in enumerate(_array(task["labelIds"], here + ".labelIds", 200)):
                _string(label_id, f"{here}.labelIds[{i}]", limit=100)
                _unique(label_id, seen, f"{here}.labelIds[{i}]")
                if (not isinstance(task.get("boardId"), str)
                        or task["boardId"] not in boards
                        or label_id not in boards[task["boardId"]][1]):
                    _error(f"{here}.labelIds[{i}]", "unknown label for this board")
        if "customFieldValues" in task:
            if not isinstance(task.get("boardId"), str) or task["boardId"] not in boards:
                _error(here + ".boardId", "custom values require a valid board")
            _check_field_values(task["customFieldValues"], boards[task["boardId"]][2],
                                here + ".customFieldValues")
        if "checklists" in task:
            _check_checklists(task["checklists"], here + ".checklists", financial_source_ids)
        if "cover" in task:
            _check_cover(task["cover"], here + ".cover")

    for template, here in _records(state.get("templates", []), "templates", 3000):
        if not isinstance(template.get("boardId"), str) or template["boardId"] not in boards:
            _error(here + ".boardId", "unknown board")
        _string(template.get("name"), here + ".name", limit=180)
        _string(template.get("title", ""), here + ".title", limit=300, empty=True)
        _string(template.get("description", ""), here + ".description", limit=10000, empty=True)
        label_ids = boards[template["boardId"]][1]
        for i, value in enumerate(_array(template.get("labelIds", []), here + ".labelIds", 200)):
            if not isinstance(value, str) or value not in label_ids:
                _error(f"{here}.labelIds[{i}]", "unknown label for this board")
        _check_checklists(template.get("checklists", []), here + ".checklists")
        _check_field_values(template.get("customFieldValues", {}),
                            boards[template["boardId"]][2], here + ".customFieldValues")
    return True


def normalize_plus(state):
    """Clone and expand a v1 state into a lossless, idempotent v0.3 model.

    Keeps ``version=1``, all legacy project/task fields, global ``stages`` and
    user metadata. Adds a default workspace and a stable board per project.
    Existing workspace/board/template definitions and archival flags survive;
    card ``boardId`` / ``listId`` are only inferred when absent. Existing task
    labels remain text; matching per-board label definitions and ``labelIds``
    are added so colored labels can be introduced without deleting old labels.
    The first named ``checklists`` group copies the legacy flat checklist once.

    Important: ``checklist`` vs ``checklists``, and ``status`` vs ``listId`` are
    compatibility pairs. Once a newer UI edits one, its write path must keep
    the counterpart synchronized. Calling normalize_plus again will preserve
    existing named checklists, custom field values and board-specific stages;
    it does not guess which conflicting view contains a newer user edit.

    The function has no IO or remote sync side effects. Unsupported/malformed
    data raises ValueError before the source object can be modified.
    """
    try:
        output = json.loads(json.dumps(state, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("state: expected JSON-serializable data") from exc
    # Earlier interim migrations could create a named `checklist-legacy`
    # group containing repeated/missing item IDs. Repair only that recognized
    # compatibility group, then validate the entire state. Unknown malformed
    # custom checklists must still fail validation instead of losing content.
    _repair_partial_legacy_checklists(output)
    validate_plus(output)
    output.setdefault("settings", {})
    output.setdefault("stages", json.loads(json.dumps(DEFAULT_STAGES, ensure_ascii=False)))
    workspaces = output.setdefault("workspaces", [])
    if not workspaces:
        workspaces.append({"id": DEFAULT_WORKSPACE_ID, "name": "فضای کاری من", "archived": False})
    primary_workspace = next((w["id"] for w in workspaces
                              if w["id"] == DEFAULT_WORKSPACE_ID), workspaces[0]["id"])
    boards = output.setdefault("boards", [])
    existing_board_ids = {b["id"] for b in boards}
    first_by_project = {}
    for board in boards:
        if board.get("projectId") is not None:
            first_by_project.setdefault(board["projectId"], board["id"])

    for project in output["projects"]:
        if project["id"] not in first_by_project:
            identifier = _digest("board-legacy-", project["id"])
            if identifier in existing_board_ids:
                _error("boards", "generated legacy board id collides with an existing board")
            boards.append({"id": identifier, "workspaceId": primary_workspace,
                           "projectId": project["id"], "name": project["name"],
                           "color": project.get("color", "#64748b"), "archived": False,
                           "stages": json.loads(json.dumps(output["stages"], ensure_ascii=False)),
                           "labelDefinitions": [], "customFields": []})
            first_by_project[project["id"]] = identifier
            existing_board_ids.add(identifier)

    boards_by_id = {b["id"]: b for b in boards}
    for board in boards:
        board.setdefault("archived", False)
        board.setdefault("labelDefinitions", [])
        board.setdefault("customFields", [])
    output.setdefault("templates", [])

    for task in output["tasks"]:
        task.setdefault("boardId", first_by_project[task["projectId"]])
        board = boards_by_id[task["boardId"]]
        board_list_ids = {s["id"] for s in board["stages"]}
        if "listId" not in task:
            if task["status"] not in board_list_ids:
                _error("tasks", f"card {task['id']!r} needs explicit listId for this board")
            task["listId"] = task["status"]
        task.setdefault("archived", False)
        task.setdefault("labels", [])
        definitions = board["labelDefinitions"]
        by_name = {item["name"]: item["id"] for item in definitions}
        for label in task["labels"]:
            if label not in by_name:
                label_id = _digest("label-legacy-", board["id"], label)
                if any(item["id"] == label_id for item in definitions):
                    _error("boards", "generated label id collides with an existing definition")
                definitions.append({"id": label_id, "name": label, "color": "#64748b"})
                by_name[label] = label_id
        task.setdefault("labelIds", list(dict.fromkeys(by_name[label] for label in task["labels"])))
        if "checklists" not in task:
            task["checklists"] = ([{"id": DEFAULT_CHECKLIST_ID, "name": "چک‌لیست",
                                   "items": _legacy_checklist_items(task)}]
                                  if task.get("checklist") else [])
        task.setdefault("customFieldValues", {})

    validate_plus(output)
    return output


def _workspace_edit(state, edit):
    """Validate, clone, edit and validate again; never mutate the caller's state."""
    output = normalize_plus(state)
    edit(output)
    validate_plus(output)
    return output


def create_workspace(state, workspace_id, name):
    """Create a workspace with an app-generated stable ID (caller supplies the ID)."""
    _string(workspace_id, "workspace.id", limit=100)
    _string(name, "workspace.name", limit=180)

    def edit(output):
        if any(item["id"] == workspace_id for item in output["workspaces"]):
            _error("workspace.id", "already exists")
        output["workspaces"].append({"id": workspace_id, "name": name.strip(), "archived": False})
    return _workspace_edit(state, edit)


def rename_workspace(state, workspace_id, name):
    _string(name, "workspace.name", limit=180)

    def edit(output):
        workspace = next((item for item in output["workspaces"] if item["id"] == workspace_id), None)
        if workspace is None:
            _error("workspace.id", "not found")
        workspace["name"] = name.strip()
    return _workspace_edit(state, edit)


def set_workspace_archived(state, workspace_id, archived=True):
    _boolean(archived, "workspace.archived")

    def edit(output):
        workspace = next((item for item in output["workspaces"] if item["id"] == workspace_id), None)
        if workspace is None:
            _error("workspace.id", "not found")
        if archived and sum(not item.get("archived", False) for item in output["workspaces"]) <= 1 and not workspace.get("archived", False):
            _error("workspace", "last active workspace cannot be archived")
        workspace["archived"] = archived
    return _workspace_edit(state, edit)


def move_board_workspace(state, board_id, workspace_id):
    """Move a board and all of its cards by reference, preserving project/cost fields."""
    def edit(output):
        workspace = next((item for item in output["workspaces"] if item["id"] == workspace_id), None)
        board = next((item for item in output["boards"] if item["id"] == board_id), None)
        if workspace is None or workspace.get("archived", False):
            _error("workspace.id", "active destination workspace required")
        if board is None:
            _error("board.id", "not found")
        board["workspaceId"] = workspace_id
    return _workspace_edit(state, edit)


def delete_empty_workspace(state, workspace_id):
    """Hard deletion is allowed only when no board refers to the workspace."""
    def edit(output):
        if not any(item["id"] == workspace_id for item in output["workspaces"]):
            _error("workspace.id", "not found")
        if len(output["workspaces"]) <= 1:
            _error("workspace", "last workspace cannot be deleted")
        if any(board["workspaceId"] == workspace_id for board in output["boards"]):
            _error("workspace", "move or delete its boards first")
        output["workspaces"] = [item for item in output["workspaces"] if item["id"] != workspace_id]
    return _workspace_edit(state, edit)


def _legacy_checklist_items(task):
    """Give old checklist entries stable IDs without touching the flat original.

    native_app v1 requires ``text`` and ``done`` but permits absent or repeated
    checklist item IDs. Named lists need identifiers for independent editing.
    """
    items = json.loads(json.dumps(task["checklist"], ensure_ascii=False))
    return _assign_legacy_item_ids(items, task["id"])


def _valid_generated_source_id(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 100


def _make_unique_legacy_id(prefix, source_id, ordinal, occupied):
    """Allocate a deterministic identifier outside *all* original identifiers.

    A later valid ID may equal the first candidate digest. Reserving those
    IDs before generating replacements preserves the original owner's ID.
    """
    attempt = 0
    while True:
        proposed = (_digest(prefix, source_id, ordinal) if attempt == 0
                    else _digest(prefix, source_id, ordinal, attempt))
        if proposed not in occupied:
            occupied.add(proposed)
            return proposed
        attempt += 1


def _assign_legacy_item_ids(items, task_id, group_id=None):
    reserved = {item["id"] for item in items if isinstance(item, dict)
                and _valid_generated_source_id(item.get("id"))}
    used = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            _error(f"tasks[{task_id!r}].checklist[{index}]", "expected object")
        identifier = item.get("id")
        if not _valid_generated_source_id(identifier) or identifier in used:
            item["id"] = _make_unique_legacy_id(
                "step-legacy-", task_id if group_id is None else (task_id, group_id),
                index, reserved)
            identifier = item["id"]
        used.add(identifier)
    return items


def _repair_partial_legacy_checklists(state):
    """Repair only recognized older generated named groups, non-destructively.

    Leaves flat ``task.checklist`` untouched. A malformed custom list is a
    validation error, but a generated compatibility group may lack group/item
    IDs or contain duplicates after partial upgrades.
    """
    if not isinstance(state, dict) or not isinstance(state.get("tasks"), list):
        return
    for task in state["tasks"]:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            continue
        groups = task.get("checklists")
        if not isinstance(groups, list):
            continue
        reserved = {g["id"] for g in groups if isinstance(g, dict)
                    and _valid_generated_source_id(g.get("id"))}
        used = set()
        for index, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            group_id = group.get("id")
            recognized = (group_id == DEFAULT_CHECKLIST_ID
                          or (isinstance(group_id, str)
                              and group_id.startswith("checklist-legacy-"))
                          or (not _valid_generated_source_id(group_id)
                              and group.get("name") == "چک‌لیست"))
            if not recognized:
                if isinstance(group_id, str):
                    used.add(group_id)
                continue
            if not _valid_generated_source_id(group_id) or group_id in used:
                group["id"] = _make_unique_legacy_id(
                    "checklist-legacy-", task["id"], index, reserved)
                group_id = group["id"]
            used.add(group_id)
            if isinstance(group.get("items"), list):
                _assign_legacy_item_ids(group["items"], task["id"], group_id)
