# Sileo + Context Help (Taraz) / 2026-11-10

**QA-only, not a release or installed-app acceptance.** This task owns only a
new browser-test file and this new report. Shared, dirty existing Taraz source
belongs to worker17/prime and was inspected, not changed by this worker.

## In-memory Chromium test

Source: `tests/taraz_sileo_help_integration_browser_20261110.test.cjs`

Command: `node --test tests/taraz_sileo_help_integration_browser_20261110.test.cjs`

**Observed final validation:** 8 tests / 8 passed / 0 failed; exit 0. One
headless Microsoft Edge/Chromium browser was reused across disposable browser
contexts. Test markup, bundled real-current JSX and CSS remained in memory;
all HTTP(S)/file requests were blocked. No Windows Taraz installed binary,
finance profile, account database, company identity, LAN or real user data was
loaded. `crypto.randomUUID` was provided inside the insecure `about:blank`
test page using `crypto.getRandomValues`, without changing production source.

The browser uses the actual current
`StandaloneAccountingWorkspace`, `AccountingNavigationShell`,
`TarazContextHelp`, `TarazSileoToaster`,
`tarazIntegrationFeedbackApi` and live React handlers against a synthetic
in-memory accounting API. The test reads the current `SECTIONS` source
declaration and requires guide labels to match the current navigation.
Real clicks verified:

1. Dashboard, invoice and reports: actual tab switching, section-specific
   1–3-step RTL help, Escape close and focus return; no finance command or
   unsolicited toast on navigation.
2. Manual, synthetic `party.register`: only one host call after submit;
   a validated synthetic host response with increasing revision yields one
   Sileo success text. Test neither persists a party nor simulates a real
   authenticated host.
3. Ambiguous same-revision response and synthetic host exception: each
   produces a warning/uncertain toast, preserves manual same-event recovery,
   and never automatically sends another command or emits a success toast.
4. Manual Madar nonfinancial review: success only after manual opt-in,
   refresh, second confirmation and a source-compatible mock ACK. Error and
   wrong-request-ID responses do not create success toasts. No financial
   invoice, peer receipt or accounting command results from these actions.
5. The **toast** text never displays seeded synthetic private invoice title,
   customer name or backend token, and never claims a verified official
   receipt. This does not imply the entire application redacts host errors.

## One source-frozen, isolated QA EXE build

Worker17 completed its shared-source changes and prime confirmed source freeze
before this worker invoked the latest builder **once**:

```powershell
py -3.12 -B scripts/qa_mtr_taraz_build_20261110.py
```

The builder copied an immutable source fingerprint and offline dependencies
into an isolated, create-only external QA directory, built HTML/Vite and
PyInstaller without starting the EXE, rechecked source fingerprints, and
statically inspected the packaged UI and Python archive.

- Report: `D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110\qa-dfb8dad7602c\qa-build-report.json`
- Status: `QA_BUNDLE_VERIFIED`
- QA-only EXE: `D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110\qa-dfb8dad7602c\pyinstaller\dist\Taraz-MTR-QA-dfb8dad7602c.exe`
- EXE SHA-256: `02b961605232c5eefc49111495505a904a246426013b9a1d7d9de454ffb4e4e9`
- EXE size: `17,033,215` bytes.
- Source snapshot SHA-256: `ddb06b10b8cbeacfdad6f16b67d15965fd0f31ff3d75c9892df65cd5db85726b`, 128 source inputs.
- Dependencies copied from **current isolated Taraz local node_modules**, not an older sibling tree.
- Static compiled indicators `sileoToastReactHost=true`,
  `perSectionContextHelpTrigger=true`; packed HTML-to-native forwarding
  for list/review/recover = true; packed source-bound durable-review gate = true.
- Report flags `installed=false`, `realLedgerAccessed=false`,
  `releaseReady=false`.

**Independent check:** `Get-FileHash -Algorithm SHA256` against the created
EXE returned the SHA-256 above, equal to the builder report. This confirms
file bytes/hash only; it is not a GUI launch or issuer certificate validation.

## Unresolved real UI observations (not concealed by passing tests)

1. **Help close button pointer failure in invoice mode.** In a separate
   real React/Chromium run, the visible `بستن راهنما` button in the invoice
   help panel could not be clicked normally. Playwright repeatedly reported
   `.sac-root.taraz-vt-app.sac-invoice-work-mode` intercepting the pointer.
   The same help panel opened correctly and could close through Escape.
   This suggests a stacking/hit-testing bug. **The owner must fix actual
   pointer behavior** and repeat the close-button test; tests here use
   Escape as a navigation workaround, not as proof pointer close works.
2. **Host exception text in page alert.** A synthetic backend exception
   containing `QA-SECRET-TOKEN-7001` was redacted from the Sileo toast, but
   `StandaloneAccountingWorkspace.send` currently displays the thrown
   `err.message` verbatim in the separate in-page `.sac-alert`. Depending
   on actual backend exception content, this can expose details. Whether all
   host messages are safe is **not verified**. Worker17/prime own any
   masking change; this test cannot patch their paths.

Neither outstanding issue justifies an installed production or financial
receipt-success claim. The observed build proves bounded source/compiled
artifact presence, not installed-user operation, end-to-end identity, live
company access or official finance receipts.
