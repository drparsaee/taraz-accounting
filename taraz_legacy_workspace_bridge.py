"""Versioned identity-pending workspace for a single proven legacy Taraz book.

Not a company registry, ownership proof, role grant, import, or finance write.
Only an independently restored clone may be migrated by this module. The
original 1.0.4 ledger and immutable event history remain byte-for-byte intact.
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
import time

from standalone_accounting import _decode_checked


MARKER = 'legacy-workspace.json'
VERSION = 1
LABEL = 'دفتر قدیمی تراز (مالکیت تأییدنشده)'
_HEX = re.compile(r'[0-9a-f]{64}\Z')


class LegacyBridgeBlocked(PermissionError):
    pass


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and not (
        getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def _inventory(root: Path) -> dict[str, str]:
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise LegacyBridgeBlocked('An existing absolute nonlinked legacy root is required')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or (getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
            raise LegacyBridgeBlocked('Linked member in legacy root')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def inspect_legacy_book(root: Path) -> dict:
    """Read exact legacy revision and events, without inventing ownership.

    No company name or potentially identifying accounting content is returned.
    All digests bind the current state; only the first-event anchor is used for
    a stable workspace ID, so later legitimate journal activity cannot change it.
    """
    root = Path(root)
    if ((root / 'companies.json').exists() or (root / 'books').exists() or
            (root / 'local-users.json').exists()):
        raise LegacyBridgeBlocked('Registered or ambiguous profile is not legacy')
    path = root / 'standalone-accounting.sqlite3'
    if not _regular(path):
        raise LegacyBridgeBlocked('Real legacy accounting book is missing')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON')
        if conn.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise LegacyBridgeBlocked('Accounting SQLite integrity failed')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version != 1:
            raise LegacyBridgeBlocked('Unrecognized legacy accounting schema')
        rows = conn.execute('SELECT revision,state,digest FROM standalone_accounting').fetchall()
        if len(rows) != 1:
            raise LegacyBridgeBlocked('Expected exactly one legacy accounting state')
        revision, payload, digest = rows[0]
    state = _decode_checked(payload, digest)
    events = state['events']
    if not events or revision != len(events):
        raise LegacyBridgeBlocked('Incomplete legacy event chain')
    # This ID identifies a book, not a legal company, user, or owner.
    first = json.dumps(events[0], sort_keys=True, ensure_ascii=False,
                       separators=(',', ':')).encode('utf-8')
    anchor = hashlib.sha256(first).hexdigest()
    workspace_id = hashlib.sha256(('taraz-legacy-book-v1:' + anchor).encode()).hexdigest()[:32]
    ids = [event['eventId'] for event in events]
    history_digest = hashlib.sha256(json.dumps(ids, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    # Extract *source presence*, not claimed legal names or private document
    # bodies. A printed invoice may contain an issuer label but that is still
    # not legal authority to register a company's owner or administrator.
    candidate_sources = []
    for key in ('companyProfile', 'issuerProfile', 'companySettings'):
        entry = state.get(key)
        if not isinstance(entry, dict):
            continue
        for field in ('legalName', 'companyName', 'issuerName'):
            value = entry.get(field)
            if isinstance(value, str) and value.strip():
                candidate_sources.append({'source': 'accounting state / ' + key + '/' + field,
                    'valueSha256': hashlib.sha256(value.strip().encode('utf-8')).hexdigest(),
                    'status': 'reported_unverified'})
    invoice_issuers = set()
    invoice_collection = state.get('invoices')
    if isinstance(invoice_collection, dict):
        for invoice in invoice_collection.values():
            if not isinstance(invoice, dict):
                continue
            for key in ('issuerLegalName', 'issuerName'):
                name = invoice.get(key)
                if isinstance(name, str) and name.strip():
                    invoice_issuers.add(hashlib.sha256(name.strip().encode()).hexdigest())
    for issuer_digest in sorted(invoice_issuers):
        candidate_sources.append({'source': 'accounting state / invoice issuer header',
            'valueSha256': issuer_digest, 'status': 'reported_unverified'})
    actor_count = len({str(event['actor']) for event in events})
    # Never treat customer/party names, invoice recipients, or historical
    # Windows account names as evidence of legal ownership or admin authority.
    evidence = [
        {'field': 'workspaceId', 'source': 'standalone-accounting.sqlite3 / first immutable event',
         'status': 'derived_book_identifier_not_legal_identity', 'sha256': anchor},
        {'field': 'ledgerRevision', 'source': 'standalone-accounting.sqlite3 / revision',
         'status': 'verified'},
        {'field': 'documentIdsAndEvents', 'source': 'standalone-accounting.sqlite3 / state.events',
         'status': 'verified', 'sha256': history_digest},
        {'field': 'companyLegalName', 'source': 'accounting profile and issuer headers',
         'status': 'unverified_do_not_assume', 'reportedCandidates': candidate_sources},
        {'field': 'companyOwner', 'source': 'no authenticated historical ownership registry',
         'status': 'unclaimed'},
        {'field': 'companyAdministrator', 'source': 'local-users.json absent',
         'status': 'unverified_no_user_created', 'historicalDistinctEventActors': actor_count},
        {'field': 'windowsPrincipal', 'source': 'local operating-system session',
         'status': 'device_context_only_not_ownership'},
        {'field': 'printTemplatesAndSettings', 'source': 'three-root backup / file manifest',
         'status': 'preserved_as_original_not_reassigned'},
        {'field': 'madarOutboxAssociation', 'source': 'Madar-Taraz-Bridge / pending, reviewed, send-intents',
         'status': 'preserved_without_claiming_verified_tenant_link'},
        {'field': 'aiChatHistory', 'source': 'three-root backup / registered AI chat files',
         'status': 'preserve_existing_no_implicit_creation'},
    ]
    return {'version': VERSION, 'workspaceId': workspace_id,
            'label': LABEL, 'identityStatus': 'identity_pending',
            'ownershipStatus': 'ownership_unclaimed', 'roleGrants': [],
            'ledgerRevision': revision, 'eventCount': len(events),
            'eventHistorySha256': history_digest, 'ledgerStateSha256': digest,
            'firstEventSha256': anchor, 'evidenceMatrix': evidence}


def verify_workspace(root: Path) -> dict:
    root = Path(root)
    marker = root / MARKER
    if not _regular(marker) or marker.stat().st_size > 16_384:
        raise LegacyBridgeBlocked('Missing or invalid versioned legacy workspace marker')
    try:
        existing = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LegacyBridgeBlocked('Damaged legacy workspace marker') from exc
    actual = inspect_legacy_book(root)
    if (type(existing) is not dict or set(existing) != set(actual) or
        any(existing[key] != actual[key] for key in (
            'version', 'workspaceId', 'label', 'identityStatus',
            'ownershipStatus', 'roleGrants', 'firstEventSha256')) or
            existing.get('ledgerRevision', 0) > actual['ledgerRevision'] or
            existing.get('eventCount', 0) > actual['eventCount']):
        raise LegacyBridgeBlocked('Legacy workspace marker mismatches accounting provenance')
    return actual


def migrate_restored_clone(roaming: Path, local: Path, bridge: Path,
                           *, original_snapshot_manifest: Path) -> dict:
    """Create-only sidecar in a restore; never touch the live profile.

    The inputs must be exactly the three externally restored roots and their
    source manifest. Idempotent re-entry validates the existing sidecar.
    Independently verify the snapshot before accepting any restored root.
    """
    from taraz_three_root_backup_20261114 import verify_three_root_backup
    roots = [Path(roaming), Path(local), Path(bridge)]
    manifest = Path(original_snapshot_manifest)
    if manifest.name != 'TARAZ_THREE_ROOT_MANIFEST.json' or not _regular(manifest):
        raise LegacyBridgeBlocked('Original three-root manifest required')
    original = verify_three_root_backup(manifest.parent)
    if original['mode'] != 'legacy' or original['sqlite'] < 1:
        raise LegacyBridgeBlocked('Snapshot is not a verified legacy Taraz profile')
    real_home = os.environ.get('APPDATA')
    if real_home:
        live = Path(real_home) / 'Taraz'
        if live.resolve() in [r.resolve() for r in roots]:
            raise LegacyBridgeBlocked('Refusing in-place legacy migration of live data')
    if len({r.resolve() for r in roots}) != 3 or any(
        not r.is_absolute() or not r.is_dir() or r.is_symlink() for r in roots):
        raise LegacyBridgeBlocked('Three disjoint restored roots required')
    # The marker cannot be stamped on an arbitrary or substituted financial
    # book simply by pointing to some other valid backup manifest.
    source_doc = json.loads(manifest.read_text(encoding='utf-8'))
    expected = [{entry['path']: entry['sha256'] for entry in
                 source_doc['roots'][role]['files']}
                for role in ('roaming_taraz', 'local_taraz', 'local_bridge')]
    root = roots[0]
    marker = root / MARKER
    if marker.exists() or marker.is_symlink():
        return {'status': 'ALREADY_MIGRATED', **verify_workspace(root)}
    before = [_inventory(r) for r in roots]
    if before != expected:
        raise LegacyBridgeBlocked('Restored roots do not match verified original snapshot')
    result = inspect_legacy_book(root)
    if any(not _inventory(r) == prior for r, prior in zip(roots, before)):
        raise LegacyBridgeBlocked('Source changed during legacy inspection')
    with marker.open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.flush()
        os.fsync(output.fileno())
    after = [_inventory(r) for r in roots]
    for previous, current in zip(before, after):
        if {k: v for k, v in current.items() if k != MARKER} != previous:
            raise LegacyBridgeBlocked('Unrelated restored clone member changed')
    if after[1:] != before[1:]:
        raise LegacyBridgeBlocked('Companion stores changed during migration')
    return {'status': 'MIGRATED_IDENTITY_PENDING', **verify_workspace(root)}


class LegacyLocalViewerIdentity:
    """In-process viewer of a proven local book, never a company login.

    A Windows logon identifies the local data boundary but does not establish
    legal title or administrator privileges. No secret or local-users file is
    generated. Mutations always fail the existing host ACL.
    """
    USER = 'legacy_local_viewer'

    def __init__(self, root: Path):
        self.root = Path(root)
        self.workspace = verify_workspace(self.root)
        self._token = secrets.token_urlsafe(48)
        self._expires = time.monotonic() + 3600

    def session(self) -> tuple[dict, str]:
        return self.require_session(self._token), self._token

    def require_session(self, token, required='viewer') -> dict:
        if (not isinstance(token, str) or not secrets.compare_digest(token, self._token)
                or time.monotonic() > self._expires or required != 'viewer'):
            raise LegacyBridgeBlocked('Pending ownership permits local viewing only')
        current = verify_workspace(self.root)
        if current['workspaceId'] != self.workspace['workspaceId']:
            raise LegacyBridgeBlocked('Legacy book workspace changed')
        return {'username': self.USER, 'role': 'viewer', 'jobTitle': ''}

    def accounting_accounts(self) -> dict:
        return {self.USER: {'username': self.USER, 'role': 'viewer',
                            'financeView': True, 'financeEdit': False}}

    def logout(self, token):
        if isinstance(token, str) and secrets.compare_digest(token, self._token):
            self._token = secrets.token_urlsafe(48)
            self._expires = 0


def main(argv=None) -> int:
    """Create an independent real-data clone and its identity-pending sidecar."""
    import argparse
    from taraz_three_root_backup_20261114 import restore_three_root_backup

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args(argv)
    snapshot, destination = args.snapshot.resolve(), args.destination
    if (not snapshot.is_absolute() or not destination.is_absolute() or
            destination.exists() or not destination.parent.is_dir() or
            destination.resolve() in snapshot.parents or snapshot in destination.parents):
        raise LegacyBridgeBlocked('Create-only isolated clone and existing parent required')
    from taraz_full_profile_backup_20261114 import _private_new_folder
    _private_new_folder(destination)
    roles = ('roaming_taraz', 'local_taraz', 'local_bridge')
    paths = [destination / name for name in roles]
    restored = restore_three_root_backup(snapshot, *paths,
                                         offline_acknowledged=True)
    result = migrate_restored_clone(*paths,
        original_snapshot_manifest=snapshot / 'TARAZ_THREE_ROOT_MANIFEST.json')
    repeat = migrate_restored_clone(*paths,
        original_snapshot_manifest=snapshot / 'TARAZ_THREE_ROOT_MANIFEST.json')
    if repeat['status'] != 'ALREADY_MIGRATED':
        raise LegacyBridgeBlocked('Migration was not idempotent')
    output = {'status': result['status'], 'workspaceId': result['workspaceId'],
              'identityStatus': result['identityStatus'],
              'ownershipStatus': result['ownershipStatus'],
              'ledgerRevision': result['ledgerRevision'],
              'eventCount': result['eventCount'],
              'eventHistorySha256': result['eventHistorySha256'],
              'restoreFiles': restored['files'], 'restoreSQLite': restored['sqlite'],
              'idempotentSecondRun': True, 'liveDataChanged': False,
              'financialEventsCreated': False}
    with (destination / 'legacy-clone-verification.json').open('x', encoding='utf-8') as stream:
        json.dump(output, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
