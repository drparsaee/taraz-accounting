"""User-visible no-password fresh-start capability in a real Frozen Taraz EXE.

Strictly PRIVATE data and Win32 desktop, no production mutation or credentials.
Verifies actual empty, bound account after a graceful EXE shutdown. This is not
full financial/AI UI acceptance.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v103_native_gui_20261111 as native
from scripts import qa_taraz_ai_frozen_real_auth_20261114 as frozen
from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import secure_private_directory
from taraz_fresh_windows_workspace import inspect_fresh_workspace, stage_new_empty_root

OUTPUT = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.6-aaas" / "fresh-windows-frozen-qa-20261115"


def _sha(p: Path) -> str:
    with p.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def _name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def run(exe: Path, expected_sha: str):
    if os.name != "nt" or not exe.is_file() or _sha(exe) != expected_sha:
        raise RuntimeError("Pinned Windows candidate unavailable")
    import psutil
    if any((p.info.get("name") or "").casefold() == "taraz.exe"
           for p in psutil.process_iter(["name"])):
        raise RuntimeError("Another real Taraz.exe is running")
    if not OUTPUT.is_dir():
        secure_private_directory(OUTPUT)
    work = OUTPUT / ("qa-" + uuid.uuid4().hex[:12])
    secure_private_directory(work)
    runtime = work / "qa" / "qa-runtime"
    (runtime / "roaming").mkdir(parents=True)
    (runtime / "localappdata").mkdir()
    fresh = runtime / "roaming" / "Taraz"
    staged = stage_new_empty_root(fresh)
    if staged["ledgerRevision"] != 0 or staged["role"] != "admin":
        raise RuntimeError("Empty Windows account did not bootstrap")
    env = native.isolated_env(runtime, {
        "roaming": fresh, "local": runtime / "localappdata" / "Taraz",
        "bridge": runtime / "localappdata" / "Madar-Taraz-Bridge",
    }, work / "native-startup.json", native.unused_port())
    env["TARAZ_QA_DATA_DIR"] = str(fresh)
    result = {"status": "BLOCKED", "private": True,
              "installed104Unchanged": True, "testLedgerRevision": 0,
              "noNativeLoginOrEnrollmentWindow": False,
              "realTarazWebviewWindowVisible": False,
              "gracefulExit": False, "exeSha256": expected_sha}
    with native.PrivateDesktop() as desktop:
        pid, handle, thread = desktop.spawn(exe, work, env)
        try:
            deadline = time.monotonic() + 28
            observed = set()
            while time.monotonic() < deadline:
                try:
                    _, owned = frozen._owned_processes(pid, exe)
                    windows = frozen._owned_private_windows(desktop, owned)
                except frozen.FrozenAuthBlocked:
                    time.sleep(.35)
                    continue
                observed.update(_name(h) for h in windows)
                if "تراز | حسابداری" in observed:
                    result["realTarazWebviewWindowVisible"] = True
                    break
                time.sleep(.35)
            result["noNativeLoginOrEnrollmentWindow"] = (
                not any("ورود امن" in label or "تأیید یک‌باره" in label
                        or "انتخاب شرکت" in label for label in observed))
        finally:
            try:
                close = frozen._graceful_close(desktop, pid, exe)
                result["gracefulExit"] = close.get("graceful") is True
            except frozen.FrozenAuthBlocked:
                result["gracefulExit"] = False
            if not result["gracefulExit"]:
                from scripts.qa_taraz_owned_private_graceful_close_20261115 import run as recovery
                try:
                    result["gracefulExit"] = recovery(pid, exe, expected_sha, close=True).get(
                        "gracefullyExited") is True
                except Exception:
                    pass
            ctypes.windll.kernel32.CloseHandle(handle)
            ctypes.windll.kernel32.CloseHandle(thread)
    after = inspect_fresh_workspace(fresh)
    result["revisionAfterExit"] = after["ledgerRevision"]
    if (result["realTarazWebviewWindowVisible"] and
            result["noNativeLoginOrEnrollmentWindow"] and
            result["gracefulExit"] and after["ledgerRevision"] == 0):
        result["status"] = "PASS_FROZEN_FRESH_WINDOWS_ACCOUNT_OPEN"
    (work / "fresh-windows-frozen-result.json").write_text(
        json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    return {"status": result["status"], "work": str(work), **result}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: QA script <exact candidate exe> <sha256>")
    print(json.dumps(run(Path(sys.argv[1]), sys.argv[2]), ensure_ascii=True))
