"""Bounded, explicitly authorized, read-only Madar dashboard snapshots for Taraz.

Madar remains the authority.  Explicit local mode reads only the same Windows
user's fixed %APPDATA%/MadarDesk/tasks.json snapshot and warns it may be stale;
this is not host authentication or authoritative LAN read. Explicit host mode
uses Madar's authenticated /api/state, whose server-side view_for applies the
logged-in user's project permissions. No SQLite, ProgramData, identity registry,
or credential cache is ever opened.

The opt-in 'all' scope means *all supported non-financial projections*, NOT a
raw copy of every Madar datum.  Financial books, attachments, accounts, tokens,
passwords, and arbitrary plugin data are deliberately excluded.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from http.client import HTTPSConnection
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import stat
from urllib.parse import urlsplit


class MadarReadError(ValueError):
    """Fail closed without returning server-supplied secrets/error bodies."""


_MAX_JSON_BYTES = 12 * 1024 * 1024
_MAX_ITEMS_PER_COLLECTION = 50000
_MAX_LIMIT = 200
_MAX_OFFSET = 50000
_FINGERPRINT = re.compile(r"[a-fA-F0-9]{64}\Z")
_USERNAME = re.compile(r"[a-zA-Z0-9._-]{3,40}\Z")
_SCOPES = ("summary", "all", "projects", "tasks", "boards", "workspaces", "templates")
_FIELDS = {
    "projects": ("id", "name", "title", "description", "status", "color"),
    "tasks": ("id", "projectId", "boardId", "title", "summary",
              "description", "status", "priority", "dueDate", "createdAt", "updatedAt"),
    "boards": ("id", "projectId", "workspaceId", "name", "title", "color"),
    "workspaces": ("id", "name", "title", "description"),
    "templates": ("id", "boardId", "name", "title", "description"),
}
_IDENTITY_FIELDS = frozenset(("id", "projectId", "boardId", "workspaceId"))


def _network_config(connection):
    """Reject arbitrary web origins, plaintext or implicit credential discovery."""
    if type(connection) is not dict or set(connection) != {
            "url", "fingerprint", "username", "password"}:
        raise MadarReadError("Explicit host URL, fingerprint and credentials required")
    url, pin = connection["url"], connection["fingerprint"]
    username, password = connection["username"], connection["password"]
    if (type(url) is not str or len(url) > 120 or type(pin) is not str or
            not _FINGERPRINT.fullmatch(pin) or type(username) is not str or
            not _USERNAME.fullmatch(username) or type(password) is not str or
            not 10 <= len(password) <= 4096):
        raise MadarReadError("Invalid Madar host authorization parameters")
    try:
        target = urlsplit(url)
        address = ipaddress.ip_address(target.hostname or "")
        port = target.port
    except (ValueError, TypeError) as exc:
        raise MadarReadError("An explicit private HTTPS IP and port are required") from exc
    if (target.scheme != "https" or not target.hostname or port is None or
            target.username is not None or target.password is not None or
            target.path not in ("", "/") or target.query or target.fragment or
            not 1 <= port <= 65535 or
            not (address.is_private or address.is_loopback) or
            address.is_multicast or address.is_unspecified or
            address.is_link_local):
        raise MadarReadError("Only a private pinned HTTPS Madar host is supported")
    return (str(address), port, bytes.fromhex(pin), username, password,
            f"https://{target.netloc}")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MadarReadError("Duplicate host response key")
        result[key] = value
    return result


def _reject_nonfinite(_value):
    raise MadarReadError("Nonfinite value in host response")


def _pinned_json(host, port, pin, method, path, *, payload=None, token=None):
    """Check TLS leaf SHA-256 BEFORE sending even the login HTTP request.

    A fresh connection per request is used; bearer tokens/passwords are neither
    persisted nor forwarded to another hostname. No redirect is followed.
    """
    if method not in ("GET", "POST") or path not in ("/api/login", "/api/state"):
        raise MadarReadError("Only Madar login/state read routes are permitted")
    if (method, path) not in (("POST", "/api/login"), ("GET", "/api/state")):
        raise MadarReadError("Invalid method for Madar route")
    if type(token) is not str and path == "/api/state":
        raise MadarReadError("Authenticated Madar session required")
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(body) > 8192:
            raise MadarReadError("Login payload too large")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # mandatory pin verified before request
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = HTTPSConnection(host, port, timeout=8, context=context)
    try:
        connection.connect()
        leaf = connection.sock.getpeercert(binary_form=True)
        if not leaf or not hmac.compare_digest(hashlib.sha256(leaf).digest(), pin):
            raise MadarReadError("Madar host TLS certificate fingerprint mismatch")
        headers = {"Accept": "application/json", "Connection": "close"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        declared = response.getheader("Content-Length")
        if declared is not None and (not declared.isdecimal() or
                                     int(declared) > _MAX_JSON_BYTES):
            raise MadarReadError("Madar host response exceeds byte limit")
        if response.status != 200:
            raise MadarReadError("Madar host authorization/read failed")
        if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise MadarReadError("Unexpected Madar host response type")
        raw = response.read(_MAX_JSON_BYTES + 1)
        if not 1 <= len(raw) <= _MAX_JSON_BYTES:
            raise MadarReadError("Madar host response exceeds byte limit")
        try:
            result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                                parse_constant=_reject_nonfinite)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise MadarReadError("Malformed Madar host JSON response") from exc
        if type(result) is not dict:
            raise MadarReadError("Unexpected Madar host JSON structure")
        return result
    finally:
        connection.close()


def _validate_paging(scope, offset, limit):
    if scope not in _SCOPES or type(scope) is not str:
        raise MadarReadError("Unsupported Madar dashboard scope")
    if type(offset) is not int or not 0 <= offset <= _MAX_OFFSET:
        raise MadarReadError("Invalid Madar data offset")
    if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
        raise MadarReadError("Madar data page must contain 1 to 200 entries")


def _clean_record(record, kind):
    if type(record) is not dict:
        raise MadarReadError("Invalid Madar record from authenticated host")
    output = {}
    for key in _FIELDS[kind]:
        value = record.get(key)
        # Only an allowlisted set of flat, bounded fields. No nested data,
        # passwords, attachments, financial amounts, tokens, or opaque blobs.
        if type(value) is str:
            cap = 180 if key in _IDENTITY_FIELDS else 2048
            if len(value) > cap:
                output[key] = value[:cap]
            else:
                output[key] = value
        elif type(value) in (int, bool) and key not in _IDENTITY_FIELDS:
            output[key] = value
    if type(output.get("id")) is not str or not output["id"]:
        raise MadarReadError("Madar record missing stable identifier")
    return output


def _validate_host_result(login, result):
    if type(login) is not dict or type(login.get("token")) is not str or not (
            20 <= len(login["token"]) <= 4096):
        raise MadarReadError("Madar login returned no authenticated session")
    user = login.get("user")
    if (type(user) is not dict or type(user.get("username")) is not str or
            not user["username"] or user.get("role") not in ("viewer", "editor", "admin")):
        raise MadarReadError("Madar account role unavailable")
    state, revision = result.get("state"), result.get("revision")
    result_user = result.get("user")
    if (type(state) is not dict or type(revision) is not str or
            not re.fullmatch(r"[a-f0-9]{64}", revision) or
            type(result_user) is not dict or
            result_user.get("username") != user.get("username") or
            result_user.get("role") != user.get("role") or
            result_user.get("projects") != user.get("projects")):
        raise MadarReadError("Madar host principal/snapshot mismatch")
    try:
        raw = json.dumps(state, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise MadarReadError("Madar state cannot be verified") from exc
    if len(raw) > _MAX_JSON_BYTES or not hmac.compare_digest(
            hashlib.sha256(raw).hexdigest(), revision):
        raise MadarReadError("Madar state revision mismatch")
    return state, user, revision


def _unsafe_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return (stat.S_ISLNK(info.st_mode) or
            bool(getattr(info, "st_file_attributes", 0) &
                 getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)) or
            bool(getattr(path, "is_junction", lambda: False)()))


def local_madar_available():
    """Metadata-only probe of the current Windows user's fixed Madar folder."""
    appdata = os.environ.get("APPDATA")
    if not appdata or not Path(appdata).is_absolute():
        return {"available": False, "source": "local-appdata-madar"}
    root = Path(appdata) / "MadarDesk"
    target = root / "tasks.json"
    if any(_unsafe_link(part) for part in (target, root, *root.parents)):
        return {"available": False, "source": "local-appdata-madar"}
    return {"available": root.is_dir() and target.is_file(),
            "source": "local-appdata-madar"}


def _read_local_state():
    """Read only %APPDATA%/MadarDesk/tasks.json; never accept a JS-supplied path.

    This is NOT authenticated by the Madar server and can be a stale solo copy.
    The file's complete state is never returned: only bounded allowlist fields.
    """
    appdata = os.environ.get("APPDATA")
    if not appdata or not Path(appdata).is_absolute():
        raise MadarReadError("Local Madar profile unavailable")
    root = Path(appdata) / "MadarDesk"
    path = root / "tasks.json"
    if any(_unsafe_link(part) for part in (path, root, *root.parents)):
        raise MadarReadError("Linked local Madar path refused")
    if not root.is_dir() or not path.is_file():
        raise MadarReadError("Local Madar tasks snapshot not found")
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_JSON_BYTES or
            before.st_nlink != 1):
        raise MadarReadError("Unsafe local Madar tasks snapshot")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) |
                 getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or
                not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1):
            raise MadarReadError("Local Madar snapshot replaced")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(_MAX_JSON_BYTES + 1)
        final = path.lstat()
        if (_unsafe_link(path) or
                (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) !=
                (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) or
                len(raw) > _MAX_JSON_BYTES):
            raise MadarReadError("Local Madar snapshot changed during read")
    finally:
        os.close(fd)
    try:
        state = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                           parse_constant=_reject_nonfinite)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise MadarReadError("Invalid local Madar state JSON") from exc
    if type(state) is not dict or type(state.get("tasks")) is not list or (
            type(state.get("projects")) is not list):
        raise MadarReadError("Invalid local Madar tasks snapshot schema")
    return state, hashlib.sha256(raw).hexdigest()


def _projection(state, *, scope, offset, limit):
    collections = {}
    counts = {}
    for kind in _FIELDS:
        records = state.get(kind, [])
        if type(records) is not list or len(records) > _MAX_ITEMS_PER_COLLECTION:
            raise MadarReadError("Madar state collection exceeded limits")
        counts[kind] = len(records)
        if scope in ("all", kind):
            collections[kind] = [_clean_record(item, kind)
                                 for item in records[offset:offset + limit]]
    return counts, collections


def read_local_madar_state(*, scope, explicit_consent, offset=0, limit=50):
    """An explicit same-user local-file fallback, clearly NOT host authenticated."""
    _validate_paging(scope, offset, limit)
    if explicit_consent is not True:
        raise PermissionError("Explicit local Madar data read consent required")
    state, source_digest = _read_local_state()
    counts, collections = _projection(state, scope=scope, offset=offset, limit=limit)
    return {
        "connected": True, "scope": scope, "counts": counts,
        "items": collections, "offset": offset, "limit": limit,
        "more": {key: offset + len(rows) < counts[key]
                 for key, rows in collections.items()},
        "source": {
            "kind": "madar-local-appdata-tasks-json",
            "sha256": source_digest,
            "readUtc": datetime.now(timezone.utc).isoformat(),
            "hostAuthenticated": False, "serverAclApplied": False,
            "mayBeStale": True, "readOnly": True,
        },
        "excluded": ["financial-ledger", "attachments", "passwords", "tokens",
                     "private-files", "unrecognized-state-fields"],
        "financialEventCreated": False,
    }


def read_authorized_madar_state(*, scope, connection, explicit_consent,
                                offset=0, limit=50):
    """One operator-approved authenticated snapshot; returns no finance ledger.

    No fallback to local Madar files or an existing GUI's cached credentials.
    """
    _validate_paging(scope, offset, limit)
    if explicit_consent is not True:
        raise PermissionError("Explicit Madar full-data read consent required")
    host, port, pin, username, password, origin = _network_config(connection)
    login = _pinned_json(host, port, pin, "POST", "/api/login",
                         payload={"username": username, "password": password})
    token = login.get("token")
    if type(token) is not str or not 20 <= len(token) <= 4096:
        raise MadarReadError("Madar host did not authenticate this session")
    result = _pinned_json(host, port, pin, "GET", "/api/state", token=token)
    state, actor, revision = _validate_host_result(login, result)
    counts, collections = _projection(state, scope=scope, offset=offset, limit=limit)
    response = {
        "connected": True, "scope": scope, "counts": counts,
        "items": collections, "offset": offset, "limit": limit,
        "more": {key: offset + len(rows) < counts[key]
                 for key, rows in collections.items()},
        "source": {
            "kind": "madar-authorized-host-state-projection",
            "url": origin,
            "actor": actor["username"],
            "role": actor["role"],
            "projectGrants": actor.get("projects"),
            "revision": revision,
            "readUtc": datetime.now(timezone.utc).isoformat(),
            "serverAclApplied": True,
            "readOnly": True,
        },
        "excluded": ["financial-ledger", "attachments", "passwords", "tokens",
                     "private-files", "unrecognized-state-fields"],
        "financialEventCreated": False,
    }
    return response
