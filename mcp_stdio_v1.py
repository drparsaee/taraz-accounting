"""Bounded, read-only Madar MCP stdio adapter for the existing HTTPS Integration API.

No inbound listener, file operations, arbitrary HTTP targets, or mutation tools.
The integration key is supplied only through the child process environment.
"""
from __future__ import annotations

from collections import deque
from http.client import HTTPSConnection
import hashlib
import hmac
import ipaddress
import json
import os
import re
import ssl
import sys
import time
from urllib.parse import urlencode, urlsplit


MAX_FRAME = 65536
MAX_HTTP_RESPONSE = 262144
MAX_OUTPUT = 524288
MAX_CALLS_PER_MINUTE = 60
PROTOCOL = "2025-11-25"
LEGACY_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_KEY = re.compile(r"mdv1_[A-Za-z0-9_-]{64}\Z", re.ASCII)
_HEX = re.compile(r"[0-9a-fA-F]{64}\Z", re.ASCII)
_CARD_FIELDS = ("id", "projectId", "title", "status", "priority", "dueDate")
_PROJECT_FIELDS = ("id", "name")
_SERVER_INFO = {"name": "madar-desk-readonly", "version": "1.0.0"}


TOOLS = [
    {"name": "madar_list_projects", "description": "List projects visible to the authorized Madar account.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}},
    {"name": "madar_list_cards", "description": "List at most 200 visible cards, optionally filtered by project.",
     "inputSchema": {"type": "object", "properties": {
         "projectId": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 200}},
         "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}},
    {"name": "madar_get_card", "description": "Read one visible card by its Madar card ID.",
     "inputSchema": {"type": "object", "properties": {
         "cardId": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$"}},
         "required": ["cardId"], "additionalProperties": False},
     "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}},
]


class ProtocolProblem(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class APIProblem(Exception):
    def __init__(self, reason):
        self.reason = reason


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_member")
        result[key] = value
    return result


def _decode(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_object_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_number")))


def _encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _params(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProtocolProblem(-32602, "Invalid params")
    return value


def _validate_args(name, supplied):
    if not isinstance(supplied, dict):
        raise ProtocolProblem(-32602, "Invalid tool arguments")
    allowed = {"madar_list_projects": set(),
               "madar_list_cards": {"projectId", "limit"},
               "madar_get_card": {"cardId"}}
    if name not in allowed:
        raise ProtocolProblem(-32602, "Unknown tool")
    if set(supplied) - allowed[name]:
        raise ProtocolProblem(-32602, "Unexpected tool argument")
    for field in ("projectId", "cardId"):
        if field in supplied and (not isinstance(supplied[field], str)
                                  or not _ID.fullmatch(supplied[field])):
            raise ProtocolProblem(-32602, "Invalid identifier")
    if name == "madar_get_card" and "cardId" not in supplied:
        raise ProtocolProblem(-32602, "cardId required")
    if "limit" in supplied and (type(supplied["limit"]) is not int
                                or not 1 <= supplied["limit"] <= 200):
        raise ProtocolProblem(-32602, "limit must be between 1 and 200")
    return supplied


class PinnedIntegrationClient:
    """Read-only HTTPS client; certificate pin checked before sending secret."""

    def __init__(self, url, fingerprint, key):
        if not isinstance(url, str) or len(url) > 160:
            raise ValueError("invalid MCP URL")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.username is not None
                or parsed.password is not None or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError("MCP URL must be an HTTPS origin")
        try:
            address = ipaddress.ip_address(parsed.hostname or "")
            port = parsed.port
        except ValueError as exc:
            raise ValueError("MCP URL must use a private/loopback IP") from exc
        if not (address.is_private or address.is_loopback) or port is None or not 1 <= port <= 65535:
            raise ValueError("MCP URL must use a private/loopback IP and port")
        if not isinstance(fingerprint, str):
            raise ValueError("missing certificate pin")
        clean_pin = fingerprint.replace(":", "")
        if not (_HEX.fullmatch(clean_pin)
                and (len(fingerprint) == 64 or re.fullmatch(r"[A-Fa-f0-9]{2}(?::[A-Fa-f0-9]{2}){31}", fingerprint))):
            raise ValueError("invalid certificate pin")
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ValueError("invalid integration key")
        self.host, self.port = str(address), port
        self.fingerprint = bytes.fromhex(clean_pin)
        self.key = key

    def get(self, path):
        # Paths originate exclusively from _validate_args and a fixed allowlist.
        if not isinstance(path, str) or not path.startswith("/integrations/v1/") or len(path) > 320:
            raise APIProblem("invalid_request")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # Explicit pin is the trust anchor.
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        connection = HTTPSConnection(self.host, self.port, context=context, timeout=5)
        try:
            connection.connect()
            peer = connection.sock.getpeercert(binary_form=True)
            if not peer or not hmac.compare_digest(hashlib.sha256(peer).digest(), self.fingerprint):
                raise APIProblem("certificate_mismatch")
            connection.request("GET", path, headers={"X-Madar-Integration-Key": self.key,
                                                     "Accept": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                code = {401: "authentication_required", 403: "permission_denied",
                        404: "not_found"}.get(response.status, "integration_unavailable")
                raise APIProblem(code)
            if not response.getheader("Content-Type", "").lower().startswith("application/json"):
                raise APIProblem("invalid_response")
            raw = response.read(MAX_HTTP_RESPONSE + 1)
            if len(raw) > MAX_HTTP_RESPONSE:
                raise APIProblem("response_too_large")
            try:
                value = _decode(raw)
            except (UnicodeError, ValueError, RecursionError):
                raise APIProblem("invalid_response") from None
            if not isinstance(value, dict) or value.get("version") != 1:
                raise APIProblem("invalid_response")
            return value
        except APIProblem:
            raise
        except (OSError, ValueError, TimeoutError) as exc:
            raise APIProblem("integration_unavailable") from None
        finally:
            connection.close()


def _projection(items, fields, maximum):
    if not isinstance(items, list) or len(items) > maximum:
        raise APIProblem("invalid_response")
    if any(not isinstance(item, dict) for item in items):
        raise APIProblem("invalid_response")
    return [{field: item[field] for field in fields if field in item} for item in items]


def _safe_read(client, name, args):
    if name == "madar_list_projects":
        source = client.get("/integrations/v1/projects")
        return {"projects": _projection(source.get("projects"), _PROJECT_FIELDS, 10000)}
    if name == "madar_list_cards":
        query = {"limit": args.get("limit", 100)}
        if "projectId" in args:
            query["projectId"] = args["projectId"]
        source = client.get("/integrations/v1/cards?" + urlencode(query))
        if type(source.get("hasMore")) is not bool or not isinstance(source.get("revision"), str):
            raise APIProblem("invalid_response")
        return {"revision": source["revision"],
                "cards": _projection(source.get("cards"), _CARD_FIELDS, query["limit"]),
                "hasMore": source["hasMore"]}
    if name == "madar_get_card":
        source = client.get("/integrations/v1/cards/" + args["cardId"])
        item = source.get("card")
        if not isinstance(item, dict):
            raise APIProblem("invalid_response")
        return {"card": {field: item[field] for field in _CARD_FIELDS if field in item}}
    raise ProtocolProblem(-32602, "Unknown tool")


class MCPServer:
    def __init__(self, client):
        self.client = client
        self.initialized = False
        self.ready = False
        self.calls = deque()

    @staticmethod
    def _error(identifier, code, message):
        return {"jsonrpc": "2.0", "id": identifier,
                "error": {"code": code, "message": message}}

    @staticmethod
    def _success(identifier, result):
        return {"jsonrpc": "2.0", "id": identifier, "result": result}

    def dispatch(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._error(None, -32600, "Invalid Request")
        identifier = message.get("id")
        if "id" in message and (type(identifier) not in (int, str)
                                 or (isinstance(identifier, str) and len(identifier) > 128)):
            return self._error(None, -32600, "Invalid Request")
        method = message.get("method")
        if not isinstance(method, str) or len(method) > 80 or "result" in message or "error" in message:
            return self._error(identifier if "id" in message else None, -32600, "Invalid Request")
        if "id" not in message:
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            # Notifications never receive responses.
            return None
        try:
            params = _params(message.get("params"))
            if method == "initialize":
                if self.initialized or set(params) != {"protocolVersion", "capabilities", "clientInfo"}:
                    raise ProtocolProblem(-32602, "Invalid initialize request")
                if (not isinstance(params["protocolVersion"], str)
                        or not isinstance(params["capabilities"], dict)
                        or not isinstance(params["clientInfo"], dict)
                        or not all(isinstance(params["clientInfo"].get(k), str)
                                   for k in ("name", "version"))):
                    raise ProtocolProblem(-32602, "Invalid initialize request")
                self.initialized = True
                version = params["protocolVersion"]
                return self._success(identifier, {"protocolVersion": version if version in LEGACY_PROTOCOLS else PROTOCOL,
                    "capabilities": {"tools": {"listChanged": False}}, "serverInfo": _SERVER_INFO})
            if not self.ready:
                raise ProtocolProblem(-32000, "Server not initialized")
            if method == "ping":
                if params:
                    raise ProtocolProblem(-32602, "Invalid ping parameters")
                return self._success(identifier, {})
            if method == "tools/list":
                if params:
                    raise ProtocolProblem(-32602, "Pagination unsupported")
                return self._success(identifier, {"tools": TOOLS})
            if method == "tools/call":
                if set(params) - {"name", "arguments", "_meta"} or not isinstance(params.get("name"), str):
                    raise ProtocolProblem(-32602, "Invalid tools/call parameters")
                name = params["name"]
                args = _validate_args(name, params.get("arguments", {}))
                now = time.monotonic()
                while self.calls and self.calls[0] <= now - 60:
                    self.calls.popleft()
                if len(self.calls) >= MAX_CALLS_PER_MINUTE:
                    return self._success(identifier, {"content": [{"type": "text", "text": "rate_limited"}], "isError": True})
                self.calls.append(now)
                try:
                    data = _safe_read(self.client, name, args)
                    content = _encode(data).decode("utf-8")
                    if len(content.encode("utf-8")) > MAX_HTTP_RESPONSE:
                        raise APIProblem("response_too_large")
                    result = {"content": [{"type": "text", "text": content}], "isError": False}
                except APIProblem as exc:
                    result = {"content": [{"type": "text", "text": exc.reason}], "isError": True}
                return self._success(identifier, result)
            raise ProtocolProblem(-32601, "Method not found")
        except ProtocolProblem as exc:
            return self._error(identifier, exc.code, exc.message)


def serve(server, incoming=None, outgoing=None):
    incoming = sys.stdin.buffer if incoming is None else incoming
    outgoing = sys.stdout.buffer if outgoing is None else outgoing
    while True:
        line = incoming.readline(MAX_FRAME + 1)
        if not line:
            return
        if len(line) > MAX_FRAME or not line.endswith(b"\n"):
            response = MCPServer._error(None, -32700, "Frame too large or unterminated")
            outgoing.write(_encode(response) + b"\n")
            outgoing.flush()
            return  # Drop connection rather than risk an unbounded line drain.
        try:
            message = _decode(line)
        except (UnicodeError, ValueError, RecursionError):
            response = MCPServer._error(None, -32700, "Parse error")
        else:
            response = server.dispatch(message)
        if response is not None:
            raw = _encode(response)
            if len(raw) > MAX_OUTPUT:
                raw = _encode(MCPServer._error(response.get("id"), -32603, "Response too large"))
            try:
                outgoing.write(raw + b"\n")
                outgoing.flush()
            except BrokenPipeError:
                return


def main():
    try:
        client = PinnedIntegrationClient(os.environ.get("MADAR_MCP_URL"),
                                         os.environ.get("MADAR_MCP_CERT_SHA256"),
                                         os.environ.get("MADAR_MCP_INTEGRATION_KEY"))
    except (ValueError, TypeError):
        # Never include environment values or exception details in diagnostics.
        print("Madar MCP: invalid configuration", file=sys.stderr)
        return 2
    serve(MCPServer(client))
    return 0


if __name__ == "__main__":
    sys.exit(main())
