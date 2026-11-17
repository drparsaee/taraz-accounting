# Taraz 1.0.1 offline Windows update candidate, 2026-11-10

Production-candidate EXE compiled from frozen current Taraz source after the
invoice designer navigation and native template persistence updates.
No installed EXE, finance profile, ledger, launcher or version pointer was edited
by this builder.

## Verified outputs

- Folder: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.1-production-candidate\build-057caff5080e`
- Native EXE: `binary\Taraz.exe`
- Native EXE SHA-256: `5b5a550f3b95cda8352f757cd9e61d44a62531e0e4dfe0fc6d586a0d6a452d4b`
- Offline ZIP: `Taraz-v1.0.1-OFFLINE-SIDE-BY-SIDE-UPDATE.zip`
- ZIP SHA-256: `883d4bc945632abecb148982b0615f782d0d961baa7972bde3b85433df324410`
- Package manifest SHA-256: `23b185accb2b2e58bb6191ad13872a7479712e6c0c1e4da04439561610b597e2`
- Version: package, lock, embedded release PYZ module, PE version `1.0.1.0`.
- Source: 128 runtime inputs fingerprinted; no source drift during compilation.
- UI: 15 packaged assets match the compiled Vite dist bytes; the print designer
  navigation, template save/default, and Sileo markers are present.
- Native: accounting template persistence module and CRUD methods verified in
  frozen Python PYZ, with no QA-only entry gate. Default data root remains
  `%APPDATA%\Taraz`.
- Backup witness: independent backup manifest and copied 178 files / 124011301
  bytes / 67 SQLite integrity readbacks verified. Prior `1.0.0` EXE unchanged.

## Installation stages

The folder `offline-update` contains the non-QA binary, frozen manifest,
source hashes and two separate PowerShell scripts:

1. Execute `Install-Taraz-V101.ps1` without `-Apply` to preflight the
   current version, original EXE SHA-256, process state, package SHA-256 and
   independently copied backup. This was run against the actual machine and
   returned `READY_FOR_CREATE_ONLY_SIDE_BY_SIDE_INSTALL` exit 0.
2. Execute the same script with `-Apply` to create only
   `%LOCALAPPDATA%\Programs\Taraz\versions\1.0.1\Taraz.exe`.
   It refuses an already-existing destination and does not change the
   `current-version.txt` pointer. This stage has **not** been run by worker23.
3. Run independent installed-binary/UI login/template tests, then execute
   `Activate-Taraz-V101.ps1` first without `-Apply` and then with `-Apply`
   to perform an atomic `1.0.0` to `1.0.1` pointer switch. It retains the old
   EXE and writes a separate backup of the pointer. This stage has **not** been
   run by worker23.

## Tests and boundaries

5/5 new Python unit tests pass. Both generated PowerShell scripts parse with
zero syntax errors. Offline ZIP readback passes. Real production execution,
WebView2 GUI startup, installed-version authentication and user invoice form
interaction require separate post-install checks. The release is unsigned and
does not claim any unverified peer finance posting. All existing accounting
records stay governed by the current Taraz native authorization rules.
