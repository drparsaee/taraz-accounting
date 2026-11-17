"""Real 127.0.0.1 TLS: Madar host -> Taraz book -> signed reply -> Madar.

Only temporary synthetic *registered company books* and disposable Madar LAN
hosts are used. The installed apps and real accounting data are never read.
"""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from tests.test_taraz_ecosystem_client_20261116 import RealCrossProductPairingTests
from tests.test_taraz_ecosystem_counterparties_20261116 import (
    COMPANY_A, COMPANY_B, registered_book, seed_db, make_state,
)
from taraz_ecosystem_mailbox_peer import TarazMailboxPeer
from taraz_ecosystem_mailbox_consent import NativeMailboxBatchConsent
from taraz_ecosystem_client import EcosystemConnectionError


class RealMadarTarazMailboxTests(RealCrossProductPairingTests):
    def setUp(self):
        super().setUp()
        # This is a synthetic-only substitute for a human OS dialog. It
        # verifies the authenticated TLS/mailbox protocol but makes NO claim
        # about a real native operator clicking a Frozen window.
        native_qa = patch.object(NativeMailboxBatchConsent, "_native_prompt",
                                 return_value=True)
        native_qa.start()
        self.addCleanup(native_qa.stop)

    @staticmethod
    def _synthetic_consent(workspace, company, installation):
        return NativeMailboxBatchConsent(
            None, actor="qa-native-admin", company_id=company,
            workspace_id=workspace, installation_id=installation,
            session_verified=lambda: True)

    def _setup_mailbox(self):
        from integration_mailbox_host_v1 import MadarMailboxHost
        pairing = self.client.pair(self.issue_code())
        workspace = pairing["workspaceId"]
        install = pairing["installationId"]
        token = self.server.authenticate("owner", "sample-test-owner-password")["token"]
        key_id = next(item["keyId"] for item in
                      self.server.integration_router.connected_installs(token)["connections"]
                      if item["installationId"] == install and item["status"] == "active")
        host = MadarMailboxHost(self.server.integration_router)
        host.approve_company(token, company_id=COMPANY_A,
                             installation_id=install, key_id=key_id,
                             manual_confirmation=True)
        hub = self.root / "registered-taraz"
        hub.mkdir()
        book_a = registered_book(hub, COMPANY_A)
        book_b = registered_book(hub, COMPANY_B)
        ledger_a = seed_db(book_a, make_state([
            ("TARAZ-A01", "مشتري شركت آریا", "customer"),
            ("TARAZ-A02", "تامین‌کننده", "vendor")]))
        ledger_b = seed_db(book_b, make_state([
            ("TARAZ-B01", "محرمانه شرکت دوم", "customer")]))
        peer = TarazMailboxPeer(self.client, workspace_id=workspace,
            company_id=COMPANY_A, company_book=book_a,
            authorizer=lambda **kwargs: kwargs.get("company_id") == COMPANY_A,
            native_consent=self._synthetic_consent(workspace, COMPANY_A, install))
        return host, peer, token, key_id, workspace, install, ledger_a, ledger_b

    def test_full_live_loopback_customer_search_restart_isolation_and_rotation(self):
        host, peer, admin, key_id, workspace, install, ledger_a, ledger_b = self._setup_mailbox()
        original_a = hashlib.sha256(ledger_a.read_bytes()).hexdigest()
        original_b = hashlib.sha256(ledger_b.read_bytes()).hexdigest()
        request = "e" * 32
        queued = host.enqueue_search(admin, company_id=COMPANY_A,
            installation_id=install, request_id=request,
            query="مشتری شرکت آریا", kind="customer", limit=5)
        self.assertEqual(queued["status"], "pending")
        self.assertEqual(peer.run_once(limit=5)["completed"], 1)
        self.assertTrue(peer.cache._archive_file(request).is_file())
        confirmed = host.reconcile(admin, company_id=COMPANY_A,
                                   installation_id=install, request_id=request)
        self.assertEqual(confirmed["status"], "completed")
        self.assertEqual([p["partyId"] for p in confirmed["result"]["parties"]],
                         ["TARAZ-A01"])
        self.assertEqual(peer.run_once(limit=5)["received"], 0)
        self.assertTrue(host.reconcile(admin, company_id=COMPANY_A,
                                      installation_id=install, request_id=request,
                                      acknowledge=True)["acknowledged"])
        self.assertTrue(peer.cache._archive_file(request).is_file())
        # Result is durable even if the LAN service and peer client restart.
        self.server.stop()
        self.server = self.start_host()
        self.client = self.make_client()
        host = type(host)(self.server.integration_router)
        admin = self.server.authenticate("owner", "sample-test-owner-password")["token"]
        after_restart = host.reconcile(admin, company_id=COMPANY_A,
                                       installation_id=install, request_id=request)
        self.assertEqual(after_restart["result"], confirmed["result"])
        self.assertEqual(after_restart["status"], "completed")
        self.assertTrue(after_restart["acknowledged"])
        self.assertEqual(hashlib.sha256(ledger_a.read_bytes()).hexdigest(), original_a)
        self.assertEqual(hashlib.sha256(ledger_b.read_bytes()).hexdigest(), original_b)
        # A peer paired to company A cannot poll B, even with the same token.
        bad = TarazMailboxPeer(self.client, workspace_id=workspace,
            company_id=COMPANY_B, company_book=ledger_b.parent,
            authorizer=lambda **kwargs: True,
            native_consent=self._synthetic_consent(workspace, COMPANY_B, install))
        with self.assertRaises(EcosystemConnectionError):
            bad.run_once(limit=5)
        self.assertTrue(self.server.integration_router.revoke_key(admin, key_id))
        with self.assertRaises(EcosystemConnectionError):
            TarazMailboxPeer(self.client, workspace_id=workspace, company_id=COMPANY_A,
                company_book=ledger_a.parent, authorizer=lambda **kwargs: True,
                native_consent=self._synthetic_consent(workspace, COMPANY_A, install)).run_once()
        # A new one-time pairing is NOT a grant for the old company.
        self.client.pair(self.issue_code())
        with self.assertRaises(EcosystemConnectionError):
            TarazMailboxPeer(self.client, workspace_id=workspace, company_id=COMPANY_A,
                company_book=ledger_a.parent, authorizer=lambda **kwargs: True,
                native_consent=self._synthetic_consent(workspace, COMPANY_A, install)).run_once()

    def test_reply_retry_after_lost_transport_failure_uses_sealed_snapshot(self):
        host, peer, admin, _, workspace, install, ledger_a, _ = self._setup_mailbox()
        request = "d" * 32
        host.enqueue_search(admin, company_id=COMPANY_A,
            installation_id=install, request_id=request,
            query="مشتری شرکت آریا", kind="customer", limit=5)
        actual = self.client._request
        def disconnected(method, path, **kwargs):
            if path.endswith("/mailbox/reply"):
                raise EcosystemConnectionError("Simulated connectivity interruption")
            return actual(method, path, **kwargs)
        with patch.object(self.client, "_request", side_effect=disconnected):
            with self.assertRaises(EcosystemConnectionError):
                peer.run_once(limit=5)
        # A changed legal name after the interruption MUST NOT change the
        # signed reply content of the original immutable request.
        ledger_a.unlink()
        seed_db(ledger_a.parent, make_state([
            ("TARAZ-A01", "نام جدید بعد از قطع ارتباط", "customer")]))
        self.assertEqual(peer.run_once(limit=5)["completed"], 1)
        result = host.reconcile(admin, company_id=COMPANY_A,
                                installation_id=install, request_id=request)
        self.assertEqual(result["status"], "completed")
        self.assertIn("آریا", result["result"]["parties"][0]["name"])
        self.assertNotIn("نام جدید", json.dumps(result, ensure_ascii=False))

    def test_native_madar_bridge_uses_fresh_admin_credentials_not_owner_shortcut(self):
        host, peer, admin, key_id, workspace, install, _, _ = self._setup_mailbox()
        self.bridge.lan = self.server
        self.bridge.connection = {**self.bridge.connection, "mode": "server"}
        credentials = {"username": "owner", "password": "sample-test-owner-password"}
        with self.assertRaises(PermissionError):
            self.bridge.integrationMailboxConnections({
                "username": "owner", "password": "wrong-password"})
        listed = self.bridge.integrationMailboxConnections(credentials)
        self.assertTrue(any(x["keyId"] == key_id for x in listed["connections"]))
        request = "f" * 32
        queued = self.bridge.integrationMailboxEnqueue(credentials, {
            "companyId": COMPANY_A, "installationId": install,
            "requestId": request, "query": "مشتری شرکت آریا", "kind": "customer",
            "limit": 5, "cursor": None})
        self.assertEqual(queued["status"], "pending")
        self.assertEqual(peer.run_once(limit=5)["completed"], 1)
        result = self.bridge.integrationMailboxReconcile(credentials, {
            "companyId": COMPANY_A, "installationId": install,
            "requestId": request, "acknowledge": True})
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["result"]["parties"][0]["partyId"], "TARAZ-A01")
        self.assertNotIn("password", str(result))

    def test_native_taraz_company_bridge_processes_real_book_and_madar_card_link_survives(self):
        """Both REAL native backends on a disposable, registered Taraz company."""
        from taraz_fresh_windows_workspace import stage_new_empty_root, open_fresh_company
        company_root = self.root / "taraz-native-book"
        stage_new_empty_root(company_root)
        api, identity, login_token = open_fresh_company(company_root)
        try:
            # An explicitly synthetic window identity permits the patched
            # Python-only dialog above. Production requires a real Window.
            api._native_window = object()
            written = api.standaloneAccountingCommand({
                "expectedRevision": 0,
                "command": {"type": "party.register",
                            "eventId": "phase-c-fresh-book-only-customer",
                            "partyId": "qa-party-one",
                            "name": "مشتری مجاز فاز سی",
                            "kind": "customer", "creditLimit": 12345}})
            self.assertEqual(written["revision"], 1)
            book_before = hashlib.sha256(api.path.read_bytes()).hexdigest()
            paired = api.tarazEcosystemPair({
                "endpoint": f"https://127.0.0.1:{self.server.port}",
                "certSha256": self.pin, "code": self.issue_code(),
                "manualConsent": True})
            company_id = api.company_workspace_id
            installation_id = api.tarazEcosystemConnections()["installationId"]
            owner = self.server.authenticate("owner", "sample-test-owner-password")["token"]
            key_id = next(x["keyId"] for x in
                self.server.integration_router.connected_installs(owner)["connections"]
                if x["installationId"] == installation_id and x["status"] == "active")
            self.bridge.lan = self.server
            self.bridge.connection = {**self.bridge.connection, "mode": "server"}
            admin_credentials = {"username": "owner",
                                 "password": "sample-test-owner-password"}
            verified = self.bridge.integrationMailboxApproveCompany(admin_credentials, {
                "keyId": key_id, "companyId": company_id,
                "installationId": installation_id, "manualConfirmation": True})
            self.assertTrue(verified["approved"])
            request_id = "9" * 32
            self.assertEqual(self.bridge.integrationMailboxEnqueue(admin_credentials, {
                "companyId": company_id, "installationId": installation_id,
                "requestId": request_id, "query": "مشتری مجاز",
                "kind": "customer", "limit": 5, "cursor": None})["status"], "pending")
            with self.assertRaises(PermissionError):
                api.tarazEcosystemMailboxProcess({
                    "workspaceId": paired["workspaceId"],
                    "limit": 5, "manualConsent": False})
            completed = api.tarazEcosystemMailboxProcess({
                "workspaceId": paired["workspaceId"],
                "limit": 5, "manualConsent": True})
            self.assertEqual(completed["received"], 1)
            self.assertEqual(completed["completed"], 1)
            self.assertFalse(completed["financialEventCreated"])
            result = self.bridge.integrationMailboxReconcile(admin_credentials, {
                "companyId": company_id, "installationId": installation_id,
                "requestId": request_id, "acknowledge": True})
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["result"]["parties"], [{
                "partyId": "qa-party-one", "name": "مشتری مجاز فاز سی",
                "kind": "customer"}])
            self.assertEqual(hashlib.sha256(api.path.read_bytes()).hexdigest(), book_before)
            self.assertEqual(api.standaloneAccountingRead()["revision"], 1)

            # Reopen the actual Madar persisted state, not browser-only mock.
            before = self.bridge.getState()
            self.assertTrue(before["tasks"])
            chosen = before["tasks"][0]
            reference = {"workspaceId": paired["workspaceId"],
                         "installationId": installation_id,
                         "companyId": company_id, "partyId": "qa-party-one",
                         "kind": "customer"}
            chosen["tarazCustomerRef"] = reference
            self.bridge.saveState(before)
            with patch.object(self.native_app, "datadir", return_value=self.users_path.parent):
                after_restart = self.native_app.Bridge()
            persisted = next(t for t in after_restart.getState()["tasks"]
                             if t["id"] == chosen["id"])
            self.assertEqual(persisted["tarazCustomerRef"], reference)
            self.assertEqual(hashlib.sha256(api.path.read_bytes()).hexdigest(), book_before)
        finally:
            identity.logout(login_token)
        with self.assertRaises(PermissionError):
            api.tarazEcosystemMailboxProcess({
                "workspaceId": paired["workspaceId"],
                "limit": 5, "manualConsent": True})

