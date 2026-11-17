# Taraz P1 UX, notifications, RTL and Madar acceptance, 2026-11-11

## Evidence and scope

New independent test: `tests/taraz_p1_ux_notifications_browser_20261111.test.cjs`.

```powershell
node --test tests/taraz_p1_ux_notifications_browser_20261111.test.cjs
```

**Observed final run:** 7 tests passed, 0 failed, exit code 0, 16.56 s. The test
read the installed PyInstaller archive without launching the application. It
also compiled the **current detached worktree's genuine React JSX/CSS** in
memory with esbuild and exercised actual interactions in disposable headless
Microsoft Edge/Chromium pages. API return values and exceptional failures were
synthetic and held in page memory. HTTP(S)/file fetches were blocked; the tests
did not open installed Taraz, access user finance records, connect to Madar LAN,
save templates to a real host, modify installer files or switch versions.

Additional existing regression rerun after the shared-source error-masking
edits: `node --test tests/taraz_sileo_help_integration_browser_20261110.test.cjs`
returned **8 tests passed, 0 failed, exit code 0**, 11.95 s. That existing test
covers uncertain/error command outcomes and Madar manual review scenarios.

## Already-installed compiled feature evidence

Read-only inspection of `%LOCALAPPDATA%\Programs\Taraz` yielded:

| Observation | Result |
| --- | --- |
| `current-version.txt` | `1.0.2` |
| Active executable | `versions\1.0.2\Taraz.exe` |
| Executable bytes | 17,056,486 |
| SHA-256 | `095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52` |
| PyInstaller embedded JS | `dist\assets\accounting-ugnxBTYM.js`, 904,668 bytes |
| Static compiled markers | Sileo feedback host; context help trigger; RTL accounting root; responsive navigation; visible Madar dashboard and quick nav; invoice print designer; `invoiceDesign` tab |

For reference, installed `1.0.1` executable SHA-256 was
`5b5a550f3b95cda8352f757cd9e61d44a62531e0e4dfe0fc6d586a0d6a452d4b`;
its packed UI had the Sileo/help/print markers but not the later visible Madar
dashboard markers. Presence in a compiled asset **does not verify that a
feature operates inside the installed Windows WebView2 application**.

## Current-source browser acceptance

| User behavior exercised | Actual assertions | Result |
| --- | --- | --- |
| Desktop RTL contextual guide | Root `dir=rtl`; dashboard and invoice help; actual pointer click on **بستن راهنما**, portal outside app stacking context, focus restored | PASS |
| Invoice print studio | Navigate through real drawer, edit template/company labels, actual canvas renders over 500 px per side, no financial API command | PASS |
| Narrow viewport (390 × 844) | Direct Madar nav, active section, RTL, help pointer-close in invoice, no root/document horizontal overflow | PASS |
| Madar read consent | No data request before consent plus explicit click; exactly one requested, read-only synthetic project page after click; no finance command | PASS |
| Madar data read error | Throw `QA-MADAR-SECRET-470129` from mock bridge and assert the visible error alert does not disclose it | PASS |
| Settings integration error | Throw the same fake secret on manual integration list request; assert error message is generic, no finance command | PASS |
| Sileo post-action notice | No toast on navigation; one manual synthetic `party.register` with progressing revision produces a visible Sileo confirmation; customer name is not repeated in toast | PASS |
| Standalone entry-point error alerts | Bundle actual `src/standalone_main.jsx`; mock user management/company switch failures carrying `QA-STANDALONE-HOST-SECRET-2001`; visible alerts suppress the raw token, no finance command | PASS |

There are seven top-level tests; some group several related behavioral
assertions. In particular, the pointer test used Playwright's ordinary click,
without `force`, programmatic DOM `.click()` or Escape fallback. This checks
the previously reported invoice-help interception regression in the **current
source**.

## Remaining boundaries for P1

- The context-help map `src/taraz_context_help_data.js` contains general
  section guides, but has **no direct `madar` or `invoiceDesign` guide**. A
  separate Madar help trigger and field-level help for every form were not
  verified. If P1 requires contextual help throughout all sections, this is
  still an implementation gap, not a passed acceptance condition.
- Responsiveness was actually measured at 390 px width and at a 1440 px
  desktop viewport. Other breakpoints, browser zoom, touch hardware, native
  Windows window minimum size and keyboard/screen-reader coverage remain
  untested here.
- Financial command correctness, PDF byte output, actual template persistence,
  live Madar authentication/permissions, installed WebView2 GUI behavior,
  runtime parity between the current dirty source and installed `1.0.2`, and
  production release readiness were outside this test. Other dedicated tests
  may cover some of these separately.
- This worker changed only the two new files listed above. Shared React
  sources were read while the prime agent owned and patched them. The source
  error masking tested here reflects the **current source at test time**;
  after any further shared-source changes the browser test must be rerun.

**Result classification:** static presence in installed 1.0.2 = confirmed;
current-source synthetic-browser interactions = confirmed within the scope
above; live installed P1 operation and release approval = unverified.
