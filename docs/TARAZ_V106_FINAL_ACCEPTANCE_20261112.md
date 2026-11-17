# Taraz 1.0.6 - Final Clarify candidate (2026-11-12)

**Final immutable build:** `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-777cb53341bb`

* Source inventory: **138 files**, SHA-256 `d07e92f054066858459d4d836de7bf4a56ece0362e8ae9ece755e743ef7a5fcf`.
* Non-QA Windows EXE: PE 1.0.6.0 / PYZ 1.0.6; SHA-256 `54aa3f8ca32703bbc20a033a281197fb1e1cbe88889d6951e92803c702b4b6a4`.
* Offline ZIP SHA-256: `724ae4448f468f3f873bc6d4096b094483d08d1aaa1f6dae9f3f294bdcbc0691`.
* Manifest SHA-256: `9caf1a303c789ed3f8fa9c92ad3bb353c5ed050a6cd108299486ca71607ac27b`.

## Implemented

* One-page beginner/advanced invoice: sales invoice/proforma choice; existing/new/walk-in customer with explicit party registration; real item-code suggestion/accept/reject/hide; actual catalog units or uncoded fallback; automatic trailing line; separate editable explanation; manual draft creation and post-save PDF preview. Financial approval/issue remains a separate human operation.
* Event-sourced actual created/edited timestamps, independent of editable invoice date; journal number and ID shown only when actually issued.
* Order intake: sale/purchase, sold/planned/actual/scrap/healthy-surplus quantities, conservation checks, supplier/stage costs and unknown-cost support, schedule/procurement fields and manual status approvals. Historic estimated waste remains separate from measured scrap.
* Optional **authenticated Madar project picker**: Taraz admin, explicit user consent, pinned private HTTPS host login, server ACL and revision check, only exact source project ID applied manually. Stored projectReference is not a synchronized foreign key. Password not saved with orders.
* Print canvas: presets, movable fields/logo, reorderable columns, real catalog units, multipage preview. Existing Parsian export options preserved.
* Authenticated local-only Ollama qwen3:4b suggestion APIs with strict JSON validation and explicit Apply; no automatic finance. **Real model inference for order and print is not certified**: repeated 35–45s timeouts despite one separate short ping yielding JSON.

## Actual tests

* Final SHA-pinned build completed; PE/PYZ/assets byte parity verified; v106 builder/disposable installer suite **8/8 passed**.
* Focused Python contract/build tests **31/31 passed**, expanded relevant Python source regressions **52/52 passed** before the final UI-only picker change.
* Final compiled Vite synthetic-host Edge UI tests **12/12 passed** for beginner invoice, print and project picker; separate final compiled asset invoice Clarify Edge tests **7/7 passed**. Updated order browser tests **13/13 passed**.
* Final actual Windows EXE Green private smoke **PASS_GREEN_V106_PRIVATE_NATIVE_STARTUP_ONLY**: verified non-QA executable launched, WebView+accounting bridge loaded, private window observed, 181 backed-up QA files rehashed, no financial operation or input sent, all test-owned processes exited and user processes were preserved.
* Independent native UIA testing of prior build observed actual Madar panel/consent, but WebView CDP controls were unavailable; native invoice/order/print end-to-end acceptance and physical printer remain **unverified**. Browser E2E uses synthetic host and is not a substitute.

## Current operational status

* Installed production pointer remains **1.0.4**. The final v1.0.6 binary is built and Green-testable, **not installed**.
* Final install preflight refuses operation when existing installed Taraz windows are running. This is expected and protects unsaved work. No process force-kill, ledger migration or pointer modification was carried out.
* Current test launcher: `Run-Taraz-v1.0.6-GREEN-FINAL.cmd`; SHA-pinned installer: `Install-Activate-Taraz-v1.0.6-FINAL-WHEN-CLOSED.cmd`; rollback: `Rollback-Taraz-v1.0.6-FINAL-To-1.0.4-WHEN-CLOSED.cmd`, all under the v1.0.6-aaas folder.
* No full autonomous AaaS orchestration, live Madar integration login or installed financial flow has been independently certified. These claims remain open, not hidden beneath passing unit tests.
* Original source worktree contains pre-existing dirty/untracked changes; no blanket reset or unrelated commit was made. Immutable source manifest and binaries are retained.