"""Taraz real SQLite link with SYNTHETIC Madar-host response, not live Madar QA."""
import hashlib
import json
import secrets
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import taraz_madar_data_reader as reader
from taraz_madar_order_link import MadarOrderLinkStore
from taraz_order_store import TarazOrderStore, OrderConflict
from tests.test_taraz_order_finance_20261112 import passport
from tests.taraz_p1_real_backend_http_fixture_20261112 import (
    AuthenticatedQaTarazAPI, Identity,
)

class MadarOrderAssociationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix="qa-madar-order-provenance-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"company"
        self.root.mkdir()
        self.book=self.root/"standalone-accounting.sqlite3"
        self.book.write_bytes(b"QA-PRESERVED-FINANCE-BOOK")
        self.book_sha=hashlib.sha256(self.book.read_bytes()).hexdigest()
        self.api=AuthenticatedQaTarazAPI(self.root,Identity())
        self.store=TarazOrderStore(self.root)
        self.links=MadarOrderLinkStore(self.root)
        order_data=passport()
        order_data["projectReference"]="MADAR-QA-1"
        self.order=self.store.command({
            "action":"create","idempotencyKey":secrets.token_hex(16),
            "orderId":"","expectedRevision":0,"data":order_data,
            "nextStatus":None,"manualConfirmation":False,
        },actor="qa-invoice-operator",role="admin")
        self.conn={"url":"https://127.0.0.1:48370",
                   "fingerprint":"a"*64,"username":"madar-qa",
                   "password":"synthetic-not-used-password"}
        self.user={"username":"madar-qa","role":"admin","projects":["MADAR-QA-1"]}
        self.state={"projects":[
            {"id":"MADAR-QA-1","name":"QA project","token":"DO-NOT-COPY","amount":123456},
            {"id":"MADAR-QA-2","name":"Other project"}],
            "tasks":[],"boards":[],"workspaces":[],"templates":[]}

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.book.read_bytes()).hexdigest(),
                         self.book_sha)

    def packets(self,*,tamper=False,user=None):
        digest=hashlib.sha256(json.dumps(self.state,sort_keys=True,ensure_ascii=False,
            separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()
        return ({"token":"T"*40,"user":self.user},
                {"state":self.state,"revision":"0"*64 if tamper else digest,
                 "user":self.user if user is None else user})

    def req(self,revision=0,key=None,order_rev=None,project=None):
        return {"orderId":self.order["id"],
                "expectedOrderRevision":self.order["revision"] if order_rev is None else order_rev,
                "projectId":project or "MADAR-QA-1","pageOffset":0,
                "expectedLinkRevision":revision,"connection":self.conn,
                "explicitConsent":True,"idempotencyKey":key or secrets.token_hex(16)}

    def test_verified_read_only_project_link_and_replay(self):
        self.assertFalse(self.links.path.exists())
        key=secrets.token_hex(16)
        request=self.req(key=key)
        with patch.object(reader,"_pinned_json",side_effect=self.packets()) as calls:
            result=self.api.tarazOrderMadarLink(request)
            self.assertEqual(calls.call_count,2)
        self.assertEqual(result["status"],"VERIFIED_READ_ONLY_MADAR_LINK")
        self.assertEqual(result["linkRevision"],1)
        self.assertTrue(result["serverAclApplied"])
        self.assertFalse(result["madarWritePerformed"])
        read=AuthenticatedQaTarazAPI(self.root,Identity()).tarazOrderMadarLinkRead(
            self.order["id"])
        self.assertTrue(read["currentOrderMatches"])
        self.assertFalse(read["hostMembershipRechecked"])
        self.assertEqual(read["link"]["actor"],"madar-qa")
        self.assertEqual(read["link"]["host_state_revision"],result["sourceRevision"])
        raw=self.links.path.read_bytes()
        self.assertNotIn(self.conn["password"].encode(),raw)
        self.assertNotIn(b"DO-NOT-COPY",raw)
        self.assertNotIn(b"123456",raw)
        with patch.object(reader,"_pinned_json",side_effect=self.packets()):
            replay=self.api.tarazOrderMadarLink(request)
        self.assertEqual(replay,result)
        self.assertEqual(self.links.read(self.order["id"])["link"]["revision"],1)

    def test_bad_project_tampered_authority_consent_stale_refuse(self):
        with self.assertRaises(PermissionError):
            self.api.tarazOrderMadarLink({**self.req(),"explicitConsent":False})
        with self.assertRaises(ValueError):
            self.api.tarazOrderMadarLink(self.req(project="MADAR-QA-2"))
        with self.assertRaises(ValueError):
            self.api.tarazOrderMadarLink(self.req(order_rev=99))
        with patch.object(reader,"_pinned_json",side_effect=self.packets(tamper=True)):
            with self.assertRaises(reader.MadarReadError):
                self.api.tarazOrderMadarLink(self.req())
        with patch.object(reader,"_pinned_json",side_effect=self.packets(
            user={"username":"other","role":"admin","projects":["MADAR-QA-1"]})):
            with self.assertRaises(reader.MadarReadError):
                self.api.tarazOrderMadarLink(self.req())
        self.assertFalse(self.links.path.exists())

    def test_order_revision_change_invalidates_previous_snapshot(self):
        with patch.object(reader,"_pinned_json",side_effect=self.packets()):
            done=self.api.tarazOrderMadarLink(self.req())
        self.assertEqual(done["linkRevision"],1)
        with patch.object(reader,"_pinned_json",side_effect=self.packets()):
            with self.assertRaises(OrderConflict):
                self.api.tarazOrderMadarLink(self.req(revision=0))
        changed=passport()
        changed["projectReference"]="MADAR-QA-1"
        changed["notes"]="updated operational description"
        row=self.store.command({
            "action":"update","idempotencyKey":secrets.token_hex(16),
            "orderId":self.order["id"],"expectedRevision":self.order["revision"],
            "data":changed,"nextStatus":None,"manualConfirmation":False,
        },actor="qa-invoice-operator",role="editor")
        self.assertEqual(row["revision"],self.order["revision"]+1)
        self.assertFalse(self.links.read(row["id"])["currentOrderMatches"])
        with self.assertRaises(ValueError):
            self.api.tarazOrderMadarLink(self.req())
        self.assertEqual(self.links.read(row["id"])["link"]["revision"],1)

if __name__=="__main__":
    unittest.main()
