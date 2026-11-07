"""Operator-owned invoice templates kept alongside ONE explicitly selected ledger.

No company discovery, no financial events. Writes are atomic and the prior
snapshot is saved for independent template recovery. Never interprets content
as code or as a filesystem path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import uuid

_LOCK = threading.RLock()
_KINDS = {"entry", "print", "issuer"}
_ID = re.compile(r"[a-f0-9]{32}\Z")
_MAX_BYTES = 2 * 1024 * 1024


class TemplateStoreError(ValueError):
    pass


def validate_library_document(document):
    """Strict enough to reject corrupt/untrusted backup companions before restore."""
    if (not isinstance(document, dict) or set(document) != {"version", "templates", "defaults"} or
            document["version"] != 1 or not isinstance(document["templates"], list) or
            len(document["templates"]) > 100 or not isinstance(document["defaults"], dict) or
            set(document["defaults"]) - _KINDS):
        raise TemplateStoreError("Invalid template library structure")
    ids = set()
    by_kind = {kind: set() for kind in _KINDS}
    for template in document["templates"]:
        if (not isinstance(template, dict) or set(template) != {"id", "kind", "title", "data"} or
                not isinstance(template["id"], str) or not _ID.fullmatch(template["id"]) or
                template["id"] in ids or template["kind"] not in _KINDS or
                not isinstance(template["title"], str) or not 1 <= len(template["title"].strip()) <= 100 or
                any(ord(char) < 32 for char in template["title"]) or
                not isinstance(template["data"], dict)):
            raise TemplateStoreError("Invalid template entry")
        ids.add(template["id"])
        kind = template["kind"]
        by_kind[kind].add(template["id"])
        data = template["data"]
        if kind == "entry":
            if (data.get("format") != "madar-invoice-lines-v1" or data.get("version") != 1 or
                    data.get("currency") not in ("RIAL", "TOMAN") or
                    not isinstance(data.get("lines"), list) or not 1 <= len(data["lines"]) <= 1000):
                raise TemplateStoreError("Invalid invoice-entry template")
            for line in data["lines"]:
                if (not isinstance(line, dict) or
                        not isinstance(line.get("description"), str) or
                        not 1 <= len(line["description"].strip()) <= 300 or
                        not str(line.get("quantity", "")).isdigit() or
                        not str(line.get("unitPrice", "")).isdigit()):
                    raise TemplateStoreError("Invalid invoice-entry row")
        elif kind == "print":
            if (data.get("format") != "madar-print-layout-v1" or data.get("version") != 1 or
                    data.get("page") not in ("A4", "A5") or
                    data.get("orientation") not in ("portrait", "landscape") or
                    not isinstance(data.get("fields"), list) or len(data["fields"]) != 6 or
                    {field.get("id") for field in data["fields"] if isinstance(field, dict)} !=
                    {"title", "seller", "buyer", "number", "date", "note"}):
                raise TemplateStoreError("Invalid print-layout template")
        elif kind == "issuer":
            profile = data.get("profile")
            if (data.get("format") != "madar-issuer-profile-v1" or
                    not isinstance(profile, dict) or
                    set(profile) - {"legalName", "nationalId", "economicCode", "postalCode", "phone", "address"} or
                    not isinstance(profile.get("legalName"), str) or not profile["legalName"].strip() or
                    any(not isinstance(v, str) or len(v) > 500 or any(ord(c) < 32 for c in v)
                        for v in profile.values())):
                raise TemplateStoreError("Invalid issuer profile")
    for kind, selected in document["defaults"].items():
        if not isinstance(selected, str) or (selected and selected not in by_kind[kind]):
            raise TemplateStoreError("Invalid default template reference")
    return document


def _safe_root(root):
    path = Path(root)
    if not path.is_absolute() or not path.is_dir():
        raise TemplateStoreError("An existing absolute company ledger directory is required")
    for part in (path, *path.parents):
        if part.is_symlink() or (getattr(part.lstat(), 'st_file_attributes', 0) &
                                  getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
            raise TemplateStoreError("Reparse points forbidden in template path")
    return path


class StandaloneAccountingTemplateStore:
    def __init__(self, explicit_company_ledger_directory):
        self.root = _safe_root(explicit_company_ledger_directory)
        self.path = self.root / "invoice-templates.json"
        self.previous = self.root / "invoice-templates.previous.json"

    def _check_kind(self, kind):
        if kind not in _KINDS:
            raise TemplateStoreError("Unknown invoice template kind")

    def _read(self):
        _safe_root(self.root)
        if self.path.is_symlink() or (self.path.exists() and
            getattr(self.path.lstat(), 'st_file_attributes', 0) &
            getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
            raise TemplateStoreError("Linked template file refused")
        if not self.path.exists():
            return {"version": 1, "templates": [], "defaults": {}}
        if self.path.stat().st_size > _MAX_BYTES:
            raise TemplateStoreError("Template library too large")
        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise TemplateStoreError("Template library is damaged") from exc
        return validate_library_document(obj)

    def _persist(self, obj):
        _safe_root(self.root)
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > _MAX_BYTES:
            raise TemplateStoreError("Template library too large")
        validate_library_document(obj)
        if self.previous.is_symlink() or self.path.is_symlink():
            raise TemplateStoreError("Linked template library refused")
        def write_atomic(target, content):
            fd, name = tempfile.mkstemp(prefix=".madar-template-", suffix=".tmp", dir=str(self.root))
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, target)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        if self.path.exists():
            write_atomic(self.previous, self.path.read_bytes())
        write_atomic(self.path, payload)

    def list(self, kind):
        self._check_kind(kind)
        with _LOCK:
            obj = self._read()
            return {"templates": [dict(t) for t in obj["templates"] if t.get("kind") == kind],
                    "defaultId": obj["defaults"].get(kind, "")}

    def save(self, kind, title, data, template_id=""):
        self._check_kind(kind)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100 or any(ord(c) < 32 for c in title):
            raise TemplateStoreError("Invalid template title")
        if not isinstance(data, dict) or len(json.dumps(data, ensure_ascii=False)) > 600000:
            raise TemplateStoreError("Invalid template payload")
        if kind == "entry":
            if data.get("format") != "madar-invoice-lines-v1" or data.get("currency") not in {"RIAL", "TOMAN"} or not isinstance(data.get("lines"), list):
                raise TemplateStoreError("Invalid entry template")
        elif kind == "print" and data.get("format") != "madar-print-layout-v1":
            raise TemplateStoreError("Invalid print template")
        elif kind == "issuer":
            permitted = {"legalName", "nationalId", "economicCode", "postalCode", "phone", "address"}
            if (data.get("format") != "madar-issuer-profile-v1" or
                not isinstance(data.get("profile"), dict) or
                set(data["profile"]) - permitted or
                not isinstance(data["profile"].get("legalName"), str) or
                not data["profile"]["legalName"].strip() or
                any(not isinstance(v, str) or len(v)>500 or any(ord(c)<32 for c in v)
                    for v in data["profile"].values())):
                raise TemplateStoreError("Invalid issuer profile")
        if template_id and (not isinstance(template_id, str) or not _ID.fullmatch(template_id)):
            raise TemplateStoreError("Invalid template identifier")
        with _LOCK:
            obj = self._read()
            if len(obj["templates"]) >= 100 and not template_id:
                raise TemplateStoreError("Template count limit reached")
            found = next((t for t in obj["templates"] if t.get("id") == template_id and t.get("kind") == kind), None)
            if template_id and found is None:
                raise TemplateStoreError("Template not found in current company")
            ident = template_id or uuid.uuid4().hex
            record = {"id": ident, "kind": kind, "title": title.strip(), "data": data}
            if found is None:
                obj["templates"].append(record)
            else:
                obj["templates"][obj["templates"].index(found)] = record
            if not obj["defaults"].get(kind):
                obj["defaults"][kind] = ident
            self._persist(obj)
            return record

    def delete(self, kind, template_id):
        self._check_kind(kind)
        with _LOCK:
            obj = self._read()
            target = [t for t in obj["templates"] if t.get("kind") == kind and t.get("id") == template_id]
            if not target:
                raise TemplateStoreError("Template not found")
            obj["templates"] = [t for t in obj["templates"] if t not in target]
            if obj["defaults"].get(kind) == template_id:
                obj["defaults"][kind] = next((t["id"] for t in obj["templates"] if t.get("kind") == kind), "")
            self._persist(obj)
            return self.list(kind)

    def set_default(self, kind, template_id):
        self._check_kind(kind)
        with _LOCK:
            obj = self._read()
            if not any(t.get("kind") == kind and t.get("id") == template_id for t in obj["templates"]):
                raise TemplateStoreError("Template not found")
            obj["defaults"][kind] = template_id
            self._persist(obj)
            return self.list(kind)

    def duplicate(self, kind, template_id):
        self._check_kind(kind)
        with _LOCK:
            obj = self._read()
            item = next((t for t in obj["templates"] if t.get("kind") == kind and t.get("id") == template_id), None)
            if not item:
                raise TemplateStoreError("Template not found")
            return self.save(kind, item["title"] + " (کپی)", item["data"])
