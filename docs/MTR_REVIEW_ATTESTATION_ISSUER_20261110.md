# Madar / Taraz: authenticated NONFINANCIAL review attestation issuer (2026-11-10)

## Scope and release state

New source-only adapter: `taraz_mtr_review_attestation_issuer.py`.
Its response can prove a manually reviewed **metadata-only** request from
an authenticated, operator-provisioned Taraz source instance. It does not
assert any official finance posting, vendor payment, invoice, ledger receipt,
installation acceptance, or production peer identity.

**This adapter is NOT wired into Taraz's installed GUI, network service, or
production profile.** It never invokes a network send, background callback,
ledger or installer. Operator configuration and manual user action are
mandatory; a bare approval boolean is not a substitute for a trusted host
which guarantees an actual UI gesture. No secret is embedded or persisted.

## Source of authority and protocol

The issuer is an internal Python class instantiated exclusively by a
trusted operator host with:

- A real `TarazAPI` and a currently valid `LocalCompanyIdentity`
  editor/admin session. It calls the actual
  `TarazAPI._require_authenticated('editor')` and verifies the current
  identity and role. **Default source TarazAPI uses implicit local-admin
  fallback and MUST fail this issuer gate.** Production authenticated
  company-mode Taraz API construction is presently missing.
- A live `TarazPeerRegistry` object whose `PeerConfig` is the exact same
  in-process provisioned instance. Directional 32+ byte HMAC keys and
  organization/sender/key slot identifiers come from that trusted
  configuration only, **never from the request JSON, the EXE version, a
  static key, or a caller-provided peer flag**.
- The exact reviewed source directory from
  `taraz_desktop.bridge_root()` and an independent, existing
  operator-selected nonlinked folder for consumed challenge tombstones.
  No profile discovery, automatic creation, or silent fallback occurs.

The Madar input consists of **two actual HMAC-verified v2 envelopes**:

1. The *original* Madar `finance_review_request` (already accepted and
   indexed in `TarazPeerRegistry`) must contain the signed payload
   `{id,taskId,projectId,sourceDigest}`; sourceDigest is SHA-256 of the
   **exact bytes** of the reviewed Madar proposal. The issuer independently
   confirms original sender, organization, key ID, actor role, payload
   digest, registry binding and local file bytes.
2. A fresh, signed Madar `receipt_lookup` query for that exact original
   payload. Its unique 32-hex query requestId is used as a
   **single-use Madar-issued challenge**. Source/digest, signed
   organization/sender/key, actor role and query TTL must all agree.
   A bare challenge string or unrelated query cannot trigger signing.

This reuses the *existing* Madar v2 lookup-query protocol; it does NOT
pretend the existing client has an automatic, dedicated attestation
challenge publisher. The operator must deliberately request/approve the
review proof, and Madar must explicitly treat this query ID as its
outstanding attestation challenge and atomically consume it on receipt.
Current end-to-end publication/consumption wiring is an **open integration
gate**, not a passed release test.

## Exact durable source binding and review validity

Only files at the current local bridge's `reviewed/<id>` path are read:

- `<id>.json`: original Madar proposal (bounded, schema 1, strict no
  duplicate keys).
- `<id>.intent.json`: current-source durable Taraz intent, strictly
  containing `sourceDigest` equal to the SHA-256 of that exact proposal.
- `<id>.review.json`: stored Taraz review receipt, exactly the intent
  fields **excluding** `sourceDigest`, with
  `financialEventCreated=false` and a valid review chronology.

A still-pending copy, missing/linked/modified file, mismatched identity
or digest, malformed/duplicate keys, forged finance flag, or incomplete
crash-recovery state fails closed. The issuer never calls
`review_request` to repair or finalize unfinished source metadata.

## Wire format and replay model

The portable signer uses the **same canonical JSON, field set,
`MTR-Taraz-peer-review-v1\x00` HMAC-SHA256 domain and byte encoding**
as Madar's read-only `mtr_taraz_peer_identity.make_peer_review_attestation`.
Response HMAC uses the independently provisioned Taraz-direction key and
contains exact source/review SHA-256, the signed Madar query ID, peer/org/key
identity, time bounds, and `financialEventCreated=false`.

Only `issue_manual(..., explicit_manual_action=True)` returns bytes; there
is no automatic send or I/O on construction. After authorization and
signing, the issuer atomically creates an exclusive
`review-challenge-<queryId>` directory in the operator's replay folder
**before releasing the proof**. A second request, a second process, a
recreated issuer or a post-claim crash cannot silently issue that
challenge again. Ambiguous power-loss durability on Windows is not a
certified replacement for a final operational backup/recovery gate.
Separately, Madar's verifier MUST atomically consume its independently
issued challenge; a local Taraz tombstone alone never authenticates Madar.

The final Madar verifier only accepts a valid peer proof as
`peerVerified=true` with `officialFinancialReceiptVerified=false`,
`postingEnabled=false` and `ledgerPostingPerformed=false`.

## Synthetic evidence and blockers

The test suite `tests/test_taraz_mtr_review_attestation_issuer_20261110.py`
uses disposable synthetic local identities, exact source
`TarazAPI.tarazIntegrationReview` and durable intent/receipt files, new
random test-only peer keys, and actual read-only Madar signer/verifier
imports. Tests verify **byte-for-byte wire compatibility** and Madar's
independent HMAC verifier, as well as wrong session/role, fallback local
admin, forged config, wrong/tampered source, corrupt/missing intent,
finance spoof, unregistered/mismatched original, invalid/expired/future
query, lost-response tombstone, concurrent replay, rejected metadata and
post-restart one-time denial. No actual finance or real profile was read.

Reproduction from the isolated Taraz source worktree:

```powershell
py -3.12 -B -m unittest -v tests.test_taraz_mtr_review_attestation_issuer_20261110
```

Observed with the current isolated source on 2026-11-10:
**18/18 unittest cases PASS, exit 0** (synthetic, no installed-app test).

**Operational blockers:** (1) the current unmodified Taraz GUI's
`TarazAPI` constructor does not establish a real company identity,
(2) the operational Madar signed original must include the agreed
sourceDigest binding and issue a fresh query to be consumed as the
review challenge, (3) no approved operator provisioning/UI/manual
delivery and deployment integration exists, (4) installed Taraz
v1.0.0 does not persist the newer current-source intent marker.
These are not bypassed by passing isolated tests. **E2 live trust/
installed acceptance remains OPEN; official finance remains NO_GO.**
