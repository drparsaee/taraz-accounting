"""Read-only P0 release reconciliation for the existing Taraz v1.0.2 build.

Compares installed code, its immutable build evidence, the old cold backup,
and the live detached source. A matching SHA is not an approval to release.
No app processes, profiles, network services or installers are invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
PARENT = SOURCE.parents[1]
BUILD = PARENT / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.2-madar-dashboard" / "build-544b6e6bf45b"
BACKUP = PARENT / "MTR-REAL-UPGRADE-BACKUPS-20261110" / "taraz-v102-cold-20261111"
EXPECTED_INSTALLED_SHA = "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52"
EXPECTED_BUILD_REPORT_SHA = "bf362091527d43f2ad6a50ee9f08f6bdb6d46a70a1b7886e0cb5453da12ba68f"
EXPECTED_FROZEN_SOURCE_SHA = "dd38e5bdb43aa6be0dc5f96abcd62d680a5239393fee88a385c202919f86c38e"
EXPECTED_BUNDLE_ZIP_SHA = "1499170aae4fa5cfe4876e7e604db8e20e3172c48722c645c4682210275749c6"
EXPECTED_BACKUP_MANIFEST_SHA = "0817ffeb5178767c292e64e5b73db4814665b67e8465a829c3ffb254fa924767"
EXPECTED_BACKUP_REPORT_SHA = "f7f5ae2915ccafd3eb16c6809c11cd3fb5fee8288ba7bbaedc3e0257803bcf77"
REQUIRED_BUILD_TOOLS = (
    "scripts/build_taraz_v102_madar_dashboard_20261111.py",
    "scripts/build_taraz_v101_local_update_20261110.py",
    "scripts/qa_mtr_taraz_build_20261110.py",
    "scripts/qa_taraz_v101_upgrade_acceptance_20261110.py",
)
EXCLUDED = frozenset(("node_modules", "dist", "release", "build", ".git", "__pycache__"))
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_BACKUP_BYTES = 300 * 1024 * 1024
MAX_BACKUP_FILES = 1000


class AuditError(RuntimeError):
    """Input evidence is incomplete, inconsistent, or unsafe to read."""


def regular(path: Path, *, directory: bool = False) -> Path:
    """Refuse symlinks/junctions at every path component, including ancestors."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and bool(getattr(part.lstat(), "st_file_attributes", 0) & 0x400)):
            raise AuditError("Linked path refused: " + str(part))
    if directory:
        if not path.is_dir():
            raise AuditError("Missing directory: " + str(path))
    elif not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise AuditError("Missing regular file: " + str(path))
    return path


def digest(path: Path) -> str:
    regular(path)
    h = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    regular(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise AuditError("JSON is larger than limit: " + str(path))
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise AuditError("Expected JSON object: " + str(path))
    return value


def is_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def safe_relative(relative: str, allowed: tuple[str, ...] | None = None) -> Path:
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise AuditError("Unsafe relative path")
    parts = PurePosixPath(relative).parts
    if not parts or any(part in ("", ".", "..") for part in parts) or relative.startswith("/"):
        raise AuditError("Unsafe relative path")
    if allowed is not None and parts[0] not in allowed:
        raise AuditError("Unexpected backup root prefix")
    return Path(*parts)


def runtime_inventory(root: Path) -> dict[str, str]:
    """Reimplement the pinned QA builder's source selection without importing it."""
    regular(root, directory=True)
    result: dict[str, str] = {}
    for directory, subdirs, names in os.walk(root, followlinks=False):
        relative_dir = Path(directory).relative_to(root)
        if relative_dir.parts and relative_dir.parts[0] in EXCLUDED:
            subdirs[:] = []
            continue
        subdirs[:] = sorted(d for d in subdirs if d not in EXCLUDED)
        for name in sorted(names):
            relative = relative_dir / name
            if not ((len(relative.parts) == 1 and
                     (name.endswith(".py") or name in ("accounting.html", "vite.config.js", "package.json", "package-lock.json")))
                    or relative.parts[0] in ("src", "public", "assets")):
                continue
            path = root / relative
            result[relative.as_posix()] = digest(path)
    return dict(sorted(result.items()))


def fingerprint(inventory: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(inventory, sort_keys=True).encode("utf-8")).hexdigest()


def compare_frozen(current: dict[str, str], frozen: dict[str, str]) -> dict:
    if any(not is_sha(v) for v in frozen.values()):
        raise AuditError("Frozen source contains invalid SHA")
    return {
        "identical": sorted(k for k in current.keys() & frozen.keys() if current[k] == frozen[k]),
        "changed": sorted(k for k in current.keys() & frozen.keys() if current[k] != frozen[k]),
        "added": sorted(current.keys() - frozen.keys()),
        "removed": sorted(frozen.keys() - current.keys()),
    }


def git_snapshot(root: Path) -> dict:
    def git(*args: str) -> bytes:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                timeout=15, check=False)
        if result.returncode:
            raise AuditError("Git inspection failed: " + result.stderr.decode("utf-8", "replace")[:300])
        return result.stdout

    head = git("rev-parse", "HEAD").decode("ascii").strip()
    # `symbolic-ref` returns 1 on detached HEAD, so use `branch --show-current`.
    branch = git("branch", "--show-current").decode("utf-8", "replace").strip() or None
    raw = git("status", "--porcelain=v1", "-z", "-uall")
    entries: list[dict[str, str]] = []
    items = raw.split(b"\0")
    pos = 0
    while pos < len(items) and items[pos]:
        record = items[pos]
        if len(record) < 4:
            raise AuditError("Malformed git status record")
        code = record[:2].decode("ascii", "replace")
        name = record[3:].decode("utf-8", "surrogateescape")
        entries.append({"status": code, "path": name})
        pos += 1
        if "R" in code or "C" in code:
            if pos >= len(items) or not items[pos]:
                raise AuditError("Malformed git rename record")
            entries[-1]["from"] = items[pos].decode("utf-8", "surrogateescape")
            pos += 1
    return {
        "head": head, "branch": branch, "detached": branch is None,
        "changedCount": len(entries),
        "trackedDirty": sorted(e["path"] for e in entries if e["status"] != "??"),
        "untracked": sorted(e["path"] for e in entries if e["status"] == "??"),
    }


def installed_state(installed_root: Path, expected_sha: str) -> dict:
    regular(installed_root, directory=True)
    pointer = installed_root / "current-version.txt"
    launcher = installed_root / "Run-Taraz.cmd"
    regular(pointer)
    regular(launcher)
    version = pointer.read_text(encoding="utf-8-sig").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise AuditError("Invalid installed version pointer")
    exe = installed_root / "versions" / version / "Taraz.exe"
    result = {
        "version": version,
        "pointerSha256": digest(pointer),
        "launcherSha256": digest(launcher),
        "launcherVersioned": "versions\\%TARAZ_VERSION%\\Taraz.exe" in launcher.read_text(encoding="utf-8", errors="replace"),
        "exeSha256": digest(exe),
        "exeBytes": exe.stat().st_size,
    }
    result["matchesCandidate"] = result["exeSha256"] == expected_sha
    return result


def _check_hash(path: Path, expected: object) -> bool:
    return is_sha(expected) and digest(path) == expected


def verify_candidate(build: Path, report: dict) -> dict:
    """Check independent binary, manifest, scripts and archived byte parity."""
    regular(build, directory=True)
    offline = build / "offline-update"
    manifest_file = offline / "update-manifest.json"
    snapshot_file = offline / "source-sha256.json"
    manifest = read_json(manifest_file)
    frozen = read_json(snapshot_file)
    expected = report.get("exeSha256")
    if not is_sha(expected):
        raise AuditError("Missing candidate executable SHA")
    actual_bin = build / "binary" / "Taraz.exe"
    package_bin = offline / "Taraz.exe"
    expected_items = {
        "exe": actual_bin,
        "manifest": manifest_file,
        "installScript": offline / "Install-Taraz-V102.ps1",
        "activationScript": offline / "Activate-Taraz-V102.ps1",
    }
    hashes = {name: digest(path) for name, path in expected_items.items()}
    hashes["offlineExe"] = digest(package_bin)
    hashes["sourceManifest"] = digest(snapshot_file)
    for key, path in expected_items.items():
        actual = Path(report.get(key, ""))
        if actual != path or not _check_hash(path, report.get(key + "Sha256")):
            raise AuditError("Build report path/hash mismatch: " + key)
    if not (_check_hash(actual_bin, expected) and hashes["offlineExe"] == expected):
        raise AuditError("Candidate and copied executable SHA disagree")
    if not (_check_hash(snapshot_file, manifest.get("sourceFileManifestSha256"))
            and hashes["sourceManifest"] == manifest.get("sourceFileManifestSha256")):
        raise AuditError("Frozen source manifest SHA mismatch")
    if report.get("sourceFreezeSha256") != fingerprint(frozen) or manifest.get("sourceSnapshotSha256") != fingerprint(frozen):
        raise AuditError("Candidate source fingerprint mismatch")
    if report.get("sourceInputCount") != len(frozen) or manifest.get("sourceFilesCount") != len(frozen):
        raise AuditError("Candidate source file count mismatch")
    if not (manifest.get("exeSha256") == expected
            and manifest.get("exeBytes") == actual_bin.stat().st_size
            and manifest.get("targetVersion") == report.get("version")
            and manifest.get("peVersion") == report.get("compiled", {}).get("peVersion")):
        raise AuditError("Candidate EXE metadata disagree")

    zip_path = build / "Taraz-v1.0.2-MADAR-DASHBOARD-OFFLINE-UPDATE.zip"
    if Path(report.get("zip", "")) != zip_path or not _check_hash(zip_path, report.get("zipSha256")):
        raise AuditError("ZIP hash or report path mismatch")
    expected_files = {
        "Taraz.exe": package_bin,
        "Install-Taraz-V102.ps1": expected_items["installScript"],
        "Activate-Taraz-V102.ps1": expected_items["activationScript"],
        "source-sha256.json": snapshot_file,
        "update-manifest.json": manifest_file,
    }
    with zipfile.ZipFile(zip_path, "r") as archive:
        members = archive.infolist()
        if len(members) != len(expected_files) or set(x.filename for x in members) != set(expected_files):
            raise AuditError("ZIP entry list differs from unpacked bundle")
        for member in members:
            safe_relative(member.filename)
            if member.is_dir() or member.file_size > 70 * 1024 * 1024:
                raise AuditError("Unexpected ZIP member type or size")
            with archive.open(member, "r") as content:
                h = hashlib.sha256()
                for chunk in iter(lambda: content.read(1024 * 1024), b""):
                    h.update(chunk)
            if h.hexdigest() != digest(expected_files[member.filename]):
                raise AuditError("ZIP member differs from unpacked file: " + member.filename)

    return {
        "status": "HASH_PARITY_VERIFIED", "version": report.get("version"),
        "exeSha256": expected, "exeBytes": actual_bin.stat().st_size,
        "sourceFreezeSha256": fingerprint(frozen), "sourceInputCount": len(frozen),
        "zipSha256": digest(zip_path), "zipMembersVerified": len(expected_files),
        "candidateUnsignedReported": manifest.get("unsigned"),
        "candidateNotInstalledAtBuildReported": report.get("installed") is False,
        "manifest": manifest, "frozen": frozen,
    }


def verify_backup(root: Path, reported: dict) -> dict:
    regular(root, directory=True)
    manifest_file = root / "snapshot-manifest.json"
    report_file = root / "backup-acceptance-report.json"
    manifest = read_json(manifest_file)
    report = read_json(report_file)
    if not (_check_hash(manifest_file, reported.get("manifestSha256"))
            and _check_hash(report_file, reported.get("reportSha256"))):
        raise AuditError("Cold backup witness SHA changed")
    files = manifest.get("files")
    if not isinstance(files, dict) or not (1 <= len(files) <= MAX_BACKUP_FILES):
        raise AuditError("Invalid cold backup file inventory")
    if len(files) != manifest.get("fileCount") or manifest.get("fileCount") != reported.get("fileCount"):
        raise AuditError("Cold backup file counts disagree")
    if (manifest.get("verifiedNoOverwrite") is not True
            or manifest.get("allFilesIncluded") is not True
            or not isinstance(manifest.get("sqliteChecks"), dict)
            or len(manifest["sqliteChecks"]) != reported.get("sqliteValidatedCount")):
        raise AuditError("Cold backup readback/SQLite witness incomplete")
    actual_bytes = 0
    expected_names: set[str] = set()
    for relative, item in sorted(files.items()):
        relative_path = safe_relative(relative, ("roaming", "local", "bridge"))
        expected_names.add(relative_path.as_posix())
        full = root / "files" / relative_path
        regular(full)
        if not isinstance(item, dict) or not is_sha(item.get("sha256")):
            raise AuditError("Invalid backup entry")
        byte_count = full.stat().st_size
        if byte_count != item.get("bytes") or not _check_hash(full, item.get("sha256")):
            raise AuditError("Cold backup file changed: " + relative)
        actual_bytes += byte_count
        if actual_bytes > MAX_BACKUP_BYTES:
            raise AuditError("Cold backup above size cap")
    actual_names: set[str] = set()
    for current, subdirs, names in os.walk(root / "files", followlinks=False):
        for subdir in subdirs:
            regular(Path(current) / subdir, directory=True)
        for name in names:
            full = Path(current) / name
            regular(full)
            actual_names.add(full.relative_to(root / "files").as_posix())
    if expected_names != actual_names or actual_bytes != manifest.get("totalBytes") or actual_bytes != reported.get("totalBytes"):
        raise AuditError("Cold backup file set or byte total changed")
    witness = report.get("backup", {})
    if (report.get("status") != "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING"
            or not isinstance(witness, dict)
            or witness.get("independentReadback") is not True
            or witness.get("manifestSha256") != digest(manifest_file)
            or witness.get("fileCount") != len(files)
            or witness.get("totalBytes") != actual_bytes
            or witness.get("sqliteValidatedCount") != len(manifest["sqliteChecks"])):
        raise AuditError("Cold backup reported witness inconsistent")
    return {
        "status": "COPIED_BYTES_AND_WITNESS_MATCH", "filesHashed": len(files),
        "bytesHashed": actual_bytes, "sqliteChecksReported": len(manifest["sqliteChecks"]),
        "backupCapturedFromVersion": report.get("installedBefore"),
        "backupCapturedToVersion": report.get("installedAfter"),
        "sqliteIntegrityRerun": False,
    }


def inspect(root: Path = SOURCE, build: Path = BUILD, backup: Path = BACKUP,
            installed: Path | None = None) -> dict:
    if installed is None:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise AuditError("LOCALAPPDATA not available")
        installed = Path(local) / "Programs" / "Taraz"
    record: dict = {"decision": "NO_GO", "scope": "static-read-only-P0-release-inventory",
                    "build": str(build), "source": str(root), "checks": {}, "gates": []}
    gates: list[str] = record["gates"]

    report = read_json(build / "build-report.json")
    record["buildReport"] = {"statusAtBuild": report.get("status"), "version": report.get("version")}
    record["buildReport"]["sha256"] = digest(build / "build-report.json")
    if record["buildReport"]["sha256"] != EXPECTED_BUILD_REPORT_SHA:
        gates.append("v102_build_report_differs_from_pinned_witness")
    try:
        candidate = verify_candidate(build, report)
        frozen = candidate.pop("frozen")
        manifest = candidate.pop("manifest")
        record["checks"]["candidateBundle"] = candidate
        if (candidate["sourceFreezeSha256"] != EXPECTED_FROZEN_SOURCE_SHA
                or candidate["zipSha256"] != EXPECTED_BUNDLE_ZIP_SHA):
            gates.append("v102_artifacts_differ_from_pinned_reference")
    except (AuditError, OSError, ValueError, zipfile.BadZipFile) as error:
        record["checks"]["candidateBundle"] = {"status": "FAILED", "error": str(error)}
        gates.append("candidate_artifact_parity_unverified")
        frozen = None
        manifest = {}

    try:
        current = runtime_inventory(root)
        record["checks"]["source"] = {"currentFingerprint": fingerprint(current), "sourceInputCount": len(current)}
        if frozen is not None:
            comparison = compare_frozen(current, frozen)
            record["checks"]["source"]["againstV102Freeze"] = comparison
            record["checks"]["source"]["counts"] = {k: len(v) for k, v in comparison.items()}
            if comparison["changed"] or comparison["added"] or comparison["removed"]:
                gates.append("source_drift_from_v102_frozen_candidate")
    except (AuditError, OSError, ValueError) as error:
        record["checks"]["source"] = {"status": "FAILED", "error": str(error)}
        gates.append("source_fingerprint_unverified")

    try:
        state = installed_state(installed, EXPECTED_INSTALLED_SHA)
        record["checks"]["installed"] = state
        if (state["version"] != report.get("version") or not state["matchesCandidate"]
                or state["exeSha256"] != record["checks"]["candidateBundle"].get("exeSha256")):
            gates.append("installed_v102_candidate_sha_or_version_mismatch")
        if not state["launcherVersioned"]:
            gates.append("installed_versioned_launcher_contract_failed")
    except (AuditError, OSError, ValueError) as error:
        state = {}
        record["checks"]["installed"] = {"status": "FAILED", "error": str(error)}
        gates.append("installed_executable_unverified")

    try:
        backup_state = verify_backup(backup, report.get("backup", {}))
        record["checks"]["backup"] = backup_state
        if (report.get("backup", {}).get("manifestSha256") != EXPECTED_BACKUP_MANIFEST_SHA
                or report.get("backup", {}).get("reportSha256") != EXPECTED_BACKUP_REPORT_SHA):
            gates.append("backup_witness_differs_from_pinned_reference")
        if backup_state["backupCapturedToVersion"] != state.get("version"):
            gates.append("cold_backup_predates_current_installed_version")
    except (AuditError, OSError, ValueError) as error:
        record["checks"]["backup"] = {"status": "FAILED", "error": str(error)}
        gates.append("cold_backup_witness_unverified")

    try:
        record["checks"]["git"] = git_snapshot(root)
        if record["checks"]["git"]["detached"]:
            gates.append("detached_head_release_basis")
        if record["checks"]["git"]["changedCount"]:
            gates.append("working_tree_not_frozen")
    except (AuditError, OSError) as error:
        record["checks"]["git"] = {"status": "FAILED", "error": str(error)}
        gates.append("git_revision_unverified")

    try:
        package = read_json(root / "package.json")
        lock = read_json(root / "package-lock.json")
        versions = [package.get("version"), lock.get("version"), lock.get("packages", {}).get("", {}).get("version")]
        tool_hashes = {relative: digest(root / relative) for relative in REQUIRED_BUILD_TOOLS}
        configured_dist = package.get("scripts", {}).get("dist:rc", "")
        record["checks"]["buildInputs"] = {
            "packageVersions": versions, "buildToolSha256": tool_hashes,
            "builderIncludedInFrozenRuntimeInputs": bool(frozen and any(name.startswith("scripts/") for name in frozen)),
            "distCommand": configured_dist,
            "configuredBuildScriptPresent": (root / "scripts" / "build_integrated_v122.py").is_file(),
        }
        if len(set(versions)) != 1 or versions[0] != state.get("version"):
            gates.append("source_package_version_not_installed_version")
        if not record["checks"]["buildInputs"]["configuredBuildScriptPresent"]:
            gates.append("package_distribution_entrypoint_missing")
    except (AuditError, OSError, ValueError, AttributeError) as error:
        record["checks"]["buildInputs"] = {"status": "FAILED", "error": str(error)}
        gates.append("build_inputs_unverified")

    if state.get("version") == manifest.get("targetVersion"):
        gates.append("existing_v102_install_must_not_be_reinstalled_as_next_release")
    if manifest.get("unsigned") is True:
        gates.append("candidate_reported_unsigned")
    else:
        gates.append("candidate_signature_independently_unverified")
    gates.extend(("fresh_post_v102_backup_and_restore_acceptance_needed",
                  "next_version_binary_and_install_acceptance_missing",
                  "offline_zip_is_not_signed_windows_setup_installer",
                  "release_authorization_not_established"))
    record["gates"] = sorted(set(gates))
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--build", type=Path, default=BUILD)
    parser.add_argument("--backup", type=Path, default=BACKUP)
    parser.add_argument("--installed", type=Path)
    args = parser.parse_args()
    try:
        result = inspect(args.source, args.build, args.backup, args.installed)
    except (AuditError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        result = {"decision": "NO_GO", "error": f"{type(error).__name__}: {error}"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 2  # Every run is a read-only P0 block, never release authorization.


if __name__ == "__main__":
    sys.exit(main())
