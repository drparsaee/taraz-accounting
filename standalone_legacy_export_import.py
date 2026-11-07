"""Offline financial import of a normalized, reviewed previous-system export.

Never guesses proprietary Parsian SQL Server tables. The source must be a
validated JSON export mapped to this documented contract, with an explicit
source currency. Import ALWAYS targets a new independent RIAL database.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from accounting_core import (
    MAX_TOMAN, accounting_view, apply_accounting_command,
    empty_rial_accounting_state, validate_accounting_state,
)
from standalone_accounting import StandaloneAccountingStore, _canonical


class LegacyFinancialImportError(ValueError):
    pass


def _shape(obj, required, optional=()):
    if type(obj) is not dict or not set(required) <= obj.keys() or set(obj) - set(required) - set(optional):
        raise LegacyFinancialImportError("Unexpected previous-accounting export fields")


def _money(value, currency):
    if type(value) is not int or value < 0:
        raise LegacyFinancialImportError("Invalid previous-accounting amount")
    result = value * (10 if currency == "TOMAN" else 1)
    if result > MAX_TOMAN:
        raise LegacyFinancialImportError("Amount exceeds exact RIAL limit")
    return result


def _read_source(source):
    path = Path(source).absolute()
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 20_000_000:
        raise LegacyFinancialImportError("Expected explicit regular JSON export under 20MB")
    raw = path.read_bytes()
    def no_duplicates(pairs):
        record = {}
        for key, value in pairs:
            if key in record:
                raise LegacyFinancialImportError("Duplicate JSON source key")
            record[key] = value
        return record
    def reject_constant(value):
        raise LegacyFinancialImportError("Invalid JSON numeric constant")
    data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=no_duplicates,
                      parse_constant=reject_constant)
    _shape(data, ("schemaVersion", "currency", "parties", "documents", "settlements"),
           ("openingDeposits",))
    if type(data["schemaVersion"]) is not int or data["schemaVersion"] != 1 or data["currency"] not in ("TOMAN", "RIAL"):
        raise LegacyFinancialImportError("Unsupported explicit source currency/schema")
    for key in ("parties", "documents", "settlements", "openingDeposits"):
        if type(data.get(key, [])) is not list or len(data.get(key, [])) > 5000:
            raise LegacyFinancialImportError("Invalid/bounded source collection")
    return data, sha256(raw).hexdigest()


def _build(data):
    currency = data["currency"]
    state = empty_rial_accounting_state()
    actors = {"migration": {"username": "migration", "role": "admin"}}
    event_counter = 0

    def put(kind, fields, when):
        nonlocal state, event_counter
        event_counter += 1
        command = {"type": kind, "eventId": f"legacy.import.{event_counter}", **fields}
        # Dates are Gregorian YYYY-MM-DD from normalized exports, never Jalali guesses.
        if type(when) is not str or len(when) != 10:
            raise LegacyFinancialImportError("Explicit Gregorian posting date required")
        output = apply_accounting_command(state, command, actor="migration",
                   accounts=actors, now=when+"T23:59:59+00:00")
        if not output["changed"]:
            raise LegacyFinancialImportError("Duplicate migration event")
        state = output["state"]
        return output["result"]

    for party in data["parties"]:
        _shape(party, ("id", "name", "kind"))
        put("party.register", {"partyId": party["id"], "name": party["name"],
                               "kind": party["kind"]}, "2026-01-01")
    for deposit in data.get("openingDeposits", []):
        _shape(deposit, ("id", "accountId", "postingDate", "amount", "note"))
        put("funds.deposit", {
              "accountId": deposit["accountId"], "postingDate": deposit["postingDate"],
              "amount": _money(deposit["amount"], currency),
              "note": deposit["note"]}, deposit["postingDate"])
    for doc in data["documents"]:
        _shape(doc, ("kind", "id", "partyId", "documentDate", "postingDate",
                     "status", "lines", "discount", "tax"), ("note",))
        if doc["kind"] not in ("invoice", "bill") or doc["status"] not in ("draft", "issued"):
            raise LegacyFinancialImportError("Unknown document kind/status")
        if type(doc["lines"]) is not list or not 1 <= len(doc["lines"]) <= 1000:
            raise LegacyFinancialImportError("Invalid source invoice lines")
        lines = []
        for line in doc["lines"]:
            _shape(line, ("description", "quantity", "unitPrice"))
            if type(line["quantity"]) is not int or not 1 <= line["quantity"] <= 1000000:
                raise LegacyFinancialImportError("Invalid source quantity")
            lines.append({"description": line["description"], "quantity": line["quantity"],
                          "unitPrice": _money(line["unitPrice"], currency)})
        fields = {doc["kind"]+"Id": doc["id"], "partyId": doc["partyId"],
                  "documentDate": doc["documentDate"], "lines": lines,
                  "discount": _money(doc["discount"], currency),
                  "tax": _money(doc["tax"], currency),
                  "sourceType": "legacy.export", "sourceId": doc["id"]}
        if doc.get("note"):
            fields["note"] = doc["note"]
        put(doc["kind"]+".create", fields, doc["documentDate"])
        if doc["status"] == "issued":
            put(doc["kind"]+".approve", {doc["kind"]+"Id": doc["id"]}, doc["postingDate"])
            put(doc["kind"]+".issue", {doc["kind"]+"Id": doc["id"],
                                      "postingDate": doc["postingDate"]}, doc["postingDate"])
    for settlement in data["settlements"]:
        _shape(settlement, ("kind", "id", "partyId", "accountId", "postingDate",
                            "allocations"))
        kind = settlement["kind"]
        if kind not in ("receipt", "payment"):
            raise LegacyFinancialImportError("Unknown settlement kind")
        if type(settlement["allocations"]) is not list:
            raise LegacyFinancialImportError("Invalid source allocations")
        key = "invoiceId" if kind == "receipt" else "billId"
        allocations = []
        for allocation in settlement["allocations"]:
            _shape(allocation, ("documentId", "amount"))
            allocations.append({key: allocation["documentId"],
                                "amount": _money(allocation["amount"], currency)})
        put(kind+".record", {kind+"Id": settlement["id"],
             "partyId": settlement["partyId"], "accountId": settlement["accountId"],
             "postingDate": settlement["postingDate"], "allocations": allocations},
            settlement["postingDate"])
    validate_accounting_state(state)
    return state


def import_reviewed_export(source, destination, *, apply=False, offline_ack=False,
                           plaintext_ack=False):
    if offline_ack is not True or plaintext_ack is not True:
        raise PermissionError("OFFLINE and plaintext financial import acknowledgment required")
    dest = Path(destination).absolute()
    if (dest.name != "standalone-accounting.sqlite3" or dest.exists()
            or dest.is_symlink() or not dest.parent.is_dir()
            or dest.parent.is_symlink()):
        raise LegacyFinancialImportError("Use a NEW standalone-accounting.sqlite3 destination")
    data, source_sha = _read_source(source)
    state = _build(data)
    accounts = {"audit": {"username": "audit", "role": "admin"}}
    view = accounting_view(state, actor="audit", accounts=accounts)
    report = {"preview": not apply, "currency": "RIAL",
              "sourceSha256": source_sha, "events": len(state["events"]),
              "parties": len(view["parties"]), "invoices": len(view["invoices"]),
              "bills": len(view["bills"]), "receipts": len(view["receipts"]),
              "payments": len(view["payments"]), "sourceUnchanged": True}
    if not apply:
        return report
    with tempfile.TemporaryDirectory(dir=dest.parent,prefix="madar-legacy-validated-") as tmp:
        temporary = Path(tmp) / dest.name
        store = StandaloneAccountingStore(temporary, default_currency="RIAL")
        if state["events"]:
            with store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    store._write(conn, 0, len(state["events"]), _canonical(state))
                    conn.execute("COMMIT")
                except BaseException:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
        readback = store.read(actor="audit",accounts=accounts)
        if (readback["revision"] != len(state["events"])
                or readback["view"]["currency"] != "RIAL"):
            raise LegacyFinancialImportError("Imported ledger readback failed")
        with closing(sqlite3.connect(temporary, isolation_level=None)) as conn:
            result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if result is not None and result[0]:
                raise LegacyFinancialImportError("SQLite backup checkpoint failed")
            if conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() != "delete":
                raise LegacyFinancialImportError("Portable database mode failed")
        os.link(temporary, dest)  # New name only; no-clobber atomic publication.
    return {**report, "preview": False, "destination": str(dest)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reviewed normalized financial export -> NEW RIAL ledger")
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--offline-ack", action="store_true")
    parser.add_argument("--plaintext-ack", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    print(import_reviewed_export(args.source, args.destination, apply=args.apply,
                                 offline_ack=args.offline_ack,
                                 plaintext_ack=args.plaintext_ack))


if __name__ == "__main__":
    main()
