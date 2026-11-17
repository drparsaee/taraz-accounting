# Taraz 1.0.3 to 1.0.2 | Operator rollback | 2026-11-11

**State: OPERATOR_ROLLBACK_GATE_CREATED_NOT_EXECUTED.** The canonical
PowerShell operator gate passed **22/22 tests** in disposable Windows
installation directories containing byte-identical copies of the real
v1.0.2 and v1.0.3 executables. No production rollback was performed.

## Canonical output

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\rollback-gate-3714fee2ca06`

| File | SHA-256 |
| --- | --- |
| `Rollback-Taraz-V103-To-V102.ps1` | `39b62821db04b3c2fc8de783148bf1e374113802fa1d36702cb89ab50c970c5a` |
| `rollback-gate-manifest.json` | `dcf868d2f483c7514ce5f80c3713850a14d78aa2e1d71d6aeb8c9700af7be1f6` |

Only the following **new** source files belong to this change:
`scripts/taraz_v103_operator_rollback_20261111.py`,
`tests/test_taraz_v103_operator_rollback_20261111.py` and
`docs/TARAZ_V103_ROLLBACK_20261111.md`.

Earlier drafts `rollback-gate-f20444872b56`,
`rollback-gate-24180164d190` and
`rollback-gate-dad44a3c6367` are **SUPERSEDED / INVALID**. They are
not operator artifacts and must not be used. The canonical gate above
contains the repaired script and has complete passing test evidence.
The frozen v1.0.3 EXE, ZIP and installer have not been modified.

## Version and executable authority

| Executable | Native PE file/product version | SHA-256 |
| --- | --- | --- |
| Retained v1.0.2 | `1.0.2.0` | `095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52` |
| Frozen v1.0.3 | `1.0.3.0` | `e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c` |

The generator read and verified the immutable v1.0.3 release
`build-eb9d4f2ab076`, its source snapshot fingerprint
`a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279`
and release manifest SHA
`0f76af740467a1630be9aca7477df5f4a920fdfc879a9aa68a29807f5ecac634`.
The unchanged v1.0.3 offline ZIP SHA is
`4e46df72c488f824b9a5eb9683b8d7f32b7d1f94d4af2858f9c8623b40ca0eae`.

## Operator gate behavior

The PowerShell script reads the installed root at
`%LOCALAPPDATA%\Programs\Taraz`. It does not accept an install-root
override and fails closed unless all of the following are true:

1. `current-version.txt` contains exactly `1.0.3` and the original
   activation backup `current-version-pre-1.0.3.txt` contains `1.0.2`.
2. Both versioned EXE files exist, match both pinned SHA-256 values and
   have the required Windows PE versions.
3. The launcher retains the
   `versions\%TARAZ_VERSION%\Taraz.exe` contract.
4. No active Taraz process is detected and process enumeration succeeds.
5. Required files and their ancestors are local and have no symlinks,
   junctions or other reparse points. The pointer, both EXEs, launcher
   and original activation backup must also have **exactly one NTFS
   hardlink**, verified with PowerShell and independent `fsutil` output.
   An unavailable hardlink count is treated as blocked.
6. The pointer and installed root have writable Windows ACLs; the
   pointer is not read-only.
7. Neither `current-version-pre-rollback-1.0.3.txt` nor
   `current-version-rollback-to-1.0.2-pending.txt` already exists.

**Default invocation** performs preflight only and prints
`READY_FOR_OPERATOR_ROLLBACK_1.0.3_TO_1.0.2_NO_CHANGES`.
It does not create or modify any installed file.

**Explicit `-Apply`** checks the state twice, then validates the
process list, both executable hashes, old pointer and activation
backup again. It writes a temporary pointer containing `1.0.2`,
then atomically replaces `current-version.txt` via `File.Replace`
and preserves the former `1.0.3` pointer at
`current-version-pre-rollback-1.0.3.txt`.
Both executables and the original activation backup are retained.
No accounting database or finance profile path is opened or written.
On post-replace readback failure the script reports a hard error for
operator inspection instead of attempting an unverified second write.

## Operator invocation only after v1.0.3 activation

Verify that the script SHA matches the canonical value above. The
commands below are documented examples; **they were not run on the
actual installed Taraz**.

```powershell
$gate = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\rollback-gate-3714fee2ca06'
$script = Join-Path $gate 'Rollback-Taraz-V103-To-V102.ps1'
(Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash.ToLowerInvariant()

# Read-only preflight
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script

# Operator-approved pointer rollback
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $script -Apply
```

## Verified test evidence

Windows Python 3.12 and PowerShell 5.1:

```powershell
$env:TARAZ_V103_ROLLBACK_GATE = 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\rollback-gate-3714fee2ca06'
python -B -m unittest -v tests.test_taraz_v103_operator_rollback_20261111
Remove-Item Env:TARAZ_V103_ROLLBACK_GATE
```

**Observed:** `Ran 22 tests in 23.747s`, `OK`, exit `0`.
**22 passed, 0 failed, 0 skipped**. Tests exercised the **actual generated
PS1**, not an edited test copy. They copied authentic, SHA-pinned
v1.0.2 and v1.0.3 EXE bytes to private simulated installation directories
and did not execute either EXE.

Coverage: default preflight does not modify the simulated install;
`-Apply` atomically switches only the pointer and creates the backup,
with both EXEs unchanged; repeated `-Apply` is blocked. Negative
cases include changed pointer, missing or corrupt activation backup,
missing old EXE, tampering with either executable hash, wrong PE
version, existing backup/pending file, changed launcher, read-only
pointer, symlink pointer, hardlinked pointer and either executable,
active Taraz and failed process enumeration.
Each test checks unchanged fixture EXE hashes and a finance-data sentinel.

The fixture uses a process-enumeration stub to isolate the tests
from unrelated concurrent Taraz GUI QA sessions. Dedicated tests
prove that the gate rejects an active process and an unavailable
process list. The canonical PS1 retains its real `Get-CimInstance` check.

After testing, a read-only check showed the actual installed
pointer remains `1.0.2`, the actual installed v1.0.2 EXE SHA
remains `095a7c25...` and `versions\1.0.3` is absent. Thus,
the rollback would currently block on the real installation, as
intended, and was never executed there.

This validates the **pointer rollback contract**, not live v1.0.3
application startup, financial migration, complete data recovery
or an actual installed rollback. Independent QA worker26 review
was requested via the prime agent; its signoff is separate and
must not be claimed until its report arrives.

**Critical adjacent release blocker:** The unchanged original frozen
v1.0.3 install/activate scripts have an ancestor junction validation
defect in `FileInfo.Parent`. The prime independently reproduced that
defect on a disposable Windows 5.1 path. This corrected rollback gate
does **not** repair that installer. The original offline v1.0.3 ZIP
must remain **NO_GO** pending a separately pinned replacement package
and independent acceptance.
