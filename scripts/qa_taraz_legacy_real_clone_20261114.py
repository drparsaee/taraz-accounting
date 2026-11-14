"""Real restored-clone acceptance; read user data without exposing its rows.

Never runs on APPDATA, creates financial events, launches an installer, or
sets up a fake administrator. Captures precise status, counts and SHA digests.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from standalone_accounting import _decode_checked
from taraz_desktop import open_identity_pending_legacy_workspace
from taraz_legacy_workspace_bridge import verify_workspace
from taraz_three_root_backup_20261114 import verify_three_root_backup


def _book(path: Path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON')
        if conn.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise RuntimeError('Invalid accounting book SQLite integrity')
        record = conn.execute('SELECT revision,state,digest FROM standalone_accounting').fetchone()
        if record is None:
            raise RuntimeError('Accounting book missing persisted state')
        revision, payload, digest = record
        state = _decode_checked(payload, digest)
    events = state['events']
    return {'revision': revision, 'stateDigest': digest,
            'eventCount': len(events), 'eventIdDigest': hashlib.sha256(json.dumps(
                [e['eventId'] for e in events], ensure_ascii=False,
                separators=(',', ':')).encode()).hexdigest(),
            'journalEventCount': sum(e['command']['type'].startswith('journal.') for e in events)}


def _view(api) -> dict:
    result = api.standaloneAccountingRead()
    view = result['view']
    collections = {}
    for name in ('parties', 'items', 'invoices', 'proformas', 'bills',
                 'journals', 'payments', 'cheques', 'orders'):
        group = view.get(name)
        if isinstance(group, dict):
            ids = sorted(str(identifier) for identifier in group)
        elif isinstance(group, list):
            ids = [str(item.get('id')) for item in group if isinstance(item, dict)]
        else:
            continue
        collections[name] = {
            'count': len(ids),
            'stableIdDigest': hashlib.sha256(json.dumps(ids, ensure_ascii=False).encode()).hexdigest()}
    return {'revision': result['revision'], 'collections': collections,
            'role': result['currentUser']['role'],
            'canManage': result['capabilities']['canManage'],
            'canDraft': result['capabilities']['canDraft'],
            'legacyIdentity': view['legacyWorkspaceState']}


def run(snapshot: Path, clone: Path) -> dict:
    if os.name != 'nt':
        raise RuntimeError('Real DPAPI backup and Windows viewer required')
    snapshot = Path(snapshot).resolve()
    clone = Path(clone).resolve()
    real_home = Path(os.environ['APPDATA']) / 'Taraz'
    if clone == real_home.resolve() or real_home.resolve() in clone.parents:
        raise RuntimeError('Refusing real profile acceptance against APPDATA')
    verify_three_root_backup(snapshot)
    root = clone / 'roaming_taraz'
    workspace = verify_workspace(root)
    baseline = _book(snapshot / 'roaming_taraz' / 'standalone-accounting.sqlite3')
    before = _book(root / 'standalone-accounting.sqlite3')
    if baseline != before:
        raise RuntimeError('Real restored clone already differs from backed up ledger')
    with patch('taraz_desktop.taraz_data_root', return_value=root):
        first, first_identity, first_token = open_identity_pending_legacy_workspace(root)
        try:
            first_view = _view(first)
            with __import__('unittest').TestCase().assertRaises(PermissionError):
                first.standaloneAccountingCommand({'command': {
                    'type': 'party.register', 'eventId': 'qa-refused',
                    'partyId': 'qa-refused', 'name': 'QA REFUSED',
                    'kind': 'customer'}, 'expectedRevision': before['revision']})
        finally:
            first_identity.logout(first_token)
        with __import__('unittest').TestCase().assertRaises(PermissionError):
            first.standaloneAccountingRead()
        second, second_identity, second_token = open_identity_pending_legacy_workspace(root)
        try:
            after_restart = _view(second)
        finally:
            second_identity.logout(second_token)
    after = _book(root / 'standalone-accounting.sqlite3')
    if baseline != after or first_view != after_restart:
        raise RuntimeError('Financial data or permissions changed during viewer restart')
    if first_view['canManage'] or first_view['canDraft'] or first_view['role'] != 'viewer':
        raise RuntimeError('Unclaimed company unexpectedly granted financial rights')
    return {'status': 'REAL_CLONE_LEGACY_VIEWER_READBACK_PASS',
            'workspaceId': workspace['workspaceId'],
            'identityStatus': workspace['identityStatus'],
            'ownershipStatus': workspace['ownershipStatus'],
            'accounting': after, 'view': first_view,
            'secondSessionEqual': True, 'financialMutationDenied': True,
            'productionProfileUsed': False, 'financialEventCreated': False,
            'nativeUiVerified': False, 'frozenExeVerified': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--clone', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.snapshot, args.clone)
    path = args.clone / 'legacy-real-viewer-verification.json'
    with path.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, sort_keys=True, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({k: v for k, v in result.items() if k not in ('view',)},
                     sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
