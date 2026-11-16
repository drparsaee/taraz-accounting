"""User-authorized NEW empty Taraz book bound to the current Windows account.

This is not a migration. No legacy ledger is copied, read, overwritten or
given a synthetic owner. A new local Windows principal may own its own empty
book. A generated per-book password is DPAPI-protected, never shown to users.
The usual authenticated TarazAPI and all financial permissions remain active.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import stat

from standalone_accounting import StandaloneAccountingStore
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_identity import LocalCompanyIdentity
from taraz_ai_chat_store import _protect, _unprotect
from taraz_legacy_ownership_enrollment import current_windows_sid

MARKER = "taraz-windows-local-identity.json"
USER = "windows_local"
LABEL = "دفتر جدید تراز"


class FreshStartBlocked(PermissionError):
    pass


def _safe(path: Path) -> None:
    if not path.is_absolute():
        raise FreshStartBlocked("Absolute profile path required")
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and
                getattr(item.lstat(), "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise FreshStartBlocked("Linked directory or file refused")


def _scope(sid: str, company_id: str) -> str:
    return "FRESH-LOCAL-WINDOWS-ONLY-V1:" + sid + ":" + company_id


def _principal() -> tuple[str, str]:
    if os.name != "nt":
        raise FreshStartBlocked("Windows-only local sign-in")
    sid = current_windows_sid()
    machine = os.environ.get("COMPUTERNAME", "").strip()
    if not machine or len(machine) > 80:
        raise FreshStartBlocked("No verified local Windows machine name")
    return sid, machine


def stage_new_empty_root(root: Path) -> dict:
    """Create only at an ABSENT destination; caller archives old data first."""
    root = Path(root)
    _safe(root)
    if root.exists() or not root.parent.is_dir():
        raise FreshStartBlocked("New profile destination must not exist")
    sid, machine = _principal()
    staging = root.parent / (root.name + ".fresh-staged-" + secrets.token_hex(8))
    staging.mkdir(mode=0o700)
    _safe(staging)
    # Never adopt any contents: create a truly new single-company ledger.
    registry = StandaloneCompanyRegistry(staging)
    created = registry.create_company(LABEL)
    book = registry.company_data_directory(created["id"])
    StandaloneAccountingStore(book / "standalone-accounting.sqlite3",
                              default_currency="RIAL")
    identity = LocalCompanyIdentity(book)
    password = secrets.token_urlsafe(48)
    identity.add_user(USER, password, "admin", job_title="مالک دفتر جدید")
    ciphertext = _protect(password, _scope(sid, created["id"]))
    data = {"version": 1, "mode": "windows-local-fresh",
            "companyId": created["id"], "username": USER,
            "windowsSid": sid, "computerName": machine,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "passwordDpapi": base64.b64encode(ciphertext).decode("ascii")}
    with (book / MARKER).open("x", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, sort_keys=True)
        out.flush()
        os.fsync(out.fileno())
    # Validate all new content before publishing.
    inspect_fresh_workspace(staging, allow_staging=True)
    if root.exists():
        raise FreshStartBlocked("Profile appeared during staging")
    staging.rename(root)
    return inspect_fresh_workspace(root)


def inspect_fresh_workspace(root: Path, *, allow_staging=False) -> dict:
    root = Path(root)
    _safe(root)
    if not root.is_dir():
        raise FreshStartBlocked("Fresh workspace root missing")
    registry = StandaloneCompanyRegistry(root)
    companies = registry.list_companies()
    if len(companies) != 1 or companies[0]["name"] != LABEL:
        raise FreshStartBlocked("Not a single-company fresh workspace")
    company = companies[0]
    book = registry.company_data_directory(company["id"])
    marker = book / MARKER
    _safe(marker)
    if not marker.is_file() or marker.stat().st_size > 8192:
        raise FreshStartBlocked("Missing or oversized Windows binding")
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError) as exc:
        raise FreshStartBlocked("Malformed Windows binding") from exc
    sid, machine = _principal()
    if (type(data) is not dict or
            set(data) != {"version", "mode", "companyId", "username",
                          "windowsSid", "computerName", "createdAt",
                          "passwordDpapi"} or
            data["version"] != 1 or data["mode"] != "windows-local-fresh" or
            data["companyId"] != company["id"] or data["username"] != USER or
            data["windowsSid"] != sid or data["computerName"] != machine):
        raise FreshStartBlocked("Windows binding mismatch")
    try:
        encrypted = base64.b64decode(data["passwordDpapi"], validate=True)
        password = _unprotect(encrypted, _scope(sid, company["id"]))
    except (ValueError, OSError, TypeError) as exc:
        raise FreshStartBlocked("Cannot open the current Windows identity") from exc
    identity = LocalCompanyIdentity(book)
    if set(identity.accounting_accounts()) != {USER}:
        raise FreshStartBlocked("Fresh workspace identity changed")
    ledger = book / "standalone-accounting.sqlite3"
    _safe(ledger)
    if not ledger.is_file():
        raise FreshStartBlocked("Existing fresh book is missing; refusing to recreate it")
    token = identity.login(USER, password)
    try:
        user = identity.require_session(token, "admin")
        store = StandaloneAccountingStore(
            ledger, default_currency="RIAL")
        view = store.read(actor=USER, accounts=identity.accounting_accounts())
        if view["view"].get("currency") != "RIAL":
            raise FreshStartBlocked("Invalid fresh currency")
    finally:
        identity.logout(token)
    return {"companyId": company["id"], "companyLabel": LABEL,
            "mode": "windows-local-fresh", "windowsPrincipalBound": True,
            "ledgerRevision": view["revision"], "user": user["username"],
            "role": user["role"], "book": str(book)}


def open_fresh_company(root: Path):
    """Return a real authenticated API session, not a synthetic QA identity."""
    info = inspect_fresh_workspace(root)
    book = Path(info["book"])
    data = json.loads((book / MARKER).read_text(encoding="utf-8"))
    sid, _ = _principal()
    password = _unprotect(base64.b64decode(data["passwordDpapi"], validate=True),
                          _scope(sid, info["companyId"]))
    identity = LocalCompanyIdentity(book)
    token = identity.login(USER, password)
    try:
        current = identity.require_session(token, "admin")
        from taraz_desktop import TarazAPI
        api = TarazAPI(book, company_name=info["companyLabel"],
                       company_workspace_id=info["companyId"],
                       authenticated_user=current, identity_store=identity,
                       identity_token=token)
        # Only this verified Windows-bound entrypoint can mark the session as
        # fresh. UI uses the marker to omit obsolete Parsian archive requests;
        # it never relaxes any financial backend permission.
        api._verified_fresh_workspace = True
        return api, identity, token
    except BaseException:
        identity.logout(token)
        raise
