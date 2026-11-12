"""Explicitly opted-in, loopback-only HTTPS bridge for MTR peer v2 metadata.

Only POST /mtr/peer/v2/intake and POST /mtr/peer/v2/query are implemented. This bridge
authenticates a separately configured transport bearer inside TLS *before*
reading a request body, and only then asks the independently configured
TarazPeerRegistry to enforce canonical HMAC, identity, role, key and time.

No program entry point, background service, financial posting or Taraz
accounting integration exists here. Server construction requires opt-in and
the caller must explicitly run serve_forever().
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import socketserver
import ssl
import threading
import time

from taraz_mtr_peer_registry import PeerConflict, PeerDenied, TarazPeerRegistry


_MAX_BODY = 32768
_MAX_BEARER = 4096
_HOST = "127.0.0.1"
_ROUTES = frozenset({"/mtr/peer/v2/intake", "/mtr/peer/v2/query"})
_PEER_MEDIA = "application/vnd.mtr-peer+json"
_PROHIBITED_HEADERS = frozenset({
    "transfer-encoding", "te", "trailer", "upgrade", "expect",
    "proxy-authorization", "proxy-connection", "forwarded",
    "x-forwarded-for", "x-forwarded-host", "x-real-ip",
    "x-verified-transport-peer", "verified-transport-peer",
    "content-encoding",
})
_KNOWN_HEADERS = frozenset({
    "host", "authorization", "content-type", "content-length",
    "accept", "accept-encoding", "user-agent", "connection",
})


class PeerHTTPConfigError(ValueError):
    """Refuse unsafe or unconfigured server startup."""


class _LoopbackServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True
    request_queue_size = 8
    address_family = socket.AF_INET

    def server_bind(self):
        # Do not perform getfqdn/reverse DNS as HTTPServer normally does.
        socketserver.TCPServer.server_bind(self)
        self.server_name = _HOST
        self.server_port = self.server_address[1]

    def get_request(self):
        raw_socket, client_address = super().get_request()
        try:
            if client_address[0] != _HOST:
                raise PermissionError("non-loopback peer")
            # Accept must not perform the blocking TLS handshake: a single
            # unauthenticated slow client would stall the entire accept loop,
            # before process_request could apply the worker limit.
            raw_socket.settimeout(self.peer_read_timeout)
            return raw_socket, client_address
        except BaseException:
            raw_socket.close()
            raise

    def process_request(self, request, client_address):
        if not self.peer_slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.peer_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            # process_request reserves one of eight slots before this thread
            # starts. Both TLS handshake and HTTP body reads now consume the
            # SAME bounded slot and timeout. Never pass plaintext to Handler.
            tls_socket = self.peer_ssl_context.wrap_socket(
                request, server_side=True,
            )
            tls_socket.settimeout(self.peer_read_timeout)
            super().process_request_thread(tls_socket, client_address)
        except (ssl.SSLError, TimeoutError, OSError, ValueError):
            # Malformed, stalled or disconnected TLS peers have no registry
            # side effects and cannot hold the accept loop.
            pass
        finally:
            request.close()
            self.peer_slots.release()


class _Handler(BaseHTTPRequestHandler):
    server_version = "MTR-Peer-HTTPS-Pilot"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True

    def log_message(self, format, *args):
        # Never log Authorization, URLs, body contents, or peer identifiers.
        pass

    def _reply(self, status: int, payload: dict | bytes,
               content_type: str = "application/json"):
        if isinstance(payload, bytes):
            body = payload
        else:
            body = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            if status == 401:
                self.send_header("WWW-Authenticate", 'Bearer realm="mtr-peer"')
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except (OSError, ValueError):
            # A disconnected client must never change the recorded result.
            self.close_connection = True

    def send_error(self, code, message=None, explain=None):
        # Do not echo potentially sensitive malformed request lines/headers.
        self._reply(code, {"error": "invalid_http_request"})

    def handle_expect_100(self):
        # Prevent the HTTP stack from acknowledging an unauthenticated body.
        self._reply(417, {"error": "expect_not_supported"})
        return False

    def _no_method(self):
        self._reply(405, {"error": "method_not_allowed"})

    do_GET = _no_method
    do_HEAD = _no_method
    do_PUT = _no_method
    do_DELETE = _no_method
    do_PATCH = _no_method
    do_OPTIONS = _no_method
    do_TRACE = _no_method
    do_CONNECT = _no_method

    def _validate_headers(self):
        if self.request_version != "HTTP/1.1":
            self._reply(400, {"error": "http_1_1_required"})
            return None
        fields = {}
        for key, value in self.headers.raw_items():
            key = key.lower()
            if (key in fields or key not in _KNOWN_HEADERS
                    or key in _PROHIBITED_HEADERS or "\r" in value
                    or "\n" in value or "\x00" in value):
                self._reply(400, {"error": "invalid_or_duplicate_header"})
                return None
            fields[key] = value
        if any(header in fields for header in _PROHIBITED_HEADERS):
            self._reply(400, {"error": "forbidden_header"})
            return None
        if fields.get("host") != f"{_HOST}:{self.server.server_port}":
            self._reply(400, {"error": "invalid_host"})
            return None
        if not isinstance(self.connection, ssl.SSLSocket) or not self.connection.cipher():
            self._reply(403, {"error": "tls_required"})
            return None
        return fields

    def _authorized(self, headers):
        raw = headers.get("authorization", "")
        if not raw.startswith("Bearer "):
            self._reply(401, {"error": "unauthorized"})
            return False
        candidate = raw[7:]
        if not (32 <= len(candidate) <= _MAX_BEARER):
            self._reply(401, {"error": "unauthorized"})
            return False
        try:
            token = candidate.encode("ascii", "strict")
        except UnicodeError:
            self._reply(401, {"error": "unauthorized"})
            return False
        if any(b < 33 or b > 126 for b in token):
            self._reply(401, {"error": "unauthorized"})
            return False
        candidate_digest = hashlib.sha256(token).digest()
        if not hmac.compare_digest(candidate_digest, self.server.peer_bearer_digest):
            self._reply(401, {"error": "unauthorized"})
            return False
        return True

    def _read_bounded(self, length):
        remaining = length
        chunks = []
        deadline = time.monotonic() + self.server.peer_read_timeout
        while remaining:
            allowance = deadline - time.monotonic()
            if allowance <= 0:
                raise TimeoutError("request body deadline expired")
            self.connection.settimeout(max(0.001, min(
                self.server.peer_read_timeout, allowance,
            )))
            piece = self.rfile.read1(min(8192, remaining))
            if not piece:
                raise ValueError("incomplete request body")
            chunks.append(piece)
            remaining -= len(piece)
        return b"".join(chunks)

    def do_POST(self):
        self.close_connection = True
        headers = self._validate_headers()
        if headers is None:
            return
        # Authentication is deliberately BEFORE content validation/body read.
        if not self._authorized(headers):
            return
        if self.path not in _ROUTES:
            self._reply(404, {"error": "route_not_found"})
            return
        if headers.get("content-type") != _PEER_MEDIA:
            self._reply(415, {"error": "peer_content_type_required"})
            return
        length_text = headers.get("content-length", "")
        if not re.fullmatch(r"[1-9][0-9]*", length_text, re.ASCII):
            self._reply(411, {"error": "valid_content_length_required"})
            return
        if len(length_text) > 5 or int(length_text) > _MAX_BODY:
            self._reply(413, {"error": "body_too_large"})
            return
        try:
            wire = self._read_bounded(int(length_text))
        except (TimeoutError, socket.timeout):
            self._reply(408, {"error": "read_timeout"})
            return
        except (OSError, ValueError):
            self._reply(400, {"error": "incomplete_body"})
            return
        now = datetime.now(timezone.utc).replace(microsecond=0)
        try:
            if self.path == "/mtr/peer/v2/intake":
                result = self.server.peer_registry.intake(
                    wire, now=now,
                    verified_transport_peer=True,  # Set ONLY after TLS+bearer.
                )
                response = {
                    "requestId": result["requestId"],
                    "received": result["received"],
                    "idempotent": result["idempotent"],
                    "financialEventCreated": False,
                }
                self._reply(200, response)
            else:
                signed_receipt = self.server.peer_registry.query_receipt(
                    wire, now=now,
                    verified_transport_peer=True,  # Set ONLY after TLS+bearer.
                )
                if type(signed_receipt) is not bytes or len(signed_receipt) > _MAX_BODY:
                    raise PeerDenied("invalid signed receipt")
                self._reply(200, signed_receipt, content_type=_PEER_MEDIA)
        except PeerConflict:
            self._reply(409, {"error": "peer_conflict"})
        except (PeerDenied, PermissionError):
            self._reply(403, {"error": "peer_denied"})
        except Exception:
            # Do not echo database exceptions or secret-bearing details.
            self._reply(503, {"error": "peer_unavailable"})


def create_loopback_https_server(
    *,
    registry: TarazPeerRegistry,
    transport_bearer: bytes,
    certfile: Path,
    keyfile: Path,
    opt_in: bool = False,
    port: int = 0,
    read_timeout_seconds: float = 2.0,
) -> ThreadingHTTPServer:
    """Build a TLS listener restricted to 127.0.0.1; NEVER start it implicitly.

    The host must explicitly opt in, inject a separately provisioned 32+ byte
    bearer and trusted TarazPeerRegistry, and call server.serve_forever()
    itself. Server TLS alone does not authenticate a client: the bearer does.
    """
    if opt_in is not True:
        raise PeerHTTPConfigError("explicit opt-in required")
    if type(registry) is not TarazPeerRegistry:
        raise PeerHTTPConfigError("injected TarazPeerRegistry required")
    if (type(transport_bearer) is not bytes
            or not 32 <= len(transport_bearer) <= _MAX_BEARER
            or any(byte < 33 or byte > 126 for byte in transport_bearer)):
        raise PeerHTTPConfigError("independent printable ASCII bearer >=32 bytes required")
    if type(port) is not int or not 0 <= port <= 65535:
        raise PeerHTTPConfigError("invalid loopback port")
    if (type(read_timeout_seconds) not in (int, float)
            or not 0.1 <= read_timeout_seconds <= 15.0):
        raise PeerHTTPConfigError("invalid bounded read timeout")
    for name, path in (("certificate", certfile), ("private key", keyfile)):
        if (not isinstance(path, Path) or not path.is_absolute()
                or not path.is_file() or path.is_symlink()
                or getattr(path, "is_junction", lambda: False)()):
            raise PeerHTTPConfigError(f"trusted absolute {name} file required")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
    server = _LoopbackServer((_HOST, port), _Handler, bind_and_activate=True)
    server.peer_registry = registry
    server.peer_bearer_digest = hashlib.sha256(transport_bearer).digest()
    server.peer_ssl_context = context
    server.peer_read_timeout = float(read_timeout_seconds)
    server.peer_slots = threading.BoundedSemaphore(8)
    return server


__all__ = ["PeerHTTPConfigError", "create_loopback_https_server"]
