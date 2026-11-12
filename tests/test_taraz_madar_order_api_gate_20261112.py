"""Full TarazAPI gated Madar operation using synthetic HTTPS responses only.

No real Madar credentials or LAN write. Actual local Taraz SQLite and actual
Madar state adapter are exercised; only the network transport is replaced.
"""
import hashlib
import json
import secrets
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import taraz_madar_data_reader as reader
import taraz_madar_order_sync as sync
from taraz_order_store import TarazOrderStore
from tests.test_taraz_order_finance_20261112 import passport
from tests.test_taraz_madar_order_sync_20261112 import madar_state
from tests.taraz_p1_real_backend_http_fixture_20261112 import (
    AuthenticatedQaTarazAPI, Identity,
)


class MadarOperationalApiGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix="qa-taraz-madar-api-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"company"
        self.root.mkdir()
        self.sentinel=self.root/"standalone-accounting.sqlite3"
        self.sentinel.write_bytes(b"TEST-ACCOUNTING-LEDGER-DO-NOT-ALTER")
        self.before=hashlib.sha256(self.sentinel.read_bytes()).hexdigest()
        self.identity=Identity()
        self.api=AuthenticatedQaTarazAPI(self.root,self.identity)
        self.store=TarazOrderStore(self.root)
        data=passport()
        data["projectReference"]="test-p1"
        self.order=self.store.command({
            "action":"create","idempotencyKey":secrets.token_hex(16),
            "orderId":"","expectedRevision":0,"data":data,
            "nextStatus":None,"manualConfirmation":False,
        },actor="qa-invoice-operator",role="admin")
        self.conn={"url":"https://127.0.0.1:48370","fingerprint":"a"*64,
                   "username":"madar-test","password":"synthetic-test-password"}
        self.madar=madar_state()
        self.user={"username":"madar-test","role":"admin","projects":None}

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.sentinel.read_bytes()).hexdigest(),
                         self.before)

    def packets(self,state=None):
        source=self.madar if state is None else state
        revision=hashlib.sha256(json.dumps(source,ensure_ascii=False,
            sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
        return ({"token":"R"*40,"user":self.user},
                {"state":source,"revision":revision,"user":self.user})

    def bind_project(self):
        request={"orderId":self.order["id"],
            "expectedOrderRevision":self.order["revision"],
            "projectId":"test-p1","pageOffset":0,"expectedLinkRevision":0,
            "connection":self.conn,"explicitConsent":True,
            "idempotencyKey":secrets.token_hex(16)}
        with patch.object(reader,"_pinned_json",side_effect=self.packets()):
            output=self.api.tarazOrderMadarLink(request)
        self.assertEqual(output["status"],"VERIFIED_READ_ONLY_MADAR_LINK")
        self.assertFalse(output["madarWritePerformed"])

    def preview(self):
        with patch.object(sync,"_pinned_json",side_effect=self.packets()) as read, patch.object(
                sync,"_write_pinned_state") as write:
            result=self.api.tarazMadarOrderPreview(
                self.order["id"],"test-p1",self.conn,True)
            self.assertEqual(read.call_count,2)
            write.assert_not_called()
        self.assertEqual(result["status"],"PREVIEW_ONLY")
        self.assertEqual(result["taskPreview"]["tarazOrderSourceId"],self.order["id"])
        self.assertFalse(result["wroteMadarState"])
        return result

    def payload(self,preview):
        return {"orderId":self.order["id"],
                "expectedOrderRevision":self.order["revision"],
                "projectId":"test-p1",
                "expectedMadarRevision":preview["sourceRevision"],
                "previewDigest":preview["previewDigest"],
                "explicitConsent":True,"manualConfirmation":True}

    def test_explicit_confirmed_preview_commit_one_task_and_recovery(self):
        self.bind_project()
        preview=self.preview()
        writes=[]
        def emulate_transport(host,port,pin,token,state,expected):
            writes.append((host,port,expected,state))
            return {"state":state,"user":self.user,
                    "revision":hashlib.sha256(json.dumps(state,ensure_ascii=False,
                        sort_keys=True,separators=(",",":"),allow_nan=False
                    ).encode()).hexdigest()}
        with patch.object(sync,"_pinned_json",side_effect=self.packets()), patch.object(
                sync,"_write_pinned_state",side_effect=emulate_transport):
            result=self.api.tarazMadarOrderCommit(self.payload(preview),self.conn)
        self.assertEqual(result["status"],"SYNCHRONIZED")
        self.assertTrue(result["wroteMadarState"])
        self.assertEqual(len(writes),1)
        self.assertEqual(writes[0][0],"127.0.0.1")
        self.assertEqual(writes[0][2],preview["sourceRevision"])
        self.assertEqual(len(writes[0][3]["tasks"]),1)
        self.assertEqual(writes[0][3]["tasks"][0]["tarazOrderSourceId"],
                         self.order["id"])
        # Lost acknowledgement recovery: READ the remote task, do not repeat
        # an already-reviewed write against a newer Madar state revision.
        with patch.object(sync,"_pinned_json",
                          side_effect=self.packets(writes[0][3])), patch.object(
                sync,"_write_pinned_state") as second_write:
            recovered=self.api.tarazMadarOrderPreview(
                self.order["id"],"test-p1",self.conn,True)
            second_write.assert_not_called()
        self.assertEqual(recovered["status"],"ALREADY_SYNCED")
        self.assertFalse(recovered["wroteMadarState"])
        self.assertEqual(self.store.get(self.order["id"])["revision"],1)

    def test_authenticated_host_progress_is_read_only_and_role_gated(self):
        with self.assertRaises(PermissionError):
            self.api.tarazMadarOrderProgress(
                self.order['id'],'test-p1',self.conn,False)
        with patch.object(sync,'_pinned_json') as host:
            with self.assertRaises(PermissionError):
                self.api.tarazMadarOrderProgress(
                    self.order['id'],'test-p1',self.conn,True)
            host.assert_not_called()
        self.bind_project()
        state,task,_=sync.prepare_madar_order_state(
            self.madar,order=self.order,project_id='test-p1')
        state['tasks'][0]['checklist'][2]['done']=True
        before=json.dumps(state,sort_keys=True,ensure_ascii=False)
        with patch.object(sync,'_pinned_json',
                          side_effect=self.packets(state)) as reads, patch.object(
                              sync,'_write_pinned_state') as writes:
            output=self.api.tarazMadarOrderProgress(
                self.order['id'],'test-p1',self.conn,True)
            self.assertEqual(reads.call_count,2)
            writes.assert_not_called()
        self.assertEqual(output['status'],'CURRENT_SOURCE')
        self.assertEqual(output['source'],'MADAR_AUTHENTICATED_HOST_READ')
        self.assertTrue(output['readOnly'])
        self.assertFalse(output['hostWriteAttempted'])
        self.assertFalse(output['financialEventCreated'])
        self.assertEqual(output['completedStages'],1)
        self.assertEqual(len(output['stages']),6)
        self.assertEqual(json.dumps(state,sort_keys=True,ensure_ascii=False),before)
        self.assertEqual(self.store.get(self.order['id'])['revision'],1)

    def test_no_link_confirmation_or_stale_host_never_posts(self):
        with patch.object(sync,"_pinned_json") as host, patch.object(
                sync,"_write_pinned_state") as writer:
            with self.assertRaises(PermissionError):
                self.api.tarazMadarOrderPreview(
                    self.order["id"],"test-p1",self.conn,True)
            host.assert_not_called()
            writer.assert_not_called()
        self.bind_project()
        preview=self.preview()
        with patch.object(sync,"_pinned_json") as host, patch.object(
                sync,"_write_pinned_state") as writer:
            with self.assertRaises(PermissionError):
                self.api.tarazMadarOrderCommit({
                    **self.payload(preview),"manualConfirmation":False},self.conn)
            host.assert_not_called()
            writer.assert_not_called()
        with patch.object(sync,"_pinned_json",side_effect=self.packets()), patch.object(
                sync,"_write_pinned_state") as writer:
            with self.assertRaises(sync.MadarReadError):
                self.api.tarazMadarOrderCommit({
                    **self.payload(preview),"expectedMadarRevision":"0"*64},self.conn)
            writer.assert_not_called()
        with patch.object(sync,"_pinned_json",side_effect=self.packets()), patch.object(
                sync,"_write_pinned_state") as writer:
            with self.assertRaises(sync.MadarReadError):
                self.api.tarazMadarOrderCommit({
                    **self.payload(preview),"previewDigest":"0"*64},self.conn)
            writer.assert_not_called()

    def test_role_and_revocation_forbid_madar_sync(self):
        self.bind_project()
        operator=Identity()
        operator.user["role"]="editor"
        editor=AuthenticatedQaTarazAPI(self.root,operator)
        with self.assertRaises(PermissionError):
            editor.tarazMadarOrderPreview(
                self.order["id"],"test-p1",self.conn,True)
        with self.assertRaises(PermissionError):
            editor.tarazMadarOrderCommit({
                "orderId":self.order["id"],"expectedOrderRevision":1,
                "projectId":"test-p1","expectedMadarRevision":"a"*64,
                "previewDigest":"b"*64,"explicitConsent":True,
                "manualConfirmation":True},self.conn)


if __name__=="__main__":
    unittest.main()
