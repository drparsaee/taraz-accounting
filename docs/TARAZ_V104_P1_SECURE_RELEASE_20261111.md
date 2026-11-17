# Taraz v1.0.4 P1: isolated secure native build, November 11, 2026

## Scope and safety boundary

**Decision: CREATE-ONLY QA CANDIDATE BUILT; PRODUCTION NO_GO.** The new
builder `scripts/build_taraz_v104_p1_secure_release_20261111.py` executed
only after independent source-stage QA (11/11) and staged-Edge QA (10/10)
were SHA-pinned. The build is isolated under the new
`taraz-v1.0.4-p1/build-6d851f756264` folder. No installation, activation,
user-profile edit or real-ledger mutation was performed. **A separate
post-build residual error/secret leak audit has found three further exposed
UI paths, so this candidate is explicitly rejected for publication.**

The source of truth for the v1.0.4 runtime is the *actual 131 file bytes*
in the applied stage:

```text
D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-959986753b61
```

| Pinned evidence | SHA-256 / value | Independently checked |
| --- | --- | --- |
| Applied source fingerprint | `6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1` | 131 individual file hashes, SHA over sorted canonical JSON |
| Applied source inventory file | `12f54656851c65e981d6bf20bb86952029d57ef79081d26c5dde51d6565f1add` | Yes |
| Applied stage report | `d8cd7344b943a0b40f27c1dbdfb7bee24c58ab49a36f07349d6f654dc3e132c0` | Read-only SHA |
| Old frozen source fingerprint | `a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279` | 131 old inputs compared: exactly nine approved source changes |
| Original installed v1.0.2 EXE | `095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52` | Expected baseline (no write) |
| Frozen v1.0.3 EXE, explicitly forbidden in v1.0.4 output | `e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c` | Reuse rejected |
| Worker29 detached Vite stage | `vite-qa-1ff6df468d81` | Actual JS/CSS/HTML rehashed |
| Vite-stage JavaScript | `b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453` | Actual asset SHA matched attestation |

The modified source files are confined to nine files: accounting action home,
raw archive explorer, bank movements, company, dashboard, extended, invoices,
CSV migration and home command. No tenth modified source file and no missing or
extra runtime input is accepted. The source stage deliberately retains
`package.json` and lock at `1.0.0`; only a detached, new build snapshot
receives `1.0.4`.

## Independent prerequisites for native build

The following **two separately SHA-pinned QA witnesses** are mandatory. A
producer's `stage-report.json`, a Vite build report with
`browserQaVerified=false`, or a successful unit test count copied into chat
is **not** sufficient:

1. Applied-source-stage structural tests, with the exact 131-file fingerprint
   and verified PASS result, zero failures and a SHA-pinned witness file.
2. Staged-Edge redaction acceptance against worker29's detached Vite assets,
   including the seven known host-exception error paths, with zero failures,
   source fingerprint and independently pinned result.

The CLI contract requires each witness JSON to provide `kind`
(`applied-source-stage` or `staged-edge-redaction`), `status=PASS`,
`sourceStage`, `sourceSha256`, `sourceCount=131`, `failures=0`, and a
positive `checksPassed` integer. It verifies the **actual supplied witness
bytes** against the explicit SHA argument. It then rehashes 131 source files
again, rechecks the Vite asset hashes and verifies the untouched installed
v1.0.2 baseline. All gates execute **before** any `build-<id>` folder exists.

The user has already authorized the **isolated create-only P1 build once
these gates pass**. This is not authorization for installation, activation,
publication, financial mutation, or operator production GO.

## Native build and evidence

After the gates are proven, the builder reuses the established v1.0.3
Windows PyInstaller + Vite architecture, but not its broken original
installer script or its frozen v1.0.3 EXE. Specifically:

- Copy 131 runtime files into the new build snapshot with independently
  checked hashes. Only there, stamp package and lock `1.0.4`, add a
  `taraz_release_version` module with `APP_VERSION="1.0.4"` and
  `QA_ONLY=False`, and inject a strict version check into the native entry.
- Rebuild Vite from that snapshot; compare its actual JS, CSS and HTML bytes
  with the independently tested detached Vite QA stage. A mismatch fails
  before PyInstaller.
- Compile a new onefile Windows `Taraz.exe` using an actual `1.0.4.0`
  native PE version resource and the five source-proven hidden modules.
- Open the compiled EXE **as an archive without launching it**. Inspect actual
  PE resource, PYZ release module constant assignments, native bridge
  allowlist/methods and SHA equality of all packed UI bytes. Reject any
  reused v1.0.3 EXE or JavaScript.
- Create a seven-member `Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip`,
  containing the **new** EXE, hardened v1.0.4 installer/activator,
  update manifest, 131-input source manifest, and staged package/lock.
  Every ZIP member is rehashed against the unpacked output and its manifest.

The hardened v1.0.4 scripts reuse the proven v1.0.3 security primitives:
`FileInfo.Directory` and each `DirectoryInfo.Parent` ancestor checked
for NTFS junction/reparse points, Windows
`GetFileInformationByHandle` hardlink count exactly **1** (fail closed),
create-only v1.0.4 EXE, no-running-Taraz gate, independently witnessed cold
backup, atomic pointer replacement, and original pointer + launcher backup
readback. **Every version identifier and binary/source hash is restamped
for v1.0.4**; no v1.0.3 rollback file is copied.

A separate **v1.0.4-to-v1.0.2 operator rollback must be generated with the
new actual EXE SHA**, then separately tested before any production approval.
The earlier v1.0.3 rollback cannot safely be reused. The secure ZIP has
`rollbackIncluded=false` until that independent step.

## Test commands and current evidence

```powershell
# Both commands are read-only with respect to the staged source and real install.
py -3.12 -B scripts/build_taraz_v104_p1_secure_release_20261111.py --preflight
py -3.12 -B -m unittest -v tests.test_taraz_v104_p1_secure_release_20261111
```

Final builder/disposable results: **24/24 tests PASS**, 0 errors/skips. Read-only
preflight rehashed all 131 source bytes, confirmed the exact nine changes,
and found no compiled EXE. A test intentionally calls `--build` without
QA witnesses and confirms it **fails before invoking Vite/PyInstaller or
creating any new build directory**. Tests also check rejected path traversal,
tampered fingerprints, equal-but-wrong package names, QA report hash drift,
incorrect QA results, no v1.0.3 rollback/script/binary reuse, actual
PowerShell 5.1 AST parsing, and seven-member ZIP creation using only a fake
synthetic executable in a temporary directory.

The actual isolated build ran only after stage QA witnesses were available
and independently rehashed. Its audited command follows (shown for
reproducibility, **not** a recommendation to rebuild the frozen candidate):

```powershell
py -3.12 -B scripts/build_taraz_v104_p1_secure_release_20261111.py --build `
  --frozen-sha 6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1 `
  --stage-qa D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\qa-evidence-prime-79d7d3c40b08\source-stage-qa.json `
  --stage-qa-sha ee9743970f38f4d1086ffca5edcbd9843fc0509dc9ec7ba7de4690744c1abe74 `
  --edge-qa D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\qa-evidence-prime-79d7d3c40b08\staged-edge-qa.json `
  --edge-qa-sha 1c2856c365298950a64235fac68f35642832c3c43a56f12aa594756ca0c0e997 `
  --vite-dir D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-1ff6df468d81 `
  --vite-js-sha b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453
```

**Actual generated artifacts:**

| Result | Verified SHA-256 |
| --- | --- |
| New real Windows EXE, PE `1.0.4.0`, PYZ `1.0.4` non-QA | `8e2a8026b48e278df95693d9349f5a566df9b75c12497882b3bebca96679adc6` |
| Hardened seven-member ZIP | `721bbf8d6fd461fb1317fb1394b26d0ad67237d4fbc8f3d9cbfc8442b5f79777` |
| Manifest | `116f325052c8db7b5386e0eae937d45db809760fbac42780d3e0d62657b32c75` |
| Install PS1 | `f904625641734ba23912a39430ccfdc2581bdbb0cbc2a6a3686b8698b8abb0c4` |
| Activate PS1 | `c2547005c3246b1519db7be8c864936ada4eb994963d1fc5a7c3eadf28577900` |
| Build report | `c2f3ed699c679098e158f8dff619fc440abaf180089ea30a4e5796139bb8027b` |
| Embedded compiled JavaScript (same as stage Vite SHA) | `b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453` |

Independent source/compiled-PYZ/PE/embedded-UI checks passed. The **compiled
EXE** Edge test completed `VERIFIED_MODE=EXE_COMPILED_UI`, 10/10 PASS,
zero failures or skips, covering the original seven host-rejection sinks and
two locally authored validations. However, a **different** independent
worker27 audit subsequently found real residual leaks in print-designer
Canvas exception handling, bank CSV file-text exception handling, and a
host-provided invoice-key diagnostic surfaced in the analytics dashboard.
These are **not** covered by the original seven rejection tests. The
compiled version remains **NO_GO**; preserving the binary does not fix them.

The full **24/24** Python suite also executed the actual hardened
`Install-Taraz-V104.ps1` and `Activate-Taraz-V104.ps1` in native PowerShell
5.1 against disposable copies of the byte-pinned v1.0.2 and v1.0.4 EXEs.
Positive dry-run/install/activation succeeded; only the private pointer
advanced to v1.0.4, with pointer and launcher backups hash-verified and
duplicate activation rejected. Negative tests rejected NTFS hardlinked
installed v1.0.2 EXE, v1.0.4 EXE, pointer, nested junctions, and a missing
backup. A synthetic financial canary was unchanged.

Finally, the **real installed** Taraz remains version `1.0.2`. Its EXE SHA
`095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52`,
pointer SHA `0dc8489f55b24f8c7f12619f9e5e25a3eab2ce5cce7e057413d9c27c26b7d675`,
and launcher SHA `93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21`
were unchanged. The installed `versions/1.0.4` folder is absent.
The compiled v1.0.4 candidate remains unsigned and has no dedicated,
independently validated v1.0.4-to-v1.0.2 rollback. The next candidate must
be a **new create-only source freeze/build** after the three residual leaks
are repaired, not a rewrite of this frozen output.

**Do not conflate successful source-stage QA with compiled executable
acceptance or production permission.**
