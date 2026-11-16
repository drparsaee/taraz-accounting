"""Operator-owned invoice templates kept alongside ONE explicitly selected ledger.

No company discovery, no financial events. Writes are atomic and the prior
snapshot is saved for independent template recovery. Never interprets content
as code or as a filesystem path.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import unicodedata
import uuid

_LOCK = threading.RLock()
_KINDS = {"entry", "print", "issuer", "brand"}
_ID = re.compile(r"[a-f0-9]{32}\Z")
_MAX_BYTES = 2 * 1024 * 1024
_PRINT_IDS = frozenset({"title", "seller", "buyer", "number", "date", "note"})
_PRINT_FONTS = frozenset({"Vazirmatn", "Tahoma", "Arial"})
_PRINT_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
_PRINT_LOGO = re.compile(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+\Z")
_BRAND_FIELDS = frozenset({"displayName", "header", "contact", "logo", "printTemplateId"})
_PRINT_COLUMNS = frozenset({"rowNumber", "description", "itemId", "accountId",
                            "quantity", "unit", "price", "total"})
_PRINT_CUSTOM_COLUMN_ID = re.compile(r"custom_[1-4]\Z")
_PRINT_CUSTOM_SOURCES = frozenset({"description", "itemId", "accountId",
                                   "quantity", "unit", "price", "total"})
_JS_WHITESPACE = ("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"
                  "\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff")


class TemplateStoreError(ValueError):
    pass


def _bounded_number(value, minimum, maximum):
    return (type(value) in (int, float) and math.isfinite(value) and
            minimum <= value <= maximum)


def _js_utf16_length(value):
    """Mirror JS String.length for UTF-16 browser-provided print labels."""
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _js_trim(value):
    """Mirror JS String.trim, including U+FEFF but not Python-only C0 chars."""
    return value.strip(_JS_WHITESPACE)


def _validate_print_design(data):
    """Match the native React print designer's complete editable v1 contract."""
    if (not isinstance(data, dict) or data.get("format") != "madar-print-layout-v1" or
            type(data.get("version")) is not int or data["version"] != 1 or
            not isinstance(data.get("title"), str) or
            not _js_trim(data["title"]) or _js_utf16_length(data["title"]) > 100 or
            data.get("page") not in ("A4", "A5") or
            data.get("orientation") not in ("portrait", "landscape") or
            not _bounded_number(data.get("margin"), 3, 30) or
            not isinstance(data.get("font"), str) or
            data["font"] not in _PRINT_FONTS or
            not isinstance(data.get("color"), str) or
            not _PRINT_COLOR.fullmatch(data["color"]) or
            not isinstance(data.get("signature"), str) or
            _js_utf16_length(data["signature"]) > 100 or
            not isinstance(data.get("logo"), str) or
            len(data["logo"]) > 300000 or
            (data["logo"] and not _PRINT_LOGO.fullmatch(data["logo"]))):
        raise TemplateStoreError("Invalid print-layout template")
    fields = data.get("fields")
    if not isinstance(fields, list) or len(fields) != len(_PRINT_IDS):
        raise TemplateStoreError("Invalid print-layout fields")
    field_ids = set()
    for field in fields:
        if (not isinstance(field, dict) or
                not isinstance(field.get("id"), str) or
                field["id"] not in _PRINT_IDS or field["id"] in field_ids or
                type(field.get("visible")) is not bool or
                not isinstance(field.get("label"), str) or
                _js_utf16_length(field["label"]) > 60 or
                not _bounded_number(field.get("x"), 0, 297) or
                not _bounded_number(field.get("y"), 0, 297) or
                not _bounded_number(field.get("size"), 7, 22)):
            raise TemplateStoreError("Invalid print-layout field")
        field_ids.add(field["id"])
    if field_ids != _PRINT_IDS:
        raise TemplateStoreError("Invalid print-layout fields")
    table = data.get("table")
    if (not isinstance(table, dict) or
            not _bounded_number(table.get("y"), 30, 250) or
            any(type(table.get(key)) is not bool for key in
                ("showQuantity", "showPrice", "showTotal")) or
            not _bounded_number(data.get("totalsY"), 75, 290)):
        raise TemplateStoreError("Invalid print-layout table")
    # Match the native Canvas renderer's one-actual-row minimum on every
    # paper size and orientation. A forged template must not save a table
    # entirely outside A5 merely because the old static range allows y<=250.
    row_height = table.get("rowHeight", 8.5)
    if not _bounded_number(row_height, 6, 14):
        raise TemplateStoreError("Invalid print-layout row height")
    page_width, page_height = {"A4": (210, 297), "A5": (148, 210)}[data["page"]]
    if data["orientation"] == "landscape":
        page_width, page_height = page_height, page_width
    limit = min(250, math.floor(page_height - data["margin"] - 61 - row_height))
    if table["y"] > limit:
        raise TemplateStoreError("Print-layout table exceeds the selected page")
    custom = table.get("customColumns", [])
    if not isinstance(custom, list) or len(custom) > 4:
        raise TemplateStoreError("Invalid user-defined print columns")
    custom_ids = set()
    for definition in custom:
        if (type(definition) is not dict or
                set(definition) != {"id", "label", "source"} or
                type(definition["id"]) is not str or
                not _PRINT_CUSTOM_COLUMN_ID.fullmatch(definition["id"]) or
                definition["id"] in custom_ids or
                type(definition["label"]) is not str or
                not _js_trim(definition["label"]) or
                _js_utf16_length(definition["label"]) > 25 or
                type(definition["source"]) is not str or
                definition["source"] not in _PRINT_CUSTOM_SOURCES):
            raise TemplateStoreError("Invalid user-defined print column")
        custom_ids.add(definition["id"])
    for key, maximum in (("companyHeader", 120), ("companySubtitle", 120),
                         ("footerText", 70)):
        value = data.get(key, "")
        if not isinstance(value, str) or _js_utf16_length(value) > maximum:
            raise TemplateStoreError("Invalid company print-layout metadata")
    logo_layout = data.get("logoLayout")
    if logo_layout is not None:
        if (not isinstance(logo_layout, dict) or
                not _bounded_number(logo_layout.get("x"), 0, page_width) or
                not _bounded_number(logo_layout.get("y"), 0, page_height) or
                not _bounded_number(logo_layout.get("width"), 8, 100) or
                not _bounded_number(logo_layout.get("height"), 6, 75) or
                logo_layout["x"] + logo_layout["width"] > page_width or
                logo_layout["y"] + logo_layout["height"] > page_height):
            raise TemplateStoreError("Invalid print-layout logo position")
    columns = table.get("columns")
    if columns is not None:
        if (not isinstance(columns, list) or
                not 1 <= len(columns) <= len(_PRINT_COLUMNS) + len(custom_ids) or
                any(type(key) is not str or key not in _PRINT_COLUMNS | custom_ids for key in columns) or
                len(set(columns)) != len(columns) or "description" not in columns):
            raise TemplateStoreError("Invalid print-layout columns")
    labels = table.get("labels")
    if labels is not None:
        if (not isinstance(labels, dict) or
                any(key not in _PRINT_COLUMNS or not isinstance(value, str) or
                    not _js_trim(value) or _js_utf16_length(value) > 25
                    for key, value in labels.items()) or
                any(not isinstance(labels.get(key), str) or not _js_trim(labels[key])
                    for key in ("description", "quantity", "price", "total"))):
            raise TemplateStoreError("Invalid print-layout column headings")


def _validate_commercial_profile(data):
    """Branding is strictly display-only; never an alternate tax identity."""
    if (type(data) is not dict or set(data) != {"format", "profile"} or
            data.get("format") != "taraz-commercial-invoice-profile-v1" or
            type(data.get("profile")) is not dict or
            set(data["profile"]) != _BRAND_FIELDS):
        raise TemplateStoreError("Invalid commercial invoice profile schema")
    item = data["profile"]
    # The target PDF renderer accepts at most 70 UTF-16 characters in footer.
    # Accepting longer contact text here would save an unusable brand profile.
    for field, maximum in (("displayName", 100), ("header", 120),
                           ("contact", 70)):
        value = item[field]
        if (type(value) is not str or len(value) > maximum or
                (field == "displayName" and not value.strip()) or
                any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise TemplateStoreError("Invalid commercial display field: " + field)
    logo = item["logo"]
    if (type(logo) is not str or len(logo) > 300000 or
            (logo and not _PRINT_LOGO.fullmatch(logo))):
        raise TemplateStoreError("Invalid commercial logo")
    template = item["printTemplateId"]
    if type(template) is not str or (template and not _ID.fullmatch(template)):
        raise TemplateStoreError("Invalid commercial print template reference")


def _brand_name_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).translate(
        str.maketrans({"ي": "ی", "ك": "ک"}))
    return " ".join("".join(char for char in normalized if
        char != "ـ" and unicodedata.category(char) != "Mn").casefold().split())


def validate_library_document(document):
    """Strict enough to reject corrupt/untrusted backup companions before restore."""
    if (not isinstance(document, dict) or set(document) != {"version", "templates", "defaults"} or
            type(document["version"]) is not int or document["version"] != 1 or
            not isinstance(document["templates"], list) or
            len(document["templates"]) > 100 or not isinstance(document["defaults"], dict) or
            set(document["defaults"]) - _KINDS):
        raise TemplateStoreError("Invalid template library structure")
    ids = set()
    by_kind = {kind: set() for kind in _KINDS}
    brands = []
    for template in document["templates"]:
        if (not isinstance(template, dict) or set(template) != {"id", "kind", "title", "data"} or
                not isinstance(template["id"], str) or not _ID.fullmatch(template["id"]) or
                template["id"] in ids or not isinstance(template["kind"], str) or
                template["kind"] not in _KINDS or
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
            _validate_print_design(data)
        elif kind == "issuer":
            profile = data.get("profile")
            if (data.get("format") != "madar-issuer-profile-v1" or
                    not isinstance(profile, dict) or
                    set(profile) - {"legalName", "nationalId", "economicCode", "postalCode", "phone", "address"} or
                    not isinstance(profile.get("legalName"), str) or not profile["legalName"].strip() or
                    any(not isinstance(v, str) or len(v) > 500 or any(ord(c) < 32 for c in v)
                        for v in profile.values())):
                raise TemplateStoreError("Invalid issuer profile")
        elif kind == "brand":
            _validate_commercial_profile(data)
            brands.append(data["profile"])
    if any(profile["printTemplateId"] and
           profile["printTemplateId"] not in by_kind["print"] for profile in brands):
        raise TemplateStoreError("Commercial profile references a missing print template")
    labels = [_brand_name_key(profile["displayName"]) for profile in brands]
    if len(labels) != len(set(labels)):
        raise TemplateStoreError("Duplicate commercial branding within one ledger")
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
        if not isinstance(kind, str) or kind not in _KINDS:
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
        elif kind == "brand":
            _validate_commercial_profile(data)
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
            if kind == "print" and any(
                    t.get("kind") == "brand" and
                    t["data"]["profile"]["printTemplateId"] == template_id
                    for t in obj["templates"]):
                raise TemplateStoreError("A commercial profile uses this print template")
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
