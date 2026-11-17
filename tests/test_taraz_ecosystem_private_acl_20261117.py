"""Windows ACL regression: paired credentials and sealed reply-cache ONLY.

All paths are freshly created, disposable, and never point to installed books,
users' roaming profiles, LAN services, or a real financial ledger.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from taraz_ecosystem_credentials import (
    TarazEcosystemCredentialVault, _principal_sid,
)
from taraz_ecosystem_mailbox_peer import _SealedReplyCache


def _add_everyone_read(path: Path) -> None:
    subprocess.run(
        ["icacls.exe", str(path), "/grant", "*S-1-1-0:(R)"],
        capture_output=True, text=True, check=True, timeout=15)


def _observed_sids(path: Path) -> dict:
    # Translate names to SIDs so this works on non-English Windows.
    script = """
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:TARAZ_QA_ACL_SUBJECT
$rules = @($acl.Access | ForEach-Object {
  [pscustomobject]@{
    sid = $_.IdentityReference.Translate(
      [System.Security.Principal.SecurityIdentifier]).Value
    inherited = [bool]$_.IsInherited
    kind = [string]$_.AccessControlType
  }
})
[pscustomobject]@{
  protected = [bool]$acl.AreAccessRulesProtected
  rules = $rules
} | ConvertTo-Json -Depth 4 -Compress
"""
    output = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive",
         "-EncodedCommand", __import__("base64").b64encode(
             script.encode("utf-16le")).decode("ascii")],
        env={**os.environ, "TARAZ_QA_ACL_SUBJECT": str(path)},
        capture_output=True, text=True, check=True, timeout=15).stdout
    result = json.loads(output)
    if isinstance(result["rules"], dict):
        result["rules"] = [result["rules"]]
    return result


def _assert_private(test, path: Path) -> None:
    result = _observed_sids(path)
    test.assertTrue(result["protected"])
    test.assertEqual(
        {entry["sid"] for entry in result["rules"]},
        {_principal_sid(), "S-1-5-18", "S-1-5-32-544"})
    test.assertTrue(all(not entry["inherited"] and entry["kind"] == "Allow"
                        for entry in result["rules"]))


@unittest.skipUnless(os.name == "nt", "Windows ACL security descriptor required")
class StrictTarazPrivateAclTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="taraz-ecosystem-acl-qa-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def test_existing_credential_root_and_files_remove_extra_explicit_trustees(self):
        root = self.base / "private-integration"
        root.mkdir()
        vault = TarazEcosystemCredentialVault(root)
        vault.initialize()
        vault.pair(workspace_id="a"*32, peer_id="MADAR",
                   cert_sha256="c"*64)
        before = {
            name: (root / name).read_bytes()
            for name in ("taraz-ecosystem-credentials.json",
                         ".taraz-ecosystem-credentials.lock")}
        for path in (root, *root.iterdir()):
            _add_everyone_read(path)
            self.assertIn("S-1-1-0", {r["sid"] for r in _observed_sids(path)["rules"]})
        self.assertEqual(len(vault.list_peers()), 1)
        for path in (root, *root.iterdir()):
            _assert_private(self, path)
        self.assertEqual(before, {name: (root / name).read_bytes() for name in before})

    def test_reopened_sealed_mailbox_cache_scrubs_foreign_file_and_root_ace(self):
        book = self.base / "synthetic-book"
        book.mkdir()
        cache = _SealedReplyCache(book)
        envelope = {"requestId": "f"*32, "testOnly": "synthetic"}
        result = {"party": {"partyId": "TARAZ-QA-1",
                            "name": "نمونه", "kind": "customer"}}
        self.assertEqual(cache.get_or_create(envelope, lambda: result), result)
        file = cache._archive_file("f"*32)
        before = file.read_bytes()
        for path in (cache.root, cache.root / ".lock",
                     cache.archive, file.parent, file):
            _add_everyone_read(path)
            self.assertIn("S-1-1-0", {r["sid"] for r in _observed_sids(path)["rules"]})
        reopened = _SealedReplyCache(book)
        self.assertEqual(reopened.get_or_create(envelope, lambda: self.fail(
            "Existing immutable reply must be reused")), result)
        self.assertEqual(file.read_bytes(), before)
        for path in (cache.root, cache.root / ".lock",
                     cache.archive, file.parent, file):
            _assert_private(self, path)


if __name__ == "__main__":
    unittest.main()
