"""Focused Windows lock/row-witness checks for real-profile backup guard."""
from __future__ import annotations

from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
import os

from scripts.taraz_live_three_root_backup_20261114 import (
    RealBackupBlocked, _db_rows_digest, _hold_windows_read_only,
)
from taraz_three_root_backup_20261114 import _same_source_inventory


@unittest.skipUnless(os.name == 'nt', 'Windows file sharing is required')
class RealProfileBackupSafetyTests(unittest.TestCase):
    def test_shm_mtime_is_transient_but_wal_and_sqlite_are_not(self):
        original = (('books',), {'a.sqlite3': (1, 2, 4096, 5)},
                    {'a.sqlite3-shm': (1, 4, 32768, 10),
                     'a.sqlite3-wal': (1, 5, 0, 20)})
        shm_touch = (original[0], original[1],
                     {'a.sqlite3-shm': (1, 4, 32768, 99),
                      'a.sqlite3-wal': (1, 5, 0, 20)})
        self.assertTrue(_same_source_inventory(original, shm_touch))
        self.assertFalse(_same_source_inventory(
            original, (original[0], original[1],
                       {'a.sqlite3-shm': (1, 4, 32769, 99),
                        'a.sqlite3-wal': (1, 5, 0, 20)})))
        self.assertFalse(_same_source_inventory(
            original, (original[0], original[1],
                       {'a.sqlite3-shm': (1, 4, 32768, 10),
                        'a.sqlite3-wal': (1, 5, 0, 21)})))
        self.assertFalse(_same_source_inventory(
            original, (original[0], {'a.sqlite3': (1, 2, 4096, 6)},
                       original[2])))

    def test_denies_writer_while_allowing_sqlite_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'sample.sqlite3'
            with closing(sqlite3.connect(db)) as con:
                with con:
                    con.execute('CREATE TABLE sample (id TEXT PRIMARY KEY, value TEXT)')
                    con.execute("INSERT INTO sample VALUES ('stable-1', 'original')")
            with _hold_windows_read_only(db):
                with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as con:
                    self.assertEqual(con.execute('SELECT count(*) FROM sample').fetchone()[0], 1)
                # Windows must not grant a new GENERIC_WRITE file handle.
                import ctypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                    ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                    ctypes.c_uint32, ctypes.c_void_p]
                kernel.CreateFileW.restype = ctypes.c_void_p
                denied = kernel.CreateFileW(str(db), 0x40000000, 3, None, 3, 0x80, None)
                self.assertEqual(denied, ctypes.c_void_p(-1).value)
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(con.execute('SELECT value FROM sample').fetchone()[0],
                                 'original')

    def test_row_fingerprint_detects_changed_ids_and_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / 'a.sqlite3', Path(tmp) / 'b.sqlite3'
            for target, data in ((first, 'one'), (second, 'two')):
                with closing(sqlite3.connect(target)) as con:
                    with con:
                        con.execute('CREATE TABLE customer (id TEXT PRIMARY KEY, value TEXT)')
                        con.execute('INSERT INTO customer VALUES (?, ?)', ('legacy-id', data))
            self.assertNotEqual(_db_rows_digest(first), _db_rows_digest(second))
            with closing(sqlite3.connect(second)) as con:
                with con:
                    con.execute('UPDATE customer SET value=?', ('one',))
            self.assertEqual(_db_rows_digest(first), _db_rows_digest(second))


if __name__ == '__main__':
    unittest.main()
