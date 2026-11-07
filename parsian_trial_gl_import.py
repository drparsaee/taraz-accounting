"""One-time Parsian RIAL GL -> fresh, isolated Madar standalone ledger.

This is a *general-ledger journal* migration, not a full operational ERP
migration. Accounting docs, item stock, payments, cheques and party subledgers
remain available in private source quarantine, not silently reclassified as
Madar operational documents. Never connects to a SQL Server or APPDATA.

Input currency RIAL must be explicitly asserted by the owner. Source input is
the attached live SQL export, not a restored copy of the BAK. No read/write
access to the existing trial book or main operational accounting database.
All events are replayed and verified before the *single* SQLite publication.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import json
import os
import sqlite3

from accounting_core import (
    apply_accounting_command, empty_rial_accounting_state,
    validate_accounting_state, accounting_view,
)
from accounting_reporting import ledger_reports
from parsian_financial_preflight import build_financial_plan
from parsian_quarantine_stage import profile_export
from scripts.import_parsian_catalog_to_trial import _source_catalog
from standalone_accounting import StandaloneAccountingStore, _canonical

ACTOR = "trial-importer"
ACCOUNTS = {ACTOR: {"username": ACTOR, "role": "admin"}}
NOW = "2026-10-24T12:00:00Z"
SOURCE_CLASS = "ATTACHED_LIVE_SQL_READ_ONLY_NOT_BAK_SNAPSHOT"
RESTORED_CLASS = "RESTORED_BAK_ISOLATED_VERIFIED_20261026"
RESTORED_SHA = "65E85D8BED539C4CB98D2A3F20416637524E5133CB7B940D6A4015A7CA368441"
RESTORED_SHA_1405_R19 = "EAF55D9A4C2CF2EF28C9C5AF01B57E61C1773E8A33F16F09174D1E41967B6946"
ACCOUNT_KIND_BY_GROUP = {
    11: "asset", 12: "asset", 21: "liability", 22: "liability",
    31: "equity", 41: "revenue", 51: "expense", 61: "expense",
}


class TrialMigrationError(ValueError):
    pass


def _code_id(path):
    if (type(path) not in (tuple, list) or len(path) != 3 or
            any(type(x) is not int or x < 0 or x > 2**31 for x in path)):
        raise TrialMigrationError("Invalid source chart account path")
    return "ps." + ".".join(str(x) for x in path)


def _mapping(source, used_paths):
    charts = source["tables"]
    kol = {int(row["Code"]): row for row in charts["tbl_Kol"]}
    moeen = {
        (int(row["KolCode"]), int(row["Code"])): row
        for row in charts["tbl_Moeen"]
    }
    taf = {
        (int(row["KolCode"]), int(row["MoeenCode"]), int(row["Code"])): row
        for row in charts["tbl_Tafsili"]
    }
    classified = {}
    for path in used_paths:
        k, m, t = path
        if k not in kol or (k, m) not in moeen:
            raise TrialMigrationError("Unknown referenced general or sub account")
        if t != 0 and path not in taf:
            raise TrialMigrationError("Unknown referenced detail account")
        group = kol[k]["GroupCode"]
        if k == 66 and group is None:
            kind, reason = "equity", "opening_balance_temporary_equity_provisional"
        elif group in ACCOUNT_KIND_BY_GROUP:
            kind, reason = ACCOUNT_KIND_BY_GROUP[group], "source_group_code"
            if k == 61:
                kind, reason = "revenue", "returns_as_contra_revenue_provisional"
        else:
            raise TrialMigrationError(
                "Unclassified source general ledger account prevents posting")
        name = taf[path]["CName"] if t and path in taf else moeen[(k, m)]["CName"]
        if type(name) is not str or not name.strip() or len(name.strip()) > 290:
            raise TrialMigrationError("Invalid source chart account name")
        classified[_code_id(path)] = {
            "sourcePath": list(path),
            "sourceKol": str(kol[k]["CName"]),
            "sourceMoeen": str(moeen[(k, m)]["CName"]),
            "sourceDetail": str(taf[path]["CName"]) if t and path in taf else None,
            "name": name.strip(),
            "kind": kind,
            "classification": reason,
            # Historical cash/bank postings can be temporarily negative;
            # do not misrepresent a historic ledger as live cash operations.
            "liquid": False,
            "financialOperationalSubledgerLinked": False,
        }
    return classified


def _strict_decode(path, max_bytes=8_000_000):
    path = Path(path).absolute()
    if not path.is_file() or path.is_symlink() or path.stat().st_size > max_bytes:
        raise TrialMigrationError("Untrusted or oversized source artifact")
    def pairs(items):
        out = {}
        for key, val in items:
            if key in out:
                raise TrialMigrationError("Duplicate source JSON key")
            out[key] = val
        return out
    return json.loads(path.read_bytes().decode("utf-8"),
                      object_pairs_hook=pairs)


def stage_trial_gl(*, source_path, date_path, quarantine_path,
                   destination_dir, confirmed_unit: str,
                   include_goods: bool = True):
    """Create-only new book and compare every journal/account line in RIAL.

    Destination_dir MUST NOT EXIST. Never opens a non-disposable database for
    writing. No experimental database is a production replacement.
    """
    if confirmed_unit != "RIAL":
        raise TrialMigrationError("Source currency requires explicit RIAL confirmation")
    destination = Path(destination_dir).absolute()
    source_path = Path(source_path).absolute()
    date_path = Path(date_path).absolute()
    quarantine_path = Path(quarantine_path).absolute()
    if (destination.exists() or destination.is_symlink() or
            destination.name != "parsian-rial-gl-import-disposable" or
            not destination.parent.name.startswith("migration-experiment-") or
            not destination.parent.is_dir() or
            any(x.is_symlink() for x in
                (destination.parent, source_path, date_path, quarantine_path))):
        raise TrialMigrationError("Only a new disposable migration folder is allowed")
    source = _strict_decode(source_path)
    dates = _strict_decode(date_path)
    if source.get("sourceType") not in (SOURCE_CLASS, RESTORED_CLASS):
        raise TrialMigrationError("Refusing unknown source provenance")
    if source["sourceType"] == RESTORED_CLASS and source.get("backupCopySha256",'').upper() not in (
            RESTORED_SHA, RESTORED_SHA_1405_R19):
        raise TrialMigrationError("Restored backup source hash mismatch")
    profile_export(source)
    with closing(sqlite3.connect(
            "file:" + quarantine_path.as_posix() + "?mode=ro", uri=True)) as archive:
        meta = dict(archive.execute("SELECT key,value FROM metadata"))
        num_rows = archive.execute("SELECT COUNT(*) FROM raw_source_rows").fetchone()[0]
    if (meta.get("source_export_sha256") != sha256(source_path.read_bytes()).hexdigest()
            or meta.get("financial_posting_allowed") != "false" or
            num_rows != sum(len(rows) for rows in source["tables"].values())):
        raise TrialMigrationError("Source disagrees with immutable quarantine")
    detail, preview = build_financial_plan(source, dates)
    if (detail["sourceClass"] != source["sourceType"] or
            preview["unbalancedDocuments"] or
            preview["sourceJournalRows"] != len(source["tables"]["tbl_Document"])):
        raise TrialMigrationError("Source financial preview is inconsistent")
    paths = sorted((tuple(p) for p in detail["accountPathsReferenced"]))
    classified = _mapping(source, paths)
    document_list = sorted(detail["journalGroups"],
                           key=lambda x: (x["postingDateISO"],
                                          x["sourceDocumentNumber"]))
    event_commands = []
    for account_id, item in sorted(classified.items()):
        event_commands.append({
            "type": "account.create", "eventId": "ps.account." + account_id[3:],
            "accountId": account_id, "name": item["name"],
            "kind": item["kind"], "liquid": False,
        })
    added, deferred = _source_catalog(source)
    if include_goods:
        event_commands.extend(added)
    for doc in document_list:
        event_id = "ps.sanad." + str(doc["sourceDocumentNumber"])
        lines = []
        for original in doc["rows"]:
            lines.append({
                "accountId": _code_id(original["sourceAccountPath"]),
                "debit": original["debitSourceUnits"],
                "credit": original["creditSourceUnits"],
            })
        event_commands.append({
            "type": "journal.manual",
            "eventId": event_id,
            "postingDate": doc["postingDateISO"],
            "note": "Parsian RIAL GL trial, original Sanad " +
                    str(doc["sourceDocumentNumber"]),
            "lines": lines,
        })

    state = empty_rial_accounting_state()
    for command in event_commands:
        result = apply_accounting_command(
            state, command, actor=ACTOR, accounts=ACCOUNTS,
            now="2026-10-26T20:00:00Z" if source["sourceType"] == RESTORED_CLASS else NOW)
        if not result["changed"]:
            raise TrialMigrationError("Duplicate accounting event")
        state = result["state"]
    validate_accounting_state(state)
    view = accounting_view(state, actor=ACTOR, accounts=ACCOUNTS)
    reports = ledger_reports(view)
    original_debits = sum(x["sourceDebitTotal"] for x in document_list)
    original_credits = sum(x["sourceCreditTotal"] for x in document_list)
    target_debits = sum(sum(row["debit"] for row in j["lines"])
                        for j in view["journals"])
    target_credits = sum(sum(row["credit"] for row in j["lines"])
                         for j in view["journals"])
    if (original_debits != original_credits or
            (target_debits, target_credits) != (original_debits, original_credits) or
            len(view["journals"]) != len(document_list)):
        raise TrialMigrationError("Imported journal totals disagree with Parsian")
    source_movements = defaultdict(lambda: [0, 0])
    for d in document_list:
        for row in d["rows"]:
            aid = _code_id(row["sourceAccountPath"])
            source_movements[aid][0] += row["debitSourceUnits"]
            source_movements[aid][1] += row["creditSourceUnits"]
    destination_movements = defaultdict(lambda: [0, 0])
    for journal in view["journals"]:
        for row in journal["lines"]:
            destination_movements[row["accountId"]][0] += row["debit"]
            destination_movements[row["accountId"]][1] += row["credit"]
    if (dict(source_movements) != dict(destination_movements) or
            reports["trialBalance"]["totalDebit"] !=
            reports["trialBalance"]["totalCredit"]):
        raise TrialMigrationError("Imported GL chart balance mismatches source")
    # Only now create the entirely new and empty disposable destination.
    destination.mkdir(exist_ok=False)
    book_path = destination/"standalone-accounting.sqlite3"
    store = StandaloneAccountingStore(book_path, default_currency="RIAL")
    raw = _canonical(state)
    with store._connect() as sql:
        sql.execute("BEGIN IMMEDIATE")
        try:
            current_revision, _ = store._current(sql)
            if current_revision != 0:
                raise TrialMigrationError("Trial database was not empty")
            store._write(sql, 0, len(state["events"]), raw)
            sql.execute("COMMIT")
        except BaseException:
            if sql.in_transaction:
                sql.execute("ROLLBACK")
            raise
    independently_read = StandaloneAccountingStore(
        book_path, default_currency="TOMAN").read(
            actor=ACTOR, accounts=ACCOUNTS)
    if (independently_read["revision"] != len(state["events"]) or
            independently_read["view"]["currency"] != "RIAL" or
            len(independently_read["view"]["journals"]) != len(document_list)):
        raise TrialMigrationError("Independent SQLite replay validation failed")
    summary = {
        "status": "TRIAL_GL_POSTED_AND_RECONCILED_NOT_OPERATIONAL_ERP",
        "source": source["sourceType"],
        "sourceCurrency": "RIAL_OWNER_CONFIRMED",
        "bakSnapshotEquivalenceVerified": source["sourceType"] == RESTORED_CLASS,
        "journalGroupsImported": len(document_list),
        "journalLinesImported": sum(len(x["rows"]) for x in document_list),
        "distinctAccountsImported": len(classified),
        "goodsImported": len(added) if include_goods else 0,
        "goodsDeferredMissingUnit": len(deferred) if include_goods else 0,
        "originalDebitRial": original_debits,
        "originalCreditRial": original_credits,
        "importedDebitRial": target_debits,
        "importedCreditRial": target_credits,
        "sourceAccountBalancesIdentical": True,
        "financialTrialLedgerCurrency": "RIAL",
        "trialRevision": independently_read["revision"],
        "cashBankOperationalSubledgerMigrated": False,
        "customerAndSupplierOperationalSubledgersMigrated": False,
        "salesPurchaseInvoicesMigratedAsOperationalDocuments": False,
        "chequesAndStockMovementsMigrated": False,
        "safeToReplaceParsian": False,
    }
    with (destination/"source-account-crosswalk-REVIEW.json").open(
            "x", encoding="utf-8") as file:
        json.dump(classified, file, ensure_ascii=False, indent=2)
    with (destination/"gl-import-audit.json").open("x", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    return summary


__all__ = ["stage_trial_gl", "TrialMigrationError"]
