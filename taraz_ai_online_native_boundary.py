"""Authenticated native Taraz book -> isolated online AI DPAPI vault.

Only a caller that has ALREADY checked a live company session may call this.
No ambient APPDATA/profile lookup, no ledger access, no provider transmission.
The root is created only for an explicit administrator configuration action.
Directory ACL is verified against the current Windows SID on every access.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import stat
import subprocess

from taraz_ai_online_credentials import (
    OnlineCredentialError, TarazOnlineAiCredentialVault,
)
from taraz_ecosystem_credentials import _principal_sid

DIRECTORY = ".taraz-online-ai-private-v1"
# SOURCE-ONLY RELEASE STOP. Browser consent is not a verifiable native human
# confirmation; per-request estimated prices are not an aggregate spending
# authority. No environment flag, stored config or renderer request lifts it.
ONLINE_EXTERNAL_TRANSMISSION_ENABLED = False
ONLINE_EXTERNAL_BLOCKER = "NATIVE_HUMAN_CONSENT_AND_AGGREGATE_BUDGET_NOT_IMPLEMENTED"
_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:TARAZ_ONLINE_AI_ACL_PATH
$rules = @($acl.Access | ForEach-Object {
  $sid = $_.IdentityReference.Translate(
    [System.Security.Principal.SecurityIdentifier]).Value
  [pscustomobject]@{
    sid = $sid
    inherited = [bool]$_.IsInherited
    kind = [string]$_.AccessControlType
    rights = [int64]$_.FileSystemRights
  }
})
[pscustomobject]@{
  protected = [bool]$acl.AreAccessRulesProtected
  rules = $rules
} | ConvertTo-Json -Depth 4 -Compress
""".strip()
_ENFORCE_NEW_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$target = $env:TARAZ_ONLINE_AI_ACL_PATH
$ownerSid = New-Object System.Security.Principal.SecurityIdentifier(
  $env:TARAZ_ONLINE_AI_OWNER_SID)
$acl = Get-Acl -LiteralPath $target
$acl.SetAccessRuleProtection($true, $false)
$sids = @($acl.Access | ForEach-Object {
  $_.IdentityReference.Translate(
    [System.Security.Principal.SecurityIdentifier]).Value
} | Select-Object -Unique)
foreach($sidString in $sids){
  $oldSid = New-Object System.Security.Principal.SecurityIdentifier($sidString)
  $acl.PurgeAccessRules($oldSid)
}
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
  $ownerSid,
  [System.Security.AccessControl.FileSystemRights]::FullControl,
  [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit',
  [System.Security.AccessControl.PropagationFlags]::None,
  [System.Security.AccessControl.AccessControlType]::Allow)
$acl.SetAccessRule($rule)
Set-Acl -LiteralPath $target -AclObject $acl
""".strip()


def _directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink():
        raise OnlineCredentialError("Verified regular credential directory required")
    for component in (path, *path.parents):
        if component.is_symlink() or not component.is_dir():
            raise OnlineCredentialError("Linked credential directory refused")
        attributes = getattr(component.lstat(), "st_file_attributes", 0)
        if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise OnlineCredentialError("Reparse-point credential directory refused")


def _acl_is_private(root: Path) -> None:
    """Fail closed on inherited, foreign or non-full-control allow ACEs."""
    sid = _principal_sid()
    env = dict(os.environ, TARAZ_ONLINE_AI_ACL_PATH=str(root))
    try:
        encoded = base64.b64encode(_ACL_SCRIPT.encode("utf-16le")).decode("ascii")
        reply = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", encoded],
            env=env, capture_output=True, text=True, timeout=15, check=True)
        report = json.loads(reply.stdout)
        rules = report["rules"]
        if type(rules) is dict:  # PowerShell's 1-item array normalization
            rules = [rules]
        if (report["protected"] is not True or type(rules) is not list or
                not rules or any(
                    type(rule) is not dict or
                    rule.get("sid") != sid or
                    rule.get("inherited") is not False or
                    rule.get("kind") != "Allow" or
                    type(rule.get("rights")) is not int or
                    (rule["rights"] & 2032127) != 2032127
                    for rule in rules)):
            raise OnlineCredentialError("Credential directory ACL is not private")
    except OnlineCredentialError:
        raise
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        raise OnlineCredentialError("Credential directory ACL could not be verified") from None


def _harden_new_directory(root: Path) -> None:
    """Only newly created, empty vault dirs: replace *all* explicit foreign ACEs."""
    if list(root.iterdir()):
        raise OnlineCredentialError("Cannot change ACL of a nonempty vault")
    sid = _principal_sid()
    env = dict(os.environ, TARAZ_ONLINE_AI_ACL_PATH=str(root),
               TARAZ_ONLINE_AI_OWNER_SID=sid)
    try:
        encoded = base64.b64encode(
            _ENFORCE_NEW_ACL_SCRIPT.encode("utf-16le")).decode("ascii")
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                        "-EncodedCommand", encoded], env=env, capture_output=True,
                       text=True, timeout=15, check=True)
    except (OSError, subprocess.SubprocessError):
        raise OnlineCredentialError(
            "New online credential directory DACL setup failed") from None
    _acl_is_private(root)


def company_online_vault(book_directory: Path, *, initialize=False):
    """Return existing private vault or None if absent; never inspect the book."""
    if type(initialize) is not bool:
        raise OnlineCredentialError("Invalid vault initialization intent")
    book = Path(book_directory)
    if not book.is_absolute():
        raise OnlineCredentialError("Native absolute book path required")
    _directory(book)
    root = book / DIRECTORY
    if os.path.lexists(root):
        _directory(root)
        _acl_is_private(root)
        vault = TarazOnlineAiCredentialVault(root)
        vault.metadata()  # Existing corrupt vault must fail closed, not reset.
        return vault
    if not initialize:
        return None
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        raise OnlineCredentialError("Concurrent online credential directory creation refused") from None
    # No secrets have been written yet. Existing inherited permissions must
    # be removed and checked BEFORE creating any credential lock/document.
    _directory(root)
    _harden_new_directory(root)
    vault = TarazOnlineAiCredentialVault(root)
    vault.initialize()
    return vault


__all__ = ["company_online_vault", "DIRECTORY"]
