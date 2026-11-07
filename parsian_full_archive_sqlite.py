"""Lossless typed-JSON preservation of all legacy SQL source rows in SQLite.

No trusted access to Madar accounting/event tables, no password accounts
creation, no parsing of tax/customer identifiers into live systems. The source
remains attached-live export, NOT a verified restored BAK snapshot.
"""
from __future__ import annotations

import base64
from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile


class FullArchiveError(ValueError):
    pass


_ALLOWED_TYPES = {"null", "integer", "float", "decimal", "datetime",
                  "text", "bit", "binary"}
_LIVE_SOURCE = "ATTACHED_LIVE_SQL_NOT_RESTORED_BACKUP"
_RESTORED_SOURCE = "ISOLATED_RESTORED_BAK_VERIFIED_20261026"
_NAME = re.compile(r"tbl_[A-Za-z0-9_]+\Z", re.IGNORECASE)
MAX_RAW_FILE = 120 * 1024 * 1024
MAX_LINE = 3 * 1024 * 1024
MAX_ROWS = 150000


def _strict_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise FullArchiveError("Duplicate JSON field")
        out[key] = value
    return out


def _strict_json(s):
    return json.loads(s, object_pairs_hook=_strict_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(
                          FullArchiveError("Nonfinite JSON numeric constant")))


def _check_fields(fields):
    if type(fields) is not dict or len(fields) > 150:
        raise FullArchiveError("Invalid number of source columns")
    for key, field in fields.items():
        if (type(key) is not str or not key or len(key) > 128 or
                type(field) is not dict or
                field.get("t") not in _ALLOWED_TYPES):
            raise FullArchiveError("Invalid source field type")
        kind = field["t"]
        expected = ({"t"} if kind == "null" else
                    {"t", "value"} if kind in ("bit", "text") else
                    {"t", "b64"} if kind == "binary" else {"t", "text"})
        if set(field) != expected:
            raise FullArchiveError("Unknown value shape")
        if kind == "bit" and type(field["value"]) is not bool:
            raise FullArchiveError("Invalid bit value")
        if kind == "text" and type(field["value"]) is not str:
            raise FullArchiveError("Invalid text value")
        if kind in ("float", "integer", "decimal", "datetime"):
            if type(field["text"]) is not str or len(field["text"]) > 96:
                raise FullArchiveError("Unexpected numeric/date value")
        if kind == "binary":
            val = field["b64"]
            if type(val) is not str or len(val) > MAX_LINE:
                raise FullArchiveError("Oversized binary field")
            try:
                base64.b64decode(val, validate=True)
            except ValueError as exc:
                raise FullArchiveError("Invalid base64 field") from exc


def create_archive(raw_jsonl, source_manifest, archive_db):
    """Create only on nonexistent SQLite path; verify every source row digest.

    Returns aggregate counts; never prints actual private row contents.
    """
    src = Path(raw_jsonl).absolute()
    manifest_path = Path(source_manifest).absolute()
    dest = Path(archive_db).absolute()
    if (not src.is_file() or not manifest_path.is_file() or
            dest.exists() or dest.is_symlink() or
            any(x.is_symlink() for x in
                (src, manifest_path, dest.parent)) or
            not dest.parent.is_dir() or dest.suffix != ".sqlite3" or
            dest.name == "standalone-accounting.sqlite3" or
            src.stat().st_size > MAX_RAW_FILE):
        raise FullArchiveError("Unsafe source/target path")
    manifest = _strict_json(manifest_path.read_bytes().decode("utf-8"))
    if (type(manifest) is not dict or
        manifest.get("source") not in (_LIVE_SOURCE, _RESTORED_SOURCE) or
        manifest.get("snapshotMatchesBackup") is not
            (manifest.get("source") == _RESTORED_SOURCE) or
        manifest.get("sourceCurrency") not in (
            "RIAL_OWNER_CONFIRMED", "UNKNOWN_RAW_LEGACY_UNITS") or
            type(manifest.get("tableCounts")) is not dict or
            manifest.get("vendorTableCount") != len(manifest["tableCounts"]) or
            type(manifest.get("vendorRowCount")) is not int or
            not 0 <= manifest["vendorRowCount"] <= MAX_ROWS):
        raise FullArchiveError("Malformed full archive manifest")
    for name, count in manifest["tableCounts"].items():
        if not _NAME.fullmatch(name) or type(count) is not int or count < 0:
            raise FullArchiveError("Malformed source table declaration")
    with src.open("rb") as file:
        source_hash = sha256()
        while block := file.read(1024*1024):
            source_hash.update(block)
    if source_hash.hexdigest() != manifest.get("archiveSha256", "").lower():
        raise FullArchiveError("Source archive digest mismatch")
    counts = Counter()
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
                prefix=".parsian-full-", suffix=".sqlite3",
                dir=dest.parent, delete=False) as handle:
            temp_path = Path(handle.name)
        with closing(sqlite3.connect(temp_path, isolation_level=None)) as db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("CREATE TABLE archive_meta("
                           "key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("CREATE TABLE archived_rows("
                           "source_table TEXT NOT NULL, ordinal INTEGER NOT NULL,"
                           "typed_raw_json BLOB NOT NULL, row_sha256 TEXT NOT NULL,"
                           "PRIMARY KEY(source_table,ordinal))")
                for key, value in {
                    "source_class": manifest["source"],
                    "source_archive_sha256": source_hash.hexdigest(),
                    "financial_posting_authorized": "false",
                    "bak_snapshot_equivalence_verified": (
                        "true" if manifest["source"] == _RESTORED_SOURCE else "false"),
                    "vendor_login_data_not_installed": "true",
                    "encoding": "UTF-8, JSON typed values",
                }.items():
                    db.execute("INSERT INTO archive_meta VALUES(?,?)",
                               (key, value))
                with src.open("rb") as stream:
                    for raw in stream:
                        if len(raw) > MAX_LINE:
                            raise FullArchiveError("Oversized source row")
                        entry = _strict_json(raw.decode("utf-8"))
                        if type(entry) is not dict or set(entry) != {
                                "table", "fields"}:
                            raise FullArchiveError("Invalid source row envelope")
                        table = entry["table"]
                        if table not in manifest["tableCounts"]:
                            raise FullArchiveError("Undeclared source table")
                        _check_fields(entry["fields"])
                        idx = counts[table]
                        counts[table] += 1
                        db.execute("INSERT INTO archived_rows VALUES(?,?,?,?)",
                                   (table, idx, raw.rstrip(b"\r\n"),
                                    sha256(raw.rstrip(b"\r\n")).hexdigest()))
                        if sum(counts.values()) > MAX_ROWS:
                            raise FullArchiveError("Row cap exceeded")
                if (dict(counts) != {k: v for k, v in
                                    manifest["tableCounts"].items() if v > 0} or
                        sum(counts.values()) != manifest["vendorRowCount"]):
                    raise FullArchiveError("Missing or unexpected table rows")
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise FullArchiveError("Broken destination SQLite integrity")
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        os.link(temp_path, dest)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return {
        "archivedSourceTables": len(manifest["tableCounts"]),
        "archivedSourceRows": sum(counts.values()),
        "archiveIntegrity": "OK",
        "sourceProvenance": manifest["source"],
        "financialOperationalDataImported": False,
        "sourceBackupSnapshotProven": manifest["source"] == _RESTORED_SOURCE,
        "userCredentialsMigratedToMadar": False,
    }


__all__ = ["create_archive", "FullArchiveError"]
