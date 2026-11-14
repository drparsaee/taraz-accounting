"""Create-only, explicit-path, OFFLINE TARAZ company-registry profile snapshots.

The existing automatic accounting backup keeps its original contract. This
module snapshots every regular profile file, including all company SQLite
databases, using SQLite's online backup API so WAL pages are not lost.

An OFFLINE declaration cannot prove that an unrelated writer is stopped.
Metadata races are detected, but callers must separately enforce quiescence.
The manifest contains SHA256 checksums, NOT an authenticity signature.
Windows DPAPI chat cannot be moved to another machine/principal by this tool.
"""
from __future__ import annotations

from contextlib import closing
import base64
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import secrets
import sqlite3
import stat
import subprocess
import sys

from standalone_accounting_backup import _check_snapshot, _readonly_sqlite, _sync_directory
from standalone_accounting_backup_manifest import verify_completion_manifest
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_identity import validate_identity_document
from standalone_accounting_template_store import validate_library_document


MANIFEST_NAME = "TARAZ_FULL_PROFILE_MANIFEST.json"
FORMAT = "taraz-full-profile"
VERSION = 1
_MAX_FILES = 4096
_MAX_DIRS = 8192
_LOCKS = frozenset({".company-registry.lock", ".standalone-company-active.lock",
                    ".taraz-session.lock", ".standalone-accounting-auto.lock"})
_DB_SUFFIXES = (".sqlite3", ".sqlite", ".db")
_RESERVED_WINDOWS = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)
_HEX_ID = re.compile(r"^[0-9a-f]{32}$")


class FullProfileError(RuntimeError):
    """Snapshot, verification or restore was refused before publication."""


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) &
                                     getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_path(path: Path, *, existing: bool = True) -> Path:
    path = Path(path)
    if not path.is_absolute() or not path.name or path.name in (".", ".."):
        raise FullProfileError("An explicit absolute path is required")
    for part in (path, *path.parents):
        if os.path.lexists(part) and _linked(part):
            raise FullProfileError("Symlink or Windows reparse point refused")
    if existing and not path.is_dir():
        raise FullProfileError("Required existing directory is missing")
    return path


def _relative(name: str) -> Path:
    if (type(name) is not str or not name or "\\" in name or ":" in name or
            name.startswith("/") or "\x00" in name):
        raise FullProfileError("Invalid relative profile path")
    parts = name.split("/")
    if any(not item or item in (".", "..") or item.endswith((" ", ".")) or
           _RESERVED_WINDOWS.fullmatch(item) or any(ord(ch) < 32 for ch in item)
           for item in parts):
        raise FullProfileError("Unsafe profile path component")
    if parts[0] == MANIFEST_NAME:
        raise FullProfileError("Profile path collides with snapshot manifest")
    return Path(*parts)


def _regular(path: Path) -> os.stat_result:
    if not os.path.lexists(path) or _linked(path):
        raise FullProfileError("Missing or linked profile file")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise FullProfileError("Nonregular or hardlinked profile file")
    return info


def _stamp(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _inventory(root: Path, *, allow_manifest: bool = False):
    """Inventory includes WAL/SHM stamps for race detection but not payloads."""
    dirs: list[str] = []
    files: dict[str, tuple] = {}
    sidecars: dict[str, tuple] = {}
    def fail_unreadable(exc):
        raise FullProfileError("Unreadable profile directory; refusing incomplete inventory") from exc
    for parent, children, names in os.walk(root, topdown=True, followlinks=False,
                                           onerror=fail_unreadable):
        base = Path(parent)
        if _linked(base):
            raise FullProfileError("Linked profile directory refused")
        for child in children:
            path = base / child
            _relative(path.relative_to(root).as_posix())
            if _linked(path) or not path.is_dir():
                raise FullProfileError("Linked or non-directory profile member")
            dirs.append(path.relative_to(root).as_posix())
        for name in names:
            path = base / name
            key = path.relative_to(root).as_posix()
            if not (allow_manifest and key == MANIFEST_NAME):
                _relative(key)
            info = _regular(path)
            if name in _LOCKS:
                continue
            suffix = next((x for x in ('-wal', '-shm', '-journal')
                           if name.endswith(x) and name[:-len(x)].endswith(_DB_SUFFIXES)), None)
            if suffix:
                sidecars[key] = _stamp(info)
            else:
                files[key] = _stamp(info)
        if len(dirs) > _MAX_DIRS or len(files) > _MAX_FILES:
            raise FullProfileError("Profile exceeds bounded file inventory")
    for key in sidecars:
        if key.endswith('-journal'):
            raise FullProfileError("Unfinished SQLite rollback journal; stop writers safely")
        if 'standalone-accounting-backups' in key.split('/'):
            raise FullProfileError("Archived SQLite backup has live WAL/SHM sidecars")
        suffix = next(x for x in ('-wal', '-shm', '-journal') if key.endswith(x))
        if key[:-len(suffix)] not in files:
            raise FullProfileError("Orphan SQLite WAL/SHM sidecar")
    names = list(files) + dirs
    if len({x.casefold() for x in names}) != len(names):
        raise FullProfileError("Case-colliding profile entries")
    return tuple(sorted(dirs)), dict(sorted(files.items())), dict(sorted(sidecars.items()))


def _company_ids(root: Path) -> list[str]:
    _regular(root / 'companies.json')
    _safe_path(root / 'books')
    companies = StandaloneCompanyRegistry(root).list_companies()
    if not companies:
        raise FullProfileError("Existing company registry has no companies")
    ids = sorted(c['id'] for c in companies)
    for ident in ids:
        if not _HEX_ID.fullmatch(ident):
            raise FullProfileError("Invalid company identifier")
        _safe_path(root / 'books' / ident)
    actual = {entry.name for entry in (root / 'books').iterdir() if entry.is_dir()}
    if actual != set(ids):
        raise FullProfileError("Company directories and registry do not match")
    return ids


def _recognized_dpapi_chat(names, company_ids) -> bool:
    expected = {'taraz-ai-chat.sqlite3', *(
        'books/' + company + '/taraz-ai-chat.sqlite3' for company in company_ids)}
    present = {name for name in names if name.split('/')[-1] == 'taraz-ai-chat.sqlite3'}
    if present - expected:
        raise FullProfileError("AI chat found outside known company scope; cannot prove DPAPI recovery")
    return bool(present)


def _sha(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(data)
            size += len(data)
    return h.hexdigest(), size


def _sqlite_valid(path: Path) -> None:
    with closing(_readonly_sqlite(path)) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise FullProfileError("SQLite integrity_check failed")
        if path.name == 'standalone-accounting.sqlite3':
            _check_snapshot(db)  # full accounting event history replay


def _snapshot_sqlite(source: Path, output: Path) -> None:
    with output.open('xb'):
        pass
    with closing(_readonly_sqlite(source)) as old:
        old.execute('PRAGMA query_only=ON')
        with closing(sqlite3.connect(str(output), timeout=10)) as new:
            old.backup(new, pages=128, sleep=0.025)
            new.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            if new.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower() != 'delete':
                raise FullProfileError("SQLite snapshot could not be made portable")
    _sqlite_valid(output)


def _copy_stable(source: Path, output: Path, expected: tuple) -> None:
    if _stamp(_regular(source)) != expected:
        raise FullProfileError("Profile file changed before snapshot")
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(source, flags)
    try:
        if _stamp(os.fstat(descriptor)) != expected:
            raise FullProfileError("Profile file changed while opening")
        with os.fdopen(descriptor, 'rb', closefd=False) as reader, output.open('xb') as writer:
            for block in iter(lambda: reader.read(1024 * 1024), b''):
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
        if _stamp(os.fstat(descriptor)) != expected or _stamp(_regular(source)) != expected:
            raise FullProfileError("Profile file changed during snapshot")
    finally:
        os.close(descriptor)


def _windows_sid() -> str:
    if os.name != 'nt':
        raise FullProfileError("Windows DPAPI recovery is unavailable on this platform")
    completed = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                               capture_output=True, text=True, timeout=10, check=True)
    rows = list(csv.reader(io.StringIO(completed.stdout)))
    if len(rows) != 1 or len(rows[0]) != 2 or not re.fullmatch(r'S-1-(?:\d+-)+\d+', rows[0][1]):
        raise FullProfileError("Unable to verify Windows principal SID")
    return rows[0][1]


def _principal() -> dict:
    return {'machine': platform.node().casefold(), 'sid': _windows_sid()} if os.name == 'nt' else {
        'machine': None, 'sid': None}


def _private_new_folder(path: Path) -> None:
    path.mkdir(mode=0o700)
    if os.name == 'nt':
        sid = _windows_sid()
        # Apply the private ACL before any financial material is written.
        for args in (['/inheritance:r'], ['/grant:r', '*' + sid + ':(OI)(CI)F']):
            subprocess.run(['icacls', str(path), *args], capture_output=True,
                           check=True, timeout=15)
        acl = subprocess.run(['icacls', str(path)], capture_output=True,
                             text=True, check=True, timeout=15).stdout
        # icacls resolves a granted SID to DOMAIN\user in its display.
        # Its successful /grant:r exit is the grant proof; no inherited ACL
        # entries are permitted after /inheritance:r.
        if '(I)' in acl:
            raise FullProfileError("Private Windows backup ACL could not be verified")
    else:
        os.chmod(path, 0o700)


def _private_child_folder(path: Path) -> None:
    """Children inherit the verified restricted ACL of their private parent."""
    path.mkdir(mode=0o700)
    if os.name != 'nt':
        os.chmod(path, 0o700)


def _dpapi_readback(company_dir: Path) -> None:
    """Decrypt in memory, discard data; never echo private chat contents."""
    path = company_dir / 'taraz-ai-chat.sqlite3'
    if not path.exists():
        return
    if os.name != 'nt':
        raise FullProfileError("DPAPI chat requires recovery under the Windows principal")
    from taraz_ai_chat_store import _unprotect
    with closing(_readonly_sqlite(path)) as db:
        scopes = set()
        for tenant, actor in db.execute('SELECT DISTINCT tenant_id,user_id FROM conversations'):
            if type(tenant) is not str or type(actor) is not str:
                raise FullProfileError("AI conversation owner metadata invalid")
            scopes.add(tenant + ':' + actor)
        for table, column in (('messages', 'content_cipher'), ('executions', 'payload_cipher')):
            sql = (f'SELECT c.tenant_id,c.user_id,t.{column} FROM {table} t '
                   'JOIN conversations c ON c.id=t.conversation_id')
            counted = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            joined = db.execute('SELECT COUNT(*) FROM ' + table + ' t JOIN conversations c '
                                'ON c.id=t.conversation_id').fetchone()[0]
            if joined != counted:
                raise FullProfileError("AI encrypted rows have missing conversation ownership")
            for tenant, actor, blob in db.execute(sql):
                _unprotect(bytes(blob), tenant + ':' + actor)
        for (encoded,) in db.execute('SELECT response_json FROM action_keys'):
            blob = base64.b64decode(encoded, validate=True)
            if not any(_try_dpapi(blob, scope, _unprotect) for scope in scopes):
                raise FullProfileError("DPAPI idempotency receipt cannot be recovered")


def _try_dpapi(payload, scope, function) -> bool:
    try:
        function(payload, scope)
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _profile_readback(root: Path, ids: list[str], *, dpapi: bool) -> None:
    if _company_ids(root) != ids:
        raise FullProfileError("Restored company registry does not match manifest")
    for folder in (root, *(root / 'books' / ident for ident in ids)):
        history = folder / 'standalone-accounting-backups'
        if history.is_dir():
            for archived in history.glob('standalone-accounting-auto-*.sqlite3'):
                verify_completion_manifest(archived)
        for name in ('local-users.json', 'invoice-templates.json'):
            path = folder / name
            if path.exists():
                content = json.loads(path.read_text(encoding='utf-8'))
                (validate_identity_document if name == 'local-users.json'
                 else validate_library_document)(content)
        if dpapi:
            _dpapi_readback(folder)


def _manifest(root: Path) -> dict:
    path = root / MANIFEST_NAME
    _regular(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise FullProfileError("Profile manifest exceeds size bound")
    doc = json.loads(path.read_text(encoding='utf-8'))
    if (type(doc) is not dict or set(doc) !=
            {'format', 'version', 'created_utc', 'principal', 'company_ids', 'directories', 'files', 'dpapi_required'} or
            doc['format'] != FORMAT or type(doc['version']) is not int or
            doc['version'] != VERSION or type(doc['created_utc']) is not str or
            type(doc['dpapi_required']) is not bool or type(doc['principal']) is not dict or
            set(doc['principal']) != {'machine', 'sid'} or type(doc['company_ids']) is not list or
            type(doc['directories']) is not list or type(doc['files']) is not list):
        raise FullProfileError("Unsupported full profile manifest")
    if (not doc['company_ids'] or len(doc['company_ids']) > 100 or
            sorted(set(doc['company_ids'])) != doc['company_ids'] or
            any(type(x) is not str or not _HEX_ID.fullmatch(x) for x in doc['company_ids'])):
        raise FullProfileError("Untrusted manifest company identifiers")
    if doc['dpapi_required'] and (not isinstance(doc['principal']['machine'], str) or
                                   not isinstance(doc['principal']['sid'], str)):
        raise FullProfileError("DPAPI source binding is missing")
    if len(doc['directories']) > _MAX_DIRS or len(doc['files']) > _MAX_FILES:
        raise FullProfileError("Oversized manifest inventory")
    dirs = doc['directories']
    if any(type(x) is not str for x in dirs) or dirs != sorted(set(dirs)):
        raise FullProfileError("Invalid directory listing")
    for item in dirs:
        _relative(item)
    names = []
    for item in doc['files']:
        if (type(item) is not dict or set(item) != {'path', 'size', 'sha256', 'kind'} or
                type(item['path']) is not str or type(item['size']) is not int or item['size'] < 0 or
                type(item['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', item['sha256']) or
                item['kind'] not in ('file', 'sqlite', 'sqlite-archive')):
            raise FullProfileError("Invalid manifest file description")
        _relative(item['path'])
        archived = 'standalone-accounting-backups' in item['path'].split('/')
        expected_kind = ('sqlite-archive' if archived else 'sqlite') if item['path'].endswith(_DB_SUFFIXES) else 'file'
        if item['kind'] != expected_kind:
            raise FullProfileError("Invalid SQLite manifest kind")
        names.append(item['path'])
    if names != sorted(set(names)) or len({x.casefold() for x in names + dirs}) != len(names) + len(dirs):
        raise FullProfileError("Manifest contains colliding paths")
    if 'companies.json' not in names or 'books' not in dirs:
        raise FullProfileError("Company registry missing from manifest")
    if doc['dpapi_required'] != _recognized_dpapi_chat(names, doc['company_ids']):
        raise FullProfileError("DPAPI manifest does not describe its chat stores")
    if any(str(Path(name).parent).replace('\\', '/') not in ('.', *dirs) for name in names):
        raise FullProfileError("Manifest file parent was not declared")
    return doc


def _bind_dpapi(doc: dict) -> None:
    if doc['dpapi_required'] and _principal() != doc['principal']:
        raise FullProfileError("DPAPI recovery blocked: different Windows machine or principal")


def verify_full_profile_backup(backup_dir: Path) -> dict:
    """Verify bytes, source tree, registry, SQLite, and same-principal DPAPI."""
    root = _safe_path(Path(backup_dir))
    doc = _manifest(root)
    _bind_dpapi(doc)
    dirs, files, extra = _inventory(root, allow_manifest=True)
    if extra or list(dirs) != doc['directories'] or set(files) != {
            *[item['path'] for item in doc['files']], MANIFEST_NAME}:
        raise FullProfileError("Snapshot has unmanifested or missing entries")
    for item in doc['files']:
        path = root / _relative(item['path'])
        sha, size = _sha(path)
        if sha != item['sha256'] or size != item['size']:
            raise FullProfileError("Snapshot SHA256 mismatch: " + item['path'])
        if item['kind'] in ('sqlite', 'sqlite-archive'):
            _sqlite_valid(path)
    _profile_readback(root, doc['company_ids'], dpapi=doc['dpapi_required'])
    return {'manifest': root / MANIFEST_NAME, 'companies': len(doc['company_ids']),
            'files': len(doc['files']), 'sqlite': sum(x['kind'] != 'file' for x in doc['files']),
            'dpapi_required': doc['dpapi_required'], 'dpapi_verified': doc['dpapi_required']}


def create_full_profile_backup(profile_root: Path, destination: Path, *,
                               offline_acknowledged: bool = False) -> dict:
    """Snapshot to a NEW, private destination dir; source is never written."""
    if offline_acknowledged is not True:
        raise PermissionError("Full profile backup requires an OFFLINE declaration")
    source = _safe_path(Path(profile_root))
    output = _safe_path(Path(destination), existing=False)
    _safe_path(output.parent)
    if source == output or source in output.parents or output in source.parents:
        raise FullProfileError("Source/backup paths must be disjoint")
    if os.path.lexists(output):
        raise FileExistsError("Backup directory already exists")
    ids = _company_ids(source)
    dirs, files, sidecars = _inventory(source)
    if 'companies.json' not in files:
        raise FullProfileError("Registry unavailable")
    principal = _principal()
    dpapi = _recognized_dpapi_chat(files, ids)
    if dpapi and os.name != 'nt':
        raise FullProfileError("DPAPI chat backup requires same-principal Windows verification")
    _profile_readback(source, ids, dpapi=dpapi)
    # Read-only validation may touch OS-managed SQLite shared-memory timestamps.
    # Start the protected metadata race window only after preflight concludes.
    dirs, files, sidecars = _inventory(source)
    _private_new_folder(output)
    for directory in dirs:
        dest = output / _relative(directory)
        _private_child_folder(dest)
    contents = []
    for name, stamp in files.items():
        original = source / _relative(name)
        target = output / _relative(name)
        archived = 'standalone-accounting-backups' in name.split('/')
        kind = ('sqlite-archive' if archived else 'sqlite') if name.endswith(_DB_SUFFIXES) else 'file'
        if kind == 'sqlite':
            if _stamp(_regular(original)) != stamp:
                raise FullProfileError("SQLite source changed before snapshot")
            _snapshot_sqlite(original, target)
        else:
            _copy_stable(original, target, stamp)
        os.chmod(target, 0o600)
        sha, size = _sha(target)
        contents.append({'path': name, 'sha256': sha, 'size': size, 'kind': kind})
    if _inventory(source) != (dirs, files, sidecars):
        raise FullProfileError("Profile changed during snapshot; do not use partial backup")
    _profile_readback(output, ids, dpapi=dpapi)
    doc = {'format': FORMAT, 'version': VERSION,
           'created_utc': datetime.now(timezone.utc).isoformat(),
           'principal': principal, 'company_ids': ids, 'directories': list(dirs),
           'files': contents, 'dpapi_required': dpapi}
    # A private, unfinished directory is intentionally left for review on error.
    # Publishing this completion marker is the only success gate.
    manifest_file = output / MANIFEST_NAME
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    with manifest_file.open('xb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(output)
    original_marker = _stamp(_regular(manifest_file))
    try:
        return verify_full_profile_backup(output)
    except BaseException:
        # Withdraw only the completion marker we published. Leave the private
        # incomplete backup files available for operator investigation.
        if (_stamp(_regular(manifest_file)) == original_marker and
                _sha(manifest_file) == (hashlib.sha256(payload).hexdigest(), len(payload))):
            manifest_file.unlink()
        raise


def _publish_new_directory(stage: Path, destination: Path) -> None:
    """Atomic create-only directory rename (Windows or Linux renameat2)."""
    if os.path.lexists(destination):
        raise FileExistsError("Existing profile destination cannot be overwritten")
    if os.name == 'nt':
        os.rename(stage, destination)  # Windows MoveFile without REPLACE_EXISTING
    elif sys.platform.startswith('linux'):
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, 'renameat2', None)
        if renameat2 is None:
            raise FullProfileError("Atomic create-only rename is unavailable")
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                              ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(stage), -100, os.fsencode(destination), 1):
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
    else:
        raise FullProfileError("Atomic create-only directory restore unsupported on this platform")


def restore_full_profile_backup(backup_dir: Path, destination: Path, *,
                                offline_acknowledged: bool = False) -> dict:
    """Restore into NEW isolated profile; never overwrite files or call APPDATA."""
    if offline_acknowledged is not True:
        raise PermissionError("Full profile restore requires an OFFLINE declaration")
    source = _safe_path(Path(backup_dir))
    dest = _safe_path(Path(destination), existing=False)
    _safe_path(dest.parent)
    if source == dest or source in dest.parents or dest in source.parents:
        raise FullProfileError("Backup and restore paths must be disjoint")
    if os.path.lexists(dest):
        raise FileExistsError("Restore target already exists")
    checked = verify_full_profile_backup(source)
    doc = _manifest(source)
    original_manifest_hash = _sha(source / MANIFEST_NAME)
    stage = dest.parent / ('.taraz-full-profile-stage-' + secrets.token_hex(16))
    _safe_path(stage, existing=False)
    _private_new_folder(stage)
    for name in doc['directories']:
        _private_child_folder(stage / _relative(name))
    for item in doc['files']:
        rel = _relative(item['path'])
        original = source / rel
        target = stage / rel
        _copy_stable(original, target, _stamp(_regular(original)))
        os.chmod(target, 0o600)
        if _sha(target) != (item['sha256'], item['size']):
            raise FullProfileError("Restored file checksum mismatch")
        if item['kind'] in ('sqlite', 'sqlite-archive'):
            _sqlite_valid(target)
    _profile_readback(stage, doc['company_ids'], dpapi=doc['dpapi_required'])
    if verify_full_profile_backup(source) != checked:
        raise FullProfileError("Backup changed during restore")
    if _sha(source / MANIFEST_NAME) != original_manifest_hash:
        raise FullProfileError("Backup manifest changed during restore")
    _publish_new_directory(stage, dest)
    _sync_directory(dest.parent)
    return {'profile': dest, 'companies': checked['companies'], 'files': checked['files'],
            'sqlite': checked['sqlite'], 'dpapi_verified': checked['dpapi_verified']}


__all__ = ['create_full_profile_backup', 'verify_full_profile_backup',
           'restore_full_profile_backup', 'FullProfileError', 'MANIFEST_NAME']
