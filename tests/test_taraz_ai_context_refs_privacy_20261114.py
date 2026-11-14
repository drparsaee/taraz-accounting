"""QA-only privacy contract: AI references must never persist arbitrary metadata."""
from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from taraz_ai_chat_store import AiChatError, TarazAiChatStore


@unittest.skipUnless(os.name == "nt", "AI private store requires Windows DPAPI")
class ContextReferencePrivacyTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="qa-taraz-reference-privacy-")
        self.addCleanup(temporary.cleanup)
        self.company = Path(temporary.name) / "synthetic-company"
        self.company.mkdir()
        self.store = TarazAiChatStore(self.company, tenant_id="a" * 32, actor="qa_user")
        self.cid = self.store.create("QA conversation")["conversationId"]

    def message_count(self):
        return len(self.store.read(self.cid)["messages"])

    def test_only_verified_reference_fields_persist_and_read_back(self):
        refs = [{"kind": "invoice", "id": "QA-SOURCE-INV", "sourceRevision": 7},
                {"kind": "madar-task", "id": "qa-task-2"}]
        self.store.append(self.cid, "QA request", "QA reply", refs=refs)
        read = self.store.read(self.cid)
        self.assertEqual(self.message_count(), 2)
        expected = [{"kind": "invoice", "id": "QA-SOURCE-INV", "sourceRevision": 7},
                    {"kind": "madar-task", "id": "qa-task-2", "sourceRevision": None}]
        self.assertEqual(read["messages"][0]["references"], expected)
        with closing(sqlite3.connect(self.company / "taraz-ai-chat.sqlite3")) as db:
            links = db.execute("SELECT entity_type,entity_id,source_revision "
                               "FROM context_links ORDER BY entity_type").fetchall()
        self.assertEqual(len(links), 2)

    def test_unknown_fields_and_private_payload_are_rejected_before_write(self):
        secret = "private-customer-contact@example.test"
        with self.assertRaises(AiChatError):
            self.store.append(self.cid, "QA request", "QA reply",
                refs=[{"kind": "party", "id": "arya", "sourceRevision": 1,
                       "privateContact": secret}])
        self.assertEqual(self.message_count(), 0)
        self.assertNotIn(secret.encode(), (self.company / "taraz-ai-chat.sqlite3").read_bytes())

    def test_unsafe_ids_and_revisions_fail_closed_without_messages(self):
        invalid = [
            [{"kind": "invoice", "id": "INV\u202e-hijack"}],
            [{"kind": "invoice", "id": "INV\nnewline"}],
            [{"kind": "invoice", "id": "safe", "sourceRevision": True}],
            [{"kind": "invoice", "id": "safe", "sourceRevision": -1}],
            [{"kind": "invoice", "id": "safe", "sourceRevision": 1 << 63}],
            [{"kind": ["invoice"], "id": "safe"}],
            ["not a record"],
            [{"kind": "radar-customer", "id": "missing-api"}],
            [{"kind": "invoice", "id": "x"}] * 33,
        ]
        for refs in invalid:
            with self.subTest(refs=str(refs)[:50]):
                with self.assertRaises(AiChatError):
                    self.store.append(self.cid, "QA request", "QA reply", refs=refs)
        self.assertEqual(self.message_count(), 0)


if __name__ == "__main__":
    unittest.main()
