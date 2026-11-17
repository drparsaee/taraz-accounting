"""Strict preflight contract for historical AR/AP opening balances.

NO ledger mutation here. This module validates the shape and internal
reconciliation of a candidate opening batch. Its source digest is an external
provenance assertion, NOT proof that the originating Parsian data was verified.
The accounting kernel and trusted host must enforce authority separately.
"""
from __future__ import annotations

from datetime import date
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_MAX_AMOUNT = 10**15
_MAX_ROWS = 5000


def _date(value, key):
    if type(value) is not str or not _DATE.fullmatch(value):
        raise ValueError(f"Invalid {key}; use YYYY-MM-DD")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError(f"Noncanonical {key}")
    except ValueError as error:
        raise ValueError(f"Invalid {key}") from error


def _identifier(value, key):
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {key}")


def inspect_opening_batch(command: dict) -> dict:
    """Return a read-only reconciliation preview, never permission to post.

    RIAL only: we refuse implicit TOMAN migration or currency reinterpretation.
    Historical amount and source authenticity require independent evidence.
    """
    keys = {"type", "eventId", "sourceId", "sourceDigest", "postingDate",
            "fiscalStartDate", "currency", "rows", "expectedReceivableRial",
            "expectedPayableRial"}
    if type(command) is not dict or set(command) != keys:
        raise ValueError("Opening requires an exact versioned command shape")
    if command["type"] != "opening.balance.post":
        raise ValueError("Unknown opening operation")
    for key in ("eventId", "sourceId"):
        _identifier(command[key], key)
    if (type(command["sourceDigest"]) is not str
            or not _SHA256.fullmatch(command["sourceDigest"])):
        raise ValueError("Invalid verified-source SHA-256 format")
    if command["currency"] != "RIAL" or type(command["currency"]) is not str:
        raise ValueError("Historical opening requires explicit RIAL currency")
    for key in ("postingDate", "fiscalStartDate"):
        _date(command[key], key)
    if command["postingDate"] < command["fiscalStartDate"]:
        raise ValueError("Opening posting cannot precede fiscal period start")
    rows = command["rows"]
    if type(rows) is not list or not 1 <= len(rows) <= _MAX_ROWS:
        raise ValueError("Opening requires 1..5000 explicit rows")
    identifiers = set()
    receivable = payable = 0
    for row in rows:
        if type(row) is not dict or set(row) != {"sourceRef", "partyId", "direction", "amountRial"}:
            raise ValueError("Opening row has missing or unknown fields")
        _identifier(row["sourceRef"], "sourceRef")
        _identifier(row["partyId"], "partyId")
        if row["sourceRef"] in identifiers:
            raise ValueError("Duplicate opening sourceRef")
        identifiers.add(row["sourceRef"])
        if row["direction"] not in ("receivable", "payable"):
            raise ValueError("Unknown opening balance direction")
        amount = row["amountRial"]
        if type(amount) is not int or not 1 <= amount <= _MAX_AMOUNT:
            raise ValueError("Opening amount must be an exact positive RIAL integer")
        if row["direction"] == "receivable":
            receivable += amount
        else:
            payable += amount
        if receivable > _MAX_AMOUNT or payable > _MAX_AMOUNT:
            raise ValueError("Opening aggregate amount exceeds ledger bound")
    for field, total in (("expectedReceivableRial", receivable),
                         ("expectedPayableRial", payable)):
        expected = command[field]
        if type(expected) is not int or expected < 0 or expected > _MAX_AMOUNT or expected != total:
            raise ValueError(f"Opening source reconciliation mismatch: {field}")
    return {
        "status": "CONTRACT_ONLY_NOT_POSTED",
        "postingAllowed": False,
        "currency": "RIAL",
        "sourceId": command["sourceId"],
        "rowCount": len(rows),
        "receivableRial": receivable,
        "payableRial": payable,
        "netRial": receivable - payable,
        "sourceDigest": command["sourceDigest"],
    }
