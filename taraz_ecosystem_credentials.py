"""Windows-only, host-scoped ecosystem integration credential vault.

The native authenticated host must select an EXISTING dedicated, private
directory and authorize each operation. This module has no APPDATA discovery,
installer, listener, ledger access, pairing transport or privilege escalation.
Do not expose its token-returning methods directly to a WebView/HTTP client.

DPAPI encryption uses the current Windows principal and additional entropy
bound to the absolute vault path. A canonical authenticated inner payload
binds all public metadata; there is no plaintext token fallback. An offline
rollback of an entire previously valid vault cannot be detected without a
separate trusted monotonic counter, which is not supplied by this module.
"""
from __future__ import annotations

from contextlib import contextmanager
import base64
import csv
import ctypes
from ctypes import wintypes
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import subprocess
import threading
import uuid

from taraz_ai_chat_store import _protect, _unprotect

_FILE = "taraz-ecosystem-credentials.json"
_LOCK_FILE = ".taraz-ecosystem-credentials.lock"
_INTERRUPTED_UPDATE = re.compile(r"\.taraz-credential-update-[0-9a-f]{32}\Z")
_FORMAT = "taraz-ecosystem-dpapi-credentials"
_VERSION = 1
_HEX32 = re.compile(r"[a-f0-9]{32}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_PEER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{64,128}\Z")
_MADAR_ISSUED_TOKEN = re.compile(r"mdv1_[A-Za-z0-9_-]{64}\Z")
_MAX_FILE = 128 * 1024
_MAX_PEERS = 64
_THREAD_LOCK = threading.RLock()


class CredentialVaultError(PermissionError):
    """Invalid scope, missing Windows key, damaged vault or forbidden action."""


def _must_windows() -> None:
    if os.name != "nt":
        raise CredentialVaultError("Windows current-user DPAPI is required")


def _safe_root(root: Path) -> Path:
    _must_windows()
    if not root.is_absolute() or not root.is_dir() or root.name in ("", ".", ".."):
        raise CredentialVaultError("Explicit existing private vault directory required")
    for component in (root, *root.parents):
        try:
            st = component.lstat()
        except OSError as exc:
            raise CredentialVaultError("Vault root is unavailable") from exc
        if (component.is_symlink() or not stat.S_ISDIR(st.st_mode) or
                getattr(st, "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise CredentialVaultError("Linked or reparse-point vault root refused")
    # Refuse operational folders without opening even one of their contents.
    if root.name.casefold() in {"taraz", "books", "roaming", "localappdata", "appdata"}:
        raise CredentialVaultError("Dedicated credential-only directory required")
    return root


def _regular(path: Path) -> os.stat_result:
    try:
        st = path.lstat()
    except OSError as exc:
        raise CredentialVaultError("Missing credential vault member") from exc
    if (path.is_symlink() or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or
            getattr(st, "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise CredentialVaultError("Linked, hardlinked or nonregular vault file refused")
    return st


def _inventory(root: Path, *, initializing: bool = False) -> None:
    allowed = {_LOCK_FILE} if initializing else {_LOCK_FILE, _FILE}
    # A crash after securely writing a replacement but before os.replace()
    # leaves exactly one abandoned temp. The committed document remains the
    # sole authority; allow only our bounded temp naming scheme for cleanup.
    if any(item.name not in allowed and
           (initializing or not _INTERRUPTED_UPDATE.fullmatch(item.name))
           for item in root.iterdir()):
        raise CredentialVaultError("Vault root must be dedicated to credentials")
    for item in root.iterdir():
        _regular(item)
        _private_acl(item)


def _cleanup_interrupted_updates(root: Path) -> None:
    """Only under the exclusive vault lock; never promote staged ciphertext."""
    for item in root.iterdir():
        if _INTERRUPTED_UPDATE.fullmatch(item.name):
            _regular(item)
            item.unlink()


def _principal_sid() -> str:
    try:
        result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                                capture_output=True, text=True, timeout=10, check=True)
        data = list(csv.reader(io.StringIO(result.stdout)))
    except (OSError, subprocess.SubprocessError, csv.Error) as exc:
        raise CredentialVaultError("Cannot verify Windows user principal") from exc
    if (len(data) != 1 or len(data[0]) != 2 or
            not re.fullmatch(r"S-1-(?:\d+-)+\d+", data[0][1])):
        raise CredentialVaultError("Cannot verify Windows user SID")
    return data[0][1]


def _private_acl(path: Path) -> None:
    """Atomically replace AND verify explicit Windows ACL on the real handle.

    The older icacls /inheritance:r + /grant:r retained explicit Everyone
    or other-account access grants. Exact protected DACL prevents that leak.
    """
    _must_windows()
    path = Path(path)
    try:
        info = path.lstat()
        if (path.is_symlink() or
                not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)
                or getattr(info, "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise CredentialVaultError("Unsafe credential ACL target")
    except OSError:
        raise CredentialVaultError("Credential ACL target unavailable") from None
    sid = _principal_sid()
    pointer = ctypes.c_void_p
    dword = wintypes.DWORD
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR, dword, dword, pointer, dword, dword, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.LocalFree.argtypes = (pointer,)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR, dword, ctypes.POINTER(pointer), ctypes.POINTER(dword))
    advapi.GetSecurityDescriptorDacl.argtypes = (
        pointer, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(pointer),
        ctypes.POINTER(wintypes.BOOL))
    advapi.SetSecurityInfo.argtypes = (
        wintypes.HANDLE, dword, dword, pointer, pointer, pointer, pointer)
    advapi.SetSecurityInfo.restype = dword
    advapi.GetSecurityInfo.argtypes = (
        wintypes.HANDLE, dword, dword, ctypes.POINTER(pointer),
        ctypes.POINTER(pointer), ctypes.POINTER(pointer),
        ctypes.POINTER(pointer), ctypes.POINTER(pointer))
    advapi.GetSecurityInfo.restype = dword
    advapi.GetSecurityDescriptorControl.argtypes = (
        pointer, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(dword))
    advapi.GetAclInformation.argtypes = (pointer, pointer, dword, dword)
    advapi.GetAce.argtypes = (pointer, dword, ctypes.POINTER(pointer))
    advapi.ConvertSidToStringSidW.argtypes = (
        pointer, ctypes.POINTER(pointer))

    # READ_CONTROL | WRITE_DAC; share reads/writes without delete/rename.
    # BACKUP_SEMANTICS opens directory handles. OPEN_REPARSE_POINT prevents
    # following a link created after the first lstat().
    handle = kernel.CreateFileW(str(path), 0x00060000, 0x00000003,
                                None, 3, 0x02200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise CredentialVaultError("Cannot lock credential ACL target")
    try:
        descriptor = pointer()
        sddl = "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;" + sid + ")"
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None):
            raise CredentialVaultError("Cannot create protected credential ACL")
        try:
            present, acl, defaulted = (
                wintypes.BOOL(), pointer(), wintypes.BOOL())
            if not advapi.GetSecurityDescriptorDacl(
                    descriptor, ctypes.byref(present), ctypes.byref(acl),
                    ctypes.byref(defaulted)) or not present.value or not acl:
                raise CredentialVaultError("Invalid credential ACL descriptor")
            if advapi.SetSecurityInfo(
                    handle, 1, 0x80000004, None, None, acl, None):
                raise CredentialVaultError("Cannot enforce protected credential ACL")
        finally:
            kernel.LocalFree(descriptor)

        observed_acl, observed_descriptor = pointer(), pointer()
        if advapi.GetSecurityInfo(
                handle, 1, 0x00000004, None, None,
                ctypes.byref(observed_acl), None,
                ctypes.byref(observed_descriptor)):
            raise CredentialVaultError("Cannot verify credential ACL")
        try:
            controls, revision = wintypes.WORD(), dword()
            if (not observed_acl or not advapi.GetSecurityDescriptorControl(
                    observed_descriptor, ctypes.byref(controls),
                    ctypes.byref(revision)) or not controls.value & 0x1000):
                raise CredentialVaultError("Credential ACL is not protected")

            class AclSize(ctypes.Structure):
                _fields_ = [("count", dword), ("used", dword), ("free", dword)]

            info = AclSize()
            if not advapi.GetAclInformation(
                    observed_acl, ctypes.byref(info),
                    ctypes.sizeof(info), 2) or info.count != 3:
                raise CredentialVaultError("Unexpected credential trustees")
            observed = set()
            for index in range(info.count):
                ace = pointer()
                if not advapi.GetAce(observed_acl, index, ctypes.byref(ace)):
                    raise CredentialVaultError("Cannot verify credential ACE")
                kind, flags, size, rights = struct.unpack(
                    "<BBHI", ctypes.string_at(ace, 8))
                if kind != 0 or flags != 0 or size < 16 or rights != 0x001F01FF:
                    raise CredentialVaultError("Unsafe credential ACE")
                trustee = pointer()
                if not advapi.ConvertSidToStringSidW(
                        pointer(ace.value + 8), ctypes.byref(trustee)):
                    raise CredentialVaultError("Cannot verify credential trustee")
                try:
                    observed.add(ctypes.wstring_at(trustee))
                finally:
                    kernel.LocalFree(trustee)
            if observed != {sid, "S-1-5-18", "S-1-5-32-544"}:
                raise CredentialVaultError("Unexpected credential trustees")
        finally:
            kernel.LocalFree(observed_descriptor)
    finally:
        kernel.CloseHandle(handle)


def _create_secure_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    completed = False
    try:
        _private_acl(path)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        completed = True
    finally:
        os.close(fd)
        if not completed:
            # On Windows the handle must close *before* removing a failed
            # CREATE-ONLY file. It is exclusively owned by this call.
            try:
                path.unlink()
            except OSError:
                pass


@contextmanager
def _locked(root: Path, *, initializing: bool = False):
    with _THREAD_LOCK:
        _safe_root(root)
        lock = root / _LOCK_FILE
        if os.path.lexists(root / _FILE) and not os.path.lexists(lock):
            raise CredentialVaultError("Credential vault lock was removed")
        # Check the entire dedicated inventory before changing ANY ACL.
        # Harden existing child files first so Windows removing inherited
        # access on the parent cannot temporarily lock us out of a child.
        _inventory(root, initializing=initializing)
        _private_acl(root)
        if not os.path.lexists(lock):
            if not initializing:
                raise CredentialVaultError("Credential vault has not been initialized")
            try:
                _create_secure_file(lock, b"0")
            except FileExistsError:
                pass
        _regular(lock)
        _inventory(root)
        import msvcrt
        with lock.open("r+b") as handle:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            except OSError as exc:
                raise CredentialVaultError("Credential vault lock unavailable") from exc
            try:
                _safe_root(root)
                _inventory(root)
                _cleanup_interrupted_updates(root)
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _canonical(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _unique(items):
    result = {}
    for key, value in items:
        if key in result:
            raise CredentialVaultError("Duplicate vault JSON property")
        result[key] = value
    return result


def _parse(raw: bytes) -> dict:
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(
                                CredentialVaultError("Nonfinite vault JSON")))
    except (UnicodeError, ValueError, RecursionError, TypeError) as exc:
        raise CredentialVaultError("Corrupt credential document") from exc
    if type(result) is not dict or raw != _canonical(result):
        raise CredentialVaultError("Noncanonical credential document")
    return result


def _id(value: str, name: str) -> str:
    if type(value) is not str or not _HEX32.fullmatch(value):
        raise CredentialVaultError("Invalid " + name)
    return value


def _pin(value: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise CredentialVaultError("A pinned SHA256 certificate fingerprint is required")
    return value


def _peer(value: str) -> str:
    if type(value) is not str or not _PEER.fullmatch(value):
        raise CredentialVaultError("Invalid peer ID")
    return value


def _scope(root: Path) -> str:
    # DPAPI entropy is independent of attacker-controlled outer metadata.
    return "TARAZ-ECOSYSTEM-VAULT-V1:" + str(root.resolve()).casefold()


def _validate_state(data: dict) -> dict:
    if (type(data) is not dict or set(data) !=
            {"format", "version", "installationId", "generation", "peers"} or
            data["format"] != _FORMAT or type(data["version"]) is not int or
            data["version"] != _VERSION or
            type(data["generation"]) is not int or data["generation"] < 0 or
            type(data["peers"]) is not list or len(data["peers"]) > _MAX_PEERS):
        raise CredentialVaultError("Invalid credential vault schema")
    _id(data["installationId"], "installation ID")
    seen = set()
    for entry in data["peers"]:
        if (type(entry) is not dict or set(entry) !=
                {"workspaceId", "peerId", "certSha256", "token", "revoked", "generation"}
                and set(entry) !=
                {"workspaceId", "peerId", "certSha256", "token", "revoked", "generation", "endpoint"} or
                type(entry["revoked"]) is not bool or type(entry["generation"]) is not int or
                not 1 <= entry["generation"] <= data["generation"]):
            raise CredentialVaultError("Invalid peer credential record")
        workspace, peer = _id(entry["workspaceId"], "workspace ID"), _peer(entry["peerId"])
        _pin(entry["certSha256"])
        if "endpoint" in entry and (type(entry["endpoint"]) is not str or
                                    len(entry["endpoint"]) > 160 or
                                    not entry["endpoint"].startswith("https://")):
            raise CredentialVaultError("Invalid stored peer transport endpoint")
        key = (workspace, peer)
        if key in seen:
            raise CredentialVaultError("Duplicate peer identity")
        seen.add(key)
        token = entry["token"]
        if (entry["revoked"] and token is not None or
                not entry["revoked"] and
                (type(token) is not str or not _TOKEN.fullmatch(token))):
            raise CredentialVaultError("Invalid peer token state")
    if data["generation"] == 0 and data["peers"]:
        raise CredentialVaultError("Invalid initial credential vault generation")
    return data


class TarazEcosystemCredentialVault:
    """An explicit, dedicated private directory; no ambient profile discovery."""

    def __init__(self, root: Path):
        self.root = _safe_root(Path(root))
        self.path = self.root / _FILE

    def _load(self) -> dict:
        _regular(self.path)
        if self.path.stat().st_size > _MAX_FILE:
            raise CredentialVaultError("Credential document exceeds maximum size")
        with self.path.open("rb") as reader:
            raw = reader.read(_MAX_FILE + 1)
        outer = _parse(raw)
        if (set(outer) != {"format", "version", "installationId", "generation", "sealed"} or
                outer["format"] != _FORMAT or type(outer["version"]) is not int or
                outer["version"] != _VERSION or
                type(outer["generation"]) is not int or outer["generation"] < 0 or
                type(outer["sealed"]) is not str or len(outer["sealed"]) > _MAX_FILE):
            raise CredentialVaultError("Invalid public credential envelope")
        _id(outer["installationId"], "installation ID")
        try:
            encoded = base64.b64decode(outer["sealed"], validate=True)
            inner = _parse(_unprotect(encoded, _scope(self.root)).encode("utf-8"))
        except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
            raise CredentialVaultError("Credential DPAPI decryption or authentication failed") from exc
        _validate_state(inner)
        if (inner["installationId"] != outer["installationId"] or
                inner["generation"] != outer["generation"]):
            raise CredentialVaultError("Credential metadata authentication failed")
        return inner

    def _save(self, data: dict, *, create: bool = False) -> None:
        _validate_state(data)
        sealed = base64.b64encode(_protect(_canonical(data).decode("utf-8"),
                                           _scope(self.root))).decode("ascii")
        outer = {"format": _FORMAT, "version": _VERSION,
                 "installationId": data["installationId"],
                 "generation": data["generation"], "sealed": sealed}
        payload = _canonical(outer)
        if len(payload) > _MAX_FILE:
            raise CredentialVaultError("Credential vault capacity exceeded")
        if create:
            _create_secure_file(self.path, payload)
            return
        _regular(self.path)
        temp = self.root / (".taraz-credential-update-" + secrets.token_hex(16))
        try:
            _create_secure_file(temp, payload)
            # No filesystem-based lock can prevent an unauthorized process from
            # editing the file. The host must keep this directory private.
            _regular(self.path)
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()

    def initialize(self) -> str:
        """Create a fresh installation identity only in an empty private root."""
        with _locked(self.root, initializing=True):
            if os.path.lexists(self.path):
                raise CredentialVaultError("Vault already exists; open it instead")
            _inventory(self.root, initializing=True)
            document = {"format": _FORMAT, "version": _VERSION,
                        "installationId": uuid.uuid4().hex,
                        "generation": 0, "peers": []}
            self._save(document, create=True)
            return document["installationId"]

    def installation_id(self) -> str:
        with _locked(self.root):
            return self._load()["installationId"]

    def list_peers(self) -> list[dict]:
        """Safe metadata only; integration tokens are never returned here."""
        with _locked(self.root):
            data = self._load()
            return [{**{field: entry[field] for field in
                     ("workspaceId", "peerId", "certSha256", "revoked", "generation")}
                     , "endpoint": entry.get("endpoint", "")}
                    for entry in data["peers"]]

    @staticmethod
    def _find(data: dict, workspace_id: str, peer_id: str) -> dict:
        workspace_id, peer_id = _id(workspace_id, "workspace ID"), _peer(peer_id)
        for entry in data["peers"]:
            if entry["workspaceId"] == workspace_id and entry["peerId"] == peer_id:
                return entry
        raise CredentialVaultError("Unknown paired peer")

    def pair(self, *, workspace_id: str, peer_id: str, cert_sha256: str) -> dict:
        """Generate and return one new 384-bit token to trusted pairing code."""
        workspace_id, peer_id, cert_sha256 = (_id(workspace_id, "workspace ID"),
                                             _peer(peer_id), _pin(cert_sha256))
        with _locked(self.root):
            data = self._load()
            if len(data["peers"]) >= _MAX_PEERS:
                raise CredentialVaultError("Maximum paired peers reached")
            if any(entry["workspaceId"] == workspace_id and entry["peerId"] == peer_id
                   for entry in data["peers"]):
                raise CredentialVaultError("Peer already registered; explicit rotation required")
            token = secrets.token_urlsafe(48)
            data["generation"] += 1
            data["peers"].append({"workspaceId": workspace_id, "peerId": peer_id,
                                  "certSha256": cert_sha256, "token": token,
                                  "revoked": False, "generation": data["generation"]})
            self._save(data)
            return {"installationId": data["installationId"], "workspaceId": workspace_id,
                    "peerId": peer_id, "certSha256": cert_sha256, "token": token}

    def store_issued_credential(self, *, workspace_id: str, peer_id: str,
                                cert_sha256: str, issued_token: str,
                                endpoint: str = "") -> dict:
        """Persist a credential actually issued by a pinned Madar HTTPS peer.

        Only a trusted native pairing client may call this after validating the
        live TLS certificate, exact response schema and installation identity.
        Do NOT expose this method over WebView/HTTP. A locally generated token
        is NOT interchangeable with the peer's actual issued credential.
        """
        workspace_id, peer_id, cert_sha256 = (_id(workspace_id, "workspace ID"),
                                             _peer(peer_id), _pin(cert_sha256))
        if type(issued_token) is not str or not _MADAR_ISSUED_TOKEN.fullmatch(issued_token):
            raise CredentialVaultError("Invalid peer-issued integration credential")
        if type(endpoint) is not str or not 1 <= len(endpoint) <= 160 or not endpoint.startswith("https://"):
            raise CredentialVaultError("Authenticated peer endpoint required")
        with _locked(self.root):
            data = self._load()
            existing = next((entry for entry in data["peers"] if
                             entry["workspaceId"] == workspace_id and
                             entry["peerId"] == peer_id), None)
            if existing is not None:
                # Certificate renewal is an explicit fresh one-time pairing,
                # never automatic pin substitution during a read. The native
                # client must first verify the newly administrator-approved
                # certificate against the presented SHA256 and redeem a
                # fresh, single-use code over that verified TLS channel.
                existing["certSha256"] = cert_sha256
                existing["token"] = issued_token
                existing["endpoint"] = endpoint
                existing["revoked"] = False
                data["generation"] += 1
                existing["generation"] = data["generation"]
            else:
                if len(data["peers"]) >= _MAX_PEERS:
                    raise CredentialVaultError("Maximum paired peers reached")
                data["generation"] += 1
                data["peers"].append({"workspaceId": workspace_id, "peerId": peer_id,
                                      "certSha256": cert_sha256,
                                      "endpoint": endpoint,
                                      "token": issued_token, "revoked": False,
                                      "generation": data["generation"]})
            self._save(data)
            return {"installationId": data["installationId"],
                    "workspaceId": workspace_id, "peerId": peer_id,
                    "certSha256": cert_sha256}

    def require_token(self, *, workspace_id: str, peer_id: str,
                      cert_sha256: str) -> str:
        """Trusted host only: bind token access to workspace, peer and TLS pin."""
        _pin(cert_sha256)
        with _locked(self.root):
            entry = self._find(self._load(), workspace_id, peer_id)
            if entry["revoked"] or not hmac.compare_digest(entry["certSha256"], cert_sha256):
                raise CredentialVaultError("Peer revoked or certificate pin mismatch")
            return entry["token"]

    def rotate(self, *, workspace_id: str, peer_id: str,
               cert_sha256: str) -> str:
        """Replace an active peer token; the previous token is not retained."""
        _pin(cert_sha256)
        with _locked(self.root):
            data = self._load()
            entry = self._find(data, workspace_id, peer_id)
            if entry["revoked"] or not hmac.compare_digest(entry["certSha256"], cert_sha256):
                raise CredentialVaultError("Peer revoked or certificate pin mismatch")
            token = secrets.token_urlsafe(48)
            data["generation"] += 1
            entry["token"] = token
            entry["generation"] = data["generation"]
            self._save(data)
            return token

    def revoke(self, *, workspace_id: str, peer_id: str) -> None:
        """Permanently remove token access for this peer from the active vault."""
        with _locked(self.root):
            data = self._load()
            entry = self._find(data, workspace_id, peer_id)
            if entry["revoked"]:
                raise CredentialVaultError("Peer is already revoked")
            data["generation"] += 1
            entry["token"] = None
            entry["revoked"] = True
            entry["generation"] = data["generation"]
            self._save(data)


__all__ = ["TarazEcosystemCredentialVault", "CredentialVaultError"]
