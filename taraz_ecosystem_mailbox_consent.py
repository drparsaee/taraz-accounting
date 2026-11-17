"""Trusted Windows confirmation for exactly one authenticated mailbox batch.

The browser may *request* a poll, but no renderer boolean approves an outbound
counterparty reply. Only a shown pywebview Window's native confirmation dialog
can create the short-lived, single-use permissions consumed by the peer.
No listener, journal write, stored approval, or remote service is introduced.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import unicodedata


_HEX32 = re.compile(r"[a-f0-9]{32}\Z", re.ASCII)
_MAX_BATCH = 10
_MAX_PREVIEW_CHARS = 3500
_MAX_POLL_AGE_SECONDS = 120
_PERMIT_TTL_SECONDS = 120
_PROMPT_LOCK = threading.Lock()
_SCOPE_FIELDS = frozenset(("workspaceId", "companyId", "installationId"))
_ENVELOPE_FIELDS = frozenset((
    "workspaceId", "companyId", "installationId", "requestId",
    "requestedActor", "requestedGrant", "operation", "parameters",
))


class NativeMailboxConsentDenied(PermissionError):
    """Missing native operator approval, stale batch, or changed identity."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _safe_preview_text(value):
    """Refuse Unicode direction overrides and controls in a native approval."""
    if type(value) is str:
        if any(ord(ch) < 32 or 127 <= ord(ch) <= 159 or
               (unicodedata.category(ch) == "Cf" and ch != "\u200c")
               for ch in value):
            raise NativeMailboxConsentDenied("Untrusted control character in approval")
    elif type(value) is dict:
        for key, item in value.items():
            _safe_preview_text(key)
            _safe_preview_text(item)
    elif type(value) is list:
        for item in value:
            _safe_preview_text(item)


def _id(value):
    return type(value) is str and _HEX32.fullmatch(value) is not None


class _OneBatchPermit:
    """In-memory; every request ID can be consumed exactly once, before IO."""

    def __init__(self, *, identity, envelopes, verified, now):
        self._identity = {"actor": identity["actor"],
                          "scope": dict(identity["scope"])}
        self._hashes = {
            envelope["requestId"]: hashlib.sha256(_canonical(envelope)).digest()
            for envelope in envelopes
        }
        self._used = set()
        self._verified = verified
        self._now = now
        self._expiry = now() + _PERMIT_TTL_SECONDS
        self._lock = threading.Lock()

    def check(self, envelope, *, scope, consume=False):
        with self._lock:
            try:
                request_id = envelope["requestId"]
                expected = self._hashes[request_id]
                actual = hashlib.sha256(_canonical(envelope)).digest()
            except (TypeError, ValueError, KeyError, OverflowError):
                raise NativeMailboxConsentDenied("Unapproved reply envelope") from None
            if (type(scope) is not dict or scope != self._identity["scope"] or
                    actual != expected or self._now() > self._expiry or
                    self._verified() is not True or
                    (consume and request_id in self._used)):
                raise NativeMailboxConsentDenied("Native batch consent is invalid or expired")
            if consume:
                self._used.add(request_id)
            elif request_id not in self._used:
                raise NativeMailboxConsentDenied("Reply has not consumed native consent")


class NativeMailboxBatchConsent:
    """OS confirmation bound to the current native window and verified session.

    session_verified must recheck the real Taraz admin, company and window
    identity and return the exact bool True. Only the native Python host builds
    this object; it and its approval/permit are never exposed in window.madar.
    """

    def __init__(self, native_window, *, actor, company_id, workspace_id,
                 installation_id, session_verified):
        if (type(actor) is not str or not 1 <= len(actor) <= 96 or
                not _id(company_id) or not _id(workspace_id) or
                not _id(installation_id) or not callable(session_verified)):
            raise NativeMailboxConsentDenied("Verified native administrator required")
        _safe_preview_text(actor)
        self.window = native_window
        self.actor = actor
        self.scope = {"companyId": company_id, "workspaceId": workspace_id,
                      "installationId": installation_id}
        self.session_verified = session_verified

    def _native_prompt(self, title, preview):
        """The sole production approval path: pywebview native OS dialog."""
        if os.name != "nt":
            raise NativeMailboxConsentDenied("Windows native confirmation required")
        from webview.window import Window
        if not isinstance(self.window, Window):
            raise NativeMailboxConsentDenied("Live native Taraz window unavailable")
        # pywebview binds the OS dialog to this window's uid; a JS confirm
        # cannot return a value for this call.
        return self.window.create_confirmation_dialog(title, preview) is True

    def approve(self, envelopes, *, scope):
        if (type(scope) is not dict or set(scope) != _SCOPE_FIELDS or
                scope != self.scope or type(envelopes) is not list or
                not 1 <= len(envelopes) <= _MAX_BATCH):
            raise NativeMailboxConsentDenied("Invalid native mailbox scope or batch")
        unique = set()
        for envelope in envelopes:
            if (type(envelope) is not dict or set(envelope) != _ENVELOPE_FIELDS or
                    any(envelope[k] != v for k, v in scope.items()) or
                    not _id(envelope["requestId"]) or
                    envelope["requestId"] in unique or
                    envelope["requestedGrant"] != "counterparties.read" or
                    envelope["operation"] not in
                    ("Counterparties.Search", "Counterparties.Get") or
                    type(envelope["requestedActor"]) is not str or
                    not 1 <= len(envelope["requestedActor"]) <= 96 or
                    type(envelope["parameters"]) is not dict):
                raise NativeMailboxConsentDenied("Untrusted native batch envelope")
            unique.add(envelope["requestId"])
        _safe_preview_text(envelopes)
        identity = {"actor": self.actor, "scope": scope}
        # WinForms MessageBox has no scrollable JSON inspector. Render each
        # exact envelope field compactly and refuse batches that cannot fit;
        # never silently truncate IDs, cursors or selected parameters.
        preview_lines = [
            "درخواست‌های دقیق مدار برای ارسال فقط partyId، name و kind",
            "تأیید فقط برای همین دسته و همین نشست معتبر است.",
            "مدیر محلی تراز: " + self.actor,
            "شرکت تراز: " + scope["companyId"],
            "فضای مدار: " + scope["workspaceId"],
            "نصب تراز: " + scope["installationId"],
        ]
        try:
            for index, envelope in enumerate(envelopes, 1):
                parameters = json.dumps(
                    envelope["parameters"], sort_keys=True,
                    separators=(",", ":"), ensure_ascii=False, allow_nan=False)
                preview_lines.extend([
                    "",
                    str(index) + ") شناسه درخواست: " + envelope["requestId"],
                    "   درخواست‌کننده: " + envelope["requestedActor"],
                    "   مجوز: " + envelope["requestedGrant"],
                    "   عملیات: " + envelope["operation"],
                    "   پارامترها: " + parameters,
                ])
        except (ValueError, TypeError, OverflowError):
            raise NativeMailboxConsentDenied("Invalid native mailbox preview") from None
        preview = "\n".join(preview_lines)
        if len(preview) > _MAX_PREVIEW_CHARS:
            raise NativeMailboxConsentDenied("Mailbox request preview exceeds native dialog")
        if not _PROMPT_LOCK.acquire(blocking=False):
            raise NativeMailboxConsentDenied("Native mailbox confirmation already pending")
        try:
            requested_at = time.monotonic()
            if self.session_verified() is not True:
                raise NativeMailboxConsentDenied("Administrator identity changed")
            try:
                approved = self._native_prompt("تراز | تأیید بومی پاسخ‌های مدار", preview)
            except Exception:
                approved = False
            if (approved is not True or
                    time.monotonic() - requested_at > _MAX_POLL_AGE_SECONDS or
                    self.session_verified() is not True):
                raise NativeMailboxConsentDenied("Native operator did not approve batch")
            return _OneBatchPermit(
                identity=identity, envelopes=envelopes,
                verified=self.session_verified, now=time.monotonic)
        finally:
            _PROMPT_LOCK.release()


__all__ = ["NativeMailboxBatchConsent", "NativeMailboxConsentDenied"]
