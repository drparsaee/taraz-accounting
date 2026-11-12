"""Independently inspect the exact frozen code, not a source-hosted alias."""
from pathlib import Path
import types
import unittest

from PyInstaller.archive.readers import CArchiveReader
from scripts import qa_taraz_v106_cas_frozen_private_gui_20261112 as current


def nested_code(code):
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from nested_code(value)


class FrozenCASContract(unittest.TestCase):
    def test_exact_build_and_real_embedded_runtime(self):
        pins = current.qa.candidate()
        self.assertEqual(pins['sourceSha'], current.qa.SOURCE_SHA)
        self.assertEqual(pins['exeSha'], current.qa.EXE_SHA)

        frozen = CArchiveReader(str(current.qa.EXE))
        pyz = frozen.open_embedded_archive('PYZ.pyz')
        module = pyz.extract('taraz_ecosystem_outbox')
        self.assertIsInstance(module, types.CodeType)
        codes = list(nested_code(module))
        dispatch = [code for code in codes if code.co_name == 'mark_possibly_sent']
        self.assertEqual(len(dispatch), 1)
        self.assertIn('source_witness', dispatch[0].co_varnames)
        strings = {value for code in codes for value in code.co_consts
                   if isinstance(value, str)}
        self.assertIn('Source changed after staging, remote send refused', strings)
        self.assertIn('Prior entity event is not remotely acknowledged', strings)


if __name__ == '__main__':
    unittest.main()
