"""Real Windows disposable install/activation/rollback and v1.0.5 build gates."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import build_taraz_v105_aaas_20261111 as v105


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def put(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def fixture(root: Path) -> tuple[Path, dict[str, Path]]:
    local = root / "isolated-user-localappdata"
    app = local / "Programs" / "Taraz"
    old = app / "versions" / "1.0.4" / "Taraz.exe"
    launcher = app / "Run-Taraz.cmd"
    pointer = app / "current-version.txt"
    put(old, b"synthetic-v104-program-only")
    put(launcher, b"@echo off\r\nversions\\%TARAZ_VERSION%\\Taraz.exe\r\n")
    put(pointer, b"1.0.4\r\n")
    package = root / "offline-update"
    payload = package / "Taraz.exe"
    put(payload, b"synthetic-v105-new-program-only")
    put(package / "update-manifest.json", json.dumps({
        "targetVersion": "1.0.5", "qaOnly": False,
        "exeSha256": v105.sha(payload),
        "installedBaselineSha256": v105.sha(old),
    }).encode("utf-8"))
    rendered = v105.render_scripts(
        v105.sha(payload), base_sha=v105.sha(old),
        pointer_sha=v105.sha(pointer), launcher_sha=v105.sha(launcher))
    for name, body in rendered.items():
        put(package / name, body.encode("utf-8"))
    return local, {"old": old, "launcher": launcher, "pointer": pointer,
                   "payload": payload, "package": package,
                   "new": app / "versions" / "1.0.5" / "Taraz.exe",
                   "backup": app / "current-version-pre-1.0.5.txt"}


def execute(path: Path, local: Path, apply: bool = False) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(local)
    args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
            "Bypass", "-File", str(path)]
    if apply:
        args.append("-Apply")
    return subprocess.run(args, env=environment, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=50)


class TarazAaaSBuilderTests(unittest.TestCase):
    def test_stages_105_only_in_isolated_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / "package.json").write_text(
                '{"name":"taraz-accounting","version":"1.0.0"}', encoding="utf-8")
            (source / "package-lock.json").write_text(json.dumps({
                "name": "taraz-accounting", "version": "1.0.0",
                "packages": {"": {"version": "1.0.0"}}}), encoding="utf-8")
            (source / "taraz_desktop.py").write_text(
                "from __future__ import annotations\nprint('test')\n", encoding="utf-8")
            result = v105.stage_version(source)
            self.assertEqual(json.loads((source / "package.json").read_text())["version"], "1.0.5")
            self.assertEqual(json.loads((source / "package-lock.json").read_text())["packages"][""]["version"], "1.0.5")
            self.assertIn("QA_ONLY = False", (source / "taraz_release_version.py").read_text())
            self.assertIn("1.0.5", (source / "taraz_desktop.py").read_text())
            self.assertEqual(result["entrypoint"], v105.sha(source / "taraz_desktop.py"))
            with self.assertRaises(v105.BuildBlocked):
                v105.stage_version(source)

    def test_bad_version_and_qa_instrumented_entry_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / "package.json").write_text(
                '{"name":"taraz-accounting","version":"1.0.4"}', encoding="utf-8")
            (source / "package-lock.json").write_text(json.dumps({
                "name": "taraz-accounting", "version": "1.0.4",
                "packages": {"": {"version": "1.0.4"}}}), encoding="utf-8")
            (source / "taraz_desktop.py").write_text(
                "from __future__ import annotations\n_taraz_qa_launch_gate()\n", encoding="utf-8")
            with self.assertRaises(v105.BuildBlocked):
                v105.stage_version(source)

    def test_scripts_have_exact_versions_sha_and_no_delete_or_payload_overwrite(self):
        scripts = v105.render_scripts("c" * 64)
        self.assertEqual(set(scripts), {
            "Install-Taraz-V105.ps1", "Activate-Taraz-V105.ps1",
            "Rollback-Taraz-V105.ps1"})
        combined = "\n".join(scripts.values())
        self.assertIn("versions\\1.0.4\\Taraz.exe", combined)
        self.assertIn("versions\\1.0.5\\Taraz.exe", combined)
        self.assertIn(v105.BASE_EXE_SHA, combined)
        self.assertIn(v105.LAUNCHER_SHA, combined)
        self.assertIn(v105.BASE_POINTER_SHA, combined)
        self.assertIn("[IO.FileMode]::CreateNew", combined)
        self.assertIn("[IO.File]::Replace", combined)
        self.assertNotIn("Remove-Item", combined)
        self.assertNotIn("TARAZ_QA_MODE", combined)
        self.assertNotIn("__NEW_EXE_SHA__", combined)
        with self.assertRaises(v105.BuildBlocked):
            v105.render_scripts("not-a-sha")

    def test_build_explicit_freeze_sha_is_required_before_output(self):
        with self.assertRaisesRegex(v105.BuildBlocked, "Prime-approved exact source-freeze"):
            v105.build(freeze_sha="")
        with self.assertRaisesRegex(v105.BuildBlocked, "Prime-approved exact source-freeze"):
            v105.build(freeze_sha="deadbeef")

    def test_existing_real_candidate_if_created(self):
        if not v105.OUTPUT.is_dir():
            self.skipTest("No frozen 1.0.5 build yet")
        built = []
        for folder in v105.OUTPUT.glob("build-*"):
            report_file = folder / "build-report.json"
            if not report_file.is_file():
                continue
            report = json.loads(report_file.read_text(encoding="utf-8"))
            if report.get("status") == "V105_AAAS_NON_QA_BUILT_NOT_INSTALLED":
                built.append((folder, report))
        if not built:
            self.skipTest("No successful 1.0.5 PE compilation yet")
        folder, report = built[-1]
        exe = folder / "binary" / "Taraz.exe"
        self.assertEqual(v105.sha(exe), report["exeSha256"])
        self.assertEqual(v105.pe_version(exe), "1.0.5.0")
        self.assertTrue(report["compiled"]["compiledByteParity"])
        self.assertTrue(report["compiled"]["compiledOrderAndInvoice"])
        with zipfile.ZipFile(report["zip"]) as archive:
            self.assertEqual(len(archive.namelist()), 8)
            self.assertEqual(set(archive.namelist()), set(report["memberSha256"]))
            for filename, checksum in report["memberSha256"].items():
                self.assertEqual(hash_bytes(archive.read(filename)), checksum)
        self.assertEqual(v105.sha(Path(report["manifest"])), report["manifestSha256"])
        self.assertFalse(json.loads(Path(report["manifest"]).read_text())["qaOnly"])


@unittest.skipUnless(os.name == "nt", "Real Windows PowerShell 5.1 required")
class TarazAaaSInstallerTests(unittest.TestCase):
    def test_disposable_install_activation_rollback_and_idempotence(self):
        with tempfile.TemporaryDirectory() as temporary:
            local, paths = fixture(Path(temporary))
            old_hash = v105.sha(paths["old"])
            payload_hash = v105.sha(paths["payload"])
            scripts = paths["package"]
            installer = scripts / "Install-Taraz-V105.ps1"
            activator = scripts / "Activate-Taraz-V105.ps1"
            rollback = scripts / "Rollback-Taraz-V105.ps1"
            for name, message in (("Install-Taraz-V105.ps1", "READY_V105_SIDE_BY_SIDE_INSTALL"),):
                result = execute(scripts / name, local)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(message, result.stdout)
            installed = execute(installer, local, apply=True)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertIn("INSTALLED_V105_SIDE_BY_SIDE_POINTER_STILL_V104", installed.stdout)
            self.assertEqual(paths["pointer"].read_bytes(), b"1.0.4\r\n")
            self.assertEqual(v105.sha(paths["new"]), payload_hash)
            repeated_install = execute(installer, local, apply=True)
            self.assertNotEqual(repeated_install.returncode, 0)
            ready = execute(activator, local)
            self.assertEqual(ready.returncode, 0, ready.stderr)
            self.assertIn("READY_V105_ACTIVATION", ready.stdout)
            activated = execute(activator, local, apply=True)
            self.assertEqual(activated.returncode, 0, activated.stderr)
            self.assertEqual(paths["pointer"].read_bytes(), b"1.0.5\r\n")
            self.assertEqual(paths["backup"].read_bytes(), b"1.0.4\r\n")
            ready = execute(rollback, local)
            self.assertEqual(ready.returncode, 0, ready.stderr)
            self.assertIn("READY_V105_ROLLBACK_TO_V104", ready.stdout)
            restored = execute(rollback, local, apply=True)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual(paths["pointer"].read_bytes(), b"1.0.4\r\n")
            self.assertEqual(v105.sha(paths["old"]), old_hash)
            self.assertEqual(v105.sha(paths["new"]), payload_hash)
            repeated = execute(rollback, local, apply=True)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertIn("ALREADY_ROLLED_BACK_V104_NO_CHANGE", repeated.stdout)

    def test_tampered_payload_and_installed_baseline_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            local, paths = fixture(Path(temporary))
            paths["payload"].write_bytes(b"tampered")
            result = execute(paths["package"] / "Install-Taraz-V105.ps1", local, apply=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(paths["new"].exists())
            self.assertEqual(paths["pointer"].read_bytes(), b"1.0.4\r\n")
        with tempfile.TemporaryDirectory() as temporary:
            local, paths = fixture(Path(temporary))
            paths["old"].write_bytes(b"tampered")
            result = execute(paths["package"] / "Install-Taraz-V105.ps1", local, apply=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(paths["new"].exists())

    def test_activation_and_rollback_require_exact_baseline_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            local, paths = fixture(Path(temporary))
            put(paths["new"], paths["payload"].read_bytes())
            result = execute(paths["package"] / "Activate-Taraz-V105.ps1", local, apply=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            paths["backup"].write_bytes(b"bad original pointer")
            blocked = execute(paths["package"] / "Rollback-Taraz-V105.ps1", local, apply=True)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(paths["pointer"].read_bytes(), b"1.0.5\r\n")


if __name__ == "__main__":
    unittest.main()
