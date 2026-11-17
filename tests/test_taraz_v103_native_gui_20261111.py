"""Safety and native evidence gates for the uninstalled Taraz 1.0.3 binary."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import CodeType
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import qa_taraz_v103_native_gui_20261111 as native


class NativeGuiV103Acceptance(unittest.TestCase):
    def test_exact_binary_pin_and_existing_install_still_v102(self):
        evidence = native.pin()
        self.assertEqual(native.digest(native.EXE),native.EXE_SHA)
        self.assertEqual(evidence['installed']['version'],'1.0.2')
        self.assertTrue(evidence['installed']['futureFolderAbsent'])
        self.assertEqual(evidence['backup']['filesRehashed'],181)

    def test_no_interactive_desktop_api_or_production_install_action(self):
        source=Path(native.__file__).read_text(encoding='utf-8')
        tree=ast.parse(source)
        self.assertTrue(any(isinstance(node,ast.FunctionDef) and node.name=='stop_owned'
            for node in ast.walk(tree)))
        self.assertFalse(any(token in source for token in ('SwitchDesktop(',
            'SetForegroundWindow(', 'SetCursorPos(', 'SendInput(', 'SetThreadDesktop(')))
        self.assertFalse(any(word in source for word in (
            'os.startfile(', 'winreg.SetValue', 'winreg.CreateKey',
            'schtasks', 'sc.exe', 'icacls /grant everyone')))
        self.assertIn('CreateDesktopW',source)
        self.assertIn('lpDesktop',source)
        self.assertIn('CreateProcessW',source)
        self.assertIn('psutil.Process(root_pid)',source)
        self.assertIn('item.create_time() == created',source)

    def test_private_profile_environment_is_separate_and_qa_only(self):
        with tempfile.TemporaryDirectory(prefix='qa-taraz-test-') as temporary:
            root=Path(temporary)/'qa'/'runtime'
            roots={'roaming':root/'roaming'/'Taraz'}
            env=native.isolated_env(root,roots,root/'report.json',45411)
            for name in ('APPDATA','LOCALAPPDATA','TEMP','TMP','USERPROFILE'):
                self.assertTrue(Path(env[name]).is_relative_to(root))
                self.assertNotEqual(Path(env[name]).resolve(),Path(os.environ[name]).resolve())
            self.assertTrue(Path(env['TARAZ_QA_DATA_DIR']).is_relative_to(root))
            self.assertEqual(env['TARAZ_QA_MODE'],'1')
            self.assertIn('--remote-debugging-address=127.0.0.1',
                          env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'])

    def test_frozen_binary_python_archive_gates_cdp_on_internal_setting(self):
        from PyInstaller.archive.readers import CArchiveReader
        pyz=CArchiveReader(str(native.EXE)).open_embedded_archive('PYZ.pyz')
        module=pyz.extract('webview.platforms.edgechromium')
        methods=[module]
        while methods:
            code=methods.pop()
            nested=[v for v in code.co_consts if isinstance(v,CodeType)]
            methods.extend(nested)
            if code.co_name=='__init__' and {'AdditionalBrowserArguments','REMOTE_DEBUGGING_PORT'}.issubset(
                    set(code.co_names)|set(v for v in code.co_consts if isinstance(v,str))):
                import dis
                instructions=list(dis.get_instructions(code))
                switches=[str(ins.argval) for ins in instructions]
                self.assertIn(' --remote-debugging-port=',switches)
                self.assertIn('REMOTE_DEBUGGING_PORT',switches)
                self.assertIn('AdditionalBrowserArguments',switches)
                self.assertIn('POP_JUMP_IF_NONE',[ins.opname for ins in instructions])
                return
        self.fail('Actual frozen PYZ does not contain expected pywebview debug gate')

    def test_private_uia_navigation_uses_strict_non_financial_allowlist(self):
        source=native.PRIVATE_UIA_PS
        self.assertIn('noFinanceActionAttempted=$true',source)
        self.assertIn("'اطلاعات مدار'",source)
        self.assertIn("'بستن راهنما'",source)
        self.assertIn("'طراحی فرم فاکتور'",source)
        self.assertIn('Rejected non-allowlisted UIA action',source)
        self.assertIn('TarazPrivateHwndAudit',source)
        self.assertNotIn('SendInput',source)
        self.assertNotIn('SwitchDesktop',source)
        self.assertNotIn('SetCursorPos',source)

    def test_mismatched_binary_is_fail_closed_before_any_launch(self):
        with patch.object(native,'EXE_SHA','0'*64):
            with self.assertRaisesRegex(native.NativeBlocked,'SHA mismatch'):
                native.pin()

    def test_pinned_nonqa_gui_read_only_diagnostic_is_not_full_gui_approval(self):
        command=[sys.executable,'-B',str(native.__file__),'--static-only']
        result=subprocess.run(command,check=False,capture_output=True,text=True,
                              encoding='utf-8',errors='replace',timeout=90)
        self.assertEqual(result.returncode,0,msg=result.stderr[-200:])
        record=json.loads(result.stdout)
        self.assertEqual(record['status'],'STATIC_PIN_PASS_NATIVE_NOT_LAUNCHED')
        self.assertEqual(record['candidateSha256'],native.EXE_SHA)


if __name__=='__main__':
    unittest.main()
