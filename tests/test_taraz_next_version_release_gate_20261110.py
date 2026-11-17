"""Synthetic READ-ONLY release-gate contract tests. No real Taraz account data."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "qa_taraz_next_version_release_gate_20261110",
    ROOT / "scripts" / "qa_taraz_next_version_release_gate_20261110.py",
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def write_json(file: Path, data: dict) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data), encoding="utf8")


def minimal_source(root: Path, *, version: str = "1.0.0") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir()
    (root / "taraz_desktop.py").write_text(
        "class TarazAPI:\n"
        " def releaseCheck(self): raise RuntimeError('not configured')\n"
        " def releaseDownload(self): raise RuntimeError('not configured')\n"
        " def releaseInstall(self): raise RuntimeError('not configured')\n",
        encoding="utf8",
    )
    (root / "taraz_integration.py").write_text("def review_request(): pass\n", encoding="utf8")
    (root / "src" / "standalone_accounting_workspace.jsx").write_text(
        "export const workspace = 1;\n", encoding="utf8"
    )
    (root / "src" / "taraz_context_help.jsx").write_text(
        "export const help = 1;\n", encoding="utf8"
    )
    (root / "src" / "taraz_sileo_feedback.jsx").write_text(
        "export const feedback = 1;\n", encoding="utf8"
    )
    write_json(root / "package.json", {
        "version": version, "scripts": {
            "dist:rc": "python -B scripts/build_integrated_v122.py"
        }
    })
    write_json(root / "package-lock.json", {
        "version": version, "packages": {"": {"version": version}}
    })
    return root


def synthetic_pe() -> bytes:
    binary = bytearray(160)
    binary[0:2] = b"MZ"
    binary[0x3C:0x40] = (128).to_bytes(4, "little")
    binary[128:132] = b"PE\0\0"
    return bytes(binary)


class ReleaseGateSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="taraz-release-no-mutate-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def candidate(self, version="1.0.1", *,
                  sha_override=None, name="Taraz-Setup-1.0.1.exe"):
        artifact = self.root / name
        artifact.write_bytes(synthetic_pe())
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        manifest = self.root / "candidate-manifest.json"
        write_json(manifest, {
            "schemaVersion": 1, "application": "Taraz",
            "version": version, "installerPath": str(artifact),
            "installerSha256": sha_override or digest,
            "installerBytes": artifact.stat().st_size,
        })
        return manifest, artifact

    def test_strict_stable_semver_and_minimum_higher_version(self):
        self.assertEqual(gate.version_tuple("1.0.1"), (1, 0, 1))
        self.assertEqual(gate.version_tuple("2.0.0"), (2, 0, 0))
        for invalid in ("1.0.0-rc1", "1.0", "v1.0.1", "01.0.1",
                        "1.0.0+qa", "", "1.0.1;rm", "10000.0.0", None):
            with self.subTest(invalid=invalid), self.assertRaises(gate.GateBlocked):
                gate.version_tuple(invalid)
        manifest, _ = self.candidate(version="1.0.0")
        outcome = gate.inspect_candidate(None, manifest, {"version": "1.0.0"},
                                         qa_root=self.root)
        self.assertEqual(outcome["status"], "NO_GO_STATIC_CANDIDATE")
        self.assertIn("STRICTLY higher", outcome["reason"])

    def test_source_inventory_matches_builder_style_and_is_read_only(self):
        source = minimal_source(self.root / "source")
        before = sorted((str(p.relative_to(source)), p.stat().st_mtime_ns)
                        for p in source.rglob("*") if p.is_file())
        result = gate.inspect_source(source)
        after = sorted((str(p.relative_to(source)), p.stat().st_mtime_ns)
                       for p in source.rglob("*") if p.is_file())
        self.assertEqual(before, after, "inspecting source must never write")
        self.assertEqual(result["version"], "1.0.0")
        self.assertEqual(result["lockVersion"], "1.0.0")
        self.assertTrue(result["updaterUnconfigured"])
        self.assertFalse(result["installerBuilderPresent"])
        self.assertRegex(result["snapshotSha256"], r"^[a-f0-9]{64}$")
        self.assertGreater(result["sourceInputCount"], 5)

    def test_source_snapshot_detects_mutation_and_rejects_missing_mandatory(self):
        source = minimal_source(self.root / "source")
        digest = gate.source_snapshot(source)["sha256"]
        (source / "src" / "taraz_context_help.jsx").write_text("changed", encoding="utf8")
        self.assertNotEqual(gate.source_snapshot(source)["sha256"], digest)
        (source / "src" / "taraz_context_help.jsx").unlink()
        with self.assertRaisesRegex(gate.GateBlocked, "Missing mandatory"):
            gate.source_snapshot(source)

    def test_lockfile_must_match_source_version(self):
        source = minimal_source(self.root / "source")
        write_json(source / "package-lock.json", {
            "version": "1.0.2", "packages": {"": {"version": "1.0.0"}}
        })
        with self.assertRaisesRegex(gate.GateBlocked, "version mismatch"):
            gate.inspect_source(source)

    def test_candidate_manifest_digest_version_pe_is_only_declared(self):
        manifest, binary = self.candidate()
        source = {"version": "1.0.1"}
        mtime = binary.stat().st_mtime_ns
        outcome = gate.inspect_candidate("1.0.1", manifest, source, qa_root=self.root)
        self.assertEqual(outcome["status"], "HASH_MATCH_DECLARED_VERSION_ONLY")
        self.assertTrue(outcome["declaredVersionNotBinaryVerified"])
        self.assertFalse(outcome["signedInstallerVerified"])
        self.assertFalse(outcome["installerExecutionPerformed"])
        self.assertEqual(binary.stat().st_mtime_ns, mtime)
        self.assertEqual(binary.read_bytes(), synthetic_pe())

    def test_candidate_untrusted_version_source_mismatch_is_no_go(self):
        manifest, _ = self.candidate()
        outcome = gate.inspect_candidate(None, manifest, {"version": "1.0.0"},
                                         qa_root=self.root)
        self.assertEqual(outcome["status"], "NO_GO_STATIC_CANDIDATE")
        self.assertIn("does not match", outcome["reason"])
        wrong = gate.inspect_candidate("1.0.2", manifest, {"version": "1.0.2"},
                                       qa_root=self.root)
        self.assertIn("differs", wrong["reason"])

    def test_candidate_corruption_extra_keys_and_qa_exe_fail_closed(self):
        manifest, binary = self.candidate()
        initial = json.loads(manifest.read_text(encoding="utf8"))
        binary.write_bytes(b"not a PE or the original digest")
        corrupt = gate.inspect_candidate(None, manifest, {"version": "1.0.1"},
                                         qa_root=self.root)
        self.assertEqual(corrupt["status"], "NO_GO_STATIC_CANDIDATE")
        self.assertIn("hash/size mismatch", corrupt["reason"])
        initial["trustedOfficialReceipt"] = True
        write_json(manifest, initial)
        extra = gate.inspect_candidate(None, manifest, {"version": "1.0.1"},
                                       qa_root=self.root)
        self.assertIn("unexpected fields", extra["reason"])
        manifest, _ = self.candidate(name="Taraz-MTR-QA-999.exe")
        rejected = gate.inspect_candidate(None, manifest, {"version": "1.0.1"},
                                          qa_root=self.root)
        self.assertIn("QA-only", rejected["reason"])

    def test_candidate_manifest_outside_permitted_root_rejected(self):
        external = self.root / "external.json"
        write_json(external, {})
        result = gate.inspect_candidate(None, external, {"version": "1.0.1"},
                                        qa_root=self.root / "bounded")
        self.assertEqual(result["status"], "NO_GO_STATIC_CANDIDATE")
        self.assertIn("outside", result["reason"])

    def test_bounded_json_symlink_and_invalid_manifest(self):
        file = self.root / "big.json"
        file.write_bytes(b"{" + b"x" * gate.MAX_JSON_BYTES + b"}")
        with self.assertRaisesRegex(gate.GateBlocked, "size limit"):
            gate._json(file)
        file.write_text("{}", encoding="utf8")
        with self.assertRaisesRegex(gate.GateBlocked, "size bounds"):
            gate._file_hash(file, limit=1)
        link = self.root / "linked.json"
        try:
            link.symlink_to(file)
        except OSError:
            self.skipTest("Windows symlink privileges unavailable")
        with self.assertRaisesRegex(gate.GateBlocked, "link or junction"):
            gate._json(link)

    def test_forged_green_reports_never_authorize_release(self):
        full = {
            "verified": True, "preMoveDurableIntentPresent": True,
            "perRequestLockPresent": True,
        }
        source = {"version": "1.0.1", "updaterUnconfigured": False,
                  "updaterVerifiedConfigured": True, "installerBuilderPresent": True}
        qa = {"status": "QA_BUNDLE_VERIFIED_NOT_RELEASE",
              "sourceIntegrationModuleInPYZ": {
                  name: True for name in gate.INTEGRATION_MODULES
              }}
        candidate = {"status": "HASH_MATCH_DECLARED_VERSION_ONLY",
                     "signedInstallerVerified": True,
                     "fakeOfficialFinanceReceipt": True}
        observed = gate.decision(full, source, qa, candidate)
        self.assertEqual(observed["decision"], "NO_GO")
        self.assertFalse(observed["releaseApproved"])
        self.assertFalse(observed["officialFinanceReceiptVerified"])
        self.assertIn("REAL_INSTALL_AUTH_AND_POST_UPGRADE_SMOKE_NOT_PROVEN",
                      observed["blockers"])

    def test_qa_only_report_cannot_be_promoted_without_actual_archive(self):
        base = self.root / "qa-root"
        fake = base / "qa-fake" / "qa-build-report.json"
        write_json(fake, {"status": "QA_BUNDLE_VERIFIED", "qaOnly": True,
                          "installed": True, "releaseReady": True})
        with self.assertRaisesRegex(gate.GateBlocked, "bounded QA-only status"):
            gate.inspect_qa(fake, {"snapshotSha256": "a"*64,
                                   "sourceInputCount": 1}, qa_parent=base)

    def test_missing_source_is_no_go_without_install_or_finance(self):
        source = self.root / "absent"
        with patch.object(gate, "SOURCE", source):
            observed = gate.run(root=source,
                exe=self.root / "missing.exe",
                qa_report=self.root / "missing-report.json",
                candidate_version="1.0.1")
        self.assertEqual(observed["decision"], "NO_GO")
        self.assertFalse(observed["installedExecutableLaunched"])
        self.assertFalse(observed["installerBuiltOrLaunched"])
        self.assertFalse(observed["ledgerOrProfileAccessed"])
        self.assertEqual(observed["evidence"]["source"]["status"], "UNVERIFIED")
        self.assertEqual(observed["evidence"]["candidate"]["status"],
                         "NO_GO_STATIC_CANDIDATE")

    def test_gate_script_has_no_external_write_install_or_network_imports(self):
        script = (ROOT / "scripts" /
                  "qa_taraz_next_version_release_gate_20261110.py").read_text(
                      encoding="utf8")
        for forbidden in (
            "subprocess.run", "Popen(", "os.remove(", "os.unlink(",
            "shutil.copy", "mkdir(", "write_text(", "write_bytes(",
            "sqlite3.connect(", "requests.", "urllib.request", "socket.socket",
        ):
            self.assertNotIn(forbidden, script, forbidden)
        self.assertIn('decision": "NO_GO"', script)


if __name__ == "__main__":
    unittest.main()
