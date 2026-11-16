"""Opt-in, pinned HTTPS Taraz -> Madar *read-only* integration client.

No listener, background sync, SQL, finance mutation, automatic discovery, or
cloud transport. A native authenticated UI must obtain the expected TLS pin
from a trusted administrator and prompt for a one-use code before pair().
Tokens never leave the DPAPI vault except as an authenticated HTTPS header.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import socket
import ssl
import time
from urllib.parse import urlsplit

from taraz_ecosystem_credentials import TarazEcosystemCredentialVault


_PIN = re.compile(r"[a-f0-9]{64}\Z")
_CODE = re.compile(r"[A-Z2-7]{13}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_INSTALL = re.compile(r"[0-9a-f]{32}\Z")
_TOKEN = re.compile(r"mdv1_[A-Za-z0-9_-]{64}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_MAX_RESPONSE_BYTES = 262144
_NETWORK_DEADLINE_SECONDS = 8.0
_FIELDS = frozenset({"id", "projectId", "title", "status", "priority", "dueDate"})


class EcosystemConnectionError(RuntimeError):
    pass


def _unique_pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise EcosystemConnectionError("Duplicate field in peer response")
        value[key] = item
    return value


class MadarPinnedClient:
    """Existing Madar HTTPS LAN endpoint; no parallel services are started."""

    def __init__(self, vault: TarazEcosystemCredentialVault, *, endpoint: str,
                 cert_sha256: str, peer_id: str = "MADAR"):
        if type(vault) is not TarazEcosystemCredentialVault:
            raise TypeError("Trusted local credential vault required")
        if type(endpoint) is not str or len(endpoint) > 160:
            raise ValueError("Invalid Madar endpoint")
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "https" or parsed.username is not None
                or parsed.password is not None or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment or not parsed.hostname):
            raise ValueError("Expected an explicit pinned HTTPS host endpoint")
        try:
            address = ipaddress.ip_address(parsed.hostname)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Endpoint must be a numeric private IP address") from exc
        if address.version != 4 or not (address.is_loopback or address.is_private):
            raise ValueError("Only a private IPv4 or local loopback is supported")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("An explicit HTTPS port is required")
        if type(cert_sha256) is not str or not _PIN.fullmatch(cert_sha256):
            raise ValueError("Trusted full certificate SHA256 pin required")
        if type(peer_id) is not str or not _ID.fullmatch(peer_id):
            raise ValueError("Invalid integration peer name")
        self.vault = vault
        self.host = str(address)
        self.port = port
        self.endpoint = "https://" + self.host + ":" + str(self.port)
        self.cert_sha256 = cert_sha256
        self.peer_id = peer_id

    def _request(self, method, path, *, payload=None, token=None):
        if (method, path.split("?", 1)[0]) not in (
                ("POST", "/integrations/v1/pair"),
                ("GET", "/integrations/v1/cards")):
            raise EcosystemConnectionError("Unsupported Madar integration operation")
        if method == "GET" and payload is not None:
            raise ValueError("GET cannot contain a request body")
        if method == "GET" and re.fullmatch(
                r"/integrations/v1/cards\?limit=(?:[1-9][0-9]{0,2})\Z", path) is None:
            raise ValueError("Invalid bounded Madar card path")
        if method == "POST" and path != "/integrations/v1/pair":
            raise ValueError("Invalid peer pairing path")
        body = (json.dumps(payload, ensure_ascii=False,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
                if payload is not None else None)
        if body is not None and len(body) > 1024:
            raise ValueError("Pairing request exceeds size limit")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        # No OS trust anchor is assumed for a self-signed local host. The
        # administrator-supplied SHA256 pin is checked BEFORE sending secrets.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        deadline = time.monotonic() + _NETWORK_DEADLINE_SECONDS
        request_headers = [
            f"{method} {path} HTTP/1.1",
            f"Host: {self.host}:{self.port}",
            "Accept: application/json",
            "Accept-Encoding: identity",
            "Connection: close",
        ]
        if body is not None:
            request_headers += ["Content-Type: application/json",
                                "Content-Length: " + str(len(body))]
        if token is not None:
            if type(token) is not str or not _TOKEN.fullmatch(token):
                raise EcosystemConnectionError("Invalid stored peer credential")
            request_headers.append("X-Madar-Integration-Key: " + token)
        outgoing = ("\r\n".join(request_headers) + "\r\n\r\n").encode("ascii")
        if body is not None:
            outgoing += body
        if len(outgoing) > 4096:
            raise EcosystemConnectionError("Integration request exceeds transport limit")

        def receive(transport, size, deadline):
            left = deadline - time.monotonic()
            if left <= 0:
                raise EcosystemConnectionError("Integration network deadline exceeded")
            transport.settimeout(min(6.0, left))
            return transport.recv(size)

        try:
            with socket.create_connection((self.host, self.port), timeout=6.0) as underlying:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise EcosystemConnectionError("Integration network deadline exceeded")
                underlying.settimeout(min(6.0, left))
                with ctx.wrap_socket(underlying, server_hostname=None) as transport:
                    peer_certificate = transport.getpeercert(binary_form=True)
                    if (not peer_certificate or not hmac.compare_digest(
                            hashlib.sha256(peer_certificate).hexdigest(), self.cert_sha256)):
                        raise EcosystemConnectionError("Madar TLS certificate pin mismatch")
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise EcosystemConnectionError("Integration network deadline exceeded")
                    transport.settimeout(min(6.0, left))
                    transport.sendall(outgoing)
                    frame = b""
                    while b"\r\n\r\n" not in frame:
                        frame += receive(transport, 4096, deadline)
                        if len(frame) > 16384 or not frame:
                            raise EcosystemConnectionError("Invalid bounded HTTP response headers")
                    header_blob, raw = frame.split(b"\r\n\r\n", 1)
                    lines = header_blob.split(b"\r\n")
                    status_line = lines[0].decode("ascii")
                    status_match = re.fullmatch(r"HTTP/1\.[01] ([0-9]{3})(?: [^\r\n]*)?", status_line)
                    if status_match is None:
                        raise EcosystemConnectionError("Invalid HTTP status line")
                    status = int(status_match.group(1))
                    response_headers = {}
                    for line in lines[1:]:
                        if (b":" not in line or any(ch < 32 or ch == 127 for ch in line)):
                            raise EcosystemConnectionError("Invalid HTTP response header")
                        name, value = line.split(b":", 1)
                        name = name.decode("ascii").lower()
                        if name in response_headers:
                            raise EcosystemConnectionError("Duplicate peer response header")
                        response_headers[name] = value.strip().decode("latin-1")
                    raw_len = response_headers.get("content-length", "")
                    if (not raw_len.isascii() or not raw_len.isdecimal()
                            or len(raw_len) > 8):
                        raise EcosystemConnectionError("Verified Content-Length required")
                    length = int(raw_len)
                    if length > _MAX_RESPONSE_BYTES or len(raw) > length:
                        raise EcosystemConnectionError("Integration response exceeds size limit")
                    if response_headers.get("transfer-encoding") is not None:
                        raise EcosystemConnectionError("Chunked peer responses are unsupported")
                    while len(raw) < length:
                        piece = receive(transport, min(4096, length - len(raw)), deadline)
                        if not piece:
                            raise EcosystemConnectionError("Incomplete integration response")
                        raw += piece
                    if time.monotonic() > deadline:
                        raise EcosystemConnectionError("Integration network deadline exceeded")
            if response_headers.get("content-encoding") not in (None, "identity"):
                raise EcosystemConnectionError("Unsupported integration response encoding")
            if response_headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                raise EcosystemConnectionError("Unexpected integration response format")
            result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                                parse_constant=lambda _: (_ for _ in ()).throw(
                                    EcosystemConnectionError("Invalid numeric JSON constant")))
            if type(result) is not dict:
                raise EcosystemConnectionError("Invalid integration JSON response")
            if status not in (200, 201):
                raise EcosystemConnectionError(
                    "Integration peer rejected request, HTTP " + str(status))
            return status, result
        except (OSError, TimeoutError, ssl.SSLError,
                UnicodeError, ValueError) as exc:
            raise EcosystemConnectionError("Madar HTTPS request failed validation") from exc

    def redeem(self, code: str) -> dict:
        """Exchange code over pinned HTTPS, but do NOT persist a token yet.

        The native bridge must revalidate the admin session after network IO,
        then call commit_redeemed() under its company authorization lock.
        """
        if type(code) is not str or not _CODE.fullmatch(code):
            raise ValueError("Invalid one-time pairing code")
        installation_id = self.vault.installation_id()
        status, reply = self._request("POST", "/integrations/v1/pair", payload={
            "code": code, "product": "TARAZ", "installationId": installation_id})
        exact = {"version", "integrationCredential", "keyId", "workspaceId",
                 "expiresAt", "product", "installationId", "permissions"}
        if (status != 201 or set(reply) != exact or type(reply["version"]) is not int
                or reply["version"] != 1 or reply["product"] != "TARAZ"
                or reply["installationId"] != installation_id
                or type(reply["workspaceId"]) is not str
                or not _INSTALL.fullmatch(reply["workspaceId"])
                or type(reply["integrationCredential"]) is not str
                or not _TOKEN.fullmatch(reply["integrationCredential"])
                or type(reply["keyId"]) is not str
                or not re.fullmatch(r"ik_[a-f0-9]{24}", reply["keyId"])
                or type(reply["expiresAt"]) is not int
                or reply["expiresAt"] <= time.time()
                or type(reply["permissions"]) is not list
                or not reply["permissions"] or
                not set(reply["permissions"]).issubset({"read", "write"})):
            raise EcosystemConnectionError("Invalid peer-issued pairing response")
        return {"installationId": installation_id,
                "workspaceId": reply["workspaceId"],
                "issuedToken": reply["integrationCredential"]}

    def commit_redeemed(self, result: dict) -> dict:
        if (type(result) is not dict or
                set(result) != {"installationId", "workspaceId", "issuedToken"} or
                result["installationId"] != self.vault.installation_id() or
                type(result["workspaceId"]) is not str or
                not _INSTALL.fullmatch(result["workspaceId"]) or
                type(result["issuedToken"]) is not str or
                not _TOKEN.fullmatch(result["issuedToken"])):
            raise EcosystemConnectionError("Invalid redeemed peer credential")
        return self.vault.store_issued_credential(
            workspace_id=result["workspaceId"], peer_id=self.peer_id,
            cert_sha256=self.cert_sha256,
            issued_token=result["issuedToken"], endpoint=self.endpoint)

    def pair(self, code: str) -> dict:
        """For trusted backend callers without a separate session boundary."""
        return self.commit_redeemed(self.redeem(code))

    def cards(self, *, workspace_id: str, limit: int = 100) -> dict:
        """Retrieve only Madar-authorized card projection. No finance data."""
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid bounded card limit")
        if type(workspace_id) is not str or not _INSTALL.fullmatch(workspace_id):
            raise ValueError("Invalid paired workspace identity")
        token = self.vault.require_token(
            workspace_id=workspace_id, peer_id=self.peer_id,
            cert_sha256=self.cert_sha256)
        status, data = self._request(
            "GET", "/integrations/v1/cards?limit=" + str(limit), token=token)
        if (status != 200 or set(data) != {"version", "revision", "cards", "hasMore"}
                or type(data["version"]) is not int or data["version"] != 1
                or type(data["revision"]) is not str or not _SHA.fullmatch(data["revision"])
                or type(data["hasMore"]) is not bool
                or type(data["cards"]) is not list or len(data["cards"]) > limit):
            raise EcosystemConnectionError("Invalid or partial Madar card response")
        for card in data["cards"]:
            if (type(card) is not dict or not {"id", "projectId", "title"}.issubset(card)
                    or set(card) - _FIELDS
                    or any(type(card[key]) is not str for key in ("id", "projectId", "title"))
                    or not _ID.fullmatch(card["id"]) or not _ID.fullmatch(card["projectId"])):
                raise EcosystemConnectionError("Madar card is outside authorized projection")
        return {"source": "MADAR", "workspaceId": workspace_id,
                "revision": data["revision"], "cards": data["cards"],
                "hasMore": data["hasMore"], "complete": not data["hasMore"],
                "readOnly": True}


__all__ = ["MadarPinnedClient", "EcosystemConnectionError"]
