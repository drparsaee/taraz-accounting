# Taraz v1.0.4 residual exception-to-UI audit | 2026-11-11

**Disposition: NO_GO for the examined v1.0.4 Vite-stage UI under the rule against
showing arbitrary sensitive exception/error text.** This is an **isolated
synthetic browser failure** result, not an observation of an actual password,
token, user data, or native backend error leaking from a real Windows host.

The seven *previously confirmed v1.0.3* backend-exception leaks were separately
verified as fixed: `taraz_v104_host_error_redaction_acceptance_20261111.test.cjs`
reported 10/10 PASS in both `STAGE_UI_ONLY` and the independent full compiled
EXE asset-parity mode. The **three additional residual UI exposures below**
must be kept distinct from those seven fixes and from each other.

## Exact provenance, commands and completed tests

Vite QA root:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-1ff6df468d81`

Patched source-stage:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-959986753b61\source`

| Integrity measure | Observed |
| --- | --- |
| `vite-qa-report.json` status | `STAGE_UI_ONLY`; compiled frontend true, EXE built false |
| Source fingerprint | `6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1` |
| Source inventory | **131/131** staged files independently rehashed, stage report and inventory hashes matched Vite attestation |
| Compiled asset | `dist/assets/accounting-DANnPkpK.js` |
| Compiled JS SHA-256 | `b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453` |
| Browser | Real headless Microsoft Edge, fresh private Playwright context for each case |
| Network | Fake `https://taraz-residual-qa.invalid/accounting.html` fulfilled **entirely in-memory**; all other requests aborted |
| Finance | **0 applied writes** in all cases; one pre-write rejected synthetic financial method *attempt* in the InlineForm test |

Reproduction from `D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

```powershell
node --check tests/taraz_v104_residual_exception_leak_20261111.test.cjs
node --test tests/taraz_v104_residual_exception_leak_20261111.test.cjs
```

**Final observed result:** syntax check exit `0`, Edge tests **7/7 passed**,
zero failures, test runner exit `0`, **13.6754 seconds**. These tests
intentionally assert that unsafe raw-text reflection **exists** in the three
positive leak cases; green tests therefore **do not** indicate a safe release.

The independent original seven-leak acceptance was also rerun against the
newly built v1.0.4 candidate using:

```powershell
Remove-Item Env:\TARAZ_V104_STAGE_DIR -ErrorAction SilentlyContinue
$env:TARAZ_V104_BUILD_DIR = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-6d851f756264'
node --test tests/taraz_v104_host_error_redaction_acceptance_20261111.test.cjs
```

That EXE-asset-verification run was **10/10 passed, exit 0, 10.1500 sec**,
with `VERIFIED_MODE=EXE_COMPILED_UI` and JS SHA-256 `b72441a9...4f453`.
This establishes only EXE embedded-JS/PE/PYZ provenance and **Edge simulated
UI paths**. It was not a real installed native WebView2 financial acceptance.

## Residual outcomes with source lines and selectors

| Case | Classification | Evidence / source and visible selector |
| --- | --- | --- |
| **InlineForm native command failure** | **Masked, no host text exposure reproduced** | Real user form path `src/accounting_operational_panels.jsx:52-58` for bank statement registration in cash tab. Synthetic `standaloneAccountingCommand` threw fake secret **before any write**, one API attempt, zero writes. Workspace `execute` catches at `src/standalone_accounting_workspace.jsx:1178-1201`, emits generic error through workspace `.sac-alert.error` at `:1642-1644`; no injected secret anywhere in body; no InlineForm `.sac-alert.error` generated. |
| **InlineForm bad amount** | **Trusted local authored validation (safe tested path)** | Invalid amount `abc` threw `src/accounting_operational_panels.jsx:29` parser's authored numeric validation, caught by `InlineForm:55`, rendered in form `.sac-alert.error`, zero host command attempts/writes. |
| **Management dashboard view error** | **CONFIRMED host-controlled field-name reflection into user-visible error** | Synthetic `standaloneAccountingRead` returned a **structurally accepted but deliberately malformed** `view.invoices` object with a property name `QA-V104-RESIDUAL-LOCAL-58317` and issued invoice `total=-1`. `src/accounting_management_analytics.js:89-95` constructs `Error('مبلغ نامعتبر در فاکتور '+id)`, catches and returns `error.message` at `:258-260`. `src/accounting_management_dashboard.jsx:244-250,303-304` renders it verbatim in `.mdash-error[role="alert"]` after opening `details.sac-vtr-management-details` → `گزارش‌های تحلیلی و یادآورهای مدیریتی`. Fake secret **appeared in DOM**. No native rejected promise, no write. |
| **Print preview rendering failure** | **CONFIRMED arbitrary local exception text reflected; native-host pathway NOT proven** | In a private browser only, `HTMLCanvasElement.prototype.getContext('2d')` was instrumented to throw `Error('QA-V104-RESIDUAL-LOCAL-58317::CANVAS_RENDER_FAILURE')` on a large preview canvas. The actual Vite component caught it in `src/accounting_print_designer.jsx:25-32`, displayed it verbatim at `:147` in `.sac-print-designer .sac-print-error` after opening tab `invoiceDesign`. Zero finance commands. This proves a **local rendering exception-to-UI sink**, not a backend token leak. |
| **Bank CSV file read exception** | **CONFIRMED arbitrary local browser-file exception text reflected; native-host pathway NOT proven** | `File.prototype.text` was instrumented in the private Edge context to reject with `Error('QA-V104-RESIDUAL-LOCAL-58317::FILE_READ_FAILURE')`; a synthetic CSV was attached to `input[type="file"][aria-label="فایل CSV بانک"]`. The real Vite handler at `src/accounting_operational_panels.jsx:605-615` displayed the raw error at `:618` in the matching bank CSV section's `.sac-alert.error`. Zero finance commands. This is a **browser-local file read error**, not the Taraz native accounting API. |
| **Purchase discount allocation preview** | **Trusted local authored validation (safe tested path)** | Built synthetic discounted issued bill, navigated `items`, selected exact allocation in `LiveInventory`, entered invalid discount `abc`; the preflight at `src/accounting_operational_panels.jsx:208-297` returned an authored validation error in `[aria-label="تخصیص دقیق تخفیف خرید"] [role="alert"]` through `:490`. No arbitrary host error and zero financial method calls. This **does not demonstrate** a native backend rejection through `:297`. |

The **dashboard finding** demonstrates that an untrusted input *inside an
accepted host projection* can end up in a rendered error. It does **not**
establish that the real backend generates such malformed IDs or that a native
Promise rejection is displayed. The two local exception findings prove raw
reflection when the local environment raises an arbitrary message; their
severity depends on whether that local error could realistically include
private paths or tokens. For release gating, classify both as actionable
**error-redaction robustness issues**, not proven live credential disclosure.

## Minimal targeted remediation and RC2 inverse gates

1. **Analytics:** at `src/accounting_management_dashboard.jsx:250` and/or
   `:303-304`, do not display arbitrary `analytics.error` or caught
   `err.message` originating from host-controlled invoice and cheque IDs.
   Use a stable Persian error such as
   `محاسبه شاخص‌های مدیریتی ناموفق بود؛ داده دفتر و بازه زمانی را بررسی کنید.`
   Where operator validation details are needed, explicitly map *trusted,
   fixed* error codes/messages, never arbitrary concatenated record IDs.
2. **Print:** at `src/accounting_print_designer.jsx:32`, mask unexpected
   canvas/rendering exceptions with a generic preview error. Keep only
   explicit, source-owned `validatePrintTemplate` diagnostics, if needed,
   via a strict allowlist or tagged error; never trust arbitrary `e.message`.
3. **CSV:** at `src/accounting_operational_panels.jsx:615`, distinguish a
   failing browser `file.text()` read (generic operator message) from trusted
   authored CSV parser validation, without returning generic native/browser
   Error.message verbatim. Safeguard any parser details containing raw fields.

**RC2 required inverse tests on its own compiled Vite asset and new source
attestation:** reuse exactly the three private browser reproductions here,
but invert their assertions: (a) poisoned host invoice key **absent** from all
visible page text while a meaningful analytics error is visible, (b) forced
canvas error secret **absent** while generic preview error visible, (c)
forced `File.text()` secret **absent** while a generic CSV read error visible.
Additionally retain two safe controls: InlineForm native pre-write rejection
remains masked, and valid local numerical/purchase validation stays useful.
These independent **inverted assertions are implemented in the same new
residual QA test file** behind explicit, fail-closed RC2 environment settings.
The original Vite artifact remains the immutable *positive exposure* baseline
when the RC2 variable is absent. RC2 mode strictly requires a **different**
`vite-qa-*` directory and source/JS SHA-256 values different from baseline;
it independently checks its report, complete 131-file staged source inventory,
source fingerprint, compiled HTML, JS, and CSS. It can be executed after a
separately attested RC2 Vite build exists:

```powershell
$env:TARAZ_V104_RESIDUAL_RC2_STAGE_DIR = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-<actual-rc2-id>'
$env:TARAZ_V104_RESIDUAL_RC2_SOURCE_SHA256 = '<verified-64-character-new-source-hash>'
$env:TARAZ_V104_RESIDUAL_RC2_JS_SHA256 = '<verified-64-character-new-js-hash>'
node --test tests/taraz_v104_residual_exception_leak_20261111.test.cjs
```

The paths/hashes in angle brackets are **placeholders**, not a claim of a
future corrected build. A deliberate test giving the old
`vite-qa-1ff6df468d81` directory as RC2 was executed and **failed closed,
exit 1**, with the explicit assertion
`original vulnerable Vite artifact cannot impersonate repaired RC2`.

### Actual first RC2 stage dynamic test (not approved)

Worker29 subsequently produced a separately attested source stage
`source-stage-146b4c62e3f8` and Vite frontend `vite-qa-899a40d30820`. The
RC2 report is specifically `rc2-vite-qa-report.json`, **not** the prior
`vite-qa-report.json`. The test's RC2 mode explicitly recognizes this
separate report name, schema and status
`V104_RC2_STAGE_UI_ONLY_EDGE_QA_PENDING`. It rehashed all 131 source
files and the Vite CSS/HTML/JS assets. Pin evidence:

- RC2 source fingerprint:
  `aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8`
- RC2 JavaScript SHA-256:
  `39295ea85bf2d6ee9fd94fce862c2bc505d4ac6ce01153fbc7ef9d8eea0b5b79`

Executed exactly:

```powershell
$env:TARAZ_V104_RESIDUAL_RC2_STAGE_DIR = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-899a40d30820'
$env:TARAZ_V104_RESIDUAL_RC2_SOURCE_SHA256 = 'aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8'
$env:TARAZ_V104_RESIDUAL_RC2_JS_SHA256 = '39295ea85bf2d6ee9fd94fce862c2bc505d4ac6ce01153fbc7ef9d8eea0b5b79'
node --test tests/taraz_v104_residual_exception_leak_20261111.test.cjs
```

**Observed: FAIL, exit 1.** Five of the six Edge subcases passed, one
failed, which also failed the parent; Node reported `tests 7, pass 5,
fail 2`, duration **7.0771 sec**. The print preview Canvas exception and
browser CSV `File.text()` exception were **masked** with useful operator
messages; the InlineForm synthetic host-command failure remained masked;
trusted local numeric/purchase validation remained visible.

**Confirmed remaining first RC2 leak:** with the malformed synthetic native
projection `view.invoices["QA-V104-RESIDUAL-LOCAL-58317"]` and invalid `total=-1`,
management dashboard `.mdash-error[role="alert"]` **still displayed**:

```text
مبلغ نامعتبر در فاکتور QA-V104-RESIDUAL-LOCAL-58317
```

The RC2 fix masked the component's `catch(err)` branch, but the lower-level
`buildManagementAnalytics` at `src/accounting_management_analytics.js:258-260`
**returns** `{error: error.message}`. The component directly renders
`analytics.error` at `src/accounting_management_dashboard.jsx:303-304`, so it
escapes the newly masked `catch`. A later RC3 must mask the
**`analytics.error` rendering path**, and be rebuilt into a separately attested
Vite asset for the same inverted Edge test. First RC2 is **not approved**;
no updated native EXE, production installation, or finance interaction was
performed by this worker.

### Expanded RC2 historical regression replay

The same task-owned test was extended to replay **all seven** old v1.0.3
backend exception redaction paths against RC2's own compiled Vite JavaScript.
Each synthetic rejected bridge method was invoked; its secret text remained
absent in the entire rendered body, and there were zero finance commands in
these seven additional tests.

**Latest RC2 Edge rerun:** Node reported `tests 14, pass 12, fail 2`, exit
**1**, duration **12.9733 seconds**. The **13 leaf scenarios** included 12
PASS and **one FAIL** (malformed host invoice key inside management error);
the second failed test reported by Node is their parent. Thus the seven old
backend leaks remain fixed, both local print/CSV error reflections are fixed,
and the **one analytics host-data error echo** still prevents RC2 signoff.

## RC3 independent compiled Vite Edge acceptance: PASS (STAGE_UI_ONLY)

The subsequent **detached RC3 source and Vite output** were produced by the
separate release-stage worker and examined **read-only** by this QA worker.
The residual QA test has a distinct `RC3` branch (not a source-only test),
which requires explicit RC3 directory and two SHA-256 pins, reads the
`rc3-vite-qa-report.json` schema, and refuses the original Vite or failed
RC2 output as an RC3 substitute.

| Independent evidence | Confirmed value |
| --- | --- |
| RC3 source stage | `source-stage-ca9761aa43d8` |
| RC3 source stage report | `V104_RC3_SOURCE_ONLY_EDGE_QA_PENDING` |
| RC3 source SHA-256 | `e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de` |
| RC3 Vite stage | `vite-qa-72ee216638e4` |
| RC3 Vite report | `rc3-vite-qa-report.json`: `V104_RC3_STAGE_UI_ONLY_EDGE_QA_PENDING` |
| Compiled JavaScript | `dist/assets/accounting-5ZRme707.js` |
| RC3 JS SHA-256 | `3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9` |
| Source inventory | All **131** files individually rehashed, canonical inventory fingerprint matched |
| Source difference from RC2 | Independently compared both inventories: **only** `src/accounting_management_dashboard.jsx` differs |
| Compiled HTML and CSS | Rehashed and matched explicit Vite RC3 attestation |

**Exact executed command** from the Taraz isolated checkout:

```powershell
Remove-Item Env:\TARAZ_V104_RESIDUAL_RC2_STAGE_DIR -ErrorAction SilentlyContinue
Remove-Item Env:\TARAZ_V104_RESIDUAL_RC2_SOURCE_SHA256 -ErrorAction SilentlyContinue
Remove-Item Env:\TARAZ_V104_RESIDUAL_RC2_JS_SHA256 -ErrorAction SilentlyContinue
$env:TARAZ_V104_RESIDUAL_RC3_STAGE_DIR = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-72ee216638e4'
$env:TARAZ_V104_RESIDUAL_RC3_SOURCE_SHA256 = 'e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de'
$env:TARAZ_V104_RESIDUAL_RC3_JS_SHA256 = '3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9'
node --test tests/taraz_v104_residual_exception_leak_20261111.test.cjs
```

**Observed Node output (before wording-only test-label cleanup):**

```text
✔ InlineForm authored validation is visible without a finance command
✔ InlineForm intercepted host write failure stays masked by workspace execute
✔ print preview LOCAL canvas exception is directly visible in compiled UI
✔ bank CSV browser File.text LOCAL exception is directly visible
✔ management dashboard with malformed host invoice ID: classify reachability
✔ discount allocation :297 exposes locally authored validation, not native error
✔ historical v103 leak regression: company archive backend rejection stays masked
✔ historical v103 leak regression: overview history backend rejection stays masked
✔ historical v103 leak regression: migration extended backend rejection stays masked
✔ historical v103 leak regression: migration invoices backend rejection stays masked
✔ historical v103 leak regression: cash bank history backend rejection stays masked
✔ historical v103 leak regression: archive table rows backend rejection stays masked
✔ historical v103 leak regression: CSV choose backend rejection stays masked
✔ v104 exact detached Vite stage residual local/native error channels
ℹ RC3_INVERTED_STAGE_UI_ONLY: source=e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de JS=3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9
ℹ tests 14
ℹ pass 14
ℹ fail 0
ℹ duration_ms 12914.8127
--- exit code 0 ---
```

The three passing assertions **do not** reproduce the baseline leaks in RC3:
for the canvas and CSV cases the source-injected fake exception was absent
from **all rendered page body text** and an operator error remained visible;
for the management case the malformed host invoice ID was likewise absent
from the entire body while a generic analytics error remained visible.
The earlier test labels were shared with the positive exposure baseline and
have since been clarified to explicitly say **masked** in repaired modes.
The underlying assertions, not the labels, determine the pass/fail verdict.

**Final rerun after label clarification:** `node --check` exit **0**,
the exact RC3 command above exit **0**, `tests 14`, **`pass 14`**, **`fail 0`**, 
**`duration_ms 12792.3261`**. The console explicitly showed
`print preview LOCAL canvas exception is masked in compiled UI`,
`bank CSV browser File.text LOCAL exception is masked`, and
`management dashboard masks malformed host invoice ID`, each with a checkmark.
The source and compiled JS SHA-256 diagnostic was unchanged. Thus the completed
review does **not** depend on the previous ambiguous test-case label text.

The other **ten** leaf checks include all seven historical rejected-native
read regressions (real host API simulation), one native command rejected
**before any write**, and two trusted local validation cases. All passed.
There were **zero applied financial writes** and no external network;
Playwright served the synthetic page entirely in-memory and blocked all
other requests. No installed application was launched or modified.

**Scope boundary:** RC3 is accepted as **`STAGE_UI_ONLY`**, not a compiled
native Windows EXE, installer, rollback, financial-state, or production
release approval. This result does not retroactively approve the earlier
failed RC2/Vite or original v1.0.4 EXE. RC3 was reported to prime immediately.

After adding the RC2-only checks, the original stage exposure suite was rerun:
**7/7 PASS, 0 failed, exit 0, 13.5107 seconds**. The earlier 13.6754-second
run and this rerun agree on the observed exposures.

**No broader release approval** is claimed. This worker modified only the
two task-owned new test/report files. No frozen source, native binary, real
installed application/profile/data, or external network was touched.
