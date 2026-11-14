"""Real local API/SQLite/DPAPI tests; every finance fixture is disposable QA."""
from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from taraz_ai_chat_store import TarazAiChatStore, AiChatError
from taraz_ai_invoice_intake import invoice_preview
from taraz_desktop import TarazAPI
from standalone_accounting_desktop import AccountingDesktopAPI

REQUEST = ("برای شرکت آریا یک فاکتور فروش بساز. ۱۰۰ عدد جعبه و ۲۰۰ عدد لیبل اضافه کن. "
           "قیمت هر کالا را از آخرین فاکتور معتبر همین مشتری بردار.")
QA_COMPANY_ID = "a" * 32


class QaIdentity:
    user = {"username": "qa-ai", "role": "admin", "financeView": True,
            "financeEdit": True, "jobTitle": "QA"}

    def require_session(self, token, required="viewer"):
        if token != "qa-ai-account-session":
            raise PermissionError("Unverified synthetic user")
        if required not in ("viewer", "editor", "admin"):
            raise PermissionError("Unknown role")
        return dict(self.user)

    def accounting_accounts(self):
        return {self.user["username"]: dict(self.user)}


class AuthenticatedQaTarazAPI(TarazAPI):
    def __init__(self, root):
        ident = QaIdentity()
        AccountingDesktopAPI.__init__(
            self, root, authenticated_user=ident.user, company_workspace_id=QA_COMPANY_ID,
            identity_store=ident, identity_token="qa-ai-account-session")
        self._requires_migration = False


@unittest.skipUnless(os.name == "nt", "Encrypted AI chat requires Windows DPAPI")
class AiChatVerticalAcceptance(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="qa-taraz-ai-chat-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "qa" / "company"
        self.root.mkdir(parents=True)
        self.api = AuthenticatedQaTarazAPI(self.root)
        self.events = 0
        self.commit({"type": "party.register", "eventId": "qa-party-arya",
                     "partyId": "arya", "name": "شرکت آریا", "kind": "customer"})
        for name, ident in (("جعبه", "box"), ("لیبل", "label")):
            self.commit({"type": "item.create", "eventId": "qa-catalog-" + ident,
                         "itemId": ident, "sku": ident.upper(),
                         "name": name, "kind": "goods", "unit": "piece"})

    def commit(self, command):
        old = self.api.standaloneAccountingRead()["revision"]
        result = self.api.standaloneAccountingCommand(
            {"command": command, "expectedRevision": old})
        self.events += 1
        return result

    def seed_issued_price(self):
        """Manual synthetic fixture, never a live finance book."""
        self.commit({"type": "invoice.create", "eventId": "qa-price-create",
                     "invoiceId": "QA-SOURCE-INV", "partyId": "arya",
                     "documentDate": "2026-11-12",
                     "lines": [{"description": "جعبه", "quantity": 2, "unitPrice": 1000,
                                "accountId": "4000", "itemId": "box"},
                               {"description": "لیبل", "quantity": 2, "unitPrice": 500,
                                "accountId": "4000", "itemId": "label"}]})
        self.commit({"type": "invoice.approve", "eventId": "qa-source-approve",
                     "invoiceId": "QA-SOURCE-INV"})
        self.commit({"type": "invoice.issue", "eventId": "qa-source-issue",
                     "invoiceId": "QA-SOURCE-INV", "postingDate": "2026-11-12"})

    def test_encrypted_history_survives_restart_and_rejects_other_actor(self):
        created = self.api.tarazAiChatCommand({"action": "create", "title": "آزمون گفتگو"})
        cid = created["conversationId"]
        sent = self.api.tarazAiChatCommand(
            {"action": "send", "conversationId": cid, "text": REQUEST})
        self.assertEqual(sent["status"], "BLOCKED")  # no issued price source
        reopened = AuthenticatedQaTarazAPI(self.root)
        messages = reopened.tarazAiChatRead(cid)["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], REQUEST)
        raw = (self.root / "taraz-ai-chat.sqlite3").read_bytes()
        self.assertNotIn("شرکت آریا".encode("utf-8"), raw)
        forbidden = TarazAiChatStore(self.root, tenant_id=QA_COMPANY_ID,
                                     actor="not-current-user")
        with self.assertRaises(PermissionError):
            forbidden.read(cid)
        self.assertEqual(len(reopened.tarazAiChatList("جعبه")["conversations"]), 1)
        other_company = TarazAiChatStore(
            self.root, tenant_id="b" * 32, actor=QaIdentity.user["username"])
        with self.assertRaises(PermissionError):
            other_company.read(cid)
        self.assertEqual(len(reopened.tarazAiChatCommand(
            {"action": "export", "conversationId": cid})["export"]["messages"]), 2)
        reopened.tarazAiChatCommand({"action": "delete", "conversationId": cid})
        with self.assertRaises(PermissionError):
            reopened.tarazAiChatRead(cid)

    def test_same_windows_user_restore_under_another_path_keeps_encrypted_messages(self):
        cid = self.api.tarazAiChatCommand({
            "action": "create", "title": "آزمون انتقال مجاز"})["conversationId"]
        self.api.tarazAiChatCommand({"action": "send", "conversationId": cid, "text": REQUEST})
        from tempfile import TemporaryDirectory
        import shutil
        with TemporaryDirectory(prefix="qa-ai-restore-another-location-") as dirname:
            restored = Path(dirname) / "restored-company"
            restored.mkdir()
            shutil.copy2(self.root / "taraz-ai-chat.sqlite3",
                         restored / "taraz-ai-chat.sqlite3")
            recovered = AuthenticatedQaTarazAPI(restored)
            texts = recovered.tarazAiChatRead(cid)["messages"]
            self.assertEqual(texts[0]["content"], REQUEST)
            self.assertEqual(len(texts), 2)

    def test_sensitive_text_fails_closed(self):
        cid = self.api.tarazAiChatCommand({"action": "create", "title": "محرمانه"})["conversationId"]
        with self.assertRaises(AiChatError):
            self.api.tarazAiChatCommand({
                "action": "send", "conversationId": cid, "text": "api_key=TOPSECRET"})
        self.assertEqual(self.api.tarazAiChatRead(cid)["messages"], [])

    def test_missing_web_or_madar_source_does_not_invent(self):
        view = self.api.standaloneAccountingRead()
        for suffix, reason in (
            (" از اینترنت اطلاعات را پیدا کن.", "ONLINE_CONSENT_REQUIRED"),
            (" طبق تسک مدار ثبت کن.", "TASK_SOURCE_NOT_CONNECTED")):
            proposal = invoice_preview(REQUEST + suffix, view)
            self.assertEqual(proposal["reason"], reason)
            self.assertFalse(proposal["ready"])
        self.assertEqual(view["view"]["journals"], [])

    def test_issued_sequence_overrides_backdated_document_and_rejects_mixed_prices(self):
        self.seed_issued_price()
        state = deepcopy(self.api.standaloneAccountingRead())
        original = state["view"]["invoices"]["QA-SOURCE-INV"]
        # Synthetic invoice #2 was issued later but has an older document date.
        # The latest source must be the official issue sequence, not max(date).
        newer = {
            **original, "id": "QA-BACKDATED-SECOND", "number": 2,
            "documentDate": "2026-10-01",
            "lines": [{"description": "جعبه", "quantity": 1, "unitPrice": 1700,
                       "accountId": "4000", "itemId": "box"}],
        }
        state["view"]["invoices"]["QA-BACKDATED-SECOND"] = newer
        proposal = invoice_preview(REQUEST, state)
        self.assertTrue(proposal["ready"])
        self.assertEqual(proposal["lines"][0]["unitPrice"], 1700)
        self.assertEqual(proposal["sources"][0]["invoiceId"], "QA-BACKDATED-SECOND")
        self.assertEqual(proposal["sources"][1]["invoiceId"], "QA-SOURCE-INV")
        self.assertEqual(proposal["total"], 270000)
        # Two different prices for the same catalog item in the latest
        # issued invoice are ambiguous. Never select one lexically.
        newer["lines"].append({
            "description": "جعبه", "quantity": 2, "unitPrice": 1900,
            "accountId": "4000", "itemId": "box"})
        blocked = invoice_preview(REQUEST, state)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIn("AMBIGUOUS_SOURCE_LINE_PRICES",
                      [item["reason"] for item in blocked["missing"]])

    def test_cross_company_identical_actor_cannot_read_chat(self):
        cid = self.api.tarazAiChatCommand(
            {"action": "create", "title": "شرکت خصوصی"})["conversationId"]
        other = TarazAiChatStore(self.root, tenant_id="qa-another-company", actor="local")
        with self.assertRaises(PermissionError):
            other.read(cid)

    def test_same_customer_issued_price_human_confirmed_only_draft(self):
        self.seed_issued_price()
        before = self.api.standaloneAccountingRead()
        original_journals = before["view"]["journals"]
        cid = self.api.tarazAiChatCommand({"action": "create", "title": "فاکتور آریا"})["conversationId"]
        result = self.api.tarazAiChatCommand({"action": "send", "conversationId": cid, "text": REQUEST})
        self.assertEqual(result["status"], "READY_FOR_REVIEW")
        proposal = result["proposal"]
        self.assertEqual(proposal["total"], 200000)
        self.assertEqual(len(proposal["sources"]), 2)
        self.assertTrue(all(item["invoiceId"] == "QA-SOURCE-INV" for item in proposal["sources"]))
        self.assertEqual(self.api.standaloneAccountingRead()["revision"], before["revision"])
        with self.assertRaises(PermissionError):
            self.api.tarazAiChatCommand({
                "action": "approve", "conversationId": cid, "actionId": result["actionId"],
                "manualConfirmation": False})
        confirmed = self.api.tarazAiChatCommand({
            "action": "approve", "conversationId": cid, "actionId": result["actionId"],
            "manualConfirmation": True})
        self.assertEqual(confirmed["status"], "DRAFT_SAVED")
        again = AuthenticatedQaTarazAPI(self.root).standaloneAccountingRead()
        saved = again["view"]["invoices"][confirmed["invoiceId"]]
        self.assertEqual(saved["status"], "draft")
        self.assertIsNone(saved.get("postedEntryId"))
        self.assertEqual(saved["total"], 200000)
        self.assertEqual(again["view"]["journals"], original_journals)
        self.assertEqual(self.api.tarazAiChatRead(cid)["executions"][0]["status"], "executed")
        with self.assertRaises(AiChatError):
            self.api.tarazAiChatCommand({
                "action": "approve", "conversationId": cid, "actionId": result["actionId"],
                "manualConfirmation": True})
        self.assertEqual(len(again["view"]["invoices"]), 2)

    def test_stale_revision_rejects_without_draft(self):
        self.seed_issued_price()
        cid = self.api.tarazAiChatCommand({"action": "create", "title": "نسخه قدیمی"})["conversationId"]
        result = self.api.tarazAiChatCommand({"action": "send", "conversationId": cid, "text": REQUEST})
        self.commit({"type": "party.register", "eventId": "qa-party-next",
                     "partyId": "next", "name": "مشتری ساختگی دیگر", "kind": "customer"})
        with self.assertRaises(AiChatError):
            self.api.tarazAiChatCommand({
                "action": "approve", "conversationId": cid, "actionId": result["actionId"],
                "manualConfirmation": True})
        self.assertEqual(len(self.api.standaloneAccountingRead()["view"]["invoices"]), 1)

    def test_legacy_implicit_admin_cannot_open_private_ai_chat(self):
        # The old standalone launcher has implicit 'local' admin: it must
        # NOT inherit the AI service's confidential multi-user capability.
        implicit = TarazAPI(self.root)
        with self.assertRaises(PermissionError):
            implicit.tarazAiChatList("")
        with self.assertRaises(PermissionError):
            implicit.tarazAiChatCommand({"action": "create", "title": "نباید ساخته شود"})
        self.assertEqual(self.api.tarazAiChatList("")["conversations"], [])

    def test_uncertain_action_never_retries_and_cannot_be_deleted(self):
        self.seed_issued_price()
        cid = self.api.tarazAiChatCommand({"action": "create", "title": "قطع عملیات"})[
            "conversationId"]
        proposal = self.api.tarazAiChatCommand({
            "action": "send", "conversationId": cid, "text": REQUEST})
        from taraz_ai_business_service import AiBusinessService
        service = AiBusinessService(self.api)
        service.store.update_action(cid, proposal["actionId"],
                                    approval="approved", status="uncertain")
        original_rev = self.api.standaloneAccountingRead()["revision"]
        # No proof that an accounting command completed: reconciliation
        # reads only; a repeated approval must be blocked.
        readback = self.api.tarazAiChatCommand({
            "action": "reconcile", "conversationId": cid,
            "actionId": proposal["actionId"]})
        self.assertEqual(readback["status"], "UNCERTAIN_NOT_FOUND")
        self.assertFalse(readback["safeToRetry"])
        self.assertEqual(self.api.standaloneAccountingRead()["revision"], original_rev)
        with self.assertRaises(AiChatError):
            self.api.tarazAiChatCommand({
                "action": "approve", "conversationId": cid,
                "actionId": proposal["actionId"], "manualConfirmation": True})
        with self.assertRaises(AiChatError):
            self.api.tarazAiChatCommand({
                "action": "delete", "conversationId": cid})

    def test_executed_action_retains_protected_provenance_after_chat_delete(self):
        self.seed_issued_price()
        cid = self.api.tarazAiChatCommand({"action": "create", "title": "ردگیری اجرا"})[
            "conversationId"]
        proposed = self.api.tarazAiChatCommand({
            "action": "send", "conversationId": cid, "text": REQUEST})
        result = self.api.tarazAiChatCommand({
            "action": "approve", "conversationId": cid,
            "actionId": proposed["actionId"], "manualConfirmation": True})
        from taraz_ai_business_service import AiBusinessService
        store = AiBusinessService(self.api).store
        self.api.tarazAiChatCommand({"action": "delete", "conversationId": cid})
        # Public chat is gone, but minimal encrypted proof must still exist
        # for a future qualified financial audit.
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(store.path)) as db:
            row = db.execute(
                "SELECT payload_cipher,result_reference FROM executions WHERE id=?",
                (proposed["actionId"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[1], result["invoiceId"])
        self.assertNotIn(b'"ready"', row[0])
        from taraz_ai_chat_store import _unprotect
        import json
        self.assertTrue(json.loads(_unprotect(row[0], store.scope))["ready"])


if __name__ == "__main__":
    unittest.main()
