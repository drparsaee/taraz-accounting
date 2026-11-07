"""Strictly offline, non-destructive Parsian SQL Server BAK *staging preview*.

No path or file APIs, SQL clients, network calls, SQL execution, application
state writes, business-row access, data conversion, import or restore exist
here. Inputs are synthetic byte headers and manually supplied schema *names*.
A TAPE magic prefix identifies only a possible SQL Server backup medium;
it does not reveal a schema, prove a restorable backup or verify currency.

Financial migration is ALWAYS blocked. A human-readable unit claim is NOT
independent unit verification. A new standalone Madar book uses whole RIAL;
legacy books can remain TOMAN and MUST NOT be silently reinterpreted.
"""

from __future__ import annotations

from hashlib import sha256
import json
import re


STAGING_VERSION = 1
MIN_BACKUP_BYTES = 512
MAX_BACKUP_BYTES = 50 * 1024**3  # Same bounds as parsian_backup_probe.
MAX_TABLES = 128
MAX_COLUMNS_PER_TABLE = 256
MAX_MAPPINGS = 128
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_REVIEW = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{3,95}\Z", re.ASCII)
_UNITS = frozenset({"RIAL", "TOMAN"})
_UNIT_METHODS = frozenset({"restored_schema_and_trial_balance",
                           "vendor_docs_and_reconciled_trial_balance"})

# A strictly finite *proposal vocabulary*, not a SQL-schema parser and not a
# commitment to a fully implemented Madar import API.
_TARGET_GROUPS = {
    "party": frozenset({"party.id", "party.name", "party.kind"}),
    "sales_invoice": frozenset({
        "sales_invoice.id", "sales_invoice.party_id", "sales_invoice.date",
        "sales_invoice.total",
    }),
    "purchase_bill": frozenset({
        "purchase_bill.id", "purchase_bill.party_id", "purchase_bill.date",
        "purchase_bill.total",
    }),
    "receipt": frozenset({
        "receipt.id", "receipt.invoice_id", "receipt.date", "receipt.amount",
    }),
    "payment": frozenset({
        "payment.id", "payment.bill_id", "payment.date", "payment.amount",
    }),
}
_TARGETS = frozenset().union(*_TARGET_GROUPS.values())
_MONEY_TARGETS = frozenset({
    "sales_invoice.total", "purchase_bill.total",
    "receipt.amount", "payment.amount",
})


def _text_id(value: object, field: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {field} identifier")
    return value


def _table_name(value: object) -> str:
    if type(value) is not str:
        raise ValueError("Invalid source table")
    fragments = value.split(".")
    if len(fragments) != 2:
        raise ValueError("Source table must be schema.table")
    for part in fragments:
        _text_id(part, "source table")
    return value


def _shape(value: object, fields: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"Invalid {label} shape")
    return value


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def classify_backup_header(header: bytes, *, size_bytes: int) -> dict:
    """Classify *caller-provided bytes*. Never open a file or infer schema.

    Require the full 16-byte synthetic/probe sample, not a path, stream, or
    row dump. The caller is responsible for obtaining it from a permitted copy
    under a separate authorization. Never point that caller at private BAKs.
    """
    if type(header) is not bytes or len(header) != 16:
        raise ValueError("Exactly 16 header bytes required")
    if (type(size_bytes) is not int or
            not MIN_BACKUP_BYTES <= size_bytes <= MAX_BACKUP_BYTES):
        raise ValueError("Backup byte count outside safe bounds")
    candidate = header.startswith(b"TAPE")
    return {
        "format": ("sqlserver_media_header_candidate" if candidate
                   else "unrecognized_media_header"),
        "signature": "TAPE" if candidate else "unsupported",
        "sizeBytes": size_bytes,
        "confidence": "signature_only" if candidate else "none",
        "schemaParsed": False,
        "backupValidityVerified": False,
        "canRestore": False,
        "canImport": False,
    }


def validate_schema_inventory(inventory: object) -> dict:
    """Validate manually curated table/column *names*, never data records.

    Does not parse SQL Server. Reject SQL syntax, case-colliding identifiers,
    extra fields/row content, oversized catalogs, missing primary keys and
    duplicate columns. A syntactically valid inventory is still UNVERIFIED.
    """
    _shape(inventory, {"schemaVersion", "tables"}, "schema inventory")
    if type(inventory["schemaVersion"]) is not int or inventory["schemaVersion"] != 1:
        raise ValueError("Unsupported schema inventory version")
    tables = inventory["tables"]
    if type(tables) is not list or not 1 <= len(tables) <= MAX_TABLES:
        raise ValueError("Invalid table count")
    known_tables = set()
    rows = {}
    column_count = 0
    for table in tables:
        _shape(table, {"name", "columns", "primaryKey"}, "table")
        name = _table_name(table["name"])
        norm = name.lower()
        if norm in known_tables:
            raise ValueError("Duplicate or case-colliding table")
        known_tables.add(norm)
        cols, key = table["columns"], table["primaryKey"]
        if (type(cols) is not list or not 1 <= len(cols) <= MAX_COLUMNS_PER_TABLE or
                type(key) is not list or not 1 <= len(key) <= 8):
            raise ValueError("Invalid columns or primary key")
        names = set()
        for column in cols:
            label = _text_id(column, "column")
            low = label.lower()
            if low in names:
                raise ValueError("Duplicate or case-colliding column")
            names.add(low)
        primary = [_text_id(item, "primary key") for item in key]
        if len({item.lower() for item in primary}) != len(primary):
            raise ValueError("Duplicate primary-key component")
        if any(item.lower() not in names for item in primary):
            raise ValueError("Primary key not present in table columns")
        rows[norm] = sorted(names)
        column_count += len(names)
    return {"tables": rows, "tableCount": len(rows), "columnCount": column_count}


def validate_field_mapping(inventory: object, mappings: object,
                           *, required_groups: object = ()) -> dict:
    """Validate proposals structurally; no records or money can be imported.

    A mapping is {sourceTable, sourceColumn, targetField, sourceUnit}.
    sourceUnit is null for non-money targets; a literal RIAL/TOMAN *claim*
    is mandatory for money fields but does not verify unit. The mapping cannot
    create SQL or call into accounting and contains no transformation language.
    """
    source = validate_schema_inventory(inventory)
    if type(mappings) is not list or not 1 <= len(mappings) <= MAX_MAPPINGS:
        raise ValueError("Invalid mapping count")
    if type(required_groups) not in (tuple, list):
        raise ValueError("Invalid required groups")
    groups = []
    for group in required_groups:
        if type(group) is not str or group not in _TARGET_GROUPS or group in groups:
            raise ValueError("Unsupported or duplicate required group")
        groups.append(group)
    used_sources, used_targets, units = set(), set(), set()
    normalized = []
    for item in mappings:
        _shape(item, {"sourceTable", "sourceColumn", "targetField", "sourceUnit"},
               "mapping")
        table = _table_name(item["sourceTable"])
        column = _text_id(item["sourceColumn"], "source column")
        target = item["targetField"]
        if type(target) is not str or target not in _TARGETS:
            raise ValueError("Unknown destination field")
        if table.lower() not in source["tables"] or (
                column.lower() not in source["tables"][table.lower()]):
            raise ValueError("Mapping source missing from supplied inventory")
        key = (table.lower(), column.lower())
        if key in used_sources or target in used_targets:
            raise ValueError("Duplicate source or destination mapping")
        used_sources.add(key)
        used_targets.add(target)
        unit = item["sourceUnit"]
        if target in _MONEY_TARGETS:
            if type(unit) is not str or unit not in _UNITS:
                raise ValueError("Money target requires explicit RIAL/TOMAN claim")
            units.add(unit)
        elif unit is not None:
            raise ValueError("Non-money mappings must have null sourceUnit")
        normalized.append({"table": table.lower(), "column": column.lower(),
                           "target": target, "unit": unit})
    if len(units) > 1:
        # A source with mixed currencies needs line-level, independently
        # verified attribution, which this staging contract does not support.
        raise ValueError("Mixed RIAL/TOMAN source units are not supported")
    required = set().union(*(_TARGET_GROUPS[group] for group in groups))
    missing = sorted(required - used_targets)
    return {
        "mappedFields": len(normalized),
        "moneyFields": sum(item["target"] in _MONEY_TARGETS for item in normalized),
        "claimedSourceUnit": next(iter(units), None),
        "requiredGroups": sorted(groups),
        "missingTargets": missing,
        "mappingComplete": bool(groups) and not missing,
        # This is a digest of *declared mapping metadata*, not of any backup.
        "proposalDigest": sha256(_json(normalized).encode("ascii")).hexdigest(),
    }


def validate_currency_evidence(evidence: object) -> dict:
    """Shape-check a review claim. DO NOT interpret this as verification.

    Hash/reference are caller-provided, not authenticated or compared against
    SQL Server restored ledgers. No public flag can turn on a money import.
    """
    if evidence is None:
        return {"unitClaim": None, "claimFormatValid": False,
                "independentlyVerified": False, "status": "missing"}
    _shape(evidence, {"sourceUnit", "method", "evidenceSha256", "reviewId"},
           "currency evidence")
    unit = evidence["sourceUnit"]
    if type(unit) is not str or unit not in _UNITS:
        raise ValueError("Currency unit must be explicit RIAL or TOMAN")
    if (type(evidence["method"]) is not str or
            evidence["method"] not in _UNIT_METHODS or
            type(evidence["evidenceSha256"]) is not str or
            not _SHA256.fullmatch(evidence["evidenceSha256"]) or
            type(evidence["reviewId"]) is not str or
            not _REVIEW.fullmatch(evidence["reviewId"])):
        raise ValueError("Unacceptable currency review claim")
    return {"unitClaim": unit, "claimFormatValid": True,
            "independentlyVerified": False, "status": "review_claim_only"}


def build_staging_manifest(header: bytes, *, size_bytes: int,
                           inventory: object = None, mappings: object = None,
                           required_groups: object = (),
                           currency_evidence: object = None) -> dict:
    """Return a redacted, JSON-serializable MANIFEST, never an import payload.

    No source tables, source column labels, names, people, balances, BAK file
    paths or evidence hashes are exposed in the returned manifest. A source
    *unit claim* is intentionally kept separate from verified currency.
    """
    classification = classify_backup_header(header, size_bytes=size_bytes)
    evidence = validate_currency_evidence(currency_evidence)
    if (inventory is None) != (mappings is None):
        raise ValueError("Inventory and mappings must be supplied together")
    if inventory is None:
        if required_groups not in ((), []):
            raise ValueError("Required groups need a schema mapping")
        summary = None
        mapping = None
    else:
        summary = validate_schema_inventory(inventory)
        mapping = validate_field_mapping(inventory, mappings,
                                         required_groups=required_groups)
        claimed = mapping["claimedSourceUnit"]
        if claimed is not None and evidence["unitClaim"] is not None and (
                claimed != evidence["unitClaim"]):
            raise ValueError("Money mapping unit contradicts currency review claim")
    return {
        "stagingVersion": STAGING_VERSION,
        "classification": classification,
        "schemaStatus": "not_parsed_from_backup",
        "inventoryStatus": ("absent" if summary is None
                            else "manually_supplied_unverified"),
        "inventoryCounts": (None if summary is None else
                            {"tables": summary["tableCount"],
                             "columns": summary["columnCount"]}),
        "mapping": mapping,
        "currencyReview": evidence,
        "targetUnit": "RIAL",
        "conversionPlan": (
            "none_without_verified_source_unit"
            if evidence["unitClaim"] is None or mapping is None or
            mapping["moneyFields"] == 0
            else "RIAL_identity_requires_reconciliation"
            if evidence["unitClaim"] == "RIAL"
            else "TOMAN_to_RIAL_requires_exact_multiply_by_10_per_amount"
        ),
        "moneyImportAllowed": False,
        "allImportAllowed": False,
        "canApplyToMadar": False,
        "blockingReasons": [
            "backup_not_restored_or_schema_verified",
            "no_verified_source_unit_or_authenticated_review",
            "mapping_not_verified_against_restored_schema",
            "no_reconciled_trial_balance_or_atomic_import",
        ],
    }


__all__ = [
    "STAGING_VERSION", "classify_backup_header", "validate_schema_inventory",
    "validate_field_mapping", "validate_currency_evidence",
    "build_staging_manifest",
]
