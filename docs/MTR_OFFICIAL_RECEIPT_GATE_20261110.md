# Madar / Taraz: official finance receipt evidence gate (2026-11-10)

## Source inspection and classification

**An official Madar-to-Taraz finance receipt is NOT currently available.**
The actual `TarazAPI.tarazIntegrationReview` calls
`taraz_integration.review_request`, which creates a metadata-only decision
whose `financialEventCreated` flag is always false. Neither its review
marker nor the user's confirmation is a booked invoice.

Separately, `StandaloneAccountingStore.command` and `accounting_core`
implement real local `invoice.create`, `invoice.approve` and `invoice.issue`
commands. Only issuing the invoice records an immutable event, posted
`J:<eventId>` journal, invoice number and `postedEntryId`. Its stored event
chain is SHA-256 checked, canonicalized and revalidated through the full
financial state replay. **However, invoice.create.sourceType/sourceId
are chosen by the caller and are not independently authenticated as a
genuine Madar request.** No signed or otherwise trusted cross-application
official receipt issuer was found in the examined APIs.

## New adapter (read-only, fail-closed)

File: `taraz_mtr_official_receipt_gate.py`.

`classify_metadata_review(marker)` classifies a strict ordinary Taraz
review receipt as `NONFINANCIAL_REVIEW_ONLY`, never as finance posting.

`assess_official_receipt(...)` requires an already existing
`AccountingDesktopAPI` instance with the real current
`LocalCompanyIdentity` session, finance-edit role, matching company
workspace ID and an existing `StandaloneCompanyRegistry` entry.
An unbound local-admin fallback and a mocked/subclassed desktop do not
qualify as this company-mode authority.

The gate opens only the supplied company accounting SQLite using
`mode=ro`, `PRAGMA query_only=ON` and one read transaction.
It invokes the actual store's checked/replayed snapshot reader and
`accounting_view`. It rejects a stale expected revision, missing or
unissued invoice, duplicate or wrong source link, nonmatching issuing
event/actor, absent or reversed journal, inconsistent posting amounts
or event IDs, revoked role/session, wrong company and bad persistence
checksums. The current principal is checked both before and after read.

With genuine persisted invoice and journal evidence, the strongest
result is `PERSISTED_INVOICE_JOURNAL_OBSERVED_UNBOUND`, with
`persistedInvoiceJournalVerified=true`. **This is ledger evidence only.**
For all results `officialFinanceReceiptVerified=false`,
`trustedMadarInvoiceBindingVerified=false`,
`signedTarazReceiptPresent=false` and
`safeToRetryFinancialPosting=false`. A lost acknowledgement after COMMIT
cannot authorize blind reposting.

## Verified synthetic test boundary

The new tests create a disposable real company registry, real local
company identities/password sessions, and a synthetic RIAL SQLite
accounting book. All ledger mutations use the authoritative public
`AccountingDesktopAPI.standaloneAccountingCommand` CAS method,
not manual journal fabrication. Tests cover actual invoice
creation/approval/issue and readback across fresh authenticated host
instances, real `taraz_integration.review_request` without financial
posting, forged review flags, wrong company, revoked or downgraded
session, stale revisions, ambiguous crash after COMMIT, source
duplication, reversed journal, corrupted SQLite digest and spoofed
invoice/journal IDs.

Command:

```powershell
py -3.12 -B -m unittest -v tests.test_taraz_mtr_official_receipt_gate_20261110
```

Observed on 2026-11-10: **15/15 tests PASS, exit 0**, all on
disposable data. No real ledger, installed EXE, user profile,
network, service, installer, commit, push or release was touched.

## Remaining operational release blocker

To declare a Madar proposal **officially booked**, a trusted
Taraz-host operation is still needed to: authenticate the Madar-origin
request ID/digest and company; authorize the current Taraz finance
principal; bind the exact posted invoice and journal to that request
independently of the caller-controlled invoice-source fields; and issue
a durable integrity-protected receipt that Madar can independently
check and reconcile after a timeout/restart.

The inspected public APIs do not provide that complete contract.
The older installed Taraz 1.0.0 also lacks current source's durable
metadata intent marker. **Official finance acceptance: OPEN / NO_GO.**
