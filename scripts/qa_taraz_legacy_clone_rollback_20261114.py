"""Verify rollback of a migrated real-data clone, never installed Taraz."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taraz_three_root_backup_20261114 import (
    restore_three_root_backup, verify_three_root_backup,
)
from taraz_legacy_workspace_bridge import MARKER, verify_workspace


def run(snapshot: Path, clone: Path) -> dict:
    snapshot, clone = snapshot.resolve(), clone.resolve()
    if clone == (Path(os.environ['APPDATA']) / 'Taraz').resolve():
        raise RuntimeError('Refusing live data rollback')
    verify_workspace(clone / 'roaming_taraz')
    original = verify_three_root_backup(snapshot)
    paths = [clone / ('rollback_' + role) for role in
             ('roaming_taraz', 'local_taraz', 'local_bridge')]
    restored = restore_three_root_backup(snapshot, *paths, offline_acknowledged=True)
    if restored['files'] != original['files'] or restored['sqlite'] != original['sqlite']:
        raise RuntimeError('Restored rollback clone did not match the backup')
    doc = json.loads((snapshot / 'TARAZ_THREE_ROOT_MANIFEST.json').read_text(encoding='utf-8'))
    count = 0
    for role, root in zip(('roaming_taraz', 'local_taraz', 'local_bridge'), paths):
        source_files = doc['roots'][role]['files']
        for entry in source_files:
            digest = hashlib.sha256((root / entry['path']).read_bytes()).hexdigest()
            if digest != entry['sha256']:
                raise RuntimeError('Rollback member hash mismatch')
            count += 1
    if (paths[0] / MARKER).exists():
        raise RuntimeError('Rollback retained migration sidecar')
    report = {'status': 'LEGACY_MARKER_MIGRATION_ROLLBACK_VERIFIED',
              'filesRestored': count, 'sqliteRestored': original['sqlite'],
              'legacyMarkerAbsentAfterRollback': True,
              'installedExeRolledBack': False,
              'interruptedInstallerRolledBack': False,
              'liveDataChanged': False}
    with (clone / 'legacy-rollback-verification.json').open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--clone', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.snapshot, args.clone), sort_keys=True))
