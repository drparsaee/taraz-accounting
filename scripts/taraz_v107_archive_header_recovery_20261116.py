"""One-time, fail-closed recovery of a pinned damaged auto-backup SQLite header.

No live ledger modification. The ORIGINAL damaged archive and its exact manifest
are preserved outside the active profile before the two-byte header correction.
Only a byte-exact result already authenticated by the original manifest is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import taraz_v107_hotfix_protected_update_20261116 as update
from standalone_accounting_backup_manifest import verify_completion_manifest
from taraz_three_root_backup_20261114 import _windows_principal

COMPANY = "6fe8b758d2ca74d0a1edcb3509b8dc78"
BAD_NAME = "standalone-accounting-auto-20261116T081947672608Z-52ae1359a84b3032.sqlite3"
GOOD_NAME = "standalone-accounting-auto-20261116T081529467673Z-03483aeeb809b9ad.sqlite3"
BAD_SHA = "d52eb6587366490d9d37f1c2a044e4b2832c98b02015cc9ecd928fa65f079c0c"
EXPECTED_SHA = "f9f78bf35580e9d87499ef76d5ffd58e5607991041bbca3bd458370a182d66cb"
OFFSETS = (27, 95)
RESCUE = Path("D:/CoS-Test/TARAZ-V107-ARCHIVE-HEADER-RECOVERY-20261116-A")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_paths():
    if os.name != "nt" or os.environ.get("TARAZ_QA_MODE"):
        raise update.ReleaseBlocked("Real non-QA Windows principal required")
    _windows_principal()
    app, pointer, launcher, old = update.installed_paths()
    update.safe(app)
    update.safe(pointer, directory=False)
    update.safe(launcher, directory=False)
    update.safe(old, directory=False)
    if pointer.read_text(encoding="utf-8-sig").strip() != "1.0.6" or (
        update.sha(pointer) != update.BASE_POINTER_SHA or
        update.sha(launcher) != update.LAUNCHER_SHA or
        update.sha(old) != update.BASE_EXE_SHA
    ):
        raise update.ReleaseBlocked("Pinned installed 1.0.6 is absent")
    folder = Path(os.environ["APPDATA"]) / "Taraz" / "books" / COMPANY / "standalone-accounting-backups"
    update.safe(folder)
    bad = update.safe(folder / BAD_NAME, directory=False)
    good = update.safe(folder / GOOD_NAME, directory=False)
    bad_manifest = update.safe(bad.with_suffix(".manifest.json"), directory=False)
    update.safe(good.with_suffix(".manifest.json"), directory=False)
    return bad, good, bad_manifest


def content_digest(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise update.ReleaseBlocked("Damaged archive SQLite integrity is not OK")
        tables = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        counts = [(name, db.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0])
                  for name, _ in tables]
        return tables, counts


def prove():
    update.no_live_writers()
    bad, good, manifest = source_paths()
    original, reference, marker = bad.read_bytes(), good.read_bytes(), manifest.read_bytes()
    if sha(original) != BAD_SHA or sha(reference) != EXPECTED_SHA:
        raise update.ReleaseBlocked("Archived source fingerprints differ from pinned witness")
    verify_completion_manifest(good)
    details = json.loads(marker.decode("utf-8"))
    if details.get("files", {}).get("sqlite", {}).get("sha256") != EXPECTED_SHA or (
        details["files"]["sqlite"]["size"] != len(original)
    ):
        raise update.ReleaseBlocked("Original completion manifest does not support recovery")
    differences = tuple(i for i, (a, b) in enumerate(zip(original, reference)) if a != b)
    if len(original) != len(reference) or differences != OFFSETS:
        raise update.ReleaseBlocked("Damage is not limited to the two SQLite header counter bytes")
    candidate = bytearray(original)
    for offset in OFFSETS:
        candidate[offset] = reference[offset]
    candidate = bytes(candidate)
    if sha(candidate) != EXPECTED_SHA or candidate != reference:
        raise update.ReleaseBlocked("Recovered data does not match original manifest exactly")
    if content_digest(bad) != content_digest(good):
        raise update.ReleaseBlocked("Archived SQLite schemas or row counts differ")
    update.no_live_writers()
    return bad, good, manifest, original, marker, candidate


def preserve_new(destination: Path, payload: bytes):
    update.create_new(destination, payload)
    if sha(destination.read_bytes()) != sha(payload):
        raise update.ReleaseBlocked("Rescue archive write verification failed")


def verify_existing_rescue(original: bytes, marker: bytes, reference: bytes):
    update.safe(RESCUE)
    pins = {
        "original-damaged.sqlite3": original,
        "original-completion-manifest.json": marker,
        "reference-intact.sqlite3": reference,
    }
    for name, expected in pins.items():
        item = update.safe(RESCUE / name, directory=False)
        if item.read_bytes() != expected:
            raise update.ReleaseBlocked("Existing rescue is incomplete or differs: " + name)
    evidence = json.loads(update.safe(RESCUE / "rescue-evidence.json", directory=False).read_text())
    if (evidence.get("status") != "PRESERVED_BEFORE_REPAIR" or
        evidence.get("damagedSha256") != BAD_SHA or
        evidence.get("manifestExpectedSha256") != EXPECTED_SHA or
        evidence.get("originalPreserved") is not True):
        raise update.ReleaseBlocked("Existing rescue witness invalid")


def apply():
    update.safe(RESCUE.parent)
    bad, good, manifest, original, marker, candidate = prove()
    # Immutable forensic evidence: keep the ORIGINAL corrupt bytes, not only
    # a manifest-derived reconstruction, before touching the source archive.
    if RESCUE.exists():
        verify_existing_rescue(original, marker, good.read_bytes())
    else:
        RESCUE.mkdir(mode=0o700)
        preserve_new(RESCUE / "original-damaged.sqlite3", original)
        preserve_new(RESCUE / "original-completion-manifest.json", marker)
        preserve_new(RESCUE / "reference-intact.sqlite3", good.read_bytes())
        record = {
            "status": "PRESERVED_BEFORE_REPAIR",
            "source": str(bad),
            "damagedSha256": BAD_SHA,
            "manifestExpectedSha256": EXPECTED_SHA,
            "offsets": list(OFFSETS),
            "originalPreserved": True,
            "activeLedgerTouched": False,
        }
        preserve_new(RESCUE / "rescue-evidence.json", json.dumps(record, sort_keys=True, indent=2).encode())
    update.no_live_writers()
    if sha(bad.read_bytes()) != BAD_SHA or manifest.read_bytes() != marker:
        raise update.ReleaseBlocked("Archive changed after rescue staging")
    # The private archive ACL permits opening for writing but denies the
    # DELETE right needed by os.replace. Only the two attested SQLite header
    # counter bytes are rewritten; never touch a live ledger or table page.
    with bad.open("r+b") as writable:
        if sha(writable.read()) != BAD_SHA:
            raise update.ReleaseBlocked("Source changed before held writable handle")
        for offset in OFFSETS:
            writable.seek(offset)
            if writable.write(candidate[offset:offset + 1]) != 1:
                raise update.ReleaseBlocked("Header byte could not be written")
        writable.flush()
        os.fsync(writable.fileno())
    if sha(bad.read_bytes()) != EXPECTED_SHA:
        raise update.ReleaseBlocked("Recovered archive hash invalid")
    verify_completion_manifest(bad)
    preserve_new(RESCUE / "completion-evidence.json", json.dumps({
        "status": "PASS_ARCHIVE_HEADER_ONLY_RESTORED",
        "recoveredSha256": EXPECTED_SHA,
        "manifestVerified": True,
        "activeLedgerTouched": False,
    }, sort_keys=True, indent=2).encode())
    return {
        "status": "PASS_ORIGINAL_ARCHIVE_PRESERVED_AND_MANIFEST_RESTORED",
        "source": str(bad), "originalSha256": BAD_SHA,
        "recoveredSha256": EXPECTED_SHA,
        "rescueFolder": str(RESCUE), "activeLedgerTouched": False,
    }


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = apply()
    else:
        bad, good, manifest, original, marker, candidate = prove()
        result = {
            "status": "PASS_RECOVERABLE_PINNED_HEADER_ONLY" if not RESCUE.exists() else "BLOCKED_RESCUE_EXISTS",
            "damagedSha256": sha(original), "recoveredSha256": sha(candidate),
            "activeLedgerTouched": False,
        }
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
