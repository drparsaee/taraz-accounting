"""Host-selected private credential directory inside the authenticated book.

Only TarazAPI may call this after its *native* company/admin ACL. No ambient
profile discovery, no installer modification, no ledger read or financial IO.
"""
from __future__ import annotations

from pathlib import Path
import os

from taraz_ecosystem_credentials import (
    CredentialVaultError, TarazEcosystemCredentialVault, _private_acl,
)

DIRECTORY = ".taraz-ecosystem-integration-auth-v1"


def company_vault(book_directory: Path, *, initialize: bool = False):
    book = Path(book_directory)
    if not book.is_absolute() or not book.is_dir() or book.is_symlink():
        raise CredentialVaultError("Verified native company book required")
    root = book / DIRECTORY
    if root.is_symlink():
        raise CredentialVaultError("Linked integration credential directory refused")
    if not root.exists():
        if not initialize:
            return None
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            raise CredentialVaultError("Credential path appeared concurrently")
        try:
            # Do not rely on Windows' interpretation of POSIX mode=0700.
            # Remove inherited directory ACL and add the current principal.
            _private_acl(root)
            vault = TarazEcosystemCredentialVault(root)
            vault.initialize()
            return vault
        except BaseException:
            # A failed initialization may have left evidence of a competing
            # process. Never recursively clean or overwrite a nonempty root.
            try:
                if not list(root.iterdir()):
                    root.rmdir()
            except OSError:
                pass
            raise
    vault = TarazEcosystemCredentialVault(root)
    # An existing folder without its lock/file is corruption, not a request
    # to auto-regenerate stable installation identity.
    vault.installation_id()
    return vault


__all__ = ["company_vault", "DIRECTORY"]
