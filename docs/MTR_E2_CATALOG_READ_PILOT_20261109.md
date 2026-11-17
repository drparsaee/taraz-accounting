# E2/E4 local Taraz catalog read boundary pilot (2026-11-09)

**Classification: read-only, local, synthetic pilot; NOT authenticated remote Taraz peer transport, official party certification or E2/E4 end-to-end acceptance.**

## Scope / files

New files only in detached Taraz worktree:

- taraz_mtr_catalog_read.py
- tests/test_taraz_mtr_catalog_read.py
- docs/MTR_E2_CATALOG_READ_PILOT_20261109.md

No existing files, profiles, customer data, installed applications, services, LAN routes, source-ledger records, commits, pushes or deployments changed. The adapter has **no default path** and exposes no mutation API.

## Existing source code actually inspected

- standalone_accounting.StandaloneAccountingStore.read(actor,accounts) uses a read transaction, verifies the persisted SQLite state checksum and replays the complete event chain via accounting_core before calling accounting_view; it returns revision and a **full** accounting view.
- accounting_core.accounting_view returns parties alongside receivable/payable/netReceivable, possible historical ledger balance fields, complete account balance rows, invoices, bills, cheques, payroll, stock, payments, journals, company profile and more. Forwarding its raw view to Madar would leak financial data.
- Actual registered company identity comes from StandaloneCompanyRegistry.company_data_directory(company_id); local enabled user/session and current role are checked by LocalCompanyIdentity.require_session, then accounting_accounts supplies the authoritative local accounting actor and financeView. The standalone local account registry currently gives financeView to every **enabled** identity, so additional per-user financial-read revocation is **not independently modeled** there. Role restriction and disabled-session checks remain enforced.

## Narrow host-only API

HostCatalogScope is a frozen host-injected policy. It requires the registered 32-hex company ID as org ID; selected project and explicit project grants; role grants; field grants; row grants (explicit frozenset of allowed IDs, or None for the host-operator-authorized entire book); source revision; and a UTC source-observation time. Standalone Taraz accounting has **no native project grants**. Project and per-row/per-field rules are therefore **additional host policy**, not verified financial-ledger facts. Production must derive this policy from a trusted and authenticated Taraz host, never browser JSON.

TarazCatalogRead is bound to an already initialized StandaloneCompanyRegistry, LocalCompanyIdentity, StandaloneAccountingStore, and HostCatalogScope. Each read checks current registry membership, exact identity/book directory binding, canonical ledger filename standalone-accounting.sqlite3, non-linked path, active local company session, current role and financeView, then calls the actual StandaloneAccountingStore.read(actor,accounts) and rejects a stale revision. A host-supplied trusted_now must be within 300 seconds of source observation, with at most 30 seconds future skew.

Only the four-key query_json is accepted: kind (parties/items), offset, limit, expectedRevision. It is strict UTF-8 JSON <=1024 bytes; nested duplicate keys, unknown fields, client-provided actors/org/grants/proof/candidate IDs, invalid numbers and unbounded pagination are rejected. Limit is 1..50, offset 0..8192; maximum 8192 source records per collection, maximum 65,536 encoded bytes per response.

Allowed public fields are a **closed, safe upper bound**:

| Type | Exposable only if host grants | Always excluded |
|---|---|---|
| Party | id, name, kind | creditLimit, changeHistory, receivable, payable, netReceivable, historical balances, bank/tax/private data |
| Item/product/service | id, sku, name, kind, unit, active | inventory stockTracked, costs, prices, stock layers, purchase/sale history, source documents |

Every authorized record is returned, ordered by ID and paginated, even when two parties have the same name or competing candidate claims; the adapter **never deduplicates, auto-links, ranks, guesses official ID, posts, or merges**. Host row-grant IDs absent from the current projection cause a stale-source rejection instead of silently vanishing. Absent ungranted rows are never exposed, including through counts.

The response states authenticatedLocalCompany=True **only for the completed local registry/session checks**, and explicitly states remoteTarazPeerAuthenticated=False, importedIdentityOfficiallyVerified=False, officialPartyLinkCreated=False, financialPostingPerformed=False, networkUsed=False. It never returns raw accounting_view, tokens, password records or ledger fields.

## Synthetic test evidence

Executed from D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109:

    python -B -m unittest -v tests.test_taraz_mtr_catalog_read

Initial run: **22 tests, OK, exit code 0, 32.164 seconds** on Windows. Final post-cleanup run after extra security cases: **25 tests, OK, exit code 0, 38.906 seconds** with the same command. These tests constructed the actual local StandaloneCompanyRegistry, LocalCompanyIdentity (synthetic users/sessions) and StandaloneAccountingStore with disposable TemporaryDirectory-backed SQLite databases; wrote synthetic parties/items using the existing accounting store command API **only in test fixtures**. They checked duplicate-name retention, products/services, paginated all-authorized rows, narrow fields, no ledger/credit/history leaks, source/company/project mismatch, stale timestamp/revision, invalid JSON and booleans, revoked role/view, absent/granted ID conflict, readback without ledger state changes, and schema fail-closed.

The final aggregate includes three additional tests exercising **actual local identity role downgrade, disabled session and corrupted SQLite state digest**. The underlying source remained disposable; these tests do not establish any live Taraz integration.

## Remaining gaps

1. Authentication is **local company session**, not an independently authenticated, signed or TLS-bound remote Taraz peer. Local records could be manually created or imported. Their presence in accounting_view does not certify party identity or official tax/legal data. No real two-device transport or peer attestation was executed.
2. HostCatalogScope project/row/field grants are externally injected assertions. Existing standalone company accounts do not provide per-project ACL or independently revocable financeView granularity. Production must bind policy to authenticated host session, company data directory and current revocation authority.
3. Reading a revision and projecting it does not establish that a later client action still targets that same Taraz catalog state. A later official link or create requires its own fresh authenticated source check, atomic destination CAS, idempotency and explicit human finance review.
4. Read-only SQLite activity may involve SQLite-side read locks/journal metadata, but the adapter invokes no write/command or finance mutation. Synthetic tests compare persisted accounting revision/state/digest before and after repeated reads; this is **not** a physical power-loss test, a hostile file writer test, or a guarantee against external writes.
5. The catalog schema is bounded and projected, not a full accounting data export. This work has no trusted official receipt, finance posting, product synchronization, customer reconciliation, production credential rollout, LAN endpoint or deploy.
