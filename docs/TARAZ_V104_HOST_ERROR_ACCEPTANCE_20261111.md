# Taraz v1.0.4: host exception redaction acceptance (2026-11-11)

**Current gate: STAGE_UI_ONLY ACCEPTED (Edge browser), compiled EXE gate still BLOCKED.**

The patched v1.0.4 **Vite-produced frontend** was independently exercised in
headless Microsoft Edge on 2026-11-11: **10 tests passed, zero failed**, exit
`0`, total 15.9945 seconds. All seven previously reproduced native-bridge
message leaks were absent. Two distinct trusted, locally authored error
messages remained visible. This does **not** approve an EXE, installer or
production release.

The frozen v1.0.3 candidate was previously shown to display arbitrary native
bridge `Error.message` strings in **seven** accounting screens. This new,
independent, QA-only test turns those seven reproductions into strict
**redaction acceptance criteria**. It has a separate, non-optional artifact
gate so a successful browser result cannot be attributed to an old v1.0.3
binary or to unbuilt v1.0.4 source proposals.

## Owner-controlled files

- New test: `tests/taraz_v104_host_error_redaction_acceptance_20261111.test.cjs`
- This new report: `docs/TARAZ_V104_HOST_ERROR_ACCEPTANCE_20261111.md`

No runtime/source/installer/profile changes were made by this worker.

## Execution

PowerShell, from `D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

For the **actually completed stage-only test**, run:

```powershell
node --check tests/taraz_v104_host_error_redaction_acceptance_20261111.test.cjs
Remove-Item Env:\TARAZ_V104_BUILD_DIR -ErrorAction SilentlyContinue
$env:TARAZ_V104_STAGE_DIR = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-1ff6df468d81'
node --test tests/taraz_v104_host_error_redaction_acceptance_20261111.test.cjs
```

For a **separately built, future native EXE candidate**, use the independent
full artifact mode:

```powershell
Remove-Item Env:\TARAZ_V104_STAGE_DIR -ErrorAction SilentlyContinue
$env:TARAZ_V104_BUILD_DIR = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-<actual-id>'
node --test tests/taraz_v104_host_error_redaction_acceptance_20261111.test.cjs
```

Replace `build-<actual-id>` with an **observed** completed v1.0.4 build
directory provided by the owner of the build. This is an illustrative shell
command, not an assertion that the path exists. The two environment variables
are **mutually exclusive**. An applied source stage, an unbuilt patch proposal,
the old v1.0.3 build, or a missing environment value is deliberately rejected.
No automatic latest-directory discovery is used.

The **EXE gate** requires: a direct `build-*` child of the fixed v1.0.4 QA root;
completed non-installed v1.0.4 build-report and source package version;
non-QA `1.0.4.0` PE and `1.0.4` PYZ release module; actual compiled JS hash
and length identical to the bytes extracted from the selected EXE's
PyInstaller CArchive; and both EXE and JS hashes different from pinned
v1.0.3. The evidence is obtained by read-only inspection. The EXE is **never
launched** by this test. No EXE was present in this completed Vite-stage run.

The **Vite-stage gate** accepts only an explicitly named `vite-qa-*` child of
the fixed v1.0.4 QA root, with `vite-qa-report.json` status `STAGE_UI_ONLY`.
It validates the attested source-stage report hash, patched source inventory
hash, hashes of each of the 131 actual staged source files, canonical source
fingerprint, and compiled HTML/JS/CSS hashes. The following values were
**independently observed and checked**:

| Evidence | Actual value |
| --- | --- |
| Source stage | `source-stage-959986753b61` |
| Source fingerprint | `6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1` |
| Vite QA directory | `vite-qa-1ff6df468d81` |
| Compiled asset | `dist/assets/accounting-DANnPkpK.js` |
| Compiled JS SHA-256 | `b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453` |
| Source input files rehashed | 131 / 131 |
| Native executable | **Not built or tested here** |

After that gate, the test opens the real compiled v1.0.4 accounting JavaScript
and CSS in a disposable **headless Microsoft Edge** context. A fake URL
`https://taraz-qa.invalid/accounting.html` is served inside a Playwright
interception. Every other request is aborted before reaching the network.
The `window.madar` API is a synthetic in-memory bridge returning deliberate
failures such as `QA-V104-HOST-SECRET-91317 :: company ; AUTH=confidential-host-value`.
Test assertions require zero attempted financial command calls, absence of
that secret in visible page text, a stable and meaningful Persian error
message, correct user action, and no uncaught page error.

## Seven inverted UI cases

| User action | Must reject leaked host text; must show useful operator error |
| --- | --- |
| Company tab and company archive details | Company metadata load failure |
| Overview dashboard | Historical accounting source failure |
| Migration tab, extended history | Extended Parsian data load failure |
| Migration tab, historical invoices | Parsian historic invoice load failure |
| Cash/bank tab | Historical bank and cash movements load failure |
| Migration tab, select the synthetic archive table | Archive table rows load failure |
| Migration tab, click **انتخاب CSV** | CSV file picker failure |

Each scenario asserts that the named fake-host method was **actually invoked**,
that the visible error meets its own domain-specific Persian text pattern,
that neither the host secret marker nor the fake credential segment appears
anywhere in visible page text, and that there were **zero financial API
commands**. A missing error message, a missing API invocation or an inaccessible
tab fails the case.

## Trusted local validations retained

Two additional browser cases must preserve useful, *locally authored* input
errors even while the external bridge is being masked:

1. A synthetic history response with an invalid invoice count must still
   show `اطلاعات معتبر ۱۹۵ فاکتور پارسیان دریافت نشد.` from the local
   195-invoice validation.
2. A read-only CSV preview attempted with **no three selected CSV files**
   must still show `انتخاب هر سه فایل CSV الزامی است.` and must not call the
   native CSV preview API.

This distinction is limited to the tested validation paths. The QA test does
not claim that all other local validation conditions or all future backend
error combinations have been covered.

## Test runs recorded

| Execution | Result | Meaning |
| --- | --- | --- |
| `node --check` | Exit **0** | New test file parses |
| `node --test` with neither selection variable | Exit **1**, `BLOCKED_V104_COMPILED_ACCEPTANCE` | Fail-closed; **zero** v1.0.4 browser acceptance checks run |
| Explicitly point `TARAZ_V104_BUILD_DIR` to pinned v1.0.3 build `build-eb9d4f2ab076` | Exit **1**, `BLOCKED_V104_COMPILED_ACCEPTANCE` | Old build refused before browser execution |
| Explicitly point `TARAZ_V104_BUILD_DIR` to patched `source-stage-959986753b61` | Exit **1**, `BLOCKED_V104_COMPILED_ACCEPTANCE` | A source patch stage without compiled artifacts cannot impersonate a release |
| Explicitly point `TARAZ_V104_STAGE_DIR` to verified `vite-qa-1ff6df468d81` | Exit **0**, **10/10 passed**, 15.9945 s | Seven distinct host-secret redaction screens passed; both local validation controls passed; **STAGE_UI_ONLY** |

The initial blocked checks observed
`source-stage-c0e2d0e0a190`, a detached original-source and proposed-patches
stage, and `source-stage-959986753b61`, a separately created applied-patch
stage with `stage-report.json` status
`V104_PATCHED_SOURCE_FROZEN_QA_PENDING_NO_EXE`. Neither contained a compiled
v1.0.4 EXE or Vite dist when inspected. Later, worker29 produced the separately
attested Vite QA frontend. The first Edge run passed seven redaction tests and
the 195-invoice validation, while the CSV-control case was blocked by a QA
selector that failed to find the correct dropdown; that test selector was
corrected within this worker's owned test file. The full subsequent run was
**10/10 PASS**. The available evidence supports the **Vite frontend** only.
**No v1.0.4 production release decision can be made from this report**. A
separately produced real EXE must pass the full native-asset gate and other
release approval checks.

This test intentionally avoids any write to the installed 1.0.2 pointer,
production finance files, Windows user profile, or Madar LAN service.
