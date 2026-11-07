"""Password-protected LAN task collaboration, independent from cloud services.

Plain HTTP is restricted to a literal loopback bind for local compatibility.
Network-accessible listeners require TLS; HTTPS clients verify the certificate
fingerprint before sending credentials or other data. Mutations are authorized
on the server.
"""
from __future__ import annotations
from copy import deepcopy
import base64
import binascii
import hashlib
import hmac
from http.client import HTTPSConnection
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import re
import secrets
import ssl
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.parse import parse_qs
from datetime import datetime, timezone
from automation_due import due_events
from attachments import AttachmentStore
from offline_exchange import atomic_json
from role_profiles import (BUILTIN_LABELS, MAX_ROLES, MODE_RANK,
                           DISPLAY_FEATURE_TIERS, LEGACY_DISPLAY_ROLE,
                           default_roles, effective_display, public_role, validate_role)
import collab
import automation_buttons
import finance

ROLES = {"admin", "editor", "viewer"}


def standalone_finance_access(actor, accounts, *, mutation=False):
    """Only trusted server-side account grants, independent of project ACL."""
    if (type(actor) is not str or not actor or type(accounts) is not dict
            or type(accounts.get(actor)) is not dict):
        raise PermissionError("Authenticated standalone-accounting principal required")
    account = accounts[actor]
    if account.get("username") != actor or account.get("role") not in ROLES:
        raise PermissionError("Standalone-accounting principal/role mismatch")
    if account["role"] == "admin":
        return
    if mutation:
        if account["role"] != "editor" or account.get("financeEdit") is not True:
            raise PermissionError("Standalone-accounting mutations require finance editor")
        return
    # A finance writer must be able to read the ledger it is allowed to edit.
    # The editor grant is still explicit and does not elevate viewers.
    if (account.get("financeView") is not True and not
            (account["role"] == "editor" and account.get("financeEdit") is True)):
        raise PermissionError("Standalone-accounting read requires financeView")


def standalone_finance_accounts(accounts):
    """Give isolated reducer only finance ACLs, never password hashes or tasks."""
    if type(accounts) is not dict or not accounts:
        raise PermissionError("Authenticated account registry required")
    result = {}
    for username, account in accounts.items():
        if (type(username) is not str or type(account) is not dict or
                account.get("username") != username or account.get("role") not in ROLES):
            raise PermissionError("Malformed standalone finance principal registry")
        result[username] = {
            "username": username, "role": account["role"],
            "financeView": (account["role"] == "admin" or
                            account.get("financeView") is True or
                            (account["role"] == "editor" and
                             account.get("financeEdit") is True)),
            "financeEdit": (account["role"] == "admin" or
                            (account["role"] == "editor" and
                             account.get("financeEdit") is True)),
        }
    return result


def standalone_command_request(request):
    """Strict UI/LAN envelope, never accepts caller-selected actor or company."""
    if (type(request) is not dict or set(request) != {"command", "expectedRevision"}
            or type(request["command"]) is not dict
            or type(request["expectedRevision"]) is not int
            or request["expectedRevision"] < 0):
        raise ValueError("Expected {command: object, expectedRevision: nonnegative integer}")
    return request["command"], request["expectedRevision"]

AVATAR_ICONS = {
    "user", "briefcase", "code", "palette", "wrench", "chart", "sparkles",
    "check", "rocket", "folder", "star", "camera", "finance", "management",
    "support", "production", "operations", "sales", "quality", "marketing",
}
AVATAR_COLOR_DEFAULT = "#5376b5"
AVATAR_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_LAN_PASSWORD_CHARS = 4096
MAX_LAN_LOGIN_BODY_BYTES = 65_536


def clean_profile(payload, old=None):
    old = old or {}
    name = payload.get("displayName", old.get("displayName", ""))
    icon = payload.get("avatarIcon", old.get("avatarIcon", "user"))
    photo = payload.get("avatarPhoto", old.get("avatarPhoto", ""))
    color = payload.get("avatarColor", old.get("avatarColor", AVATAR_COLOR_DEFAULT))
    if not isinstance(name, str) or len(name.strip()) > 80:
        raise ValueError("نام نمایشی باید کوتاه باشد.")
    if not isinstance(icon, str) or icon not in AVATAR_ICONS:
        raise ValueError("آیکون انتخابی معتبر نیست.")
    if not isinstance(color, str) or not AVATAR_COLOR_PATTERN.fullmatch(color):
        raise ValueError("رنگ آواتار باید در قالب شش‌رقمی #RRGGBB باشد.")
    if not isinstance(photo, str) or len(photo) > 120000:
        raise ValueError("حجم تصویر پروفایل بیشتر از حد مجاز است.")
    if photo:
        prefix, separator, content = photo.partition(",")
        if prefix not in ("data:image/png;base64", "data:image/jpeg;base64") or not separator:
            raise ValueError("فقط عکس PNG یا JPEG مجاز است.")
        try:
            decoded = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("فرمت تصویر درست نیست.") from exc
        if len(decoded) > 85000 or not (
            decoded.startswith(b"\x89PNG\r\n\x1a\n") or decoded.startswith(b"\xff\xd8\xff")
        ):
            raise ValueError("فرمت فایل عکس تأیید نشد.")
    return {"displayName": name.strip(), "avatarIcon": icon,
            "avatarPhoto": photo, "avatarColor": color.lower()}


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 10 <= len(password) <= MAX_LAN_PASSWORD_CHARS:
        raise ValueError("رمز شبکه باید بین ۱۰ و ۴۰۹۶ نویسه باشد.")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 250_000)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, stored):
    try:
        salt, expected = stored.split(":")
        value = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 250_000)
        return hmac.compare_digest(value, bytes.fromhex(expected))
    except (TypeError, ValueError):
        return False


# Public dummy verifier, not a credential: PBKDF2-SHA256 of a synthetic string
# with a zero salt. Unknown LAN usernames must do the same KDF work as a wrong
# password for an existing account, without creating a login-capable identity.
_UNKNOWN_ACCOUNT_HASH = (
    "00000000000000000000000000000000:"
    "4c10f81f63c0d92af760073a748e39961670145213c09e81db117eff04dc361a"
)


def make_account(username, password, role="viewer", projects=None):
    if not isinstance(username, str) or not 3 <= len(username) <= 40 or not all(
        c.isascii() and (c.isalnum() or c in "._-") for c in username
    ):
        raise ValueError("نام کاربری باید ۳ تا ۴۰ کاراکتر انگلیسی باشد.")
    if role not in ROLES:
        raise ValueError("نقش معتبر نیست.")
    if projects is not None and (not isinstance(projects, list) or
                                 not all(isinstance(p, str) for p in projects)):
        raise ValueError("محدوده پروژه‌ها معتبر نیست.")
    return {"username": username, "passwordHash": password_hash(password),
            "role": role, "projects": projects, **clean_profile({})}


def public_user(account, display_roles=None):
    return {k: account.get(k) for k in ("username", "role", "projects")} | {
        "financeView": (account.get("role") == "admin" or
                        account.get("financeView") is True),
        "financeEdit": (account.get("role") == "admin" or
                        (account.get("role") == "editor" and
                         account.get("financeEdit") is True)),
        **clean_profile({}, account),
        **effective_display(account, display_roles)
    }


def view_for(data, account):
    if account["role"] == "admin":
        return deepcopy(data)
    filtered = deepcopy(data)
    # Project price historically lived in shared task JSON. Hide the existing
    # legacy field from every non-admin, even if they can view all projects.
    from finance_visibility import redact_card
    for project in filtered["projects"]:
        project["price"] = 0
    filtered["tasks"] = [redact_card(task) for task in filtered["tasks"]]
    if account["projects"] is None:
        return filtered
    permitted = set(account["projects"])
    filtered["projects"] = [p for p in filtered["projects"] if p["id"] in permitted]
    filtered["tasks"] = [t for t in filtered["tasks"] if t["projectId"] in permitted]
    if "boards" in filtered:
        # Never reintroduce references to the live host state after deepcopy.
        # Read projections must remain detached until an authorized write.
        filtered["boards"] = [b for b in filtered["boards"] if b.get("projectId") in permitted]
        allowed_boards = {b["id"] for b in filtered["boards"]}
        filtered["templates"] = [t for t in filtered.get("templates", [])
                                 if t["boardId"] in allowed_boards]
        allowed_workspaces = {b["workspaceId"] for b in filtered["boards"]}
        filtered["workspaces"] = [w for w in filtered.get("workspaces", [])
                                  if w["id"] in allowed_workspaces]
    return filtered


def revision(data):
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def certificate_fingerprint(certfile):
    """Return the SHA-256 fingerprint of the first PEM certificate (the leaf)."""
    pem = Path(certfile).read_text(encoding="ascii")
    match = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S)
    if not match:
        raise ValueError("PEM certificate missing")
    der = ssl.PEM_cert_to_DER_cert(match.group())
    return hashlib.sha256(der).hexdigest()


def _fingerprint_bytes(fingerprint):
    """Require an explicit complete SHA-256 pin, with optional colon separators."""
    if not isinstance(fingerprint, str):
        raise ValueError("SHA-256 server fingerprint is required")
    value = fingerprint.strip()
    if re.fullmatch(r"[a-fA-F0-9]{64}", value):
        return bytes.fromhex(value)
    if re.fullmatch(r"[a-fA-F0-9]{2}(?::[a-fA-F0-9]{2}){31}", value):
        return bytes.fromhex(value.replace(":", ""))
    raise ValueError("Expected a complete 64-digit SHA-256 server fingerprint")


def pinned_https_json(url, fingerprint, *, method="GET", data=None, headers=None, timeout=25):
    """Make one JSON API request over HTTPS, pinning the leaf certificate.

    Self-signed LAN certificates are supported. TLS is established first and
    the peer certificate is checked on that SAME connection before the HTTP
    request (including passwords and bearer tokens) is sent. No redirects or
    HTTP fallback are followed. HTTP failures raise urllib HTTPError.
    """
    expected = _fingerprint_bytes(fingerprint)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.port is None or (
        parsed.username is not None or parsed.password is not None or parsed.fragment
    ):
        raise ValueError("Expected https://PRIVATE_IP:PORT/path without userinfo or fragment")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise ValueError("LAN HTTPS requires a private or loopback IP address") from exc
    if not (address.is_private or address.is_loopback):
        raise ValueError("LAN HTTPS requires a private or loopback IP address")
    if method not in ("GET", "POST", "DELETE"):
        raise ValueError("Unsupported LAN HTTP method")

    body = None if data is None else (data if isinstance(data, bytes)
                                       else json.dumps(data).encode("utf8"))
    request_headers = dict(headers or {})
    if body is not None:
        request_headers.setdefault("Content-Type", "application/json")
    # A trusted fingerprint authenticates a self-signed peer. Skipping CA
    # checks here is safe ONLY because a mandatory pin is checked pre-request.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = HTTPSConnection(parsed.hostname, parsed.port, timeout=timeout,
                                 context=context)
    try:
        connection.connect()
        der = connection.sock.getpeercert(binary_form=True)
        if not der or not hmac.compare_digest(hashlib.sha256(der).digest(), expected):
            raise ssl.SSLCertVerificationError("LAN server certificate fingerprint mismatch")
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection.request(method, target, body=body, headers=request_headers)
        response = connection.getresponse()
        # LAN attachment JSON may contain base64 payloads up to 16 MB.
        raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError("LAN HTTPS response exceeds size limit")
        if not 200 <= response.status < 300:
            raise HTTPError(url, response.status, response.reason,
                            response.headers, BytesIO(raw))
        return json.loads(raw.decode("utf8"))
    finally:
        connection.close()


class LanService:
    def __init__(self, bridge, users_path, bind="0.0.0.0", port=48370,
                 *, certfile=None, keyfile=None):
        self.bridge = bridge
        self.users_path = users_path
        self.bind, self.port = bind, port
        self.certfile, self.keyfile = certfile, keyfile
        self.lock = threading.RLock()
        self.sessions = {}
        self.failed = {}
        # A valid account must not erase failed guesses aimed at other users.
        # Store only a fixed-size digest, never arbitrary attempted usernames.
        self.failed_target = {}
        self.failed_accounts = {}
        self.failed_unknown_users = {}
        self.users = self._read_users()
        self.display_roles_path = self.users_path.with_name(self.users_path.stem + ".display-roles.json")
        self.display_roles = self._read_display_roles()
        self.delete_journal_path = self.users_path.with_name(self.users_path.name + ".delete-pending.json")
        self._delete_recovery_required = False
        # Never accept a login or account mutation against mismatched task
        # assignments and user identities after a previous host hard-stop.
        self._recover_pending_delete()
        self.server = None
        self.thread = None
        self.integration_router = None

    def _commit_domain(self, domain, state, *, expected_finance_sha256=None):
        """Use the unified store when available, or the legacy JSON bridge."""
        if domain not in ("collab", "finance"):
            raise ValueError("Unsupported persistence domain")
        commit = getattr(self.bridge, "_commit_domain", None)
        if callable(commit):
            return commit(domain, state,
                          expected_finance_sha256=expected_finance_sha256)
        if expected_finance_sha256 is not None:
            raise ValueError("RIAL financial CAS requires unified SQLite host")
        path = self.bridge.collab_path if domain == "collab" else self.bridge.finance_path
        return atomic_json(path, state)

    def _read_users(self):
        if not self.users_path.exists():
            return {}
        data = json.loads(self.users_path.read_text(encoding="utf8"))
        if not isinstance(data, dict):
            raise ValueError("فایل کاربران شبکه معتبر نیست.")
        return data

    def _store_users(self, users=None):
        # Use a unique, fsynced temporary file rather than a fixed *.tmp
        # path which may be owned or planted by an unrelated process.
        atomic_json(self.users_path, self.users if users is None else users)

    def _recover_pending_delete(self):
        """Complete an authenticated delete intent before the host serves LAN.

        A single process owns this LAN host. The journal is written before
        either JSON registry or board store, so a crash at either boundary is
        recoverable by idempotently finishing the deletion, not resurrecting
        an identity whose credentials might already have been revoked.
        """
        marker = self.delete_journal_path
        if not marker.exists() and not marker.is_symlink():
            self._delete_recovery_required = False
            return
        if marker.is_symlink() or marker.stat().st_size > 4096:
            raise ValueError("Unsafe pending LAN user deletion journal")
        try:
            intent = json.loads(marker.read_text(encoding="utf8"))
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Corrupt pending LAN user deletion journal") from exc
        if (type(intent) is not dict or set(intent) != {"version", "operation", "username"}
                or type(intent["version"]) is not int or intent["version"] != 1
                or intent["operation"] != "user.delete" or
                type(intent["username"]) is not str or
                not 3 <= len(intent["username"]) <= 40 or
                any(not c.isascii() or (not c.isalnum() and c not in "._-")
                    for c in intent["username"])):
            raise ValueError("Invalid pending LAN user deletion journal")
        username = intent["username"]
        with self.lock, self.bridge._lock:
            # Refresh disk truth; a completed delete may have reached the
            # registry but not yet removed the journal or card assignments.
            current_users = self._read_users()
            state = deepcopy(self.bridge.getState())
            changed = False
            for task in state["tasks"]:
                if username in task.get("assignees", []):
                    task["assignees"] = [u for u in task["assignees"] if u != username]
                    changed = True
            updated = {name: account for name, account in current_users.items()
                       if name != username}
            if updated != current_users:
                self._store_users(updated)
            if changed:
                self.bridge.saveState(state)
            self.users = updated
            marker.unlink()
            self._delete_recovery_required = False

    def _publish_users(self, updated):
        """Keep live identities consistent with an existing on-disk registry.

        Atomic publication may succeed before a writer reports a later error.
        Only compensate an exact copy of our candidate; never replace an
        unexpected registry revision after a failed write.
        """
        previous = self.users
        existed = self.users_path.exists()
        try:
            self._store_users(updated)
        except Exception:
            try:
                observed = self._read_users()
            except Exception as inspection_error:
                raise RuntimeError(
                    "LAN identity save failed; persisted registry could not be inspected"
                ) from inspection_error
            if observed == updated:
                try:
                    if existed:
                        self._store_users(previous)
                    else:
                        self.users_path.unlink()
                except Exception as rollback_error:
                    raise RuntimeError(
                        "LAN identity save failed and registry rollback failed"
                    ) from rollback_error
            elif observed != previous:
                raise RuntimeError(
                    "LAN identity save failed; unexpected registry revision prevents rollback"
                )
            raise
        self.users = updated

    def _read_display_roles(self):
        defaults = default_roles()
        if not self.display_roles_path.exists():
            return defaults
        data = json.loads(self.display_roles_path.read_text(encoding="utf8"))
        if (type(data) is not dict or set(data) != {"version", "roles"} or
                type(data["version"]) is not int or data["version"] != 1 or
                type(data["roles"]) is not list or
                not len(defaults) <= len(data["roles"]) <= MAX_ROLES):
            raise ValueError("Invalid display role catalog")
        roles = {}
        for entry in data["roles"]:
            role = validate_role(entry)
            if role["id"] in roles:
                raise ValueError("Duplicate display role id")
            # Release updates may add new UI features. Built-in templates are
            # code-owned and normalized on read; custom templates are persisted.
            roles[role["id"]] = defaults.get(role["id"], role)
        if not set(BUILTIN_LABELS).issubset(roles):
            raise ValueError("Required display roles are missing")
        return roles

    def _publish_display_roles(self, updated):
        """Compensate a catalog write that publishes before reporting failure."""
        path = self.display_roles_path
        previous = json.loads(path.read_text(encoding="utf8")) if path.exists() else None
        candidate = {"version": 1, "roles": list(updated.values())}
        try:
            atomic_json(path, candidate)
        except Exception:
            try:
                observed = json.loads(path.read_text(encoding="utf8")) if path.exists() else None
            except Exception as inspection_error:
                raise RuntimeError(
                    "LAN display role save failed; persisted catalog could not be inspected"
                ) from inspection_error
            if observed == candidate:
                try:
                    if previous is None:
                        path.unlink()
                    else:
                        atomic_json(path, previous)
                except Exception as rollback_error:
                    raise RuntimeError(
                        "LAN display role save failed and catalog rollback failed"
                    ) from rollback_error
            elif observed != previous:
                raise RuntimeError(
                    "LAN display role save failed; unexpected catalog revision prevents rollback"
                )
            raise
        self.display_roles = updated

    def _public_user(self, account):
        return public_user(account, self.display_roles)

    def list_display_roles(self, token):
        with self.lock:
            who = self.account_for(token)
            if who["role"] != "admin":
                raise PermissionError("Only administrators can manage presentation roles")
            return [public_role(role) for role in self.display_roles.values()]

    def upsert_display_role(self, token, payload):
        with self.lock:
            who = self.account_for(token)
            if who["role"] != "admin":
                raise PermissionError("Only administrators can manage presentation roles")
            role = validate_role(payload)
            if role["id"] in BUILTIN_LABELS:
                raise ValueError("Built-in display role templates cannot be edited")
            if role["id"] not in self.display_roles and len(self.display_roles) >= MAX_ROLES:
                raise ValueError("Display role catalog limit reached")
            updated = {**self.display_roles, role["id"]: role}
            self._publish_display_roles(updated)
            return public_role(role)

    def delete_display_role(self, token, role_id):
        with self.lock:
            who = self.account_for(token)
            if who["role"] != "admin":
                raise PermissionError("Only administrators can manage presentation roles")
            if type(role_id) is not str or role_id not in self.display_roles:
                raise ValueError("Display role not found")
            if role_id in BUILTIN_LABELS:
                raise ValueError("Built-in display roles cannot be deleted")
            if any(account.get("displayRole", LEGACY_DISPLAY_ROLE.get(account.get("role"))) == role_id
                   for account in self.users.values()):
                raise ValueError("Display role is assigned to an account")
            updated = {k: v for k, v in self.display_roles.items() if k != role_id}
            self._publish_display_roles(updated)
            return True

    def setup_owner(self, username, password):
        with self.lock:
            if self.users:
                raise ValueError("مدیر قبلاً تعریف شده است.")
            account = make_account(username, password, "admin")
            account["displayRole"] = "superadmin"
            updated = {**self.users, username: account}
            self._publish_users(updated)
            return self._public_user(account)

    def authenticate(self, username, password, ip="127.0.0.1"):
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError("نام کاربری و رمز عبور باید متن باشند.")
        # A malformed login must not consume a 16 MB JSON body and then run
        # PBKDF2 on an attacker-controlled megabyte-scale credential.
        if len(username) > 40 or len(password) > MAX_LAN_PASSWORD_CHARS:
            raise ValueError("نام کاربری یا رمز شبکه بیش از حد طولانی است.")
        with self.lock:
            if self._delete_recovery_required:
                raise PermissionError("LAN user deletion recovery is required before login")
            now = time.time()
            failures, last = self.failed.get(ip, (0, 0))
            if now - last >= 120:
                failures = 0
                self.failed.pop(ip, None)
                self.failed_target.pop(ip, None)
            target_digest = hashlib.sha256(username.encode("utf-8")).digest()
            account = self.users.get(username)
            # A valid login cannot erase the IP's budget for probing arbitrary
            # nonexistent usernames. Keep one entry per IP, never per guess.
            unknown_failures, unknown_last = self.failed_unknown_users.get(ip, (0, 0))
            if now - unknown_last >= 120:
                unknown_failures = 0
            # A different account's valid login must not reset this account's
            # failed guesses. Track only existing users to bound memory growth.
            key = (ip, username) if account else None
            account_failures, account_last = self.failed_accounts.get(key, (0, 0))
            if now - account_last >= 120:
                account_failures = 0
            if failures >= 6 or account_failures >= 6 or unknown_failures >= 6:
                raise PermissionError("تلاش‌های ورود بیش از حد است. دو دقیقه بعد دوباره امتحان کنید.")
            # Do not expose account existence through a skipped PBKDF2 call.
            # A dummy-hash match never authenticates a nonexistent username.
            verified = verify_password(
                password, account["passwordHash"] if account else _UNKNOWN_ACCOUNT_HASH)
            if not account or not verified:
                self.failed[ip] = (failures + 1, now)
                prior_target = self.failed_target.get(ip)
                self.failed_target[ip] = (target_digest if failures == 0 else
                                          target_digest if prior_target == target_digest else None)
                if key is not None:
                    self.failed_accounts[key] = (account_failures + 1, now)
                else:
                    self.failed_unknown_users[ip] = (unknown_failures + 1, now)
                raise PermissionError("نام کاربری یا رمز عبور نادرست است.")
            # Only a success for the sole previously guessed target can
            # reset the IP-wide budget. Otherwise password spraying across
            # known accounts would evade the global throttle.
            if self.failed_target.get(ip) == target_digest:
                self.failed.pop(ip, None)
                self.failed_target.pop(ip, None)
            self.failed_accounts.pop(key, None)
            token = secrets.token_urlsafe(32)
            self.sessions[token] = (username, now + 12 * 3600)
            return {"token": token, "user": self._public_user(account)}

    def account_for(self, token):
        with self.lock:
            if self._delete_recovery_required:
                raise PermissionError("LAN user deletion recovery is required before serving requests")
            record = self.sessions.get(token)
            if not record or time.time() >= record[1]:
                self.sessions.pop(token, None)
                raise PermissionError("جلسه ورود معتبر نیست. دوباره وارد شوید.")
            account = self.users.get(record[0])
            if not account:
                raise PermissionError("حساب کاربری پیدا نشد.")
            return account

    def list_users(self, token):
        with self.lock:
            who = self.account_for(token)
            if who["role"] != "admin":
                raise PermissionError("فقط مدیر به کاربران دسترسی دارد.")
            return [self._public_user(u) for u in self.users.values()]

    def list_profiles(self, token):
        with self.lock:
            who = self.account_for(token)
            if who["role"] == "admin":
                return [self._public_user(u) for u in self.users.values()]
            result = []
            for user in self.users.values():
                if user["username"] == who["username"]:
                    result.append(self._public_user(user))
                    continue
                # Profiles are directory entries for coworkers on shared projects,
                # not a general user directory. A user with zero grants sees self.
                # An unrestricted viewer still shares no project with a
                # coworker whose explicit scope is empty.
                if user["projects"] is not None and not user["projects"]:
                    continue
                if who["projects"] is not None and not who["projects"]:
                    continue
                if who["projects"] is not None and user["projects"] is not None:
                    shared = set(who["projects"]) & set(user["projects"])
                    if not shared:
                        continue
                else:
                    shared = None if who["projects"] is None else set(who["projects"])
                visible = self._public_user(user)
                # Do not disclose coworkers' project permissions outside what the
                # requesting user can already see.
                if shared is not None:
                    visible["projects"] = sorted(shared)
                result.append(visible)
            return result

    def update_profile(self, token, payload):
        if not isinstance(payload, dict) or set(payload) - {
            "displayName", "avatarIcon", "avatarPhoto", "avatarColor"
        }:
            raise PermissionError("تغییر نقش، حساب یا دسترسی از پروفایل شخصی مجاز نیست.")
        with self.lock:
            who = self.account_for(token)
            account = {**who, **clean_profile(payload, who)}
            updated = {**self.users, who["username"]: account}
            self._publish_users(updated)
            return self._public_user(account)

    def current_user(self, token):
        with self.lock:
            return self._public_user(self.account_for(token))

    def change_password(self, token, current, new_password):
        with self.lock:
            who = self.account_for(token)
            if not isinstance(current, str) or not verify_password(current, who["passwordHash"]):
                raise PermissionError("رمز فعلی درست نیست.")
            updated = {**self.users, who["username"]: {
                **who, "passwordHash": password_hash(new_password)}}
            self._publish_users(updated)
            # Other sessions are revoked, current session is kept.
            for key, item in list(self.sessions.items()):
                if item[0] == who["username"] and key != token:
                    del self.sessions[key]
            return True

    def reset_password(self, token, username, new_password):
        with self.lock:
            who = self.account_for(token)
            if who["role"] != "admin":
                raise PermissionError("فقط مدیر می‌تواند رمز را بازنشانی کند.")
            target = self.users.get(username)
            if not target:
                raise ValueError("کاربر پیدا نشد.")
            updated = {**self.users, username: {
                **target, "passwordHash": password_hash(new_password)}}
            self._publish_users(updated)
            for key, item in list(self.sessions.items()):
                if item[0] == username:
                    del self.sessions[key]
            return True

    def authenticate_owner_token(self):
        """Trusted in-process administrator channel, never exposed on HTTP."""
        with self.lock:
            admins = [a for a in self.users.values() if a["role"] == "admin"]
            if not admins:
                raise PermissionError("مدیر شبکه تعریف نشده است.")
            token = secrets.token_urlsafe(32)
            self.sessions[token] = (admins[0]["username"], time.time() + 60)
            return token

    def upsert_user(self, token, payload):
        who = self.account_for(token)
        if who["role"] != "admin":
            raise PermissionError("فقط مدیر می‌تواند کاربران را تغییر دهد.")
        if not isinstance(payload, dict):
            raise ValueError("اطلاعات حساب معتبر نیست.")
        username, password = payload.get("username"), payload.get("password")
        if (not isinstance(username, str) or
                not 3 <= len(username) <= 40 or
                any(not c.isascii() or (not c.isalnum() and c not in "._-")
                    for c in username)):
            raise ValueError("نام کاربری باید ۳ تا ۴۰ کاراکتر انگلیسی باشد.")
        for grant in ("financeView", "financeEdit"):
            if grant in payload and type(payload[grant]) is not bool:
                raise ValueError("مجوز مالی باید مقدار درست یا نادرست داشته باشد.")
        profile_fields = {key: payload[key] for key in
                          ("displayName", "avatarIcon", "avatarPhoto", "avatarColor")
                          if key in payload}
        with self.lock:
            # Role changes can race a request already authenticated above.
            who = self.account_for(token)
            if who["role"] != "admin":
                raise PermissionError("فقط مدیر می‌تواند کاربران را تغییر دهد.")
            old = self.users.get(username)
            # An omitted field is not an instruction to downgrade a role or
            # silently widen a scoped account to all projects.
            role = payload.get("role", old["role"] if old else "viewer")
            scope = payload.get("projects", old["projects"] if old else None)
            if role == "admin" and old and old["role"] != "admin" and "projects" not in payload:
                # Explicit promotion to admin already implies unrestricted scope.
                scope = None
            if not isinstance(role, str) or role not in ROLES:
                raise ValueError("سطح دسترسی معتبر نیست.")
            if (scope is not None and (
                    not isinstance(scope, list) or len(scope) > 500 or
                    any(not isinstance(p, str) for p in scope) or
                    len(scope) != len(set(scope)))):
                raise ValueError("محدوده پروژه‌ها معتبر نیست.")
            if role == "admin" and scope is not None:
                raise ValueError("مدیر به تمام پروژه‌ها دسترسی دارد؛ محدوده انتخابی برای مدیر مجاز نیست.")
            if role == "viewer" and payload.get("financeEdit") is True:
                raise ValueError("کاربر مشاهده‌گر نمی‌تواند مجوز ویرایش مالی داشته باشد.")
            display_role = payload.get("displayRole", old.get("displayRole", LEGACY_DISPLAY_ROLE[role])
                                       if old else LEGACY_DISPLAY_ROLE[role])
            # A legacy ACL downgrade resets presentation defaults unless the
            # administrator explicitly chooses a new display role.
            if old and "displayRole" not in payload and old.get("role") != role:
                display_role = LEGACY_DISPLAY_ROLE[role]
            if type(display_role) is not str or display_role not in self.display_roles:
                raise ValueError("Display role does not exist")
            if display_role == "superadmin" and role != "admin":
                raise ValueError("Superadmin display is reserved for administrators")
            if role == "admin" and display_role != "superadmin":
                raise ValueError("Administrator accounts must use superadmin display")
            if username == who["username"] and role != "admin":
                raise ValueError("مدیر نمی‌تواند نقش خودش را کاهش دهد.")
            if not password and not old:
                raise ValueError("برای کاربر جدید باید رمز تعیین شود.")
            if password:
                account = make_account(username, password, role, scope)
                if old:
                    account.update(clean_profile({}, old))
            else:
                account = {**old, "role": role, "projects": scope}
            account["displayRole"] = display_role
            # Per-account customization can narrow its role's visible features,
            # but cannot exceed the role's presentation ceiling.
            display_role_profile = self.display_roles[display_role]
            base_mode = display_role_profile["displayMode"]
            role_changed = bool(old and old.get("displayRole", LEGACY_DISPLAY_ROLE.get(old.get("role"))) != display_role)
            explicit_mode = "displayMode" in payload
            account_mode = (payload["displayMode"] if explicit_mode else
                            old.get("displayMode") if old and not role_changed else None)
            if account_mode is not None:
                if (type(account_mode) is not str or account_mode not in MODE_RANK or
                        MODE_RANK[account_mode] > MODE_RANK[base_mode]):
                    if explicit_mode:
                        raise ValueError("User display mode exceeds assigned role")
                    # Template shrank since this account was last edited.
                    # Clear its stale override so the current role ceiling wins.
                    account_mode = None
            elif explicit_mode:
                raise ValueError("User display mode must be valid")
            if account_mode is not None:
                account["displayMode"] = account_mode
            else:
                account.pop("displayMode", None)
            allowed = [feature for feature in display_role_profile["features"]
                       if MODE_RANK[DISPLAY_FEATURE_TIERS[feature]] <=
                       MODE_RANK[account_mode or base_mode]]
            explicit_features = "displayFeatures" in payload
            account_features = (payload["displayFeatures"] if explicit_features else
                                old.get("displayFeatures") if old and not role_changed else None)
            if account_features is not None:
                if (type(account_features) is not list or len(account_features) > len(allowed) or
                        any(type(feature) is not str or feature not in allowed
                            for feature in account_features) or
                        len(account_features) != len(set(account_features))):
                    if explicit_features:
                        raise ValueError("User display features exceed assigned role")
                    # Only inherited stale overrides are intersected. A caller
                    # attempting an explicit override outside the role still fails.
                    if type(account_features) is list:
                        account_features = [feature for feature in allowed
                                            if feature in account_features]
                    else:
                        account_features = []
                account["displayFeatures"] = [feature for feature in allowed
                                              if feature in account_features]
            elif explicit_features:
                raise ValueError("User display features must be a list")
            else:
                account.pop("displayFeatures", None)
            # The admin API is the only place where finance grants are
            # assigned. Password/profile updates preserve existing grants.
            # A downgrade to viewer must revoke write access immediately.
            account["financeView"] = (payload.get(
                "financeView", old.get("financeView", False) if old else False)
                if role != "admin" else True)
            account["financeEdit"] = (payload.get(
                "financeEdit", old.get("financeEdit", False) if old else False)
                if role == "editor" else role == "admin")
            if profile_fields:
                account.update(clean_profile(profile_fields, account))
            with self.bridge._lock:
                data = self.bridge.getState()
                if account["projects"] is not None and any(
                    p not in {v["id"] for v in data["projects"]} for p in account["projects"]
                ):
                    raise ValueError("یک پروژه در محدوده دسترسی وجود ندارد.")
                if account["role"] != "admin" and account["projects"] is not None and any(
                    username in task.get("assignees", []) and task["projectId"] not in account["projects"]
                    for task in data["tasks"]
                ):
                    raise ValueError("این کاربر هنوز مسئول کارهایی خارج از محدوده جدید است.")
            updated = {**self.users, username: account}
            self._publish_users(updated)
            if password and old:
                for key, record in list(self.sessions.items()):
                    if record[0] == username:
                        del self.sessions[key]
            return self._public_user(account)

    def delete_user(self, token, username):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            if who["role"] != "admin" or username == who["username"]:
                raise PermissionError("حذف این حساب مجاز نیست.")
            if type(username) is not str or username not in self.users:
                raise ValueError("کاربر پیدا نشد.")
            # Prepare a separate task snapshot; getState() may return a live
            # object and must not expose uncommitted assignee removals.
            before_state = deepcopy(self.bridge.getState())
            state = deepcopy(before_state)
            changed = False
            for task in state["tasks"]:
                if username in task.get("assignees", []):
                    task["assignees"] = [u for u in task["assignees"] if u != username]
                    changed = True
            updated_users = {name: account for name, account in self.users.items()
                             if name != username}
            if self.delete_journal_path.exists() or self.delete_journal_path.is_symlink():
                self._delete_recovery_required = True
                raise RuntimeError("Pending LAN user deletion requires recovery")
            # Durable, intentionally small write-ahead intent. A hard stop
            # after this point is completed on the next host construction.
            atomic_json(self.delete_journal_path, {
                "version": 1, "operation": "user.delete", "username": username})
            # Preserve the previous transaction's order: unassign cards first
            # and revoke the identity only after the task write succeeds. The
            # durable intent above still completes a hard-stopped transaction
            # on the next host startup, whichever file was published last.
            if changed:
                try:
                    self.bridge.saveState(state)
                except BaseException:
                    try:
                        observed = deepcopy(self.bridge.getState())
                    except BaseException as inspection_error:
                        self._delete_recovery_required = True
                        raise RuntimeError(
                            "LAN deletion state save failed; persisted state could not be inspected"
                        ) from inspection_error
                    if observed != before_state:
                        if observed != state:
                            self._delete_recovery_required = True
                            raise RuntimeError(
                                "LAN deletion state save failed; unexpected state revision prevents rollback"
                            )
                        try:
                            self.bridge.saveState(before_state)
                        except BaseException as rollback_error:
                            self._delete_recovery_required = True
                            raise RuntimeError(
                                "LAN deletion state save failed and task-state rollback failed"
                            ) from rollback_error
                    self.delete_journal_path.unlink()
                    raise
            try:
                self._store_users(updated_users)
            except BaseException:
                try:
                    persisted_users = self._read_users()
                except BaseException as inspection_error:
                    self._delete_recovery_required = True
                    raise RuntimeError(
                        "LAN deletion registry save failed; persisted registry could not be inspected"
                    ) from inspection_error
                if persisted_users != self.users:
                    if persisted_users != updated_users:
                        # An unrelated registry revision must never be replaced
                        # by this delete's compensation.
                        if changed:
                            try:
                                self.bridge.saveState(before_state)
                            except BaseException as rollback_error:
                                self._delete_recovery_required = True
                                raise RuntimeError(
                                    "LAN deletion failed and task-state rollback failed"
                                ) from rollback_error
                        self.delete_journal_path.unlink()
                        raise RuntimeError(
                            "LAN deletion registry save failed; unexpected registry revision prevents rollback"
                        )
                    try:
                        self._store_users(self.users)
                    except BaseException as rollback_error:
                        self._delete_recovery_required = True
                        raise RuntimeError(
                            "LAN deletion failed and user-registry rollback failed"
                        ) from rollback_error
                if changed:
                    try:
                        self.bridge.saveState(before_state)
                    except BaseException as rollback_error:
                        self._delete_recovery_required = True
                        raise RuntimeError(
                            "LAN deletion failed and task-state rollback failed"
                        ) from rollback_error
                self.delete_journal_path.unlink()
                raise
            self.users = updated_users
            for key, record in list(self.sessions.items()):
                if record[0] == username:
                    del self.sessions[key]
            self.delete_journal_path.unlink()
        return True

    def read_state(self, token):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            data = view_for(self.bridge.getState(), who)
            return {"state": data, "revision": revision(data), "user": self._public_user(who)}

    def write_state(self, token, incoming, expected):
        from native_app import is_valid, normalize_state
        # Keep the same lock order as user-management actions (users -> state).
        # The previous order (state -> users via read_state) could deadlock when
        # an administrator changed account scope during a concurrent card save.
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            if who["role"] == "viewer":
                raise PermissionError("این کاربر فقط اجازه مشاهده دارد.")
            old = self.bridge.getState()
            current_view = view_for(old, who)
            if revision(current_view) != expected:
                raise RuntimeError("CONFLICT: اطلاعات روی سرور تغییر کرده است. ابتدا تازه‌سازی کنید.")
            next_view = normalize_state(incoming)
            is_valid(next_view)
            if who["role"] == "admin":
                for t in next_view["tasks"]:
                    for username in t.get("assignees", []):
                        target = self.users.get(username)
                        if target is None or (
                            target["role"] != "admin" and target["projects"] is not None
                            and t["projectId"] not in target["projects"]
                        ):
                            raise PermissionError("کاربر مسئول به پروژه دسترسی ندارد.")
                self.bridge._save_local_state(next_view, actor=who["username"],
                                              accounts=self.users,
                                              expected_local_revision=revision(old))
                return self.read_state(token)
            # Editors cannot edit structure or global configuration, only tasks
            # in the projects explicitly granted to them.
            if next_view["stages"] != current_view["stages"] or next_view["settings"] != current_view["settings"]:
                raise PermissionError("ویرایش ستون‌ها یا تنظیمات مخصوص مدیر است.")
            if next_view["projects"] != current_view["projects"]:
                raise PermissionError("ویرایش پروژه مخصوص مدیر است.")
            for field in ("boards", "workspaces", "templates"):
                if next_view.get(field) != current_view.get(field):
                    raise PermissionError("ویرایش ساختار بردها و قالب‌ها مخصوص مدیر است.")
            allowed = {p["id"] for p in current_view["projects"]}
            if any(t["projectId"] not in allowed for t in next_view["tasks"]):
                raise PermissionError("دسترسی به پروژه مقصد وجود ندارد.")
            for t in next_view["tasks"]:
                for username in t.get("assignees", []):
                    target = self.users.get(username)
                    if target is None or (
                        target["role"] != "admin" and target["projects"] is not None
                        and t["projectId"] not in target["projects"]
                    ):
                        raise PermissionError("کاربر مسئول به پروژه دسترسی ندارد.")
            old_other = [t for t in old["tasks"] if t["projectId"] not in allowed]
            # Editor receives a redacted financial projection. Restore original
            # finance fields on the trusted host before saving ordinary edits.
            # Reject any attempted monetary mutation or paid checklist deletion.
            from finance_visibility import preserve_editor_finance
            # Only the editor-visible subset is submitted. Unrelated projects
            # are kept byte-for-byte in old_other, not treated as deletions.
            preserve_editor_finance(
                [task for task in old["tasks"] if task["projectId"] in allowed],
                next_view["tasks"])
            merged = {**old, "tasks": old_other + next_view["tasks"]}
            is_valid(merged)
            self.bridge._save_local_state(merged, actor=who["username"],
                                          accounts=self.users,
                                          expected_local_revision=revision(old))
            return self.read_state(token)

    def collab_read(self, token, kind, card_id=""):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            state = self.bridge.getState()
            stored = self.bridge._load_collab()
            kwargs = {"actor": who["username"], "accounts": self.users,
                      "cards": state["tasks"], "projects": state["projects"]}
            if kind == "comments":
                return collab.list_comments(stored, card_id, **kwargs)
            if kind == "notifications":
                return collab.list_notifications(stored, **kwargs)
            if kind == "rules":
                return collab.list_rules(stored, project_id=card_id or None, **kwargs)
            if kind == "activity":
                return collab.list_activity(stored, **kwargs)
            raise ValueError("نوع اطلاعات همکاری معتبر نیست.")

    def collab_command(self, token, command):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            current = self.bridge.getState()
            output = collab.apply_command(
                self.bridge._load_collab(), command, actor=who["username"],
                accounts=self.users, cards=current["tasks"],
                projects=current["projects"],
                now=datetime.now(timezone.utc).isoformat())
            if output["changed"]:
                self._commit_domain("collab", output["state"])
            return output["result"]

    def automation_buttons_list(self, token, request):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            return self.bridge._automation_buttons_read_local(
                request, actor=who["username"], accounts=self.users)

    def automation_buttons_command(self, token, command):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            if not isinstance(command, dict):
                raise ValueError("Invalid button command")
            if command.get("type") == "button.execute":
                return self.bridge._automation_button_execute_local(
                    command, actor=who["username"], accounts=self.users)
            return self.bridge._automation_buttons_mutate_local(
                command, actor=who["username"], accounts=self.users)

    def finance_read(self, token, project_id=""):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            state = self.bridge.getState()
            return finance.list_invoices(
                self.bridge._load_finance(), actor=who["username"],
                accounts=self.users, cards=state["tasks"], projects=state["projects"],
                project_id=project_id or None)

    def finance_overview(self, token, project_id="", start_date="", end_date=""):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            if who["role"] != "admin":
                raise PermissionError("Financial overview requires administrator")
            state = self.bridge.getState()
            return finance.financial_overview(
                self.bridge._load_finance(), actor=who["username"],
                accounts=self.users, cards=state["tasks"], projects=state["projects"],
                project_id=project_id, start_date=start_date, end_date=end_date)

    def finance_status(self, token):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            if who["role"] != "admin":
                raise PermissionError("فقط مدیر می‌تواند وضعیت صف مالی را مشاهده کند.")
            return {"pending": len(self.bridge._pending_finance_events()),
                    "warning": self.bridge._finance_warning}

    def finance_command(self, token, command):
        if not isinstance(command, dict) or command.get("type") == "completion.record":
            raise ValueError("رویداد تکمیل را فقط سرور از تغییر وضعیت کار تولید می‌کند.")
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            state = self.bridge.getState()
            before = self.bridge._load_finance()
            now = datetime.now(timezone.utc).isoformat()
            if "rialJournalV2" in before and command["type"] == "invoice.issue":
                from ir_invoice_joint_issue import issue_legacy_sales_with_rial
                output = issue_legacy_sales_with_rial(
                    before, command, actor=who["username"], accounts=self.users,
                    cards=state["tasks"], projects=state["projects"], now=now)
            else:
                output = finance.apply_finance_command(
                    before, command, actor=who["username"],
                    accounts=self.users, cards=state["tasks"], projects=state["projects"],
                    now=now)
            if output["changed"]:
                if "rialJournalV2" in before:
                    from money_policy import snapshot_sha256
                    self._commit_domain(
                        "finance", output["state"],
                        expected_finance_sha256=snapshot_sha256(before))
                else:
                    self._commit_domain("finance", output["state"])
            return output["result"]

    def accounting_read(self, token, project_id=""):
        from accounting_service import read_madar_accounting
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            state = self.bridge.getState()
            return read_madar_accounting(
                self.bridge._load_finance(), actor=who["username"],
                accounts=self.users, project_id=project_id,
                cards=state["tasks"], projects=state["projects"])

    def standalone_accounting_read(self, token):
        """Authenticated standalone DB only; no task or legacy accounting state."""
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            standalone_finance_access(who["username"], self.users, mutation=False)
            return self.bridge._standalone_accounting_read_local(
                actor=who["username"], accounts=self.users)

    def standalone_accounting_command(self, token, request):
        """One authenticated standalone store CAS, no shared finance transaction."""
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            standalone_finance_access(who["username"], self.users, mutation=True)
            command, expected_revision = standalone_command_request(request)
            return self.bridge._standalone_accounting_command_local(
                {"command": command, "expectedRevision": expected_revision},
                actor=who["username"], accounts=self.users)

    def standalone_accounting_prepare(self, token, request):
        """Resolve commercial fields exclusively from authoritative saved tasks."""
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            if who["role"] != "admin":
                raise PermissionError("Task accounting preparation requires administrator")
            from standalone_task_prepare import prepare_from_saved_task
            return prepare_from_saved_task(
                self.bridge._standalone_accounting_store(), request,
                tasks=self.bridge.getState()["tasks"], actor=who["username"],
                accounts=standalone_finance_accounts(self.users))

    def standalone_accounting_quote(self, token, request):
        """Quote only: admin identity is verified before numerical evaluation."""
        with self.lock:
            who = self.account_for(token)
            if who.get("role") != "admin":
                raise PermissionError("Only administrator can request a task sale quote")
            from standalone_accounting_quote import quote_standalone_sale
            head = self.bridge._standalone_accounting_store().read(
                actor=who["username"], accounts=standalone_finance_accounts(self.users))
            return quote_standalone_sale(request,
                                         ledger_currency=head["view"]["currency"])

    def rial_journal_read(self, token, request):
        """Role-checked RIAL V2 read. No legacy finance conversion or posting."""
        with self.lock, self.bridge._lock:
            principal = self.account_for(token)
            if principal.get("role") != "admin":
                raise PermissionError("RIAL journal is restricted to administrators")
            if (type(request) is not dict or
                    set(request) != {"companyId", "fiscalPeriodId"}):
                raise ValueError("Invalid RIAL scope request")
            import re
            for value in request.values():
                if type(value) is not str or not re.fullmatch(
                        r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", value):
                    raise ValueError("Invalid RIAL scope identifier")
            return self.bridge._rial_journal_read_local(request)

    def rial_journal_activate(self, token, command):
        """Only the authenticated owner/admin can create a pristine RIAL ledger."""
        with self.lock, self.bridge._lock:
            principal = self.account_for(token)
            if principal.get("role") != "admin":
                raise PermissionError("Only admin may activate RIAL accounting")
            if (type(command) is not dict or
                    set(command) != {"companyId", "fiscalPeriodId",
                                     "startDate", "endDate"}):
                raise ValueError("Invalid RIAL activation command")
            import re
            if any(type(command[k]) is not str or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", command[k])
                   for k in ("companyId", "fiscalPeriodId")):
                raise ValueError("Invalid RIAL activation company/period ID")
            return self.bridge._rial_journal_activate_local(
                command, actor=principal["username"])

    def accounting_command(self, token, command):
        from accounting_service import apply_madar_accounting
        if type(command) is not dict:
            raise ValueError("Invalid authenticated accounting command")
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            state = self.bridge.getState()
            before = self.bridge._load_finance()
            context = {"actor": who["username"], "accounts": self.users,
                       "cards": state["tasks"], "projects": state["projects"],
                       "now": datetime.now(timezone.utc).isoformat()}
            if "rialJournalV2" in before and isinstance(command, dict) and (
                    command.get("type") in (
                        "intake.create", "intake.price", "intake.cancel",
                        "intake.convert")):
                store = self.bridge._unified_store
                if store is None:
                    raise ValueError("Authenticated supplier intake requires unified SQLite")
                from money_policy import snapshot_sha256
                current = store.load()
                if current is None:
                    raise RuntimeError("CONFLICT: unified finance snapshot missing")
                committed = store.commit_authenticated_intake(
                    command, actor=who["username"], accounts=self.users,
                    now=context["now"], expected_revision=current.revision,
                    expected_finance_sha256=snapshot_sha256(before))
                return committed["result"]
            if "rialJournalV2" in before and command.get("type") == "document.issue":
                from ir_purchase_host_adapter import issue_supplier_purchase_with_rial
                output = issue_supplier_purchase_with_rial(before, command, **context)
            else:
                output = apply_madar_accounting(before, command, **context)
            if output["changed"]:
                if "rialJournalV2" in before:
                    from money_policy import snapshot_sha256
                    self._commit_domain(
                        "finance", output["state"],
                        expected_finance_sha256=snapshot_sha256(before))
                else:
                    self._commit_domain("finance", output["state"])
            return output["result"]

    def run_scheduler(self, token):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            if who["role"] != "admin":
                raise PermissionError("Only admin can run scheduler")
            enhanced = self.bridge._run_engine_scheduler(who["username"], self.users)
            if enhanced is not None:
                return enhanced
            current = self.bridge.getState()
            events = due_events(current["tasks"], today=datetime.now().date())
            snapshot = self.bridge._load_collab()
            changed = 0
            for event in events:
                output = collab.apply_command(
                    snapshot, event, actor=who["username"],
                    accounts=self.users, cards=current["tasks"], projects=current["projects"],
                    now=datetime.now(timezone.utc).isoformat())
                if output["changed"]:
                    self._commit_domain("collab", output["state"])
                    changed += 1
                snapshot = output["state"]
            return {"events": len(events), "new": changed}

    def attachment_action(self, token, kind, *, card_id="", attachment_id="", payload=None):
        with self.lock, self.bridge._lock:
            who = self.account_for(token)
            state = self.bridge.getState()
            context = {"actor": who["username"], "accounts": self.users,
                       "cards": state["tasks"], "projects": state["projects"]}
            store = self.bridge._attachment_store()
            if kind == "list":
                return store.list_card(card_id=card_id, **context)
            if kind == "read":
                return store.read(attachment_id=attachment_id, **context)
            if kind == "preview":
                return store.preview(attachment_id=attachment_id, **context)
            if kind == "upload":
                if not isinstance(payload, dict) or set(payload) != {"kind", "cardId", "filename",
                                                                      "contentBase64", "requestId"}:
                    raise ValueError("Invalid upload schema")
                return store.upload(card_id=payload["cardId"], filename=payload["filename"],
                                    content_base64=payload["contentBase64"],
                                    request_id=payload["requestId"],
                                    now=datetime.now(timezone.utc).isoformat(), **context)
            if kind == "delete":
                if not isinstance(payload, dict) or set(payload) != {"kind", "attachmentId", "requestId"}:
                    raise ValueError("Invalid attachment delete schema")
                return store.delete(attachment_id=payload["attachmentId"],
                                    request_id=payload["requestId"],
                                    now=datetime.now(timezone.utc).isoformat(), **context)
            raise ValueError("Invalid attachment kind")

    def start(self):
        if self._delete_recovery_required or self.delete_journal_path.exists():
            raise RuntimeError("LAN user deletion recovery required before listener start")
        if self.server:
            return self.port
        if not self.users:
            raise ValueError("ابتدا حساب مدیر سرور را بسازید.")
        if bool(self.certfile) != bool(self.keyfile):
            raise ValueError("TLS requires both certificate and private key")
        if not self.certfile:
            # Checking the listener address is essential: a private peer IP
            # check inside Handler.process is too late to protect passwords.
            # Hostnames are deliberately excluded from the plaintext exception.
            try:
                loopback_only = ipaddress.ip_address(self.bind).is_loopback
            except ValueError:
                loopback_only = False
            if not loopback_only:
                raise ValueError("TLS is required for non-loopback LAN listeners")
        tls_context = None
        if self.certfile:
            tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
            tls_context.load_cert_chain(certfile=str(self.certfile),
                                        keyfile=str(self.keyfile))
        service = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                return

            def reply(self, status, obj):
                raw = json.dumps(obj, ensure_ascii=False).encode("utf8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def process(self):
                # This direct LAN API accepts origin-form targets only. An
                # absolute URI's authority must not silently become a local
                # authenticated route when its path happens to match /api/.
                # BaseHTTPRequestHandler normalizes leading double slashes in
                # self.path, so inspect the original parsed request line.
                request_target = self.requestline.split()[1]
                if (not request_target.startswith("/") or
                        request_target.startswith("//") or "#" in request_target):
                    return self.reply(400, {"error": "نشانی درخواست نامعتبر است."})
                endpoint = urlparse(self.path).path
                try:
                    client_ip = ipaddress.ip_address(self.client_address[0])
                    if not (client_ip.is_private or client_ip.is_loopback):
                        return self.reply(403, {"error": "فقط اتصال شبکه خصوصی مجاز است."})
                except ValueError:
                    return self.reply(403, {"error": "نشانی کاربر نامعتبر است."})
                # Apply the same unambiguous HTTP framing to *every* route,
                # including login and account mutations (not just integrations).
                names = [name.lower() for name in self.headers.keys()]
                if len(names) != len(set(names)):
                    return self.reply(400, {"error": "هدر تکراری مجاز نیست."})
                if self.request_version == "HTTP/1.1" and not self.headers.get("Host"):
                    return self.reply(400, {"error": "هدر Host الزامی است."})
                if self.headers.get("Transfer-Encoding") is not None:
                    return self.reply(400, {"error": "Transfer-Encoding پشتیبانی نمی‌شود."})
                declared = self.headers.get("Content-Length")
                if declared is not None:
                    # Keep the historical 413 for negative/oversized bodies
                    # on body-carrying routes, while disallowing signed and
                    # otherwise ambiguous HTTP message framing globally.
                    if re.fullmatch(r"-[0-9]+", declared):
                        status = 400 if self.command == "GET" else 413
                        return self.reply(status, {"error": "طول درخواست نامعتبر است."})
                    if not re.fullmatch(r"[0-9]+", declared):
                        return self.reply(400, {"error": "طول درخواست نامعتبر است."})
                    if len(declared) > 20:
                        status = 400 if self.command == "GET" else 413
                        return self.reply(status, {"error": "طول درخواست نامعتبر است."})
                if self.command == "GET":
                    if declared is not None and int(declared) != 0:
                        # Do not leave a body unread on an authenticated GET.
                        # Integration routes already enforced this contract.
                        return self.reply(400, {"error": "GET نباید داده داشته باشد."})
                if endpoint.startswith("/integrations/v1/"):
                    # Never expose integration credentials over the plaintext
                    # LAN handler. The router rechecks TLS and current ACL.
                    if service.integration_router is None:
                        return self.reply(404, {"error": "مسیر پیدا نشد."})
                    # Header framing was validated globally before dispatch.
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except (ValueError, TypeError):
                        return self.reply(400, {"error": "طول درخواست نامعتبر است."})
                    if length < 0 or length > 8192:
                        return self.reply(413, {"error": "حجم درخواست نامعتبر است."})
                    if self.command == "GET" and length:
                        return self.reply(400, {"error": "GET نباید داده داشته باشد."})
                    body = self.rfile.read(length) if length else b""
                    outcome = service.integration_router.handle(
                        self.command, self.path, dict(self.headers.items()), body)
                    self.send_response(outcome.status)
                    for key, value in outcome.headers.items():
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(outcome.body)))
                    self.end_headers()
                    self.wfile.write(outcome.body)
                    return
                if endpoint not in ("/api/login", "/api/state", "/api/me", "/api/display-roles", "/api/users", "/api/user",
                                    "/api/profiles", "/api/profile", "/api/password",
                                    "/api/reset-password", "/api/comments", "/api/notifications",
                                    "/api/activity", "/api/collab", "/api/finance", "/api/finance-status",
                                    "/api/finance-overview", "/api/accounting",
                                    "/api/standalone-accounting", "/api/standalone-accounting/prepare",
                                    "/api/standalone-accounting/quote",
                                    "/api/rial-journal", "/api/rial-journal/activate",
                                    "/api/rules", "/api/scheduler", "/api/attachments",
                                    "/api/buttons"):
                    return self.reply(404, {"error": "مسیر پیدا نشد."})
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                payload = {}
                if self.command == "POST":
                    # Do not spend up to 16 MB decoding anonymous JSON before
                    # the destination's normal token/ACL check. Close this
                    # connection because the denied request body is unread.
                    if endpoint != "/api/login":
                        try:
                            service.account_for(token)
                        except PermissionError as error:
                            self.close_connection = True
                            return self.reply(403, {"error": str(error)})
                    # Always validate the byte limit before reading POST bodies.
                    # Returning 415 with an unread body can cause Windows TCP
                    # to reset the connection before the client receives JSON.
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except (ValueError, TypeError):
                        return self.reply(400, {"error": "ساختار JSON نامعتبر است."})
                    if length <= 0 or length > 16_000_000:
                        return self.reply(413, {"error": "حجم درخواست نامعتبر است."})
                    if endpoint == "/api/login" and length > MAX_LAN_LOGIN_BODY_BYTES:
                        return self.reply(413, {"error": "حجم درخواست ورود بیش از حد مجاز است."})
                    content_type = self.headers.get("Content-Type", "")
                    if content_type.split(";", 1)[0].strip().lower() != "application/json":
                        # Read only an already bounded declared body so HTTP
                        # error responses are observable instead of racing a
                        # TCP reset triggered by unread request data.
                        self.rfile.read(length)
                        return self.reply(415, {"error": "درخواست باید JSON باشد."})
                    try:
                        payload = json.loads(self.rfile.read(length))
                        if not isinstance(payload, dict):
                            raise ValueError()
                    except (TypeError, ValueError, json.JSONDecodeError):
                        return self.reply(400, {"error": "ساختار JSON نامعتبر است."})
                try:
                    if self.command == "POST" and endpoint == "/api/login":
                        return self.reply(200, service.authenticate(payload.get("username"),
                                                                     payload.get("password"), self.client_address[0]))
                    if self.command == "GET" and endpoint == "/api/state":
                        return self.reply(200, service.read_state(token))
                    if self.command == "GET" and endpoint == "/api/me":
                        return self.reply(200, {"user": service.current_user(token)})
                    if self.command == "POST" and endpoint == "/api/state":
                        return self.reply(200, service.write_state(token, payload.get("state"),
                                                                    payload.get("revision")))
                    if self.command == "GET" and endpoint in ("/api/comments", "/api/notifications", "/api/activity", "/api/rules"):
                        params = parse_qs(urlparse(self.path).query)
                        return self.reply(200, {"items": service.collab_read(
                            token, endpoint.removeprefix("/api/"), params.get(
                                "projectId" if endpoint == "/api/rules" else "cardId", [""])[0])})
                    if self.command == "POST" and endpoint == "/api/collab":
                        return self.reply(200, {"result": service.collab_command(token, payload)})
                    if self.command == "GET" and endpoint == "/api/buttons":
                        params = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                        if set(params) - {"projectId", "boardId"} or any(len(v) != 1 for v in params.values()):
                            raise ValueError("Invalid button listing query")
                        return self.reply(200, {"items": service.automation_buttons_list(
                            token, {key: value[0] for key, value in params.items()})})
                    if self.command == "POST" and endpoint == "/api/buttons":
                        return self.reply(200, {"result": service.automation_buttons_command(token, payload)})
                    if self.command == "GET" and endpoint == "/api/finance":
                        params = parse_qs(urlparse(self.path).query)
                        return self.reply(200, {"invoices": service.finance_read(
                            token, params.get("projectId", [""])[0])})
                    if self.command == "GET" and endpoint == "/api/accounting":
                        params = parse_qs(urlparse(self.path).query)
                        return self.reply(200, service.accounting_read(
                            token, params.get("projectId", [""])[0]))
                    if self.command == "GET" and endpoint == "/api/standalone-accounting":
                        if urlparse(self.path).query:
                            raise ValueError("Standalone accounting read takes no query arguments")
                        return self.reply(200, service.standalone_accounting_read(token))
                    if self.command == "GET" and endpoint == "/api/rial-journal":
                        params = parse_qs(urlparse(self.path).query)
                        if set(params) != {"companyId", "fiscalPeriodId"} or any(
                                len(values) != 1 for values in params.values()):
                            raise ValueError("Company and fiscal period must be specified exactly once")
                        return self.reply(200, service.rial_journal_read(
                            token, {"companyId": params["companyId"][0],
                                    "fiscalPeriodId": params["fiscalPeriodId"][0]}))
                    if self.command == "GET" and endpoint == "/api/finance-overview":
                        params = parse_qs(urlparse(self.path).query)
                        return self.reply(200, service.finance_overview(
                            token, params.get("projectId", [""])[0],
                            params.get("startDate", [""])[0],
                            params.get("endDate", [""])[0]))
                    if self.command == "GET" and endpoint == "/api/finance-status":
                        return self.reply(200, service.finance_status(token))
                    if self.command == "POST" and endpoint == "/api/finance":
                        return self.reply(200, {"result": service.finance_command(token, payload)})
                    if self.command == "POST" and endpoint == "/api/accounting":
                        return self.reply(200, {"result": service.accounting_command(token, payload)})
                    if self.command == "POST" and endpoint == "/api/standalone-accounting":
                        return self.reply(200, service.standalone_accounting_command(token, payload))
                    if self.command == "POST" and endpoint == "/api/standalone-accounting/prepare":
                        return self.reply(200, service.standalone_accounting_prepare(token, payload))
                    if self.command == "POST" and endpoint == "/api/standalone-accounting/quote":
                        return self.reply(200, service.standalone_accounting_quote(token, payload))
                    if self.command == "POST" and endpoint == "/api/rial-journal/activate":
                        return self.reply(200, {"result": service.rial_journal_activate(token, payload)})
                    if self.command == "POST" and endpoint == "/api/scheduler":
                        if payload != {"run": True}:
                            raise ValueError("Invalid scheduler command")
                        return self.reply(200, {"result": service.run_scheduler(token)})
                    if self.command == "GET" and endpoint == "/api/attachments":
                        params = parse_qs(urlparse(self.path).query)
                        kind = params.get("kind", [""])[0]
                        if kind not in {"list", "read", "preview"}:
                            raise ValueError("Invalid attachment operation")
                        return self.reply(200, {"result": service.attachment_action(
                            token, kind, card_id=params.get("cardId", [""])[0],
                            attachment_id=params.get("attachmentId", [""])[0])})
                    if self.command == "POST" and endpoint == "/api/attachments":
                        if payload.get("kind") not in ("upload", "delete"):
                            raise ValueError("Invalid attachment operation")
                        return self.reply(200, {"result": service.attachment_action(
                            token, payload["kind"], payload=payload)})
                    if self.command == "GET" and endpoint == "/api/users":
                        return self.reply(200, {"users": service.list_users(token)})
                    if self.command == "GET" and endpoint == "/api/display-roles":
                        return self.reply(200, {"roles": service.list_display_roles(token)})
                    if self.command == "POST" and endpoint == "/api/display-roles":
                        if payload.get("action") == "delete":
                            if set(payload) != {"action", "id"}:
                                raise ValueError("Invalid display role deletion request")
                            return self.reply(200, {"ok": service.delete_display_role(token, payload["id"])})
                        return self.reply(200, {"role": service.upsert_display_role(token, payload)})
                    if self.command == "DELETE" and endpoint == "/api/display-roles":
                        params = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                        if set(params) != {"id"} or len(params["id"]) != 1:
                            raise ValueError("Display role id is required")
                        return self.reply(200, {"ok": service.delete_display_role(token, params["id"][0])})
                    if self.command == "GET" and endpoint == "/api/profiles":
                        return self.reply(200, {"users": service.list_profiles(token)})
                    if self.command == "POST" and endpoint == "/api/profile":
                        return self.reply(200, {"user": service.update_profile(token, payload)})
                    if self.command == "POST" and endpoint == "/api/password":
                        return self.reply(200, {"ok": service.change_password(
                            token, payload.get("current"), payload.get("newPassword"))})
                    if self.command == "POST" and endpoint == "/api/reset-password":
                        return self.reply(200, {"ok": service.reset_password(
                            token, payload.get("username"), payload.get("newPassword"))})
                    if self.command == "POST" and endpoint == "/api/user":
                        return self.reply(200, {"user": service.upsert_user(token, payload)})
                    if self.command == "POST" and endpoint == "/api/users":
                        return self.reply(200, {"ok": service.delete_user(token, payload.get("username"))})
                    return self.reply(405, {"error": "روش درخواست معتبر نیست."})
                except PermissionError as e:
                    return self.reply(403, {"error": str(e)})
                except ValueError as e:
                    return self.reply(400, {"error": str(e)})
                except RuntimeError as e:
                    status = 409 if str(e).startswith("CONFLICT:") else 400
                    return self.reply(status, {"error": str(e)})

            def do_GET(self):
                self.process()

            def do_POST(self):
                self.process()

            def do_DELETE(self):
                self.process()

            def do_PATCH(self):
                self.process()

        server = ThreadingHTTPServer((self.bind, self.port), Handler)
        try:
            if tls_context:
                server.socket = tls_context.wrap_socket(server.socket, server_side=True)
        except Exception:
            server.server_close()
            raise
        self.server = server
        if tls_context:
            from integration_api_v1 import IntegrationRouter
            self.integration_router = IntegrationRouter(self)
        else:
            self.integration_router = None
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.port

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=3)
            self.server = None
            self.integration_router = None
