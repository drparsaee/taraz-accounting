"""M-08 independent, pure, append-only double-entry general ledger kernel.

No disk, network, native host, finance.py, app_storage.py, clocks, or automatic
invoice posting. The caller authenticates the actor and CAS-commits the whole
returned state. Integer amounts are exact whole tomans.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from hashlib import sha256
import json
import re


SCHEMA_VERSION = 1
CURRENCY = "TOMAN"
MAX_TOMAN = 10**15
MAX_EVENTS = 10_000
MAX_LINES = 200
MAX_STATE_BYTES = 12_000_000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z", re.ASCII)
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z", re.ASCII)
_KINDS = frozenset(("asset", "liability", "equity", "revenue", "expense"))
_DEBIT_NORMAL = frozenset(("asset", "expense"))
_ZERO_HASH = "0" * 64


def _object(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(f"{label}: missing or unexpected fields")
    return value


def _id(value, label):
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label}: invalid identifier")
    return value


def _text(value, label, limit=500):
    if (type(value) is not str or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError(f"{label}: invalid text")
    return value


def _int(value, label, *, positive=False):
    if (type(value) is not int or value < (1 if positive else 0)
            or value > MAX_TOMAN):
        raise ValueError(f"{label}: whole positive/nonnegative integer tomans required")
    return value


def _day(value):
    if type(value) is not str or not _DATE.fullmatch(value):
        raise ValueError("postingDate: expected YYYY-MM-DD")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Noncanonical postingDate")
    except ValueError as exc:
        raise ValueError("postingDate: invalid calendar day") from exc
    return value


def _time(value):
    if type(value) is not str or not _STAMP.fullmatch(value):
        raise ValueError("at: timezone-aware ISO timestamp required")
    try:
        if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError("Missing timezone")
    except ValueError as exc:
        raise ValueError("at: invalid timestamp") from exc
    return value


def _canonical(value):
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("Only finite JSON-compatible values are allowed") from exc
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError("GL data exceeds 12 MB limit")
    return raw


def _hash(value):
    return sha256(_canonical(value)).hexdigest()


def _copy(value):
    return json.loads(_canonical(value).decode("utf-8"))


def _require_admin(actor, accounts):
    """The host must supply its authoritative accounts for EVERY write/read."""
    _id(actor, "actor")
    if type(accounts) is dict:
        users = []
        for key, record in accounts.items():
            if type(record) is not dict or record.get("username") != key:
                raise ValueError("Authoritative account index mismatch")
            users.append(record)
    elif type(accounts) is list:
        users = accounts
    else:
        raise PermissionError("Authoritative authentication is required")
    known = {}
    for record in users:
        if type(record) is not dict:
            raise ValueError("Invalid account record")
        name = _id(record.get("username"), "username")
        if name in known or record.get("role") not in ("admin", "editor", "viewer"):
            raise ValueError("Duplicate or invalid account")
        known[name] = record
    if actor not in known or known[actor]["role"] != "admin":
        raise PermissionError("Only authenticated GL administrator is permitted")


def empty_gl_state():
    return {"schemaVersion": SCHEMA_VERSION, "currency": CURRENCY, "events": []}


def _new_projection():
    return {"accounts": {}, "journals": [], "journalIndex": {},
            "reversed": set(), "eventIndex": {}}


def _command_shape(command):
    if type(command) is not dict:
        raise ValueError("Invalid GL command")
    schema = {
        "account.create": {"type", "eventId", "accountId", "name", "kind"},
        "journal.post": {"type", "eventId", "journalId", "postingDate",
                         "description", "lines"},
        "journal.reverse": {"type", "eventId", "journalId",
                            "reversesJournalId", "postingDate", "reason"},
    }
    kind = command.get("type")
    if type(kind) is not str or kind not in schema:
        raise ValueError("Unsupported GL command")
    _object(command, schema[kind], "command")
    _id(command["eventId"], "eventId")
    return kind


def _lines(value, accounts):
    if type(value) is not list or not 2 <= len(value) <= MAX_LINES:
        raise ValueError("Journal must have 2 to 200 lines")
    result = []
    seen = set()
    debits = credits = 0
    for index, line in enumerate(value):
        _object(line, {"accountId", "debit", "credit"}, f"lines[{index}]")
        account_id = _id(line["accountId"], "accountId")
        if account_id not in accounts:
            raise ValueError("Unknown journal account")
        if account_id in seen:
            raise ValueError("Journal account duplicated; consolidate before posting")
        seen.add(account_id)
        debit = _int(line["debit"], "debit")
        credit = _int(line["credit"], "credit")
        if (debit > 0) == (credit > 0):
            raise ValueError("Each journal line requires exactly one positive side")
        debits = _int(debits + debit, "journal total")
        credits = _int(credits + credit, "journal total")
        result.append({"accountId": account_id, "debit": debit, "credit": credit})
    if debits == 0 or debits != credits:
        raise ValueError("Unbalanced journal: total debit must equal total credit")
    return result, debits


def _transition(projection, command, at):
    kind = _command_shape(command)
    event_id = command["eventId"]
    accounts = projection["accounts"]
    if kind == "account.create":
        account_id = _id(command["accountId"], "accountId")
        name = _text(command["name"], "account name", 180)
        account_kind = command["kind"]
        if type(account_kind) is not str or account_kind not in _KINDS:
            raise ValueError("Unsupported chart-of-accounts kind")
        if account_id in accounts:
            raise ValueError("GL account already exists")
        accounts[account_id] = {"id": account_id, "name": name, "kind": account_kind,
                                "normalSide": "debit" if account_kind in _DEBIT_NORMAL else "credit"}
        return {"type": kind, "eventId": event_id, "accountId": account_id}

    journal_id = _id(command["journalId"], "journalId")
    if journal_id in projection["journalIndex"]:
        raise ValueError("Duplicate journal identifier")
    when = _day(command["postingDate"])
    if when > at[:10]:
        raise ValueError("Posting in the future is not allowed")

    if kind == "journal.post":
        description = _text(command["description"], "description", 500)
        lines, total = _lines(command["lines"], accounts)
        reversed_id = None
    else:
        target_id = _id(command["reversesJournalId"], "reversesJournalId")
        target = projection["journalIndex"].get(target_id)
        if target is None or target["type"] != "journal.post":
            raise ValueError("Only a previously posted journal can be reversed")
        if target_id in projection["reversed"]:
            raise ValueError("Journal already reversed")
        if when < target["postingDate"]:
            raise ValueError("Reversal predates original posting")
        description = _text(command["reason"], "reversal reason", 500)
        lines = [{"accountId": line["accountId"], "debit": line["credit"],
                  "credit": line["debit"]} for line in target["lines"]]
        lines, total = _lines(lines, accounts)
        reversed_id = target_id
        projection["reversed"].add(target_id)

    journal = {"id": journal_id, "type": kind, "eventId": event_id,
               "postingDate": when, "description": description, "lines": lines,
               "total": total, "reversesJournalId": reversed_id}
    projection["journals"].append(journal)
    projection["journalIndex"][journal_id] = journal
    return {"type": kind, "eventId": event_id, "journalId": journal_id,
            "reversesJournalId": reversed_id, "total": total}


def _replay(state):
    _object(state, {"schemaVersion", "currency", "events"}, "GL state")
    if type(state["schemaVersion"]) is not int or state["schemaVersion"] != SCHEMA_VERSION:
        raise ValueError("Unsupported GL schema version")
    if state["currency"] != CURRENCY:
        raise ValueError("GL currency must be TOMAN")
    events = state["events"]
    if type(events) is not list or len(events) > MAX_EVENTS:
        raise ValueError("Invalid or oversized GL events")
    _canonical(state)
    projection = _new_projection()
    previous = _ZERO_HASH
    for number, entry in enumerate(events, start=1):
        _object(entry, {"seq", "actor", "at", "command", "fingerprint",
                        "result", "prevHash", "hash"}, "GL event")
        if type(entry["seq"]) is not int or entry["seq"] != number:
            raise ValueError("GL event sequence mismatch")
        _id(entry["actor"], "historical actor")
        _time(entry["at"])
        _command_shape(entry["command"])
        event_id = entry["command"]["eventId"]
        if event_id in projection["eventIndex"]:
            raise ValueError("Duplicate GL eventId")
        expected_fingerprint = _hash([entry["actor"], entry["command"]])
        if entry["fingerprint"] != expected_fingerprint:
            raise ValueError("GL event fingerprint mismatch")
        if entry["prevHash"] != previous or type(entry["hash"]) is not str or not _HASH.fullmatch(entry["hash"]):
            raise ValueError("GL hash chain mismatch")
        body = {k: v for k, v in entry.items() if k != "hash"}
        if entry["hash"] != _hash(body):
            raise ValueError("GL event content hash mismatch")
        computed = _transition(projection, entry["command"], entry["at"])
        if entry["result"] != computed:
            raise ValueError("GL event outcome mismatch")
        projection["eventIndex"][event_id] = entry
        previous = entry["hash"]
    return projection


def validate_gl_state(state):
    """Full replay validates strict event shapes, hashes and accounting invariants."""
    _replay(state)
    return True


def apply_gl_command(state, command, *, actor, accounts, now):
    """Pure command handler; caller owns authentication source and atomic CAS commit.

    Returns {state, changed, result}; rejects invalid commands without mutating
    the input. Exact retries replay the original result after rechecking ACL.
    """
    _require_admin(actor, accounts)
    now = _time(now)
    _command_shape(command)
    command = _copy(command)
    projection = _replay(state)
    event_id = command["eventId"]
    fingerprint = _hash([actor, command])
    existing = projection["eventIndex"].get(event_id)
    if existing is not None:
        if existing["fingerprint"] != fingerprint:
            raise ValueError("Idempotency eventId reused for different actor/command")
        return {"state": _copy(state), "changed": False, "result": _copy(existing["result"])}
    if len(state["events"]) >= MAX_EVENTS:
        raise ValueError("GL event limit reached")
    result = _transition(projection, command, now)
    event = {"seq": len(state["events"]) + 1, "actor": actor, "at": now,
             "command": command, "fingerprint": fingerprint,
             "result": result,
             "prevHash": state["events"][-1]["hash"] if state["events"] else _ZERO_HASH}
    event["hash"] = _hash(event)
    candidate = _copy(state)
    candidate["events"].append(event)
    validate_gl_state(candidate)
    return {"state": candidate, "changed": True, "result": _copy(result)}


def _trial(projection, through_date=None):
    if through_date is not None:
        _day(through_date)
    balances = {aid: {"debitTurnover": 0, "creditTurnover": 0}
                for aid in projection["accounts"]}
    for journal in projection["journals"]:
        if through_date is not None and journal["postingDate"] > through_date:
            continue
        for line in journal["lines"]:
            item = balances[line["accountId"]]
            item["debitTurnover"] += line["debit"]
            item["creditTurnover"] += line["credit"]
    rows = []
    totals = {"debitTurnover": 0, "creditTurnover": 0,
              "debitBalance": 0, "creditBalance": 0}
    for aid, account in sorted(projection["accounts"].items()):
        values = balances[aid]
        net = values["debitTurnover"] - values["creditTurnover"]
        row = {**account, **values, "debitBalance": max(net, 0),
               "creditBalance": max(-net, 0),
               "normalBalance": net if account["normalSide"] == "debit" else -net}
        for field in totals:
            totals[field] += row[field]
        rows.append(row)
    if totals["debitTurnover"] != totals["creditTurnover"] or totals["debitBalance"] != totals["creditBalance"]:
        raise ValueError("Trial balance invariant violated")
    return {"currency": CURRENCY, "throughDate": through_date,
            "accounts": rows, "totals": totals, "balanced": True}


def trial_balance(state, *, actor, accounts, through_date=None):
    _require_admin(actor, accounts)
    return _trial(_replay(state), through_date)


def gl_view(state, *, actor, accounts):
    _require_admin(actor, accounts)
    projection = _replay(state)
    return _copy({
        "currency": CURRENCY,
        "accounts": [value for _, value in sorted(projection["accounts"].items())],
        "journals": projection["journals"],
        "reversedJournalIds": sorted(projection["reversed"]),
        "trialBalance": _trial(projection),
        "lastEventHash": state["events"][-1]["hash"] if state["events"] else _ZERO_HASH,
    })


__all__ = ("SCHEMA_VERSION", "MAX_TOMAN", "empty_gl_state", "validate_gl_state",
           "apply_gl_command", "trial_balance", "gl_view")
