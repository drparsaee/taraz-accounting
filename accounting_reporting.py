"""Read-only double-entry reports from the verified Madar accounting projection.

All reports are company-wide (never silently misrepresented as per-project).
No file, tax policy, external banking integration or source DB access.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from accounting_operational_extensions import pending_goods_issues


def _day(value, name):
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("Invalid " + name)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Invalid " + name) from error
    if parsed.isoformat() != value:
        raise ValueError("Invalid " + name)
    return value


def ledger_reports(view, *, from_date=None, through_date=None):
    """Trial balance, ledger statements, P&L and balance sheet in exact ledger units.

    A caller MUST supply an authenticated `accounting_view` projection; this
    helper is pure but is not an authorization boundary. Includes historical
    reversal postings (never erases entries). `from_date` bounds movements,
    while ending balances are accumulated from inception through `through_date`.
    """
    if type(view) is not dict or view.get("currency") not in ("TOMAN", "RIAL"):
        raise ValueError("Expected verified RIAL/TOMAN ledger projection")
    first = _day(from_date, "from_date")
    last = _day(through_date, "through_date")
    if first and last and first > last:
        raise ValueError("Report start after end")
    accounts = view.get("accounts")
    journals = view.get("journals")
    if type(accounts) is not dict or type(journals) is not list:
        raise ValueError("Invalid accounting projection")
    initial = {ident: 0 for ident in accounts}
    balances = dict(initial)
    movement = {ident: {"debit": 0, "credit": 0} for ident in accounts}
    # Fiscal closing entries correctly affect account balances and the trial
    # balance, but must not erase operational P&L for the fiscal year.
    operational_movement = {ident: {"debit": 0, "credit": 0} for ident in accounts}
    ledger = {ident: [] for ident in accounts}
    party_net = {}
    count = 0
    for entry in sorted(enumerate(journals), key=lambda p: (p[1]["date"], p[0])):
        _, journal = entry
        day = _day(journal["date"], "journal date")
        if last is not None and day > last:
            continue
        count += 1
        for line in journal["lines"]:
            aid = line["accountId"]
            if aid not in accounts:
                raise ValueError("Unknown report account")
            debit, credit = line["debit"], line["credit"]
            if type(debit) is not int or type(credit) is not int or debit < 0 or credit < 0:
                raise ValueError("Invalid report amounts")
            balances[aid] += debit - credit
            if aid in ("1200", "2000"):
                party_id = line.get("partyId")
                if (type(party_id) is not str or not party_id
                        or party_id not in view.get("parties", {})):
                    raise ValueError("Receivable/payable posting requires a known party")
                party_net[(aid, party_id)] = party_net.get((aid, party_id), 0) + debit - credit
            if first is None or day >= first:
                movement[aid]["debit"] += debit
                movement[aid]["credit"] += credit
                if journal["sourceType"] != "fiscal.year.close":
                    operational_movement[aid]["debit"] += debit
                    operational_movement[aid]["credit"] += credit
                ledger[aid].append({"date": day, "journalId": journal["id"],
                                    "sourceType": journal["sourceType"],
                                    "sourceId": journal["sourceId"],
                                    "debit": debit, "credit": credit,
                                    "partyId": line.get("partyId"),
                                    "balanceDebitMinusCredit": balances[aid]})
    rows = []
    for aid, meta in sorted(accounts.items()):
        signed = balances[aid]
        rows.append({"accountId": aid, "name": meta["name"], "kind": meta["kind"],
                     "debit": max(signed, 0), "credit": max(-signed, 0),
                     "debitMovement": movement[aid]["debit"],
                     "creditMovement": movement[aid]["credit"],
                     "balanceDebitMinusCredit": signed})
    debit_total = sum(row["debit"] for row in rows)
    credit_total = sum(row["credit"] for row in rows)
    if debit_total != credit_total:
        raise ValueError("Trial balance mismatch")
    # Income/expense movements in the selected interval; closing retained
    # earnings is a presentation adjustment, NOT an unposted journal entry.
    period_net = sum(operational_movement[r["accountId"]]["credit"] -
                     operational_movement[r["accountId"]]["debit"] for r in rows
                     if r["kind"] == "revenue") - sum(
                         operational_movement[r["accountId"]]["debit"] -
                         operational_movement[r["accountId"]]["credit"] for r in rows
                         if r["kind"] == "expense")
    lifetime_net = sum(-balances[r["accountId"]] for r in rows if r["kind"] == "revenue") - sum(
        balances[r["accountId"]] for r in rows if r["kind"] == "expense")
    assets = sum(balances[r["accountId"]] for r in rows if r["kind"] == "asset")
    liabilities = sum(-balances[r["accountId"]] for r in rows if r["kind"] == "liability")
    capital = sum(-balances[r["accountId"]] for r in rows if r["kind"] == "equity")
    if assets != liabilities + capital + lifetime_net:
        raise ValueError("Balance sheet does not reconcile")
    counterparties = []
    parties = view.get("parties", {})
    if type(parties) is not dict:
        raise ValueError("Invalid counterparties")
    for party_id, party in sorted(parties.items()):
        receivable = party_net.get(("1200", party_id), 0)
        payable = -party_net.get(("2000", party_id), 0)
        if receivable < 0 or payable < 0:
            raise ValueError("Negative counterparty control balance")
        if last is None and (party.get("receivable") != receivable or
                             party.get("payable") != payable):
            raise ValueError("Counterparty subledger and GL do not reconcile")
        counterparties.append({"partyId": party_id, "name": party["name"],
                               "receivable": receivable, "payable": payable,
                               "netReceivable": receivable - payable})
    if (sum(x["receivable"] for x in counterparties) != balances.get("1200", 0)
            or sum(x["payable"] for x in counterparties) != -balances.get("2000", 0)):
        raise ValueError("AR/AP control account mismatch")
    liquid_accounts = []
    for account_id, account in sorted(accounts.items()):
        if account["liquid"]:
            liquid_accounts.append({"accountId": account_id, "name": account["name"],
                                    "balance": balances[account_id]})
    pending_cogs = pending_goods_issues(view, through_date=last)
    return deepcopy({"currency": view["currency"], "scope": "all-projects",
                     "fromDate": first, "throughDate": last,
                     "journalCountThroughDate": count,
                     "trialBalance": {"rows": rows, "totalDebit": debit_total,
                                      "totalCredit": credit_total},
                     "accountStatements": ledger,
                     "counterpartyBalances": counterparties,
                     "cashBankBalances": liquid_accounts,
                     "reconciled": True,
                     "profitLossComplete": not pending_cogs,
                     "unpostedGoodsIssues": pending_cogs,
                     "profitLoss": {"revenue": sum(
                         operational_movement[r["accountId"]]["credit"] -
                         operational_movement[r["accountId"]]["debit"] for r in rows if r["kind"] == "revenue"),
                                    "expense": sum(
                                        operational_movement[r["accountId"]]["debit"] -
                                        operational_movement[r["accountId"]]["credit"] for r in rows
                                        if r["kind"] == "expense"),
                                    "net": period_net},
                     "balanceSheet": {"assets": assets, "liabilities": liabilities,
                                      "capital": capital, "unclosedProfitLoss": lifetime_net,
                                      "liabilitiesAndEquity": liabilities + capital + lifetime_net}})
