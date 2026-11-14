"""Verify a genuinely synthetic finance book is eligible for normal startup.

Uses the real production backing-up and accounting API code. No real user data.
Personal Parsian history remains guarded and inaccessible from this book.
"""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from standalone_accounting import StandaloneAccountingStore
from standalone_accounting import AccountingIntegrityError
from standalone_accounting_auto_backup import AutomaticStandaloneBackups
from taraz_desktop import TarazAPI, prepare_offline_accounting_on_launch


class IsolatedBootstrapTest(unittest.TestCase):
    def test_local_synthetic_book_and_backup_without_personal_history(self):
        with TemporaryDirectory(prefix='qa-taraz-frozen-bootstrap-') as directory:
            root = Path(directory) / 'qa' / 'Taraz'
            root.mkdir(parents=True)
            original = StandaloneAccountingStore(
                root / 'standalone-accounting.sqlite3', default_currency='RIAL')
            original.command({
                'type': 'party.register', 'eventId': 'QA-BOOTSTRAP-PARTY-1',
                'partyId': 'QA-ONLY-CUSTOMER', 'name': 'مشتری ساختگی تراز',
                'kind': 'customer',
            }, actor='local', accounts={'local': {'username': 'local', 'role': 'admin'}},
               expected_revision=0, now=datetime.now(timezone.utc).isoformat())
            api = TarazAPI(root)
            backups = AutomaticStandaloneBackups(root, plaintext_acknowledged=True)
            prepare_offline_accounting_on_launch(api, backups)
            result = api.standaloneAccountingRead()
            self.assertEqual(result['revision'], 1)
            self.assertEqual(result['view']['journals'], [])
            self.assertEqual(len(result['view']['parties']), 1)
            self.assertTrue(backups.last_success.is_file())
            with self.assertRaises(PermissionError):
                api.standaloneAccountingParsianHistory()

            # A fresh company's book must not be mistaken for the historical
            # personal source by any read/archives endpoint.
            for personal_call in (
                api.standaloneAccountingParsianCompany,
                api.standaloneAccountingParsianExtended,
                api.standaloneAccountingParsianArchiveIndex,
            ):
                with self.subTest(personal_call=personal_call.__name__):
                    with self.assertRaises(PermissionError):
                        personal_call()
            with self.assertRaises(PermissionError):
                api.standaloneAccountingParsianArchiveRows('1405', 'journals', 0)

    def test_corrupt_synthetic_event_digest_never_bootstraps_or_repairs_itself(self):
        with TemporaryDirectory(prefix='qa-taraz-corrupt-source-') as directory:
            root=Path(directory)/'qa'/'Taraz'
            root.mkdir(parents=True)
            book=StandaloneAccountingStore(
                root/'standalone-accounting.sqlite3',default_currency='RIAL')
            book.command({'type':'party.register','eventId':'QA-CORRUPT-WITNESS',
                          'partyId':'QA-ONLY-1','name':'مشتری ساختگی',
                          'kind':'customer'},actor='local',
                         accounts={'local':{'username':'local','role':'admin'}},
                         expected_revision=0,
                         now=datetime.now(timezone.utc).isoformat())
            with closing(sqlite3.connect(root/'standalone-accounting.sqlite3')) as db:
                with db:
                    db.execute('UPDATE standalone_accounting SET digest=? WHERE id=1',
                               ('0'*64,))
            api=TarazAPI(root)
            backups=AutomaticStandaloneBackups(root,plaintext_acknowledged=True)
            with self.assertRaises(AccountingIntegrityError):
                prepare_offline_accounting_on_launch(api,backups)
            with closing(sqlite3.connect(root/'standalone-accounting.sqlite3')) as db:
                digest=db.execute(
                    'SELECT digest FROM standalone_accounting WHERE id=1'
                ).fetchone()[0]
            self.assertEqual(digest,'0'*64)

    def test_proforma_created_and_edited_audit_preserves_actor(self):
        with TemporaryDirectory(prefix='qa-taraz-proforma-audit-') as directory:
            root = Path(directory) / 'qa' / 'Taraz'
            root.mkdir(parents=True)
            api = TarazAPI(root)
            book = api._store()
            date = datetime.now(timezone.utc).isoformat()
            commands = [
                {'type':'party.register','eventId':'QA-PARTY-EVENT',
                 'partyId':'QA-PERSON', 'name':'مشتری ساختگی', 'kind':'customer'},
                {'type':'proforma.create','eventId':'QA-PROFORMA-CREATE',
                 'proformaId':'QA-PROFORMA','partyId':'QA-PERSON',
                 'documentDate':'2026-11-12',
                 'lines':[{'description':'چاپ نمونه','quantity':2,'unitPrice':2500}]},
                {'type':'proforma.update','eventId':'QA-PROFORMA-EDIT',
                 'proformaId':'QA-PROFORMA','partyId':'QA-PERSON',
                 'documentDate':'2026-11-12',
                 'lines':[{'description':'چاپ نمونه','quantity':3,'unitPrice':2500}]},
            ]
            for revision, command in enumerate(commands):
                result = book.command(command,actor='local',accounts={
                    'local': {'username':'local','role':'admin'}},
                    expected_revision=revision,now=date)
                self.assertEqual(result['revision'],revision+1)
            refreshed = TarazAPI(root).standaloneAccountingRead()
            offer = refreshed['view']['proformas']['QA-PROFORMA']
            self.assertEqual(offer['createdBy'],'local')
            self.assertEqual(offer['editedBy'],'local')
            self.assertEqual(offer['createdAt'],date)
            self.assertEqual(offer['editedAt'],date)
            self.assertEqual(offer['total'],7500)
            self.assertEqual(refreshed['view']['journals'],[])


if __name__ == '__main__':
    unittest.main()
