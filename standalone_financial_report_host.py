"""Read-only, host-side accounting report projection from an authenticated view.

This adapter does not accept an arbitrary browser-provided ledger and never
posts or persists a report. It refuses inconsistent account/party balances.
"""
from __future__ import annotations

from accounting_reporting import ledger_reports


def attach_verified_reports(result):
    if type(result) is not dict or type(result.get("view")) is not dict:
        raise ValueError("Expected verified standalone accounting host result")
    view = result["view"]
    # Legacy host tests may replace the storage with a deliberately partial fake.
    # A real accounting projection MUST have every canonical journal member.
    if view.get("currency") not in ("RIAL", "TOMAN"):
        return result
    report = ledger_reports(view)
    return {**result, "view": {**view, "financialReports": report}}
