"""Cross-product QA: real loopback HTTPS, pinned TLS, DPAPI vault, restart.

Set MADAR_QA_SOURCE to the local Madar source folder. All test stores are
disposable, no installed application, APPDATA ledger or real user is touched.
"""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from taraz_ecosystem_credentials import TarazEcosystemCredentialVault
from taraz_ecosystem_client import MadarPinnedClient, EcosystemConnectionError


class RealCrossProductPairingTests(unittest.TestCase):
    def setUp(self):
        source = os.environ.get("MADAR_QA_SOURCE", "")
        if not source or not Path(source).is_dir():
            self.skipTest("Set MADAR_QA_SOURCE for two-source HTTPS integration QA")
        self._sys_path = list(sys.path)
        sys.path.insert(0, source)
        # A recovered 1.0.28 stage keeps its disposable TLS fixtures in the
        # isolated candidate's sibling tests/ directory. Do not silently fall
        # back to ACTIVE Madar test credentials when validating that candidate.
        fixtures = (Path(source) / "tests", Path(source).parent / "tests")
        for folder in fixtures:
            if (folder / "test_lan_tls.py").is_file():
                sys.path.insert(0, str(folder))
                break
        self.addCleanup(lambda: setattr(sys, "path", self._sys_path))
        import native_app
        from lan import LanService, certificate_fingerprint
        try:
            from tests.test_lan_tls import _CERT, _KEY
        except ImportError:
            from test_lan_tls import _CERT, _KEY
        self.native_app = native_app
        self.LanService = LanService
        self.tmp = tempfile.TemporaryDirectory(prefix="ecosystem-real-https-qa-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.appdata = self.root / "appdata"
        self.appdata.mkdir()
        self.env = patch.dict(os.environ, {"APPDATA": str(self.appdata)})
        self.env.start()
        self.addCleanup(self.env.stop)
        host_folder = self.root / "madar-host"
        host_folder.mkdir()
        with patch.object(native_app, "datadir", return_value=host_folder):
            self.bridge = native_app.Bridge()
            self.bridge.saveState(native_app.initial_state())
        self.users_path = host_folder / "lan-users.json"
        self.cert = self.root / "test.crt"
        self.key = self.root / "test.key"
        self.cert.write_text(_CERT, encoding="ascii")
        self.key.write_text(_KEY, encoding="ascii")
        self.pin = certificate_fingerprint(self.cert)
        self.server = self.start_host(first=True)
        vault_root = self.root / "taraz-integration-secrets"
        vault_root.mkdir()
        self.vault = TarazEcosystemCredentialVault(vault_root)
        self.vault.initialize()
        self.client = self.make_client()

    def start_host(self, first=False):
        server = self.LanService(self.bridge, self.users_path,
                                 bind="127.0.0.1", port=0,
                                 certfile=self.cert, keyfile=self.key)
        if first:
            server.setup_owner("owner", "sample-test-owner-password")
        server.start()
        self.addCleanup(lambda s=server: s.stop() if s.server else None)
        return server

    def make_client(self, pin=None):
        return MadarPinnedClient(self.vault,
                                 endpoint=f"https://127.0.0.1:{self.server.port}",
                                 cert_sha256=pin or self.pin)

    def issue_code(self):
        auth = self.server.authenticate("owner", "sample-test-owner-password")
        return self.server.integration_router.begin_pairing(
            auth["token"], "owner", product="TARAZ")["code"]

    def test_real_https_pairing_card_acl_restart_rotation_revocation(self):
        code = self.issue_code()
        with self.assertRaises(EcosystemConnectionError):
            self.make_client(pin="0" * 64).pair(code)
        first = self.client.pair(code)
        self.assertEqual(first["installationId"], self.vault.installation_id())
        self.assertEqual(len(first["workspaceId"]), 32)
        result = self.client.cards(workspace_id=first["workspaceId"], limit=2)
        self.assertEqual(result["source"], "MADAR")
        self.assertTrue(result["readOnly"])
        self.assertLessEqual(len(result["cards"]), 2)
        for card in result["cards"]:
            self.assertFalse(set(card) & {"amount", "cost", "finance", "checklists", "ledger"})
        with self.assertRaises(EcosystemConnectionError):
            self.client.pair(code)  # one-use must not succeed a second time

        self.server.stop()
        self.server = self.start_host()
        self.client = self.make_client()
        self.assertEqual(self.client.cards(workspace_id=first["workspaceId"], limit=2)["source"], "MADAR")

        next_code = self.issue_code()
        self.client.pair(next_code)
        self.assertEqual(self.client.cards(workspace_id=first["workspaceId"], limit=2)["source"], "MADAR")
        auth = self.server.authenticate("owner", "sample-test-owner-password")
        peers = self.server.integration_router.connected_installs(auth["token"])["connections"]
        self.assertEqual(sum(p["status"] == "active" for p in peers), 1)
        active = next(p for p in peers if p["status"] == "active")
        self.assertTrue(self.server.integration_router.revoke_key(auth["token"], active["keyId"]))
        with self.assertRaises(EcosystemConnectionError):
            self.client.cards(workspace_id=first["workspaceId"], limit=2)

    def test_tls_pin_required_numeric_host_and_wrong_installation_id_denied(self):
        for endpoint in ("https://localhost:8443", "http://127.0.0.1:443",
                         "https://8.8.8.8:443", "https://test.com:443",
                         "https://127.0.0.1:443/x"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                MadarPinnedClient(self.vault, endpoint=endpoint, cert_sha256=self.pin)
        with self.assertRaises(ValueError):
            self.make_client().cards(workspace_id="invalid")
        with self.assertRaises(Exception):
            self.make_client().cards(workspace_id="f" * 32)

    def test_real_windows_native_company_bridge_pair_read_restart_and_no_post(self):
        from taraz_fresh_windows_workspace import stage_new_empty_root, open_fresh_company
        taraz_root = self.root / "Taraz"
        stage_new_empty_root(taraz_root)
        api, identity, token = open_fresh_company(taraz_root)
        try:
            before = api.standaloneAccountingRead()["revision"]
            self.assertEqual(before, 0)
            self.assertEqual(api.tarazEcosystemConnections()["connections"], [])
            code = self.issue_code()
            request = {"endpoint": f"https://127.0.0.1:{self.server.port}",
                       "certSha256": self.pin, "code": code, "manualConsent": True}
            with self.assertRaises(PermissionError):
                api.tarazEcosystemPair({**request, "manualConsent": False})
            linked = api.tarazEcosystemPair(request)
            self.assertTrue(linked["connected"])
            self.assertFalse(linked["financialEventCreated"])
            self.assertEqual(api.standaloneAccountingRead()["revision"], before)
            connected = api.tarazEcosystemConnections()
            self.assertTrue(connected["configured"])
            self.assertEqual(len(connected["connections"]), 1)
            self.assertNotIn("token", str(connected))
            workspace = linked["workspaceId"]
            cards = api.tarazEcosystemCards({"workspaceId": workspace, "limit": 10})
            self.assertTrue(cards["readOnly"])
            self.assertFalse(cards["financialEventCreated"])
            self.assertEqual(api.standaloneAccountingRead()["revision"], before)
        finally:
            identity.logout(token)
        api, identity, token = open_fresh_company(taraz_root)
        try:
            again = api.tarazEcosystemCards({"workspaceId": workspace, "limit": 10})
            self.assertTrue(again["readOnly"])
            forgotten = api.tarazEcosystemForget({"workspaceId": workspace})
            self.assertTrue(forgotten["revokedLocally"])
            self.assertFalse(forgotten["remoteRevocationConfirmed"])
            with self.assertRaises(PermissionError):
                api.tarazEcosystemCards({"workspaceId": workspace, "limit": 10})
            renewed = api.tarazEcosystemPair({
                "endpoint": f"https://127.0.0.1:{self.server.port}",
                "certSha256": self.pin,
                "code": self.issue_code(), "manualConsent": True})
            self.assertEqual(renewed["workspaceId"], workspace)
            self.assertTrue(api.tarazEcosystemCards(
                {"workspaceId": workspace, "limit": 10})["readOnly"])
            self.assertEqual(api.standaloneAccountingRead()["revision"], 0)
        finally:
            identity.logout(token)


if __name__ == "__main__":
    unittest.main()
