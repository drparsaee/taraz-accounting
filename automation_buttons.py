"""Allowlisted, host-authorized Card/Board automation buttons.

Button definitions live in a small atomically replaced host JSON document.
Executing a button writes notifications/comments and its idempotency receipt
together in the existing collaboration persistence transaction. No dynamic
code, task mutation, or financial operation is supported.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

import collab
from offline_exchange import atomic_json


VERSION = 1
MAX_BUTTONS = 500
ICONS = frozenset({
    "zap", "bell", "message-square", "check-circle-2", "flag", "star",
    "rocket", "bookmark", "heart", "settings-2", "mouse-pointer-click",
    "layout-dashboard",
})


def _object(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError("Invalid automation button object")
    return value


def _clean_text(value, name, maximum):
    collab._text(value, name, maximum)
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("Invalid " + name)
    return value.strip()


def _actions(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 5:
        raise ValueError("Button requires one to five actions")
    out = []
    for action in value:
        if not isinstance(action, dict):
            raise ValueError("Invalid button action")
        if action.get("type") == "notify":
            _object(action, {"type", "users", "message"})
            users = action["users"]
            if not isinstance(users, list) or not 1 <= len(users) <= 20:
                raise ValueError("Invalid notification recipients")
            for username in users:
                collab._username(username)
            if len(set(users)) != len(users):
                raise ValueError("Duplicate notification recipients")
            out.append({"type": "notify", "users": list(users),
                        "message": _clean_text(action["message"], "notification message", 240)})
        elif action.get("type") == "comment":
            _object(action, {"type", "text"})
            out.append({"type": "comment",
                        "text": _clean_text(action["text"], "comment text", 4000)})
        else:
            raise ValueError("Button action is not allowlisted")
    return out


def _definition(value, *, persisted=False):
    required = {"id", "projectId", "boardId", "scope", "icon", "title", "actions",
                "enabled", "closeAfterAction"}
    if persisted:
        required |= {"owner", "createdAt", "updatedAt"}
    _object(value, required)
    for name in ("id", "projectId"):
        collab._identifier(value[name], name)
    if value["boardId"]:
        collab._identifier(value["boardId"], "boardId")
    elif type(value["boardId"]) is not str:
        raise ValueError("Invalid boardId")
    if value["scope"] not in ("card", "board"):
        raise ValueError("Invalid button scope")
    if value["scope"] == "board" and not value["boardId"]:
        raise ValueError("Board button requires boardId")
    for flag in ("enabled", "closeAfterAction"):
        collab._bool(value[flag])
    if value["scope"] == "board" and value["closeAfterAction"]:
        raise ValueError("Only card buttons may close the action panel")
    icon = value["icon"]
    if type(icon) is not str or icon not in ICONS:
        raise ValueError("Invalid button icon")
    title = _clean_text(value["title"], "button title", 80)
    actions = _actions(value["actions"])
    out = {**value, "icon": icon, "title": title, "actions": actions}
    if persisted:
        collab._username(value["owner"])
        collab._timestamp(value["createdAt"])
        collab._timestamp(value["updatedAt"])
    return out


def empty_state():
    return {"schemaVersion": VERSION, "buttons": [], "receipts": {}}


def validate_state(state):
    _object(state, {"schemaVersion", "buttons", "receipts"})
    if type(state["schemaVersion"]) is not int or state["schemaVersion"] != VERSION:
        raise ValueError("Unsupported button store schema")
    if not isinstance(state["buttons"], list) or len(state["buttons"]) > MAX_BUTTONS:
        raise ValueError("Invalid button collection")
    keys = set()
    for item in state["buttons"]:
        checked = _definition(item, persisted=True)
        if checked["id"] in keys:
            raise ValueError("Duplicate button ID")
        keys.add(checked["id"])
    if not isinstance(state["receipts"], dict) or len(state["receipts"]) > 10000:
        raise ValueError("Invalid button receipts")
    for event_id, record in state["receipts"].items():
        collab._identifier(event_id, "eventId")
        _object(record, {"fingerprint", "actor", "projectId", "result"})
        if type(record["fingerprint"]) is not str or not re.fullmatch("[a-f0-9]{64}", record["fingerprint"]):
            raise ValueError("Invalid button receipt hash")
        collab._username(record["actor"])
        collab._identifier(record["projectId"], "projectId")
        if not isinstance(record["result"], dict):
            raise ValueError("Invalid button receipt result")
    return True


def load(path):
    if not path.exists():
        return empty_state()
    if path.stat().st_size > 1_000_000:
        raise ValueError("Button store exceeds size limit")
    data = json.loads(path.read_text(encoding="utf8"))
    validate_state(data)
    return data


def persist(path, state):
    validate_state(state)
    if len(json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf8")) > 1_000_000:
        raise ValueError("Button store exceeds size limit")
    atomic_json(path, state)


def _authorized_context(actor, accounts, app_state):
    users, cards, projects = collab._context(actor, accounts, app_state["tasks"], app_state["projects"])
    boards = {board["id"]: board for board in app_state.get("boards", [])}
    return users, cards, projects, boards


def _board_check(definition, boards):
    board_id = definition["boardId"]
    if board_id:
        board = boards.get(board_id)
        if board is None or board.get("projectId") != definition["projectId"] or board.get("archived"):
            raise ValueError("Button board is missing, archived, or belongs to another project")


def list_buttons(state, *, actor, accounts, app_state, project_id, board_id=""):
    validate_state(state)
    users, _, projects, boards = _authorized_context(actor, accounts, app_state)
    collab._identifier(project_id, "projectId")
    if project_id not in projects:
        raise ValueError("Unknown project")
    collab._require(users[actor], project_id)
    if board_id:
        collab._identifier(board_id, "boardId")
        if board_id not in boards or boards[board_id].get("projectId") != project_id:
            raise ValueError("Unknown project board")
    return deepcopy([item for item in state["buttons"]
                     if item["projectId"] == project_id
                     and (not board_id or item["boardId"] in ("", board_id))
                     and (not item["boardId"] or
                          (item["boardId"] in boards and
                           boards[item["boardId"]].get("projectId") == project_id
                           and not boards[item["boardId"]].get("archived")))])


def mutate(state, command, *, actor, accounts, app_state, now):
    """Create/update/delete; callers serialize load, mutation and atomic save."""
    validate_state(state)
    users, _, projects, boards = _authorized_context(actor, accounts, app_state)
    _object(command, {"type", "eventId"},
            {"button", "buttonId"})
    kind = command["type"]
    if kind not in {"button.upsert", "button.delete"}:
        raise ValueError("Unsupported button command")
    if set(command) != ({"type", "eventId", "button"} if kind == "button.upsert"
                        else {"type", "eventId", "buttonId"}):
        raise ValueError("Invalid button command schema")
    event_id = collab._identifier(command["eventId"], "eventId")
    collab._timestamp(now)
    fingerprint = collab._json_fingerprint(command, actor)
    receipt = state["receipts"].get(event_id)
    if receipt:
        if receipt["fingerprint"] != fingerprint or receipt["actor"] != actor:
            raise ValueError("Idempotency key reused for different button command")
        collab._require(users[actor], receipt["projectId"], write=True)
        if users[actor]["role"] != "admin":
            raise PermissionError("Only admin can change buttons")
        return {"state": deepcopy(state), "result": deepcopy(receipt["result"]), "changed": False}
    if users[actor]["role"] != "admin":
        raise PermissionError("Only admin can change buttons")
    updated = deepcopy(state)
    if kind == "button.upsert":
        raw = command["button"]
        if not isinstance(raw, dict):
            raise ValueError("Invalid button payload")
        raw = dict(raw)
        raw.setdefault("id", "btn_" + hashlib.sha256(event_id.encode()).hexdigest()[:24])
        raw.setdefault("boardId", "")
        raw.setdefault("icon", "mouse-pointer-click")
        raw.setdefault("enabled", True)
        raw.setdefault("closeAfterAction", False)
        _object(raw, {"id", "projectId", "boardId", "scope", "icon", "title", "actions",
                      "enabled", "closeAfterAction"})
        button = _definition(raw)
        project_id = button["projectId"]
        if project_id not in projects:
            raise ValueError("Unknown button project")
        collab._require(users[actor], project_id, write=True)
        _board_check(button, boards)
        prior = next((v for v in updated["buttons"] if v["id"] == button["id"]), None)
        if prior:
            if prior["projectId"] != project_id or prior["owner"] != actor:
                raise PermissionError("Button owner and project cannot change")
            button = {**button, "owner": prior["owner"], "createdAt": prior["createdAt"], "updatedAt": now}
            updated["buttons"] = [button if b["id"] == button["id"] else b for b in updated["buttons"]]
        else:
            if len(updated["buttons"]) >= MAX_BUTTONS:
                raise ValueError("Button limit exceeded")
            button = {**button, "owner": actor, "createdAt": now, "updatedAt": now}
            updated["buttons"].append(button)
        result = deepcopy(button)
    else:
        button_id = collab._identifier(command["buttonId"], "buttonId")
        button = next((v for v in updated["buttons"] if v["id"] == button_id), None)
        if button is None:
            raise ValueError("Button not found")
        project_id = button["projectId"]
        collab._require(users[actor], project_id, write=True)
        if button["owner"] != actor:
            raise PermissionError("Only button owner can delete")
        updated["buttons"] = [b for b in updated["buttons"] if b["id"] != button_id]
        result = {"buttonId": button_id}
    updated["receipts"][event_id] = {"fingerprint": fingerprint, "actor": actor,
                                     "projectId": project_id, "result": deepcopy(result)}
    validate_state(updated)
    return {"state": updated, "result": result, "changed": True}


def execute(buttons_state, collab_state, command, *, actor, accounts, app_state, now):
    """Prepare atomic collaboration receipt + action effects for host commit."""
    validate_state(buttons_state)
    collab.validate_state(collab_state)
    _object(command, {"type", "eventId", "buttonId"}, {"cardId"})
    if command["type"] != "button.execute":
        raise ValueError("Unsupported button execution")
    event_id = collab._identifier(command["eventId"], "eventId")
    button_id = collab._identifier(command["buttonId"], "buttonId")
    collab._timestamp(now)
    users, cards, projects, boards = _authorized_context(actor, accounts, app_state)
    fingerprint = collab._json_fingerprint(command, actor)
    old = collab_state["receipts"].get(event_id)
    if old:
        if old["fingerprint"] != fingerprint:
            raise ValueError("Idempotency key reused for a different button execution")
        collab._require(users[actor], old["projectId"], write=True)
        return {"state": deepcopy(collab_state), "result": deepcopy(old["result"]), "changed": False}
    button = next((v for v in buttons_state["buttons"] if v["id"] == button_id), None)
    if button is None:
        raise ValueError("Button not found")
    if not button["enabled"]:
        raise PermissionError("Button is disabled")
    project_id = button["projectId"]
    if project_id not in projects:
        raise ValueError("Unknown project")
    collab._require(users[actor], project_id, write=True)
    owner = users.get(button["owner"])
    if owner is None or owner["role"] != "admin" or not collab._permitted(owner, project_id, write=True):
        raise PermissionError("Button owner no longer authorized")
    _board_check(button, boards)
    card_id = command.get("cardId")
    if not card_id:
        raise ValueError("A cardId is required to execute card or board actions")
    card = collab._card(cards, card_id)
    if card["projectId"] != project_id:
        raise PermissionError("Card does not belong to button project")
    if button["boardId"] and card.get("boardId") != button["boardId"]:
        raise PermissionError("Card does not belong to button board")
    candidate = deepcopy(collab_state)
    notification_ids, comment_ids = [], []
    for index, action in enumerate(button["actions"]):
        origin = collab._id("button_o_", event_id, button_id, index)
        if action["type"] == "notify":
            notification_ids.extend(collab._notify(
                candidate, origin=origin, kind="rule", recipients=action["users"],
                actor=actor, project_id=project_id, card_id=card_id,
                users=users, now=now, message=action["message"]))
        else:
            result = collab._append_comment(candidate, origin=origin, text=action["text"],
                                            actor=actor, card=card, users=users,
                                            now=now, automated=True)
            comment_ids.append(result["commentId"])
            notification_ids.extend(result["notificationIds"])
    collab._activity(candidate, event_id, actor, "event.publish", project_id, card_id, now)
    result = {"buttonId": button_id, "cardId": card_id, "notificationIds": notification_ids,
              "commentIds": comment_ids, "eventId": event_id}
    candidate["receipts"][event_id] = {
        "fingerprint": fingerprint, "projectId": project_id,
        "write": True, "adminOnly": False, "result": deepcopy(result)}
    collab.validate_state(candidate)
    return {"state": candidate, "result": result, "changed": True}
