# ECOSYSTEM PRIME — Independent QA / Release Gate Matrix

Date: 2026-11-12. A VERIFIED PASS is scoped only to the code, command,
test environment and output identified in that row. Isolated source QA
never substitutes for frozen/native/production acceptance.

| # | User-required scenario | Status | Evidence and limitations |
| --- | --- | --- | --- |
| 1 | Frozen EXE invoice/create/edit/reopen/print | PARTIAL VERIFIED / GATE OPEN | `build-8ad80825928e`: actual Frozen GUI + independent SQLite confirms same-ID Invoice create 13,500 → edit 18,000, Revision 3→4, no duplicate; Proforma create 5,000 and its creation audit; print template saved. Proforma **edit** not persisted via this QA method and invoice **PDF file not observed**, so full Gate A BLOCKED |
| 2 | Orders, actual costs, production conservation | VERIFIED PASS (isolated); Frozen PARTIAL | Exact Frozen creates synthetic order with sold=100/planned=120 and one stage (Revision 1); records 500,000 incoming amount in order file (Revision 2, status=recorded, never bank). Date field `type=date` cannot be set from current UIA ValuePattern/RangeValuePattern; real cost GUI still BLOCKED. Source-hosted costs remain independently tested |
| 3 | Financial controls, permissions, no unintended posting | VERIFIED PASS (isolated source); live NOT TESTED | Disposable ledgers and draft-only handoffs; official Cloud/Local financial authority OPEN |
| 4 | Agent with online AI | NOT TESTED | New online status checks make no cloud inference; no provider cost/model quality or actual data-consent proof |
| 5 | Agent with installed local AI | BLOCKED | Previous qwen3:4b / qwen3:0.6b inference unreliable/timeout; discovery only, not model success |
| 6 | Core business without AI | VERIFIED PASS (source scope) | Optional-AI tests: disabled status sends no provider request; manual local order/finance code remains available |
| 7 | Full LAN without internet | BLOCKED ecosystem E2E; private loopback PASS | Real ephemeral MADAR HTTPS localhost and real TARAZ client with TLS pin/CAS; not external multi-client/host failover |
| 8 | Full three-product integration | BLOCKED | Real private TARAZ–MADAR task sync, checklist and identity; RADAR source/API NOT FOUND |
| 9 | Cloud loss and local business continuation | NOT TESTED E2E | Local stores work independently, but cloud/local authority switch is not implemented/approved |
| 10 | Reconnection and duplicate-free reconciliation | VERIFIED PASS (isolated contract); Cloud E2E BLOCKED | Durable SQLite outbox: no blind resend, unknown-after-crash, typed receipt, conflict review, required source CAS recheck before dispatch, and no overtake by later unacknowledged entity revisions |
| 11 | Tenant and permissions | VERIFIED PASS (isolated contracts); cross-product identity BLOCKED | Company-scope ACL and negative tests; no actual shared SSO |
| 12 | Backup and restore | NOT TESTED ecosystem-wide | Existing Madar tests do not establish a cross-product RPO/RTO |
| 13 | PostgreSQL parity | NOT TESTED | DB0 five real disposable SQLite schemas and DB1 order read contract; DB2 not authorized until ADR |
| 14 | Installer, rollback | NOT TESTED for new runtime | Installed 1.0.4 preserved. No production install/activation authorization |
| 15 | PDF and physical printer | VERIFIED PASS source-hosted PDF only; Frozen/physical BLOCKED or NOT TESTED | Current source-hosted native PDF 82,142 bytes; on exact Frozen QA, PDF button is accessible and invoked, but no file was found in explicitly configured QA-only Chromium download folder. PDF bytes/pages/content and physical printer remain UNVERIFIED |

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

## Update 2026-11-14 — Exact frozen UIA gate, still open

Candidate `build-8ad80825928e`, EXE SHA256 `70eb46a3430985cca18aeaaf21339a2c7f49fca3f75066f091a8600d862dc512`, 145-file source SHA256 `96cd0132dff1c8769df0dc7e6454241bf61433b85abcb8efaa62730defd3138e`.
Results are independently captured in the disposable Windows profile:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\frozen-synthetic-private-uia-20261112\qa-3edf86189818\`.

| Witness file | Status | Grounded claim |
| --- | --- | --- |
| `synthetic-invoice-fd8552f5.json` | VERIFIED PASS | Real Frozen GUI created `INV-1405-0001`, 13,500; SQLite 1 invoice / 0 journal |
| `synthetic-proforma-63c69fa3.json` | VERIFIED PASS | Real Frozen GUI created `PF-1405-0001`, 5,000; `createdBy=local` in new Frozen |
| `synthetic-invoice-edit-edd257dc.json` | VERIFIED PASS | After restart same invoice changed to 18,000, ledger revision 3→4, `editedBy=local`; still one invoice |
| `synthetic-print-0de9c715.json` | VERIFIED PASS | Custom print template saved via native UI and re-read from QA template store |
| `synthetic-order-create-d66daa34.json` | VERIFIED PASS | Stored order quantity 100, planned 120, 1 stage, order Revision 1 |
| `synthetic-order-payment-4f2d69d4.json` | VERIFIED PASS | Recorded non-bank incoming payment 500,000, same order Revision 2; `financialEventCreated=false` |
| `synthetic-proforma-edit-a83bc0d2.json` | BLOCKED | Controlled input values reverted before save; UIA did not establish a React state change, so Save was not attempted |
| `synthetic-order-cost-6317df45.json` | BLOCKED | Date input exposed month/day/year UIA spinner segments, but SetValue/RangeValue did not persist a complete valid date; cost save was not attempted |
| `synthetic-pdf-invoice-07e73ca8.json` | BLOCKED | Real GUI PDF button was invoked; no PDF in QA-only download directory, so bytes/pages/content not verified |

The initially interrupted Frozen root/child were identified by exact hash, PID, owner-window and private desktop; the QA-only browser discard confirmation was accepted through UIA. Processes exited normally, no Force Kill or global user input occurred. One later transient timeout was likewise recovered without termination. Earlier passing tests were preserved, not restarted en masse.

Only the current disposable accounting book/order files were read/written. Main installed Taraz remained 1.0.4 and unchanged in each completed QA report; journal count stayed zero. Human finance issue, bank API, operational MadarHost, production LAN, install and printer were not touched.
