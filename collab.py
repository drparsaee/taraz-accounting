"""Pure, deterministic collaboration domain operations for Madar Desk.

The authenticated host supplies actor, accounts, cards, projects, timestamp and
an idempotency key, then persists the returned state atomically. This module
does not perform I/O, authenticate a session, render Markdown or run code.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re


SCHEMA_VERSION = 1
ROLES = {"admin", "editor", "viewer"}
TRIGGERS = {"card_created", "card_moved", "due_soon", "label_changed",
            "checklist_completed", "custom_field_changed"}
CONDITION_FIELDS = {"fromColumnId", "toColumnId", "labelId", "checklistId",
                    "fieldId", "priority", "completed", "dueWithinDays"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_USERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,39}\Z")
_MENTION = re.compile(r"(?<![\w@.-])@([A-Za-z0-9][A-Za-z0-9._-]{2,39})(?![\w.-])")
_STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)\Z")


def _record(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError("Invalid object schema")
    return value


def _identifier(value, name="id"):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    return value


def _username(value):
    if not isinstance(value, str) or not _USERNAME.fullmatch(value):
        raise ValueError("Invalid username")
    return value


def _text(value, name, maximum, allow_empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value.strip()) or "\x00" in value:
        raise ValueError(f"Invalid {name}")
    return value


def _timestamp(value):
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        raise ValueError("Timestamp must be timezone-aware ISO 8601")
    try:
        if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError("Missing timezone")
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    return value


def _bool(value):
    if type(value) is not bool:
        raise ValueError("Expected boolean")
    return value


def _json_fingerprint(command, actor):
    try:
        encoded = json.dumps([actor, command], sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid JSON command payload") from exc
    return hashlib.sha256(encoded).hexdigest()


def _id(prefix, *parts):
    raw = json.dumps(parts, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return prefix + hashlib.sha256(raw).hexdigest()[:24]


def _index(items, field):
    if isinstance(items, dict):
        values = list(items.values())
        for key, item in items.items():
            if not isinstance(item, dict) or item.get(field) != key:
                raise ValueError("Invalid indexed record")
    elif isinstance(items, list):
        values = items
    else:
        raise ValueError("Expected list or indexed records")
    result = {}
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("Invalid record")
        key = _username(item.get(field)) if field == "username" else _identifier(item.get(field))
        if key in result:
            raise ValueError("Duplicate record ID")
        result[key] = item
    return result


def _context(actor, accounts, cards, projects):
    users = _index(accounts, "username")
    indexed_cards = _index(cards, "id")
    indexed_projects = _index(projects, "id")
    _username(actor)
    if actor not in users:
        raise PermissionError("Unknown authenticated user")
    for user in users.values():
        if user.get("role") not in ROLES or not (
            user.get("projects") is None or (
                isinstance(user["projects"], list) and
                all(isinstance(p, str) and p in indexed_projects for p in user["projects"])
            )
        ):
            raise ValueError("Invalid account role or project scope")
    for card in indexed_cards.values():
        if card.get("projectId") not in indexed_projects:
            raise ValueError("Card references missing project")
    return users, indexed_cards, indexed_projects


def _permitted(account, project_id, write=False):
    if write and account["role"] == "viewer":
        return False
    return account["role"] == "admin" or account["projects"] is None or project_id in account["projects"]


def _require(account, project_id, write=False):
    if not _permitted(account, project_id, write):
        raise PermissionError("Project access denied")


def _card(cards, card_id):
    card = cards.get(_identifier(card_id, "cardId"))
    if card is None:
        raise ValueError("Card not found")
    return card


def _comment(state, comment_id):
    cid = _identifier(comment_id, "commentId")
    return next((comment for comment in state["comments"] if comment["id"] == cid), None)


def _notification(state, notification_id):
    nid = _identifier(notification_id, "notificationId")
    return next((item for item in state["notifications"] if item["id"] == nid), None)


def _unique(records, key):
    if any(not isinstance(item, dict) or not isinstance(item.get(key), str) for item in records):
        raise ValueError("Invalid state record")
    values = [item[key] for item in records]
    if len(values) != len(set(values)):
        raise ValueError("Duplicate state IDs")


def extract_mentions(text):
    """Extract explicit @usernames in their first-occurrence order."""
    _text(text, "comment text", 4000)
    return list(dict.fromkeys(match.group(1) for match in _MENTION.finditer(text)))


def _validate_rule(rule):
    _record(rule, {"id", "projectId", "owner", "trigger", "conditions", "actions", "enabled", "createdAt"})
    for key in ("id", "projectId"):
        _identifier(rule[key], key)
    _username(rule["owner"])
    _timestamp(rule["createdAt"])
    if rule["trigger"] not in TRIGGERS:
        raise ValueError("Invalid rule trigger")
    _bool(rule["enabled"])
    if not isinstance(rule["conditions"], list) or len(rule["conditions"]) > 8:
        raise ValueError("Invalid rule conditions")
    for condition in rule["conditions"]:
        _record(condition, {"field", "equals"})
        if condition["field"] not in CONDITION_FIELDS or type(condition["equals"]) not in (str, bool, int):
            raise ValueError("Invalid rule condition")
        if isinstance(condition["equals"], str) and len(condition["equals"]) > 100:
            raise ValueError("Rule condition too long")
    if not isinstance(rule["actions"], list) or not 1 <= len(rule["actions"]) <= 5:
        raise ValueError("Invalid rule actions")
    for action in rule["actions"]:
        if not isinstance(action, dict):
            raise ValueError("Invalid rule action")
        if action.get("type") == "notify":
            _record(action, {"type", "users", "message"})
            if not isinstance(action["users"], list) or not 1 <= len(action["users"]) <= 20:
                raise ValueError("Invalid notification recipients")
            for username in action["users"]:
                _username(username)
            if len(set(action["users"])) != len(action["users"]):
                raise ValueError("Duplicate recipients")
            _text(action["message"], "notification message", 240)
        elif action.get("type") == "comment":
            _record(action, {"type", "text"})
            _text(action["text"], "automation comment", 4000)
        else:
            raise ValueError("Automation action is not allowlisted")


def empty_state():
    """Initial JSON-serializable collaboration state, schema version 1."""
    return {"schemaVersion": SCHEMA_VERSION, "comments": [], "notifications": [],
            "activity": [], "watchers": {}, "rules": [], "runs": [], "receipts": {}}


def validate_state(state):
    """Fail closed on corrupt/mismatched persisted collaboration snapshots."""
    _record(state, {"schemaVersion", "comments", "notifications", "activity", "watchers", "rules", "runs", "receipts"})
    if type(state["schemaVersion"]) is not int or state["schemaVersion"] != SCHEMA_VERSION:
        raise ValueError("Unsupported collaboration schema")
    for field in ("comments", "notifications", "activity", "rules", "runs"):
        if not isinstance(state[field], list):
            raise ValueError("Invalid " + field)
        _unique(state[field], "id")
    for comment in state["comments"]:
        _record(comment, {"id", "cardId", "projectId", "author", "text", "mentions", "createdAt", "updatedAt", "deletedAt"})
        for key in ("id", "cardId", "projectId"):
            _identifier(comment[key], key)
        _username(comment["author"])
        _text(comment["text"], "comment text", 4000, allow_empty=True)
        if not isinstance(comment["mentions"], list) or len(comment["mentions"]) > 100:
            raise ValueError("Invalid mentions")
        for mention in comment["mentions"]:
            _username(mention)
        if len(set(comment["mentions"])) != len(comment["mentions"]):
            raise ValueError("Duplicate mentions")
        _timestamp(comment["createdAt"])
        _timestamp(comment["updatedAt"])
        if comment["deletedAt"] is not None:
            _timestamp(comment["deletedAt"])
            if comment["text"] or comment["mentions"]:
                raise ValueError("Deleted comment retains contents")
    for notice in state["notifications"]:
        _record(notice, {"id", "recipient", "projectId", "cardId", "kind", "originId", "message", "createdAt", "readAt"})
        for key in ("id", "projectId", "cardId", "originId"):
            _identifier(notice[key], key)
        _username(notice["recipient"])
        if notice["kind"] not in {"mention", "watch", "rule"}:
            raise ValueError("Invalid notification kind")
        _text(notice["message"], "notification message", 240)
        _timestamp(notice["createdAt"])
        if notice["readAt"] is not None:
            _timestamp(notice["readAt"])
    for entry in state["activity"]:
        _record(entry, {"id", "eventId", "actor", "action", "projectId", "cardId", "at"})
        for key in ("id", "eventId", "projectId"):
            _identifier(entry[key], key)
        if entry["cardId"] is not None:
            _identifier(entry["cardId"], "cardId")
        _username(entry["actor"])
        if entry["action"] not in {"comment.add", "comment.edit", "comment.delete", "watch.set",
                                   "rule.upsert", "rule.delete", "event.publish", "automation.comment"}:
            raise ValueError("Invalid activity action")
        _timestamp(entry["at"])
    if not isinstance(state["watchers"], dict):
        raise ValueError("Invalid watchers")
    for card_id, watchers in state["watchers"].items():
        _identifier(card_id, "cardId")
        if not isinstance(watchers, list) or len(watchers) > 500:
            raise ValueError("Invalid watchers")
        for username in watchers:
            _username(username)
        if len(set(watchers)) != len(watchers):
            raise ValueError("Duplicate watchers")
    for rule in state["rules"]:
        _validate_rule(rule)
    for run in state["runs"]:
        _record(run, {"id", "eventId", "ruleId", "status", "at"})
        for key in ("id", "eventId", "ruleId"):
            _identifier(run[key], key)
        if run["status"] not in {"applied", "skipped_scope"}:
            raise ValueError("Invalid run status")
        _timestamp(run["at"])
    if not isinstance(state["receipts"], dict):
        raise ValueError("Invalid event receipts")
    for event_id, receipt in state["receipts"].items():
        _identifier(event_id, "eventId")
        _record(receipt, {"fingerprint", "projectId", "write", "adminOnly", "result"})
        _identifier(receipt["projectId"], "projectId")
        _bool(receipt["write"])
        _bool(receipt["adminOnly"])
        if not isinstance(receipt["fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", receipt["fingerprint"]):
            raise ValueError("Invalid event fingerprint")
        if not isinstance(receipt["result"], dict):
            raise ValueError("Invalid event receipt result")
    return True


def _activity(state, event_id, actor, action, project_id, card_id, now, suffix=""):
    state["activity"].append({"id": _id("a_", event_id, action, suffix), "eventId": event_id,
                              "actor": actor, "action": action, "projectId": project_id,
                              "cardId": card_id, "at": now})


def _notify(state, *, origin, kind, recipients, actor, project_id, card_id, users, now, message):
    recipients = dict.fromkeys(recipients)
    created = []
    for username in recipients:
        target = users.get(username)
        if username == actor or target is None or not _permitted(target, project_id):
            continue
        key = _id("n_", origin, username)
        if any(item["id"] == key for item in state["notifications"]):
            continue
        state["notifications"].append({"id": key, "recipient": username, "projectId": project_id,
                                       "cardId": card_id, "kind": kind, "originId": origin,
                                       "message": message, "createdAt": now, "readAt": None})
        created.append(key)
    return created


def _append_comment(state, *, origin, text, actor, card, users, now, automated=False):
    project_id, card_id = card["projectId"], card["id"]
    mentions = [name for name in extract_mentions(text)
                if name in users and _permitted(users[name], project_id)]
    comment_id = _id("c_", origin)
    state["comments"].append({"id": comment_id, "cardId": card_id, "projectId": project_id,
                              "author": actor, "text": text, "mentions": mentions,
                              "createdAt": now, "updatedAt": now, "deletedAt": None})
    watchers = state["watchers"].get(card_id, [])
    recipients = mentions + [name for name in watchers if name not in mentions]
    notifications = _notify(state, origin=origin, kind="mention", recipients=mentions,
                            actor=actor, project_id=project_id, card_id=card_id,
                            users=users, now=now, message="You were mentioned in a comment")
    notifications += _notify(state, origin=origin, kind="watch", recipients=[n for n in recipients if n not in mentions],
                             actor=actor, project_id=project_id, card_id=card_id,
                             users=users, now=now, message="New comment on a watched card")
    _activity(state, origin, actor, "automation.comment" if automated else "comment.add",
              project_id, card_id, now)
    return {"commentId": comment_id, "notificationIds": notifications}


def _event_data(value):
    if not isinstance(value, dict) or len(value) > len(CONDITION_FIELDS) or set(value) - CONDITION_FIELDS:
        raise ValueError("Invalid event data keys")
    for field, item in value.items():
        if type(item) not in (str, int, bool) or (type(item) is str and len(item) > 100):
            raise ValueError("Invalid event data field: " + field)
    return value


def _execute_rules(state, command, actor, user, users, cards, now):
    if command["trigger"] not in TRIGGERS:
        raise ValueError("Invalid event trigger")
    data = _event_data(command["data"])
    card = _card(cards, command["cardId"])
    _require(user, card["projectId"], write=True)
    matched = [rule for rule in state["rules"] if rule["enabled"] and
               rule["projectId"] == card["projectId"] and rule["trigger"] == command["trigger"] and
               all(c["field"] in data and type(data[c["field"]]) is type(c["equals"])
                   and data[c["field"]] == c["equals"] for c in rule["conditions"])]
    if len(matched) > 20 or sum(len(rule["actions"]) for rule in matched) > 50:
        raise ValueError("Automation execution limit exceeded")
    created = []
    for rule in sorted(matched, key=lambda item: item["id"]):
        owner = users.get(rule["owner"])
        allowed = owner is not None and owner["role"] == "admin" and _permitted(owner, card["projectId"], write=True)
        status = "applied" if allowed else "skipped_scope"
        state["runs"].append({"id": _id("r_", command["eventId"], rule["id"]),
                              "eventId": command["eventId"], "ruleId": rule["id"], "status": status, "at": now})
        if not allowed:
            continue
        for pos, action in enumerate(rule["actions"]):
            origin = _id("o_", command["eventId"], rule["id"], pos)
            if action["type"] == "notify":
                created.extend(_notify(state, origin=origin, kind="rule", recipients=action["users"],
                                       actor=actor, project_id=card["projectId"], card_id=card["id"],
                                       users=users, now=now, message=action["message"]))
            else:
                result = _append_comment(state, origin=origin, text=action["text"], actor=actor,
                                         card=card, users=users, now=now, automated=True)
                created.extend(result["notificationIds"])
    _activity(state, command["eventId"], actor, "event.publish", card["projectId"], card["id"], now)
    return {"matchedRules": len(matched), "notificationIds": created}


def apply_command(state, command, *, actor, accounts, cards, projects, now):
    """Return {state, changed, result}; never mutate caller-owned structures.

    Caller MUST obtain actor from an authenticated session, and serialize read,
    apply and commit under one server transaction/lock. eventId is a durable
    idempotency key. Reuse with a different actor/payload raises ValueError.
    """
    validate_state(state)
    users, indexed_cards, indexed_projects = _context(actor, accounts, cards, projects)
    _timestamp(now)
    _record(command, {"type", "eventId"}, {"cardId", "text", "commentId", "enabled",
                                           "notificationId", "rule", "ruleId", "trigger", "data"})
    kind, event_id = command["type"], _identifier(command["eventId"], "eventId")
    fields = {
        "comment.add": {"cardId", "text"}, "comment.edit": {"commentId", "text"},
        "comment.delete": {"commentId"}, "watch.set": {"cardId", "enabled"},
        "notification.read": {"notificationId"}, "rule.upsert": {"rule"},
        "rule.delete": {"ruleId"}, "event.publish": {"cardId", "trigger", "data"},
    }
    if kind not in fields or set(command) != {"type", "eventId"} | fields[kind]:
        raise ValueError("Invalid command schema")
    fingerprint = _json_fingerprint(command, actor)
    receipt = state["receipts"].get(event_id)
    if receipt:
        if receipt["fingerprint"] != fingerprint:
            raise ValueError("Idempotency key reused for a different command")
        if receipt["adminOnly"] and users[actor]["role"] != "admin":
            raise PermissionError("Administrator permission has been revoked")
        _require(users[actor], receipt["projectId"], write=receipt["write"])
        return {"state": deepcopy(state), "changed": False, "result": deepcopy(receipt["result"])}
    next_state = deepcopy(state)
    user = users[actor]
    if kind == "comment.add":
        card = _card(indexed_cards, command["cardId"])
        _require(user, card["projectId"], write=True)
        receipt_project = card["projectId"]
        _text(command["text"], "comment text", 4000)
        result = _append_comment(next_state, origin=event_id, text=command["text"],
                                 actor=actor, card=card, users=users, now=now)
    elif kind in {"comment.edit", "comment.delete"}:
        comment = _comment(next_state, command["commentId"])
        if comment is None or comment["deletedAt"] is not None:
            raise ValueError("Comment not found")
        card = _card(indexed_cards, comment["cardId"])
        if card["projectId"] != comment["projectId"]:
            raise ValueError("Comment/card project mismatch")
        _require(user, card["projectId"], write=True)
        receipt_project = card["projectId"]
        if kind == "comment.edit" and actor != comment["author"]:
            raise PermissionError("Only the author can edit a comment")
        if kind == "comment.delete" and actor != comment["author"] and user["role"] != "admin":
            raise PermissionError("Only the author or admin can delete a comment")
        if kind == "comment.edit":
            _text(command["text"], "comment text", 4000)
            comment["text"] = command["text"]
            new_mentions = [name for name in extract_mentions(comment["text"])
                            if name in users and _permitted(users[name], card["projectId"])]
            newly_mentioned = [name for name in new_mentions if name not in comment["mentions"]]
            comment["mentions"] = new_mentions
            notifications = _notify(next_state, origin=event_id, kind="mention", recipients=newly_mentioned,
                                    actor=actor, project_id=card["projectId"], card_id=card["id"],
                                    users=users, now=now, message="You were mentioned in an edited comment")
        else:
            comment["text"], comment["mentions"], comment["deletedAt"] = "", [], now
            notifications = []
        comment["updatedAt"] = now
        _activity(next_state, event_id, actor, kind, card["projectId"], card["id"], now)
        result = {"commentId": comment["id"], "notificationIds": notifications}
    elif kind == "watch.set":
        card = _card(indexed_cards, command["cardId"])
        _require(user, card["projectId"])
        receipt_project = card["projectId"]
        _bool(command["enabled"])
        watchers = set(next_state["watchers"].get(card["id"], []))
        if command["enabled"]:
            watchers.add(actor)
        else:
            watchers.discard(actor)
        if watchers:
            next_state["watchers"][card["id"]] = sorted(watchers)
        else:
            next_state["watchers"].pop(card["id"], None)
        _activity(next_state, event_id, actor, kind, card["projectId"], card["id"], now)
        result = {"watching": command["enabled"]}
    elif kind == "notification.read":
        notice = _notification(next_state, command["notificationId"])
        if notice is None or notice["recipient"] != actor:
            raise PermissionError("Notification is not accessible")
        _require(user, notice["projectId"])
        receipt_project = notice["projectId"]
        if notice["readAt"] is None:
            notice["readAt"] = now
        result = {"notificationId": notice["id"], "readAt": notice["readAt"]}
    elif kind == "rule.upsert":
        if user["role"] != "admin":
            raise PermissionError("Only admin can manage automation rules")
        payload = command["rule"]
        if not isinstance(payload, dict):
            raise ValueError("Invalid rule schema")
        _record(payload, {"id", "projectId", "trigger", "conditions", "actions", "enabled"})
        project_id = _identifier(payload["projectId"], "projectId")
        if project_id not in indexed_projects:
            raise ValueError("Project not found")
        receipt_project = project_id
        existing = next((r for r in next_state["rules"] if r["id"] == payload["id"]), None)
        if existing and (existing["projectId"] != project_id or existing["owner"] != actor):
            raise PermissionError("Rule owner/project cannot be reassigned")
        rule = {**deepcopy(payload), "owner": actor, "createdAt": existing["createdAt"] if existing else now}
        _validate_rule(rule)
        if existing:
            next_state["rules"].remove(existing)
        elif len(next_state["rules"]) >= 100:
            raise ValueError("Rule count limit exceeded")
        next_state["rules"].append(rule)
        _activity(next_state, event_id, actor, kind, project_id, None, now)
        result = {"ruleId": rule["id"]}
    elif kind == "rule.delete":
        if user["role"] != "admin":
            raise PermissionError("Only admin can manage automation rules")
        rule_id = _identifier(command["ruleId"], "ruleId")
        rule = next((r for r in next_state["rules"] if r["id"] == rule_id), None)
        if rule is None or rule["owner"] != actor:
            raise PermissionError("Rule is not accessible")
        receipt_project = rule["projectId"]
        next_state["rules"].remove(rule)
        _activity(next_state, event_id, actor, kind, rule["projectId"], None, now)
        result = {"ruleId": rule_id}
    else:
        receipt_project = _card(indexed_cards, command["cardId"])["projectId"]
        result = _execute_rules(next_state, command, actor, user, users, indexed_cards, now)
    next_state["receipts"][event_id] = {
        "fingerprint": fingerprint, "projectId": receipt_project,
        "write": kind not in {"watch.set", "notification.read"},
        "adminOnly": kind in {"rule.upsert", "rule.delete"},
        "result": deepcopy(result),
    }
    validate_state(next_state)
    return {"state": next_state, "changed": True, "result": result}


def list_comments(state, card_id, *, actor, accounts, cards, projects):
    validate_state(state)
    users, indexed_cards, _ = _context(actor, accounts, cards, projects)
    card = _card(indexed_cards, card_id)
    _require(users[actor], card["projectId"])
    return deepcopy([item for item in state["comments"]
                     if item["cardId"] == card_id and item["projectId"] == card["projectId"]])


def list_notifications(state, *, actor, accounts, cards, projects, unread_only=False):
    validate_state(state)
    users, _, _ = _context(actor, accounts, cards, projects)
    _bool(unread_only)
    return deepcopy([item for item in state["notifications"] if item["recipient"] == actor
                     and _permitted(users[actor], item["projectId"])
                     and (not unread_only or item["readAt"] is None)])


def list_rules(state, *, actor, accounts, cards, projects, project_id=None):
    """Only admins may inspect project rules (including automation recipients)."""
    validate_state(state)
    users, _, indexed_projects = _context(actor, accounts, cards, projects)
    if users[actor]["role"] != "admin":
        raise PermissionError("Only admin can inspect automation rules")
    if project_id is not None and project_id not in indexed_projects:
        raise ValueError("Unknown project")
    return deepcopy([item for item in state["rules"]
                     if project_id is None or item["projectId"] == project_id])


def list_activity(state, *, actor, accounts, cards, projects, limit=100):
    validate_state(state)
    users, _, _ = _context(actor, accounts, cards, projects)
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("Invalid activity limit")
    return deepcopy([item for item in reversed(state["activity"])
                     if _permitted(users[actor], item["projectId"])][:limit])


__all__ = ["SCHEMA_VERSION", "TRIGGERS", "empty_state", "validate_state",
           "extract_mentions", "apply_command", "list_comments",
           "list_notifications", "list_activity"]
