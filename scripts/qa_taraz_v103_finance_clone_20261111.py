"""Read-only Taraz v1.0.3 financial acceptance on a private OFFLINE backup clone.

Never connects to an installed user profile or executes the non-QA EXE.
Only independently pinned v1.0.3 cold-backup files may be copied. All database
inspection happens on the clone through immutable, query-only SQLite handles.
Synthetic accounting transactions execute in a SEPARATE virgin test database.
No real financial records are posted, echoed to reports, or used in test writes.
"""
from __future__ import annotations

from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import sys
import uuid

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.qa_taraz_v101_upgrade_acceptance_20261110 import secure_private_directory
from standalone_accounting import AccountingRevisionConflict, StandaloneAccountingStore
from standalone_accounting_backup import _check_snapshot

QA_PARENT = (PROJECT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" /
             "taraz-v1.0.3-p1")
BACKUP = (PROJECT.parents[1] / "MTR-REAL-UPGRADE-BACKUPS-20261110" /
          "taraz-v103-cold-20261111")
CANDIDATE = QA_PARENT / "build-eb9d4f2ab076" / "binary" / "Taraz.exe"
EXPECTED_CANDIDATE_SHA = "e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c"
EXPECTED_MANIFEST_SHA = "8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d"
EXPECTED_ACCEPTANCE_SHA = "68bb6e26b9a9a10818e6752a7cc1475a3861c5f380f2021eb5c112a74cd7d2c9"
EXPECTED_FILE_COUNT = 181
EXPECTED_TOTAL_BYTES = 124_011_875
EXPECTED_SQLITE_COUNT = 67
MAX_FILES = 1_000
MAX_BYTES = 300 * 1024 * 1024
MAX_SINGLE = 100 * 1024 * 1024
MAX_JSON = 2 * 1024 * 1024
HEX_SHA = re.compile(r"[a-f0-9]{64}\Z")
FINANCE = "roaming/standalone-accounting.sqlite3"


class FinanceCloneBlocked(RuntimeError):
    """No financial acceptance evidence is issued when a prerequisite fails."""


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def regular(path: Path, *, directory: bool = False) -> Path:
    path = Path(path).absolute()
    for component in (path, *path.parents):
        if component.is_symlink() or (component.exists() and
                getattr(component.lstat(), "st_file_attributes", 0) & 0x400):
            raise FinanceCloneBlocked("Symlink or junction forbidden")
    if directory:
        if not path.is_dir():
            raise FinanceCloneBlocked("Required directory unavailable")
    elif not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise FinanceCloneBlocked("Required regular file unavailable")
    return path


def safe_relative(name: object) -> Path:
    if (not isinstance(name, str) or len(name) > 500 or
            "\\" in name or ":" in name or name.startswith("/") or
            name.endswith("/") or "//" in name):
        raise FinanceCloneBlocked("Unsafe backup member")
    parts = PurePosixPath(name).parts
    if (len(parts) < 2 or parts[0] not in ("roaming", "local", "bridge")
            or any(p in ("", ".", "..") or p.endswith((" ", ".")) for p in parts)
            or any(re.search(r'[<>|"?*\x00-\x1f]', p) for p in parts)):
        raise FinanceCloneBlocked("Unsafe backup member")
    return Path(*parts)


def read_json(path: Path) -> dict:
    regular(path)
    if path.stat().st_size > MAX_JSON:
        raise FinanceCloneBlocked("Unbounded attestation")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise FinanceCloneBlocked("Invalid attestation JSON") from exc
    if not isinstance(value, dict):
        raise FinanceCloneBlocked("Unexpected attestation shape")
    return value


def attestation(backup: Path = BACKUP) -> tuple[dict, dict]:
    regular(backup, directory=True)
    regular(backup / "files", directory=True)
    manifest_file, report_file = (
        backup / "snapshot-manifest.json", backup / "backup-acceptance-report.json")
    if sha(regular(manifest_file)) != EXPECTED_MANIFEST_SHA:
        raise FinanceCloneBlocked("Fresh backup manifest pin mismatch")
    if sha(regular(report_file)) != EXPECTED_ACCEPTANCE_SHA:
        raise FinanceCloneBlocked("Independent backup acceptance pin mismatch")
    manifest, report = read_json(manifest_file), read_json(report_file)
    entries, sqlite_checks = manifest.get("files"), manifest.get("sqliteChecks")
    witness = report.get("backup")
    if (manifest.get("schemaVersion") != 1
            or manifest.get("verifiedNoOverwrite") is not True
            or manifest.get("allFilesIncluded") is not True
            or manifest.get("fileCount") != EXPECTED_FILE_COUNT
            or manifest.get("totalBytes") != EXPECTED_TOTAL_BYTES
            or not isinstance(entries, dict) or len(entries) != EXPECTED_FILE_COUNT
            or not isinstance(sqlite_checks, dict) or len(sqlite_checks) != EXPECTED_SQLITE_COUNT
            or FINANCE not in entries or FINANCE not in sqlite_checks
            or report.get("status") != "VERIFIED_REAL_DATA_BACKUP_PRODUCTION_PENDING"
            or report.get("installedBefore") != "1.0.2"
            or report.get("installedAfter") != "1.0.2"
            or not isinstance(witness, dict)
            or witness.get("backupRoot") != str(backup)
            or witness.get("manifestSha256") != EXPECTED_MANIFEST_SHA
            or witness.get("independentReadback") is not True
            or witness.get("fileCount") != EXPECTED_FILE_COUNT
            or witness.get("totalBytes") != EXPECTED_TOTAL_BYTES
            or witness.get("sqliteValidatedCount") != EXPECTED_SQLITE_COUNT):
        raise FinanceCloneBlocked("Pinned cold-backup acceptance evidence does not agree")
    total, seen = 0, set()
    for name, detail in entries.items():
        relative = safe_relative(name)
        key = str(relative).casefold()
        if key in seen:
            raise FinanceCloneBlocked("Case-fold duplicate backup name")
        seen.add(key)
        if (not isinstance(detail, dict)
                or not isinstance(detail.get("bytes"), int)
                or not 0 <= detail["bytes"] <= MAX_SINGLE
                or not isinstance(detail.get("sha256"), str)
                or not HEX_SHA.fullmatch(detail["sha256"])):
            raise FinanceCloneBlocked("Invalid backup file evidence")
        total += detail["bytes"]
        if total > MAX_BYTES:
            raise FinanceCloneBlocked("Backup exceeds approved budget")
        if str(relative).lower().endswith(".sqlite3") and name not in sqlite_checks:
            raise FinanceCloneBlocked("SQLite member lacks integrity attestation")
    if total != EXPECTED_TOTAL_BYTES:
        raise FinanceCloneBlocked("Aggregate cold-backup bytes mismatch")
    if sum(name.endswith(".sqlite3") for name in entries) != EXPECTED_SQLITE_COUNT:
        raise FinanceCloneBlocked("Unexpected SQLite inventory")
    return manifest, report


def candidate_pin() -> str:
    if sha(regular(CANDIDATE)) != EXPECTED_CANDIDATE_SHA:
        raise FinanceCloneBlocked("Frozen v1.0.3 executable SHA changed")
    return EXPECTED_CANDIDATE_SHA


def inventory_files(files_root: Path, entries: dict) -> dict[str, tuple[int, str, int]]:
    """Check actual file SET, every SHA, size, metadata. Never open SQLite."""
    regular(files_root, directory=True)
    found: set[str] = set()
    observed = {}
    for base, dirs, names in os.walk(files_root, followlinks=False):
        for folder in dirs:
            regular(Path(base) / folder, directory=True)
        for name in names:
            path = regular(Path(base) / name)
            relative = path.relative_to(files_root).as_posix()
            safe_relative(relative)
            if relative not in entries or relative in found:
                raise FinanceCloneBlocked("Undeclared backup file")
            found.add(relative)
            details = entries[relative]
            st = path.stat()
            if st.st_size != details["bytes"] or sha(path) != details["sha256"]:
                raise FinanceCloneBlocked("Backup member SHA/length changed")
            observed[relative] = (st.st_size, details["sha256"], st.st_mtime_ns)
    if found != set(entries):
        raise FinanceCloneBlocked("Missing backup member")
    return observed


def clone_snapshot(src: Path, dst: Path, entries: dict) -> None:
    """Copy exactly the approved offline backup inventory, create-only."""
    regular(src, directory=True)
    if dst.exists() or dst.is_symlink():
        raise FinanceCloneBlocked("Clone destination already exists")
    dst.mkdir(exist_ok=False)
    for name in sorted(entries):
        rel = safe_relative(name)
        origin = regular(src / rel)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        regular(target.parent, directory=True)
        if target.exists() or target.is_symlink():
            raise FinanceCloneBlocked("Clone overwrite prohibited")
        with origin.open("rb") as reader, target.open("xb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        if target.stat().st_size != entries[name]["bytes"] or sha(target) != entries[name]["sha256"]:
            raise FinanceCloneBlocked("Byte-for-byte clone copy mismatch")


def _open_readonly_sqlite(path: Path):
    regular(path)
    # immutable=1 reads precisely one frozen backup file, never writes or
    # checkpoints the clone. Non-empty WAL sidecars are explicitly rejected.
    for suffix in ("-wal", "-shm"):
        sibling = path.with_name(path.name + suffix)
        if sibling.exists() and suffix == "-wal" and sibling.stat().st_size:
            raise FinanceCloneBlocked("Uncheckpointed WAL cannot be audited as immutable")
        if sibling.is_symlink():
            raise FinanceCloneBlocked("Linked SQLite sidecar")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1",
                                 uri=True, timeout=5, isolation_level=None)
    try:
        connection.execute("PRAGMA query_only=ON")
        return connection
    except BaseException:
        connection.close()
        raise


def finance_sqlite_invariants(root: Path, manifest: dict) -> dict:
    """Inspect copied SQLite metadata, ledger revision/digest, no real posting."""
    snapshots = {}
    for name, witness in sorted(manifest["sqliteChecks"].items()):
        if name not in manifest["files"] or not name.endswith(".sqlite3"):
            raise FinanceCloneBlocked("Untrusted SQLite attestation member")
        path = regular(root / safe_relative(name))
        try:
            with closing(_open_readonly_sqlite(path)) as connection:
                if connection.execute("PRAGMA query_only").fetchone() != (1,):
                    raise FinanceCloneBlocked("Query-only SQLite gate not active")
                check = connection.execute("PRAGMA integrity_check").fetchall()
                if check != [("ok",)]:
                    raise FinanceCloneBlocked("SQLite integrity_check failed")
                user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                schema_version = int(connection.execute("PRAGMA schema_version").fetchone()[0])
                if (witness.get("integrityCheck") != "ok"
                        or type(witness.get("schemaVersion")) is not int
                        or witness["schemaVersion"] != user_version):
                    raise FinanceCloneBlocked("SQLite schema version differs from pinned witness")
                schema = connection.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
                schema_fingerprint = hashlib.sha256(json.dumps(
                    schema, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
                head = None
                if name == FINANCE:
                    # The independent preexisting verifier checks the exact
                    # table columns, revision head and event chain. It reads
                    # copied history into memory but returns ONLY revision.
                    revision = _check_snapshot(connection)
                    rows = connection.execute(
                        "SELECT revision,state,digest FROM standalone_accounting").fetchall()
                    if len(rows) > 1:
                        raise FinanceCloneBlocked("Multiple finance revision heads")
                    if rows:
                        row_revision, state, digest = rows[0]
                        if (type(row_revision) is not int or row_revision != revision
                                or not isinstance(state, bytes)
                                or not isinstance(digest, str)
                                or hashlib.sha256(state).hexdigest() != digest):
                            raise FinanceCloneBlocked("Finance revision/digest not coherent")
                        head = (revision, digest)
                    elif revision != 0:
                        raise FinanceCloneBlocked("Missing revision head")
                    else:
                        head = (0, None)
                snapshots[name] = (user_version, schema_version, schema_fingerprint, head)
        except (sqlite3.DatabaseError, ValueError, TypeError) as exc:
            raise FinanceCloneBlocked("Copied SQLite integrity/schema/revision failure") from exc
    if len(snapshots) != EXPECTED_SQLITE_COUNT or FINANCE not in snapshots:
        raise FinanceCloneBlocked("Expected SQLite coverage incomplete")
    return snapshots


def synthetic_transaction_test(root: Path) -> dict:
    """Actual posting only to an INVENTED, new, separate SQLite ledger."""
    regular(root, directory=True)
    synthetic = root / "synthetic-ledger"
    synthetic.mkdir(exist_ok=False)
    store = StandaloneAccountingStore(synthetic / "synthetic-qa-only.sqlite3",
                                      default_currency="RIAL")
    actor = "clone-qa-test-actor"
    accounts = {actor: {"username": actor, "role": "admin"}}
    stamp = "2026-11-11T12:00:00Z"
    commands = [
        {"type": "party.register", "eventId": "synthetic-party-001",
         "partyId": "synthetic-customer-001", "name": "Synthetic QA Only",
         "kind": "customer"},
        {"type": "invoice.create", "eventId": "synthetic-create-001",
         "invoiceId": "synthetic-invoice-001", "partyId": "synthetic-customer-001",
         "documentDate": "2026-11-11",
         "lines": [{"description": "Synthetic QA Service", "quantity": 1,
                    "unitPrice": 1200}]},
        {"type": "invoice.approve", "eventId": "synthetic-approve-001",
         "invoiceId": "synthetic-invoice-001"},
        {"type": "invoice.issue", "eventId": "synthetic-issue-001",
         "invoiceId": "synthetic-invoice-001", "postingDate": "2026-11-11"},
    ]
    revision = 0
    for entry in commands:
        output = store.command(entry, actor=actor, accounts=accounts,
                               expected_revision=revision, now=stamp)
        revision = output["revision"]
    if revision != len(commands) or store.read(actor=actor, accounts=accounts)["revision"] != 4:
        raise FinanceCloneBlocked("Synthetic ledger transaction revision incorrect")
    replay = store.command(commands[-1], actor=actor, accounts=accounts,
                           expected_revision=revision, now=stamp)
    if replay["revision"] != revision:
        raise FinanceCloneBlocked("Synthetic idempotent issue advanced revision")
    try:
        store.command(commands[-1], actor=actor, accounts=accounts,
                      expected_revision=revision - 1, now=stamp)
    except AccountingRevisionConflict:
        pass
    else:
        raise FinanceCloneBlocked("Synthetic stale revision was accepted")
    with closing(_open_readonly_sqlite(store.path)) as connection:
        checked_revision = _check_snapshot(connection)
    if checked_revision != 4:
        raise FinanceCloneBlocked("Synthetic ledger did not replay reliably")
    return {"transactionsOnSyntheticLedgerOnly": True,
            "newRevisions": revision, "idempotentReplayStable": True,
            "staleRevisionRejected": True, "syntheticLedgerReplayVerified": True}


def audit(*, backup: Path = BACKUP, destination: Path | None = None) -> Path:
    """Create unique ACL-restricted QA output and remove copied finance data."""
    if os.name != "nt":
        raise FinanceCloneBlocked("Windows ACL-restricted financial clone QA required")
    candidate_pin()
    manifest, _ = attestation(backup)
    entries = manifest["files"]
    before = inventory_files(backup / "files", entries)
    regular(QA_PARENT, directory=True)
    run = destination or QA_PARENT / ("finance-clone-gate-" + uuid.uuid4().hex[:12])
    if run.parent.resolve() != QA_PARENT.resolve():
        raise FinanceCloneBlocked("QA output must be direct child of approved candidate root")
    if run.exists() or run.is_symlink():
        raise FinanceCloneBlocked("Refusing existing QA run destination")
    secure_private_directory(run)
    clone = run / "private-offline-copy"
    report_path = run / "finance-clone-report.json"
    record = {"status": "BLOCKED", "version": "1.0.3",
              "originalBackupFiles": EXPECTED_FILE_COUNT,
              "expectedSQLite": EXPECTED_SQLITE_COUNT,
              "originalDataWritten": False, "realTransactionsPosted": False,
              "compiledCandidateLaunched": False, "productionFinanceSignoff": False,
              "privateCloneCleaned": False, "output": str(run)}
    cleanup_error = None
    try:
        clone_snapshot(backup / "files", clone, entries)
        copied_before = inventory_files(clone, entries)
        sqlite_before = finance_sqlite_invariants(clone, manifest)
        synthetic = synthetic_transaction_test(run)
        sqlite_after = finance_sqlite_invariants(clone, manifest)
        copied_after = inventory_files(clone, entries)
        if copied_before != copied_after or sqlite_before != sqlite_after:
            raise FinanceCloneBlocked("Finance clone mutated during inspection")
        original_after = inventory_files(backup / "files", entries)
        if original_after != before:
            raise FinanceCloneBlocked("Original backup mutated during inspection")
        if any(copied_after[k][:2] != before[k][:2] for k in entries):
            raise FinanceCloneBlocked("Clone and offline source hash/length disagree")
        record.update({"status": "CLONE_READONLY_INVARIANTS_PASSED_NO_FINANCE_SIGNOFF",
                       "original181ShaBeforeAfterMatch": True,
                       "clone181ShaBeforeAfterMatch": True,
                       "sqliteIntegrityReadOnlyCount": len(sqlite_after),
                       "sqliteSchemaAndRevisionInvariantsMatch": True,
                       "ledgerDigestAndChainVerifiedOnClone": True,
                       "syntheticLedger": synthetic})
    except Exception as exc:
        record.update({"status": "BLOCKED", "errorType": type(exc).__name__,
                       "error": str(exc) if isinstance(exc, FinanceCloneBlocked)
                       else "Private clone audit failed"})
        raise
    finally:
        # Unique private QA run only. Never recursive-delete an original input.
        if clone.exists():
            try:
                regular(clone, directory=True)
                shutil.rmtree(clone)
            except Exception as exc:
                cleanup_error = exc
        record["privateCloneCleaned"] = not clone.exists() and cleanup_error is None
        if not record["privateCloneCleaned"]:
            record["status"] = "BLOCKED_PRIVATE_CLONE_CLEANUP"
        with report_path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
    if cleanup_error is not None:
        raise FinanceCloneBlocked("Private finance clone cleanup failed") from cleanup_error
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true",
                        help="Read-only pinned backup / artifact and 181-file SHA check")
    parser.add_argument("--audit", action="store_true",
                        help="Copy approved offline backup into private disposable QA only")
    args = parser.parse_args()
    try:
        if args.preflight:
            candidate_pin()
            manifest, _ = attestation()
            before = inventory_files(BACKUP / "files", manifest["files"])
            after = inventory_files(BACKUP / "files", manifest["files"])
            if before != after:
                raise FinanceCloneBlocked("Backup mutated during preflight")
            print(json.dumps({"status": "OFFLINE_PIN_AND_181_HASH_PREFLIGHT_PASS",
                              "backupFilesVerified": len(before),
                              "sqliteManifestCount": len(manifest["sqliteChecks"]),
                              "compiledStartupTested": False}, indent=2))
            return 0
        if args.audit:
            report = audit()
            print(json.dumps(json.loads(report.read_text(encoding="utf-8")), indent=2))
            return 0
        parser.print_help()
        return 0
    except Exception as exc:
        print(f"TARAZ V103 FINANCE CLONE BLOCKED: {type(exc).__name__}: "
              + (str(exc) if isinstance(exc, FinanceCloneBlocked) else "Private audit failure"),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
