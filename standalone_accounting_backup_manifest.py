"""Completion marker for automatic standalone-accounting backup sets.

The marker is published last. Older explicit manual SQLite-only backups keep
their original restore contract; incomplete automatic sets always fail closed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from standalone_accounting_backup import _sync_directory


FORMAT = "madar-standalone-accounting-auto-completion"
VERSION = 1
_AUTO_PREFIX = "standalone-accounting-auto-"
_COMPANIONS = {"users": ".users.json", "templates": ".templates.json"}


class BackupManifestError(RuntimeError):
    """An automatic backup set is not complete or has changed."""


def _regular(path: Path) -> bool:
    for component in (path, *path.parents):
        if component.is_symlink() or (hasattr(component, 'is_junction') and component.is_junction()):
            return False
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def _entry(path: Path) -> dict:
    if not _regular(path):
        raise BackupManifestError("Backup completion member is missing or not a regular file")
    checksum = hashlib.sha256()
    size = 0
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            size += len(block)
            checksum.update(block)
    return {"name": path.name, "size": size, "sha256": checksum.hexdigest()}


def _member_path(source: Path, kind: str) -> Path:
    return source if kind == 'sqlite' else source.with_suffix(_COMPANIONS[kind])


def _manifest_path(source: Path) -> Path:
    return source.with_suffix('.manifest.json')


def publish_completion_manifest(source: Path) -> Path:
    """Atomically publish the last file only after all members are durable."""
    if not source.name.startswith(_AUTO_PREFIX):
        raise BackupManifestError("Completion manifest requires an automatic backup name")
    files = {"sqlite": _entry(source)}
    for kind in _COMPANIONS:
        path = _member_path(source, kind)
        if os.path.lexists(path):
            files[kind] = _entry(path)
    manifest = _manifest_path(source)
    if os.path.lexists(manifest):
        raise BackupManifestError("Automatic completion manifest already exists")
    content = json.dumps({"format": FORMAT, "version": VERSION, "files": files},
                         sort_keys=True, separators=(',', ':')).encode('utf-8')
    fd, name = tempfile.mkstemp(dir=str(source.parent), prefix='.' + source.stem + '.manifest-', suffix='.tmp')
    temporary = Path(name)
    published = False
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(str(temporary), str(manifest))
        published = True
        _sync_directory(source.parent)
        verify_completion_manifest(source)
        return manifest
    except BaseException:
        if published:
            try:
                if os.path.samefile(temporary, manifest):
                    manifest.unlink()
            except OSError:
                pass
        raise
    finally:
        temporary.unlink(missing_ok=True)


def verify_completion_manifest(source: Path) -> bytes | None:
    """Validate all declared members and absence of undeclared companions.

    Returns the original marker bytes for later change detection; None means an
    explicitly named legacy manual backup without any completion manifest.
    """
    manifest = _manifest_path(source)
    if not os.path.lexists(manifest):
        if source.name.startswith(_AUTO_PREFIX):
            raise BackupManifestError("Automatic backup has no completion manifest")
        return None
    if not _regular(manifest) or manifest.stat().st_size > 16 * 1024:
        raise BackupManifestError("Invalid automatic backup completion manifest")
    try:
        raw = manifest.read_bytes()
        document = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise BackupManifestError("Damaged backup completion manifest") from exc
    if (type(document) is not dict or set(document) != {'format', 'version', 'files'} or
        document['format'] != FORMAT or type(document['version']) is not int or
        document['version'] != VERSION or type(document['files']) is not dict):
        raise BackupManifestError("Unsupported backup completion manifest")
    members = document['files']
    if not set(members) <= {'sqlite', *tuple(_COMPANIONS)} or 'sqlite' not in members:
        raise BackupManifestError("Invalid backup completion member list")
    for kind in ('sqlite', *_COMPANIONS):
        path = _member_path(source, kind)
        declared = members.get(kind)
        if declared is None:
            if kind != 'sqlite' and os.path.lexists(path):
                raise BackupManifestError("Undeclared automatic backup companion")
            continue
        if (type(declared) is not dict or set(declared) != {'name', 'size', 'sha256'} or
            declared['name'] != path.name or type(declared['size']) is not int or
            declared['size'] < 0 or type(declared['sha256']) is not str or
            len(declared['sha256']) != 64):
            raise BackupManifestError("Invalid automatic backup member descriptor")
        if _entry(path) != declared:
            raise BackupManifestError("Automatic backup member checksum or size mismatch")
    return raw
