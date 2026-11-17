"""Strict mock-only provider QA + real current-user DPAPI in disposable QA root.

Never contacts the Internet, never uses a real API key or financial ledger.
Synthetic random strings are memory-only fixtures; all network calls mocked.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

import taraz_ai_online_credentials as vault_module
import taraz_ai_online_provider as provider
from taraz_ai_online_credentials import TarazOnlineAiCredentialVault, OnlineCredentialError


OPENAI = "https://api.openai.com/v1/chat/completions"
ANTHROPIC = "https://api.anthropic.com/v1/messages"
_PUBLIC_V4 = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP,
              "", ("8.8.8.8", 443))
_PRIVATE_V4 = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP,
               "", ("127.0.0.1", 443))


def _config(provider_name="openai", secret=None, **fields):
    return {
        "provider": provider_name,
        "endpoint": OPENAI if provider_name == "openai" else ANTHROPIC,
        "model": "explicit-user-model-1",
        # Synthetic ephemeral fixture, never resembling a provider-issued key
        "apiKey": secret or secrets.token_urlsafe(32),
        "inputUsdPerMillion": fields.get("inputUsdPerMillion", "2"),
        "outputUsdPerMillion": fields.get("outputUsdPerMillion", "4"),
    }


def _reply(provider_name="openai", *, text="A short generic paragraph."):
    if provider_name == "openai":
        return {"choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": text},
        }], "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    return {"stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 100, "output_tokens": 20}}


class OnlineProviderMockTests(unittest.TestCase):
    def setUp(self):
        # Simulation only. Production has no native release authority and
        # cannot execute health or billable generation.
        release = patch.object(provider, "_require_native_release", return_value=None)
        release.start()
        self.addCleanup(release.stop)
        # A typed inert host object; its privileged source is mocked.
        self.vault = object.__new__(TarazOnlineAiCredentialVault)
        self.record = _config()
        self.load = patch.object(TarazOnlineAiCredentialVault, "_trusted_config",
                                 side_effect=lambda: dict(self.record))
        self.load.start()
        self.addCleanup(self.load.stop)

    def _send(self, text="Write a pleasant greeting", **kwargs):
        return provider.generate(self.vault, text, manual_consent=True, **kwargs)

    def test_rejects_no_consent_before_vault_or_network(self):
        with patch.object(provider, "_post") as network:
            with patch.object(TarazOnlineAiCredentialVault,
                              "_trusted_config", side_effect=AssertionError("access")):
                for flag in (None, False, 1, "true"):
                    with self.subTest(flag=flag):
                        with self.assertRaises(PermissionError):
                            provider.generate(self.vault, "hi", manual_consent=flag)
        network.assert_not_called()

    def test_rejects_financial_and_secret_bearing_inputs_without_network(self):
        for prompt in ("Please send me the invoice", "bank payment", "دفترکل را بنویس",
                       "فاکتور فروش", "my password is 12345678",
                       "Bearer something-sensitive", "", "a" * 1001,
                       "bad\x00control"):
            with self.subTest(prompt=prompt[:30]):
                with patch.object(provider, "_post") as network:
                    with self.assertRaises(ValueError):
                        self._send(prompt)
                network.assert_not_called()

    def test_openai_payload_headers_and_explicit_model_no_tools(self):
        with patch.object(provider, "_post", return_value=_reply()) as post:
            result = self._send()
        cfg, payload = post.call_args.args
        self.assertEqual(cfg["endpoint"], OPENAI)
        self.assertEqual(payload["model"], "explicit-user-model-1")
        self.assertEqual(payload["max_completion_tokens"], 64)
        self.assertFalse(payload["stream"])
        self.assertEqual(set(payload), {"model", "stream", "max_completion_tokens",
                                        "messages"})
        self.assertEqual(payload["messages"][1]["content"], "Write a pleasant greeting")
        self.assertFalse(result["financialDecisionAuthority"])
        self.assertFalse(result["readCompanyData"])
        self.assertFalse(result["journalPosted"])
        self.assertFalse(result["savedToLedger"])
        self.assertFalse(result["providerEnforcesCostCap"])
        self.assertFalse(result["pricingVerifiedByProvider"])
        self.assertFalse(result["toolCallsEnabled"])
        self.assertEqual(result["estimatedCostUsd"], "0.000280")

    def test_anthropic_payload_headers_and_text_response(self):
        self.record = _config("anthropic")
        with patch.object(provider, "_post", return_value=_reply("anthropic")) as post:
            result = self._send()
        cfg, payload = post.call_args.args
        self.assertEqual(payload["max_tokens"], 64)
        self.assertEqual(payload["model"], self.record["model"])
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(provider._headers(cfg)["x-api-key"], self.record["apiKey"])
        self.assertNotIn("Authorization", provider._headers(cfg))
        self.assertEqual(result["provider"], "anthropic")
        self.assertEqual(result["response"], "A short generic paragraph.")

    def test_price_preflight_blocks_network_for_untrusted_or_large_assumptions(self):
        self.record = _config(inputUsdPerMillion="1000", outputUsdPerMillion="1000")
        with patch.object(provider, "_post") as network:
            with self.assertRaisesRegex(provider.OnlineAiError, "COST_CAP"):
                self._send()
        network.assert_not_called()
        for cap in ("1", "0.021", "0.0", "0.000001", "0.020001", None):
            with self.subTest(cap=cap):
                with patch.object(provider, "_post") as network:
                    with self.assertRaises(ValueError):
                        self._send(max_estimated_usd=cap)
                network.assert_not_called()

    def test_unverified_or_excessive_usage_refuses_output(self):
        responses = [
            {"choices": _reply()["choices"]},
            {**_reply(), "usage": {"prompt_tokens": 100, "unexpected": 1}},
            {**_reply(), "usage": {"prompt_tokens": -1, "completion_tokens": 2}},
            {**_reply(), "usage": {"prompt_tokens": True, "completion_tokens": 2}},
            {**_reply(), "usage": {"prompt_tokens": 100, "completion_tokens": 20001}},
        ]
        for body in responses:
            with self.subTest(body=body):
                with patch.object(provider, "_post", return_value=body):
                    with self.assertRaises(provider.OnlineAiError):
                        self._send()
        self.record = _config(inputUsdPerMillion="30", outputUsdPerMillion="30")
        body = {**_reply(), "usage": {"prompt_tokens": 1000, "completion_tokens": 50}}
        with patch.object(provider, "_post", return_value=body):
            with self.assertRaisesRegex(provider.OnlineAiError, "COST_CAP"):
                self._send()

    def test_unsupported_tools_truncation_or_empty_output_refused(self):
        for changes in (
                {"finish_reason": "length"},
                {"message": {"role": "assistant", "content": "Done", "tool_calls": []}},
                {"message": {"role": "assistant", "content": ""}},
                {"message": {"role": "assistant", "content": "x" * 4001}},
                {"message": {"role": "tool", "content": "not allowed"}},
        ):
            body = _reply()
            body["choices"][0].update(changes)
            with self.subTest(changes=str(changes)[:60]):
                with patch.object(provider, "_post", return_value=body):
                    with self.assertRaises(provider.OnlineAiError):
                        self._send()
        self.record = _config("anthropic")
        body = _reply("anthropic")
        body["content"].append({"type": "tool_use", "id": "abc"})
        with patch.object(provider, "_post", return_value=body):
            with self.assertRaises(provider.OnlineAiError):
                self._send()

    def test_endpoint_configuration_exact_match_only(self):
        for destination in (
                "http://api.openai.com/v1/chat/completions",
                "https://api.openai.com.evil.test/v1/chat/completions",
                "https://api.openai.com:444/v1/chat/completions",
                "https://api.openai.com/v1/chat/completions?to=http://169.254.169.254",
                "https://api.openai.com/v1/chat/completions#fragment",
                "https://127.0.0.1/v1/chat/completions",
                "https://169.254.169.254/latest/meta-data",
                "https://api.openai.com@127.0.0.1/v1/chat/completions",
        ):
            with self.subTest(destination=destination):
                self.record = {**_config(), "endpoint": destination}
                with patch.object(provider, "_post") as network:
                    with self.assertRaises(provider.OnlineAiError):
                        self._send()
                network.assert_not_called()

    def test_dns_rejects_all_nonpublic_and_mixed_destinations(self):
        for addresses in ([_PRIVATE_V4],
                          [_PUBLIC_V4, _PRIVATE_V4],
                          [(socket.AF_INET, socket.SOCK_STREAM,
                            socket.IPPROTO_TCP, "", ("169.254.169.254", 443))],
                          [(socket.AF_INET, socket.SOCK_STREAM,
                            socket.IPPROTO_TCP, "", ("10.0.0.1", 443))],
                          [(socket.AF_INET6, socket.SOCK_STREAM,
                            socket.IPPROTO_TCP, "", ("::1", 443, 0, 0))],
                          [(socket.AF_INET6, socket.SOCK_STREAM,
                            socket.IPPROTO_TCP, "", ("2002:0a00:0001::1", 443, 0, 0))],
                          []):
            with self.subTest(addresses=addresses):
                with patch.object(provider.socket, "getaddrinfo",
                                  return_value=addresses):
                    with self.assertRaisesRegex(provider.OnlineAiError, "DNS_"):
                        provider._resolve_public_ip("api.openai.com")
        self.assertFalse(provider._public_address("::ffff:8.8.8.8"))
        self.assertFalse(provider._public_address("127.0.0.1"))

    def test_public_resolver_pins_numeric_ip_once(self):
        with patch.object(provider.socket, "getaddrinfo",
                          return_value=[_PUBLIC_V4]) as dns:
            with patch.object(provider, "_PinnedHTTPSConnection") as tls:
                conn = provider._connect("openai")
        dns.assert_called_once_with("api.openai.com", 443,
                                    type=socket.SOCK_STREAM,
                                    proto=socket.IPPROTO_TCP)
        tls.assert_called_once_with("api.openai.com", "8.8.8.8", timeout=8)
        self.assertIs(conn, tls.return_value)

    def test_pinned_socket_connects_numeric_ip_and_uses_verified_host_sni(self):
        raw = Mock()
        with patch.object(provider.socket, "create_connection", return_value=raw) as dial:
            conn = provider._PinnedHTTPSConnection("api.openai.com", "8.8.8.8")
            wrapped = Mock()
            conn._context = Mock()
            conn._context.wrap_socket.return_value = wrapped
            conn.connect()
        dial.assert_called_once_with(("8.8.8.8", 443), timeout=8,
                                     source_address=None)
        conn._context.wrap_socket.assert_called_once_with(
            raw, server_hostname="api.openai.com")
        self.assertIs(conn.sock, wrapped)

    def test_status_is_local_only_without_network_or_key(self):
        info = {"configured": True, "provider": "openai", "model": "chosen",
                "endpoint": OPENAI, "generation": 1}
        with patch.object(TarazOnlineAiCredentialVault, "metadata",
                          return_value=info), patch.object(provider, "_connect") as network:
            status = provider.configured_status(self.vault)
        network.assert_not_called()
        self.assertFalse(status["remoteRequestMade"])
        self.assertFalse(status["credentialsVerified"])
        self.assertFalse(status["providerHealthVerified"])

    def test_health_requires_consent_and_configuration_no_http_or_key(self):
        with patch.object(provider, "_connect") as conn:
            with self.assertRaises(PermissionError):
                provider.health_check(self.vault, manual_consent=False)
            conn.assert_not_called()
            info = provider.health_check(self.vault, manual_consent=True)
        self.assertTrue(info["tlsReachable"])
        self.assertFalse(info["credentialsVerified"])
        conn.return_value.connect.assert_called_once_with()
        conn.return_value.request.assert_not_called()
        self.record = {}
        with patch.object(provider, "_connect") as conn:
            with self.assertRaises(provider.OnlineAiError):
                provider.health_check(self.vault, manual_consent=True)
            conn.assert_not_called()

    def test_redirect_never_followed_and_error_redacted(self):
        connection = Mock()
        response = Mock()
        response.status = 307
        response.getheader.return_value = "https://127.0.0.1/metadata"
        connection.getresponse.return_value = response
        with patch.object(provider, "_connect", return_value=connection) as connect:
            with self.assertRaisesRegex(provider.OnlineAiError, "REDIRECT") as caught:
                provider._post(self.record, {"model": "chosen"})
        connection.close.assert_called_once()
        self.assertNotIn("127.0.0.1", str(caught.exception))
        self.assertEqual(connection.request.call_count, 1)
        self.assertEqual(connection.request.call_args.args[0], "POST")
        self.assertEqual(connection.request.call_args.args[1],
                         "/v1/chat/completions")

    def test_http_non200_hides_body_key_and_remote_message(self):
        secret = self.record["apiKey"]
        connection = Mock()
        response = Mock()
        response.status = 401
        response.read.return_value = (secret + " provider message").encode("ascii")
        connection.getresponse.return_value = response
        with patch.object(provider, "_connect", return_value=connection):
            with self.assertRaises(provider.OnlineAiError) as caught:
                provider._post(self.record, {"model": "chosen"})
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn("provider message", str(caught.exception))
        response.read.assert_not_called()
        connection.close.assert_called_once()

    def test_response_size_mime_and_invalid_json_fail_closed(self):
        for content_type, payload in (
                ("text/html", b"<html>secret</html>"),
                ("application/json", b"x" * 65537),
                ("application/json", b"not json"),
        ):
            with self.subTest(content_type=content_type, size=len(payload)):
                connection = Mock()
                response = Mock(status=200)
                response.status = 200
                response.getheader.side_effect = lambda k, default=None: (
                    content_type if k == "Content-Type" else default)
                response.read.return_value = payload
                connection.getresponse.return_value = response
                with patch.object(provider, "_connect", return_value=connection):
                    with self.assertRaises(provider.OnlineAiError):
                        provider._post(self.record, {"model": "chosen"})
                connection.close.assert_called_once()

    def test_invalid_content_encoding_is_rejected_before_read(self):
        connection = Mock()
        response = Mock(status=200)
        response.status = 200
        response.getheader.side_effect = lambda name, default=None: {
            "Content-Type": "application/json",
            "Content-Encoding": None,
        }.get(name, default)
        connection.getresponse.return_value = response
        with patch.object(provider, "_connect", return_value=connection):
            with self.assertRaisesRegex(provider.OnlineAiError, "RESPONSE"):
                provider._post(self.record, {"model": "chosen"})
        response.read.assert_not_called()

    def test_transport_socket_failure_is_redacted(self):
        secret = self.record["apiKey"]
        with patch.object(provider, "_connect",
                          side_effect=OSError("private " + secret + " path")):
            with self.assertRaises(provider.OnlineAiError) as caught:
                provider._post(self.record, {"model": "chosen"})
        self.assertEqual(str(caught.exception), "PROVIDER_TRANSPORT_OR_RESPONSE_FAILURE")
        self.assertNotIn(secret, str(caught.exception))


class OnlineReleaseGateTests(unittest.TestCase):
    def test_default_release_gate_blocks_direct_python_calls_no_network(self):
        vault = object.__new__(TarazOnlineAiCredentialVault)
        with patch.object(provider, "_connect",
                          side_effect=AssertionError("external networking forbidden")), \
             patch.object(TarazOnlineAiCredentialVault, "_trusted_config",
                          side_effect=AssertionError("vault should not be accessed")):
            for _ in range(20):
                with self.assertRaisesRegex(PermissionError, "TRANSMISSION_DISABLED"):
                    provider.generate(vault, "Hello", manual_consent=True)
                with self.assertRaisesRegex(PermissionError, "TRANSMISSION_DISABLED"):
                    provider.health_check(vault, manual_consent=True)


@unittest.skipUnless(os.name == "nt", "Requires actual current-user Windows DPAPI")
class WindowsOnlineVaultTests(unittest.TestCase):
    def setUp(self):
        output = Path(__file__).resolve().parent / "output"
        self.assertTrue(output.is_dir())
        tmp = tempfile.TemporaryDirectory(prefix="taraz-online-ai-qa-20261116-",
                                          dir=output)
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "dedicated-online-credentials"
        self.root.mkdir()
        self.vault = TarazOnlineAiCredentialVault(self.root)
        self.secret = secrets.token_urlsafe(48)

    def _store(self):
        self.vault.configure(provider="openai", endpoint=OPENAI,
                             model="chosen-model", api_key=self.secret,
                             input_usd_per_million="2",
                             output_usd_per_million="4")

    def test_actual_dpapi_seals_key_persists_metadata_and_clear(self):
        self.vault.initialize()
        self._store()
        doc = (self.root / vault_module._FILE).read_bytes()
        self.assertNotIn(self.secret.encode(), doc)
        self.assertNotIn(b"apiKey", doc)
        metadata = TarazOnlineAiCredentialVault(self.root).metadata()
        self.assertTrue(metadata["configured"])
        self.assertEqual(metadata["model"], "chosen-model")
        self.assertNotIn("apiKey", metadata)
        self.assertEqual(self.vault._trusted_config()["apiKey"], self.secret)
        self.vault.clear()
        self.assertFalse(self.vault.metadata()["configured"])
        self.assertNotIn(self.secret.encode(), (self.root / vault_module._FILE).read_bytes())
        with self.assertRaises(OnlineCredentialError):
            self.vault._trusted_config()

    def test_mutated_ciphertext_fails_closed(self):
        self.vault.initialize()
        self._store()
        path = self.root / vault_module._FILE
        record = json.loads(path.read_bytes())
        buf = bytearray(base64.b64decode(record["sealed"]))
        buf[len(buf) // 2] ^= 1
        record["sealed"] = base64.b64encode(buf).decode("ascii")
        path.write_bytes(json.dumps(record, sort_keys=True, separators=(",", ":")).encode())
        with self.assertRaises(OnlineCredentialError):
            self.vault._trusted_config()

    def test_replaced_vault_file_symlink_fails_closed(self):
        self.vault.initialize()
        self._store()
        path = self.root / vault_module._FILE
        outside = self.base / "synthetic-outside"
        path.rename(outside)
        try:
            os.symlink(outside, path)
        except (OSError, NotImplementedError):
            self.skipTest("Windows symlink privilege unavailable")
        with self.assertRaises(OnlineCredentialError):
            self.vault.metadata()

    def test_other_root_cannot_decrypt_original_windows_principal_ciphertext(self):
        self.vault.initialize()
        self._store()
        other = self.base / "other-dedicated-root"
        other.mkdir()
        shutil.copy2(self.root / vault_module._FILE, other / vault_module._FILE)
        # A copied lock is not a substitute for the original DPAPI path entropy.
        shutil.copy2(self.root / vault_module._LOCK, other / vault_module._LOCK)
        with self.assertRaises(OnlineCredentialError):
            TarazOnlineAiCredentialVault(other).metadata()

    def test_missing_dpapi_key_fails_closed(self):
        self.vault.initialize()
        self._store()
        with patch.object(vault_module, "_unprotect",
                          side_effect=RuntimeError("different Windows user")):
            with self.assertRaises(OnlineCredentialError):
                self.vault.metadata()

    def test_invalid_endpoint_and_duplicate_initialization_refuse_write(self):
        self.vault.initialize()
        before = (self.root / vault_module._FILE).read_bytes()
        with self.assertRaises(OnlineCredentialError):
            self.vault.configure(provider="openai", endpoint="https://127.0.0.1",
                                 model="chosen", api_key=self.secret,
                                 input_usd_per_million="2",
                                 output_usd_per_million="4")
        self.assertEqual((self.root / vault_module._FILE).read_bytes(), before)
        with self.assertRaises(OnlineCredentialError):
            self.vault.initialize()
        self.assertEqual((self.root / vault_module._FILE).read_bytes(), before)

    def test_vault_is_dedicated_and_fails_closed_on_symlink_or_extra_file(self):
        self.vault.initialize()
        self._store()
        extra = self.root / "synthetic-ledger-marker.sqlite3"
        extra.write_bytes(b"not a real ledger")
        with self.assertRaises(OnlineCredentialError):
            self.vault.metadata()
        self.assertEqual(extra.read_bytes(), b"not a real ledger")

    def test_actual_windows_file_acl_does_not_inherit(self):
        import subprocess
        self.vault.initialize()
        self._store()
        for path in self.root.iterdir():
            out = subprocess.run(["icacls", str(path)], capture_output=True,
                                 text=True, check=True, timeout=15)
            self.assertNotIn("(I)", out.stdout)

    def test_status_without_configuration_never_issues_network(self):
        self.vault.initialize()
        with patch.object(provider, "_connect") as conn:
            with self.assertRaisesRegex(PermissionError, "TRANSMISSION_DISABLED"):
                provider.health_check(self.vault, manual_consent=True)
            conn.assert_not_called()

    def test_failed_atomic_replace_keeps_old_key(self):
        self.vault.initialize()
        self._store()
        before = (self.root / vault_module._FILE).read_bytes()
        with patch.object(vault_module.os, "replace",
                          side_effect=OSError("synthetic atomic failure")):
            with self.assertRaises(OSError):
                self.vault.configure(provider="openai", endpoint=OPENAI,
                                     model="next-model", api_key=secrets.token_urlsafe(48),
                                     input_usd_per_million="2",
                                     output_usd_per_million="4")
        self.assertEqual((self.root / vault_module._FILE).read_bytes(), before)
        self.assertEqual(self.vault._trusted_config()["apiKey"], self.secret)


if __name__ == "__main__":
    unittest.main()
