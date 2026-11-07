"""Immutable, explicitly UNTRUSTED Parsian SQL export quarantine.

This tool is not an importer into Madar's event-sourced accounting ledger.
It accepts only the known read-only export shape, preserves the original raw
numbers and Jalali strings, and creates a private SQLite *quarantine* database
without connecting to any SQL Server or writing a Madar accounting command.

An attached live SQL database and a copied BAK are distinct financial sources;
an export of the former MUST NOT be presented as a validated restore of the
latter. No staged amounts may be posted until source, currency, account kinds,
opening balances, and all document semantics are independently reconciled.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

_TABLES = {
    "tbl_ACCGroup": ("Code", "CName"),
    "tbl_Kol": ("Code", "CName", "GroupCode", "iType"),
    "tbl_Moeen": ("KolCode", "Code", "CName", "HaveChild"),
    "tbl_Tafsili": ("KolCode", "MoeenCode", "Code", "CName"),
    "tbl_Document": ("ID", "Sanad_Num", "SanadDate", "KolCode",
                     "MoeenCode", "TafsiliCode", "Bed", "Bes", "IsNote"),
    "tbl_Factor": ("ID", "Factor_Num", "Factor_Date", "TitleCode",
                   "I/O", "FactorKind", "Sanad_Num", "GoodsCode",
                   "Tedad", "Price", "Discont"),
    "tbl_Goods": ("Code", "CName", "GroupCode", "UnitName_1"),
}
_EXPECTED_TYPE = "ATTACHED_LIVE_SQL_READ_ONLY_NOT_BAK_SNAPSHOT"
_RESTORED_TYPE = "RESTORED_BAK_ISOLATED_VERIFIED_20261026"
_HASH_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
_JALALI_DATE = re.compile(r"(1[234]\d\d)/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])\Z")
MAX_ROWS = 20000
MAX_BYTES = 8_000_000
MAX_AMOUNT = 10**15


class QuarantineError(ValueError):
    pass


def _unique_key(table, row):
    if table in ("tbl_Document", "tbl_Factor"):
        return str(row["ID"])
    if table == "tbl_Tafsili":
        return ":".join(str(row[x]) for x in ("KolCode", "MoeenCode", "Code"))
    if table == "tbl_Moeen":
        return f'{row["KolCode"]}:{row["Code"]}'
    return str(row["Code"])


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def _amount(value):
    if type(value) not in (int, float, str):
        raise QuarantineError("Invalid legacy floating-point amount")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise QuarantineError("Invalid decimal source amount") from exc
    if (not decimal.is_finite() or decimal < 0 or decimal > MAX_AMOUNT or
            decimal != decimal.to_integral_exact()):
        raise QuarantineError("Source amount is not an exact positive whole unit")
    # SQL Server 'float' is exact for integers below 2**53; this cap ensures
    # already-parsed JSON float values are in that range.
    return int(decimal)


def _jalali_syntax(value):
    if type(value) is not str or not _JALALI_DATE.fullmatch(value):
        raise QuarantineError("Unknown or invalid legacy Jalali date format")
    # This validates the shape, NOT Persian leap-year semantics.
    y, m, day = map(int, value.split("/"))
    if day > (31 if m <= 6 else 30):
        raise QuarantineError("Impossible Jalali day")
    return value


def profile_export(export):
    """No mutations. Summarize finance document integrity without any PII."""
    if (type(export) is not dict or set(export) !=
            {"schemaVersion", "sourceType", "backupCopySha256",
             "extractedAtUtc", "tables"}):
        raise QuarantineError("Unknown source export shape")
    if (type(export["schemaVersion"]) is not int or
            export["schemaVersion"] != 1 or
            export["sourceType"] not in (_EXPECTED_TYPE, _RESTORED_TYPE) or
            type(export["backupCopySha256"]) is not str or
            not _HASH_RE.fullmatch(export["backupCopySha256"])):
        raise QuarantineError("Untrusted export schema or missing source digest")
    try:
        dt = datetime.fromisoformat(export["extractedAtUtc"].replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise QuarantineError("Missing or untrusted source capture timestamp") from exc
    tables = export["tables"]
    if type(tables) is not dict or set(tables) != set(_TABLES):
        raise QuarantineError("Incomplete source table coverage")
    indexed = {}
    for name, columns in _TABLES.items():
        rows = tables[name]
        if type(rows) is not list or len(rows) > MAX_ROWS:
            raise QuarantineError("Unsupported source record count")
        seen = set()
        for item in rows:
            if type(item) is not dict or set(item) != set(columns):
                raise QuarantineError("Unexpected source record fields")
            ident = _unique_key(name, item)
            if not ident or ident in seen:
                raise QuarantineError("Duplicate source record primary key")
            seen.add(ident)
            _canonical(item)
        indexed[name] = len(rows)

    doc = tables["tbl_Document"]
    groups = defaultdict(lambda: {"lines": 0, "debit": 0, "credit": 0})
    for line in doc:
        if type(line["Sanad_Num"]) is not int or line["Sanad_Num"] < 0:
            raise QuarantineError("Invalid source journal number")
        if type(line["IsNote"]) is not bool:
            raise QuarantineError("Invalid source note flag")
        _jalali_syntax(line["SanadDate"])
        debit, credit = _amount(line["Bed"]), _amount(line["Bes"])
        if (debit > 0) == (credit > 0):
            raise QuarantineError("Legacy journal row has zero or two positive sides")
        key = line["Sanad_Num"]
        groups[key]["lines"] += 1
        groups[key]["debit"] += debit
        groups[key]["credit"] += credit
    for factor in tables["tbl_Factor"]:
        _jalali_syntax(factor["Factor_Date"])
    unbalanced = sum(a["debit"] != a["credit"] for a in groups.values())
    too_short = sum(a["lines"] < 2 or a["lines"] > 100
                    for a in groups.values())
    known_kol = {x["Code"] for x in tables["tbl_Kol"]}
    known_moeen = {(x["KolCode"], x["Code"]) for x in tables["tbl_Moeen"]}
    known_tafsili = {
        (x["KolCode"], x["MoeenCode"], x["Code"])
        for x in tables["tbl_Tafsili"]
    }
    orphan_kol = sum(x["KolCode"] not in known_kol for x in doc)
    orphan_moeen = sum(
        (x["KolCode"], x["MoeenCode"]) not in known_moeen for x in doc)
    orphan_tafsili = sum(
        x["TafsiliCode"] not in (0, None) and
        (x["KolCode"], x["MoeenCode"], x["TafsiliCode"])
        not in known_tafsili for x in doc)
    known_sanads = set(groups)
    unmatched_factors = sum(
        x["Sanad_Num"] not in known_sanads for x in tables["tbl_Factor"])
    return {
        "sourceType": export["sourceType"],
        "sourceSnapshotProven": export["sourceType"] == _RESTORED_TYPE,
        "sourceCurrencyVerified": False,
        "sourceDateCalendarReviewed": False,
        "sourceChartAccountTypesReviewed": False,
        "sourceRowCounts": indexed,
        "documentGroups": len(groups),
        "unbalancedDocumentGroups": unbalanced,
        "oversizedOrSingletonGroups": too_short,
        "orphanKolReferences": orphan_kol,
        "orphanMoeenReferences": orphan_moeen,
        "orphanTafsiliReferences": orphan_tafsili,
        "factorRowsWithoutMatchedJournalNumber": unmatched_factors,
        "factorLinkSemanticsReviewed": False,
        "financialPostingAllowed": False,
        "stageStatus": "READ_ONLY_SOURCE_CAPTURE_UNVERIFIED",
    }


def create_quarantine(export_file: str | Path, output: str | Path, *,
                      backup_copy: str | Path):
    """Create-only SQLite source archive; no access to any Madar database."""
    inp = Path(export_file).absolute()
    dest = Path(output).absolute()
    copy = Path(backup_copy).absolute()
    if (any(x.is_symlink() for x in (inp, dest, copy, *dest.parents)) or
            not inp.is_file() or not copy.is_file() or
            inp == dest or copy == dest or dest.exists() or
            not dest.parent.is_dir() or dest.suffix != ".sqlite3" or
            dest.name == "standalone-accounting.sqlite3"):
        raise QuarantineError("Unsafe source/quarantine/destination path")
    if inp.stat().st_size > MAX_BYTES:
        raise QuarantineError("Staging export too large")
    data = inp.read_bytes()
    try:
        export = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=lambda pairs: _strict_pairs(pairs),
            parse_constant=lambda _: (_ for _ in ()).throw(
                QuarantineError("Non-finite JSON constant")),
        )
    except (ValueError, UnicodeError) as exc:
        raise QuarantineError("Source export is invalid strict JSON") from exc
    report = profile_export(export)
    with copy.open("rb") as source:
        digest = sha256()
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    if digest.hexdigest().lower() != export["backupCopySha256"].lower():
        raise QuarantineError("Backup copy does not match read-only source declaration")
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
                prefix=".quarantine-", suffix=".sqlite3", dir=dest.parent,
                delete=False) as handle:
            tmp = Path(handle.name)
        cn = sqlite3.connect(str(tmp), isolation_level=None)
        try:
            cn.execute("PRAGMA journal_mode=DELETE")
            cn.execute("PRAGMA synchronous=FULL")
            cn.execute("BEGIN IMMEDIATE")
            cn.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            cn.execute("CREATE TABLE raw_source_rows("
                       "source_table TEXT NOT NULL, source_key TEXT NOT NULL,"
                       "raw_json BLOB NOT NULL, sha256 TEXT NOT NULL,"
                       "PRIMARY KEY(source_table, source_key))")
            meta = {
                "source_type": export["sourceType"],
                "backup_copy_sha256": digest.hexdigest(),
                "source_export_sha256": sha256(data).hexdigest(),
                "financial_posting_allowed": "false",
                "source_snapshot_proven": ("true" if export["sourceType"] == _RESTORED_TYPE else "false"),
                "schema_version": "1",
            }
            cn.executemany("INSERT INTO metadata VALUES (?,?)", meta.items())
            for table, rows in export["tables"].items():
                for row in rows:
                    raw = _canonical(row)
                    cn.execute("INSERT INTO raw_source_rows VALUES (?,?,?,?)",
                               (table, _unique_key(table, row), raw,
                                sha256(raw).hexdigest()))
            if cn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise QuarantineError("Quarantine SQLite integrity check failed")
            cn.execute("COMMIT")
        except BaseException:
            if cn.in_transaction:
                cn.execute("ROLLBACK")
            raise
        finally:
            cn.close()
        # Hard-link is no-clobber; we never overwrite an existing destination.
        os.link(tmp, dest)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return report


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise QuarantineError("Duplicate JSON property")
        result[key] = value
    return result


__all__ = ["QuarantineError", "profile_export", "create_quarantine"]
