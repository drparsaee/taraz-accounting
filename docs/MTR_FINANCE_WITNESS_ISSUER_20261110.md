# Taraz finance witness issuer, QA source only (2026-11-10)

Status: **SOURCE-ONLY, NONOPERATIONAL, NOT AN OFFICIAL FINANCE RECEIPT**.
No production bundle, UI, LAN service, installer, trust exchange or ledger
posting is wired by this change.

## Contract

New `taraz_mtr_finance_witness_issuer.py`:

- `FinanceIssuerTrust` has separately operator-provisioned finance-direction
  HMAC key (32 to 4096 bytes) and issuer/key IDs. It must be different from
  both peer secrets. The key is not stored in the issuer DB or the output.
- `ManualTarazFinanceWitnessIssuer` accepts an already authenticated
  `AccountingDesktopAPI` tied to a live registered-company editor session,
  an independently trusted existing v2 peer config/registry, a canonical
  durable reviewed Madar proposal, and a separate live
  `ManualExternalActorLinks` instance. Current local administrator approval
  must already have been recorded for the exact 77-character Madar actor,
  request/query, organization, key, company, project and source digest.
- `issue_manual` re-verifies both HMAC v2 wires and their durable peer
  reception, checks exact RIAL amount + source/review, independently reads
  SQLite `mode=ro` replay-validated accounting state, invoice, journal and
  immutable issue event. It also runs Taraz's existing independent journal
  assessment and re-reads the accounting state after reservation.
- Ledger digest is SHA-256 of the exact replay-validated **canonical full
  accounting state**. Journal and accounting-event bytes are sorted, canonical
  JSON projected directly from that persisted replay, with matching hashes.
  The HMAC wire exactly follows current Madar
  `mtr_taraz_finance_witness_verifier.py` witness v1 and
  `MTR-Taraz-finance-journal-witness-v1\x00` domain.
- `DurableFinanceWitnessIssuance` writes a create-only private SQLite
  `mtr-taraz-finance-witness-issued.sqlite3`, with immutable rows and unique
  original request and query nonce. It reserves **before returning signature
  bytes**. Reopen preserves consumed IDs. Crash after reservation leaves
  them permanently consumed, without automatic recovery. It does not touch
  the account ledger, review files, peer registry, host dispatch or Madar
  challenge DB.

## Validation

`python -m unittest discover -s tests -p test_taraz_mtr_finance_witness_issuer_20261110.py -v`

Ran 11 synthetic tests, **11 passed** (2026-11-10). One positive test
independently loads actual current Madar source, uses its real
`DurableFinanceWitnessChallenges` and `TarazFinanceWitnessVerifier`,
and successfully verifies a finance witness emitted from a *real disposable
Taraz registered-company ledger* containing an `invoice.issue` event.
Negative tests cover unsigned administrative authority, wrong peer/source,
source amount mutation, independent ledger amount mismatch, wrong company/role,
revoked admin, reversed/stale journal,
key mismatch, persistent replay and ambiguous crash. All ledger test writes
are confined to `TemporaryDirectory`.

## Evidence boundaries

The external actor ID is not independently authenticated as a Madar human:
the configured Madar HMAC authenticates a peer sender. The local admin
approval is a separate Taraz trust decision. Although the issuer reads real
Taraz source **in a synthetic fixture**, the independently run Madar
verifier still returns
`SIGNED_WITNESS_STRUCTURALLY_VERIFIED_OFFICIAL_ISSUER_UNAVAILABLE` with
`realTarazIssuerAuthenticated=False`,
`independentLiveLedgerReadbackVerified=False`,
`officialFinanceReceiptVerified=False` and
`safeToRetryFinancialPosting=False`.

The two private Taraz admission and issuer SQLite journals are not a
cross-database atomic transaction. The order deliberately burns one-time
issuance on ambiguous failures. A peer-verified, separately deployed trust
anchor and controlled production provisioning are still required.
