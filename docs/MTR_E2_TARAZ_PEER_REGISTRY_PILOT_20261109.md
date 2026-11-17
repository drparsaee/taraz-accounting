# Taraz E2 signed peer metadata registry (isolated pilot, unshipped)

New in the **detached Taraz development worktree only**:

- `taraz_mtr_peer_registry.py`
- `tests/test_taraz_mtr_peer_registry.py`

This independent module parses Madar's canonical MTR peer envelope v2,
verifies HMAC-SHA256 with a caller-injected Madar-direction secret, enforces
the exact organization, sender, key ID, signed purpose, actor role, audience,
and expiry before a SQLite `BEGIN IMMEDIATE` records **metadata arrival**.
The SQLite registry stores stable request identity/content digest and an
append-only audit. Exact request content replay is idempotent; changing the
digest, sender/role/key or original identity is a conflict. A separate durable
query ID registry prevents reuse for another query subject or actor.

`query_receipt` verifies a separately signed request-lookup query and returns
an HMAC response using an independent Taraz-direction secret. It can say
`received` when the exact metadata identity exists or `unknown` otherwise.
It **never fabricates `not_received`** based on missing local evidence.
This is NOT an official finance receipt and cannot approve, post, invoice,
create a party, mutate a ledger, or directly send to a remote peer.

The `verified_transport_peer` boolean is an **external host attestation** in
this pilot and must never be copied from HTTP JSON. The module does not
authenticate the true Taraz/Madar services, provision/rotate peer keys, expose
a listener, persist token vault contents, or support actual Taraz accounting
ledger idempotency. Tests inject distinct public synthetic 32-byte keys.

The deployment prerequisites include pinned TLS/service identity,
administrative key provisioning/rotation, reliable incoming request routing,
central org/project role map, transactionally correct authenticated ledger
policy under Taraz authority, crash/physical-power-loss testing, backup
restore, and installed Windows two-PC acceptance. This pilot **does not
authorize** any deployment, real accounting write or release gate closure.

Test in a disposable environment:

```powershell
py -3.12 -B -m unittest -q tests.test_taraz_mtr_peer_registry tests.test_taraz_integration tests.test_taraz_link_status
```

In Madar isolated worktree, set `MTR_TARAZ_SOURCE` to the detached Taraz
source directory and run `tests.test_mtr_e2_signed_peer_registry_cross_app`.
This is source-to-source synthetic interop, not authenticated network traffic.
