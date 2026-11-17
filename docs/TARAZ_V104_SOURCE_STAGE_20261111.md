# Taraz v1.0.4 P1: detached source stage and UI-only QA

Date: 2026-11-11. **Status: SOURCE STAGED; NATIVE BUILD AND RELEASE BLOCKED.**

This run did not edit the original v1.0.3 source or its EXE, installer,
ZIP, installed Taraz files, financial profiles, registry, services,
desktop or user windows. It did not run a production installer or
compile a Windows EXE.

## Authority and source provenance

The official `scripts.build_taraz_v103_p1_release_20261111.inventory()`
returned **131 trusted runtime inputs** with exactly this SHA-256 inventory
digest:

`a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279`

The existing `base.snapshot_source` copied those 131 files byte-for-byte
to a new create-only stage. After the copy, hashes, file-set completeness
and the original source digest were checked again.

All three owned source files are new:

- `scripts/stage_taraz_v104_p1_20261111.py`
- `tests/test_stage_taraz_v104_p1_20261111.py`
- `docs/TARAZ_V104_SOURCE_STAGE_20261111.md`

### Stage A: untouched starting copy and detached proposed diffs

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-c0e2d0e0a190`

Contents:

- `source/`: 131 original files, byte-identical to frozen source
- `starting-source-sha256.json`: 131-file reference
- `proposals/`: 11 separated, unapplied unified-diff files
- `proposal-index.json`: original/proposed SHA per file, offsets and rationale
- `stage-report.json`: no EXE, no install, no release approval

| Artifact | SHA-256 |
| --- | --- |
| `starting-source-sha256.json` | `ee77d0d4f231df32ea05d62f512f3a92cbd9d0effdeff9e5b101062637b82d49` |
| `proposal-index.json` | `b7451e6b2bad68ec73bc3e7f72483b384a492cc07a005a4e4c1760d028c544c1` |

`git apply --check --directory=source -p1` passed for **all 11** detached
patch files against Stage A. This did not apply or write any patch.

### Stage B: separately copied source with narrow reviewed masking

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-959986753b61`

Stage B started as another exact copy of the 131 official runtime inputs.
The source owner-approved targeted error masking proposals were then
applied **only in the Stage B copy** to nine frontend files. The resulting
131-file SHA-256 fingerprint is:

`6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1`

`patched-source-sha256.json` contains every new source-file hash and
`stage-report.json` records the exact nine edited file names and parent
stage. All 122 other runtime files remained byte-identical. In particular,
`package.json` and `package-lock.json` **still declare 1.0.0**, as in the
original frozen source. The two separate `1.0.4` version diffs in Stage A
are **packaging proposals only**. A future approved v1.0.4 builder should
apply the correct package/lock, PE and PYZ version inside its independent
build snapshot. It must not assume Stage B is already a 1.0.4 binary.

## Evidence for narrow UI error-redaction proposals

Worker27 tested the actual frozen v1.0.3 compiled UI in isolated Microsoft
Edge with a synthetic backend exception containing
`QA-V103-HOST-SECRET-72973`. Their reported completed tests demonstrated
visible raw exception text in **seven** flows. Stage B masks those host
exception values with fixed authored user messages:

| Proven v1.0.3 risk | Source location | Stage B proposal |
| --- | --- | --- |
| Company details load | `src/personal_parsian_company.jsx:26` | Fixed company-read failure text |
| Overview history warning | `src/taraz_home_command.jsx:95` | `L.error`, without raw exception |
| Extended history load | `src/personal_parsian_extended.jsx:48` | Fixed historical-source message |
| Historical invoices | `src/personal_parsian_invoices.jsx:44` | Fixed bridge error; preserve local 195-invoice count-validation copy |
| Bank and cash history | `src/personal_parsian_bank_movements.jsx:12` | Fixed history-read message |
| Archive row selection | `src/parsian_raw_archive_explorer.jsx:40` | Fixed row-load error; preserve the locally authored invalid-index message |
| CSV chooser | `src/provider_csv_migration.jsx:73` | Fixed native file-chooser message; preserve authored chooser-unavailable message |

Two additional sources of raw bridge errors were masked as static
precautions: `src/personal_parsian_dashboard.jsx` and
`src/accounting_action_home.jsx`. Within the nine edited files,
the archived invoice export catch was also masked, and archive index and
CSV preview catches were separated or restricted.

For CSV preview, `buildProviderCsvRequest` runs in a distinct synchronous
`try/catch` and retains **locally authored validation messages**. Any
failure returned by `api.standaloneAccountingCsvPreview` uses a generic
fixed error message. The internal and user-authored validations continue
to be available; untrusted native exception strings do not become UI copy.
The existing Madar inbox/settings redaction implementation is untouched.

**Boundary:** Edge proof of the seven leaks applies to the *original v1.0.3
bundle*. No claim that Stage B is browser-safe should be made until
worker27 independently runs the inverted seven-case fake-secret tests
on the Stage B compiled Vite bundle.

`src/accounting_print_designer.jsx` has additional local-renderer error
paths, and other UI panels contain generic `err.message` patterns.
Those were not silently rewritten without provenance. They remain
candidate review items; this limited stage does not certify complete
host-error redaction across every screen.

## Detached Vite frontend QA artifact

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-1ff6df468d81`

The Vite build used a separately copied source + locally available
dependencies inside an isolated QA workspace. Its resulting frontend
assets were created under `dist/` and the Stage B source was rehashed:

| Artifact | SHA-256 |
| --- | --- |
| `dist/assets/accounting-DANnPkpK.js` | `b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453` |
| `dist/assets/accounting-Cn_dODL0.css` | `1b267d6655ad7b78c4ee02fa4eedde46bfa7c1c711e3883020f7ef0f9cc74cbf` |

`vite-qa-report.json` contains `status=STAGE_UI_ONLY`,
`patchedSourceSha256=6cf6ca02...`, the full relative asset paths,
exact hashes and source-stage provenance. The Vite build reported
**2,056 transformed modules**, completion with exit 0, and a non-blocking
chunk-size warning for the 907.70 KB JavaScript output. **No native
Taraz.exe or release ZIP was created.**

## Repeatable validations

From the existing isolated Taraz project root:

```powershell
python -B scripts/stage_taraz_v104_p1_20261111.py --fingerprint

$env:TARAZ_V104_SOURCE_STAGE='D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-c0e2d0e0a190'
$env:TARAZ_V104_PATCHED_STAGE='D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-959986753b61'
$env:TARAZ_V104_VITE_QA_STAGE='D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-1ff6df468d81'
python -B -m unittest -v tests.test_stage_taraz_v104_p1_20261111
```

Observed **11/11 tests passed**, no skipped tests, exit 0. Test coverage
includes source drift rejection; unsafe paths and non-unique replacement
anchors; exact original and patched 131-file inventories; target SHA
checks; unchanged package and lock; syntax validation of all nine patched
JSX files through Babel parser; distinction between locally authored
validation copy and masked backend exception; Vite JS/CSS/HTML hash
readback; and EXE absence.

## Gates that remain open

1. **Worker27** must independently test the exact `accounting-DANnPkpK.js`
   bundle in isolated Edge with fake secret-bearing native failures in all
   seven previously confirmed flows. Additional regression QA must verify
   local validation messages, CSV preview behavior, archive navigation and
   finance posting commands stay disabled in synthetic browser fixtures.
2. **Worker26 and prime** must complete a separately pinned full installer
   and activation fix with proper FileInfo.Directory ancestor checks and
   fail-closed hardlink checks in disposable Windows PowerShell 5.1.
   The original frozen v1.0.3 installer/ZIP remains **NO_GO**.
3. An explicitly approved builder must create actual `1.0.4.0` PE version,
   package/lock `1.0.4`, PYZ marker and a release manifest from a pinned
   source snapshot. Independent compiled binary and installer/rollback
   tests must pass before any production installation.
4. Financial migration, real posting, installed GUI acceptance and
   recovery/rollback on live user data are **unverified** by this staging
   task; none of those actions occurred.

**Release state: STAGE_UI_ONLY, source patches reviewed structurally,
dynamic post-patch Edge QA pending, native EXE build not authorized.**
