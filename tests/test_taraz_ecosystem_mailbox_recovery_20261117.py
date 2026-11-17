"""Windows-only isolated-clone QA: immutable receipts and revoked credentials.

NEVER touches installed Taraz, real books, APPDATA, Madar host, or network.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from taraz_ecosystem_credentials import (
    CredentialVaultError, TarazEcosystemCredentialVault,
)
from taraz_ecosystem_mailbox_peer import (
    _SealedReplyCache, MailboxPeerDenied,
)
from taraz_ecosystem_mailbox_recovery import (
    backup_clone_archive, restore_clone_archive,
)
from tests.test_taraz_ecosystem_mailbox_archive_20261117 import request, reply
from tests.test_taraz_ecosystem_private_acl_20261117 import (
    _add_everyone_read, _assert_private,
)


@unittest.skipUnless(os.name == "nt", "Windows current-user DPAPI and DACL required")
class SealedMailboxCloneRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="taraz-mailbox-restore-qa-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.source = self.base / "source-book"
        self.source.mkdir()
        self.clone = self.base / "synthetic-clone-book"
        self.clone.mkdir()
        self.backup = self.base / "sealed-backup-snapshot"
        self.original = _SealedReplyCache(self.source)

    def _populate(self, n=5):
        for index in range(n):
            self.original.get_or_create(request(index), lambda i=index: reply(i))

    def _snapshot(self):
        return backup_clone_archive(self.source, self.backup)

    def test_clone_snapshot_restore_all_replays_immutable_and_private_acl(self):
        self._populate(18)
        historical = {str(file): hashlib.sha256(file.read_bytes()).hexdigest()
                      for file in self.original.archive.glob("*/*.dpapi")}
        result = self._snapshot()
        self.assertEqual(result["receipts"], 18)
        self.assertFalse(result["credentialStateIncluded"])
        filenames = list(self.backup.iterdir())
        self.assertEqual(len(filenames), 19)
        for file in filenames:
            self.assertNotIn(b"Synthetic Test Party", file.read_bytes())
            _assert_private(self, file)
        _assert_private(self, self.backup)
        restored = restore_clone_archive(self.backup, self.clone)
        self.assertEqual(restored["uniqueRequestIds"], 18)
        self.assertFalse(restored["credentialsRestored"])
        imported = _SealedReplyCache(self.clone)
        for n in range(18):
            self.assertEqual(imported.get_or_create(
                request(n), lambda: self.fail("Historic reply cannot re-read ledger")),
                reply(n))
        self.assertEqual(historical, {
            str(file): hashlib.sha256(file.read_bytes()).hexdigest()
            for file in self.original.archive.glob("*/*.dpapi")})
        self.assertEqual(len(list(imported.archive.glob("*/*.dpapi"))), 18)
        _assert_private(self, imported.root)
        _assert_private(self, imported.archive)
        for entry in imported.archive.iterdir():
            _assert_private(self, entry)
        with self.assertRaises(MailboxPeerDenied):
            restore_clone_archive(self.backup, self.clone)

    def test_revoked_paired_credential_not_in_backup_and_not_resurrected(self):
        vault_dir = self.source / "separate-credential-vault"
        vault_dir.mkdir()
        vault = TarazEcosystemCredentialVault(vault_dir)
        vault.initialize()
        peer = vault.pair(workspace_id="a"*32, peer_id="MADAR",
                          cert_sha256="b"*64)
        self._populate(3)
        self._snapshot()
        vault.revoke(workspace_id="a"*32, peer_id="MADAR")
        saved_bytes = (vault_dir / "taraz-ecosystem-credentials.json").read_bytes()
        with self.assertRaises(CredentialVaultError):
            vault.require_token(workspace_id="a"*32, peer_id="MADAR",
                                cert_sha256="b"*64)
        imported = restore_clone_archive(self.backup, self.clone)
        self.assertEqual(imported["uniqueRequestIds"], 3)
        self.assertFalse((self.clone / "separate-credential-vault").exists())
        self.assertEqual(saved_bytes,
                         (vault_dir / "taraz-ecosystem-credentials.json").read_bytes())
        self.assertTrue(vault.list_peers()[0]["revoked"])
        self.assertFalse(peer["token"] == vault.list_peers()[0].get("token"))
        with self.assertRaises(CredentialVaultError):
            vault.require_token(workspace_id="a"*32, peer_id="MADAR",
                                cert_sha256="b"*64)
        self.assertEqual(_SealedReplyCache(self.clone).get_or_create(
            request(1), lambda: self.fail("Must use archived snapshot")), reply(1))

    def test_fail_closed_disk_preflight_before_new_company_reader(self):
        self._populate(1)
        original = self.original.get_or_create(request(0), lambda: None)
        with patch("taraz_ecosystem_mailbox_peer.shutil.disk_usage",
                   return_value=shutil._ntuple_diskusage(10**9, 10**9-30000, 30000)):
            self.assertFalse(self.original.capacity_status()["canWrite"])
            with self.assertRaisesRegex(MailboxPeerDenied, "reserve"):
                self.original.get_or_create(
                    request(99), lambda: self.fail(
                        "No ledger read when durable reply cannot be stored"))
            self.assertEqual(self.original.get_or_create(
                request(0), lambda: self.fail("Existing immutable retry")), original)
        self.assertFalse(self.original._archive_file(request(99)["requestId"]).exists())

    def test_low_disk_capacity_warning_preserves_results_without_evicting(self):
        self._populate(2)
        with patch("taraz_ecosystem_mailbox_peer.shutil.disk_usage",
                   return_value=shutil._ntuple_diskusage(
                       10**9, 10**9 - 100*1024*1024, 100*1024*1024)):
            status = self.original.capacity_status()
            self.assertTrue(status["warning"])
            self.assertTrue(status["canWrite"])
            self.assertGreater(status["requiredReserveBytes"], 64*1024*1024)
        self.assertEqual(len(list(self.original.archive.glob("*/*.dpapi"))), 2)

    def test_disk_usage_unavailable_and_snapshot_preflight_fail_closed(self):
        self._populate(2)
        with patch("taraz_ecosystem_mailbox_peer.shutil.disk_usage",
                   side_effect=OSError("disconnected synthetic volume")):
            with self.assertRaisesRegex(MailboxPeerDenied, "capacity unverified"):
                self.original.get_or_create(request(3), lambda: self.fail("No read"))
            with self.assertRaisesRegex(MailboxPeerDenied, "capacity unverified"):
                self._snapshot()
        self.assertFalse(self.backup.exists())

    def test_restore_low_disk_aborts_before_any_clone_file_is_created(self):
        self._populate(3)
        self._snapshot()
        with patch("taraz_ecosystem_mailbox_peer.shutil.disk_usage",
                   return_value=shutil._ntuple_diskusage(
                       10**9, 10**9 - 1024, 1024)):
            with self.assertRaisesRegex(MailboxPeerDenied, "reserve"):
                restore_clone_archive(self.backup, self.clone)
        self.assertFalse((self.clone / ".taraz-mailbox-replies-v1").exists())
        self.assertFalse(list(self.clone.glob(".pending-mailbox-restore-*")))

    def test_encrypted_manifest_tampering_denies_clone_before_mutation(self):
        self._populate(2)
        self._snapshot()
        manifest = self.backup / "manifest.dpapi"
        manifest.write_bytes(b"synthetic-invalid-manifest")
        with self.assertRaises(MailboxPeerDenied):
            restore_clone_archive(self.backup, self.clone)
        self.assertFalse((self.clone / ".taraz-mailbox-replies-v1").exists())
        self.assertFalse(list(self.clone.glob(".pending-mailbox-restore-*")))

    def test_tamper_missing_or_extra_backup_file_refuses_before_clone_mutation(self):
        self._populate(3)
        self._snapshot()
        blob = next(x for x in self.backup.glob("r*.dpapi"))
        blob.write_bytes(b"tampered-synthetic-ciphertext")
        with self.assertRaises(MailboxPeerDenied):
            restore_clone_archive(self.backup, self.clone)
        self.assertFalse((self.clone / ".taraz-mailbox-replies-v1").exists())
        self.assertFalse(list(self.clone.glob(".pending-mailbox-restore-*")))
        with self.assertRaises(MailboxPeerDenied):
            restore_clone_archive(self.backup, self.source)

    def test_interrupted_stage_refuses_backup_instead_of_losing_unacked_reply(self):
        self._populate(1)
        pending = self.original._archive_file(request(0)["requestId"]).parent / (
            ".pending-" + request(42)["requestId"] + "." + "e"*32)
        from taraz_ecosystem_credentials import _create_secure_file
        _create_secure_file(pending, b"synthetic-pending")
        with self.assertRaisesRegex(MailboxPeerDenied, "stage"):
            self._snapshot()
        self.assertTrue(pending.exists())
        self.assertFalse(self.backup.exists())

    def test_windows_dacl_on_backup_and_restored_archive_repairs_extra_everyone(self):
        self._populate(2)
        self._snapshot()
        encrypted = next(self.backup.glob("r*.dpapi"))
        original_hash = hashlib.sha256(encrypted.read_bytes()).hexdigest()
        for path in (self.backup, encrypted):
            _add_everyone_read(path)
        restore_clone_archive(self.backup, self.clone)
        for path in (self.backup, encrypted):
            _assert_private(self, path)
        self.assertEqual(original_hash, hashlib.sha256(encrypted.read_bytes()).hexdigest())
        self.assertEqual(_SealedReplyCache(self.clone).get_or_create(
            request(0), lambda: self.fail("No ledger")), reply(0))

    def test_clone_publication_failure_keeps_original_and_backup_intact(self):
        self._populate(3)
        self._snapshot()
        original_hash = hashlib.sha256(
            self.original._archive_file(request(1)["requestId"]).read_bytes()).hexdigest()
        manifest_hash = hashlib.sha256(
            (self.backup / "manifest.dpapi").read_bytes()).hexdigest()
        with patch("taraz_ecosystem_mailbox_recovery.os.rename",
                   side_effect=OSError("synthetic interrupted clone publication")):
            with self.assertRaisesRegex(OSError, "interrupted"):
                restore_clone_archive(self.backup, self.clone)
        self.assertFalse((self.clone / ".taraz-mailbox-replies-v1").exists())
        self.assertTrue(list(self.clone.glob(".pending-mailbox-restore-*")))
        self.assertEqual(original_hash, hashlib.sha256(
            self.original._archive_file(request(1)["requestId"]).read_bytes()).hexdigest())
        self.assertEqual(manifest_hash, hashlib.sha256(
            (self.backup / "manifest.dpapi").read_bytes()).hexdigest())
        with self.assertRaisesRegex(MailboxPeerDenied, "Unresolved interrupted"):
            restore_clone_archive(self.backup, self.clone)

    def test_backup_destination_inside_company_book_is_refused_without_writes(self):
        self._populate(1)
        nested = self.source / "unsafe-backup-subfolder"
        with self.assertRaisesRegex(MailboxPeerDenied, "overlap"):
            backup_clone_archive(self.source, nested)
        self.assertFalse(nested.exists())
        self.assertEqual(self.original.get_or_create(
            request(0), lambda: self.fail("Original must remain immutable")),
            reply(0))


if __name__ == "__main__":
    unittest.main()
