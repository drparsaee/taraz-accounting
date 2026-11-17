"""Persistent, separate Green test profile for Taraz v1.0.5.

Non-QA EXE + QA-only *copied* data. Never edits the installed version pointer,
the live accounting ledger, local Madar files, or the active Blue 1.0.4.
Use --prepare first; --private-smoke verifies actual compiled Windows startup
in a non-input desktop; --launch-visible is an explicit user-facing action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import qa_taraz_v103_native_gui_20261111 as legacy
from scripts import qa_taraz_v103_independent_acceptance_20261111 as pins
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as private_acl

ARTIFACTS = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.5-aaas"
BUILD = ARTIFACTS / "build-a605e1eb5052"
EXE = BUILD / "binary" / "Taraz.exe"
EXE_SHA = "59b1d32197ebbd3b1bc34f8ce4cc2a652d84fa45fa9d091379ea839e38bdf259"
WORK = ARTIFACTS / "green-qa-profile-20261111"
SENTINEL = WORK / "green-profile.json"
REPORT = WORK / "native-readback.json"
BACKUP = pins.BACKUP


class GreenBlocked(RuntimeError):
    pass


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe(path, expect_file=False):
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or bool(
            getattr(part.lstat(), "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )):
            raise GreenBlocked("Symlink/junction in candidate/test-profile path")
    if expect_file and not path.is_file():
        raise GreenBlocked("Missing regular candidate file")


def candidate():
    if os.name != "nt":
        raise GreenBlocked("Green test requires native Windows")
    safe(EXE, True)
    if sha(EXE) != EXE_SHA:
        raise GreenBlocked("Candidate EXE changed since frozen build")
    report = json.loads((BUILD / "build-report.json").read_text(encoding="utf-8"))
    if not (
        report.get("status") == "V105_AAAS_NON_QA_BUILT_NOT_INSTALLED" and
        report.get("exeSha256") == EXE_SHA and
        report.get("sourceFilesCount") == 136 and
        report.get("compiled", {}).get("qaOnly") is False and
        report.get("compiled", {}).get("bridgeForwarded") is True and
        report.get("compiled", {}).get("compiledByteParity") is True
    ):
        raise GreenBlocked("Candidate provenance or native bridge unavailable")


def roots():
    runtime = WORK / "private-profile" / "qa" / "qa-runtime"
    return runtime, {
        "roaming": runtime / "roaming" / "Taraz",
        "local": runtime / "localappdata" / "Taraz",
        "bridge": runtime / "localappdata" / "Madar-Taraz-Bridge",
    }


def prepared():
    safe(WORK)
    safe(SENTINEL, True)
    marker = json.loads(SENTINEL.read_text(encoding="utf-8"))
    if marker != {
        "channel": "local-green-user-test",
        "candidateSha256": EXE_SHA,
        "baseline": "offline-verified-cold-backup-20261111",
        "financialEventsCreatedByPreparation": False,
    }:
        raise GreenBlocked("Unexpected Green profile identity")
    runtime, folders = roots()
    for path in folders.values():
        safe(path)
        if not path.is_dir():
            raise GreenBlocked("Copied Green profile incomplete")
    ledger = folders["roaming"] / "standalone-accounting.sqlite3"
    safe(ledger, True)
    return runtime, folders


def prepare():
    candidate()
    if SENTINEL.exists():
        prepared()
        return "EXISTING_GREEN_QA_PROFILE_RETAINED"
    if WORK.exists():
        raise GreenBlocked("Incomplete Green directory exists; never overwrite")
    evidence = pins.verify_backup(BACKUP)
    if evidence.get("filesRehashed") != 181:
        raise GreenBlocked("Cold backup was not independently verified")
    safe(ARTIFACTS)
    private_acl.secure_private_directory(WORK)
    runtime, folders = legacy.clone_offline_snapshot(WORK)
    if any(
        folder.resolve() == (Path(os.environ.get(key, "")) / "Taraz").resolve()
        for folder, key in (
            (folders["roaming"], "APPDATA"), (folders["local"], "LOCALAPPDATA")
        )
    ):
        raise GreenBlocked("Green clone resolved to user's real profile")
    marker = {
        "channel": "local-green-user-test",
        "candidateSha256": EXE_SHA,
        "baseline": "offline-verified-cold-backup-20261111",
        "financialEventsCreatedByPreparation": False,
    }
    with SENTINEL.open("x", encoding="utf-8") as output:
        json.dump(marker, output, ensure_ascii=False, indent=2)
    prepared()
    return "GREEN_QA_CLONE_CREATED_AND_181_FILES_HASH_VERIFIED"


def isolated():
    runtime, folders = prepared()
    report = WORK / "native-green-startup.json"
    env = legacy.isolated_env(runtime, folders, report, legacy.unused_port())
    if any(
        Path(env[key]).resolve() == Path(os.environ[key]).resolve()
        for key in ("APPDATA", "LOCALAPPDATA", "TEMP")
    ):
        raise GreenBlocked("Green process inherited a live user-data path")
    # The remote debugging option is only needed by the legacy CDP test harness,
    # not by the user. Avoid leaving a browser debug port open.
    args = env.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    args = " ".join(part for part in args.split()
                    if not part.startswith("--remote-debugging-"))
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = args
    return env, report


def smoke():
    import psutil
    candidate()
    prepare()
    env, report_file = isolated()
    original = {p.pid: p.create_time() for p in psutil.process_iter(["name"])
                if (p.info.get("name") or "").casefold() == "taraz.exe"}
    tracked = {}
    status = {
        "candidateSha256": EXE_SHA,
        "nativeNonQaExeStarted": False,
        "greenProfileCopied": True,
        "userDesktopInputSent": False,
        "financeActionAttempted": False,
        "installedBluePointerChanged": False,
        "ownedProcessesLeftAlive": None,
    }
    p_id = 0
    handles = []
    def capture():
        if not p_id:
            return
        try:
            process = psutil.Process(p_id)
            if process.exe().casefold() != str(EXE).casefold():
                raise GreenBlocked("Candidate process identity drift")
            for child in [process] + process.children(recursive=True):
                try:
                    tracked[child.pid] = child.create_time()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except psutil.NoSuchProcess:
            pass
    try:
        with legacy.PrivateDesktop() as desktop:
            p_id, process_handle, thread_handle = desktop.spawn(EXE, WORK, env)
            handles = [process_handle, thread_handle]
            status["nativeNonQaExeStarted"] = True
            capture()
            deadline = time.monotonic() + 26
            while time.monotonic() < deadline:
                capture()
                if report_file.is_file():
                    try:
                        loaded = json.loads(report_file.read_text(encoding="utf-8"))
                    except (ValueError, OSError):
                        loaded = {}
                    if loaded.get("loaded") is True:
                        break
                time.sleep(.4)
            capture()
            summary = json.loads(report_file.read_text(encoding="utf-8")) if report_file.is_file() else {}
            status["nativeWebViewLoaded"] = summary.get("loaded") is True
            status["accountingBridgePresent"] = summary.get("accountingBridge") == "function"
            status["privateWindowObserved"] = bool(desktop.owned_windows(set(tracked)))
            status["result"] = (
                "PASS_GREEN_V105_PRIVATE_NATIVE_STARTUP_ONLY" if all(
                    status.get(key) for key in (
                        "nativeNonQaExeStarted", "nativeWebViewLoaded",
                        "accountingBridgePresent", "privateWindowObserved",
                    )
                ) else "GREEN_NATIVE_STARTUP_NOT_VERIFIED"
            )
    finally:
        capture()
        owned=[]
        for pid, started in tracked.items():
            try:
                process = psutil.Process(pid)
                if process.create_time() == started:
                    owned.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        for process in reversed(owned):
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(owned, timeout=8)
        status["ownedProcessesLeftAlive"] = len(alive)
        # Original Taraz v1.0.4 process must never be targeted by our cleanup.
        remaining = {
            p.pid: p.create_time() for p in psutil.process_iter(["name"])
            if (p.info.get("name") or "").casefold() == "taraz.exe"
        }
        status["originalTarazPidsIntact"] = all(
            remaining.get(pid) == started for pid, started in original.items()
        )
        for handle in handles:
            if handle:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(handle)
        status["candidateExeUnchanged"] = sha(EXE) == EXE_SHA
        if not (
            status["ownedProcessesLeftAlive"] == 0 and
            status["originalTarazPidsIntact"] and
            status["candidateExeUnchanged"]
        ):
            status["result"] = "BLOCKED_GREEN_SMOKE_POSTFLIGHT"
        REPORT.write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return status


def launch_visible():
    candidate()
    prepare()
    env, _ = isolated()
    # Only this explicit mode opens the user's real input desktop window.
    process = subprocess.Popen([str(EXE)], cwd=str(WORK), env=env,
                               close_fds=True)
    time.sleep(1.5)
    if process.poll() is not None:
        raise GreenBlocked("Green EXE exited before its test window was available")
    return {
        "result": "GREEN_V105_LAUNCHED_ON_ISOLATED_QA_DATA",
        "pid": process.pid,
        "profile": str(WORK),
        "installedPointerTouched": False,
        "realFinancialDataTouched": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    opts = parser.add_mutually_exclusive_group(required=True)
    opts.add_argument("--prepare", action="store_true")
    opts.add_argument("--private-smoke", action="store_true")
    opts.add_argument("--launch-visible", action="store_true")
    opts.add_argument("--status", action="store_true")
    args = parser.parse_args()
    try:
        if args.prepare:
            result = {"result": prepare()}
        elif args.private_smoke:
            result = smoke()
        elif args.launch_visible:
            result = launch_visible()
        else:
            candidate()
            runtime, folders = prepared()
            result = {
                "result": "READY_GREEN_V105_INTERACTIVE_QA",
                "candidateSha256": EXE_SHA,
                "privateLedgerPresent": (
                    folders["roaming"] / "standalone-accounting.sqlite3"
                ).is_file(),
                "installedPointerTouched": False,
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print("V105 GREEN TEST BLOCKED: " + type(exc).__name__ +
              ": " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
