# Taraz 1.0.6 | 2026-11-12 Clarify integration and acceptance

## User intent and release state

This iteration implements the user's Nov 11 Clarify invoice/order/print workflow in an isolated dirty source worktree. **Non-QA Windows v1.0.6 EXE + ZIP exist, NOT INSTALLED.** Installed Blue pointer remains 1.0.4. Existing user ledger/installer were not written by the compiler or Green QA. The visible Green instance uses a verified *cloned* QA profile. No public-launch or real financial-operation certification is claimed.

## Implemented source features (specific scope)

- Invoice beginner: direct choice of sales proforma or sales invoice; existing/new/walk-in customer path with explicit real `party.register` and no phantom customer; item code suggestions from actual catalog, accept/reject/persistent hide; genuine catalog unit or uncoded `???`; automatic trailing row without accidentally saving blanks; separate editable additional note; once removed/edited, transferred Madar suggestion is not auto-reinserted; validation and a single explicit Save Draft. Professional editor preserved; no automatic approve/issue/post.
- Post-save: PDF iframe preview and explicit open-for-print link for saved invoice/proforma; no printing/financial posting automatically. The original print/Parsian FR3 export remains. Actual printer and browser download not independently verified.
- Event audit: read-only, authenticated projection of `createdAt/By`, `editedAt/By`, `lastChangedAt/By/EventId` from authoritative events; separated from editable `documentDate`. Issued invoice number and journal ID are visible when existing. No historical event mutation/backfill.
- Order: sale/purchase independent of journal; planned production vs actual produced vs measured scrap vs healthy surplus; balance before delivery for new orders, legacy compatibility; project reference, scheduling and procurement notes; unknown supplier/cost remains unknown; manual confirmation before status transitions. Local deterministic suggestions remain visibly rule-based.
- Print designer: movable fields + logo, three presets, reorderable/optional columns, real catalog unit resolution, multipage preview/print; optional on-device AI suggestion of safe layout settings staged until human accepts.
- Two authenticated *suggestion-only* APIs use fixed local `127.0.0.1:11434` qwen3:4b; no automatic order/ledger write, no external model endpoint. Fallback offline rules remain. Local real model service did not complete inference in 14/35/45-second attempts; genuine AI functionality NOT end-to-end verified.

## Frozen native candidate

- Builder: `scripts/build_taraz_v106_aaas_20261111.py`
- Frozen source files: 138
- SHA-256 of frozen source inventory: `f54e6fcfec63eb961dce1da7a26e8f80c34fc4f4b272c4e83a1ae50e185fe2a5`
- Immutable build directory: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-561050d1d27d`
- Actual EXE SHA-256: `c3afa5e1bbb27edd41a1f6e05256fc78e37e50fe2655880e585fe20d023e4e8f` (17,104,293 bytes)
- ZIP SHA-256: `dda3ad882f92ae95f68dce0e677be91303861a38eab32734bd42f1ed517df041`
- Manifest SHA-256: `6e13f4ba858b1304435a82b5bd5df1ab3cb3134b801c5d2aab1db1781531d87b`
- Windows PE: 1.0.6.0; frozen PYZ: 1.0.6; QA_ONLY=False; packed UI byte parity=True; required native API and model modules included.

## Executed checks (bounded to their evidence)

- v1.0.6 build/package source freeze; 8/8 `tests.test_taraz_v106_aaas_20261111` passed after compilation, zero skip.
- Source synthetic backend/AI/order tests: 29 results, 28 passed plus one release-candidate prebuild skip, then full v106 suite 8/8 after build.
- Source order tests 11/11 JS, new print Edge tests 3/3, new invoice worker Edge+Vite tests 7/7, older invoice compiled-v106-assets Edge tests 6/6; no live financial posting.
- Prepared separate Green QA ledger cloned from a cold backup, 181 files individually hash checked. Private desktop *real compiled v1.0.6 EXE* startup PASS: WebView loaded, accounting JS bridge present, window visible on private desktop, owned processes cleaned, original Taraz PIDs intact, no input/financial operation.
- Visible v1.0.6 Green launched to user desktop from isolated profile (PID originally 13208); existing installed pointer remains 1.0.4; Blue installed EXE SHA remains `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce`.

## Operator paths and safe next action

Working folder: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas`

- `Run-Taraz-v1.0.6-GREEN-TEST.cmd`: launch compiled v106 against isolated copied QA data; NEVER writes Blue ledger.
- `Install-Activate-Taraz-v1.0.6-WHEN-CLOSED.cmd`: SHA-pinned preflight then install + atomic pointer activation; only when installed Taraz processes have been closed. Not executed.
- `Rollback-Taraz-v1.0.6-To-v1.0.4-WHEN-CLOSED.cmd`: SHA-pinned pointer rollback after activation; not executed.

## Explicit remaining verification/gaps

- Real on-device Ollama generation currently times out; app's deterministic fallback is available but **not** autonomous AaaS. No external AI provider is silently used.
- `projectReference` is a validated operational reference, not a verified cross-app Madar project link or bidirectional sync.
- Native Green has a startup proof, not full native UI click-by-click invoice/order/printing/finance acceptance. Physical printer and actual installed v106 regression/rollback need operator-controlled acceptance.
- Installed Blue 1.0.4 remained in use when tested; v106 install/activate has NOT been executed and may be blocked until all running Taraz windows are closed. No automatic migration from QA clone.
- Original isolated source worktree was already dirty before this project continuation; no blanket reset/cleanup/commit has been performed.
