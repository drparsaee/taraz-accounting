# Taraz 1.0.3 P1: independent candidate acceptance, 2026-11-11

**Release decision: NO_GO.** Independent static verification, disposable offline installation/activation, isolated native WebView2 startup, and **the corrected, separately created operator rollback in a disposable install** all passed. The candidate is still unsigned and interactive GUI, financial acceptance, and operator approval remain unverified.

## Scope, current evidence and immutable pins

The independently checked candidate is at:

```text
D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\build-eb9d4f2ab076
```

| Item | Verified result | Boundary |
| --- | --- | --- |
| Installed baseline | `current-version.txt = 1.0.2`; `versions/1.0.2/Taraz.exe` SHA-256 `095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52`; normal versioned launcher contract present; 1.0.3 absent | Installer/pointer/user profiles were **never** modified |
| New compiled EXE | **17,057,530 bytes**, SHA-256 `e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c` | Binary read-only inspected, then launched only on private desktop |
| Actual Windows PE resource | Fixed FileVersion `1.0.3.0`, from independent Windows `VerQueryValueW` | Not only build-report metadata |
| Frozen PYZ | Release module assigns `APP_VERSION = "1.0.3"` and `QA_ONLY = False`; native Madar APIs and WebView2 forwarder, template store and reader modules found | Static marshal/PyInstaller inspection; no frozen module execution during artifact verification |
| P0 pending visibility | `taraz_integration.list_requests` frozen code contains `pendingTruncated` return key and bounded 201/100 scan constants; shipped JS contains `pendingTruncated` and the actual incomplete-inbox warning | Proves code and UI are bundled, **not** end-to-end review workflow behavior |
| Context help | Frozen JS contains `madar` and `invoiceDesign` keys **and** their unique help caution sentences | Content embedded; no interactive click testing |
| Source freeze | Runtime source fingerprint `a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279`; **131** inventoried inputs; 128 unstaged source files rehashed against package snapshot | `package.json`, lock and native entrypoint are version-staged, checked against their separately pinned SHA |
| Offline ZIP | SHA-256 `4e46df72c488f824b9a5eb9683b8d7f32b7d1f94d4af2858f9c8623b40ca0eae`; all **7** ZIP entries independently streamed/rehashed against offline files | ZIP includes EXE, 2 PowerShell scripts, manifest, source manifest and staged package/lock |
| Update manifest | SHA-256 `0f76af740467a1630be9aca7477df5f4a920fdfc879a9aa68a29807f5ecac634` | `productionCandidate=true`, `qaOnly=false`, `unsigned=true`, `installed=false`, `activationApprovalGranted=false` were **claims at packaging time** |
| Installed-v102 cold backup for v103 | Manifest SHA-256 `8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d`; report SHA-256 `68bb6e26b9a9a10818e6752a7cc1475a3861c5f380f2021eb5c112a74cd7d2c9` | Fresh evidence records `installedBefore=installedAfter=1.0.2` |
| Backup file readback | All **181 / 181** stored file hashes matched, **124,011,875** bytes, no extra/missing entries | Report claims 67 SQLite checks; this audit **did not** rerun SQLite `integrity_check` |

All checks were run locally on Windows. The baseline executable, real version pointer, bridge data and backups were read-only. Neither production networking nor an installed application update was triggered.

## Actual disposable installer exercise

Run with `--disposable` after static evidence passes. The script creates a completely separate disposable `LOCALAPPDATA` and copies the pinned v1.0.2 binary, versioned launcher, pointer and independently verified v1.0.3 payload there. Packaged PowerShell scripts can run **only** if their hashes equal the reviewed script pair:

- Installer SHA-256 `fd5cb5ddc024370cce21388c8f906bb6d46e849b628351fd65cd18cadefbb08a`
- Activator SHA-256 `623f89e19d1e640767cf4bec6c1a2b9304a7513f4a2658faf3b67df7a3b825d5`

**Observed: 4 of 4 PowerShell stages passed** with exit 0 and expected marker:

1. Install script preflight: `READY_FOR_CREATE_ONLY_1.0.3_INSTALL`.
2. Install script `-Apply`: `INSTALLED_SIDE_BY_SIDE_1.0.3_POINTER_REMAINS_1.0.2`.
3. Activate script preflight: `READY_TO_ACTIVATE_1.0.3_OLD_VERSION_RETAINED`.
4. Activate script `-Apply`: `ACTIVATED_1.0.3_VERSION_1.0.2_RETAINED`.

The new binary SHA matched after copying; the old binary remained pinned; the pointer was `1.0.2` after side-by-side installation and `1.0.3` after activation. The isolated harness subsequently restored the disposable pointer to `1.0.2` and verified the old binary hash. Status: `DISPOSABLE_INSTALL_ACTIVATE_AND_MANUAL_POINTER_RESTORE_PASSED`.

**Limit:** the ZIP does not contain a rollback script. A separately generated, pinned operator rollback script was later independently tested as described below. Its success in a disposable install does not establish production financial recovery.

## Actual private Windows desktop GUI smoke

The independent harness copied all 181 previously pinned backup files into a new private `qa` profile tree, then launched the exact v1.0.3 candidate EXE via `CreateProcessW` **suspended**, assigned it to a new kill-on-close Windows Job Object, and resumed it on a newly created Win32 desktop. The existing private desktop helper in `D:\CoS-Test\ArtiosMamad\qa_compiled_gui_v051.py` was reused **only for Windows desktop/job/process containment**; its app-specific tests and release verification were not reused.

**Final observed status: `PRIVATE_DESKTOP_WEBVIEW2_SMOKE_PASSED`.** The private desktop had a job-owned window titled `تراز | حسابداری`. The application's own isolated QA report stated `loaded=true` and `accountingBridge="function"`; `taskBridgeExposed` was not a function. No user-desktop input or global window actions occurred. Job and private desktop handles were cleaned up and the cloned profile was removed afterwards.

During an initial iteration, the harness got `QA directory must be an absolute QA-only path` from the compiled entrypoint because its synthetic path lacked the exact `qa` directory segment. The harness-only path was corrected; no frozen code or production installation was altered. A separate Windows console encoding issue affecting reporting of Persian window titles was addressed by ASCII-escaped JSON. The final private run passed.

**Limit:** a loaded private WebView2 does not prove login, the interactive Madar flow, role restrictions, accounting ledger mutations or authorized financial posting. No CDP interaction, finance action or data migration was attempted here.

## Separate operator rollback: defect detected and corrected independently

Worker29 created an additional, standalone operator rollback artifact **outside the original v1.0.3 ZIP**. The original artifact was found defective, and a new immutable artifact was generated.

```text
D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\rollback-gate-f20444872b56
```

The **first** supplied `Rollback-Taraz-V103-To-V102.ps1` was **7,326 bytes**, SHA-256 `0e84daa8618b60c6493822ad72aa3117e424fc5e2d4ce69f385f5bae5624f105`; its manifest SHA-256 is `3cb0ccfe2ec6ffaf609b43aa2f3bce05a8fcb475bf2e67cce65fa9e81809be57`. Independent source review found intended preconditions: old/new PE version and EXE hashes, pointer backup, reparse-point checks, process inactivity, ACL rights, and atomic pointer replacement.

**Actual independent `--disposable-rollback` result: FAILED at preflight**, before any pointer mutation. The PowerShell file contains an invalid .NET regular expression for local drive roots on both lines 10 and 87:

```powershell
# Original, invalid: single literal backslash escapes the regex terminator
if($env:LOCALAPPDATA -notmatch '^[a-zA-Z]:\') { ... }
```

PowerShell threw `ArgumentException` at line 87. In PowerShell single-quoted literals, the intended regular expression needs **two literal backslashes**, i.e. `'^[a-zA-Z]:\\'`. The audit now rejects the original script at the static gate even though its published SHA is internally consistent. **No real pointer or ledger was changed by the failing test.**

The **corrected** artifact is:

```text
D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\rollback-gate-dad44a3c6367
```

- Fixed PowerShell script SHA-256: `34b15cfea1e3407a73888ac17fcfc353158f6f329d940d0f58159eea7230f334`
- Fixed `rollback-gate-manifest.json` SHA-256: `030d6402cd3428fb0902767654e7d3513cb7327843b1f93421726ea28565372b`

The **independent static gate passed** for the corrected artifact. The actual `--disposable-rollback` execution also **PASSED**: initial PowerShell preflight returned exit 0 with no file modifications; `-Apply` returned exit 0 and atomically changed the synthetic pointer from `1.0.3` to `1.0.2`. Its dedicated rollback backup contains `1.0.3`; the original activation backup remains `1.0.2`; both pinned EXEs and an independent synthetic finance-file sentinel had unchanged SHA-256. A second `-Apply` was refused. This exercised actual PowerShell and real binary copies in a fresh disposable `LOCALAPPDATA`; it did not operate on production profiles or demonstrate recovery of a real financial ledger.

## Reproduce

From `D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

```powershell
py -3.12 -B -m unittest -v tests.test_taraz_v103_independent_acceptance_20261111
py -3.12 -B scripts/qa_taraz_v103_independent_acceptance_20261111.py
py -3.12 -B scripts/qa_taraz_v103_independent_acceptance_20261111.py --disposable
py -3.12 -B scripts/qa_taraz_v103_independent_acceptance_20261111.py --private-gui
py -3.12 -B scripts/qa_taraz_v103_independent_acceptance_20261111.py --disposable-rollback
```

The CLI always prints deterministic JSON including `decision=NO_GO` and intentionally returns exit code **2**, even if the available static/disposable/private checks pass. It automatically selects one completed build under the v1.0.3 candidate root. If later builds appear, pass `--build <exact completed build directory>` explicitly.

For the final independent combined run, all of the following were observed together:

```powershell
py -3.12 -B scripts/qa_taraz_v103_independent_acceptance_20261111.py --disposable --disposable-rollback --private-gui
```

| Gate | Final observed status |
| --- | --- |
| Candidate | `ARTIFACT_PINS_PE_PYZ_ZIP_VERIFIED` |
| Fresh backup | `FRESH_V102_BACKUP_BYTES_MATCH` |
| Rollback static/pins | `OPERATOR_ROLLBACK_STATIC_PIN_AND_GUARDS_VERIFIED` |
| Upgrade in temporary files | `DISPOSABLE_INSTALL_ACTIVATE_AND_MANUAL_POINTER_RESTORE_PASSED` |
| Corrected rollback in temporary files | `DISPOSABLE_OPERATOR_ROLLBACK_APPLY_PASSED` |
| Native private desktop | `PRIVATE_DESKTOP_WEBVIEW2_SMOKE_PASSED` |
| Production approval | **`NO_GO`** |

The separate unit test command completed **14 tests, 0 failures**. Tests use synthetic temporary binaries, source snapshots, ZIPs and backups; they deliberately tamper with frozen source, PE version result, PYZ inspection result, ZIP duplicate entries, versions, copied backup data and invalid Windows path regex. Test fixtures never execute an installer or access real profiles. Real PowerShell and GUI checks are explicitly opt-in CLI options with isolated data roots.

## Remaining release approval gates

1. Test **real GUI login, contextual help clicks, Madar inbox truncation handling, review/recovery actions and role restrictions** using a fully controlled desktop and synthetic/private account state, including negative permissions and durable restart handling.
2. Test **accounting and migration invariants** across disposable upgrade and failure/rollback, with separately authorized financial acceptance. A preview or suggested Madar record does not constitute a posted financial document.
3. **Keep the corrected standalone operator rollback pinned** and verify its integration with the final installation process, including recovery of interrupted migrations and real accounting data in a disposable but representative environment. The old `rollback-gate-f20444872b56` remains rejected.
4. Resolve **publisher signature / unsigned offline ZIP policy**, confirm immutable final source/installer pins and obtain explicit operator release approval before any production installation/activation.

**No production Taraz EXE, pointer, profile, accounting data, Madar host/service or installer was changed.** These checks authorize no deployment.
