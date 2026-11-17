# Taraz installed GUI vs disposable Inbox QA: bounded result (2026-11-10)

## Outcome

**Installed Taraz.exe v1.0.0: NOT LAUNCHED, NOT VERIFIED.** The installed
binary's SHA-256 or installed version were **not independently checked** in
this QA; neither the actual installed WebView2 window nor an actual user
profile was opened. The executable's guard cannot be safely satisfied from
an empty synthetic ledger through the existing official public bootstrap API.
Forcing it by fabricating personal financial provenance would defeat the
purpose of the guard. Therefore the installed-GUI lane is deliberately
**BLOCKED**, not passed.

**Alternative completed:** new standalone reproducible QA script
`scripts/qa_mtr_taraz_installed_gui_20261110.py` and isolated tests
`tests/test_mtr_taraz_installed_gui_20261110.py` exercise actual unmodified
Taraz Python Inbox API methods on a completely disposable accounting store
and synthetic metadata proposal. With an explicitly supplied existing,
read-only Node toolchain, the script also **compiles actual JSX** using
esbuild and **server-renders the components** using React/ReactDOM; it does
not claim a browser screenshot or genuine installed window.

## Exact startup blocker from inspected source

`taraz_desktop.run()` requires `%APPDATA%/Taraz/standalone-accounting.sqlite3`
to pre-exist, then calls `TarazAPI.standaloneAccountingRead()` and
`TarazAPI.standaloneAccountingParsianHistory()` before it creates the
WebView2 window. `TarazAPI._source_guard()` requires an authenticated,
non-symlink SQLite book whose `standalone_accounting` head has revision
**at least 608**, checksum-matching JSON, and **both** exact legacy
`eventId` markers
`ps.parsian.journal.1405.14050201.1` and
`ps.parsian.reconcile.1404.pnl-close.20261107`.
`personal_parsian_bridge.read_verified_history()` then expects verified
personal Parsian history: private archive manifests/data or a validated
embedded source, including historical invoice/line counts. This is not a
general-purpose first-run onboarding path. The public
`StandaloneAccountingStore` creates a valid fresh **revision-0** book,
not a migrated personal one. The test confirmed that this valid fresh book
is **denied by the unmodified source guard**, without modifying AUTH.

The source also has a `TARAZ_QA_DATA_DIR` override gated by
`TARAZ_QA_MODE=1` and an absolute QA-only directory. This path override
does not supply the missing personal ledger/history and is not used to
bypass the guard. No real ledger or archive was read/copied. No production
AUTH branch, installer, service, network endpoint, release or user session
was changed.

## Synthetic executable proof, not installed-GUI proof

The QA script creates its own temporary directory **under `D:\CoS-Test`**,
sets disposable `APPDATA`, `LOCALAPPDATA`, `TARAZ_DATA_DIR` and QA paths
for the test process, and removes the fixture on exit. It invokes the
real **`StandaloneAccountingStore`** public constructor/read, followed by
**`TarazAPI`** public methods:

1. Confirm fresh book revision **0**, healthy `standaloneAccountingRead`,
   and `standaloneAccountingParsianHistory` refusal for absent provenance.
2. Create one **synthetic** Madar metadata request under the disposable
   `Madar-Taraz-Bridge/pending` directory plus one malformed request.
3. Check `tarazIntegrationList` returns exactly one visible proposal and
   quarantines the malformed one. Call `tarazIntegrationReview` with
   `reviewed`, check durable metadata-only decision and a now-empty inbox.
4. Confirm `financialEventCreated=false`, accounting revision **still 0**
   and an **identical SHA-256** for the temporary accounting SQLite file
   before/after metadata review. No invoice, posting or payment was created.
5. Compile unmodified `src/taraz_settings.jsx` and
   `src/taraz_integration_panel.jsx` into temporary CommonJS bundles via
   existing esbuild (no package download). Test-only compiler instrumentation
   exports the already-defined, otherwise private `IntegrationSettings`
   component solely to server-render it. Actual React rendering asserts
   the checkbox/manual opt-in exists, refresh starts disabled, collapsed
   panel does not expose its list, and **zero automatic Inbox and ledger
   method calls** occur before a user gesture. This proves compileability
   and initial render only, **not click behavior in a browser**.

The original UI settings path is actually mounted by
`src/standalone_accounting_workspace.jsx` via `TarazSettings`. The
similarly named `TarazIntegrationPanel` is compiled/rendered as a
standalone component for evidence, not claimed to be a mounted installed
route. The existing `tests/taraz_settings.test.cjs` separately checks
the JavaScript metadata helper's manual invocation and safe review response.

## Reproduction

```powershell
# Run from the isolated Taraz source worktree. No network and no install.
$env:MTR_TARAZ_UI_NODE_MODULES='D:\CoS-Test\000- Madar\madar-p2-gantt-notifications-20261107\node_modules'
py -3.12 -B scripts/qa_mtr_taraz_installed_gui_20261110.py --node-modules $env:MTR_TARAZ_UI_NODE_MODULES
py -3.12 -B -m unittest -v tests.test_mtr_taraz_installed_gui_20261110
node --test tests/taraz_settings.test.cjs
Remove-Item Env:MTR_TARAZ_UI_NODE_MODULES
```

`--mode installed` is an explicit refusal with exit **2**. Without the
`--node-modules` option, the host sandbox still runs, but compiled UI
evidence is honestly labelled `NOT_RUN_NO_TOOLCHAIN`. The other mode
does not probe or launch an EXE, install packages, open network sockets,
or access any current Windows profile.

### Results actually observed in the isolated worktree, 2026-11-10

| Execution | Observed result |
|---|---|
| Script with explicit read-only sibling `node_modules` | **exit 0**, `INSTALLED_GUI_BLOCKED_UNPACKED_QA_ONLY`; synthetic Inbox 1 valid + 1 malformed hidden; metadata decision recorded; accounting revision 0 and unchanged temporary SQLite SHA-256 |
| Synthetic compiled JSX/React SSR in the same script | **PASS**; settings and Inbox components compiled; initial consent disabled/manual; zero Inbox/finance API calls; `browserGuiOpened=false` |
| `py -3.12 -B -m unittest -v tests.test_mtr_taraz_installed_gui_20261110` | **6 tests OK, exit 0**, including explicit installed refusal, ambient-profile sentinel, no compiler fail-closed and compiled React SSR |
| `node --test tests/taraz_settings.test.cjs` | **5/5 passed, exit 0**; Node printed a package module-type warning, not a test failure |
| Script `--mode installed` | **BLOCKED, exit 2 as designed**, no executable started |
| `git diff --check` | **exit 0**, with three new files untracked; separate line-end whitespace scan found **0 issues** |

These are new test runs and compiled-source checks, not a screenshot,
WebView2 integration result or an installed Taraz.exe smoke test.

**Next release gate:** provide an independently approved generic Taraz
first-run synthetic-account bootstrap or signed test-fixture migration
contract that does **not** forge personal provenance, then separately test
the exact SHA-pinned installed EXE in an isolated Windows user/VM with
disposable test data and a controlled real GUI. Until then,
**INSTALLED GUI / real Taraz Inbox acceptance: OPEN**.
