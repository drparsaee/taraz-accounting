"""Host-owned binary attachments for Madar Desk; no UI or LAN side effects.

The host supplies the authenticated actor and current authoritative project/card
registries on EVERY call. Only caller-selected storage roots are ever accessed.
"""

from __future__ import annotations

import base64
import binascii
from contextlib import closing, contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
import zlib


SCHEMA_VERSION = 1
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BASE64 = 4 * ((MAX_UPLOAD_BYTES + 2) // 3)
MAX_IMAGE_PREVIEW_BYTES = 256 * 1024
MAX_TEXT_PREVIEW_BYTES = 64 * 1024
MAX_CARD_ATTACHMENTS = 100
MAX_BACKUP_MANIFEST_BYTES = 8 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)\Z")
_BIDI = {chr(code) for code in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))}


class AttachmentError(ValueError):
    """Malformed data, damaged attachment, unsupported file, or unsafe path."""


def _id(value, name="identifier"):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise AttachmentError(f"Invalid {name}")
    return value


def _stamp(value):
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        raise AttachmentError("Expected timezone-aware ISO timestamp")
    try:
        if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
            raise AttachmentError("Timezone missing")
    except ValueError as exc:
        raise AttachmentError("Invalid timestamp") from exc
    return value


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _filename(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 180
            or value != value.strip() or value.endswith(".") or value.startswith(".")
            or any(ord(c) < 32 or ord(c) == 127 or c in '\\/:*?"<>|' or c in _BIDI for c in value)):
        raise AttachmentError("Invalid attachment filename")
    stem, dot, suffix = value.rpartition(".")
    if not dot or not stem or suffix.lower() not in {"png", "jpg", "jpeg", "pdf", "txt"}:
        raise AttachmentError("Unsupported filename extension")
    if stem.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                          *(f"LPT{i}" for i in range(1, 10))}:
        raise AttachmentError("Reserved Windows filename")
    return value, suffix.lower()


def _mime(raw, ext):
    if not raw:
        raise AttachmentError("Empty attachment")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        position, found_data, ended, count = 8, False, False, 0
        while position + 12 <= len(raw):
            length = int.from_bytes(raw[position:position + 4], "big")
            kind = raw[position + 4:position + 8]
            final = position + 12 + length
            if final > len(raw) or count >= 1024 or not re.fullmatch(rb"[A-Za-z]{4}", kind):
                raise AttachmentError("Invalid PNG chunk")
            chunk = raw[position + 8:position + 8 + length]
            crc = int.from_bytes(raw[position + 8 + length:final], "big")
            if zlib.crc32(kind + chunk) != crc:
                raise AttachmentError("Invalid PNG CRC")
            if count == 0:
                if kind != b"IHDR" or length != 13:
                    raise AttachmentError("Invalid PNG header")
                width, height = int.from_bytes(chunk[0:4], "big"), int.from_bytes(chunk[4:8], "big")
                if not (0 < width <= 16384 and 0 < height <= 16384):
                    raise AttachmentError("Invalid PNG dimensions")
            if kind == b"IDAT":
                found_data = True
            if kind == b"IEND":
                if length or final != len(raw) or not found_data:
                    raise AttachmentError("Invalid PNG terminator")
                ended = True
                break
            position, count = final, count + 1
        if not ended:
            raise AttachmentError("PNG missing final chunk")
        mime, permitted = "image/png", {"png"}
    elif raw[:3] == b"\xff\xd8\xff":
        if not raw.endswith(b"\xff\xd9"):
            raise AttachmentError("Invalid JPEG terminator")
        mime, permitted = "image/jpeg", {"jpg", "jpeg"}
    elif raw.startswith((b"%PDF-1.", b"%PDF-2.")):
        if b"%%EOF" not in raw[-1024:]:
            raise AttachmentError("Invalid PDF terminator")
        mime, permitted = "application/pdf", {"pdf"}
    else:
        try:
            decoded = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise AttachmentError("Unsupported binary file format") from exc
        if any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in decoded):
            raise AttachmentError("Invalid text control characters")
        lowered = decoded.lstrip("\ufeff \n\r\t").lower()
        if (lowered.startswith(("<!doctype", "<html", "<svg", "<?xml", "<script"))
                or re.search(r"<\s*[/!?]?\s*[A-Za-z]", decoded)):
            raise AttachmentError("Active HTML/SVG content is unsupported")
        mime, permitted = "text/plain", {"txt"}
    if ext not in permitted:
        raise AttachmentError("Filename extension does not match detected content")
    return mime


def _binary(base64_data):
    if not isinstance(base64_data, str) or not base64_data or len(base64_data) > MAX_REQUEST_BASE64:
        raise AttachmentError("Base64 payload too large or invalid")
    try:
        decoded = base64.b64decode(base64_data.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise AttachmentError("Invalid Base64 attachment") from exc
    if not decoded or len(decoded) > MAX_UPLOAD_BYTES or base64.b64encode(decoded).decode("ascii") != base64_data:
        raise AttachmentError("Invalid or oversized Base64 attachment")
    return decoded


def _safe_path(path):
    """Reject all existing symlinks / Windows junctions along an absolute path."""
    path = Path(path)
    if not path.is_absolute():
        raise AttachmentError("Storage paths must be absolute")
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise AttachmentError("Symlink or junction in storage path")
    return path


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _context(actor, accounts, cards, projects, card_id, *, write=False):
    _id(actor, "authenticated actor")
    _id(card_id, "cardId")
    users = accounts if isinstance(accounts, dict) else {a["username"]: a for a in accounts}
    task_map = cards if isinstance(cards, dict) else {a["id"]: a for a in cards}
    project_map = projects if isinstance(projects, dict) else {p["id"]: p for p in projects}
    account = users.get(actor)
    if not isinstance(account, dict) or account.get("username") != actor or account.get("role") not in {"admin", "editor", "viewer"}:
        raise PermissionError("Unknown authenticated account")
    card = task_map.get(card_id)
    if not isinstance(card, dict) or card.get("id") != card_id:
        raise AttachmentError("Card not found")
    project_id = card.get("projectId")
    if not isinstance(project_id, str) or project_id not in project_map:
        raise AttachmentError("Card project not found")
    scope = account.get("projects")
    if account["role"] != "admin" and (scope is not None and (not isinstance(scope, list) or project_id not in scope)):
        raise PermissionError("Project access denied")
    if write and account["role"] == "viewer":
        raise PermissionError("Viewer cannot modify attachments")
    return account, project_id


def _public(row):
    return {"id": row["id"], "cardId": row["card_id"], "projectId": row["project_id"],
            "filename": row["filename"], "mime": row["mime"], "size": row["size"],
            "sha256": row["digest"], "uploadedBy": row["uploaded_by"],
            "createdAt": row["created_at"], "deletedAt": row["deleted_at"]}


class AttachmentStore:
    """SQLite metadata and SHA-256 blob storage under a trusted host root."""

    def __init__(self, root):
        self.root = _safe_path(root)
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        _safe_path(self.root)
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(exist_ok=True)
        _safe_path(self.blobs)
        self.database = self.root / "attachments.sqlite3"
        self._guard_database()
        preexisting_database = self.database.exists()
        if preexisting_database:
            # Detect unknown legacy/future databases before beginning a write
            # transaction. SQLite's read-only handle is explicitly closed even
            # when rejecting the schema, which matters for Windows cleanup.
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)) as inspection:
                existing_version = inspection.execute("PRAGMA user_version").fetchone()[0]
            if existing_version == 0:
                raise AttachmentError("Unversioned existing database cannot be initialized as attachment storage")
            if existing_version != SCHEMA_VERSION:
                raise AttachmentError("Unsupported attachments database version")
        with self._connection(write=True) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise AttachmentError("Unsupported attachments database version")
            if preexisting_database and version == 0:
                raise AttachmentError("Unversioned existing database cannot be initialized as attachment storage")
            for statement in ("""CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY, card_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    filename TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL,
                    digest TEXT NOT NULL, uploaded_by TEXT NOT NULL, created_at TEXT NOT NULL,
                    deleted_at TEXT, deleted_by TEXT
                )""", "CREATE INDEX IF NOT EXISTS attachments_card ON attachments(card_id,deleted_at)",
                """CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE NOT NULL,
                    action TEXT NOT NULL, attachment_id TEXT NOT NULL, card_id TEXT NOT NULL,
                    project_id TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL
                )""", """CREATE TABLE IF NOT EXISTS receipts (
                    request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    actor TEXT NOT NULL, project_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL, result_json TEXT NOT NULL
                )"""):
                conn.execute(statement)
            if version == 0:
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _guard_database(self):
        for suffix in ("", "-journal", "-wal", "-shm"):
            _safe_path(Path(str(self.database) + suffix))

    @contextmanager
    def _connection(self, *, write=False):
        self._guard_database()
        conn = sqlite3.connect(str(self.database), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    def _blob_path(self, digest):
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise AttachmentError("Invalid blob checksum")
        return self.blobs / digest[:2] / digest

    def _load_blob(self, digest, expected_size):
        path = self._blob_path(digest)
        _safe_path(path)
        if not path.is_file():
            raise AttachmentError("Referenced attachment blob missing")
        with path.open("rb") as stream:
            raw = stream.read(MAX_UPLOAD_BYTES + 1)
            if stream.read(1):
                raise AttachmentError("Attachment blob too large")
        if len(raw) != expected_size or _sha(raw) != digest:
            raise AttachmentError("Attachment blob checksum mismatch")
        return raw

    def _publish_blob(self, raw, digest):
        path = self._blob_path(digest)
        folder = path.parent
        _safe_path(folder)
        folder.mkdir(exist_ok=True)
        _safe_path(path)
        if path.exists():
            self._load_blob(digest, len(raw))
            return
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=folder, prefix=".blob-", delete=False) as stream:
                temp = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            _safe_path(temp)
            _safe_path(path)
            if path.exists():
                self._load_blob(digest, len(raw))
            else:
                os.replace(temp, path)
                temp = None
        finally:
            if temp is not None and temp.exists():
                temp.unlink()

    @staticmethod
    def _fetch(conn, attachment_id):
        _id(attachment_id, "attachmentId")
        row = conn.execute("SELECT * FROM attachments WHERE id=?", (attachment_id,)).fetchone()
        if row is None:
            raise AttachmentError("Attachment not found")
        return row

    @staticmethod
    def _check_receipt(conn, request_id, fingerprint, actor, project_id):
        row = conn.execute("SELECT * FROM receipts WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint or row["actor"] != actor or row["project_id"] != project_id:
            raise AttachmentError("Idempotency key reused for a different operation")
        return json.loads(row["result_json"])

    @staticmethod
    def _record(conn, *, request_id, fingerprint, actor, project_id, card_id, attachment_id, action, now, result):
        conn.execute("INSERT INTO audit(request_id,action,attachment_id,card_id,project_id,actor,at) VALUES (?,?,?,?,?,?,?)",
                     (request_id, action, attachment_id, card_id, project_id, actor, now))
        conn.execute("INSERT INTO receipts(request_id,fingerprint,actor,project_id,attachment_id,result_json) VALUES (?,?,?,?,?,?)",
                     (request_id, fingerprint, actor, project_id, attachment_id, _canonical(result).decode("utf8")))

    def upload(self, *, actor, accounts, cards, projects, card_id, filename, content_base64, request_id, now):
        """Create authorized card metadata and publish deduplicated blob."""
        account, project_id = _context(actor, accounts, cards, projects, card_id, write=True)
        _id(request_id, "requestId")
        _stamp(now)
        filename, ext = _filename(filename)
        raw = _binary(content_base64)
        mime = _mime(raw, ext)
        digest = _sha(raw)
        fingerprint = _sha(_canonical([actor, "upload", project_id, card_id, filename, digest]))
        attachment_id = "att-" + _sha(request_id.encode("utf8"))[:32]
        with self._lock, self._connection(write=True) as conn:
            previous = self._check_receipt(conn, request_id, fingerprint, actor, project_id)
            if previous is not None:
                return previous
            active = conn.execute(
                "SELECT COUNT(*) FROM attachments WHERE card_id=? AND project_id=? AND deleted_at IS NULL",
                (card_id, project_id)).fetchone()[0]
            if active >= MAX_CARD_ATTACHMENTS:
                raise AttachmentError("Too many active attachments on this card")
            self._publish_blob(raw, digest)
            conn.execute("INSERT INTO attachments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (attachment_id, card_id, project_id, filename, mime, len(raw), digest,
                          account["username"], now, None, None))
            result = _public(self._fetch(conn, attachment_id))
            self._record(conn, request_id=request_id, fingerprint=fingerprint,
                         actor=actor, project_id=project_id, card_id=card_id,
                         attachment_id=attachment_id, action="upload", now=now, result=result)
            return result

    def list_card(self, *, actor, accounts, cards, projects, card_id, include_deleted=False):
        account, project_id = _context(actor, accounts, cards, projects, card_id)
        if type(include_deleted) is not bool:
            raise AttachmentError("Invalid include_deleted flag")
        if include_deleted and account["role"] != "admin":
            raise PermissionError("Only admin can list deleted attachment metadata")
        with self._lock, self._connection() as conn:
            query = "SELECT * FROM attachments WHERE card_id=? AND project_id=?"
            if not include_deleted:
                query += " AND deleted_at IS NULL"
            query += " ORDER BY created_at,id"
            return [_public(r) for r in conn.execute(query, (card_id, project_id)).fetchall()]

    def _authorized_row(self, conn, *, attachment_id, actor, accounts, cards, projects, write=False):
        row = self._fetch(conn, attachment_id)
        account, project_id = _context(actor, accounts, cards, projects, row["card_id"], write=write)
        if row["project_id"] != project_id:
            raise PermissionError("Attachment belongs to a different project")
        if row["deleted_at"] is not None:
            raise AttachmentError("Attachment has been deleted")
        return row, account

    def read(self, *, attachment_id, actor, accounts, cards, projects):
        """Authorized full-content download; host MUST use attachment + nosniff."""
        with self._lock, self._connection() as conn:
            row, _ = self._authorized_row(conn, attachment_id=attachment_id, actor=actor,
                                          accounts=accounts, cards=cards, projects=projects)
            raw = self._load_blob(row["digest"], row["size"])
            return {"attachment": _public(row), "contentBase64": base64.b64encode(raw).decode("ascii"),
                    "contentType": row["mime"], "contentDisposition": "attachment",
                    "xContentTypeOptions": "nosniff", "cacheControl": "no-store"}

    def preview(self, *, attachment_id, actor, accounts, cards, projects):
        """Bounded passive previews; PDF is intentionally never rendered inline."""
        with self._lock, self._connection() as conn:
            row, _ = self._authorized_row(conn, attachment_id=attachment_id, actor=actor,
                                          accounts=accounts, cards=cards, projects=projects)
            mime = row["mime"]
            result = {"attachment": _public(row), "available": False, "kind": "none",
                      "truncated": False, "content": None}
            if mime == "application/pdf":
                self._load_blob(row["digest"], row["size"])
                result["kind"] = "pdf-download-only"
                return result
            raw = self._load_blob(row["digest"], row["size"])
            if mime == "text/plain":
                result.update(available=True, kind="plain-text", truncated=len(raw) > MAX_TEXT_PREVIEW_BYTES,
                              content=raw[:MAX_TEXT_PREVIEW_BYTES].decode("utf-8", errors="ignore"))
            elif mime in {"image/png", "image/jpeg"}:
                result["kind"] = "image"
                if len(raw) <= MAX_IMAGE_PREVIEW_BYTES:
                    result.update(available=True, content=base64.b64encode(raw).decode("ascii"))
            return result

    def delete(self, *, attachment_id, actor, accounts, cards, projects, request_id, now):
        _id(request_id, "requestId")
        _stamp(now)
        with self._lock, self._connection(write=True) as conn:
            row = self._fetch(conn, attachment_id)
            account, project_id = _context(actor, accounts, cards, projects, row["card_id"], write=True)
            if row["project_id"] != project_id:
                raise PermissionError("Attachment belongs to a different project")
            if account["role"] != "admin" and row["uploaded_by"] != actor:
                raise PermissionError("Only uploader or admin may delete an attachment")
            fingerprint = _sha(_canonical([actor, "delete", attachment_id, row["project_id"]]))
            previous = self._check_receipt(conn, request_id, fingerprint, actor, row["project_id"])
            if previous is not None:
                return previous
            if row["deleted_at"] is not None:
                raise AttachmentError("Attachment has already been deleted")
            conn.execute("UPDATE attachments SET deleted_at=?, deleted_by=? WHERE id=? AND deleted_at IS NULL",
                         (now, actor, attachment_id))
            result = {"id": attachment_id, "deleted": True, "deletedAt": now}
            self._record(conn, request_id=request_id, fingerprint=fingerprint,
                         actor=actor, project_id=row["project_id"], card_id=row["card_id"],
                         attachment_id=attachment_id, action="delete", now=now, result=result)
            return result

    def audit_log(self, *, actor, accounts, cards, projects, project_id):
        _id(project_id, "projectId")
        users = accounts if isinstance(accounts, dict) else {u["username"]: u for u in accounts}
        who = users.get(actor)
        if not isinstance(who, dict) or who.get("username") != actor or who.get("role") != "admin":
            raise PermissionError("Audit requires administrator")
        valid_projects = projects if isinstance(projects, dict) else {p["id"]: p for p in projects}
        if project_id not in valid_projects:
            raise AttachmentError("Project not found")
        with self._lock, self._connection() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT seq,request_id,action,attachment_id,card_id,project_id,actor,at FROM audit WHERE project_id=? ORDER BY seq",
                (project_id,)).fetchall()]

    def _manifest_rows(self, conn):
        rows = conn.execute("SELECT DISTINCT digest,size FROM attachments ORDER BY digest").fetchall()
        return [{"sha256": row["digest"], "size": row["size"]} for row in rows]

    def backup_to(self, destination, *, actor, accounts):
        """Export consistent SQLite snapshot+blobs to a NEW sibling directory.

        ``manifest.json`` is written last, and the complete staging directory
        is published by atomic rename. Must not target source or its parents.
        """
        users = accounts if isinstance(accounts, dict) else {u["username"]: u for u in accounts}
        if not isinstance(users.get(actor), dict) or users[actor].get("username") != actor or users[actor].get("role") != "admin":
            raise PermissionError("Only admin may export full attachment backup")
        dest = _safe_path(destination)
        if _inside(dest, self.root) or _inside(self.root, dest) or dest.exists():
            raise AttachmentError("Backup destination must be new and disjoint from storage")
        parent = _safe_path(dest.parent)
        if not parent.is_dir():
            raise AttachmentError("Backup destination parent must exist")
        stage = Path(tempfile.mkdtemp(prefix=".attachments-backup-", dir=parent))
        try:
            with self._lock, self._connection() as conn:
                rows = self._manifest_rows(conn)
                backup_db = stage / "attachments.sqlite3"
                target = sqlite3.connect(str(backup_db))
                try:
                    conn.backup(target)
                finally:
                    target.close()
                for item in rows:
                    raw = self._load_blob(item["sha256"], item["size"])
                    folder = stage / "blobs" / item["sha256"][:2]
                    folder.mkdir(parents=True, exist_ok=True)
                    with (folder / item["sha256"]).open("xb") as dest_blob:
                        dest_blob.write(raw)
                        dest_blob.flush()
                        os.fsync(dest_blob.fileno())
            manifest = {"schemaVersion": SCHEMA_VERSION, "databaseSha256": _sha(backup_db.read_bytes()),
                        "blobs": rows}
            with (stage / "manifest.json").open("x", encoding="utf8") as target:
                json.dump(manifest, target, sort_keys=True, ensure_ascii=False)
                target.flush()
                os.fsync(target.fileno())
            _safe_path(dest)
            os.replace(stage, dest)
            return manifest
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    @classmethod
    def verify_backup(cls, source):
        """Verify manifest, snapshot DB, all referenced blob lengths and digests."""
        root = _safe_path(source)
        manifest_path = _safe_path(root / "manifest.json")
        backup_db = _safe_path(root / "attachments.sqlite3")
        if not manifest_path.is_file() or not backup_db.is_file() or manifest_path.stat().st_size > MAX_BACKUP_MANIFEST_BYTES:
            raise AttachmentError("Backup missing or manifest oversized")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf8"))
        except (ValueError, UnicodeError) as exc:
            raise AttachmentError("Invalid backup manifest") from exc
        if (not isinstance(manifest, dict) or set(manifest) != {"schemaVersion", "databaseSha256", "blobs"}
                or manifest["schemaVersion"] != SCHEMA_VERSION
                or not isinstance(manifest["databaseSha256"], str)
                or not _SHA.fullmatch(manifest["databaseSha256"])
                or not isinstance(manifest["blobs"], list)):
            raise AttachmentError("Invalid backup manifest schema")
        if _sha(backup_db.read_bytes()) != manifest["databaseSha256"]:
            raise AttachmentError("Backup database checksum mismatch")
        uri = backup_db.as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True)
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise AttachmentError("Backup SQLite integrity failed")
            if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise AttachmentError("Unsupported backup schema")
            expected = [{"sha256": row[0], "size": row[1]} for row in db.execute(
                "SELECT DISTINCT digest,size FROM attachments ORDER BY digest").fetchall()]
        finally:
            db.close()
        if manifest["blobs"] != expected:
            raise AttachmentError("Backup manifest omits or changes blob inventory")
        for row in expected:
            digest, size = row["sha256"], row["size"]
            if not isinstance(digest, str) or not _SHA.fullmatch(digest) or type(size) is not int or not 1 <= size <= MAX_UPLOAD_BYTES:
                raise AttachmentError("Invalid backup blob record")
            path = _safe_path(root / "blobs" / digest[:2] / digest)
            if not path.is_file() or path.stat().st_size != size:
                raise AttachmentError("Backup blob missing or unexpected size")
            with path.open("rb") as stream:
                if _sha(stream.read(MAX_UPLOAD_BYTES + 1)) != digest:
                    raise AttachmentError("Backup blob checksum mismatch")
        return manifest

    @classmethod
    def restore_backup(cls, source, destination):
        """Restore only to a NEW empty root after complete backup verification."""
        source_root = _safe_path(source)
        dest = _safe_path(destination)
        if dest.exists() or _inside(dest, source_root) or _inside(source_root, dest) or not dest.parent.is_dir():
            raise AttachmentError("Restore requires a new disjoint destination root")
        manifest = cls.verify_backup(source_root)
        stage = Path(tempfile.mkdtemp(prefix=".attachments-restore-", dir=dest.parent))
        try:
            shutil.copyfile(source_root / "attachments.sqlite3", stage / "attachments.sqlite3")
            for row in manifest["blobs"]:
                digest = row["sha256"]
                directory = stage / "blobs" / digest[:2]
                directory.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_root / "blobs" / digest[:2] / digest, directory / digest)
            _safe_path(dest)
            os.replace(stage, dest)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return cls(dest)


__all__ = ["AttachmentStore", "AttachmentError", "SCHEMA_VERSION", "MAX_UPLOAD_BYTES",
           "MAX_REQUEST_BASE64", "MAX_IMAGE_PREVIEW_BYTES", "MAX_TEXT_PREVIEW_BYTES"]
