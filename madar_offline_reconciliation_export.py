"""Prepare the MADAR side from a verified portable standalone backup, read-only.

The input is a portable SQLite BACKUP, never an active SQLite WAL database.
The output is an untrusted-but-structurally-verified comparison snapshot in
memory; it does not modify SQL, source backup, application state or filesystem.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path

from accounting_core import accounting_view
from accounting_reporting import ledger_reports
from parsian_reconciliation_gate import _id, _whole_date, validate_snapshot
from standalone_accounting import _decode_checked
from standalone_accounting_backup import _readonly_sqlite
from standalone_accounting_restore import _check_input

_AUDITOR = {"migration-auditor": {"username": "migration-auditor",
                                  "role": "admin"}}


def build_madar_comparison_snapshot(backup: str | Path, *,
                                    company_ref: str, as_of: str) -> dict:
    """Verified SQLite snapshot -> reviewed report structure; no disk output.

    Export labels and business mappings should be matched to the Parsian
    archive only AFTER independent human review of a detached SQL clone.
    This export does not infer cross-system identifiers or source currency.
    """
    path = Path(backup)
    _id(company_ref, "company reference")
    _whole_date(as_of, "as-of date")
    # Block active account DB even if it happens to be closed. Never initialize.
    if (not path.name.startswith("standalone-accounting-auto-") or
            not path.name.endswith(".sqlite3")):
        raise ValueError("Requires an automatically validated standalone accounting backup")
    head, _ = _check_input(path)
    with closing(_readonly_sqlite(path)) as database:
        rows = database.execute(
            "SELECT revision,state,digest FROM standalone_accounting").fetchall()
    if head == 0:
        # Revision-zero snapshots have NO persisted currency discriminator.
        # Guessing that the book was created with RIAL risks silently treating
        # a legacy TOMAN baseline as a RIAL file. Fail closed.
        raise ValueError("Cannot infer RIAL/TOMAN currency from an empty backup")
    if len(rows) != 1 or rows[0][0] != head:
        raise ValueError("Accounting backup changed during read")
    state = _decode_checked(rows[0][1], rows[0][2])
    view = accounting_view(state, actor="migration-auditor", accounts=_AUDITOR)
    if view["currency"] != "RIAL":
        raise ValueError("Target backup must use standalone RIAL, not a legacy TOMAN book")
    reports = ledger_reports(view, through_date=as_of)
    def posted_before(document):
        return (document.get("status") == "issued" and
                type(document.get("postingDate")) is str and
                document["postingDate"] <= as_of)
    # Records may be reversed; document count is original issue count, not
    # number of post-reversal open invoices. Compare this definition explicitly.
    result = {
        "schemaVersion": 1,
        "sourceSystem": "MADAR",
        "companyRef": company_ref,
        "asOf": as_of,
        "currency": "RIAL",
        "trialBalance": [
            {"id": row["accountId"], "debit": row["debit"], "credit": row["credit"]}
            for row in reports["trialBalance"]["rows"]
        ],
        "parties": [
            {"id": row["partyId"], "receivable": row["receivable"],
             "payable": row["payable"]}
            for row in reports["counterpartyBalances"]
        ],
        "cashBanks": [
            {"id": row["accountId"], "balance": row["balance"]}
            for row in reports["cashBankBalances"]
        ],
        "controlTotals": {
            "receivable": sum(row["receivable"] for row in
                              reports["counterpartyBalances"]),
            "payable": sum(row["payable"] for row in
                           reports["counterpartyBalances"]),
            "cashBank": sum(row["balance"] for row in
                            reports["cashBankBalances"]),
        },
        "documentCounts": {
            "journals": reports["journalCountThroughDate"],
            "salesInvoices": sum(posted_before(x) for x in view["invoices"].values()),
            "purchaseBills": sum(posted_before(x) for x in view["bills"].values()),
            "receipts": sum(x["date"] <= as_of for x in view["receipts"].values()),
            "payments": sum(x["date"] <= as_of for x in view["payments"].values()),
            # These independent subledgers are NOT integrated in this book.
            # A nonzero corresponding Parsian source MUST fail reconciliation.
            "inventoryMovements": 0,
            "cheques": 0,
        },
    }
    validate_snapshot(result, kind="target")
    return result


__all__ = ["build_madar_comparison_snapshot"]
