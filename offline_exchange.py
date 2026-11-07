"""Durable offline edits for a LAN client, with cautious three-way reconciliation.

Google Drive for desktop can sync exported *immutable* snapshots in a user-selected
directory. It is a transport for recovery, NOT a transaction/permission server.
No remote file is ever trusted as an authorized write to the LAN host.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import secrets
import time


def atomic_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        with tmp.open("w", encoding="utf8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def clean_data(state):
    return {k: deepcopy(v) for k, v in state.items() if not k.startswith("__")}


def _index(items):
    # A dictionary comprehension silently keeps only the last duplicate ID.
    # Offline drafts may be corrupted or stale, so never discard records while
    # reconciling them with the host's authoritative state.
    if not isinstance(items, list):
        raise RuntimeError("CONFLICT: invalid offline merge record list")
    indexed = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise RuntimeError("CONFLICT: invalid offline merge record id")
        identifier = item["id"]
        if identifier in indexed:
            raise RuntimeError("CONFLICT: duplicate record id in offline merge")
        indexed[identifier] = item
    return indexed


def _three_way_items(base, edited, latest):
    b, e, l = _index(base), _index(edited), _index(latest)
    changes = {identifier for identifier in set(b) | set(e) if b.get(identifier) != e.get(identifier)}
    # An already-applied identical edit is an idempotent retry, not a conflict.
    conflicting = sorted(identifier for identifier in changes
                         if l.get(identifier) != b.get(identifier)
                         and l.get(identifier) != e.get(identifier))
    if conflicting:
        raise RuntimeError("CONFLICT: هم‌زمان همین کار یا پروژه روی سرور و کلاینت تغییر کرده است: " + ", ".join(conflicting[:12]))
    merged = [deepcopy(v) for v in latest if v["id"] not in changes or v["id"] in e]
    # replace locally changed records without perturbing the other records or their order
    replacements = {k: deepcopy(e[k]) for k in changes if k in e}
    merged = [replacements.get(item["id"], item) for item in merged]
    for item in edited:
        if item["id"] in changes and item["id"] not in l:
            merged.append(deepcopy(item))
    return merged


def three_way_merge(base, local, latest, allow_structure=False):
    """Merge *nonoverlapping* records, rejecting overlapping edits.

    LAN access authorization is NOT handled here and must happen on the host.
    Editors are never allowed to rebase workspace/project changes.
    """
    b, e, l = (clean_data(x) for x in (base, local, latest))
    if not allow_structure and any(b.get(k) != e.get(k) for k in ("projects", "stages", "settings", "workspaces", "boards", "templates")):
        raise PermissionError("کلاینت فقط مجاز به ویرایش کارت‌های دارای دسترسی است.")
    merged = deepcopy(l)
    merged["tasks"] = _three_way_items(b["tasks"], e["tasks"], l["tasks"])
    if allow_structure:
        merged["projects"] = _three_way_items(b["projects"], e["projects"], l["projects"])
        for k in ("stages", "settings", "workspaces", "boards", "templates"):
            if b.get(k) != e.get(k):
                if b.get(k) != l.get(k) and e.get(k) != l.get(k):
                    raise RuntimeError("CONFLICT: ساختار پروژه هم‌زمان تغییر کرده است.")
                merged[k] = deepcopy(e.get(k))
    return merged


class OfflineStore:
    def __init__(self, root):
        self.root = Path(root)
        self.cache = self.root / "lan-offline-cache.json"
        self.pending = self.root / "lan-offline-pending.json"
        self.settings = self.root / "drive-folder-config.json"
        self.device = self.root / "device-identifier.json"
        self.publish_meta = self.root / "drive-folder-last-publish.json"

    def get_cached(self):
        if self.pending.exists():
            return json.loads(self.pending.read_text(encoding="utf8"))["edited"]
        if self.cache.exists():
            return json.loads(self.cache.read_text(encoding="utf8"))["state"]
        return None

    def remember(self, state, revision, username, user=None):
        if self.pending.exists():
            return
        atomic_json(self.cache, {"state": clean_data(state), "revision": revision,
                                 "username": username, "user": user or {"username": username}})

    def cached_user(self):
        if self.cache.exists():
            data = json.loads(self.cache.read_text(encoding="utf8"))
            return data.get("user", {"username": data.get("username"), "role": "viewer"})
        return None

    def has_pending(self):
        return self.pending.exists()

    def queue(self, edited, username):
        if self.pending.exists():
            saved = json.loads(self.pending.read_text(encoding="utf8"))
            if saved["username"] != username:
                raise PermissionError("پیش‌نویس حساب دیگری موجود است؛ ابتدا آن را بازیابی کنید.")
        else:
            if not self.cache.exists():
                raise RuntimeError("قبل از استفاده آفلاین باید یک بار به سرور متصل شوید.")
            cached = json.loads(self.cache.read_text(encoding="utf8"))
            if cached["username"] != username:
                raise PermissionError("داده آفلاین متعلق به حساب شبکه دیگری است.")
            saved = {"base": cached["state"], "baseRevision": cached["revision"], "username": username}
        saved["edited"] = clean_data(edited)
        saved["updatedAt"] = datetime.now(timezone.utc).isoformat()
        atomic_json(self.pending, saved)
        self.publish(saved)
        return saved

    def reconcile(self, latest, revision, username, allow_structure=False):
        if not self.pending.exists():
            self.remember(latest, revision, username)
            return None
        saved = json.loads(self.pending.read_text(encoding="utf8"))
        if saved["username"] != username:
            raise PermissionError("پیش‌نویس آفلاین متعلق به حساب کاربری دیگری است.")
        return three_way_merge(saved["base"], saved["edited"], latest, allow_structure)

    def ack(self, latest, revision, username, user=None):
        atomic_json(self.cache, {"state": clean_data(latest), "revision": revision,
                                 "username": username, "user": user or self.cached_user() or {"username": username}})
        self.pending.unlink(missing_ok=True)

    def set_sync_folder(self, folder):
        path = Path(folder).resolve(strict=True)
        if not path.is_dir() or path == Path(path.anchor) or str(path).startswith("\\\\"):
            raise ValueError("یک پوشه محلی همگام‌شده Google Drive برای دسکتاپ انتخاب کنید.")
        # Never take over, erase or overwrite arbitrary user-selected files.
        target = path / "Madar-Desk-Snapshots"
        target.mkdir(exist_ok=True)
        atomic_json(self.settings, {"folder": str(target)})
        return {"folder": str(target)}

    def folder_status(self):
        if not self.settings.exists():
            return {"configured": False, "folder": "", "pending": self.has_pending()}
        data = json.loads(self.settings.read_text(encoding="utf8"))
        folder = Path(data["folder"])
        return {"configured": True, "folder": str(folder), "available": folder.is_dir(),
                "pending": self.has_pending()}

    def list_snapshots(self):
        settings = self.folder_status()
        if not settings.get("configured") or not settings.get("available"):
            return []
        folder = Path(settings["folder"])
        files = []
        for item in sorted(folder.glob("*.json"), key=lambda x:x.stat().st_mtime, reverse=True)[:100]:
            if not item.is_file() or item.stat().st_size > 15_000_000:
                continue
            files.append({"name":item.name,"size":item.stat().st_size,
                          "modifiedAt":datetime.fromtimestamp(item.stat().st_mtime,timezone.utc).isoformat()})
        return files

    def read_snapshot(self, filename):
        if not isinstance(filename,str) or len(filename)>180 or not re.fullmatch(
            r"[A-Za-z0-9_.-]+\.json",filename
        ) or filename.startswith("."):
            raise ValueError("نام فایل بازیابی معتبر نیست.")
        folder_settings = self.folder_status()
        if not folder_settings.get("configured") or not folder_settings.get("available"):
            raise FileNotFoundError("پوشه همگام‌شده در دسترس نیست.")
        folder = Path(folder_settings["folder"])
        path = folder / filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 15_000_000:
            raise ValueError("فایل بازیابی معتبر نیست.")
        payload = json.loads(path.read_text(encoding="utf8"))
        if (not isinstance(payload,dict) or payload.get("schema")!=1
                or payload.get("type") not in ("backup","offline-draft")
                or not isinstance(payload.get("state"),dict)):
            raise ValueError("فرمت پشتیبان مدار معتبر نیست.")
        return deepcopy(payload["state"])

    def device_id(self):
        if not self.device.exists():
            atomic_json(self.device, {"id": secrets.token_hex(12)})
        return json.loads(self.device.read_text(encoding="utf8"))["id"]

    def publish(self, pending=None, current=None, username=None, force=False):
        """Write an immutable recovery record, without SMB link data or secret tokens.

        This does NOT claim another PC will automatically merge this record: a
        desktop Drive sync client must be signed in and sync the selected folder.
        """
        state = self.folder_status()
        if not state["configured"] or not state.get("available"):
            return None
        if not force and self.publish_meta.exists():
            try:
                published = json.loads(self.publish_meta.read_text(encoding="utf8"))
                if time.time() - float(published.get("time", 0)) < 30:
                    return None
            except (ValueError, TypeError, OSError):
                pass
        data = pending["edited"] if pending else current
        if data is None:
            return None
        cleaned = clean_data(data)
        for task in cleaned.get("tasks", []):
            task.pop("fileLinks", None)
        for project in cleaned.get("projects", []):
            project.pop("fileLinks", None)
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", str(username or pending.get("username", "local")))[:35]
        tick = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"{slug}-{self.device_id()}-{tick}-{secrets.token_hex(4)}.json"
        payload = {"schema": 1, "type": "offline-draft" if pending else "backup",
                   "user": slug, "device": self.device_id(), "updatedAt": tick,
                   "state": cleaned}
        path = Path(state["folder"]) / name
        atomic_json(path, payload)
        atomic_json(self.publish_meta, {"time": time.time(), "name": name})
        return {"name": name, "path": str(path)}
