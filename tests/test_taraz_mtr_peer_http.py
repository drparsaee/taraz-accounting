"""Synthetic TLS loopback-only tests for the v2 metadata peer HTTP adapter.

The embedded PEM pair is a fixed, PUBLICLY KNOWN TEST-ONLY certificate/key.
NEVER use these bytes for any real service, real user or production transport.
Every file in these tests is located inside TemporaryDirectory; no real
service, LAN listener, official finance object or financial ledger is used.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import http.client
import json
from pathlib import Path
import socket
import sqlite3
import ssl
import tempfile
import threading
import time
import unittest

from taraz_mtr_peer_registry import PeerConfig, TarazPeerRegistry
from taraz_mtr_peer_http import (
    PeerHTTPConfigError, create_loopback_https_server,
)


_CERT = """-----BEGIN CERTIFICATE-----
MIIDPzCCAiegAwIBAgIUZEz5Wm4TfFZLrTeK4XkjFPMoqIkwDQYJKoZIhvcNAQEL
BQAwITEfMB0GA1UEAwwWbG9jYWxob3N0LXRlc3Rpbmctb25seTAeFw0yNjExMDkx
NjMzMDBaFw0zNjExMDYxNjMzMDBaMCExHzAdBgNVBAMMFmxvY2FsaG9zdC10ZXN0
aW5nLW9ubHkwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQDor3hS1+yD
dON0g4hOfsltkeHV/hq104bOdVruvQ99EfQ6ja8+pXnBYELJm/8qYjqHqEGojLJ8
Ws8khTQCFOvoClMi0k796WHmxCTdHnBUyFdOIl6ZhEW0rDOyX+Ws2JpfhaTYCiBu
FXfO1jWEaZ0bW7GZ1xXuJZs751m1XFIUrC2MHCJkuOQleztBiJKvtgZrESR0CLeC
QACKkir3HX8bP1cXTXykBlFUeu3p8nJH43oQN1qQ3E3yji3c2yMEn2inEEsLtHFf
Tly3h6HxexaSriD2RwMH4s0etjS1iO7KD9t6+Nkat5FLvgdPt2Rvg2mkXWZ/hFTG
GwRiT17Ys63/AgMBAAGjbzBtMB0GA1UdDgQWBBR78lv3xHb920zXHNEQZ0lDXO3f
UTAfBgNVHSMEGDAWgBR78lv3xHb920zXHNEQZ0lDXO3fUTAPBgNVHRMBAf8EBTAD
AQH/MBoGA1UdEQQTMBGHBH8AAAGCCWxvY2FsaG9zdDANBgkqhkiG9w0BAQsFAAOC
AQEARHFWPkTS5AtbKD9+k7gzuXO/x15L0y09JaJtpq3RNotulUM8WNpRK2gtV3a6
4Q0f8JjqWF+3sCWViltkqsNkw+mrQ14Ha1EHF37bq1CFw0rb0XE+4wHPHWMX7Ok9
plVwvlw0Kr+4aTxDrHhrF4VZ8PgBrwTeI9xJqDbzzgn+lYmEuit875j9Vl7+SHyw
UgoH9E0perp4ve+HhRqGKlFd0fMAVnkdBD9OihtJrK7GQVPfxSIOwNVTZPeToppI
aYNtykgHHudezHfN7ExIrN0Ft2ffO/3HXX7KY+zER0dT6RL+QBDuJxnS5lRoyyhv
PGgAOh754UwG9I9iwBcxvSFFpg==
-----END CERTIFICATE-----
"""
_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQDor3hS1+yDdON0
g4hOfsltkeHV/hq104bOdVruvQ99EfQ6ja8+pXnBYELJm/8qYjqHqEGojLJ8Ws8k
hTQCFOvoClMi0k796WHmxCTdHnBUyFdOIl6ZhEW0rDOyX+Ws2JpfhaTYCiBuFXfO
1jWEaZ0bW7GZ1xXuJZs751m1XFIUrC2MHCJkuOQleztBiJKvtgZrESR0CLeCQACK
kir3HX8bP1cXTXykBlFUeu3p8nJH43oQN1qQ3E3yji3c2yMEn2inEEsLtHFfTly3
h6HxexaSriD2RwMH4s0etjS1iO7KD9t6+Nkat5FLvgdPt2Rvg2mkXWZ/hFTGGwRi
T17Ys63/AgMBAAECggEAFkfjIi+p5qaVNy13KmkKmbLb6LVV0m5oXLGxHOY+qu/C
rq6thraqs4EntA17gA/64c2TR/P9DVpWtn0Iz2A4fLYsYsu3o6mq5cGHdCL7h6rN
bV5uJ44abKQGqUB0ijoNgjMWZ1eE5nWozMYHRuAkGqALoBsP7wdr128eUHcAJxls
3uVyWrDNIUlKyI3PM4wzYLevKkbRGZJCRQt6UF6P6McAIn1Dg3hVouEeSCHt+Weo
LsRm9O9PtpC6jn9IXPfZ1oRk8ahdx4QXD81v/AWqqtRi1V6C99cuxYHJ+rrQVHbj
QXl+vpwZLR0/47QwNc7NjlWDdlZgkF+fL3QiNvATKQKBgQD2AnQFlqyvW3uUqegD
MlB05dWAphVAIpJEwI4lv7j5SdxBI3GPA+0Ynpa0yyVy5Yif9JHBPbni2IDr53M4
O0x/kaUxLQdDev9A3ro21uA2mOeqd5d2BVKdQzKTi698R7FYRDpYs9z+V8EtTzqJ
famqky6B401/HbQgCpr+noaJiQKBgQDyIn9J0KG40FhfuEIc7UwoNxciaK6HvI0L
Q1Nenyf5RS7qFFr1khJdJp03IbBBEY7RxNB2vQtDEWKx3dV0G5NKZu9Qh/UE8J0V
Hs3gNBhEPxTSFh4mGAjuareuxHHuY1EAOzig6PNtEU0H+mgDZEame8Dmx0IJVUHO
5wpHv4oBRwKBgCbJmjtrV0zKssBszYz7eN4FgtUm2oDjMoauiXsAMIz1jUmj6fqv
lslj78UPppboA9OcfwKl1dIjaqhHNM5v4w7WCuKnA9cq5GX4+Ak/ddiF4TjqZDIS
gsUS3D2RL5j7wMV29HAZ48UiVu3q6QLWklK3pASMryJUr5rBsVBl9DZpAoGAQDdf
9M6tJVu0JGa0ugFBMmUx8IE80Gj0KymG4dBqBJURlSki2oAL+MJ17Zo0qX0jmISP
GP6YDwh8WVnQ84MgtBnKnFwCYnYB4wkRZsXKLcdhGTqeclHrhHevEV2uLaAPanVK
VnqRnLp66IPDtCqTBjJJ/aqY2+rNkjb6Jf8pdZ8CgYAQx69YPERC0DQAviatRFwN
TS25zYJhZmgd1kTLzGTZbbN+6u+rZ2I79cBw/MgYh9I9yVERyMDiQCpK1Zi4x+c+
5+EUfiftKO923FsoVDTSQLiXSCUKN6aFCbo0VqXiy59srShIzwx4Z+3WB/VktW5f
Du3ZUdoWZXP32mCUWqffUQ==
-----END PRIVATE KEY-----
"""

_DOMAIN = b"MTR-peer-envelope-v2\x00"
_BEARER = b"synthetic-bearer-never-for-production-1234567890"
_MEDIA = "application/vnd.mtr-peer+json"
_INTAKE = "/mtr/peer/v2/intake"
_QUERY = "/mtr/peer/v2/query"


def _raw(data):
    return json.dumps(
        data, separators=(",", ":"), sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")


def _wire(kind, payload, request_id, *, clock=None, secret=b"m" * 32,
          org="office-one", role="editor", key="madar-key", expires=60):
    if clock is None:
        clock = datetime.now(timezone.utc).replace(microsecond=0)
    body = {
        "protocol": "mtr-peer", "version": 2, "algorithm": "HMAC-SHA256",
        "kind": kind,
        "purpose": ("finance_review_request" if kind == "request"
                    else "receipt_lookup"),
        "organizationId": org, "senderId": "madar-host-1",
        "senderRole": "madar_sender", "actorRole": role,
        "audience": "taraz_peer", "keyId": key, "requestId": request_id,
        "issuedUtc": clock.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresUtc": (clock + timedelta(seconds=expires)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "payloadSha256": hashlib.sha256(_raw(payload)).hexdigest(),
        "payload": payload,
    }
    body["mac"] = hmac.new(
        secret, _DOMAIN + _raw(body), hashlib.sha256,
    ).hexdigest()
    return _raw(body)


def _subject(wire):
    record = json.loads(wire)
    return {
        "originalRequestId": record["requestId"],
        "originalPayloadSha256": record["payloadSha256"],
        "originalPurpose": "finance_review_request",
    }


class TarazPeerHTTPTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="taraz-https-pilot-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.certfile = self.directory / "fixture-cert.pem"
        self.keyfile = self.directory / "fixture-key.pem"
        self.certfile.write_text(_CERT, encoding="ascii")
        self.keyfile.write_text(_KEY, encoding="ascii")
        self.registry_path = self.directory / "metadata-only.sqlite3"
        config = PeerConfig(
            "office-one", "madar-host-1", "madar-key",
            "taraz-peer-1", "taraz-key",
            b"m" * 32, b"t" * 32,
        )
        self.registry = TarazPeerRegistry(self.registry_path, config)
        self.server = create_loopback_https_server(
            registry=self.registry, transport_bearer=_BEARER,
            certfile=self.certfile, keyfile=self.keyfile,
            opt_in=True, port=0, read_timeout_seconds=0.6,
        )
        self.port = self.server.server_port
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True,
        )
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.context = ssl.create_default_context(cafile=str(self.certfile))
        self.original_id = "a" * 32
        self.payload = {
            "schema": 1, "source": "madar",
            "taskId": "synthetic-2", "projectId": "project-synth",
            "title": "metadata only, no finance posting",
        }
        self.original_wire = _wire(
            "request", self.payload, self.original_id,
        )

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def connection(self):
        return http.client.HTTPSConnection(
            "127.0.0.1", self.port, context=self.context, timeout=5,
        )

    def call(self, *, path=_INTAKE, wire=None, bearer=_BEARER, method="POST",
             headers=None):
        if wire is None:
            wire = self.original_wire
        params = {
            "Authorization": "Bearer " + bearer.decode("ascii"),
            "Content-Type": _MEDIA,
            "Content-Length": str(len(wire)),
        }
        if headers:
            params.update(headers)
        connection = self.connection()
        try:
            connection.request(method, path, body=wire, headers=params)
            response = connection.getresponse()
            status = response.status
            content_type = response.getheader("Content-Type")
            result = response.read()
            return status, content_type, result, dict(response.getheaders())
        finally:
            connection.close()

    def counts(self):
        with closing(sqlite3.connect(self.registry_path)) as db:
            return tuple(
                db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("requests", "queries", "audit")
            )

    def test_tls_is_loopback_only_and_requires_opt_in(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertNotEqual(self.port, 0)
        with self.assertRaises(PeerHTTPConfigError):
            create_loopback_https_server(
                registry=self.registry, transport_bearer=_BEARER,
                certfile=self.certfile, keyfile=self.keyfile,
                opt_in=False,
            )
        with self.assertRaises(PeerHTTPConfigError):
            create_loopback_https_server(
                registry=self.registry, transport_bearer=b"short",
                certfile=self.certfile, keyfile=self.keyfile,
                opt_in=True,
            )
        with self.assertRaises(PeerHTTPConfigError):
            create_loopback_https_server(
                registry=self.registry, transport_bearer=_BEARER,
                certfile=self.certfile, keyfile=self.keyfile,
                opt_in=True, port=True,
            )

    def test_successful_intake_200_replay_no_finance_posting(self):
        first = self.call()
        self.assertEqual(first[0], 200)
        self.assertEqual(first[1], "application/json")
        data = json.loads(first[2])
        self.assertEqual(data["requestId"], self.original_id)
        self.assertTrue(data["received"])
        self.assertFalse(data["idempotent"])
        self.assertFalse(data["financialEventCreated"])
        self.assertEqual(self.call()[0], 200)
        self.assertTrue(json.loads(self.call()[2])["idempotent"])
        self.assertEqual(self.counts(), (1, 0, 1))
        with closing(sqlite3.connect(self.registry_path)) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertFalse({"ledger", "invoices", "payments", "official_receipts"} & tables)

    def test_query_unknown_and_received_both_signed_in_taraz_direction(self):
        query_id = "b" * 32
        query_wire = _wire(
            "query", _subject(self.original_wire), query_id,
        )
        status, media, wire, _ = self.call(path=_QUERY, wire=query_wire)
        self.assertEqual(status, 200)
        self.assertEqual(media, _MEDIA)
        envelope = json.loads(wire)
        self.assertEqual(envelope["payload"]["lookupStatus"], "unknown")
        self.assertEqual(envelope["kind"], "receipt")
        self.assertEqual(envelope["senderRole"], "taraz_peer")
        self.assertEqual(envelope["audience"], "madar_sender")
        signature = envelope.pop("mac")
        self.assertEqual(signature, hmac.new(
            b"t" * 32, _DOMAIN + _raw(envelope), hashlib.sha256,
        ).hexdigest())
        self.assertEqual(wire, _raw({**envelope, "mac": signature}))
        self.assertEqual(self.counts(), (0, 1, 0))
        self.assertEqual(self.call()[0], 200)
        new_query = _wire(
            "query", _subject(self.original_wire), "c" * 32,
        )
        status, media, reply, _ = self.call(path=_QUERY, wire=new_query)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(reply)["payload"]["lookupStatus"], "received")
        self.assertNotIn(b"not_received", reply)

    def test_missing_wrong_and_short_transport_bearer_401_no_body_needed(self):
        for token in (b"wrong-bearer-synthetic-1234567890123456789",
                      b"too-short", b"z" * 32):
            with self.subTest(token=token):
                response = self.call(bearer=token)
                self.assertEqual(response[0], 401)
                self.assertNotIn(token, response[2])
                self.assertNotIn(_BEARER, response[2])
        connection = self.connection()
        try:
            connection.putrequest("POST", _INTAKE)
            connection.putheader("Content-Type", _MEDIA)
            connection.putheader("Content-Length", "32768")
            connection.endheaders()  # No bearer and NO body whatsoever.
            reply = connection.getresponse()
            self.assertEqual(reply.status, 401)
            reply.read()
        finally:
            connection.close()
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_wrong_org_key_role_signature_and_expiry_403(self):
        earlier = datetime.now(timezone.utc).replace(
            microsecond=0) - timedelta(hours=1)
        invalid = (
            _wire("request", self.payload, self.original_id, org="other-office"),
            _wire("request", self.payload, self.original_id, key="wrong-key"),
            _wire("request", self.payload, self.original_id, role="viewer"),
            _wire("request", self.payload, self.original_id, secret=b"x" * 32),
            _wire("request", self.payload, self.original_id, clock=earlier),
            self.original_wire + b" ",
            self.original_wire.replace(b'"kind":"request",',
                                       b'"kind":"request","kind":"request",'),
        )
        for wire in invalid:
            with self.subTest(wire=wire[:30]):
                status, _, body, _ = self.call(wire=wire)
                self.assertEqual(status, 403, body)
                self.assertEqual(json.loads(body), {"error": "peer_denied"})
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_signed_kind_cannot_be_reused_on_other_route(self):
        subject = _subject(self.original_wire)
        signed_query = _wire("query", subject, "d" * 32)
        self.assertEqual(self.call(path=_INTAKE, wire=signed_query)[0], 403)
        self.assertEqual(self.call(path=_QUERY, wire=self.original_wire)[0], 403)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_conflicting_request_id_is_409_and_original_unchanged(self):
        self.assertEqual(self.call()[0], 200)
        other = _wire(
            "request", {**self.payload, "title": "conflicting"},
            self.original_id,
        )
        status, _, body, _ = self.call(wire=other)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body), {"error": "peer_conflict"})
        self.assertEqual(self.counts(), (1, 0, 1))

    def test_query_id_conflict_is_409_and_no_original_intake(self):
        first = _wire("query", _subject(self.original_wire), "b" * 32)
        self.assertEqual(self.call(path=_QUERY, wire=first)[0], 200)
        another = _wire("query", {
            "originalRequestId": "f" * 32,
            "originalPayloadSha256": "0" * 64,
            "originalPurpose": "finance_review_request",
        }, "b" * 32)
        self.assertEqual(self.call(path=_QUERY, wire=another)[0], 409)
        self.assertEqual(self.counts(), (0, 1, 0))

    def test_wrong_routes_querystrings_and_methods_have_no_side_effects(self):
        for route in (
            "/v2/request", "/v2/query", _INTAKE + "?trusted=true",
            _QUERY + "?kind=request", "/mtr/peer/v2/intake/",
            "http://127.0.0.1:" + str(self.port) + _INTAKE,
        ):
            with self.subTest(route=route):
                self.assertEqual(self.call(path=route)[0], 404)
        for method in ("GET", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"):
            with self.subTest(method=method):
                self.assertEqual(self.call(method=method)[0], 405)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_wrong_content_type_and_invalid_lengths_deny_before_body(self):
        for content_type in (
            "application/json", _MEDIA + "; charset=utf-8", "",
        ):
            self.assertEqual(self.call(headers={
                "Content-Type": content_type,
            })[0], 415)
        self.assertEqual(self.call(headers={"Content-Length": "32769"})[0], 413)
        for length in ("", "0", "-1", "1.0", "0100", "+1"):
            with self.subTest(length=length):
                self.assertEqual(self.call(headers={
                    "Content-Length": length,
                })[0], 411)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_host_and_transfer_encoding_and_forwarded_headers_denied(self):
        self.assertEqual(self.call(headers={
            "Host": "localhost:" + str(self.port),
        })[0], 400)
        for forbidden in ("Transfer-Encoding", "X-Verified-Transport-Peer",
                          "X-Forwarded-Host", "Content-Encoding", "Expect"):
            with self.subTest(header=forbidden):
                status, _, _, _ = self.call(headers={
                    forbidden: "chunked" if forbidden == "Transfer-Encoding"
                    else "true",
                })
                self.assertIn(status, (400, 417))
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_duplicate_host_authorization_length_or_content_type_400(self):
        for header, value in (
            ("Host", "127.0.0.1:" + str(self.port)),
            ("Authorization", "Bearer " + _BEARER.decode("ascii")),
            ("Content-Length", "12"), ("Content-Type", _MEDIA),
        ):
            with self.subTest(header=header):
                connection = self.connection()
                try:
                    connection.putrequest(
                        "POST", _INTAKE, skip_host=True,
                        skip_accept_encoding=True,
                    )
                    connection.putheader("Host", "127.0.0.1:" + str(self.port))
                    connection.putheader(
                        "Authorization", "Bearer " + _BEARER.decode("ascii"),
                    )
                    connection.putheader("Content-Type", _MEDIA)
                    connection.putheader(
                        "Content-Length", str(len(self.original_wire)),
                    )
                    connection.putheader(header, value)
                    connection.endheaders()  # No body, must reject headers first.
                    response = connection.getresponse()
                    self.assertEqual(response.status, 400)
                    response.read()
                finally:
                    connection.close()
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_explicit_body_timeout_and_incomplete_body_never_commit(self):
        connection = self.connection()
        try:
            connection.putrequest("POST", _INTAKE)
            connection.putheader("Authorization", "Bearer " + _BEARER.decode())
            connection.putheader("Content-Type", _MEDIA)
            connection.putheader("Content-Length", "123")
            connection.endheaders()  # Accepted headers, but do not send a body.
            before = time.monotonic()
            response = connection.getresponse()
            self.assertEqual(response.status, 408)
            self.assertLess(time.monotonic() - before, 3)
            response.read()
        finally:
            connection.close()
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_plaintext_http_is_never_processed(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as client:
            client.settimeout(3)
            client.sendall(
                b"POST " + _INTAKE.encode() +
                b" HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n"
            )
            try:
                response = client.recv(1024)
            except (ConnectionResetError, OSError):
                response = b""
        self.assertFalse(response.startswith(b"HTTP/1.1 200"))
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_slow_unauthenticated_tls_handshakes_do_not_stall_accept_loop(self):
        # Before admission hardening, get_request performed the handshake on
        # the single accept thread. Five idle TCP peers each waited 0.6 sec,
        # stalling the valid signed request for roughly three seconds.
        slow = []
        try:
            for _ in range(5):
                peer = socket.create_connection(("127.0.0.1", self.port), timeout=3)
                peer.settimeout(2)
                slow.append(peer)  # No TLS ClientHello and no bearer.
            time.sleep(0.1)
            started = time.monotonic()
            response = self.call()
            duration = time.monotonic() - started
            self.assertEqual(response[0], 200)
            self.assertLess(duration, 2.2,
                            "unauthenticated TLS handshakes blocked the accept loop")
            self.assertEqual(self.counts(), (1, 0, 1))
        finally:
            for peer in slow:
                peer.close()

    def test_registry_durability_no_http_auto_send_after_restart(self):
        self.assertEqual(self.call()[0], 200)
        reopened = TarazPeerRegistry(self.registry_path, self.registry.config)
        self.assertTrue(reopened.intake(
            self.original_wire, now=datetime.now(timezone.utc).replace(
                microsecond=0), verified_transport_peer=True,
        )["idempotent"])
        self.assertEqual(self.counts(), (1, 0, 1))

    def test_no_secrets_echoed_by_invalid_requests(self):
        bad_mac = _wire(
            "request", {"token": "private-not-to-be-echoed"}, "e" * 32,
            secret=b"r" * 32,
        )
        _, _, response, headers = self.call(wire=bad_mac)
        self.assertNotIn(b"private-not-to-be-echoed", response)
        self.assertNotIn(_BEARER, response)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
