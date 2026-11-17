"""DPAPI-sealed online-AI credential vault. No ambient profile discovery.

An authenticated native Taraz host must select and provision an existing,
private, DEDICATED directory. Never expose privileged methods to WebView
clients. No code here accesses accounting, UI, SQL, Internet or logs.

The entire canonical record (including API key) is bound via current-user
Windows DPAPI to the absolute directory. Clearing a credential revokes its
use by this module; it cannot erase old disk snapshots or provider keys.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import secrets
import threading

from taraz_ai_chat_store import _protect, _unprotect
from taraz_ecosystem_credentials import (
    CredentialVaultError, _create_secure_file, _regular, _safe_root,
)

_FILE = "taraz-online-ai-credentials.json"
_LOCK = ".taraz-online-ai-credentials.lock"
_TEMP = re.compile(r"\.taraz-online-ai-update-[0-9a-f]{32}\Z")
_FORMAT = "taraz-online-ai-dpapi-v1"
_KEY = re.compile(r"[\x21-\x7e]{16,512}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,99}\Z")
_MAX_DOC = 16384
_THREAD_LOCK = threading.RLock()
_SUPPORTED = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
}


class OnlineCredentialError(PermissionError):
    """Denied or corrupted private online credentials; never contains secrets."""


def validate_provider(provider: str, endpoint: str, model: str) -> None:
    if (type(provider) is not str or provider not in _SUPPORTED or
            type(endpoint) is not str or endpoint != _SUPPORTED[provider]):
        raise OnlineCredentialError("Unsupported exact HTTPS provider endpoint")
    if type(model) is not str or not _MODEL.fullmatch(model):
        raise OnlineCredentialError("Invalid explicitly selected model")


def _rate(value, field: str) -> str:
    # Require decimal text, not a rounded binary float or unbounded exponent.
    if type(value) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{1,6})?", value):
        raise OnlineCredentialError("Invalid " + field)
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise OnlineCredentialError("Invalid " + field) from None
    if not Decimal("0.01") <= amount <= Decimal("1000"):
        raise OnlineCredentialError("Unapproved " + field + " range")
    return value


def _check_root(root: Path) -> Path:
    try:
        root = _safe_root(root)
    except (OSError, ValueError, PermissionError):
        raise OnlineCredentialError("Existing explicit private directory required") from None
    if root.name.casefold() in {"taraz", "books", "appdata", "roaming", "local"}:
        raise OnlineCredentialError("Operational profile cannot be used as credential vault")
    return root


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _unique(pairs):
    out = {}
    for name, value in pairs:
        if name in out:
            raise OnlineCredentialError("Duplicate vault field")
        out[name] = value
    return out


def _read_canonical(blob: bytes) -> dict:
    if not blob or len(blob) > _MAX_DOC:
        raise OnlineCredentialError("Invalid credential document size")
    try:
        value = json.loads(blob.decode("ascii"), object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               OnlineCredentialError("Invalid numeric value")))
        if type(value) is not dict or _canonical(value) != blob:
            raise OnlineCredentialError("Noncanonical credential document")
        return value
    except (UnicodeError, ValueError, RecursionError, TypeError):
        raise OnlineCredentialError("Corrupt credential document") from None


def _scope(root: Path) -> str:
    return "TARAZ-ONLINE-AI-VAULT-V1:" + str(root.resolve()).casefold()


def _state(state: dict) -> dict:
    if (type(state) is not dict or set(state) !=
            {"format", "generation", "configuration"} or
            state["format"] != _FORMAT or type(state["generation"]) is not int or
            not 0 <= state["generation"] <= 1000000000):
        raise OnlineCredentialError("Invalid vault schema")
    record = state["configuration"]
    if record is None:
        return state
    if (type(record) is not dict or set(record) !=
            {"provider", "endpoint", "model", "apiKey",
             "inputUsdPerMillion", "outputUsdPerMillion"}):
        raise OnlineCredentialError("Invalid provider configuration")
    validate_provider(record["provider"], record["endpoint"], record["model"])
    if type(record["apiKey"]) is not str or not _KEY.fullmatch(record["apiKey"]):
        raise OnlineCredentialError("Invalid sealed API credential")
    _rate(record["inputUsdPerMillion"], "input price")
    _rate(record["outputUsdPerMillion"], "output price")
    if state["generation"] < 1:
        raise OnlineCredentialError("Invalid credential generation")
    return state


@contextmanager
def _exclusive(root: Path, *, initializing=False):
    """Windows process lock + thread lock. Private existing root is mandatory."""
    import msvcrt
    with _THREAD_LOCK:
        _check_root(root)
        lock = root / _LOCK
        doc = root / _FILE
        if not os.path.lexists(lock):
            if os.path.lexists(doc) or not initializing:
                raise OnlineCredentialError("Missing vault lock or initialization")
            if list(root.iterdir()):
                raise OnlineCredentialError("Credential directory is not dedicated")
            try:
                _create_secure_file(lock, b"0")
            except FileExistsError:
                pass
        _regular(lock)
        with lock.open("r+b") as handle:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            except OSError:
                raise OnlineCredentialError("Credential lock unavailable") from None
            try:
                _check_root(root)
                items = list(root.iterdir())
                for item in items:
                    if item.name not in {_LOCK, _FILE} and not _TEMP.fullmatch(item.name):
                        raise OnlineCredentialError("Credential root contains unexpected data")
                    try:
                        _regular(item)
                    except CredentialVaultError:
                        raise OnlineCredentialError(
                            "Linked or nonregular credential vault member refused") from None
                for item in items:
                    if _TEMP.fullmatch(item.name):
                        item.unlink()
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class TarazOnlineAiCredentialVault:
    """Host-only storage; the API key never appears in metadata or file plaintext."""

    def __init__(self, root: Path):
        self.root = _check_root(Path(root))
        self.path = self.root / _FILE

    def _read(self):
        try:
            _regular(self.path)
            with self.path.open("rb") as handle:
                outer = _read_canonical(handle.read(_MAX_DOC + 1))
            if set(outer) != {"format", "generation", "sealed"} or outer["format"] != _FORMAT:
                raise OnlineCredentialError("Invalid credential envelope")
            if type(outer["generation"]) is not int or type(outer["sealed"]) is not str:
                raise OnlineCredentialError("Invalid credential envelope types")
            ciphertext = base64.b64decode(outer["sealed"], validate=True)
            cleartext = _unprotect(ciphertext, _scope(self.root))
            state = _state(_read_canonical(cleartext.encode("ascii")))
            if state["generation"] != outer["generation"]:
                raise OnlineCredentialError("Credential envelope authentication failed")
            return state
        except (OSError, UnicodeError, ValueError, RuntimeError,
                CredentialVaultError):
            raise OnlineCredentialError("Credential vault unreadable or DPAPI unavailable") from None

    def _write(self, state: dict, *, create=False):
        _state(state)
        try:
            ciphertext = _protect(_canonical(state).decode("ascii"), _scope(self.root))
        except (OSError, RuntimeError):
            raise OnlineCredentialError("Credential encryption unavailable") from None
        payload = _canonical({
            "format": _FORMAT, "generation": state["generation"],
            "sealed": base64.b64encode(ciphertext).decode("ascii"),
        })
        if len(payload) > _MAX_DOC:
            raise OnlineCredentialError("Credential document exceeds size limit")
        if create:
            _create_secure_file(self.path, payload)
            return
        _regular(self.path)
        temporary = self.root / (".taraz-online-ai-update-" + secrets.token_hex(16))
        try:
            _create_secure_file(temporary, payload)
            _regular(self.path)
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def initialize(self) -> None:
        with _exclusive(self.root, initializing=True):
            if os.path.lexists(self.path):
                raise OnlineCredentialError("Credential vault already exists")
            self._write({"format": _FORMAT, "generation": 0,
                         "configuration": None}, create=True)

    def configure(self, *, provider: str, endpoint: str, model: str, api_key: str,
                  input_usd_per_million: str,
                  output_usd_per_million: str) -> dict:
        """Explicit host action; never accepts arbitrary endpoints or zero pricing."""
        validate_provider(provider, endpoint, model)
        if type(api_key) is not str or not _KEY.fullmatch(api_key):
            raise OnlineCredentialError("Invalid API credential shape")
        record = {
            "provider": provider, "endpoint": endpoint, "model": model,
            "apiKey": api_key,
            "inputUsdPerMillion": _rate(input_usd_per_million, "input price"),
            "outputUsdPerMillion": _rate(output_usd_per_million, "output price"),
        }
        with _exclusive(self.root):
            state = self._read()
            if state["generation"] >= 1000000000:
                raise OnlineCredentialError("Vault update generation exhausted")
            state["generation"] += 1
            state["configuration"] = record
            self._write(state)
            return self._public(state)

    @staticmethod
    def _public(state: dict) -> dict:
        record = state["configuration"]
        return {
            "configured": record is not None, "generation": state["generation"],
            "provider": record["provider"] if record else None,
            "endpoint": record["endpoint"] if record else None,
            "model": record["model"] if record else None,
            "inputUsdPerMillion": record["inputUsdPerMillion"] if record else None,
            "outputUsdPerMillion": record["outputUsdPerMillion"] if record else None,
        }

    def metadata(self) -> dict:
        with _exclusive(self.root):
            return self._public(self._read())

    def _trusted_config(self) -> dict:
        """Internal host-only API: obtain secret in memory for one authorized call."""
        with _exclusive(self.root):
            state = self._read()
            if state["configuration"] is None:
                raise OnlineCredentialError("Online AI provider not configured")
            return dict(state["configuration"])

    def clear(self) -> None:
        """Remove active key; old external backups cannot be securely erased."""
        with _exclusive(self.root):
            state = self._read()
            if state["configuration"] is None:
                raise OnlineCredentialError("Online AI provider already unconfigured")
            state["generation"] += 1
            state["configuration"] = None
            self._write(state)


__all__ = ["TarazOnlineAiCredentialVault", "OnlineCredentialError",
           "validate_provider"]
