"""Offline create-only snapshot and isolated rollback restore of TARAZ's three roots.

The caller supplies three *existing* source directories explicitly: roaming
Taraz, local Taraz, and local Madar-Taraz-Bridge. The roaming root may be a
registered company hub or a legacy unregistered standalone ledger. No ambient
APPDATA discovery, installer, migration, production mutation, or key export.

An offline_acknowledged flag is a declaration: it DOES NOT prove all external
writers are stopped or give cross-database atomicity. Stable inventory and a
second SQLite online snapshot detect many races, but not a stopped/restarted
writer or writes reverting to the same state. Treat live upgrade as BLOCKED
until independent quiescence evidence exists. Windows DPAPI remains bound to
the identical machine and Windows principal; cross-device restore is BLOCKED.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from standalone_accounting_backup import _sync_directory
from standalone_accounting_backup_manifest import verify_completion_manifest
from standalone_accounting_identity import validate_identity_document
from standalone_accounting_template_store import validate_library_document
from taraz_full_profile_backup_20261114 import (
    _company_ids, _copy_stable, _dpapi_readback, _private_child_folder,
    _private_new_folder, _profile_readback, _publish_new_directory,
    _principal, _regular, _relative, _safe_path, _snapshot_sqlite,
    _sqlite_valid, _stamp, FullProfileError,
)


MANIFEST_NAME = 'TARAZ_THREE_ROOT_MANIFEST.json'
FORMAT = 'taraz-three-root-offline-snapshot'
VERSION = 1
ROLES = ('roaming_taraz', 'local_taraz', 'local_bridge')
_DB_EXT = ('.sqlite3', '.sqlite', '.db')
_SIDECARS = ('-wal', '-shm', '-journal')
_MAX_FILES = 8192
_MAX_DIRS = 16384
_MAX_MANIFEST_BYTES = 3 * 1024 * 1024


class ThreeRootBackupError(FullProfileError):
    """The exact, complete three-root snapshot or restore is unsafe."""


class PartialThreeRootRestoreError(ThreeRootBackupError):
    """One or more owned, newly published clones require operator review."""

    def __init__(self, published: list[str]):
        super().__init__('Restore partially published; inspect new clones: ' + ', '.join(published))
        self.published = tuple(published)


def _windows_principal():
    if os.name != 'nt':
        raise ThreeRootBackupError('Only Windows can prove same-principal DPAPI recovery')
    principal = _principal()
    if (not isinstance(principal.get('machine'), str) or not principal['machine'] or
            not isinstance(principal.get('sid'), str) or not principal['sid'].startswith('S-1-')):
        raise ThreeRootBackupError('Windows principal binding unavailable')
    return principal


def _paths(*paths: Path, existing: tuple[bool, ...]):
    if len(paths) != len(existing):
        raise ValueError('Internal path preflight mismatch')
    checked = []
    for path, required in zip(paths, existing):
        value = _safe_path(Path(path), existing=required)
        if not required:
            _safe_path(value.parent)
            if os.path.lexists(value):
                raise FileExistsError('Create-only destination exists: ' + value.name)
        checked.append(value)
    canonical = [x.resolve(strict=False) for x in checked]
    for i, first in enumerate(canonical):
        for second in canonical[i + 1:]:
            if first == second or first in second.parents or second in first.parents:
                raise ThreeRootBackupError('Source, backup, and three targets must be disjoint')
    return checked


def _name(name: str) -> Path:
    if name == MANIFEST_NAME:
        raise ThreeRootBackupError('Manifest filename collides with a profile member')
    return _relative(name)


def _sidecar_name(name: str) -> str | None:
    return next((suffix for suffix in _SIDECARS
                 if name.endswith(suffix) and name[:-len(suffix)].endswith(_DB_EXT)), None)


def _secure_open(path: Path):
    """Open a checked regular, unique-inode file without following a race link."""
    before = _regular(path)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    opened = os.fstat(descriptor)
    if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
            _stamp(opened) != _stamp(before)):
        os.close(descriptor)
        raise ThreeRootBackupError('File identity changed while opening')
    # Windows os.fstat may round creation timestamps differently than lstat;
    # dev/inode/size/mtime remain comparable across the two file views.
    return descriptor, _stamp(before)


def _secure_digest(path: Path) -> tuple[str, int]:
    descriptor, before = _secure_open(path)
    digest, size = hashlib.sha256(), 0
    try:
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
        after = os.fstat(descriptor)
        current = _regular(path)
        if (_stamp(after) != before or _stamp(current) != before or
                size != after.st_size):
            raise ThreeRootBackupError('File changed during SHA256 readback')
        return digest.hexdigest(), size
    finally:
        os.close(descriptor)


def _read_small_file(path: Path, maximum: int) -> bytes:
    descriptor, before = _secure_open(path)
    try:
        if before[2] > maximum:
            raise ThreeRootBackupError('Manifest exceeds safe size')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            payload = stream.read(maximum + 1)
        after = os.fstat(descriptor)
        current = _regular(path)
        if (len(payload) > maximum or _stamp(after) != before or
                _stamp(current) != before):
            raise ThreeRootBackupError('Manifest changed during read')
        return payload
    finally:
        os.close(descriptor)


def _scan(root: Path, *, allow_manifest: bool = False):
    """Exact recursive inventory (including lock files); classify SQLite journals."""
    directories: list[str] = []
    files: dict[str, tuple] = {}
    sidecars: dict[str, tuple] = {}

    def unreadable(error):
        raise ThreeRootBackupError('Unreadable source directory; incomplete inventory') from error

    for folder, subdirs, names in os.walk(root, topdown=True, followlinks=False, onerror=unreadable):
        here = Path(folder)
        _safe_path(here)
        for item in subdirs:
            member = here / item
            relative = member.relative_to(root).as_posix()
            _name(relative)
            _safe_path(member)
            directories.append(relative)
        for item in names:
            member = here / item
            relative = member.relative_to(root).as_posix()
            if not (allow_manifest and relative == MANIFEST_NAME):
                _name(relative)
            info = _regular(member)
            suffix = _sidecar_name(relative)
            if suffix:
                sidecars[relative] = _stamp(info)
            else:
                files[relative] = _stamp(info)
        if len(files) > _MAX_FILES or len(directories) > _MAX_DIRS:
            raise ThreeRootBackupError('Profile inventory exceeds safe bound')

    for name in sidecars:
        suffix = _sidecar_name(name)
        if suffix == '-journal':
            raise ThreeRootBackupError('SQLite rollback journal present; shut down writer first')
        if name[:-len(suffix)] not in files:
            raise ThreeRootBackupError('Orphan WAL/SHM sidecar')
        if 'standalone-accounting-backups' in name.split('/'):
            raise ThreeRootBackupError('Archive database has live WAL/SHM')

    all_names = directories + list(files) + list(sidecars)
    if len(all_names) != len({x.casefold() for x in all_names}):
        raise ThreeRootBackupError('Case-colliding paths')
    for name in files:
        for component in (Path(name).parent,):
            if str(component).replace('\\', '/') not in ('.', *directories):
                raise ThreeRootBackupError('Missing declared parent directory')
    return tuple(sorted(directories)), dict(sorted(files.items())), dict(sorted(sidecars.items()))


def _roaming_mode(root: Path) -> tuple[str, list[str]]:
    registry = os.path.lexists(root / 'companies.json')
    books = os.path.lexists(root / 'books')
    if registry != books:
        raise ThreeRootBackupError('Partial registered profile cannot be restored')
    if registry:
        return 'registered', _company_ids(root)
    if not os.path.lexists(root / 'standalone-accounting.sqlite3'):
        raise ThreeRootBackupError('Unregistered legacy profile has no accounting ledger')
    _sqlite_valid(root / 'standalone-accounting.sqlite3')
    return 'legacy', []


def _readback(root: Path, *, role: str, mode: str, ids: list[str], files: dict):
    if role == 'roaming_taraz':
        if mode == 'registered':
            _profile_readback(root, ids, dpapi=False)
        elif mode == 'legacy':
            if _roaming_mode(root) != ('legacy', []):
                raise ThreeRootBackupError('Legacy profile changed classification')
        else:
            raise ThreeRootBackupError('Unknown roaming profile mode')
    for name in files:
        path = root / Path(*name.split('/'))
        if name.endswith('.sqlite3') or name.endswith(('.sqlite', '.db')):
            if 'standalone-accounting-backups' in name.split('/'):
                if path.name.startswith('standalone-accounting-auto-'):
                    verify_completion_manifest(path)
            else:
                _sqlite_valid(path)
        if path.name == 'local-users.json':
            validate_identity_document(json.loads(path.read_text(encoding='utf-8')))
        elif path.name == 'invoice-templates.json':
            validate_library_document(json.loads(path.read_text(encoding='utf-8')))
        elif path.name == 'taraz-ai-chat.sqlite3':
            _dpapi_readback(path.parent)


def _is_archive(name: str) -> bool:
    return 'standalone-accounting-backups' in name.split('/')


def _kind(name: str) -> str:
    if not name.endswith(_DB_EXT):
        return 'file'
    return 'sqlite-archive' if _is_archive(name) else 'sqlite'


def _stable_file_copy(source: Path, dest: Path, source_stamp: tuple, baseline: tuple):
    if _secure_digest(source) != baseline:
        raise ThreeRootBackupError('Source contents changed before copy')
    _copy_stable(source, dest, source_stamp)
    if _secure_digest(source) != baseline or _secure_digest(dest) != baseline:
        raise ThreeRootBackupError('File content changed while backing up')


def _snapshot_twice(source: Path, dest: Path, expected_stamp: tuple):
    if _stamp(_regular(source)) != expected_stamp:
        raise ThreeRootBackupError('SQLite source changed before snapshot')
    _snapshot_sqlite(source, dest)
    first = _secure_digest(dest)
    # A second, independent hot snapshot catches commits between store copies.
    # Its pathname is private and is removed before manifest publication.
    second = dest.parent / ('.taraz-sqlite-second-' + secrets.token_hex(16) + '.sqlite3')
    try:
        _snapshot_sqlite(source, second)
        if first != _secure_digest(second):
            raise ThreeRootBackupError('SQLite changed between consistency snapshots')
    finally:
        for suffix in ('-wal', '-shm', '-journal', ''):
            path = Path(str(second) + suffix)
            path.unlink(missing_ok=True)
    if _stamp(_regular(source)) != expected_stamp:
        raise ThreeRootBackupError('SQLite source changed during snapshot')


def _validate_doc(doc) -> dict:
    if (type(doc) is not dict or set(doc) != {'format', 'version', 'created_utc',
            'principal', 'roots'} or doc['format'] != FORMAT or
            type(doc['version']) is not int or doc['version'] != VERSION or
            type(doc['created_utc']) is not str or type(doc['principal']) is not dict or
            set(doc['principal']) != {'machine', 'sid'} or type(doc['roots']) is not dict or
            set(doc['roots']) != set(ROLES)):
        raise ThreeRootBackupError('Unsupported three-root completion manifest')
    if doc['principal'] != _windows_principal():
        raise ThreeRootBackupError('DPAPI recovery BLOCKED on different computer or Windows user')
    for role in ROLES:
        entry = doc['roots'][role]
        if (type(entry) is not dict or set(entry) != {'mode', 'company_ids', 'directories', 'files'} or
                type(entry['mode']) is not str or type(entry['company_ids']) is not list or
                type(entry['directories']) is not list or type(entry['files']) is not list or
                len(entry['directories']) > _MAX_DIRS or len(entry['files']) > _MAX_FILES):
            raise ThreeRootBackupError('Invalid role manifest shape')
        if role == 'roaming_taraz':
            if entry['mode'] not in ('registered', 'legacy'):
                raise ThreeRootBackupError('Invalid roaming mode')
        elif entry['mode'] != 'data' or entry['company_ids']:
            raise ThreeRootBackupError('Invalid local data role')
        company_ids = entry['company_ids']
        if (len(company_ids) > 100 or company_ids != sorted(set(company_ids)) or
                any(type(cid) is not str or not re.fullmatch('[a-f0-9]{32}', cid)
                    for cid in company_ids) or
                (role == 'roaming_taraz' and ((entry['mode'] == 'legacy') != (not company_ids)))):
            raise ThreeRootBackupError('Invalid company registry IDs')
        directories = entry['directories']
        if (directories != sorted(set(directories)) or
                any(type(x) is not str or not _name(x) for x in directories)):
            raise ThreeRootBackupError('Invalid manifest directories')
        if len(set(x.casefold() for x in directories)) != len(directories):
            raise ThreeRootBackupError('Case-colliding manifest directories')
        names = []
        for item in entry['files']:
            if (type(item) is not dict or set(item) != {'path', 'sha256', 'size', 'kind'} or
                    type(item['path']) is not str or type(item['sha256']) is not str or
                    not re.fullmatch('[a-f0-9]{64}', item['sha256']) or
                    type(item['size']) is not int or item['size'] < 0 or item['kind'] != _kind(item['path'])):
                raise ThreeRootBackupError('Invalid file descriptor')
            _name(item['path'])
            names.append(item['path'])
            parent = str(Path(item['path']).parent).replace('\\', '/')
            if parent != '.' and parent not in directories:
                raise ThreeRootBackupError('Manifest omits file parent')
        if names != sorted(set(names)) or len({x.casefold() for x in directories + names}) != len(directories) + len(names):
            raise ThreeRootBackupError('Missing, duplicate, or colliding manifest files')
        if role == 'roaming_taraz':
            if entry['mode'] == 'registered' and not {'companies.json', 'books'} <= (set(names) | set(directories)):
                raise ThreeRootBackupError('Registered role lacks company registry')
            if entry['mode'] == 'legacy' and 'standalone-accounting.sqlite3' not in names:
                raise ThreeRootBackupError('Legacy role lacks accounting database')
    return doc


def _read_manifest(bundle: Path) -> dict:
    marker = bundle / MANIFEST_NAME
    try:
        doc = json.loads(_read_small_file(marker, _MAX_MANIFEST_BYTES).decode('utf-8'))
    except (ValueError, UnicodeError, OSError) as exc:
        raise ThreeRootBackupError('Damaged completion manifest') from exc
    return _validate_doc(doc)


def verify_three_root_backup(bundle_dir: Path) -> dict:
    """Verify exact backup membership, every SHA256, SQLite, DPAPI, and mode."""
    bundle = _safe_path(Path(bundle_dir))
    doc = _read_manifest(bundle)
    dirs, files, sidecars = _scan(bundle, allow_manifest=True)
    expected_dirs = {role for role in ROLES}
    expected_files = {MANIFEST_NAME}
    for role in ROLES:
        entry = doc['roots'][role]
        expected_dirs.update(role + '/' + name for name in entry['directories'])
        expected_files.update(role + '/' + item['path'] for item in entry['files'])
        root = bundle / role
        role_dirs, role_files, role_sidecars = _scan(root)
        if (role_sidecars or list(role_dirs) != entry['directories'] or
                list(role_files) != [x['path'] for x in entry['files']]):
            raise ThreeRootBackupError('Snapshot differs from role manifest: ' + role)
        for item in entry['files']:
            source = root / Path(*item['path'].split('/'))
            if _secure_digest(source) != (item['sha256'], item['size']):
                raise ThreeRootBackupError('Snapshot SHA256 mismatch in ' + role)
        _readback(root, role=role, mode=entry['mode'], ids=entry['company_ids'], files=role_files)
    if sidecars or set(dirs) != expected_dirs or set(files) != expected_files:
        raise ThreeRootBackupError('Unexpected or missing three-root snapshot member')
    return {'manifest': bundle / MANIFEST_NAME,
            'companies': len(doc['roots']['roaming_taraz']['company_ids']),
            'mode': doc['roots']['roaming_taraz']['mode'],
            'files': sum(len(doc['roots'][role]['files']) for role in ROLES),
            'sqlite': sum(sum(x['kind'] != 'file' for x in doc['roots'][role]['files'])
                          for role in ROLES), 'dpapi_same_principal_verified': True,
            'roots': list(ROLES)}


def create_three_root_backup(roaming_taraz: Path, local_taraz: Path,
                             local_bridge: Path, destination: Path, *,
                             offline_acknowledged: bool = False) -> dict:
    """Create a private, immutable-by-contract snapshot under UNUSED directory."""
    if offline_acknowledged is not True:
        raise PermissionError('Explicit OFFLINE declaration required for all three roots')
    roaming, local, bridge, bundle = _paths(roaming_taraz, local_taraz, local_bridge,
                                            destination, existing=(True, True, True, False))
    principal = _windows_principal()
    mode, ids = _roaming_mode(roaming)
    sources = dict(zip(ROLES, (roaming, local, bridge)))
    scans = {role: _scan(root) for role, root in sources.items()}
    static_hashes = {}
    for role in ROLES:
        root = sources[role]
        dirs, files, _ = scans[role]
        _readback(root, role=role, mode=mode if role == 'roaming_taraz' else 'data',
                  ids=ids if role == 'roaming_taraz' else [], files=files)
        for name in files:
            if _kind(name) != 'sqlite':
                static_hashes[(role, name)] = _secure_digest(root / Path(*name.split('/')))
    # Read-only SQLite preflight may update WAL-sidecar metadata. Rebaseline.
    scans = {role: _scan(root) for role, root in sources.items()}
    for role in ROLES:
        for name, digest in ((name, value) for (r, name), value in static_hashes.items() if r == role):
            if _secure_digest(sources[role] / Path(*name.split('/'))) != digest:
                raise ThreeRootBackupError('Source changed during read-only preflight')

    _private_new_folder(bundle)
    manifest_roles = {}
    for role in ROLES:
        root = sources[role]
        dirs, files, _ = scans[role]
        copied = bundle / role
        _private_child_folder(copied)
        for name in dirs:
            _private_child_folder(copied / _name(name))
        descriptors = []
        for name, before in files.items():
            src = root / _name(name)
            target = copied / _name(name)
            kind = _kind(name)
            if kind == 'sqlite':
                _snapshot_twice(src, target, before)
            else:
                _stable_file_copy(src, target, before, static_hashes[(role, name)])
            os.chmod(target, 0o600)
            sha, size = _secure_digest(target)
            descriptors.append({'path': name, 'size': size, 'sha256': sha, 'kind': kind})
        if _scan(root) != scans[role]:
            raise ThreeRootBackupError('Source root changed during snapshot: ' + role)
        _readback(copied, role=role, mode=mode if role == 'roaming_taraz' else 'data',
                  ids=ids if role == 'roaming_taraz' else [], files=_scan(copied)[1])
        manifest_roles[role] = {'mode': mode if role == 'roaming_taraz' else 'data',
                                'company_ids': ids if role == 'roaming_taraz' else [],
                                'directories': list(dirs), 'files': descriptors}
    if any(_scan(sources[role]) != scans[role] for role in ROLES):
        raise ThreeRootBackupError('Cross-root source changed before completion')
    doc = {'format': FORMAT, 'version': VERSION,
           'created_utc': datetime.now(timezone.utc).isoformat(),
           'principal': principal, 'roots': manifest_roles}
    marker = bundle / MANIFEST_NAME
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode('utf-8')
    with marker.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    _sync_directory(bundle)
    try:
        return verify_three_root_backup(bundle)
    except BaseException:
        if os.path.lexists(marker) and _secure_digest(marker) == (hashlib.sha256(raw).hexdigest(), len(raw)):
            marker.unlink()
        raise


def restore_three_root_backup(bundle_dir: Path, roaming_destination: Path,
                              local_destination: Path, bridge_destination: Path, *,
                              offline_acknowledged: bool = False) -> dict:
    """Stage, verify, then publish three unused isolated rollback clone roots.

    Per-directory renames are atomic but publishing three distinct directories
    is NOT an atomic transaction. A publication error leaves any already-owned
    clones in place for explicit inspection; original paths are never touched.
    """
    if offline_acknowledged is not True:
        raise PermissionError('Three-root restore requires explicit OFFLINE declaration')
    bundle, roaming, local, bridge = _paths(bundle_dir, roaming_destination,
                                            local_destination, bridge_destination,
                                            existing=(True, False, False, False))
    before = verify_three_root_backup(bundle)
    marker_hash = _secure_digest(bundle / MANIFEST_NAME)
    doc = _read_manifest(bundle)
    destinations = dict(zip(ROLES, (roaming, local, bridge)))
    stages = {}
    for role, target in destinations.items():
        stage = target.parent / ('.taraz-three-root-stage-' + secrets.token_hex(16))
        _safe_path(stage, existing=False)
        _private_new_folder(stage)
        stages[role] = stage
        entry = doc['roots'][role]
        for name in entry['directories']:
            _private_child_folder(stage / _name(name))
        for item in entry['files']:
            relative = _name(item['path'])
            src = bundle / role / relative
            dest = stage / relative
            _stable_file_copy(src, dest, _stamp(_regular(src)),
                              (item['sha256'], item['size']))
            os.chmod(dest, 0o600)
        dirs, files, sidecars = _scan(stage)
        if sidecars or list(dirs) != entry['directories'] or list(files) != [
                item['path'] for item in entry['files']]:
            raise ThreeRootBackupError('Staged restore inventory differs from manifest')
        _readback(stage, role=role, mode=entry['mode'], ids=entry['company_ids'], files=files)
    if verify_three_root_backup(bundle) != before or _secure_digest(bundle / MANIFEST_NAME) != marker_hash:
        raise ThreeRootBackupError('Bundle changed during three-root restore')
    for dest in destinations.values():
        if os.path.lexists(dest):
            raise FileExistsError('Restore destination appeared while staging')
    published = []
    try:
        for role in ROLES:
            _publish_new_directory(stages[role], destinations[role])
            published.append(role)
            _sync_directory(destinations[role].parent)
    except BaseException as exc:
        if published:
            raise PartialThreeRootRestoreError(published) from exc
        raise
    return {'roots': {role: destinations[role] for role in ROLES},
            'files': before['files'], 'sqlite': before['sqlite'],
            'mode': before['mode'], 'dpapi_same_principal_verified': True}


__all__ = ['create_three_root_backup', 'verify_three_root_backup',
           'restore_three_root_backup', 'ThreeRootBackupError',
           'PartialThreeRootRestoreError', 'MANIFEST_NAME', 'ROLES']
