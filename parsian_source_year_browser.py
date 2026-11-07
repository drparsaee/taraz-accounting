"""Read-only, admin-gated access to complete archived Parsian source-year rows.

Nothing in this module creates operational invoices, journal entries, parties,
cash transactions, cheques or stock. Source values are archival evidence only.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3


SOURCE = "ISOLATED_RESTORED_BAK_VERIFIED_20261026"
EXPECTED_SHA = {
    "1404": "D46D6E975DF6A59C3FB42FF695F39A911979304AD54B8450DFD7AA70F5308779",
    "1405": "EAF55D9A4C2CF2EF28C9C5AF01B57E61C1773E8A33F16F09174D1E41967B6946",
}
_TABLENAME = re.compile(r"tbl_[A-Za-z0-9_]+\Z", re.IGNORECASE)
_PRIVATE = re.compile(r"password|passwd|secret|credential|token|api_?key|private_?key|salt|auth", re.I)
MAX_ROWS = 40


class SourceArchiveError(ValueError):
    pass


def _load(base, year):
    if year not in EXPECTED_SHA or type(year) is not str:
        raise SourceArchiveError("Unknown Parsian source year")
    base = Path(base).absolute()
    folder = base / "parsian-source-years"
    archive = folder / (year + ".sqlite3")
    manifest_file = folder / (year + "-manifest.json")
    if not archive.exists() and not manifest_file.exists():
        return None
    if (folder.is_symlink() or archive.is_symlink() or manifest_file.is_symlink()
            or not archive.is_file() or not manifest_file.is_file()
            or manifest_file.stat().st_size > 200_000):
        raise SourceArchiveError("Untrusted or incomplete Parsian source archive")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceArchiveError("Unreadable archive manifest") from exc
    if (type(manifest) is not dict or manifest.get("source") != SOURCE
            or manifest.get("snapshotMatchesBackup") is not True
            or manifest.get("sourceBackupSha256", "").upper() != EXPECTED_SHA[year]
            or type(manifest.get("tableCounts")) is not dict
            or manifest.get("vendorTableCount") != len(manifest["tableCounts"])
            or type(manifest.get("vendorRowCount")) is not int
            or not all(type(n) is str and _TABLENAME.fullmatch(n)
                       and type(c) is int and c >= 0
                       for n, c in manifest["tableCounts"].items())):
        raise SourceArchiveError("Invalid source-year provenance or table counts")
    return archive, manifest


def _open_db(path, manifest):
    cn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
    cn.execute("PRAGMA query_only=ON")
    meta = dict(cn.execute("SELECT key,value FROM archive_meta"))
    if (meta.get("source_class") != SOURCE
            or meta.get("bak_snapshot_equivalence_verified") != "true"
            or meta.get("financial_posting_authorized") != "false"
            or meta.get("source_archive_sha256") != manifest.get("archiveSha256", "").lower()):
        cn.close()
        raise SourceArchiveError("Source-year archive verification failed")
    return cn


def list_year_archives(book_directory):
    out = []
    for year in sorted(EXPECTED_SHA, reverse=True):
        entry = _load(book_directory, year)
        if entry is None:
            continue
        archive, manifest = entry
        with closing(_open_db(archive, manifest)) as cn:
            actual = dict(cn.execute(
                "SELECT source_table,COUNT(*) FROM archived_rows GROUP BY source_table"))
            required = {name: count for name, count in manifest["tableCounts"].items() if count}
            if actual != required or sum(actual.values()) != manifest["vendorRowCount"]:
                raise SourceArchiveError("Incomplete archived source rows")
        out.append({"year": year, "source": "restored-backup",
                    "currencyVerified": manifest.get("sourceCurrency") == "RIAL_OWNER_CONFIRMED",
                    "tableCount": len(manifest["tableCounts"]),
                    "rowCount": manifest["vendorRowCount"],
                    "tables": [{"name": name, "rows": count}
                               for name, count in sorted(manifest["tableCounts"].items())]})
    return out


def _preview_row(raw, digest):
    if sha256(raw).hexdigest() != digest:
        raise SourceArchiveError("Source row checksum mismatch")
    item = json.loads(raw)
    if type(item) is not dict or type(item.get("fields")) is not dict:
        raise SourceArchiveError("Malformed archived source row")
    values = {}
    for name, field in item["fields"].items():
        if type(name) is not str or type(field) is not dict:
            raise SourceArchiveError("Invalid source field")
        typ = field.get("t")
        if _PRIVATE.search(name):
            val = "[محافظت‌شده: مقدار حساس نمایش داده نمی‌شود]"
        elif typ == "binary":
            val = "[فایل یا داده باینری آرشیوشده]"
        elif typ == "null":
            val = ""
        elif typ in ("datetime", "decimal", "float", "integer"):
            val = str(field.get("text", ""))[:500]
        elif typ in ("bit", "text"):
            val = str(field.get("value", ""))[:500]
        else:
            raise SourceArchiveError("Invalid typed value in source row")
        values[name[:128]] = val
    return values


def source_table_page(book_directory, year, table, offset=0):
    if (type(table) is not str or not _TABLENAME.fullmatch(table)
            or type(offset) is not int or offset < 0 or offset > 150_000):
        raise SourceArchiveError("Invalid source query")
    entry = _load(book_directory, year)
    if entry is None:
        raise SourceArchiveError("No verified archive for selected year")
    archive, manifest = entry
    if table not in manifest["tableCounts"]:
        raise SourceArchiveError("Table not declared by the source backup")
    limit = manifest["tableCounts"][table]
    with closing(_open_db(archive, manifest)) as cn:
        records = cn.execute(
            "SELECT ordinal,typed_raw_json,row_sha256 FROM archived_rows "
            "WHERE source_table=? ORDER BY ordinal LIMIT ? OFFSET ?",
            (table, MAX_ROWS, offset)).fetchall()
    return {"year": year, "table": table, "offset": offset,
            "total": limit, "pageSize": MAX_ROWS,
            "rows": [{"ordinal": pos + 1, "fields": _preview_row(raw, digest)}
                     for pos, raw, digest in records],
            "sourceStatus": "historical-reference-only-not-operational"}
