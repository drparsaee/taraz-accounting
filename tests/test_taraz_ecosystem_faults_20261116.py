"""Real Windows fault-injection QA for bounded HTTPS and session revalidation.

All resources are disposable synthetic stores and loopback-only sockets. The
installed user ledger, Madar processes and production profiles are untouched.
"""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from hashlib import sha256
import os
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from taraz_ecosystem_credentials import TarazEcosystemCredentialVault
from taraz_ecosystem_client import MadarPinnedClient, EcosystemConnectionError


@unittest.skipUnless(os.name == "nt", "Windows DPAPI + local TLS acceptance")
class EcosystemFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="taraz-pair-fault-qa-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secrets = self.root / "integration-secrets"
        self.secrets.mkdir()
        self.vault = TarazEcosystemCredentialVault(self.secrets)
        self.vault.initialize()

    def test_dribbling_tls_response_hits_real_absolute_deadline(self):
        madar = Path(os.environ.get("MADAR_QA_SOURCE", ""))
        if not (madar / "lan.py").is_file():
            self.skipTest("Explicit local Madar QA source required")
        sys.path.insert(0, str(madar))
        sys.path.insert(0, str(madar / "tests"))
        self.addCleanup(lambda: sys.path.remove(str(madar / "tests")))
        self.addCleanup(lambda: sys.path.remove(str(madar)))
        from test_lan_tls import _CERT, _KEY

        class DribbleHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "80")
                self.end_headers()
                for byte in b"{" + b"a" * 79:
                    try:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break
                    time.sleep(.22)

            def log_message(self, *_):
                pass

        cert = self.root / "test.crt"
        key = self.root / "test.key"
        cert.write_text(_CERT, encoding="ascii")
        key.write_text(_KEY, encoding="ascii")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert), str(key))
        server = ThreadingHTTPServer(("127.0.0.1", 0), DribbleHandler)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        runner = threading.Thread(target=server.serve_forever, daemon=True)
        runner.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), runner.join(timeout=2)))
        from lan import certificate_fingerprint
        client = MadarPinnedClient(self.vault,
            endpoint=f"https://127.0.0.1:{server.server_port}",
            cert_sha256=certificate_fingerprint(cert))
        began = time.monotonic()
        with patch("taraz_ecosystem_client._NETWORK_DEADLINE_SECONDS", 0.85):
            with self.assertRaises(EcosystemConnectionError):
                client._request("GET", "/integrations/v1/cards?limit=1",
                                token="mdv1_" + "t" * 64)
        elapsed = time.monotonic() - began
        self.assertLess(elapsed, 2.2)

    def test_real_company_session_lost_during_redeem_does_not_save_credential(self):
        from taraz_fresh_windows_workspace import stage_new_empty_root, open_fresh_company
        from taraz_ecosystem_client import MadarPinnedClient
        root = self.root / "Taraz"
        stage_new_empty_root(root)
        api, identity, token = open_fresh_company(root)
        try:
            payload = {"endpoint": "https://127.0.0.1:48370",
                       "certSha256": "a" * 64, "code": "ABCDEFGHIJKLM",
                       "manualConsent": True}
            def revoke_session_during_network(_client, _code):
                identity.logout(token)
                return {"installationId": "b" * 32,
                        "workspaceId": "c" * 32,
                        "issuedToken": "mdv1_" + "d" * 64}
            with patch.object(MadarPinnedClient, "redeem", revoke_session_during_network):
                with self.assertRaises(PermissionError):
                    api.tarazEcosystemPair(payload)
            from taraz_ecosystem_native_boundary import company_vault
            vault = company_vault(api.path.parent)
            self.assertEqual(vault.list_peers(), [])
        finally:
            try:
                identity.logout(token)
            except Exception:
                pass

    def test_network_operation_does_not_hold_accounting_global_lock(self):
        from taraz_fresh_windows_workspace import stage_new_empty_root, open_fresh_company
        from taraz_ecosystem_client import MadarPinnedClient
        root = self.root / "Taraz"
        stage_new_empty_root(root)
        api, identity, token = open_fresh_company(root)
        began = threading.Event()
        release = threading.Event()
        payload = {"endpoint": "https://127.0.0.1:48370",
                   "certSha256": "a" * 64, "code": "ABCDEFGHIJKLM",
                   "manualConsent": True}
        def paused_redeem(client, code):
            began.set()
            release.wait(timeout=2)
            raise EcosystemConnectionError("Simulated peer timeout")
        try:
            with patch.object(MadarPinnedClient, "redeem", paused_redeem):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    pending = executor.submit(api.tarazEcosystemPair, payload)
                    self.assertTrue(began.wait(timeout=1.8))
                    # The requesting thread is paused at the network boundary.
                    # The real local accounting mutex MUST be available now.
                    self.assertTrue(api._lock.acquire(blocking=False))
                    api._lock.release()
                    release.set()
                    with self.assertRaises(EcosystemConnectionError):
                        pending.result(timeout=2)
        finally:
            release.set()
            identity.logout(token)

    def test_native_counterparties_bridge_stays_company_scoped_and_read_only(self):
        from taraz_fresh_windows_workspace import stage_new_empty_root, open_fresh_company
        root = self.root / "Taraz"
        stage_new_empty_root(root)
        api, identity, token = open_fresh_company(root)
        ledger = api.path
        before = sha256(ledger.read_bytes()).digest()
        try:
            page = api.tarazEcosystemCounterpartiesSearch(
                {"query": "", "kind": "all", "limit": 10, "cursor": None})
            self.assertEqual(page["source"], "TARAZ")
            self.assertEqual(page["counterparties"], [])
            self.assertTrue(page["readOnly"])
            self.assertFalse(page["financialEventCreated"])
            result = api.tarazEcosystemCounterpartiesGet({"partyId": "unknown_party"})
            self.assertIsNone(result["party"])
            with self.assertRaises(ValueError):
                api.tarazEcosystemCounterpartiesSearch(
                    {"query": "", "kind": "all", "limit": 51, "cursor": None})
            self.assertEqual(sha256(ledger.read_bytes()).digest(), before)
        finally:
            identity.logout(token)
        with self.assertRaises(PermissionError):
            api.tarazEcosystemCounterpartiesSearch(
                {"query": "", "kind": "all", "limit": 10, "cursor": None})


if __name__ == "__main__":
    unittest.main()
