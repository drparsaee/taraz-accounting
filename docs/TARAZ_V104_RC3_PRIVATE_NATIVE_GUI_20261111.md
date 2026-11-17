# Taraz v1.0.4 P1 RC3: private non-input Windows GUI native startup acceptance

**Date:** 2026-11-11  
**Observed scope verdict:** `PASS_REAL_RC3_PRIVATE_NATIVE_STARTUP_VIEW_ONLY`  
**Full interactive GUI / finance / network / release approval:** **NOT VERIFIED**

## Exact artifact and native launch evidence

The **real non-QA Windows EXE was launched**, not an in-browser Vite stand-in.
The launcher used a newly created `WinSta0\TarazNativeQA_<random>` Win32
**non-input private desktop** with `CreateDesktopW` and
`CreateProcessW(lpDesktop=...)`. It **never called `SwitchDesktop`,
`SetForegroundWindow`, `SendInput`, cursor, keyboard, or global UI methods**.
The EXE was launched directly from its detached build folder, never installed.

| Gate | Observed result |
| --- | --- |
| Exact EXE | `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-0bde36e11d99\binary\Taraz.exe` |
| Actual executable SHA-256 | `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` |
| Build/source | RC3, `PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED`, source fingerprint `e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de` |
| PE / PYZ | Actual PE `1.0.4.0`; actual `taraz_release_version` compiled PYZ constant `APP_VERSION='1.0.4'`, `QA_ONLY=False` |
| Embedded JS hash | PyInstaller CArchive JS SHA-256 `3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9` |
| Installed original pointer | `1.0.2` before **and after**; original installed version, launcher, pointer hashes unchanged |
| Cold backup | All **181** entries of pinned cold backup rehashed before; all 181 still matched afterward |
| Isolated data | Cold backup cloned into new **ACL-restricted private profile**, 181 files individually copied/verified; `APPDATA`, `LOCALAPPDATA`, `TEMP`, `TMP`, `USERPROFILE`, WebView2 and PyInstaller paths redirected under disposable QA runtime |
| Source data caution | The private profile is **synthetic as an isolated test environment, but its data are a copy of the authentic offline backup**, not fabricated empty accounts. This is intentional because the application must initialize a real ledger view. No financial content was emitted in this report. |
| Private desktop | Created: **true**, no original input desktop switch |
| Real compiled EXE launched | **true** |
| Real native private Taraz window | **true**, enumerated only on the private desktop and matched test-owned PIDs |
| Owned WebView2 processes | **6** observed |
| App-native startup report | `loaded=true`, `accountingBridgePresent=true`, `taskBridgeNotExposed=true` |
| Private UIAutomation | `READ_ONLY_PRIVATE_UIA_COMPLETED`; **ownedWindow=true**, **privateOwnerMatch=true**, **startupControlsObserved=true**, one named control matched |
| UIA interactions | **Zero**; deliberate read-only observation, no click/InvokePattern/default action. No Madar tab/service read, no designer save, no financial command. |
| Copy-only ledger | Private ledger's `(revision,digest)` from read-only immutable SQLite before/after **identical**; neither value printed |
| Existing user Taraz processes | **0 before**; no original Taraz process PID disturbed |
| Original visible user windows | **31 before and 31 after; all 31 existing HWND/PID pairs remained** |
| Owned process cleanup | **8** owned PIDs captured with creation time; **0 left alive**; unrelated PID targeted: **false** |
| Actual candidate binary / backup postflight | Both unchanged |

The actual generated evidence file (created in the separate QA-only run
directory, with no production artifact overwrite) is:

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v104-rc3-private-native-gui-qa\qa-rc3-5964c9838e2e\native-result.json`

The evidence report has `status =
PASS_REAL_RC3_PRIVATE_NATIVE_STARTUP_VIEW_ONLY` and the parent execution
returned **exit code 0**.

## Reproduction and test validation

Only **three new owner-scoped code/report files** were authored in the Taraz
source checkout. Neither frozen v1.0.3 harness, the RC3 EXE/builder/source,
nor any installed software was edited:

- `scripts/qa_taraz_v104_rc3_private_native_gui_20261111.py`
- `tests/test_taraz_v104_rc3_private_native_gui_20261111.py`
- `docs/TARAZ_V104_RC3_PRIVATE_NATIVE_GUI_20261111.md` (this report)

Run from:
`D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`

```powershell
py -3.12 -B -m unittest discover -s tests -p test_taraz_v104_rc3_private_native_gui_20261111.py -v
py -3.12 -B scripts/qa_taraz_v104_rc3_private_native_gui_20261111.py --static-only
py -3.12 -B scripts/qa_taraz_v104_rc3_private_native_gui_20261111.py --run-private-native
```

**Actual results:**

```text
Ran 10 tests in 3.528s
OK

{"status":"STATIC_ONLY_NATIVE_NOT_LAUNCHED",
 "exeSha256":"9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce",
 "installedVersion":"1.0.2","coldBackupFilesVerified":181}

{"status":"PASS_REAL_RC3_PRIVATE_NATIVE_STARTUP_VIEW_ONLY",
 "realNonQaExeLaunched":true,
 "nativeWebViewLoaded":true,
 "noUserWindowInterference":true,
 "ownedProcessesLeftAlive":0}
```

Each command returned **exit 0** in its own observed execution. The unit
tests include exact binary/backup pins, tampered EXE rejection, an intentionally
blocked preflight that creates **no desktop**, strict new-file-only scope,
read-only UIA no-input tests, synthetic environment isolation, and explicit
`--run-private-native` opt-in. Static-only mode does not launch an EXE or
claim native GUI acceptance.

## Security constraints and important limitations

The harness **reuses the existing v1.0.3 implementation design**, including
its verified `PrivateDesktop`, individual offline backup file clone and
re-hash, and secure DACL setup. The referenced modules were imported
read-only. The test executable is the SHA-pinned **RC3**, not legacy v1.0.3.

An external Windows PowerShell 5.1 helper was spawned **only on the private
desktop**, with UIAutomation looking up **owned** windows and an allowlist of
labels. It does not invoke controls, post invoices, toggle Madar consent,
read Madar data, or call the Madar service. All original desktop observations
are read-only `EnumWindows`, used to establish noninterference; there was no
user-facing foreground, mouse, keyboard, registry, service or network-setting
change.

WebView2 had an isolated user profile and QA environment with background
networking disabled and a deliberately unavailable local proxy
`127.0.0.1:9`. **Actual outbound network packets were not independently
captured**, so a categorical claim that the launched application made zero
network attempts would be unsupported. No integration or external request was
intentionally triggered by the harness.

**Not proven by this native startup test:** actual DOM text beyond reported
startup markers, interactive navigation, Madar integration behavior, opening
and closing contextual help, invoice print-designer interaction, Sileo toast,
real financial transaction safety, install/upgrade/rollback, WebView2
network isolation or production behavior outside this disposable profile.
The prior separate **RC3 EXE-extracted JavaScript** Edge suite passed 15/15,
but that separate result is not a substitute for native interactive GUI
tests. Neither of these two scoped tests authorizes production deployment.

**Release interpretation:** the compiled RC3 native EXE **really launched**
on an isolated private Win32 desktop, opened its own native window, started
WebView2 and exposed accounting startup markers; those facts and cleanup
are proven within the stated scope. **Full GUI acceptance remains incomplete**
because no interactions were performed. It is not evidence of a GUI failure.
