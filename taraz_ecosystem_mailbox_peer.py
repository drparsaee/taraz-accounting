"""Manually triggered, authenticated Taraz->Madar counterparties mailbox peer.

No background loop, financial posting, model calls, SQL writes, or additional
listener. The official TarazCounterpartiesDirectory is the ONLY source of
party information. Idempotent replies are sealed with current-user Windows
DPAPI in an immutable, sharded, private archive inside the registered company
book. A small process-local hot cache is only an optimization: every lookup
rechecks the durable encrypted record. Archive receipts are NEVER deleted on
ACK, retry or capacity pressure because an ACK may have been lost in transit.
No customer names, bearer or financial information is persisted in plaintext.

The native caller MUST provide a fresh company administrator authorization
predicate, derived from a real registered company session. Browser booleans do
not authorize directory reads or network transport.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections import OrderedDict
from copy import deepcopy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import threading

from taraz_ai_chat_store import _protect, _unprotect
from taraz_ecosystem_credentials import _private_acl, _create_secure_file, _regular
from taraz_ecosystem_mailbox_consent import NativeMailboxBatchConsent
from taraz_ecosystem_counterparties import TarazCounterpartiesDirectory
from taraz_ecosystem_client import MadarPinnedClient, EcosystemConnectionError


_HEX32 = re.compile(r"[a-f0-9]{32}\Z")
_PEER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_TEMP = re.compile(r"\.pending-([a-f0-9]{32})\.([a-f0-9]{32})\Z")
_ALLOWED_KINDS = frozenset({"customer", "vendor", "both"})
_THREAD_LOCK = threading.RLock()
_MAX_HOT_RESULTS = 64
_RECORD_DIR = ".taraz-mailbox-replies-v1"
_ARCHIVE_DIR = "archive"
_SHARD = re.compile(r"[a-f0-9]{2}\Z")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_MIB = 1024 * 1024
_MIN_FREE_BYTES = 64 * _MIB
_WARN_FREE_BYTES = 256 * _MIB
_MAX_REPLY_WRITE_BYTES = 40 * 1024


class MailboxPeerDenied(PermissionError):
    """Unregistered company, invalid request, or missing current admin scope."""


def _volume_capacity(path: Path, *, required_bytes=0) -> dict:
    """Fail closed on unknown space, provide an explicit non-evicting warning.

    A reserve is retained after the next immutable write. This is NOT an
    arbitrary maximum count or an excuse to delete historical receipts.
    """
    if (type(required_bytes) is not int or required_bytes < 0 or
            os.name != "nt"):
        raise MailboxPeerDenied("Windows archive capacity preflight required")
    try:
        volume = shutil.disk_usage(path)
        total, used, free = volume.total, volume.used, volume.free
        if (not all(type(n) is int and n >= 0 for n in (total, used, free))
                or used + free > total or total <= 0):
            raise ValueError("Invalid disk usage")
    except (OSError, ValueError, TypeError, OverflowError):
        raise MailboxPeerDenied("Mailbox archive volume capacity unverified") from None
    reserve = _MIN_FREE_BYTES + required_bytes
    return {"freeBytes": free, "requiredReserveBytes": reserve,
            "warnBelowBytes": max(_WARN_FREE_BYTES, total // 10),
            "warning": free < max(_WARN_FREE_BYTES, total // 10),
            "canWrite": free >= reserve}


def _require_archive_space(path: Path, estimated=0) -> dict:
    status = _volume_capacity(path, required_bytes=estimated)
    if not status["canWrite"]:
        raise MailboxPeerDenied("Mailbox archive disk reserve exhausted")
    return status


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _seal_scope(file: Path) -> str:
    return "TARAZ-COUNTERPARTIES-REPLY-V1:" + str(file.resolve()).casefold()


def _safe_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise MailboxPeerDenied("Private archive directory unavailable") from None
    if (path.is_symlink() or not stat.S_ISDIR(info.st_mode) or
            getattr(info, "st_file_attributes", 0) & _REPARSE):
        raise MailboxPeerDenied("Unsafe mailbox archive directory")


def _root_member(entry: Path) -> None:
    if entry.name == _ARCHIVE_DIR:
        _safe_directory(entry)
    elif (entry.name == ".lock" or
          re.fullmatch(r"[a-f0-9]{32}\.dpapi\Z", entry.name) or
          _TEMP.fullmatch(entry.name)):
        _regular(entry)
    else:
        raise MailboxPeerDenied("Unknown mailbox receipt file")


@contextmanager
def _private_lock(root: Path):
    if os.name != "nt" or root.is_symlink():
        raise MailboxPeerDenied("Private Windows company receipt root required")
    with _THREAD_LOCK:
        if not root.exists():
            root.mkdir(mode=0o700)
        if not root.is_dir():
            raise MailboxPeerDenied("Invalid mailbox private directory")
        # Never touch an unrelated file's ACL in a preexisting directory.
        entries = list(root.iterdir())
        for entry in entries:
            _root_member(entry)
        for entry in entries:
            _private_acl(entry)
        # Protect already verified children BEFORE the directory so removing
        # inherited ACEs does not leave a valid receipt temporarily unreadable.
        _private_acl(root)
        lock = root / ".lock"
        if not lock.exists() and entries:
            raise MailboxPeerDenied("Missing existing mailbox receipt lock")
        if not lock.exists():
            try:
                _create_secure_file(lock, b"0")
            except FileExistsError:
                pass
        _regular(lock)
        import msvcrt
        with lock.open("r+b") as handle:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                entries = list(root.iterdir())
                for entry in entries:
                    _root_member(entry)
                    _private_acl(entry)
                # Prior-version staged files are deliberately retained.
                # They have not yet been committed to an authoritative reply,
                # and deleting one could silently change retry semantics.
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class _SealedReplyCache:
    """Immutable DPAPI archive plus bounded process-local hot result cache.

    Every request ID is deterministically mapped to a two-character hash
    shard. A committed archive file is the authority even after ACK or
    process restart. No archive receipt or legacy receipt is ever deleted.
    The old 1000-file root is read/migrated lazily with full DPAPI re-sealing
    (the original Windows DPAPI entropy is bound to the absolute file path).
    """

    def __init__(self, book: Path):
        if not book.is_absolute():
            raise MailboxPeerDenied("Registered company book required")
        _safe_directory(book)
        self.root = book / _RECORD_DIR
        self.archive = self.root / _ARCHIVE_DIR
        self._hot = OrderedDict()

    @staticmethod
    def _archive_shard(request_id: str) -> str:
        return hashlib.sha256(bytes.fromhex(request_id)).hexdigest()[:2]

    def _archive_file(self, request_id):
        return self.archive / self._archive_shard(request_id) / (request_id + ".dpapi")

    def _directory(self, request_id):
        """Only root-lock holder may create and inspect archive directories."""
        if not os.path.lexists(self.archive):
            self.archive.mkdir(mode=0o700)
        _safe_directory(self.archive)
        for member in self.archive.iterdir():
            if not _SHARD.fullmatch(member.name):
                raise MailboxPeerDenied("Unknown mailbox archive member")
            _safe_directory(member)
        _private_acl(self.archive)
        shard = self.archive / self._archive_shard(request_id)
        if not os.path.lexists(shard):
            shard.mkdir(mode=0o700)
        _safe_directory(shard)
        for entry in shard.iterdir():
            if not (re.fullmatch(r"[a-f0-9]{32}\.dpapi\Z", entry.name)
                    or _TEMP.fullmatch(entry.name)):
                raise MailboxPeerDenied("Unknown mailbox shard member")
            # All ciphertext is private to this Windows principal.
            _regular(entry)
            if entry.name.endswith(".dpapi") and (
                    self._archive_shard(entry.name[:-6]) != shard.name):
                raise MailboxPeerDenied("Misplaced archive receipt")
        _private_acl(shard)
        return shard

    def _read(self, file, envelope_hash, *, sealed_for=None):
        _regular(file)
        _private_acl(file)
        try:
            raw = file.read_bytes()
            if not 1 <= len(raw) <= 32768:
                raise ValueError("Invalid encrypted receipt size")
            key = (str(file), envelope_hash,
                   str(sealed_for) if sealed_for is not None else "")
            raw_hash = hashlib.sha256(raw).digest()
            cached = self._hot.get(key)
            if cached is not None and cached[0] == raw_hash:
                self._hot.move_to_end(key)
                return deepcopy(cached[1])
            clear = _unprotect(raw, _seal_scope(sealed_for or file))
            data = json.loads(clear)
            if (type(data) is not dict or set(data) != {"envelopeSha256", "reply"}
                    or data["envelopeSha256"] != envelope_hash
                    or type(data["reply"]) is not dict):
                raise ValueError("Conflicting immutable mailbox request")
            self._hot[key] = (raw_hash, deepcopy(data["reply"]))
            self._hot.move_to_end(key)
            while len(self._hot) > _MAX_HOT_RESULTS:
                self._hot.popitem(last=False)
            return deepcopy(data["reply"])
        except (OSError, ValueError, UnicodeError, RuntimeError):
            raise MailboxPeerDenied("Corrupt or conflicting private reply archive") from None

    @staticmethod
    def _stages(folder, request_id):
        prefix = ".pending-" + request_id + "."
        stages = [item for item in folder.iterdir()
                  if item.name.startswith(prefix)]
        if len(stages) > 1:
            raise MailboxPeerDenied("Ambiguous interrupted reply stage")
        for stage in stages:
            if not _TEMP.fullmatch(stage.name):
                raise MailboxPeerDenied("Malformed interrupted reply stage")
            _regular(stage)
        return stages

    def _stage_or_publish(self, target, request_id, envelope_hash, result):
        """Publish a sealed snapshot atomically; recover stages after crash.

        Never discard an interrupted stage: it may be the only snapshot of a
        previously read ledger. Its DPAPI entropy is the final target path so
        a restart can validate and promote it without reading finance again.
        """
        existing = self._stages(target.parent, request_id)
        if existing:
            staged = self._read(existing[0], envelope_hash, sealed_for=target)
            if result is not None and _canonical(staged) != _canonical(result):
                raise MailboxPeerDenied("Conflicting staged reply")
            if os.path.lexists(target):
                committed = self._read(target, envelope_hash)
                if _canonical(committed) != _canonical(staged):
                    raise MailboxPeerDenied("Conflicting committed and staged reply")
                return committed
            os.rename(existing[0], target)
            return self._read(target, envelope_hash)
        if os.path.lexists(target):
            committed = self._read(target, envelope_hash)
            if result is not None and _canonical(committed) != _canonical(result):
                raise MailboxPeerDenied("Conflicting committed reply")
            return committed
        if result is None:
            return None
        if type(result) is not dict:
            raise MailboxPeerDenied("Invalid reply to archive")
        clear = _canonical({"envelopeSha256": envelope_hash, "reply": result})
        if len(clear) > 28000:
            raise MailboxPeerDenied("Unbounded reply snapshot")
        encrypted = _protect(clear.decode("utf-8"), _seal_scope(target))
        if not 1 <= len(encrypted) <= 32768:
            raise MailboxPeerDenied("Oversized private reply archive")
        _require_archive_space(target.parent, len(encrypted) + 4096)
        temporary = target.parent / (
            ".pending-" + request_id + "." + secrets.token_hex(16))
        _create_secure_file(temporary, encrypted)
        # The verified ciphertext is durable before the publishing rename.
        _private_acl(temporary)
        os.rename(temporary, target)
        return self._read(target, envelope_hash)

    def get_or_create(self, envelope, reader):
        if type(envelope) is not dict or not callable(reader):
            raise MailboxPeerDenied("Invalid immutable request")
        request_id = envelope.get("requestId")
        if type(request_id) is not str or not _HEX32.fullmatch(request_id):
            raise MailboxPeerDenied("Invalid immutable request ID")
        try:
            envelope_hash = hashlib.sha256(_canonical(envelope)).hexdigest()
        except (ValueError, TypeError, OverflowError):
            raise MailboxPeerDenied("Invalid immutable request") from None
        with _private_lock(self.root):
            self._directory(request_id)
            target = self._archive_file(request_id)
            legacy = self.root / (request_id + ".dpapi")
            old_stages = self._stages(self.root, request_id)
            # Recover previous-version pre-rename stages with their ORIGINAL
            # target-bound DPAPI scope. No old ciphertext is ever overwritten.
            if old_stages and not os.path.lexists(legacy):
                self._read(old_stages[0], envelope_hash, sealed_for=legacy)
                os.rename(old_stages[0], legacy)
            old = self._read(legacy, envelope_hash) if os.path.lexists(legacy) else None
            if old_stages and os.path.lexists(legacy):
                # A leftover legacy stage can never silently override a
                # committed value even when the ledger has since changed.
                stage_path = old_stages[0]
                if os.path.lexists(stage_path):
                    staged = self._read(stage_path, envelope_hash, sealed_for=legacy)
                    if _canonical(staged) != _canonical(old):
                        raise MailboxPeerDenied("Conflicting legacy reply stage")
            if os.path.lexists(target):
                archived = self._read(target, envelope_hash)
                if old is not None and _canonical(old) != _canonical(archived):
                    raise MailboxPeerDenied("Conflicting legacy and archived reply")
                # Also validate any staged archive ciphertext for this ID.
                self._stage_or_publish(target, request_id, envelope_hash, archived)
                return archived
            if old is not None:
                # An old hot reply is copied to a NEW secure archive location
                # and re-sealed for that path, then verified. Legacy file stays
                # intact because no ACK-safe deletion protocol exists.
                return self._stage_or_publish(
                    target, request_id, envelope_hash, old)
            # Always recover pending archived stage BEFORE calling reader.
            resumed = self._stage_or_publish(target, request_id, envelope_hash, None)
            if resumed is not None:
                return resumed
            # Never read the ledger for a brand-new request if there is
            # insufficient durable space for the immutable reply it creates.
            _require_archive_space(target.parent, _MAX_REPLY_WRITE_BYTES)
            # First and only read for this immutable request. A crash after
            # stage creation is recovered on restart rather than re-reading.
            return self._stage_or_publish(
                target, request_id, envelope_hash, reader())

    def capacity_status(self):
        """Read-only warning fields for the native caller; no cleanup occurs."""
        return _volume_capacity(self.root if self.root.exists() else self.root.parent,
                                required_bytes=_MAX_REPLY_WRITE_BYTES)


class TarazMailboxPeer:
    """One manual batch of requests from the exact paired Madar workspace."""

    def __init__(self, client: MadarPinnedClient, *, workspace_id, company_id,
                 company_book, authorizer, native_consent):
        if (type(client) is not MadarPinnedClient or
                type(workspace_id) is not str or not _HEX32.fullmatch(workspace_id) or
                type(company_id) is not str or not _HEX32.fullmatch(company_id) or
                not callable(authorizer) or
                type(native_consent) is not NativeMailboxBatchConsent):
            raise ValueError("Verified native peer, company and consent gate required")
        self.client = client
        self.workspace_id = workspace_id
        self.company_id = company_id
        self.book = Path(company_book)
        self.authorizer = authorizer
        self.native_consent = native_consent
        self.cache = _SealedReplyCache(self.book)

    def _authorized(self, operation=None, party_id=None, *, company_id=None):
        # The Taraz directory invokes this callback with its independently
        # registered company_id. Never ignore a foreign company claim.
        if company_id is not None and company_id != self.company_id:
            raise MailboxPeerDenied("Cross-company directory request refused")
        try:
            allowed = self.authorizer(company_id=self.company_id,
                                      operation=operation, party_id=party_id)
        except Exception:
            raise MailboxPeerDenied("Company session no longer authorized") from None
        if allowed is not True:
            raise MailboxPeerDenied("Company session no longer authorized")
        return True

    def _directory(self):
        return TarazCounterpartiesDirectory(self.book, company_id=self.company_id,
                                            authorizer=self._authorized)

    def _result(self, envelope):
        operation = envelope["operation"]
        args = envelope["parameters"]
        if operation == "Counterparties.Search":
            if (type(args) is not dict or set(args) !=
                    {"query", "kind", "limit", "cursor"} or
                    type(args["limit"]) is not int or not 1 <= args["limit"] <= 20):
                raise MailboxPeerDenied("Unsupported bounded company search")
            page = self._directory().search(query=args["query"], kind=args["kind"],
                                            limit=args["limit"], cursor=args["cursor"])
            result = {"parties": page["counterparties"],
                      "hasMore": page["hasMore"], "nextCursor": page["nextCursor"]}
        elif operation == "Counterparties.Get":
            if type(args) is not dict or set(args) != {"partyId"}:
                raise MailboxPeerDenied("Unsupported company party lookup")
            party = self._directory().get(args["partyId"])
            result = {"party": None if party is None else party["counterparty"]}
        else:
            raise MailboxPeerDenied("Unsupported company operation")
        if len(_canonical(result)) > 28000:
            raise MailboxPeerDenied("Bounded company projection exceeds transport")
        return result

    def run_once(self, *, limit=5):
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("Invalid manual mailbox batch size")
        self._authorized("search")
        token = self.client.vault.require_token(
            workspace_id=self.workspace_id, peer_id=self.client.peer_id,
            cert_sha256=self.client.cert_sha256)
        install = self.client.vault.installation_id()
        scope = {"workspaceId": self.workspace_id,
                 "installationId": install, "companyId": self.company_id}
        status, incoming = self.client._request(
            "POST", "/integrations/v1/mailbox/poll",
            payload={**scope, "limit": limit}, token=token)
        if (status != 200 or type(incoming) is not dict or
                set(incoming) != {"version", "requests"} or
                incoming["version"] != 1 or type(incoming["requests"]) is not list or
                len(incoming["requests"]) > limit):
            raise EcosystemConnectionError("Invalid authenticated mailbox queue")
        # Validate the ENTIRE authenticated poll before showing the OS prompt
        # or reading a single party. The exact entire batch is shown to the
        # operator, and a short-lived ticket binds all envelope bytes and IDs.
        for envelope in incoming["requests"]:
            self._authorized("search")
            if (type(envelope) is not dict or set(envelope) != {
                    "workspaceId", "installationId", "companyId", "requestId",
                    "requestedActor", "requestedGrant", "operation", "parameters"}
                    or any(envelope.get(key) != value for key, value in scope.items())
                    or envelope.get("requestedGrant") != "counterparties.read"
                    or type(envelope.get("requestId")) is not str
                    or not _HEX32.fullmatch(envelope["requestId"])):
                raise MailboxPeerDenied("Cross-company or malformed peer envelope")
        consent = (self.native_consent.approve(incoming["requests"], scope=scope)
                   if incoming["requests"] else None)
        completed = 0
        for envelope in incoming["requests"]:
            self._authorized("search")
            consent.check(envelope, scope=scope, consume=True)
            # Keep a sealed snapshot before any network ACK/reply. A retry after
            # the ledger changes uses exactly this same original reply.
            result = self.cache.get_or_create(envelope, lambda e=envelope: self._result(e))
            secret = self.client.vault.require_token(
                workspace_id=self.workspace_id, peer_id=self.client.peer_id,
                cert_sha256=self.client.cert_sha256)
            if not hmac.compare_digest(secret, token):
                raise MailboxPeerDenied("Paired token rotated during batch")
            self._authorized("search")
            consent.check(envelope, scope=scope)
            signature = hmac.new(token.encode("ascii"),
                b"MADAR.MAILBOX.REPLY.v1\x00" + _canonical({
                    "request": envelope, "result": result}), hashlib.sha256).hexdigest()
            response_status, response = self.client._request(
                "POST", "/integrations/v1/mailbox/reply", payload={
                    **scope, "requestId": envelope["requestId"],
                    "result": result, "signature": signature}, token=token)
            if (response_status != 200 or set(response) !=
                    {"version", "requestId", "status"} or
                    response["version"] != 1 or response["requestId"] != envelope["requestId"]
                    or response["status"] != "completed"):
                raise EcosystemConnectionError("Peer reply not durably acknowledged")
            completed += 1
        return {"source": "TARAZ", "companyId": self.company_id,
                "workspaceId": self.workspace_id, "received": len(incoming["requests"]),
                "completed": completed, "readOnly": True,
                "financialEventCreated": False,
                "archiveCapacity": self.cache.capacity_status()}


__all__ = ["MailboxPeerDenied", "TarazMailboxPeer"]
