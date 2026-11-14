"""Synthetic Windows DPAPI/SQLite replay and crash-window acceptance tests.

Does not instantiate the installed launcher or access real accounting data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from taraz_ai_business_service import AiBusinessService
from taraz_ai_chat_store import AiChatError, TarazAiChatStore


class SyntheticHost:
    def __init__(self, root: Path, actor: str, company_id: str):
        self.path = root / "standalone-accounting.sqlite3"
        self._identity_store = object()  # Synthetic already-verified QA principal.
        self._identity_token = "qa-synthetic-session"
        self._actor = actor
        self.company_workspace_id = company_id
        self._exit_backed_up = False
        self.reads = 0
        self.snapshot = {"revision": 7, "view": {
            "currency": "RIAL", "parties": {}, "items": {},
            "invoices": {}, "accounts": {}, "journals": [],
        }}

    def _require_authenticated(self, required="viewer"):
        if self._identity_token != "qa-synthetic-session":
            raise PermissionError("Synthetic identity expired")
        return {"username": self._actor, "role": "admin"}

    def standaloneAccountingRead(self):
        self.reads += 1
        return deepcopy(self.snapshot)


@unittest.skipUnless(os.name == "nt", "AI history encryption requires Windows DPAPI")
class IdempotentAiChatTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory(prefix="qa-ai-idempotency-20261114-")
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name) / "qa-company"
        self.root.mkdir()
        self.host = SyntheticHost(self.root, "qa_actor_1", "a" * 32)
        self.service = AiBusinessService(self.host)
        self.key = "1" * 32

    def action(self, kind, **args):
        return self.service.command({"action": kind, **args})

    def counts(self):
        with closing(sqlite3.connect(self.root / "taraz-ai-chat.sqlite3")) as connection:
            return {table: connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                    for table in ("conversations", "messages", "executions",
                                  "provider_requests", "action_keys")}

    def test_create_lost_response_replay_same_ids_across_reopened_service(self):
        first = self.action("create", title="گفتگوی آزمایشی", clientRequestId=self.key)
        counts = self.counts()
        reopened = AiBusinessService(self.host)
        second = reopened.command({"action": "create", "title": "گفتگوی آزمایشی",
                                   "clientRequestId": self.key})
        self.assertEqual(first, second)
        self.assertEqual(self.counts(), counts)
        self.assertEqual(counts["conversations"], 1)
        self.assertEqual(counts["action_keys"], 1)

    def test_send_lost_response_does_not_read_finance_again_or_duplicate_messages(self):
        conversation = self.action("create", title="QA")
        request = {"action": "send", "conversationId": conversation["conversationId"],
                   "text": "درخواست آزمایشی بدون مشتری", "clientRequestId": self.key}
        first = self.service.command(request)
        counts = self.counts()
        finance_reads = self.host.reads
        self.assertEqual(finance_reads, 1)
        second = AiBusinessService(self.host).command(request)
        self.assertEqual(second, first)
        self.assertEqual(self.counts(), counts)
        self.assertEqual(self.host.reads, finance_reads)
        self.assertEqual(counts["messages"], 2)
        self.assertEqual(counts["executions"], 1)
        self.assertEqual(counts["provider_requests"], 1)
        self.assertEqual(counts["action_keys"], 1)
        self.assertFalse(first["invoiceDraftCreated"])
        self.assertFalse(first["journalPosted"])

    def test_ready_proposal_replay_preserves_original_price_even_after_source_changes(self):
        self.host.snapshot["view"].update({
            "parties": {"arya": {"id": "arya", "name": "شرکت آریا", "kind": "customer"}},
            "items": {"box": {"id": "box", "name": "جعبه", "active": True,
                              "unit": "piece"}},
            "invoices": {"source": {"id": "QA-ISSUED-SOURCE", "status": "issued",
                "partyId": "arya", "currency": "RIAL", "number": 14,
                "documentDate": "2026-11-13",
                "lines": [{"itemId": "box", "unitPrice": 1000}]}},
            "accounts": {"4000": {"kind": "revenue"}},
        })
        cid = self.action("create", title="QA")["conversationId"]
        request = {"action": "send", "conversationId": cid,
                   "text": ("برای شرکت آریا یک فاکتور فروش بساز. "
                            "۱۰۰ عدد جعبه اضافه کن. "
                            "قیمت هر کالا را از آخرین فاکتور معتبر همین مشتری بردار."),
                   "clientRequestId": self.key}
        first = self.service.command(request)
        self.assertEqual(first["status"], "READY_FOR_REVIEW")
        self.assertEqual(first["proposal"]["total"], 100000)
        self.assertEqual(first["proposal"]["sources"][0]["invoiceId"],
                         "QA-ISSUED-SOURCE")
        self.host.snapshot["revision"] += 1
        self.host.snapshot["view"]["invoices"]["source"]["lines"][0]["unitPrice"] = 9000
        reads = self.host.reads
        again = AiBusinessService(self.host).command(request)
        self.assertEqual(again, first)
        self.assertEqual(self.host.reads, reads)
        self.assertEqual(self.counts()["messages"], 2)
        self.assertEqual(self.counts()["executions"], 1)
        with closing(sqlite3.connect(self.root / "taraz-ai-chat.sqlite3")) as connection:
            cached = connection.execute("SELECT response_json FROM action_keys").fetchone()[0]
        self.assertNotIn("READY_FOR_REVIEW", cached)
        self.assertNotIn("QA-ISSUED-SOURCE", cached)

    def test_same_key_different_create_payload_is_rejected(self):
        self.action("create", title="عنوان اول", clientRequestId=self.key)
        with self.assertRaisesRegex(AiChatError, "different request"):
            self.action("create", title="عنوان دوم", clientRequestId=self.key)
        self.assertEqual(self.counts()["conversations"], 1)

    def test_same_key_different_send_payload_is_rejected_before_finance_read(self):
        cid = self.action("create", title="QA")["conversationId"]
        self.action("send", conversationId=cid, text="درخواست شماره یک",
                    clientRequestId=self.key)
        original_reads = self.host.reads
        with self.assertRaisesRegex(AiChatError, "different request"):
            self.action("send", conversationId=cid, text="درخواست شماره دو",
                        clientRequestId=self.key)
        self.assertEqual(self.host.reads, original_reads)
        self.assertEqual(self.counts()["messages"], 2)

    def test_key_cannot_be_reused_for_different_action(self):
        cid = self.action("create", title="QA", clientRequestId=self.key)["conversationId"]
        with self.assertRaisesRegex(AiChatError, "different request"):
            self.action("send", conversationId=cid, text="دستور دوم",
                        clientRequestId=self.key)
        self.assertEqual(self.host.reads, 0)

    def test_same_id_is_scoped_to_actor_and_tenant(self):
        first = self.action("create", title="QA", clientRequestId=self.key)
        another_actor = SyntheticHost(self.root, "qa_actor_2", "a" * 32)
        other_actor_service = AiBusinessService(another_actor)
        actor_result = other_actor_service.command({
            "action": "create", "title": "QA", "clientRequestId": self.key})
        another_tenant = SyntheticHost(self.root, "qa_actor_1", "b" * 32)
        tenant_result = AiBusinessService(another_tenant).command({
            "action": "create", "title": "QA", "clientRequestId": self.key})
        self.assertEqual(len({first["conversationId"], actor_result["conversationId"],
                              tenant_result["conversationId"]}), 3)
        self.assertEqual(self.counts()["action_keys"], 3)
        with self.assertRaises(PermissionError):
            other_actor_service.read(first["conversationId"])
        with self.assertRaises(PermissionError):
            AiBusinessService(another_tenant).read(first["conversationId"])

    def test_invalid_client_ids_fail_closed_without_persistent_changes(self):
        for bad in ("", "x" * 32, "A" * 32, "1" * 31, "1" * 33, 42, None):
            with self.subTest(bad=bad):
                with self.assertRaises(AiChatError):
                    self.action("create", title="QA", clientRequestId=bad)
        self.assertFalse((self.root / "taraz-ai-chat.sqlite3").exists())

    def test_two_concurrent_create_calls_persist_one_conversation(self):
        request = {"action": "create", "title": "QA", "clientRequestId": self.key}
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(AiBusinessService(self.host).command, request)
                       for _ in range(2)]
            first, second = [f.result() for f in futures]
        self.assertEqual(first, second)
        self.assertEqual(self.counts()["conversations"], 1)

    def test_two_concurrent_send_calls_persist_one_pair_and_proposal(self):
        cid = self.action("create", title="QA")["conversationId"]
        request = {"action": "send", "conversationId": cid, "text": "درخواست",
                   "clientRequestId": self.key}
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(AiBusinessService(self.host).command, request)
                       for _ in range(2)]
            first, second = [f.result() for f in futures]
        self.assertEqual(first, second)
        self.assertEqual(self.counts()["messages"], 2)
        self.assertEqual(self.counts()["executions"], 1)
        self.assertEqual(self.counts()["action_keys"], 1)

    def test_failed_cache_write_rolls_back_create_and_retry_can_succeed(self):
        with patch.object(TarazAiChatStore, "_cache_response",
                          side_effect=RuntimeError("synthetic interruption")):
            with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                self.action("create", title="QA", clientRequestId=self.key)
        self.assertEqual(self.counts()["conversations"], 0)
        self.assertEqual(self.counts()["action_keys"], 0)
        self.action("create", title="QA", clientRequestId=self.key)
        self.assertEqual(self.counts()["conversations"], 1)

    def test_failed_cache_write_rolls_back_message_pair_and_proposal(self):
        cid = self.action("create", title="QA")["conversationId"]
        request = {"action": "send", "conversationId": cid, "text": "درخواست",
                   "clientRequestId": self.key}
        with patch.object(TarazAiChatStore, "_cache_response",
                          side_effect=RuntimeError("synthetic interruption")):
            with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                self.service.command(request)
        self.assertEqual(self.counts()["messages"], 0)
        self.assertEqual(self.counts()["executions"], 0)
        self.assertEqual(self.counts()["provider_requests"], 0)
        self.assertEqual(self.counts()["action_keys"], 0)
        saved = self.service.command(request)
        self.assertIsNotNone(saved["actionId"])
        self.assertEqual(self.counts()["messages"], 2)

    def test_legacy_create_send_without_client_id_remain_compatible(self):
        first = self.action("create", title="QA")
        second = self.action("create", title="QA")
        self.assertNotEqual(first["conversationId"], second["conversationId"])
        result = self.action("send", conversationId=first["conversationId"],
                             text="درخواست آزمایشی")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self.counts()["action_keys"], 0)
        self.assertFalse(result["journalPosted"])
        self.assertFalse(result["invoiceDraftCreated"])


if __name__ == "__main__":
    unittest.main()
