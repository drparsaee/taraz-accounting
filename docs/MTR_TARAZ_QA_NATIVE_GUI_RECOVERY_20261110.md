# Taraz P0: exact QA-only native EXE recovery startup gate (2026-11-10)

## Outcome

**Actual QA-only EXE startup was attempted inside a disposable Windows QA
profile. Native WebView2 recovery UI was NOT reached or accepted.** This is a
guarded negative test with independent evidence, not a GUI success claim.

The exact tested executable is:

`D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110\qa-52f6b2776362\pyinstaller\dist\Taraz-MTR-QA-52f6b2776362.exe`

| Item | Grounded value |
| --- | --- |
| QA-only EXE SHA-256 | `f3c4d65418d8f9d80a40618c01bb1534841ca18bf863fd9d09d5ca0fb8449662` |
| Pinned 120-source snapshot SHA-256 | `cedd3c8cc51802afe0270cbd08971a1f67347ed3a269d7ec5908fe4c62b6f0cc` |
| Actual PYZ taraz_integration code-object SHA-256 from prior frozen QA | `e2c12afc893dff7ab04ba090266e15172309ba4a2e90a6869106fe974e7a457e` |
| Original build manifest | `QA_BUNDLE_VERIFIED`, QA-only true, installed false, release-ready false |

An existing SHA verifier (read-only), the exact build manifest, all snapshot
input hashes, and the embedded packed native source were checked **before
any executable was started**. The executable is PyInstaller `--onefile
--windowed`, so an unhandled startup exception can cause a modal error that
does not exit automatically.

## Two independently evidenced blockers

**1. Native entrypoint refuses a ledger-free QA profile before creating a
WebView2 window.** The frozen taraz_desktop.run() source checks for a migrated
standalone-accounting.sqlite3 before instantiating TarazAPI or starting
serve_accounting_page / webview.create_window. Subsequent
standaloneAccountingParsianHistory invokes `_source_guard`, which requires
an authenticated personal ledger, revision at least 608 and two specific
historical events. Creating fake entries or bypassing this guard would not
provide a valid test and was **not** attempted.

**2. Exact f3c4 QA build has a real packed HTML bridge omission.** Static
inspection of the *actual embedded* PYZ standalone_accounting_desktop code
showed the JS_BRIDGE injected by serve_accounting_page exposes
tarazIntegrationList and tarazIntegrationReview, but **does not expose
tarazIntegrationRecover**. Both the packed React JavaScript and the packed
TarazAPI method expect it. Thus the full native HTML → pywebview recovery
click is impossible with this build, even given a valid authorized book.

**Corrective change for the source owner:** include
`'tarazIntegrationRecover'` in the JS_BRIDGE allowlist, verify the actual
embedded HTML bridge against the compiled React API, then create a fresh
manifest/SHA-pinned QA build. Prime independently reported making that source
fix later. Neither tested f3c4 nor the subsequent pre-bridge-fix 75d1 build
contains that fix; **do not call them release-ready**.

## Actual disposable EXE launch and refusal

The runner first created a **real packed-PYZ** synthetic after-move,
before-receipt interruption inside an isolated QA-local
`LOCALAPPDATA/Madar-Taraz-Bridge`. It independently verified the exact
original metadata bytes, source digest, persisted decision intent and absence
of a review receipt. All APPDATA/LOCALAPPDATA/TEMP/TMP/HOME/USERPROFILE and
TARAZ_QA_DATA_DIR were redirected inside a fresh, marked, disposable QA
directory; no ledger was provisioned or copied.

Each bounded probe starts **at most one** exact SHA-pinned EXE. The probe was
exercised by the standalone command and again by the automated tests.
The observed outcome in each run was:

- It did **not exit by itself within the 15-second bound**; the runner
  terminated its owned process tree. This is consistent with a PyInstaller
  `--windowed` startup-error dialog or another startup stall, but no error
  dialog was independently identified. No GUI success is inferred.
- No descendant named `msedgewebview2.exe` was observed during polling;
  this is a bounded process observation, not full window enumeration.
- No synthetic accounting ledger file was created, and the exact original
  moved proposal bytes and source-bound intent stayed unchanged. The
  review receipt remained absent. No financial operation was called.
- The test did **not launch installed Taraz**, contact a real Madar host,
  access a personal user profile, supply fake credentials or weaken
  source_guard. No installer, service, signing, commit or push was performed.

Evidence status:
`GUI_STARTUP_BLOCKED_WINDOWED_ERROR_DIALOG_OR_TIMEOUT`.
`actualNativeWebView2RecoveryGuiVerified=false`.

## Subsequent pre-bridge-fix package: optional stable archive witness

The source owner separately rebuilt another QA artifact before repairing
JS_BRIDGE. The new runner can read it without launching the EXE. It requires:

- QA-only EXE SHA-256:
  `75d1aadd2988d2c09b6d9de0516ef63a90445088120199ea7d1916811540d328`
- 121-file snapshot SHA-256:
  `d7e5ff8c0d8c6a87ea2249d73c7589c53587396c8447899610f467a74545bb1a`
- **Stable raw compressed PYZ member SHA-256**:
  `71cc3e7a22d471f01a5cf6e0da4eb1fab97f05d6893dac7cf4783b64ed79b036`

That last digest is computed from the exact compressed taraz_integration
member bytes at PYZ._start_offset + toc offset/length, **not** from
`marshal.dumps(code)`, which can differ between interpreters. Two fresh
interpreter runs produced the same raw digest. In synthetic metadata-only QA,
the new package suppressed duplicate pending presentation after a persisted
pre-move intent, completed the original rejection without finance posting,
and flagged a tampered reviewed payload even after receipt completion.
However, its packed JS bridge still lacked tarazIntegrationRecover.

## Executed tests

From the isolated Taraz worktree:

```powershell
py -3.12 -B scripts/qa_mtr_taraz_qa_gui_recovery_20261110.py --static-only
py -3.12 -B scripts/qa_mtr_taraz_qa_gui_recovery_20261110.py
py -3.12 -B scripts/qa_mtr_taraz_qa_gui_recovery_20261110.py --post-fix-static-only
py -3.12 -B scripts/qa_mtr_taraz_qa_gui_recovery_20261110.py --post-fix-synthetic
py -3.12 -B -m unittest -q tests.test_mtr_taraz_qa_gui_recovery_20261110
```

The final test run: **13/13 PASS, exit 0**, both new Python files parsed with
AST, and all static/synthetic QA commands finished successfully. **PASS means
the fail-closed blocked case was correctly handled, not a usable native UI.**

## Scope and remaining gate

Worker-10 changed only two new files and this new report:
`scripts/qa_mtr_taraz_qa_gui_recovery_20261110.py`,
`tests/test_mtr_taraz_qa_gui_recovery_20261110.py`, and
`docs/MTR_TARAZ_QA_NATIVE_GUI_RECOVERY_20261110.md`.
No existing source, build, installed EXE or prior QA script was modified.

Even after bridge repair and a new signed QA manifest, a genuine native
WebView2 manual recovery test without a real company book needs a supported,
explicitly nonfinancial QA boot path that never represents synthetic
credentials as authenticated operational users. The production personal-ledger
guard must remain intact. Native authentication, source guard passage, real
invoice posting, backup/rollback and release approval remain **unverified**.
No OS-level packet-capture audit of background system egress was performed.
