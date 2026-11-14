"""Isolated Windows DPAPI search coverage; no installed or live finance data."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import os
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from taraz_ai_chat_store import AiChatError, TarazAiChatStore, _protect


@unittest.skipUnless(os.name == "nt", "Private AI search requires Windows DPAPI")
class PrivateAiChatSearchTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="qa-taraz-ai-search-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "synthetic-company"
        self.root.mkdir()
        self.store = TarazAiChatStore(self.root, tenant_id="a" * 32, actor="qa_user")

    def seed_conversations(self, count, *, matches=(), title_prefix="other"):
        # Start the real V1 schema, then bulk-seed disposable fixture rows.
        self.store.create("آغاز")
        with closing(sqlite3.connect(self.store.path)) as db:
            for number in range(1, count + 1):
                ident = f"{number:032x}"
                title = f"{title_prefix} {number}" if number not in matches else f"هدف {number}"
                db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?)", (
                    ident, self.store.tenant, self.store.actor, title, "active",
                    "2026-11-14T12:00:00+00:00", "2026-11-14T12:00:00+00:00", 1,
                ))
            db.commit()
        return [f"{number:032x}" for number in range(1, count + 1)]

    def seed_messages(self, store, conversation_id, messages, *, metadata=None):
        with closing(sqlite3.connect(store.path)) as db:
            for revision, text in enumerate(messages, 1):
                db.execute("""INSERT INTO messages
                    (id,conversation_id,role,content_cipher,timestamp,revision,
                     processing_status,references_json) VALUES(?,?,?,?,?,?,?,?)""", (
                    secrets.token_hex(16), conversation_id, "user",
                    _protect(text, store.scope), "2026-11-14T12:00:00+00:00",
                    revision, "saved", metadata or "[]",
                ))
            db.commit()

    def test_older_than_first_eighty_conversations_is_retrievable(self):
        ids = self.seed_conversations(95, matches={1})
        found = self.store.list("هدف")
        self.assertEqual([row["id"] for row in found["conversations"]], [ids[0]])
        self.assertFalse(found["searchTruncated"])
        self.assertFalse(found["hasMore"])

    def test_message_older_than_last_two_hundred_is_retrievable(self):
        cid = self.store.create("مکالمه بدون کلیدواژه")["conversationId"]
        self.seed_messages(self.store, cid, ["فاکتور اصلی بسیار قدیمی"] +
                           [f"پیام معمولی {n}" for n in range(205)])
        found = self.store.list("اصلی بسیار")
        self.assertEqual([row["id"] for row in found["conversations"]], [cid])
        self.assertFalse(found["searchTruncated"])
        self.assertEqual(len(self.store.read(cid)["messages"]), 206)

    def test_persian_unicode_casefold_and_title_search_without_decryption(self):
        cid = self.store.create("گفتگوی UNICODE فارسی ✨")["conversationId"]
        self.seed_messages(self.store, cid, ["آزمون پرداخت به شرکت آریا"])
        with patch("taraz_ai_chat_store._unprotect",
                   side_effect=AssertionError("title match must not decrypt")):
            title = self.store.list("unicode")
        self.assertEqual([item["id"] for item in title["conversations"]], [cid])
        body = self.store.list("پرداخت به شرکت آریا")
        self.assertEqual([item["id"] for item in body["conversations"]], [cid])
        self.assertFalse(body["searchTruncated"])

    def test_plaintext_metadata_is_never_inferred_to_be_message_content(self):
        cid = self.store.create("گفتگوی بدون متن مرتبط")["conversationId"]
        self.seed_messages(self.store, cid, ["متن معمولی"],
                           metadata='[{"marker":"PRIVATE-METADATA-ONLY"}]')
        self.assertEqual(self.store.list("PRIVATE-METADATA-ONLY")["conversations"], [])
        # The V1 schema deliberately leaves titles in plaintext. Search
        # must still include them; encrypting metadata needs a separate review.
        self.assertEqual(self.store.list("بدون متن")["conversations"][0]["id"], cid)
        with closing(sqlite3.connect(self.store.path)) as db:
            title = db.execute("SELECT title FROM conversations WHERE id=?", (cid,)).fetchone()[0]
            cipher = db.execute("SELECT content_cipher FROM messages WHERE conversation_id=?",
                                (cid,)).fetchone()[0]
        self.assertEqual(title, "گفتگوی بدون متن مرتبط")
        self.assertNotIn("متن معمولی".encode("utf-8"), cipher)

    def test_search_enforces_tenant_and_actor_even_with_matching_plain_titles(self):
        own = self.store.create("کلید عمومی")["conversationId"]
        other_actor = TarazAiChatStore(self.root, tenant_id=self.store.tenant,
                                       actor="other_user")
        other_tenant = TarazAiChatStore(self.root, tenant_id="b" * 32,
                                        actor=self.store.actor)
        for other in (other_actor, other_tenant):
            forbidden = other.create("کلید خصوصی محرمانه")["conversationId"]
            self.seed_messages(other, forbidden, ["کلیدواژه محرمانه پیام"])
        self.assertEqual([row["id"] for row in self.store.list("کلید")["conversations"]],
                         [own])
        self.assertEqual(self.store.list("محرمانه")["conversations"], [])
        self.assertEqual(len(other_actor.list("محرمانه")["conversations"]), 1)
        self.assertEqual(len(other_tenant.list("محرمانه")["conversations"]), 1)

    def test_paginated_search_and_plain_list_have_stable_tie_break_order(self):
        ids = self.seed_conversations(14, matches=set(range(1, 15)))
        expected = list(reversed(ids))
        pages = [self.store.list("هدف", limit=5, offset=n) for n in (0, 5, 10)]
        self.assertEqual([r["id"] for page in pages
                          for r in page["conversations"]], expected)
        self.assertEqual([page["hasMore"] for page in pages], [True, True, False])
        self.assertEqual([page["nextOffset"] for page in pages], [5, 10, None])
        self.assertTrue(all(not page["searchTruncated"] for page in pages))
        # Default UI path remains the 80 newest scoped conversations.
        default = self.store.list()
        self.assertEqual(len(default["conversations"]), 15)
        self.assertEqual([item["id"] for item in self.store.list(limit=2, offset=2)[
            "conversations"]], expected[1:3])

    def test_conversation_scan_cap_reports_incomplete_search(self):
        ids = self.seed_conversations(4, matches={1})
        with patch("taraz_ai_chat_store._SEARCH_MAX_CONVERSATIONS", 2):
            result = self.store.list("هدف")
        self.assertEqual(result["conversations"], [])
        self.assertTrue(result["searchTruncated"])
        self.assertIsNone(result["hasMore"])
        self.assertIsNone(result["nextOffset"])
        self.assertIn(ids[0], [item["id"] for item in self.store.list("هدف")["conversations"]])

    def test_decryption_cap_reports_incomplete_search_without_guessed_matches(self):
        cid = self.store.create("متن بدون نتیجه")["conversationId"]
        self.seed_messages(self.store, cid, ["کلید قدیمی", "بدون تطابق", "همچنان نامرتبط"])
        with patch("taraz_ai_chat_store._SEARCH_MAX_DECRYPTIONS", 2):
            incomplete = self.store.list("کلید")
        self.assertEqual(incomplete["conversations"], [])
        self.assertTrue(incomplete["searchTruncated"])
        self.assertIsNone(incomplete["hasMore"])
        full = self.store.list("کلید")
        self.assertEqual([item["id"] for item in full["conversations"]], [cid])

    def test_sql_work_cap_fails_to_explicit_incomplete_result(self):
        self.seed_conversations(95, matches={1})
        with patch("taraz_ai_chat_store._SEARCH_MAX_SQL_PROGRESS_CALLS", 1):
            incomplete = self.store.list("هدف")
        self.assertEqual(incomplete["conversations"], [])
        self.assertTrue(incomplete["searchTruncated"])
        self.assertIsNone(incomplete["hasMore"])
        self.assertEqual(len(self.store.list("هدف")["conversations"]), 1)

    def test_search_uses_read_only_connection_and_does_not_mutate_database(self):
        cid = self.store.create("مکالمه ذخیره شده")["conversationId"]
        self.seed_messages(self.store, cid, ["در جستجوی رکورد"])
        before = sha256(self.store.path.read_bytes()).hexdigest()
        with patch("taraz_ai_chat_store.sqlite3.connect", wraps=sqlite3.connect) as connect:
            self.assertEqual(self.store.list("رکورد")["conversations"][0]["id"], cid)
            self.store.list("")
            self.store.list("ناموجود")
        self.assertTrue(connect.call_args_list)
        for call in connect.call_args_list:
            self.assertIn("mode=ro", call.args[0])
            self.assertTrue(call.kwargs["uri"])
        self.assertEqual(sha256(self.store.path.read_bytes()).hexdigest(), before)
        self.assertEqual(list(self.root.glob("taraz-ai-chat.sqlite3-*")), [])

    def test_query_validation_and_missing_database_are_non_mutating(self):
        self.assertEqual(self.store.list("ناموجود")["conversations"], [])
        self.assertFalse(self.store.path.exists())
        for kwargs in ({"limit": 0}, {"limit": True}, {"limit": 101},
                       {"offset": -1}, {"offset": True}, {"offset": 100001},
                       {"query": "ن" * 151}, {"query": None}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(AiChatError):
                    self.store.list(**kwargs)
        self.assertFalse(self.store.path.exists())


if __name__ == "__main__":
    unittest.main()
