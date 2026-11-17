"""Try a single Ctrl+Break on ONE verified QA-only PowerShell process group.

No taskkill, Stop-Process, TerminateProcess, global keyboard, console attach,
or interference with other shells. On failure, leave it running and report.
"""
from __future__ import annotations
import ctypes
from pathlib import Path
import json
import os
import psutil

PID = 32248
QA_PATH = (Path(__file__).resolve().parents[3] /
           "MTR-NEXT-UPDATE-CANDIDATES-20261110" /
           "taraz-v1.0.6-aaas" / "integrated-source-native-draft-qa-20261112" /
           "qa-final-native-6ba37306bd25" / "private-profile" / "owned-uia.ps1")


def main():
    if os.name != "nt" or not QA_PATH.is_file():
        raise RuntimeError("QA Windows source script missing")
    try:
        proc = psutil.Process(PID)
    except psutil.NoSuchProcess:
        print(json.dumps({"exactQaHelperPid": PID, "alreadyExited": True,
                          "ctrlBreakGroupOnly": False, "noForceTerminate": True}))
        return
    executable = Path(proc.exe())
    if executable.name.lower() != "powershell.exe" or not str(executable).lower().startswith(
            str(Path(os.environ["SystemRoot"]).resolve()).lower()):
        raise RuntimeError("Refused non-system or non-PowerShell PID")
    args = proc.cmdline()
    paths = [Path(arg).resolve() for arg in args if arg.lower().endswith("owned-uia.ps1")]
    if len(paths) != 1 or paths[0] != QA_PATH.resolve():
        raise RuntimeError("Target not the exact QA helper script")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GenerateConsoleCtrlEvent.argtypes = [ctypes.c_uint, ctypes.c_uint]
    kernel.GenerateConsoleCtrlEvent.restype = ctypes.c_int
    signalled = bool(kernel.GenerateConsoleCtrlEvent(1, PID))
    exited = False
    if signalled:
        try:
            proc.wait(timeout=5)
            exited = True
        except psutil.TimeoutExpired:
            pass
    print(json.dumps({"exactQaHelper": True, "pid": PID, "ctrlBreakGroupOnly": signalled,
                      "exitedGracefully": exited, "noForceTerminate": True}))


if __name__ == "__main__":
    main()
