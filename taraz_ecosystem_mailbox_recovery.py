"""Clone-only, current-Windows-user DPAPI backup/restore of immutable receipts.

This module deliberately NEVER backs up or restores the integration credential
vault, peer tokens, grants, revocation state, or a financial ledger. In
particular, restoring historical receipts cannot reactivate a revoked peer.
Restoration only creates a NEW receipt root in an explicitly fresh clone book.
No existing receipt root is overwritten, deleted, or merged.

The encrypted manifest authenticates the snapshot, original path-bound DPAPI
scopes and hashes. Individual receipt ciphertext stays encrypted on disk.
Cross-principal/machine recovery requires separate approved key escrow.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets

from taraz_ai_chat_store import _protect, _unprotect
from taraz_ecosystem_credentials import _create_secure_file, _private_acl, _regular
from taraz_ecosystem_mailbox_peer import (
    _HEX32, _TEMP, _RECORD_DIR, _ARCHIVE_DIR, _SHARD,
    _SealedReplyCache, _canonical, _private_lock, _safe_directory,
    _require_archive_space, MailboxPeerDenied,
)

_BUNDLE_SCOPE = "TARAZ-MAILBOX-SEALED-ARCHIVE-CLONE-BACKUP-V1"
_MANIFEST = "manifest.dpapi"
_BLOB = re.compile(r"r([0-9a-f]{8})\.dpapi\Z")
_MAX_MANIFEST_BYTES = 32 * 1024 * 1024
_MAX_RECORDS = 100000


def _strict_directory(directory):
    directory = Path(directory)
    if not directory.is_absolute():
        raise MailboxPeerDenied("Explicit absolute clone/backup directory required")
    for parent in (directory, *directory.parents):
        _safe_directory(parent)
    return directory


def _decrypt_record(raw, source, *, expected_digest=None):
    if not 1 <= len(raw) <= 32768:
        raise MailboxPeerDenied("Invalid sealed archive record size")
    from taraz_ecosystem_mailbox_peer import _seal_scope
    try:
        clear = _unprotect(raw, _seal_scope(Path(source)))
        value = json.loads(clear)
        if (type(value) is not dict or
                set(value) != {"envelopeSha256", "reply"} or
                type(value["envelopeSha256"]) is not str or
                re.fullmatch("[0-9a-f]{64}", value["envelopeSha256"]) is None or
                type(value["reply"]) is not dict or
                (expected_digest is not None and
                 value["envelopeSha256"] != expected_digest)):
            raise ValueError("Bad authenticated receipt")
        return value
    except (ValueError, RuntimeError, OSError, TypeError, UnicodeError):
        raise MailboxPeerDenied("Invalid or wrong-user sealed archive record") from None


def _existing_records(cache):
    """Caller holds exclusive receipt lock. No staged ciphertext is ignored."""
    if not cache.archive.exists():
        folders = []
    else:
        _safe_directory(cache.archive)
        _private_acl(cache.archive)
        folders = list(cache.archive.iterdir())
    rows = []
    for shard in folders:
        if not _SHARD.fullmatch(shard.name):
            raise MailboxPeerDenied("Unexpected archive backup directory")
        _safe_directory(shard)
        _private_acl(shard)
        for entry in shard.iterdir():
            if _TEMP.fullmatch(entry.name):
                raise MailboxPeerDenied("Interrupted archive stage blocks backup")
            if not re.fullmatch(r"[a-f0-9]{32}\.dpapi\Z", entry.name):
                raise MailboxPeerDenied("Unexpected archive backup file")
            if cache._archive_shard(entry.name[:-6]) != shard.name:
                raise MailboxPeerDenied("Invalid archive sharding")
            rows.append((str(Path(_ARCHIVE_DIR) / shard.name / entry.name), entry))
    for entry in cache.root.iterdir():
        if _TEMP.fullmatch(entry.name):
            raise MailboxPeerDenied("Interrupted legacy stage blocks backup")
        if re.fullmatch(r"[a-f0-9]{32}\.dpapi\Z", entry.name):
            rows.append((entry.name, entry))
        elif entry.name not in (".lock", _ARCHIVE_DIR):
            raise MailboxPeerDenied("Unexpected legacy backup file")
    if len(rows) > _MAX_RECORDS:
        raise MailboxPeerDenied("Backup manifest record count exceeds bounded format")
    ids = set()
    for relative, entry in rows:
        request_id = entry.name[:-6]
        # Legacy and archived copy of one request can coexist. They MUST agree
        # byte-for-byte after DPAPI decryption before the backup is accepted.
        _regular(entry)
        _private_acl(entry)
        ids.add(request_id)
    return sorted(rows, key=lambda pair: pair[0]), ids


def _manifest_from_backup(bundle):
    _strict_directory(bundle)
    _private_acl(bundle)
    entries = list(bundle.iterdir())
    if any(entry.name != _MANIFEST and not _BLOB.fullmatch(entry.name)
           for entry in entries):
        raise MailboxPeerDenied("Unexpected encrypted backup member")
    for entry in entries:
        _regular(entry)
        _private_acl(entry)
    manifest_file = bundle / _MANIFEST
    if not manifest_file.is_file():
        raise MailboxPeerDenied("Backup is not committed")
    try:
        sealed = manifest_file.read_bytes()
        if not 1 <= len(sealed) <= _MAX_MANIFEST_BYTES:
            raise ValueError("Backup manifest size")
        manifest = json.loads(_unprotect(sealed, _BUNDLE_SCOPE))
    except (OSError, RuntimeError, ValueError, UnicodeError):
        raise MailboxPeerDenied("Backup manifest is corrupt or wrong-user") from None
    if (type(manifest) is not dict or
            set(manifest) != {"format", "version", "sourceBook", "records"} or
            manifest["format"] != "taraz-sealed-reply-clone" or
            manifest["version"] != 1 or
            type(manifest["sourceBook"]) is not str or
            not Path(manifest["sourceBook"]).is_absolute() or
            type(manifest["records"]) is not list or
            len(manifest["records"]) > _MAX_RECORDS or
            len(entries) != len(manifest["records"]) + 1):
        raise MailboxPeerDenied("Unsupported or incomplete backup manifest")
    expected_files = {_MANIFEST}
    originals = {}
    request_digests = {}
    for i, item in enumerate(manifest["records"]):
        slot = "r" + format(i, "08x") + ".dpapi"
        if (type(item) is not dict or
                set(item) != {"relative", "sha256", "envelopeSha256"} or
                type(item["relative"]) is not str or
                type(item["sha256"]) is not str or
                type(item["envelopeSha256"]) is not str or
                re.fullmatch("[a-f0-9]{64}", item["sha256"]) is None or
                re.fullmatch("[a-f0-9]{64}", item["envelopeSha256"]) is None):
            raise MailboxPeerDenied("Invalid authenticated backup record")
        parts = Path(item["relative"]).parts
        if (len(parts) == 1 and _HEX32.fullmatch(parts[0][:-6]) and
                parts[0].endswith(".dpapi")):
            pass
        elif (len(parts) == 3 and parts[0] == _ARCHIVE_DIR and
              _SHARD.fullmatch(parts[1]) and
              re.fullmatch(r"[a-f0-9]{32}\.dpapi", parts[2]) and
              _SealedReplyCache._archive_shard(parts[2][:-6]) == parts[1]):
            pass
        else:
            raise MailboxPeerDenied("Invalid backup receipt path")
        if item["relative"] in originals:
            raise MailboxPeerDenied("Duplicate backup receipt path")
        originals[item["relative"]] = item["envelopeSha256"]
        req_id = parts[-1][:-6]
        if (req_id in request_digests and
                request_digests[req_id] != item["envelopeSha256"]):
            raise MailboxPeerDenied("Conflicting legacy and archive snapshots")
        request_digests[req_id] = item["envelopeSha256"]
        expected_files.add(slot)
        source = Path(manifest["sourceBook"]) / _RECORD_DIR / Path(*parts)
        raw = (bundle / slot).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise MailboxPeerDenied("Backup receipt hash mismatch")
        _decrypt_record(raw, source, expected_digest=item["envelopeSha256"])
    if {entry.name for entry in entries} != expected_files:
        raise MailboxPeerDenied("Incomplete or extra backup payload")
    return manifest


def backup_clone_archive(company_book, destination):
    """Create-only encrypted snapshot; never export or restore credential vault."""
    company_book = _strict_directory(Path(company_book))
    destination = Path(destination)
    parent = _strict_directory(destination.parent)
    if not destination.is_absolute() or os.path.lexists(destination):
        raise MailboxPeerDenied("Backup destination must be a NEW explicit directory")
    if (destination.is_relative_to(company_book) or
            company_book.is_relative_to(destination)):
        raise MailboxPeerDenied("Backup must not overlap the source company book")
    cache = _SealedReplyCache(company_book)
    with _private_lock(cache.root):
        rows, _ = _existing_records(cache)
        raw_records = []
        total_bytes = 0
        canonical_by_id = {}
        for relative, entry in rows:
            raw = entry.read_bytes()
            value = _decrypt_record(raw, entry)
            request_id = entry.name[:-6]
            if request_id in canonical_by_id and canonical_by_id[request_id] != _canonical(value):
                raise MailboxPeerDenied("Conflicting legacy and archived reply")
            canonical_by_id[request_id] = _canonical(value)
            raw_records.append((relative, raw, value["envelopeSha256"]))
            total_bytes += len(raw) + 512
        _require_archive_space(parent, total_bytes + 8192)
        destination.mkdir(mode=0o700)
        _private_acl(destination)
        manifest_rows = []
        for i, (relative, raw, envelope_digest) in enumerate(raw_records):
            slot = destination / ("r" + format(i, "08x") + ".dpapi")
            _create_secure_file(slot, raw)
            manifest_rows.append({
                "relative": relative, "sha256": hashlib.sha256(raw).hexdigest(),
                "envelopeSha256": envelope_digest})
        manifest = {"format": "taraz-sealed-reply-clone", "version": 1,
                    "sourceBook": str(company_book), "records": manifest_rows}
        encoded = _canonical(manifest)
        if len(encoded) > _MAX_MANIFEST_BYTES - 2048:
            raise MailboxPeerDenied("Encrypted manifest size exceeded")
        _require_archive_space(destination, len(encoded) + 4096)
        _create_secure_file(destination / _MANIFEST,
                            _protect(encoded.decode("utf-8"), _BUNDLE_SCOPE))
    _manifest_from_backup(destination)
    return {"version": 1, "receipts": len(raw_records),
            "credentialStateIncluded": False, "sourceChanged": False,
            "sealed": True}


def restore_clone_archive(backup_directory, clone_book):
    """Restore ONLY to fresh CLONE receipt root, never over an active archive."""
    backup_directory = _strict_directory(Path(backup_directory))
    clone_book = _strict_directory(Path(clone_book))
    if (clone_book.is_relative_to(backup_directory) or
            backup_directory.is_relative_to(clone_book)):
        raise MailboxPeerDenied("Backup cannot overlap clone company directory")
    if not any("clone" in component.casefold() or "qa" in component.casefold()
               for component in clone_book.parts):
        raise MailboxPeerDenied("Restore permitted only to explicit isolated clone/QA")
    if os.path.lexists(clone_book / _RECORD_DIR):
        raise MailboxPeerDenied("Existing immutable receipt root cannot be overwritten")
    if any(entry.name.startswith(".pending-mailbox-restore-")
           for entry in clone_book.iterdir()):
        raise MailboxPeerDenied("Unresolved interrupted clone restore stage")
    manifest = _manifest_from_backup(backup_directory)
    if str(clone_book).casefold() == manifest["sourceBook"].casefold():
        raise MailboxPeerDenied("Cannot restore archive over source book")
    estimated = sum((backup_directory / ("r" + format(i, "08x") + ".dpapi")).stat().st_size
                    + 1024 for i in range(len(manifest["records"])))
    _require_archive_space(clone_book, estimated * 2 + 8192)
    staging = clone_book / (".pending-mailbox-restore-" + secrets.token_hex(16))
    staging.mkdir(mode=0o700)
    _private_acl(staging)
    _create_secure_file(staging / ".lock", b"0")
    seen = {}
    for i, item in enumerate(manifest["records"]):
        relative = Path(item["relative"])
        source_file = (Path(manifest["sourceBook"]) / _RECORD_DIR / relative)
        original = (backup_directory / ("r" + format(i, "08x") + ".dpapi")).read_bytes()
        value = _decrypt_record(original, source_file,
                                expected_digest=item["envelopeSha256"])
        req = relative.name[:-6]
        if req in seen and seen[req] != _canonical(value):
            raise MailboxPeerDenied("Conflicting archived clone reply")
        seen[req] = _canonical(value)
        target = staging / relative
        for parent in reversed(tuple(p for p in target.parents if
                                     p != staging and staging in p.parents)):
            if not parent.exists():
                parent.mkdir(mode=0o700)
                _private_acl(parent)
        if not target.parent.exists():
            target.parent.mkdir(mode=0o700)
            _private_acl(target.parent)
        # New path must use new DPAPI entropy; it is NEVER copied as plaintext
        # onto storage. Only transient Python memory contains the projection.
        dest_final = clone_book / _RECORD_DIR / relative
        from taraz_ecosystem_mailbox_peer import _seal_scope
        new_raw = _protect(_canonical(value).decode("utf-8"), _seal_scope(dest_final))
        _create_secure_file(target, new_raw)
        if _decrypt_record(new_raw, dest_final,
                           expected_digest=item["envelopeSha256"]) != value:
            raise MailboxPeerDenied("Clone archive readback mismatch")
    # Atomic directory publication after every file is validated. A failure
    # leaves a visible, non-authoritative stage and the original clone intact.
    if os.path.lexists(clone_book / _RECORD_DIR):
        raise MailboxPeerDenied("Concurrent clone receipt root appeared")
    os.rename(staging, clone_book / _RECORD_DIR)
    return {"version": 1, "receipts": len(manifest["records"]),
            "uniqueRequestIds": len(seen), "credentialsRestored": False,
            "existingReceiptsOverwritten": False}


__all__ = ["backup_clone_archive", "restore_clone_archive"]
