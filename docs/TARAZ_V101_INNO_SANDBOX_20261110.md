# Taraz 1.0.1 Inno Setup: isolated QA candidate

**Result:** `COMPILED_QA_SETUP_NOT_EXECUTED`. This package is for binary/update
workflow review only. It is not a release or an approved update to installed
Taraz 1.0.0. It was never installed or launched by the build.

## Artifact

- Run folder: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.1-inno-qa\compile-45ac591be1f7`
- Inno EXE: `inno\Taraz-v1.0.1-SANDBOX-QA-COMPILE-ONLY.exe`
- Inno EXE SHA-256: `8f12cbd6e3d4d0896732c0627179eec285b7ef52b1d680f663dc4e788c6cb822`
- Inno EXE size: 18,771,586 bytes
- Rebuilt Taraz EXE: `binary\Taraz-v1.0.1-SANDBOX-QA.exe`
- Rebuilt Taraz EXE SHA-256: `4a409be0b464b93f593b39e527162db43ffc3dbadfc15a2e0fde3a511326bf16`
- Rebuilt Taraz PE version: `1.0.1.0`; Inno Setup ProductVersion: `1.0.1`
- Full evidence: `compile-report.json`, `sandbox-qa-manifest.json`, `vite.log`,
  `pyinstaller.log`, `inno-compile.log`, and generated `.iss` in the run folder.

## Provenance and safeguards

The input is the already audited Taraz QA snapshot `qa-4ae81695ac39`, whose
source tree hash and original EXE SHA are independently checked against the QA
build report before copying. The copied `package.json` and `package-lock.json`
were both changed from `1.0.0` to `1.0.1` in the disposable stage. A new native
version module and an executable launch gate were injected only in this stage.
The UI and Python bundle were freshly compiled from this versioned snapshot.
PyInstaller stamped Windows PE version `1.0.1.0` and the resulting archive was
inspected for the version module and actual React asset presence.

The Inno installer has a QA-specific AppId, `PrivilegesRequired=lowest`,
`Uninstallable=no`, no shortcuts, no `[Run]`/`[Registry]` actions, and a fixed
side-by-side destination under its unique output run. Its compiled Pascal
`PrepareToInstall` check refuses a redirected installation directory. The
Taraz EXE itself refuses launch unless its executable path matches that
disposable destination and the QA mode and all profile/temp/data variables
point into an explicit sandbox. No real accounting/profile path is used by
the builder.

## Verified scope and limits

- Inno compiler exited successfully and logged embedded Taraz binary and manifest.
- Five focused Python unit/negative/readback tests passed (including denial of
  non-QA synthetic launches).
- Frozen executable archive inspection found the real Sileo notification host,
  per-section contextual help, integration inbox methods, durable review, and
  HTML bridge forwarding.
- WebView2 runtime was observed in the machine's standard installed location,
  but **is not bundled**. No portability claim is made for machines without it.
- Installer execution, GUI startup, account authorization, migration, official
  financial receipt, rollback and production upgrade were **not tested**.
  Publisher signing is absent. Release gate stays **NO_GO**.

Builder: `py -3.12 -B scripts/qa_taraz_v101_inno_sandbox_20261110.py`

Tests: `py -3.12 -B -m unittest discover -s tests -p test_taraz_v101_inno_sandbox_20261110.py -v`

Running the builder creates a new unique output directory and never overwrites
or launches an earlier build.
