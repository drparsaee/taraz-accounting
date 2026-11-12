"""Private CDP activation must fail shut outside isolated real-EXE QA.

Source-level policy tests, not evidence of successful CDP in frozen WebView2.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from taraz_desktop import private_qa_cdp_port


class PrivateCdpPolicyTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory(prefix='taraz-private-cdp-policy-')
        self.addCleanup(self.folder.cleanup)
        self.roaming = Path(self.folder.name) / 'qa' / 'qa-runtime' / 'roaming'
        self.data = self.roaming / 'Taraz'
        self.data.mkdir(parents=True)
        self.marker = self.data / '.taraz-private-cdp-qa.json'
        self.marker.write_text(json.dumps(
            {'privateQaOnly':True,'profile':str(self.data.resolve())}), encoding='utf-8')
        self.env = {'APPDATA':str(self.roaming),
                    'TARAZ_QA_DATA_DIR':str(self.data),
                    'TARAZ_QA_MODE':'1','TARAZ_QA_CDP_PORT':'49152'}

    def test_off_by_default_even_in_qa(self):
        self.assertIsNone(private_qa_cdp_port(self.data,{}))
        self.assertIsNone(private_qa_cdp_port(self.data,{
            **self.env,'TARAZ_QA_CDP_PORT':None}))

    def test_explicit_marked_ephemeral_local_qa_allowed(self):
        self.assertEqual(private_qa_cdp_port(self.data,self.env),49152)

    def test_any_missing_or_forged_authority_blocks(self):
        for alterations in (
            {'TARAZ_QA_MODE':'0'},{'TARAZ_QA_DATA_DIR':str(self.roaming)},
            {'APPDATA':str(self.roaming.parent)},{'TARAZ_QA_CDP_PORT':'80'},
            {'TARAZ_QA_CDP_PORT':'49152 --allow-remote'},
            {'TARAZ_QA_CDP_PORT':'0'},{'TARAZ_QA_CDP_PORT':'065535'},
            {'TARAZ_QA_CDP_PORT':'65536'},
        ):
            with self.subTest(alterations=alterations):
                with self.assertRaises(PermissionError):
                    private_qa_cdp_port(self.data,{**self.env,**alterations})
        self.marker.write_text('{}',encoding='utf-8')
        with self.assertRaises(PermissionError):
            private_qa_cdp_port(self.data,self.env)


if __name__=='__main__':
    unittest.main()
