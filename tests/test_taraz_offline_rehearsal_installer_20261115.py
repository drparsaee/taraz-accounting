"""Rehearsal installer syntax and non-production release lock."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from scripts.build_taraz_v106_aaas_20261111 import render_scripts


@unittest.skipUnless(os.name == 'nt', 'Requires Windows PowerShell AST')
class InstallerRehearsalSourceTests(unittest.TestCase):
    def test_exact_emitters_parse_with_windows_powershell_without_execution(self):
        emitted = render_scripts('a' * 64)
        self.assertEqual(len(emitted), 3)
        powershell = Path(os.environ['SystemRoot']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
        parser = (
            '$errors=$null;$tokens=$null;'
            '[System.Management.Automation.Language.Parser]::ParseFile('
            '$env:TARAZ_QA_PARSE_FILE,[ref]$tokens,[ref]$errors) | Out-Null;'
            'if($errors.Count -gt 0){$errors | ForEach-Object {$_.Message};exit 42}')
        with TemporaryDirectory(prefix='qa-taraz-installer-parser-') as folder:
            for name, text in emitted.items():
                with self.subTest(name=name):
                    file = Path(folder) / name
                    file.write_text(text, encoding='utf-8')
                    environment = {**os.environ, 'TARAZ_QA_PARSE_FILE': str(file)}
                    result = subprocess.run([str(powershell), '-NoProfile',
                        '-NonInteractive', '-Command', parser], env=environment,
                        capture_output=True, timeout=20)
                    self.assertEqual(result.returncode, 0,
                        (result.stdout + result.stderr).decode('utf-8', errors='replace')[:600])

    def test_real_apply_stays_blocked_until_production_gates_pass(self):
        scripts = render_scripts('a' * 64)
        for text in scripts.values():
            self.assertIn('RequireIsolatedRehearsal', text)
            self.assertIn("$env:TARAZ_QA_MODE -ne '1'", text)
            self.assertIn("Den y".replace(' ', ''), text)
        self.assertIn("if(-not $Rehearsal)", scripts['Install-Taraz-V106.ps1'])
        self.assertIn("if(-not $Rehearsal)", scripts['Activate-Taraz-V106.ps1'])
        self.assertIn('Release hold: full profile backup',
                      scripts['Install-Taraz-V106.ps1'])
        self.assertIn('Release hold: full profile backup',
                      scripts['Activate-Taraz-V106.ps1'])


if __name__ == '__main__':
    unittest.main()
