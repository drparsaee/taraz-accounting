# TARAZ PRIME | Integration & Independent Acceptance

Date: 2026-11-12. Scope: isolated Windows worktree and synthetic QA companies.
**Decision: NOT READY FOR APPROVAL.** Completed, passing, and blocked gates
are deliberately kept separate. No install, real payment, official financial
post, remote Madar production write, global input, or release promotion occurred.

## Source and immutable candidate

- Branch: `codex/taraz-final-integration-20261112`
- Baseline HEAD before integration: `653089bb99747ab1c909cfdb113d2d12bc36e47a`.
- Scoped commits: `e658702` (invoices/print), `60e0390`
  (orders/Agent/Madar), `f064609` (MTR authority/peer integration),
  `ec0ced7` (independent QA and reproducible evidence), `bcef425`
  (durable Madar attempt log and read-only lost-acknowledgement recovery).
- All **141** runtime source inventory paths are tracked in Git. Tracked
  working tree and index were verified clean following the integration commits.
  Historical untracked files were deliberately preserved, not staged globally.
- Source fingerprint: `1661fab1c4e6dd66a70bd596f002a28d7db11dd30816c1ac20d0422d392abe4f`
  (rechecked after integration, identical to build source freeze).
- Uninstalled candidate:
  `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-8498c703dc4d`.
- EXE SHA-256:
  `3462cfb0dc93365e202686691eb74cc1b97dcde0333c44266191db934a42e9f4`.
- ZIP SHA-256:
  `9f8039c50f094f446856d2a69d26f2a59bf204c27500002df8f1304a8d9edebc`.
- Manifest SHA-256:
  `a11cd4691545cf615be4661b23793f87508927dc5025170fb0556be86b2b7278`.
- This **latest build** was made after committing source `bcef425`. Its
  141-input SHA was checked again after the build. Previous uninstalled
  `build-69285b6c27de` remains a superseded historical candidate, not
  current acceptance evidence.
- Installed version 1.0.4 preserved. The build remains uninstalled.

## Gate verdicts

| Gate | Actual verdict | Verified boundary | Open blocker |
| --- | --- | --- | --- |
| A: Frozen EXE E2E | **BLOCKED** | Executable/ZIP/PYZ/compiled UI parity 3/3 PASS; real frozen navigation and owned-window smoke PASS; clean graceful exit | Full invoice/proforma Save/Edit/Reload, order/memory UI and PDF/print directly inside this frozen EXE **not** proven. WebView2 had the exact remote-debug port flag, yet its local CDP listener was not available |
| B: Phase 4 | **VERIFIED PASS** (source/backend/SQLite); frozen portion **BLOCKED** | 100 sold/120 produced/5 scrap/15 healthy surplus; six actual cost stages 665,000 RIAL; two synthetic settlements 500,000 + 2,000,000; independent SQLite reopen and accounting Draft with zero journal | Frozen UI completion still blocked; no real banking or settlement performed |
| C: AaaS | **BLOCKED** for actual model autonomy; rule-based flow **VERIFIED PASS** | Persian intent mapped to read-only real SQLite tools; versioned memory propose/accept/reject, roles, source revision, separate companies and explicit human confirmation | `qwen3:4b` timed out at ~22s and `qwen3:0.6b` failed closed in 2/2 realistic ~17s calls. No reliable LLM proposal/action workflow proven |
| D: Madar | **BLOCKED** operationally; source contract **VERIFIED PASS** | Authenticated pinned TLS, CAS, task/checklist/stage status, manual-edit no-clobber, **durable pre-POST attempt audit**, lost-acknowledgement status and recovery by **read only** (no automatic retry) | MadarHost not present/reachable in bounded test environment; no authorized live host E2E |
| E: Source Integration | **VERIFIED PASS** (scoped) | Five commits, all runtime files tracked, clean tracked source at frozen SHA, untracked unrelated data preserved | No merge, push, installation or production activation requested or performed |
| F: Independent QA | **VERIFIED PASS** for 5 fresh source-side cases; product acceptance **BLOCKED** | Independent QA makes direct raw SQLite assertions, uses isolated fresh fixtures and deliberately does not inherit implementer verdicts | Full frozen/hardware/model/live-Host verification not available |

## Five independent QA scenarios

Run:
`py -3.12 -B -m unittest tests.test_taraz_prime_independent_qa_20261112 -v`.
Observed **5/5 PASS** after correcting two defects in the *QA harness* itself
(a SQLite connection not closed on Windows, and an erroneous expectation that
an identical replay of a manually edited Madar task should raise instead of
returning `ALREADY_SYNCED`). No authorization was weakened to pass the tests.

1. **Invoice to print:** **VERIFIED PASS** for source accounting API
   invoice/proforma create, reload, edit, revision, no journal; source-hosted
   WebView2 PDF/template/modes separately PASS. **BLOCKED** for whole frozen EXE.
2. **Order to synthetic settlement:** **VERIFIED PASS** in disposable SQLite,
   including six stages, all source measurements, payments, Draft handoff and
   independent table rows; **BLOCKED** for frozen GUI end-to-end.
3. **AI request to allowed action:** **VERIFIED PASS** for *human-approved
   rule-based memory action only*. **BLOCKED** for real model-based operational
   intelligence and frozen GUI.
4. **Taraz–Madar operational link:** **VERIFIED PASS** for isolated state adapter,
   pinned-host contract, durable attempt audit, crash-safe `TRANSMITTING`
   state and read-only `RECOVERED_CONFIRMED`/`REVIEW_REQUIRED` reconciliation,
   including simulated lost-acknowledgement and zero repeat-POST checks.
   **BLOCKED** for live MadarHost.
5. **Data/ACL/recovery/anti-posting:** **VERIFIED PASS** on synthetic data and
   independent restart/readback; **NOT TESTED** for production interruption
   recovery or real account permissions beyond test personas.

## Other reproducible results

- `py -3.12 -B -m unittest tests.test_taraz_integration -q`: **22/22 PASS**.
- `node --test tests/taraz_settings.test.cjs`: **6/6 PASS**.
- Nine isolated MTR modules' suite: **135/135 PASS** (~244 seconds).
- `npm run test:orders:all` on **current runtime SHA**: Vite PASS,
  **59/59 Python**, **16/16 Edge**, source-hosted native
  `PASS_ORDER_NATIVE`, exit 0; **not** frozen.
- `node scripts/run_taraz_p1_checks_20261112.mjs --native-current-source`
  repeated as a standalone run: Vite PASS, **34/34 Python**, **11/11 Edge**,
  real WebView2 source-hosted create/edit/reopen and PDF PASS (82,142 bytes),
  no journal, actual template persistence, no installed-profile mutation.
  One **overlapping** earlier run saw `ERR_EMPTY_RESPONSE` from a temporary
  HTTP QA fixture; do not assert that concurrent test runs are stable.
- Madar operational isolated/recovery tests: 20/20 PASS; additional
  combined QA/Madar/frozen static test selection 28/28 PASS.
- Latest frozen structure independent test 3/3 PASS; including module
  inventory static checks 6/6 PASS. Separate private CDP policy guard
  had 3/3 PASS on the preceding candidate and was unchanged.
- `git diff --check` exit 0; old LF/CRLF advisories on source files only.

## Native Windows and print boundaries

- Private frozen EXE read-only smoke: `PASS_NATIVE_THREE_SCREEN_NAVIGATION_VIEW_ONLY`.
  It cannot be promoted to user-equivalent end-to-end acceptance. The actual
  Chromium UIA provider does not expose needed invoke patterns for every
  control. Private CDP probe on new frozen build recorded
  `cdpFlagInOwnedWebView=true`, `cdpPortListening=false`,
  `qaProcessClosedGracefully=true`, `privateLedgerUnchanged=true`, and
  `installedBaselineUnchanged=true`. Earlier private orphan was recovered
  by uniquely owned `WM_CLOSE`, with no forced termination.
  The latest probe evidence is
  `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\frozen-aaas-cdp-private-qa-20261112\qa-feef6dfff27d\frozen-cdp-report.json`.
  The latest frozen view-only report is
  `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\current-aaas-frozen-view-qa-20261112\qa-final-native-508a9c084abf\native-gui-report.json`.
- The official pywebview `REMOTE_DEBUGGING_PORT` hook was made available
  only to an explicit private QA profile marker, defaulting to OFF; isolated
  guard test 3/3 PASS. Its presence in a production candidate does **not**
  establish that CDP is usable; a further security review of this opt-in hook
  remains appropriate before production deployment.
- The system listed Microsoft Print to PDF, XPS, Adobe PDF, OneNote and Fax.
  No physical printer was identified. The independent PDF file path is
  source-hosted PASS; actual Frozen print-dialog interaction is **NOT TESTED**
  and physical output is **BLOCKED**. Do not call virtual printers evidence of
  a physical print.

## Open acceptance blockers and next legal actions

1. Obtain truly accessible **frozen** Chromium interaction using supported
   WebView2 tools or improve app accessibility without bypassing existing
   bridge/auth/financial policy. Re-test exact EXE Save/Edit/Reopen/PDF.
   If source must change, produce and verify **one** new frozen candidate only.
2. Establish actual LLM reliability on synthetic Persian requests with
   missing-field/source checks and bounded timeout; keep the current
   rule-based fallback human-reviewed, not mislabelled autonomous AaaS.
3. Use an explicitly authorized disposable MadarHost when one becomes
   available. Confirm pinned HTTPS, task lifecycle, duplicate/stale revision,
   manual edit preservation and disconnected recovery; do not use real company
   state or credentials implicitly.
4. Validate Windows Print Dialog on the exact EXE and physical output only
   with an available, authorized printer. PDF tests do not substitute for it.
5. After these blockers close, run independent product QA again, freeze a
   clean candidate, obtain operator approval for any install or publication.

**Release decision: NOT READY FOR APPROVAL.** The remaining limitations are
product-acceptance blockers, not permission to certify missing tests as PASS.
