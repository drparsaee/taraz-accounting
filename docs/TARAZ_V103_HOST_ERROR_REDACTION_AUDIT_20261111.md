# Taraz v1.0.3: raw host-exception redaction audit (2026-11-11)

**Disposition: security/UX NO_GO for the examined frozen v1.0.3 candidate.**
Seven independent UI pathways reproduced displaying a synthetic exception
message sent by a mock native bridge. A passing reproduction test means the
**leak exists**; it is not a pass of an error-redaction requirement.

## Exact artifact and validation

Candidate inspected, strictly read-only:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\build-eb9d4f2ab076`

| Item | Independent observation |
| --- | --- |
| Compiled `binary/Taraz.exe` | SHA-256 `e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c` |
| EXE's actual `dist/assets/accounting-IoqJ3LzK.js` | 906,944 bytes; SHA-256 `001e9e7e622fee9cc375461b754847a978c0b16563a72a4cd8e5d784ca8512b4` |
| Candidate's `web/dist/assets/accounting-IoqJ3LzK.js` | Exactly identical bytes to the JS extracted directly from the EXE PyInstaller CArchive |
| Source | Relevant ten frozen `source/src` files rehashed equal to concurrently available checkout sources at test time |

Run from `D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

```powershell
node --check tests/taraz_v103_host_error_redaction_audit_20261111.test.cjs
node --test tests/taraz_v103_host_error_redaction_audit_20261111.test.cjs
```

**Final observed run:** node syntax check exit 0; native Edge/Chromium suite
**10 tests / 10 passed / 0 failed**, exit 0, **15.20 s** on final rerun. One test checked the
actual frozen EXE and compiled JS; eight Chromium subtests exercised distinct
UI paths, seven confirming unredacted fake exception messages and one
confirming an already-fixed redacted Madar error. Tests used the **exact frozen
v1.0.3 compiled JavaScript from its Vite output** that had been verified
byte-for-byte against the EXE, and the compiled CSS, in disposable browser
contexts. Test pages originated at an in-memory intercepted
`https://taraz-qa.invalid/accounting.html`; all other requests were blocked.
No real network connection, installed app, user browser profile, local
accounting DB, Madar service, installer or runtime source was changed or run.

## Reproduced user-visible leaks

The synthetic native bridge rejected named methods with
`Error('QA-V103-HOST-SECRET-72973 :: <method>')`. Exact test assertions
confirmed the marker in the *rendered DOM*, after navigation and user action,
and zero calls to the financial `standaloneAccountingCommand` method.

| Severity | Screen / user action | Frozen source catch → rendered sink | Result |
| --- | --- | --- | --- |
| HIGH | Company details, opening **مشخصات شرکت** | `src/personal_parsian_company.jsx:24-26` → `:31` (`.ppc-error`) | **Reproduced** raw `company` exception |
| HIGH | Accounting home, opening dashboard | `src/taraz_home_command.jsx:90-95` → `:152` (`.tdh-warning`) | **Reproduced** raw `history` exception |
| HIGH | Migration archive, opening page | `src/personal_parsian_extended.jsx:46-48` → `:63` (`.ppe-error`) | **Reproduced** raw `extended` exception |
| HIGH | Migration archive, historical invoices/people | `src/personal_parsian_invoices.jsx:38-44` → `:139` (`.ppi-error`) | **Reproduced** raw `history` exception |
| HIGH | Cash/bank historical movements | `src/personal_parsian_bank_movements.jsx:10-12` → `:40` (`.ppbm-notice`) | **Reproduced** raw `history` exception |
| HIGH | Migration archive, click a valid table | `src/parsian_raw_archive_explorer.jsx:38-40` → `:74` (`.pra-error`) | **Reproduced** raw `archiveRows` exception |
| HIGH | Migration CSV, press **انتخاب CSV** | `src/provider_csv_migration.jsx:65-73` → `:170` (`.pcsv-error`) | **Reproduced** raw `csvChoose` exception |
| Checked control | Settings → اتصال به مدار → consent → refresh | `src/taraz_settings.jsx:53-56` → `:98` | **Safe in tested path**; generic visible message, fake secret absent |

Risk classification: these are direct native-bridge rejection strings accepted
by React as the visible error message. The evidence establishes a **UI
redaction failure when a host method throws a sensitive string**. It does not
prove the current real Windows backend actually emits passwords, tokens,
customer information or stack traces. Because native error text is not
contractually constrained at these boundaries, treat it as untrusted and do
not allow arbitrary error text into user-visible UI.

## Additional static candidates, without fabricated runtime reproduction

- `src/provider_csv_migration.jsx:82-84`: `standaloneAccountingCsvPreview`
  rejection flows through `setError(exc?.message)` to `:170`. This second CSV
  method was **not separately browser exercised** in this run; it shares the
  already-reproduced unsafe error state/sink with the chooser.
- `src/parsian_raw_archive_explorer.jsx:18-24`: archive **index** errors also
  enter `setError(err?.message)` but the current `:74` sink is nested inside
  the `selectedYear` conditional. An index failure without a selected year
  may therefore not render the error; no claim of an index-path UI leak.
- `src/accounting_print_designer.jsx:25-32,53-56` → `:147`: preview rendering
  and logo-template validation show `e.message`. Both are **local rendering/
  validation error sources**, not demonstrated direct bridge exceptions.
  The corresponding template validator in `src/accounting_print_template.js`
  mostly throws fixed authored diagnostic strings. No browser proof here that
  a host-secret exception reaches the print error element; classify as
  **possible additional UI-risk requiring source-origin validation**, not an
  eighth proven native-bridge leak.
- `src/accounting_operational_panels.jsx:52-58`: inline form catch renders
  `err?.message`; calls are normally routed through the workspace's `execute`
  handler, which masks unexpected host errors. This is a **static boundary
  concern**, not a reproduced leak from a real native bridge in this audit.
- `src/accounting_management_dashboard.jsx:244-250,303-304` displays error
  text thrown by local `buildManagementAnalytics` over view data. That differs
  from directly displaying a rejected backend promise. **Not reproduced**.
- `src/taraz_integration_panel.jsx:14-16,27-31,41` contains raw message sinks
  but is not imported/rendered by the current standalone accounting entry
  path, so it was **not classified as a reachable compiled-UI leak**.
- `src/personal_parsian_dashboard.jsx` has similar raw-rejection handling,
  but no JSX mount of that module was found in the active workspace. No
  compiled reachability was proven.
- `src/accounting_action_home.jsx:242` stores raw history errors, but its
  active error view `:327-329` renders a fixed authored string. It was **not
  counted** as an exposed backend exception.

## Minimal repair path for v1.0.4 staging

For each of the seven reproduced cases, replace the raw backend error message
in the **visible** state with a fixed Persian message specific to that
operation, e.g. `خواندن مشخصات شرکت از آرشیو انجام نشد؛ وضعیت میزبان و دسترسی را بررسی کنید.`
for company, `خواندن سوابق تاریخی حسابداری انجام نشد؛ وضعیت آرشیو و میزبان را بررسی کنید.`
for history, `خواندن جدول آرشیوی انجام نشد؛ منبع یا مجوز را بررسی کنید.`
for archive rows, and `انتخاب فایل CSV انجام نشد؛ دسترسی به فایل و میزبان را بررسی کنید.`
for CSV. Apply the same masking to `standaloneAccountingCsvPreview`.
Preserve meaningful **authored local validation messages** through an explicit
allowlist or tagged local-error path. Do not infer trust merely from the
presence of an `Error.message` property, error language or substring.

After fixes, invert these seven tests into redaction assertions **against a
new separately built artifact**. The frozen v1.0.3 audit intentionally keeps
the positive leakage assertions as permanent evidence and a regression
reference; rewriting it to assert safety against known-vulnerable compiled
bytes would erase the distinction between the old artifact and a repaired
release. A new v1.0.4 package needs its own source/fingerprint and compiled
GUI acceptance plus existing financial and installer gates.

This worker wrote only this new report and the new audit test. **Production
release approval is not supported by these tests.**
