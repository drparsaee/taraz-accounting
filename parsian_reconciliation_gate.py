"""Offline, non-mutating Parsian -> Madar reconciliation *gate*, not an importer.

Takes two EXPLICIT, externally prepared and reviewed summary exports. Does not
connect to SQL Server, inspect an actual BAK, look for user data, or write to
Madar. Each source value is an unverified external claim until corroborated
against a genuinely isolated vendor restore and signed accountant reports.

Financial values are exact whole units. New standalone Madar ledgers use RIAL,
and historical TOMAN sources MUST be multiplied by 10, never divided.
"""
from __future__ import annotations

from datetime import date
import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys

SCHEMA_VERSION = 1
MAX_REPORT_BYTES = 5_000_000
MAX_ROWS = 100_000
MAX_RIAL = 10**15
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,95}\Z", re.ASCII)
_COUNT_KEYS = ("journals", "salesInvoices", "purchaseBills", "receipts",
               "payments", "inventoryMovements", "cheques")
_GROUP_KEYS = ("trialBalance", "parties", "cashBanks")
_CROSSWALK_KEYS = ("accounts", "parties", "cashBanks")


class ReconciliationError(ValueError):
    """Malformed, non-reconcilable or unverifiable staged input."""


def _exact(value, keys, where):
    if type(value) is not dict or set(value) != set(keys):
        raise ReconciliationError(f"Invalid {where} shape")
    return value


def _id(value, what):
    if type(value) is not str or not _KEY.fullmatch(value):
        raise ReconciliationError(f"Invalid {what}")
    return value


def _unit(value, what):
    if value not in ("TOMAN", "RIAL") or type(value) is not str:
        raise ReconciliationError(f"Invalid {what}")
    return value


def _money(value, what, *, signed=False):
    if (type(value) is not int or value > MAX_RIAL or
            value < (-MAX_RIAL if signed else 0)):
        raise ReconciliationError(f"Invalid {what} value")
    return value


def _whole_date(value, what):
    if (type(value) is not str or len(value) != 10 or
            not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value, re.ASCII)):
        raise ReconciliationError(f"Invalid {what}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ReconciliationError(f"Invalid {what}") from exc
    return value


def _rows(rows, fields, where):
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise ReconciliationError(f"Invalid {where} row count")
    index = {}
    for item in rows:
        _exact(item, fields, where)
        name = _id(item["id"], f"{where} identifier")
        if name.casefold() in index:
            raise ReconciliationError(f"Duplicate {where} identifier")
        for field in fields - {"id"}:
            _money(item[field], f"{where}.{field}",
                   signed=field == "balance")
        index[name.casefold()] = item
    return index


def validate_snapshot(snapshot, *, kind):
    """All expected domains MUST be present, including empty arrays.

    A snapshot is a declared export, not proof that the upstream database was
    actually queried. Exact schema and no null/missing values prevent a false
    PASS caused by silent omission of a financial domain.
    """
    _exact(snapshot, {"schemaVersion", "sourceSystem", "companyRef", "asOf",
                      "currency", "trialBalance", "parties", "cashBanks",
                      "controlTotals", "documentCounts"}, "snapshot")
    if type(snapshot["schemaVersion"]) is not int or snapshot["schemaVersion"] != 1:
        raise ReconciliationError("Unsupported reconciliation schema")
    expected = "PARSIAN" if kind == "source" else "MADAR"
    if snapshot["sourceSystem"] != expected:
        raise ReconciliationError("Wrong source system for snapshot")
    _id(snapshot["companyRef"], "company reference")
    _whole_date(snapshot["asOf"], "as-of date")
    _unit(snapshot["currency"], "snapshot currency")
    tb = _rows(snapshot["trialBalance"], {"id", "debit", "credit"}, "trial balance")
    party = _rows(snapshot["parties"], {"id", "receivable", "payable"}, "party")
    bank = _rows(snapshot["cashBanks"], {"id", "balance"}, "cash/bank")
    totals = _exact(snapshot["controlTotals"],
                    {"receivable", "payable", "cashBank"}, "control totals")
    for field in totals:
        _money(totals[field], "control." + field, signed=field == "cashBank")
    counts = _exact(snapshot["documentCounts"], _COUNT_KEYS, "document counts")
    for field in counts:
        if type(counts[field]) is not int or not 0 <= counts[field] <= 10**9:
            raise ReconciliationError("Invalid document count")
    if sum(x["debit"] for x in tb.values()) != sum(x["credit"] for x in tb.values()):
        raise ReconciliationError("Trial balance is not debit/credit balanced")
    if sum(x["receivable"] for x in party.values()) != totals["receivable"]:
        raise ReconciliationError("Party receivables do not match stated AR control")
    if sum(x["payable"] for x in party.values()) != totals["payable"]:
        raise ReconciliationError("Party payables do not match stated AP control")
    if sum(x["balance"] for x in bank.values()) != totals["cashBank"]:
        raise ReconciliationError("Cash/bank rows do not match stated cash control")
    return {"trialBalance": tb, "parties": party, "cashBanks": bank}


def _crosswalk(source_index, target_index, mapping, domain):
    if type(mapping) is not dict or len(mapping) > MAX_ROWS:
        raise ReconciliationError("Invalid crosswalk")
    from_ids, to_ids = set(), set()
    for old, new in mapping.items():
        _id(old, "crosswalk source ID")
        _id(new, "crosswalk target ID")
        norm_old, norm_new = old.casefold(), new.casefold()
        if norm_old in from_ids or norm_new in to_ids:
            raise ReconciliationError("Crosswalk is not one-to-one")
        if norm_old not in source_index or norm_new not in target_index:
            raise ReconciliationError(f"Crosswalk references unknown {domain} record")
        from_ids.add(norm_old)
        to_ids.add(norm_new)
    return {old.casefold(): new.casefold() for old, new in mapping.items()}


def _rials(value, unit, *, signed=False):
    value = _money(value, "financial amount", signed=signed)
    scaled = value * (10 if unit == "TOMAN" else 1)
    if abs(scaled) > MAX_RIAL:
        raise ReconciliationError("RIAL normalization exceeds safe exact integer limit")
    return scaled


def compare_snapshots(source, target, *, crosswalk=None):
    """Fail closed if any financial line, control or document count differs.

    The report deliberately omits entity identifiers, company details and
    transaction amounts. It only reports aggregate mismatch *counts* and
    status. A PASS proves equality of the provided samples, NOT completeness
    or authenticity of the original Parsian data.
    """
    src = validate_snapshot(source, kind="source")
    dst = validate_snapshot(target, kind="target")
    if source["companyRef"] != target["companyRef"]:
        raise ReconciliationError("Company identity mismatch")
    if source["asOf"] != target["asOf"]:
        raise ReconciliationError("As-of dates differ")
    if target["currency"] != "RIAL":
        raise ReconciliationError("Target must be a reviewed independent RIAL ledger")
    if crosswalk is None:
        crosswalk = {key: {} for key in _CROSSWALK_KEYS}
    _exact(crosswalk, _CROSSWALK_KEYS, "crosswalk")
    mismatches = {}
    mapping_specs = (
        ("trialBalance", "accounts", ("debit", "credit")),
        ("parties", "parties", ("receivable", "payable")),
        ("cashBanks", "cashBanks", ("balance",)),
    )
    for group, cross_key, fields in mapping_specs:
        a, b = src[group], dst[group]
        mapped = _crosswalk(a, b, crosswalk[cross_key], group)
        seen = set()
        missing, unequal = 0, 0
        for source_id, source_row in a.items():
            dest_id = mapped.get(source_id, source_id)
            if dest_id in seen:
                raise ReconciliationError("Crosswalk maps multiple source rows to one target")
            seen.add(dest_id)
            if dest_id not in b:
                missing += 1
                continue
            if any(_rials(source_row[key], source["currency"],
                          signed=key == "balance") != b[dest_id][key]
                   for key in fields):
                unequal += 1
        extra = len(set(b) - seen)
        mismatches[group] = {"missing": missing, "extra": extra, "unequal": unequal}

    different_controls = sum(
        _rials(source["controlTotals"][key], source["currency"],
               signed=key == "cashBank") != target["controlTotals"][key]
        for key in ("receivable", "payable", "cashBank")
    )
    different_counts = sum(
        source["documentCounts"][key] != target["documentCounts"][key]
        for key in _COUNT_KEYS
    )
    matched = (not different_controls and not different_counts and
               all(not any(counts.values()) for counts in mismatches.values()))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "stagingOnly": True,
        "sourceAuthenticated": False,
        "mappingIndependentlyVerified": False,
        "safeToImport": False,
        "sourceCurrencyClaim": source["currency"],
        "targetCurrency": "RIAL",
        "currencyNormalization": ("multiply_by_10" if source["currency"] == "TOMAN"
                                  else "identity"),
        "balancesMatchInSuppliedSnapshots": matched,
        "mismatches": mismatches,
        "unequalControls": different_controls,
        "unequalDocumentCounts": different_counts,
        "gateStatus": "SAMPLE_BALANCES_EQUAL_UNVERIFIED" if matched
                      else "RECONCILIATION_FAILED",
        "blockingReasons": [
            "source_restored_clone_and_schema_not_independently_attested",
            "record_and_currency_mapping_not_reviewed_by_accountant",
            "no_verified_complete_source_history_or_cutover",
            "never_write_to_live_madar_or_parsian_from_this_gate",
        ],
    }


def _no_duplicate_keys(pairs):
    result = {}
    for key, val in pairs:
        if key in result:
            raise ReconciliationError("Duplicate JSON property")
        result[key] = val
    return result


def _file(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or path.suffix.lower() != ".json":
        raise ReconciliationError("Use an explicit, regular, absolute JSON fixture")
    if not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
        raise ReconciliationError("Missing or oversized JSON fixture")
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_REPORT_BYTES:
        raise ReconciliationError("Empty or oversized JSON fixture")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ReconciliationError("Nonfinite JSON numeric constant")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError("Malformed JSON fixture") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="OFFLINE read-only comparison of reviewed PARSIAN/MADAR summary JSONs")
    parser.add_argument("--parsian-summary", required=True, type=Path)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--madar-summary", type=Path)
    target.add_argument("--madar-backup", type=Path,
                        help="ONLY a validated portable standalone accounting AUTO backup")
    parser.add_argument("--company-ref", help="Required with --madar-backup")
    parser.add_argument("--as-of", help="ISO 8601 ending date; required with --madar-backup")
    parser.add_argument("--crosswalk", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.madar_backup:
            if not args.company_ref or not args.as_of:
                raise ReconciliationError(
                    "--madar-backup requires explicit --company-ref and --as-of")
            from madar_offline_reconciliation_export import (
                build_madar_comparison_snapshot,
            )
            target_summary = build_madar_comparison_snapshot(
                args.madar_backup, company_ref=args.company_ref, as_of=args.as_of)
        else:
            if args.company_ref or args.as_of:
                raise ReconciliationError(
                    "Company/as-of arguments belong to --madar-backup only")
            target_summary = _file(args.madar_summary)
        report = compare_snapshots(_file(args.parsian_summary),
                                   target_summary,
                                   crosswalk=_file(args.crosswalk) if args.crosswalk else None)
    except (OSError, ReconciliationError, ValueError, sqlite3.Error, RuntimeError) as exc:
        print(json.dumps({"gateStatus": "INVALID_OR_UNVERIFIED_INPUT",
                          "error": str(exc), "safeToImport": False}),
              file=sys.stdout)
        return 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["balancesMatchInSuppliedSnapshots"] else 1


if __name__ == "__main__":
    sys.exit(main())
