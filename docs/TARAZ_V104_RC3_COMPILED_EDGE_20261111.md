# Taraz v1.0.4 P1 RC3: Actual compiled EXE asset → Edge error-redaction acceptance

**Observed outcome: PASS for the new RC3 EXE's extracted frontend, 2026-11-11.**

**Scope:** independent QA of **the actual PyInstaller executable's embedded
JavaScript/CSS**, executed in a disposable headless Microsoft Edge browser
against deliberately synthetic host results. This is neither execution of
the native Windows EXE nor an installer/activation/ledger/financial approval.

## Owner-only output

- `tests/taraz_v104_rc3_exe_redaction_acceptance_20261111.test.cjs`
- `docs/TARAZ_V104_RC3_COMPILED_EDGE_20261111.md` (this report)

No existing QA files, shared frontend/runtime source, frozen build, service,
Windows installed profile, financial data or network settings were changed.

## Actual candidate and independently inspected provenance

| Evidence | Result |
| --- | --- |
| Explicit RC3 build | `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-0bde36e11d99` |
| Real PyInstaller binary | `binary\Taraz.exe` |
| **Actual EXE SHA-256** | `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` |
| RC3 stage source fingerprint | `e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de` |
| Expected real Vite RC3 asset | `accounting-5ZRme707.js` SHA-256 `3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9` |
| **Actual EXE CArchive `dist\assets\accounting-5ZRme707.js`** | Bytes extracted **in memory** via `PyInstaller.archive.readers.CArchiveReader`; SHA-256 **identical** to pinned RC3 JS and build web/dist JS |
| Actual EXE CArchive CSS | `accounting-Cn_dODL0.css`, SHA-256 `1b267d6655ad7b78c4ee02fa4eedde46bfa7c1c711e3883020f7ef0f9cc74cbf`, identical to RC3 Vite CSS |
| Actual EXE CArchive `accounting.html` | SHA-256 identical to RC3 Vite HTML attestation |
| **Actual PE fixed version** | `1.0.4.0` read from the EXE version resource |
| **Actual PYZ release module** | `taraz_release_version` extracted from `PYZ.pyz`, executed in Python with empty builtins to obtain `APP_VERSION='1.0.4'`, `QA_ONLY=False`, `BUILD_CHANNEL='offline-production-candidate'` |
| Build report | `PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED`, `releaseCandidateRevision='RC3'`, `installed=false`, `pointerChanged=false`, `releaseApproved=false`, `realLedgerModified=false` |

The test requires the **exact pinned EXE SHA-256** and the observed completed
build report, plus read-only checks against the pinned RC3 source-stage and
Vite stage reports. Merely presenting old v1.0.4 EXE, source-only stage or a
new file with the same filename cannot pass the gate.

## Exact test command and results

PowerShell from `D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

```powershell
node --check tests/taraz_v104_rc3_exe_redaction_acceptance_20261111.test.cjs
$env:TARAZ_V104_RC3_BUILD_DIR = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-0bde36e11d99'
node --test tests/taraz_v104_rc3_exe_redaction_acceptance_20261111.test.cjs
```

**Actual execution:** `node --check` **exit 0**, `node --test` **exit 0**.

```text
✔ RC3 actual EXE / PE / PYZ / embedded asset integrity gate
▶ RC3 real EXE-extracted JavaScript: 13 isolated Edge leak/validation cases
  ✔ InlineForm authored validation is visible without a finance command
  ✔ InlineForm intercepted host write failure stays masked by workspace execute
  ✔ print preview LOCAL canvas exception is masked in compiled UI
  ✔ bank CSV browser File.text LOCAL exception is masked
  ✔ management dashboard masks malformed host invoice ID
  ✔ discount allocation :297 exposes locally authored validation, not native error
  ✔ historical v103 leak regression: company archive backend rejection stays masked
  ✔ historical v103 leak regression: overview history backend rejection stays masked
  ✔ historical v103 leak regression: migration extended backend rejection stays masked
  ✔ historical v103 leak regression: migration invoices backend rejection stays masked
  ✔ historical v103 leak regression: cash bank history backend rejection stays masked
  ✔ historical v103 leak regression: archive table rows backend rejection stays masked
  ✔ historical v103 leak regression: CSV choose backend rejection stays masked
✔ RC3 real EXE-extracted JavaScript: 13 isolated Edge leak/validation cases
ℹ VERIFIED_MODE=RC3_EXE_EXTRACTED_EDGE JS_SHA256=3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9
ℹ tests 15
ℹ pass 15
ℹ fail 0
ℹ duration_ms 13537.7707
--- exit code 0 ---
```

**Accounting of tests:** 13 browser leaf cases, one parent browser suite and
one independent native-EXE-integrity test = **15 total pass, zero fail**.

## What these 13 isolated compiled-byte Edge tests establish

The three **residual inverse tests** injected a private synthetic marker
`QA-V104-RESIDUAL-LOCAL-58317` into: (1) an invalid invoice key delivered
within an otherwise accepted synthetic host view, (2) a forced browser Canvas
rendering exception, and (3) a forced browser CSV `File.text()` read exception.
The RC3 EXE-embedded frontend displayed **useful generic Persian messages**
but never displayed the marker in any rendered page-body text. These three
scenarios failed for the original RC2/baseline versions where applicable.

The **seven historical host-rejected read** cases were replayed on company,
overview, migration, invoice archive, cash history, archive table and CSV
chooser. The fake backend was actually called and rejected with an invented
secret; every rendered error stayed generic. The **InlineForm financial
command** was rejected by the synthetic backend **before any write** and was
masked by workspace `execute`, with **one attempted bridge call and zero
applied financial writes**. Two **trusted local validation** cases retained
useful authored input messages. For every browser case, there were no
uncaught page errors; the synthetic page was served in-memory, and any other
HTTP request was aborted.

The 13 actual scenario implementations are reused **read-only** from the
already verified `tests/taraz_v104_residual_exception_leak_20261111.test.cjs`,
only after checking its pinned SHA-256:

`0b6612f345e856c958f7d31bb2098c057fc0d076bcf403dbdc366a0d0bf35f4f`

The new suite substitutes its asset provider **in memory**, ensuring the
scenario code consumes **EXE-extracted** JS/CSS rather than the stage Vite
file. Scenario code runs in a restricted VM without `require`, OS process,
network, or filesystem access. The EXE itself is never launched.

## Explicit limits and release decision

- **Supported:** `RC3_EXE_EXTRACTED_EDGE` UI redaction gate **PASS** for the
  exact named candidate, with authentic extracted bytes and checked PE/PYZ.
- **Not verified:** actual installed Windows native GUI behavior, packaging
  installation, activation, pointer/rollback, real bridge interactions,
  financial persistence, corrupted real-world ledger conditions, antivirus,
  and broad security beyond these 13 controlled scenarios.
- **Not authorized:** production install or release from this QA test alone.
  Earlier v1.0.4 builds and failed RC2 remain unapproved; their code is not
  substituted for the newly tested RC3 executable.

Final build acceptance must incorporate independent installer/rollback,
compiled native GUI, and financial safety gates owned by the other workers.
