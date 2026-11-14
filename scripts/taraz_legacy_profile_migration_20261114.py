"""OFFLINE, synthetic-only migration *rehearsal*, never an upgrade/installer.

An unregistered legacy Taraz book has no trustworthy company-id mapping. This
utility requires a previously registered company, a pre-existing matching
identity document and an authenticated administrator of that company. A legacy
book without those proofs is BLOCKED; it does not manufacture an admin/tenant.

Only disposable directories inside this worktree's ``tests/output`` are
accepted; this never accesses a user's Windows APPDATA/LOCALAPPDATA profile.
The synthetic marker is a test-fixture declaration, NOT provenance
or a cryptographic authorization for migrating real financial records.

Both the clone and its independently materialized backup are read-only inputs.
The destination is CREATE-ONLY and marked REHEARSAL_ONLY. SQLite files are
copied byte-for-byte, preserving the original pages, IDs and history. This
requires a quiescent source: WAL, SHM, rollback journals and lock files block.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import sys

# Direct invocation from scripts/ must resolve the project modules exactly as
# `python -m scripts.taraz_legacy_profile_migration_20261114` does.  This does
# not relax the rehearsal-only path and identity guards below.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from standalone_accounting_backup import _check_snapshot, StandaloneBackupError
from standalone_accounting import StandaloneAccountingError
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_identity import IdentityError, LocalCompanyIdentity, validate_identity_document


SOURCE_MARKER = '.taraz-synthetic-legacy-fixture.json'
BACKUP_MARKER = 'TARAZ_LEGACY_REHEARSAL_BACKUP.json'
REHEARSAL_MARKER = 'TARAZ_REHEARSAL_ONLY.json'
_SOURCE_FORMAT = 'taraz-synthetic-legacy-fixture'
_BACKUP_FORMAT = 'taraz-legacy-offline-rehearsal-backup'
_OUTPUT_FORMAT = 'taraz-legacy-offline-rehearsal'
_DB_EXT = ('.sqlite3', '.sqlite', '.db')
_HEX = re.compile(r'[0-9a-f]{32}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_MAX_FILES = 4096


class MigrationBlocked(RuntimeError):
    """Fail closed. No production profile is ever activated by this module."""


def _temp_path(path: Path, *, existing: bool) -> Path:
    path = Path(path)
    if not path.is_absolute() or path.name in ('', '.', '..'):
        raise MigrationBlocked('Explicit absolute synthetic directory required')
    temp = (Path(__file__).resolve().parent.parent / 'tests' / 'output').resolve()
    canonical = path.resolve(strict=False)
    if temp not in canonical.parents:
        raise MigrationBlocked('Only isolated disposable worktree QA output is permitted')
    for part in (path, *path.parents):
        if os.path.lexists(part) and (part.is_symlink() or
                getattr(part.lstat(), 'st_file_attributes', 0) &
                getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
            raise MigrationBlocked('Linked or reparse-point path refused')
    if existing and not path.is_dir():
        raise MigrationBlocked('Required synthetic directory is missing')
    if not existing and os.path.lexists(path):
        raise FileExistsError('CREATE-ONLY destination already exists')
    return path


def _separate(*paths: Path) -> None:
    absolute = [p.resolve(strict=False) for p in paths]
    for n, left in enumerate(absolute):
        for right in absolute[n + 1:]:
            if left == right or left in right.parents or right in left.parents:
                raise MigrationBlocked('Source, backup, authority and target must be disjoint')


def _relative(value: str) -> Path:
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value or
            value.startswith('/') or '\x00' in value or any(
                part in ('', '.', '..') or part.endswith((' ', '.')) or
                any(ord(c) < 32 for c in part) for part in value.split('/'))):
        raise MigrationBlocked('Unsafe path in rehearsal inventory')
    return Path(*value.split('/'))


def _regular(path: Path) -> os.stat_result:
    if path.is_symlink() or not path.is_file():
        raise MigrationBlocked('Missing or linked rehearsal member')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            getattr(info, 'st_file_attributes', 0) &
            getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
        raise MigrationBlocked('Nonregular or hardlinked rehearsal member')
    return info


def _digest(path: Path) -> tuple[str, int]:
    checksum, size = hashlib.sha256(), 0
    with path.open('rb') as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b''):
            checksum.update(chunk)
            size += len(chunk)
    return checksum.hexdigest(), size


def _scan(root: Path, *, skip: frozenset[str] = frozenset()) -> tuple[list[str], list[dict]]:
    directories, files = [], []
    for here, subs, names in os.walk(root, followlinks=False):
        folder = Path(here)
        if folder.is_symlink():
            raise MigrationBlocked('Linked rehearsal directory')
        for name in subs:
            member = folder / name
            _relative(member.relative_to(root).as_posix())
            if member.is_symlink() or not member.is_dir() or (
                    getattr(member.lstat(), 'st_file_attributes', 0) &
                    getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
                raise MigrationBlocked('Unsafe rehearsal folder')
            directories.append(member.relative_to(root).as_posix())
        for name in names:
            member = folder / name
            key = member.relative_to(root).as_posix()
            _relative(key)
            _regular(member)
            if (name.endswith(('-wal', '-shm', '-journal', '.lock')) or
                    name in ('.company-registry.lock', '.standalone-company-active.lock',
                             '.taraz-session.lock', '.standalone-accounting-auto.lock')):
                raise MigrationBlocked('Concurrent SQLite state or lock file: offline input required')
            if key not in skip:
                checksum, size = _digest(member)
                files.append({'path': key, 'sha256': checksum, 'size': size})
            if len(files) > _MAX_FILES:
                raise MigrationBlocked('Rehearsal inventory too large')
    names = directories + [item['path'] for item in files]
    if len(names) != len({item.casefold() for item in names}):
        raise MigrationBlocked('Case-colliding rehearsal paths')
    return sorted(directories), sorted(files, key=lambda item: item['path'])


def _json(path: Path) -> dict:
    if _regular(path).st_size > 2 * 1024 * 1024:
        raise MigrationBlocked('Oversized rehearsal manifest')
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise MigrationBlocked('Missing or invalid rehearsal manifest') from exc
    if type(doc) is not dict:
        raise MigrationBlocked('Invalid rehearsal manifest format')
    return doc


def _synthetic(root: Path) -> None:
    if _json(root / SOURCE_MARKER) != {'format': _SOURCE_FORMAT,
                                         'version': 1, 'synthetic': True}:
        raise MigrationBlocked('Explicit synthetic fixture marker required')
    if (root / 'companies.json').exists() or (root / 'books').exists():
        raise MigrationBlocked('Registered company profile must use full-profile backup')
    if not (root / 'standalone-accounting.sqlite3').is_file():
        raise MigrationBlocked('Historical accounting ledger is required')


def _valid_sqlite(root: Path, files: list[dict]) -> None:
    for item in files:
        path = root / _relative(item['path'])
        if not path.name.endswith(_DB_EXT):
            continue
        try:
            # Immutable read disables even creation of SQLite WAL/SHM sidecars
            # on the source clone. Scan already rejected existing sidecars.
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1',
                                         uri=True, isolation_level=None)) as db:
                db.execute('PRAGMA query_only=ON')
                if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise MigrationBlocked('Corrupt SQLite file: ' + item['path'])
                if path.name == 'standalone-accounting.sqlite3':
                    _check_snapshot(db)
        except (sqlite3.Error, StandaloneBackupError, StandaloneAccountingError, ValueError, KeyError,
                AssertionError) as exc:
            raise MigrationBlocked('Invalid SQLite data/history: ' + item['path']) from exc


def _copy_exact(src: Path, target: Path, descriptor: dict) -> None:
    before = _regular(src)
    stamp = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
             before.st_ctime_ns)
    if _digest(src) != (descriptor['sha256'], descriptor['size']):
        raise MigrationBlocked('Source changed before copy')
    with src.open('rb') as reader, target.open('xb') as writer:
        for block in iter(lambda: reader.read(1024 * 1024), b''):
            writer.write(block)
        writer.flush()
        os.fsync(writer.fileno())
    after = _regular(src)
    if (stamp != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                  after.st_ctime_ns) or _digest(src) !=
            (descriptor['sha256'], descriptor['size']) or
            _digest(target) != (descriptor['sha256'], descriptor['size'])):
        raise MigrationBlocked('Concurrent modification or copy corruption')


def _write_once(target: Path, data: dict) -> None:
    with target.open('xb') as stream:
        stream.write(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                separators=(',', ':')).encode('utf-8'))
        stream.flush()
        os.fsync(stream.fileno())


def _publish_new_directory(stage: Path, destination: Path) -> None:
    """Atomic CREATE-ONLY publication, refusing platforms without this primitive."""
    if os.path.lexists(destination):
        raise FileExistsError('Rehearsal destination was allocated concurrently')
    if os.name == 'nt':
        os.rename(stage, destination)  # Windows MoveFile never replaces a directory.
    elif sys.platform.startswith('linux'):
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, 'renameat2', None)
        if renameat2 is None:
            raise MigrationBlocked('Atomic create-only rename unavailable')
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                              ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(stage), -100, os.fsencode(destination), 1):
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
    else:
        raise MigrationBlocked('Platform lacks verified atomic create-only publication')


def create_legacy_rehearsal_backup(source_clone: Path, backup_dir: Path, *,
                                   offline_acknowledged: bool = False,
                                   synthetic_only: bool = False) -> dict:
    """Copy a disposable, quiescent legacy clone into a completed SHA256 backup."""
    if offline_acknowledged is not True or synthetic_only is not True:
        raise MigrationBlocked('Explicit OFFLINE and SYNTHETIC declarations required')
    source = _temp_path(Path(source_clone), existing=True)
    backup = _temp_path(Path(backup_dir), existing=False)
    _temp_path(backup.parent, existing=True)
    _separate(source, backup)
    _synthetic(source)
    directories, inventory = _scan(source)
    _valid_sqlite(source, inventory)
    backup.mkdir(mode=0o700)
    for name in directories:
        (backup / _relative(name)).mkdir(mode=0o700)
    for entry in inventory:
        _copy_exact(source / _relative(entry['path']),
                    backup / _relative(entry['path']), entry)
    if _scan(source) != (directories, inventory):
        raise MigrationBlocked('Source clone changed while backing up')
    manifest = {'format': _BACKUP_FORMAT, 'version': 1,
                'directories': directories, 'files': inventory}
    _write_once(backup / BACKUP_MARKER, manifest)
    verify_legacy_rehearsal_backup(source, backup)
    return manifest


def verify_legacy_rehearsal_backup(source_clone: Path, backup_dir: Path) -> dict:
    source = _temp_path(Path(source_clone), existing=True)
    backup = _temp_path(Path(backup_dir), existing=True)
    _separate(source, backup)
    _synthetic(source)
    manifest = _json(backup / BACKUP_MARKER)
    if (set(manifest) != {'format', 'version', 'directories', 'files'} or
            manifest['format'] != _BACKUP_FORMAT or manifest['version'] != 1 or
            type(manifest['directories']) is not list or type(manifest['files']) is not list):
        raise MigrationBlocked('Untrusted backup completion marker')
    expected = (manifest['directories'], manifest['files'])
    if _scan(source) != expected or _scan(backup, skip=frozenset({BACKUP_MARKER})) != expected:
        raise MigrationBlocked('Source or backup changed after SHA256 snapshot')
    _valid_sqlite(source, expected[1])
    _valid_sqlite(backup, expected[1])
    identity = source / 'local-users.json'
    if identity.exists():
        try:
            validate_identity_document(_json(identity))
        except IdentityError as exc:
            raise MigrationBlocked('Invalid original identity membership') from exc
    return manifest


def _rehearsal_inventory(backup: Path, authority: Path, company_id: str,
                         source: dict) -> tuple[list[str], list[dict]]:
    book = authority / 'books' / company_id
    auth_paths = _scan(book)
    if auth_paths != ([], [{'path': 'local-users.json',
                             'sha256': _digest(book / 'local-users.json')[0],
                             'size': _digest(book / 'local-users.json')[1]}]):
        raise MigrationBlocked('Authority book must be identity-only; existing data cannot be merged')
    originals = {x['path']: x for x in source['files']}
    if any(Path(name).name == 'taraz-ai-chat.sqlite3' for name in originals):
        # Chat payloads and action-key receipts use Windows DPAPI with a
        # tenant:user scope. The unregistered profile supplies no trustworthy
        # binding proof for the new tenant, so preserve it by refusing the
        # rehearsal. A separate DPAPI same-principal/tenant gate is needed.
        raise MigrationBlocked('DPAPI AI chat tenant/Windows binding unverified: BLOCKED')
    if 'local-users.json' not in originals:
        raise MigrationBlocked('BLOCKED: legacy ledger has no attributable existing identity')
    if _digest(book / 'local-users.json') != (
            originals['local-users.json']['sha256'], originals['local-users.json']['size']):
        raise MigrationBlocked('BLOCKED: authority identity does not match legacy identity')
    try:
        validate_identity_document(_json(book / 'local-users.json'))
    except IdentityError as exc:
        raise MigrationBlocked('Invalid authorized identity membership') from exc
    dirs = ['books', 'books/' + company_id] + [
        'books/' + company_id + '/' + name for name in source['directories']]
    company_sha, company_size = _digest(authority / 'companies.json')
    files = [{'path': 'companies.json', 'sha256': company_sha, 'size': company_size}]
    files += [{'path': 'books/' + company_id + '/' + x['path'],
               'sha256': x['sha256'], 'size': x['size']} for x in source['files']]
    return sorted(dirs), sorted(files, key=lambda x: x['path'])


def rehearse_legacy_migration(source_clone: Path, backup_dir: Path,
                             authority_hub: Path, destination: Path, *,
                             company_id: str, administrator: LocalCompanyIdentity,
                             administrator_token: str, expected_ledger_sha256: str,
                             offline_acknowledged: bool = False,
                             synthetic_only: bool = False) -> dict:
    """Publish a new synthetic profile only after all authorization gates pass."""
    if offline_acknowledged is not True or synthetic_only is not True:
        raise MigrationBlocked('Explicit OFFLINE and SYNTHETIC declarations required')
    source = _temp_path(Path(source_clone), existing=True)
    backup = _temp_path(Path(backup_dir), existing=True)
    authority = _temp_path(Path(authority_hub), existing=True)
    dest = _temp_path(Path(destination), existing=False)
    _temp_path(dest.parent, existing=True)
    _separate(source, backup, authority, dest)
    if not isinstance(company_id, str) or not _HEX.fullmatch(company_id):
        raise MigrationBlocked('Existing explicit registered company ID required')
    if not isinstance(expected_ledger_sha256, str) or not _SHA.fullmatch(expected_ledger_sha256):
        raise MigrationBlocked('Explicit expected ledger SHA256 required')
    verified = verify_legacy_rehearsal_backup(source, backup)
    registry = StandaloneCompanyRegistry(authority)
    companies = registry.list_companies()
    if len(companies) != 1 or companies[0]['id'] != company_id:
        raise MigrationBlocked('No unique, pre-existing registered company binding')
    book = registry.company_data_directory(company_id)
    if (not isinstance(administrator, LocalCompanyIdentity) or
            administrator.root.resolve() != book.resolve()):
        raise MigrationBlocked('Existing authority identity object required')
    try:
        operator = administrator.require_session(administrator_token, 'admin')['username']
    except (PermissionError, ValueError) as exc:
        raise MigrationBlocked('Authenticated existing company administrator required') from exc
    source_files = {item['path']: item for item in verified['files']}
    if source_files['standalone-accounting.sqlite3']['sha256'] != expected_ledger_sha256:
        raise MigrationBlocked('Explicit ledger digest does not match source evidence')
    directories, files = _rehearsal_inventory(backup, authority, company_id, verified)
    stage = dest.parent / ('.taraz-legacy-rehearsal-stage-' + secrets.token_hex(16))
    _temp_path(stage, existing=False)
    stage.mkdir(mode=0o700)
    nonce = secrets.token_hex(24)
    marker = {'format': _OUTPUT_FORMAT, 'version': 1, 'status': 'REHEARSAL_ONLY',
              'stage': str(stage), 'destination': str(dest), 'rehearsal_id': nonce,
              'company_id': company_id, 'operator': operator,
              'source_ledger_sha256': expected_ledger_sha256,
              'backup_manifest_sha256': _digest(backup / BACKUP_MARKER)[0],
              'directories': directories, 'files': files}
    # Marker is first so a crashed partial stage can be reviewed and rolled back.
    _write_once(stage / REHEARSAL_MARKER, marker)
    for name in directories:
        (stage / _relative(name)).mkdir(mode=0o700)
    for entry in files:
        rel = entry['path']
        original = authority / rel if rel == 'companies.json' else (
            backup / _relative(rel[len('books/' + company_id + '/'):]))
        _copy_exact(original, stage / _relative(rel), entry)
    if _scan(stage, skip=frozenset({REHEARSAL_MARKER})) != (directories, files):
        raise MigrationBlocked('Staged rehearsal inventory mismatch')
    if (verify_legacy_rehearsal_backup(source, backup) != verified or
            _digest(authority / 'companies.json') !=
            next((entry['sha256'], entry['size']) for entry in files
                 if entry['path'] == 'companies.json') or
            _digest(book / 'local-users.json') !=
            (source_files['local-users.json']['sha256'], source_files['local-users.json']['size']) or
            _scan(book) != ([], [source_files['local-users.json']]) or
            registry.list_companies() != companies):
        raise MigrationBlocked('Inputs changed before publishing rehearsal')
    _publish_new_directory(stage, dest)
    return {'destination': str(dest), 'rehearsal_id': nonce,
            'marker_sha256': _digest(dest / REHEARSAL_MARKER)[0],
            'company_id': company_id, 'files': len(files),
            'status': 'REHEARSAL_ONLY'}


def rollback_rehearsal(path: Path, *, rehearsal_id: str, marker_sha256: str) -> dict:
    """Remove only an unchanged, owned synthetic published/partial output.

    Extra, modified or linked content BLOCKS rollback. Source and backup are
    never deleted. The caller must supply the exact returned marker hash/id.
    """
    folder = _temp_path(Path(path), existing=True)
    if not isinstance(marker_sha256, str) or not _SHA.fullmatch(marker_sha256):
        raise MigrationBlocked('Exact rollback marker SHA256 required')
    if _digest(folder / REHEARSAL_MARKER)[0] != marker_sha256:
        raise MigrationBlocked('Rollback ownership marker changed')
    marker = _json(folder / REHEARSAL_MARKER)
    if (marker.get('format') != _OUTPUT_FORMAT or marker.get('version') != 1 or
            marker.get('status') != 'REHEARSAL_ONLY' or
            marker.get('rehearsal_id') != rehearsal_id or
            str(folder) not in (marker.get('stage'), marker.get('destination'))):
        raise MigrationBlocked('Rollback ownership not proven')
    allowed_files = {item['path']: item for item in marker['files']}
    permitted_dirs = set(marker['directories'])
    directories, actual = _scan(folder, skip=frozenset({REHEARSAL_MARKER}))
    if not set(directories) <= permitted_dirs or any(
            item['path'] not in allowed_files or item != allowed_files[item['path']]
            for item in actual):
        raise MigrationBlocked('Rollback refused: unknown or modified files')
    if str(folder) == marker['destination'] and (
            directories != marker['directories'] or actual != marker['files']):
        raise MigrationBlocked('Published rehearsal has changed')
    # Reverify immediately before each unlink; this still assumes offline use.
    for entry in actual:
        file = folder / _relative(entry['path'])
        _regular(file)
        if _digest(file) != (entry['sha256'], entry['size']):
            raise MigrationBlocked('Rollback member changed during removal')
        file.unlink()
    (folder / REHEARSAL_MARKER).unlink()
    for name in sorted(directories, key=lambda x: (-x.count('/'), -len(x))):
        (folder / _relative(name)).rmdir()
    folder.rmdir()
    return {'status': 'ROLLED_BACK', 'files_removed': len(actual), 'source_preserved': True}


__all__ = ['MigrationBlocked', 'SOURCE_MARKER', 'BACKUP_MARKER', 'REHEARSAL_MARKER',
           'create_legacy_rehearsal_backup', 'verify_legacy_rehearsal_backup',
           'rehearse_legacy_migration', 'rollback_rehearsal']
