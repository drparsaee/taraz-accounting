"""Same-Windows-principal live Taraz backup with held OS deny-write handles.

This is a real-profile backup tool, NOT an installer or an authorization to
migrate a legacy company. The handles exclude ordinary SQLite writers and
in-place edits while all three stores are copied. New files created and then
removed by an uncooperative process cannot be ruled out by inventory checks.
Do not interpret its result as an atomic multi-store VSS snapshot.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager, closing
import ctypes
import hashlib
import json
import os
from pathlib import Path
import pickle
import sqlite3
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from taraz_full_profile_backup_20261114 import _private_new_folder
from taraz_three_root_backup_20261114 import (
    ROLES, _scan, _same_source_inventory, _windows_principal,
    create_three_root_backup, verify_three_root_backup,
    restore_three_root_backup,
)


class RealBackupBlocked(RuntimeError):
    pass


def source_roots() -> dict[str, Path]:
    if os.name != 'nt' or not os.environ.get('APPDATA') or not os.environ.get('LOCALAPPDATA'):
        raise RealBackupBlocked('This backup requires the real Windows principal')
    roaming = Path(os.environ['APPDATA']) / 'Taraz'
    local = Path(os.environ['LOCALAPPDATA'])
    return {'roaming_taraz': roaming,
            'local_taraz': local / 'Taraz',
            'local_bridge': local / 'Madar-Taraz-Bridge'}


def _no_installed_taraz_process() -> None:
    """Refuse real profile writers, including unknown EXE and unknown QA.

    A single *already observed*, immutable, unrelated private QA candidate
    may be resident in another process. It is NOT a live-profile writer and
    cannot access the production roots because all application home paths
    point to its disjoint qa-runtime. Verify that fact, do not merely trust
    TARAZ_QA_MODE=1. This exemption does not approve installing or archiving.
    """
    import psutil
    known = (ROOT.parents[1] / 'MTR-NEXT-UPDATE-CANDIDATES-20261110' /
             'taraz-v1.0.6-aaas' / 'build-5e5253cd7449' / 'binary' / 'Taraz.exe')
    known_sha = 'd4692dfaf66b4de52e778bea59099ad2ea661f4e47493877a4ca9d4b6c322305'
    expected_roaming = (ROOT.parents[1] / 'MTR-NEXT-UPDATE-CANDIDATES-20261110' /
        'taraz-v1.0.6-aaas' / 'fresh-windows-frozen-qa-20261115' /
        'qa-3443357975f2' / 'qa' / 'qa-runtime' / 'roaming')
    original_owner = psutil.Process().username().casefold()
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').casefold() != 'taraz.exe':
            continue
        try:
            own = Path(process.exe()).resolve()
            environment = process.environ()
            roaming = Path(environment.get('APPDATA', '/unavailable')).resolve()
            local = Path(environment.get('LOCALAPPDATA', '/unavailable')).resolve()
            data = Path(environment.get('TARAZ_QA_DATA_DIR', '/unavailable')).resolve()
            expected_local = expected_roaming.parent / 'localappdata'
            exempt = (
                own == known.resolve() and known.is_file() and
                hashlib.sha256(known.read_bytes()).hexdigest() == known_sha and
                process.username().casefold() == original_owner and
                environment.get('TARAZ_QA_MODE') == '1' and
                roaming == expected_roaming.resolve() and
                local == expected_local.resolve() and
                data == (expected_roaming / 'Taraz').resolve())
        except (psutil.Error, OSError, ValueError):
            exempt = False
        if not exempt:
            raise RealBackupBlocked('Installed/unknown Taraz writer exists; close it normally')


@contextmanager
def _hold_windows_read_only(path: Path):
    """Deny new and existing write/delete opens, allowing concurrent readers.

    Holding this handle while SQLite's read-only backup runs is validated on
    Windows. Do not lock -shm/-wal: read-only SQLite needs shared-memory locks.
    Its main .sqlite3 file is denied write sharing instead.
    """
    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    dll.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.c_uint32, ctypes.c_void_p]
    dll.CreateFileW.restype = ctypes.c_void_p
    dll.CloseHandle.argtypes = [ctypes.c_void_p]
    dll.CloseHandle.restype = ctypes.c_int
    # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL
    handle = dll.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise RealBackupBlocked('A source file has a conflicting open writer or access restriction')
    try:
        yield
    finally:
        if not dll.CloseHandle(handle):
            raise RealBackupBlocked('Unable to release source file handle')


def _db_rows_digest(path: Path) -> tuple[str, int, int]:
    """Order-independent content proof without exposing a real financial row."""
    database_digest = hashlib.sha256()
    row_count, table_count = 0, 0
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('PRAGMA busy_timeout=10000')
        tables = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        for name, ddl in tables:
            table_count += 1
            table_sum, table_xor, rows = 0, 0, 0
            quoted = '"' + name.replace('"', '""') + '"'
            for row in conn.execute('SELECT * FROM ' + quoted):
                digest = int.from_bytes(hashlib.sha256(pickle.dumps(row, protocol=4)).digest(), 'big')
                table_sum = (table_sum + digest) % (1 << 256)
                table_xor ^= digest
                rows += 1
            row_count += rows
            database_digest.update(pickle.dumps((name, ddl, rows, table_sum, table_xor), protocol=4))
        if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RealBackupBlocked('Source or restored SQLite integrity failed')
    return database_digest.hexdigest(), table_count, row_count


def _compare_database_rows(source: dict[str, Path], clones: dict[str, Path], scans) -> dict:
    matched, tables, rows = 0, 0, 0
    for role, (directories, files, sidecars) in scans.items():
        for relative in files:
            if not relative.endswith(('.sqlite3', '.sqlite', '.db')):
                continue
            before = _db_rows_digest(source[role] / relative)
            after = _db_rows_digest(clones[role] / relative)
            if before != after:
                raise RealBackupBlocked('A restored SQLite differs in table rows, IDs or schema')
            matched += 1
            tables += before[1]
            rows += before[2]
    return {'databasesWithMatchingRows': matched,
            'tablesWithMatchingRows': tables,
            'totalSqlRowsCompared': rows}


def run(dest: Path) -> dict:
    _windows_principal()
    roots = source_roots()
    if any(not path.is_dir() for path in roots.values()):
        raise RealBackupBlocked('One of the three actual data roots does not exist')
    install = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'Taraz'
    pointer = install / 'current-version.txt'
    if not pointer.is_file() or pointer.read_text(encoding='utf-8-sig').strip() != '1.0.4':
        raise RealBackupBlocked('Active installation is not the expected v1.0.4')
    _no_installed_taraz_process()
    dest = Path(dest)
    if not dest.is_absolute() or dest.exists() or not dest.parent.is_dir():
        raise RealBackupBlocked('Create-only absolute destination with existing parent required')
    for source in roots.values():
        if source.resolve() == dest.resolve() or source.resolve() in dest.resolve().parents or dest.resolve() in source.resolve().parents:
            raise RealBackupBlocked('Backup must not overlap live data')
    start = {role: _scan(root) for role, root in roots.items()}
    stage = 'LOCKING'
    total_members = sum(len(s[1]) + len(s[2]) for s in start.values())
    total_bytes = sum((roots[role] / name).stat().st_size
                      for role, scan in start.items() for name in (list(scan[1]) + list(scan[2])))
    # The lock acquisition is all-or-nothing. No source file is modified.
    with ExitStack() as locks:
        for role in ROLES:
            for member in start[role][1]:
                locks.enter_context(_hold_windows_read_only(roots[role] / member))
        if any(not _same_source_inventory(start[role], _scan(roots[role]))
               for role in ROLES):
            raise RealBackupBlocked('Source inventory changed while obtaining writer locks')
        _no_installed_taraz_process()
        _private_new_folder(dest)
        try:
            stage = 'SNAPSHOTTING'
            backup = create_three_root_backup(*(roots[role] for role in ROLES),
                                              dest / 'snapshot', offline_acknowledged=True)
            stage = 'INDEPENDENT_READBACK'
            independent = verify_three_root_backup(dest / 'snapshot')
            if backup != independent:
                raise RealBackupBlocked('Independent backup readback differs')
            stage = 'RESTORING_CLONE'
            clone_paths = {role: dest / ('restore_' + role) for role in ROLES}
            clone = restore_three_root_backup(dest / 'snapshot',
                *(clone_paths[role] for role in ROLES), offline_acknowledged=True)
            if clone['files'] != backup['files'] or clone['sqlite'] != backup['sqlite']:
                raise RealBackupBlocked('Restored clone inventory differs from snapshot')
            stage = 'ROW_COMPARISON'
            comparisons = _compare_database_rows(roots, clone_paths, start)
            if any(not _same_source_inventory(start[role], _scan(roots[role]))
                   for role in ROLES):
                raise RealBackupBlocked('A live root changed during cross-root restore/compare')
            if pointer.read_text(encoding='utf-8-sig').strip() != '1.0.4':
                raise RealBackupBlocked('Installed pointer changed while backing up')
            result = {'status': 'VERIFIED_SAME_PRINCIPAL_SNAPSHOT_AND_ISOLATED_RESTORE',
                'sourceFileCount': total_members, 'sourceBytes': total_bytes,
                'snapshotFileCount': backup['files'], 'snapshotSQLite': backup['sqlite'],
                'mode': backup['mode'], 'dpapiSamePrincipalReadback': backup['dpapi_same_principal_verified'],
                'sourceWriteDenialHeldForAllDataFiles': True,
                'crossRootAtomicVssSnapshot': False,
                'interruptedCreateDeleteWriterExcluded': False,
                'recoveryOnOtherDeviceVerified': False, 'installedVersionUnchanged': True,
                **comparisons}
            report = dest / 'verification.json'
            with report.open('x', encoding='utf-8') as out:
                json.dump(result, out, sort_keys=True, indent=2)
                out.flush()
                os.fsync(out.fileno())
            return result
        except BaseException as exc:
            report = dest / 'blocked.json'
            with report.open('x', encoding='utf-8') as out:
                json.dump({'status': 'BLOCKED', 'stage': stage,
                           'errorType': type(exc).__name__,
                           'error': str(exc)[:300]}, out, indent=2)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True,
                        help='Create-only private folder outside any live data root')
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.destination), sort_keys=True))
        return 0
    except BaseException as exc:
        print(json.dumps({'status': 'BLOCKED', 'errorType': type(exc).__name__,
                          'reason': str(exc)[:300]}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
