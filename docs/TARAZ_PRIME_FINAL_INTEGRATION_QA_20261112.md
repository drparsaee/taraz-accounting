# TARAZ PRIME | Integration & Independent Acceptance

Date: 2026-11-12. Scope: isolated Windows worktree and synthetic QA companies.
**Decision: NOT READY FOR APPROVAL.** Completed, passing, and blocked gates
are deliberately kept separate. No install, real payment, official financial
post, remote Madar production write, global input, or release promotion occurred.

## Source and immutable candidate

- Branch: `codex/taraz-final-integration-20261112`
- Baseline HEAD before integration: `653089bb99747ab1c909cfdb113d2d12bc36e47a`.
- Scoped commits: `e658702` (invoices/print), `60e0390`
  (orders/Agent/Madar), `f064609` (MTR authority/peer integration).
- All **141** runtime source inventory paths are tracked in Git. Tracked
  working tree and index were verified clean following the three commits.
  Historical untracked files were deliberately preserved, not staged globally.
- Source fingerprint: `0c1938319cf7ef1c1fef0ee4b323acc50fabce15fd6791f9267cd37e3f3a76e9`
  (rechecked after integration, identical to build source freeze).
- Uninstalled candidate:
  `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-69285b6c27de`.
- EXE SHA-256:
  `a053a7390474f642494537f2292a1a18b637f376f4b5c4962651c806ef58d91c`.
- ZIP SHA-256:
  `ae7cd92dbf5f405eec2a886b13021890b023501a91e1adef8fa8c79c88a9f3c4`.
- Manifest SHA-256:
  `207ec66fc1ba2a2867a7a45fae1fe21dd30ad361816afaa7f1ca19e133f462da`.
- Build was produced before committing the same tracked source content. Thus
  source SHA parity is proven, but claiming the build command was executed from
  the final Git commit would be false.
- Installed version 1.0.4 preserved. The build remains uninstalled.

## Gate verdicts

| Gate | Actual verdict | Verified boundary | Open blocker |
| --- | --- | --- | --- |
| A: Frozen EXE E2E | **BLOCKED** | Executable/ZIP/PYZ/compiled UI parity 3/3 PASS; real frozen navigation and owned-window smoke PASS; clean graceful exit | Full invoice/proforma Save/Edit/Reload, order/memory UI and PDF/print directly inside this frozen EXE **not** proven. WebView2 had the exact remote-debug port flag, yet its local CDP listener was not available |
| B: Phase 4 | **VERIFIED PASS** (source/backend/SQLite); frozen portion **BLOCKED** | 100 sold/120 produced/5 scrap/15 healthy surplus; six actual cost stages 665,000 RIAL; two synthetic settlements 500,000 + 2,000,000; independent SQLite reopen and accounting Draft with zero journal | Frozen UI completion still blocked; no real banking or settlement performed |
| C: AaaS | **BLOCKED** for actual model autonomy; rule-based flow **VERIFIED PASS** | Persian intent mapped to read-only real SQLite tools; versioned memory propose/accept/reject, roles, source revision, separate companies and explicit human confirmation | `qwen3:4b` timed out at ~22s and `qwen3:0.6b` failed closed in 2/2 realistic ~17s calls. No reliable LLM proposal/action workflow proven |
| D: Madar | **BLOCKED** operationally; source contract **VERIFIED PASS** | Authenticated pinned TLS contract, scoped project link, CAS, duplicate protection, one task/checklist, read-only stage progress, source revision and manual-edit non-clobber | MadarHost not present/reachable in bounded test environment; no authorized end-to-end live host sync or recovery proven |
| E: Source Integration | **VERIFIED PASS** (scoped) | Three commits, all runtime files tracked, clean tracked working tree, unchanged runtime fingerprint, no unrelated untracked deletion | No merge, push, installation or production activation requested or performed |
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
   pinned-host contract and negative gates; **BLOCKED** for real MadarHost.
5. **Data/ACL/recovery/anti-posting:** **VERIFIED PASS** on synthetic data and
   independent restart/readback; **NOT TESTED** for production interruption
   recovery or real account permissions beyond test personas.

## Other reproducible results

- `py -3.12 -B -m unittest tests.test_taraz_integration -q`: **22/22 PASS**.
- `node --test tests/taraz_settings.test.cjs`: **6/6 PASS**.
- Nine isolated MTR modules' suite: **135/135 PASS** (~244 seconds).
- `npm run test:orders:all` before final scoped commits (the same 141-file
  runtime SHA): Vite PASS, **40/40 Python**, **16/16 Edge**, source-hosted native
  `PASS_ORDER_NATIVE`; **not** frozen.
- `node scripts/run_taraz_p1_checks_20261112.mjs --native-current-source`
  repeated as a standalone run: Vite PASS, **34/34 Python**, **11/11 Edge**,
  real WebView2 source-hosted create/edit/reopen and PDF PASS (82,142 bytes),
  no journal, actual template persistence, no installed-profile mutation.
  One **overlapping** earlier run saw `ERR_EMPTY_RESPONSE` from a temporary
  HTTP QA fixture; do not assert that concurrent test runs are stable.
- Frozen structure independent test 3/3 PASS; combined static module and
  private CDP guard tests 9/9 PASS.
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
