"""Create a new isolated usable Madar copy with registered Parsian customers.

Historic GL is already posted on ps.12.* source accounts. Registering customer
identity MUST NOT repost those prior sales, receipts or outstanding balances.
The host displays imported historic debtors separately from new invoice A/R.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import sqlite3
import tempfile

from standalone_accounting import StandaloneAccountingStore, _decode_checked
from accounting_core import apply_accounting_command, accounting_view, validate_accounting_state
from standalone_accounting_backup import _readonly_sqlite, _check_snapshot

_ACTOR = "legacy-party-registration"
_ACCOUNTS = {_ACTOR: {"username": _ACTOR, "role": "admin"}}
_NOW = "2026-10-24T12:00:00Z"
_R19_SOURCE = "RESTORED_BAK_ISOLATED_VERIFIED_20261026"
_R19_BACKUP_SHA = "EAF55D9A4C2CF2EF28C9C5AF01B57E61C1773E8A33F16F09174D1E41967B6946"


class PartyMigrationError(ValueError):
    pass


def register_historic_customers(source_book, export_file, destination):
    """Construct and publish a *new* book, do not edit running trial or source."""
    original = Path(source_book).absolute()
    export_path = Path(export_file).absolute()
    dest = Path(destination).absolute()
    if (original.name != "standalone-accounting.sqlite3" or
            not original.is_file() or not export_path.is_file() or
            dest.name != "parsian-operational-customer-test-disposable" or
            dest.exists() or dest.is_symlink() or
            not dest.parent.name.startswith("migration-experiment-")
            or not dest.parent.is_dir() or
            any(x.is_symlink() for x in (original, export_path, dest.parent))):
        raise PartyMigrationError("Only an isolated new private customer test is allowed")
    with closing(_readonly_sqlite(original)) as conn:
        initial_revision = _check_snapshot(conn)
    before = StandaloneAccountingStore(original, default_currency="TOMAN").read(
        actor=_ACTOR, accounts=_ACCOUNTS)
    historic_journals = before["view"]["journals"]
    if (before["revision"] != initial_revision or
            before["view"]["currency"] != "RIAL" or
            not historic_journals or
            any(x.get("sourceType") != "journal.manual" or
                not x.get("eventId","").startswith("ps.sanad.")
                for x in historic_journals) or
            before["view"]["parties"]):
        raise PartyMigrationError("Expected original RIAL Parsian trial with no parties")
    source = json.loads(export_path.read_text("utf8"))
    source_type=source.get("sourceType")
    if source_type == _R19_SOURCE:
        if source.get("backupCopySha256", "").upper() != _R19_BACKUP_SHA:
            raise PartyMigrationError("Unexpected restored Parsian source hash")
        manifest_path=original.parent/"parsian-archive-manifest.json"
        if not manifest_path.is_file():
            raise PartyMigrationError("Missing restored source archive")
        manifest=json.loads(manifest_path.read_text("utf8"))
        if (manifest.get("sourceBackupSha256", "").upper() != _R19_BACKUP_SHA
                or manifest.get("snapshotMatchesBackup") is not True):
            raise PartyMigrationError("Restored archived source not attested")
    elif source_type != "ATTACHED_LIVE_SQL_READ_ONLY_NOT_BAK_SNAPSHOT":
        raise PartyMigrationError("Unexpected Parsian export class")
    source_tafsili = source["tables"]["tbl_Tafsili"]
    parties = {}
    for row in source_tafsili:
        k,m,t = row["KolCode"],row["MoeenCode"],row["Code"]
        if k != 12:
            continue
        aid = f"ps.12.{m}.{t}"
        pid = f"ps.party.12.{m}.{t}"
        name = row["CName"]
        if (type(name) is not str or not name.strip() or len(name.strip())>300 or
                pid in parties):
            raise PartyMigrationError("Unusable source customer identifier/name")
        parties[pid] = {"id": pid, "name":name.strip(), "sourceAccountId":aid}
    if not parties:
        raise PartyMigrationError("No historical customers available")
    # Populate named historic customer identities for NEW invoicing,
    # not just customers with a historic amount currently outstanding.
    dest.mkdir(exist_ok=False)
    book = dest/"standalone-accounting.sqlite3"
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
                prefix=".customer-copy-",suffix=".sqlite3",
                dir=dest,delete=False) as holder:
            temp = Path(holder.name)
        with closing(_readonly_sqlite(original)) as src:
            with closing(sqlite3.connect(temp)) as target:
                src.backup(target)
        with closing(_readonly_sqlite(temp)) as copy:
            if _check_snapshot(copy) != initial_revision:
                raise PartyMigrationError("Customer test source snapshot changed")
        os.link(temp,book)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    # Store replay/command appends audited identity-only events and keeps
    # every source financial journal exactly unchanged.
    store = StandaloneAccountingStore(book, default_currency="TOMAN")
    revision = initial_revision
    for pid,meta in sorted(parties.items()):
        event = {"type":"party.register","eventId":"ps.register."+pid,
                 "partyId":pid,"name":meta["name"],"kind":"customer"}
        result = store.command(event, actor=_ACTOR,accounts=_ACCOUNTS,
                               expected_revision=revision,now=_NOW)
        revision = result["revision"]
    after = store.read(actor=_ACTOR,accounts=_ACCOUNTS)
    if (after["view"]["currency"] != "RIAL" or
            len(after["view"]["journals"]) != len(historic_journals) or
            len(after["view"]["parties"]) != len(parties) or
            any(x["receivable"] or x["payable"] for x in
                after["view"]["parties"].values())):
        raise PartyMigrationError("New-book customer registration failed reconciliation")
    before_j = json.dumps(before["view"]["journals"],
                          ensure_ascii=False, sort_keys=True)
    after_j = json.dumps(after["view"]["journals"],
                         ensure_ascii=False, sort_keys=True)
    if before_j != after_j:
        raise PartyMigrationError("Source ledger changed during customer registration")
    for filename in (
            "parsian-all-base-tables-PRIVATE.sqlite3",
            "parsian-archive-manifest.json"):
        path = original.parent/filename
        target = dest/filename
        if not path.is_file() or target.exists():
            raise PartyMigrationError("Historical source sidecar not present")
        shutil.copyfile(path,target)
        if sha256(path.read_bytes()).digest() != sha256(target.read_bytes()).digest():
            raise PartyMigrationError("Historical sidecar was not copied correctly")
    summary = {
        "status":"HISTORIC_CUSTOMERS_REGISTERED_FOR_NEW_WORK",
        "customerIdentityCount":len(parties),
        "oldGLDocumentsRetained":len(historic_journals),
        "historicGLReposted":False,
        "newCustomerBalancesRemainZeroUntilNewOperations":True,
        "historicBalancesRemainInPsAccounts":True,
        "currency":"RIAL",
        "bookRevision":after["revision"],
        "operationalHistoricSettlementsLinked":False,
    }
    with (dest/"historical-customer-account-map.json").open(
            "x",encoding="utf8") as out:
        json.dump(parties,out,ensure_ascii=False,indent=2)
    with (dest/"customer-registration-audit.json").open(
            "x",encoding="utf8") as out:
        json.dump(summary,out,ensure_ascii=False,indent=2)
    return summary


__all__ = ["register_historic_customers","PartyMigrationError"]
