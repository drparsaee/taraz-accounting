"""Bounded Taraz real-data snapshot + disposable Inno install acceptance.

The owner has authorized an upgrade conditional on proof of recoverability.
This independent verifier never edits the production launcher, production
program, accounts or ledgers; the existing v1.0.1 is QA-locked, so a production
upgrade must stay BLOCKED. Snapshot data remain offline under a private ACL.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True

SOURCE = Path(__file__).resolve().parents[1]
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
OUT = SOURCE.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.1-upgrade-acceptance"
BACKUP_PARENT = SOURCE.parents[1] / "MTR-REAL-UPGRADE-BACKUPS-20261110"
QA_RUN = SOURCE.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.1-inno-qa" / "compile-45ac591be1f7"
EXPECTED_SETUP_SHA = "8f12cbd6e3d4d0896732c0627179eec285b7ef52b1d680f663dc4e788c6cb822"
EXPECTED_BINARY_SHA = "4a409be0b464b93f593b39e527162db43ffc3dbadfc15a2e0fde3a511326bf16"
EXPECTED_INSTALLED_SHA = "de5005579039bd86890c1dca1f5f1d9c760e6c47579a42f649f80096f158e70c"
MAX_TOTAL_BYTES = 300 * 1024 * 1024
MAX_SINGLE_BYTES = 100 * 1024 * 1024
MAX_FILE_COUNT = 1000


class AcceptanceBlocked(RuntimeError):
    pass


def sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def assert_regular(path: Path, *, directory: bool = False) -> None:
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and bool(
                getattr(item.lstat(), "st_file_attributes", 0) & 0x400)):
            raise AcceptanceBlocked("Linked/junction path refused: " + str(item))
    if directory:
        if not path.is_dir():
            raise AcceptanceBlocked("Required directory missing")
    elif not path.is_file() or not stat.S_ISREG(path.lstat().st_mode):
        raise AcceptanceBlocked("Expected regular file unavailable")


def installed_baseline(local: Path, *, expected_sha: str = EXPECTED_INSTALLED_SHA) -> dict:
    root = local / "Programs" / "Taraz"
    pointer = root / "current-version.txt"
    launcher = root / "Run-Taraz.cmd"
    exe = root / "versions" / "1.0.0" / "Taraz.exe"
    for entry in (root, pointer, launcher, exe):
        assert_regular(entry, directory=entry == root)
    raw_version = pointer.read_text(encoding="utf-8-sig").strip()
    content = launcher.read_text(encoding="utf-8", errors="replace")
    if raw_version != "1.0.0" or "current-version.txt" not in content or \
            "versions\\%TARAZ_VERSION%\\Taraz.exe" not in content:
        raise AcceptanceBlocked("Installed baseline launcher/pointer changed")
    if sha(exe) != expected_sha:
        raise AcceptanceBlocked("Installed Taraz 1.0.0 digest differs from pinned baseline")
    return {"version": raw_version, "exeSha256": expected_sha,
            "launcherSha256": sha(launcher), "pointerSha256": sha(pointer),
            "exeBytes": exe.stat().st_size, "root": str(root)}


def no_active_taraz() -> None:
    """Local tasklist only; production Taraz process must be fully absent."""
    if os.name != "nt":
        raise AcceptanceBlocked("Windows-specific acceptance required")
    result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=20, check=False)
    if result.returncode:
        raise AcceptanceBlocked("Cannot establish process inactivity")
    names = [row[0].lower() for row in csv.reader(io.StringIO(result.stdout)) if row]
    if any(name == "taraz.exe" or name.startswith("taraz-v1.0.1-") for name in names):
        raise AcceptanceBlocked("A Taraz process is running")


def real_profile_roots(appdata: Path, local: Path) -> dict[str, Path]:
    return {"roaming": appdata / "Taraz",
            "local": local / "Taraz",
            "bridge": local / "Madar-Taraz-Bridge"}


def inventory(roots: dict[str, Path]) -> dict[str, dict]:
    """Fail closed on reparse points, new/removed files or excessive size."""
    result = {}
    total = 0
    for prefix, directory in roots.items():
        if not re.fullmatch(r"[a-z]{3,16}", prefix):
            raise AcceptanceBlocked("Invalid backup root label")
        assert_regular(directory, directory=True)
        for base, folders, names in os.walk(directory, followlinks=False):
            for folder in folders:
                assert_regular(Path(base) / folder, directory=True)
            for name in names:
                file = Path(base) / name
                assert_regular(file)
                relative = file.relative_to(directory).as_posix()
                if relative in ("", ".", "..") or ".." in Path(relative).parts:
                    raise AcceptanceBlocked("Unsafe relative file name")
                entry = file.stat()
                if file.name.lower().endswith(".sqlite3-wal") and entry.st_size != 0:
                    raise AcceptanceBlocked("Nonempty WAL requires separate SQLite backup checkpoint procedure")
                total += entry.st_size
                if (entry.st_size > MAX_SINGLE_BYTES or total > MAX_TOTAL_BYTES
                        or len(result) >= MAX_FILE_COUNT):
                    raise AcceptanceBlocked("Profile exceeds approved backup budget")
                result[f"{prefix}/{relative}"] = {
                    "bytes": entry.st_size, "mtimeNs": entry.st_mtime_ns,
                    "sha256": sha(file), "source": str(file)}
    if "roaming/standalone-accounting.sqlite3" not in result:
        raise AcceptanceBlocked("Accounting book absent from backup inventory")
    return dict(sorted(result.items()))


def secure_private_directory(path: Path) -> None:
    """Require a private Windows DACL BEFORE writing any financial data."""
    path.mkdir(parents=True, exist_ok=False)
    assert_regular(path, directory=True)
    username = os.environ.get("USERNAME")
    domain = os.environ.get("USERDOMAIN")
    if not username or not domain:
        raise AcceptanceBlocked("Windows user identity unavailable for private backup")
    principal = f"{domain}\\{username}"
    result = subprocess.run(["icacls", str(path), "/inheritance:r",
                             "/grant:r", principal + ":(OI)(CI)F", "SYSTEM:(OI)(CI)F"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=20, check=False)
    if result.returncode:
        raise AcceptanceBlocked("Could not restrict financial backup directory ACL")
    acl = subprocess.run(["icacls", str(path)], capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=20)
    if (acl.returncode or principal.casefold() not in acl.stdout.casefold()
            or "Everyone:(" in acl.stdout or "BUILTIN\\Users:(" in acl.stdout):
        raise AcceptanceBlocked("Private backup ACL could not be independently read back")


def source_from_entry(roots: dict[str, Path], name: str) -> Path:
    prefix, sep, tail = name.partition("/")
    if not sep or prefix not in roots or not tail or ".." in Path(tail).parts:
        raise AcceptanceBlocked("Unsafe inventory key")
    return roots[prefix] / Path(tail)


def sqlite_checks(copy_root: Path, manifest: dict[str, dict]) -> dict:
    """Inspect copied databases only; no connection to a live real-data file."""
    results = {}
    for name in manifest:
        if not name.lower().endswith(".sqlite3"):
            continue
        file = copy_root / name
        # Each source has been quiesced and copied with sidecars. Validate the
        # copy in query-only mode; any damaged historical backup blocks release.
        # Nonempty WAL was refused during inventory. `immutable` is critical:
        # SQLite must never create/update even a sidecar within the copied set.
        connection = sqlite3.connect(file.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=10)
        try:
            connection.execute("PRAGMA query_only=ON")
            verdict = connection.execute("PRAGMA integrity_check").fetchall()
            if verdict != [("ok",)]:
                raise AcceptanceBlocked("Copied SQLite integrity_check failed: " + name)
            results[name] = {"integrityCheck": "ok",
                             "schemaVersion": int(connection.execute("PRAGMA user_version").fetchone()[0])}
        finally:
            connection.close()
    if "roaming/standalone-accounting.sqlite3" not in results:
        raise AcceptanceBlocked("Main ledger not independently inspected")
    return results


def verified_backup(roots: dict[str, Path], dest: Path) -> dict:
    """Create-only full profile copy; confirm both sources and copies by SHA."""
    before = inventory(roots)
    secure_private_directory(dest)
    copies = dest / "files"
    copies.mkdir(exist_ok=False)
    for name, item in before.items():
        origin = source_from_entry(roots, name)
        target = copies / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with origin.open("rb") as source_stream, target.open("xb") as output:
            shutil.copyfileobj(source_stream, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if target.stat().st_size != item["bytes"] or sha(target) != item["sha256"]:
            raise AcceptanceBlocked("Backup byte readback mismatch: " + name)
    after = inventory(roots)
    if after != before:
        raise AcceptanceBlocked("Real profile changed during backup; snapshot is not coherent")
    # Manifest carries no personally identifying account contents; file names
    # stay inside the ACL-protected snapshot and are not printed to stdout.
    metadata = {name: {key: value for key, value in entry.items() if key != "source"}
                for name, entry in before.items()}
    check = sqlite_checks(copies, metadata)
    # File set may not change during verification.
    if inventory(roots) != before:
        raise AcceptanceBlocked("Live profile changed during backup verification")
    snapshot = {"schemaVersion": 1, "sourceCategory": "offline-Taraz-user-data",
                "verifiedNoOverwrite": True, "allFilesIncluded": True,
                "fileCount": len(metadata),
                "totalBytes": sum(value["bytes"] for value in metadata.values()),
                "files": metadata, "sqliteChecks": check}
    manifest_path = dest / "snapshot-manifest.json"
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(snapshot, stream, sort_keys=True, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    independently_verify_backup(dest, roots)
    return {"fileCount": len(metadata), "totalBytes": snapshot["totalBytes"],
            "sqliteValidatedCount": len(check), "manifestSha256": sha(manifest_path),
            "backupRoot": str(dest), "independentReadback": True}


def independently_verify_backup(dest: Path, roots: dict[str, Path] | None = None) -> None:
    manifest_file = dest / "snapshot-manifest.json"
    assert_regular(manifest_file)
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1 or data.get("verifiedNoOverwrite") is not True:
        raise AcceptanceBlocked("Unknown backup manifest schema")
    entries = data.get("files")
    if not isinstance(entries, dict) or len(entries) > MAX_FILE_COUNT:
        raise AcceptanceBlocked("Corrupt backup inventory")
    names = set()
    for base, _, files in os.walk(dest / "files", followlinks=False):
        for filename in files:
            file = Path(base) / filename
            assert_regular(file)
            names.add(file.relative_to(dest / "files").as_posix())
    if names != set(entries):
        raise AcceptanceBlocked("Backup file set differs from immutable manifest")
    for name, entry in entries.items():
        path = dest / "files" / name
        if sha(path) != entry.get("sha256") or path.stat().st_size != entry.get("bytes"):
            raise AcceptanceBlocked("Backup manifest SHA/size mismatch")
        if roots is not None:
            real = source_from_entry(roots, name)
            assert_regular(real)
            if sha(real) != entry["sha256"]:
                raise AcceptanceBlocked("Source changed since snapshot")
    if sum(v["bytes"] for v in entries.values()) != data.get("totalBytes"):
        raise AcceptanceBlocked("Backup aggregate size mismatch")
    # A fresh independent validation of the copied SQLite data.
    checks = sqlite_checks(dest / "files", entries)
    if checks != data.get("sqliteChecks"):
        raise AcceptanceBlocked("Backup SQLite readback differs from manifest")


def sandbox_install(*, output: Path, installer_run: Path = QA_RUN) -> dict:
    """Execute an Inno installer only if its destination is pinned disposable."""
    from scripts.qa_taraz_v101_inno_sandbox_20261110 import sandbox_environment
    setup = installer_run / "inno" / "Taraz-v1.0.1-SANDBOX-QA-COMPILE-ONLY.exe"
    binary = installer_run / "binary" / "Taraz-v1.0.1-SANDBOX-QA.exe"
    expected_target = installer_run / "disposable-side-by-side-install"
    report = installer_run / "compile-report.json"
    for path in (setup, binary, report):
        assert_regular(path)
    if sha(setup) != EXPECTED_SETUP_SHA or sha(binary) != EXPECTED_BINARY_SHA:
        raise AcceptanceBlocked("Unpinned QA setup or binary cannot be installed")
    compiled_report = json.loads(report.read_text(encoding="utf-8"))
    if (compiled_report.get("status") != "COMPILED_QA_SETUP_NOT_EXECUTED"
            or compiled_report.get("sideBySideInstallPath") != str(expected_target)):
        raise AcceptanceBlocked("QA Inno scope/attestation changed")
    if expected_target.exists():
        raise AcceptanceBlocked("Disposable destination already exists; create-only only")
    if not expected_target.resolve().is_relative_to(installer_run.resolve()):
        raise AcceptanceBlocked("Unsafe setup target")
    output.mkdir(exist_ok=False)
    env = sandbox_environment(installer_run)
    # Installation is into its original, explicitly fixed Inno AppId path,
    # and only source-copied QA files are installed; no production pointer.
    log = output / "inno-install.log"
    command = [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
               "/DIR=" + str(expected_target), "/LOG=" + str(log)]
    try:
        process = subprocess.run(command, cwd=str(output), env=env,
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=90, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AcceptanceBlocked("Sandbox Inno installer exceeded 90-second cap") from exc
    if process.returncode:
        raise AcceptanceBlocked(f"Sandbox Inno installer exit {process.returncode}")
    installed = expected_target / "Taraz-v1.0.1-SANDBOX-QA.exe"
    payload = expected_target / "sandbox-qa-manifest.json"
    if not installed.is_file() or sha(installed) != EXPECTED_BINARY_SHA:
        raise AcceptanceBlocked("Sandbox installed binary SHA readback failed")
    if not payload.is_file():
        raise AcceptanceBlocked("Sandbox installed QA provenance missing")
    manifest = json.loads(payload.read_text(encoding="utf-8"))
    if (manifest.get("compiledExeSha256") != EXPECTED_BINARY_SHA
            or manifest.get("sandboxInstallDir") != str(expected_target)
            or manifest.get("releaseApproved") is not False):
        raise AcceptanceBlocked("Sandbox install manifest mismatch")
    return {"installerExecuted": True, "sandboxInstalled": True,
            "sandboxBinarySha256": sha(installed), "sandboxPath": str(expected_target),
            "installLogPresent": log.is_file(), "targetVersion": "1.0.1"}


def binary_rollback_rehearsal(destination: Path, installed_root: Path) -> dict:
    """Create-only v1.0.0 binary recovery rehearsal; original remains intact."""
    old = installed_root / "versions" / "1.0.0" / "Taraz.exe"
    assert_regular(old)
    if sha(old) != EXPECTED_INSTALLED_SHA:
        raise AcceptanceBlocked("Baseline binary unavailable for rollback")
    destination.mkdir(exist_ok=False)
    target = destination / "Taraz.exe"
    with old.open("rb") as inp, target.open("xb") as out:
        shutil.copyfileobj(inp, out, 1024 * 1024)
        out.flush()
        os.fsync(out.fileno())
    if sha(target) != EXPECTED_INSTALLED_SHA:
        raise AcceptanceBlocked("Rollback rehearsal digest mismatch")
    return {"binaryRollbackReadback": True, "oldBinarySha256": sha(target),
            "didNotAlterInstalledPointer": True,
            "fullDataMigrationRollbackValidated": False}


def gui_smoke_from_immutable_backup(backup: Path, output: Path,
                                     *, installer_run: Path = QA_RUN) -> dict:
    """Load real Taraz GUI with COPY of real history, never on live user files.

    A QA-only EXE is permitted to render its native WebView2 window only when
    its dedicated profile and entire history have been cloned to a fresh ACL-
    private directory. No credentials, finance command or app UI clicks.
    The app process is terminated by this acceptance runner after reading its
    own opt-in in-app diagnostic report. Its private profile may then be dirty.
    """
    independently_verify_backup(backup)
    installed = installer_run / "disposable-side-by-side-install" / "Taraz-v1.0.1-SANDBOX-QA.exe"
    assert_regular(installed)
    if sha(installed) != EXPECTED_BINARY_SHA:
        raise AcceptanceBlocked("Unpinned sandbox Taraz executable")
    # The stage contains financial data; require a user-only DACL first.
    secure_private_directory(output)
    runtime = output / "qa-runtime"
    runtime.mkdir(exist_ok=False)
    data_roots = {"roaming": runtime / "qa" / "ledger",
                  "local": runtime / "localappdata" / "Taraz",
                  "bridge": runtime / "localappdata" / "Madar-Taraz-Bridge"}
    metadata = json.loads((backup / "snapshot-manifest.json").read_text(encoding="utf-8"))["files"]
    for destination in data_roots.values():
        destination.mkdir(parents=True, exist_ok=False)
    for name, entry in metadata.items():
        prefix, _, tail = name.partition("/")
        if prefix not in data_roots or not tail:
            raise AcceptanceBlocked("Invalid backup profile route")
        target = data_roots[prefix] / tail
        target.parent.mkdir(parents=True, exist_ok=True)
        source = backup / "files" / name
        assert_regular(source)
        with source.open("rb") as reader, target.open("xb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        if sha(target) != entry["sha256"] or target.stat().st_size != entry["bytes"]:
            raise AcceptanceBlocked("QA profile copy hash mismatch")
    # Recheck source backup after copy: no original backup is writable in QA.
    independently_verify_backup(backup)
    environment = dict(os.environ)
    for name, part in {
        "APPDATA": "appdata", "LOCALAPPDATA": "localappdata",
        "USERPROFILE": "userprofile", "HOME": "userprofile",
        "TEMP": "temp", "TMP": "temp",
    }.items():
        directory = runtime / part
        directory.mkdir(exist_ok=True)
        environment[name] = str(directory)
    environment["TARAZ_QA_MODE"] = "1"
    environment["TARAZ_QA_RUN_ROOT"] = str(runtime)
    environment["TARAZ_QA_DATA_DIR"] = str(data_roots["roaming"])
    environment["TARAZ_DATA_DIR"] = str(data_roots["roaming"])
    report = output / "webview-gui-smoke-report.json"
    environment["TARAZ_QA_REPORT"] = str(report)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop("PYTHONPATH", None)
    # A minimized native QA window may still render WebView2 for this opt-in
    # test, without commandeering the user's actual Taraz session.
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 6  # SW_MINIMIZE
    process = subprocess.Popen([str(installed)], cwd=str(output), env=environment,
                               startupinfo=startup, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    status = "NO_REPORT"
    try:
        deadline = time.monotonic() + 24
        while time.monotonic() < deadline:
            if report.is_file():
                status = "REPORT_CREATED"
                break
            if process.poll() is not None:
                status = "PROCESS_EXITED_WITHOUT_UI_REPORT"
                break
            time.sleep(0.4)
    finally:
        if process.poll() is None:
            # PyInstaller --onefile launches a second, same-named child for its
            # Python runtime. Terminating only the outer bootloader can leave
            # that child visible in Task Manager. This PID was created by our
            # own Popen above and points to the pinned sandbox EXE; /T reaches
            # only its child process tree, never an unrelated user's Taraz.
            stopped = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                     capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", timeout=15, check=False)
            if stopped.returncode:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    observed = {"status": status, "sandboxProcessExitCode": process.returncode,
                "qaProfileOnly": True, "realProfileTouched": False,
                "nativeWindowCreated": False, "webviewLoaded": False}
    if report.is_file():
        values = json.loads(report.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise AcceptanceBlocked("Malformed diagnostic from QA app")
        # Do not include private ledger paths, user records, URLs, or accounts.
        observed.update({"nativeWindowCreated": True,
                         "webviewLoaded": values.get("loaded") is True,
                         "bridgeAvailable": values.get("accountingBridge") == "function",
                         "appTitlePresent": isinstance(values.get("title"), str)
                         and "تراز" in values.get("title", ""),
                         "taskBridgeExposed": values.get("taskBridgeExposed") == "function",
                         "tabCount": values.get("tabCount")})
    independently_verify_backup(backup)
    if status != "REPORT_CREATED" or observed["webviewLoaded"] is not True:
        observed["reason"] = "Native GUI not independently verified; production acceptance must block"
    return observed


def run() -> Path:
    if os.name != "nt":
        raise AcceptanceBlocked("Windows-only upgrade acceptance")
    if not os.environ.get("APPDATA") or not os.environ.get("LOCALAPPDATA"):
        raise AcceptanceBlocked("User profile roots unavailable")
    appdata, local = Path(os.environ["APPDATA"]), Path(os.environ["LOCALAPPDATA"])
    assert_regular(appdata, directory=True)
    assert_regular(local, directory=True)
    no_active_taraz()
    original = installed_baseline(local)
    roots = real_profile_roots(appdata, local)
    for directory in roots.values():
        assert_regular(directory, directory=True)
    BACKUP_PARENT.mkdir(parents=True, exist_ok=True)
    assert_regular(BACKUP_PARENT, directory=True)
    output = BACKUP_PARENT / ("taraz-backup-" + uuid.uuid4().hex[:12])
    outcome = {"status": "IN_PROGRESS", "installedBefore": original["version"],
               "installedAfter": None, "productionPointerChanged": False,
               "realDataOverwritten": False, "realProfilePaths": "user profile inventory only",
               "output": str(output)}
    report_file = output / "backup-acceptance-report.json"
    try:
        outcome["backup"] = verified_backup(roots, output)
        no_active_taraz()
        if installed_baseline(local) != original:
            raise AcceptanceBlocked("Installed application changed during backup")
        independently_verify_backup(output, roots)
        outcome.update({"status": "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING",
                        "installedAfter": "1.0.0", "productionPointerChanged": False,
                        "reason": "Full real-data snapshot passed SHA/SQLite readback. "
                                  "No production installer has been authorized by safety gates yet."})
    except Exception as exc:
        outcome.update({"status": "BLOCKED_ACCEPTANCE", "error": str(exc),
                        "errorType": type(exc).__name__})
        report_file.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    report_file.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_file


def sandbox_acceptance(backup: Path) -> Path:
    """Only after externally reviewable real backup exists."""
    assert_regular(backup, directory=True)
    independently_verify_backup(backup)
    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / ("sandbox-" + uuid.uuid4().hex[:12])
    output.mkdir(exist_ok=False)
    report_file = output / "sandbox-acceptance-report.json"
    observed = {"status": "IN_PROGRESS", "productionPointerChanged": False,
                "realDataOverwritten": False, "backupManifestSha256": sha(backup / "snapshot-manifest.json")}
    try:
        no_active_taraz()
        observed["sandboxInstall"] = sandbox_install(output=output / "sandbox-inno-evidence")
        observed["binaryRollback"] = binary_rollback_rehearsal(
            output / "rollback-rehearsal-new-destination",
            Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz")
        independently_verify_backup(backup, real_profile_roots(
            Path(os.environ["APPDATA"]), Path(os.environ["LOCALAPPDATA"])))
        no_active_taraz()
        observed["installedBaseline"] = installed_baseline(Path(os.environ["LOCALAPPDATA"]))
        observed.update({"status": "QA_INSTALL_TESTED_PRODUCTION_BLOCKED",
                         "sandboxGuiSmoke": "PENDING_EXPLICIT_TEST",
                         "reason": "QA-guarded binary and unfinished source changes cannot be promoted to production"})
    except Exception as error:
        observed.update({"status": "BLOCKED_SANDBOX", "errorType": type(error).__name__, "error": str(error)})
        report_file.write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    report_file.write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_file


def gui_acceptance(backup: Path) -> Path:
    no_active_taraz()
    independently_verify_backup(backup)
    original = installed_baseline(Path(os.environ["LOCALAPPDATA"]))
    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / ("gui-" + uuid.uuid4().hex[:12])
    output.mkdir(exist_ok=False)
    report_file = output / "qa-webview-acceptance-report.json"
    status = {"status": "GUI_QA_IN_PROGRESS", "productionPointerChanged": False}
    try:
        status["gui"] = gui_smoke_from_immutable_backup(backup, output / "private")
        no_active_taraz()
        if installed_baseline(Path(os.environ["LOCALAPPDATA"])) != original:
            raise AcceptanceBlocked("Installed baseline changed during isolated native GUI smoke")
        status["status"] = ("GUI_QA_LOADED_NO_PRODUCTION_AUTHORIZATION" if
                            status["gui"]["webviewLoaded"] else "GUI_QA_NOT_VERIFIED")
    except Exception as exc:
        status.update({"status": "BLOCKED_GUI_QA", "errorType": type(exc).__name__, "error": str(exc)})
        report_file.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    report_file.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_file


if __name__ == "__main__":
    try:
        if len(sys.argv) == 1 or sys.argv[1:] == ["--backup-real"]:
            report = run()
        elif len(sys.argv) == 3 and sys.argv[1] == "--verify-backup":
            independently_verify_backup(Path(sys.argv[2]))
            print("VERIFIED_OFFLINE_BACKUP_READBACK")
            sys.exit(0)
        elif len(sys.argv) == 3 and sys.argv[1] == "--sandbox-acceptance":
            report = sandbox_acceptance(Path(sys.argv[2]))
        elif len(sys.argv) == 3 and sys.argv[1] == "--gui-smoke":
            report = gui_acceptance(Path(sys.argv[2]))
        else:
            raise AcceptanceBlocked("Usage: --backup-real | --verify-backup PATH | --sandbox-acceptance PATH | --gui-smoke PATH")
        data = json.loads(report.read_text(encoding="utf-8"))
        safe = {k: data.get(k) for k in (
            "status", "installedBefore", "installedAfter", "productionPointerChanged",
            "backup", "sandboxInstall", "binaryRollback", "sandboxGuiSmoke", "reason")}
        safe["reportFile"] = str(report)
        print(json.dumps(safe, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"TARAZ UPGRADE ACCEPTANCE BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
