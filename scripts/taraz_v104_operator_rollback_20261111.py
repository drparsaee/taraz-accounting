"""RC3-pinned v1.0.4 -> v1.0.2 operator-only rollback generator (NOT installer).

Requires byte-exact immutable RC3 build and checked actual v104 activation
contract before a NEW create-only rollback output can be generated. Does not
execute the rollback or mutate installed Taraz, launcher, or finance data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
OUTPUT_ROOT = SOURCE.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.4-p1"
V102_EXE_SHA256 = "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52"
SCRIPT_NAME = "Rollback-Taraz-V104-To-V102.ps1"

# Actual RC3 independent pinned evidence supplied by prime / worker26, then
# rehashed against offline-update files. Never use rejected RC1 hashes.
WORKER26_PINSET = {
    "runDirectory": "build-0bde36e11d99",
    "v104ExeSha256": "9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce",
    "offlineManifestSha256": "b6ac2e3050274e3ec8e3bcaaf32b694d673b1747cfab580245136ec500e65bc6",
    "buildReportSha256": "510de237a7fcea8553e0a64951bf76f3f7bef722318585db016d4e602df8b9fb",
    "sourceFreezeSha256": "e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de",
    "buildReportStatus": "PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED",
    "activationPointerBackupName": "current-version-pre-1.0.4.txt",
    "activationLauncherBackupName": "Run-Taraz-pre-1.0.4.cmd",
    "activeLauncherSha256": "93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21",
    "backupLauncherSha256": "93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21",
    "launcherV102Compatible": True,
}
RC3_ZIP_SHA256 = "1a9ca13c914385c92be68ffdd2034c723843dde1846fa548762864aa98ac134e"
RC3_ACTIVATION_SHA256 = "3d7cb9aea21e54864fd8215ee686c48245c1b76f032afefe455c6782f3957937"
RC3_INSTALLER_SHA256 = "6dda4897c1ce4da9120d3e6fda9c639834080f838602de02e32eea46c3de6a68"
RC3_ZIP_NAME = "Taraz-v1.0.4-P1-RC3-SECURE-OFFLINE-UPDATE.zip"


class RollbackBlocked(RuntimeError):
    """An unproven contract is never translated into a runnable rollback."""


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def local_regular(path: Path, *, require_file: bool = False) -> None:
    if not path.is_absolute():
        raise RollbackBlocked("Non-absolute path")
    for component in (path, *path.parents):
        if component.is_symlink() or (component.exists() and
            getattr(component.lstat(), "st_file_attributes", 0) & 0x400):
            raise RollbackBlocked("Symlink/junction/reparse refused: " + str(component))
    if require_file:
        if not path.is_file() or path.stat().st_nlink != 1:
            raise RollbackBlocked("Missing/non-regular/hardlinked artifact: " + str(path))


def _hash64(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _name(value: object) -> bool:
    return (isinstance(value, str) and
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,110}", value) is not None and
        value not in {".", ".."})


def validate_pinset(pins: dict) -> dict:
    """Independent worker26 pins must exist *before* any output is made."""
    if set(pins) != set(WORKER26_PINSET):
        raise RollbackBlocked("Worker26 pinset keys missing/unknown")
    if not _name(pins["runDirectory"]) or not pins["runDirectory"].startswith("build-"):
        raise RollbackBlocked("Worker26 immutable v1.0.4 build run not pinned")
    for key in ("v104ExeSha256", "offlineManifestSha256", "buildReportSha256",
                "sourceFreezeSha256", "activeLauncherSha256", "backupLauncherSha256"):
        if not _hash64(pins[key]):
            raise RollbackBlocked("Worker26 must supply independently verified " + key)
    for key in ("activationPointerBackupName", "activationLauncherBackupName"):
        if not _name(pins[key]):
            raise RollbackBlocked("Worker26 activation contract missing " + key)
    if (pins["activationPointerBackupName"] != "current-version-pre-1.0.4.txt" or
        pins["activationLauncherBackupName"] not in
            ("Run-Taraz-pre-1.0.4.cmd", "Run-Taraz-pre-activation-1.0.4.cmd")):
        raise RollbackBlocked("Activation backup names are not reviewed; coordinate with worker26")
    if pins["buildReportStatus"] != "PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED":
        raise RollbackBlocked("Verified build status contract not agreed")
    if pins["launcherV102Compatible"] is not True:
        raise RollbackBlocked("Worker26 did not attest existing launcher is v1.0.2-compatible")
    return dict(pins)


def immutable_release_preflight(pins: dict | None = None) -> dict:
    """Check *frozen* release artifacts only, never real installed profiles."""
    if os.name != "nt":
        raise RollbackBlocked("Windows required")
    verified = validate_pinset(WORKER26_PINSET if pins is None else pins)
    run = OUTPUT_ROOT / verified["runDirectory"]
    exe = run / "offline-update" / "Taraz.exe"
    manifest_path = run / "offline-update" / "update-manifest.json"
    report_path = run / "build-report.json"
    activation_path = run / "offline-update" / "Activate-Taraz-V104.ps1"
    installer_path = run / "offline-update" / "Install-Taraz-V104.ps1"
    zip_path = run / RC3_ZIP_NAME
    binary_path = run / "binary" / "Taraz.exe"
    for path in (OUTPUT_ROOT, run, exe, manifest_path, report_path,
                 activation_path, installer_path, zip_path, binary_path):
        local_regular(path, require_file=path in (exe, manifest_path, report_path,
                                                 activation_path, installer_path, zip_path, binary_path))
    actual = {key: digest(path) for key, path in (
        ("v104ExeSha256", exe), ("offlineManifestSha256", manifest_path),
        ("buildReportSha256", report_path))}
    if any(actual[key] != verified[key] for key in actual):
        raise RollbackBlocked("Frozen v104 release artifact hash != worker26 pinned manifest")
    if (digest(zip_path) != RC3_ZIP_SHA256 or
            digest(activation_path) != RC3_ACTIVATION_SHA256 or
            digest(installer_path) != RC3_INSTALLER_SHA256 or
            digest(binary_path) != verified["v104ExeSha256"]):
        raise RollbackBlocked("RC3 binary/ZIP/activation/installer SHA changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (manifest.get("targetVersion") != "1.0.4"
        or manifest.get("peVersion") != "1.0.4.0"
        or manifest.get("installedBaselineVersion") != "1.0.2"
        or manifest.get("installedBaselineSha256") != V102_EXE_SHA256
        or manifest.get("exeSha256") != verified["v104ExeSha256"]
        or manifest.get("sourceSnapshotSha256") != verified["sourceFreezeSha256"]
        or manifest.get("releaseCandidateRevision") != "RC3"
        or manifest.get("activationScriptSha256") != RC3_ACTIVATION_SHA256
        or manifest.get("installScriptSha256") != RC3_INSTALLER_SHA256
        or manifest.get("installed") is not False
        or manifest.get("pointerActivated") is not False
        or report.get("status") != verified["buildReportStatus"]
        or report.get("releaseCandidateRevision") != "RC3"
        or report.get("zipSha256") != RC3_ZIP_SHA256
        or report.get("activationScriptSha256") != RC3_ACTIVATION_SHA256
        or report.get("installScriptSha256") != RC3_INSTALLER_SHA256
        or report.get("installed") is not False
        or report.get("exeSha256") != verified["v104ExeSha256"]
        or report.get("sourceFreezeSha256") != verified["sourceFreezeSha256"]):
        raise RollbackBlocked("Release manifest/report semantic contract mismatch")
    # Actual RC3 contract: secureRepackage points to the launcher backup,
    # activation PS1 creates that backup byte-exact before File.Replace.
    # The prior proposal expected a fictitious activationBackupContract object;
    # deliberately use real RC3 immutable schema instead.
    secure = manifest.get("secureRepackage")
    baseline = manifest.get("installedBaseline")
    if (not isinstance(secure, dict) or
            secure.get("launcherBackupName") != verified["activationLauncherBackupName"] or
            secure.get("hardlinkAndAncestorGuard") != "Win32-linkcount-and-each-ancestor" or
            secure.get("rollbackIncluded") is not False or
            not isinstance(baseline, dict) or
            baseline.get("launcherSha256") != verified["activeLauncherSha256"] or
            report.get("baseline", {}).get("launcherSha256") != verified["activeLauncherSha256"] or
            verified["backupLauncherSha256"] != verified["activeLauncherSha256"]):
        raise RollbackBlocked("RC3 immutable launcher/backup contract mismatch")
    activation = activation_path.read_text(encoding="utf-8-sig")
    checked = (
        "$oldPointer=Join-Path $root 'current-version-pre-1.0.4.txt'",
        "$launcherBackup=Join-Path $root 'Run-Taraz-pre-1.0.4.cmd'",
        "RequireAbsent $launcherBackup",
        "[IO.FileMode]::CreateNew",
        "if((Digest $launcherBackup) -cne $launcherDigest)",
        "[IO.File]::Replace($pending,$pointer,$oldPointer,$true)",
        "(Digest $launcherBackup) -cne $launcherDigest",
        "CheckBackup $BackupRoot $BackupManifestSha256 $BackupReportSha256",
    )
    if any(anchor not in activation for anchor in checked):
        raise RollbackBlocked("RC3 activation backup/atomic-promotion ABI mismatch")
    # This launcher was independently read from the installed v102 baseline;
    # it uses the versioned pointer unchanged, so is v102 compatible.
    previous_launcher = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz" / "Run-Taraz.cmd"
    local_regular(previous_launcher, require_file=True)
    if digest(previous_launcher) != verified["activeLauncherSha256"]:
        raise RollbackBlocked("Read-only original installed launcher SHA mismatch")
    old_launcher_content = previous_launcher.read_text(encoding="utf-8-sig")
    if ('versions\\%TARAZ_VERSION%\\Taraz.exe' not in old_launcher_content or
            'current-version.txt' not in old_launcher_content):
        raise RollbackBlocked("Existing v102 launcher is not pointer-compatible")
    return {"run": str(run), "exeSha256": verified["v104ExeSha256"],
            "manifestSha256": verified["offlineManifestSha256"],
            "reportSha256": verified["buildReportSha256"],
            "zipSha256": RC3_ZIP_SHA256,
            "activationScriptSha256": RC3_ACTIVATION_SHA256,
            "sourceSha256": verified["sourceFreezeSha256"],
            "previousExeSha256": V102_EXE_SHA256,
            "activationPointerBackup": verified["activationPointerBackupName"],
            "activationLauncherBackup": verified["activationLauncherBackupName"],
            "activeLauncherSha256": verified["activeLauncherSha256"],
            "backupLauncherSha256": verified["backupLauncherSha256"],
            "launcherV102Compatible": True}


def operator_script(pins: dict) -> str:
    """Reuse worker29's hardlink/ACL/atomic gate; only stricter v104 additions."""
    validated = validate_pinset(pins)
    from scripts import taraz_v103_operator_rollback_20261111 as v103
    text = v103._PS_TEMPLATE
    # All 1.0.3 mentions are version-specific (including backup labels).
    text = text.replace("1.0.3", "1.0.4")
    text = text.replace("CheckVersion $new 3", "CheckVersion $new 4")
    text = text.replace("TARAZ 1.0.3 ROLLBACK BLOCKED", "TARAZ 1.0.4 ROLLBACK BLOCKED")
    text = text.replace("current-version-pre-1.0.4.txt", "__ACTIVATION_POINTER_BACKUP__")
    original_backup = "$activationBackup=Join-Path $root '__ACTIVATION_POINTER_BACKUP__'"
    if original_backup not in text:
        raise RollbackBlocked("Unexpected inherited v103 activation pointer template")
    insert = (original_backup + "\n"
        "$launcherBackup=Join-Path $root '__ACTIVATION_LAUNCHER_BACKUP__'")
    text = text.replace(original_backup, insert, 1)
    requirements = (
        ("$launcher,$activationBackup)) { SafeExisting $path }",
         "$launcher,$activationBackup,$launcherBackup)) { SafeExisting $path }"),
        ("$launcher,$activationBackup)) {",
         "$launcher,$activationBackup,$launcherBackup)) {"),
        ("  if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim()",
         "  if((Digest $launcher) -cne '__ACTIVE_LAUNCHER_SHA__' -or\n"
         "     (Digest $launcherBackup) -cne '__BACKUP_LAUNCHER_SHA__') {\n"
         "    Deny 'Current launcher or activation launcher backup changed'\n"
         "  }\n"
         "  if((Get-Content -LiteralPath $pointer -Raw -Encoding UTF8).Trim()"),
    )
    for before, after in requirements:
        if before not in text:
            raise RollbackBlocked("Unexpected inherited v103 safety gate anchor")
        text = text.replace(before, after)
    # For ordinary preflight and immediately before File.Replace, require
    # both known launcher hashes. Neither launcher file is ever rewritten.
    text = text.replace(
        "  if((Digest $old) -cne '__OLD_SHA__' -or (Digest $new) -cne '__NEW_SHA__') {",
        "  if((Digest $launcher) -cne '__ACTIVE_LAUNCHER_SHA__' -or\n"
        "     (Digest $launcherBackup) -cne '__BACKUP_LAUNCHER_SHA__') {\n"
        "    Deny 'Launcher or launcher backup changed during pointer switch'\n"
        "  }\n"
        "  if((Digest $old) -cne '__OLD_SHA__' -or (Digest $new) -cne '__NEW_SHA__') {")
    pins_to_replace = {
        "__OLD_SHA__": V102_EXE_SHA256,
        "__NEW_SHA__": validated["v104ExeSha256"],
        "__ACTIVATION_POINTER_BACKUP__": validated["activationPointerBackupName"],
        "__ACTIVATION_LAUNCHER_BACKUP__": validated["activationLauncherBackupName"],
        "__ACTIVE_LAUNCHER_SHA__": validated["activeLauncherSha256"],
        "__BACKUP_LAUNCHER_SHA__": validated["backupLauncherSha256"],
    }
    for name, value in pins_to_replace.items():
        text = text.replace(name, value)
    if "__" in text or "CheckVersion $new 3" in text:
        raise RollbackBlocked("Unresolved template substitutions")
    if ("[IO.File]::Replace($pending,$pointer,$rollbackBackup,$true)" not in text or
        "param([switch]$Apply)" not in text or "CheckSingleHardlink" not in text or
        "CheckWriteRights" not in text or "CheckNoTaraz" not in text):
        raise RollbackBlocked("Missing verified operator safety gate")
    return text


def generate() -> Path:
    pins = WORKER26_PINSET
    metadata = immutable_release_preflight(pins)
    script_source = operator_script(pins)
    local_regular(OUTPUT_ROOT)
    if not OUTPUT_ROOT.is_dir():
        raise RollbackBlocked("v104 output root missing")
    output = OUTPUT_ROOT / ("rollback-gate-" + uuid.uuid4().hex[:12])
    local_regular(output)
    output.mkdir(exist_ok=False)
    script_path = output / SCRIPT_NAME
    with script_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(script_source)
    gate = {"schemaVersion": 1, "application": "Taraz", "operatorOnly": True,
            "status": "OPERATOR_ROLLBACK_GENERATED_NOT_EXECUTED",
            "fromVersion": "1.0.4", "toVersion": "1.0.2",
            "rollbackExecuted": False, "productionTouched": False,
            "requiresApply": True, "script": SCRIPT_NAME,
            "scriptSha256": digest(script_path), "releasePinset": metadata,
            "retainsBothBinaries": True, "launcherMutation": False}
    manifest = output / "rollback-gate-manifest.json"
    with manifest.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(gate, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    if digest(script_path) != gate["scriptSha256"]:
        raise RollbackBlocked("New generated PS1 readback changed")
    return manifest


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--preflight", action="store_true")
    cli.add_argument("--generate", action="store_true")
    args = cli.parse_args()
    try:
        if args.preflight:
            print(json.dumps(immutable_release_preflight(), ensure_ascii=False, indent=2))
        elif args.generate:
            manifest = generate()
            print(json.dumps({"status": "OPERATOR_ROLLBACK_GENERATED_NOT_EXECUTED",
                              "manifest": str(manifest), "manifestSha256": digest(manifest)},
                              ensure_ascii=False))
        else:
            cli.print_help()
        return 0
    except Exception as error:
        print("V104 ROLLBACK GATE BLOCKED: " + type(error).__name__ + ": " + str(error),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
