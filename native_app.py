"""Native Windows host for Madar Desk.

This is the Windows executable entrypoint. It serves prebuilt static React assets
to an embedded Edge WebView2 window; data never leaves the computer unless the
user explicitly uploads a Google Drive backup.
"""

from __future__ import annotations

import base64
import ctypes
from contextlib import closing, contextmanager
from ctypes import wintypes
import hashlib
import http.server
import json
import mimetypes
import msvcrt
import os
from pathlib import Path, PureWindowsPath
import secrets
import shutil
import re
import sqlite3
import socket
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request, urlopen
import webbrowser

import webview
from lan import LanService, clean_profile, public_user, certificate_fingerprint, pinned_https_json, revision
from offline_exchange import OfflineStore
from offline_exchange import three_way_merge
from cloud_continuity import CloudConflict, PeerJournal
from data_model import (normalize_plus, validate_plus, _legacy_checklist_items,
                        DEFAULT_PRIORITY_DEFINITIONS, priority_definition_ids)
import collab
import automation_buttons
import finance
from automation_due import due_events
from automation_events import card_change_events
from attachments import AttachmentStore
from app_storage import UnifiedAppStorage
import automation_v1
import madar_update

APP_NAME = "MadarDesk"
SCOPE = "https://www.googleapis.com/auth/drive.appdata"
GOOGLE_API = "https://www.googleapis.com/drive/v3"
GOOGLE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
DEFAULT_STAGES = [
    {"id": "inbox", "label": "صندوق ورودی", "subtitle": "ایده‌ها و کارهای جدید", "color": "#9ca3af"},
    {"id": "planned", "label": "برنامه‌ریزی", "subtitle": "آماده شروع", "color": "#6785d8"},
    {"id": "active", "label": "در حال انجام", "subtitle": "در جریان کار", "color": "#c89141"},
    {"id": "review", "label": "در انتظار بررسی", "subtitle": "نیاز به تصمیم", "color": "#a37be1"},
    {"id": "done", "label": "تکمیل‌شده", "subtitle": "کارهای تمام‌شده", "color": "#3ca789"},
]
def datadir():
    root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if not root:
        raise RuntimeError("پوشه اطلاعات کاربر در دسترس نیست.")
    folder = Path(root) / APP_NAME
    folder.mkdir(exist_ok=True, parents=True)
    return folder


def _validate_lan_target(url):
    """Validate a LAN origin before touching profile caches or sending secrets."""
    from urllib.parse import urlparse
    import ipaddress
    if not isinstance(url, str):
        raise ValueError("نشانی میزبان شبکه معتبر نیست.")
    try:
        parsed = urlparse(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or
                parsed.port is None or parsed.username is not None or
                parsed.password is not None or parsed.query or parsed.fragment or
                parsed.path not in ("", "/")):
            raise ValueError("نشانی میزبان باید فقط IP و پورت باشد.")
        address = ipaddress.ip_address(parsed.hostname)
    except (TypeError, ValueError) as error:
        raise ValueError("برای اتصال، نشانی IP و پورت معتبر لازم است.") from error
    if not (address.is_private or address.is_loopback):
        raise ValueError("فقط IP شبکه خصوصی یا لوکال مجاز است.")
    if parsed.scheme == "http" and not address.is_loopback:
        raise ValueError("اتصال شبکه با رمز عبور فقط از طریق HTTPS مجاز است.")
    return parsed


@contextmanager
def _state_write_guard(path):
    """Serialize cooperating Windows writers sharing one local task file.

    Keep the lock for the entire read/CAS/side-effect/commit sequence, not
    merely for the final atomic rename or SQLite transaction.
    """
    lock_path = path.with_name(path.name + ".writer.lock")
    with open(lock_path, "a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"\x00")
            stream.flush()
        deadline = time.monotonic() + 5
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise RuntimeError("CONFLICT: فایل اطلاعات در حال ذخیره توسط نمونه دیگری است.") from error
                time.sleep(0.025)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def normalize_state(state):
    """Add compatible defaults without ever discarding user data."""
    if not isinstance(state, dict):
        return state
    state = json.loads(json.dumps(state))
    if not isinstance(state.get("projects"), list) or not isinstance(state.get("tasks"), list):
        return state
    state.setdefault("stages", [dict(s) for s in DEFAULT_STAGES])
    state.setdefault("settings", {})
    if isinstance(state["settings"], dict):
        state["settings"].setdefault("theme", "light")
        state["settings"].setdefault("themeForAllUsers", False)
        state["settings"].setdefault("costDefault", False)
        state["settings"].setdefault("priorityDefinitions", [dict(item) for item in DEFAULT_PRIORITY_DEFINITIONS])
    for p in state["projects"]:
        if isinstance(p, dict):
            p.setdefault("costEnabled", bool(state["settings"].get("costDefault", False)))
            p.setdefault("price", 0)
            p.setdefault("fileLinks", [])
    for t in state["tasks"]:
        if isinstance(t, dict):
            t.setdefault("cost", 0)
            t.setdefault("costCategory", "")
            t.setdefault("costDate", "")
            t.setdefault("costEnabled", None)
            t.setdefault("labelColors", {})
            t.setdefault("assignees", [])
            t.setdefault("fileLinks", [])
            t.setdefault("estimatedMinutes", 0)
            t.setdefault("actualMinutes", 0)
            for item in t.get("checklist", []):
                if isinstance(item, dict):
                    item.setdefault("cost", 0)
                    item.setdefault("costCategory", "")
                    item.setdefault("costDate", "")
    upgraded = normalize_plus(state)
    # Keep the legacy flat checklist authoritative while the current Windows
    # editor uses it. Preserve other named groups unmodified.
    for task in upgraded["tasks"]:
        for group in task.get("checklists", []):
            if group["id"] == "checklist-legacy":
                # Rebuild from the flat editor's authoritative values while
                # preserving/generated unique IDs for the named model. A raw
                # deep copy reintroduced missing/duplicate legacy identifiers.
                group["items"] = _legacy_checklist_items(task)
            for item in group["items"]:
                item.setdefault("costCategory", "")
                item.setdefault("costDate", "")
    return upgraded


def is_valid(state):
    if (not isinstance(state, dict) or state.get("version") != 1
            or not isinstance(state.get("projects"), list)
            or not isinstance(state.get("tasks"), list)
            or not isinstance(state.get("settings"), dict)):
        raise ValueError("فرمت فایل اطلاعات معتبر نیست.")
    if len(state["projects"]) > 2000 or len(state["tasks"]) > 20000:
        raise ValueError("تعداد رکوردها بیش از حد مجاز است.")
    stages = state.get("stages", DEFAULT_STAGES)
    if not isinstance(stages, list) or not 1 <= len(stages) <= 40:
        raise ValueError("تعداد ستون‌ها معتبر نیست.")
    stage_ids = set()
    for s in stages:
        if (not isinstance(s, dict) or not isinstance(s.get("id"), str)
                or not 1 <= len(s["id"]) <= 100 or s["id"] in stage_ids
                or not isinstance(s.get("label"), str) or not 1 <= len(s["label"]) <= 100
                or not isinstance(s.get("subtitle", ""), str)
                or not isinstance(s.get("color", ""), str)
                or ("archived" in s and type(s["archived"]) is not bool)):
            raise ValueError("ستون نامعتبر است.")
        stage_ids.add(s["id"])
    if (state["settings"].get("theme", "light") not in {"light", "dark"} or
            not isinstance(state["settings"].get("costDefault", False), bool) or
            not isinstance(state["settings"].get("themeForAllUsers", False), bool)):
        raise ValueError("تنظیمات نمایش نامعتبر است.")
    priority_ids = priority_definition_ids(state["settings"])
    ids = set()
    for project in state["projects"]:
        if (not isinstance(project, dict) or not isinstance(project.get("id"), str)
                or not isinstance(project.get("name"), str)
                or len(project["name"]) > 180 or project["id"] in ids
                or not isinstance(project.get("costEnabled", False), bool)
                or not valid_amount(project.get("price", 0))):
            raise ValueError("یک پروژه نامعتبر است.")
        ids.add(project["id"])
        validate_links(project.get("fileLinks", []))
    task_ids = set()
    for task in state["tasks"]:
        if isinstance(task, dict) and "deleted" in task and type(task["deleted"]) is not bool:
            raise ValueError("حذف موقت کارت باید از نوع بولی باشد.")
        if isinstance(task, dict) and "completed" in task and type(task["completed"]) is not bool:
            raise ValueError("تکمیل کارت باید از نوع بولی باشد.")
        if (not isinstance(task, dict) or not isinstance(task.get("id"), str)
                or task["id"] in task_ids or task.get("projectId") not in ids
                or not isinstance(task.get("title"), str) or len(task["title"]) > 300
                or task.get("status") not in stage_ids or task.get("priority") not in priority_ids
                or not valid_amount(task.get("cost", 0))
                or not isinstance(task.get("checklist"), list)
                or not isinstance(task.get("reports"), list)
                or len(task["checklist"]) > 300 or len(task["reports"]) > 500):
            raise ValueError("یک کار نامعتبر است.")
        task_ids.add(task["id"])
        if "cardOrder" in task and (type(task["cardOrder"]) is not int
                                   or not 0 <= task["cardOrder"] <= 1_000_000):
            raise ValueError("ترتیب کارت باید عدد صحیح بین صفر و یک میلیون باشد.")
        if ("saleQuantity" in task and (type(task["saleQuantity"]) is not int or
                                       not 1 <= task["saleQuantity"] <= 1_000_000)):
            raise ValueError("تعداد فروش کارت باید عدد صحیح مثبت باشد.")
        if ("saleUnitPrice" in task and (type(task["saleUnitPrice"]) is not int or
                                        not 0 <= task["saleUnitPrice"] <= 10**15)):
            raise ValueError("قیمت واحد فروش کارت معتبر نیست.")
        if task.get("costEnabled", None) is not None and type(task["costEnabled"]) is not bool:
            raise ValueError("وضعیت هزینه کارت معتبر نیست.")
        if not valid_cost_category(task.get("costCategory", "")):
            raise ValueError("دسته‌بندی هزینه کارت معتبر نیست.")
        if not valid_cost_date(task.get("costDate", "")):
            raise ValueError("تاریخ هزینه کارت معتبر نیست.")
        label_colors = task.get("labelColors", {})
        if (not isinstance(label_colors, dict) or len(label_colors) > 200
                or any(not isinstance(key, str) or not key.strip() or len(key) > 100
                       or not all(c.isprintable() or c == "\u200c" for c in key)
                       or not isinstance(value, str)
                       or not re.fullmatch(r"#[0-9a-fA-F]{6}", value)
                       for key, value in label_colors.items())):
            raise ValueError("رنگ برچسب معتبر نیست.")
        assignees = task.get("assignees", [])
        if (not isinstance(assignees, list) or len(assignees) > 30
                or any(not isinstance(x, str) or len(x) > 40 for x in assignees)
                or len(set(assignees)) != len(assignees)):
            raise ValueError("مسئولان کارت معتبر نیستند.")
        validate_links(task.get("fileLinks", []))
        for field in ("estimatedMinutes", "actualMinutes"):
            if type(task.get(field, 0)) is not int or not 0 <= task.get(field, 0) <= 5_256_000:
                raise ValueError("مدت زمان کار معتبر نیست.")
        for item in task["checklist"]:
            if (not isinstance(item, dict) or not isinstance(item.get("text"), str)
                    or not isinstance(item.get("done"), bool)
                    or not valid_amount(item.get("cost", 0))):
                raise ValueError("مرحله هزینه‌دار نامعتبر است.")
            if not valid_cost_category(item.get("costCategory", "")):
                raise ValueError("دسته‌بندی هزینه چک‌لیست معتبر نیست.")
            if not valid_cost_date(item.get("costDate", "")):
                raise ValueError("تاریخ هزینه چک‌لیست معتبر نیست.")
        for group in task.get("checklists", []):
            for item in group.get("items", []):
                if not valid_cost_category(item.get("costCategory", "")):
                    raise ValueError("دسته‌بندی هزینه چک‌لیست نام‌دار معتبر نیست.")
                if not valid_cost_date(item.get("costDate", "")):
                    raise ValueError("تاریخ هزینه چک‌لیست نام‌دار معتبر نیست.")
    if len(json.dumps(state, ensure_ascii=False).encode("utf8")) > 15_000_000:
        raise ValueError("حجم اطلاعات بیشتر از حد مجاز است.")
    validate_plus(state)
    # Validate task dependency DAG at the persistence boundary, including LAN
    # writes and local restores. A React-only cycle check is insufficient.
    from card_dependency_validation import validate_task_dependencies
    validate_task_dependencies(state["tasks"])
    return True


def valid_amount(amount):
    return type(amount) is int and 0 <= amount <= 10**15


def valid_cost_category(category):
    return (isinstance(category, str) and len(category) <= 80
            and all(c.isprintable() or c == "\u200c" for c in category))


def valid_cost_date(value):
    if value == "":
        return True
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def valid_share_path(value):
    """Only UNC SMB file paths, never URLs, shell commands or traversal."""
    if not isinstance(value, str) or len(value) > 2048:
        return False
    normalized = value.replace("/", "\\")
    if not normalized.startswith("\\\\") or normalized.startswith("\\\\?\\") or normalized.startswith("\\\\.\\"):
        return False
    parts = normalized[2:].split("\\")
    return (len(parts) >= 3 and all(parts[:3])
            and all(part not in (".", "..") for part in parts)
            and not any(ord(char) < 32 or char in '<>:"|?*' for char in normalized[2:])
            and not normalized.endswith("\\"))


def windows_downloads_directory():
    """Resolve the actual Windows Downloads known folder (including redirection)."""
    from uuid import UUID

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    known_id = GUID.from_buffer_copy(UUID("374de290-123f-4565-9164-39c4925e467b").bytes_le)
    folder_ptr = ctypes.c_void_p()
    getter = ctypes.windll.shell32.SHGetKnownFolderPath
    getter.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                       ctypes.POINTER(ctypes.c_void_p)]
    getter.restype = ctypes.c_long
    result = getter(ctypes.byref(known_id), 0, None, ctypes.byref(folder_ptr))
    if result != 0 or not folder_ptr.value:
        raise OSError("پوشه دانلودهای ویندوز پیدا نشد.")
    try:
        return Path(ctypes.wstring_at(folder_ptr))
    finally:
        free = ctypes.windll.ole32.CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        free(folder_ptr)


def copy_shared_file_to_directory(source_path, downloads_dir):
    """Copy a chosen SMB file without executing it or replacing an existing copy."""
    filename = PureWindowsPath(source_path).name
    if not filename or filename in (".", ".."):
        raise ValueError("نام فایل اشتراکی معتبر نیست.")
    directory = Path(downloads_dir)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = PureWindowsPath(filename).suffix
    stem = filename[:-len(suffix)] if suffix else filename
    with open(source_path, "rb") as source:
        for counter in range(10000):
            candidate = directory / (filename if counter == 0 else f"{stem} ({counter}){suffix}")
            try:
                destination = candidate.open("xb")
            except FileExistsError:
                continue
            try:
                with destination:
                    shutil.copyfileobj(source, destination)
            except BaseException:
                candidate.unlink(missing_ok=True)
                raise
            return {"downloaded": True, "name": candidate.name, "path": str(candidate)}
    raise FileExistsError("نام آزاد برای ذخیره فایل در Downloads پیدا نشد.")


def validate_links(links):
    if not isinstance(links, list) or len(links) > 200:
        raise ValueError("تعداد لینک‌های اشتراکی معتبر نیست.")
    ids = set()
    for link in links:
        if (not isinstance(link, dict) or not isinstance(link.get("id"), str)
                or link["id"] in ids or not isinstance(link.get("name"), str)
                or not 1 <= len(link["name"]) <= 180
                or not valid_share_path(link.get("path"))):
            raise ValueError("مسیر فایل اشتراکی معتبر نیست. باید با دو بک‌اسلش و نام سیستم شروع شود.")
        ids.add(link["id"])


def initial_state():
    """Historical sample fixture; retained for explicit legacy QA/import tests.

    Real first-run profiles use empty_initial_state(). Never seed examples into
    customer profiles, including after changing executable versions.
    """
    now = datetime.now(timezone.utc).isoformat()
    def task(n, title, status, priority, steps, summary=""):
        return {
            "id": "example-" + str(n), "projectId": "p-sample",
            "title": title, "description": "این کارت نمونه است و می‌توانی آن را تغییر دهی.",
            "status": status, "priority": priority, "dueDate": "",
            "labels": ["نمونه"], "createdAt": now, "updatedAt": now, "cost": 0,
            "checklist": [{"id": "step-" + str(n) + "-" + str(i), "text": s, "done": i == 0}
                          for i, s in enumerate(steps)],
            "reports": ([{"id": "report-" + str(n), "agent": "نمونه",
                          "summary": summary, "createdAt": now}] if summary else []),
        }
    return {
        "version": 1,
        "projects": [
            {"id": "p-personal", "name": "کارهای من", "color": "#5672ca", "costEnabled": False, "price": 0},
            {"id": "p-sample", "name": "پروژه نمونه", "color": "#3d977e", "costEnabled": False, "price": 0},
        ],
        "tasks": [
            task(1, "طراحی برد و چیدمان کارها", "done", "high", ["تعریف ساختار"], "طرح اولیه آماده شد."),
            task(2, "جمع‌آوری نیازمندی‌های نسخه اول", "active", "medium",
                 ["فهرست قابلیت‌ها", "انتخاب اولویت‌ها"], "فهرست اولیه ثبت شد."),
            task(3, "بازبینی تجربه کاربری", "review", "high", []),
            task(4, "تعریف شیوه گزارش ایجنت", "planned", "low", []),
        ],
        "stages": [dict(s) for s in DEFAULT_STAGES],
        "settings": {"theme": "light", "themeForAllUsers": False, "googleClientId": "", "costDefault": False},
    }


def empty_initial_state():
    """Only a default workspace and the built-in column definitions."""
    return {
        "version": 1,
        "workspaces": [
            {"id": "workspace-legacy", "name": "فضای کاری من", "archived": False},
        ],
        "boards": [],
        "projects": [],
        "tasks": [],
        "stages": [dict(stage) for stage in DEFAULT_STAGES],
        "settings": {"theme": "light", "themeForAllUsers": False, "googleClientId": "", "costDefault": False},
    }


def atomic_save(target: Path, data):
    data = normalize_state(data)
    is_valid(data)
    tmp = target.with_name(target.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with tmp.open("w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def safe_restore(target: Path, new_state):
    new_state = normalize_state(new_state)
    is_valid(new_state)
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup = target.with_name("backup-before-restore-" + stamp + ".json")
        shutil.copy2(target, backup)
    atomic_save(target, new_state)


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def protect_windows(raw, decrypt=False):
    if sys.platform != "win32":
        raise RuntimeError("رمزنگاری اتصال Google فقط در ویندوز قابل استفاده است.")
    input_buf = ctypes.create_string_buffer(raw)
    incoming = DataBlob(len(raw), ctypes.cast(input_buf, ctypes.POINTER(ctypes.c_byte)))
    output = DataBlob()
    crypt = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if decrypt:
        success = crypt(ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(output))
    else:
        success = crypt(ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(output))
    if not success:
        raise RuntimeError("ویندوز نتوانست اطلاعات ورود Google را رمزگشایی یا ذخیره کند.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(ctypes.cast(output.pbData, ctypes.c_void_p))


def http_json(url, method="GET", data=None, headers=None):
    payload = None
    if data is not None:
        payload = data if isinstance(data, bytes) else json.dumps(data).encode("utf8")
    req = Request(url, data=payload, headers=headers or {}, method=method)
    try:
        with urlopen(req, timeout=25) as res:
            return json.loads(res.read().decode("utf8"))
    except HTTPError as e:
        detail = e.read(1000).decode("utf8", errors="replace")
        if e.code == 409:
            raise RuntimeError("CONFLICT: نسخه سرور با نسخه ویرایش‌شده برابر نیست. " + detail[:160]) from e
        if e.code in (401,403):
            raise PermissionError("اجازه دسترسی ندارید یا نشست کاربری منقضی شده است: " + detail[:160]) from e
        raise RuntimeError(f"خطای سرویس HTTP {e.code}: {detail[:180]}") from e
    except URLError as e:
        raise ConnectionError("اتصال به سرور یا اینترنت برقرار نشد: " + str(e.reason)) from e


class Bridge:
    def __init__(self):
        self.path = datadir() / "tasks.json"
        self.unified_path = datadir() / "madar-unified.sqlite3"
        self.unified_marker = datadir() / "unified-active.json"
        self.auth = datadir() / "google-auth.bin"
        self.connection_path = datadir() / "lan-connection.json"
        self.client_auth_path = datadir() / "lan-login.bin"
        self.lan_users_path = datadir() / "lan-users.json"
        self.preferences_path = datadir() / "preferences.json"
        self.profile_path = datadir() / "personal-profile.json"
        self.profile_cache_path = datadir() / "lan-profiles-cache.json"
        self.backups_dir = datadir() / "backups"
        self.collab_path = datadir() / "collab.json"
        self.automation_buttons_path = datadir() / "automation-buttons.json"
        self.finance_path = datadir() / "finance.json"
        self.finance_outbox_path = datadir() / "finance-completion-outbox.json"
        self.automation_outbox_path = datadir() / "automation-card-outbox.json"
        self._finance_warning = ""
        from provider_csv_bridge import ProviderCsvPreviewBridge
        self._csv_preview = ProviderCsvPreviewBridge()
        self._lan_discovery = None
        self._lan_discovery_error = ""
        self.peer_code_path = datadir() / "cloud-peer-code.bin"
        self.offline = OfflineStore(datadir())
        self._network_available = True
        self._last_network_sync = None
        self._lock = threading.RLock()
        self._unified_store = None
        if self.unified_marker.exists():
            marker = json.loads(self.unified_marker.read_text(encoding="utf8"))
            if marker != {"schema": 1, "database": self.unified_path.name}:
                raise RuntimeError("نشانگر پایگاه داده مدار معتبر نیست؛ بازیابی دستی لازم است.")
            if not self.unified_path.is_file():
                raise RuntimeError("فایل پایگاه داده فعال مدار پیدا نشد؛ از بکاپ بازیابی کنید.")
            store = UnifiedAppStorage(self.unified_path)
            if store.load() is None or not store.integrity_check():
                raise RuntimeError("اعتبار پایگاه داده فعال مدار تایید نشد؛ نوشتن متوقف شد.")
            self._unified_store = store
        if self._unified_store is None and not self.path.exists():
            atomic_save(self.path, empty_initial_state())
        self.state = self._load()
        # Older Python callers use getState()/saveState() directly. Keep a
        # revision baseline for those callers; modern UI writes require an
        # explicit token issued by getStateForUi().
        self._observed_local_revision = revision(self.state)
        self._ui_cas_required = False
        self.lan = None
        self.remote_token = None
        self.remote_revision = None
        self.remote_user = None
        self._last_client_reconnect_attempt = 0.0
        self.connection = self._connection_config()
        if self.connection.get("mode") == "server":
            self.lan = LanService(self, self.lan_users_path,
                                  port=int(self.connection.get("port", 48370)),
                                  certfile=self.connection.get("certfile") or None,
                                  keyfile=self.connection.get("keyfile") or None)
            try:
                # A legacy HTTP host must not mutate local assignments or
                # start a network listener while attempting auto-resume.
                if not self.lan.certfile:
                    raise ValueError("میزبان شبکه بدون HTTPS غیرفعال شد؛ گواهی TLS تنظیم کنید.")
                self.lan.start()
                # Do not change assignments if TLS certificate/key validation
                # or listener startup fails.
                self._migrate_local_assignees_to_owner()
                self._start_lan_discovery()
            except (OSError, ValueError) as error:
                # Preserve the saved configuration for explicit TLS repair,
                # but do not silently revive a plaintext host.
                self.lan = None
                self.connection = {"mode": "solo", "error": str(error)}
        elif self.connection.get("mode") == "client":
            try:
                credentials = json.loads(protect_windows(self.client_auth_path.read_bytes(), True))
                self._remote_login(self.connection["url"], credentials["username"],
                                   credentials["password"],
                                   fingerprint=self.connection.get("fingerprint", ""))
            except (OSError, ValueError, RuntimeError, KeyError) as e:
                self.connection["error"] = str(e)
                cached_user = self.offline.cached_user()
                if cached_user:
                    self.remote_user = cached_user
                self._network_available = False
        if self.connection.get("mode") != "client":
            try:
                with self._lock:
                    self._drain_finance_outbox()
                    self._drain_automation_outbox()
            except (ValueError, PermissionError, RuntimeError, OSError) as error:
                self._finance_warning = str(error)

    def _connection_config(self):
        if not self.connection_path.exists():
            return {"mode": "solo"}
        return json.loads(self.connection_path.read_text(encoding="utf8"))

    def _stop_lan_discovery(self):
        responder = self._lan_discovery
        self._lan_discovery = None
        if responder is not None:
            responder.stop()

    def _start_lan_discovery(self):
        """Advertise only a live HTTPS LAN Host; discovery grants no trust."""
        if not self.lan or not self.lan.server or not self.lan.certfile:
            self._stop_lan_discovery()
            return
        if self._lan_discovery is not None and self._lan_discovery.running:
            return
        try:
            from lan_discovery import DiscoveryResponder
            responder = DiscoveryResponder(socket.gethostname()[:64],
                                           self.lan.port, self.lan.certfile)
            responder.start()
            self._lan_discovery = responder
            self._lan_discovery_error = ""
        except (OSError, ValueError, RuntimeError) as error:
            # Other LAN services must continue even if UDP is blocked or
            # already owned. Do not claim this host is discoverable.
            self._lan_discovery_error = str(error)

    def getPreferences(self):
        if not self.preferences_path.exists():
            raw = {}
        else:
            raw = json.loads(self.preferences_path.read_text(encoding="utf8"))
        if not isinstance(raw, dict):
            raw = {}
        default_widget = {"mode": "both", "theme": "aurora", "size": "regular",
                          "hourFormat": "24", "dateFormat": "full", "placement": "topbar",
                          "position": {"x": 0.83, "y": 0.12}}
        old_mode = raw.get("clockWidget", "both")
        if old_mode in ("both", "clock", "date", "hidden"):
            default_widget["mode"] = old_mode
        source = raw.get("widgetSettings")
        if isinstance(source, dict):
            for key, valid in (("mode", ("both", "clock", "date", "hidden")),
                               ("theme", ("light", "dark", "aurora")),
                               ("size", ("compact", "regular", "large")),
                               ("hourFormat", ("12", "24")),
                               ("dateFormat", ("compact", "full")),
                               ("placement", ("topbar", "floating", "top-left", "top-right",
                                              "bottom-left", "bottom-right"))):
                if source.get(key) in valid:
                    default_widget[key] = source[key]
            point = source.get("position")
            if (isinstance(point, dict) and all(
                    isinstance(point.get(k), (int, float)) and not isinstance(point.get(k), bool)
                    and 0 <= point[k] <= 1 for k in ("x", "y"))):
                default_widget["position"] = {"x": float(point["x"]), "y": float(point["y"])}
        return {
            "calendar": raw.get("calendar", "jalali") if raw.get("calendar") in ("jalali", "gregorian") else "jalali",
            "clockWidget": default_widget["mode"],
            "widgetSettings": default_widget,
        }

    def _clear_profile_cache(self):
        """A roster is private to its authenticated account and specific host."""
        self.profile_cache_path.unlink(missing_ok=True)

    def _profile_cache_identity(self):
        """Derive a non-secret cache identity from the current saved LAN login.

        Do not trust the offline user's username alone: the offline state cache
        may belong to an earlier LAN login on the same Windows account.
        """
        if self.connection.get("mode") != "client" or not isinstance(self.remote_user, dict):
            return None
        try:
            credentials = json.loads(protect_windows(self.client_auth_path.read_bytes(), True))
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            return None
        user = self.remote_user
        username = user.get("username")
        if (not isinstance(credentials, dict) or not isinstance(username, str)
                or not username or credentials.get("username") != username
                or user.get("role") not in ("admin", "editor", "viewer")):
            return None
        grants = user.get("projects")
        if grants is not None:
            if (not isinstance(grants, list) or
                    any(not isinstance(project, str) for project in grants)):
                return None
            grants = sorted(set(grants))
        url = self.connection.get("url")
        fingerprint = self.connection.get("fingerprint", "")
        if not isinstance(url, str) or not url or not isinstance(fingerprint, str):
            return None
        server = hashlib.sha256(json.dumps(
            [url.rstrip("/"), fingerprint.lower()],
            separators=(",", ":"), ensure_ascii=True).encode("utf8")).hexdigest()
        return {"server": server, "username": username,
                "role": user["role"], "projects": grants}

    def _read_profile_cache(self, identity):
        if identity is None or not self.profile_cache_path.is_file():
            return None
        try:
            if self.profile_cache_path.stat().st_size > 15_000_000:
                return None
            envelope = json.loads(self.profile_cache_path.read_text(encoding="utf8"))
        except (OSError, ValueError, UnicodeError):
            return None
        # Reject historic bare-list caches; they carry no authorization context.
        if (not isinstance(envelope, dict) or envelope.get("version") != 1
                or envelope.get("identity") != identity
                or not isinstance(envelope.get("profiles"), list)):
            return None
        profiles = envelope["profiles"]
        if len(profiles) > 2000:
            return None
        try:
            return [self._public_cached_profile(profile) for profile in profiles]
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _public_cached_profile(profile):
        """Whitelist LAN directory fields, never persist secrets from a response."""
        if not isinstance(profile, dict):
            raise ValueError("LAN profile is not an object")
        username = profile.get("username")
        role = profile.get("role")
        projects = profile.get("projects")
        if (not isinstance(username, str) or not 3 <= len(username) <= 40
                or not all(c.isascii() and (c.isalnum() or c in "._-") for c in username)
                or role not in ("admin", "editor", "viewer")
                or (projects is not None and (not isinstance(projects, list)
                    or len(projects) > 2000 or
                    any(not isinstance(value, str) for value in projects)))):
            raise ValueError("LAN profile identity is invalid")
        result = public_user(profile)
        # Server /api/profiles already supplies the *effective* presentation
        # role. Recomputing through public_user() alone loses custom role IDs
        # because the client does not possess the host's private role catalog.
        # Retain only bounded, allowlisted presentation fields, never tokens,
        # secrets or any extra fields in the live response or offline cache.
        from role_profiles import DISPLAY_FEATURE_TIERS, MODE_RANK, ID_PATTERN
        if "displayRole" in profile:
            identifier = profile["displayRole"]
            mode = profile.get("displayMode")
            label = profile.get("displayRoleLabel", identifier)
            features = profile.get("displayFeatures")
            if (type(identifier) is not str or not ID_PATTERN.fullmatch(identifier)
                    or type(mode) is not str or mode not in MODE_RANK
                    or type(label) is not str or not 1 <= len(label) <= 60
                    or any(ord(c) < 32 or ord(c) == 127 for c in label)
                    or type(features) is not list or len(features) > len(DISPLAY_FEATURE_TIERS)
                    or len(features) != len(set(map(str, features)))
                    or any(type(key) is not str or key not in DISPLAY_FEATURE_TIERS or
                           MODE_RANK[DISPLAY_FEATURE_TIERS[key]] > MODE_RANK[mode]
                           for key in features)):
                raise ValueError("LAN presentation profile contains invalid fields")
            result.update({"displayRole": identifier, "displayMode": mode,
                           "displayRoleLabel": label, "displayFeatures": list(features)})
        return result

    def lanProfiles(self):
        if self.connection.get("mode") == "client":
            identity = self._profile_cache_identity()
            try:
                if not self.remote_token:
                    raise ConnectionError("No authenticated LAN session")
                profiles = [self._public_cached_profile(profile) for profile in
                            self._remote_request("/api/profiles")["users"]]
                # A valid live response is usable even before credentials have
                # been saved; only identity-verified responses are cached.
                if identity is not None:
                    from offline_exchange import atomic_json
                    atomic_json(self.profile_cache_path,
                                {"version": 1, "identity": identity, "profiles": profiles})
                return profiles
            except RuntimeError as error:
                if "اتصال به Google برقرار نشد" not in str(error):
                    raise
            except (ConnectionError, TimeoutError, OSError):
                pass
            cached = self._read_profile_cache(identity)
            if cached is not None:
                return cached
            return [self._public_cached_profile(self.remote_user)] if identity is not None else []
        if self.lan:
            return self.lan.list_profiles(self.lan.authenticate_owner_token())
        profile = json.loads(self.profile_path.read_text(encoding="utf8")) if self.profile_path.exists() else {}
        return [{"username": "local", "role": "admin", "projects": None,
                 **clean_profile({}, {"displayName": "من", **profile})}]

    def lanMyProfile(self, payload):
        if self.connection.get("mode") == "client":
            result = self._remote_request("/api/profile", payload)["user"]
            self.remote_user = result
            self._clear_profile_cache()
            return result
        if self.lan:
            return self.lan.update_profile(self.lan.authenticate_owner_token(), payload)
        updated = clean_profile(payload, self.lanProfiles()[0])
        tmp = self.profile_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(updated, ensure_ascii=False), encoding="utf8")
        tmp.replace(self.profile_path)
        return self.lanProfiles()[0]

    def lanChangePassword(self, current, new_password):
        if self.connection.get("mode") == "client":
            result = self._remote_request("/api/password", {
                "current": current, "newPassword": new_password})["ok"]
            # Ensure the saved Windows DPAPI connection survives app restart.
            if result and self.client_auth_path.exists():
                creds = json.loads(protect_windows(self.client_auth_path.read_bytes(), True))
                creds["password"] = new_password
                self.client_auth_path.write_bytes(protect_windows(json.dumps(creds).encode()))
            return result
        if self.lan:
            # The console owner is authenticated locally as the initial admin.
            return self.lan.change_password(self.lan.authenticate_owner_token(), current, new_password)
        raise ValueError("حساب شبکه‌ای فعال نیست.")

    def lanResetPassword(self, username, new_password):
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/reset-password", {
                "username": username, "newPassword": new_password})["ok"]
        if self.lan:
            return self.lan.reset_password(self.lan.authenticate_owner_token(), username, new_password)
        raise ValueError("ابتدا شبکه محلی را فعال کنید.")

    def setPreferences(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("تنظیمات نمایشی معتبر نیست.")
        current = self.getPreferences()
        calendar = payload.get("calendar", current["calendar"])
        clock_widget = payload.get("clockWidget", current["clockWidget"])
        if calendar not in ("jalali", "gregorian") or clock_widget not in ("both", "clock", "date", "hidden"):
            raise ValueError("تنظیمات ساعت یا تقویم معتبر نیست.")
        widget = dict(current["widgetSettings"])
        if "widgetSettings" in payload:
            incoming = payload["widgetSettings"]
            if not isinstance(incoming, dict) or set(incoming) - set(widget):
                raise ValueError("گزینه‌های ویجت نامعتبر هستند.")
            for key, valid in (("mode", ("both", "clock", "date", "hidden")),
                               ("theme", ("light", "dark", "aurora")),
                               ("size", ("compact", "regular", "large")),
                               ("hourFormat", ("12", "24")),
                               ("dateFormat", ("compact", "full")),
                               ("placement", ("topbar", "floating", "top-left", "top-right",
                                              "bottom-left", "bottom-right"))):
                if key in incoming and incoming[key] not in valid:
                    raise ValueError("مقدار یکی از تنظیمات ویجت معتبر نیست.")
            if "position" in incoming:
                point = incoming["position"]
                if (not isinstance(point, dict) or set(point) != {"x", "y"} or
                        not all(isinstance(point[k], (float, int)) and not isinstance(point[k], bool)
                                and 0 <= point[k] <= 1 for k in ("x", "y"))):
                    raise ValueError("موقعیت ویجت باید در محدوده صفحه باشد.")
            widget.update(incoming)
        elif "clockWidget" in payload:
            widget["mode"] = clock_widget
        temp = self.preferences_path.with_suffix(".tmp")
        temp.write_text(json.dumps({"calendar": calendar, "clockWidget": widget["mode"],
                                    "widgetSettings": widget}), encoding="utf8")
        temp.replace(self.preferences_path)
        return self.getPreferences()

    def downloadSharedFile(self, path):
        if not valid_share_path(path):
            raise ValueError('مسیر فایل اشتراکی معتبر نیست.')
        if sys.platform != 'win32':
            raise RuntimeError('دانلود فایل اشتراکی فقط در ویندوز فعال است.')
        return copy_shared_file_to_directory(path.replace('/', '\\'), windows_downloads_directory())

    def openSharedFile(self, path):
        if not valid_share_path(path):
            raise ValueError("فقط مسیر فایل SMB از نوع \\\\Server\\Share\\Folder\\File مجاز است.")
        if sys.platform != "win32":
            raise RuntimeError("بازکردن فایل اشتراکی فقط در ویندوز فعال است.")
        # Runs locally on the client with the current Windows SMB permissions.
        location = path.replace("/", "\\")
        if os.path.isfile(location):
            args = ["explorer.exe", "/select,", location]
        elif os.path.isdir(location):
            args = ["explorer.exe", location]
        else:
            raise FileNotFoundError("فایل یا پوشه اشتراکی در دسترس نیست؛ مسیر و مجوز SMB را بررسی کنید.")
        subprocess.Popen(args, close_fds=True)
        return {"opened": True, "kind": "file" if len(args) == 3 else "folder"}

    def chooseSharedFile(self):
        """Pick an SMB file, recording only a portable UNC path."""
        if sys.platform != "win32":
            raise RuntimeError("انتخاب فایل اشتراکی فقط در ویندوز فعال است.")
        chosen = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN)
        if not chosen:
            return {"canceled": True}
        selected = str(chosen if isinstance(chosen, str) else chosen[0])
        if re.match(r"^[A-Za-z]:[\\/]", selected):
            capacity = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(capacity.value)
            status = ctypes.windll.mpr.WNetGetConnectionW(
                selected[:2], buffer, ctypes.byref(capacity))
            if status == 0:
                selected = buffer.value.rstrip("\\") + selected[2:]
        if not valid_share_path(selected):
            raise ValueError("فقط فایل‌های اشتراک شبکه پذیرفته می‌شوند؛ مسیر C: یا درایو محلی منتشر نمی‌شود.")
        return {"path": selected.replace("/", "\\"), "name": Path(selected).name}

    def releaseCheck(self):
        """Only fetch public version metadata; no tasks, tokens or LAN data."""
        return madar_update.check()

    def releaseDownload(self):
        """Never trust asset URLs supplied by JavaScript."""
        return madar_update.download(madar_update.check())

    def releaseInstall(self):
        """Explicit opt-in: defer the verified Inno installer until GUI exits.

        Inno performs an independently verified desktop-profile backup before
        switching versions. The separately running MadarHost is never stopped.
        """
        info = madar_update.check()
        saved = madar_update.download(info)
        return madar_update.schedule_verified_install(info, saved)

    def downloadSharedFile(self, path):
        if not valid_share_path(path):
            raise ValueError("فقط مسیر فایل SMB از نوع \\\\Server\\Share\\Folder\\File مجاز است.")
        if sys.platform != "win32":
            raise RuntimeError("دانلود فایل اشتراکی فقط در ویندوز فعال است.")
        # The user's own SMB credentials determine read access on this client.
        return copy_shared_file_to_directory(path.replace("/", "\\"),
                                             windows_downloads_directory())

    def createLocalBackup(self):
        if self.connection.get("mode") == "client":
            raise PermissionError("پشتیبان محلی باید روی سیستم میزبان ساخته شود.")
        with self._lock:
            self.backups_dir.mkdir(exist_ok=True, parents=True)
            if self._unified_store is not None:
                name = datetime.now(timezone.utc).strftime("madar-unified-%Y%m%d-%H%M%S-%f.sqlite3")
                output = self.backups_dir / name
                prior = self._unified_store.load()
                if prior is None:
                    raise RuntimeError("پشتیبان‌گیری انجام نشد: نسخه معتبر SQLite وجود ندارد.")
                self._unified_store.backup_database(output)
                try:
                    # Open the published file read-only; never repair or mutate
                    # the backup while deciding whether to report success.
                    with closing(sqlite3.connect(output.resolve().as_uri() + "?mode=ro", uri=True)) as copy:
                        check = copy.execute("PRAGMA quick_check").fetchone()
                        head = copy.execute(
                            "SELECT revision,digest FROM app_revisions WHERE revision="
                            "(SELECT revision FROM app_head WHERE id=1)"
                        ).fetchone()
                    if check != ("ok",) or head != (prior.revision, prior.sha256):
                        raise ValueError("snapshot does not match committed host revision")
                except (sqlite3.Error, ValueError, OSError) as error:
                    raise RuntimeError("پشتیبان‌گیری SQLite نامعتبر است؛ فایل را برای بازیابی استفاده نکنید.") from error
                return {"name": name, "path": str(output), "complete": False,
                        "scope": "sqlite-domains-only",
                        "omitted": ["attachment-binaries", "planner-local-storage",
                                    "lan-accounts", "login-credentials"],
                        "note": "This is a partial SQLite snapshot; attachment files, LAN accounts and local Planner are excluded."}
            current = self.getState()
            name = datetime.now(timezone.utc).strftime("madar-%Y%m%d-%H%M%S-%f.json")
            output = self.backups_dir / name
            atomic_save(output, current)
            try:
                with output.open(encoding="utf8") as stream:
                    recovered = json.load(stream)
                if recovered != normalize_state(current) or not is_valid(recovered):
                    raise ValueError("snapshot differs from committed host state")
            except (OSError, ValueError, TypeError) as error:
                raise RuntimeError("پشتیبان‌گیری JSON نامعتبر است؛ فایل را برای بازیابی استفاده نکنید.") from error
            return {"name": name, "path": str(output), "complete": False,
                    "scope": "task-state-only",
                    "omitted": ["finance", "collaboration", "attachment-binaries",
                                "planner-local-storage", "lan-accounts", "login-credentials"],
                    "note": "This JSON file contains task and board state only; it is not a full application backup."}

    def _automatic_backup_before_change(self):
        """One recoverable pre-edit snapshot each UTC day, not per keystroke."""
        self.backups_dir.mkdir(exist_ok=True, parents=True)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        if self._unified_store is not None:
            if list(self.backups_dir.glob("auto-unified-" + today + "-*.sqlite3")):
                return
            name = "auto-unified-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".sqlite3"
            self._unified_store.backup_database(self.backups_dir / name)
            return
        if list(self.backups_dir.glob("auto-" + today + "-*.json")):
            return
        name = "auto-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".json"
        previous = self._load()
        atomic_save(self.backups_dir / name, previous)
        older = sorted(self.backups_dir.glob("auto-*.json"), reverse=True)
        for stale in older[30:]:
            stale.unlink()

    def listLocalBackups(self):
        if self.connection.get("mode") == "client":
            return []
        self.backups_dir.mkdir(exist_ok=True, parents=True)
        backups = [*self.backups_dir.glob("madar-*.json"),
                   *self.backups_dir.glob("auto-*.json"),
                   *self.backups_dir.glob("madar-unified-*.sqlite3"),
                   *self.backups_dir.glob("auto-unified-*.sqlite3")]
        return [{"name": p.name, "size": p.stat().st_size} for p in
                sorted(backups, key=lambda file: file.stat().st_mtime, reverse=True)[:60]]

    def restoreLocalBackup(self, filename):
        if self.connection.get("mode") == "client":
            raise PermissionError("بازیابی فقط روی سیستم میزبان مجاز است.")
        if not isinstance(filename, str) or not re.fullmatch(
            r"(?:madar|auto)(?:-unified)?-\d{8}-\d{6}-\d{6}\.(?:json|sqlite3)", filename
        ):
            raise ValueError("نام نسخه پشتیبان معتبر نیست.")
        source = self.backups_dir / filename
        with self._lock:
            if filename.endswith(".sqlite3"):
                if self._unified_store is None:
                    raise RuntimeError("برای بازیابی بکاپ SQLite ابتدا ذخیره‌سازی یکپارچه را فعال کنید.")
                restored = UnifiedAppStorage(source)
                if not restored.integrity_check() or restored.load() is None:
                    raise ValueError("پشتیبان SQLite معتبر نیست.")
                self._replace_local_bundle(restored.load().bundle)
            else:
                incoming = normalize_state(json.loads(source.read_text(encoding="utf8")))
                self._replace_local_state(incoming)
            return self.state

    def storageStatus(self):
        """Indicate authoritative storage and migration readiness to the UI."""
        with self._lock:
            snapshot = self._unified_store.load() if self._unified_store else None
            return {"mode": "sqlite" if snapshot else "json",
                    "revision": snapshot.revision if snapshot else None,
                    "ready": self.connection.get("mode") != "client"}

    def plannerRead(self, account_id):
        """Read private Planner state from the Windows profile, not a random HTTP port."""
        from planner_persistence import PlannerPersistence
        with self._lock:
            return PlannerPersistence(self.path.parent).read(account_id)

    def plannerWrite(self, account_id, state):
        """Durably save personal Planner data with validation and recovery copy."""
        from planner_persistence import PlannerPersistence
        with self._lock:
            return PlannerPersistence(self.path.parent).write(account_id, state)

    def automationEngineStatus(self):
        """Expose only non-sensitive engine counts on its owning host."""
        if self.connection.get("mode") == "client":
            return {"mode": "remote", "ready": False, "pending": 0, "dead": 0}
        with self._lock:
            if self._unified_store is None:
                return {"mode": "legacy", "ready": False, "pending": 0, "dead": 0}
            snapshot = self._unified_store.load()
            engine = snapshot.bundle.get("automation")
            if engine is None:
                return {"mode": "disabled", "ready": True, "pending": 0, "dead": 0}
            return {"mode": "active", "ready": True,
                    "pending": sum(1 for job in engine["jobs"] if job["status"] != "dead"),
                    "dead": sum(1 for job in engine["jobs"] if job["status"] == "dead"),
                    "audit": len(engine["audit"])}

    def enableAutomationEngine(self):
        """Explicit one-way opt-in after a verified pre-activation SQL backup."""
        if self.connection.get("mode") == "client":
            raise PermissionError("فعال‌سازی موتور اتوماسیون فقط روی میزبان مجاز است.")
        from contextlib import nullcontext
        # Keep the same acquisition order as LAN requests: service then host.
        with (self.lan.lock if self.lan else nullcontext()), self._lock:
            if self._unified_store is None:
                raise RuntimeError("ابتدا ذخیره‌سازی یکپارچه SQLite را فعال کنید.")
            current = self._unified_store.load()
            if "automation" in current.bundle:
                return self.automationEngineStatus()
            self._drain_automation_outbox(accounts=self.lan.users if self.lan else None)
            if self._pending_automation_events():
                raise RuntimeError("صف قدیمی اتوماسیون هنوز تخلیه نشده؛ فعال‌سازی متوقف شد.")
            from app_storage import with_automation
            self.backups_dir.mkdir(exist_ok=True, parents=True)
            archive = self.backups_dir / (
                "pre-automation-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".sqlite3")
            self._unified_store.backup_database(archive)
            self._unified_store.commit(with_automation(current.bundle),
                                       expected_revision=current.revision)
            return {**self.automationEngineStatus(), "preActivationBackup": str(archive)}

    def enableUnifiedStorage(self):
        """Explicit backup-first one-way host migration to four-domain SQLite."""
        if self.connection.get("mode") == "client":
            raise PermissionError("مهاجرت فقط روی رایانه میزبان انجام می‌شود.")
        with self._lock:
            if self._unified_store is not None:
                return self.storageStatus()
            if self.unified_marker.exists() or self.unified_path.exists():
                raise RuntimeError("پایگاه داده یا نشانگر قبلی وجود دارد؛ برای جلوگیری از حذف اطلاعات، مهاجرت متوقف شد.")
            self.backups_dir.mkdir(exist_ok=True, parents=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            immutable_sources = self.backups_dir / ("migration-originals-" + stamp)
            store = UnifiedAppStorage(self.unified_path)
            def existing(path):
                return path if path.is_file() else None
            snapshot = store.import_legacy(
                self.path, collab_json=existing(self.collab_path),
                finance_json=existing(self.finance_path),
                outbox_json=existing(self.finance_outbox_path),
                backup_dir=immutable_sources)
            if not store.integrity_check():
                raise RuntimeError("اعتبارسنجی مهاجرت SQLite ناموفق بود.")
            # Activate only after the entire source backup and SQL commit succeeded.
            from offline_exchange import atomic_json
            atomic_json(self.unified_marker, {"schema": 1, "database": self.unified_path.name})
            self._unified_store = store
            self.state = normalize_state(snapshot.bundle["tasks"])
            return self.storageStatus()

    def _commit_domains(self, changes, *, expected_finance_sha256=None):
        """Update one or more domains, with a single SQL revision when enabled."""
        from offline_exchange import atomic_json
        paths = {"collab": self.collab_path, "finance": self.finance_path,
                 "completion_outbox": self.finance_outbox_path}
        if not changes or any(key not in paths for key in changes):
            raise ValueError("Invalid storage domain")
        if expected_finance_sha256 is not None:
            if (set(changes) != {"finance"} or
                    type(expected_finance_sha256) is not str or
                    not re.fullmatch(r"[a-f0-9]{64}", expected_finance_sha256)):
                raise ValueError("Invalid finance CAS precondition")
        if self._unified_store is not None:
            current = self._unified_store.load()
            if expected_finance_sha256 is not None:
                from money_policy import snapshot_sha256
                if snapshot_sha256(current.bundle["finance"]) != expected_finance_sha256:
                    raise RuntimeError("CONFLICT: authoritative finance changed before commit")
            candidate = current.bundle
            candidate.update(changes)
            self._unified_store.commit(candidate, expected_revision=current.revision)
        else:
            if expected_finance_sha256 is not None:
                # A legacy JSON file has no shared transactional CAS. Do not
                # claim dual-ledger atomicity for its writes.
                raise ValueError("Finance CAS requires unified SQLite mode")
            for key, value in changes.items():
                atomic_json(paths[key], value)

    def _commit_domain(self, domain, value, *, expected_finance_sha256=None):
        with self._lock:
            self._commit_domains({domain: value},
                                 expected_finance_sha256=expected_finance_sha256)

    def _replace_local_bundle(self, bundle):
        """Restore a full snapshot without moving the authoritative SQLite file."""
        if self._unified_store is None:
            raise RuntimeError("بازیابی کامل فقط با SQLite فعال ممکن است.")
        validated = normalize_state(bundle["tasks"])
        is_valid(validated)
        self._unified_store.backup_database(self.backups_dir / (
            "before-restore-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".sqlite3"))
        current = self._unified_store.load()
        candidate = {**bundle, "tasks": validated}
        self._unified_store.commit(candidate, expected_revision=current.revision)
        self.state = validated

    def _replace_local_state(self, incoming):
        validated = normalize_state(incoming)
        is_valid(validated)
        # JSON/Drive are tasks-only snapshots, not full-domain recovery.
        # Validate preserved collaboration, permission and financial identities
        # before creating any restore backup or changing authoritative data.
        from project_integrity import ensure_partial_restore_safe
        ensure_partial_restore_safe(
            self._load(), validated, collaboration=self._load_collab(),
            finance=self._load_finance(),
            accounts=self.lan.users if self.lan else None)
        if self._unified_store is not None:
            current = self._unified_store.load()
            self._replace_local_bundle({**current.bundle, "tasks": validated})
        else:
            safe_restore(self.path, validated)
            self.state = validated

    def _save_connection(self, config):
        old = self.connection
        if (old.get("mode"), old.get("url"), old.get("fingerprint")) != (
                config.get("mode"), config.get("url"), config.get("fingerprint")):
            self._clear_profile_cache()
        tmp = self.connection_path.with_name("lan-connection.tmp")
        tmp.write_text(json.dumps(config), encoding="utf8")
        tmp.replace(self.connection_path)
        self.connection = config

    def _remote_request(self, endpoint, payload=None, login=False):
        if self.connection.get("mode") != "client":
            raise RuntimeError("برنامه به سرور دیگری متصل نیست.")
        base = self.connection["url"]
        target = _validate_lan_target(base)
        headers = {"Content-Type": "application/json"}
        if not login:
            if not self.remote_token:
                raise RuntimeError("اتصال شبکه قطع است؛ دوباره وارد شوید.")
            headers["Authorization"] = "Bearer " + self.remote_token
        try:
            # Use the parsed scheme, not case-sensitive string prefix checks.
            # A mixed-case HTTPS origin must NEVER bypass certificate pinning.
            if target.scheme == "https":
                result = pinned_https_json(
                    base + endpoint, self.connection.get("fingerprint", ""),
                    method="POST" if payload is not None else "GET",
                    data=payload, headers=headers)
            else:
                result = http_json(base + endpoint,
                                   method="POST" if payload is not None else "GET",
                                   data=payload, headers=headers)
            self._network_available = True
            self._last_network_sync = datetime.now(timezone.utc).isoformat()
            return result
        except HTTPError as e:
            detail = e.read(1000).decode("utf8", errors="replace")
            if e.code == 409:
                raise RuntimeError("CONFLICT: نسخه سرور تغییر کرده است. " + detail[:160]) from e
            if e.code in (401, 403):
                if e.code == 401 and not login:
                    # An expired/revoked session can be restored from the
                    # existing Windows-protected credentials on the next poll.
                    self.remote_token = None
                    self._network_available = False
                raise PermissionError("دسترسی رد شد یا نشست منقضی شده است: " + detail[:160]) from e
            raise RuntimeError(f"خطای سرویس HTTP {e.code}: {detail[:180]}") from e
        except Exception as exc:
            if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or (
                isinstance(exc, RuntimeError) and "اتصال به Google برقرار نشد" in str(exc)
            ):
                self._network_available = False
            raise

    def _remote_login(self, url, username, password, *, fingerprint=""):
        parsed = _validate_lan_target(url)
        if parsed.scheme == "https":
            if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", fingerprint):
                raise ValueError("برای HTTPS اثر انگشت کامل SHA-256 میزبان لازم است.")
        elif fingerprint:
            raise ValueError("اثر انگشت TLS فقط با نشانی HTTPS قابل استفاده است.")
        previous = self.connection
        self.connection = {"mode": "client", "url": url.rstrip("/"),
                           "fingerprint": fingerprint.lower() if fingerprint else ""}
        try:
            response = self._remote_request("/api/login", {"username": username,
                                                           "password": password}, login=True)
            self.remote_token = response["token"]
            self.remote_user = response["user"]
            latest = self._remote_request("/api/state")
            self.remote_revision = latest["revision"]
            self.state = latest["state"]
            self.offline.remember(self.state, self.remote_revision, username, self.remote_user)
            return self.remote_user
        except Exception:
            self.connection = previous
            self.remote_token = None
            self.remote_user = None
            raise

    def _maybe_reconnect_client(self):
        """Reconnect a previously paired client, retaining unsent local edits.

        Only the existing DPAPI-protected login is used. No discovered host
        address or fingerprint is trusted as a replacement for the saved pin.
        Call under ``_lock``; bounded retry frequency avoids LAN storms.
        """
        if self.connection.get("mode") != "client":
            return False
        if self._network_available and self.remote_token:
            return False
        stamp = time.monotonic()
        if stamp - self._last_client_reconnect_attempt < 10:
            return False
        self._last_client_reconnect_attempt = stamp
        credentials = json.loads(protect_windows(self.client_auth_path.read_bytes(), True))
        if not all(isinstance(credentials.get(k), str) and credentials[k]
                   for k in ("username", "password")):
            raise ValueError("اطلاعات ورود ذخیره‌شده معتبر نیست.")
        configured = self.connection.copy()
        self._remote_login(configured["url"], credentials["username"],
                           credentials["password"],
                           fingerprint=configured.get("fingerprint", ""))
        # _remote_login's offline.remember intentionally preserves the local
        # pending queue. Reconcile through the authoritative Host before ACK.
        self._sync_client_from_host()
        self.connection.pop("error", None)
        return True

    def lanStatus(self, refresh=False):
        mode = self.connection.get("mode", "solo")
        if mode == "client":
            if refresh is True and (not self.remote_token or not self._network_available):
                with self._lock:
                    try:
                        self._maybe_reconnect_client()
                    except (OSError, ValueError, RuntimeError, PermissionError, KeyError) as error:
                        self._network_available = False
                        self.connection["error"] = str(error)
            if refresh is True and self.remote_token and self._network_available:
                try:
                    fresh = self._remote_request("/api/me").get("user")
                    if isinstance(fresh, dict) and fresh.get("username") == (self.remote_user or {}).get("username"):
                        self.remote_user = fresh
                except (OSError, ValueError, RuntimeError, PermissionError):
                    # Preserve the validated offline account snapshot. Network
                    # permission checks still occur on the authoritative host.
                    pass
            return {"mode": mode, "url": self.connection.get("url", ""),
                    "transport": "https" if self.connection.get("url", "").lower().startswith("https://") else "http",
                    "fingerprint": self.connection.get("fingerprint", ""),
                    "user": self.remote_user, "connected": self._network_available,
                    "pending": self.offline.has_pending(),
                    "cloudFolder": self.offline.folder_status().get("configured", False),
                    "lastSync": self._last_network_sync,
                    "error": self.connection.get("error", "")}
        return {"mode": mode, "port": self.lan.port if self.lan else 48370,
                "transport": "https" if self.lan and self.lan.certfile else "http",
                "fingerprint": certificate_fingerprint(self.lan.certfile)
                if self.lan and self.lan.certfile else "",
                "usersReady": bool(self.lan and self.lan.users),
                "user": self.lan.list_profiles(self.lan.authenticate_owner_token())[0]
                if mode == "server" else self.lanProfiles()[0],
                "error": self.connection.get("error", "")}

    def lanDiscover(self):
        """Find LAN hosts without sending credentials or trusting UDP metadata.

        A discovered fingerprint is merely a hint; the user still has to
        verify it with the host before HTTPS authentication can begin.
        """
        from lan_discovery import discover_hosts
        return discover_hosts(timeout=1.5)

    def hostServiceStatus(self):
        """Read the optional background Windows service state without changing it."""
        if sys.platform != "win32":
            return {"supported": False, "installed": False, "running": False}
        try:
            result = subprocess.run(["sc.exe", "query", "MadarHost"],
                                    capture_output=True, text=True, timeout=4,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0:
                return {"supported": True, "installed": False, "running": False}
            running = bool(re.search(r"(?m)^\s*STATE\s*:\s*4\s+", result.stdout))
            return {"supported": True, "installed": True, "running": running}
        except (OSError, subprocess.TimeoutExpired) as error:
            return {"supported": True, "installed": False, "running": False,
                    "error": "استعلام وضعیت سرویس ممکن نشد: " + str(error)}

    def automaticBackupStatus(self):
        """Report the local host-only 30-second task snapshot scheduler."""
        scheduler = getattr(self, "_host_periodic_backup", None)
        if scheduler is not None:
            return scheduler.status()
        return {"running": False, "intervalSeconds": 30, "complete": False,
                "scope": None, "lastSuccess": None,
                "mode": self.connection.get("mode", "solo")}

    def integrationIssueKey(self, username, permissions=None, lifetime_seconds=3600):
        """Explicit administrator action on the local HTTPS LAN host only."""
        if (self.connection.get("mode") != "server" or not self.lan
                or self.lan.integration_router is None):
            raise PermissionError("کلید API فقط روی میزبان LAN با HTTPS فعال ساخته می‌شود.")
        if not isinstance(username, str):
            raise ValueError("نام کاربر نامعتبر است.")
        if permissions is None:
            permissions = ["read"]
        if not isinstance(permissions, list) or any(not isinstance(x, str) for x in permissions):
            raise ValueError("مجوزهای API نامعتبر است.")
        return self.lan.integration_router.issue_key(
            self.lan.authenticate_owner_token(), username,
            permissions=permissions, lifetime_seconds=lifetime_seconds)

    def integrationRevokeKey(self, key_id):
        if (self.connection.get("mode") != "server" or not self.lan
                or self.lan.integration_router is None):
            raise PermissionError("ابطال کلید API فقط روی میزبان HTTPS مجاز است.")
        if not isinstance(key_id, str):
            raise ValueError("شناسه کلید API نامعتبر است.")
        return {"revoked": self.lan.integration_router.revoke_key(
            self.lan.authenticate_owner_token(), key_id)}

    def calendarExportIcs(self):
        """Read-only ICS export of cards visible to the current LAN account."""
        from calendar_interop import export_ics
        visible = self.getState()
        return export_ics(visible["tasks"]).decode("utf8")

    def calendarImportPreview(self, content):
        """Preview only: no state mutation. UI must commit through saveState ACL."""
        from calendar_interop import import_ics
        if self.connection.get("mode") == "client":
            if (self.remote_user or {}).get("role") != "admin":
                raise PermissionError("ورود فایل تقویم فقط برای مدیر مجاز است.")
        if not isinstance(content, str):
            raise ValueError("محتوای ICS باید متن باشد.")
        data = self.getState()
        existing = [card["calendarSourceKey"] for card in data["tasks"]
                    if isinstance(card.get("calendarSourceKey"), str)]
        return import_ics(content, existing_keys=existing)

    def lanHost(self, username, password, port=48370, certfile="", keyfile=""):
        if self.connection.get("mode") == "client":
            raise ValueError("ابتدا اتصال به سرور دیگر را قطع کنید.")
        if not isinstance(port, int) or not (1024 <= port <= 65535):
            raise ValueError("پورت معتبر نیست.")
        if bool(certfile) != bool(keyfile):
            raise ValueError("برای HTTPS فایل گواهی و کلید خصوصی هر دو لازم‌اند.")
        if not certfile:
            raise ValueError("میزبان LAN باید با گواهی و کلید HTTPS راه‌اندازی شود.")
        if certfile and (not isinstance(certfile, str) or not isinstance(keyfile, str)):
            raise ValueError("مسیر گواهی و کلید معتبر نیست.")
        certfile = str(Path(certfile).resolve()) if certfile else ""
        keyfile = str(Path(keyfile).resolve()) if keyfile else ""
        if certfile:
            certificate_fingerprint(certfile)
        if self.lan and (str(self.lan.certfile or "") != certfile
                         or str(self.lan.keyfile or "") != keyfile
                         or self.lan.port != port):
            self._stop_lan_discovery()
            self.lan.stop()
            self.lan = None
        if self.lan is None:
            self.lan = LanService(self, self.lan_users_path, port=port,
                                  certfile=certfile or None, keyfile=keyfile or None)
        if not self.lan.users:
            self.lan.setup_owner(username, password)
        self.lan.start()
        self._migrate_local_assignees_to_owner()
        self._start_lan_discovery()
        self._save_connection({"mode": "server", "port": self.lan.port,
                               "transport": "https" if certfile else "http",
                               "certfile": certfile, "keyfile": keyfile})
        return self.lanStatus()

    def _migrate_local_assignees_to_owner(self):
        """Preserve solo task assignments when the same PC becomes a LAN host."""
        if not self.lan:
            return
        owner = next((u["username"] for u in self.lan.users.values()
                      if u["role"] == "admin"), None)
        if not owner:
            return
        with self._lock:
            state = self._load()
            changed = False
            for task in state["tasks"]:
                if "local" in task.get("assignees", []):
                    task["assignees"] = list(dict.fromkeys(
                        owner if user == "local" else user
                        for user in task["assignees"]
                    ))
                    changed = True
            if changed:
                if self._unified_store is not None:
                    self._save_local_state(state)
                else:
                    backup = self.path.with_name(
                        "backup-before-host-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".json"
                    )
                    shutil.copy2(self.path, backup)
                    atomic_save(self.path, state)
                    self.state = state

    def lanJoin(self, url, username, password, fingerprint=""):
        if self.lan:
            raise ValueError("ابتدا سرور محلی خود را متوقف کنید.")
        # In particular, reject historical HTTP LAN URLs *before* clearing
        # another user's cached offline view or pending local state.
        _validate_lan_target(url)
        # Delete before authenticating: a failed account switch must not leave
        # another user's directory available to an offline fallback.
        self._clear_profile_cache()
        self._remote_login(url, username, password, fingerprint=fingerprint)
        self.client_auth_path.write_bytes(
            protect_windows(json.dumps({"username": username, "password": password}).encode()))
        self._save_connection({"mode": "client", "url": url.rstrip("/"),
                               "fingerprint": fingerprint.lower() if fingerprint else ""})
        return self.lanStatus()

    def lanLeave(self):
        self._clear_profile_cache()
        if self.lan:
            self._stop_lan_discovery()
            self.lan.stop()
            self.lan = None
        self.remote_token = None
        self.remote_revision = None
        self.remote_user = None
        self.client_auth_path.unlink(missing_ok=True)
        self._save_connection({"mode": "solo"})
        self.state = self._load()
        return self.lanStatus()

    def lanUsers(self):
        if self.lan:
            return [dict(u) for u in self.lan.list_users(self.lan.authenticate_owner_token())]
        result = self._remote_request("/api/users")
        return result["users"]

    def lanDisplayRoles(self):
        if self.lan:
            return self.lan.list_display_roles(self.lan.authenticate_owner_token())
        return self._remote_request("/api/display-roles")["roles"]

    def lanSaveDisplayRole(self, payload):
        if self.lan:
            return self.lan.upsert_display_role(self.lan.authenticate_owner_token(), payload)
        return self._remote_request("/api/display-roles", payload)["role"]

    def lanDeleteDisplayRole(self, identifier):
        if not isinstance(identifier, str):
            raise ValueError("شناسه قالب نمایش معتبر نیست.")
        if self.lan:
            return self.lan.delete_display_role(self.lan.authenticate_owner_token(), identifier)
        return self._remote_request("/api/display-roles", {"action": "delete", "id": identifier})["ok"]

    def lanSaveUser(self, payload):
        if self.lan:
            return self.lan.upsert_user(self.lan.authenticate_owner_token(), payload)
        return self._remote_request("/api/user", payload)["user"]

    def lanDeleteUser(self, username):
        if self.lan:
            return self.lan.delete_user(self.lan.authenticate_owner_token(), username)
        return self._remote_request("/api/users", {"username": username})["ok"]

    def _load(self):
        if self._unified_store is not None:
            snapshot = self._unified_store.load()
            if snapshot is None:
                raise RuntimeError("پایگاه داده فعال مدار هیچ نسخه‌ای ندارد.")
            obj = normalize_state(snapshot.bundle["tasks"])
        else:
            obj = normalize_state(json.loads(self.path.read_text(encoding="utf8")))
        is_valid(obj)
        return obj

    def syncStatus(self):
        try:
            drive_connected = self.driveStatus()["connected"]
        except (ValueError, RuntimeError, OSError):
            drive_connected = False
        return {"mode": self.connection.get("mode", "solo"),
                "connected": self._network_available if self.connection.get("mode") == "client" else True,
                "pending": self.offline.has_pending(), "lastSync": self._last_network_sync,
                "drive": drive_connected,
                "folder": self.offline.folder_status(),
                "peer": self.cloudPeerStatus()}

    def cloudPeerStatus(self):
        folder = self.offline.folder_status()
        return {"paired": self.peer_code_path.exists(),
                "enabled": bool(self.peer_code_path.exists() and folder.get("available")
                                and self.connection.get("mode") == "client"),
                "mode": "same-user-preview",
                "cloudVerified": False}

    def cloudPeerConfigure(self, code):
        """Explicit pairing between LAN clients sharing a Drive for desktop folder."""
        if self.connection.get("mode") != "client":
            raise ValueError("ابتدا به یک میزبان LAN وارد شوید.")
        if not isinstance(code, str) or len(code) < 24 or len(code) > 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", code):
            raise ValueError("کد جفت‌سازی باید حداقل ۲۴ نویسه انگلیسی باشد.")
        protected = protect_windows(code.encode("ascii"))
        tmp = self.peer_code_path.with_suffix(".tmp")
        tmp.write_bytes(protected)
        tmp.replace(self.peer_code_path)
        return self.cloudPeerStatus()

    def cloudPeerGenerate(self):
        """Generate/reveal a new code only on explicit user action."""
        code = secrets.token_urlsafe(32)
        self.cloudPeerConfigure(code)
        return {"code": code, "status": self.cloudPeerStatus()}

    def cloudPeerForget(self):
        self.peer_code_path.unlink(missing_ok=True)
        return self.cloudPeerStatus()

    def _peer_journal(self):
        if self.connection.get("mode") != "client" or not self.peer_code_path.exists():
            return None
        folder = self.offline.folder_status()
        if not folder.get("available") or not self.offline.cache.exists():
            return None
        user = self.remote_user or self.offline.cached_user()
        if not user or user.get("role") not in ("editor", "admin"):
            return None
        baseline = json.loads(self.offline.cache.read_text("utf8"))
        if baseline.get("username") != user.get("username"):
            raise PermissionError("داده LAN با هویت جفت‌شده سازگار نیست.")
        scope = user.get("projects")
        if scope is None:
            scope = [p["id"] for p in baseline["state"]["projects"]]
        if not scope:
            return None
        code = protect_windows(self.peer_code_path.read_bytes(), decrypt=True).decode("ascii")
        host = hashlib.sha256(self.connection["url"].encode("utf8")).hexdigest()[:24]
        return PeerJournal(folder["folder"], host, user["username"],
                           str(baseline["revision"]), code, scope, self.offline.device_id())

    def _cloud_peer_view(self):
        """Merge authenticated same-user peer edits into the durable LAN pending queue."""
        journal = self._peer_journal()
        if journal is None:
            return self.offline.get_cached()
        baseline = json.loads(self.offline.cache.read_text("utf8"))
        head, conflicts, _ = journal.replay(baseline["state"])
        if conflicts:
            ids = ", ".join(x["eventId"] for x in conflicts[:5])
            raise CloudConflict("CONFLICT: تغییرات هم‌زمان در پوشه Drive: " + ids)
        current = self.offline.get_cached()
        if self.offline.has_pending():
            head = three_way_merge(baseline["state"], current, head)
        head = normalize_state(head)
        is_valid(head)
        if head != current:
            self.offline.queue(head, baseline["username"])
        return head

    def _publish_peer_change(self, before, edited):
        journal = self._peer_journal()
        if journal is None or before is None:
            return None
        anchor = json.loads(self.offline.cache.read_text("utf8"))["state"]
        return journal.append(before, edited, anchor=anchor)

    def _load_collab(self):
        if self._unified_store is not None:
            return self._unified_store.load().bundle["collab"]
        if self.collab_path.exists():
            data = json.loads(self.collab_path.read_text(encoding="utf8"))
            collab.validate_state(data)
            return data
        return collab.empty_state()

    def _load_finance(self):
        if self._unified_store is not None:
            return self._unified_store.load().bundle["finance"]
        if self.finance_path.exists():
            value = json.loads(self.finance_path.read_text(encoding="utf8"))
            finance.validate_finance_state(value)
            return value
        return finance.empty_finance_state()

    def financeStatus(self):
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/finance-status")
        if self.lan:
            return self.lan.finance_status(self.lan.authenticate_owner_token())
        return {"pending": len(self._pending_finance_events()), "warning": self._finance_warning}

    def _pending_finance_events(self):
        if self._unified_store is not None:
            return self._unified_store.load().bundle["completion_outbox"]
        if not self.finance_outbox_path.exists():
            return []
        pending = json.loads(self.finance_outbox_path.read_text(encoding="utf8"))
        if not isinstance(pending, list) or len(pending) > 10000:
            raise ValueError("صف رویداد مالی معتبر نیست.")
        return pending

    def _pending_automation_events(self):
        if not self.automation_outbox_path.exists():
            return []
        saved = json.loads(self.automation_outbox_path.read_text("utf8"))
        if not isinstance(saved, list) or len(saved) > 10000:
            raise ValueError("Automation queue too large or malformed")
        return saved

    def _drain_automation_outbox(self, accounts=None):
        """Deliver saved card lifecycle events through allowlisted rule reducer."""
        from offline_exchange import atomic_json
        pending = self._pending_automation_events()
        if not pending:
            return
        state = self._load()
        accounts = accounts if accounts is not None else (
            self.lan.users if self.lan else self._solo_collab_context()[0])
        stored = self._load_collab()
        leftover = []
        for index, item in enumerate(pending):
            if not isinstance(item, dict) or set(item) != {"actor", "command"}:
                raise ValueError("Invalid saved automation event")
            try:
                out = collab.apply_command(
                    stored, item["command"], actor=item["actor"], accounts=accounts,
                    cards=state["tasks"], projects=state["projects"],
                    now=datetime.now(timezone.utc).isoformat())
            except (ValueError, PermissionError, RuntimeError):
                leftover.append(item)
                continue
            if out["changed"]:
                self._commit_domain("collab", out["state"])
            stored = out["state"]
            atomic_json(self.automation_outbox_path, leftover + pending[index + 1:])
        atomic_json(self.automation_outbox_path, leftover)

    def _drain_finance_outbox(self, accounts=None):
        """Replay completion receipts after interruption; never lose an event."""
        from offline_exchange import atomic_json
        pending = self._pending_finance_events()
        if not pending:
            self._finance_warning = ""
            return
        state = self._load()
        cards = {card["id"]: card for card in state["tasks"]}
        if accounts is None:
            accounts = self.lan.users if self.lan else self._solo_collab_context()[0]
        stored = self._load_finance()
        remaining = []
        for index, item in enumerate(pending):
            if not isinstance(item, dict) or set(item) != {"eventId", "completionId", "cardId",
                                                            "projectId", "actor", "at"}:
                raise ValueError("ساختار رویداد مالی ثبت‌شده معتبر نیست.")
            card = cards.get(item["cardId"])
            if not card or card["projectId"] != item["projectId"] or card.get("status") != "done":
                remaining.append(item)
                continue
            try:
                output = finance.apply_finance_command(
                    stored, {"type": "completion.record", "eventId": item["eventId"],
                             "cardId": item["cardId"], "completionId": item["completionId"]},
                    actor=item["actor"], accounts=accounts,
                    cards=state["tasks"], projects=state["projects"], now=item["at"])
            except (ValueError, PermissionError, RuntimeError) as error:
                self._finance_warning = str(error)
                remaining.append(item)
                continue
            remaining_now = remaining + pending[index + 1:]
            if self._unified_store is not None:
                self._commit_domains({"finance": output["state"],
                                      "completion_outbox": remaining_now})
            else:
                if output["changed"]:
                    atomic_json(self.finance_path, output["state"])
                atomic_json(self.finance_outbox_path, remaining_now)
            stored = output["state"]
        if self._unified_store is None:
            atomic_json(self.finance_outbox_path, remaining)
        elif not pending or remaining:
            self._commit_domains({"completion_outbox": remaining})
        if not remaining:
            self._finance_warning = ""

    def _save_local_state(self, state, *, actor=None, accounts=None,
                          expected_local_revision=None):
        with _state_write_guard(self.path):
            if expected_local_revision is not None:
                if (not isinstance(expected_local_revision, str)
                        or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_local_revision)):
                    raise ValueError("CONFLICT: شناسه نسخه محلی معتبر نیست.")
                current = self._load()
                if revision(current) != expected_local_revision:
                    raise RuntimeError("CONFLICT: اطلاعات محلی توسط نمونه دیگری تغییر کرده است؛ پیش از ذخیره تازه‌سازی کنید.")
            return self._save_local_state_locked(state, actor=actor, accounts=accounts)

    def _save_local_state_locked(self, state, *, actor=None, accounts=None):
        """Trusted host-side data update, with a crash-recoverable completion outbox."""
        from offline_exchange import atomic_json
        state = normalize_state(state)
        is_valid(state)
        prior = self._load()
        from project_integrity import ensure_project_identity_preserved
        previous_project_ids = {p["id"] for p in prior["projects"]}
        next_project_ids = {p["id"] for p in state["projects"]}
        ensure_project_identity_preserved(
            prior, state,
            accounts=accounts if accounts is not None else
            (self.lan.users if self.lan else None),
            collaboration=(self._load_collab() if
                           previous_project_ids - next_project_ids else None))
        # A board edit must not silently sever task/invoice/GL source links.
        # Perform the cross-domain check before any outbox or backup write.
        from finance_reference_guard import ensure_finance_references_preserved
        ensure_finance_references_preserved(prior, state, self._load_finance())
        # All bounded event computations must finish before the legacy JSON
        # completion outbox is written. A 3001-event batch must fail atomically.
        events = card_change_events(prior, state)
        before = {t["id"]: t for t in prior["tasks"]}
        completions = [t for t in state["tasks"] if t["id"] in before
                       and before[t["id"]].get("status") != "done"
                       and t.get("status") == "done"
                       and before[t["id"]].get("projectId") == t.get("projectId")]
        acting = actor or (next((u for u in self.lan.users.values() if u["role"] == "admin"),
                                {"username": "local"})["username"] if self.lan else "local")
        if completions:
            pending = self._pending_finance_events()
            for card in completions:
                nonce = secrets.token_hex(16)
                pending.append({"eventId": "completed-" + nonce,
                                "completionId": "completion-" + nonce,
                                "cardId": card["id"], "projectId": card["projectId"],
                                "actor": acting, "at": datetime.now(timezone.utc).isoformat()})
            if self._unified_store is None:
                atomic_json(self.finance_outbox_path, pending)
        if events and self._unified_store is None:
            queued = self._pending_automation_events()
            queued.extend({"actor": acting, "command": event} for event in events)
            atomic_json(self.automation_outbox_path, queued)
        if self._unified_store is not None:
            current = self._unified_store.load()
            # Save task changes and the completion queue together: a process
            # interruption can no longer record a done card without its event.
            updated = {**current.bundle, "tasks": state}
            if completions:
                updated["completion_outbox"] = pending
            if events and "automation" in current.bundle:
                # Queue + task change + authorization-dependent delivery +
                # collaboration receipts all commit under ONE SQLite CAS.
                # M07 fail-closed preflight runs against this exact candidate.
                event_accounts = accounts if accounts is not None else (
                    self.lan.users if self.lan else self._solo_collab_context()[0])
                stamp = datetime.now(timezone.utc).isoformat()
                from m07_host_guard import safe_card_events
                guarded = safe_card_events(
                    updated, events, actor=acting, accounts=event_accounts,
                    cards=state["tasks"], projects=state["projects"], now=stamp)
                updated = guarded["bundle"]
            elif events:
                # Keep card changes and their automation receipts in the same
                # durable revision. Legacy pending JSON events are replayed
                # separately, only when migrating an older installation.
                saved_collab = current.bundle["collab"]
                event_accounts = accounts if accounts is not None else (
                    self.lan.users if self.lan else self._solo_collab_context()[0])
                for event in events:
                    result = collab.apply_command(
                        saved_collab, event, actor=acting, accounts=event_accounts,
                        cards=state["tasks"], projects=state["projects"],
                        now=datetime.now(timezone.utc).isoformat())
                    saved_collab = result["state"]
                updated["collab"] = saved_collab
            # No snapshot/backup side effect before the optional M07 preflight
            # has accepted the entire candidate revision.
            self._automatic_backup_before_change()
            self._unified_store.commit(updated, expected_revision=current.revision)
        else:
            self._automatic_backup_before_change()
            atomic_save(self.path, state)
        self.state = state
        try:
            self._drain_finance_outbox(accounts=accounts)
            self._drain_automation_outbox(accounts=accounts)
        except (ValueError, PermissionError, RuntimeError, OSError) as error:
            self._finance_warning = str(error)
        self.offline.publish(current=state, username="host")
        return True

    def financeRead(self, project_id=""):
        """Expose only financial records authorized for the current LAN identity."""
        if self.connection.get("mode") == "client":
            from urllib.parse import quote
            return self._remote_request("/api/finance?projectId=" + quote(project_id))["invoices"]
        if self.lan:
            return self.lan.finance_read(self.lan.authenticate_owner_token(), project_id)
        with self._lock:
            state = self.getState()
            return finance.list_invoices(self._load_finance(), actor="local",
                                         accounts=self._solo_collab_context()[0],
                                         cards=state["tasks"], projects=state["projects"],
                                         project_id=project_id or None)

    def financeOverview(self, projectId="", startDate="", endDate=""):
        """Restricted totals; never included in the general task/board state."""
        if self.connection.get("mode") == "client":
            params = urlencode({"projectId": projectId, "startDate": startDate,
                                "endDate": endDate})
            return self._remote_request("/api/finance-overview?" + params)
        if self.lan:
            return self.lan.finance_overview(self.lan.authenticate_owner_token(),
                                             projectId, startDate, endDate)
        with self._lock:
            state = self.getState()
            return finance.financial_overview(self._load_finance(), actor="local",
                                              accounts=self._solo_collab_context()[0],
                                              cards=state["tasks"], projects=state["projects"],
                                              project_id=projectId, start_date=startDate,
                                              end_date=endDate)

    def financeCommand(self, command):
        if not isinstance(command, dict) or command.get("type") == "completion.record":
            raise ValueError("ثبت تکمیل فقط از تغییر واقعی وضعیت کارت پذیرفته می‌شود.")
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/finance", command)["result"]
        if self.lan:
            return self.lan.finance_command(self.lan.authenticate_owner_token(), command)
        from offline_exchange import atomic_json
        with self._lock:
            state = self.getState()
            before = self._load_finance()
            now = datetime.now(timezone.utc).isoformat()
            if "rialJournalV2" in before and command["type"] == "invoice.issue":
                from ir_invoice_joint_issue import issue_legacy_sales_with_rial
                output = issue_legacy_sales_with_rial(
                    before, command, actor="local",
                    accounts=self._solo_collab_context()[0],
                    cards=state["tasks"], projects=state["projects"], now=now)
            else:
                output = finance.apply_finance_command(
                    before, command, actor="local",
                    accounts=self._solo_collab_context()[0],
                    cards=state["tasks"], projects=state["projects"], now=now)
            if output["changed"]:
                if "rialJournalV2" in before:
                    from money_policy import snapshot_sha256
                    self._commit_domain(
                        "finance", output["state"],
                        expected_finance_sha256=snapshot_sha256(before))
                else:
                    self._commit_domain("finance", output["state"])
            return output["result"]

    def accountingRead(self, projectId=""):
        """Admin-only payable/receivable balances from authoritative GL."""
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/accounting?" + urlencode({"projectId": projectId}))
        if self.lan:
            return self.lan.accounting_read(self.lan.authenticate_owner_token(), projectId)
        from accounting_service import read_madar_accounting
        with self._lock:
            state = self.getState()
            return read_madar_accounting(
                self._load_finance(), actor="local",
                accounts=self._solo_collab_context()[0], project_id=projectId,
                cards=state["tasks"], projects=state["projects"])

    def accountingCommand(self, command):
        """Apply named-party double-entry workflow under existing finance CAS."""
        if not isinstance(command, dict):
            raise ValueError("Invalid accounting command")
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/accounting", command)["result"]
        if self.lan:
            return self.lan.accounting_command(self.lan.authenticate_owner_token(), command)
        from accounting_service import apply_madar_accounting
        with self._lock:
            state = self.getState()
            before = self._load_finance()
            now = datetime.now(timezone.utc).isoformat()
            context = {"actor": "local", "accounts": self._solo_collab_context()[0],
                       "cards": state["tasks"], "projects": state["projects"], "now": now}
            if "rialJournalV2" in before and command.get("type") in (
                    "intake.create", "intake.price", "intake.cancel",
                    "intake.convert"):
                if self._unified_store is None:
                    raise ValueError("Authenticated supplier intake requires unified SQLite")
                from money_policy import snapshot_sha256
                current = self._unified_store.load()
                if current is None:
                    raise RuntimeError("CONFLICT: unified finance snapshot missing")
                committed = self._unified_store.commit_authenticated_intake(
                    command, actor=context["actor"], accounts=context["accounts"],
                    now=now, expected_revision=current.revision,
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

    def _standalone_accounting_store(self):
        """Explicit-use only. Never mount this DB into tasks/finance/legacy/RIAL V2."""
        from standalone_accounting import StandaloneAccountingStore
        # Bridge.path is resolved by datadir() at initialization, so this is
        # always the same application's data root, not cwd or an imported DB.
        return StandaloneAccountingStore(self.path.parent / "standalone-accounting.sqlite3",
                                         default_currency="RIAL")

    def _standalone_accounting_read_local(self, *, actor, accounts):
        from lan import standalone_finance_access, standalone_finance_accounts
        from standalone_financial_report_host import attach_verified_reports
        standalone_finance_access(actor, accounts, mutation=False)
        result = attach_verified_reports(self._standalone_accounting_store().read(
            actor=actor, accounts=standalone_finance_accounts(accounts)))
        # Capabilities are trusted host-side statements, not user-supplied JS.
        # Structure/closing/equity operations remain administrator-only.
        principal = accounts[actor]
        editor = principal["role"] == "editor" and principal.get("financeEdit") is True
        result["capabilities"] = {
            "canView": True,
            "canManage": principal["role"] == "admin" or editor,
            "canDraft": principal["role"] == "admin" or editor,
            "canAdmin": principal["role"] == "admin",
        }
        return result

    def _standalone_accounting_command_local(self, request, *, actor, accounts):
        if getattr(self, "_exit_financial_locked", False):
            raise RuntimeError("Financial writes are locked after the mandatory exit backup")
        from lan import (
            standalone_finance_access, standalone_finance_accounts,
            standalone_command_request,
        )
        command, expected_revision = standalone_command_request(request)
        standalone_finance_access(actor, accounts, mutation=True)
        from standalone_financial_report_host import attach_verified_reports
        return attach_verified_reports(self._standalone_accounting_store().command(
            command, actor=actor, accounts=standalone_finance_accounts(accounts),
            expected_revision=expected_revision,
            now=datetime.now(timezone.utc).isoformat()))

    def standaloneAccountingRead(self):
        """Standalone-only read: no task/card/project lookup or cached LAN fallback."""
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/standalone-accounting")
        if self.lan:
            return self.lan.standalone_accounting_read(
                self.lan.authenticate_owner_token())
        with self._lock:
            local = {"local": {"username": "local", "role": "admin",
                               "financeView": True, "financeEdit": True}}
            return self._standalone_accounting_read_local(
                actor="local", accounts=local)

    def _require_personal_parsian_access(self):
        # Never expose another book to LAN clients or collaborative sessions.
        if self.connection.get("mode") == "client" or self.lan is not None:
            raise PermissionError("Private Parsian history is only available in local solo mode")
        # Bind the personal source archive to THIS exact ledger, not merely
        # the current Windows login. Empty/new/different company ledgers fail.
        book_path = datadir() / "standalone-accounting.sqlite3"
        if not book_path.is_file() or book_path.is_symlink():
            raise PermissionError("The original personal Parsian ledger is not selected")
        with closing(sqlite3.connect(book_path.as_uri() + "?mode=ro", uri=True)) as connection:
            source = connection.execute(
                "SELECT revision,state,digest FROM standalone_accounting WHERE id=1").fetchone()
        if not source or source[0] < 608 or hashlib.sha256(source[1]).hexdigest() != source[2]:
            raise PermissionError("Private Parsian ledger checksum or revision invalid")
        state = json.loads(source[1])
        event_ids = {row.get("eventId") for row in state.get("events", [])}
        if not {"ps.parsian.journal.1405.14050201.1",
                "ps.parsian.reconcile.1404.pnl-close.20261107"} <= event_ids:
            raise PermissionError("Private historical invoices belong to another accounting ledger")

    def standaloneAccountingParsianHistory(self):
        self._require_personal_parsian_access()
        with self._lock:
            from personal_parsian_bridge import read_verified_history
            return read_verified_history()

    def standaloneAccountingParsianExtended(self):
        self._require_personal_parsian_access()
        with self._lock:
            from personal_parsian_bridge import read_personal_extended
            return read_personal_extended()

    def standaloneAccountingParsianCompany(self):
        self._require_personal_parsian_access()
        with self._lock:
            from personal_parsian_bridge import read_personal_company
            return read_personal_company()

    def standaloneAccountingParsianArchiveIndex(self):
        self._require_personal_parsian_access()
        with self._lock:
            from personal_parsian_bridge import list_archives
            return list_archives()

    def standaloneAccountingParsianArchiveRows(self, year, table, offset=0):
        self._require_personal_parsian_access()
        with self._lock:
            from personal_parsian_bridge import read_archive_rows
            return read_archive_rows(year,table,offset)

    def standaloneAccountingCsvChooseFile(self, group, encoding, delimiter):
        """Native-selected local CSV headers only, without any finance write."""
        from provider_csv_bridge import GROUPS
        if type(group) is not str or group not in GROUPS:
            raise ValueError("Unknown CSV group")
        if self.connection.get("mode") == "client" and (
                (self.remote_user or {}).get("role") != "admin"):
            raise PermissionError("CSV review is restricted to the accounting administrator")
        if not webview.windows:
            raise RuntimeError("Native file chooser is unavailable")
        chosen = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=("CSV files (*.csv)",))
        with self._lock:
            return self._csv_preview.select(group, encoding, delimiter, chosen)

    def standaloneAccountingCsvPreview(self, request):
        """Only analyze three explicitly selected local CSVs; no ledger writes."""
        if self.connection.get("mode") == "client" and (
                (self.remote_user or {}).get("role") != "admin"):
            raise PermissionError("CSV review is restricted to the accounting administrator")
        with self._lock:
            return self._csv_preview.preview(request)

    def standaloneAccountingCommand(self, request):
        """One strict CAS command; the remote/client path never opens local DB."""
        from lan import standalone_command_request
        standalone_command_request(request)
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/standalone-accounting", request)
        if self.lan:
            return self.lan.standalone_accounting_command(
                self.lan.authenticate_owner_token(), request)
        with self._lock:
            local = {"local": {"username": "local", "role": "admin",
                               "financeView": True, "financeEdit": True}}
            return self._standalone_accounting_command_local(
                request, actor="local", accounts=local)

    def standaloneAccountingPrepare(self, request):
        """Task bridge: UI passes IDs only; host resolves its SAVED task state."""
        if type(request) is not dict or set(request) != {"taskId", "expenseId"}:
            raise ValueError("Expected taskId and expenseId only")
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/standalone-accounting/prepare", request)
        if self.lan:
            return self.lan.standalone_accounting_prepare(
                self.lan.authenticate_owner_token(), request)
        with self._lock:
            from standalone_task_prepare import prepare_from_saved_task
            if getattr(self, "_exit_financial_locked", False):
                raise RuntimeError("Financial writes are locked after the mandatory exit backup")
            local = {"local": {"username": "local", "role": "admin",
                               "financeView": True, "financeEdit": True}}
            return prepare_from_saved_task(
                self._standalone_accounting_store(), request,
                tasks=self.getState()["tasks"], actor="local", accounts=local)

    def standaloneAccountingQuote(self, request):
        """Exact quote against the currency of the independent accounting head."""
        from standalone_accounting_quote import quote_standalone_sale
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/standalone-accounting/quote", request)
        if self.lan:
            return self.lan.standalone_accounting_quote(
                self.lan.authenticate_owner_token(), request)
        with self._lock:
            accounts = {"local": {"username": "local", "role": "admin"}}
            currency = self._standalone_accounting_store().read(
                actor="local", accounts=accounts)["view"]["currency"]
            return quote_standalone_sale(request, ledger_currency=currency)

    def rialJournalRead(self, request):
        """Read only an already-initialized RIAL V2 journal, never legacy TOMAN."""
        if (type(request) is not dict or
                set(request) != {"companyId", "fiscalPeriodId"}):
            raise ValueError("V2 read requires companyId and fiscalPeriodId")
        import re
        for field in ("companyId", "fiscalPeriodId"):
            value = request[field]
            if type(value) is not str or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", value):
                raise ValueError("Invalid RIAL V2 scope: " + field)
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/rial-journal?" + urlencode(request))
        if self.lan:
            return self.lan.rial_journal_read(
                self.lan.authenticate_owner_token(), request)
        with self._lock:
            return self._rial_journal_read_local(request)

    def rialJournalActivate(self, command):
        """Admin-only opt-in empty RIAL ledger in the SAME unified finance CAS."""
        if (type(command) is not dict or
                set(command) != {"companyId", "fiscalPeriodId", "startDate", "endDate"}):
            raise ValueError("RIAL V2 activation requires explicit company and fiscal calendar")
        import re
        for field in ("companyId", "fiscalPeriodId"):
            value = command[field]
            if type(value) is not str or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", value):
                raise ValueError("Invalid RIAL activation identifier")
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/rial-journal/activate", command)["result"]
        if self.lan:
            return self.lan.rial_journal_activate(
                self.lan.authenticate_owner_token(), command)
        with self._lock:
            return self._rial_journal_activate_local(command, actor="local")

    def _rial_journal_activate_local(self, command, *, actor):
        """Never migrates old TOMAN amounts or opens a second SQLite transaction."""
        from ir_journal_v2 import FiscalPeriod, new_journal_state
        from ir_finance_v2_extension import HostCompanyProof, activate_rial_finance
        from money_policy import snapshot_sha256
        if self._unified_store is None:
            raise ValueError("RIAL activation requires opt-in unified SQLite storage")
        financial = self._load_finance()
        if "rialJournalV2" in financial:
            raise ValueError("Additional RIAL company needs verified project/company mapping")
        # A zero-history transition is safe. A live TOMAN journal must first be
        # reconciled by a separately audited migration, not silently ignored.
        if (financial["invoices"] or financial["ledger"] or
                financial["contracts"] or financial["cardCosts"] or
                financial["receipts"] or financial["completionIds"] or
                financial.get("accounting") or financial.get("purchaseIntakes")):
            raise ValueError("Legacy TOMAN activity exists; audited migration is required")
        period = FiscalPeriod(command["companyId"], command["fiscalPeriodId"],
                              command["startDate"], command["endDate"])
        empty = new_journal_state(command["companyId"], (period,))
        proof = HostCompanyProof(command["companyId"], actor,
                                 snapshot_sha256(financial))
        candidate = activate_rial_finance(financial, empty, proof=proof)
        self._commit_domain("finance", candidate)
        return {"companyId": command["companyId"], "currency": "RIAL",
                "fiscalPeriodId": period.fiscal_period_id, "revision": empty.revision,
                "status": "activated-empty-only", "migrationPerformed": False}

    def _rial_journal_read_local(self, request):
        """Only server/solo admin calls this; prefer the same-CAS finance domain."""
        from ir_journal_sqlite import RIALJournalStorage
        from ir_journal_v2 import PostedJournal
        legacy_finance = self._load_finance()
        if "rialJournalV2" in legacy_finance:
            from ir_finance_v2_extension import load_finance_rial_journal
            try:
                state = load_finance_rial_journal(
                    legacy_finance, request["companyId"])
            except KeyError as exc:
                raise ValueError("Company is not activated in the unified RIAL finance domain") from exc
        else:
            # Backward-compatible opt-in isolated V2 only. No TOMAN coercion.
            path = datadir() / "madar-rial-v2.sqlite3"
            if not path.is_file():
                raise ValueError(
                    "RIAL V2 has not been initialized; old TOMAN data was not imported")
            store = RIALJournalStorage(path)
            state = store.read(request["companyId"])
        if state is None:
            raise ValueError("Company has no verified RIAL V2 journal")
        period = request["fiscalPeriodId"]
        if period not in {p.fiscal_period_id for p in state.periods}:
            raise ValueError("Fiscal period does not exist in this RIAL journal")
        matching = [
            event for event in state.events
            if type(event) is PostedJournal and event.fiscal_period_id == period
        ]
        if len(matching) > 500:
            raise ValueError("RIAL V2 UI read exceeds 500 events; pagination required")
        return {
            "schema": "IR-JOURNAL-V2.1",
            "companyId": request["companyId"],
            "fiscalPeriodId": period,
            "currency": "RIAL",
            "revision": state.revision,
            "journals": [
                {"eventId": event.event_id, "companyId": event.company_id,
                 "fiscalPeriodId": event.fiscal_period_id,
                 "postingDate": event.posting_date,
                 "source": {"kind": event.source.kind,
                            "sourceId": event.source.source_id},
                 "reversalOf": event.reversal_of,
                 "lines": [
                     {"accountCode": line.reference.account_code,
                      "debitRial": str(line.debit_rial),
                      "creditRial": str(line.credit_rial),
                      "costCenterCode": line.reference.cost_center_code}
                     for line in event.lines]}
                for event in matching
            ],
        }

    def _solo_collab_context(self):
        if self.lan:
            return self.lan.users, self.lan.authenticate_owner_token(), True
        return {"local": {"username": "local", "role": "admin", "projects": None}}, None, False

    def collabRead(self, kind, card_id=""):
        if kind not in ("comments", "notifications", "activity", "rules"):
            raise ValueError("نوع اطلاعات همکاری معتبر نیست.")
        if self.connection.get("mode") == "client":
            from urllib.parse import quote
            suffix = "?cardId=" + quote(card_id) if kind == "comments" else (
                     "?projectId=" + quote(card_id) if kind == "rules" else "")
            return self._remote_request("/api/" + kind + suffix)["items"]
        if self.lan:
            return self.lan.collab_read(self.lan.authenticate_owner_token(), kind, card_id)
        with self._lock:
            snapshot = self.getState()
            kwargs = {"actor": "local", "accounts": self._solo_collab_context()[0],
                      "cards": snapshot["tasks"], "projects": snapshot["projects"]}
            saved = self._load_collab()
            if kind == "comments":
                return collab.list_comments(saved, card_id, **kwargs)
            if kind == "notifications":
                return collab.list_notifications(saved, **kwargs)
            if kind == "rules":
                return collab.list_rules(saved, project_id=card_id or None, **kwargs)
            return collab.list_activity(saved, **kwargs)

    def collabCommand(self, command):
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/collab", command)["result"]
        if self.lan:
            return self.lan.collab_command(self.lan.authenticate_owner_token(), command)
        from offline_exchange import atomic_json
        with self._lock:
            state = self.getState()
            result = collab.apply_command(self._load_collab(), command, actor="local",
                                          accounts=self._solo_collab_context()[0],
                                          cards=state["tasks"], projects=state["projects"],
                                          now=datetime.now(timezone.utc).isoformat())
            if result["changed"]:
                self._commit_domain("collab", result["state"])
            return result["result"]

    def _automation_buttons_read_local(self, request, *, actor, accounts):
        if not isinstance(request, dict) or set(request) - {"projectId", "boardId"}:
            raise ValueError("Invalid button listing request")
        with self._lock:
            return automation_buttons.list_buttons(
                automation_buttons.load(self.automation_buttons_path),
                actor=actor, accounts=accounts, app_state=self.getState(),
                project_id=request.get("projectId", ""),
                board_id=request.get("boardId", ""))

    def _automation_buttons_mutate_local(self, command, *, actor, accounts):
        with self._lock, _state_write_guard(self.automation_buttons_path):
            output = automation_buttons.mutate(
                automation_buttons.load(self.automation_buttons_path), command,
                actor=actor, accounts=accounts, app_state=self.getState(),
                now=datetime.now(timezone.utc).isoformat())
            if output["changed"]:
                automation_buttons.persist(self.automation_buttons_path, output["state"])
            return output["result"]

    def _automation_button_execute_local(self, command, *, actor, accounts):
        # The execution receipt, comments and notices commit in ONE existing
        # collaboration domain transaction. Replays cannot double-create them.
        with self._lock, _state_write_guard(self.automation_buttons_path):
            output = automation_buttons.execute(
                automation_buttons.load(self.automation_buttons_path),
                self._load_collab(), command,
                actor=actor, accounts=accounts, app_state=self.getState(),
                now=datetime.now(timezone.utc).isoformat())
            if output["changed"]:
                self._commit_domain("collab", output["state"])
            return output["result"]

    def automationButtonsList(self, request):
        if self.connection.get("mode") == "client":
            if not isinstance(request, dict) or set(request) - {"projectId", "boardId"}:
                raise ValueError("Invalid button listing request")
            return self._remote_request("/api/buttons?" + urlencode(request))["items"]
        if self.lan:
            return self.lan.automation_buttons_list(self.lan.authenticate_owner_token(), request)
        return self._automation_buttons_read_local(
            request, actor="local", accounts=self._solo_collab_context()[0])

    def automationButtonsSave(self, definition):
        command = {"type": "button.upsert", "eventId": "button-" + secrets.token_hex(16),
                   "button": definition}
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/buttons", command)["result"]
        if self.lan:
            return self.lan.automation_buttons_command(self.lan.authenticate_owner_token(), command)
        return self._automation_buttons_mutate_local(
            command, actor="local", accounts=self._solo_collab_context()[0])

    def automationButtonsDelete(self, button_id):
        command = {"type": "button.delete", "eventId": "button-" + secrets.token_hex(16),
                   "buttonId": button_id}
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/buttons", command)["result"]
        if self.lan:
            return self.lan.automation_buttons_command(self.lan.authenticate_owner_token(), command)
        return self._automation_buttons_mutate_local(
            command, actor="local", accounts=self._solo_collab_context()[0])

    def automationButtonRun(self, request):
        if not isinstance(request, dict) or set(request) - {"buttonId", "cardId", "eventId"}:
            raise ValueError("Invalid button execution request")
        command = {"type": "button.execute", "eventId": request.get("eventId") or
                   "button-" + secrets.token_hex(16),
                   "buttonId": request.get("buttonId")}
        if request.get("cardId"):
            command["cardId"] = request["cardId"]
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/buttons", command)["result"]
        if self.lan:
            return self.lan.automation_buttons_command(self.lan.authenticate_owner_token(), command)
        return self._automation_button_execute_local(
            command, actor="local", accounts=self._solo_collab_context()[0])

    def _attachment_store(self):
        if self.connection.get("mode") == "client":
            raise PermissionError("Attachments belong to the authorized LAN host")
        if not hasattr(self, "_attachments"):
            self._attachments = AttachmentStore(datadir() / "attachment-storage")
        return self._attachments

    def _attachment_action(self, kind, *, card_id="", attachment_id="", payload=None):
        from urllib.parse import quote
        if self.connection.get("mode") == "client":
            if kind in ("upload", "delete"):
                return self._remote_request("/api/attachments", {"kind": kind, **payload})["result"]
            return self._remote_request("/api/attachments?kind=" + quote(kind) +
                                        "&cardId=" + quote(card_id) +
                                        "&attachmentId=" + quote(attachment_id))["result"]
        if self.lan:
            return self.lan.attachment_action(self.lan.authenticate_owner_token(),
                                              kind, card_id=card_id,
                                              attachment_id=attachment_id, payload=payload)
        with self._lock:
            state = self.getState()
            context = {"actor": "local", "accounts": self._solo_collab_context()[0],
                       "cards": state["tasks"], "projects": state["projects"]}
            store = self._attachment_store()
            if kind == "list":
                return store.list_card(card_id=card_id, **context)
            if kind == "preview":
                return store.preview(attachment_id=attachment_id, **context)
            if kind == "read":
                return store.read(attachment_id=attachment_id, **context)
            if kind == "upload":
                return store.upload(card_id=payload["cardId"], filename=payload["filename"],
                                    content_base64=payload["contentBase64"],
                                    request_id=payload["requestId"],
                                    now=datetime.now(timezone.utc).isoformat(), **context)
            if kind == "delete":
                return store.delete(attachment_id=payload["attachmentId"],
                                    request_id=payload["requestId"],
                                    now=datetime.now(timezone.utc).isoformat(), **context)
            raise ValueError("Unknown attachment action")

    def attachmentList(self, card_id):
        return self._attachment_action("list", card_id=card_id)

    def attachmentPreview(self, attachment_id):
        return self._attachment_action("preview", attachment_id=attachment_id)

    def attachmentRead(self, attachment_id):
        return self._attachment_action("read", attachment_id=attachment_id)

    def attachmentSave(self, attachment_id):
        """Native Save-As, avoiding WebView2's synthetic-anchor download path."""
        import binascii
        result = self.attachmentRead(attachment_id)
        meta = result.get("attachment")
        encoded = result.get("contentBase64")
        if (not isinstance(meta, dict) or not isinstance(encoded, str) or
                not re.fullmatch(r"[0-9a-f]{64}", str(meta.get("sha256", ""))) or
                len(encoded) > 4 * ((4 * 1024 * 1024 + 2) // 3)):
            raise ValueError("اطلاعات فایل دریافتی معتبر نیست.")
        from attachments import _filename
        filename, _ = _filename(meta.get("filename"))
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("محتوای پیوست مخدوش است.") from exc
        if (not raw or len(raw) > 4 * 1024 * 1024 or
                len(raw) != meta.get("size") or
                hashlib.sha256(raw).hexdigest() != meta["sha256"]):
            raise ValueError("صحت فایل دریافتی تأیید نشد.")
        chosen = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE, save_filename=filename)
        if not chosen:
            return {"canceled": True}
        target = Path(chosen if isinstance(chosen, str) else chosen[0])
        if not target.parent.is_dir():
            raise FileNotFoundError("پوشه مقصد برای ذخیره در دسترس نیست.")
        # Stage on the destination volume; a failed write cannot truncate an
        # existing file. The Save As dialog owns the overwrite confirmation.
        staged = target.with_name(".madar-attachment-" + secrets.token_hex(16) + ".partial")
        try:
            with staged.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
        return {"saved": True, "filename": target.name, "size": len(raw)}

    def attachmentUpload(self, card_id, filename, content_base64, request_id):
        return self._attachment_action("upload", payload={"cardId": card_id,
            "filename": filename, "contentBase64": content_base64, "requestId": request_id})

    def attachmentDelete(self, attachment_id, request_id):
        return self._attachment_action("delete", payload={"attachmentId": attachment_id,
                                                          "requestId": request_id})

    def attachmentBackup(self):
        """Explicit local attachment backup; never silently upload blob data to Drive."""
        if self.connection.get("mode") == "client":
            raise PermissionError("پشتیبان کامل پیوست‌ها فقط روی میزبان ساخته می‌شود.")
        with self._lock:
            if self.lan:
                actor = self.lan.account_for(self.lan.authenticate_owner_token())["username"]
                accounts = self.lan.users
            else:
                actor, accounts = "local", self._solo_collab_context()[0]
            self.backups_dir.mkdir(parents=True, exist_ok=True)
            destination = self.backups_dir / ("attachment-backup-" +
                          datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") +
                          "-" + secrets.token_hex(6))
            manifest = self._attachment_store().backup_to(destination, actor=actor, accounts=accounts)
            return {"path": str(destination), "blobs": len(manifest["blobs"])}

    def createUnifiedSqliteBackup(self):
        """Verified 4/5-domain SQLite snapshot, NOT a full archive of blobs/users."""
        if self.connection.get("mode") == "client":
            raise PermissionError("خروجی SQLite یکپارچه فقط روی میزبان مجاز است.")
        with self._lock:
            self.backups_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            label = "unified-export-" + stamp + "-" + secrets.token_hex(6)
            destination = self.backups_dir / (label + ".sqlite3")
            if self._unified_store is not None:
                self._unified_store.backup_database(destination)
                archive = UnifiedAppStorage(destination)
                if not archive.integrity_check():
                    raise RuntimeError("خروجی پایگاه داده معتبر نیست.")
                saved = archive.load()
                return {"path": str(destination), "sourceCopies": "",
                        "revision": saved.revision, "sha256": saved.sha256,
                        "note": "Active SQLite backup; attachment binaries are separate."}
            immutable_sources = self.backups_dir / (label + "-originals")
            store = UnifiedAppStorage(destination)
            def current(path):
                return path if path.is_file() else None
            exported = store.import_legacy(
                self.path, collab_json=current(self.collab_path),
                finance_json=current(self.finance_path),
                outbox_json=current(self.finance_outbox_path),
                backup_dir=immutable_sources)
            if not store.integrity_check():
                raise RuntimeError("اعتبارسنجی خروجی SQLite ناموفق بود.")
            return {"path": str(destination), "sourceCopies": str(immutable_sources),
                    "revision": exported.revision, "sha256": exported.sha256,
                    "note": "Export only; JSON is still authoritative. Attachments have separate backup."}

    def runDueScheduler(self):
        """Process due-soon rule events with persistent idempotency receipts."""
        if self.connection.get("mode") == "client":
            return self._remote_request("/api/scheduler", {"run": True})["result"]
        if self.lan:
            return self.lan.run_scheduler(self.lan.authenticate_owner_token())
        with self._lock:
            enhanced = self._run_engine_scheduler("local", self._solo_collab_context()[0])
            if enhanced is not None:
                return enhanced
            current = self.getState()
            events = due_events(current["tasks"], today=datetime.now().date())
            snapshot = self._load_collab()
            changed = 0
            for event in events:
                result = collab.apply_command(
                    snapshot, event, actor="local",
                    accounts=self._solo_collab_context()[0], cards=current["tasks"],
                    projects=current["projects"], now=datetime.now(timezone.utc).isoformat())
                if result["changed"]:
                    self._commit_domain("collab", result["state"])
                    changed += 1
                snapshot = result["state"]
            return {"events": len(events), "new": changed}

    def _run_engine_scheduler(self, actor, accounts):
        """Caller holds host lock; LAN caller holds service lock first."""
        if self._unified_store is None:
            return None
        current = self._unified_store.load()
        if "automation" not in current.bundle:
            return None
        cards = current.bundle["tasks"]["tasks"]
        projects = current.bundle["tasks"]["projects"]
        stamp = datetime.now(timezone.utc).isoformat()
        from m07_host_guard import safe_due_tick
        guarded = safe_due_tick(
            current.bundle, actor=actor, accounts=accounts,
            cards=cards, projects=projects,
            today=datetime.now().date(), now=stamp)
        if guarded["added"] or guarded["processed"]:
            self._unified_store.commit(
                guarded["bundle"], expected_revision=current.revision)
        return {"events": guarded["added"], "new": guarded["applied"],
                "replayed": guarded["replayed"], "retried": guarded["retried"],
                "dead": guarded["dead"], "pending": guarded["pending"]}

    def startScheduledJobs(self):
        """Hourly recurring checks while the Windows host process is running."""
        if self.connection.get("mode") == "client":
            return
        if getattr(self, "_scheduler_thread", None) and self._scheduler_thread.is_alive():
            return
        self._scheduler_stop = threading.Event()
        self._scheduler_error = ""
        def run():
            while not self._scheduler_stop.is_set():
                try:
                    self.runDueScheduler()
                    self._scheduler_error = ""
                except Exception as error:
                    self._scheduler_error = str(error)
                self._scheduler_stop.wait(3600)
        self._scheduler_thread = threading.Thread(target=run, daemon=True)
        self._scheduler_thread.start()

    def stopScheduledJobs(self):
        if hasattr(self, "_scheduler_stop"):
            self._scheduler_stop.set()
        if getattr(self, "_scheduler_thread", None):
            self._scheduler_thread.join(timeout=2)
        self._stop_lan_discovery()

    def chooseDriveFolder(self):
        """User explicitly selects a Google Drive for desktop synced directory."""
        window = webview.windows[0]
        chosen = window.create_file_dialog(webview.FileDialog.FOLDER)
        if not chosen:
            return {"canceled": True}
        path = chosen if isinstance(chosen, str) else chosen[0]
        return self.offline.set_sync_folder(path)

    def driveFolderStatus(self):
        return self.offline.folder_status()

    def driveFolderList(self):
        return self.offline.list_snapshots()

    def driveFolderRestore(self, filename):
        if self.connection.get("mode") == "client":
            raise PermissionError("بازیابی نسخه پوشه در حالت کلاینت مجاز نیست؛ ابتدا میزبان را بازیابی کنید.")
        with self._lock:
            payload = self.offline.read_snapshot(filename)
            payload = normalize_state(payload)
            self._replace_local_state(payload)
            return self.state

    def driveFolderBackup(self):
        folder = self.offline.folder_status()
        if not folder.get("configured"):
            raise RuntimeError("ابتدا پوشه پشتیبان در Google Drive for desktop را انتخاب کنید.")
        if not folder.get("available"):
            raise RuntimeError("پوشه پشتیبان در دسترس نیست؛ اتصال یا مسیر پوشه را بررسی کنید.")
        if self.connection.get("mode") == "client" and self.offline.has_pending():
            return self.offline.publish(json.loads(self.offline.pending.read_text(encoding="utf8")), force=True)
        state = self.getState()
        return self.offline.publish(current=state,
                                    username=(self.remote_user or {}).get("username", "local"),force=True)

    def _sync_client_from_host(self):
        if self.peer_code_path.exists() and self.offline.cache.exists():
            # Preserve peer edits before acknowledging a fresh LAN revision.
            self._cloud_peer_view()
        latest = self._remote_request("/api/state")
        username = (self.remote_user or latest["user"])["username"]
        if self.offline.has_pending():
            is_admin = latest["user"].get("role") == "admin"
            merged = self.offline.reconcile(latest["state"], latest["revision"],
                                            username, allow_structure=is_admin)
            remote = self._remote_request("/api/state", {
                "state": merged, "revision": latest["revision"]})
            latest = remote
        self.remote_revision = latest["revision"]
        self.remote_user = latest["user"]
        self.state = latest["state"]
        self.offline.ack(self.state, self.remote_revision, username, self.remote_user)
        return {**self.state, "__remoteRevision": self.remote_revision}

    def getState(self):
        with self._lock:
            if self.connection.get("mode") == "client":
                try:
                    if not self._network_available or not self.remote_token:
                        self._maybe_reconnect_client()
                    return self._sync_client_from_host()
                except PermissionError:
                    raise
                except (ConnectionError, TimeoutError, OSError) as error:
                    self._network_available = False
                    cached = self.offline.get_cached()
                    if cached is None:
                        raise RuntimeError("هیچ اطلاعات محلی از این حساب برای استفاده آفلاین پیدا نشد.") from error
                    cached = self._cloud_peer_view()
                    return {**cached, "__remoteRevision": self.remote_revision or "offline", "__offline": True}
                except RuntimeError as error:
                    if "اتصال به Google برقرار نشد" not in str(error):
                        raise
                    self._network_available = False
                    cached = self.offline.get_cached()
                    if cached is None:
                        raise
                    cached = self._cloud_peer_view()
                    return {**cached, "__remoteRevision": self.remote_revision or "offline", "__offline": True}
            self.state = self._load()
            self._observed_local_revision = revision(self.state)
            return self.state

    def getStateForUi(self):
        """Add an optimistic-write token only to the UI view, never backups/LAN."""
        with self._lock:
            state = self.getState()
            if self.connection.get("mode") == "client":
                return state
            self._ui_cas_required = True
            return {**state, "__localRevision": revision(state)}

    def saveState(self, state):
        with self._lock:
            base_revision = state.get("__remoteRevision") if isinstance(state, dict) else None
            local_revision = state.get("__localRevision") if isinstance(state, dict) else None
            if isinstance(state, dict):
                state = {key: value for key, value in state.items() if not key.startswith("__")}
            state = normalize_state(state)
            if self.connection.get("mode") == "client":
                username = (self.remote_user or {}).get("username")
                if not username:
                    raise PermissionError("حساب کاربر شبکه شناسایی نشد.")
                if (self.remote_user or {}).get("role") == "viewer":
                    raise PermissionError("این کاربر فقط مجاز به مشاهده است.")
                if (self._network_available and not self.offline.has_pending()
                        and self.remote_revision and base_revision
                        and base_revision != self.remote_revision):
                    raise RuntimeError("CONFLICT: این نسخه قدیمی است. پیش از ذخیره تازه‌سازی کنید.")
                previous = self.offline.get_cached()
                self.offline.queue(state, username)
                try:
                    result = self._sync_client_from_host()
                    return {"revision": result["__remoteRevision"], "offline": False}
                except PermissionError:
                    raise
                except (ConnectionError, TimeoutError, OSError):
                    self._network_available = False
                    self._publish_peer_change(previous, state)
                    return {"revision": base_revision or "offline", "offline": True}
                except RuntimeError as error:
                    if "اتصال به Google برقرار نشد" in str(error):
                        self._network_available = False
                        self._publish_peer_change(previous, state)
                        return {"revision": base_revision or "offline", "offline": True}
                    raise
            if local_revision is None and self._ui_cas_required:
                raise RuntimeError("CONFLICT: شناسه نسخه محلی از درخواست رابط حذف شده است.")
            expected = local_revision if local_revision is not None else self._observed_local_revision
            saved = self._save_local_state(state, expected_local_revision=expected)
            self._observed_local_revision = revision(state)
            return {"localRevision": revision(state)} if local_revision is not None else saved

    def exportBackup(self):
        window = webview.windows[0]
        chosen = window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename="madar-backup.json",
            file_types=("JSON files (*.json)",),
        )
        if not chosen:
            return {"canceled": True}
        target = Path(chosen if isinstance(chosen, str) else chosen[0])
        with self._lock:
            backup = self.getState()
            backup.pop("__remoteRevision", None)
            atomic_save(target, backup)
        return {"path": str(target)}

    def importBackup(self):
        if self.connection.get("mode") == "client":
            raise PermissionError("بازیابی نسخه پشتیبان باید روی کامپیوتر سرور انجام شود.")
        window = webview.windows[0]
        chosen = window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("JSON files (*.json)",),
        )
        if not chosen:
            return {"canceled": True}
        selected = chosen if isinstance(chosen, str) else chosen[0]
        incoming = normalize_state(json.loads(Path(selected).read_text(encoding="utf8")))
        with self._lock:
            self._replace_local_state(incoming)
        return {"state": incoming}

    def _credentials(self):
        if not self.auth.exists():
            return None
        return json.loads(protect_windows(self.auth.read_bytes(), decrypt=True).decode("utf8"))

    def _save_credentials(self, credentials):
        self.auth.write_bytes(protect_windows(json.dumps(credentials).encode("utf8")))

    def driveStatus(self):
        c = self._credentials()
        return {"connected": bool(c), "clientId": c.get("clientId", "") if c else ""}

    def driveDisconnect(self):
        self.auth.unlink(missing_ok=True)
        return {"connected": False}

    def driveConnect(self, clientId):
        import re
        if not isinstance(clientId, str) or not re.fullmatch(r"\d+-[a-zA-Z0-9_-]+\.apps\.googleusercontent\.com", clientId.strip()):
            raise ValueError("Google OAuth Desktop Client ID معتبر نیست.")
        clientId = clientId.strip()
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        csrf = secrets.token_urlsafe(28)
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from queue import Queue
        queue = Queue(maxsize=1)
        class Callback(BaseHTTPRequestHandler):
            def do_GET(self):
                params = parse_qs(urlsplit(self.path).query)
                if urlsplit(self.path).path != "/oauth2callback":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write("<meta charset='utf-8'><p>می‌توانید این پنجره را ببندید و به مدار برگردید.</p>".encode())
                if params.get("state", [""])[0] != csrf:
                    queue.put(("error", "درخواست ورود Google از نظر امنیتی معتبر نیست."))
                elif params.get("error"):
                    queue.put(("error", "ورود Google لغو شد."))
                else:
                    queue.put(("code", params.get("code", [""])[0]))
            def log_message(self, *args):
                return
        server = HTTPServer(("127.0.0.1", 0), Callback)
        redirect = f"http://127.0.0.1:{server.server_port}/oauth2callback"
        params = {
            "client_id": clientId, "redirect_uri": redirect, "response_type": "code",
            "scope": SCOPE, "state": csrf, "code_challenge": challenge,
            "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent",
        }
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            webbrowser.open("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))
            from queue import Empty
            try:
                kind, code = queue.get(timeout=180)
            except Empty:
                raise RuntimeError("زمان ورود Google تمام شد.")
            if kind != "code" or not code:
                raise RuntimeError(code or "Google کد ورود ارسال نکرد.")
            form = urlencode({
                "client_id": clientId, "code": code, "code_verifier": verifier,
                "redirect_uri": redirect, "grant_type": "authorization_code",
            }).encode()
            tokens = http_json(
                "https://oauth2.googleapis.com/token", method="POST", data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if not tokens.get("refresh_token"):
                raise RuntimeError("Google مجوز بازیابی بلندمدت نداد؛ دوباره متصل شوید.")
            self._save_credentials({
                "clientId": clientId, "accessToken": tokens["access_token"],
                "refreshToken": tokens["refresh_token"],
                "expiresAt": time.time() + int(tokens.get("expires_in", 3600)),
            })
            return {"connected": True, "clientId": clientId}
        finally:
            server.shutdown()
            server.server_close()

    def _access_token(self):
        c = self._credentials()
        if not c:
            raise RuntimeError("ابتدا حساب Google را متصل کنید.")
        if c.get("expiresAt", 0) > time.time() + 90:
            return c["accessToken"]
        form = urlencode({
            "client_id": c["clientId"], "refresh_token": c["refreshToken"],
            "grant_type": "refresh_token",
        }).encode()
        tokens = http_json(
            "https://oauth2.googleapis.com/token", method="POST", data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        c["accessToken"] = tokens["access_token"]
        c["expiresAt"] = time.time() + int(tokens.get("expires_in", 3600))
        self._save_credentials(c)
        return c["accessToken"]

    def _drive(self, url, method="GET", data=None, headers=None):
        token = self._access_token()
        return http_json(url, method, data, {"Authorization": "Bearer " + token, **(headers or {})})

    def driveList(self):
        params = urlencode({
            "spaces": "appDataFolder", "fields": "nextPageToken,files(id,name,createdTime,modifiedTime,size)",
            "pageSize": 100, "orderBy": "modifiedTime desc",
        })
        response = self._drive(GOOGLE_API + "/files?" + params)
        return [{
            "id": f["id"], "name": f["name"],
            "createdAt": f.get("createdTime") or f.get("modifiedTime"),
            "size": int(f.get("size", 0)),
        } for f in response.get("files", []) if f.get("name", "").startswith("madar-backup-")]

    def driveUpload(self):
        with self._lock:
            state = self.getState()
            state.pop("__remoteRevision", None)
            is_valid(state)
            stamp = datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")
            name = "madar-backup-" + stamp + ".json"
            boundary = "madar" + secrets.token_hex(12)
            start = ("--" + boundary + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n" +
                     json.dumps({"name": name, "parents": ["appDataFolder"], "mimeType": "application/json"}) +
                     "\r\n--" + boundary + "\r\nContent-Type: application/json\r\n\r\n").encode()
            body = start + json.dumps(state, ensure_ascii=False).encode("utf8") + ("\r\n--" + boundary + "--").encode()
        result = self._drive(
            GOOGLE_UPLOAD, "POST", body,
            {"Content-Type": "multipart/related; boundary=" + boundary},
        )
        return {"id": result.get("id"), "name": name}

    def driveRestore(self, identifier):
        if self.connection.get("mode") == "client":
            raise PermissionError("بازیابی Google Drive فقط روی سرور مجاز است.")
        if not isinstance(identifier, str):
            raise ValueError("شناسه فایل معتبر نیست.")
        listed = self.driveList()
        if not any(item["id"] == identifier for item in listed):
            raise ValueError("نسخه انتخاب‌شده پیدا نشد.")
        restored = normalize_state(self._drive(GOOGLE_API + "/files/" + identifier + "?alt=media"))
        with self._lock:
            self._replace_local_state(restored)
        return restored


JS_BRIDGE = """
<script>
window.madar = Object.fromEntries(
 ['getState','getStateForUi','saveState','exportBackup','importBackup','driveStatus',
  'driveConnect','driveDisconnect','driveList','driveUpload','driveRestore',
  'lanStatus','lanDiscover','hostServiceStatus','lanHost','lanJoin','lanLeave','lanUsers','lanSaveUser','lanDeleteUser',
  'lanDisplayRoles','lanSaveDisplayRole','lanDeleteDisplayRole',
  'lanProfiles','lanMyProfile','lanChangePassword','lanResetPassword',
  'getPreferences','setPreferences','plannerRead','plannerWrite','openSharedFile','downloadSharedFile','chooseSharedFile','attachmentSave','releaseCheck','releaseDownload','releaseInstall','createLocalBackup','listLocalBackups','restoreLocalBackup','automaticBackupStatus',
  'syncStatus','chooseDriveFolder','driveFolderStatus','driveFolderBackup']
  .concat(['collabRead','collabCommand','automationButtonsList',
           'automationButtonsSave','automationButtonsDelete','automationButtonRun',
           'driveFolderList','driveFolderRestore',
           'cloudPeerStatus','cloudPeerConfigure','cloudPeerGenerate','cloudPeerForget',
           'financeRead','financeOverview','financeStatus','financeCommand',
           'accountingRead','accountingCommand',
           'standaloneAccountingRead','standaloneAccountingCommand',
           'standaloneAccountingParsianHistory','standaloneAccountingParsianCompany','standaloneAccountingParsianExtended',
           'standaloneAccountingParsianArchiveIndex','standaloneAccountingParsianArchiveRows',
           'standaloneAccountingCsvChooseFile','standaloneAccountingCsvPreview',
           'standaloneAccountingPrepare',
           'standaloneAccountingQuote',
           'runDueScheduler','attachmentList','attachmentPreview','attachmentRead',
           'attachmentUpload','attachmentDelete','attachmentBackup',
           'createUnifiedSqliteBackup','storageStatus','enableUnifiedStorage',
           'integrationIssueKey','integrationRevokeKey',
           'calendarExportIcs','calendarImportPreview',
           'automationEngineStatus','enableAutomationEngine'])
 .map(key => [key, (...args) => new Promise((resolve, reject) => {
   // WebView2 can publish window.pywebview.api before each exported method is
   // ready after navigation. Never call an undefined bridge entry.
   const invoke = (attempt = 0) => {
     const exported = window.pywebview && window.pywebview.api;
     if (exported && typeof exported[key] === 'function') {
       try { Promise.resolve(exported[key](...args)).then(resolve, reject); }
       catch (error) { reject(error); }
     } else if (attempt < 75) {
       setTimeout(() => invoke(attempt + 1), 80);
     } else {
       reject(new Error('Native bridge method unavailable: ' + key));
     }
   };
   invoke();
 })])
);
</script>
"""

# Keep the accounting page's JavaScript wrapper independent from task routes.
# This is UI-surface reduction, not an OS/process security sandbox: pywebview
# still holds the original Bridge and native authorization remains mandatory.
ACCOUNTING_JS_BRIDGE = """
<script>
window.madar = Object.fromEntries(
 ['standaloneAccountingRead','standaloneAccountingCommand',
  'standaloneAccountingParsianHistory','standaloneAccountingParsianCompany','standaloneAccountingParsianExtended',
           'standaloneAccountingParsianArchiveIndex','standaloneAccountingParsianArchiveRows',
           'standaloneAccountingCsvChooseFile','standaloneAccountingCsvPreview',
  'releaseCheck','releaseDownload','releaseInstall'].map(key =>
 [key, (...args) => new Promise((resolve, reject) => {
   // The standalone page frequently follows an in-window navigation from the
   // task desk. Its JavaScript API must not race WebView2 method injection.
   const invoke = (attempt = 0) => {
     const exported = window.pywebview && window.pywebview.api;
     if (exported && typeof exported[key] === 'function') {
       try { Promise.resolve(exported[key](...args)).then(resolve, reject); }
       catch (error) { reject(error); }
     } else if (attempt < 75) {
       setTimeout(() => invoke(attempt + 1), 80);
     } else {
       reject(new Error('Native bridge method unavailable: ' + key));
     }
   };
   invoke();
 })])
);
</script>
"""


def integrated_native_closing_scripts():
    """Explicit URL allow-list for the main window's native close decision.

    A partially loaded or unknown page cannot bypass unsaved accounting edits.
    Unlike the standalone accounting window, the task board has no React
    accounting hook and is safe to close after the mandatory host backup.
    """
    confirm = (
        "(()=>{const path=location.pathname.toLowerCase();"
        "if(path==='/'||path==='/index.html')return "
        "typeof window.__madarTasksConfirmNativeClose==='function' "
        "&&window.__madarTasksConfirmNativeClose();"
        "if(path==='/accounting.html')return "
        "typeof window.__madarAccountingConfirmNativeClose==='function' "
        "&&window.__madarAccountingConfirmNativeClose();"
        "return false})()")
    abort = (
        "(()=>{const path=location.pathname.toLowerCase();"
        "if(path==='/'||path==='/index.html')return "
        "typeof window.__madarTasksAbortNativeClose==='function' "
        "&&window.__madarTasksAbortNativeClose();"
        "if(path==='/accounting.html')return "
        "typeof window.__madarAccountingAbortNativeClose==='function' "
        "&&window.__madarAccountingAbortNativeClose();"
        "return false})()")
    return confirm, abort


def main():
    # A crashed offline full restore can leave the prior data root under a
    # journal-owned sibling. Refuse to create/open a new live database here;
    # explicit offline rollback must happen before any Bridge writer exists.
    from maintenance_recovery import pending_restore_journal
    appdata_root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if not appdata_root:
        raise RuntimeError("پوشه اطلاعات کاربر در دسترس نیست.")
    data_root = Path(appdata_root) / APP_NAME
    pending = pending_restore_journal(data_root)
    if pending is not None:
        raise RuntimeError(
            "بازیابی قبلی مدار ناتمام است. برنامه برای حفاظت از داده‌ها اجرا نشد. "
            "برنامه‌های مدار را ببندید و از ابزار maintenance_recovery "
            "برای recover آفلاین استفاده کنید. ژورنال: " + str(pending)
        )
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    site = bundle / "dist"
    if not (site / "index.html").exists():
        raise RuntimeError("فایل‌های رابط یافت نشد. ابتدا npm run build اجرا شود.")
    api = Bridge()
    # Financial snapshots are separate from task/board backups. On the local
    # host, the accounting SQLite is initialized explicitly before the first
    # validated snapshot. A LAN client must not back up its empty local copy.
    financial_backup = None
    periodic_backup = None
    exit_financial_backup_done = False
    if api.connection.get("mode") != "client":
        from standalone_accounting_auto_backup import AutomaticStandaloneBackups
        from host_backup_scheduler import HostBackupScheduler
        api._standalone_accounting_store()
        financial_backup = AutomaticStandaloneBackups(
            api.path.parent, plaintext_acknowledged=True)
        financial_backup.backup_now()  # Fail startup if a valid backup cannot be made.
        financial_backup.start()
        try:
            periodic_backup = HostBackupScheduler(api)
            periodic_backup.start()  # Initial validated task snapshot before GUI.
            api._host_periodic_backup = periodic_backup
        except Exception:
            financial_backup.stop()
            raise
    api.startScheduledJobs()
    class StaticHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(site), **kwargs)
        def do_GET(self):
            page = urlsplit(self.path).path
            if page in ("/", "/index.html", "/accounting.html"):
                filename = "accounting.html" if page == "/accounting.html" else "index.html"
                content = (site / filename).read_text(encoding="utf8")
                bridge_js = ACCOUNTING_JS_BRIDGE if filename == "accounting.html" else JS_BRIDGE
                content = content.replace("</head>", bridge_js + "</head>")
                encoded = content.encode("utf8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(encoded)
            else:
                super().do_GET()
        def log_message(self, *args):
            return
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        window = webview.create_window(
            "مدار | مدیریت کارهای من", f"http://127.0.0.1:{server.server_port}/",
            width=1500, height=960, min_size=(900, 650), js_api=api,
            background_color="#f7f8fa",
        )
        from standalone_accounting_desktop import (
            NativeAccountingCloseGate, recover_native_editor_after_close_abort)
        # The integrated executable also navigates to accounting.html. Its
        # titlebar X must not bypass React's unsaved-financial-editor veto.
        # The ordinary task-manager page has no accounting React callback;
        # permit it only for these two exact, already-loaded document paths.
        integrated_confirm, integrated_abort = integrated_native_closing_scripts()
        failed_exit_backup_notice = False

        def require_backup_before_close():
            nonlocal exit_financial_backup_done, failed_exit_backup_notice
            try:
                with api._lock:
                    if financial_backup is not None:
                        financial_backup.backup_now()
                    api._exit_financial_locked = True
                exit_financial_backup_done = True
                failed_exit_backup_notice = False
                return True
            except Exception as error:
                failed_exit_backup_notice = True
                print("MANDATORY FINANCIAL EXIT BACKUP FAILED: " + str(error),
                      file=sys.stderr)
                return False

        def restore_after_abort():
            nonlocal exit_financial_backup_done, failed_exit_backup_notice
            recovered = recover_native_editor_after_close_abort(
                window, api, js_script=integrated_abort,
                host_lock_attribute='_exit_financial_locked')
            if recovered:
                exit_financial_backup_done = False
                if failed_exit_backup_notice:
                    failed_exit_backup_notice = False
                    # The installed Windows EXE is windowed: stderr alone is
                    # invisible to its operator. Give a clear explanation only
                    # AFTER the financial editor has been safely unfrozen.
                    try:
                        window.evaluate_js('window.alert(' + json.dumps(
                            'بستن مدار متوقف شد، چون ذخیره نسخه پشتیبان مالی ناموفق بود. '
                            'فضای دیسک و دسترسی پوشه داده را بررسی کنید و دوباره تلاش کنید.',
                            ensure_ascii=False) + ')')
                    except Exception as error:
                        print('Unable to display finance backup warning: '+str(error),
                              file=sys.stderr)
            return recovered

        integrated_close_gate = NativeAccountingCloseGate(
            window, api, require_backup_before_close,
            on_aborted_close=restore_after_abort,
            decision_script=integrated_confirm)
        window.events.closing += integrated_close_gate.closing
        if os.environ.get("MADAR_QA_REPORT"):
            bridge_qa_started = threading.Event()
            bridge_qa_start_lock = threading.Lock()
            def diagnostic():
                # Navigation from main to the standalone accounting document
                # emits additional loaded events. Allow only one diagnostic
                # runner to own a navigation-based QA session; otherwise two
                # concurrent flows can click one another's buttons and race
                # while writing the same report. Ordinary view-specific QA
                # runs retain their original loaded-event behavior.
                singleflight = (
                    os.environ.get("MADAR_QA_VIEW") in ("bridge-readiness", "fresh-profile") or
                    (os.environ.get("MADAR_RELEASE_QA") == "1" and
                     os.environ.get("MADAR_QA_INTERACTION") == "1")
                )
                if singleflight:
                    with bridge_qa_start_lock:
                        if bridge_qa_started.is_set():
                            return
                        bridge_qa_started.set()
                time.sleep(2)
                if os.environ.get("MADAR_QA_VIEW") == "fresh-profile":
                    # Isolated release QA: record only counts and the empty
                    # workspace CTA; never include user titles or financial data.
                    snapshot = api.getState()
                    result = {
                        "projectCount": len(snapshot.get("projects", [])),
                        "boardCount": len(snapshot.get("boards", [])),
                        "cardCount": len(snapshot.get("tasks", [])),
                        "workspaceCount": len(snapshot.get("workspaces", [])),
                        "workspaceNameIsDefault": (
                            len(snapshot.get("workspaces", [])) == 1 and
                            snapshot["workspaces"][0].get("name") == "فضای کاری من"
                        ),
                        "mounted": False,
                        "emptyOnboardingVisible": False,
                    }
                    for _ in range(40):
                        try:
                            ui = window.evaluate_js(
                                "(()=>({mounted:!!document.querySelector('.app-shell'),"
                                "emptyOnboardingVisible:!!document.querySelector('.workspace-empty-board'),"
                                "createButton:!!Array.from(document.querySelectorAll("
                                "'.workspace-empty-board button')).find("
                                "x=>x.textContent.includes('ساخت اولین پروژه'))}))()")
                            result.update(ui)
                            if ui.get("mounted") and ui.get("emptyOnboardingVisible"):
                                break
                        except Exception:
                            pass
                        time.sleep(0.25)
                    Path(os.environ["MADAR_QA_REPORT"]).write_text(
                        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
                    return
                if os.environ.get("MADAR_QA_VIEW") == "read-only-runtime-health":
                    # Real-profile smoke is opt-in and must never disclose task
                    # titles, account details, or mutate any financial record.
                    details = {}
                    for _ in range(16):
                        try:
                            details = window.evaluate_js("(()=>({"
                                "path:location.pathname,"
                                "ready:document.readyState,"
                                "rootLength:document.getElementById('root')?.innerHTML.length||0,"
                                "main:!!document.querySelector('.app-shell'),"
                                "accounting:!!document.querySelector('.sac-root'),"
                                "loading:!!document.querySelector('.loading'),"
                                "bridge:typeof window.madar,"
                                "read:typeof window.pywebview?.api?.standaloneAccountingRead,"
                                "errorPresent:!!document.querySelector('.sac-alert.error,[role=alert]')"
                                "}))()")
                            if details.get("rootLength", 0) > 1000:
                                break
                        except Exception as exc:
                            details = {"diagnosticError": type(exc).__name__}
                        time.sleep(0.25)
                    Path(os.environ["MADAR_QA_REPORT"]).write_text(
                        json.dumps(details, ensure_ascii=False, indent=2), encoding="utf8")
                    return
                # First-run isolated profiles initialize the accounting bridge
                # and board asynchronously; document.readyState alone may be
                # complete while React's root is still empty. Bound the wait.
                if os.environ.get("MADAR_QA_VIEW", "").startswith("board-"):
                    for _ in range(32):
                        try:
                            if window.evaluate_js("!!document.querySelector('.kanban-lane')"):
                                break
                        except Exception:
                            pass
                        time.sleep(0.25)
                values = {"port": server.server_port}
                if os.environ.get("MADAR_QA_VIEW", "").startswith("board-"):
                    try:
                        values["preActionRootLength"] = window.evaluate_js("document.getElementById('root')?.innerHTML.length ?? -1")
                        window.evaluate_js("window.__madarQaErrors=[];window.addEventListener('error',e=>window.__madarQaErrors.push(String(e.message)));window.addEventListener('unhandledrejection',e=>window.__madarQaErrors.push(String(e.reason)))")
                    except Exception:
                        pass
                if os.environ.get("MADAR_QA_VIEW") == "sample-project":
                    try:
                        window.evaluate_js("document.querySelectorAll('.projects-nav .project-entry > button:first-child')[1]?.click()")
                        time.sleep(0.4)
                    except Exception:
                        pass
                elif os.environ.get("MADAR_QA_VIEW") == "widget-settings":
                    try:
                        window.evaluate_js("document.querySelector('button[aria-label=\"تنظیمات\"]')?.click()")
                        time.sleep(0.4)
                    except Exception:
                        pass
                elif os.environ.get("MADAR_QA_VIEW") == "task-detail":
                    try:
                        window.evaluate_js("document.querySelector('.task-card')?.click()")
                        time.sleep(0.5)
                    except Exception:
                        pass
                elif os.environ.get("MADAR_QA_VIEW") == "workspace-manager":
                    try:
                        window.evaluate_js("Array.from(document.querySelectorAll('.sidebar button')).find(button=>button.textContent.includes('مدیریت فضاهای کاری'))?.click()")
                        time.sleep(0.5)
                    except Exception:
                        pass
                elif os.environ.get("MADAR_QA_VIEW") == "clock-quick":
                    try:
                        window.evaluate_js("document.querySelector('.clock-widget__trigger')?.click()")
                        time.sleep(0.6)
                    except Exception:
                        pass
                elif os.environ.get("MADAR_QA_VIEW") == "bridge-readiness":
                    # Isolated, read-only WebView2 contract probe. Never navigate
                    # a live accounting profile through synthetic automation.
                    qa_root = str(Path(os.environ.get("APPDATA", "")).resolve()).lower()
                    if "madar-qa-bridge-" not in qa_root:
                        raise PermissionError("Bridge QA requires isolated APPDATA")
                    def bridge_state():
                        return window.evaluate_js("(()=>({"
                            "path:location.pathname,"
                            "ready:document.readyState,"
                            "bridge:typeof window.madar,"
                            "api:typeof window.pywebview?.api,"
                            "read:typeof window.pywebview?.api?.standaloneAccountingRead,"
                            "command:typeof window.pywebview?.api?.standaloneAccountingCommand,"
                            "root:document.getElementById('root')?.innerHTML.length||0,"
                            "error:document.querySelector('.sac-alert.error')?.textContent.slice(0,160)||''"
                            "}))()")
                    try:
                        values["nativeBridgeBefore"] = bridge_state()
                        window.load_url(f"http://127.0.0.1:{server.server_port}/accounting.html")
                        for _ in range(36):
                            time.sleep(0.25)
                            try:
                                current = bridge_state()
                            except Exception:
                                continue
                            if (current and current.get("path") == "/accounting.html" and
                                    current.get("root", 0) > 500):
                                break
                        values["nativeBridgeAccounting"] = bridge_state()
                        # Exercise the real, read-only Python Bridge method.
                        # Store only pass/fail metadata, never ledger values.
                        window.evaluate_js(
                            "(()=>{window.__madarReadHealth={done:false};"
                            "Promise.resolve().then(()=>window.madar.standaloneAccountingRead())"
                            ".then(value=>{window.__madarReadHealth={done:true,"
                            "ok:!!value&&typeof value==='object',errorType:''}})"
                            ".catch(error=>{window.__madarReadHealth={done:true,"
                            "ok:false,errorType:String(error?.name||'Error')}});"
                            "return true})()")
                        for _ in range(30):
                            time.sleep(0.2)
                            response = window.evaluate_js("window.__madarReadHealth||{}")
                            if response and response.get("done"):
                                break
                        values["nativeAccountingReadHealth"] = response
                        window.load_url(f"http://127.0.0.1:{server.server_port}/index.html")
                        for _ in range(30):
                            time.sleep(0.2)
                            current = bridge_state()
                            if (current and current.get("path") == "/index.html" and
                                    current.get("root", 0) > 1000):
                                break
                        values["nativeBridgeAfterReturn"] = bridge_state()
                    except Exception as exc:
                        values["nativeBridgeError"] = repr(exc)
                elif os.environ.get("MADAR_QA_VIEW") in ("board-list-menu", "board-add-list", "board-add-create"):
                    try:
                        control = (".lane-menu-trigger" if os.environ["MADAR_QA_VIEW"] == "board-list-menu"
                                   else ".kanban-add-list__trigger")
                        window.evaluate_js("document.querySelector(" + json.dumps(control) + ")?.click()")
                        time.sleep(0.5)
                        # Only the explicitly isolated QA profile may submit
                        # a synthetic list; never mutate a normal user's data.
                        if os.environ["MADAR_QA_VIEW"] == "board-add-create":
                            qa_root = str(Path(os.environ.get("APPDATA", "")).resolve()).lower()
                            if (os.environ.get("MADAR_QA_MUTATE_ISOLATED") != "1" or
                                    "madar-qa-boards-" not in qa_root):
                                raise PermissionError("Synthetic board mutation requires isolated QA profile")
                            window.evaluate_js(
                                "(()=>{const f=document.querySelector('.kanban-add-list__form input');"
                                "if(!f)return false;"
                                "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(f,'QA list creation');"
                                "f.dispatchEvent(new Event('input',{bubbles:true}));return true;})()"
                            )
                            time.sleep(0.3)
                            window.evaluate_js("document.querySelector('.kanban-add-list__form button[type=submit]')?.click()")
                            time.sleep(0.7)
                    except Exception:
                        pass
                if os.environ.get("MADAR_QA_THEME") == "dark":
                    try:
                        window.evaluate_js("document.documentElement.dataset.theme='dark'")
                        time.sleep(0.35)
                    except Exception:
                        pass
                if (os.environ.get("MADAR_RELEASE_QA") == "1" and
                        os.environ.get("MADAR_QA_INTERACTION") == "1"):
                    # Hardcoded QA clicks only in the isolated smoke harness.
                    # Never load arbitrary JS from a path or an environment value.
                    from gui_user_flow import run_ui_flow
                    values["uiFlow"] = run_ui_flow(window, api)
                for name, script in {
                    "url": "location.href",
                    "readyState": "document.readyState",
                    "rootLength": "document.getElementById('root')?.innerHTML.length ?? -1",
                    "bodyTextStart": "document.body?.innerText.slice(0,250) ?? ''",
                    "bridgeType": "typeof window.madar",
                    "pywebviewType": "typeof window.pywebview",
                    "fontLoaded": "document.fonts.check('14px Vazirmatn')",
                    "theme": "document.documentElement.dataset.theme",
                    "stageCount": "document.querySelectorAll('.kanban-lane').length",
                    "cardCount": "document.querySelectorAll('.task-card').length",
                    "cardTextStart": "document.querySelector('.task-card')?.innerText.slice(0,120) ?? ''",
                    "assignedDisplay": "document.querySelector('.interface-mode-selector--compact')?.innerText.slice(0,160) ?? ''",
                    "widgetTheme": "document.querySelector('.clock-widget')?.dataset.widgetTheme ?? ''",
                    "widgetPlacement": "document.querySelector('.clock-widget')?.className ?? ''",
                    "widgetSettingsShown": "!!document.querySelector('.settings-modal .widget-settings')",
                    "widgetSettingsSections": "document.querySelectorAll('.settings-modal .widget-settings__group').length",
                    "taskLayout": "(()=>{const d=document.querySelector('.drawer');if(!d)return null;const r=d.getBoundingClientRect();return {width:Math.round(r.width),height:Math.round(r.height),quickButtons:d.querySelectorAll('.task-quick-actions button').length,sections:d.querySelectorAll('.edit-section').length,optionalGroups:d.querySelectorAll('.task-optional-block').length,openOptionalGroups:d.querySelectorAll('.task-optional-block[open]').length,scrollPadding:getComputedStyle(d.querySelector('.drawer-scroll')).padding,layoutColumns:getComputedStyle(d.querySelector('.edit-grid')).gridTemplateColumns};})()",
                    "taskQuickJumpFocus": "(()=>{const b=document.querySelector('.task-quick-actions button[aria-controls=task-section-description]');b?.click();return document.activeElement?.id||'';})()",
                    "workspaceModalStyle": "(()=>{const p=document.querySelector('.dialog > .workspaces-panel');if(!p)return null;const s=getComputedStyle(p);const h=p.querySelector('.workspaces-heading strong');const t=h?getComputedStyle(h):null;return {text:s.color,background:s.backgroundColor,heading:t?.color||null,rows:p.querySelectorAll('.workspaces-row').length};})()",
                    "clockQuickPopup": "(()=>{const m=document.querySelector('.clock-widget__menu');if(!m)return null;const r=m.getBoundingClientRect();return {width:Math.round(r.width),height:Math.round(r.height),insideViewport:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,quickChoices:m.querySelectorAll('.widget-settings__choices button').length,fullSettingsLink:!!m.querySelector('.clock-widget__more-button')};})()",
                    "kanbanGeometry": "(()=>{const b=document.querySelector('.kanban');if(!b)return null;const lanes=[...b.querySelectorAll(':scope > .kanban-lane')];const tile=b.querySelector(':scope > .kanban-add-list');const r=b.getBoundingClientRect();return {width:Math.round(r.width),lanes:lanes.map(x=>{const box=x.getBoundingClientRect(),css=getComputedStyle(x);return {width:Math.round(box.width),height:Math.round(box.height),flex:css.flex,caption:x.querySelector('.lane-heading strong')?.innerText||'',buttons:x.querySelectorAll('.lane-menu-trigger').length};}),addTileWidth:tile?Math.round(tile.getBoundingClientRect().width):null,boardScrollWidth:b.scrollWidth,boardClientWidth:b.clientWidth};})()",
                    "laneMenuGeometry": "(()=>{const p=document.querySelector('.lane-actions-popover');if(!p)return null;const r=p.getBoundingClientRect();return {width:Math.round(r.width),height:Math.round(r.height),withinViewport:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,editorInputs:p.querySelectorAll('form input').length,menuActions:p.querySelectorAll('button').length};})()",
                    "inlineListForm": "!!document.querySelector('.kanban-add-list__form')",
                    "qaAddedList": "!![...document.querySelectorAll('.lane-heading strong')].find(node=>node.textContent.includes('QA list creation'))",
                    "qaBrowserErrors": "window.__madarQaErrors || []",
                }.items():
                    try:
                        values[name] = window.evaluate_js(script)
                    except Exception as ex:
                        values[name] = repr(ex)
                screenshot_path = os.environ.get("MADAR_QA_SCREENSHOT")
                if screenshot_path:
                    try:
                        from System import Action
                        from System.IO import File
                        from System.Threading.Tasks import Task
                        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
                        control = window.native.browser.webview
                        finished = threading.Event()
                        output_stream = File.Create(screenshot_path)
                        outcome = {"done": False}
                        def complete(task):
                            try:
                                outcome["done"] = bool(task.IsCompletedSuccessfully)
                                if task.Exception:
                                    outcome["error"] = str(task.Exception)
                            finally:
                                output_stream.Close()
                                finished.set()
                        def begin():
                            task = control.CoreWebView2.CapturePreviewAsync(
                                CoreWebView2CapturePreviewImageFormat.Png, output_stream)
                            task.ContinueWith(Action[Task](complete),
                                              window.native.browser.syncContextTaskScheduler)
                        control.Invoke(Action(begin))
                        finished.wait(12)
                        values["screenshot"] = outcome
                    except Exception as ex:
                        values["screenshot"] = repr(ex)
                Path(os.environ["MADAR_QA_REPORT"]).write_text(
                    json.dumps(values, ensure_ascii=False, indent=2), encoding="utf8"
                )
            window.events.loaded += lambda: threading.Thread(target=diagnostic, daemon=True).start()
        webview.start(gui="edgechromium", debug=False)
    finally:
        api.stopScheduledJobs()
        try:
            if periodic_backup is not None:
                periodic_backup.stop()
            if financial_backup is not None:
                financial_backup.stop()
                if not exit_financial_backup_done:
                    # Fallback for missing closing callbacks. A failure stays
                    # visible but must not leave the loopback host running.
                    financial_backup.backup_now()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
