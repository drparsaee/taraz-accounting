# Taraz / Madar: P0 finance binding readback (synthetic implementation)

Scope: `taraz_mtr_finance_binding_authority.py` is an **opt-in, one-time, read-only evidence gate**, not a live finance issuer. It changes no accounting state. The sole positive decision is `SIGNED_BINDING_TO_EXISTING_JOURNAL_OBSERVED_NOT_OFFICIAL`; it retains `officialFinanceReceiptVerified=false`, `trustedMadarInvoiceBindingVerified=false`, and `independentlyAuthenticatedMadarActorVerified=false`.

Verified in synthetic tests: an operator-provisioned v2 HMAC configuration, original request and previously accepted query in `TarazPeerRegistry`, exactly checked durable reviewed Madar source and SHA-256, company/project/actor/invoice/event/journal IDs signed inside the original, a matching positive source amount in RIAL, an actual registered-company editor session with finance edit privilege, and a replay-validated persisted `invoice.issue` event and balanced journal at the requested revision. A create-only directory consumed per Madar request ID blocks repeat manual claims across authority instances. Crash after claim is permanently ambiguous and cannot trigger financial reposting.

**Important production gaps (observed in current local sources):**

1. `mtr_peer_envelope.sign_request` signs an arbitrary metadata payload and actor *role* claim. It does not itself authenticate the actual Madar human actor or bind an account-lineage identity. The existing reviewed metadata proposal also has no required company or actor identity. A real issuer must obtain immutable actor/company/project assertions from an authenticated Madar host action, not from request JSON. The extended signed invoice-binding payload exercised by these tests is a synthetic protocol shape and **is not a demonstrated shipped Madar finance command**.
2. `TarazAPI` currently constructs its superclass in local-fallback mode. The inspected `AccountingDesktopAPI` registered-company identity and financial authority checks are available, but no production Taraz operator wiring for the required selected registered-company session was identified. The gate will fail closed for the fallback actor.
3. `invoice.create` accepts caller-provided `sourceType`/`sourceId`; a matching ledger reference is never sufficient proof of Madar authorization. The added HMAC/source/amount readback improves evidence without retrospectively making that historical invoice source authoritative.
4. No issuer of independently authenticated **official Taraz finance receipts**, no Madar-side verifier/consumption protocol for such receipts, and no cross-app finance actor mapping were identified in the inspected source. The existing `taraz_mtr_review_attestation_issuer.py` signs **nonfinancial metadata reviews** and is not a substitute.

Test command (Windows isolated worktree):

`python -m unittest discover -s tests -p test_taraz_mtr_finance_binding_authority_20261110.py -q`

Result on 2026-11-10: **10 tests passed** in approximately 29 seconds; `python -m py_compile` of both new files passed. Tests use `TemporaryDirectory`, real local Taraz accounting reducers and company identity, and the current Madar HMAC signing module imported read-only. No installed application, real profile, network, live ledger, or production trust source was exercised. Production official receipt is still **blocked**.
