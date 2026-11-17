# P0 | Current Taraz React click → SHA-pinned packaged PYZ recovery

**Result: CURRENT_REACT_CHROMIUM_TO_PINNED_PYZ_RECOVERY_PASS** on 2026-11-10.
This is a controlled synthetic QA result, **not** installed EXE or release
acceptance. The test uses actual current React JSX and actual embedded Python
code from the specified QA-only executable. It does not simulate a successful
financial transaction.

## Exactly verified inputs

| Evidence | SHA-256 |
| --- | --- |
| QA-only EXE (qa-52f6b2776362) | f3c4d65418d8f9d80a40618c01bb1534841ca18bf863fd9d09d5ca0fb8449662 |
| Preserved 120-input build snapshot | cedd3c8cc51802afe0270cbd08971a1f67347ed3a269d7ec5908fe4c62b6f0cc |
| Embedded PYZ taraz_integration code object | e2c12afc893dff7ab04ba090266e15172309ba4a2e90a6869106fe974e7a457e |
| Actual current src/taraz_settings.jsx | 7d27de48718574ab292b7b7619fcb38be7445ac38bd92d4aaa2ece607dd281f8 |
| Actual current src/taraz_settings_integration.js | 09a4266c7ff6180eb52ab2f88160d0ab658b64fdcae640cd10c5dbf39ba3b371 |

The build manifest was rechecked against those exact pins, including
QA_BUNDLE_VERIFIED, qaOnly=true, installed=false, releaseReady=false, the
three native Inbox methods, 120 snapshot inputs, and the extracted **real**
PYZ recovery code. The React source hashes were checked before and after
the browser run to detect concurrent changes.

## Files and execution

Only these new project files were created by worker-10:

- scripts/qa_mtr_packed_browser_recovery_20261110.py
- tests/test_mtr_packed_browser_recovery_20261110.py
- docs/MTR_PACKED_BROWSER_RECOVERY_E2E_20261110.md

Read-only references: the earlier SHA-gated
qa_mtr_latest_bundle_recovery_20261110.py, its original snapshot helper,
and existing qa_taraz_review_native_browser_20261110.cjs (pattern/reference
only, not executed). No original Taraz source, existing runner or packaged
EXE was edited.

Executed:

    py -3.12 -B scripts/qa_mtr_packed_browser_recovery_20261110.py --manifest-only
    py -3.12 -B scripts/qa_mtr_packed_browser_recovery_20261110.py
    py -3.12 -B -m unittest -v tests.test_mtr_packed_browser_recovery_20261110

The standalone browser run exited 0. The **12 newly added Python tests**
passed **12/12, exit 0** in the final run; both new .py files also passed
Python AST syntax validation.

### Actual UI → packed code path

The Python parent creates two separate, explicitly marked, disposable QA
roots and uses the SHA-pinned PYZ module to synthesize an after-move,
before-receipt crash, one each for the **reviewed** and **rejected**
decisions. Both leave the exact source proposal in reviewed, the immutable
source-digest-bound intent, and **no** review receipt.

One system-installed Edge Chromium process is launched with an ephemeral
QA-only profile. Its pages load bundled, actual current Taraz React JSX.
Playwright exposes only a bounded QA native-function shim that calls
fresh isolated Python -I -B processes, verifies the specified EXE manifest
and PYZ hash again, and executes the actual packed
list_requests / list_recoverable_reviews / recover_review functions.
There is **no mocked success return** from a financial or recovery API.

The observed interaction sequence for **each decision**:

1. Opening Integration, then opting in: **0 backend Inbox reads, 0 recoveries**.
2. Manual Refresh: **one real packed-PYZ Inbox listing**, with the original
   durable decision visible as a manual recovery row.
3. Clicking Manual Recovery: opens a second confirmation, **no backend
   recovery** yet. Cancelling it also performs **zero** recoveries.
4. Reopening the confirmation and clicking Confirm: **exactly one**
   packed-PYZ recover_review via the shim, with manual confirmation true.
5. A post-recovery packed Inbox read: recovery row disappears. The Python
   parent independently rereads the preserved proposal bytes, original
   intent bytes and actual generated metadata receipt and verifies
   financialEventCreated=false.

Each case had **2 Inbox reads, 1 recovery call, 0 normal review calls and
0 financial commands**. The actual call sequence was
list → recover → list. The test checked that source digest and persisted
intent match and that no accounting ledger was used.

The new Python tests also cover pending-only reads, manual=false denial,
legacy receipt with no intent, tampered after-move payload, unsupported
shim operations, unauthorized QA roots, altered hash pins, idempotent
recovery and fail-closed browser-dependency absence.

## Strict limitations

This **did not launch Taraz.exe** or its WebView2 GUI and did not execute
the installed TarazAPI authentication/source_guard path. It is a React
source → disposable shim → exact **packaged integration PYZ** test, not
proof of the full installed native bridge. No actual Taraz app profile,
customer data, financial ledger, real Madar host, live networking,
financial posting, official receipt, installer, signing, commit or push
was touched.

All browser pages have network requests aborted, and background-network
flags were used; no packet-level OS egress audit was performed. Browser
automation used existing system Edge and the read-only globally installed
Playwright npm tooling dependency; no personal accounting profile was read
or written. Browsers' temporary data and bridge fixtures lived in
automatically cleaned QA scratch directories. Durability under sudden
power loss, authenticated installed operator actions and release gates
remain separately unverified.
