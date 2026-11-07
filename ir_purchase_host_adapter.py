"""Host-only convenience adapter for an authenticated supplier bill issue.

Pure reduction; only the host's SAME unified SQLite finance CAS may persist
the composed candidate. Never trust company IDs, chart or scopes from clients.
"""
from __future__ import annotations

from hashlib import sha256
import json

from accounting_service import apply_madar_accounting
from ir_finance_v2_extension import load_finance_rial_journal
from ir_purchase_joint_issue import compose_purchase_issue_with_rial
from money_policy import snapshot_sha256


def issue_supplier_purchase_with_rial(finance_before, command, *,
                                      actor, accounts, cards, projects, now):
    if type(command) is not dict or command.get("type") != "document.issue":
        raise ValueError("Only purchase document.issue may enter this joint adapter")
    extension = finance_before.get("rialJournalV2")
    if type(extension) is not dict or len(extension["companies"]) != 1:
        raise ValueError("Supplier joint issue requires one activated RIAL company")
    company_id = next(iter(extension["companies"]))
    current = load_finance_rial_journal(finance_before, company_id)
    old_result = apply_madar_accounting(
        finance_before, command, actor=actor, accounts=accounts,
        cards=cards, projects=projects, now=now)
    bill_id = command["documentId"]
    event_id = "purchase-" + sha256(
        json.dumps([command["eventId"], bill_id],
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    if not old_result["changed"]:
        # A second delivery of an already-confirmed command can succeed only
        # if this exact old document/event has a committed RIAL counterpart.
        matching = [event for event in current.events
                    if getattr(event, "event_id", None) == event_id
                    and getattr(event, "actor_id", None) == actor
                    and not getattr(event, "reversal_of", "")
                    and getattr(event, "source", None) is not None
                    and event.source.kind == "independent"
                    and event.source.source_id == bill_id]
        if len(matching) != 1:
            raise ValueError("Old purchase issue receipt lacks matching RIAL posting")
        total = old_result["result"]["total"]
        if (type(total) is not int or
                sum(line.debit_rial for line in matching[0].lines) != total * 10):
            raise ValueError("Purchase replay amount does not reconcile with RIAL")
        return {"state": old_result["state"], "changed": False,
                "result": {**old_result["result"], "rialJournalEventId": event_id,
                           "rialCompanyId": company_id, "rialAmount": str(total * 10),
                           "postingMode": "verified-intake-purchase-shadow"}}
    return compose_purchase_issue_with_rial(
        finance_before, old_result["state"], command, actor=actor,
        accounts=accounts, cards=cards, projects=projects, now=now,
        expected_finance_sha256=snapshot_sha256(finance_before),
        expected_journal_revision=current.revision,
    )


__all__ = ["issue_supplier_purchase_with_rial"]
