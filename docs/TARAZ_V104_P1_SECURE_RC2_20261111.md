# Taraz v1.0.4 P1: RC2 security follow-up and RC3 build gate

**Status: RC3 CREATE-ONLY NATIVE BUILD AND DISPOSABLE QA COMPLETED;
NO PRODUCTION RELEASE.**

The scope was initially to create a new binary based on worker29's RC2 source
stage, after three residual dynamic UI errors had been fixed. During the
independent worker27 Edge verification, one leak remained: a host-provided
invoice-key value was returned as a structured analytics error and rendered
raw by the management dashboard. The RC2 stage was therefore rejected for
binary generation. The builder now requires **a separate RC3 stage** that
changes *only* the dashboard component relative to RC2 while preserving the
other two RC2 repairs and the original 131-file source inventory.

## Immutable, observed evidence

| Evidence | Observed value | Status |
| --- | --- | --- |
| Frozen v1.0.4 RC1 stage | `source-stage-959986753b61`, source SHA `6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1` | Preserved |
| Frozen RC1 compiled EXE | `build-6d851f756264/binary/Taraz.exe`, SHA `8e2a8026b48e278df95693d9349f5a566df9b75c12497882b3bebca96679adc6` | Preserved, NO_GO |
| RC1 compiled JS | `b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453` | Reuse forbidden |
| New RC2 source stage | `source-stage-146b4c62e3f8` | Rejected, NO_GO |
| RC2 131-file source fingerprint | `aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8` | Independently cross-checked from its manifest |
| RC2 source manifest SHA | `33892e1772ba79a5476dc69520d0e79197a5adcd2ec1bba797c98974032129f7` | Read-only |
| RC2 producer stage report SHA | `72171484e6e509244ef16e61cadb4d6eeab8e987f50edd399d93c8a1d360c4e9` | Read-only |
| RC2 Vite stage | `vite-qa-899a40d30820`, JS SHA `39295ea85bf2d6ee9fd94fce862c2bc505d4ac6ce01153fbc7ef9d8eea0b5b79` | **Not approved**: Edge inversion leaked an invoice identifier |
| **RC3 source stage** | `source-stage-ca9761aa43d8` | **131 actual inputs rehashed** |
| RC3 source SHA-256 | `e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de` | New source, distinct from RC1 and failed RC2 |
| RC3 source manifest SHA-256 | `b31db9348ad61f132be02788adfbbf5b93cc532f7f25bed25a7c701d8ed4ef11` | Independently rehashed |
| RC3 stage report SHA-256 | `2813cbcaeab16b7cbc9ce9b79d19fa3f5c24688cc2906e7fed06352f0a0b0ebe` | Independently rehashed |
| **RC3 Vite stage** | `vite-qa-72ee216638e4` | JS/CSS/HTML actual bytes checked |
| RC3 compiled-stage JavaScript SHA-256 | `3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9` | Distinct from RC1/failed RC2 |
| RC3 Vite report SHA-256 | `5940d2765b6a9ff6810078364fb5422c1eb112697f7f02f46156aa85624d69b8` | Independently rehashed |

**Additional independent RC3 source and Edge execution:** on the actual
source-stage and Vite assets above,
`py -3.12 -B -m unittest -v tests.test_stage_taraz_v104_rc3_20261111`
exited **0** with **10/10 passed, 0 skips**, and
`node --test tests/taraz_v104_residual_exception_leak_20261111.test.cjs`
using the exact `TARAZ_V104_RESIDUAL_RC3_STAGE_DIR`,
`TARAZ_V104_RESIDUAL_RC3_SOURCE_SHA256` and
`TARAZ_V104_RESIDUAL_RC3_JS_SHA256` variables exited **0** with **14/14
passed, 0 failed, 0 skips**. Output identified
`RC3_INVERTED_STAGE_UI_ONLY`. The three residual sources and seven
historical host-rejection cases were masked, with no finance API writes.
These observed executions establish independent stage-level evidence but
**do not replace final independently SHA-pinned QA witness artifacts** or
the later compiled-EXE test.

The three extra JSX files relative to RC1 are
`src/accounting_print_designer.jsx`,
`src/accounting_operational_panels.jsx`, and
`src/accounting_management_dashboard.jsx`. Only the dashboard component
may change between failed RC2 and corrected RC3. A new stage must preserve
all remaining files exactly, with 131 actual SHA-256 readbacks and no
symlinks or junctions.

## Owned deliverables

- `scripts/build_taraz_v104_p1_secure_rc2_20261111.py`
- `tests/test_taraz_v104_p1_secure_rc2_20261111.py`
- `docs/TARAZ_V104_P1_SECURE_RC2_20261111.md`

No RC1 source, builders, old EXE, original manifests, ZIP or installed Taraz
files are modified. New native output, when fully authorized by evidence,
will be exclusively a **new** `taraz-v1.0.4-p1/build-<id>` directory.

## Mandatory binary-generation gates

Every new RC3 build requires explicit, SHA-pinned paths and values for:

1. Worker29 RC3 stage directory, its SHA-256 source manifest and stage report,
   the 131-file canonical source fingerprint, and the actual file hashes.
   RC1 and failed RC2 stages are categorically rejected.
2. Worker29 newly compiled detached RC3 Vite stage, with exact JavaScript,
   CSS and HTML readback checks and a separately pinned Vite report.
   The JS SHA must differ from RC1's and rejected RC2's.
3. Independent source-stage QA PASS, with command/exit code and zero skipped
   or failed checks.
4. Independent real Edge **original seven host-error masking tests**, including
   evidence that no host-supplied secret reaches user-visible alerts.
5. Independent real Edge **three residual leak inversion tests**, covering
   print designer canvas exception, bank CSV file-text exception and malicious
   invoice-key analytics error. All must PASS and report zero finance API
   commands, with the same actual stage/Vite SHA as the builder.

None of these can be replaced by the stage producer's own
`stage-report.json`, a source-only claim, or an unpinned chat message. The
builder verifies all input gates **before** it creates any `build-*`
directory. After building, PE `1.0.4.0` and frozen PYZ `APP_VERSION=1.0.4`,
`QA_ONLY=False` are independently inspected from the binary, together with
all embedded UI asset hashes. New EXE and JS must not equal RC1 or v1.0.3.

The installer and activator reuse the already-tested Windows PowerShell 5.1
hardening: explicit `FileInfo.Directory` ancestor walking, fail-closed
Win32 hardlink count, create-only destination files, versioned pointer and
launcher backups, explicit installed v1.0.2 SHA, and independently witnessed
cold backup before switching versions. Both secure scripts are regenerated
with the **new RC3 source manifest hash and actual compiled EXE SHA**.
Obsolete v1.0.3/RC1 rollback files are never bundled.

## Current verification and limits

Command:

```powershell
py -3.12 -B -m unittest -v tests.test_taraz_v104_p1_secure_rc2_20261111
py -3.12 -B scripts/build_taraz_v104_p1_secure_rc2_20261111.py
```

The initial pre-build suite was **15 pass, 3 intentionally skipped, 0
failures**. Those skipped cases were native-disposable tests blocked until
the compiled RC3 binary existed. The **final complete run was 20/20 PASS,
zero skipped or failed** (see below). The suite
checks immutable original/failing-stage pins, rejects old RC1/RC2 stages,
requires real independent Edge witness evidence, verifies source/version
retargeting in both PowerShell templates, runs actual Windows PowerShell
5.1 AST parsing, exercises synthetic seven-member ZIP creation, and confirms
the failed-stage build gate never starts Vite/PyInstaller or creates output.

After the subsequent independent stage Edge PASS, the create-only RC3 EXE
and ZIP were built, their exact hashes captured, and the actual native
PowerShell disposable install and activation tests completed. A dedicated
RC3-compatible operator rollback and production-scale financial tests
remain mandatory.

**Production remains NO_GO** pending all runtime, GUI/role, finance,
rollback, signing and operator-approval gates.

## Completed RC3 create-only native build and QA

**Final observed RC3 build directory:**

```text
D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-0bde36e11d99
```

This was produced **only after** a separate prime-owned 10/10 source QA,
14/14 RC3 Edge QA (covering the prior seven and three residual sinks), and
exact SHA verification of the following three create-only QA witnesses:

- `qa-evidence-rc3-prime-59c27fd65bbe/rc3-source-stage-qa.json` SHA
  `0accc1863a82dadfd057b19ad48c962747b1f2a06290c7937c207d4d958b027f`.
- `rc3-original-seven-edge-qa.json` SHA
  `1743aaa93d185c1895545b497b324344d25541ef1bde1d2e4df54bf1524ece54`.
- `rc3-residual-three-edge-qa.json` SHA
  `b6db26fceb2197e1125c97e313cf16ff510ddb64ae7eef9d1aaa519928e08f25`.

No RC1/failing RC2 source or compiled JavaScript was accepted. The actual
new source digest was
`e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de`.

| Actual RC3 artifact | SHA-256 independently read back |
| --- | --- |
| `binary/Taraz.exe` | `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` |
| `Taraz-v1.0.4-P1-RC3-SECURE-OFFLINE-UPDATE.zip` | `1a9ca13c914385c92be68ffdd2034c723843dde1846fa548762864aa98ac134e` |
| `offline-update/update-manifest.json` | `b6ac2e3050274e3ec8e3bcaaf32b694d673b1747cfab580245136ec500e65bc6` |
| `build-report.json` | `510de237a7fcea8553e0a64951bf76f3f7bef722318585db016d4e602df8b9fb` |
| `offline-update/Install-Taraz-V104.ps1` | `6dda4897c1ce4da9120d3e6fda9c639834080f838602de02e32eea46c3de6a68` |
| `offline-update/Activate-Taraz-V104.ps1` | `3d7cb9aea21e54864fd8215ee686c48245c1b76f032afefe455c6782f3957937` |
| Embedded compiled JS asset | `3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9` |

The Windows PE version **1.0.4.0**, frozen Python PYZ version **1.0.4**,
`QA_ONLY=False`, expected native bridge and embedded Vite asset hashes were
checked from the real newly built executable, which was never launched.
The new seven-member ZIP was rehashed member by member; no previously
generated v1.0.3/v1.0.4 RC1 rollback was included.

Native Windows PowerShell 5.1 test command, with the actual build path and
the four artifact hashes above pinned in environment variables:
`py -3.12 -B -m unittest -v tests.test_taraz_v104_p1_secure_rc2_20261111`.
Result: **20 tests passed, 0 failed, 0 skipped**. The successful tests
included actual `-Apply` installation and activation in a *disposable*
LOCALAPPDATA with copied real pinned 1.0.2 and RC3 EXE, backup readback of
`current-version-pre-1.0.4.txt` and `Run-Taraz-pre-1.0.4.cmd`, retention
of the original binary and synthetic finance canary, denial of a second
activation, denial of hardlinked pointer/new EXE/package EXE, and denial of
the nested junction in the private installation path.

The separate original-seven redaction acceptance was also executed
**against the actual compiled RC3 EXE**, not the Vite stage:
`TARAZ_V104_BUILD_DIR=.../build-0bde36e11d99 node --test
tests/taraz_v104_host_error_redaction_acceptance_20261111.test.cjs`.
Result: `VERIFIED_MODE=EXE_COMPILED_UI`, **10/10 PASS**, zero failures/skips,
compiled JS SHA identical to RC3 staged JavaScript. The three additional
residual scenarios were independently proven against that identical staged
JavaScript, **14/14 stage-level cases**; a separate native-EXE/browser
exercise of those three cases is outside this worker's completed direct
browser test.

**Published release decision remains NO_GO.** Additional pending gates:
dedicated RC3 EXE-hash-specific v1.0.4-to-v1.0.2 operator rollback,
authentication/roles, representative financial migration and readback,
production GUI functional acceptance, executable signing and explicit
operator approval. Successful build and disposable tests do not install or
approve the software.
