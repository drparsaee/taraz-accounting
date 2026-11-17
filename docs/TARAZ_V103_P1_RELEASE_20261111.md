# Taraz 1.0.3 | P1 offline upgrade candidate | 2026-11-11

## Purpose and scope

This is a **non-QA native Windows candidate** built from the frozen Taraz P1
source. Its staging path is create-only and independent of the installed app.
It does not launch Taraz, update a finance profile, overwrite an existing
version folder, or switch the installed version pointer. Installing or
activating requires separate operator action and fresh cold-backup evidence.

Baseline observed read-only in `%LOCALAPPDATA%\Programs\Taraz`:

| Property | Value |
| --- | --- |
| Installed pointer | `1.0.2` |
| Installed binary | `versions\1.0.2\Taraz.exe` |
| Installed binary bytes | `17,056,486` |
| Installed binary SHA-256 | `095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52` |
| Frozen source inputs | `131` runtime inputs |
| Approved source SHA-256 | `a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279` |

The source freeze was communicated by the prime agent after completing P0
overflow/recovery signaling and P1 contextual-help and exception-redaction
changes. Build tooling independently checks the complete source inventory
before the build, during source snapshot, and after native compilation.

## Build and verification

From `D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

```powershell
python -B -m unittest -v tests.test_taraz_v103_p1_release_20261111
python -B scripts/build_taraz_v103_p1_release_20261111.py --fingerprint
python -B scripts/build_taraz_v103_p1_release_20261111.py --build --frozen-sha a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279
```

The builder makes `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\build-<id>`.
Inside the run, `source/` has a byte-matched immutable snapshot, `web/dist/`
the Vite frontend, `binary/Taraz.exe` the PyInstaller onefile native EXE,
`offline-update/` the installer, activation script, complete package/lock,
source hash manifest and candidate metadata, and the ZIP at the run root.

It independently inspects the new PE `1.0.3.0` file version, frozen PYZ release
module `APP_VERSION=1.0.3` and `QA_ONLY=False`, native Madar methods, packed
bridge/reader/template store modules, and byte equality between all Vite
assets and resources embedded in the final EXE. These are **static binary
checks**, not installed GUI or live accounting acceptance.

### Actual 2026-11-11 candidate

Build completed with exit code `0` and status
`PRODUCTION_V103_P1_CANDIDATE_BUILT_NOT_INSTALLED`. Its exact output root is:

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\build-eb9d4f2ab076`

| Artifact | SHA-256 / result |
| --- | --- |
| `offline-update/Taraz.exe` | `e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c` |
| `Taraz-v1.0.3-P1-OFFLINE-SIDE-BY-SIDE-UPDATE.zip` | `4e46df72c488f824b9a5eb9683b8d7f32b7d1f94d4af2858f9c8623b40ca0eae` |
| `offline-update/update-manifest.json` | `0f76af740467a1630be9aca7477df5f4a920fdfc879a9aa68a29807f5ecac634` |
| Compiled native EXE bytes | `17,057,530` |
| Offline ZIP bytes | `16,797,567` |
| Standalone builder + disposable PowerShell + actual frozen archive tests | `8 tests / 8 passed` |
| Actual 1.0.2-installed `Install-Taraz-V103.ps1` dry-run | `READY_FOR_CREATE_ONLY_1.0.3_INSTALL`, exit `0` |
| Post-build installed pointer | `1.0.2` |
| Post-build installed `versions\1.0.3` directory | Absent |

The real dry-run verified the existing installed binary, active-version
pointer, launcher, new backup acceptance report, and backup file hashes with
the full 181-file snapshot. It did not supply `-Apply`; no production install,
pointer update, GUI launch or financial write was performed.

The eighth test reads the actual PE/PYZ and every ZIP member independently:
the packed integration module contains `pendingTruncated` and
`recoveryTruncated`, and the embedded JavaScript includes both inbox
truncation signals, invoice designer navigation, and the contextual-help
trigger. To rerun all eight, set `TARAZ_V103_BUILD_REPORT` to the absolute
`build-report.json` path before the unittest command; without it, the
artifact-specific eighth test skips and seven contract tests run.

## New cold-backup witness

Prime reported that the existing independent cold-copy and readback verifier
finished a fresh source/snapshot check. The backup is stored at:

`D:\CoS-Test\MTR-REAL-UPGRADE-BACKUPS-20261110\taraz-v103-cold-20261111`

Evidence values from the current backup files and prime report:

| Field | Value |
| --- | --- |
| Snapshot file count | `181` |
| Total bytes | `124,011,875` |
| SQLite check count | `67` |
| Snapshot manifest SHA-256 | `8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d` |
| Independent acceptance report SHA-256 | `68bb6e26b9a9a10818e6752a7cc1475a3861c5f380f2021eb5c112a74cd7d2c9` |
| Reported installed before/after | `1.0.2` / `1.0.2` |

The build process does not inspect live finance data or treat the backup as
permission to activate. At install time, the operator must supply both
independently pinned SHA-256 values; the PowerShell preflight rehashes **every
backed-up file** and compares full file counts/bytes, proof metadata and
SQLite witness counts. The source of those two SHA-256 pins must be checked
separately from the backup directory. An absent or changed report fails shut.

## Operator-only side-by-side procedure

Run from the unpacked `offline-update` directory, in PowerShell 5.1. These
commands are **examples**; they are not executed by the build worker:

```powershell
$backup = 'D:\CoS-Test\MTR-REAL-UPGRADE-BACKUPS-20261110\taraz-v103-cold-20261111'
$manifestSha = '8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d'
$reportSha = '68bb6e26b9a9a10818e6752a7cc1475a3861c5f380f2021eb5c112a74cd7d2c9'

# Read-only preflight for the not-yet-installed version:
.\Install-Taraz-V103.ps1 -BackupRoot $backup -BackupManifestSha256 $manifestSha -BackupReportSha256 $reportSha

# Requires explicit release decision. Creates versions\1.0.3 only:
.\Install-Taraz-V103.ps1 -Apply -BackupRoot $backup -BackupManifestSha256 $manifestSha -BackupReportSha256 $reportSha

# Verify bytes before activation, still keeping pointer at 1.0.2:
.\Install-Taraz-V103.ps1 -VerifyExisting -BackupRoot $backup -BackupManifestSha256 $manifestSha -BackupReportSha256 $reportSha

# Read-only activation preflight:
.\Activate-Taraz-V103.ps1 -BackupRoot $backup -BackupManifestSha256 $manifestSha -BackupReportSha256 $reportSha

# Requires a separate explicit operator release decision:
.\Activate-Taraz-V103.ps1 -Apply -BackupRoot $backup -BackupManifestSha256 $manifestSha -BackupReportSha256 $reportSha
```

At every stage, the scripts require the exact installed 1.0.2 binary digest,
pointer, launcher contract, zero running Taraz processes, a clean backup
attestation, and an untouched 1.0.3 destination. Install uses a new directory
and `CreateNew` file write; activation alone atomically replaces the pointer
while retaining a separate 1.0.2 pointer backup. Neither script alters the
ledger or rewrites the previous executable.

## Required acceptance before operator activation

The candidate is unsigned and no installed GUI/accounting acceptance or
independent rollback execution has been recorded by this builder. Before
activation, check the release hashes against the candidate manifest, test
upgrade, startup, data readback, help, Madar inbox overflow and recovery,
invoices, and rollback in a disposable Windows user profile. Confirm real
WebView2 prerequisites on target devices. Operator approval of the exact
candidate is required for the actual installed version switch.

**Release status:** build and static verification results are recorded in the
generated `build-report.json`. A successful build establishes a native
candidate only; it is not a production installation or activation.
