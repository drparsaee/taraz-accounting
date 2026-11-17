# E2 offline query-epoch evidence preparation: activation BLOCKED

**Worktree:** detached Taraz `D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`.
**Only new files:** `taraz_mtr_epoch_rollover.py`,
`tests/test_taraz_mtr_epoch_rollover.py`, this document. The existing
registry, transport, HTTP listener, protocol, keys, historical tests, and
production/user data were not modified.

## Critical discovery

`TarazPeerRegistry.query_receipt()` reads **only the active SQLite
`queries` table** to detect use of an already-bound query ID, then refuses
the 10,001st distinct ID. The `archive_to()` function preserves a complete
point-in-time backup but intentionally does not release the limit. The HTTP
listener requires `type(registry) is TarazPeerRegistry` and has no
epoch-aware replay lookup. Neither the query wire protocol nor key registry
contains a signed epoch ID and a cross-epoch binding policy.

**Confirmed synthetic unsafe scenario:** after accepting an original query
ID, a newly created separate `TarazPeerRegistry` configured with rotated
keys accepts a different correctly HMAC-signed query that reuses that ID.
The fresh registry lacks knowledge of old IDs. This is an **unsafe isolated
simulation**, not a live exploit or proof that a remote attacker possesses
signing keys.

**Result:** no safe activation, capacity reset, ID recycling, truncation,
request ownership remap, resend, or automatic rollover is implemented.
`activate_epoch()` **always raises `EpochRolloverBlocked`**, even when a
verified archive exists. A complete future implementation must atomically
enforce historical and current ID bindings on *every* incoming query, define
cryptographically authenticated epoch/key rotation, handle interrupted
cutover and prior-epoch receipt lookup, and receive separate review.

## What the new OFFLINE primitive actually does

`prepare_offline_epoch_evidence(...)` is an unmounted, Python-only **stage
operation**; it does not issue credentials or activate a new registry.

It requires:

1. The actual `TarazPeerRegistry` and the **same** private `PeerConfig`
   object already owned by that host (identity check, not a JSON/client
   dict). A prospective new `PeerConfig` must preserve organization and
   both sender IDs while rotating both directional key IDs and all secret
   values.
2. An independent domain-separated **HMAC-SHA256 offline approval** over
   the exact source/archive/receipt paths, key IDs, organization/sender
   identity and digests of prospective secret values, using the old
   host-owned Taraz-direction secret. No secret bytes are serialized in the
   approval or exported receipt. This proves key possession **only** and
   is *not* a substitute for host admin authentication/physical access
   control; a future host integration must perform that authorization.
3. New absolute paths in existing trusted non-symlink/non-reparse
   directories: a create-only `.sqlite3` historical archive and a
   create-only `.json` evidence receipt. An existing destination is never
   overwritten. The operator must provision private OS ACLs.

The primitive calls the existing `archive_to()`, independently verifies the
archive's SHA-256, SQLite quick check, schema version, immutable triggers,
request identity, all query binding fields and roles, counts and a
deterministic SHA-256 digest of **every sorted historical query tuple**.
It checks query counts in the live registry before and after the snapshot,
then writes a compact create-only, fsynced, byte-verified evidence receipt
stating `activationAuthorized: false` and
`liveQueryCapacityReleased: false`. Neither live source table is touched.

The backup retains the original full request, audit and query tables; the
receipt contains only counts, hashes, key **IDs** and immutable
preparation status, never actual HMAC key bytes.

**Availability and crash limitations:** A snapshot is not a durable
quiescence barrier. A separate host process could write after both count
checks; an intake may add request/audit rows while the snapshot is taken.
Operators must stop listeners and unrelated writers independently, then
reconcile the original DB and readback archives offline. File creation
across archive and receipt is not atomic as a pair: injected failures leave
the evidence in place for inspection, *not* a transition to resume or
automatically roll back. No power-failure test, directory fsync guarantee,
independent archive custodian signature, or Windows private ACL test was
performed. The returned digest is local verification evidence, not
independent attestation.

## Operator staging outline (not an activation script)

An authorized host-only Python caller must independently provide the live
`registry`, private `host_config` that is precisely
`registry.config`, newly provisioned `proposed_config`, and a 32-byte
HMAC over the domain-separated offline approval intent. Do not pass those
objects or the approval key through HTTP, IPC, task JSON or a browser.

```python
from taraz_mtr_epoch_rollover import prepare_offline_epoch_evidence

evidence = prepare_offline_epoch_evidence(
    registry=trusted_existing_registry,
    host_config=trusted_existing_registry.config,
    proposed_config=trusted_new_peer_config,
    archive_path=approved_new_archive_path,
    receipt_path=approved_new_receipt_path,
    approval_mac=operator_host_signed_intent_mac,  # private trusted host only
)
assert not evidence["activationAuthorized"]
assert not evidence["liveQueryCapacityReleased"]
```

The user-facing application has **no mounted endpoint** for these methods.
An independently authenticated host-offline operator must review and record
the resulting hashes and file custody. Do not delete the original registry
or start a new one from the staged candidate configuration.

## Exact synthetic verification

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
py -3.12 -B -m unittest -q tests.test_taraz_mtr_epoch_rollover
py -3.12 -B -m unittest -q tests.test_taraz_mtr_peer_registry tests.test_taraz_mtr_epoch_rollover
```

Executed 2026-11-10 in the detached Taraz worktree:

- **12/12** offline rollover negative/evidence tests PASS, exit 0.
- **28/28** combined peer registry + rollover tests PASS, exit 0.
- The synthetic full 10,000-query archive retains all query IDs and the
  original request/audit. A legitimate replay against the same active
  registry remains accepted; conflicting binding or a new ID at capacity
  remains denied.
- Fresh empty database accepts a previously consumed ID under rotated HMAC
  keys: this reproduces the design blocker; `activate_epoch` refuses it.
- Tests deny forged/missing approval MAC, changed key/organization claims,
  previously existing target files, malformed historical bindings,
  wrong archive SHA, altered receipt readback and source changes after
  archive; ambiguous post-publication failures retain evidence without
  activating anything.

**Release gate:** BLOCKED. This artifact supplies inspectable offline
evidence for the next design iteration, not a working capacity rollover or
release-ready cross-epoch protocol.
