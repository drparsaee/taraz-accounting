"""Explicit offline, local-only full-domain archive and recovery for Madar Desk.

No default APPDATA path, network, native Bridge or live LAN process is used.
The caller must stop *all* writers before setting offline=True.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import sqlite3
import stat
import tempfile
import zipfile

import collab
import finance
from app_storage import UnifiedAppStorage, _decode, validated_bundle
from attachments import AttachmentStore, MAX_UPLOAD_BYTES
from lan import clean_profile

FORMAT = "madar-full-backup"
VERSION = 1
MAX_FILES = 10000
MAX_TOTAL = 1024 * 1024 * 1024  # 1 GiB; bounded archive for predictable recovery
MAX_FILE = 256 * 1024 * 1024
MAX_MANIFEST = 2 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_USER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,39}\Z")
_SAFE_DIR = re.compile(r"\.madar-restore-(?:stage|old)-[0-9a-f]{24}\Z")
_LOOSE = (
    "tasks.json", "collab.json", "finance.json", "finance-completion-outbox.json",
    "automation-card-outbox.json", "lan-users.json", "personal-profile.json",
    "preferences.json", "unified-active.json",
)
_EXCLUDED = ("lan-login.bin", "google-auth.bin", "cloud-peer-code.bin",
             "lan-connection.json", "lan-profiles-cache.json")


class RecoveryError(ValueError):
    """Invalid source/backup, unsupported layout, or recovery precondition."""


def _safe_path(value):
    path = Path(value)
    if not path.is_absolute():
        raise RecoveryError("All paths must be explicit absolute paths")
    if any(part in ("..", ".") for part in path.parts):
        raise RecoveryError("Paths cannot contain traversal")
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise RecoveryError("Symlink/junction in filesystem path")
    return path


def _inside(candidate, root):
    return candidate == root or root in candidate.parents


def _paths(data_root, archive_path, *, offline):
    if offline is not True:
        raise RecoveryError("Stop LAN and native writers and explicitly pass offline=True")
    root, archive = _safe_path(data_root), _safe_path(archive_path)
    if root == root.parent or _inside(archive, root) or _inside(root, archive):
        raise RecoveryError("Archive and data root must be disjoint")
    if not archive.parent.is_dir() or not root.parent.is_dir():
        raise RecoveryError("Both parent folders must exist")
    return root, archive


def _safe_member(name):
    if (not isinstance(name, str) or not name or len(name) > 250
            or "\\" in name or "\x00" in name or ":" in name
            or name.startswith("/") or name.endswith("/") or name.startswith("~")):
        raise RecoveryError("Unsafe archive path")
    parts = PurePosixPath(name).parts
    if (len(parts) > 7 or not parts or any(
            p in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9._-]+", p)
            or p.endswith((" ", ".")) or p.upper().split(".")[0] in (
                "CON", "PRN", "AUX", "NUL",
                *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10)))
            for p in parts)):
        raise RecoveryError("Unsafe archive member")
    if name != "/".join(parts):
        raise RecoveryError("Noncanonical archive member")
    permitted = (name in _LOOSE or name == "madar-unified.sqlite3" or
                 name == "attachment-storage/attachments.sqlite3" or
                 name == "attachment-storage/manifest.json" or
                 re.fullmatch(r"attachment-storage/blobs/[0-9a-f]{2}/[0-9a-f]{64}", name))
    if not permitted:
        raise RecoveryError("Unrecognized managed archive path: " + name)
    return name


def _file(path):
    _safe_path(path)
    if not path.is_file() or path.is_symlink():
        raise RecoveryError("Missing or unsupported regular file: " + str(path))
    if path.stat().st_size > MAX_FILE:
        raise RecoveryError("File is too large for a full backup")
    return path


def _read_json(path):
    raw = _file(path).read_bytes()
    return _decode(raw)


def _validate_accounts(data, project_ids):
    if not isinstance(data, dict) or len(data) > 500:
        raise RecoveryError("Invalid LAN accounts")
    if data and not any(isinstance(value, dict) and value.get("role") == "admin"
                        for value in data.values()):
        raise RecoveryError("LAN users must include an administrator")
    for username, value in data.items():
        if (not _USER.fullmatch(username) or not isinstance(value, dict)
                or value.get("username") != username
                or value.get("role") not in ("admin", "editor", "viewer")
                or not isinstance(value.get("passwordHash"), str)
                or not re.fullmatch(r"[0-9a-f]{32}:[0-9a-f]{64}", value["passwordHash"])):
            raise RecoveryError("Invalid LAN account identity or password hash")
        grants = value.get("projects")
        if grants is not None and (not isinstance(grants, list) or len(grants) > 500
                                   or any(not isinstance(p, str) for p in grants)
                                   or len(grants) != len(set(grants))):
            raise RecoveryError("Invalid LAN project scope")
        if value["role"] == "admin" and grants is not None:
            raise RecoveryError("Scoped LAN administrator not supported")
        if grants is not None and not set(grants).issubset(project_ids):
            raise RecoveryError("LAN account references unknown project")
        clean_profile({}, value)


def _validate_tree(folder):
    """Validate archive/extracted state before allowing any restore-side rename."""
    folder = _safe_path(folder)
    if (folder / "unified-active.json").exists():
        marker = _read_json(folder / "unified-active.json")
        if marker != {"schema": 1, "database": "madar-unified.sqlite3"}:
            raise RecoveryError("Invalid active SQLite marker")
        db = _file(folder / "madar-unified.sqlite3")
        store = UnifiedAppStorage(db)
        if not store.integrity_check() or store.load() is None:
            raise RecoveryError("Corrupt unified SQLite archive")
        project_ids = {p["id"] for p in store.load().bundle["tasks"]["projects"]}
    else:
        if (folder / "madar-unified.sqlite3").exists():
            raise RecoveryError("Unmarked SQLite file cannot be restored as active data")
        tasks = _read_json(folder / "tasks.json")
        sources = {
            "tasks": tasks,
            "collab": (_read_json(folder / "collab.json") if (folder / "collab.json").exists()
                       else collab.empty_state()),
            "finance": (_read_json(folder / "finance.json") if (folder / "finance.json").exists()
                        else finance.empty_finance_state()),
            "completion_outbox": (_read_json(folder / "finance-completion-outbox.json")
                                  if (folder / "finance-completion-outbox.json").exists() else []),
        }
        validated_bundle(sources)
        project_ids = {p["id"] for p in tasks["projects"]}
    if (folder / "lan-users.json").exists():
        _validate_accounts(_read_json(folder / "lan-users.json"), project_ids)
    if (folder / "personal-profile.json").exists():
        profile = _read_json(folder / "personal-profile.json")
        if not isinstance(profile, dict):
            raise RecoveryError("Invalid personal profile")
        clean_profile({}, profile)
    if (folder / "preferences.json").exists():
        preferences = _read_json(folder / "preferences.json")
        if not isinstance(preferences, dict) or preferences.get("calendar", "jalali") not in ("jalali", "gregorian"):
            raise RecoveryError("Invalid preferences")
    if (folder / "automation-card-outbox.json").exists():
        pending = _read_json(folder / "automation-card-outbox.json")
        if not isinstance(pending, list) or len(pending) > 10000 or any(
                not isinstance(item, dict) or set(item) != {"actor", "command"}
                or not isinstance(item["actor"], str) or not isinstance(item["command"], dict)
                for item in pending):
            raise RecoveryError("Invalid automation outbox")
    attachments = folder / "attachment-storage"
    if attachments.exists():
        AttachmentStore.verify_backup(attachments)


def _snapshot(root, folder):
    """Copy only authoritative managed state, with consistent SQLite snapshots."""
    folder.mkdir(parents=True, exist_ok=False)
    for name in _LOOSE:
        source = root / name
        if source.exists() or source.is_symlink():
            shutil.copyfile(_file(source), folder / name)
    active = (root / "unified-active.json").exists()
    db = root / "madar-unified.sqlite3"
    if active:
        _file(db)
        store = UnifiedAppStorage(db)
        if not store.integrity_check():
            raise RecoveryError("Invalid active SQLite source")
        store.backup_database(folder / db.name)
    elif db.exists():
        raise RecoveryError("Unexpected unmarked SQLite source; resolve manually")
    attachments = root / "attachment-storage"
    if attachments.exists() or attachments.is_symlink():
        _safe_path(attachments)
        if not attachments.is_dir():
            raise RecoveryError("Invalid attachment storage directory")
        source_database = _file(attachments / "attachments.sqlite3")
        export = folder / "attachment-storage"
        export.mkdir()
        target_database = export / "attachments.sqlite3"
        # Read-only source prevents backup from initializing or modifying an
        # unknown attachment database, even if it is damaged.
        source = sqlite3.connect(source_database.as_uri() + "?mode=ro", uri=True)
        try:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RecoveryError("Damaged attachment SQLite source")
            if source.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise RecoveryError("Unsupported attachment SQLite schema")
            rows = source.execute(
                "SELECT DISTINCT digest,size FROM attachments ORDER BY digest").fetchall()
            target = sqlite3.connect(target_database)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        inventory = []
        for digest, size in rows:
            if (not isinstance(digest, str) or not _SHA.fullmatch(digest)
                    or type(size) is not int or not 1 <= size <= MAX_UPLOAD_BYTES):
                raise RecoveryError("Invalid referenced attachment digest or size")
            blob = _file(attachments / "blobs" / digest[:2] / digest)
            if blob.stat().st_size != size:
                raise RecoveryError("Referenced attachment blob size mismatch")
            content = blob.read_bytes()
            if sha256(content).hexdigest() != digest:
                raise RecoveryError("Referenced attachment SHA-256 mismatch")
            dest = export / "blobs" / digest[:2]
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / digest
            with target.open("xb") as out:
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
            inventory.append({"sha256": digest, "size": size})
        attachment_manifest = {"schemaVersion": 1,
                               "databaseSha256": sha256(target_database.read_bytes()).hexdigest(),
                               "blobs": inventory}
        with (export / "manifest.json").open("x", encoding="utf8") as out:
            json.dump(attachment_manifest, out, sort_keys=True, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        AttachmentStore.verify_backup(export)
    _validate_tree(folder)


def _inventory(folder):
    rows, total = {}, 0
    for root, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files:
            _safe_path(Path(root) / name)
        for name in files:
            path = Path(root) / name
            key = path.relative_to(folder).as_posix()
            _safe_member(key)
            size = _file(path).stat().st_size
            total += size
            if total > MAX_TOTAL or len(rows) >= MAX_FILES:
                raise RecoveryError("Full archive exceeds file/byte limits")
            digest = sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            rows[key] = {"size": size, "sha256": digest.hexdigest()}
    if not rows or (("tasks.json" not in rows) and ("madar-unified.sqlite3" not in rows)):
        raise RecoveryError("Full archive missing core data")
    return dict(sorted(rows.items())), total


def create_full_backup(data_root, archive_path, *, offline=False):
    """Create a new SHA-256-manifest ZIP; never overwrite or edit user data."""
    root, archive = _paths(data_root, archive_path, offline=offline)
    if not root.is_dir() or archive.exists():
        raise RecoveryError("Source directory required; target archive must not exist")
    stage = Path(tempfile.mkdtemp(prefix=".madar-backup-", dir=archive.parent))
    temporary = archive.with_name("." + archive.name + "." + secrets.token_hex(12) + ".tmp")
    try:
        payload = stage / "data"
        _snapshot(root, payload)
        files, total = _inventory(payload)
        manifest = {"format": FORMAT, "version": VERSION,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "files": files}
        manifest_raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf8")
        if len(manifest_raw) > MAX_MANIFEST:
            raise RecoveryError("Archive manifest too large")
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_STORED,
                             allowZip64=True) as archive_zip:
            archive_zip.writestr("manifest.json", manifest_raw, compress_type=zipfile.ZIP_STORED)
            for name in files:
                archive_zip.write(payload / name, "data/" + name,
                                  compress_type=zipfile.ZIP_STORED)
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        # A valid source snapshot does not prove that bytes written into the
        # ZIP still match its manifest. Read back the completed archive through
        # the same bounded verifier used by restore before exposing its name.
        verified_folder = stage / "verified"
        verified_folder.mkdir()
        checked = _extract_verified(temporary, verified_folder)
        with zipfile.ZipFile(temporary, "r") as finished:
            if finished.read("manifest.json") != manifest_raw:
                raise RecoveryError("Published archive manifest differs from the snapshot")
        if checked != {"files": len(files), "bytes": total}:
            raise RecoveryError("Archive readback inventory differs from the snapshot")
        # Exclusive creation; a concurrent archiver cannot overwrite output.
        os.link(temporary, archive)
        return {"path": str(archive), "files": len(files), "bytes": total,
                "manifestSha256": sha256(manifest_raw).hexdigest()}
    finally:
        temporary.unlink(missing_ok=True)
        shutil.rmtree(stage)


def _extract_verified(archive, folder):
    _safe_path(archive)
    if not archive.is_file():
        raise RecoveryError("Archive not found")
    if archive.stat().st_size > MAX_TOTAL + MAX_MANIFEST + 1024 * MAX_FILES:
        raise RecoveryError("Archive exceeds configured limit")
    with zipfile.ZipFile(archive, "r") as incoming:
        entries = incoming.infolist()
        if not entries or len(entries) > MAX_FILES + 1:
            raise RecoveryError("Archive entry count invalid")
        observed = {}
        for item in entries:
            name = item.filename
            if (item.is_dir() or item.flag_bits & 1 or item.compress_type != zipfile.ZIP_STORED
                    or (item.create_system == 3 and
                        stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG))
                    or name in observed or name.casefold() in (n.casefold() for n in observed)):
                raise RecoveryError("Archive contains duplicate, compressed or non-regular member")
            if name != "manifest.json":
                if not name.startswith("data/"):
                    raise RecoveryError("Archive traversal / unrecognized root")
                _safe_member(name[5:])
            observed[name] = item
        if "manifest.json" not in observed or observed["manifest.json"].file_size > MAX_MANIFEST:
            raise RecoveryError("Missing or oversized manifest")
        manifest = _decode(incoming.read("manifest.json"))
        if (not isinstance(manifest, dict)
                or set(manifest) != {"format", "version", "createdAt", "files"}
                or manifest["format"] != FORMAT or type(manifest["version"]) is not int
                or manifest["version"] != VERSION or not isinstance(manifest["createdAt"], str)
                or not isinstance(manifest["files"], dict)):
            raise RecoveryError("Unsupported full-backup manifest")
        files = manifest["files"]
        if len(files) > MAX_FILES or set(observed) != {"manifest.json", *(f"data/{n}" for n in files)}:
            raise RecoveryError("Archive entries do not match manifest")
        total = 0
        for name, record in files.items():
            _safe_member(name)
            item = observed["data/" + name]
            if (not isinstance(record, dict) or set(record) != {"size", "sha256"}
                    or type(record["size"]) is not int or not 0 <= record["size"] <= MAX_FILE
                    or not isinstance(record["sha256"], str) or not _SHA.fullmatch(record["sha256"])
                    or item.file_size != record["size"]):
                raise RecoveryError("Malformed manifest entry")
            total += item.file_size
            if total > MAX_TOTAL:
                raise RecoveryError("Archive exceeds total decompressed size limit")
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = sha256()
            with incoming.open(item) as source, target.open("xb") as dest:
                remaining = record["size"]
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise RecoveryError("Truncated backup entry")
                    remaining -= len(chunk)
                    digest.update(chunk)
                    dest.write(chunk)
                if source.read(1):
                    raise RecoveryError("Entry larger than declared size")
                dest.flush()
                os.fsync(dest.fileno())
            if digest.hexdigest() != record["sha256"]:
                raise RecoveryError("Archive SHA-256 mismatch: " + name)
    _validate_tree(folder)
    return {"files": len(files), "bytes": total}


def _journal_path(root):
    return root.parent / (".madar-restore-" + sha256(str(root).encode("utf8")).hexdigest()[:24] + ".json")


def _journal_write(path, document):
    with path.open("x", encoding="utf8") as stream:
        json.dump(document, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def recover_interrupted_restore(data_root, *, offline=False):
    """Fail-safe rollback of an interrupted swap; only uses journal-owned siblings."""
    if offline is not True:
        raise RecoveryError("Restore recovery requires offline=True")
    root = _safe_path(data_root)
    journal = _safe_path(_journal_path(root))
    if not journal.exists():
        return {"recovered": False}
    record = _read_json(journal)
    if (not isinstance(record, dict) or set(record) != {"stage", "old", "root"}
            or record["root"] != str(root)
            or not all(isinstance(record[k], str) and _SAFE_DIR.fullmatch(record[k])
                       for k in ("stage", "old")) or record["stage"] == record["old"]):
        raise RecoveryError("Untrusted restore journal; manual review required")
    stage, old = _safe_path(root.parent / record["stage"]), _safe_path(root.parent / record["old"])
    if record["stage"].rsplit("-", 1)[-1] != record["old"].rsplit("-", 1)[-1]:
        raise RecoveryError("Restore journal operation identifiers disagree")
    if old.exists():
        # Old application directory is authoritative until commit completes.
        if not old.is_dir():
            raise RecoveryError("Expected original directory is not a directory")
        if root.exists():
            if stage.exists():
                raise RecoveryError("Both root and stage present; manual review required")
            os.replace(root, stage)
        os.replace(old, root)
    elif not root.exists():
        raise RecoveryError("Source disappeared before first rename; manual review required")
    # Both tracked paths are now outside live root and owned by this operation.
    journal.unlink()
    if stage.exists():
        shutil.rmtree(stage)
    return {"recovered": True, "path": str(root)}


def restore_full_backup(data_root, archive_path, *, offline=False):
    """Backup-first staged restore; any exception rolls back the directory swap.

    On sudden process termination call recover_interrupted_restore before opening
    Madar. Excludes runtime authentication secrets and network settings.
    """
    root, archive = _paths(data_root, archive_path, offline=offline)
    if not root.is_dir() or not archive.is_file():
        raise RecoveryError("Existing local data root and archive are required")
    journal = _journal_path(root)
    if journal.exists():
        raise RecoveryError("Pending recovery journal; run recover_interrupted_restore first")
    token = secrets.token_hex(12)
    stage = root.parent / (".madar-restore-stage-" + token)
    old = root.parent / (".madar-restore-old-" + token)
    if stage.exists() or old.exists():
        raise RecoveryError("Restore staging collision")
    stage.mkdir()
    rollback_archive = root.parent / ("madar-pre-restore-" + token + ".zip")
    try:
        checked = _extract_verified(archive, stage)
        # The existing app must also be valid so a recoverable full backup can
        # be created before any live file is replaced or renamed.
        rollback = create_full_backup(root, rollback_archive, offline=True)
        _journal_write(journal, {"stage": stage.name, "old": old.name, "root": str(root)})
        try:
            os.replace(root, old)
            os.replace(stage, root)
        except BaseException:
            recover_interrupted_restore(root, offline=True)
            raise
        # At this point swap has completed; both the rollback ZIP and the
        # unmodified pre-restore directory remain available. Never silently
        # delete unrelated/unknown user files from the previous data root.
        journal.unlink()
        return {"path": str(root), "preRestoreArchive": rollback["path"],
                "preRestoreRoot": str(old), **checked}
    finally:
        # If the journal remains, preserve stage and old for explicit recovery.
        if not journal.exists() and stage.exists():
            shutil.rmtree(stage)


__all__ = ["RecoveryError", "create_full_backup", "restore_full_backup",
           "recover_interrupted_restore"]
