"""Read-only reconciliation of the exact 2026-11-14 Frozen Gate A QA runs.

Does NOT launch Taraz, install anything, modify accounting data, or change
earlier reports. Writes only a new aggregate JSON inside the synthetic QA run.
The original blocked reports remain blocked and are not relabeled.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.qa_taraz_frozen_synthetic_uia_20261112 import (
    BUILD_NAME,
    EXE_SHA,
    SOURCE_SHA,
    book_witness,
    pdf_integrity,
    synthetic_paths,
)

BASE = Path("D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.6-aaas")
RUNS = BASE / "frozen-synthetic-private-uia-20261112"
MAIN = RUNS / "qa-8d2a2170c741"
FRESH = RUNS / "qa-958f63883537"
EXE = BASE / BUILD_NAME / "binary" / "Taraz.exe"
PDF = MAIN / "private-downloads" / "QA-FROZEN-INV-1405-0001.pdf"
PDF_SHA = "0413641cde01ee0d99692a21962f704e4ef916677a896fc8246cdf3444452466"
SAVED = MAIN / "private-profile" / "qa-private-save-4162ede3.json"
PHASES = {
    "invoice": (FRESH, "synthetic-invoice-252b3673.json", "PASS_FROZEN_SYNTHETIC_INVOICE_DRAFT"),
    "invoice-edit": (MAIN, "synthetic-invoice-edit-25dc5661.json", "PASS_FROZEN_SYNTHETIC_INVOICE_REOPEN_EDIT"),
    "proforma": (MAIN, "synthetic-proforma-5934dee3.json", "PASS_FROZEN_SYNTHETIC_PROFORMA_DRAFT"),
    "proforma-edit": (MAIN, "synthetic-proforma-edit-03dde646.json", "PASS_FROZEN_SYNTHETIC_PROFORMA_REOPEN_EDIT"),
    "print": (MAIN, "synthetic-print-21a081ef.json", "PASS_FROZEN_SYNTHETIC_PRINT_TEMPLATE"),
    "order-create": (MAIN, "synthetic-order-create-9a73becc.json", "PASS_FROZEN_SYNTHETIC_ORDER_CREATE"),
    "order-cost": (MAIN, "synthetic-order-cost-1752f55e.json", "PASS_FROZEN_SYNTHETIC_ORDER_COST"),
    "order-payment": (MAIN, "synthetic-order-payment-a6100dee.json", "PASS_FROZEN_SYNTHETIC_ORDER_PAYMENT"),
}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AssertionError(code)


def load(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink(), f"UNSAFE_OR_MISSING:{path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def owned(path: Path) -> None:
    require(path.is_dir() and not path.is_symlink(), "QA_RUN_MISSING")
    manifest = load(path / "synthetic-ownership.json")
    require(
        manifest == {"syntheticOnly": True, "candidate": BUILD_NAME, "exeSha256": EXE_SHA},
        "SYNTHETIC_OWNER_MISMATCH",
    )


def main() -> int:
    owned(MAIN)
    owned(FRESH)
    require(EXE.is_file() and sha256(EXE) == EXE_SHA, "BINARY_HASH_MISMATCH")
    build = load(BASE / BUILD_NAME / "build-report.json")
    require(
        build["sourceFreezeSha256"] == SOURCE_SHA
        and build["exeSha256"] == EXE_SHA
        and build["installed"] is False
        and build["status"] == "V106_AAAS_NON_QA_BUILT_NOT_INSTALLED",
        "BUILD_IDENTITY_MISMATCH",
    )
    phases = {}
    for name, (run, filename, expected) in PHASES.items():
        report = load(run / filename)
        require(report["phase"] == name and report["status"] == expected, f"PHASE_NOT_PASS:{name}")
        require(
            report["syntheticOnly"] is True
            and report["exeSha256"] == EXE_SHA
            and report["sourceSha256"] == SOURCE_SHA
            and report["realUserDataRead"] is False
            and report["forcedProcessTermination"] is False
            and report["usedCDP"] is False
            and report["qaOwnedProcessExitedGracefully"] is True
            and report["installedUnchanged"] is True
            and report["previousTarazPidsPreserved"] is True
            and report["candidateUnchanged"] is True
            and report["webviewLoaded"] is True
            and report["realNativeBridge"] is True
            and report["after"]["journalCount"] == 0,
            f"PHASE_SAFETY_MISMATCH:{name}",
        )
        phases[name] = {"status": expected, "evidence": str(run / filename)}
    _, roots = synthetic_paths(MAIN)
    final = book_witness(roots)
    require(final["journalCount"] == 0, "UNEXPECTED_JOURNAL")
    require(final["revision"] == 5, "ACCOUNTING_REVISION_MISMATCH")
    require(final["invoiceCount"] == final["proformaCount"] == 1, "DOCUMENT_DUPLICATION")
    require(
        final["invoices"][0]["id"] == "INV-1405-0001"
        and final["invoices"][0]["total"] == 18000
        and final["proformas"][0]["id"] == "PF-1405-0001"
        and final["proformas"][0]["total"] == 7500,
        "DOCUMENT_READBACK_MISMATCH",
    )
    require(final["orderCount"] == 1, "ORDER_COUNT_MISMATCH")
    order = final["orders"][0]
    require(
        order["revision"] == 3
        and order["financialEventCreated"] is False
        and len(order["costRecords"]) == len(order["payments"]) == 1,
        "ORDER_REVISION_OR_FINANCE_MISMATCH",
    )
    cost, payment = order["costRecords"][0], order["payments"][0]
    require(
        cost["actual_cost"] == 180000
        and cost["cost_date"] == "2026-11-14"
        and cost["status"] == "recorded"
        and cost["approved_by"] is None
        and payment["amount"] == 500000
        and payment["status"] == "recorded"
        and payment["approved_by"] is None,
        "ORDER_AMOUNT_DATE_APPROVAL_MISMATCH",
    )
    saved = load(SAVED)
    require(
        saved["exeSha256"] == EXE_SHA
        and saved["saved"] is True
        and saved["qaPathSet"] is True
        and saved["qaSetMessageDelivered"] is True
        and saved["qaGetMessageDelivered"] is True
        and saved["qaFilenameReadbackMatched"] is True
        and saved["saveButtonPosted"] is True
        and saved["pdfBytes"] == 56462,
        "NATIVE_SAVE_AS_EVIDENCE_MISMATCH",
    )
    require(PDF.is_file() and PDF.resolve().is_relative_to(MAIN.resolve()), "PDF_PATH_UNSAFE")
    integrity = pdf_integrity(PDF)
    require(
        integrity["sha256"] == PDF_SHA
        and integrity["bytes"] == 56462
        and integrity["headerValid"]
        and integrity["hasEof"]
        and integrity["pageCount"] == integrity["jpegPageCount"] == 1
        and integrity["renderedContentNonblank"],
        "PDF_INTEGRITY_MISMATCH",
    )
    result = {
        "status": "PASS_FROZEN_GATE_A_SYNTHETIC_EVIDENCE_RECONCILED",
        "boundary": "Uninstalled candidate; no approval for production posting or physical printing",
        "candidate": BUILD_NAME,
        "exeSha256": EXE_SHA,
        "sourceFreezeSha256": SOURCE_SHA,
        "phases": phases,
        "pdf": {"nativeSaveAs": True, "integrity": integrity, "evidence": str(SAVED)},
        "finalSqliteReadback": final,
        "originalPdfPhaseStatus": "BLOCKED; independently reconciled through native Save As helper",
        "installed": False,
    }
    target = MAIN / "gate-a-synthetic-evidence-reconciled-20261114.json"
    require(not target.is_symlink(), "EVIDENCE_LINK_NOT_ALLOWED")
    if target.exists():
        require(load(target) == result, "EXISTING_EVIDENCE_MISMATCH")
    else:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(target),
                      "phases": len(phases), "journalCount": final["journalCount"],
                      "orderRevision": order["revision"], "invoiceTotal": 18000,
                      "proformaTotal": 7500}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
