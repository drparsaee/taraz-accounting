"""Explicit offline CSV migration for counterparties into a NEW standalone DB.

This does not interpret proprietary Parsian BAK files or migrate monetary
history. Never modifies an existing destination and never opens APPDATA.
"""
import argparse
import csv
from pathlib import Path
import re

from standalone_accounting import StandaloneAccountingStore

FIELDS = ["partyId", "name", "kind"]
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)


def parse_parties_csv(source):
    path = Path(source).resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 5_000_000:
        raise ValueError("Expected a regular CSV file under 5 MB")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != FIELDS:
            raise ValueError("CSV columns must be partyId,name,kind in this order")
        records = []
        ids = set()
        for line in reader:
            if len(records) >= 10000 or None in line:
                raise ValueError("Malformed or oversized CSV")
            ident, name, kind = (line[field] for field in FIELDS)
            if (not SAFE_ID.fullmatch(ident) or ident in ids
                    or not name.strip() or len(name) > 300
                    or kind not in ("customer", "vendor", "both")):
                raise ValueError("Invalid or duplicate party in CSV")
            ids.add(ident)
            records.append((ident, name.strip(), kind))
    return records


def import_to_new_database(source, destination, *, confirmed=False):
    """Prepare and validate before publishing. Failure leaves no destination."""
    rows = parse_parties_csv(source)
    dest = Path(destination).absolute()
    if dest.exists() or dest.is_symlink():
        raise FileExistsError("Destination must not exist; never overwrite")
    if dest.name != "standalone-accounting.sqlite3":
        raise ValueError("Destination must use standalone accounting DB filename")
    if Path(source).resolve() == dest.resolve():
        raise ValueError("Source and destination must differ")
    if not confirmed:
        return {"preview": True, "count": len(rows), "destination": str(dest)}
    if not rows:
        raise ValueError("Empty import refused")
    if not dest.parent.is_dir():
        raise ValueError("Existing destination directory required")
    import tempfile
    import os
    with tempfile.TemporaryDirectory(prefix="madar-migrate-", dir=dest.parent) as tmp:
        staging = Path(tmp) / "standalone-accounting.sqlite3"
        store = StandaloneAccountingStore(staging, default_currency="RIAL")
        actor, accounts = "migration", {"migration": {"username": "migration", "role": "admin"}}
        revision = 0
        for i, (ident, name, kind) in enumerate(rows):
            result = store.command({"type": "party.register", "eventId": f"import-party-{i+1}",
                                    "partyId": ident, "name": name, "kind": kind},
                                   actor=actor, accounts=accounts, expected_revision=revision,
                                   now="2026-01-01T00:00:00+00:00")
            revision = result["revision"]
        assert len(store.read(actor=actor, accounts=accounts)["view"]["parties"]) == len(rows)
        # Atomic no-clobber publication on the same filesystem. Hard-linking
        # avoids making a partially copied financial database visible.
        os.link(staging, dest)
    return {"preview": False, "count": len(rows), "destination": str(dest)}


def main():
    parser = argparse.ArgumentParser(description="Offline party-only CSV migration")
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(import_to_new_database(args.source, args.destination, confirmed=args.apply))


if __name__ == "__main__":
    main()
