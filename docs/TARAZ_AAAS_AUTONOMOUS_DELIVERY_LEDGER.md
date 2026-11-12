# TARAZ AaaS — autonomous delivery ledger

**Owner:** Prime (single decision maker). **Mission:** deliver the user-defined AaaS product, not merely build or package a conventional accounting app.

## Source and non-destructive rules

- Candidate worktree: `D:/CoS-Test/000- Taraz/taraz-mtr-e2-isolated-20261109`.
- Observed HEAD on 2026-11-12: `653089bb99747ab1c909cfdb113d2d12bc36e47a`.
- The worktree has substantial modified and untracked work. It is **not** an integrated release commit. Preserve existing work. Do not reset, clean, delete, overwrite, or conflate it with `main`.
- The 2026-11-12 P0 ledger names `build-e1723a88abe2` as the latest frozen corrected candidate, while the newer print-position source fix is **not** packed into that EXE. See `docs/TARAZ_P0_P1_SOURCE_GATES_20261112.md`.
- No user installation, production finance data, financial approval, public release or live Madar write may be changed without explicit user authorization. Only isolated QA data and user-controlled acceptance operations are allowed.

## Product contract (not optional enhancements)

1. **Invoice and print:** one-page beginner and complete professional paths on the same data, invoice/proforma, existing/new/walk-in customer, automatic document identifier, editable document date plus immutable real created/edited timestamps, catalog-code suggestions and units, miscellaneous lines and automatic next row, accurate totals/discount/tax, save/reopen, Madar notes copied once without overwriting user edits, automatic post-save preview, multi-page PDF, draggable canvas layout, user-added column/variables and opt-in AI layout assistance. Sensitive finance actions require authenticated human approval.
2. **Order:** sales and purchasing are independent of a quote/invoice. Capture free text and structured requests, identify only supported missing fields, associate customer/project/vendor/stages/timeline, handle production and loss separately from sold quantity (e.g. sell 100, manufacture 120), track real vs planned quantities, stage costs, payments and approvals, then explicitly create the formal Taraz finance event.
3. **AaaS:** actual task-specific agents rather than a decorative chat box. Org-scoped durable, versioned, auditable working memory; minimum follow-up questions at an operator-selected point; inspectable proposals with accept/edit/reject; repeated safe tasks via tools; no invented evidence, silent financial posting or unapproved remote access.
4. **Madar ↔ Taraz:** permissioned project/task/order linkage, revision-aware reconciliation, accountable source identities and no silent duplicate entry. Taraz owns formal accounting; Madar owns operational execution.

## Verified execution in the 2026-11-12 chat, not product acceptance

- `git rev-parse --show-toplevel`, `git status --short`, `git rev-parse HEAD`: executed with CoS terminal; path and HEAD matched above.
- `node --test tests/taraz_clarify_invoice_flow_20261111.test.cjs tests/taraz_clarify_print_20261111.test.cjs tests/taraz_clarify_order_20261111.test.cjs`: 13 passed, 1 skipped, 0 failed; the skipped case is real Edge/Vite invoice flow.
- `py -3.12 -B -m unittest tests.test_taraz_clarify_product_contract_20261111 tests.test_taraz_clarify_order_20261111 -q`: 21 tests passed.
- `git diff --check`: exit 0, with two existing LF→CRLF advisories.
- These are source/synthetic tests, **not** native end-to-end acceptance. There was no EXE build or GUI test in this chat.

## Acceptance gates, always evidence-based

| Gate | Current status | Minimum missing evidence |
| --- | --- | --- |
| P0 trustworthy source | Source identified, integration incomplete | Provenance mapping for dirty files and final build source parity |
| P1 invoice + print | **NOT ACCEPTED** | Integrated current-source EXE, private native create/save/reopen, template save/reopen, PDF inspection; full user-decision UX coverage |
| P2 real purchase/sales order | **NOT ACCEPTED** | Native operator workflow with production/scrap/cost/approval and finance separation |
| P3 autonomous AaaS | **NOT ACCEPTED** | Persisted company memory, bounded task execution, safe corrections/approvals, real model quality and negative QA |
| P4 Madar integration | **NOT ACCEPTED** | Authorized live-endpoint QA with identity, consent, revision, no duplicate entry; user-owned system remains untouched |

## Next autonomous work, in priority order

1. Establish file ownership and build reproducible candidate from the existing dirty source **without** erasing work; run the source regression suite. Reuse already-implemented invoice/order and validator code.
2. Build and test a private/current-source EXE, never activate the installed version. Diagnose native UIA/WebView limitations; do not substitute synthetic browser tests for Win32/WebView save and reopen.
3. Fix discovered UX/backend gaps across P1 and prove them, then P2, P3, P4. Work in complete vertical slices internally without requiring the user to shuttle worker progress.
4. Keep the authoritative acceptance table above updated after each substantive change, including command, exit code, real evidence, side effects and blockers. Never mark a gate ACCEPTED on source presence or a green build alone.

**Reporting policy:** do not ask for routine status confirmations. Surface only verifiable milestones or a concrete blocker requiring the user's intervention. Do not claim continuously running execution unless an actual scheduled task or persistent process has been verified.

## Prime continuation — 2026-11-12, second execution

**Current active phase:** Phase 1 (UX/domain foundation and P1 vertical evidence). Phase 0 source recovery was read back again and source remains the dirty detached worktree at `653089bb99747ab1c909cfdb113d2d12bc36e47a`; `main` remains the clean baseline, not the source of new feature code. The changed files are not integrated into a clean release commit. No workers were created: CoS `agents(status)` returned `self=null`, `run_id=null`, zero retained workers for this caller.

**Reproducible source identifiers:** The previously corrected build `build-e1723a88abe2` remains historical. Before the second bounded backend correction, `--fingerprint` measured 138 runtime files with source digest `b6d63424fbccda75d6fe2699c7ffc07442d403d4e5564b5563389b06eea45362`; builder produced isolated candidate `build-250eead995ca`, EXE SHA-256 `ca290b6c250be0d2c09c92502426d0649343255a019dd1a93f2c2cb18671d308`, marked BUILT_NOT_INSTALLED. **This is not a product acceptance or release.** Later backend print-validation changes yield the *current* source fingerprint `9248a80030bbbfb1d794b2169a9ea0f17d70facf968de328195bccfd64a78861`. The build-250 EXE therefore does **not** contain the latest backend changes. No installed pointer, user ledger, user processes, or deployment was intentionally modified.

**Actual source corrections, test-first:**

- The PHP-free native Python template store allowed a forged A5 table to start outside printable paper even though React had been fixed. New `tests/test_taraz_print_page_bounds_20261112.py` first reproduced **7 failures**, then `standalone_accounting_template_store.py` enforced page-size/orientation-sensitive start position and finite row-height bounds. The fixture uses temporary owned company folders and checks no write on failure.
- The same store allowed invalid duplicate/unknown columns, off-page logo placement and malformed company print metadata. Six independent negative subcases failed before correction. The backend validator now mirrors the current JS constraints while accepting legacy v1 layouts with missing optional fields.
- New `tests/test_taraz_invoice_native_bridge_vertical_20261112.py` exercises authenticated `AccountingDesktopAPI` via real temporary SQLite: two lines, customer registration, draft creation, separate API process-object reopen, revision-safe edit, readback and unchanged journal; rejects stale CAS, premature issuance, and viewer writes. It is host/backend integration, **not** a real native GUI click-through.
- Current frozen EXE Edge synthetic browser test is `tests/taraz_v106_current_invoice_frozen_20261112.test.cjs`; it extracts and hashes the actual embedded compiled UI assets, then checks current invoice flows and Beginner↔Guided↔Professional unsaved-data preservation.
- Print Edge tests now assert each of 32 multi-page invoice rows renders exactly once. Template preview, customization, save, reload and local model explicit-apply controls are covered in isolated synthetic browser tests.

**Executed evidence this turn:**

| Check | Actual observed result | Boundary |
|---|---|---|
| Backend print validation negative tests | Initially 7 failures; corrected; 6 further failures then corrected | Fail-before-fix reproduced on synthetic template folders |
| `py -3.12 -B -m unittest tests.test_taraz_print_page_bounds_20261112 tests.test_taraz_invoice_template_bridge_20261110 tests.test_taraz_invoice_native_bridge_vertical_20261112 tests.test_taraz_clarify_product_contract_20261111 -q` | 25/25 PASS | Real local API and SQLite tests, no live financial data |
| `node --test tests/taraz_clarify_print_20261111.test.cjs tests/taraz_invoice_print_designer_browser_20261110.test.cjs` | 4/4 PASS | Edge synthetic designer and multi-page rendering |
| `node --test tests/taraz_v106_current_invoice_frozen_20261112.test.cjs` | 8/8 PASS | Actual build-250 EXE asset parity, then synthetic Edge host |
| SHA-pinned build runner | PASS, isolated build-250 EXE | Build is NOT acceptance and does not include newest validation change |
| Native view-only QA on build-250 | `PASS_NATIVE_THREE_SCREEN_NAVIGATION_VIEW_ONLY` | Real private Windows EXE, three screens visible, no save/print |
| Private unsaved input probe | UIA `ValuePattern.SetValue` readback 3/3; **overall FAIL safety** | No finance save; `qaProcessClosedGracefully=false` |
| `git diff --check` | Exit 0; two pre-existing LF→CRLF warnings | Not an integration commit |

**Safety blocker requiring next attention:** The last unsaved native input probe left a test-owned Taraz PID **23868** after its guarded `WM_CLOSE` was vetoed by the dirty-editor close flow. The report is at `.../taraz-v1.0.6-aaas/current-source-native-input-probe-20261112/qa-final-native-0ed3b7f7994c/native-gui-report.json`. The process executable path and SHA match the exact isolated build-250; it owns the uniquely identified private desktop `TarazNativeQA_0144fa507b4344`. The cloned ledger SHA and installed baseline matched pre-test, no financial save attempted, pre-existing Taraz PID/start-times preserved, and no process was forcibly terminated. **Do not run another native input QA until the QA-owned orphan is cleaned up safely and independently verified.** Never kill unrelated processes or change global desktop/session settings.

**Product gate:** Phase 1 implementation foundations have strong source, browser and backend evidence, but the complete real Win32 GUI create/save/reopen/template PDF flow and independent operator QA remain **NOT ACCEPTED**. Full autonomous AaaS, production order scenario, two-way Madar integration, real print hardware and deployment are also **NOT ACCEPTED**. The next safe actions are: resolve the isolated orphan without force-kill; finish same-EXE native save/reopen and printing on a *fresh* QA profile; rerun full tests and source freeze; reconcile into a controlled Git commit; independent QA. No further phase may be declared DONE merely on synthetic tests or new installers.

### Additional UI-to-real-backend vertical acceptance (same run)

- Added `tests/taraz_p1_real_backend_http_fixture_20261112.py`: allowlisted loopback-only HTTP test server injects a strictly bounded `window.madar` RPC facade into the **actual immutable build-250 compiled GUI assets** and dispatches to authenticated `AccountingDesktopAPI` + a brand-new temporary SQLite company directory. Rejects accounting actions except party registration and draft invoice/proforma create/update. No user profile or installed program is accessed, and the server has a graceful shutdown endpoint.
- Added `tests/taraz_p1_ui_real_sqlite_20261112.test.cjs`: launches Microsoft Edge against that compiled UI and real Python backend, creates a new QA customer, enters invoice item/qty/price/note, saves a draft, checks the real SQLite-backed revision 2 and journal list `[]`, reloads the entire page, opens saved draft editing, persists a real A5 print template and then edits/saves another template from the **real designer UI**, reloads, and verifies durable template storage. External network requests are blocked. Test initially timed out navigating away from an open professional editor because the unsaved-change confirmation was dismissed; corrected the **test** to explicitly accept discarding only the synthetic editor state. Final command `node --test tests/taraz_p1_ui_real_sqlite_20261112.test.cjs`: **1/1 PASS**, exit 0, without source changes. This is substantive UI→Backend→SQLite integration but runs in Edge rather than native Windows WebView2 and thus does NOT meet the full native gate.
- Additional read-only orphan investigation verified PID 23868 belongs to immutable QA EXE (verified SHA), whose private Win32 desktop is `TarazNativeQA_0144fa507b4344`, and enumerated only its owned windows/children. Existing native close guard vetoed closure with unsaved edits. **No force kill, WinSta0 switch, or other user-process interference performed.** The QA process remains an outstanding native acceptance/safety blocker.

### Recovery of the exact QA orphan, 2026-11-12

- Safe recovery is **DONE** and supersedes the earlier blocker status. Read-only UIA launched on the isolated desktop confirmed exactly one owned Taraz root, one browser dialog with `OK`/`Cancel`, and the source-known unsaved-change discard phrase (boolean match; no private ledger content exposed).
- `py -3.12 -B scripts/qa_taraz_orphan_private_dialog_audit_20261112.py --discard-private` succeeded with `status=EXACT_PRIVATE_QA_DISCARD_INVOKED`, `qaProcessClosedGracefully=true`, `qaLedgerUnchanged=true`, `installedBaselineUnchanged=true`, `noProcessForceKilled=true`. Its preflight verified exact PID 23868, SHA-pinned build-250 EXE, private desktop name, and QA failure report. Only the known private discard-confirmation's unique `OK` was invoked using UI Automation; no global UI input or force terminate was used. PID 23868 has exited normally.
- Fresh full-source candidate `build-98e815dd931c`, source fingerprint `9248a80030bbbfb1d794b2169a9ea0f17d70facf968de328195bccfd64a78861`, EXE SHA-256 `b7d27d1a44c6980a3121827eee9d502ea52a8c27f6d75f67ac67f86bddd09db7`, ZIP `bde8af706df9a16deb8fc878866f5e3ed0a30e05ee16bae69b144596d48e831c`; builder reported `V106_AAAS_NON_QA_BUILT_NOT_INSTALLED`. **Still not an accepted release.** New pinned native view wrapper is `scripts/qa_taraz_v106_integrated_private_gui_20261112.py`.
- The actual build-98 compiled source passed `node --test tests/taraz_v106_p1_current_frozen_20261112.test.cjs tests/taraz_p1_ui_real_sqlite_20261112.test.cjs` with 9 PASS: frozen EXE JS/CSS byte parity, synthetic Edge invoice cases and real loopback Python/SQLite invoice draft/edit, print design save/reload and entire operational order 100 sold/120 planned/120 produced/5 scrap/15 healthy surplus, stepwise confirmations, delivery and reload; no general-ledger journal side effect.

### Later P1 product correction, locked tests and latest immutable QA candidate

- The isolated Native WebView invoice SAVE gate remains **NOT ACCEPTED**. A live window screenshot demonstrated the prior UIA helper found off-screen form controls in a long legacy invoice list; `ScrollItemPattern.ScrollIntoView()` successfully made the walk-in button visible, but that WebView2 button exposed neither reliable InvokePattern nor a trustworthy response to an owned-child HWND mouse PostMessage. The verified QA walk-in selection remained false, so **no save was attempted**. Private copied SQLite did not acquire a financial journal; each failed QA-only process was closed using its uniquely proven unsaved-form discard dialog, without killing any process. This is an **automation accessibility/integration blocker**, not evidence that a human cannot click the button.
- Implemented a bounded user-defined print column slice on the existing canvas: up to four custom column IDs, human-editable header, explicit source mapped to one of seven already-recorded per-line values (`description`, `itemId`, `accountId`, `quantity`, `unit`, `price`, `total`); view/reorder/delete and saved company-specific template; no arbitrary formula, private lookup, or invented data. Files: `src/accounting_print_template.js`, `src/accounting_print_designer.jsx`, `standalone_accounting_template_store.py`, companion tests. PDF pagination uses the same actual row source. Old v1 layouts remain accepted.
- Expanded JS/Python differential print-validation test to 324 page layout permutations plus malformed labels/columns, custom IDs and Unicode non-BMP/UTF-16 cases. The test initially detected raw-title length and eight Unicode/trim mismatches; product Python validation was corrected. Both JS and native Python now reject forged sources, duplicate custom columns, invalid references and off-paper A5 tables. Python store tests exercise actual save/reload and prove invalid updates leave the old template file unchanged.
- `package.json` previously referenced nonexistent `tools/safe_test_runner.py` and Playwright was not declared locally. Added the exact `playwright@1.64.1` dev dependency and npm lock, `npm test`/`npm run test:p1` targeting `scripts/run_taraz_p1_checks_20261112.mjs`. It compiles local Vite UI and performs only the enumerated ephemeral P1 Python+Edge+real SQLite checks. `scripts/verify_taraz_npm_lock_20261112.py` independently reconstructed all locked npm packages with `npm ci --offline --ignore-scripts` in an automatically removed QA directory: **PASS**, Playwright+Vite required versions present. This establishes local offline lock reproducibility, not universal Windows/macOS/Linux runtime certification.
- **Executed full P1 source QA:** `npm test` exit 0, **34/34 Python tests, 11/11 JS/Edge tests, zero skip**. A real Edge UI flow used authenticated Python/SQLite in a temporary company to save/reopen/edit a customer invoice and a user-defined print template, requested a downloadable real PDF, checked PDF header/pages/trailer, and executed order 100/120/120 actual/5 scrap/15 healthy surplus through manual approval and delivery. It verified zero new general-ledger journals. Page-to-native boundaries remain unverified; no printer was used.
- Latest source freeze `91b33ad118c8b855dc1207d491b7fc01675a8d1caa5fc30717beb4d4a3cfc642` across 138 files; isolated non-QA EXE `build-7e54afa3c1a5` SHA-256 `e7020686f15d67b2ae888caef3c65b271494ec98a672fc902f390f35ae33ee63`; created by builder with status `V106_AAAS_NON_QA_BUILT_NOT_INSTALLED`. Actual embedded GUI JavaScript/CSS byte-parity test passed; compiled frozen invoice Edge suite **8/8 PASS**. New SHA-pinned private native VIEW-ONLY QA `scripts/qa_taraz_v106_custom_columns_private_gui_20261112.py --run-private` returned `PASS_NATIVE_THREE_SCREEN_NAVIGATION_VIEW_ONLY` exit 0 with unchanged QA ledger/installed baseline, graceful native close, and all prior user PIDs preserved. This EXE is **not** installed, merged, or independently user-accepted.
- **Acceptance matrix (strict):** P0 source identity proven; integration worktree still dirty and not an authoritative clean release commit. P1 0/10 formal all-gates acceptance because full native draft/save/reopen/print, real printer and all product clarifications remain unproven. P2 operational order backend+Edge flow substantially proven but native finance hand-off incomplete, thus not accepted. P3 real multi-agent execution, organizational memory, quality-gated LLM and P4 Madar synchronization not accepted. Do not count a green build or test subset as those deliverables.

## P1 native source-hosted continuation — 2026-11-12

- Source authority remains the dirty detached worktree at `653089bb99747ab1c909cfdb113d2d12bc36e47a`. The actual latest **uninstalled** build is `build-357bec1519e9` (EXE SHA-256 `f369f99947ad5c7d7c436e4e5716466d5b69e2aeb807b9fba052a26664f3d978`), with unchanged 138-file runtime source SHA-256 `800134e38c7a865aa6a8dfbf48d6cf527a8cd297c1edb6d9739b4a4242fb184d`. QA-only script/doc edits did not change that runtime fingerprint.
- In `scripts/qa_taraz_native_bridge_vertical_20261112.py`, the real isolated Windows WebView2/pywebview bridge was extended to reload the document and edit the same invoice (13,500→18,000 RIAL), exercise **all three beginner/guided/professional modes** with verified field preservation, check trusted create/edit actor/timestamp projection and reject a stale CAS update with no database mutation. It additionally reopens **the same proforma** and edits 5,000→7,500 RIAL via its actual UI navigation and form, with independent SQLite readback. Final revision **5**, zero journal entries, no issue/approve/post/send or production ledger mutation. A QA-only detached React node and a closed-drawer navigation selector caused temporary test failures and were fixed without weakening the assertions.
- The final `py -3.12 -B scripts/qa_taraz_native_bridge_vertical_20261112.py` and `npm run test:p1:all` both returned **exit code 0**. The latter ran **34/34 Python**, **11/11 JavaScript/Edge** and the enhanced **native source-hosted** vertical. `git diff --check` returned 0 (two existing LF/CRLF warnings). A following `Get-Process -Name Taraz` returned no matching process (PowerShell exit 1), consistent with no Taraz process at that instant, not proof of permanent inactivity.
- **Acceptance remains open:** this test's host is development Python even though WebView2, compiled UI, API bridge and SQLite are real and matched to frozen EXE assets. Full human-equivalent invoice click-through on the actual PyInstaller EXE, physical printer verification, historical Clarify coverage audit, reviewed integration commit and separate independent acceptance QA are not completed. The native view-only frozen EXE result must not be promoted into a full product pass. Remain on P1; do not start P2/P3/P4 or install/publish based on this run.

## Prime resumed execution — 2026-11-12, current source/Phase4–6 integration

**Source authority:** Detached/dirty worktree at `653089bb99747ab1c909cfdb113d2d12bc36e47a`. CoS `agents(status)` returned `self=null`, `run_id=null`, no recoverable worker; **no new worker spawned**. No Git reset/clean/commit/push, installed app change, financial posting or Madar live write was performed.

**P1 and financial-control correction:** Historic test `tests/test_taraz_clarify_order_20261111.py` improperly attempted admin-only approval/delivery as an editor after the backend added an explicit privilege gate. The test now asserts that the editor is rejected, then uses admin for authorized transitions. Synthetic Edge harness `tests/taraz_clarify_order_20261111.test.cjs` supplies an explicit `canAdmin` to test authorized transitions. **No backend authorization was weakened.** Targeted Python 12/12 and Edge 4/4 PASS. Extended actual SQLite/accounting test to register an explicit vendor and prove purchase `bill.create` yields only an idempotent expense `5000` Draft, with no sales invoice, journal, posting, foreign-currency conversion or duplicate; order vendor is currently represented by the legacy `customerId` field, and this alias needs future product migration review.

**Reproducible execution, this resumed session:**

| Gate and command | Observed result | Trust boundary |
| --- | --- | --- |
| `py -3.12 -B -m unittest tests.test_taraz_order_accounting_draft_20261112 -v` (before added purchase case) | 3/3 PASS, exit 0 | Real disposable SQLite, no production finance |
| `py -3.12 -B -m unittest tests.test_taraz_aaas_agent_20261112 -v` | 3/3 PASS, exit 0 | Tool-backed, rule-based Agent and versioned SQLite memory; no autonomous LLM inference |
| `py -3.12 -B -m unittest tests.test_taraz_clarify_order_20261111 tests.test_taraz_order_accounting_draft_20261112 -v` (after corrections) | 12/12 PASS, exit 0 | Sale and purchase Draft, local role/Idempotency checks |
| `py -3.12 -B -m unittest tests.test_taraz_madar_order_sync_20261112 tests.test_taraz_madar_order_api_gate_20261112 tests.test_taraz_madar_order_link_20261112 -v` | 12/12 PASS, exit 0 | Auth/ACL/Revision/duplicate and actual Madar source schema validator when present; no real LAN Host POST |
| `npm run test:orders:all` (latest run) | Vite build PASS, 36/36 Python, 16/16 Edge, `PASS_ORDER_NATIVE`, exit 0 | Source-hosted private WebView2/Bridge/SQLite; independently readable order and Agent memory |
| `node scripts/run_taraz_p1_checks_20261112.mjs --native-current-source` | Vite build PASS, 34/34 Python, 11/11 Edge, `PASS_WEBVIEW2_REAL_BRIDGE_DRAFT` including `PASS_RELOAD_EDIT_WEBVIEW2`, exit 0 | Source-hosted **current** native WebView2, not frozen EXE |
| `py -3.12 -B -m unittest tests.test_taraz_frozen_aaas_inventory_20261112 -v` | 3/3 PASS, exit 0 | Static checks of source/builder contract; not a frozen binary test |
| `git diff --check` | exit 0; existing LF→CRLF advisories | Changed files remain dirty; no commit |

**Native P1 evidence:** Current-source QA retains a separate, strict frozen-parity default and an explicit `--current-source` mode. The latter binds the tested HTML/JS/CSS and 141 runtime source inputs to fingerprint `223f87be3892e4567a412701510f100d0607957b47794574994576e9b52b98fb`; verifies unchanged before/after. It saved/reopened/edited **the same** invoice (13,500 → 18,000 RIAL) and proforma (5,000 → 7,500 RIAL), preserved all three editor modes, created 82,142-byte PDF and persistent user print template, authenticated audit ownership, rejected stale CAS, created no journal, and verified installed baseline/processes unchanged. The former historical frozen-parity test correctly rejects source mismatch with the older build. Protective pywebview exceptions for unverified personal accounting access and a temporary WebView folder deletion warning remain in stderr; no false zero-error claim.

**Phase 5:** `taraz_aaas_agent.py` and native bridge perform real order/memory tools, rejection/idempotency, human approval and provenance; `modelRan=false`. This is **not** an accepted model-autonomous AaaS engine. The separate loopback Ollama order-intake advisor does not establish autonomous operational planning.

**Phase 6:** `taraz_madar_order_sync.py` implements pinned HTTPS preview, CAS write contract and idempotent task association; synthetically patched host writes and native Madar schema validator pass. **No authenticated real Host end-to-end two-way sync or disconnection recovery has been proven.** A project reference alone is not a sync.

**Frozen delivery hardening:** Previously the v1.0.6 builder did not explicitly require AaaS and Madar runtime modules inside the frozen PYZ, despite their inclusion in the runtime source inventory. The builder now requires and checks `taraz_aaas_agent`, `taraz_madar_order_link`, `taraz_madar_order_sync`, all new native/bridge API entrypoints, `TarazOrderStore.get`, and exact runtime UI witnesses. Dedicated three-case static contract QA passed. The actual non-installed frozen candidate's build and binary attestation must be recorded separately, once complete; a successful source Build never means released/accepted.

**Remaining non-negotiable gates:** Direct full PyInstaller EXE form clickthrough and PDF/template save/reopen (not just source-hosted, view-only or Edge), real printer, independent QA/operator audit, live Madar authorized bidirectional synchronization with recovery, and measured LLM-agent quality. No production installation/activation or financial posting authorized.

### Frozen 1.0.6 candidate after explicit module gate

- Source lock: **141 inputs**, SHA-256 `223f87be3892e4567a412701510f100d0607957b47794574994576e9b52b98fb` (rechecked unchanged after build). `scripts/build_taraz_v106_aaas_20261111.py --build --freeze-sha <exact pinned SHA>` returned exit **0** with status `V106_AAAS_NON_QA_BUILT_NOT_INSTALLED`; build directory `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-05511322d050`. No installation, live ledger write or pointer change.
- EXE SHA-256 `fd613f23883dc716277811fc6a908f18bec823bfac39a9ddb76392f59be24ee9`; ZIP SHA-256 `93de7178c46a8bc5ded3710de54f7714d9f43927896cb338b178e06e174ed797`; manifest SHA-256 `821048eff3df0d42848740f9df1bca3bdfef0522ef5827ae06cd6b814970b47a`.
- Actual builder report independently reopened: embedded native API includes Finance Draft, Agent Review/Memory and Madar Preview/Commit; actual PYZ contains `taraz_aaas_agent`, `taraz_madar_order_link` and `taraz_madar_order_sync`; compiled HTML/JS/CSS byte parity checked. Actual EXE and ZIP hashes recomputed. Installed 1.0.4 pointer, launcher and binary hashes agreed with pinned baseline.
- New separate read-only `tests/test_taraz_v106_current_frozen_aaas_20261112.py` does **not** call the builder or accept its claimed PYZ module list as proof. It reopens the actual PyInstaller archive, recursively inspects frozen code method names, hashes actual embedded UI bytes and ZIP member, compares installed pointer read-only. **3/3 PASS**, exit 0.
- `py -3.12 -B scripts/qa_taraz_v106_aaas_current_frozen_private_gui_20261112.py --static`: exit **0**, SHA-pin/actual EXE UI byte parity, 181 copied cold-backup files independently rehashed. `--run-private`: exit **0**, `PASS_NATIVE_THREE_SCREEN_NAVIGATION_VIEW_ONLY`, private real frozen PyInstaller EXE, owned Win32 desktop, startup/Bridge and order/invoice/print navigation witnessed; actual private test process closed gracefully; clone ledger/installed baseline/prior Taraz processes unchanged. UIA `InvokePattern` or `LegacyIAccessiblePattern` still missing for some Chromium controls; the human-equivalent **Frozen EXE save/reopen/edit/PDF is NOT proven**. Never confuse this view-only check with the source-hosted vertical.
- Decision: **Candidate built and structurally verified, product release remains NOT ACCEPTED.** No commit, merge, promotion, install, activation, printer operation, real Madar host mutation, real finance action or independent human QA was performed.

## Project control and PostgreSQL roadmap — 2026-11-12

The project now has a single documentation entry point:

- docs/README.md: document index and status overview.
- docs/TARAZ_MASTER_ROADMAP.md: product scope, phase order, dependencies and acceptance gates.
- docs/TARAZ_POSTGRESQL_MIGRATION_PLAN.md: proposed target architecture, SQLite inventory, migration stages, reconciliation, security and rollback.
- This ledger remains the execution-evidence record; it does not replace the Roadmap.

### Current evidence snapshot

The latest user-supplied TARAZ Prime handoff reports:

- Source baseline 653089bb99747ab1c909cfdb113d2d12bc36e47a, dirty tracked/untracked Worktree and git diff --check exit 0.
- P1 current-source WebView2 invoice/proforma save, reload, edit, template and PDF scenarios pass; full click-through inside Frozen EXE and physical printer remain open.
- Finance Draft 3/3 and Agent Memory 3/3 reported PASS.
- npm run test:orders:all reported Vite build success, 26/26 Python, 16/16 JS/Edge and PASS_ORDER_NATIVE; the Frozen EXE order flow remains unaccepted.
- Frozen candidate build-05511322d050 was built and structurally checked, not installed. Native Frozen EXE evidence is view-only three-screen navigation, not full Save/Edit/PDF acceptance.
- self=null, run_id=null; no Worker was recoverable. No install, release or operational financial write was performed.

**Evidence reconciliation required:** the latest handoff reports 26/26 Python tests for npm run test:orders:all, while the preceding Ledger entry records 36/36 Python tests for a related run. The exact raw output and runner revision must be reconciled before any formal P2 acceptance. This documentation task did not rerun either suite.

### PostgreSQL status

PostgreSQL is a proposed central data platform, not an implemented migration. Source inspection found:

- Main accounting SQLite is a revisioned canonical JSON/event snapshot with a SHA-256 digest and WAL.
- Order SQLite schema v2 contains orders, actions, audit, actual stage costs, payments and finance handoffs.
- Agent memory and Madar project links use separate company-scoped SQLite sidecars.
- No PostgreSQL driver/configuration or Alembic migration structure was found in the bounded Worktree search.

No application code, SQLite database, installed program, installer, production data or Git history was changed while creating these project-control documents.

### Next controlled actions

1. Continue P1 Frozen EXE and historical Clarify acceptance; keep printer hardware as a separate gate.
2. Complete P2 Frozen EXE order workflow and reconcile the test-count discrepancy.
3. Decide deployment topology and offline policy before implementing DB2 of the PostgreSQL plan.
4. Build only an isolated PostgreSQL pilot after Repository contracts and schema inventory are approved.
5. Continue P3 Agent model-quality and P4 real Madar Host end-to-end validation without treating source presence as acceptance.

## Prime final integration and independent QA | 2026-11-12

The current, newly verified handoff supersedes the older build/commit inventory
above **for the current release candidate only**. Keep the older snapshots as
historical evidence, never as current acceptance claims.

See `docs/TARAZ_PRIME_FINAL_INTEGRATION_QA_20261112.md` for exact commands,
trust boundaries, five independent QA axes, evidence and blockers.

- Integration branch `codex/taraz-final-integration-20261112`; five scoped
  commits `e658702`, `60e0390`, `f064609`, `ec0ced7`, `bcef425`.
  Runtime source tracked, clean and frozen with exact SHA.
- All 141 runtime files tracked, current source freeze
  `1661fab1c4e6dd66a70bd596f002a28d7db11dd30816c1ac20d0422d392abe4f`.
- **Current uninstalled build** `build-8498c703dc4d`: EXE SHA-256
  `3462cfb0dc93365e202686691eb74cc1b97dcde0333c44266191db934a42e9f4`,
  ZIP SHA-256 `9f8039c50f094f446856d2a69d26f2a59bf204c27500002df8f1304a8d9edebc`.
  Independent binary structure 3/3 PASS; real frozen GUI **view-only** PASS.
- Independent five-case QA fresh disposable SQLite **5/5 PASS** (including
  independent raw SQLite readback); separate MTR tests **135/135 PASS**.
  Current-order suite **59/59 Python**, **16/16 Edge**, Native Source-hosted
  PASS; P1 source-hosted WebView2 **34/34 Python**, **11/11 Edge**, Native
  PASS. These remain **not frozen EXE acceptance**.
- Frozen CDP native process receives the expected flag but no listening
  debugger endpoint. Its QA window exited gracefully; installed 1.0.4 and
  cloned ledger remained unchanged. Gate A **BLOCKED**.
- Actual Persian model `qwen3:4b` timed out in ~22 seconds and `qwen3:0.6b`
  failed closed on two operational synthetic prompts; rule-based
  request/memory flow works but AaaS model Gate C **BLOCKED**.
- Madar project/stage guarded contract and manual-edit no-clobber tested;
  durable sync attempt audit, failed/stale pre-POST refusal, lost-ack
  `OUTCOME_UNKNOWN`, crash `TRANSMITTING` and authenticated read-only
  recovery tested with **no automatic repeat POST** (20/20 isolated tests);
  no real authorized MadarHost present for E2E. Gate D **BLOCKED**.
- PDF source path tested; only virtual printer devices found, no physical
  output proven. Real frozen print dialogue and hardware remain open.
- **Decision: NOT READY FOR APPROVAL.** No install, release, external financial
  transaction, production Madar write, Git reset/clean/push/merge.
