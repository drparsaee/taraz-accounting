"""Independent read-only acceptance of Parsian RIAL trial migration evidence."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import json
import sqlite3

from standalone_accounting import StandaloneAccountingStore
from accounting_reporting import ledger_reports
from parsian_financial_preflight import build_financial_plan

AUDITOR = "trial-audit"
ACTORS = {AUDITOR: {"username": AUDITOR, "role": "admin"}}


class TrialAuditError(ValueError):
    pass


def audit_import(*, export, date_mapping, trial_root, source_archive,
                 archive_manifest):
    root = Path(trial_root).absolute()
    export = Path(export).absolute()
    dates_path = Path(date_mapping).absolute()
    source_archive = Path(source_archive).absolute()
    archive_manifest = Path(archive_manifest).absolute()
    if (not root.is_dir() or
            any(x.is_symlink() for x in
                (root, export, dates_path, source_archive, archive_manifest))):
        raise TrialAuditError("Invalid private trial artifact paths")
    source = json.loads(export.read_text("utf-8"))
    date_map = json.loads(dates_path.read_text("utf-8"))
    detail, preview = build_financial_plan(source, date_map)
    dbfile = root/"standalone-accounting.sqlite3"
    if not dbfile.is_file():
        raise TrialAuditError("Missing trial ledger")
    store = StandaloneAccountingStore(dbfile, default_currency="TOMAN")
    result = store.read(actor=AUDITOR, accounts=ACTORS)
    view = result["view"]
    if view["currency"] != "RIAL":
        raise TrialAuditError("Unexpected or unpersisted RIAL currency")
    original_docs = {
        str(d["sourceDocumentNumber"]): d for d in detail["journalGroups"]}
    actual_docs = {}
    for journal in view["journals"]:
        event = journal["eventId"]
        if type(event) is not str or not event.startswith("ps.sanad."):
            raise TrialAuditError("Foreign document in trial ledger")
        key = event[len("ps.sanad."):]
        if key in actual_docs:
            raise TrialAuditError("Duplicate source journal number")
        actual_docs[key] = journal
    if original_docs.keys() != actual_docs.keys():
        raise TrialAuditError("Missing or extra GL document")
    for number, doc in original_docs.items():
        j = actual_docs[number]
        if j["date"] != doc["postingDateISO"] or len(j["lines"]) != len(doc["rows"]):
            raise TrialAuditError("Source journal date or line count mismatch")
        for actual, original in zip(j["lines"], doc["rows"]):
            aid = "ps." + ".".join(map(str, original["sourceAccountPath"]))
            if (actual["accountId"] != aid or
                    actual["debit"] != original["debitSourceUnits"] or
                    actual["credit"] != original["creditSourceUnits"]):
                raise TrialAuditError("Source GL line changed in trial book")
    totals = ledger_reports(view)
    raw_total = sum(x["sourceDebitTotal"] for x in original_docs.values())
    if (sum(sum(x["debit"] for x in j["lines"])
            for j in actual_docs.values()) != raw_total or
            sum(sum(x["credit"] for x in j["lines"])
                for j in actual_docs.values()) != raw_total or
            totals["trialBalance"]["totalDebit"] !=
            totals["trialBalance"]["totalCredit"]):
        raise TrialAuditError("Raw journals or trial balances not balanced")
    manifest = json.loads(archive_manifest.read_text("utf-8"))
    with closing(sqlite3.connect(source_archive.as_uri()+"?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise TrialAuditError("Source archive SQLite integrity failure")
        archived = Counter()
        bad_sha = 0
        document_ids = Counter()
        for table, raw, digest in db.execute(
                "SELECT source_table,typed_raw_json,row_sha256 FROM archived_rows"):
            archived[table] += 1
            if sha256(raw).hexdigest() != digest:
                bad_sha += 1
            if table == "tbl_Document":
                parsed = json.loads(raw)
                code = parsed["fields"]["ID"]
                if code["t"] != "integer":
                    raise TrialAuditError("Bad document archive key")
                document_ids[int(code["text"])] += 1
        meta = dict(db.execute("SELECT key,value FROM archive_meta"))
    expected = manifest["tableCounts"]
    if (dict(archived) != {k: v for k, v in expected.items() if v > 0} or
            sum(archived.values()) != manifest["vendorRowCount"] or bad_sha or
            meta.get("source_archive_sha256") != manifest["archiveSha256"].lower() or
            meta.get("financial_posting_authorized") != "false"):
        raise TrialAuditError("Raw archive coverage/hash/guardrail check failed")
    staged_ids = Counter(x["ID"] for x in source["tables"]["tbl_Document"])
    if document_ids != staged_ids:
        raise TrialAuditError("GL source document IDs differ from full archive")
    return {
        "status": "TRIAL_GL_LEDGER_AND_FULL_SOURCE_ARCHIVE_RECONCILED",
        "currency": "RIAL_OWNER_CONFIRMED",
        "trialCurrency": view["currency"],
        "journalDocuments": len(actual_docs),
        "journalLines": sum(len(x["rows"]) for x in original_docs.values()),
        "exactDocumentAndLineMatches": len(original_docs),
        "glGrossDebitRial": raw_total,
        "glGrossCreditRial": raw_total,
        "trialAccountBalanceIsBalanced": True,
        "trialGoods": len(view["items"]),
        "rawBaseTablesPreserved": len(expected),
        "rawBaseTableRowsPreserved": sum(archived.values()),
        "sourceRowDigestMismatches": bad_sha,
        "sourceDocumentIdCoverageExact": True,
        "sourceSQL": ("ISOLATED_VERIFIED_RESTORED_BAK"
                      if detail["sourceBackupSnapshotVerified"] else
                      "READ_ONLY_ATTACHED_SQL_NOT_RESTORED_BAK"),
        "snapshotEqualToBakProven": detail["sourceBackupSnapshotVerified"],
        "operationalARAPBankInvoiceChequeStockModulesMigrated": False,
        "canReplaceParsianWithoutFurtherWork": False,
    }


__all__ = ["audit_import", "TrialAuditError"]
