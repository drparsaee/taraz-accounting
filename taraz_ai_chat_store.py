"""TARAZ private, versioned and user-scoped AI chat history.

Never discovers an ambient company, invokes a provider, stores raw credentials,
or modifies accounting. Message bodies and proposal payloads are protected
with Windows DPAPI for the current Windows principal. Cross-machine restores
therefore require a separately approved key-recovery design.
"""
from __future__ import annotations

from contextlib import closing
import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import unicodedata

from taraz_order_store import _path_ok

SCHEMA_VERSION = 1
# AI message bodies are DPAPI-encrypted and cannot be indexed as plaintext.
# Bound the work of one search; callers must check searchTruncated when the
# requested page could not be proven complete within these limits.
_SEARCH_MAX_CONVERSATIONS = 2048
_SEARCH_MAX_DECRYPTIONS = 8192
# A preexisting V1 database has no secondary message/tenant indexes. Even a
# limited SELECT could scan many out-of-scope rows, so cap SQLite VM work too.
_SEARCH_SQL_PROGRESS_STEPS = 1000
_SEARCH_MAX_SQL_PROGRESS_CALLS = 50000
_ID = re.compile(r"^[a-f0-9]{32}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_SECRET = re.compile(
    r"(?i)(?:(?:api[_ -]?key|access[_ -]?token|password|secret|رمز|گذرواژه)\s*[:=]\s*\S+"
    r"|bearer\s+[A-Za-z0-9._~+/=-]+|-----BEGIN [A-Z ]+-----)"
)


class AiChatError(ValueError):
    pass


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data if data else b"\0")
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))), buf


def _protect(data: str, scope: str) -> bytes:
    """DPAPI encryption; no plaintext fallback on other platforms."""
    if os.name != "nt":
        raise RuntimeError("Private AI chat encryption requires Windows DPAPI")
    raw = data.encode("utf-8")
    inp, buf = _blob(raw)
    entropy, entbuf = _blob(("TARAZ-AI-CHAT-V1:" + scope).encode("utf-8"))
    out = _BLOB()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(ctypes.byref(inp), None, ctypes.byref(entropy),
                                     None, None, 0x01, ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), "Windows DPAPI encryption failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _unprotect(payload: bytes, scope: str) -> str:
    if os.name != "nt":
        raise RuntimeError("Private AI chat decryption requires Windows DPAPI")
    inp, buf = _blob(payload)
    entropy, entbuf = _blob(("TARAZ-AI-CHAT-V1:" + scope).encode("utf-8"))
    out = _BLOB()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(ctypes.byref(inp), None, ctypes.byref(entropy),
                                       None, None, 0x01, ctypes.byref(out)):
        raise AiChatError("Chat encryption key is not available for this Windows user")
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _valid_text(text: str, *, limit=4000) -> str:
    if not isinstance(text, str) or not text.strip() or len(text) > limit or any(
        ord(c) < 32 and c not in "\n\t" for c in text
    ):
        raise AiChatError("Invalid bounded AI chat content")
    if _SECRET.search(text):
        raise AiChatError("Credentials cannot be stored in AI chat history")
    return text.strip()


def _verified_context_refs(refs):
    """Persist only scoped reference identifiers; never arbitrary client metadata.

    Message references are stored as JSON in V1 rather than as DPAPI blobs.
    Reject unexpected fields instead of accidentally writing names, contact
    details, tokens or whole source payloads to a plaintext column.
    """
    if refs is None:
        return []
    if type(refs) is not list or len(refs) > 32:
        raise AiChatError("Invalid bounded AI context references")
    allowed_kinds = {"invoice", "proforma", "order", "item", "party", "madar-task"}
    verified = []
    for reference in refs:
        if (type(reference) is not dict or
                not {"kind", "id"} <= set(reference) or
                not set(reference) <= {"kind", "id", "sourceRevision"} or
                type(reference["kind"]) is not str or
                reference["kind"] not in allowed_kinds):
            raise AiChatError("Unverified AI context reference")
        ident = reference["id"]
        if (type(ident) is not str or not 1 <= len(ident) <= 96 or
                any(unicodedata.category(c) in ("Cc", "Cf") for c in ident)):
            raise AiChatError("Unverified AI context reference")
        revision = reference.get("sourceRevision")
        if (revision is not None and
                (type(revision) is not int or not 0 <= revision < (1 << 63))):
            raise AiChatError("Unverified AI source revision")
        verified.append({"kind": reference["kind"], "id": ident,
                         "sourceRevision": revision})
    return verified


def _canonical_request(payload: dict) -> bytes:
    """Hash the exact validated client payload, not an accounting snapshot."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


class TarazAiChatStore:
    def __init__(self, company_root, *, tenant_id, actor):
        self.root = Path(company_root)
        _path_ok(self.root)
        if not self.root.is_dir() or not self.root.is_absolute():
            raise AiChatError("An existing explicit company directory is required")
        if not isinstance(tenant_id, str) or not tenant_id or len(tenant_id) > 96:
            raise AiChatError("Invalid company scope")
        if not isinstance(actor, str) or not _ACTOR.fullmatch(actor):
            raise AiChatError("Invalid authenticated user")
        self.tenant = tenant_id
        self.actor = actor
        self.scope = tenant_id + ":" + actor
        self.path = self.root / "taraz-ai-chat.sqlite3"

    def _request_identity(self, client_request_id, payload):
        if client_request_id is None:
            return None
        if type(client_request_id) is not str or not _ID.fullmatch(client_request_id):
            raise AiChatError("Invalid cryptographic clientRequestId")
        if (type(payload) is not dict or payload.get("action") not in ("create", "send") or
                (payload["action"] == "create" and set(payload) != {"action", "title"}) or
                (payload["action"] == "send" and
                 set(payload) != {"action", "conversationId", "text"})):
            raise AiChatError("Invalid idempotent request payload")
        try:
            digest = hashlib.sha256(_canonical_request(payload)).hexdigest()
        except (TypeError, ValueError) as exc:
            raise AiChatError("Invalid idempotent request payload") from exc
        key = hashlib.sha256(_canonical_request({
            "domain": "taraz-ai-chat-request-v1", "tenant": self.tenant,
            "actor": self.actor, "clientRequestId": client_request_id,
        })).hexdigest()
        return key, digest

    def _cached(self, db, identity):
        if identity is None:
            return None
        key, expected = identity
        row = db.execute("SELECT digest,response_json FROM action_keys WHERE idempotency_key=?",
                         (key,)).fetchone()
        if row is None:
            return None
        if row["digest"] != expected:
            raise AiChatError("clientRequestId was already used for a different request")
        try:
            result = json.loads(_unprotect(base64.b64decode(
                row["response_json"], validate=True), self.scope))
        except (ValueError, TypeError) as exc:
            raise AiChatError("Invalid encrypted idempotency receipt") from exc
        if type(result) is not dict:
            raise AiChatError("Invalid cached request result")
        # A deleted conversation must not become readable through an old key.
        self._owner(db, result.get("conversationId"))
        return result

    def replay(self, client_request_id, payload):
        identity = self._request_identity(client_request_id, payload)
        if identity is None:
            return None
        db = self._connect()
        if db is None:
            return None
        try:
            return self._cached(db, identity)
        finally:
            db.close()

    def _cache_response(self, db, identity, response):
        if identity is None:
            return
        key, digest = identity
        encrypted = _protect(json.dumps(response, sort_keys=True,
                          ensure_ascii=False, separators=(",", ":")), self.scope)
        db.execute("INSERT INTO action_keys (idempotency_key,digest,response_json) VALUES(?,?,?)",
                   (key, digest, base64.b64encode(encrypted).decode("ascii")))

    def _connect(self, write=False):
        _path_ok(self.root)
        if self.path.is_symlink():
            raise AiChatError("Linked AI store refused")
        if not write and not self.path.is_file():
            return None
        connection = sqlite3.connect(
            str(self.path) if write else self.path.as_uri() + "?mode=ro",
            timeout=8, isolation_level=None, uri=not write)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=8000")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION) or (version == 0 and not write):
            connection.close()
            raise AiChatError("Unsupported or incomplete AI history schema")
        if write:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("""CREATE TABLE IF NOT EXISTS conversations(
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
                    title TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, schema_version INTEGER NOT NULL)""")
                connection.execute("""CREATE TABLE IF NOT EXISTS messages(
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL, content_cipher BLOB NOT NULL,
                    timestamp TEXT NOT NULL, revision INTEGER NOT NULL,
                    processing_status TEXT NOT NULL, references_json TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id))""")
                connection.execute("""CREATE TABLE IF NOT EXISTS executions(
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL, payload_cipher BLOB NOT NULL,
                    source_revision INTEGER, approval_status TEXT NOT NULL,
                    execution_status TEXT NOT NULL, error_code TEXT,
                    audit_timestamp TEXT NOT NULL, result_reference TEXT)""")
                connection.execute("""CREATE TABLE IF NOT EXISTS provider_requests(
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    provider_type TEXT NOT NULL, model_id TEXT NOT NULL,
                    request_status TEXT NOT NULL, latency_ms INTEGER,
                    token_usage INTEGER, error_code TEXT, consent_reference TEXT,
                    created_at TEXT NOT NULL)""")
                connection.execute("""CREATE TABLE IF NOT EXISTS context_links(
                    conversation_id TEXT NOT NULL, entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL, source_revision INTEGER,
                    PRIMARY KEY(conversation_id,entity_type,entity_id))""")
                connection.execute("""CREATE TABLE IF NOT EXISTS action_keys(
                    idempotency_key TEXT PRIMARY KEY, digest TEXT NOT NULL,
                    response_json TEXT NOT NULL)""")
                connection.execute("PRAGMA user_version=1")
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                connection.close()
                raise
        return connection

    def _owner(self, db, conversation_id):
        if not isinstance(conversation_id, str) or not _ID.fullmatch(conversation_id):
            raise AiChatError("Invalid conversation identifier")
        row = db.execute(
            "SELECT * FROM conversations WHERE id=? AND tenant_id=? AND user_id=? AND status='active'",
            (conversation_id, self.tenant, self.actor)).fetchone()
        if row is None:
            raise PermissionError("Conversation does not exist in current user/company scope")
        return row

    def list(self, query="", limit=80, *, offset=0):
        """Search the current actor's history in stable newest-first order.

        `offset` counts matching conversations, not raw conversation rows.
        Searches stop at fixed per-request scan/decryption budgets and signal
        incomplete results rather than presenting partial matches as complete.
        No plaintext message index, schema migration, or write is performed.
        """
        if (not isinstance(query, str) or len(query) > 150 or
                type(limit) is not int or not 1 <= limit <= 100 or
                type(offset) is not int or not 0 <= offset <= 100000):
            raise AiChatError("Invalid chat search")
        db = self._connect()
        if db is None:
            return {"schemaVersion": SCHEMA_VERSION, "conversations": [],
                    "hasMore": False, "nextOffset": None, "searchTruncated": False}
        try:
            # A read transaction keeps the candidate order and messages on
            # one SQLite snapshot if another session appends while we search.
            db.execute("BEGIN")
            needle = query.strip().casefold()
            scope = (self.tenant, self.actor)
            if not needle:
                rows = db.execute("""SELECT id,title,created_at,updated_at
                    FROM conversations
                    WHERE tenant_id=? AND user_id=? AND status='active'
                    ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?""",
                    (*scope, limit + 1, offset)).fetchall()
                entries = [dict(row) for row in rows[:limit]]
                has_more = len(rows) > limit
                return {"schemaVersion": SCHEMA_VERSION, "conversations": entries,
                        "hasMore": has_more,
                        "nextOffset": offset + len(entries) if has_more else None,
                        "searchTruncated": False}

            entries = []
            matches = 0
            decryptions = 0
            truncated = False
            has_more = False
            sql_calls = 0
            sql_interrupted = False

            def bound_sql_work():
                nonlocal sql_calls, sql_interrupted
                sql_calls += 1
                if sql_calls >= _SEARCH_MAX_SQL_PROGRESS_CALLS:
                    sql_interrupted = True
                    return 1
                return 0

            db.set_progress_handler(bound_sql_work, _SEARCH_SQL_PROGRESS_STEPS)
            try:
                # LIMIT bounds the SQLite result set; the progress handler
                # also bounds scanning/sorting work on legacy unindexed DBs.
                rows = db.execute("""SELECT id,title,created_at,updated_at
                    FROM conversations
                    WHERE tenant_id=? AND user_id=? AND status='active'
                    ORDER BY updated_at DESC,id DESC LIMIT ?""",
                    (*scope, _SEARCH_MAX_CONVERSATIONS + 1))
                for position, row in enumerate(rows):
                    if position == _SEARCH_MAX_CONVERSATIONS:
                        truncated = True
                        break
                    item = dict(row)
                    found = needle in item["title"].casefold()
                    if not found:
                        # Iterate every message, including those older than
                        # 200, without retaining decrypted text or a full
                        # message list in memory.
                        remaining = _SEARCH_MAX_DECRYPTIONS - decryptions
                        messages = db.execute("""SELECT content_cipher FROM messages
                            WHERE conversation_id=? ORDER BY rowid DESC LIMIT ?""",
                            (item["id"], remaining + 1))
                        for message_position, message in enumerate(messages):
                            if message_position == remaining:
                                truncated = True
                                break
                            decryptions += 1
                            if needle in _unprotect(bytes(message[0]), self.scope).casefold():
                                found = True
                                break
                        if truncated:
                            break
                    if found:
                        if matches >= offset + limit:
                            has_more = True
                            break
                        if matches >= offset:
                            entries.append(item)
                        matches += 1
            except sqlite3.OperationalError:
                if not sql_interrupted:
                    raise
                truncated = True
            finally:
                db.set_progress_handler(None, 0)
            return {"schemaVersion": SCHEMA_VERSION, "conversations": entries,
                    "hasMore": None if truncated else has_more,
                    "nextOffset": offset + len(entries) if has_more else None,
                    "searchTruncated": truncated}
        finally:
            db.close()

    def read(self, conversation_id):
        db = self._connect()
        if db is None:
            raise PermissionError("Conversation not found")
        try:
            row = self._owner(db, conversation_id)
            messages = [{
                "id": r["id"], "role": r["role"],
                "content": _unprotect(bytes(r["content_cipher"]), self.scope),
                "timestamp": r["timestamp"], "revision": r["revision"],
                "status": r["processing_status"],
                "references": json.loads(r["references_json"])
            } for r in db.execute(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY revision",
                (conversation_id,))]
            execs = [{
                "id": r["id"], "messageId": r["message_id"], "tool": r["tool_name"],
                "sourceRevision": r["source_revision"], "approval": r["approval_status"],
                "status": r["execution_status"], "errorCode": r["error_code"],
                "proposal": json.loads(_unprotect(bytes(r["payload_cipher"]), self.scope))
            } for r in db.execute(
                "SELECT * FROM executions WHERE conversation_id=? ORDER BY audit_timestamp",
                (conversation_id,))]
            return {"conversation": dict(row), "messages": messages, "executions": execs,
                    "schemaVersion": SCHEMA_VERSION}
        finally:
            db.close()

    def create(self, title="گفتگوی جدید", *, client_request_id=None):
        identity = self._request_identity(client_request_id, {"action": "create", "title": title})
        title = _valid_text(title, limit=120)
        db = self._connect(write=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            cached = self._cached(db, identity)
            if cached is not None:
                db.execute("COMMIT")
                return cached
            now, cid = _now(), secrets.token_hex(16)
            db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?)",
                       (cid, self.tenant, self.actor, title, "active", now, now, SCHEMA_VERSION))
            response = {"conversationId": cid, "title": title}
            self._cache_response(db, identity, response)
            db.execute("COMMIT")
            return response
        except BaseException:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def append(self, conversation_id, text, reply, *, proposal=None,
               source_revision=None, refs=None, client_request_id=None,
               request_payload=None, response_base=None):
        identity = self._request_identity(client_request_id, request_payload)
        text = _valid_text(text)
        reply = _valid_text(reply)
        refs = _verified_context_refs(refs)
        if proposal is not None and not isinstance(proposal, dict):
            raise AiChatError("Invalid proposed action")
        if response_base is not None and type(response_base) is not dict:
            raise AiChatError("Invalid AI chat response")
        db = self._connect(write=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            cached = self._cached(db, identity)
            if cached is not None:
                db.execute("COMMIT")
                return cached
            self._owner(db, conversation_id)
            revision = db.execute("SELECT COALESCE(MAX(revision),0) FROM messages WHERE conversation_id=?",
                                  (conversation_id,)).fetchone()[0]
            now = _now()
            message_id, assistant_id = secrets.token_hex(16), secrets.token_hex(16)
            db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)",
                       (message_id, conversation_id, "user", _protect(text, self.scope),
                        now, revision + 1, "saved", json.dumps(refs)))
            db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)",
                       (assistant_id, conversation_id, "assistant", _protect(reply, self.scope),
                        now, revision + 2, "completed", json.dumps(refs)))
            action_id = None
            if proposal is not None:
                action_id = secrets.token_hex(16)
                db.execute("INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (action_id, conversation_id, message_id, "invoice.draft.preview",
                            _protect(json.dumps(proposal, ensure_ascii=False), self.scope),
                            source_revision, "pending", "proposed", None, now, None))
            for reference in refs:
                db.execute("""INSERT OR REPLACE INTO context_links
                    (conversation_id,entity_type,entity_id,source_revision)
                    VALUES(?,?,?,?)""",
                    (conversation_id, reference["kind"], reference["id"],
                     reference["sourceRevision"]))
            db.execute("INSERT INTO provider_requests VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (secrets.token_hex(16), conversation_id, "local", "rules-v1",
                        "no_model_called", 0, 0, None, None, now))
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            response = {**(response_base or {}),
                        "messageId": message_id, "assistantMessageId": assistant_id,
                        "actionId": action_id, "sourceRevision": source_revision}
            self._cache_response(db, identity, response)
            db.execute("COMMIT")
            return response
        except BaseException:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def pending_action(self, conversation_id, action_id):
        if not isinstance(action_id, str) or not _ID.fullmatch(action_id):
            raise AiChatError("Invalid action identifier")
        db = self._connect()
        if db is None:
            raise PermissionError("No AI history")
        try:
            self._owner(db, conversation_id)
            row = db.execute(
                "SELECT * FROM executions WHERE id=? AND conversation_id=?",
                (action_id, conversation_id)).fetchone()
            if row is None:
                raise PermissionError("Action not in current conversation")
            return {**dict(row), "proposal": json.loads(
                _unprotect(bytes(row["payload_cipher"]), self.scope))}
        finally:
            db.close()

    def update_action(self, conversation_id, action_id, *, approval, status, result=None):
        if approval not in ("approved", "rejected") or status not in (
            "executed", "rejected", "uncertain"):
            raise AiChatError("Invalid action transition")
        db = self._connect(write=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            self._owner(db, conversation_id)
            row = db.execute(
                "SELECT approval_status,execution_status FROM executions WHERE id=? AND conversation_id=?",
                (action_id, conversation_id)).fetchone()
            if row is None or row["approval_status"] != "pending":
                raise AiChatError("Action already handled; reconcile rather than retry")
            db.execute("""UPDATE executions SET approval_status=?, execution_status=?,
                       result_reference=?,audit_timestamp=? WHERE id=? AND conversation_id=?""",
                       (approval, status, result, _now(), action_id, conversation_id))
            db.execute("COMMIT")
            return {"actionId": action_id, "approval": approval, "status": status}
        except BaseException:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def complete_uncertain_action(self, conversation_id, action_id, *, result):
        """Complete only an action already claimed before an accounting write."""
        db = self._connect(write=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            self._owner(db, conversation_id)
            row = db.execute(
                "SELECT approval_status,execution_status FROM executions WHERE id=? AND conversation_id=?",
                (action_id, conversation_id)).fetchone()
            if not row or (row["approval_status"], row["execution_status"]) != (
                "approved", "uncertain"):
                raise AiChatError("Not a recoverable claimed action")
            db.execute("UPDATE executions SET execution_status='executed',result_reference=?,audit_timestamp=? WHERE id=?",
                       (result, _now(), action_id))
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def delete(self, conversation_id):
        db = self._connect(write=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            self._owner(db, conversation_id)
            unresolved = db.execute(
                """SELECT 1 FROM executions WHERE conversation_id=?
                   AND approval_status='approved' AND execution_status='uncertain'
                   LIMIT 1""", (conversation_id,)).fetchone()
            if unresolved:
                raise AiChatError("Uncertain financial draft must be reconciled before chat deletion")
            # User-visible messages can be removed, but any executed financial
            # proposal must retain its protected source details and receipt.
            # Deleting them made a future audit/restore impossible.
            db.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
            db.execute("""UPDATE executions SET
                payload_cipher=CASE WHEN execution_status='executed'
                  THEN payload_cipher ELSE ? END,
                result_reference=CASE WHEN execution_status='executed'
                  THEN result_reference ELSE NULL END
                WHERE conversation_id=?""",
                (_protect("{}", self.scope), conversation_id))
            db.execute("UPDATE conversations SET status='deleted',title='[deleted]',updated_at=? WHERE id=?",
                       (_now(), conversation_id))
            db.execute("COMMIT")
            return {"deleted": True}
        except BaseException:
            if db.in_transaction: db.execute("ROLLBACK")
            raise
        finally:
            db.close()
