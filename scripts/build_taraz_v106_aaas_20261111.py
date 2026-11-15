"""Genuine Taraz 1.0.6 non-QA offline candidate for orders and beginner invoices.

Builds ONLY after the prime supplies the byte-exact source inventory digest
from worker27's frozen frontend/backend. No changes to installed Taraz,
live data, services, launcher, pointer, or old build candidates. Installation,
activation and rollback are distinct manually invoked scripts. Default action
is read-only preflight.
"""
from __future__ import annotations

import argparse
import ctypes
import dis
import hashlib
import json
import marshal
import os
from pathlib import Path
import re
import shutil
import sys
import types
import uuid
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import build_taraz_v101_local_update_20261110 as legacy

VERSION = "1.0.6"
BASE_VERSION = "1.0.4"
BASE_EXE_SHA = "9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce"
LAUNCHER_SHA = "93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21"
BASE_POINTER_SHA = "eb8d72a2c4783965876f89d494d6ecdd3502c814e0229d50cea66eb65169856d"
ACTIVATED_POINTER_SHA = hashlib.sha256(b"1.0.6\r\n").hexdigest()
OUTPUT = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.6-aaas"
MAX_EXE = 100 * 1024 * 1024
MANDATORY = {
    "taraz_order_store.py", "taraz_desktop.py", "standalone_accounting_desktop.py",
    "taraz_aaas_agent.py", "taraz_madar_order_link.py",
    "taraz_madar_order_sync.py",
    "taraz_ecosystem_protocol.py", "taraz_ecosystem_outbox.py",
    "taraz_repository_contracts.py",
    "taraz_ai_provider_status.py",
    "taraz_ai_chat_store.py", "taraz_ai_business_service.py",
    "taraz_ai_invoice_intake.py",
    "standalone_accounting_identity.py",
    "standalone_accounting_company_registry.py",
    "standalone_accounting_secure_login.py",
    "taraz_legacy_workspace_bridge.py",
    "taraz_legacy_ownership_enrollment.py",
    "taraz_legacy_enrollment_dialog.py",
    "taraz_fresh_windows_workspace.py",
    "taraz_llm_order_suggest.py", "taraz_llm_print_suggest.py",
    "src/taraz_order_workspace.jsx", "src/taraz_order_workspace.css",
    "src/accounting_invoice_wizard.jsx", "src/accounting_invoice_wizard.css",
    "src/accounting_top_ribbon.jsx", "src/standalone_accounting_workspace.jsx",
    "src/taraz_ai_chat_workspace.jsx", "src/taraz_ai_chat_workspace.css",
    "src/taraz_order_intake.js", "src/accounting_print_designer.jsx",
    "src/accounting_print_template.js",
    "src/standalone_main.jsx", "package.json", "package-lock.json",
    "src/accounting_navigation_shell.jsx",
    "accounting.html", "vite.config.js",
}
REQUIRED_ORDER_API = {
    "tarazOrderList", "tarazOrderCommand", "tarazOrderSuggest", "tarazPrintSuggest",
    "tarazOrderFinanceDraft", "tarazAgentOrderReview",
    "tarazAgentNaturalRequest", "tarazAgentMemoryList",
    "tarazAgentMemoryCommand", "tarazOrderMadarLinkRead", "tarazOrderMadarLink",
    "tarazMadarOrderPreview", "tarazMadarOrderCommit",
    "tarazMadarOrderProgress",
    "tarazMadarOrderSyncHistory", "tarazMadarOrderRecover",
    "tarazEcosystemStatus", "tarazAiProviderStatus",
    "tarazAiChatList", "tarazAiChatRead", "tarazAiChatCommand",
}
REQUIRED_PYZ = {
    "taraz_legacy_workspace_bridge": {"verify_workspace", "LegacyLocalViewerIdentity"},
    "taraz_legacy_ownership_enrollment": {"stage_legacy_company", "approve_declaration", "pending_company"},
    "taraz_legacy_enrollment_dialog": {"prompt_pending_legacy_enrollment"},
    "taraz_fresh_windows_workspace": {"stage_new_empty_root", "open_fresh_company"},
    "taraz_ai_chat_store": {"TarazAiChatStore", "create", "append", "read", "replay"},
    "taraz_ai_business_service": {"AiBusinessService", "command"},
    "taraz_ai_invoice_intake": {"invoice_preview", "preview_reply"},
    "standalone_accounting_identity": {"LocalCompanyIdentity", "login", "require_session"},
    "standalone_accounting_company_registry": {"StandaloneCompanyRegistry", "company_data_directory"},
    "standalone_accounting_secure_login": {"prompt_premium_accounting_login"},
    "taraz_order_store": {"TarazOrderStore", "list", "command", "get"},
    "taraz_aaas_agent": {"CompanyAgentMemory", "review_order_tools",
                         "interpret_natural_order_request", "list", "command"},
    "taraz_madar_order_link": {"MadarOrderLinkStore", "read", "bind",
                               "begin_sync_attempt", "mark_sync_transmitting",
                               "finish_sync_attempt", "reconcile_uncertain"},
    "taraz_madar_order_sync": {"sync_order_to_madar", "prepare_madar_order_state",
                               "extract_madar_order_stage_progress",
                               "read_madar_order_stage_progress"},
    "taraz_ecosystem_protocol": {"TrustedScope", "validate_envelope"},
    "taraz_ecosystem_outbox": {"EcosystemOutbox", "enqueue",
                                "mark_possibly_sent", "reconcile_verified_receipt"},
    "taraz_repository_contracts": {"TarazOrderReadRepository",
                                   "VersionedReference", "read_reference"},
    "taraz_ai_provider_status": {"provider_status"},
    "taraz_llm_order_suggest": {"suggest_order"},
    "taraz_llm_print_suggest": {"suggest_print_layout"},
    "standalone_accounting_template_store": {"save", "set_default", "duplicate"},
    "taraz_madar_data_reader": {"read_local_madar_state", "read_authorized_madar_state"},
}
JS_WITNESSES = (b"tarazOrderList", b"tarazOrderCommand", b"tarazOrderSuggest", b"tarazPrintSuggest", b"taraz-orders",
                b"tarazOrderFinanceDraft", b"tarazAgentOrderReview",
                b"tarazAgentMemoryCommand", b"tarazAgentNaturalRequest",
                b"tarazMadarOrderPreview", b"tarazMadarOrderProgress",
                b"tarazMadarOrderSyncHistory", b"tarazMadarOrderRecover",
                b"tarazEcosystemStatus", b"tarazAiProviderStatus",
                b"tarazAiChatList", b"tarazAiChatRead", b"tarazAiChatCommand",
                "دستیار تجاری".encode("utf-8"),
                b"sac-invoice-beginner", b"invoiceDesign")
CSS_WITNESSES = (b".taraz-orders", b".sac-invoice-beginner-pane", b".taraz-ai-chat")
BuildBlocked = legacy.BuildBlocked


def sha(file: Path) -> str:
    return legacy.sha(file)


def source_inventory() -> dict[str, str]:
    source = legacy.source_hashes(ROOT)
    absent = MANDATORY - source.keys()
    if absent or len(source) < 131:
        raise BuildBlocked("Incomplete AaaS runtime source inventory: " + ",".join(sorted(absent)))
    entry = (ROOT / "taraz_desktop.py").read_text(encoding="utf-8")
    if any("def " + method + "(" not in entry for method in REQUIRED_ORDER_API):
        raise BuildBlocked("Native order API methods are missing")
    bridge = (ROOT / "standalone_accounting_desktop.py").read_text(encoding="utf-8")
    if "window.madar = Object.fromEntries(" not in bridge or any(
            "'" + method + "'" not in bridge for method in REQUIRED_ORDER_API):
        raise BuildBlocked("WebView2 JavaScript bridge omits required order methods")
    ui = (ROOT / "src" / "standalone_accounting_workspace.jsx").read_text(encoding="utf-8")
    if ("TarazOrderWorkspace" not in ui or "invoiceWizardMode" not in ui or
            "beginner" not in ui or "TarazAiChatWorkspace" not in ui):
        raise BuildBlocked("Order workspace or beginner invoice entry is missing")
    ai_frontend = (ROOT / "src" / "taraz_ai_chat_workspace.jsx").read_text(encoding="utf-8")
    if ("tarazAiChatCommand" not in ai_frontend or
            "manualConfirmation:true" not in ai_frontend):
        raise BuildBlocked("AI conversation bridge or manual human approval missing")
    if "tarazOrderCommand" not in (ROOT / "src" / "taraz_order_workspace.jsx").read_text(
            encoding="utf-8"):
        raise BuildBlocked("Order frontend does not call native command API")
    return source


def digest_inventory(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def installed_baseline(*, root: Path | None = None) -> dict:
    if os.name != "nt":
        raise BuildBlocked("Windows 1.0.4 baseline required")
    app = root or (Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz")
    pointer = app / "current-version.txt"
    launcher = app / "Run-Taraz.cmd"
    exe = app / "versions" / BASE_VERSION / "Taraz.exe"
    future = app / "versions" / VERSION
    for path in (app, pointer, launcher, exe, future):
        legacy.refuse_links(path)
    if not app.is_dir() or not all(p.is_file() for p in (pointer, launcher, exe)):
        raise BuildBlocked("Installed 1.0.4 launcher/EXE/pointer missing")
    if pointer.read_text(encoding="utf-8-sig").strip() != BASE_VERSION:
        raise BuildBlocked("Installed pointer differs from 1.0.4")
    for path, expected in ((pointer, BASE_POINTER_SHA),
                           (launcher, LAUNCHER_SHA), (exe, BASE_EXE_SHA)):
        if sha(path) != expected:
            raise BuildBlocked("Installed 1.0.4 attestation mismatch: " + path.name)
    if "versions\\%TARAZ_VERSION%\\Taraz.exe" not in launcher.read_text(
            encoding="utf-8", errors="replace"):
        raise BuildBlocked("Installed versioned-launcher contract changed")
    if future.exists():
        raise BuildBlocked("Installed 1.0.6 already exists; never overwrite")
    return {"version": BASE_VERSION, "exeSha256": BASE_EXE_SHA,
            "pointerSha256": BASE_POINTER_SHA, "launcherSha256": LAUNCHER_SHA,
            "root": str(app), "version105Absent": True}


def stage_version(snapshot: Path) -> dict:
    package, lock = snapshot / "package.json", snapshot / "package-lock.json"
    p = json.loads(package.read_text(encoding="utf-8"))
    l = json.loads(lock.read_text(encoding="utf-8"))
    if (p.get("name") != "taraz-accounting" or l.get("name") != "taraz-accounting" or
            [p.get("version"), l.get("version"),
             l.get("packages", {}).get("", {}).get("version")] != ["1.0.0"] * 3):
        raise BuildBlocked("Unexpected source package/version lock inputs")
    p["version"] = l["version"] = l["packages"][""]["version"] = VERSION
    package.write_text(json.dumps(p, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lock.write_text(json.dumps(l, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    module = snapshot / "taraz_release_version.py"
    if module.exists():
        raise BuildBlocked("Release version module is already staged")
    module.write_text(
        '"""Non-QA Taraz AaaS release metadata."""\nAPP_VERSION = "1.0.6"\n'
        'QA_ONLY = False\nBUILD_CHANNEL = "offline-production-candidate"\n',
        encoding="utf-8")
    main = snapshot / "taraz_desktop.py"
    original = main.read_text(encoding="utf-8")
    anchor = "from __future__ import annotations\n"
    if original.count(anchor) != 1 or "taraz_release_version" in original or (
            "_taraz_qa_launch_gate" in original or "TARAZ_QA_RUN_ROOT" in original):
        raise BuildBlocked("Native main includes unknown QA/release launch guard")
    main.write_text(original.replace(anchor, anchor +
        '\nfrom taraz_release_version import APP_VERSION as _taraz_app_version\n'
        'if _taraz_app_version != "1.0.6":\n'
        '    raise RuntimeError("Taraz 1.0.6 release version mismatch")\n', 1),
        encoding="utf-8")
    return {"package": sha(package), "lock": sha(lock),
            "releaseModule": sha(module), "entrypoint": sha(main)}


def pe_resource(path: Path) -> None:
    # Format comes from the tested v101 resource; only the v106 fields differ.
    legacy.version_resource(path)
    original = path.read_text(encoding="utf-8")
    updated = original.replace("1,0,1,0", "1,0,6,0").replace(
        "1.0.1.0", "1.0.6.0")
    if "1.0.1.0" in updated or "1,0,1,0" in updated:
        raise BuildBlocked("Old PE version resource leaked into v106")
    path.write_text(updated, encoding="utf-8")


def pe_version(exe: Path) -> str:
    from scripts.qa_taraz_v103_independent_acceptance_20261111 import pe_fixed_version
    found = pe_fixed_version(exe)
    if found != "1.0.6.0":
        raise BuildBlocked("Expected PE 1.0.6.0; actual " + found)
    return found


def assigned(code: types.CodeType, name: str):
    instructions = list(dis.get_instructions(code))
    for i, instruction in enumerate(instructions):
        if i and instruction.opname in ("STORE_NAME", "STORE_GLOBAL") and (
                instruction.argval == name and instructions[i - 1].opname == "LOAD_CONST"):
            return instructions[i - 1].argval
    raise BuildBlocked("Release PYZ missing exact constant " + name)


def inspect_exe(exe: Path, web: Path) -> dict:
    from PyInstaller.archive.readers import CArchiveReader
    from scripts.qa_mtr_taraz_build_20261110 import _code_strings
    if not exe.is_file() or exe.stat().st_size > MAX_EXE:
        raise BuildBlocked("Native binary missing/oversized")
    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    release = pyz.extract("taraz_release_version")
    if (not isinstance(release, types.CodeType) or assigned(release, "APP_VERSION") != VERSION or
            assigned(release, "QA_ONLY") is not False or
            assigned(release, "BUILD_CHANNEL") != "offline-production-candidate"):
        raise BuildBlocked("Frozen PYZ is QA-only or has mismatched version")
    packed_entry = archive.extract("taraz_desktop")
    if not isinstance(packed_entry, bytes):
        raise BuildBlocked("Missing native Taraz entry in EXE")
    entry = marshal.loads(packed_entry)
    if not isinstance(entry, types.CodeType):
        raise BuildBlocked("Invalid frozen native entry")
    available = legacy.methods(entry)
    if not REQUIRED_ORDER_API <= available or "_taraz_qa_launch_gate" in available:
        raise BuildBlocked("Order API missing or QA guard present in real EXE")
    bridge = pyz.extract("standalone_accounting_desktop")
    if not isinstance(bridge, types.CodeType):
        raise BuildBlocked("Native WebView2 bridge absent from EXE")
    forwarders = [value for value in _code_strings(bridge)
                  if "window.madar = Object.fromEntries(" in value]
    if len(forwarders) != 1 or not all(
            "'" + method + "'" in forwarders[0] for method in REQUIRED_ORDER_API):
        raise BuildBlocked("Native-to-JavaScript order bridge forwarding absent")
    for module_name, required in REQUIRED_PYZ.items():
        code = pyz.extract(module_name)
        if not isinstance(code, types.CodeType) or not required <= legacy.methods(code):
            raise BuildBlocked("Frozen runtime PYZ lacks " + module_name)
    packed_names = {name.replace("\\", "/"): name for name in archive.toc}
    ui, js, css = {}, {}, {}
    for file in sorted(web.rglob("*")):
        if not file.is_file():
            continue
        name = file.relative_to(web).as_posix()
        archive_name = packed_names.get("dist/" + name)
        if archive_name is None:
            raise BuildBlocked("Compiled UI asset absent in EXE: " + name)
        actual = archive.extract(archive_name)
        expected = sha(file)
        if not isinstance(actual, bytes) or hashlib.sha256(actual).hexdigest() != expected:
            raise BuildBlocked("Frozen UI asset hash mismatch: " + name)
        ui[name] = expected
        if name.endswith(".js"):
            js[name] = expected
        if name.endswith(".css"):
            css[name] = expected
    if not js or not css or "accounting.html" not in ui:
        raise BuildBlocked("Missing HTML/JS/CSS in packed EXE")
    script = b" ".join((web / name).read_bytes() for name in js)
    styles = b" ".join((web / name).read_bytes() for name in css)
    if any(marker not in script for marker in JS_WITNESSES):
        raise BuildBlocked("Packed AaaS orders/invoice UI JS witnesses missing")
    if any(marker not in styles for marker in CSS_WITNESSES):
        raise BuildBlocked("Packed AaaS orders/invoice CSS witnesses missing")
    return {"peVersion": pe_version(exe), "pyzVersion": VERSION,
            "qaOnly": False, "orderApiMethods": sorted(REQUIRED_ORDER_API),
            "pyzRuntimeModules": {k: sorted(v) for k, v in REQUIRED_PYZ.items()},
            "bridgeForwarded": True, "compiledOrderAndInvoice": True,
            "assetsSha256": ui, "jsSha256": js, "compiledByteParity": True}


# PowerShell 5.1 scripts are intentionally small and independent. The explicit
# baseline/current/payload digests are substituted only after actual EXE build.
_PS_HEADER = r'''param([switch]$Apply,[switch]$Rehearsal)
$ErrorActionPreference = 'Stop'
function Deny([string]$message) { throw ('TARAZ V106 OPERATION BLOCKED: ' + $message) }
function RequireIsolatedRehearsal {
  if(-not $Rehearsal -or $env:TARAZ_QA_MODE -ne '1' -or
     [string]::IsNullOrWhiteSpace($env:TARAZ_QA_ROOT)) {
    Deny 'Rehearsal requires an explicit private QA root'
  }
  $sandbox=[IO.Path]::GetFullPath($env:TARAZ_QA_ROOT).TrimEnd('\')
  $expected=Join-Path $sandbox 'qa\qa-runtime\localappdata'
  if(-not [String]::Equals([IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\'),
       [IO.Path]::GetFullPath($expected).TrimEnd('\'),
       [StringComparison]::OrdinalIgnoreCase)) {
    Deny 'Rehearsal must use a disjoint private QA local application root'
  }
  if(($sandbox -notmatch '(?i)[\\/]qa[\\/]') -and
     ($sandbox -notmatch '(?i)[\\/]qa-[a-z0-9-]+$')) {
    Deny 'Private QA marker missing from rehearsal sandbox'
  }
  Safe $sandbox
  Safe $expected
  $realLocal=[Environment]::GetFolderPath('LocalApplicationData')
  if([String]::Equals([IO.Path]::GetFullPath($realLocal).TrimEnd('\'),
       [IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\'),
       [StringComparison]::OrdinalIgnoreCase)) {
    Deny 'Rehearsal must never target the real Windows profile'
  }
}
function Safe([string]$path) {
  if(-not (Test-Path -LiteralPath $path)) { Deny 'Required path missing' }
  $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
  while($null -ne $item) {
    if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      Deny 'Junction/symlink path refused'
    }
    $item=$item.Parent
  }
}
function Digest([string]$path) {
  Safe $path
  if(-not (Test-Path -LiteralPath $path -PathType Leaf)) { Deny 'Required file missing' }
  (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function NoTaraz {
  try {
    $procs=@(Get-CimInstance Win32_Process -ErrorAction Stop |
      Where-Object { $_.Name -match '^Taraz(?:-v[0-9.]+.*)?\.exe$' })
  } catch { Deny 'Could not check active Taraz processes' }
  $prefix=[IO.Path]::GetFullPath($root).TrimEnd('\') + '\'
  foreach($proc in $procs) {
    if([string]::IsNullOrWhiteSpace([string]$proc.ExecutablePath)) {
      Deny 'Taraz executable path is not inspectable'
    }
    $running=[IO.Path]::GetFullPath([string]$proc.ExecutablePath)
    if($running.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) {
      Deny 'Close the Taraz instance using the target installed directory'
    }
  }
}
if(-not $env:LOCALAPPDATA) { Deny 'LOCALAPPDATA missing' }
$root=Join-Path $env:LOCALAPPDATA 'Programs\Taraz'
$old=Join-Path $root 'versions\1.0.4\Taraz.exe'
$new=Join-Path $root 'versions\1.0.6\Taraz.exe'
$destination=Join-Path $root 'versions\1.0.6'
$pointer=Join-Path $root 'current-version.txt'
$launcher=Join-Path $root 'Run-Taraz.cmd'
$oldPointer=Join-Path $root 'current-version-pre-1.0.6.txt'
$pending=Join-Path $root 'current-version-1.0.6-pending.txt'
$activateBackup=Join-Path $root 'current-version-before-activation-1.0.6.txt'
$rollbackBackup=Join-Path $root 'current-version-before-rollback-1.0.6.txt'
Safe $root
NoTaraz
if((Digest $old) -ne '__BASE_EXE_SHA__') { Deny 'Installed 1.0.4 EXE differs' }
if((Digest $launcher) -ne '__LAUNCHER_SHA__') { Deny 'Launcher changed' }
'''

_PS_INSTALL = r'''$payload=Join-Path $PSScriptRoot 'Taraz.exe'
$manifestFile=Join-Path $PSScriptRoot 'update-manifest.json'
if((Digest $payload) -ne '__NEW_EXE_SHA__') { Deny 'Update payload changed' }
$manifest=Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
if($manifest.targetVersion -ne '1.0.6' -or $manifest.qaOnly -ne $false -or
   $manifest.exeSha256 -ne '__NEW_EXE_SHA__' -or
   $manifest.installedBaselineSha256 -ne '__BASE_EXE_SHA__') { Deny 'Manifest version or digest changed' }
if((Digest $pointer) -ne '__BASE_POINTER_SHA__' -or
   (Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.4') {
   Deny 'Current version is not pinned 1.0.4'
}
if(Test-Path -LiteralPath $destination) { Deny '1.0.6 directory exists; never overwrite' }
if(-not $Apply) { Write-Output 'BLOCKED_V106_INSTALL_AWAITING_DATA_GATES'; exit 0 }
if(-not $Rehearsal) {
  Deny 'Release hold: full profile backup, legacy migration, clone/rollback and Frozen AI acceptance are not approved'
}
RequireIsolatedRehearsal
$expected=Join-Path $destination 'Taraz.exe'
try {
  [IO.Directory]::CreateDirectory($destination) | Out-Null
  $bytes=[IO.File]::ReadAllBytes($payload)
  $stream=[IO.File]::Open($expected,[IO.FileMode]::CreateNew,
                         [IO.FileAccess]::Write,[IO.FileShare]::None)
  try {$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}
  finally {$stream.Dispose()}
  if((Digest $expected) -ne '__NEW_EXE_SHA__') { Deny 'Rehearsal EXE readback mismatch' }
  if((Digest $pointer) -ne '__BASE_POINTER_SHA__'){ Deny 'Rehearsal changed active version' }
  Write-Output 'REHEARSAL_V106_INSTALLED_NOT_ACTIVATED'
} catch { throw }
'''

_PS_ACTIVATE = r'''if((Digest $new) -ne '__NEW_EXE_SHA__') { Deny 'Installed 1.0.6 differs' }
if((Digest $pointer) -ne '__BASE_POINTER_SHA__' -or
   (Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.4'){
   Deny 'Expected active v1.0.4 pointer'
}
if(Test-Path -LiteralPath $oldPointer) { Deny 'Earlier activation backup exists' }
if(Test-Path -LiteralPath $pending) { Deny 'Pending activation pointer exists' }
if(Test-Path -LiteralPath $activateBackup) { Deny 'Earlier activation replacement backup exists' }
if(-not $Apply) { Write-Output 'BLOCKED_V106_ACTIVATION_AWAITING_DATA_GATES'; exit 0 }
if(-not $Rehearsal) {
  Deny 'Release hold: full profile backup, legacy migration, clone/rollback and Frozen AI acceptance are not approved'
}
RequireIsolatedRehearsal
$baseline=[IO.File]::ReadAllBytes($pointer)
$out=[IO.File]::Open($oldPointer,[IO.FileMode]::CreateNew,
                     [IO.FileAccess]::Write,[IO.FileShare]::None)
try {$out.Write($baseline,0,$baseline.Length);$out.Flush($true)}
finally {$out.Dispose()}
if((Digest $oldPointer) -ne '__BASE_POINTER_SHA__') { Deny 'Rehearsal old pointer backup differs' }
$bytes=[Text.Encoding]::ASCII.GetBytes("1.0.6`r`n")
$out=[IO.File]::Open($pending,[IO.FileMode]::CreateNew,
                     [IO.FileAccess]::Write,[IO.FileShare]::None)
try {$out.Write($bytes,0,$bytes.Length);$out.Flush($true)}
finally {$out.Dispose()}
if((Digest $pending) -ne '__ACTIVATED_POINTER_SHA__') { Deny 'Rehearsal new pointer hash differs' }
if((Digest $pointer) -ne '__BASE_POINTER_SHA__') { Deny 'Original pointer changed during rehearsal' }
 # The Windows .NET Framework File.Replace overload rejects null backup paths
 # on this target. Use a create-only known backup path and verify it afterwards.
[IO.File]::Replace($pending,$pointer,$activateBackup,$true)
if((Digest $pointer) -ne '__ACTIVATED_POINTER_SHA__') { Deny 'Rehearsal activation readback differs' }
if((Digest $activateBackup) -ne '__BASE_POINTER_SHA__') { Deny 'Rehearsal activation backup differs' }
Write-Output 'REHEARSAL_V106_ACTIVATED'
'''

_PS_ROLLBACK = r'''if((Digest $new) -ne '__NEW_EXE_SHA__'){ Deny 'Installed v1.0.6 changed' }
$active=(Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim()
if($active -eq '1.0.4'){
  if((Digest $pointer) -ne '__BASE_POINTER_SHA__') { Deny 'Unexpected v1.0.4 pointer bytes' }
  # An interrupted install before activation has NO oldPointer backup yet.
  # The original installed v1.0.4 is still active and must remain usable.
  if(Test-Path -LiteralPath $pending) { Deny 'Interrupted pending pointer needs review' }
  if((Test-Path -LiteralPath $oldPointer) -and
     (Digest $oldPointer) -ne '__BASE_POINTER_SHA__') {
    Deny 'Existing baseline backup mismatch'
  }
  Write-Output 'ALREADY_ROLLED_BACK_V104_NO_CHANGE'
  exit 0
}
if($active -ne '1.0.6'){ Deny 'Only active v1.0.6 can roll back' }
if((Digest $oldPointer) -ne '__BASE_POINTER_SHA__' -or
   (Get-Content -LiteralPath $oldPointer -Raw -Encoding UTF8).Trim() -ne '1.0.4') {
   Deny 'Original v1.0.4 pointer backup corrupt or missing'
}
if((Digest $pointer) -ne '__ACTIVATED_POINTER_SHA__'){ Deny 'Unrecognized active v1.0.6 pointer bytes' }
if(Test-Path -LiteralPath $pending){ Deny 'Pending activation or rollback exists' }
if(Test-Path -LiteralPath $rollbackBackup){ Deny 'Rollback backup already exists' }
if(-not $Apply){ Write-Output 'READY_V106_ROLLBACK_TO_V104'; exit 0 }
NoTaraz
$bytes=[IO.File]::ReadAllBytes($oldPointer)
$out=[IO.File]::Open($pending,[IO.FileMode]::CreateNew,
                     [IO.FileAccess]::Write,[IO.FileShare]::None)
try{$out.Write($bytes,0,$bytes.Length);$out.Flush($true)}
finally{$out.Dispose()}
if((Digest $pending) -ne '__BASE_POINTER_SHA__') { Deny 'Staged rollback SHA mismatch' }
if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim() -ne '1.0.6') {
  Deny 'Pointer changed during rollback'
}
[IO.File]::Replace($pending,$pointer,$rollbackBackup,$true)
if((Digest $pointer) -ne '__BASE_POINTER_SHA__' -or
   (Get-Content -LiteralPath $rollbackBackup -Raw -Encoding UTF8).Trim() -ne '1.0.6'){
   Deny 'Rollback readback mismatch'
}
Write-Output 'ROLLED_BACK_V104_BOTH_BINARIES_RETAINED'
'''


def render_scripts(exe_sha: str, *, base_sha: str = BASE_EXE_SHA,
                   pointer_sha: str = BASE_POINTER_SHA,
                   launcher_sha: str = LAUNCHER_SHA) -> dict[str, str]:
    for value in (exe_sha, base_sha, pointer_sha, launcher_sha):
        if re.fullmatch(r"[0-9a-f]{64}", value or "") is None:
            raise BuildBlocked("Install scripts require SHA-pinned lower-case digests")
    substitutions = {"__NEW_EXE_SHA__": exe_sha, "__BASE_EXE_SHA__": base_sha,
                     "__BASE_POINTER_SHA__": pointer_sha, "__LAUNCHER_SHA__": launcher_sha,
                     "__ACTIVATED_POINTER_SHA__": ACTIVATED_POINTER_SHA}
    result = {}
    for filename, tail in (
        ("Install-Taraz-V106.ps1", _PS_INSTALL),
        ("Activate-Taraz-V106.ps1", _PS_ACTIVATE),
        ("Rollback-Taraz-V106.ps1", _PS_ROLLBACK),
    ):
        body = _PS_HEADER + tail
        for key, value in substitutions.items():
            body = body.replace(key, value)
        if any(key in body for key in substitutions):
            raise BuildBlocked("PowerShell has unresolved SHA placeholder")
        result[filename] = body
    return result


def package(run: Path, exe: Path, files: dict, staged: dict,
            inspected: dict, baseline: dict) -> dict:
    folder = run / "offline-update"
    folder.mkdir(exist_ok=False)
    payload = folder / "Taraz.exe"
    with exe.open("rb") as source, payload.open("xb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
    exe_sha = sha(exe)
    if sha(payload) != exe_sha:
        raise BuildBlocked("Copied frozen candidate differs from compiled EXE")
    for name, body in render_scripts(exe_sha).items():
        with (folder / name).open("x", encoding="utf-8", newline="\n") as file:
            file.write(body)
    for name in ("package.json", "package-lock.json"):
        with (run / "source" / name).open("rb") as src, (folder / name).open("xb") as dst:
            shutil.copyfileobj(src, dst)
    inventory_file = folder / "source-sha256.json"
    inventory_file.write_text(json.dumps(files, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schemaVersion": 1, "application": "Taraz", "targetVersion": VERSION,
        "installedBaselineVersion": BASE_VERSION, "installedBaselineSha256": BASE_EXE_SHA,
        "installedBaseline": baseline, "qaOnly": False,
        "productionCandidate": True, "releaseGateStatus": "BLOCKED_DATA_PRESERVATION",
        "installApplyAllowed": False, "activateApplyAllowed": False,
        "installed": False, "pointerActivated": False,
        "defaultDataRoot": "%APPDATA%\\Taraz", "previousVersionRetained": BASE_VERSION,
        "exeSha256": exe_sha, "exeBytes": exe.stat().st_size, "peVersion": "1.0.6.0",
        "sourceFingerprintSha256": digest_inventory(files), "sourceFilesCount": len(files),
        "sourceManifestSha256": sha(inventory_file), "stagedSourceSha256": staged,
        "compiledEvidence": inspected, "installedGuiTested": False,
        "orderPostingAutomaticallyEnabled": False,
        "installerSha256": sha(folder / "Install-Taraz-V106.ps1"),
        "activatorSha256": sha(folder / "Activate-Taraz-V106.ps1"),
        "rollbackSha256": sha(folder / "Rollback-Taraz-V106.ps1"),
    }
    manifest_file = folder / "update-manifest.json"
    manifest_file.write_text(json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    members = {"Taraz.exe", "package.json", "package-lock.json", "source-sha256.json",
               "update-manifest.json", "Install-Taraz-V106.ps1",
               "Activate-Taraz-V106.ps1", "Rollback-Taraz-V106.ps1"}
    if {file.name for file in folder.iterdir()} != members:
        raise BuildBlocked("Unexpected offline package member set")
    zip_path = run / "Taraz-v1.0.6-AAAS-OFFLINE-UPDATE.zip"
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for member in sorted(folder.iterdir()):
            z.write(member, member.name)
    member_sha = {item.name: sha(item) for item in folder.iterdir()}
    with zipfile.ZipFile(zip_path) as z:
        if len(z.infolist()) != len(members) or set(z.namelist()) != members:
            raise BuildBlocked("ZIP count/names differ from approved set")
        for item in z.infolist():
            if item.is_dir() or hashlib.sha256(z.read(item.filename)).hexdigest() != member_sha[item.filename]:
                raise BuildBlocked("Offline ZIP member digest differs")
    return {"exe": str(exe), "exeSha256": exe_sha, "zip": str(zip_path),
            "zipSha256": sha(zip_path), "manifest": str(manifest_file),
            "manifestSha256": sha(manifest_file),
            "memberSha256": dict(sorted(member_sha.items())),
            "installScript": str(folder / "Install-Taraz-V106.ps1"),
            "activationScript": str(folder / "Activate-Taraz-V106.ps1"),
            "rollbackScript": str(folder / "Rollback-Taraz-V106.ps1")}


def build(*, freeze_sha: str) -> Path:
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise BuildBlocked("Requires native Windows Python 3.12")
    if re.fullmatch(r"[0-9a-f]{64}", freeze_sha or "") is None:
        raise BuildBlocked("Prime-approved exact source-freeze SHA required")
    expected = source_inventory()
    if digest_inventory(expected) != freeze_sha:
        raise BuildBlocked("Runtime source differs from frozen post-worker27 SHA")
    baseline = installed_baseline()
    legacy.refuse_links(OUTPUT.parent)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    run = OUTPUT / ("build-" + uuid.uuid4().hex[:12])
    run.mkdir(exist_ok=False)
    report = {"status": "IN_PROGRESS", "version": VERSION, "installed": False,
              "sourceFreezeSha256": freeze_sha, "sourceFilesCount": len(expected),
              "pointerChanged": False, "realLedgerModified": False, "output": str(run)}
    report_file = run / "build-report.json"
    try:
        snapshot = run / "source"
        legacy.snapshot_source(ROOT, snapshot, expected)
        staged = stage_version(snapshot)
        from scripts.qa_mtr_taraz_build_20261110 import _trusted_modules, _safe_copytree
        _safe_copytree(_trusted_modules(), snapshot / "node_modules")
        env = legacy.offline_environment(run)
        dist = run / "web" / "dist"
        dist.parent.mkdir()
        legacy.run_command(
            [shutil.which("node") or "node", str(snapshot / "node_modules/vite/bin/vite.js"),
             "build", "--config", str(snapshot / "vite.config.js"),
             "--outDir", str(dist), "--emptyOutDir"], cwd=snapshot, env=env,
            log=run / "vite-build.log", timeout=300)
        if not (dist / "accounting.html").is_file():
            raise BuildBlocked("Vite did not produce accounting.html")
        resource = run / "taraz-v106-pe-version.txt"
        pe_resource(resource)
        bin_dir = run / "binary"
        bin_dir.mkdir()
        legacy.run_command(
            [sys.executable, "-B", "-m", "PyInstaller", "--onefile", "--windowed",
             "--noconfirm", "--version-file", str(resource), "--name", "Taraz",
             "--hidden-import", "taraz_order_store",
             "--hidden-import", "taraz_aaas_agent",
             "--hidden-import", "taraz_madar_order_link",
             "--hidden-import", "taraz_madar_order_sync",
             "--hidden-import", "taraz_ecosystem_protocol",
             "--hidden-import", "taraz_ecosystem_outbox",
             "--hidden-import", "taraz_repository_contracts",
             "--hidden-import", "taraz_ai_provider_status",
             "--hidden-import", "taraz_ai_chat_store",
             "--hidden-import", "taraz_ai_business_service",
             "--hidden-import", "taraz_ai_invoice_intake",
             "--hidden-import", "standalone_accounting_identity",
             "--hidden-import", "standalone_accounting_company_registry",
             "--hidden-import", "standalone_accounting_secure_login",
             "--hidden-import", "taraz_legacy_workspace_bridge",
             "--hidden-import", "taraz_legacy_ownership_enrollment",
             "--hidden-import", "taraz_legacy_enrollment_dialog",
             "--hidden-import", "taraz_fresh_windows_workspace",
             "--hidden-import", "taraz_llm_order_suggest",
             "--hidden-import", "taraz_llm_print_suggest",
             "--hidden-import", "taraz_madar_data_reader",
             "--hidden-import", "standalone_accounting_template_store",
             "--hidden-import", "taraz_integration",
             "--hidden-import", "personal_parsian_bridge",
             "--hidden-import", "standalone_accounting_auto_backup",
             "--icon", str(snapshot / "assets/taraz.ico"),
             "--add-data", str(dist) + ";dist", "--distpath", str(bin_dir),
             "--workpath", str(run / "pyinstaller/work"),
             "--specpath", str(run / "pyinstaller/spec"),
             "--paths", str(snapshot), str(snapshot / "taraz_desktop.py")],
            cwd=snapshot, env=env, log=run / "pyinstaller-build.log", timeout=900)
        exe = bin_dir / "Taraz.exe"
        inspected = inspect_exe(exe, dist)
        if digest_inventory(source_inventory()) != freeze_sha:
            raise BuildBlocked("Source changed during v106 native build")
        if installed_baseline() != baseline:
            raise BuildBlocked("Installed 1.0.4 changed during native build")
        artifacts = package(run, exe, expected, staged, inspected, baseline)
        report.update({"status": "V106_AAAS_NON_QA_BUILT_NOT_INSTALLED",
                       "compiled": inspected, "baseline": baseline, **artifacts})
    except Exception as exc:
        report.update({"status": "BLOCKED", "errorType": type(exc).__name__,
                       "error": str(exc)})
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        raise
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return report_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fingerprint", action="store_true", help="Read-only runtime source SHA, not authorization")
    parser.add_argument("--build", action="store_true", help="Build after worker27/prime frozen-source approval")
    parser.add_argument("--freeze-sha", default="")
    args = parser.parse_args()
    try:
        if args.fingerprint:
            files = source_inventory()
            print(json.dumps({"sourceFilesCount": len(files), "sourceSha256": digest_inventory(files)}))
        elif args.build:
            path = build(freeze_sha=args.freeze_sha)
            report = json.loads(path.read_text(encoding="utf-8"))
            print(json.dumps({name: report[name] for name in (
                "status", "output", "exeSha256", "zipSha256", "manifestSha256")},
                indent=2))
        else:
            print(json.dumps({"installedBaseline": installed_baseline(),
                              "candidateBuilt": False, "sourceSnapshotTaken": False}, indent=2))
        return 0
    except Exception as exc:
        print("V106 AaaS BUILD BLOCKED: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
