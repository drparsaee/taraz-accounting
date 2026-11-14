"""Read-only full 67-DB/three-root witness after running real frozen Taraz.

The binary is launched separately under a disposable, independently restored
clone. This script never launches an installed app, writes live data, posts a
financial event, or reports private row contents.
"""
from __future__ import annotations

from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import pickle
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taraz_legacy_workspace_bridge import verify_workspace
from taraz_three_root_backup_20261114 import verify_three_root_backup


def _sqlite_rows(path: Path) -> tuple[str, int, int]:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError('Expected regular SQLite member missing')
    result = hashlib.sha256()
    rows = tables = 0
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RuntimeError('SQLite integrity_check failed')
        for name, ddl in db.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"):
            tables += 1
            sum_hash = xor_hash = table_rows = 0
            escaped = '"' + name.replace('"', '""') + '"'
            for row in db.execute('SELECT * FROM ' + escaped):
                digest = int.from_bytes(hashlib.sha256(pickle.dumps(row, protocol=4)).digest(), 'big')
                sum_hash = (sum_hash + digest) % (1 << 256)
                xor_hash ^= digest
                table_rows += 1
            rows += table_rows
            result.update(pickle.dumps((name, ddl, table_rows, sum_hash, xor_hash), protocol=4))
    return result.hexdigest(), tables, rows


def verify(snapshot: Path, clone: Path) -> dict:
    snapshot, clone = snapshot.resolve(), clone.resolve()
    live = (Path(os.environ['APPDATA']) / 'Taraz').resolve()
    if clone == live or live in clone.parents or not clone.is_dir():
        raise RuntimeError('Refusing to inspect the installed live data root')
    doc = json.loads((snapshot / 'TARAZ_THREE_ROOT_MANIFEST.json').read_text(encoding='utf-8'))
    if verify_three_root_backup(snapshot)['mode'] != 'legacy':
        raise RuntimeError('The source backup was not independently verified')
    if subprocess.run(['tasklist.exe', '/FI', 'IMAGENAME eq Taraz.exe', '/FO', 'CSV', '/NH'],
                      capture_output=True, text=True, check=True, timeout=15).stdout.startswith('"Taraz.exe",'):
        raise RuntimeError('Taraz still running; no consistent postflight')
    workspace = verify_workspace(clone / 'roaming_taraz')
    matched_db = matched_files = rows = tables = 0
    for role in ('roaming_taraz', 'local_taraz', 'local_bridge'):
        for record in doc['roots'][role]['files']:
            name = record['path']
            source = snapshot / role / name
            restored = clone / role / name
            if not restored.is_file() or restored.is_symlink():
                raise RuntimeError('Restored original file missing')
            if record['kind'] in ('sqlite', 'sqlite-archive'):
                original, copied = _sqlite_rows(source), _sqlite_rows(restored)
                if original != copied:
                    raise RuntimeError('Restored SQLite records, IDs or schema changed')
                matched_db += 1
                tables += original[1]
                rows += original[2]
            else:
                digest = hashlib.sha256(restored.read_bytes()).hexdigest()
                if digest != record['sha256']:
                    raise RuntimeError('Restored non-SQLite archival file differs')
                matched_files += 1
    installed = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'Taraz' / 'current-version.txt'
    if installed.read_text(encoding='utf-8-sig').strip() != '1.0.4':
        raise RuntimeError('Installed 1.0.4 unexpectedly changed')
    return {
        'status': 'FROZEN_NATIVE_CLONE_POSTFLIGHT_ALL_ORIGINAL_DATA_PRESERVED',
        'originalDbRowMatched': matched_db, 'originalOtherFilesShaMatched': matched_files,
        'originalTablesCompared': tables, 'originalSqlRowsCompared': rows,
        'legacyWorkspaceId': workspace['workspaceId'],
        'ownershipStatus': workspace['ownershipStatus'],
        'ledgerRevision': workspace['ledgerRevision'],
        'allOriginalSnapshotMembersCompared': matched_db + matched_files,
        'installedVersion': '1.0.4', 'productionDataChanged': False,
        'nativeWindowOpenedIndependently': True,
        'frontendDomTraversalVerified': False,
        'installerRollbackVerified': False,
        'snapshotCrossRootAtomicityVerified': False,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--clone', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.snapshot, args.clone)
    out = args.clone / 'legacy-frozen-postflight.json'
    with out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
