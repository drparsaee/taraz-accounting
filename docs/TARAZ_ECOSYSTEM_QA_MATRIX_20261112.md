# ECOSYSTEM PRIME — Independent QA / Release Gate Matrix

Date: 2026-11-12. A VERIFIED PASS is scoped only to the code, command,
test environment and output identified in that row. Isolated source QA
never substitutes for frozen/native/production acceptance.

| # | User-required scenario | Status | Evidence and limitations |
| --- | --- | --- | --- |
| 1 | Frozen EXE invoice/create/edit/reopen/print | BLOCKED | New build-7f17dbf72519 is real and hash-attested, archive/code/UI 6/6 PASS, private real Frozen navigation view-only PASS; CDP flag observed but no listener. Direct Save/Edit/Reopen/PDF still NOT verified on this EXE |
| 2 | Orders, actual costs, production conservation | VERIFIED PASS (isolated); Frozen BLOCKED | Repeated current runtime source 59/59 Python / 16/16 Edge, Native source-hosted PASS, separate raw SQLite five-axis QA |
| 3 | Financial controls, permissions, no unintended posting | VERIFIED PASS (isolated source); live NOT TESTED | Disposable ledgers and draft-only handoffs; official Cloud/Local financial authority OPEN |
| 4 | Agent with online AI | NOT TESTED | New online status checks make no cloud inference; no provider cost/model quality or actual data-consent proof |
| 5 | Agent with installed local AI | BLOCKED | Previous qwen3:4b / qwen3:0.6b inference unreliable/timeout; discovery only, not model success |
| 6 | Core business without AI | VERIFIED PASS (source scope) | Optional-AI tests: disabled status sends no provider request; manual local order/finance code remains available |
| 7 | Full LAN without internet | BLOCKED ecosystem E2E; private loopback PASS | Real ephemeral MADAR HTTPS localhost and real TARAZ client with TLS pin/CAS; not external multi-client/host failover |
| 8 | Full three-product integration | BLOCKED | Real private TARAZ–MADAR task sync, checklist and identity; RADAR source/API NOT FOUND |
| 9 | Cloud loss and local business continuation | NOT TESTED E2E | Local stores work independently, but cloud/local authority switch is not implemented/approved |
| 10 | Reconnection and duplicate-free reconciliation | VERIFIED PASS (isolated contract); Cloud E2E BLOCKED | Durable SQLite outbox: no blind resend, unknown-after-crash, typed receipt and conflict review |
| 11 | Tenant and permissions | VERIFIED PASS (isolated contracts); cross-product identity BLOCKED | Company-scope ACL and negative tests; no actual shared SSO |
| 12 | Backup and restore | NOT TESTED ecosystem-wide | Existing Madar tests do not establish a cross-product RPO/RTO |
| 13 | PostgreSQL parity | NOT TESTED | DB0 five real disposable SQLite schemas and DB1 order read contract; DB2 not authorized until ADR |
| 14 | Installer, rollback | NOT TESTED for new runtime | Installed 1.0.4 preserved. No production install/activation authorization |
| 15 | PDF and physical printer | VERIFIED PASS source-hosted PDF only; physical NOT TESTED | Current source-hosted native PDF 82,142 bytes; Frozen GUI and printer hardware gates open |

## Commands observed in this continuation

- py -3.12 -B -m unittest tests.test_taraz_ecosystem_db0_db1_20261112 tests.test_taraz_ecosystem_native_capabilities_20261112 tests.test_taraz_ai_optional_policy_20261112 tests.test_taraz_ecosystem_offline_contract_20261112 -q: 21/21 PASS in disposable SQLite. An earlier concurrent WAL-init race was identified and corrected; later rerun passed.
- py -3.12 -B -m unittest tests.test_taraz_madar_real_ephemeral_https_20261112 -q: 4/4 PASS with REAL ephemeral Madar v126 HTTPS loopback host, real Taraz client, authorized project link, new task CAS, manual task completion readback, revision conflict refusal, no duplicate.
- From D:\CoS-Test\000- Madar\madar-mtr-v126-integration-20261110: py -3.12 -B -m unittest tests.test_lan_tls -q: 10/10 PASS on isolated Madar TLS.
- npm run build: Vite build passed, 2060 modules. It is not Frozen EXE acceptance.
- npm run test:orders:all: exit 0, Vite PASS, 59/59 Python, 16/16 Edge, PASS_ORDER_NATIVE (real source-hosted WebView2 with SQLite order+Agent memory readback).
- node scripts/run_taraz_p1_checks_20261112.mjs --native-current-source: exit 0, Vite PASS, 34/34 Python, 11/11 Edge and PASS_WEBVIEW2_REAL_BRIDGE_DRAFT including same-ID invoice and proforma reopen/edit, print template, 82,142-byte PDF and zero journals.
- py -3.12 -B -m unittest tests.test_taraz_ecosystem_db0_db1_20261112 tests.test_taraz_ecosystem_native_capabilities_20261112 tests.test_taraz_ai_optional_policy_20261112 tests.test_taraz_ecosystem_offline_contract_20261112 tests.test_taraz_madar_real_ephemeral_https_20261112 tests.test_taraz_frozen_aaas_inventory_20261112 -q: 28/28 PASS.
- py -3.12 -B -m unittest tests.test_taraz_v106_current_frozen_aaas_20261112 tests.test_taraz_frozen_aaas_inventory_20261112 -q: 6/6 PASS after updating the older fixed source-count assertion 141 to actual 145.
- New frozen build-7f17dbf72519: source 145 files SHA256 23bd9f26a7954220f0e3720483a355a9442f15a0505960968d5a5edd1bd09ff7; EXE SHA256 301dfede5eeaa597f73c03b86d17fcee6f23083ac78e3945b161aef547937ede; ZIP SHA256 f6f1ca75bfcdbef0246ee54cf7028a143a4a63b6320bdb94be8c66aaeecb7db9; build not installed.
- New exact Frozen EXE private QA: PASS_NATIVE_THREE_SCREEN_NAVIGATION_VIEW_ONLY, exit 0; CDP probe exit 1 BLOCKED, cdpFlagInOwnedWebView=true and cdpPortListening=false. QA-owned frozen window closed gracefully; original installed app and accounting book hashes preserved.

## Approved and open

Product requirements APPROVED: LAN host, customer-managed enterprise host,
Cloud plus on-premises offline node, online Cloud, AI optional, and all core
business functions available without internet. Network hardware/customer
LAN maintenance is customer-owned. Application sync, CAS and recovery are
product obligations.

OPEN: formal financial single-writer authority and fencing, Cloud/Local lease
transfer, split-brain prevention, conflict resolution, backups, tenant key
boundaries and RPO/RTO. PostgreSQL DB2, financial cutover and production
service mutation are blocked or not authorized.

Release decision: NOT READY FOR APPROVAL.
