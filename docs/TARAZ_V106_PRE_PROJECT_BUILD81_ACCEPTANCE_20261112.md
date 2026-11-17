# Taraz 1.0.6 - Clarify acceptance and release readiness

**Source status:** Isolated existing dirty working tree, frozen source fingerprint `cb9c84a349cc09c8f343a8b1b3a5a4fcec1bfa9fa9ec5a0d8d41424e219cad31`, 138 runtime files; identical to current source upon independent final recheck.

**Final built snapshot:** `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-81cd2dc22365`.

**Non-QA EXE SHA-256:** `4b5d17a460e1f5de827f0d36e63e72e27140362b79def5fd268e6e76b7f95731`; `PE 1.0.6.0`, packed PYZ version `1.0.6`, compiled UI byte-parity true.

**ZIP SHA-256:** `801a7dc14d7543ba5d236171ed9825655307d93c863f56476c93d0b8f36b59d5`.

**Manifest SHA-256:** `5a75490c6489bb84155a74b620ed4ccf6dfa26b7f5d0afc8fc32d336d2db407c`.

## Implementation in frozen code

- Beginner/advanced invoice editor, direct sales invoice/proforma choice; explicit registration of new/visiting customer, catalog code suggestion/accept/reject/hide, real unit from catalog, uncoded amount unit fallback, trailing row automation, separate optional note and explain field, human explicit save; no auto-approve/issue.
- Post-save PDF preview, print/open link; draft status and genuine issuance numbering/journal ID. Event-sourced created/edited timestamp projection without falsifying historic event data.
- Independent operational order entry; sold, planned quantity, actual produced, scrap, healthy surplus, balancing and delivery guards; supplier/unknown cost, project reference, scheduling, purchase order fields; user-approved status changes.
- Print canvas templates, draggable logo, reorderable/optional columns, multipage preview/printing; original Parsian profile/template options retained.
- Authenticated local-only Ollama suggestion bridges (`tarazOrderSuggest`, `tarazPrintSuggest`) with explicit human review, strict output limits and no auto financial posting. **Real order/print inference in the app is NOT accepted**: test calls timed out after 35-45 seconds despite separate minimal `/api/generate` ping responding in around 20 s. Fallback remains rule-based and honest.

## Actual execution evidence

- `py -3.12 -B -m unittest tests.test_taraz_v106_aaas_20261111`: 8/8 PASSED, including real Windows disposable install/activation/rollback and compiled ZIP/PE/PYZ member checks.
- Combined targeted Python source suites: 31/31 PASS, before final immutable build. Additional final integrity check confirms exact source SHA unchanged.
- Browser Edge synthetic-host tests from final packed Vite: `taraz_invoice_beginner_20261111` 6/6 PASS, combined orders/print/Edge 15/15 PASS, `taraz_clarify_invoice_flow_20261111` 7/7 PASS against HTTP-served final build assets. The synthetic host confirms no implicit finance posting and correct draft/proforma command contract; it does not validate a real accounting ledger.
- Green profile prepared from 181 independently hash-verified cold-backup files; privately launched **real compiled non-QA EXE** with window, loaded WebView and accounting bridge; private native smoke returned `PASS_GREEN_V106_PRIVATE_NATIVE_STARTUP_ONLY`, 0 test-owned processes left alive, installed user PIDs untouched, no financial action attempted.
- Final compiled Green launched visibly on isolated QA profile to permit manual review. It is not the installed application and does not use live financial data.
- Installed user pointer before/after verification remains `1.0.4` and installed old binary SHA remains pinned. Final PowerShell install preflight returns exit code 1 with expected `Close the Taraz instance using the target installed directory` while v1.0.4 windows are open. NO installation or pointer change occurred.

## Remaining explicit limits

- Installation/activation of v1.0.6 on the real desktop is **BLOCKED until all currently running installed Taraz windows are closed safely**. Do not force-kill them or alter the version pointer manually. Final SHA-pinned install and rollback launchers exist in the package root.
- Real complete native interaction/printing/hardware and all financial flows under v1.0.6 were not yet accepted; startup and synthetic Edge tests are narrower than that.
- A real fully autonomous AaaS agent with verified planning/tool orchestration is not delivered: on-device Ollama has repeated timeouts; existing implementation is validated human-approved suggestions plus offline deterministic rules. No fake LLM success claim.
- `projectReference` is a validated reference, not proof of two-way Madar project sync; reading live project registry requires specific user authorization and source-scoped credentials. No invented ID linkage.
- The original repo had outstanding unrelated dirty/untracked changes before this task; no wholesale reset, hidden commit, or cleanup performed. The final source snapshot and its fingerprint are preserved in the immutable build directory.

## Entry points

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\00-START-HERE-v106-FINAL.txt`

`Run-Taraz-v1.0.6-GREEN-FINAL.cmd` (isolated QA, no installed pointer change)

`Install-Activate-Taraz-v1.0.6-FINAL-WHEN-CLOSED.cmd` (requires all installed Taraz windows closed; SHA-pinned checks)

`Rollback-Taraz-v1.0.6-FINAL-To-1.0.4-WHEN-CLOSED.cmd` (separate rollback, preserves 1.0.4)