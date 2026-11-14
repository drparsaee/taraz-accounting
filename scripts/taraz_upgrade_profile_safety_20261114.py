"""Independent Taraz upgrade gate and isolated, synthetic-first recovery proof.

Live mode is metadata-only. Backup/restore methods reject live data roots and
require caller-owned QA fixtures and create-only, private destinations. No
installer, launcher, accounting API or financial operation is invoked.
"""
from __future__ import annotations

import argparse
from contextlib import closing
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

sys.dont_write_bytecode = True

LABELS = ("roaming", "local", "bridge")
LIMIT_FILES = 1500
LIMIT_TOTAL = 400 * 1024 * 1024
LIMIT_SINGLE = 110 * 1024 * 1024
SIDECARS = ("-wal", "-shm", "-journal")
BASE_SHA = {
    "current-version.txt": "eb8d72a2c4783965876f89d494d6ecdd3502c814e0229d50cea66eb65169856d",
    "Run-Taraz.cmd": "93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21",
    "versions/1.0.4/Taraz.exe": "9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce",
}


class UpgradeBlocked(RuntimeError):
    """Safety condition cannot be proven."""


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def guard(path: Path, *, directory: bool | None = None) -> None:
    """Reject links, junctions, file reparse points and hardlinked files."""
    if not path.is_absolute():
        raise UpgradeBlocked("Absolute path required")
    for part in (path, *path.parents):
        if not os.path.lexists(part):
            continue
        info = part.lstat()
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & 0x400 or
                (hasattr(part, "is_junction") and part.is_junction())):
            raise UpgradeBlocked("Link or junction refused")
    if directory is True and not path.is_dir():
        raise UpgradeBlocked("Required directory missing")
    if directory is False:
        if not path.is_file() or not stat.S_ISREG(path.lstat().st_mode):
            raise UpgradeBlocked("Expected a regular file")
        if path.lstat().st_nlink != 1:
            raise UpgradeBlocked("Hardlinked file refused")


def _private_dir(path: Path) -> None:
    guard(path.parent, directory=True)
    if os.path.lexists(path):
        raise UpgradeBlocked("Destination exists; no overwrite")
    path.mkdir(mode=0o700)
    guard(path, directory=True)
    if os.name != "nt":
        if stat.S_IMODE(path.stat().st_mode) != 0o700:
            raise UpgradeBlocked("Private directory permission verification failed")
        return
    try:
        who = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                             capture_output=True, text=True, timeout=15, check=True)
        rows = list(csv.reader(io.StringIO(who.stdout)))
        sid = rows[0][-1].strip() if rows and rows[0] else ""
        owner = rows[0][0].strip() if rows and rows[0] else ""
        if not sid.startswith("S-1-"):
            raise UpgradeBlocked("Owner SID could not be established")
        proc = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                               "*" + sid + ":(OI)(CI)F", "SYSTEM:(OI)(CI)F"],
                              capture_output=True, text=True, timeout=20, check=False)
        if proc.returncode:
            raise UpgradeBlocked("Private DACL update failed")
        verify = subprocess.run(["icacls", str(path)], capture_output=True,
                                text=True, timeout=20, check=False)
        acl = verify.stdout.casefold()
        if (verify.returncode or "(i)" in acl or
                any(x in acl for x in ("everyone:(", "built in\\users:(",
                                           "builtin\\users:(", "authenticated users:(")) or
                not any(name.casefold() in acl for name in (sid, owner) if name) or
                "system:(" not in acl):
            raise UpgradeBlocked("Private DACL readback rejected")
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise UpgradeBlocked("Private DACL verification unavailable") from exc


def real_roots() -> dict[str, Path]:
    roaming = os.environ.get("APPDATA")
    local = os.environ.get("LOCALAPPDATA")
    if not roaming or not local:
        raise UpgradeBlocked("Windows profile roots not available")
    return {"roaming": Path(roaming) / "Taraz",
            "local": Path(local) / "Taraz",
            "bridge": Path(local) / "Madar-Taraz-Bridge"}


def _prevent_real_profile(roots: dict[str, Path]) -> None:
    if os.environ.get("APPDATA") and os.environ.get("LOCALAPPDATA"):
        live = real_roots()
        for value in roots.values():
            for real in live.values():
                if os.path.normcase(os.path.abspath(value)) == os.path.normcase(os.path.abspath(real)):
                    raise UpgradeBlocked("Live snapshot is unavailable in this QA-only module")


def _scan(roots: dict[str, Path], *, hashes: bool,
          strict_transients: bool = True) -> dict:
    if set(roots) != set(LABELS):
        raise UpgradeBlocked("All three data roots must be covered")
    entries: dict[str, dict] = {}
    directories: list[str] = []
    total = 0
    sqlite_count = 0
    sidecars = {"walNonzero": 0, "shmNonzero": 0,
                "journalNonzero": 0, "lockFiles": 0}
    for label in LABELS:
        root = roots[label]
        guard(root, directory=True)
        todo = [(root, "")]
        while todo:
            folder, prefix = todo.pop()
            guard(folder, directory=True)
            with os.scandir(folder) as source:
                children = sorted(list(source), key=lambda d: d.name)
            for child in children:
                node = folder / child.name
                guard(node)
                rel = (prefix + "/" if prefix else "") + child.name
                key = label + "/" + rel
                info = node.lstat()
                if stat.S_ISDIR(info.st_mode):
                    directories.append(key)
                    todo.append((node, rel))
                    continue
                guard(node, directory=False)
                lower = child.name.casefold()
                if lower.endswith(".lock"):
                    sidecars["lockFiles"] += 1
                for suffix, category in (("-wal", "walNonzero"),
                                         ("-shm", "shmNonzero"),
                                         ("-journal", "journalNonzero")):
                    if lower.endswith(suffix) and info.st_size:
                        sidecars[category] += 1
                        if strict_transients:
                            raise UpgradeBlocked("Nonempty SQLite WAL/SHM/journal; quiescence unproven")
                total += info.st_size
                if (len(entries) >= LIMIT_FILES or info.st_size > LIMIT_SINGLE or
                        total > LIMIT_TOTAL):
                    raise UpgradeBlocked("QA profile inventory budget exceeded")
                kind = "sqlite" if lower.endswith((".sqlite3", ".sqlite", ".db")) else "file"
                if kind == "sqlite":
                    sqlite_count += 1
                item = {"bytes": info.st_size, "mtimeNs": info.st_mtime_ns, "kind": kind}
                if hashes:
                    item["sha256"] = digest(node)
                entries[key] = item
    if "roaming/standalone-accounting.sqlite3" not in entries:
        raise UpgradeBlocked("Accounting ledger not present")
    if sqlite_count == 0:
        raise UpgradeBlocked("No SQLite files found")
    return {"files": dict(sorted(entries.items())),
            "directories": sorted(directories), "fileCount": len(entries),
            "sqliteCount": sqlite_count, "totalBytes": total,
            "sidecars": sidecars}


def _check_sqlite(path: Path) -> dict:
    guard(path, directory=False)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise UpgradeBlocked("SQLite integrity validation failed")
        return {"integrity": "ok", "userVersion": int(
            connection.execute("PRAGMA user_version").fetchone()[0])}
    except sqlite3.DatabaseError as exc:
        raise UpgradeBlocked("Invalid SQLite database") from exc
    finally:
        connection.close()


def _copy_exact(source: Path, target: Path) -> None:
    guard(source, directory=False)
    guard(target.parent, directory=True)
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer, 1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())


def _backup_sqlite(source: Path, target: Path) -> None:
    guard(source, directory=False)
    guard(target.parent, directory=True)
    with target.open("xb"):
        pass
    # Online backup creates a coherent SQLite file even when its source uses WAL.
    # Full profile coherence separately requires source quiescence/digest stability.
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=3)) as src:
            src.execute("PRAGMA query_only=ON")
            with closing(sqlite3.connect(str(target), timeout=3)) as dst:
                src.backup(dst, pages=128, sleep=0.02)
        _check_sqlite(target)
        for suffix in SIDECARS:
            if (target.parent / (target.name + suffix)).exists():
                raise UpgradeBlocked("SQLite backup emitted an unexpected transient file")
        with target.open("r+b") as written:
            os.fsync(written.fileno())
    except sqlite3.DatabaseError as exc:
        raise UpgradeBlocked("SQLite backup failed") from exc


def _source_file(roots: dict[str, Path], name: str) -> Path:
    label, slash, relative = name.partition("/")
    if (not slash or label not in roots or not relative or
            "\\" in relative or ":" in relative or "\x00" in relative or
            any(part in ("", ".", "..") for part in relative.split("/"))):
        raise UpgradeBlocked("Unsafe manifest key")
    return roots[label].joinpath(*relative.split("/"))


def _listed_files(folder: Path) -> tuple[set[str], set[str]]:
    guard(folder, directory=True)
    files: set[str] = set()
    dirs: set[str] = set()
    for base, directory_names, names in os.walk(folder, followlinks=False):
        base_path = Path(base)
        for dirname in directory_names:
            p = base_path / dirname
            guard(p, directory=True)
            rel = p.relative_to(folder).as_posix()
            if rel not in LABELS:
                dirs.add(rel)
        for name in names:
            p = base_path / name
            guard(p, directory=False)
            files.add(p.relative_to(folder).as_posix())
    return files, dirs


def verify_snapshot(folder: Path, *, expected_sha: str | None = None) -> dict:
    guard(folder, directory=True)
    manifest = folder / "snapshot-manifest.json"
    marker = folder / "snapshot-manifest.sha256"
    guard(manifest, directory=False)
    guard(marker, directory=False)
    actual = digest(manifest)
    if (marker.read_text(encoding="ascii") != actual + "\n" or
            (expected_sha is not None and actual != expected_sha)):
        raise UpgradeBlocked("Snapshot manifest checksum mismatch")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (type(data) is not dict or data.get("format") != "taraz-upgrade-qa-v1" or
            data.get("complete") is not True or type(data.get("files")) is not dict or
            type(data.get("directories")) is not list or
            len(data["files"]) > LIMIT_FILES):
        raise UpgradeBlocked("Snapshot manifest schema rejected")
    file_root = folder / "files"
    found, directories = _listed_files(file_root)
    if found != set(data["files"]) or directories != set(data["directories"]):
        raise UpgradeBlocked("Snapshot file/directory inventory mismatch")
    count_db = 0
    size_total = 0
    for name, record in data["files"].items():
        p = _source_file({label: file_root / label for label in LABELS}, name)
        if (type(record) is not dict or set(record) !=
                {"bytes", "sha256", "sourceSha256", "kind", "sqliteCheck"} or
                record["kind"] not in ("sqlite", "file") or
                type(record["bytes"]) is not int or record["bytes"] < 0 or
                type(record["sha256"]) is not str or
                type(record["sourceSha256"]) is not str or
                not re.fullmatch(r"[a-f0-9]{64}", record["sha256"]) or
                not re.fullmatch(r"[a-f0-9]{64}", record["sourceSha256"])):
            raise UpgradeBlocked("Malformed manifest member")
        guard(p, directory=False)
        if p.stat().st_size != record["bytes"] or digest(p) != record["sha256"]:
            raise UpgradeBlocked("Snapshot member checksum mismatch")
        if record["kind"] == "sqlite":
            count_db += 1
            if _check_sqlite(p) != record["sqliteCheck"]:
                raise UpgradeBlocked("SQLite snapshot changed")
        elif record["sqliteCheck"] is not None:
            raise UpgradeBlocked("Unexpected SQLite entry metadata")
        size_total += record["bytes"]
    if (data.get("fileCount") != len(found) or
            data.get("sqliteCount") != count_db or
            data.get("totalBytes") != size_total):
        raise UpgradeBlocked("Snapshot totals mismatch")
    return {"status": "VERIFIED_QA_SNAPSHOT", "fileCount": len(found),
            "sqliteCount": count_db, "totalBytes": size_total, "manifestSha256": actual}


def make_synthetic_snapshot(roots: dict[str, Path], destination: Path) -> dict:
    """Create a private, comprehensive QA backup, with source readback checks."""
    _prevent_real_profile(roots)
    guard(destination.parent, directory=True)
    for root in roots.values():
        if os.path.commonpath((os.path.abspath(root), os.path.abspath(destination))) == os.path.abspath(root):
            raise UpgradeBlocked("Backup destination inside source profile")
    initial = _scan(roots, hashes=True)
    _private_dir(destination)
    files = destination / "files"
    files.mkdir(mode=0o700)
    for label in LABELS:
        (files / label).mkdir(mode=0o700)
    for name in initial["directories"]:
        target = files.joinpath(*name.split("/"))
        target.mkdir(mode=0o700)
    members: dict[str, dict] = {}
    for name, item in initial["files"].items():
        source = _source_file(roots, name)
        target = _source_file({label: files / label for label in LABELS}, name)
        if item["kind"] == "sqlite":
            _backup_sqlite(source, target)
            checks = _check_sqlite(target)
        else:
            _copy_exact(source, target)
            checks = None
        copied = digest(target)
        if item["kind"] == "file" and copied != item["sha256"]:
            raise UpgradeBlocked("Copied non-SQLite file digest mismatch")
        members[name] = {"bytes": target.stat().st_size, "sha256": copied,
                         "sourceSha256": item["sha256"], "kind": item["kind"],
                         "sqliteCheck": checks}
    if _scan(roots, hashes=True) != initial:
        raise UpgradeBlocked("Source changed during cross-file snapshot")
    completed = {"format": "taraz-upgrade-qa-v1", "complete": True,
                 "files": members, "directories": initial["directories"],
                 "fileCount": len(members), "sqliteCount": initial["sqliteCount"],
                 "totalBytes": sum(member["bytes"] for member in members.values())}
    manifest = destination / "snapshot-manifest.json"
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(completed, stream, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    with (destination / "snapshot-manifest.sha256").open("x", encoding="ascii") as stream:
        stream.write(digest(manifest) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return verify_snapshot(destination)


def restore_isolated(snapshot: Path, destination: Path,
                     *, expected_sha: str) -> dict:
    """Restore only into a new QA directory and prove byte/SQLite recovery."""
    result = verify_snapshot(snapshot, expected_sha=expected_sha)
    guard(destination.parent, directory=True)
    if not any(part.lower().startswith("qa") or "qa-" in part.lower()
               for part in destination.parts):
        raise UpgradeBlocked("Isolated QA-only restore location required")
    if (os.path.commonpath((os.path.abspath(snapshot), os.path.abspath(destination))) == os.path.abspath(snapshot)):
        raise UpgradeBlocked("Restore cannot be nested inside backup")
    _private_dir(destination)
    info = json.loads((snapshot / "snapshot-manifest.json").read_text(encoding="utf-8"))
    for label in LABELS:
        (destination / label).mkdir(mode=0o700)
    for directory in info["directories"]:
        destination.joinpath(*directory.split("/")).mkdir(mode=0o700)
    for name, member in info["files"].items():
        source = snapshot / "files" / name
        target = destination / name
        _copy_exact(source, target)
        if digest(target) != member["sha256"]:
            raise UpgradeBlocked("Isolated restore digest mismatch")
        if member["kind"] == "sqlite" and _check_sqlite(target) != member["sqliteCheck"]:
            raise UpgradeBlocked("Restored SQLite integrity failed")
    observed, dirs = _listed_files(destination)
    if observed != set(info["files"]) or dirs != set(info["directories"]):
        raise UpgradeBlocked("Restored directory tree differs from manifest")
    if verify_snapshot(snapshot, expected_sha=expected_sha) != result:
        raise UpgradeBlocked("Source snapshot changed during restore")
    return {"status": "RESTORED_ISOLATED_QA", "fileCount": len(observed),
            "sqliteCount": result["sqliteCount"], "manifestSha256": expected_sha}


def live_preflight() -> dict:
    """Inventory only; no live reads of financial rows and no snapshot."""
    installed = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Taraz"
    versions = {}
    for relative, expected in BASE_SHA.items():
        path = installed.joinpath(*relative.split("/"))
        guard(path, directory=False)
        versions[relative] = digest(path) == expected
    pointer = installed / "current-version.txt"
    if pointer.read_text(encoding="utf-8-sig").strip() != "1.0.4":
        raise UpgradeBlocked("Installed pointer is not 1.0.4")
    candidates = Path(__file__).resolve().parents[3] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.6-aaas"
    available = []
    if candidates.is_dir():
        for build in candidates.glob("build-*/build-report.json"):
            guard(build, directory=False)
            report = json.loads(build.read_text(encoding="utf-8"))
            exe = build.parent / "binary" / "Taraz.exe"
            if (report.get("version") == "1.0.6" and
                    report.get("status") == "V106_AAAS_NON_QA_BUILT_NOT_INSTALLED" and
                    exe.is_file()):
                guard(exe, directory=False)
                available.append({"build": build.parent.name, "sha256": digest(exe),
                                  "reportHashMatches": digest(exe) == report.get("exeSha256"),
                                  "mtimeNs": exe.stat().st_mtime_ns})
    available.sort(key=lambda x: x["mtimeNs"], reverse=True)
    roots = real_roots()
    reasons = []
    try:
        observed = _scan(roots, hashes=False, strict_transients=False)
        size, count, databases = observed["totalBytes"], observed["fileCount"], observed["sqliteCount"]
        sidecars = observed["sidecars"]
        if any(sidecars[k] for k in ("walNonzero", "shmNonzero", "journalNonzero")):
            reasons.append("Nonempty SQLite WAL/SHM/journal; quiescence unproven")
    except UpgradeBlocked as exc:
        reasons.append(str(exc))
        size = count = databases = None
        sidecars = None
    official = candidates / "Install-Activate-Taraz-v1.0.6-FINAL-WHEN-CLOSED.cmd"
    launcher_build = None
    if official.is_file():
        guard(official, directory=False)
        content = official.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"build-[0-9a-f]{12}", content)
        if match:
            launcher_build = match.group(0)
    if available and launcher_build != available[0]["build"]:
        reasons.append("Official activation entrypoint targets a different build from latest timestamped candidate")
    # This gate cannot claim global process quiescence, future migration parity
    # or restore of a live profile. No production activation is authorized.
    reasons.append("Cross-database quiescence and live restore have not been proven")
    return {"status": "BLOCKED_FOR_LIVE_UPGRADE", "installed": "1.0.4",
            "installedHashesMatch": all(versions.values()),
            "candidateCount": len(available), "latestCandidate": available[0] if available else None,
            "officialActivationBuild": launcher_build,
            "dataRootsPresent": {label: path.is_dir() for label, path in roots.items()},
            "fileCount": count, "sqliteCount": databases, "totalBytes": size,
            "transientFileCounts": sidecars,
            "blockers": reasons, "liveSnapshotTaken": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Taraz read-only live upgrade preflight")
    parser.add_argument("--live-preflight", action="store_true")
    args = parser.parse_args()
    if not args.live_preflight:
        parser.error("Only --live-preflight is available on real profiles")
    try:
        print(json.dumps(live_preflight(), ensure_ascii=False, sort_keys=True, indent=2))
    except (UpgradeBlocked, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED_FOR_LIVE_UPGRADE", "reason": str(exc),
                          "liveSnapshotTaken": False}, ensure_ascii=False))
        sys.exit(2)
