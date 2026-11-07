"""Opt-in REST integration router for Madar Desk v1. NO listener is opened.

Prime must explicitly mount handle() on the existing HTTPS LAN server. Tokens
are separate from LAN login sessions, never persisted, and always resolved
against current LAN roles and project grants. No finance domain is exposed.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import hmac
import json
import re
import secrets
import ssl
import threading
import time
from urllib.parse import parse_qs, urlsplit


API_PREFIX = "/integrations/v1"
_KEY_RE = re.compile(r"mdv1_[A-Za-z0-9_-]{64}\Z", re.ASCII)
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_REV_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_REPLAY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}\Z", re.ASCII)
_READ_FIELDS = ("id", "projectId", "title", "status", "priority", "dueDate")
_RESPONSE_LIMIT = 200
_MAX_BODY = 8192
_MAX_KEYS = 512
_MAX_REPLAYS = 1024


@dataclass(frozen=True)
class IntegrationResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body)


class _Problem(Exception):
    def __init__(self, status, code):
        self.status = status
        self.code = code
        super().__init__(code)


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _response(status, payload):
    return IntegrationResponse(status, {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Madar-Integration-Version": "1",
    }, _json_bytes(payload))


def _strict_object(raw):
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("Duplicate JSON property")
            result[name] = value
        return result

    def invalid_constant(_):
        raise ValueError("Unsupported JSON numeric value")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=invalid_constant)
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise _Problem(400, "invalid_json") from exc
    if not isinstance(result, dict):
        raise _Problem(400, "invalid_json_object")
    return result


def _text_id(value):
    return isinstance(value, str) and bool(_ID_RE.fullmatch(value))


def _card_public(card):
    # Explicit projection. NEVER send full task JSON: it may contain cost,
    # checklist cost, budget, hidden finance fields or future sensitive keys.
    return {key: deepcopy(card[key]) for key in _READ_FIELDS if key in card}


def _project_public(project):
    return {key: deepcopy(project[key]) for key in ("id", "name") if key in project}


class IntegrationRouter:
    """In-process HTTPS-only router; caller owns HTTP parsing/socket lifecycle.

    issue_key/revoke_key are trusted Python-side admin operations, deliberately
    not mounted as REST endpoints. Integration credentials never grant LAN admin
    or financial domain access, regardless of the selected account's role.
    """

    def __init__(self, service):
        if not all(hasattr(service, attr) for attr in
                   ("lock", "account_for", "read_state", "write_state", "sessions", "users")):
            raise TypeError("Expected a running Madar LAN service")
        self.service = service
        self._lock = threading.RLock()
        self._keys = {}      # SHA256(secret) -> metadata
        self._replays = {}   # (key_id, idempotency_key) -> response + digest

    def _require_https(self):
        server = getattr(self.service, "server", None)
        sock = getattr(server, "socket", None)
        if not (getattr(self.service, "certfile", None)
                and getattr(self.service, "keyfile", None)
                and isinstance(sock, ssl.SSLSocket)):
            raise _Problem(503, "https_required")

    def _prune(self):
        now = time.time()
        self._keys = {key: item for key, item in self._keys.items()
                      if item["expiresAt"] > now}
        self._replays = {key: item for key, item in self._replays.items()
                         if item["expiresAt"] > now}
        if len(self._replays) > _MAX_REPLAYS:
            older = sorted(self._replays, key=lambda key: self._replays[key]["createdAt"])
            for key in older[:len(self._replays) - _MAX_REPLAYS]:
                del self._replays[key]

    def issue_key(self, admin_lan_token, username, *, permissions=("read",),
                  lifetime_seconds=3600):
        """Administrator opt-in. Secret is shown ONCE, kept hashed in RAM."""
        with self._lock, self.service.lock:
            self._require_https()
            admin = self.service.account_for(admin_lan_token)
            if admin["role"] != "admin":
                raise PermissionError("Only a LAN administrator can issue integration keys")
            if not isinstance(username, str) or username not in self.service.users:
                raise ValueError("Unknown account")
            if (not isinstance(permissions, (list, tuple, set, frozenset))
                    or not permissions or any(not isinstance(item, str) for item in permissions)
                    or not set(permissions).issubset({"read", "write"})):
                raise ValueError("Integration permissions must be read and/or write")
            if type(lifetime_seconds) is not int or not 60 <= lifetime_seconds <= 86400:
                raise ValueError("Key TTL must be between 60 and 86400 seconds")
            self._prune()
            if len(self._keys) >= _MAX_KEYS:
                raise RuntimeError("Integration key limit reached; revoke an old key")
            target = self.service.users[username]
            # Password reset/replacement immediately invalidates all old keys.
            password_revision = hashlib.sha256(target["passwordHash"].encode()).digest()
            raw = "mdv1_" + secrets.token_urlsafe(48)
            digest = hashlib.sha256(raw.encode("ascii")).digest()
            key_id = "ik_" + secrets.token_hex(12)
            expiry = time.time() + lifetime_seconds
            self._keys[digest] = {
                "keyId": key_id, "username": username,
                "permissions": frozenset(permissions),
                "passwordRevision": password_revision, "expiresAt": expiry,
            }
            return {"key": raw, "keyId": key_id, "expiresAt": int(expiry),
                    "permissions": sorted(set(permissions)), "username": username}

    def revoke_key(self, admin_lan_token, key_id):
        with self._lock, self.service.lock:
            admin = self.service.account_for(admin_lan_token)
            if admin["role"] != "admin":
                raise PermissionError("Only a LAN administrator can revoke integration keys")
            matches = [digest for digest, item in self._keys.items()
                       if item["keyId"] == key_id]
            if not matches:
                return False
            for digest in matches:
                del self._keys[digest]
            self._replays = {key: item for key, item in self._replays.items()
                             if key[0] != key_id}
            return True

    def _authorize(self, headers, permission):
        raw = headers.get("x-madar-integration-key")
        if not isinstance(raw, str) or not _KEY_RE.fullmatch(raw):
            raise _Problem(401, "authentication_required")
        entry = self._keys.get(hashlib.sha256(raw.encode("ascii")).digest())
        if entry is None or entry["expiresAt"] <= time.time():
            raise _Problem(401, "invalid_or_expired_key")
        account = self.service.users.get(entry["username"])
        if not account:
            raise _Problem(401, "invalid_or_expired_key")
        current_revision = hashlib.sha256(account["passwordHash"].encode()).digest()
        if not hmac.compare_digest(current_revision, entry["passwordRevision"]):
            raise _Problem(401, "invalid_or_expired_key")
        if permission not in entry["permissions"]:
            raise _Problem(403, "permission_denied")
        if permission == "write" and account["role"] == "viewer":
            raise _Problem(403, "permission_denied")
        return entry, account

    def _session(self, username):
        # Ephemeral INTERNAL LanService token: never returned to integration users.
        token = secrets.token_urlsafe(32)
        self.service.sessions[token] = (username, time.time() + 30)
        return token

    @staticmethod
    def _parse(method, path, headers, body):
        if method not in ("GET", "PATCH"):
            raise _Problem(405, "method_not_allowed")
        if not isinstance(path, str) or len(path) > 320:
            raise _Problem(400, "invalid_path")
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment or "%" in parsed.path:
            raise _Problem(400, "invalid_path")
        if not parsed.path.startswith(API_PREFIX + "/"):
            raise _Problem(404, "not_found")
        if not isinstance(headers, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) or len(k) > 120
                or len(v) > 1024 for k, v in headers.items()):
            raise _Problem(400, "invalid_headers")
        normalized = {}
        for key, value in headers.items():
            low = key.lower()
            if low in normalized:
                raise _Problem(400, "duplicate_headers")
            normalized[low] = value
        if not isinstance(body, bytes) or len(body) > _MAX_BODY:
            raise _Problem(413, "invalid_body_length")
        if method == "GET" and body:
            raise _Problem(400, "get_body_forbidden")
        if method == "PATCH" and normalized.get("content-type", "").split(";")[0].strip() != "application/json":
            raise _Problem(415, "json_required")
        query = parse_qs(parsed.query, keep_blank_values=True)
        if any(len(vals) != 1 for vals in query.values()):
            raise _Problem(400, "duplicate_query_parameter")
        return parsed.path[len(API_PREFIX):], query, normalized

    def handle(self, method, path, headers=None, body=b""):
        """Return IntegrationResponse without starting any HTTP listener.

        Integration key is accepted only when attached LanService currently has
        a live TLS server socket. Host must additionally mount this route on
        that *same* HTTPS listener; never proxy it to plaintext HTTP.
        """
        try:
            with self._lock, self.service.lock:
                self._require_https()
                suffix, query, normalized = self._parse(method, path, headers or {}, body)
                self._prune()
                permission = "write" if method == "PATCH" else "read"
                entry, account = self._authorize(normalized, permission)
                token = self._session(account["username"])
                try:
                    return self._dispatch(method, suffix, query, normalized, body,
                                          entry, account, token)
                finally:
                    self.service.sessions.pop(token, None)
        except _Problem as error:
            return _response(error.status, {"error": error.code, "version": 1})
        except PermissionError:
            return _response(403, {"error": "permission_denied", "version": 1})
        except ValueError:
            return _response(400, {"error": "invalid_request", "version": 1})
        except RuntimeError as exc:
            if str(exc).startswith("CONFLICT:"):
                return _response(409, {"error": "revision_conflict", "version": 1})
            return _response(500, {"error": "internal_error", "version": 1})
        except Exception:
            # HTTP callers must not receive internal tracebacks or cause the
            # existing LAN request-handler thread to terminate without JSON.
            return _response(500, {"error": "internal_error", "version": 1})

    def _dispatch(self, method, suffix, query, headers, body, entry, account, token):
        if suffix == "/me" and method == "GET":
            if query:
                raise _Problem(400, "invalid_query")
            return _response(200, {"version": 1, "user": {
                "username": account["username"], "role": account["role"]}})

        if suffix == "/projects" and method == "GET":
            if query:
                raise _Problem(400, "invalid_query")
            state = self.service.read_state(token)
            return _response(200, {"version": 1, "projects": [
                _project_public(item) for item in state["state"]["projects"]
            ]})

        state = self.service.read_state(token)
        cards = state["state"]["tasks"]
        if suffix == "/cards" and method == "GET":
            if set(query) - {"projectId", "limit"}:
                raise _Problem(400, "invalid_query")
            selected = query.get("projectId", [None])[0]
            if selected is not None and not _text_id(selected):
                raise _Problem(400, "invalid_query")
            raw_limit = query.get("limit", ["100"])[0]
            if not raw_limit.isascii() or not raw_limit.isdecimal():
                raise _Problem(400, "invalid_query")
            limit = int(raw_limit)
            if not 1 <= limit <= _RESPONSE_LIMIT:
                raise _Problem(400, "invalid_query")
            visible = [t for t in cards if selected is None or t["projectId"] == selected]
            return _response(200, {"version": 1, "revision": state["revision"],
                                   "cards": [_card_public(t) for t in visible[:limit]],
                                   "hasMore": len(visible) > limit})

        match = re.fullmatch(r"/cards/([A-Za-z0-9][A-Za-z0-9_.:-]{0,95})", suffix)
        if not match:
            raise _Problem(404, "not_found")
        if query:
            raise _Problem(400, "invalid_query")
        card = next((item for item in cards if item["id"] == match.group(1)), None)
        if card is None:
            # A missing card and a card hidden by project grants look identical.
            raise _Problem(404, "not_found")
        if method == "GET":
            return _response(200, {"version": 1, "revision": state["revision"],
                                   "card": _card_public(card)})

        replay_key = headers.get("idempotency-key")
        if not isinstance(replay_key, str) or not _REPLAY_RE.fullmatch(replay_key):
            raise _Problem(400, "idempotency_key_required")
        patch = _strict_object(body)
        if set(patch) != {"title", "revision"}:
            raise _Problem(400, "invalid_patch_fields")
        title = patch["title"]
        expected = patch["revision"]
        if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 160
                or any(ord(char) < 32 or ord(char) == 127 for char in title)
                or not isinstance(expected, str) or not _REV_RE.fullmatch(expected)):
            raise _Problem(400, "invalid_patch_fields")
        request_digest = hashlib.sha256(_json_bytes([method, suffix, patch])).digest()
        memo_key = (entry["keyId"], replay_key)
        memo = self._replays.get(memo_key)
        if memo is not None:
            if not hmac.compare_digest(memo["requestDigest"], request_digest):
                raise _Problem(409, "idempotency_key_conflict")
            # Role, project visibility, key expiry and password revocation were
            # already checked in this request, even when replaying a cached 200.
            return memo["response"]
        if state["revision"] != expected:
            raise _Problem(409, "revision_conflict")
        next_view = state["state"]
        for item in next_view["tasks"]:
            if item["id"] == card["id"]:
                item["title"] = title.strip()
                break
        saved = self.service.write_state(token, next_view, expected)
        updated = next(t for t in saved["state"]["tasks"] if t["id"] == card["id"])
        response = _response(200, {"version": 1, "revision": saved["revision"],
                                   "card": _card_public(updated)})
        self._replays[memo_key] = {"requestDigest": request_digest,
                                   "response": response,
                                   "createdAt": time.time(),
                                   "expiresAt": min(entry["expiresAt"], time.time() + 3600)}
        self._prune()
        return response


__all__ = ["API_PREFIX", "IntegrationResponse", "IntegrationRouter"]
