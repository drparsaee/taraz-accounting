"""Native Taraz 1.0.1 WebView2 + invoice designer acceptance, copied data only.

Runs the attested *non-QA packaged binary* with ALL profile/data/cache roots
redirected to a brand-new private disposable directory. Drive the *real*
WebView2 instance via local-only Chromium DevTools. Save a QA-only invoice
print layout, reload, and confirm persistence in the cloned profile.

Never installs, changes version pointer, reads real ledger content, or calls
any financial mutation. Source data only come from the verified offline backup.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acceptance

QA_OUT = PROJECT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.1-nonqa-native-gui-qa"
NEW_RUN = PROJECT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.1-production-candidate" / "build-057caff5080e"
NEW_EXE = NEW_RUN / "offline-update" / "Taraz.exe"
EXPECTED_EXE = "5b5a550f3b95cda8352f757cd9e61d44a62531e0e4dfe0fc6d586a0d6a452d4b"
EXPECTED_BUILD_REPORT = "PRODUCTION_CANDIDATE_BUILT_NOT_INSTALLED"
BACKUP = PROJECT.parents[1] / "MTR-REAL-UPGRADE-BACKUPS-20261110" / "taraz-backup-4ea33b2b953d"
EXPECTED_BACKUP = "b854970e6e99f8abeec001cdb4c8f9c4e501eca6a919a8436cd02dfb87907afb"
PLAYWRIGHT = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "playwright"
CDP_SCRIPT = PROJECT / "scripts" / "qa_taraz_v101_nonqa_native_gui_cdp_20261110.cjs"


class NonQaGuiBlocked(RuntimeError):
    pass


def pin_sources():
    for path in (NEW_EXE, NEW_RUN / "build-report.json", BACKUP / "snapshot-manifest.json", CDP_SCRIPT):
        acceptance.assert_regular(path)
    if acceptance.sha(NEW_EXE) != EXPECTED_EXE:
        raise NonQaGuiBlocked("New non-QA Taraz.exe SHA mismatch")
    if acceptance.sha(BACKUP / "snapshot-manifest.json") != EXPECTED_BACKUP:
        raise NonQaGuiBlocked("Attested real backup manifest changed")
    report = json.loads((NEW_RUN / "build-report.json").read_text(encoding="utf-8"))
    if (report.get("status") != EXPECTED_BUILD_REPORT or
            report.get("exeSha256") != EXPECTED_EXE or
            report.get("targetVersion") != "1.0.1" or
            report.get("compiled", {}).get("nonQaRuntime") is not True or
            report.get("compiled", {}).get("invoiceDesignerCompiled") is not True or
            report.get("sourceFileCount") != 128 or
            report.get("productionPointerChanged") is not False):
        raise NonQaGuiBlocked("Non-QA build report lacks required compiled evidence")
    acceptance.independently_verify_backup(BACKUP)
    if not PLAYWRIGHT.is_dir():
        raise NonQaGuiBlocked("Global known Playwright dependency unavailable")
    return report


def copy_private_profile(dest: Path):
    """Clone only the signed-off snapshot; never read profile source directly."""
    acceptance.secure_private_directory(dest)
    qa_segment = dest / "qa"
    qa_segment.mkdir(exist_ok=False)
    runtime = qa_segment / "qa-runtime"
    runtime.mkdir(exist_ok=False)
    roots = {
        "roaming": runtime / "roaming" / "Taraz",
        "local": runtime / "localappdata" / "Taraz",
        "bridge": runtime / "localappdata" / "Madar-Taraz-Bridge",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=False)
    files = json.loads((BACKUP / "snapshot-manifest.json").read_text(encoding="utf-8"))["files"]
    for name, entry in files.items():
        branch, _, relative = name.partition("/")
        if branch not in roots or not relative or ".." in Path(relative).parts:
            raise NonQaGuiBlocked("Unsupported snapshot path")
        original = BACKUP / "files" / name
        acceptance.assert_regular(original)
        target = roots[branch] / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with original.open("rb") as inp, target.open("xb") as out:
            shutil.copyfileobj(inp, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        if target.stat().st_size != entry["bytes"] or acceptance.sha(target) != entry["sha256"]:
            raise NonQaGuiBlocked("Cloned private profile SHA readback mismatch")
    acceptance.independently_verify_backup(BACKUP)
    return runtime, roots


def local_cdp_port():
    """Ephemeral loopback-only port; not a public remote-debugging endpoint."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def isolated_env(runtime: Path, roots: dict[str, Path], report: Path, cdp_port: int) -> dict:
    mapping = {
        "APPDATA": runtime / "roaming",
        "LOCALAPPDATA": runtime / "localappdata",
        "USERPROFILE": runtime / "userprofile",
        "HOME": runtime / "userprofile",
        "TEMP": runtime / "temp",
        "TMP": runtime / "temp",
        "PYINSTALLER_CONFIG_DIR": runtime / "pyinstaller-config",
        "PYTHONPYCACHEPREFIX": runtime / "pycache",
        "WEBVIEW2_USER_DATA_FOLDER": runtime / "webview-user-data",
        "XDG_CACHE_HOME": runtime / "cache",
    }
    env = dict(os.environ)
    for k in list(env):
        if k.upper().startswith("TARAZ_") or k.upper() in ("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "PYTHONPATH"):
            env.pop(k, None)
    for key, path in mapping.items():
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update({
        "TARAZ_QA_MODE": "1",
        "TARAZ_QA_DATA_DIR": str(roots["roaming"]),
        "TARAZ_DATA_DIR": str(roots["roaming"]),
        "TARAZ_QA_REPORT": str(report),
        "PYTHONDONTWRITEBYTECODE": "1",
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": (
            f"--remote-debugging-port={cdp_port} "
            "--remote-debugging-address=127.0.0.1 "
            "--force-renderer-accessibility "
            "--disable-background-networking --disable-extensions "
            "--disable-sync --disable-component-update "
            "--no-first-run --no-default-browser-check"),
    })
    return env


def stop_qa_process_tree(pid: int) -> None:
    """Stop ONLY our own spawned, pinned Taraz.exe process and children."""
    import psutil
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        parent = None
    if parent is not None and Path(parent.exe()).resolve() != NEW_EXE.resolve():
        raise NonQaGuiBlocked("QA shutdown refused unrelated PID")
    owned = list(parent.children(recursive=True)) if parent is not None else []
    # PyInstaller one-file child may outlive its bootloader; identify precisely
    # by pinned executable location and the PID of our own bootloader.
    for process in psutil.process_iter(["pid", "ppid", "exe"]):
        try:
            if (process.info["ppid"] == pid and process.info["exe"] and
                    Path(process.info["exe"]).resolve() == NEW_EXE.resolve() and
                    process not in owned):
                owned.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    for child in reversed(owned):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    if parent is not None:
        try:
            parent.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs([*owned, *([parent] if parent else [])], timeout=8)
    if alive:
        raise NonQaGuiBlocked("QA process descendants remain after shutdown")


def finance_row(db: Path) -> tuple:
    acceptance.assert_regular(db)
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=8) as conn:
        conn.execute("PRAGMA query_only=ON")
        record = conn.execute("SELECT revision,digest FROM standalone_accounting WHERE id=1").fetchone()
    if not record or record[0] != 608 or not isinstance(record[1], str):
        raise NonQaGuiBlocked("Cloned accounting revision or digest is invalid")
    return record


def run(*, native_only: bool = False) -> Path:
    if os.name != "nt":
        raise NonQaGuiBlocked("Windows WebView2 native QA only")
    pin_sources()
    acceptance.no_active_taraz()
    local = Path(os.environ["LOCALAPPDATA"])
    initial = acceptance.installed_baseline(local)
    if not (local / "Programs" / "Taraz" / "versions" / "1.0.1" / "Taraz.exe").is_file():
        raise NonQaGuiBlocked("Installed side-by-side 1.0.1 staging absent")
    if acceptance.sha(local / "Programs" / "Taraz" / "versions" / "1.0.1" / "Taraz.exe") != EXPECTED_EXE:
        raise NonQaGuiBlocked("Actual installed side-by-side candidate differs from verified source")
    QA_OUT.mkdir(parents=True, exist_ok=True)
    acceptance.assert_regular(QA_OUT, directory=True)
    work = QA_OUT / ("native-" + uuid.uuid4().hex[:12])
    work.mkdir(exist_ok=False)
    result_path = work / "native-gui-acceptance.json"
    verdict = {"status": "IN_PROGRESS", "candidateSha256": EXPECTED_EXE,
               "qaOnly": True, "realProfileOpenedByCandidate": False,
               "productionPointerChanged": False, "productionTargetVersion": "1.0.1"}
    try:
        runtime, paths = copy_private_profile(work / "private-profile")
        ledger_path = paths["roaming"] / "standalone-accounting.sqlite3"
        finance_before = finance_row(ledger_path)
        ui_report = work / "private-profile" / "qa-webview-native-report.json"
        port = local_cdp_port()
        env = isolated_env(runtime, paths, ui_report, port)
        if native_only:
            env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
                "--force-renderer-accessibility --disable-background-networking "
                "--disable-sync --disable-component-update --no-first-run")
        debug = work / "private-profile" / "qa-binary-stderr.log"
        capture = debug.open("xb")
        try:
            child = subprocess.Popen([str(NEW_EXE)], cwd=str(work), env=env,
                                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                                     stdout=capture, stderr=subprocess.STDOUT)
        finally:
            capture.close()
        try:
            if native_only:
                expires = time.monotonic() + 35
                while time.monotonic() < expires and not ui_report.is_file() and child.poll() is None:
                    time.sleep(.3)
                verdict["nativeOnly"] = True
                verdict["nativeReportPresent"] = ui_report.is_file()
                if verdict["nativeReportPresent"]:
                    time.sleep(2)
                    probe = work / "private-profile" / "qa-native-uia-probe.json"
                    probe_script = PROJECT / "scripts" / "qa_taraz_v101_nonqa_native_uia_probe_20261110.ps1"
                    outcome = subprocess.run(["powershell", "-NoProfile", "-File", str(probe_script),
                                              "-QaPid", str(child.pid), "-ResultFile", str(probe)],
                                             capture_output=True, text=True,
                                             encoding="utf-8", errors="replace", timeout=17)
                    verdict["uiaProbeExitCode"] = outcome.returncode
                    if probe.is_file():
                        verdict["uia"] = json.loads(probe.read_text(encoding="utf-8"))
            else:
                node_script = ["node", str(CDP_SCRIPT), str(port), str(PLAYWRIGHT),
                           str(work / "private-profile" / "qa-cdp-result.json"),
                           str(paths["roaming"] / "invoice-templates.json")]
                try:
                    result = subprocess.run(node_script, cwd=str(work), env=env,
                                            capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", timeout=65)
                except subprocess.TimeoutExpired as exc:
                    raise NonQaGuiBlocked("Native CDP acceptance timed out after 65 seconds") from exc
                if result.returncode:
                    raise NonQaGuiBlocked("CDP invoice designer rejected: " + (result.stderr or result.stdout)[-1000:])
                observed = json.loads((work / "private-profile" / "qa-cdp-result.json").read_text(encoding="utf-8"))
                verdict["gui"] = observed
            if ui_report.is_file():
                loaded = json.loads(ui_report.read_text(encoding="utf-8"))
                verdict["nativeWebViewLoaded"] = loaded.get("loaded") is True
                verdict["nativeAccountingBridgePresent"] = loaded.get("accountingBridge") == "function"
                verdict["nativeTaskBridgeAbsent"] = loaded.get("taskBridgeExposed") != "function"
            else:
                raise NonQaGuiBlocked("No native pywebview in-app load report")
        finally:
            stop_qa_process_tree(child.pid)
        if not native_only:
            verdict["gui"]["financeLedgerUnchanged"] = finance_row(ledger_path) == finance_before
        acceptance.independently_verify_backup(BACKUP,
            acceptance.real_profile_roots(Path(os.environ["APPDATA"]), local))
        if acceptance.installed_baseline(local) != initial:
            raise NonQaGuiBlocked("Production launcher/pointer/old binary changed")
        acceptance.no_active_taraz()
        if native_only:
            if not all((verdict.get("nativeReportPresent"),
                        verdict.get("nativeWebViewLoaded"),
                        verdict.get("nativeAccountingBridgePresent"),
                        verdict.get("nativeTaskBridgeAbsent"))):
                raise NonQaGuiBlocked("Native-only diagnostic never loaded WebView2")
            verdict.update({"status": "NATIVE_GUI_LOADED_INVOICE_ROUNDTRIP_NOT_TESTED",
                            "currentVersionStill": "1.0.0", "productionPointerChanged": False})
            result_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            return result_path
        if not all((verdict.get("nativeWebViewLoaded"),
                    verdict.get("nativeAccountingBridgePresent"),
                    verdict.get("nativeTaskBridgeAbsent"),
                    verdict.get("gui", {}).get("invoiceDesignOpened"),
                    verdict.get("gui", {}).get("templateSaved"),
                    verdict.get("gui", {}).get("templateReloaded"),
                    verdict.get("gui", {}).get("financeLedgerUnchanged"),
                    verdict.get("gui", {}).get("noExternalRequestsObserved"))):
            raise NonQaGuiBlocked("Native invoice design roundtrip or safety check failed")
        verdict.update({"status": "GO_FOR_POINTER_ACTIVATION_WITH_GUARDS",
                        "currentVersionStill": "1.0.0",
                        "realSnapshotReverified": True, "productionPointerChanged": False})
    except Exception as error:
        verdict.update({"status": "FAIL_PRODUCTION_ACTIVATION", "errorType": type(error).__name__,
                        "error": str(error)})
        result_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    result_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result_path


if __name__ == "__main__":
    try:
        file = run(native_only=sys.argv[1:] == ["--native-only"])
        data = json.loads(file.read_text(encoding="utf-8"))
        print(json.dumps({"status": data["status"], "gui": data.get("gui"),
                          "nativeWebViewLoaded": data.get("nativeWebViewLoaded"),
                          "currentVersionStill": data.get("currentVersionStill"),
                          "productionPointerChanged": False, "report": str(file)},
                         ensure_ascii=False, indent=2))
    except Exception as error:
        print("NATIVE NON-QA GUI BLOCKED: " + type(error).__name__ + ": " + str(error), file=sys.stderr)
        sys.exit(1)
