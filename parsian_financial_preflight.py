"""Strict offline, NON-POSTING financial migration plan from quarantined export.

No connection to SQL Server, no writes to Madar's event ledger. The monetary
unit in Parsian and the semantic account classes MUST be independently
verified before any future posting. Never reinterpret unknown raw money as
RIAL or TOMAN. Inputs must be the reviewed, explicit, private stage artifacts.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path

from parsian_quarantine_stage import profile_export, QuarantineError


def _obj(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _amount(value):
    if type(value) not in (int, float):
        raise QuarantineError("Source amount is not an exact numeric value")
    try:
        dec = Decimal(str(value))
    except InvalidOperation as err:
        raise QuarantineError("Invalid money value") from err
    if not dec.is_finite() or dec < 0 or dec > 10**15 or dec != int(dec):
        raise QuarantineError("Nonwhole or out-of-range raw financial amount")
    return int(dec)


def build_financial_plan(source: dict, date_mapping: dict) -> tuple[dict, dict]:
    check = profile_export(source)
    if (type(date_mapping) is not dict or set(date_mapping) != {
            "schemaVersion", "sourceClass", "calendar", "dates"} or
            date_mapping["sourceClass"] != source["sourceType"] or
            date_mapping["schemaVersion"] != 1 or
            date_mapping["calendar"] != "System.Globalization.PersianCalendar" or
            type(date_mapping["dates"]) is not dict):
        raise QuarantineError("Invalid independently converted Persian date proof")

    mapping = date_mapping["dates"]
    all_jalali = {x["SanadDate"] for x in source["tables"]["tbl_Document"]}
    all_jalali.update(x["Factor_Date"] for x in source["tables"]["tbl_Factor"])
    if set(mapping) != all_jalali:
        raise QuarantineError("Source dates changed or some dates are unmapped")
    for legacy, iso in mapping.items():
        if type(legacy) is not str or type(iso) is not str or len(iso) != 10:
            raise QuarantineError("Invalid source-to-ISO date mapping")
        try:
            if date.fromisoformat(iso).isoformat() != iso:
                raise ValueError
        except ValueError as err:
            raise QuarantineError("Invalid Gregorian date") from err
    accounts = {
        "kol": {x["Code"] for x in source["tables"]["tbl_Kol"]},
        "moeen": {(x["KolCode"], x["Code"])
                  for x in source["tables"]["tbl_Moeen"]},
        "tafsili": {(x["KolCode"], x["MoeenCode"], x["Code"])
                    for x in source["tables"]["tbl_Tafsili"]},
        "groups": {x["Code"] for x in source["tables"]["tbl_ACCGroup"]},
    }
    group_orphans = sorted(
        str(x["Code"]) for x in source["tables"]["tbl_Kol"]
        if x["GroupCode"] not in accounts["groups"]
    )
    groups = defaultdict(list)
    used = set()
    for row in source["tables"]["tbl_Document"]:
        code = (row["KolCode"], row["MoeenCode"], row["TafsiliCode"])
        if (code[0] not in accounts["kol"] or
            code[:2] not in accounts["moeen"] or
            (code[2] not in (0, None) and code not in accounts["tafsili"])):
            raise QuarantineError("Source journal contains an unresolved account")
        debit = _amount(row["Bed"])
        credit = _amount(row["Bes"])
        if (debit > 0) == (credit > 0):
            raise QuarantineError("Source posting must have exactly one side")
        used.add(code)
        groups[row["Sanad_Num"]].append({
            "legacyRowId": row["ID"],
            "sourceAccountPath": [*code],
            "debitSourceUnits": debit,
            "creditSourceUnits": credit,
            "sourceDateJalali": row["SanadDate"],
            "postingDateISO": mapping[row["SanadDate"]],
        })
    preview = []
    for number, rows in sorted(groups.items()):
        dates = {row["postingDateISO"] for row in rows}
        dr = sum(x["debitSourceUnits"] for x in rows)
        cr = sum(x["creditSourceUnits"] for x in rows)
        if len(dates) != 1 or len(rows) < 2 or len(rows) > 100 or dr != cr:
            raise QuarantineError("Source document fails strict financial validation")
        rows.sort(key=lambda x: x["legacyRowId"])
        preview.append({
            "sourceDocumentNumber": number,
            "postingDateISO": next(iter(dates)),
            "sourceDebitTotal": dr,
            "sourceCreditTotal": cr,
            "rows": rows,
            "sourceDocumentSha256": sha256(_obj(rows)).hexdigest(),
            "postingAuthorized": False,
        })
    factor_rows = source["tables"]["tbl_Factor"]
    absent = sum(factor["Sanad_Num"] not in groups for factor in factor_rows)
    restored = source["sourceType"] == "RESTORED_BAK_ISOLATED_VERIFIED_20261026"
    blockers = [
        "the_source_currency_unit_has_not_been_independently_verified",
        "the_parsian_kol_moeen_tafsili_to_madar_account_types_are_not_reviewed",
        "opening_balances_and_account_party_allocation_are_not_reconciled",
        "full_document_factors_receipts_cheques_inventory_semantics_unmapped",
    ]
    if not restored:
        blockers.insert(0,"the_attached_live_database_is_not_proven_equal_to_the_copied_backup")
    if group_orphans:
        blockers.append("some_kol_groups_have_no_matching_group_reference")
    if absent:
        blockers.append("some_factor_rows_have_no_matching_journal_number")
    detail = {
        "formatVersion": 1,
        "sourceClass": source["sourceType"],
        "sourceBackupSnapshotVerified": restored,
        "sourceCurrencyUnit": "UNVERIFIED_NO_RIAL_OR_TOMAN_ASSUMPTION",
        "accountClassMappingVerified": False,
        "financialPostingAuthorized": False,
        "journalGroups": preview,
        "accountPathsReferenced": [list(x) for x in sorted(
            used, key=lambda x: tuple(str(y) for y in x))],
        "blockers": blockers,
        "disclaimer": ("Source amounts are original, unitless Parsian numbers. "
                       "Never post them to a RIAL or TOMAN ledger as-is."),
    }
    summary = {
        "sourceDocumentGroups": len(preview),
        "sourceJournalRows": sum(len(p["rows"]) for p in preview),
        "distinctReferencedAccountPaths": len(used),
        "sourceJalaliDatesMapped": len(mapping),
        "orphanKolReferences": check["orphanKolReferences"],
        "orphanMoeenReferences": check["orphanMoeenReferences"],
        "orphanTafsiliReferences": check["orphanTafsiliReferences"],
        "kolGroupEntriesMissingReference": len(group_orphans),
        "factorRowsWithoutMatchedJournal": absent,
        "unbalancedDocuments": 0,
        "sourceBackupSnapshotVerified": restored,
        "sourceCurrencyUnitVerified": False,
        "readyToPostToMadarTrial": False,
        "migrationStatus": "PREPARED_RECONCILABLE_PREVIEW_FINANCIAL_POSTING_BLOCKED",
        "blockingReasons": blockers,
    }
    return detail, summary


def run_plan(source_path: str | Path, date_path: str | Path, *,
             detail_output: str | Path, summary_output: str | Path):
    paths = [Path(x).absolute() for x in
             (source_path, date_path, detail_output, summary_output)]
    if any(x.is_symlink() for x in paths) or len(set(paths)) != 4:
        raise QuarantineError("Unsafe input/output paths")
    if any(x.exists() for x in paths[2:]) or (
            not paths[2].parent.is_dir() or
            paths[2].parent != paths[3].parent):
        raise QuarantineError("Outputs must be new files in the same trial root")
    if any(not p.is_file() or p.stat().st_size > 8_000_000 for p in paths[:2]):
        raise QuarantineError("Missing or oversized source/date export")
    def strict_pairs(pairs):
        item = {}
        for key, value in pairs:
            if key in item:
                raise QuarantineError("Duplicate JSON property")
            item[key] = value
        return item
    source, dates = [
        json.loads(p.read_text(encoding="utf-8"),
                   object_pairs_hook=strict_pairs) for p in paths[:2]
    ]
    detail, summary = build_financial_plan(source, dates)
    # Exclusive creation prevents accidental overwrite of financial evidence.
    with paths[2].open("x", encoding="utf-8") as file:
        json.dump(detail, file, ensure_ascii=False, indent=2)
    with paths[3].open("x", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    return summary


__all__ = ["build_financial_plan", "run_plan"]
