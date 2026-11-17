# Taraz 1.0.6 Clarify: independent native/compiled UI acceptance

Date: 2026-11-12 (Tehran). **Decision: PARTIAL. Native GUI acceptance of invoice, order and print is NOT established.**

## Exact second immutable candidate

- Source freeze SHA-256: `cb9c84a349cc09c8f343a8b1b3a5a4fcec1bfa9fa9ec5a0d8d41424e219cad31` (from candidate build report).
- Build: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-81cd2dc22365`.
- EXE SHA-256: `4b5d17a460e1f5de827f0d36e63e72e27140362b79def5fd268e6e76b7f95731`. Independently hashed from the actual binary.
- Embedded `dist/assets/accounting-CVrWdeBJ.js` SHA-256: `1e6a207dcbb92e9388b12b932c6e798268792fabb15ea63f226c9660b0ef2654`. Read directly from the PyInstaller EXE archive; equal to build-report asset digest.
- Cold offline backup: 181 files rehashed by existing backup integrity verifier. The exact contents of the ledger were not reported.
- This is a non-QA build marked **not installed**, with PE version `1.0.6.0`, `qaOnly=false` and native bridge forwarding in its signed-off build metadata. Release signature or publisher signing was not checked.

## Actual Windows EXE and WebView2, separate private desktop

Independent tool: `scripts/qa_taraz_v106_clarify_native_20261112.py`. It SHA-pins the second build and launches that EXE in a new non-input Win32 desktop using an ACL-restricted profile copied from the verified offline backup. The Windows account's active desktop, installed files, active data directories and original Taraz processes are not selected as targets.

Final native evidence: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\clarify-native-qa-20261112\qa-v106-b175ef275454\native-acceptance.json`.

| Check | Observed result |
| --- | --- |
| Real second-build EXE launched on private desktop | **Yes** |
| Actual native WebView loaded | **Yes** (native startup report) |
| Accounting JS bridge present | **Yes** (native startup report) |
| Visible owned private Taraz window | **Yes** |
| WebView2 child processes | **6** |
| Native UI Automation attached to private owned window | **Yes** |
| Native UIA navigation to `اطلاعات مدار` | **Yes** |
| Madar page heading, source and consent controls accessible after navigation | **Yes** |
| Native UIA navigation into print designer | **No**: print menu invocation not available |
| CDP control of actual WebView2 | **Unavailable**: remote debugging flag absent on WebView2 children and localhost debug port closed |
| Native invoice/order/print click-through | **Not performed** |
| Native local Ollama inference/print suggestion | **Not performed** |
| Copied QA ledger file bytes changed by this test | **No** |
| Installed 1.0.4 attestation changed | **No** |
| Pre-existing Taraz processes altered or killed | **No** |
| Test-owned processes remaining after cleanup | **0** |
| Physical printer, actual finance posting or live user account action | **None performed** |

Because CDP was inaccessible and the safe UIA path could not open the section drawer, the overall native outcome is **`PARTIAL_OR_FAILED_PRIVATE_NATIVE_CLARIFY`**, rather than claiming full functional GUI acceptance. The native startup and one real panel navigation are supported by the report. Failed attempts were not counted as passed checks.

## Independent complementary compiled UI test

`node --test tests/taraz_v106_clarify_compiled_edge_20261112.test.cjs`: **1/1 PASS** (headless Microsoft Edge with a synthetic, in-memory host, against the second build's compiled `web/dist` JS and CSS; hashes checked against the candidate build report and the EXE's independently extracted JS).

The actual compiled interface:

- displayed the order screen and switched to the professional order form; request text was entered unsaved;
- displayed the print designer; applied the A5 starter preset and enabled the unit column, with canvas drawn; local model proposal button present in the synthetic capability setup;
- displayed the beginner invoice entry and accepted unsaved line description/quantity/price, with calculation preview;
- sent **zero** synthetic finance/order mutation commands; 4 non-fixture requests were blocked by the test browser before network access, 0 additional bundled assets were served.

The synthetic host reports model methods for UI visibility only: **no Ollama model request or native WebView2 UI interaction is proven by this Edge test**. Full invoice-save, order-save, real local model output, native printing, installed version update and rollback remain outside these checks.

## Reproduction

From `D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

```powershell
py -3.12 -B scripts/qa_taraz_v106_clarify_native_20261112.py --static
py -3.12 -B scripts/qa_taraz_v106_clarify_native_20261112.py --run-private-native
node --test tests/taraz_v106_clarify_compiled_edge_20261112.test.cjs
```

Each native run creates a new restricted QA clone. The script only terminates processes it spawned and recorded, with PID/create-time checks. Do not interpret the `--run-private-native` command's nonzero exit as an EXE startup failure when the report shows a successful startup and blocked GUI automation; read the per-check evidence.

Remaining gate for native click-by-click acceptance: enable a supported accessibility/automation route for the compiled private WebView2 or execute the test manually against the isolated Green profile. The latter would require controlled GUI steps and independent readback; no such claim is made here.
