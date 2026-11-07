"""Explicit OFFLINE, no-clobber conversion of a legacy standalone TOMAN ledger.

Creates a NEW RIAL v2 database, leaving the original immutable. Replays each
original command with exactly scaled money and preserved actor/event lineage.
Proprietary Parsian backups are NOT an input to this tool.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from copy import deepcopy
import os
from pathlib import Path
import sqlite3
import tempfile

from accounting_core import (
    MAX_TOMAN, accounting_view, apply_accounting_command,
    empty_rial_accounting_state, validate_accounting_state,
)
from standalone_accounting import StandaloneAccountingStore, _decode_checked
from standalone_accounting_restore import _check_input, _check_new_destination


class RialMigrationError(ValueError):
    pass


def _times_ten(number):
    if type(number) is not int or number < 0 or number > MAX_TOMAN // 10:
        raise RialMigrationError("Legacy amount exceeds exact RIAL ledger capacity")
    return number * 10


def _convert_command(original):
    command = deepcopy(original)
    kind = command.get("type")
    if kind in {"invoice.create", "invoice.update", "bill.create", "bill.update",
                "proforma.create", "proforma.update"}:
        for line in command["lines"]:
            line["unitPrice"] = _times_ten(line["unitPrice"])
        for key in ("discount", "tax"):
            if key in command:
                command[key] = _times_ten(command[key])
    elif kind in {"contractor.job.intake", "contractor.job.price"}:
        if command["currency"] != "TOMAN":
            raise RialMigrationError("Unexpected non-TOMAN contractor history")
        command["currency"] = "RIAL"
        if command.get("unitPrice") is not None:
            command["unitPrice"] = _times_ten(command["unitPrice"])
    elif kind in {"receipt.record", "payment.record"}:
        for allocation in command["allocations"]:
            allocation["amount"] = _times_ten(allocation["amount"])
    elif kind in {"funds.deposit", "funds.transfer"}:
        command["amount"] = _times_ten(command["amount"])
    elif kind == "journal.manual":
        for line in command["lines"]:
            for key in ("debit", "credit"):
                line[key] = _times_ten(line[key])
    elif kind not in {
        "party.register", "account.create", "item.create", "item.update",
        "proforma.send", "proforma.accept", "proforma.reject",
        "proforma.cancel", "proforma.convert",
        "contractor.job.approve", "contractor.bill.create", "invoice.approve",
        "bill.approve", "invoice.cancel", "bill.cancel", "invoice.issue",
        "bill.issue", "journal.reverse", "period.close",
    }:
        raise RialMigrationError("Unknown legacy command; no safe conversion policy")
    return command


def _scaled_view_consistent(old, new):
    """Compare cross-ledger balances, document lifecycle and job identities."""
    for group in ("proformas", "invoices", "bills", "contractorJobs", "receipts", "payments"):
        if set(old[group]) != set(new[group]):
            raise RialMigrationError("Business IDs differ after migration: " + group)
    if set(old["parties"]) != set(new["parties"]):
        raise RialMigrationError("Party identities differ after migration")
    for party_id in old["parties"]:
        a, b = old["parties"][party_id], new["parties"][party_id]
        for key in ("receivable", "payable", "netReceivable"):
            if b[key] != a[key] * 10:
                raise RialMigrationError("Party balances differ after migration")
    for account_id, old_account in old["accounts"].items():
        new_account = new["accounts"].get(account_id)
        if new_account is None:
            raise RialMigrationError("Account missing in converted ledger")
        for key in ("debitMinusCredit", "normalBalance"):
            if new_account[key] != old_account[key] * 10:
                raise RialMigrationError("Ledger balance differs after migration")
    for group in ("invoices", "bills"):
        for doc_id, a in old[group].items():
            b = new[group][doc_id]
            if (b["status"] != a["status"] or b["partyId"] != a["partyId"]
                    or b["total"] != a["total"] * 10
                    or b["allocated"] != a["allocated"] * 10):
                raise RialMigrationError("Document reconciliation failed")
    for ident, a in old.get("proformas", {}).items():
        b = new["proformas"][ident]
        if (b["status"] != a["status"] or b["partyId"] != a["partyId"]
                or b["convertedInvoiceId"] != a["convertedInvoiceId"]
                or b["total"] != a["total"] * 10):
            raise RialMigrationError("Proforma reconciliation failed")
    for job_id, a in old["contractorJobs"].items():
        b = new["contractorJobs"][job_id]
        if (a["status"] != b["status"] or a["quantity"] != b["quantity"]
                or b["unitPrice"] != (a["unitPrice"] * 10 if a["unitPrice"] is not None else None)
                or b["currency"] != "RIAL"):
            raise RialMigrationError("Contractor job reconciliation failed")
    if len(old["journals"]) != len(new["journals"]):
        raise RialMigrationError("Journal entry count differs after migration")
    for a, b in zip(old["journals"], new["journals"]):
        if len(a["lines"]) != len(b["lines"]):
            raise RialMigrationError("Journal line count differs after migration")
        for original, converted in zip(a["lines"], b["lines"]):
            if any(converted[key] != original[key] * 10 for key in ("debit", "credit")):
                raise RialMigrationError("Journal posting amount differs after migration")


def convert_state(old):
    validate_accounting_state(old)
    if old.get("schemaVersion") != 1 or old.get("currency") != "TOMAN":
        raise RialMigrationError("Only version 1 TOMAN accounting can be converted")
    state = empty_rial_accounting_state()
    for event in old["events"]:
        account = {"username": event["actor"], "role": event["role"],
                   "financeEdit": event["financeEdit"]}
        output = apply_accounting_command(
            state, _convert_command(event["command"]),
            actor=event["actor"], accounts={event["actor"]: account},
            now=event["at"])
        if output["changed"] is not True:
            raise RialMigrationError("Unexpected repeated legacy event")
        state = output["state"]
    validate_accounting_state(state)
    inspector = {"audit": {"username": "audit", "role": "admin"}}
    old_view = accounting_view(old, actor="audit", accounts=inspector)
    new_view = accounting_view(state, actor="audit", accounts=inspector)
    _scaled_view_consistent(old_view, new_view)
    return state


def migrate_offline(source, destination, *, offline_acknowledged=False,
                    plaintext_acknowledged=False, apply=False):
    if offline_acknowledged is not True or plaintext_acknowledged is not True:
        raise PermissionError("Explicit OFFLINE and plaintext acknowledgements required")
    src, dest = Path(source).absolute(), Path(destination).absolute()
    _check_new_destination(src, dest)
    _check_input(src)  # Check portable backup shape and immutable event replay.
    with closing(sqlite3.connect(src.as_uri() + "?mode=ro", uri=True)) as conn:
        row = conn.execute("SELECT state,digest FROM standalone_accounting WHERE id=1").fetchone()
    if row is None:
        old = {"schemaVersion": 1, "currency": "TOMAN", "events": []}
    else:
        old = _decode_checked(row[0], row[1])
    converted = convert_state(old)
    if not apply:
        return {"preview": True, "events": len(converted["events"]),
                "currency": "RIAL", "sourceUnchanged": True}
    with tempfile.TemporaryDirectory(prefix="madar-rial-migrate-", dir=dest.parent) as folder:
        temporary = Path(folder) / dest.name
        store = StandaloneAccountingStore(temporary, default_currency="RIAL")
        # Persist through the same transaction/CAS boundary as ordinary writes.
        if converted["events"]:
            from standalone_accounting import _canonical
            with store._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    store._write(connection, 0, len(converted["events"]), _canonical(converted))
                    connection.execute("COMMIT")
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
        checker = {"audit": {"username": "audit", "role": "admin"}}
        readback = store.read(actor="audit", accounts=checker)
        if (readback["revision"] != len(converted["events"])
                or readback["view"]["currency"] != "RIAL"):
            raise RialMigrationError("Converted RIAL database failed verification")
        with closing(sqlite3.connect(temporary, isolation_level=None)) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("PRAGMA journal_mode=DELETE")
        os.link(temporary, dest)  # Atomic no-clobber publication, same volume.
    return {"preview": False, "events": len(converted["events"]),
            "currency": "RIAL", "sourceUnchanged": True, "destination": str(dest)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="OFFLINE TOMAN v1 to RIAL v2 migration")
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--offline-ack", action="store_true")
    parser.add_argument("--plaintext-ack", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    print(migrate_offline(args.source, args.destination,
                          offline_acknowledged=args.offline_ack,
                          plaintext_acknowledged=args.plaintext_ack,
                          apply=args.apply))


if __name__ == "__main__":
    main()
