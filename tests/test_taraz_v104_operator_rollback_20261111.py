"""Actual immutable RC3 v104 -> v102 PS1 on disposable Windows installs.

Uses unedited generated operator PS1 and SHA-pinned authentic v104/v102 EXE
copies; no production install, profile or finance writes. This validates the
pointer-only rollback, not real installed activation or official finance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import taraz_v104_operator_rollback_20261111 as gate


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"),
                     "Win32 PowerShell 5.1 required")
class ExactRC3PinTests(unittest.TestCase):
    def test_real_rc3_preflight_checks_immutable_bytes(self):
        actual=gate.immutable_release_preflight()
        self.assertEqual(actual["exeSha256"],gate.WORKER26_PINSET["v104ExeSha256"])
        self.assertEqual(actual["zipSha256"],gate.RC3_ZIP_SHA256)
        self.assertEqual(actual["activationScriptSha256"],gate.RC3_ACTIVATION_SHA256)
        self.assertEqual(actual["activationPointerBackup"],"current-version-pre-1.0.4.txt")
        self.assertEqual(actual["activationLauncherBackup"],"Run-Taraz-pre-1.0.4.cmd")

    def test_read_only_preflight_does_not_mutate_candidate_root(self):
        before=set(gate.OUTPUT_ROOT.iterdir()) if gate.OUTPUT_ROOT.is_dir() else set()
        run=subprocess.run([sys.executable,"-B",str(Path(gate.__file__)),"--preflight"],
            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
        self.assertEqual(run.returncode,0,(run.stdout,run.stderr))
        self.assertEqual(json.loads(run.stdout)["exeSha256"],gate.WORKER26_PINSET["v104ExeSha256"])
        self.assertEqual(before,
                         set(gate.OUTPUT_ROOT.iterdir()) if gate.OUTPUT_ROOT.is_dir() else set())

    def test_required_immutable_source_metadata_and_contract(self):
        fixture=dict(gate.WORKER26_PINSET)
        accepted=gate.validate_pinset(fixture)
        self.assertEqual(accepted["runDirectory"], fixture["runDirectory"])
        for key in ("v104ExeSha256","offlineManifestSha256","buildReportSha256",
                    "sourceFreezeSha256","activeLauncherSha256","backupLauncherSha256"):
            variant=dict(fixture,**{key:None})
            with self.subTest(key=key), self.assertRaises(gate.RollbackBlocked):
                gate.validate_pinset(variant)
        for key in ("activationPointerBackupName","activationLauncherBackupName"):
            variant=dict(fixture,**{key:"untrusted-activation.txt"})
            with self.subTest(key=key), self.assertRaises(gate.RollbackBlocked):
                gate.validate_pinset(variant)
        with self.assertRaises(gate.RollbackBlocked):
            gate.validate_pinset(dict(fixture, launcherV102Compatible=False))

    def test_wrong_rc3_artifact_hash_fails_closed_and_creates_no_gate(self):
        from unittest.mock import patch
        before=set(gate.OUTPUT_ROOT.iterdir())
        changed=dict(gate.WORKER26_PINSET,v104ExeSha256="f"*64)
        with patch.object(gate,"WORKER26_PINSET",changed):
            with self.assertRaisesRegex(gate.RollbackBlocked,"hash"):
                gate.generate()
        self.assertEqual(set(gate.OUTPUT_ROOT.iterdir()),before)

    def test_real_generated_operator_manifest_sha(self):
        folder=Path(os.environ["TARAZ_V104_ROLLBACK_GATE"])
        self.assertEqual(folder.parent.resolve(),gate.OUTPUT_ROOT.resolve())
        self.assertRegex(folder.name,r"^rollback-gate-[0-9a-f]{12}$")
        manifest=json.loads((folder/"rollback-gate-manifest.json").read_text(encoding="utf-8"))
        operator=folder/gate.SCRIPT_NAME
        self.assertEqual(gate.digest(operator),manifest["scriptSha256"])
        self.assertEqual(manifest["fromVersion"],"1.0.4")
        self.assertEqual(manifest["toVersion"],"1.0.2")
        self.assertEqual(manifest["releasePinset"]["exeSha256"],gate.WORKER26_PINSET["v104ExeSha256"])
        self.assertFalse(manifest["rollbackExecuted"])
        self.assertFalse(manifest["productionTouched"])
        self.assertTrue(manifest["requiresApply"])


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"),
                     "Win32 PowerShell 5.1 required")
class V104RealRC3DisposableRollbackTests(unittest.TestCase):
    """Exact generated operator PS1, byte-exact genuine v104 / v102 copies."""

    @classmethod
    def setUpClass(cls):
        cls.real_old = (Path(os.environ["LOCALAPPDATA"]) / "Programs" /
                        "Taraz" / "versions" / "1.0.2" / "Taraz.exe")
        cls.real_new = gate.OUTPUT_ROOT/gate.WORKER26_PINSET["runDirectory"]/"offline-update"/"Taraz.exe"
        if gate.digest(cls.real_old) != gate.V102_EXE_SHA256:
            raise AssertionError("Authentic read-only v1.0.2 EXE not pinned")
        if gate.digest(cls.real_new) != gate.WORKER26_PINSET["v104ExeSha256"]:
            raise AssertionError("Actual immutable RC3 v1.0.4 EXE differs")
        if not gate.OUTPUT_ROOT.is_dir():
            raise AssertionError("V104 candidate output root missing")
        cls.qa = Path(os.environ["TARAZ_V104_ROLLBACK_GATE"])
        if cls.qa.parent.resolve()!=gate.OUTPUT_ROOT.resolve():
            raise AssertionError("Real RC3 gate output outside v104 root")
        cls.script=cls.qa/gate.SCRIPT_NAME
        operator_hash=json.loads((cls.qa/"rollback-gate-manifest.json").read_text(encoding="utf-8"))["scriptSha256"]
        if gate.digest(cls.script)!=operator_hash:
            raise AssertionError("Original generated RC3 operator PS1 not pinned")
        actual_script=cls.script.read_text(encoding="utf-8")
        if "CheckVersion $new 4" not in actual_script or "CheckVersion $new 3" in actual_script:
            raise AssertionError("Operator script must require authentic PE v104")
        cls.launcher_source=Path(os.environ["LOCALAPPDATA"])/"Programs"/"Taraz"/"Run-Taraz.cmd"
        if gate.digest(cls.launcher_source)!=gate.WORKER26_PINSET["activeLauncherSha256"]:
            raise AssertionError("Original v102 launcher changed")

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="qa-disposable-",dir=self.qa)
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.local=self.root/"private-localappdata"
        self.appdata=self.root/"private-appdata"
        self.install=self.local/"Programs"/"Taraz"
        olddir=self.install/"versions"/"1.0.2"
        newdir=self.install/"versions"/"1.0.4"
        olddir.mkdir(parents=True)
        newdir.mkdir(parents=True)
        self.old=olddir/"Taraz.exe"
        self.new=newdir/"Taraz.exe"
        shutil.copyfile(self.real_old,self.old)
        shutil.copyfile(self.real_new,self.new)
        self.pointer=self.install/"current-version.txt"
        self.pointer.write_bytes(b"1.0.4\r\n")
        self.backup=self.install/"current-version-pre-1.0.4.txt"
        self.backup.write_bytes(b"1.0.2\r\n")
        self.launcher=self.install/"Run-Taraz.cmd"
        shutil.copyfile(self.launcher_source,self.launcher)
        self.launcher_backup=self.install/"Run-Taraz-pre-1.0.4.cmd"
        shutil.copyfile(self.launcher_source,self.launcher_backup)
        self.appdata.mkdir()
        self.ledger=self.appdata/"Taraz"/"finance-sentinel.sqlite3"
        self.ledger.parent.mkdir()
        self.ledger.write_bytes(b"QA-DISPOSABLE-FINANCE-SENTINEL-NO-CUSTOMER-DATA")
        self.ledger_sha=gate.digest(self.ledger)
        # Invoke EXACT generated immutable PS1. Only the test wrapper is new.

    def tearDown(self):
        self.assertEqual(gate.digest(self.ledger),self.ledger_sha)
        self.assertEqual(gate.digest(self.old),gate.V102_EXE_SHA256)
        self.assertEqual(gate.digest(self.new),gate.WORKER26_PINSET["v104ExeSha256"])

    def run_gate(self,*arguments:str,cim:str="function Get-CimInstance { @() }"):
        wrapper=self.root/"invoke-fixture.ps1"
        quoted=str(self.script).replace("'","''")
        wrapper.write_text(cim+"\n& '"+quoted+"' "+' '.join(arguments)+"\n",
                           encoding="utf-8-sig")
        env=dict(os.environ,LOCALAPPDATA=str(self.local),APPDATA=str(self.appdata),
                 TEMP=str(self.root),TMP=str(self.root))
        return subprocess.run([shutil.which("powershell.exe"),"-NoProfile","-NonInteractive",
            "-ExecutionPolicy","Bypass","-File",str(wrapper)],env=env,
            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=40)

    def must_block(self,needle:str,*args:str,cim:str="function Get-CimInstance { @() }"):
        initial=self.pointer.read_bytes() if self.pointer.exists() else None
        run=self.run_gate(*args,cim=cim)
        self.assertNotEqual(run.returncode,0,(run.stdout,run.stderr))
        self.assertIn(needle.casefold(),(run.stdout+run.stderr).casefold())
        if initial is not None:
            self.assertEqual(self.pointer.read_bytes(),initial)
        self.assertFalse((self.install/"current-version-pre-rollback-1.0.4.txt").exists())
        return run

    def test_preflight_no_files_changed(self):
        def state():
            return {str(p.relative_to(self.root)):gate.digest(p)
                for base in (self.install,self.appdata) for p in base.rglob("*")
                if p.is_file()}
        before=state()
        run=self.run_gate()
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn("READY_FOR_OPERATOR_ROLLBACK_1.0.4_TO_1.0.2_NO_CHANGES",run.stdout)
        self.assertEqual(state(),before)

    def test_apply_changes_only_pointer_and_creates_dedicated_backup(self):
        before_launcher=self.launcher.read_bytes()
        result=self.run_gate("-Apply")
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.pointer.read_bytes(),b"1.0.2\r\n")
        self.assertEqual((self.install/"current-version-pre-rollback-1.0.4.txt").read_bytes(),
                         b"1.0.4\r\n")
        self.assertEqual(self.backup.read_bytes(),b"1.0.2\r\n")
        self.assertEqual(self.launcher.read_bytes(),before_launcher)
        self.assertEqual(self.launcher_backup.read_bytes(),before_launcher)
        self.assertFalse((self.install/"current-version-rollback-to-1.0.2-pending.txt").exists())
        again=self.run_gate("-Apply")
        self.assertNotEqual(again.returncode,0)

    def test_changed_pointer_blocks(self):
        self.pointer.write_bytes(b"1.0.3\r\n")
        self.must_block("pointer","-Apply")

    def test_missing_pointer_activation_backup_blocks(self):
        self.backup.unlink()
        self.must_block("required path","-Apply")

    def test_corrupt_pointer_activation_backup_blocks(self):
        self.backup.write_bytes(b"1.0.1\r\n")
        self.must_block("original 1.0.2 pointer backup","-Apply")

    def test_missing_launcher_activation_backup_blocks(self):
        self.launcher_backup.unlink()
        self.must_block("required path","-Apply")

    def test_corrupt_launcher_activation_backup_blocks(self):
        self.launcher_backup.write_bytes(b"@echo off\r\nTAMPER")
        self.must_block("launcher","-Apply")

    def test_corrupt_active_launcher_blocks(self):
        self.launcher.write_bytes(b"@echo off\r\nTAMPER")
        self.must_block("launcher","-Apply")

    def test_hardlinked_pointer_blocks(self):
        os.link(self.pointer,self.root/"hardlink-pointer.txt")
        self.must_block("hardlink","-Apply")

    def test_hardlinked_activation_launcher_backup_blocks(self):
        os.link(self.launcher_backup,self.root/"hardlink-launcher.cmd")
        self.must_block("hardlink","-Apply")

    def test_hardlinked_current_v104_slot_blocks(self):
        os.link(self.new,self.root/"hardlink-surrogate-v103.bin")
        self.must_block("hardlink","-Apply")

    def test_hardlinked_old_v102_slot_blocks(self):
        os.link(self.old,self.root/"hardlink-original-v102.bin")
        self.must_block("hardlink","-Apply")

    def test_pointer_reparse_symlink_blocks(self):
        outside=self.root/"test-only-unlinked-pointer.txt"
        outside.write_bytes(self.pointer.read_bytes())
        self.pointer.unlink()
        try:self.pointer.symlink_to(outside)
        except (OSError,NotImplementedError):
            self.skipTest("No Windows symlink privilege")
        self.must_block("linked/junction","-Apply")

    def test_ancestor_junction_blocks(self):
        # Genuine NTFS junction, created only beneath disposable fixture.
        # No global junction or user profile is touched.
        staging=self.root/"real-versions"
        (self.install/"versions").rename(staging)
        cmd=subprocess.run(["cmd.exe","/c","mklink","/J",
            str(self.install/"versions"),str(staging)],capture_output=True,text=True)
        if cmd.returncode != 0:self.skipTest("Junction unavailable in test VM")
        self.must_block("linked/junction","-Apply")

    def test_readonly_pointer_acl_blocks(self):
        self.pointer.chmod(stat.S_IREAD)
        try:self.must_block("read-only","-Apply")
        finally:self.pointer.chmod(stat.S_IWRITE)

    def test_real_explicit_deny_windows_acl_blocks(self):
        # Disposable synthetic pointer only, never a real installed profile.
        before=self.pointer.read_bytes()
        sid=subprocess.run([shutil.which("powershell.exe"),"-NoProfile",
            "-NonInteractive","-Command",
            "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=15)
        self.assertEqual(sid.returncode,0,sid.stderr)
        user_sid=sid.stdout.strip()
        self.assertRegex(user_sid,r"^S-1-5-")
        deny=subprocess.run(["icacls.exe",str(self.pointer),"/deny",
            "*"+user_sid+":(WD)"],capture_output=True,text=True,
            encoding="utf-8",errors="replace",timeout=15)
        self.assertEqual(deny.returncode,0,deny.stderr)
        try:
            run=self.run_gate("-Apply")
            self.assertNotEqual(run.returncode,0,(run.stdout,run.stderr))
            self.assertTrue(any(marker in (run.stdout+run.stderr).casefold()
                for marker in ("acl","inaccessible required path","access to the path")),
                (run.stdout,run.stderr))
        finally:
            restore=subprocess.run(["icacls.exe",str(self.pointer),"/remove:d",
                "*"+user_sid],capture_output=True,text=True,
                encoding="utf-8",errors="replace",timeout=15)
            self.assertEqual(restore.returncode,0,restore.stderr)
        self.assertEqual(self.pointer.read_bytes(),before)

    def test_acl_query_failure_is_fail_closed(self):
        result=self.must_block("ACL","-Apply",
            cim="function Get-CimInstance { @() }\nfunction Get-Acl { throw 'QA Synthetic ACL outage' }")
        self.assertNotEqual(result.returncode,0)

    def test_missing_original_v102_exe_blocks(self):
        self.old.rename(self.root/"old-v102-test-only.bin")
        try:self.must_block("required path","-Apply")
        finally:(self.root/"old-v102-test-only.bin").rename(self.old)

    def test_original_v102_executable_tamper_blocks(self):
        with self.old.open("ab") as stream:stream.write(b"QA-TAMPER")
        try:self.must_block("Original v1.0.2 binary hash","-Apply")
        finally:shutil.copyfile(self.real_old,self.old)

    def test_active_taraz_process_blocks(self):
        self.must_block("process is running","-Apply",
            cim="function Get-CimInstance { [pscustomobject]@{Name='Taraz.exe'} }")

    def test_process_query_failure_blocks(self):
        self.must_block("process inactivity","-Apply",
            cim="function Get-CimInstance { throw 'QA CIM outage' }")

    def test_existing_rollback_backup_blocks(self):
        (self.install/"current-version-pre-rollback-1.0.4.txt").write_text("occupied")
        run=self.run_gate("-Apply")
        self.assertNotEqual(run.returncode,0)
        self.assertIn("never overwrite",run.stderr.casefold())
        self.assertEqual(self.pointer.read_bytes(),b"1.0.4\r\n")

    def test_existing_pending_pointer_blocks(self):
        (self.install/"current-version-rollback-to-1.0.2-pending.txt").write_text("occupied")
        self.must_block("never overwrite","-Apply")


if __name__=="__main__":
    unittest.main()
