"""Independent per-company accounting workspaces.

No global APPDATA discovery, no import from Parsian/Mohsensoft, no shared
book, and no company metadata stored inside another company's ledger.

The caller must supply an existing absolute hub directory. Each company gets
a fresh unique subdirectory. Selection only yields that explicit path.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import threading
import time
import unicodedata

_ID = re.compile(r"[a-f0-9]{32}\Z")
_VERSION = 1
_REGISTRY = "companies.json"
_BOOK_DIR = "books"
_MAX_COMPANIES = 100
_LOCK = threading.RLock()


class CompanyRegistryError(RuntimeError):
    """A requested company operation cannot be completed safely."""


def _check_directory(path: Path, *, must_exist: bool = True):
    if not path.is_absolute():
        raise CompanyRegistryError("Company hub directory must be absolute")
    for parent in (path, *path.parents):
        if not parent.exists() and not parent.is_symlink():
            if must_exist:
                raise CompanyRegistryError("Company root component does not exist")
            continue
        if parent.is_symlink():
            raise CompanyRegistryError("Symlinks are not allowed in company paths")
        attributes = getattr(parent.lstat(), "st_file_attributes", 0)
        if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise CompanyRegistryError("Reparse points are not allowed in company paths")
    if must_exist and not path.is_dir():
        raise CompanyRegistryError("Expected existing company directory")
    return path


def _safe_company_name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120 or \
            any(ord(c) < 32 or ord(c) == 127 or (
                unicodedata.category(c) == 'Cf' and c not in '\u200c\u200d')
                for c in value):
        raise CompanyRegistryError("Company name must be 1..120 visible characters")
    return value.strip()


def normalized_company_label(value):
    """Compare human-visible Persian/Arabic names without visual duplicates."""
    return unicodedata.normalize('NFKC', value).casefold().replace('ي', 'ی').replace('ك', 'ک')


@contextmanager
def _exclusive_company_lock(root: Path, timeout: float = 10):
    """Serialize all registry creation and book allocation across processes."""
    with _LOCK:
        target = root / ".company-registry.lock"
        if target.is_symlink():
            raise CompanyRegistryError("Refusing symlinked registry lock")
        with target.open("a+b") as stream:
            deadline = time.monotonic() + timeout
            if sys.platform == "win32":
                import msvcrt
                stream.seek(0)
                if stream.read(1) == b"":
                    stream.seek(0)
                    stream.write(b"0")
                    stream.flush()
                def take():
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                def release():
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                def take():
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                def release():
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            while True:
                try:
                    take()
                    break
                except (OSError, PermissionError) as exc:
                    if time.monotonic() >= deadline:
                        raise CompanyRegistryError("Company registry is busy") from exc
                    time.sleep(.05)
            try:
                yield
            finally:
                release()


class StandaloneCompanyRegistry:
    """Registry of standalone company books inside one operator-selected root."""

    def __init__(self, explicit_root):
        self.root = _check_directory(Path(explicit_root))
        self.registry_file = self.root / _REGISTRY
        self.books_root = self.root / _BOOK_DIR

    def list_companies(self):
        _check_directory(self.root)
        if not self.registry_file.exists():
            return []
        if self.registry_file.is_symlink() or \
                getattr(self.registry_file.lstat(), "st_file_attributes", 0) & \
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise CompanyRegistryError("Company registry must not be a reparse point")
        if self.registry_file.stat().st_size > 262144:
            raise CompanyRegistryError("Company registry exceeds safe size")
        try:
            doc = json.loads(self.registry_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise CompanyRegistryError("Company registry is damaged") from exc
        if not isinstance(doc, dict) or doc.get("version") != _VERSION or \
                not isinstance(doc.get("companies"), list) or \
                len(doc["companies"]) > _MAX_COMPANIES:
            raise CompanyRegistryError("Invalid company registry format")
        ids, names = set(), set()
        for c in doc["companies"]:
            if not isinstance(c, dict) or set(c) != {"id", "name", "createdAt"} or \
                    not isinstance(c["id"], str) or not _ID.fullmatch(c["id"]) or \
                    not isinstance(c["createdAt"], str):
                raise CompanyRegistryError("Invalid company record")
            name = _safe_company_name(c["name"])
            if c["id"] in ids or normalized_company_label(name) in names:
                raise CompanyRegistryError("Duplicate company entries")
            ids.add(c["id"])
            names.add(normalized_company_label(name))
        return [dict(c) for c in doc["companies"]]

    def company_data_directory(self, company_id: str):
        if not isinstance(company_id, str) or not _ID.fullmatch(company_id):
            raise CompanyRegistryError("Invalid company identifier")
        companies = self.list_companies()
        if company_id not in {c["id"] for c in companies}:
            raise CompanyRegistryError("Unknown company identifier")
        _check_directory(self.books_root)
        book = self.books_root / company_id
        return _check_directory(book)

    def create_company(self, name: str):
        name = _safe_company_name(name)
        with _exclusive_company_lock(self.root):
            companies = self.list_companies()
            if len(companies) >= _MAX_COMPANIES:
                raise CompanyRegistryError("Company limit reached")
            if normalized_company_label(name) in {normalized_company_label(c["name"]) for c in companies}:
                raise CompanyRegistryError("This company name already exists")
            if self.books_root.exists():
                _check_directory(self.books_root)
            else:
                self.books_root.mkdir()
            ident = secrets.token_hex(16)
            if any(c["id"] == ident for c in companies):
                raise CompanyRegistryError("Company identifier collision")
            book = self.books_root / ident
            book.mkdir(exist_ok=False)
            record = {"id": ident, "name": name,
                      "createdAt": datetime.now(timezone.utc).isoformat()}
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                        prefix=".companies-", suffix=".tmp",
                        dir=self.root, delete=False) as output:
                    tmp = Path(output.name)
                    json.dump({"version": _VERSION, "companies": [*companies, record]},
                              output, ensure_ascii=False, separators=(",", ":"))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(tmp, self.registry_file)
            except Exception:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)
                # Only remove the newly allocated empty folder on failed
                # publication; never delete a folder that acquired data.
                try:
                    book.rmdir()
                except OSError:
                    pass
                raise
            return dict(record)


class CompanySessionGuard:
    """Reject concurrent application instances pointing at the same book."""

    def __init__(self, selected_company_dir):
        self.book_dir = _check_directory(Path(selected_company_dir))
        self.stream = None

    def acquire(self):
        if self.stream is not None:
            raise CompanyRegistryError("Company book lock already held")
        path = self.book_dir / ".standalone-company-active.lock"
        if path.is_symlink():
            raise CompanyRegistryError("Refusing linked accounting lock")
        handle = path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt
                handle.seek(0)
                if handle.read(1) == b"":
                    handle.seek(0)
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, PermissionError) as exc:
            handle.close()
            raise CompanyRegistryError(
                "The selected company is already open in another accounting session") from exc
        self.stream = handle
        return self

    def release(self):
        handle = self.stream
        if handle is None:
            return
        self.stream = None
        try:
            if sys.platform == "win32":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback):
        self.release()


def pick_company_dialog(registry: StandaloneCompanyRegistry):
    """Premium operator entry point. Never starts WebView or touches a ledger."""
    from standalone_accounting_premium_chooser import pick_premium_company_dialog
    return pick_premium_company_dialog(registry)
