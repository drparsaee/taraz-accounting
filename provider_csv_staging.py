"""Read-only, provider-neutral CSV review before any accounting migration.

This module neither imports to Madar nor infers proprietary software formats.
Every provider supplies an explicit CSV header mapping, text encoding, delimiter,
Gregorian dates, enum translations and source monetary unit. No SQL/APPDATA/DB
access or RIAL/TOMAN conversion is performed.
"""

from __future__ import annotations

import csv
from datetime import date
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re


class CsvStagingError(ValueError):
    """CSV format, mapping, reference or currency cannot be trusted."""


SCHEMA_VERSION = 1
MAX_BYTES = 5_000_000
MAX_ROWS = 10_000
MAX_COLUMNS = 64
MAX_MONEY = 10**15
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_REQUIRED = {
    "parties": frozenset({"id", "name", "kind"}),
    "invoices": frozenset({"id", "partyId", "kind", "date", "status", "total"}),
    "transactions": frozenset({"id", "partyId", "documentId", "kind", "date", "amount"}),
}
_ENUMS = {
    "parties": {"kind": frozenset({"customer", "vendor", "both"})},
    "invoices": {"kind": frozenset({"invoice", "bill"}),
                 "status": frozenset({"draft", "issued"})},
    "transactions": {"kind": frozenset({"receipt", "payment"})},
}
_ENCODINGS = frozenset({"utf-8", "utf-8-sig", "cp1256"})
_DELIMITERS = frozenset({",", ";", "\t"})


def _shape(value, required, optional=(), *, label="object"):
    if (type(value) is not dict or not set(required) <= set(value)
            or set(value) - set(required) - set(optional)):
        raise CsvStagingError(f"Invalid {label} fields")


def _identifier(value, label):
    if type(value) is not str or not _ID.fullmatch(value):
        raise CsvStagingError(f"Invalid {label} identifier")
    return value


def _date(value):
    if type(value) is not str or len(value) != 10:
        raise CsvStagingError("Expected explicit Gregorian YYYY-MM-DD date")
    try:
        parsed = date.fromisoformat(value)
        # An ISO-looking Jalali 14xx date is also syntactically valid in the
        # Gregorian calendar. Refuse that ambiguity in historical migration.
        if not 1900 <= parsed.year <= 2100 or parsed.isoformat() != value:
            raise ValueError("Non-canonical date")
    except ValueError as exc:
        raise CsvStagingError("Invalid Gregorian YYYY-MM-DD date") from exc
    return value


def _money(value, label):
    # Fractional values, digit grouping, signs and non-ASCII numerals require
    # review by the provider; guessing would affect the financial truth.
    if type(value) is not str or not re.fullmatch(r"[0-9]+", value, re.ASCII):
        raise CsvStagingError(f"{label} requires whole ASCII digits")
    amount = int(value)
    if amount > MAX_MONEY:
        raise CsvStagingError(f"{label} exceeds maximum RIAL value")
    return amount


def _safe_text(value, label):
    if (type(value) is not str or not value.strip() or len(value) > 300
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise CsvStagingError(f"Invalid {label} text")
    return value.strip()


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False)
                  .encode("utf-8")).hexdigest()


def _spec(name, source):
    _shape(source, {"path", "format", "encoding", "delimiter", "mapping"},
           {"ignoreColumns", "valueMaps"}, label=f"{name} CSV specification")
    if (source["format"] != "csv" or type(source["encoding"]) is not str
            or source["encoding"] not in _ENCODINGS):
        raise CsvStagingError("Unsupported CSV format or encoding")
    if type(source["delimiter"]) is not str or source["delimiter"] not in _DELIMITERS:
        raise CsvStagingError("Unsupported CSV delimiter")
    mapping = source["mapping"]
    if type(mapping) is not dict or set(mapping) != _REQUIRED[name]:
        raise CsvStagingError(f"Incomplete or unknown {name} column mapping")
    if any(type(column) is not str or not column.strip() or len(column) > 128
           for column in mapping.values()):
        raise CsvStagingError("Invalid mapped CSV column")
    ignore = source.get("ignoreColumns", [])
    if (type(ignore) is not list or len(ignore) > MAX_COLUMNS
            or any(type(c) is not str or not c.strip() or len(c) > 128 for c in ignore)):
        raise CsvStagingError("Invalid ignored columns declaration")
    declared = [*mapping.values(), *ignore]
    if len(set(c.casefold() for c in declared)) != len(declared):
        raise CsvStagingError("Duplicated source mapping or ignored column")
    value_maps = source.get("valueMaps", {})
    if type(value_maps) is not dict or set(value_maps) - set(_ENUMS[name]):
        raise CsvStagingError("Unknown enum mapping")
    for key, translation in value_maps.items():
        if (type(translation) is not dict or not translation or
                any(type(k) is not str or not k or type(v) is not str or
                    v not in _ENUMS[name][key] for k, v in translation.items())):
            raise CsvStagingError("Invalid source enum translations")
    return declared, value_maps


def inspect_csv_headers(path, *, encoding, delimiter):
    """Return only exact CSV column names from an explicit bounded local file.

    No rows are returned. A subsequent staging preview validates all rows.
    """
    if type(path) is not str or not Path(path).is_absolute():
        raise CsvStagingError("Selected CSV path must be absolute")
    if (type(encoding) is not str or encoding not in _ENCODINGS or
            type(delimiter) is not str or delimiter not in _DELIMITERS):
        raise CsvStagingError("Unsupported CSV encoding or delimiter")
    source = Path(path)
    if (source.is_symlink() or not source.is_file() or
            not 0 < source.stat().st_size <= MAX_BYTES):
        raise CsvStagingError("Expected regular non-symlink CSV under 5 MB")
    raw = source.read_bytes()
    if len(raw) > MAX_BYTES or b"\x00" in raw:
        raise CsvStagingError("CSV bytes exceed bound or contain NUL")
    try:
        decoded = raw.decode(encoding, errors="strict")
    except UnicodeError as exc:
        raise CsvStagingError("CSV cannot decode using declared encoding") from exc
    if "\ufeff" in decoded:
        raise CsvStagingError("Unexpected BOM; use utf-8-sig for BOM input")
    try:
        header = next(csv.reader(StringIO(decoded, newline=""),
                                 delimiter=delimiter, strict=True), None)
    except csv.Error as exc:
        raise CsvStagingError("Malformed CSV header") from exc
    if (type(header) is not list or not 1 <= len(header) <= MAX_COLUMNS
            or any(type(h) is not str or not h.strip() or len(h) > 128
                   for h in header)
            or len({h.casefold() for h in header}) != len(header)):
        raise CsvStagingError("Invalid CSV header")
    return header


def _read_csv(name, source):
    declared, value_maps = _spec(name, source)
    try:
        path = Path(source["path"])
    except (TypeError, ValueError) as exc:
        raise CsvStagingError("Invalid CSV path") from exc
    if (path.is_symlink() or not path.is_file() or
            not 0 < path.stat().st_size <= MAX_BYTES):
        raise CsvStagingError("Expected regular non-symlink CSV under 5 MB")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES or b"\x00" in raw:
        raise CsvStagingError("CSV bytes exceed bound or contain NUL")
    try:
        decoded = raw.decode(source["encoding"], errors="strict")
    except UnicodeError as exc:
        raise CsvStagingError("CSV cannot decode using declared encoding") from exc
    if "\ufeff" in decoded:
        raise CsvStagingError("Unexpected BOM; use utf-8-sig for BOM input")
    try:
        from io import StringIO
        reader = csv.DictReader(StringIO(decoded, newline=""),
                                delimiter=source["delimiter"], strict=True)
        header = reader.fieldnames
        if (type(header) is not list or not 1 <= len(header) <= MAX_COLUMNS
                or any(type(h) is not str or not h.strip() or len(h) > 128
                       for h in header)
                or len({h.casefold() for h in header}) != len(header)):
            raise CsvStagingError(f"Invalid {name} CSV header")
        if set(header) != set(declared):
            raise CsvStagingError(f"Unmapped, missing or unexpected {name} CSV columns")
        result = []
        for record in reader:
            if len(result) >= MAX_ROWS or None in record or any(v is None for v in record.values()):
                raise CsvStagingError(f"Malformed or oversized {name} CSV row")
            row = {}
            for field, column in source["mapping"].items():
                value = record[column]
                if field in _ENUMS[name]:
                    value = value_maps.get(field, {}).get(value, value)
                    if value not in _ENUMS[name][field]:
                        raise CsvStagingError(f"Unmapped {name}.{field} value")
                elif field in ("total", "amount"):
                    value = _money(value, f"{name}.{field}")
                elif field == "date":
                    value = _date(value)
                elif field == "name":
                    value = _safe_text(value, "party name")
                else:
                    value = _identifier(value, f"{name}.{field}")
                row[field] = value
            result.append(row)
    except csv.Error as exc:
        raise CsvStagingError(f"Malformed {name} CSV quoting") from exc
    return result, sha256(raw).hexdigest()


def _expectations(expected, counts, totals):
    if expected is None:
        return []
    _shape(expected, set(), {"counts", "totals"}, label="expectations")
    discrepancies = []
    for name, measured, labels in (("counts", counts, _REQUIRED),
                                   ("totals", totals, totals)):
        declared = expected.get(name, {})
        if (type(declared) is not dict or set(declared) - set(labels)
                or any(type(v) is not int or v < 0 for v in declared.values())):
            raise CsvStagingError(f"Invalid expected {name}")
        for key, amount in declared.items():
            if amount != measured[key]:
                discrepancies.append({"type": f"{name}_mismatch", "group": key,
                                      "expected": amount, "actual": measured[key]})
    return discrepancies


def stage_provider_csv(spec, *, previous_identity_fingerprints=()):
    """Validate three declared CSV exports; report review-only synthetic-safe metadata.

    No filesystem writes, SQL access, conversion, or accounting posting exists.
    Callers must not interpret a matching preview as approved reconciliation.
    """
    _shape(spec, {"schemaVersion", "provider", "currency", "datasets"},
           {"expectations"}, label="provider import contract")
    if type(spec["schemaVersion"]) is not int or spec["schemaVersion"] != SCHEMA_VERSION:
        raise CsvStagingError("Unsupported provider import schema version")
    provider = _safe_text(spec["provider"], "source provider")
    if len(provider) > 100:
        raise CsvStagingError("Source provider label too long")
    if spec["currency"] != "RIAL":
        raise CsvStagingError("Source currency must explicitly match RIAL; conversion unsupported")
    datasets = spec["datasets"]
    if type(datasets) is not dict or set(datasets) != set(_REQUIRED):
        raise CsvStagingError("Explicit parties/invoices/transactions CSV files required")
    if (type(previous_identity_fingerprints) not in (tuple, list, set, frozenset)
            or len(previous_identity_fingerprints) > 3 * MAX_ROWS
            or any(type(f) is not str or not _DIGEST.fullmatch(f)
                   for f in previous_identity_fingerprints)):
        raise CsvStagingError("Invalid previous identity fingerprints")
    previous = set(previous_identity_fingerprints)
    data, source_hashes = {}, {}
    fingerprints = {}
    discrepancies = []
    for group in _REQUIRED:
        rows, source_hashes[group] = _read_csv(group, datasets[group])
        ids = set()
        fingerprints[group] = []
        for row in rows:
            ident = row["id"].casefold()
            if ident in ids:
                raise CsvStagingError(f"Duplicate/case-colliding {group} ID")
            ids.add(ident)
            identity = _digest([SCHEMA_VERSION, provider, group, ident])
            fingerprints[group].append({"identity": identity,
                                        "content": _digest([identity, row])})
            if identity in previous:
                discrepancies.append({"type": "previous_identity_duplicate", "group": group,
                                      "identityFingerprint": identity})
        data[group] = rows
    parties = {item["id"]: item for item in data["parties"]}
    invoices = {item["id"]: item for item in data["invoices"]}
    for invoice in data["invoices"]:
        party = parties.get(invoice["partyId"])
        if party is None:
            raise CsvStagingError("Invoice references an unknown party")
        if (invoice["kind"] == "invoice" and party["kind"] == "vendor") or (
                invoice["kind"] == "bill" and party["kind"] == "customer"):
            raise CsvStagingError("Invoice kind conflicts with party role")
    allocated = {identifier: 0 for identifier in invoices}
    for transaction in data["transactions"]:
        invoice = invoices.get(transaction["documentId"])
        if invoice is None or transaction["partyId"] != invoice["partyId"]:
            raise CsvStagingError("Transaction has missing or mismatched invoice/party")
        if ((transaction["kind"] == "receipt" and invoice["kind"] != "invoice")
                or (transaction["kind"] == "payment" and invoice["kind"] != "bill")
                or invoice["status"] != "issued"):
            raise CsvStagingError("Transaction kind/status conflicts with document")
        if transaction["amount"] == 0:
            raise CsvStagingError("Zero-amount transaction is unsupported")
        allocated[invoice["id"]] += transaction["amount"]
        if allocated[invoice["id"]] > MAX_MONEY:
            raise CsvStagingError("Transaction allocation exceeds RIAL limit")
    for identifier, amount in allocated.items():
        if amount > invoices[identifier]["total"]:
            discrepancies.append({"type": "overallocated_document",
                                  "documentFingerprint": _digest([provider, "invoices", identifier]),
                                  "allocated": amount,
                                  "documentTotal": invoices[identifier]["total"]})
    counts = {group: len(data[group]) for group in _REQUIRED}
    totals = {kind: sum(r["total"] for r in data["invoices"] if r["kind"] == kind)
              for kind in ("invoice", "bill")}
    totals.update({kind: sum(r["amount"] for r in data["transactions"]
                             if r["kind"] == kind) for kind in ("receipt", "payment")})
    discrepancies.extend(_expectations(spec.get("expectations"), counts, totals))
    return {
        "schemaVersion": SCHEMA_VERSION, "previewOnly": True,
        "canApplyToMadar": False, "provider": provider, "sourceCurrency": "RIAL",
        "counts": counts, "totalsRial": totals,
        "sourceSha256": source_hashes, "fingerprints": fingerprints,
        "previewRows": {group: data[group][:3] for group in _REQUIRED},
        "discrepancies": discrepancies, "structuralChecksPassed": not discrepancies,
        "blockedReason": "financial_migration_requires_verified_line_items_gl_reconciliation_and_approval",
    }


__all__ = ["CsvStagingError", "SCHEMA_VERSION", "inspect_csv_headers",
           "stage_provider_csv"]
