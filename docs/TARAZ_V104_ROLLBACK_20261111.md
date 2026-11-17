# Taraz RC3 v1.0.4 → v1.0.2 | Operator-only pointer rollback

**Result: REAL PINNED OPERATOR GATE CREATED, DISPOSABLE QA PASS 28/28, ZERO SKIPS.**
**Production installation/rollback: NOT PERFORMED.** This is readiness of the
rollback *script*, not final v1.0.4 release approval or financial migration QA.

## Create-only operator output

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\rollback-gate-38a3fb5dbb19`

| Verified output | SHA-256 |
|---|---|
| `Rollback-Taraz-V104-To-V102.ps1` | `fa1c3216c59b9f98b0603255c388831ac75c1e4e37032055369f7edda6b31922` |
| `rollback-gate-manifest.json` | `053fbea99e9a9441c73ff5131185b890f0ba6b044afa1922b1b80ae1b8f91dec` |

Manifest status: `OPERATOR_ROLLBACK_GENERATED_NOT_EXECUTED`, from `1.0.4`
to `1.0.2`, `requiresApply=true`, `rollbackExecuted=false`, `productionTouched=false`.
The **exact generated PS1** was read back by SHA and invoked during simulated
Windows QA, without editing the operator script or treating a surrogate as RC3.

Only these three NEW source/doc files are owned by this work:
`scripts/taraz_v104_operator_rollback_20261111.py`,
`tests/test_taraz_v104_operator_rollback_20261111.py`,
`docs/TARAZ_V104_ROLLBACK_20261111.md`.

## Independent RC3 file/hash provenance

Actual immutable build:

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-0bde36e11d99`

| RC3 artifact | Verified SHA-256 |
|---|---|
| `offline-update/Taraz.exe` and `binary/Taraz.exe` | `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` |
| RC3 secure offline ZIP | `1a9ca13c914385c92be68ffdd2034c723843dde1846fa548762864aa98ac134e` |
| `offline-update/update-manifest.json` | `b6ac2e3050274e3ec8e3bcaaf32b694d673b1747cfab580245136ec500e65bc6` |
| `build-report.json` | `510de237a7fcea8553e0a64951bf76f3f7bef722318585db016d4e602df8b9fb` |
| `offline-update/Activate-Taraz-V104.ps1` | `3d7cb9aea21e54864fd8215ee686c48245c1b76f032afefe455c6782f3957937` |
| `offline-update/Install-Taraz-V104.ps1` | `6dda4897c1ce4da9120d3e6fda9c639834080f838602de02e32eea46c3de6a68` |
| RC3 source snapshot fingerprint (manifest/report) | `e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de` |
| Existing genuine v1.0.2 EXE | `095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52` |
| Existing v1.0.2 launcher | `93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21` |

All SHA values above were rehashed directly from actual files where available;
the source snapshot value is a checked **manifest/report fingerprint**, not
an independent rehash of every source file. No RC1 hashes were reused.

The actual RC3 `Activate-Taraz-V104.ps1` was read and checked, including
create-new byte-preserving launcher backup and atomic pointer replacement:

* Pre-activation pointer backup `current-version-pre-1.0.4.txt`.
* Byte-identical launcher backup `Run-Taraz-pre-1.0.4.cmd`, created with
  `FileMode.CreateNew` and checked against current launcher digest.
* Final pointer `1.0.4` through `File.Replace` with rechecks.

The existing launcher contains `current-version.txt` and the exact versioned
`versions\%TARAZ_VERSION%\Taraz.exe` path, and is compatible with retained
v1.0.2 when the pointer returns to `1.0.2`. The RC3 manifest
`secureRepackage.launcherBackupName` and baseline launcher fingerprint matched.
The generator specifically checks this *real* RC3 schema instead of inventing
the previously proposed `activationBackupContract` object.

## Exact operator script behavior

The resulting PS1 is **not run automatically** and performs no installation.
It requires a real installed v1.0.4 and approved operator action. By default,
invocation without `-Apply` is read-only preflight and should yield
`READY_FOR_OPERATOR_ROLLBACK_1.0.4_TO_1.0.2_NO_CHANGES` only when all
prerequisites hold. On the *currently installed* v1.0.2 it must block.

Preflight requires exact SHA and native PE versions for both retained
executables, current pointer `1.0.4`, pre-activation pointer backup `1.0.2`,
active and backed-up launcher pinned SHA values, correct launcher ABI,
no active Taraz PID (fail closed if CIM process detection unavailable), local
non-junction paths and ancestors, precisely one NTFS hardlink for critical
files (with independent `fsutil` confirmation), write ACLs for parent/pointer,
and no pre-existing rollback/pending backup files.

Only explicit `-Apply` rechecks prerequisites and creates a temporary
`1.0.2` pointer, then uses `File.Replace` atomically, saving the previous
`1.0.4` pointer in `current-version-pre-rollback-1.0.4.txt`. It does not
replace, remove or modify either EXE, either launcher, finance ledger, or
profile. A post-replacement readback mismatch reports a hard error without
retrying an uncertain financial or pointer mutation.

**Operator example, NOT executed on installed Taraz:**

```powershell
$gate = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\rollback-gate-38a3fb5dbb19'
$script = Join-Path $gate 'Rollback-Taraz-V104-To-V102.ps1'
(Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant()
# Explicitly read-only operator preflight, once v104 is genuinely installed:
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script
# Operator-authorized rollback ONLY when separately approved:
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script -Apply
```

## Tests performed

Windows PowerShell 5.1 + Python 3.12:

```powershell
$env:TARAZ_V104_ROLLBACK_GATE = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\rollback-gate-38a3fb5dbb19'
python -B -m unittest discover -s tests -p test_taraz_v104_operator_rollback_20261111.py -v
Remove-Item Env:TARAZ_V104_ROLLBACK_GATE
```

**Observed: `Ran 28 tests in 29.194s`, `OK`, exit `0`, 0 skips.**

The tests copy the **actual independently hashed RC3 v1.0.4 executable** and
the real retained, pinned v1.0.2 executable into disposable Windows install
directories, with matching byte-exact launcher and activation backups. They
execute the exact generated operator PS1, without changing its PE4 check.
Only an isolated PowerShell wrapper overrides `Get-CimInstance` for
determinism; dedicated tests inject both an active Taraz process and a CIM
failure. The canonical PS1 still checks actual CIM at operator runtime.

Verified positive cases: `-Apply` changes the *synthetic* pointer from
`1.0.4` to `1.0.2`, writes previous `1.0.4` as rollback backup, retains both
EXE hashes and both launcher bytes, and does not change disposable finance
sentinel. Repeated application blocks. Default preflight makes no mutation.

Negative cases: changed pointer, missing/corrupt pointer activation backup,
missing/corrupt launcher backup, modified active launcher, deleted/tampered
v1.0.2 EXE, single-file hardlink violations on pointer, both executables and
launcher backup, ancestor NTFS junction, pointer symlink, read-only pointer,
explicit real Windows ACL deny, ACL lookup failure, active Taraz process,
CIM outage, existing rollback/pending pointer name, and wrong RC3 pin/manifest
preflight. Every test asserts both EXE hashes and finance canary unchanged.

After testing, a **read-only** check of the actual installation confirmed:
pointer `1.0.2`, genuine v1.0.2 EXE SHA unchanged, launcher SHA unchanged,
and no installed `versions/1.0.4` directory. Thus no actual installation,
activation or rollback occurred.

## Scope / outstanding gates

This validates the exact RC3 pointer-only rollback gate in disposable paths;
it does **not** imply product release GO, real installation success, customer
data recovery, durable power-cut safety or finance-migration acceptance.
RC3 build report itself records `installed=false` and `releaseApproved=false`.
Production deployment and any financial recovery still require separate
operator approval and release/backup acceptance. No network, Madar service,
actual user desktop, installed profile, launcher, original EXE or ledger was
modified.
