"""Pure opt-in RIAL V2 journal embedded in an existing TOMAN finance snapshot.

These functions never persist anything. Only an authenticated host can establish
the truth of a proof's fields; constructing one in Python is NOT authentication.
The caller must commit the entire returned finance domain under ONE existing
UnifiedAppStorage revision CAS, or decline to perform the operation.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json

from ir_journal_sqlite import _serialize, _deserialize, _validate_append_only
from ir_journal_v2 import (
    JournalState, JournalV2Conflict, PostedJournal, new_journal_state,
)
from money_policy import MAX_RIAL, snapshot_sha256


EXTENSION_KEY = "rialJournalV2"
EXTENSION_VERSION = 1
MAX_COMPANIES = 100
MAX_EXTENSION_BYTES = 12_000_000


@dataclass(frozen=True, slots=True)
class HostCompanyProof:
    """A host-verified company activation attestation, NOT a bearer token."""

    company_id: str
    actor_id: str
    finance_snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedInvoiceSourceProof:
    """Host observation of a *newly issued* legacy TOMAN invoice.

    The host MUST authenticate actor/company and derive these fields from its
    current locked finance, card, and permission context. No client is allowed
    to supply this proof or the embedded V2 VerifiedScopes directly.
    """

    company_id: str
    actor_id: str
    invoice_id: str
    project_id: str
    card_id: str
    invoice_snapshot_sha256: str
    total_toman: int
    finance_before_sha256: str
    finance_after_sha256: str


def _canonical_snapshot(state: JournalState) -> dict:
    if type(state) is not JournalState:
        raise ValueError("An immutable RIAL JournalState is required")
    return json.loads(_serialize(state))


def _entry(state: JournalState) -> dict:
    return {"revision": state.revision, "snapshot": _canonical_snapshot(state)}


def _read_entry(company_id: str, record: dict) -> JournalState:
    if type(record) is not dict or set(record) != {"revision", "snapshot"}:
        raise ValueError("Invalid embedded RIAL journal record")
    if type(record["snapshot"]) is not dict:
        raise ValueError("Invalid embedded RIAL JSON snapshot")
    # Both conversion directions validate complete replay, hash chain,
    # historical chart/scopes, period closure, and duplicate business sources.
    snapshot_bytes = json.dumps(record["snapshot"], ensure_ascii=False,
                                allow_nan=False, sort_keys=True,
                                separators=(",", ":")).encode("utf-8")
    state = _deserialize(snapshot_bytes)
    if (state.company_id != company_id or type(record["revision"]) is not str
            or state.revision != record["revision"]
            or _canonical_snapshot(state) != record["snapshot"]):
        raise ValueError("Noncanonical/mismatched RIAL journal revision or company")
    return state


def validate_rial_finance_extension(finance_state: dict) -> bool:
    """Strictly validate the optional serialized finance field, without IO."""
    if type(finance_state) is not dict:
        raise ValueError("Finance must be an object")
    if EXTENSION_KEY not in finance_state:
        return True
    extension = finance_state[EXTENSION_KEY]
    if type(extension) is not dict or set(extension) != {"schemaVersion", "companies"}:
        raise ValueError("Invalid RIAL finance extension schema")
    if (type(extension["schemaVersion"]) is not int
            or extension["schemaVersion"] != EXTENSION_VERSION):
        raise ValueError("Unsupported RIAL finance extension version")
    companies = extension["companies"]
    if type(companies) is not dict or not 1 <= len(companies) <= MAX_COMPANIES:
        raise ValueError("Invalid RIAL company journal collection")
    if len(json.dumps(extension, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")) > MAX_EXTENSION_BYTES:
        raise ValueError("RIAL journal extension exceeds safe domain budget")
    for company_id, record in companies.items():
        _read_entry(company_id, record)
    return True


def load_finance_rial_journal(finance_state: dict, company_id: str) -> JournalState:
    """Return a validated immutable V2 company journal from a finance bundle."""
    validate_rial_finance_extension(finance_state)
    extension = finance_state.get(EXTENSION_KEY)
    if extension is None or company_id not in extension["companies"]:
        raise KeyError("RIAL company journal has not been opted in")
    return _read_entry(company_id, extension["companies"][company_id])


def activate_rial_finance(finance_state: dict, initial_journal: JournalState,
                          *, proof: HostCompanyProof) -> dict:
    """Opt in an empty, explicitly verified company journal without changing TOMAN."""
    from finance import validate_finance_state

    validate_finance_state(finance_state)
    if type(proof) is not HostCompanyProof or type(initial_journal) is not JournalState:
        raise ValueError("Host activation proof and RIAL journal are required")
    if (proof.company_id != initial_journal.company_id or not proof.actor_id
            or snapshot_sha256(finance_state) != proof.finance_snapshot_sha256):
        raise PermissionError("Host company activation proof does not match current finance")
    if initial_journal != new_journal_state(initial_journal.company_id,
                                           initial_journal.periods):
        raise ValueError("Activation requires a pristine V2 journal; no historical import")
    clone = deepcopy(finance_state)
    if EXTENSION_KEY not in clone:
        clone[EXTENSION_KEY] = {"schemaVersion": EXTENSION_VERSION, "companies": {}}
    companies = clone[EXTENSION_KEY]["companies"]
    if initial_journal.company_id in companies:
        raise JournalV2Conflict("RIAL company already activated")
    companies[initial_journal.company_id] = _entry(initial_journal)
    validate_finance_state(clone)
    return clone


def _preserve_issued_history(before: dict, after: dict, *,
                             allow_accounting_transition: bool = False) -> None:
    """An explicit composer cannot delete or rewrite old TOMAN history."""
    for name in ("invoices", "contracts", "ledger"):
        historical = before[name]
        current = after[name]
        if type(current) is not list or current[:len(historical)] != historical:
            raise ValueError("Existing TOMAN " + name + " history is immutable")
    for name in ("receipts", "completionIds"):
        old, new = before[name], after[name]
        if any(key not in new or new[key] != record for key, record in old.items()):
            raise ValueError("Existing TOMAN " + name + " records are immutable")
    if after["nextInvoiceNumber"] < before["nextInvoiceNumber"]:
        raise ValueError("Legacy invoice number sequence cannot decrease")
    # These accounting domains have their own posting and source invariants.
    # Combining their mutations with new RIAL posting needs a separate host
    # reconciliation contract before enabling their joint updates.
    if not allow_accounting_transition:
        for name in ("accounting", "accountingSources", "purchaseIntakes"):
            if before.get(name) != after.get(name):
                raise ValueError("Independent legacy accounting domains require reconciliation")


def compose_finance_rial_snapshot(
    finance_before: dict, finance_after: dict, candidate_journal: JournalState,
    *, expected_journal_revision: str, proof: VerifiedInvoiceSourceProof,
) -> dict:
    """Compose a newly issued TOMAN invoice and one RIAL posting in ONE domain.

    The host must commit this whole result with the existing finance CAS. The
    full *pre-extension* finance_after is produced by its authorized TOMAN
    reducer, and the candidate by immutable V2 post_journal(). Only new invoice
    issue events are supported in this first narrowly scoped bridge.
    """
    from finance import invoice_status, validate_finance_state

    validate_finance_state(finance_before)
    validate_finance_state(finance_after)
    if type(proof) is not VerifiedInvoiceSourceProof or type(candidate_journal) is not JournalState:
        raise ValueError("Host-verified invoice proof and V2 candidate required")
    if (proof.company_id != candidate_journal.company_id
            or snapshot_sha256(finance_before) != proof.finance_before_sha256
            or snapshot_sha256(finance_after) != proof.finance_after_sha256):
        raise PermissionError("Finance/source proof differs from observed host snapshots")
    if (type(proof.total_toman) is not int or proof.total_toman <= 0
            or proof.total_toman > MAX_RIAL // 10):
        raise ValueError("Explicit exact whole TOMAN invoice amount required")
    if finance_before.get(EXTENSION_KEY) != finance_after.get(EXTENSION_KEY):
        raise ValueError("The TOMAN reducer cannot alter the RIAL extension")
    _preserve_issued_history(finance_before, finance_after)
    # The v1 bridge is deliberately limited to ONE existing invoice.issue
    # reducer result; any extra unrelated finance mutation must be reviewed
    # under its own authorization and accounting/source reconciliation policy.
    for name in ("cardCosts", "contracts", "activeContracts", "invoices", "completionIds"):
        if finance_before[name] != finance_after[name]:
            raise ValueError("Invoice issuance must preserve legacy " + name)
    if (finance_after["nextInvoiceNumber"] != finance_before["nextInvoiceNumber"] + 1
            or len(finance_after["ledger"]) != len(finance_before["ledger"]) + 1
            or len(finance_after["receipts"]) != len(finance_before["receipts"]) + 1):
        raise ValueError("Exactly one TOMAN invoice.issue mutation is required")
    previous = load_finance_rial_journal(finance_before, proof.company_id)
    if previous.revision != expected_journal_revision:
        raise JournalV2Conflict("Stale embedded RIAL journal revision")
    _validate_append_only(previous, candidate_journal)
    if len(candidate_journal.events) != len(previous.events) + 1:
        raise ValueError("Exactly one newly posted V2 event is required")
    event = candidate_journal.events[-1]
    if type(event) is not PostedJournal or event.reversal_of:
        raise ValueError("Only a new ordinary RIAL posting can accompany invoice issuance")
    source = event.source
    task_bound = (source.kind in ("task", "card") and
                  source.source_id == proof.card_id and source.task_id == proof.card_id)
    invoice_bound = (source.kind == "independent" and
                     source.source_id == proof.invoice_id and not source.task_id
                     and not source.checklist_id)
    if (event.company_id != proof.company_id or event.actor_id != proof.actor_id
            or not (task_bound or invoice_bound)
            or source.project_id != proof.project_id):
        raise PermissionError("RIAL posting is not bound to the verified invoice source")
    invoices = [row for row in finance_after["invoices"] if row["id"] == proof.invoice_id]
    if len(invoices) != 1:
        raise ValueError("Verified issued invoice not found")
    invoice = invoices[0]
    if (invoice["snapshotHash"] != proof.invoice_snapshot_sha256
            or invoice["projectId"] != proof.project_id
            or invoice["cardId"] != proof.card_id
            or invoice["sale"]["total"] != proof.total_toman):
        raise PermissionError("Invoice source provenance or TOMAN total mismatch")
    if invoice["sale"]["advance"] != 0:
        raise ValueError("Advance receipt is not supported by the RIAL sales mirror")
    issued = finance_after["ledger"][-1]
    if (issued["action"] != "invoice.issue" or issued["invoiceId"] != proof.invoice_id
            or issued["actor"] != proof.actor_id
            or issued["projectId"] != proof.project_id
            or issued["cardId"] != proof.card_id
            or event.posting_date != issued["at"][:10]
            or issued["payload"].get("number") != finance_before["nextInvoiceNumber"]
            or issued["eventId"] not in finance_after["receipts"]
            or issued["eventId"] in finance_before["receipts"]
            or invoice_status(finance_after, proof.invoice_id)["status"] != "Issued"):
        raise ValueError("RIAL dual posting requires a newly issued legacy invoice")
    if sum(line.debit_rial for line in event.lines) != proof.total_toman * 10:
        raise ValueError("Posting gross debit must equal verified TOMAN invoice x10 RIAL")
    context = next((e for e in candidate_journal.evidence
                    if e.evidence_digest == event.evidence_digest), None)
    if context is None:
        raise ValueError("Journal chart evidence is missing")
    account_kinds = {item.code: item.kind for item in context.chart.accounts}
    debits = [line for line in event.lines if line.debit_rial]
    if (len(debits) != 1 or
            account_kinds.get(debits[0].reference.account_code) != "asset"):
        raise ValueError("Sales posting needs one receivable asset debit")
    expected_revenue = (
        invoice["sale"]["subtotal"] - invoice["sale"]["discount"]) * 10
    expected_tax = invoice["sale"]["tax"] * 10
    credits = {"revenue": 0, "liability": 0}
    for line in event.lines:
        if (line.reference.company_id != proof.company_id
                or line.reference.project_id != proof.project_id
                or line.reference.task_id != proof.card_id):
            raise PermissionError("Sales journal line source/project does not match")
        if line.credit_rial:
            kind = account_kinds.get(line.reference.account_code)
            if kind not in credits:
                raise ValueError("Only revenue and tax liability can be credited")
            credits[kind] += line.credit_rial
    if credits != {"revenue": expected_revenue, "liability": expected_tax}:
        raise ValueError("Sales net revenue/tax RIAL allocation does not reconcile")
    clone = deepcopy(finance_after)
    clone[EXTENSION_KEY]["companies"][proof.company_id] = _entry(candidate_journal)
    validate_finance_state(clone)
    return clone


__all__ = [
    "EXTENSION_KEY", "HostCompanyProof", "VerifiedInvoiceSourceProof",
    "activate_rial_finance", "load_finance_rial_journal",
    "compose_finance_rial_snapshot", "validate_rial_finance_extension",
]
