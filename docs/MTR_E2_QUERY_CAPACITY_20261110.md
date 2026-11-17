# MTR E2 peer query capacity: fail-closed retention and offline evidence

**Scope:** detached Taraz metadata-only peer registry pilot, not a deployed
Taraz accounting connector. The original finance request intake, HMAC
verification, signed receipt format, and no-auto-resend contract are unchanged.

## Why simply pruning the 10,000-row query registry is unsafe

The immutable `queries` table maps each signed `query_id` to its organization,
original request ID, original payload SHA-256, signed query payload SHA-256,
and original actor role. This is the peer's exact replay/conflict index.
Removing a row, resetting the DB, or restoring a pre-query snapshot would
allow a later, validly HMAC-signed *different* query to reuse the forgotten ID.
Neither short-lived signatures nor a separately saved archive establish a
complete anti-replay lookup after deletion. There is no independently
authenticated rollover epoch, delegation authority, or archive replay index
in this pilot.

**Therefore no automatic pruning, capacity reset, query-ID reuse, or resend
is implemented.** The active registry remains limited to 10,000 distinct
accepted query IDs. This is a deliberate *availability limit*, not a resolution
of indefinite query growth. Reaching the limit must block any operational
release until a separately reviewed epoch/migration protocol is available.

## New bounded behavior

The callable `TarazPeerRegistry.query_capacity_status()` is read-only and
does not expose request IDs, payloads, bearer material, or HMAC keys.

- Below 9,000 rows: capacity available; monitor usage.
- From 9,000 through 9,999: `archiveRecommended=True`. Arrange a
  controlled offline evidence export and recovery planning.
- At 10,000: `newQueryIdsAllowed=False`; unseen signed query IDs are denied
  before insert. An **identical previously registered** query ID/subject/role
  remains queryable; a conflicting use of that ID is still `PeerConflict`.
- The response can be `unknown` or `received` depending on the current
  immutable request-intake evidence. Repeating a query does not create a
  second query row. The signed lookup result is *metadata only*, not an
  official finance receipt or proof of nonreceipt.
- The intake table and immutable intake audit remain untouched by query
  capacity; accepting a new original request does **not** authorize dispatch
  retries or an official ledger posting.

The status method is a snapshot, not a reservation. Concurrent queries can
change remaining capacity immediately; `BEGIN IMMEDIATE` remains the single
writer/limit authority for insertion.

## Create-only offline evidence archival

`TarazPeerRegistry.archive_to(destination: Path)` creates an immutable-
history SQLite **snapshot** in a separately selected existing, trusted
directory. The destination must be a distinct absolute `.sqlite3` file.
It will not overwrite an existing file or follow a symlink/junction ancestor.
It uses SQLite's consistent backup, checks `quick_check`, schema version,
table presence, and all existing immutable audit/query/request triggers,
flushes the copy, and returns its SHA-256 and record counts.

Authorized offline operations with an already configured synthetic/trusted
`registry` object may call:

```python
from pathlib import Path
evidence = registry.archive_to(Path("D:/approved-evidence/mtr-peer-20261110.sqlite3"))
assert evidence["created"] and not evidence["liveQueryCapacityReleased"]
print(evidence["archiveSha256"], evidence["queries"], evidence["auditEvents"])
```

This is an **API example only**, not an executed production workflow. The
operator must ensure the archive directory's OS ACLs and independent backup
location are appropriate, record the digest in a separately trusted log,
read back the saved file from that location, and retain source and archive
under an approved retention policy. A SHA-256 returned by the same machine
does not independently authenticate its custodian. No automatic scheduler,
deletion, upload, or archive rotation is installed.

**Archiving never clears the live `queries` table or reopens capacity.**
It only preserves evidence for review and a future, separately approved
migration. Do not remove the live DB, copy an old archive over it, truncate
immutable tables, or change `PRAGMA user_version` to bypass the limit.
Physical-power-loss recovery, signed external archive custody, rollover
epoch/key rotation, historical replay lookup, and two-host installation
acceptance remain out of scope and unverified.

## Synthetic verification

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m unittest -q tests.test_taraz_mtr_peer_registry
```

Tests cover 9,000 warning, 9,999/10,000 boundaries, denied first-time
query after exhaustion, permitted identical replay, rejected conflicting
query-ID reuse, restarted SQLite, independent new request intake, archive
readback and SHA-256, no overwrite, invalid destinations, and snapshot
noninterference with the live registry. Eight concurrent fresh queries
competing for the last slot yield exactly one acceptance; invalid HMAC
remains denied at full capacity. No network, deployed service, real finance,
or user profile is exercised by these capacity tests.

On 2026-11-10, the scoped registry suite ran with **16/16 PASS, exit code
0** in the detached Taraz worktree. No deployment or operational migration
was tested or authorized.
