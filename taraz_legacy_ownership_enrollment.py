"""One-time v1.0.4 legacy company enrollment; no implicit owner or administrator.

Stage from an independently verified three-root restore.  The legacy business
label is NOT a legal name.  An explicit, same-Windows-principal *declaration*
is needed before a named administrator with a real password may be created.
The declaration records user intent, NOT independent evidence of ownership.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess

from standalone_accounting import _decode_checked
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_identity import LocalCompanyIdentity, _validate_password, _USER
from taraz_legacy_workspace_bridge import MARKER, verify_workspace
from taraz_three_root_backup_20261114 import verify_three_root_backup


INTENT = 'legacy-enrollment-intent.json'
BOOK_PROVENANCE = 'legacy-company-provenance.json'
DECLARATION = 'legacy-administrator-declaration.json'
LABEL = 'دفتر واردشده تراز ۱.۰.۴ (نام حقوقی تأییدنشده)'
CONSENT = 'من اختیار مدیریت این دفتر قدیمی را دارم'
_COPY_EXCLUDE = {MARKER, '.taraz-session.lock', INTENT, 'companies.json'}


class EnrollmentBlocked(PermissionError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 65536:
        raise EnrollmentBlocked('Required enrollment evidence missing or unsafe')
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise EnrollmentBlocked('Invalid enrollment evidence') from exc
    if type(doc) is not dict:
        raise EnrollmentBlocked('Invalid enrollment evidence format')
    return doc


def _write_new(path: Path, data: dict) -> None:
    if path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise EnrollmentBlocked('Enrollment output already exists or is untrusted')
    with path.open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_windows_sid() -> str:
    if os.name != 'nt':
        raise EnrollmentBlocked('Enrollment requires local Windows logon')
    system = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    command = system / 'System32' / 'whoami.exe'
    if not command.is_file():
        raise EnrollmentBlocked('Windows principal cannot be verified')
    result = subprocess.run([str(command), '/user', '/fo', 'csv', '/nh'],
                            capture_output=True, text=True, encoding='utf-8-sig',
                            errors='replace', timeout=12, check=True)
    import csv
    rows = list(csv.reader(result.stdout.splitlines()))
    if len(rows) != 1 or len(rows[0]) != 2:
        raise EnrollmentBlocked('Ambiguous Windows principal')
    sid = rows[0][1].strip()
    if not re.fullmatch(r'S-1-5-(?:[0-9]+-){2,}[0-9]+', sid):
        raise EnrollmentBlocked('Invalid Windows principal identifier')
    return sid


def _snapshot_proof(manifest: Path) -> tuple[dict, dict]:
    manifest = Path(manifest)
    if manifest.name != 'TARAZ_THREE_ROOT_MANIFEST.json':
        raise EnrollmentBlocked('Original three-root manifest required')
    verified = verify_three_root_backup(manifest.parent)
    doc = _json(manifest)
    if verified['mode'] != 'legacy' or doc.get('format') != 'taraz-three-root-offline-snapshot':
        raise EnrollmentBlocked('Snapshot is not a proven 1.0.4 legacy profile')
    principal = doc.get('principal')
    if (type(principal) is not dict or
            principal.get('sid', '').casefold() != current_windows_sid().casefold() or
            principal.get('machine', '').casefold() !=
                os.environ.get('COMPUTERNAME', '').casefold()):
        raise EnrollmentBlocked('Snapshot device/principal differs from current Windows logon')
    return verified, doc


def _original_files_match(roaming: Path, manifest: dict):
    expected = manifest['roots']['roaming_taraz']['files']
    for entry in expected:
        rel = Path(entry['path'])
        if rel.is_absolute() or '..' in rel.parts:
            raise EnrollmentBlocked('Invalid snapshot inventory path')
        source = roaming / rel
        if not source.is_file() or source.is_symlink() or _sha(source) != entry['sha256']:
            raise EnrollmentBlocked('Legacy original changed since consistent snapshot')
    return expected


def _ledger_proof(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise EnrollmentBlocked('Legacy accounting ledger missing')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON')
        if conn.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise EnrollmentBlocked('Legacy financial integrity failed')
        if conn.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise EnrollmentBlocked('Unexpected legacy accounting schema')
        row = conn.execute('SELECT revision,state,digest FROM standalone_accounting').fetchone()
    if row is None:
        raise EnrollmentBlocked('Empty legacy book')
    revision, state, digest = row
    events = _decode_checked(state, digest)['events']
    if revision != len(events) or len({e['eventId'] for e in events}) != len(events):
        raise EnrollmentBlocked('Inconsistent or repeated legacy events')
    ids = hashlib.sha256(json.dumps([e['eventId'] for e in events], ensure_ascii=False,
                      separators=(',', ':')).encode()).hexdigest()
    return {'revision': revision, 'eventCount': len(events),
            'stateSha256': digest, 'eventIdsSha256': ids}


def _installed_baseline_evidence() -> dict:
    """Read current 1.0.4 installation identity, NOT owner authorization."""
    root = Path(os.environ.get('LOCALAPPDATA', '/__unavailable__')) / 'Programs' / 'Taraz'
    pointer = root / 'current-version.txt'
    exe = root / 'versions' / '1.0.4' / 'Taraz.exe'
    if not pointer.is_file() or pointer.is_symlink() or not exe.is_file() or exe.is_symlink():
        return {'status': 'NOT_AVAILABLE', 'provesOwnership': False}
    version = pointer.read_text(encoding='utf-8-sig').strip()
    return {'status': 'PRESENT' if version == '1.0.4' else 'DIFFERENT_VERSION',
            'version': version, 'exeSha256': _sha(exe),
            'provesOwnership': False}


def stage_legacy_company(roaming: Path, local: Path, bridge: Path, *,
                         original_snapshot_manifest: Path) -> dict:
    """Create/repair a *clone-only*, ownerless registered workspace.

    Never operates on the actual APPDATA roots, and never creates credentials.
    During a crash a matching staged company can be resumed; conflicting files
    or identities always block rather than silently overwrite anything.
    """
    roots = [Path(v).resolve() for v in (roaming, local, bridge)]
    if len(set(roots)) != 3 or any(not r.is_dir() or r.is_symlink() for r in roots):
        raise EnrollmentBlocked('Three disjoint existing clone roots required')
    if os.environ.get('APPDATA') and roots[0] == (Path(os.environ['APPDATA'])/'Taraz').resolve():
        raise EnrollmentBlocked('Production profile migration requires separately accepted release')
    _, manifest = _snapshot_proof(Path(original_snapshot_manifest))
    before_legacy = _original_files_match(roots[0], manifest)
    for role, root in zip(('local_taraz', 'local_bridge'), roots[1:]):
        for entry in manifest['roots'][role]['files']:
            path = root / entry['path']
            if not path.is_file() or path.is_symlink() or _sha(path) != entry['sha256']:
                raise EnrollmentBlocked('Companion store differs from verified source')
    root = roots[0]
    evidence = _ledger_proof(root / 'standalone-accounting.sqlite3')
    intent_file = root / INTENT
    if not intent_file.exists():
        pending = verify_workspace(root)
        if (pending['ledgerRevision'] != evidence['revision'] or
                pending['ledgerStateSha256'] != evidence['stateSha256'] or
                pending['eventHistorySha256'] != evidence['eventIdsSha256']):
            raise EnrollmentBlocked('Legacy provenance marker mismatch')
        if (root / 'companies.json').exists() or (root / 'books').exists():
            raise EnrollmentBlocked('Existing company registry may not be reassigned')
        intent = {'schemaVersion': 1, 'state': 'STAGING_NO_OWNER',
                  'legacyWorkspaceId': pending['workspaceId'],
                  'ledger': evidence, 'sourceManifestSha256': _sha(Path(original_snapshot_manifest)),
                  'windowsPrincipalSidSha256': hashlib.sha256(
                      current_windows_sid().encode()).hexdigest(),
                  'historicalInstallation': _installed_baseline_evidence(),
                  'legalCompanyName': None, 'ownerVerified': False,
                  'principalProvesLegalOwnership': False,
                  'createdAt': _utc(), 'label': LABEL}
        _write_new(intent_file, intent)
    else:
        intent = _json(intent_file)
        if (intent.get('schemaVersion') != 1 or intent.get('ledger') != evidence or
                intent.get('sourceManifestSha256') != _sha(Path(original_snapshot_manifest)) or
                intent.get('windowsPrincipalSidSha256') != hashlib.sha256(
                    current_windows_sid().encode()).hexdigest() or
                intent.get('legalCompanyName', 'invalid') is not None or
                intent.get('label') != LABEL or intent.get('ownerVerified') is not False):
            raise EnrollmentBlocked('Unrecognized or conflicting enrollment intent')
    registry = StandaloneCompanyRegistry(root)
    companies = registry.list_companies()
    if not companies:
        record = registry.create_company(LABEL)
    elif len(companies) == 1 and companies[0]['name'] == LABEL:
        record = companies[0]
    else:
        raise EnrollmentBlocked('Multi-company or ambiguous ownership requires manual review')
    book = registry.company_data_directory(record['id'])
    if (book / 'local-users.json').exists():
        # An already enrolled identity can only be read by the separate
        # declaration verifier; staging never substitutes an administrator.
        raise EnrollmentBlocked('Company identity already present; use authenticated login')
    for entry in before_legacy:
        rel = Path(entry['path'])
        if rel.as_posix() in _COPY_EXCLUDE:
            continue
        target = book / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            if not target.is_file() or target.is_symlink() or _sha(target) != entry['sha256']:
                raise EnrollmentBlocked('Existing staged company member differs')
            continue
        with (root / rel).open('rb') as source, target.open('xb') as destination:
            shutil.copyfileobj(source, destination, 1024*1024)
            destination.flush()
            os.fsync(destination.fileno())
        if _sha(target) != entry['sha256']:
            raise EnrollmentBlocked('Copied historical member fails SHA readback')
    proof = {'schemaVersion': 1, 'companyId': record['id'],
             'legalCompanyName': None, 'legacyWorkspaceId': intent['legacyWorkspaceId'],
             'sourceManifestSha256': intent['sourceManifestSha256'],
             'windowsPrincipalSidSha256': intent['windowsPrincipalSidSha256'],
             'ledger': evidence, 'ownershipStatus': 'unclaimed',
             'principalProvesLegalOwnership': False}
    provenance_file = book / BOOK_PROVENANCE
    if provenance_file.exists():
        if _json(provenance_file) != proof:
            raise EnrollmentBlocked('Staged provenance mismatch')
        status = 'ALREADY_STAGED_OWNERLESS'
    else:
        _write_new(provenance_file, proof)
        status = 'STAGED_OWNERLESS'
    if _ledger_proof(book / 'standalone-accounting.sqlite3') != evidence:
        raise EnrollmentBlocked('Staged financial history differs from original')
    _original_files_match(root, manifest)
    return {'status': status, 'companyId': record['id'],
            'legacyWorkspaceId': intent['legacyWorkspaceId'], 'ledger': evidence,
            'roleGrants': [], 'ownerVerified': False, 'declarationAccepted': False,
            'oldSourcePreserved': True}


def pending_company(roaming: Path) -> dict | None:
    """Return exactly one staged unclaimed company, never infer consent."""
    root = Path(roaming)
    if not (root / INTENT).is_file() or not (root / 'companies.json').is_file():
        return None
    companies = StandaloneCompanyRegistry(root).list_companies()
    if len(companies) != 1 or companies[0]['name'] != LABEL:
        raise EnrollmentBlocked('Multi-company or ambiguous legacy claim')
    book = StandaloneCompanyRegistry(root).company_data_directory(companies[0]['id'])
    proof = _json(book / BOOK_PROVENANCE)
    intent = _json(root / INTENT)
    if (proof.get('companyId') != companies[0]['id'] or
            proof.get('ledger') != intent.get('ledger') or
            proof.get('legacyWorkspaceId') != intent.get('legacyWorkspaceId') or
            proof.get('windowsPrincipalSidSha256') != hashlib.sha256(
                current_windows_sid().encode()).hexdigest() or
            _ledger_proof(book / 'standalone-accounting.sqlite3') != proof['ledger']):
        raise EnrollmentBlocked('Staged company identity or ledger mismatches provenance')
    if (book / 'local-users.json').exists():
        declaration = _json(book / DECLARATION)
        from standalone_accounting_identity import IdentityError
        try:
            identity = LocalCompanyIdentity(book)
            users = identity.accounting_accounts()
        except IdentityError as exc:
            raise EnrollmentBlocked('Invalid historical company local identity') from exc
        if (declaration.get('status') != 'DECLARATION_ONLY_NOT_INDEPENDENT_PROOF' or
                declaration.get('companyId') != proof['companyId'] or
                declaration.get('legacyWorkspaceId') != proof['legacyWorkspaceId'] or
                declaration.get('ledger') != proof['ledger'] or
                declaration.get('windowsPrincipalSidSha256') != proof['windowsPrincipalSidSha256'] or
                declaration.get('authorizationBasis') != 'explicit_local_user_declaration' or
                declaration.get('legalOwnershipIndependentlyVerified') is not False or
                declaration.get('declaredByLocalUser') not in users or
                users[declaration['declaredByLocalUser']]['role'] != 'admin'):
            raise EnrollmentBlocked('Administrator identity mismatches explicit declaration')
        return None
    return {'companyId': companies[0]['id'], 'book': book,
            'workspaceId': proof['legacyWorkspaceId'],
            'ledger': proof['ledger'], 'status': 'WAITING_USER_DECLARATION'}


def approve_declaration(roaming: Path, *, company_id: str, username: str,
                        password: str, confirmation: str, consent_checked: bool) -> dict:
    """Explicit operator action only, never invoked during startup automatically.

    Current Windows principal + user declaration establish a *local access*
    enrollment. They do NOT independently certify legal company ownership.
    """
    if consent_checked is not True or confirmation.strip() != CONSENT:
        raise EnrollmentBlocked('A precise voluntary administrator declaration is required')
    if type(username) is not str or not _USER.fullmatch(username):
        raise EnrollmentBlocked('A valid explicit administrator username is required')
    _validate_password(password)
    pending = pending_company(Path(roaming))
    if not pending or pending['companyId'] != company_id:
        raise EnrollmentBlocked('Not an unclaimed one-company legacy workspace')
    book = pending['book']
    intent = _json(Path(roaming) / INTENT)
    # Create-only audit intent before password account creation. Interrupted
    # cases are marked ambiguous and must not be retried with invented identity.
    receipt = {'schemaVersion': 1, 'status': 'DECLARATION_ONLY_NOT_INDEPENDENT_PROOF',
        'companyId': company_id, 'legacyWorkspaceId': pending['workspaceId'],
        'ledger': pending['ledger'], 'windowsPrincipalSidSha256':
        intent['windowsPrincipalSidSha256'], 'declarationText': CONSENT,
        'declaredByLocalUser': username, 'declaredAt': _utc(),
        'legalCompanyName': None, 'legalOwnershipIndependentlyVerified': False,
        'authorizationBasis': 'explicit_local_user_declaration',
        'auditNonce': secrets.token_hex(16)}
    audit = book / DECLARATION
    if audit.exists() or audit.is_symlink():
        old_receipt = _json(audit)
        expected = {k: v for k, v in receipt.items()
                    if k not in ('declaredAt', 'auditNonce')}
        if ({k: v for k, v in old_receipt.items()
             if k not in ('declaredAt', 'auditNonce')} != expected):
            raise EnrollmentBlocked('Interrupted declaration conflicts with previous user')
        # Explicit repeat declaration for the SAME identity after crash only.
        # No automatic user or credential is ever reconstructed.
    else:
        _write_new(audit, receipt)
    try:
        identity = LocalCompanyIdentity(book)
        identity.add_user(username, password, 'admin',
                          job_title='مدیر معرفی‌شده توسط کاربر')
        authenticated = identity.login(username, password)
        identity.require_session(authenticated, 'admin')
        identity.logout(authenticated)
    except Exception:
        # Do not silently discard the declaration after a partial identity write.
        # Operator must inspect the audit/identity combination and recover.
        raise
    return {'status': 'LOCAL_ADMIN_CREATED_FROM_EXPLICIT_DECLARATION',
            'companyId': company_id, 'principalBindingVerified': True,
            'legalOwnershipIndependentlyVerified': False,
            'financialLedgerUntouched': True}
