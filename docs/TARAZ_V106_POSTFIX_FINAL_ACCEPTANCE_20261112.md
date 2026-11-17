# Taraz 1.0.6: corrected Clarify release candidate (12 Nov 2026)

## Immutable provenance

- Final source inventory: **138 runtime files**, SHA-256 `d926f949b1d002f9a9cdad55265efd313908d61e54e077a4b1b86d06cedc2c1b`.
- Build: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-e1723a88abe2`.
- Non-QA Windows EXE: SHA-256 `eded01af7c8e2676b427a30f8bdabd41d59fba9df4e99a42995cd2d6184f6251`.
- Offline update ZIP: SHA-256 `2850be3a70dabc03bf5676c3c314a46ce5b731a497a342fd2fe1eee31a9651e3`.
- Update manifest SHA-256 `89891eab7138d8c86db65f16e3610465055ee0da573108a04d18ff5b3ed03417`.
- PE/PYZ version 1.0.6, QA_ONLY false; packed JS/CSS bytes verified against bundled dist by builder. `built-not-installed`, not an installed release.

## Source behaviors retained and corrected

- Beginner/advanced invoices: manual invoice/proforma selection, existing/new/walk-in customers with explicit registration, source-backed item code suggestions/units, optional explanations, automatic next blank line, manual draft submission and post-save PDF preview; no automatic approval, financial posting, or payment.
- Read-only trusted event audit: creation and edit time/actor independent of the editable invoice date; actual issued journal number/ID when available.
- Orders: independent sale/purchase records; planned vs actual produced units, measured scrap and healthy surplus, delivery balance gate, optional supplier/stage costs, projects and schedules; no automatic invoice or ledger event.
- Madar project picker is available only to authenticated Taraz administrators; read requires explicit consent and authenticated pinned HTTPS Madar host. No two-way sync or enforced foreign key is claimed.
- Print designer: draggable logo/fields, presets, reordering columns, catalog units and multipage previews; native/model error details are not exposed in the UI.
- Local print layout suggestions use **qwen3:0.6b** at fixed localhost Ollama, bypass proxies and reject redirects, strict allowed output and manual Apply. Real in-process outputs were validated: first cold call 38.81 s; warm 34.93 s; another direct source call 2.55 s and post no-proxy source call 2.42 s. User must inspect semantic accuracy (one proposed color differed from the requested color). Model availability depends on local Ollama; no external service fallback.
- Local order suggestions retain **qwen3:4b** and fail closed if stage kinds or any other content are ungrounded in the request. Real model calls timed out at 45 seconds; no usable end-to-end order AI result is certified. Deterministic offline intake remains available, explicitly labeled rule-based.

## Executed acceptance

- Python built-release, financial contract, order and model bridge tests: **35/35 PASS**, zero failure.
- Print designer Edge browser suite: **3/3 PASS**; final source Vite production build compiled 2,060 modules successfully.
- Admin project picker Edge 3/3, non-admin denial Edge 1/1; independent Madar contract QA 6/6 on current source (older pre-gate immutable build explicitly identified as superseded).
- Final invoice EXE-embedded web-assets synthetic Edge acceptance from prior pre-correction build: **7/7 PASS**. The corrected source changes are scoped to admin-gate/AI model/error handling, so these do not independently certify the newer EXE invoice interactions.
- Verified separate cloned Green profile (181 cold-backup members rehashed). Real corrected EXE `build-e1723a88abe2` private Win32 startup: `PASS_GREEN_V106_PRIVATE_NATIVE_STARTUP_ONLY`; WebView+bridge loaded; no financial action or user-desktop input, original process identities retained, no QA-owned process remaining.
- Exact corrected EXE private native UIA+PrintWindow: `PASS_NATIVE_THREE_SCREEN_NAVIGATION_VIEW_ONLY`; sales invoices, beginner composer, orders, print canvas observed. Backend ledger clone checksum unchanged and installed 1.0.4 unchanged. Native order professional interactions, save, issue, payment, physical print and full end-to-end validation **not** performed.

## Deployment gate and operator safety

Installed production pointer remains **1.0.4**. The latest update/rollback scripts are SHA-pinned and refuse to run while installed Taraz processes are open. Two installed v1.0.4 instances were observed; do not force-close user windows or lose unsaved accounting changes. Only after closing all installed Taraz normally may an operator use the current final installer. Previous 1.0.4 binary remains on disk for rollback.

Remaining product limitations: no fully autonomous AaaS planner/tool orchestration; local order LLM still times out; `projectReference` is a validated or user-supplied reference, not a synchronized cross-app foreign key; native financial posting, printer hardware and actual installed v1.0.6 workflow have not been accepted. Do not report full product completion until those gates are met.
