"""Pending, genuine frozen Taraz.exe AI acceptance on an isolated Win32 desktop.

There is NO bundled/pinned candidate here and importing the module launches
NOTHING. Only an explicitly pinned UNINSTALLED build may be run with
``--run-private --exe PATH --sha256 HASH --source-sha256 HASH``.

Creates an entirely synthetic registered company with REAL LocalCompanyIdentity
credentials and an issued QA invoice. The frozen EXE itself must display its
company selector + native password login twice, use its own WebView2/bridge,
and save an AI-reviewed DRAFT with no new journal. A private PowerShell UIA
helper interacts only with controls owned by the frozen PID; Playwright attaches
to the one existing owned WebView CDP page and clicks the actual React UI.

Never invokes the source-hosted TarazAPI, installs, touches ambient profiles,
sends global input, changes the user's desktop, or terminates a process.
Unverifiable ownership, login, CDP, UI or graceful shutdown => BLOCKED.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTIFACTS = (ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" /
             "taraz-v1.0.6-aaas")
PRIVATE_OUT = ARTIFACTS / "frozen-ai-real-auth-qa-20261114"
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_BUILD = re.compile(r"build-[a-f0-9]{8,20}\Z")
_REGISTRY_ID = re.compile(r"[a-f0-9]{32}\Z")
_SAFE_UIA_CODES = frozenset({
    "OWNED_PIDS_EMPTY", "AMBIGUOUS_NATIVE_WINDOW", "OWNED_NATIVE_WINDOW_NOT_FOUND",
    "EXACT_NATIVE_BUTTON_UNAVAILABLE", "NATIVE_BUTTON_NOT_INVOKABLE",
    "QA_COMPANY_SELECTION_NOT_ACCESSIBLE", "QA_COMPANY_SELECTION_PATTERN_MISSING",
    "PRIVATE_QA_CREDENTIALS_ABSENT", "NATIVE_LOGIN_FIELDS_AMBIGUOUS",
    "NATIVE_LOGIN_VALUE_PATTERN_UNAVAILABLE", "NATIVE_LOGIN_USERNAME_NOT_SET",
    "QA_SINGLE_COMPANY_PRESELECTION_UNVERIFIED", "UIA_SETUP_FAILED",
    "UIA_ROOT_ACCESS_FAILED", "UIA_TOP_LEVEL_ENUMERATION_FAILED",
    "UIA_DESCENDANT_QUERY_FAILED", "UIA_BUTTON_SEARCH_FAILED",
    "UIA_BUTTON_INVOKE_PATTERN_FAILED", "UIA_BUTTON_INVOKE_FAILED",
    "UIA_LISTITEM_SEARCH_FAILED", "UIA_LISTITEM_SELECTION_PATTERN_FAILED",
    "UIA_LISTITEM_SELECT_FAILED", "UIA_LOGIN_EDIT_SEARCH_FAILED",
    "UIA_LOGIN_EDIT_PATTERN_FAILED", "UIA_LOGIN_USERNAME_SET_FAILED",
    "UIA_LOGIN_PASSWORD_SET_FAILED", "PRIVATE_TK_LOGIN_ADMIN_NOT_UNIQUE",
    "PRIVATE_TK_LOGIN_FOCUS_NOT_ENTRY", "PRIVATE_TK_LOGIN_FOCUS_NOT_ADVANCED",
    "PRIVATE_TK_USERNAME_INPUT_FAILED", "PRIVATE_TK_PASSWORD_INPUT_FAILED",
    "PRIVATE_TK_LOGIN_TAB_REJECTED", "PRIVATE_TK_LOGIN_DID_NOT_OPEN_ACCOUNTING",
    "PRIVATE_TK_CREDENTIALS_NON_ASCII", "PRIVATE_TK_LOGIN_WINDOW_TRANSITION_FAILED",
    "PRIVATE_TK_NATIVE_HANDLE_UNAVAILABLE", "PRIVATE_TK_GUI_THREAD_UNAVAILABLE",
    "PRIVATE_TK_FOCUS_NOT_OWNED", "PRIVATE_TK_FOCUS_OUTSIDE_WINDOW",
    "PRIVATE_TK_DIRECT_ENTER_REJECTED", "PRIVATE_TK_ENTER_DID_NOT_OPEN_LOGIN",
    "PRIVATE_TK_LOGIN_TRANSITION_CHECK_FAILED", "UIA_BUTTON_LEGACY_PATTERN_FAILED",
})
QA_USER = "qa_frozen_ai"
QA_COMPANY = "شرکت آریا"
QA_SOURCE = "QA-SOURCE-INV"
QA_REQUEST = ("برای شرکت آریا یک فاکتور فروش بساز. "
              "۱۰۰ عدد جعبه و ۲۰۰ عدد لیبل اضافه کن. "
              "قیمت هر کالا را از آخرین فاکتور معتبر همین مشتری بردار.")


class FrozenAuthBlocked(RuntimeError):
    """Precondition or verification failure; never report PASS."""


def safe_native_uia_error_code(value) -> str:
    """Redact untrusted UIA messages, credentials and filesystem paths."""
    return value if type(value) is str and value in _SAFE_UIA_CODES else "UNKNOWN_NATIVE_UIA_ERROR"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _ordinary_path(path: Path) -> bool:
    for part in (path, *path.parents):
        if part.is_symlink():
            return False
        if part.exists() and (getattr(part.lstat(), "st_file_attributes", 0) &
                              getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            return False
    return True


def validate_candidate(exe: Path, expected_sha: str, source_sha: str, *,
                       artifact_root: Path = ARTIFACTS) -> dict:
    """Read-only exact-build preflight; never searches installed executables."""
    if (type(expected_sha) is not str or not _SHA256.fullmatch(expected_sha) or
            type(source_sha) is not str or not _SHA256.fullmatch(source_sha)):
        raise FrozenAuthBlocked("Explicit lowercase SHA-256 pins required")
    exe, artifact_root = Path(exe), Path(artifact_root)
    if (not exe.is_absolute() or not artifact_root.is_absolute() or
            not _ordinary_path(exe) or not _ordinary_path(artifact_root)):
        raise FrozenAuthBlocked("Untrusted candidate path or reparse point")
    if (not exe.is_file() or exe.name != "Taraz.exe" or
            exe.parent.name != "binary" or
            not _BUILD.fullmatch(exe.parent.parent.name) or
            exe.parent.parent.parent.resolve() != artifact_root.resolve()):
        raise FrozenAuthBlocked("Only a direct uninstalled QA build/Taraz.exe is allowed")
    if digest(exe) != expected_sha:
        raise FrozenAuthBlocked("Frozen EXE SHA-256 mismatch")
    report_file = exe.parent.parent / "build-report.json"
    if not report_file.is_file() or not _ordinary_path(report_file):
        raise FrozenAuthBlocked("Matching frozen build report unavailable")
    try:
        if report_file.stat().st_size > 256 * 1024:
            raise ValueError("Oversize manifest")
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FrozenAuthBlocked("Frozen build report is invalid") from exc
    if (type(report) is not dict or report.get("exeSha256") != expected_sha or
            report.get("sourceFreezeSha256") != source_sha or
            report.get("installed") is not False):
        raise FrozenAuthBlocked("EXE/source pins or uninstalled status not proven")
    return {"exeSha256": expected_sha, "sourceFreezeSha256": source_sha,
            "build": exe.parent.parent.name, "uninstalledManifest": True}


def _guard_private_paths(runtime: Path, profile: Path, book: Path, env: dict) -> None:
    """Validate the exact current Taraz CDP gate before launching a process."""
    from taraz_desktop import private_qa_cdp_port
    if (not runtime.is_absolute() or not profile.is_absolute() or
            not book.is_absolute() or profile != runtime / "roaming" / "Taraz" or
            book.parent != profile / "books" or not _REGISTRY_ID.fullmatch(book.name) or
            "qa-runtime" not in [x.casefold() for x in profile.parts] or
            not _ordinary_path(profile) or not _ordinary_path(book)):
        raise FrozenAuthBlocked("Private QA profile boundary not verified")
    if (Path(env.get("TARAZ_QA_DATA_DIR", "")) != profile or
            Path(env.get("APPDATA", "")) != profile.parent or
            env.get("TARAZ_QA_MODE") != "1"):
        raise FrozenAuthBlocked("Private Taraz data and roaming roots differ")
    for name in ("APPDATA", "LOCALAPPDATA", "TEMP", "USERPROFILE", "WEBVIEW2_USER_DATA_FOLDER"):
        value = Path(env.get(name, ""))
        if not value.is_absolute() or not value.is_relative_to(runtime):
            raise FrozenAuthBlocked("Non-isolated runtime directory: " + name)
        if name in os.environ and value.resolve() == Path(os.environ[name]).resolve():
            raise FrozenAuthBlocked("Ambient runtime directory was reused")
    from standalone_accounting_company_registry import StandaloneCompanyRegistry
    registry = StandaloneCompanyRegistry(profile)
    if registry.company_data_directory(book.name) != book:
        raise FrozenAuthBlocked("Private book is not a registered company")
    # The Tk chooser preselects entry 0; never rely on that behavior unless
    # the private registry has exactly one QA company and no other option.
    companies = registry.list_companies()
    if (env.get("TARAZ_QA_SINGLE_COMPANY") != "1" or
            len(companies) != 1 or companies[0]["id"] != book.name or
            companies[0]["name"] != QA_COMPANY):
        raise FrozenAuthBlocked("Exactly one synthetic company is required for Tk fallback")
    from standalone_accounting_identity import LocalCompanyIdentity
    accounts = LocalCompanyIdentity(book).accounting_accounts()
    if (env.get("TARAZ_QA_SINGLE_ADMIN") != "1" or
            set(accounts) != {QA_USER} or accounts[QA_USER]["role"] != "admin"):
        raise FrozenAuthBlocked("Exactly one real synthetic admin required for private Tk login")
    marker = book / ".taraz-private-cdp-qa.json"
    if (not marker.is_file() or not _ordinary_path(marker) or
            json.loads(marker.read_text(encoding="utf-8")) != {
                "privateQaOnly": True, "profile": str(book.resolve())}):
        raise FrozenAuthBlocked("Private company-book CDP marker is invalid")
    if private_qa_cdp_port(book, env) is None:
        raise FrozenAuthBlocked("Source-side private CDP entitlement refused")
    args = env.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    if ("--remote-debugging-address=127.0.0.1" not in args or
            "--proxy-server=http://127.0.0.1:9" not in args or
            "--disable-background-networking" not in args):
        raise FrozenAuthBlocked("WebView2 loopback/network restrictions unavailable")


def create_private_fixture(runtime: Path) -> dict:
    """Only a NEW QA-owned profile. No source or production DB is copied."""
    from standalone_accounting_company_registry import StandaloneCompanyRegistry
    from standalone_accounting_identity import LocalCompanyIdentity
    from standalone_accounting import StandaloneAccountingStore

    profile = runtime / "roaming" / "Taraz"
    profile.mkdir(parents=True, exist_ok=False)
    registry = StandaloneCompanyRegistry(profile)
    company = registry.create_company(QA_COMPANY)
    company_id = company["id"]
    if not _REGISTRY_ID.fullmatch(company_id):
        raise FrozenAuthBlocked("Synthetic company registry ID invalid")
    book = registry.company_data_directory(company_id)
    credential = secrets.token_urlsafe(36)
    identity = LocalCompanyIdentity(book)
    identity.add_user(QA_USER, credential, "admin")
    token = identity.login(QA_USER, credential)
    identity.require_session(token, "admin")
    identity.logout(token)

    finance = StandaloneAccountingStore(book / "standalone-accounting.sqlite3",
                                       default_currency="RIAL")
    changes = [
        {"type": "party.register", "eventId": "qa-real-auth-party", "partyId": "arya",
         "name": QA_COMPANY, "kind": "customer"},
        {"type": "item.create", "eventId": "qa-real-auth-box", "itemId": "box",
         "name": "جعبه", "sku": "QA-AI-BOX", "kind": "goods", "unit": "piece"},
        {"type": "item.create", "eventId": "qa-real-auth-label", "itemId": "label",
         "name": "لیبل", "sku": "QA-AI-LABEL", "kind": "goods", "unit": "piece"},
        {"type": "invoice.create", "eventId": "qa-real-auth-source-create",
         "invoiceId": QA_SOURCE, "partyId": "arya", "documentDate": "2026-11-12",
         "lines": [{"description": "جعبه", "quantity": 1, "unitPrice": 1000,
                    "accountId": "4000", "itemId": "box"},
                   {"description": "لیبل", "quantity": 1, "unitPrice": 500,
                    "accountId": "4000", "itemId": "label"}]},
        {"type": "invoice.approve", "eventId": "qa-real-auth-source-approve",
         "invoiceId": QA_SOURCE},
        {"type": "invoice.issue", "eventId": "qa-real-auth-source-issue",
         "invoiceId": QA_SOURCE, "postingDate": "2026-11-12"},
    ]
    for revision, command in enumerate(changes):
        current = finance.command(command, actor=QA_USER,
                                  accounts=identity.accounting_accounts(),
                                  expected_revision=revision,
                                  now="2026-11-14T09:00:00+00:00")
        if current["revision"] != revision + 1:
            raise FrozenAuthBlocked("Synthetic fixture event revision mismatch")
    baseline = finance.read(actor=QA_USER, accounts=identity.accounting_accounts())
    if (baseline["revision"] != len(changes) or
            len(baseline["view"]["invoices"]) != 1 or
            len(baseline["view"]["journals"]) != 1):
        raise FrozenAuthBlocked("Synthetic issued source and journal not initialized")
    marker = book / ".taraz-private-cdp-qa.json"
    marker.write_text(json.dumps({"privateQaOnly": True,
                                  "profile": str(book.resolve())}), encoding="utf-8")
    return {"profile": profile, "book": book, "companyId": company_id,
            "password": credential, "baseline": baseline}


AUTH_UIA_PS = r'''param(
 [Parameter(Mandatory=$true)][string]$OwnerIds,
 [Parameter(Mandatory=$true)][ValidateSet('select','login')][string]$Stage,
 [Parameter(Mandatory=$true)][string]$ResultFile)
$ErrorActionPreference='Stop'
$result=@{status='BLOCKED';stage=$Stage;ownerVerified=$false;submitted=$false;
  errorCode='NOT_ATTEMPTED';selectionMethod='NOT_ATTEMPTED';
  activationMethod='NOT_ATTEMPTED';verifiedTransition=$false}
$script:safeStage='UIA_SETUP_FAILED'
# Emit only fixed, source-authored codes. Exception.Message can contain
# window text, credentials or machine paths and MUST never be serialized.
$known=@('OWNED_PIDS_EMPTY','AMBIGUOUS_NATIVE_WINDOW',
 'OWNED_NATIVE_WINDOW_NOT_FOUND','EXACT_NATIVE_BUTTON_UNAVAILABLE',
 'NATIVE_BUTTON_NOT_INVOKABLE','QA_COMPANY_SELECTION_NOT_ACCESSIBLE',
 'QA_COMPANY_SELECTION_PATTERN_MISSING','PRIVATE_QA_CREDENTIALS_ABSENT',
 'NATIVE_LOGIN_FIELDS_AMBIGUOUS','NATIVE_LOGIN_VALUE_PATTERN_UNAVAILABLE',
 'NATIVE_LOGIN_USERNAME_NOT_SET','QA_SINGLE_COMPANY_PRESELECTION_UNVERIFIED',
 'PRIVATE_TK_NATIVE_HANDLE_UNAVAILABLE','PRIVATE_TK_GUI_THREAD_UNAVAILABLE',
 'PRIVATE_TK_FOCUS_NOT_OWNED','PRIVATE_TK_FOCUS_OUTSIDE_WINDOW',
 'PRIVATE_TK_DIRECT_ENTER_REJECTED','PRIVATE_TK_ENTER_DID_NOT_OPEN_LOGIN',
 'PRIVATE_TK_LOGIN_ADMIN_NOT_UNIQUE','PRIVATE_TK_LOGIN_FOCUS_NOT_ENTRY',
 'PRIVATE_TK_LOGIN_FOCUS_NOT_ADVANCED','PRIVATE_TK_USERNAME_INPUT_FAILED',
 'PRIVATE_TK_PASSWORD_INPUT_FAILED','PRIVATE_TK_LOGIN_TAB_REJECTED',
 'PRIVATE_TK_LOGIN_DID_NOT_OPEN_ACCOUNTING','PRIVATE_TK_CREDENTIALS_NON_ASCII')
try {
 Add-Type -AssemblyName UIAutomationClient
 Add-Type -AssemblyName UIAutomationTypes
 # P/Invoke is limited to the exact already-proven private Tk window/thread.
 # PostMessage targets its OWN focused HWND; it cannot synthesize system-wide
 # keyboard events or reach the foreground desktop or other applications.
 Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class TarazQaOwnedTk {
  [StructLayout(LayoutKind.Sequential)]
  public struct GuiThreadInfo {
    public UInt32 cbSize, flags;
    public IntPtr hwndActive, hwndFocus, hwndCapture, hwndMenuOwner;
    public IntPtr hwndMoveSize, hwndCaret;
    public Int32 left, top, right, bottom;
  }
  [DllImport("user32.dll", SetLastError=true)]
  public static extern UInt32 GetWindowThreadProcessId(IntPtr handle, out UInt32 pid);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool GetGUIThreadInfo(UInt32 threadId, ref GuiThreadInfo info);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern IntPtr GetAncestor(IntPtr handle, UInt32 flags);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool PostMessageW(IntPtr handle, UInt32 message, IntPtr wParam, IntPtr lParam);
}
'@
 $script:safeStage='UIA_ROOT_ACCESS_FAILED'
 $root=[System.Windows.Automation.AutomationElement]::RootElement
 $owned=@($OwnerIds.Split(',') | ForEach-Object {[int]$_})
 if($owned.Count -lt 1){throw 'OWNED_PIDS_EMPTY'}
 $expected=if($Stage -eq 'select'){'تراز | انتخاب شرکت ثبت‌شده'}
           else {'مدار | ورود امن حسابداری'}
 $window=$null
 for($i=0;$i -lt 80;$i++){
   $script:safeStage='UIA_TOP_LEVEL_ENUMERATION_FAILED'
   $all=$root.FindAll([System.Windows.Automation.TreeScope]::Children,
     [System.Windows.Automation.Condition]::TrueCondition)
   $matches=@($all | Where-Object { $owned -contains $_.Current.ProcessId -and
     $_.Current.Name -eq $expected -and
     $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window })
   if($matches.Count -gt 1){throw 'AMBIGUOUS_NATIVE_WINDOW'}
   if($matches.Count -eq 1){$window=$matches[0];break}
   Start-Sleep -Milliseconds 200
 }
 if($null -eq $window){throw 'OWNED_NATIVE_WINDOW_NOT_FOUND'}
 $result.ownerVerified=$true
 function ByType([System.Windows.Automation.ControlType]$kind) {
   $script:safeStage='UIA_DESCENDANT_QUERY_FAILED'
   $condition=[System.Windows.Automation.PropertyCondition]::new(
     [System.Windows.Automation.AutomationElement]::ControlTypeProperty,$kind)
   return @($window.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition))
 }
 function InvokeExact([string]$label) {
   $script:safeStage='UIA_BUTTON_SEARCH_FAILED'
   $buttons=@(ByType ([System.Windows.Automation.ControlType]::Button) |
     Where-Object { $_.Current.Name -eq $label -and $_.Current.IsEnabled })
   if($buttons.Count -ne 1){throw 'EXACT_NATIVE_BUTTON_UNAVAILABLE'}
   $script:safeStage='UIA_BUTTON_INVOKE_PATTERN_FAILED'
   try {
     $pattern=$null
     if($buttons[0].TryGetCurrentPattern(
       [System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern) -and $null -ne $pattern){
       $script:safeStage='UIA_BUTTON_INVOKE_FAILED'
       $pattern.Invoke()
       $result.activationMethod='OWNED_UIA_INVOKE'
       return
     }
   } catch { }
   # Tk may expose accessible widgets through MSAA rather than UIA Invoke.
   $script:safeStage='UIA_BUTTON_LEGACY_PATTERN_FAILED'
   try {
     $legacy=$null
     if($buttons[0].TryGetCurrentPattern(
       [System.Windows.Automation.LegacyIAccessiblePattern]::Pattern,[ref]$legacy) -and
       $null -ne $legacy){
       $legacy.DoDefaultAction()
       $result.activationMethod='OWNED_MSAA_DEFAULT_ACTION'
       return
     }
   } catch { }
   throw 'NATIVE_BUTTON_NOT_INVOKABLE'
 }
 function PrivateTkFocusedOwnedChild {
   $script:safeStage='PRIVATE_TK_NATIVE_HANDLE_UNAVAILABLE'
   $hwnd=[IntPtr]::new([int]$window.Current.NativeWindowHandle)
   if($hwnd -eq [IntPtr]::Zero){throw 'PRIVATE_TK_NATIVE_HANDLE_UNAVAILABLE'}
   $owner=[UInt32]0
   $script:safeStage='PRIVATE_TK_GUI_THREAD_UNAVAILABLE'
   $thread=[TarazQaOwnedTk]::GetWindowThreadProcessId($hwnd,[ref]$owner)
   if($thread -eq 0 -or $owned -notcontains [int]$owner){
     throw 'PRIVATE_TK_GUI_THREAD_UNAVAILABLE'
   }
   $info=[TarazQaOwnedTk+GuiThreadInfo]::new()
   $info.cbSize=[uint32][Runtime.InteropServices.Marshal]::SizeOf($info)
   if(-not [TarazQaOwnedTk]::GetGUIThreadInfo($thread,[ref]$info) -or
      $info.hwndFocus -eq [IntPtr]::Zero){
     throw 'PRIVATE_TK_GUI_THREAD_UNAVAILABLE'
   }
   $focusedOwner=[UInt32]0
   [void][TarazQaOwnedTk]::GetWindowThreadProcessId($info.hwndFocus,[ref]$focusedOwner)
   if($owned -notcontains [int]$focusedOwner -or $focusedOwner -ne $owner){
     throw 'PRIVATE_TK_FOCUS_NOT_OWNED'
   }
   if([TarazQaOwnedTk]::GetAncestor($info.hwndFocus,2) -ne $hwnd){
     throw 'PRIVATE_TK_FOCUS_OUTSIDE_WINDOW'
   }
   if($info.hwndFocus -eq $hwnd){throw 'PRIVATE_TK_LOGIN_FOCUS_NOT_ENTRY'}
   return $info.hwndFocus
 }
 function PrivateTkReturnOnlyWhenFocusOwned {
   $target=PrivateTkFocusedOwnedChild
   # The ONLY send target is the focused child HWND inside the verified
   # single-company Tk chooser, and the ONLY key is Return, never passwords.
   $script:safeStage='PRIVATE_TK_DIRECT_ENTER_REJECTED'
   if(-not [TarazQaOwnedTk]::PostMessageW($target,0x0100,[IntPtr]::new(13),[IntPtr]::Zero) -or
      -not [TarazQaOwnedTk]::PostMessageW($target,0x0101,[IntPtr]::new(13),[IntPtr]::Zero)){
     throw 'PRIVATE_TK_DIRECT_ENTER_REJECTED'
   }
   $result.activationMethod='OWNED_TK_FOCUSED_HWND_RETURN'
 }
 function PrivateTkPostAsciiOnly([IntPtr]$target,[string]$value){
   # Never print or read back credentials. Each WM_CHAR goes to a validated
   # child HWND of the ONE owned, private native login window, not OS input.
   foreach($ch in $value.ToCharArray()){
     $num=[int]$ch
     if($num -lt 33 -or $num -gt 126){throw 'PRIVATE_TK_CREDENTIALS_NON_ASCII'}
     if(-not [TarazQaOwnedTk]::PostMessageW($target,0x0102,[IntPtr]::new($num),[IntPtr]::Zero)){
       throw $script:safeStage
     }
   }
 }
 function PrivateTkEnterRealQaCredentials {
   if($env:TARAZ_QA_SINGLE_COMPANY -ne '1' -or
      $env:TARAZ_QA_SINGLE_ADMIN -ne '1'){
     throw 'PRIVATE_TK_LOGIN_ADMIN_NOT_UNIQUE'
   }
   Start-Sleep -Milliseconds 300  # Tk root.after(100) focuses username field
   $userHwnd=PrivateTkFocusedOwnedChild
   $script:safeStage='PRIVATE_TK_USERNAME_INPUT_FAILED'
   PrivateTkPostAsciiOnly $userHwnd $env:TARAZ_QA_USERNAME
   Start-Sleep -Milliseconds 160
   $script:safeStage='PRIVATE_TK_LOGIN_TAB_REJECTED'
   if(-not [TarazQaOwnedTk]::PostMessageW($userHwnd,0x0100,[IntPtr]::new(9),[IntPtr]::Zero) -or
      -not [TarazQaOwnedTk]::PostMessageW($userHwnd,0x0101,[IntPtr]::new(9),[IntPtr]::Zero)){
     throw 'PRIVATE_TK_LOGIN_TAB_REJECTED'
   }
   Start-Sleep -Milliseconds 220
   $passwordHwnd=PrivateTkFocusedOwnedChild
   if($passwordHwnd -eq $userHwnd){throw 'PRIVATE_TK_LOGIN_FOCUS_NOT_ADVANCED'}
   $script:safeStage='PRIVATE_TK_PASSWORD_INPUT_FAILED'
   PrivateTkPostAsciiOnly $passwordHwnd $env:TARAZ_QA_PASSWORD
   Start-Sleep -Milliseconds 220
   $script:safeStage='PRIVATE_TK_DIRECT_ENTER_REJECTED'
   if(-not [TarazQaOwnedTk]::PostMessageW($passwordHwnd,0x0100,[IntPtr]::new(13),[IntPtr]::Zero) -or
      -not [TarazQaOwnedTk]::PostMessageW($passwordHwnd,0x0101,[IntPtr]::new(13),[IntPtr]::Zero)){
     throw 'PRIVATE_TK_DIRECT_ENTER_REJECTED'
   }
   $result.activationMethod='OWNED_TK_FOCUSED_HWND_CREDENTIALS'
 }
 if($Stage -eq 'select') {
   $script:safeStage='UIA_LISTITEM_SEARCH_FAILED'
   $items=@()
   try {
     $items=@(ByType ([System.Windows.Automation.ControlType]::ListItem) |
       Where-Object { $_.Current.Name -eq $env:TARAZ_QA_COMPANY })
   } catch {
     # Tk's native Listbox can have only MSAA or window-proxy providers;
     # recover only when our own synthetic registry has EXACTLY one company.
     if($env:TARAZ_QA_SINGLE_COMPANY -ne '1'){throw 'QA_COMPANY_SELECTION_NOT_ACCESSIBLE'}
     $items=@()
   }
   if($items.Count -gt 1){throw 'QA_COMPANY_SELECTION_NOT_ACCESSIBLE'}
   if($items.Count -eq 1){
     $script:safeStage='UIA_LISTITEM_SELECTION_PATTERN_FAILED'
     try {
       $selection=$items[0].GetCurrentPattern(
         [System.Windows.Automation.SelectionItemPattern]::Pattern)
       if($null -eq $selection){throw 'QA_COMPANY_SELECTION_PATTERN_MISSING'}
       $script:safeStage='UIA_LISTITEM_SELECT_FAILED'
       $selection.Select()
       $result.selectionMethod='OWNED_LIST_ITEM'
     } catch {
       if($env:TARAZ_QA_SINGLE_COMPANY -ne '1'){throw 'QA_SINGLE_COMPANY_PRESELECTION_UNVERIFIED'}
     }
   }
   if($result.selectionMethod -eq 'NOT_ATTEMPTED'){
     if($env:TARAZ_QA_SINGLE_COMPANY -ne '1'){throw 'QA_SINGLE_COMPANY_PRESELECTION_UNVERIFIED'}
     $result.selectionMethod='SINGLE_REGISTERED_PRESELECTED_TK'
   }
   try {
     InvokeExact 'ورود به شرکت'
   } catch {
     if($env:TARAZ_QA_SINGLE_COMPANY -ne '1'){throw 'QA_SINGLE_COMPANY_PRESELECTION_UNVERIFIED'}
     PrivateTkReturnOnlyWhenFocusOwned
   }
   # A UIA action or a posted private Return is not evidence of advancing;
   # require the owned native login window to actually appear before PASS.
   $script:safeStage='PRIVATE_TK_LOGIN_TRANSITION_CHECK_FAILED'
   for($j=0;$j -lt 40;$j++){
     $all=$root.FindAll([System.Windows.Automation.TreeScope]::Children,
       [System.Windows.Automation.Condition]::TrueCondition)
     $logins=@($all | Where-Object { $owned -contains $_.Current.ProcessId -and
       $_.Current.Name -eq 'مدار | ورود امن حسابداری' -and
       $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window })
     if($logins.Count -gt 1){throw 'AMBIGUOUS_NATIVE_WINDOW'}
     if($logins.Count -eq 1){$result.verifiedTransition=$true;break}
     Start-Sleep -Milliseconds 150
   }
   if(-not $result.verifiedTransition){throw 'PRIVATE_TK_ENTER_DID_NOT_OPEN_LOGIN'}
 } else {
   if([string]::IsNullOrEmpty($env:TARAZ_QA_USERNAME) -or
      [string]::IsNullOrEmpty($env:TARAZ_QA_PASSWORD)){
     throw 'PRIVATE_QA_CREDENTIALS_ABSENT'
   }
   $script:safeStage='UIA_LOGIN_EDIT_SEARCH_FAILED'
   $edits=@()
   try {
     $edits=@(ByType ([System.Windows.Automation.ControlType]::Edit) |
       Where-Object { $_.Current.IsEnabled })
   } catch {
     if($env:TARAZ_QA_SINGLE_ADMIN -ne '1'){throw 'NATIVE_LOGIN_FIELDS_AMBIGUOUS'}
   }
   if($edits.Count -ne 2){
     PrivateTkEnterRealQaCredentials
   } else {
     $script:safeStage='UIA_LOGIN_EDIT_PATTERN_FAILED'
     $user=$edits[0].GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
     $pass=$edits[1].GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
     if($null -eq $user -or $null -eq $pass){throw 'NATIVE_LOGIN_VALUE_PATTERN_UNAVAILABLE'}
     $script:safeStage='UIA_LOGIN_USERNAME_SET_FAILED'
     $user.SetValue($env:TARAZ_QA_USERNAME)
     if([string]$user.Current.Value -ne $env:TARAZ_QA_USERNAME){
       throw 'NATIVE_LOGIN_USERNAME_NOT_SET'
     }
     $script:safeStage='UIA_LOGIN_PASSWORD_SET_FAILED'
     $pass.SetValue($env:TARAZ_QA_PASSWORD)
     # Never retrieve, print or serialize the password field's value.
     InvokeExact 'ورود امن'
   }
   $script:safeStage='PRIVATE_TK_LOGIN_WINDOW_TRANSITION_FAILED'
   for($j=0;$j -lt 55;$j++){
     $all=$root.FindAll([System.Windows.Automation.TreeScope]::Children,
       [System.Windows.Automation.Condition]::TrueCondition)
     $new=@($all | Where-Object { $owned -contains $_.Current.ProcessId -and
       $_.Current.Name -eq 'تراز | حسابداری' -and
       $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window })
     if($new.Count -gt 1){throw 'AMBIGUOUS_NATIVE_WINDOW'}
     if($new.Count -eq 1){$result.verifiedTransition=$true;break}
     Start-Sleep -Milliseconds 180
   }
   if(-not $result.verifiedTransition){throw 'PRIVATE_TK_LOGIN_DID_NOT_OPEN_ACCOUNTING'}
 }
 $result.submitted=$true
 $result.status='PASS_NATIVE_OWNED_UIA'
 $result.errorCode='NONE'
} catch {
 $result.errorKind=$_.Exception.GetType().Name
 $message=$_.Exception.Message
 $result.errorCode=if($known -ccontains $message){$message}else{$script:safeStage}
 $result.status='BLOCKED_NATIVE_UIA'
} finally {
 $result | ConvertTo-Json -Compress | Set-Content -LiteralPath $ResultFile -Encoding UTF8
}
if($result.status -ne 'PASS_NATIVE_OWNED_UIA'){exit 2}
'''


CDP_TEST = r'''/* Attach to exactly one ALREADY-RUNNING private frozen WebView2 page.
 No browser launch, no API mutation except via the actual visible React UI. */
'use strict';
const fs=require('node:fs');
const {chromium}=require(process.argv[3]);
const port=Number(process.argv[2]),out=process.argv[4],stage=process.argv[5];
const expectedRevision=Number(process.argv[6]);
let browser;
const result={status:'BLOCKED',stage,sourceHosted:false,frozenExe:true,
  actualUiInteraction:false,bridgeReadback:false,draftSaved:false,journalUnchanged:false};
const request='برای شرکت آریا یک فاکتور فروش بساز. ۱۰۰ عدد جعبه و ۲۰۰ عدد لیبل اضافه کن. قیمت هر کالا را از آخرین فاکتور معتبر همین مشتری بردار.';
function assert(ok,label){if(!ok)throw Error(label);}
async function main(){
 assert(['create','reopen'].includes(stage),'UNSUPPORTED_STAGE');
 browser=await chromium.connectOverCDP('http://127.0.0.1:'+port,{timeout:9000});
 const contexts=browser.contexts();
 assert(contexts.length===1,'PRIVATE_CDP_CONTEXT_AMBIGUOUS');
 const pages=contexts[0].pages().filter(p=>{
   try{const u=new URL(p.url());return u.hostname==='127.0.0.1' &&
     u.pathname==='/accounting.html';}catch{return false;}
 });
 assert(pages.length===1,'PRIVATE_ACCOUNTING_PAGE_AMBIGUOUS');
 const page=pages[0];
 await page.locator('.sac-root').waitFor({state:'visible',timeout:15000});
 assert(await page.evaluate(()=>typeof window.madar?.tarazAiChatCommand==='function' &&
    typeof window.madar?.standaloneAccountingRead==='function'), 'REAL_BRIDGE_UNAVAILABLE');
 const before=await page.evaluate(()=>window.madar.standaloneAccountingRead());
 assert(before.view.currency==='RIAL','SYNTHETIC_CURRENCY_CHANGED');
 assert(before.revision===expectedRevision,'SYNTHETIC_REVISION_UNEXPECTED');
 assert(before.view.invoices['QA-SOURCE-INV']?.status==='issued','QA_SOURCE_INVOICE_MISSING');
 assert(before.view.journals.length===1,'QA_ISSUED_JOURNAL_MISSING');
 const nav=page.locator('.sac-sidebar button').filter({hasText:'دستیار تجاری'});
 assert(await nav.count()===1,'AI_UI_NAV_AMBIGUOUS');
 await nav.click();
 const chat=page.locator('.taraz-ai-chat');
 await chat.waitFor({state:'visible',timeout:10000});
 if(stage==='create'){
   const create=chat.getByRole('button',{name:'گفتگوی جدید',exact:true});
   assert(await create.count()===1,'CHAT_CREATE_BUTTON_AMBIGUOUS');
   await create.click();
   await chat.locator('.taraz-ai-compose textarea:not([disabled])').waitFor({timeout:15000});
   await chat.locator('.taraz-ai-compose textarea').fill(request);
   const send=chat.getByRole('button',{name:'ثبت درخواست و تهیه پیشنهاد',exact:true});
   assert(await send.count()===1,'CHAT_SEND_BUTTON_AMBIGUOUS');
   await send.click();
   const proposal=chat.locator('.taraz-ai-proposal');
   await proposal.waitFor({state:'visible',timeout:15000});
   await page.waitForFunction(()=>document.querySelector('.taraz-ai-proposal')?.textContent
     ?.includes('200000'),undefined,{timeout:15000});
   assert((await proposal.innerText()).includes('QA-SOURCE-INV'),'SOURCE_REFERENCE_NOT_SHOWN');
   const beforeApproval=await page.evaluate(()=>window.madar.standaloneAccountingRead());
   assert(beforeApproval.revision===before.revision &&
     Object.keys(beforeApproval.view.invoices).length===1,'MUTATION_BEFORE_APPROVAL');
   const review=proposal.locator('.taraz-ai-review input[type="checkbox"]');
   assert(await review.count()===1,'REVIEW_CHECKBOX_MISSING');
   await review.check();
   const approve=proposal.getByRole('button',{name:'تأیید و ذخیره پیش‌نویس',exact:true});
   assert(await approve.count()===1,'APPROVAL_BUTTON_AMBIGUOUS');
   await approve.click();
   await page.waitForFunction(rev=>window.madar?.standaloneAccountingRead &&
     document.querySelector('.taraz-ai-proposal')?.textContent.includes('executed'),
     expectedRevision,{timeout:15000});
 } else {
   const entries=chat.locator('.taraz-ai-conversation-list button');
   await entries.first().waitFor({state:'visible',timeout:15000});
   assert(await entries.count()===1,'RESTART_CHAT_COUNT_MISMATCH');
   await entries.first().click();
   await chat.locator('.taraz-ai-messages article').first().waitFor({state:'visible',timeout:12000});
   assert(await chat.locator('.taraz-ai-messages article').count()===2,'RESTART_MESSAGES_MISSING');
   assert((await chat.locator('.taraz-ai-messages').innerText()).includes('۱۰۰ عدد') ||
     (await chat.locator('.taraz-ai-messages').innerText()).includes('100 عدد'),
     'ORIGINAL_REQUEST_NOT_SHOWN');
   assert((await chat.locator('.taraz-ai-proposal').innerText()).includes('executed'),
     'RESTART_EXECUTION_AUDIT_MISSING');
 }
 const after=await page.evaluate(()=>window.madar.standaloneAccountingRead());
 assert(after.revision===expectedRevision+(stage==='create'?1:0),
   'INVOICE_EVENT_REVISION_MISMATCH');
 const docs=Object.values(after.view.invoices);
 const drafts=docs.filter(d=>d.id.startsWith('AI-INV-'));
 assert(docs.length===2 && drafts.length===1,'DUPLICATE_OR_MISSING_DRAFT');
 assert(drafts[0].status==='draft' && drafts[0].total===200000 &&
        drafts[0].postedEntryId==null && drafts[0].number==null,
        'DRAFT_IS_NOT_UNISSUED');
 assert(after.view.journals.length===before.view.journals.length,
        'JOURNAL_COUNT_CHANGED');
 const conversations=await page.evaluate(()=>window.madar.tarazAiChatList(''));
 assert(conversations.conversations?.length===1,'CHAT_STORE_CONVERSATIONS_MISMATCH');
 const detail=await page.evaluate(id=>window.madar.tarazAiChatRead(id),
   conversations.conversations[0].id);
 assert(detail.messages?.length===2 && detail.executions?.length===1 &&
   detail.executions[0].status==='executed','CHAT_STORE_READBACK_MISSING');
 result.actualUiInteraction=true;
 result.bridgeReadback=true;
 result.draftSaved=true;
 result.journalUnchanged=true;
 result.messageCount=2;
 result.conversationCount=1;
 result.invoiceCount=2;
 result.savedInvoice=drafts[0].id; // synthetic-only deterministic receipt
 result.status=stage==='create'?'PASS_FROZEN_AUTH_AI_DRAFT_UI':'PASS_FROZEN_RESTART_READBACK';
 await page.screenshot({path:out.replace(/\.json$/i,'.png'),animations:'disabled'});
}
main().catch(e=>{result.status='BLOCKED';result.errorCode=String(e?.message||e).slice(0,115);
 process.exitCode=1;}).finally(async()=>{
 if(browser)try{await browser.close()}catch{}
 fs.writeFileSync(out,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
});
'''


def _owned_processes(pid: int, exe: Path) -> tuple[object, set[int]]:
    """Only the exact already-spawned candidate and current descendants."""
    import psutil
    try:
        parent = psutil.Process(pid)
        if Path(parent.exe()).resolve() != exe.resolve():
            raise FrozenAuthBlocked("Private root process is not pinned frozen EXE")
        children = parent.children(recursive=True)
        return parent, {pid, *(child.pid for child in children)}
    except psutil.Error as exc:
        raise FrozenAuthBlocked("Private EXE process identity unavailable") from exc


def _native_uia_stage(desktop, pid: int, exe: Path, stage: str,
                      work: Path, environment: dict, index: int) -> dict:
    """Invoke UIA against EXACT private-desktop native window, never user input."""
    if stage not in ("select", "login"):
        raise FrozenAuthBlocked("Unknown private UIA stage")
    # Frozen one-file bootloader can spawn its real GUI in a later child PID.
    # Observe only windows attached to this private desktop and verified tree.
    deadline = time.monotonic() + 9
    while True:
        _parent, pids = _owned_processes(pid, exe)
        if _owned_private_windows(desktop, pids):
            break
        if time.monotonic() > deadline:
            raise FrozenAuthBlocked("Owned native authentication window unavailable")
        time.sleep(.25)
    powershell = (Path(os.environ.get("SystemRoot", "")) / "System32" /
                  "WindowsPowerShell" / "v1.0" / "powershell.exe")
    if not powershell.is_file():
        raise FrozenAuthBlocked("Private native UI automation unavailable")
    script = work / f"private-auth-{index}-{stage}.ps1"
    outcome = work / f"private-auth-{index}-{stage}.json"
    script.write_text(AUTH_UIA_PS, encoding="utf-8-sig")
    helper_pid, handle, thread = desktop.spawn(
        powershell, work, environment,
        ("-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-OwnerIds", ",".join(str(p) for p in sorted(pids)),
         "-Stage", stage, "-ResultFile", str(outcome)))
    kernel = ctypes.windll.kernel32
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        if kernel.WaitForSingleObject(handle, 26000) != 0:
            raise FrozenAuthBlocked("Private UIA helper timeout; no force stop")
        if not outcome.is_file():
            raise FrozenAuthBlocked("Private UIA helper produced no witness")
        raw = outcome.read_text(encoding="utf-8-sig")
        proof = json.loads(raw)
        if (type(proof) is not dict or proof.get("status") != "PASS_NATIVE_OWNED_UIA" or
                proof.get("ownerVerified") is not True or
                proof.get("submitted") is not True or proof.get("stage") != stage):
            code = safe_native_uia_error_code(proof.get("errorCode"))
            raise FrozenAuthBlocked("Native " + stage + " blocked: " + code)
        return {"stage": stage, "ownerVerified": True, "submitted": True}
    finally:
        kernel.CloseHandle(handle)
        kernel.CloseHandle(thread)


def _confirmed_private_cdp(pid: int, exe: Path, port: int) -> dict:
    from scripts import qa_taraz_v103_native_gui_20261111 as native
    import psutil
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        parent, pids = _owned_processes(pid, exe)
        evidence = native.safe_webview_diagnostics(pid, port)
        if (evidence.get("cdpPortListening") is True and
                evidence.get("expectedPortFlag") is True and
                evidence.get("anyIsolatedWebviewProfileArg") is True):
            break
        if not parent.is_running():
            raise FrozenAuthBlocked("Private EXE exited before verified WebView CDP")
        time.sleep(.35)
    else:
        raise FrozenAuthBlocked("Private frozen WebView2 CDP unavailable")
    listeners = [connection for connection in psutil.net_connections(kind="tcp")
                 if connection.laddr and connection.laddr.port == port and
                 connection.status == psutil.CONN_LISTEN]
    if (len(listeners) != 1 or
            listeners[0].laddr.ip not in ("127.0.0.1", "::1") or
            listeners[0].pid not in pids):
        raise FrozenAuthBlocked("CDP listener not uniquely owned and loopback-only")
    return {"ownedWebViewCount": evidence["ownedWebView2Count"],
            "ownedPort": True, "isolatedProfile": True, "loopbackOnly": True}


def _execute_private_cdp(port: int, work: Path, environment: dict,
                         stage: str, expected_revision: int, index: int) -> dict:
    import shutil
    runner = shutil.which("node")
    playwright = ROOT / "node_modules" / "playwright"
    if not runner or not playwright.is_dir():
        raise FrozenAuthBlocked("Local Node and Playwright CDP automation unavailable")
    script = work / f"private-frozen-cdp-{index}.cjs"
    outcome = work / f"private-frozen-cdp-{index}.json"
    script.write_text(CDP_TEST, encoding="utf-8")
    # Connect ONLY to the running frozen browser. Do not launch Chromium.
    process = subprocess.run([runner, str(script), str(port), str(playwright),
                              str(outcome), stage, str(expected_revision)],
                             cwd=work, env=environment, check=False, capture_output=True,
                             timeout=65, text=True, encoding="utf-8", errors="replace")
    if process.returncode or not outcome.is_file():
        raise FrozenAuthBlocked("Real frozen CDP UI test failed/produced no witness")
    report = json.loads(outcome.read_text(encoding="utf-8"))
    expected_status = ("PASS_FROZEN_AUTH_AI_DRAFT_UI" if stage == "create" else
                       "PASS_FROZEN_RESTART_READBACK")
    if (type(report) is not dict or report.get("status") != expected_status or
            report.get("actualUiInteraction") is not True or
            report.get("bridgeReadback") is not True or
            report.get("journalUnchanged") is not True or
            report.get("draftSaved") is not True or
            report.get("sourceHosted") is not False or
            report.get("frozenExe") is not True or
            not outcome.with_suffix(".png").is_file()):
        raise FrozenAuthBlocked("Frozen UI → Bridge → SQLite acceptance incomplete")
    return report


def _owned_private_windows(desktop, valid_pids: set[int]) -> list[int]:
    """Find only known Taraz/Tk windows on our unexposed private desktop."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.EnumDesktopWindows.argtypes = [wintypes.HANDLE, callback_type, wintypes.LPARAM]
    user32.EnumDesktopWindows.restype = wintypes.BOOL
    windows = []

    @callback_type
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value not in valid_pids or not user32.IsWindowVisible(hwnd):
            return True
        label = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, label, len(label))
        if (label.value.startswith("تراز | ") or
                label.value == "مدار | ورود امن حسابداری"):
            windows.append(int(hwnd))
        return True

    if not user32.EnumDesktopWindows(desktop.handle, visit, 0):
        raise FrozenAuthBlocked("Private desktop owned-window enumeration failed")
    return windows


def _graceful_close(desktop, pid: int, exe: Path) -> dict:
    """WM_CLOSE one verifiably owned native window; NEVER kill any process."""
    import psutil
    try:
        process, pids = _owned_processes(pid, exe)
    except FrozenAuthBlocked:
        return {"graceful": False, "reason": "OWNED_PID_UNAVAILABLE"}
    windows = _owned_private_windows(desktop, pids)
    if len(windows) != 1:
        return {"graceful": False, "reason": "OWNED_WINDOW_NOT_UNIQUE",
                "windowCount": len(windows)}
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    if not user32.PostMessageW(windows[0], 0x0010, 0, 0):
        return {"graceful": False, "reason": "WM_CLOSE_NOT_ACCEPTED"}
    try:
        process.wait(timeout=24)
    except (psutil.TimeoutExpired, psutil.Error):
        return {"graceful": False, "reason": "PRIVATE_EXE_STILL_RUNNING", "pid": pid}
    # Do not claim success while owned WebView processes still remain.
    alive = []
    for child_pid in pids - {pid}:
        try:
            if psutil.Process(child_pid).is_running():
                alive.append(child_pid)
        except psutil.NoSuchProcess:
            pass
    return {"graceful": not alive, "reason": "CLOSED" if not alive else "CHILDREN_REMAIN",
            "ownedChildrenRemaining": len(alive)}


def _phase(desktop, exe: Path, work: Path, env: dict, *,
           port: int, phase: str, revision: int, index: int) -> dict:
    """One frozen EXE process lifecycle, one CDP attachment, private native UIA."""
    from scripts import qa_taraz_v103_native_gui_20261111 as native
    pid, handle, thread = desktop.spawn(exe, work, env)
    output = {"phase": phase, "frozenPid": pid,
              "realNativeLogin": False, "privateUiTest": False,
              "gracefulShutdown": False}
    try:
        # The process can have one PyInstaller bootloader and a child GUI PID.
        time.sleep(.9)
        _owned_processes(pid, exe)
        selection = _native_uia_stage(desktop, pid, exe, "select", work, env, index)
        authentication = _native_uia_stage(desktop, pid, exe, "login", work, env, index)
        output["realNativeLogin"] = selection["submitted"] and authentication["submitted"]
        output["cdp"] = _confirmed_private_cdp(pid, exe, port)
        output["ui"] = _execute_private_cdp(port, work, env, phase, revision, index)
        output["privateUiTest"] = True
    except Exception as exc:
        output["errorType"] = type(exc).__name__
        # Restrict reports to reason categories, not financial data or passwords.
        output["errorCode"] = (str(exc)[:120] if isinstance(exc, FrozenAuthBlocked)
                               else "UNEXPECTED_PRIVATE_QA_ERROR")
    finally:
        try:
            output["close"] = _graceful_close(desktop, pid, exe)
            output["gracefulShutdown"] = output["close"]["graceful"] is True
        except Exception as exc:
            output["close"] = {"graceful": False, "errorType": type(exc).__name__}
        ctypes.windll.kernel32.CloseHandle(handle)
        ctypes.windll.kernel32.CloseHandle(thread)
    output["status"] = ("PASS_PRIVATE_FROZEN_SESSION" if
                        output["realNativeLogin"] and output["privateUiTest"] and
                        output["gracefulShutdown"] else "BLOCKED")
    return output


def _independent_readback(fixture: dict) -> dict:
    """Independent local SQLite/DPAPI witness after BOTH EXE sessions exit."""
    from standalone_accounting import StandaloneAccountingStore
    from standalone_accounting_identity import LocalCompanyIdentity
    from taraz_ai_chat_store import TarazAiChatStore

    book = fixture["book"]
    identity = LocalCompanyIdentity(book)
    state = StandaloneAccountingStore(book / "standalone-accounting.sqlite3",
                                      default_currency="RIAL").read(
                                          actor=QA_USER, accounts=identity.accounting_accounts())
    baseline = fixture["baseline"]
    docs = state["view"].get("invoices", {})
    drafts = [doc for doc in docs.values() if doc["id"].startswith("AI-INV-")]
    chat = TarazAiChatStore(book, tenant_id=fixture["companyId"], actor=QA_USER)
    conversations = chat.list("")["conversations"]
    details = chat.read(conversations[0]["id"]) if len(conversations) == 1 else None
    passed = (state["revision"] == baseline["revision"] + 1 and
              state["view"].get("journals") == baseline["view"].get("journals") and
              state["view"].get("currency") == "RIAL" and
              len(docs) == 2 and len(drafts) == 1 and
              drafts[0].get("status") == "draft" and
              drafts[0].get("postedEntryId") is None and
              drafts[0].get("total") == 200000 and
              details is not None and len(details["messages"]) == 2 and
              len(details["executions"]) == 1 and
              details["executions"][0]["status"] == "executed" and
              details["messages"][0]["content"] == QA_REQUEST)
    return {"status": "PASS_INDEPENDENT_PRIVATE_SQLITE" if passed else "BLOCKED",
            "syntheticOnly": True, "invoiceCount": len(docs),
            "draftCount": len(drafts), "messageCount": len(details["messages"]) if details else 0,
            "journalUnchanged": state["view"].get("journals") == baseline["view"].get("journals"),
            "revisionDelta": state["revision"] - baseline["revision"]}


def _resources_available(parent: Path) -> None:
    import psutil
    import shutil
    if os.cpu_count() is None or os.cpu_count() < 2:
        raise FrozenAuthBlocked("At least two logical CPU cores are required")
    if psutil.virtual_memory().available < 1024 * 1024 * 1024:
        raise FrozenAuthBlocked("Insufficient RAM for private WebView2 QA")
    if shutil.disk_usage(parent).free < 1024 * 1024 * 1024:
        raise FrozenAuthBlocked("Insufficient private QA disk space")
    if not (ROOT / "node_modules" / "playwright").is_dir():
        raise FrozenAuthBlocked("Project-local Playwright package unavailable")
    powershell = (Path(os.environ.get("SystemRoot", "")) / "System32" /
                  "WindowsPowerShell" / "v1.0" / "powershell.exe")
    if not powershell.is_file():
        raise FrozenAuthBlocked("Native private-desktop UIA runner unavailable")
    try:
        probe = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command",
             "Add-Type -AssemblyName UIAutomationClient; "
             "Add-Type -AssemblyName UIAutomationTypes; "
             "$item=[System.Windows.Automation.PropertyCondition]::new(" 
             "[System.Windows.Automation.AutomationElement]::ControlTypeProperty," 
             "[System.Windows.Automation.ControlType]::Edit); "
             "if($null -eq $item){exit 2}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=12, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrozenAuthBlocked("Native UIA capability check unavailable") from exc
    if probe.returncode:
        raise FrozenAuthBlocked("Native UIAutomation framework unavailable")


def run_private(exe: Path, exe_sha: str, source_sha: str) -> dict:
    """Explicit FUTURE invocation only. No candidate => no process or profile."""
    if os.name != "nt":
        raise FrozenAuthBlocked("Private frozen Windows QA requires Windows")
    candidate = validate_candidate(exe, exe_sha, source_sha)
    if not PRIVATE_OUT.parent.is_dir() or not _ordinary_path(PRIVATE_OUT.parent):
        raise FrozenAuthBlocked("Untrusted output parent")
    _resources_available(PRIVATE_OUT.parent)
    from scripts import qa_taraz_v103_native_gui_20261111 as native
    from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acl
    import psutil

    if not PRIVATE_OUT.exists():
        acl.secure_private_directory(PRIVATE_OUT)
    elif not PRIVATE_OUT.is_dir() or not _ordinary_path(PRIVATE_OUT):
        raise FrozenAuthBlocked("Untrusted private QA output root")
    work = PRIVATE_OUT / ("qa-" + uuid.uuid4().hex[:16])
    acl.secure_private_directory(work)
    marker = work / "qa-owned-marker.json"
    marker.write_text(json.dumps({"syntheticOnly": True, "frozenOnly": True,
                                  "pinned": candidate}), encoding="utf-8")
    output = {"status": "BLOCKED", "sourceHosted": False,
              "frozenExeExecuted": False, "syntheticOnly": True,
              "candidate": candidate, "qaDirectory": str(work),
              "noForcedTermination": True, "installedExecutableLaunched": False}
    initial_pids = {p.pid: p.create_time() for p in psutil.process_iter(["name"])
                    if (p.info.get("name") or "").casefold() == "taraz.exe"}
    started = time.monotonic()
    fixture = None
    try:
        runtime = work / "qa" / "qa-runtime"
        runtime.mkdir(parents=True, exist_ok=False)
        fixture = create_private_fixture(runtime)
        # Actual Taraz expects profile == TARAZ_QA_DATA_DIR, while
        # private_qa_cdp_port also requires profile.parent == APPDATA.
        roots = {"roaming": fixture["profile"],
                 "local": runtime / "localappdata", "bridge": runtime / "localappdata"}
        ports = [native.unused_port(), native.unused_port()]
        if ports[0] == ports[1]:
            raise FrozenAuthBlocked("Two QA CDP launches cannot share one port")
        for index, phase in enumerate(("create", "reopen"), 1):
            environment = native.isolated_env(
                runtime, roots, work / f"native-startup-{index}.json", ports[index - 1])
            environment["TARAZ_QA_DATA_DIR"] = str(fixture["profile"])
            environment["TARAZ_QA_CDP_PORT"] = str(ports[index - 1])
            environment["TARAZ_QA_COMPANY"] = QA_COMPANY
            environment["TARAZ_QA_SINGLE_COMPANY"] = "1"
            environment["TARAZ_QA_SINGLE_ADMIN"] = "1"
            environment["TARAZ_QA_USERNAME"] = QA_USER
            environment["TARAZ_QA_PASSWORD"] = fixture["password"]
            _guard_private_paths(runtime, fixture["profile"], fixture["book"], environment)
            if digest(exe) != exe_sha:
                raise FrozenAuthBlocked("Frozen EXE changed between private sessions")
            with native.PrivateDesktop() as desktop:
                phase_result = _phase(
                    desktop, exe, work, environment,
                    port=ports[index - 1], phase=phase,
                    revision=fixture["baseline"]["revision"] + (index - 1),
                    index=index)
            # `_phase` returns only after a verified private CreateProcessW.
            output["frozenExeExecuted"] = True
            output["phase" + str(index)] = phase_result
            if phase_result["status"] != "PASS_PRIVATE_FROZEN_SESSION":
                raise FrozenAuthBlocked("Frozen " + phase + " UI session not accepted")
        output["independent"] = _independent_readback(fixture)
        if output["independent"]["status"] != "PASS_INDEPENDENT_PRIVATE_SQLITE":
            raise FrozenAuthBlocked("Post-restart independent SQLite/DPAPI witness failed")
        output["status"] = "PASS_PRIVATE_FROZEN_AUTH_AI_UI_BRIDGE_SQLITE"
    except Exception as exc:
        output["status"] = "BLOCKED"
        output["errorType"] = type(exc).__name__
        output["errorCode"] = (str(exc)[:120] if isinstance(exc, FrozenAuthBlocked)
                               else "UNEXPECTED_PRIVATE_QA_FAILURE")
    finally:
        output["durationSeconds"] = round(time.monotonic() - started, 2)
        output["candidateShaUnchanged"] = (exe.is_file() and digest(exe) == exe_sha)
        current_pids = {p.pid: p.create_time() for p in psutil.process_iter(["name"])
                        if (p.info.get("name") or "").casefold() == "taraz.exe"}
        output["preexistingTarazPidsUnchanged"] = all(
            current_pids.get(pid) == ctime for pid, ctime in initial_pids.items())
        output["qaTarazProcessesRemain"] = len(set(current_pids) - set(initial_pids))
        if (not output["candidateShaUnchanged"] or
                not output["preexistingTarazPidsUnchanged"] or
                output["qaTarazProcessesRemain"]):
            output["status"] = "BLOCKED"
        (work / "frozen-real-auth-acceptance.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PENDING private frozen Taraz authenticated AI QA")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true",
                      help="Read-only candidate verification; never starts a process")
    mode.add_argument("--run-private", action="store_true",
                      help="Explicitly run SHA-pinned uninstalled EXE on private desktop")
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--source-sha256")
    args = parser.parse_args(argv)
    if not (args.exe and args.sha256 and args.source_sha256):
        print(json.dumps({"status": "BLOCKED_CANDIDATE_NOT_READY",
                          "frozenExeTested": False, "privateDesktopLaunched": False}))
        return 2
    try:
        report = validate_candidate(args.exe, args.sha256, args.source_sha256)
        if args.preflight:
            print(json.dumps({"status": "PINNED_UNINSTALLED_CANDIDATE_FOUND_NOT_TESTED",
                              "frozenExeTested": False, "candidate": report}))
            return 0
        result = run_private(args.exe, args.sha256, args.source_sha256)
        print(json.dumps({"status": result["status"],
                          "frozenExeTested": result["frozenExeExecuted"],
                          "report": str(Path(result["qaDirectory"]) /
                                        "frozen-real-auth-acceptance.json")},
                         ensure_ascii=False))
        return 0 if result["status"] == "PASS_PRIVATE_FROZEN_AUTH_AI_UI_BRIDGE_SQLITE" else 1
    except FrozenAuthBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "frozenExeTested": False,
                          "reason": str(exc)[:120]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
