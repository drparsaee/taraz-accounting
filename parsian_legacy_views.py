"""Accountant-facing, read-only historical Parsian views from a sealed sidecar.

Never creates book entries, changes invoice/party balances, or installs legacy
users. The historic GL is already in Madar's independent RIAL ledger. Historical
invoice rows are archival REFERENCES, not reissued Madar invoices or stock.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

_SCHEMA = "ATTACHED_LIVE_SQL_NOT_RESTORED_BACKUP"
_RESTORED_SCHEMA = "ISOLATED_RESTORED_BAK_VERIFIED_20261026"
_TABLES = ("tbl_Factor","tbl_FactorKind","tbl_Goods","tbl_Check",
           "tbl_TopCheck","tbl_Tafsili","tbl_Moeen")
_MAX_ROWS = 20000


class HistoricalDataError(ValueError):
    pass


def _read_rows(db, table):
    rows = []
    for raw, digest in db.execute(
            "SELECT typed_raw_json,row_sha256 FROM archived_rows "
            "WHERE source_table=? ORDER BY ordinal", (table,)):
        if sha256(raw).hexdigest() != digest:
            raise HistoricalDataError("Historical source row checksum mismatch")
        record = json.loads(raw)
        if (type(record) is not dict or record.get("table") != table
                or type(record.get("fields")) is not dict):
            raise HistoricalDataError("Invalid historical source row")
        row = {}
        for key, item in record["fields"].items():
            if type(item) is not dict or item.get("t") not in (
                    "null","text","bit","integer","float","decimal",
                    "datetime","binary"):
                raise HistoricalDataError("Unknown historical source field")
            kind = item["t"]
            if kind == "null":
                row[key] = None
            elif kind in ("text", "bit"):
                row[key] = item["value"]
            elif kind == "integer":
                row[key] = int(item["text"])
            elif kind in ("float", "decimal"):
                # Keep exact original decimal representation for archive
                # display; these are NOT accounting posting amounts.
                val = Decimal(item["text"])
                if not val.is_finite():
                    raise HistoricalDataError("Nonfinite historical decimal")
                row[key] = str(val)
            elif kind == "datetime":
                row[key] = item["text"]
            else:
                # Never return raw uploaded photos/attachments through UI.
                row[key] = "(باینری آرشیوشده)"
        rows.append(row)
        if len(rows) > _MAX_ROWS:
            raise HistoricalDataError("Too many historical rows")
    return rows


def _int(value, where):
    if type(value) is int:
        return value
    if type(value) is str:
        try:
            value = Decimal(value)
        except InvalidOperation as exc:
            raise HistoricalDataError("Invalid "+where) from exc
        if value.is_finite() and value == value.to_integral_value():
            return int(value)
    raise HistoricalDataError("Invalid "+where)


def _safe_text(value):
    return value.strip()[:240] if type(value) is str else ""


def legacy_views(view, *, archive_path: Path, manifest_path: Path):
    """Return view subset only after source manifest and ledger checks.

    A missing sidecar returns None; a corrupt one causes a visible failure
    instead of silently pretending the customer accounts are current or zero.
    """
    archive_path = Path(archive_path).absolute()
    manifest_path = Path(manifest_path).absolute()
    if not archive_path.exists() and not manifest_path.exists():
        return None
    if (archive_path.is_symlink() or manifest_path.is_symlink()
            or not archive_path.is_file() or not manifest_path.is_file()
            or archive_path.parent != manifest_path.parent):
        raise HistoricalDataError("Incomplete or unsafe historical source package")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if (type(manifest) is not dict
            or manifest.get("source") not in (_SCHEMA,_RESTORED_SCHEMA)
            or manifest.get("snapshotMatchesBackup") is not
                (manifest.get("source") == _RESTORED_SCHEMA)
            or manifest.get("sourceCurrency") != "RIAL_OWNER_CONFIRMED"
            or type(manifest.get("tableCounts")) is not dict
            or manifest.get("vendorTableCount") != len(manifest["tableCounts"])
            or view.get("currency") != "RIAL"):
        raise HistoricalDataError("Historical package/currency mismatch")
    with closing(sqlite3.connect(
            archive_path.as_uri()+"?mode=ro", uri=True,
            isolation_level=None, timeout=5)) as db:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise HistoricalDataError("Historical archive SQLite is damaged")
        meta = dict(db.execute("SELECT key,value FROM archive_meta"))
        if (meta.get("source_class") != manifest["source"]
                or meta.get("financial_posting_authorized") != "false"
                or meta.get("bak_snapshot_equivalence_verified") !=
                   ("true" if manifest["source"] == _RESTORED_SCHEMA else "false")
                or meta.get("source_archive_sha256") !=
                manifest.get("archiveSha256", "").lower()):
            raise HistoricalDataError("Historical archive provenance mismatch")
        # The table row counts, including zero-count tables, must exactly
        # match the separately signed manifest.
        counts = dict(db.execute(
            "SELECT source_table,COUNT(*) FROM archived_rows "
            "GROUP BY source_table"))
        expected = {k:v for k,v in manifest["tableCounts"].items() if v}
        if counts != expected or sum(counts.values()) != manifest["vendorRowCount"]:
            raise HistoricalDataError("Historical source table coverage mismatch")
        tables = {name:_read_rows(db, name) for name in _TABLES}
    groups = {
        _int(x["Code"], "factor kind code"): x for x in tables["tbl_FactorKind"]
    }
    historical = defaultdict(list)
    for row in tables["tbl_Factor"]:
        key = tuple(_int(row.get(name), name) for name in
                    ("TitleCode","I/O","FactorKind","Factor_Num"))
        historical[key].append(row)
    invoice_rows = []
    goods = {_int(x["Code"], "goods code"): x for x in tables["tbl_Goods"]}
    seen_source_line_ids = set()
    for key, lines in sorted(historical.items()):
        type_code, io, kind, number = key
        meta = groups.get(type_code, {})
        labels = {_safe_text(x.get("Factor_Date")) for x in lines}
        if len(labels) != 1:
            raise HistoricalDataError("Historical invoice lines have mixed dates")
        linked = {_int(x["Sanad_Num"], "journal number") for x in lines}
        detail_lines = []
        for row in lines:
            rowid = _int(row["ID"], "factor row ID")
            if rowid in seen_source_line_ids:
                raise HistoricalDataError("Duplicate archived invoice row ID")
            seen_source_line_ids.add(rowid)
            goods_code = row.get("GoodsCode")
            product = goods.get(_int(goods_code, "factor goods code")) if goods_code is not None else None
            detail_lines.append({
                "sourceRowId": rowid,
                "sourceGoodsCode": str(goods_code) if goods_code is not None else "",
                "goodsName": _safe_text(product.get("CName")) if product else
                             _safe_text(row.get("GoodsComment")),
                "quantitySource": str(row.get("Tedad") or ""),
                "unitPriceSource": str(row.get("Price") or ""),
                "discountSource": str(row.get("Discont") or ""),
                "sourceJournal": str(row.get("Sanad_Num") or ""),
                "amountSemanticsReviewed": False,
            })
        party_paths = {
            tuple(str(row.get(column)) for column in ("Taraf_K","Taraf_M","Taraf_T"))
            for row in lines
        }
        party_path = next(iter(party_paths)) if len(party_paths) == 1 else None
        connected = all("ps.sanad."+str(num) in {
            x["eventId"] for x in view.get("journals", [])} for num in linked)
        invoice_rows.append({
            "sourceId": f"ps.factor.{type_code}.{io}.{kind}.{number}",
            "number": str(number),
            "kind": _safe_text(meta.get("CName")) or
                    f"نوع پارسیان {type_code}",
            "dateJalali": next(iter(labels)),
            "lineCount": len(lines),
            "linkedSanad": ", ".join(str(x) for x in sorted(linked)),
            "sourcePartyPath": ".".join(party_path) if party_path else "نامشخص / متفاوت در ردیف‌ها",
            "sourceRows": detail_lines,
            "linkedJournalExists": connected,
            "priceAndStockConverted": False,
            "status": "سند تاریخی آرشیوی، بدون ثبت مجدد در دفترکل",
        })
    if len(invoice_rows) > 5000:
        raise HistoricalDataError("Too many historical documents")
    # GL-derived customer balances: these have already been posted as ps.12.*
    # leaf accounts; never re-post to the 1200 operational AR control.
    deb = []
    for ident, acc in view.get("accounts", {}).items():
        if ident.startswith("ps.12.") and type(acc.get("debitMinusCredit")) is int:
            deb.append({
                "sourceAccountId": ident,
                "name": _safe_text(acc.get("name")),
                "balanceRial": acc["debitMinusCredit"],
                "isOperationalParty": False,
            })
    deb.sort(key=lambda x: (-x["balanceRial"],x["sourceAccountId"]))
    positive = [x for x in deb if x["balanceRial"] > 0]
    negative = [x for x in deb if x["balanceRial"] < 0]
    customer_view = []
    for party in view.get("parties", {}).values():
        if not str(party.get("id","")).startswith("ps.party."):
            continue
        source_id = party["id"].replace("ps.party.","ps.",1)
        source_account = view.get("accounts", {}).get(source_id)
        customer_view.append({
            "partyId":party["id"],"name":_safe_text(party.get("name")),
            "historicalAccountId":source_id,
            "historicalBalanceRial":source_account["debitMinusCredit"]
                if source_account else None,
            "newReceivableRial":party.get("receivable",0),
            "newPayableRial":party.get("payable",0),
            "historicalBalanceIsSeparate":True,
        })
    historic_bank = [
        {"accountId":aid,"name":_safe_text(acc.get("name")),
         "balanceRial":acc["debitMinusCredit"],
         "isOperationalTreasury":False}
        for aid,acc in view.get("accounts",{}).items()
        if aid.startswith(("ps.10.","ps.11.")) and acc.get("kind")=="asset"
    ]
    history_items = [
        {"sourceGoodsCode":str(x.get("Code","")),
         "name":_safe_text(x.get("CName")),
         "unitName":_safe_text(x.get("UnitName_1")),
         "rawCountNumber":str(x.get("CountNumber") or ""),
         "isVerifiedStock":False}
        for x in tables["tbl_Goods"]
    ]
    return {
        "sourceStatus": ("منبع: فایل بکاپ بازیابی‌شده در دیتابیس آزمایشی مستقل؛ رکوردها آرشیوی‌اند"
                         if manifest["source"] == _RESTORED_SCHEMA else
                         "منبع: دیتابیس متصل پارسیان؛ تطبیق با فایل بکاپ تأیید نشده"),
        "readOnlyHistory": True,
        "notOperationalInvoicesOrPayments": True,
        "currency": "RIAL",
        "debtors": deb,
        "positiveDebtorCount": len(positive),
        "positiveDebtorTotal": sum(x["balanceRial"] for x in positive),
        "creditBalanceCustomerCount": len(negative),
        "unifiedCustomerSummaries": customer_view,
        "historicCashBankBalances": historic_bank,
        "historicCatalogSourceRows": history_items,
        "historicalDocuments": invoice_rows,
        "historicalInvoiceGroups": len(invoice_rows),
        "historicalFactorLines": len(tables["tbl_Factor"]),
        "historicalProducts": len(tables["tbl_Goods"]),
        "historicalCheques": len(tables["tbl_Check"]),
        "historicalTopCheckRows": len(tables["tbl_TopCheck"]),
        "archiveBaseTables": len(manifest["tableCounts"]),
        "archiveRows": manifest["vendorRowCount"],
    }


__all__ = ["legacy_views", "HistoricalDataError"]
