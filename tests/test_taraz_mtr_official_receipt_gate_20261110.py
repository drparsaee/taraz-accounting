"""Synthetic, official-store-backed evidence tests; NEVER any real profile."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_desktop import AccountingDesktopAPI
from standalone_accounting_identity import LocalCompanyIdentity
from taraz_integration import review_request
from taraz_mtr_official_receipt_gate import (
    assess_official_receipt, classify_metadata_review,
    _safe_company, _principal, _snapshot,
)


class OfficialFinanceReceiptGateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="taraz-receipt-qa-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.hub = self.root / "company-hub"
        self.hub.mkdir()
        self.registry = StandaloneCompanyRegistry(self.hub)
        record = self.registry.create_company("Synthetic company, NOT official")
        self.company_id = record["id"]
        self.book = self.registry.company_data_directory(self.company_id)
        self.identity = LocalCompanyIdentity(self.book)
        self.identity.add_user("qaowner", "syntheticOnlyPwd-1", role="admin")
        self.admin_token = self.identity.login("qaowner", "syntheticOnlyPwd-1")
        self.identity.add_user("qaeditor", "syntheticOnlyPwd-2", role="editor",
                               administrator=self.admin_token)
        self.editor_token = self.identity.login("qaeditor", "syntheticOnlyPwd-2")
        self.host = AccountingDesktopAPI(
            self.book, company_name="Synthetic company, NOT official",
            company_workspace_id=self.company_id,
            authenticated_user=self.identity.require_session(self.editor_token),
            identity_store=self.identity, identity_token=self.editor_token)
        self.rev = self.host.standaloneAccountingRead()["revision"]
        self.assertEqual(self.rev, 0)
        self.today = datetime.now(timezone.utc).date().isoformat()
        self.request_id = "a1" * 16
        self.invoice_id = "synthetic-invoice-1"
        self.issue_event_id = "qa-event-invoice-issue-1"
        self.journal_id = "J:" + self.issue_event_id

    def command(self, event):
        result = self.host.standaloneAccountingCommand({
            "command": event, "expectedRevision": self.rev})
        self.rev = result["revision"]
        return result

    def party(self):
        self.command({"type": "party.register", "eventId": "qa-party-1",
                      "partyId": "qa-customer-1", "name": "Synthetic customer",
                      "kind": "customer"})

    def create_invoice(self, *, invoice_id=None, source=True,
                       suffix="1", approve=True):
        name = invoice_id or self.invoice_id
        event = {
            "type": "invoice.create",
            "eventId": "qa-create-" + suffix,
            "invoiceId": name, "partyId": "qa-customer-1",
            "documentDate": self.today,
            "lines": [{"description": "Synthetic service",
                       "quantity": 1, "unitPrice": 1000}],
        }
        if source:
            event.update({"sourceType": "madar", "sourceId": self.request_id})
        self.command(event)
        if approve:
            self.command({"type": "invoice.approve",
                          "eventId": "qa-approve-" + suffix,
                          "invoiceId": name})
        return name

    def issue(self, *, invoice_id=None, event_id=None):
        return self.command({
            "type": "invoice.issue",
            "eventId": event_id or self.issue_event_id,
            "invoiceId": invoice_id or self.invoice_id,
            "postingDate": self.today,
        })

    def booked(self):
        self.party()
        self.create_invoice()
        return self.issue()

    def assess(self, **overrides):
        params = dict(
            host=self.host,
            company_id=self.company_id,
            madar_request_id=self.request_id,
            invoice_id=self.invoice_id,
            issue_event_id=self.issue_event_id,
            journal_id=self.journal_id,
            expected_revision=self.rev)
        params.update(overrides)
        return assess_official_receipt(**params)

    def marker(self, *, decision="reviewed", **changes):
        return {
            "schema": 1, "id": self.request_id, "source": "taraz",
            "taskId": "qa-task", "state": decision,
            "reviewedUtc": "2026-11-10T09:00:00+00:00",
            "financialEventCreated": False, **changes}

    def test_real_store_posted_invoice_journal_is_observable_but_not_official(self):
        self.booked()
        result = self.assess()
        self.assertEqual(result["decision"],
                         "PERSISTED_INVOICE_JOURNAL_OBSERVED_UNBOUND")
        self.assertTrue(result["persistedInvoiceJournalVerified"])
        self.assertTrue(result["currentCompanyAndRoleChecked"])
        self.assertEqual(result["ledgerRevisionObserved"], 4)
        self.assertFalse(result["officialFinanceReceiptVerified"])
        self.assertFalse(result["trustedMadarInvoiceBindingVerified"])
        self.assertFalse(result["safeToRetryFinancialPosting"])
        # Explicit restart/readback from the *same persisted* synthetic book.
        another = AccountingDesktopAPI(
            self.book, company_workspace_id=self.company_id,
            authenticated_user=self.identity.require_session(self.editor_token),
            identity_store=self.identity, identity_token=self.editor_token)
        second = self.assess(host=another)
        self.assertEqual(second["decision"], result["decision"])

    def test_current_integration_review_is_never_financial_posting(self):
        identity = _safe_company(self.host, self.company_id)
        accounts = _principal(self.host, identity)
        self.assertEqual(_snapshot(self.host, accounts)[0], 0)
        self.assertEqual(self.assess()["decision"], "NO_PERSISTED_INVOICE")
        bridge = self.root / "synthetic-bridge"
        (bridge / "pending").mkdir(parents=True)
        raw = {
            "schema": 1, "id": self.request_id, "source": "madar",
            "taskId": "qa-task", "projectId": "qa-project",
            "title": "Synthetic QA proposal",
            "createdUtc": "2026-11-10T08:00:00+00:00"}
        (bridge / "pending" / (self.request_id + ".json")).write_text(
            json.dumps(raw), encoding="utf-8")
        receipt = review_request(bridge, self.request_id, "reviewed")
        self.assertFalse(receipt["financialEventCreated"])
        marker = json.loads((bridge / "reviewed" /
                             (self.request_id + ".review.json")).read_text(encoding="utf8"))
        classified = classify_metadata_review(marker)
        self.assertEqual(classified["decision"], "NONFINANCIAL_REVIEW_ONLY")
        observed = self.assess(review_marker=marker)
        self.assertEqual(observed["decision"], "NO_PERSISTED_INVOICE")
        self.assertTrue(observed["nonfinancialReviewObserved"])
        self.assertFalse(observed["persistedInvoiceJournalVerified"])
        self.assertFalse(observed["officialFinanceReceiptVerified"])
        self.assertEqual(self.host.standaloneAccountingRead()["revision"], 0)

    def test_spoofed_finance_flag_and_marker_id_are_rejected(self):
        self.booked()
        spoof = self.assess(review_marker=self.marker(financialEventCreated=True))
        self.assertEqual(spoof["decision"], "UNTRUSTED_REVIEW_NOT_FINANCE_AUTHORITY")
        self.assertFalse(spoof["persistedInvoiceJournalVerified"])
        wrong = self.assess(review_marker=self.marker(id="b2" * 16))
        self.assertEqual(wrong["decision"], "UNTRUSTED_REVIEW_NOT_FINANCE_AUTHORITY")
        self.assertEqual(classify_metadata_review({"financialEventCreated": True})[
            "decision"], "INVALID_REVIEW_MARKER")

    def test_unposted_draft_and_approved_invoice_not_booked(self):
        self.party()
        self.create_invoice(approve=False)
        self.assertEqual(self.assess()["decision"], "INVOICE_NOT_ISSUED_OR_REVERSED")
        self.command({"type": "invoice.approve", "eventId": "qa-approve-1",
                      "invoiceId": self.invoice_id})
        self.assertEqual(self.assess()["decision"], "INVOICE_NOT_ISSUED_OR_REVERSED")
        self.assertFalse(self.assess()["persistedInvoiceJournalVerified"])

    def test_stale_revision_and_ambiguous_crash_never_enable_retry(self):
        self.party()
        self.create_invoice()
        prior_rev = self.rev
        # Simulated client exception after actual successful COMMIT: no ACK.
        with self.assertRaisesRegex(TimeoutError, "lost acknowledgement"):
            self.issue()
            raise TimeoutError("lost acknowledgement")
        stale = self.assess(expected_revision=prior_rev)
        self.assertEqual(stale["decision"], "STALE_REVISION_AMBIGUOUS_POSTING")
        self.assertFalse(stale["safeToRetryFinancialPosting"])
        self.assertFalse(stale["officialFinanceReceiptVerified"])
        recovery = self.assess()
        self.assertTrue(recovery["persistedInvoiceJournalVerified"])
        self.assertFalse(recovery["officialFinanceReceiptVerified"])

    def test_cross_company_and_wrong_selected_identity_denied(self):
        self.booked()
        self.assertEqual(
            self.assess(company_id="b2" * 16)["decision"],
            "CURRENT_COMPANY_OR_AUTHORITY_DENIED")
        self.host.company_workspace_id = "b2" * 16
        self.assertEqual(self.assess()["decision"],
                         "CURRENT_COMPANY_OR_AUTHORITY_DENIED")
        self.host.company_workspace_id = self.company_id

    def test_revoked_session_and_role_downgrade_denied(self):
        self.booked()
        self.identity.logout(self.editor_token)
        self.assertEqual(self.assess()["decision"],
                         "CURRENT_COMPANY_OR_AUTHORITY_DENIED")
        new_token = self.identity.login("qaeditor", "syntheticOnlyPwd-2")
        self.host._identity_token = new_token
        self.identity.change_role("qaeditor", "viewer", administrator=self.admin_token)
        self.assertEqual(self.assess()["decision"],
                         "CURRENT_COMPANY_OR_AUTHORITY_DENIED")

    def test_local_admin_fallback_is_not_trusted_official_authority(self):
        self.booked()
        local = AccountingDesktopAPI(self.book, company_workspace_id=self.company_id)
        denied = self.assess(host=local)
        self.assertEqual(denied["decision"], "CURRENT_COMPANY_OR_AUTHORITY_DENIED")
        self.assertFalse(denied["persistedInvoiceJournalVerified"])

    def test_fabricated_host_and_closing_company_session_denied(self):
        self.booked()
        forged = SimpleNamespace(**self.host.__dict__)
        self.assertEqual(self.assess(host=forged)["decision"],
                         "CURRENT_COMPANY_OR_AUTHORITY_DENIED")
        self.host._exit_backed_up = True
        self.assertEqual(self.assess()["decision"],
                         "CURRENT_COMPANY_OR_AUTHORITY_DENIED")
        self.host._exit_backed_up = False
        original_path = self.host.path
        self.host.path = self.book / "fake-ledger.sqlite3"
        self.assertEqual(self.assess()["decision"],
                         "CURRENT_COMPANY_OR_AUTHORITY_DENIED")
        self.host.path = original_path

    def test_exact_command_replay_never_becomes_new_official_finance_receipt(self):
        self.booked()
        same_issue = {
            "type": "invoice.issue", "eventId": self.issue_event_id,
            "invoiceId": self.invoice_id, "postingDate": self.today}
        repeat = self.command(same_issue)
        self.assertEqual(repeat["revision"], 4)
        self.assertTrue(self.assess()["persistedInvoiceJournalVerified"])
        self.assertFalse(self.assess()["officialFinanceReceiptVerified"])

    def test_invalid_invoice_event_and_voucher_boundaries(self):
        self.booked()
        self.assertEqual(self.assess(invoice_id="other")["decision"],
                         "NO_PERSISTED_INVOICE")
        self.assertEqual(self.assess(journal_id="J:other")["decision"],
                         "INVALID_OR_UNBOUND_INPUT")
        self.assertEqual(self.assess(issue_event_id="other")["decision"],
                         "INVALID_OR_UNBOUND_INPUT")
        self.assertEqual(self.assess(expected_revision=True)["decision"],
                         "INVALID_OR_UNBOUND_INPUT")

    def test_duplicate_or_ambiguous_source_link_is_not_a_receipt(self):
        self.party()
        self.create_invoice(approve=False)
        self.command({"type": "invoice.cancel", "eventId": "qa-cancel-1",
                      "invoiceId": self.invoice_id,
                      "reason": "Synthetic cancellation"})
        replacement = "synthetic-invoice-2"
        self.create_invoice(invoice_id=replacement, suffix="2")
        self.issue(invoice_id=replacement, event_id=self.issue_event_id)
        verdict = self.assess(invoice_id=replacement)
        self.assertEqual(verdict["decision"], "DUPLICATE_OR_AMBIGUOUS_SOURCE_LINK")
        self.assertFalse(verdict["officialFinanceReceiptVerified"])

    def test_caller_controlled_source_reference_is_not_an_authenticated_madar_link(self):
        self.party()
        self.create_invoice(source=False)
        self.issue()
        result = self.assess()
        self.assertEqual(result["decision"], "UNTRUSTED_INVOICE_SOURCE_LINK")
        self.assertFalse(result["persistedInvoiceJournalVerified"])

    def test_verified_journal_reversed_no_longer_active_booking(self):
        self.booked()
        self.command({"type": "journal.reverse",
                      "eventId": "qa-journal-reverse-1",
                      "journalId": self.journal_id,
                      "postingDate": self.today,
                      "reason": "Synthetic reversal"})
        verdict = self.assess()
        self.assertIn(verdict["decision"], {
            "INVOICE_NOT_ISSUED_OR_REVERSED", "INVOICE_JOURNAL_REVERSED"})
        self.assertFalse(verdict["persistedInvoiceJournalVerified"])

    def test_corrupt_persisted_sqlite_digest_fail_closed(self):
        self.booked()
        with closing(sqlite3.connect(str(self.host.path))) as connection:
            with connection:
                connection.execute(
                    "UPDATE standalone_accounting SET digest=? WHERE id=1",
                    ("0" * 64,))
        verdict = self.assess()
        self.assertEqual(verdict["decision"], "ACCOUNTING_SNAPSHOT_UNVERIFIABLE")
        self.assertFalse(verdict["persistedInvoiceJournalVerified"])


if __name__ == "__main__":
    unittest.main()
