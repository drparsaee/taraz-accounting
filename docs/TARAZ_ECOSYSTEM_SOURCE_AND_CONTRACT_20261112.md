# TARAZ / MADAR / RADAR — Verified Source Inventory & Interop Boundary

Date: 2026-11-12. This is a bounded source audit and partial implementation
record, NOT an acceptance of deployed three-product interoperability.

## Product source inventory

| Product | Verified location and Git | Evidence boundary |
| --- | --- | --- |
| TARAZ | D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109; branch codex/taraz-final-integration-20261112; feature Commit 47830f6 after base db22b9c | New uninstalled Frozen build-7f17dbf72519 structurally verified and real view-only smoke PASS; direct UI Save/Edit/PDF E2E remains BLOCKED |
| MADAR Windows/LAN candidate | D:\CoS-Test\000- Madar\madar-mtr-v126-integration-20261110; detached HEAD 785a419af482f998154464a41df7770c9c9c87d4; 7 tracked modifications found | package version 1.0.26, real native LAN API, local file proposal bridge and Web API |
| MADAR primary checkout | D:\CoS-Test\000- Madar\madar-desk; main c9aaf3e4a9cd7653a620d3671ffc58f546c3d17e; 10 tracked modifications | Separate older main snapshot; never overwrite without provenance reconciliation |
| MADAR PWA | D:\CoS-Test\000- Madar\madar-web-pwa-20261106; feat/madar-web-pwa-20261106 d48c09450251c2c74aea64a26f20bcebb4ae1e; 12 tracked modifications | Separate IndexedDB/offline browser experiment, NOT proof of production offline sync |
| RADAR | **SOURCE NOT FOUND** in bounded D:\CoS-Test depth-2 / nearby root scans | LocalForge read-only repo search unavailable; no RADAR schema, API, actual behavior, deployed endpoint or code can be claimed |

The MADAR v126 worktree is used for **interface inspection** and read-only
import of its actual LAN server classes, not declared the uniquely latest
installed or released system. No MADAR *operational* writes, repo cleaning,
migration, service restarts or LAN changes were performed. A NEW disposable
MADAR HTTPS test server was started/stopped on a dynamic 127.0.0.1 port and
received one human-confirmed **synthetic** task write.

## Existing interoperability surfaces — VERIFIED IN SOURCE, NOT LIVE E2E

- TARAZ native TarazAPI: independent order/cost/finance-draft store, Agent
  memory, human approvals, Madar project link and pinned HTTPS preview,
  verified revision/digest, task checklist progress, durable attempt audit
  and read-only uncertain-outcome reconciliation. Finance Draft != posting.
- MADAR LAN lan.py: separate authenticated /api/login and /api/state,
  CAS and server-owned project ACL. Neither shared TARAZ company identity
  nor cross-product SSO is established by the inspected code.
- MADAR web server/index.cjs: a DIFFERENT /api/web/v1 browser endpoint with
  cookies/CSRF, per-workspace CAS and idempotency receipts. Its web state
  model is not the native LAN transport.
- MADAR taraz_exchange.py: user-controlled one-way file proposals in
  Madar-Taraz-Bridge/pending; never official financial ledger posting.
- RADAR: only a source-neutral contract boundary exists. Its purported CRM
  capabilities are UNVERIFIED until actual source/access is supplied.

### Real cross-product interoperability observed in an isolated test

tests.test_taraz_madar_real_ephemeral_https_20261112 imported the real
MADAR LanService and native Bridge from the verified v126 source, used the
MADAR public-only QA TLS certificate fixture and a new synthetic data folder,
and started an HTTPS listener restricted to 127.0.0.1 with port=0. The real
TarazAPI performed pinned TLS login, authenticated project link, reviewed
task preview, explicit admin-confirmed state POST with CAS, read-back of
actual remote checklist progress and confirmed no duplicate on recovery.
An authenticated MADAR admin changed the checklist and a manual description;
TARAZ read the change and did not overwrite it. Wrong TLS fingerprint and
changed remote revision were rejected. **4/4 PASS**. Test server was shut
down without touching installed MadarHost or any actual user's data.

This is stronger than mocked packet tests but **NOT** proof of production
MadarHost, multiple physical LAN devices, Cloud failover, cross-tenant SSO
or RADAR interoperability.

## New TARAZ partial implementation

1. taraz_ecosystem_protocol.py: version 1 strict metadata-only events with
   company/actor/source/target, stable entity references, source Revision,
   Digest and idempotency. Only nonfinancial project, task progress and
   reference events are allowed. Unknown attributes, finance fields, forged
   scope and viewer mutation are rejected.
2. taraz_ecosystem_outbox.py: per-company SQLite v1, source-witness recheck,
   BEGIN IMMEDIATE, durable event/receipt tables, idempotency, ordering and
   cross-company rejection. A possible remote send is persisted as
   OUTCOME_UNKNOWN BEFORE network I/O, and never retried automatically.
   It has NO remote sender, no RADAR recipient and no verified transport.
   VerifiedReceipt is an internal trust-contract type, not authentication.
3. taraz_repository_contracts.py: read-only DB1 adapter for the EXISTING
   TarazOrderStore, preserving revision and the actual MADAR source digest.
   The RADAR adapter explicitly raises NotImplementedError.
4. taraz_ai_provider_status.py: AI Disabled by default. Explicit Online
   policy requires consent and sends no network request during inspection.
   Local mode checks only a pinned 127.0.0.1 Ollama discovery endpoint and
   reports installed but quality-UNVERIFIED rather than claiming model success.
   No model means no AI-dependent actions, not disabled commercial workflows.
5. TarazAPI authenticated read-only ecosystem/AI status and a visible
   order-workspace status affordance. No financial posting, real host write
   or automatic Cloud AI call is introduced.

## DB0 — Actual disposable SQLite schema inventory

The test tests.test_taraz_ecosystem_db0_db1_20261112 invokes real
production store methods with **synthetic** data, then reads sqlite_master
and PRAGMA user_version. Expected tables were checked as follows:

| Database | Version | Required observed tables |
| --- | --- | --- |
| standalone-accounting.sqlite3 | 1 | standalone_accounting |
| taraz-orders.sqlite3 | 2 | orders, actions, audit, order_costs, order_payments, order_finance_handoffs |
| taraz-agent-memory.sqlite3 | 1 | entries, commands, revisions, audit |
| taraz-madar-order-links.sqlite3 | 1 | links, commands, audit, sync_attempts |
| taraz-ecosystem-outbox.sqlite3 | 1 | event_outbox, sync_receipts |

Other historical Parsian and MTR databases, MADAR LAN/Web state stores,
cache databases and RADAR remain NOT exhaustively inventoried. Do not migrate
with file globbing or overwrite existing accounting event history.

## DB1 and remaining architecture gates

OrderReadRepository is a real read-only adapter, not a new official database.
Its contract tests prove source ID, Revision and Digest survive updates.
No PostgreSQL adapter, accounting writer repository, dual-write or migration
has been implemented.

**APPROVED PRODUCT REQUIREMENTS:** customer LAN host, enterprise private
host, Cloud with on-premises offline node, pure Cloud-online; all core
business workflows must remain usable without internet. AI is optional.

**OPEN AND BLOCKING DB2:** official financial single-writer authority,
fencing/lease transfer when LAN/Cloud disconnect, nonfinancial/financial
conflict policy, tenant boundaries, backup and RPO/RTO. The installed
application, old candidate and live accounting books remain unchanged.
