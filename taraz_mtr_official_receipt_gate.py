"""Read-only evidence gate between Madar metadata and an *actual* Taraz booking.

Even a valid, persisted invoice.issue journal is NOT an official Madar receipt:
the current Taraz accounting API does not authenticate the Madar source binding
or issue signed cross-app finance receipts. This module never promotes metadata
review or a caller-supplied receipt into official success.

Use an existing, authenticated AccountingDesktopAPI tied to a registered company
book and a current LocalCompanyIdentity session. No ledger or identity creation,
no publishing, no network, and no re-posting/retrying ambiguous transactions.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace
from urllib.parse import quote

from accounting_core import accounting_view
from standalone_accounting import StandaloneAccountingStore
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_desktop import AccountingDesktopAPI, ACCOUNTING_FILE
from standalone_accounting_identity import LocalCompanyIdentity

_ID = re.compile(r"^[a-zA-Z0-9._-]{1,100}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_JOURNAL = re.compile(r"^J:[a-zA-Z0-9._-]{1,100}$")
_REVIEW_FIELDS = frozenset((
    "schema", "source", "id", "taskId", "state",
    "reviewedUtc", "financialEventCreated",
))


def _report(reason: str, *, revision=None, nonfinancial_review=False,
            journal_posted=False, authoritative_company=False):
    return {
        "schemaVersion": 1,
        "decision": reason,
        "ledgerRevisionObserved": revision,
        "nonfinancialReviewObserved": nonfinancial_review,
        "persistedInvoiceJournalVerified": journal_posted,
        "currentCompanyAndRoleChecked": authoritative_company,
        "trustedMadarInvoiceBindingVerified": False,
        "officialFinanceReceiptVerified": False,
        "financialEventCreatedByMadarReview": False,
        "safeToRetryFinancialPosting": False,
        "signedTarazReceiptPresent": False,
    }


def classify_metadata_review(marker: dict):
    """Validate an untrusted source-only marker; never a finance receipt."""
    if type(marker) is not dict or set(marker) != _REVIEW_FIELDS:
        return _report("INVALID_REVIEW_MARKER")
    if (type(marker["schema"]) is not int or marker["schema"] != 1
            or marker["source"] != "taraz"
            or type(marker["id"]) is not str or not _HEX32.fullmatch(marker["id"])
            or type(marker["taskId"]) is not str or not marker["taskId"]
            or len(marker["taskId"]) > 180
            or marker["state"] not in ("reviewed", "rejected")
            or type(marker["reviewedUtc"]) is not str
            or marker["financialEventCreated"] is not False):
        return _report("SPOOFED_OR_INVALID_REVIEW_MARKER")
    try:
        from datetime import datetime
        stamp = datetime.fromisoformat(marker["reviewedUtc"])
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return _report("INVALID_REVIEW_MARKER_TIME")
    except (ValueError, TypeError):
        return _report("INVALID_REVIEW_MARKER_TIME")
    return _report("NONFINANCIAL_REVIEW_ONLY", nonfinancial_review=True)


def _safe_company(host, expected_company_id: str):
    """Reject local-admin fallback, renamed-folder spoof and wrong company."""
    if type(host) is not AccountingDesktopAPI:
        raise PermissionError("Only the real authenticated desktop host is allowed")
    identity = host._identity_store
    if type(identity) is not LocalCompanyIdentity or not host._identity_token:
        raise PermissionError("An actual company identity session is required")
    folder = Path(host.path).parent
    if (not _HEX32.fullmatch(expected_company_id)
            or host.company_workspace_id != expected_company_id
            or Path(host.path).name != ACCOUNTING_FILE
            or folder.name != expected_company_id
            or identity.root != folder
            or folder.parent.name != "books"):
        raise PermissionError("Current selected company differs from requested company")
    registry = StandaloneCompanyRegistry(folder.parent.parent)
    if registry.company_data_directory(expected_company_id) != folder:
        raise PermissionError("Company is absent from authoritative registry")
    if (host.path.is_symlink() or folder.is_symlink()
            or getattr(folder, "is_junction", lambda: False)()):
        raise PermissionError("Unsafe accounting path")
    if host._exit_backed_up:
        raise PermissionError("Accounting company session is closing")
    return identity


def _principal(host, identity):
    checked = identity.require_session(host._identity_token, "editor")
    if (type(checked) is not dict or checked.get("username") != host._actor
            or checked.get("role") not in ("admin", "editor")):
        raise PermissionError("Current company principal changed or was revoked")
    accounts = identity.accounting_accounts()
    principal = accounts.get(host._actor)
    if (type(principal) is not dict
            or principal.get("role") != checked["role"]
            or principal.get("financeEdit") is not True):
        raise PermissionError("Current actor lacks authoritative finance-edit permission")
    return accounts


def _snapshot(host, accounts):
    """One SQLite read-only transaction, with real canonical replay validation.

    Unlike StandaloneAccountingStore.__init__ this never creates missing tables
    or executes PRAGMA journal_mode. Never use sqlite3 non-URI default rw mode.
    """
    path = Path(host.path)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("Accounting book missing or linked")
    uri = "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=5,
                                 isolation_level=None)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Accounting schema is not verified")
            names = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")}
            if names != {"standalone_accounting"}:
                raise ValueError("Unexpected accounting tables")
            # _current needs only default_currency when the ledger is empty.
            # Do not construct StandaloneAccountingStore here: its __init__
            # is allowed to create/upgrade a database, which is forbidden
            # for a strictly read-only receipt inspector.
            revision, state = StandaloneAccountingStore._current(
                SimpleNamespace(default_currency="RIAL"), connection)
            # _current checks stored digest, canonical JSON and full replay.
            if revision != len(state["events"]):
                raise ValueError("Accounting revision/event count diverged")
            view = accounting_view(state, actor=host._actor, accounts=accounts)
            return revision, state["events"], view
        finally:
            if connection.in_transaction:
                connection.execute("ROLLBACK")


def assess_official_receipt(*, host, company_id: str, madar_request_id: str,
                            invoice_id: str, issue_event_id: str,
                            journal_id: str, expected_revision: int,
                            review_marker: dict | None = None):
    """Read-only, fail-closed assessment. NEVER returns official success.

    There is currently no authenticated Madar->invoice binding or signed
    cross-app receipt issuer. A valid posting is reported as OBSERVED_UNBOUND,
    never OFFICIAL_VERIFIED, even for genuine synthetic accounting commands.
    """
    if (type(company_id) is not str or not _HEX32.fullmatch(company_id)
            or type(madar_request_id) is not str or not _HEX32.fullmatch(madar_request_id)
            or type(invoice_id) is not str or not _ID.fullmatch(invoice_id)
            or type(issue_event_id) is not str or not _ID.fullmatch(issue_event_id)
            or type(journal_id) is not str or not _JOURNAL.fullmatch(journal_id)
            or journal_id != "J:" + issue_event_id
            or type(expected_revision) is not int or expected_revision < 0):
        return _report("INVALID_OR_UNBOUND_INPUT")

    reviewed = False
    if review_marker is not None:
        metadata = classify_metadata_review(review_marker)
        if (metadata["decision"] != "NONFINANCIAL_REVIEW_ONLY"
                or review_marker["id"] != madar_request_id):
            return _report("UNTRUSTED_REVIEW_NOT_FINANCE_AUTHORITY")
        reviewed = True

    try:
        identity = _safe_company(host, company_id)
        # Holding the current native host lock coordinates with its own
        # commands; SQLite read BEGIN preserves one cross-process snapshot.
        with host._lock:
            accounts = _principal(host, identity)
            revision, events, view = _snapshot(host, accounts)
            _principal(host, identity)  # detect role/session revoked mid-read
    except (PermissionError, AttributeError, TypeError, KeyError):
        return _report("CURRENT_COMPANY_OR_AUTHORITY_DENIED",
                       nonfinancial_review=reviewed)
    except (OSError, sqlite3.Error, ValueError, RuntimeError, FileNotFoundError):
        return _report("ACCOUNTING_SNAPSHOT_UNVERIFIABLE",
                       nonfinancial_review=reviewed)

    def outcome(reason, posted=False):
        return _report(reason, revision=revision, nonfinancial_review=reviewed,
                       journal_posted=posted, authoritative_company=True)

    if revision != expected_revision:
        return outcome("STALE_REVISION_AMBIGUOUS_POSTING")
    invoices = view.get("invoices")
    journals = view.get("journals")
    reversed_map = view.get("reversed")
    if type(invoices) is not dict or type(journals) is not list or type(reversed_map) is not dict:
        return outcome("LEDGER_PROJECTION_UNVERIFIABLE")

    linked = [item for item in invoices.values()
              if type(item) is dict and item.get("sourceType") == "madar"
              and item.get("sourceId") == madar_request_id]
    if len(linked) > 1:
        return outcome("DUPLICATE_OR_AMBIGUOUS_SOURCE_LINK")
    invoice = invoices.get(invoice_id)
    if not invoice:
        return outcome("NO_PERSISTED_INVOICE")
    if (type(invoice) is not dict or invoice.get("sourceType") != "madar"
            or invoice.get("sourceId") != madar_request_id
            or len(linked) != 1 or linked[0].get("id") != invoice_id):
        return outcome("UNTRUSTED_INVOICE_SOURCE_LINK")
    if invoice.get("status") != "issued":
        return outcome("INVOICE_NOT_ISSUED_OR_REVERSED")
    if (invoice.get("postedEntryId") != journal_id
            or type(invoice.get("number")) is not int
            or invoice["number"] <= 0
            or type(invoice.get("total")) is not int or invoice["total"] <= 0):
        return outcome("INVOICE_POSTING_NOT_VERIFIED")
    if journal_id in reversed_map:
        return outcome("INVOICE_JOURNAL_REVERSED")
    matched = [j for j in journals if type(j) is dict and j.get("id") == journal_id]
    events_matched = [e for e in events
                      if type(e) is dict and e.get("eventId") == issue_event_id]
    if len(matched) != 1 or len(events_matched) != 1:
        return outcome("AMBIGUOUS_OR_MISSING_POSTING_EVIDENCE")
    journal, event = matched[0], events_matched[0]
    command = event.get("command")
    recorded = event.get("result")
    if (journal.get("eventId") != issue_event_id
            or journal.get("sourceType") != "invoice.issue"
            or journal.get("sourceId") != invoice_id
            or journal.get("date") != invoice.get("postingDate")
            or journal.get("reversalOf") is not None
            or type(command) is not dict or command.get("type") != "invoice.issue"
            or command.get("invoiceId") != invoice_id
            or type(recorded) is not dict
            or recorded.get("journalId") != journal_id
            or recorded.get("documentId") != invoice_id
            or recorded.get("total") != invoice["total"]
            or event.get("actor") != host._actor):
        return outcome("POSTING_EVENT_AND_JOURNAL_MISMATCH")
    rows = journal.get("lines")
    if (type(rows) is not list or len(rows) < 2
            or any(type(r) is not dict or type(r.get("debit")) is not int
                   or type(r.get("credit")) is not int for r in rows)):
        return outcome("INVALID_POSTED_JOURNAL")
    debits = sum(r["debit"] for r in rows)
    credits = sum(r["credit"] for r in rows)
    if debits <= 0 or debits != credits:
        return outcome("UNBALANCED_POSTED_JOURNAL")
    # This is valuable verified *ledger* evidence, but sourceType/sourceId
    # were caller-controlled in invoice.create. Neither they nor a reviewed
    # metadata marker prove an authenticated linkage or an official receipt.
    return outcome("PERSISTED_INVOICE_JOURNAL_OBSERVED_UNBOUND", posted=True)


__all__ = ("classify_metadata_review", "assess_official_receipt")
