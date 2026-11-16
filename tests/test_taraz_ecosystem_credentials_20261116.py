"""Real Windows DPAPI tests using disposable, dedicated QA directories only."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from taraz_ecosystem_credentials import (
    CredentialVaultError, TarazEcosystemCredentialVault,
)

WORKSPACE = "a" * 32
OTHER_WORKSPACE = "b" * 32
PIN = "c" * 64
WRONG_PIN = "d" * 64
PEER = "madar-peer-qa"
VAULT = "taraz-ecosystem-credentials.json"


@unittest.skipUnless(os.name == "nt", "Real current-user Windows DPAPI required")
class CredentialVaultWindowsTests(unittest.TestCase):
    def setUp(self):
        output = Path(__file__).resolve().parent / "output"
        self.assertTrue(output.is_dir())
        tmp = tempfile.TemporaryDirectory(prefix="taraz-credentials-qa-20261116-",
                                          dir=output)
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "host-selected-dedicated-vault"
        self.root.mkdir()
        self.vault = TarazEcosystemCredentialVault(self.root)

    def _pair(self, peer=PEER, workspace=WORKSPACE, pin=PIN):
        return self.vault.pair(workspace_id=workspace, peer_id=peer,
                               cert_sha256=pin)

    def _read(self):
        return (self.root / VAULT).read_bytes()

    def test_real_windows_dpapi_persists_installation_id_and_seals_token(self):
        installation = self.vault.initialize()
        self.assertRegex(installation, r"^[0-9a-f]{32}$")
        issued = self._pair()
        self.assertEqual(issued["installationId"], installation)
        self.assertRegex(issued["token"], r"^[A-Za-z0-9_-]{64}$")
        self.assertEqual(self.vault.require_token(workspace_id=WORKSPACE,
                         peer_id=PEER, cert_sha256=PIN), issued["token"])
        self.assertEqual(TarazEcosystemCredentialVault(self.root).installation_id(),
                         installation)
        self.assertNotIn(issued["token"].encode(), self._read())
        self.assertNotIn(issued["token"].encode(), b"".join(
            p.read_bytes() for p in self.root.iterdir() if p.is_file()))
        self.assertNotIn("token", self.vault.list_peers()[0])

    def test_rotation_replaces_token_and_revoke_persists(self):
        self.vault.initialize()
        issued = self._pair()
        rotated = self.vault.rotate(workspace_id=WORKSPACE, peer_id=PEER,
                                   cert_sha256=PIN)
        self.assertNotEqual(issued["token"], rotated)
        self.assertEqual(self.vault.require_token(workspace_id=WORKSPACE,
                         peer_id=PEER, cert_sha256=PIN), rotated)
        self.assertNotIn(issued["token"].encode(), self._read())
        self.vault.revoke(workspace_id=WORKSPACE, peer_id=PEER)
        self.assertTrue(self.vault.list_peers()[0]["revoked"])
        with self.assertRaises(CredentialVaultError):
            self.vault.require_token(workspace_id=WORKSPACE, peer_id=PEER,
                                     cert_sha256=PIN)
        with self.assertRaises(CredentialVaultError):
            self.vault.rotate(workspace_id=WORKSPACE, peer_id=PEER,
                              cert_sha256=PIN)
        with self.assertRaises(CredentialVaultError):
            self._pair()

    def test_wrong_cert_workspace_peer_are_rejected(self):
        self.vault.initialize()
        self._pair()
        for workspace, peer, pin in (
                (WORKSPACE, PEER, WRONG_PIN),
                (OTHER_WORKSPACE, PEER, PIN),
                (WORKSPACE, "forged-madar-peer", PIN)):
            with self.subTest(workspace=workspace, peer=peer, pin=pin):
                with self.assertRaises(CredentialVaultError):
                    self.vault.require_token(workspace_id=workspace, peer_id=peer,
                                             cert_sha256=pin)

    def test_reject_invalid_workspace_peer_and_certificate_before_write(self):
        self.vault.initialize()
        before = self._read()
        for workspace, peer, pin in (
                ("", PEER, PIN), ("not-an-id", PEER, PIN),
                (WORKSPACE, "../path", PIN), (WORKSPACE, "", PIN),
                (WORKSPACE, PEER, "z" * 64), (WORKSPACE, PEER, "A" * 64)):
            with self.subTest(workspace=workspace, peer=peer, pin=pin):
                with self.assertRaises(CredentialVaultError):
                    self._pair(peer, workspace, pin)
                self.assertEqual(self._read(), before)

    def test_new_installation_requires_empty_existing_dedicated_directory(self):
        with self.assertRaises(CredentialVaultError):
            TarazEcosystemCredentialVault(self.base / "missing")
        sentinel = self.root / "standalone-accounting.sqlite3"
        sentinel.write_bytes(b"synthetic-unchanged-ledger-marker")
        with self.assertRaises(CredentialVaultError):
            self.vault.initialize()
        self.assertEqual(sentinel.read_bytes(), b"synthetic-unchanged-ledger-marker")
        self.assertFalse((self.root / VAULT).exists())

    def test_reinitialize_refuses_overwrite(self):
        installation = self.vault.initialize()
        before = self._read()
        with self.assertRaises(CredentialVaultError):
            self.vault.initialize()
        self.assertEqual(self._read(), before)
        self.assertEqual(self.vault.installation_id(), installation)

    def test_missing_vault_read_is_strictly_read_only(self):
        with self.assertRaisesRegex(CredentialVaultError, "not been initialized"):
            self.vault.installation_id()
        with self.assertRaisesRegex(CredentialVaultError, "not been initialized"):
            self.vault.list_peers()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_paired_peers_are_scoped_independently(self):
        self.vault.initialize()
        first = self._pair()
        second = self._pair(peer=PEER, workspace=OTHER_WORKSPACE)
        self.assertNotEqual(first["token"], second["token"])
        self.assertEqual(len(self.vault.list_peers()), 2)
        self.vault.revoke(workspace_id=WORKSPACE, peer_id=PEER)
        self.assertEqual(self.vault.require_token(workspace_id=OTHER_WORKSPACE,
                         peer_id=PEER, cert_sha256=PIN), second["token"])

    def test_sealed_blob_tampering_fails_closed(self):
        self.vault.initialize()
        self._pair()
        doc = json.loads(self._read())
        sealed = bytearray(base64.b64decode(doc["sealed"]))
        sealed[len(sealed) // 2] ^= 1
        doc["sealed"] = base64.b64encode(sealed).decode()
        (self.root / VAULT).write_bytes(json.dumps(
            doc, sort_keys=True, separators=(",", ":")).encode())
        with self.assertRaises(CredentialVaultError):
            self.vault.list_peers()

    def test_outer_metadata_tampering_fails_closed(self):
        self.vault.initialize()
        self._pair()
        doc = json.loads(self._read())
        doc["installationId"] = "f" * 32
        (self.root / VAULT).write_bytes(json.dumps(
            doc, sort_keys=True, separators=(",", ":")).encode())
        with self.assertRaises(CredentialVaultError):
            self.vault.installation_id()

    def test_noncanonical_duplicate_fields_are_rejected(self):
        self.vault.initialize()
        (self.root / VAULT).write_bytes(
            b'{"format":"x","format":"y"}')
        with self.assertRaises(CredentialVaultError):
            self.vault.list_peers()

    def test_invalid_outer_version_type_fails_closed(self):
        self.vault.initialize()
        doc = json.loads(self._read())
        doc["version"] = True  # bool compares equal to integer 1 in Python.
        (self.root / VAULT).write_bytes(json.dumps(
            doc, sort_keys=True, separators=(",", ":")).encode())
        with self.assertRaises(CredentialVaultError):
            self.vault.installation_id()

    def test_missing_lock_member_does_not_recreate_trusted_concurrency_state(self):
        self.vault.initialize()
        (self.root / ".taraz-ecosystem-credentials.lock").unlink()
        before = self._read()
        with self.assertRaisesRegex(CredentialVaultError, "lock was removed"):
            self.vault.installation_id()
        self.assertEqual(self._read(), before)
        self.assertFalse((self.root / ".taraz-ecosystem-credentials.lock").exists())

    def test_private_acl_failure_cleans_new_lock_file(self):
        with patch("taraz_ecosystem_credentials._private_acl",
                   side_effect=CredentialVaultError("synthetic ACL rejection")):
            with self.assertRaisesRegex(CredentialVaultError, "ACL rejection"):
                self.vault.initialize()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_actual_dpapi_scope_prevents_moving_ciphertext_to_another_root(self):
        self.vault.initialize()
        self._pair()
        second = self.base / "second-private-root"
        second.mkdir()
        shutil.copy2(self.root / VAULT, second / VAULT)
        moved = TarazEcosystemCredentialVault(second)
        with self.assertRaises(CredentialVaultError):
            moved.list_peers()

    def test_missing_or_inaccessible_dpapi_key_fails_closed(self):
        self.vault.initialize()
        self._pair()
        with patch("taraz_ecosystem_credentials._unprotect",
                   side_effect=RuntimeError("unavailable Windows user key")):
            with self.assertRaisesRegex(CredentialVaultError, "DPAPI"):
                self.vault.installation_id()

    def test_vault_hardlink_refused(self):
        self.vault.initialize()
        link = self.base / "qa-hardlink"
        try:
            os.link(self.root / VAULT, link)
        except (OSError, NotImplementedError):
            self.skipTest("Hardlink not supported on test filesystem")
        with self.assertRaises(CredentialVaultError):
            self.vault.installation_id()

    def test_vault_symlink_refused(self):
        self.vault.initialize()
        original = self.root / VAULT
        relocated = self.base / "qa-relocated"
        original.rename(relocated)
        try:
            os.symlink(relocated, original)
        except (OSError, NotImplementedError):
            self.skipTest("Windows developer mode/symlink privilege unavailable")
        with self.assertRaises(CredentialVaultError):
            self.vault.installation_id()

    def test_new_unrelated_file_after_initialization_blocks_all_operations(self):
        self.vault.initialize()
        (self.root / "synthetic-unrelated.txt").write_text("leave untouched")
        with self.assertRaises(CredentialVaultError):
            self._pair()
        self.assertEqual((self.root / "synthetic-unrelated.txt").read_text(),
                         "leave untouched")

    def test_concurrent_duplicate_enrollment_never_overwrites(self):
        self.vault.initialize()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self._pair) for _ in range(2)]
            successes, blocked = [], []
            for future in futures:
                try:
                    successes.append(future.result())
                except CredentialVaultError as exc:
                    blocked.append(str(exc))
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(len(self.vault.list_peers()), 1)
        self.assertEqual(self.vault.require_token(workspace_id=WORKSPACE,
                         peer_id=PEER, cert_sha256=PIN), successes[0]["token"])

    def test_atomic_replace_failure_preserves_original_record(self):
        self.vault.initialize()
        issued = self._pair()
        before = self._read()
        with patch("taraz_ecosystem_credentials.os.replace",
                   side_effect=OSError("synthetic replace failure")):
            with self.assertRaisesRegex(OSError, "synthetic replace failure"):
                self.vault.rotate(workspace_id=WORKSPACE, peer_id=PEER,
                                  cert_sha256=PIN)
        self.assertEqual(self._read(), before)
        self.assertEqual(self.vault.require_token(workspace_id=WORKSPACE,
                         peer_id=PEER, cert_sha256=PIN), issued["token"])
        self.assertFalse(list(self.root.glob(".taraz-credential-update-*")))

    def test_interrupted_atomic_replace_discarded_and_committed_vault_survives(self):
        self.vault.initialize()
        issued = self._pair()
        before = self._read()
        # Simulate abrupt process loss after writing a temporary file but
        # before os.replace. Never promote the incomplete/unknown ciphertext.
        staged = self.root / (".taraz-credential-update-" + "e" * 32)
        staged.write_bytes(b"incomplete-stage-not-a-credential")
        self.assertEqual(self.vault.require_token(
            workspace_id=WORKSPACE, peer_id=PEER, cert_sha256=PIN), issued["token"])
        self.assertEqual(self._read(), before)
        self.assertFalse(staged.exists())

    def test_trusted_repair_repin_and_reconnect_after_local_revocation(self):
        self.vault.initialize()
        first = "mdv1_" + "a" * 64
        renewed = "mdv1_" + "b" * 64
        endpoint = "https://127.0.0.1:48370"
        self.vault.store_issued_credential(workspace_id=WORKSPACE,
            peer_id="MADAR", cert_sha256=PIN, issued_token=first, endpoint=endpoint)
        self.vault.revoke(workspace_id=WORKSPACE, peer_id="MADAR")
        # The trusted caller only invokes store_issued_credential after a
        # fresh explicit code redemption and independently checked new pin.
        self.vault.store_issued_credential(workspace_id=WORKSPACE,
            peer_id="MADAR", cert_sha256=WRONG_PIN,
            issued_token=renewed, endpoint=endpoint)
        self.assertEqual(self.vault.require_token(
            workspace_id=WORKSPACE, peer_id="MADAR", cert_sha256=WRONG_PIN), renewed)
        with self.assertRaises(CredentialVaultError):
            self.vault.require_token(workspace_id=WORKSPACE,
                peer_id="MADAR", cert_sha256=PIN)

    def test_private_files_have_no_inherited_windows_acl(self):
        self.vault.initialize()
        self._pair()
        for file in self.root.iterdir():
            proc = subprocess.run(["icacls", str(file)], capture_output=True,
                                  text=True, timeout=15, check=True)
            self.assertNotIn("(I)", proc.stdout)


if __name__ == "__main__":
    unittest.main()
