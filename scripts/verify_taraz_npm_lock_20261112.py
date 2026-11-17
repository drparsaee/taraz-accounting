"""Recreate locked npm dependencies in an isolated temporary directory.

No mutation to the worktree's node_modules, user profiles, EXE or ledger.
The test is offline intentionally; missing cache is reported, not fetched.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    command = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    node = shutil.which("node.exe" if os.name == "nt" else "node")
    if not command or not node:
        raise RuntimeError("Node/npm not found in development PATH")
    with TemporaryDirectory(prefix="qa-taraz-npm-lock-", dir=ROOT.parent) as folder:
        target = Path(folder)
        for filename in ("package.json", "package-lock.json"):
            shutil.copy2(ROOT / filename, target / filename)
        install = subprocess.run([command, "ci", "--offline", "--ignore-scripts",
                                  "--no-audit", "--no-fund"], cwd=target,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, timeout=150, check=False)
        if install.returncode != 0:
            print(json.dumps({"status": "BLOCKED_LOCK_RECONSTRUCTION",
                              "exitCode": install.returncode,
                              "errorTail": install.stderr[-1500:]}))
            return 1
        probe = subprocess.run([node, "-e",
                                "const p=require('playwright/package.json');"
                                "const v=require('vite/package.json');"
                                "if(p.version!=='1.64.1'||!v.version)process.exit(2);"],
                               cwd=target, timeout=15, capture_output=True,
                               text=True, check=False)
        status = "PASS_OFFLINE_LOCK_RECONSTRUCTION" if probe.returncode == 0 else "LOCKED_PACKAGE_MISMATCH"
        print(json.dumps({"status": status, "npmCiExit": install.returncode,
                          "packageProbeExit": probe.returncode,
                          "isolation": "auto-deleted temporary QA directory",
                          "network": "npm ci --offline"}))
        return 0 if probe.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
