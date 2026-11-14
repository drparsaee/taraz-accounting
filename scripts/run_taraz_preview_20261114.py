"""Persistent, visible Taraz source preview using ONLY a synthetic QA profile.

No changes to installed Taraz, ambient APPDATA/LOCALAPPDATA or real books.
The demo's seeded issued invoice is synthetic; draft creation still requires
the application's explicit review confirmation. A real QA identity session
is established automatically ONLY for this isolated, single-company fixture.
This preview is not a production update or a Frozen EXE acceptance witness.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.qa_taraz_ai_frozen_real_auth_20261114 import (
    ARTIFACTS, QA_COMPANY, QA_REQUEST, QA_USER, create_private_fixture,
)
from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import secure_private_directory
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_identity import LocalCompanyIdentity
from standalone_accounting import StandaloneAccountingStore

PREVIEW = ARTIFACTS / 'preview-qa-user-visible-20261114'
RUNTIME = PREVIEW / 'qa' / 'qa-runtime'
PROFILE = RUNTIME / 'roaming' / 'Taraz'
MANIFEST = PREVIEW / 'preview-manifest.json'
CREDENTIALS = PREVIEW / 'synthetic-login.txt'
_KEYS = ('APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP', 'USERPROFILE',
         'HOME', 'WEBVIEW2_USER_DATA_FOLDER', 'PYINSTALLER_CONFIG_DIR',
         'PYTHONPYCACHEPREFIX')


class PreviewBlocked(RuntimeError):
    pass


def ordinary(path: Path) -> bool:
    for part in (path, *path.parents):
        if part.is_symlink():
            return False
        if part.exists() and (getattr(part.lstat(), 'st_file_attributes', 0) &
                              getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
            return False
    return True


def guard_paths():
    if (os.name != 'nt' or not PREVIEW.is_absolute() or
            not ordinary(PREVIEW) or not ordinary(RUNTIME) or
            not PREVIEW.is_relative_to(ARTIFACTS) or
            'qa' not in (part.casefold() for part in RUNTIME.parts) or
            'qa-runtime' not in (part.casefold() for part in RUNTIME.parts)):
        raise PreviewBlocked('Windows private QA boundary is unavailable')
    if not (ROOT / 'dist' / 'accounting.html').is_file():
        raise PreviewBlocked('Built accounting UI unavailable; do not show stale preview')
    if (not ordinary(ROOT / 'dist' / 'accounting.html') or
            not ordinary(ROOT / 'taraz_desktop.py')):
        raise PreviewBlocked('Source or UI assets are not regular files')
    # Never allow an arbitrary environment to rebind the preview to live data.
    if not ARTIFACTS.is_dir():
        raise PreviewBlocked('Expected non-installed QA artifact directory missing')


def prepare():
    guard_paths()
    if not PREVIEW.exists():
        secure_private_directory(PREVIEW)
    if not PREVIEW.is_dir():
        raise PreviewBlocked('Private preview root unavailable')
    if not MANIFEST.exists() and (PROFILE.exists() or CREDENTIALS.exists()):
        raise PreviewBlocked('Incomplete preview setup; refuse overwriting existing data')
    if not MANIFEST.exists():
        RUNTIME.mkdir(parents=True, exist_ok=False)
        fixture = create_private_fixture(RUNTIME)
        if fixture['profile'] != PROFILE:
            raise PreviewBlocked('Private QA root was redirected')
        with CREDENTIALS.open('x', encoding='utf-8') as stream:
            stream.write('ONLY SYNTHETIC TARAZ PREVIEW; NOT A REAL LOGIN\n')
            stream.write('Username: ' + QA_USER + '\n')
            stream.write('Password: ' + fixture['password'] + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        payload = {'syntheticOnly': True, 'sourceHosted': True,
                   'profile': str(PROFILE.resolve()),
                   'companyId': fixture['companyId'], 'companyName': QA_COMPANY,
                   'username': QA_USER, 'installedVersionChanged': False}
        with MANIFEST.open('x', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
    return verify()


def verify():
    guard_paths()
    if not PREVIEW.is_dir() or not all(ordinary(p) for p in
         (PREVIEW, PROFILE, MANIFEST, CREDENTIALS)):
        raise PreviewBlocked('Private preview path or file unavailable')
    if not MANIFEST.is_file() or not CREDENTIALS.is_file():
        raise PreviewBlocked('Missing private preview identity or credentials')
    if MANIFEST.stat().st_size > 8192 or CREDENTIALS.stat().st_size > 2048:
        raise PreviewBlocked('Oversize preview manifest/credential')
    try:
        data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise PreviewBlocked('Invalid preview manifest') from exc
    if (type(data) is not dict or data.get('syntheticOnly') is not True or
            data.get('sourceHosted') is not True or
            data.get('profile') != str(PROFILE.resolve()) or
            data.get('username') != QA_USER or
            data.get('companyName') != QA_COMPANY or
            type(data.get('companyId')) is not str):
        raise PreviewBlocked('Untrusted preview manifest')
    book = StandaloneCompanyRegistry(PROFILE).company_data_directory(data['companyId'])
    if not ordinary(book):
        raise PreviewBlocked('Linked company book is not allowed')
    user = LocalCompanyIdentity(book)
    if not user.initialized() or set(user.accounting_accounts()) != {QA_USER}:
        raise PreviewBlocked('Preview company identity drift')
    companies = StandaloneCompanyRegistry(PROFILE).list_companies()
    if (len(companies) != 1 or companies[0]['id'] != data['companyId'] or
            companies[0]['name'] != QA_COMPANY):
        raise PreviewBlocked('Preview must contain exactly one synthetic company')
    state = StandaloneAccountingStore(book / 'standalone-accounting.sqlite3',
                                     default_currency='RIAL').read(
                                         actor=QA_USER, accounts=user.accounting_accounts())
    if (state['view'].get('currency') != 'RIAL' or
            state['view'].get('invoices', {}).get('QA-SOURCE-INV', {}).get('status') != 'issued' or
            len(state['view'].get('journals', [])) != 1):
        raise PreviewBlocked('Synthetic source invoice/journal changed unexpectedly')
    return {'status': 'READY_SOURCE_PREVIEW_NOT_INSTALLED',
            'sourceHosted': True, 'syntheticOnly': True, 'company': QA_COMPANY,
            'username': QA_USER, 'profile': str(PROFILE),
            'credentialsFile': str(CREDENTIALS),
            'ledgerRevision': state['revision'],
            'aiConversationCountUnverified': True,
            'installedVersionChanged': False}


def isolated_environment():
    guard_paths()
    variables = dict(os.environ)
    for key in list(variables):
        if (key.upper().startswith(('TARAZ_', 'WEBVIEW2_')) or
                key.upper() == 'PYTHONPATH'):
            variables.pop(key, None)
    mapping = {'APPDATA': 'roaming', 'LOCALAPPDATA': 'localappdata',
               'TEMP': 'temp', 'TMP': 'temp', 'USERPROFILE': 'userprofile',
               'HOME': 'userprofile', 'WEBVIEW2_USER_DATA_FOLDER': 'webview-profile',
               'PYINSTALLER_CONFIG_DIR': 'pyinstaller-config',
               'PYTHONPYCACHEPREFIX': 'pycache'}
    for key, child in mapping.items():
        path = RUNTIME / child
        path.mkdir(exist_ok=True)
        variables[key] = str(path)
        ambient = os.environ.get(key)
        if ambient and path.resolve() == Path(ambient).resolve():
            raise PreviewBlocked('Preview would reuse ambient ' + key)
    variables['TARAZ_QA_MODE'] = '1'
    variables['TARAZ_QA_DATA_DIR'] = str(PROFILE)
    variables['TARAZ_QA_REPORT'] = str(PREVIEW / 'preview-ui-qa-report.json')
    variables['PYTHONDONTWRITEBYTECODE'] = '1'
    # No CDP listener, no cloud provider, no ambient Madar/Taraz API secrets.
    variables['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (
        '--disable-background-networking --disable-sync --disable-extensions '
        '--no-first-run --proxy-server=http://127.0.0.1:9 '
        '--proxy-bypass-list=<-loopback>')
    assert 'TARAZ_QA_CDP_PORT' not in variables
    return variables


def _synthetic_demo_password():
    """Extract only the fixture's private password, never log or return it to UI."""
    data = CREDENTIALS.read_text(encoding='utf-8').splitlines()
    if (len(data) != 3 or
            data[0] != 'ONLY SYNTHETIC TARAZ PREVIEW; NOT A REAL LOGIN' or
            data[1] != 'Username: ' + QA_USER or
            not data[2].startswith('Password: ')):
        raise PreviewBlocked('Invalid synthetic fixture credential marker')
    value = data[2].removeprefix('Password: ')
    if not 4 <= len(value) <= 256:
        raise PreviewBlocked('Invalid synthetic fixture password')
    return value


def run_synthetic_demo_child():
    """Use authenticated Taraz API directly; skip only irrelevant QA login UI."""
    if (os.environ.get('TARAZ_QA_MODE') != '1' or
            Path(os.environ.get('TARAZ_QA_DATA_DIR', '')).resolve() != PROFILE.resolve() or
            Path(os.environ.get('APPDATA', '')).resolve() != (RUNTIME / 'roaming').resolve() or
            Path(os.environ.get('LOCALAPPDATA', '')).resolve() !=
                (RUNTIME / 'localappdata').resolve()):
        raise PreviewBlocked('Synthetic preview child is not on the isolated profile')
    verify()
    from taraz_desktop import TarazAPI, _run_authenticated_taraz_api
    reg = StandaloneCompanyRegistry(PROFILE)
    book = reg.company_data_directory(
        json.loads(MANIFEST.read_text(encoding='utf-8'))['companyId'])
    identity = LocalCompanyIdentity(book)
    token = identity.login(QA_USER, _synthetic_demo_password())
    try:
        logged_in = identity.require_session(token, 'viewer')
        if logged_in.get('username') != QA_USER:
            raise PreviewBlocked('Synthetic user identity mismatch')
        api = TarazAPI(book, company_name=QA_COMPANY,
                       company_workspace_id=book.name,
                       authenticated_user=logged_in, identity_store=identity,
                       identity_token=token)
        return _run_authenticated_taraz_api(api)
    finally:
        identity.logout(token)


@contextmanager
def preview_lock():
    import msvcrt
    lock = PREVIEW / '.preview-launch.lock'
    with lock.open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.seek(0)
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise PreviewBlocked('This preview already has an open session') from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def launch():
    prepare()
    env = isolated_environment()
    print('TARAZ PREVIEW - direct accounting workspace, synthetic data only.', flush=True)
    print('No company-selection or login screen in this demonstration.', flush=True)
    print('Installed Taraz 1.0.4 and real data are not used.', flush=True)
    with preview_lock():
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                                 '--demo-child'],
                                env=env, cwd=ROOT, check=False)
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description='Non-installed Taraz source preview')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--verify', action='store_true')
    mode.add_argument('--launch', action='store_true')
    mode.add_argument('--demo-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.launch:
            return launch()
        if args.demo_child:
            run_synthetic_demo_child()
            return 0
        print(json.dumps(prepare() if args.prepare else verify(),
                         ensure_ascii=True, indent=2))
        return 0
    except (PreviewBlocked, OSError, ValueError, PermissionError) as exc:
        print(json.dumps({'status': 'BLOCKED_SOURCE_PREVIEW',
                          'errorType': type(exc).__name__,
                          'reason': str(exc)[:140]}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
