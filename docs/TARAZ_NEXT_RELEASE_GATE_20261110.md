# Taraz next-version release gate | 2026-11-10

**Decision: NO_GO.** The newest QA EXE is not a complete, installable Taraz
upgrade. Neither an installer nor an installed-user acceptance test was
produced here. The gate is intentionally **read-only** and refuses to turn
claims in a user-supplied JSON manifest into verified release evidence.

## Repeatable bounded gate

From the isolated Taraz source directory:

```powershell
py -3.12 -B scripts/qa_taraz_next_version_release_gate_20261110.py
py -3.12 -B -m unittest -v tests.test_taraz_next_version_release_gate_20261110
```

The first command emits JSON with `decision=NO_GO`, reasons and provenance;
**exit code 2 is the expected blocked-release result**, not a successful
installer. The second command exercised **13/13 synthetic contract tests,
exit 0**. The script never executes Taraz packed bytecode, starts an EXE,
changes a profile, opens finance SQLite, reads user data, installs or updates
anything. Only the installed **program binary** is inspected read-only.
Untrusted file paths reject links/junctions; file/JSON counts and sizes are
bounded. A changed source snapshot, missing/tampered artifact, or unreadable
evidence fails closed.

Optional, **static only**, next-candidate validation:

```powershell
py -3.12 -B scripts/qa_taraz_next_version_release_gate_20261110.py --candidate-version 1.0.1
py -3.12 -B scripts/qa_taraz_next_version_release_gate_20261110.py --candidate-manifest D:\CoS-Test\example\candidate-manifest.json
```

The strict manifest is schema version 1 with exactly
`application="Taraz"`, `version`, `installerPath`, `installerSha256`,
and `installerBytes`. All supplied candidate files must be inside the
approved D: QA workspace. The version must be higher than installed 1.0.0
**and equal to package.json/package-lock.json**. The gate checks SHA-256,
byte length and PE header. A successful candidate check is explicitly only
`HASH_MATCH_DECLARED_VERSION_ONLY`: the version string is untrusted external
metadata, not embedded-version or publisher-signature proof. The overall
release decision **remains NO_GO**, even when a candidate manifest passes.

## Read-only evidence observed

| Surface | Observed evidence | Meaning |
| --- | --- | --- |
| Installed binary | `%LOCALAPPDATA%/Programs/Taraz/versions/1.0.0/Taraz.exe`; SHA-256 `de5005579039bd86890c1dca1f5f1d9c760e6c47579a42f649f80096f158e70c`; 16,968,567 bytes | SHA-pinned executable at installed version directory. No embedded Windows ProductVersion was found. Not executed |
| Installed packed review | `_atomic_json` pre-move durable intent **absent**; `_request_lock` **absent** | Older metadata-review implementation; not current-source parity |
| Source | package.json, lockfile root and lockfile version all `1.0.0` | **No version increase**; current same-version build must not overwrite installed app |
| Source updater | `TarazAPI.releaseCheck/releaseDownload/releaseInstall` raise `not configured`; desktop base class also raises | No trustworthy installed app updater |
| Installer script | package `dist:rc` refers to `scripts/build_integrated_v122.py` which is **absent** from this isolated source | Existing package command is not a validated buildable Taraz-specific installer |
| Latest independently checked QA | `D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110\qa-4ae81695ac39\qa-build-report.json`; SHA-256 `49ef093765801c56fc1b9e04eabe3d8370d7db7982de51a28ef996e7079dc7d6`; 17,033,670 bytes | `QA_BUNDLE_VERIFIED`; `qaOnly=true`, `installed=false`, `releaseReady=false`; source snapshot `3b39a7f55d30b98064f5df5ec913ef0e544f41dc46614cb7102d39c766166be7`, 128 inputs |
| Packaged UI | Sileo host and contextual help trigger present in **actual** compiled QA asset | Static packaged feature evidence, *not* installed GUI usability |
| Actual QA PYZ | `taraz_integration` present; `taraz_mtr_review_attestation_issuer`, `taraz_mtr_finance_witness_issuer`, `taraz_mtr_finance_binding_authority`, `taraz_mtr_peer_registry`, `taraz_mtr_peer_http` **all absent** | Source-only pilot adapters are not part of the bundled EXE; cannot claim complete peer/finance issuer |

The gate independently recomputes the installed/QA binary hashes and QA
builder-style source snapshot SHA, and reads PYZ names without loading or
executing packed modules. Previous synthetic browser QA covered Sileo and
help, but **not** a signed production installer, installed account/session,
real data migration, LAN/TLS peer identity or official booked finance receipt.

## Minimum upgrades before any future release GO

1. Version: choose and build a real Taraz next version strictly greater than
   `1.0.0`, with coherent package/lock/native/installer version evidence.
2. Installer/update path: implement and audit a **Taraz-specific**, create-only
   higher-version installer with pinned manifest, publisher signature,
   WebView2/prerequisites and secure upgrade initiation; do not reuse Madar
   update authority or the QA PyInstaller EXE as an installer.
3. Peer/finance: intentionally wire and package authenticated peer/issuer
   modules; verify role, provenance, nonfinancial review vs actual invoice
   posting, signed receipts and independent recovery/readback. No fake
   `officialFinanceReceiptVerified=true` flags.
4. Data safety: demonstrate independently verified create-only backups of
   all three affected data stores, compatible migration in disposable
   environments, exact readback, restart handling and independently exercised
   rollback. Do not overwrite installed 1.0.0 or real profile as a test.
5. Release acceptance: audit source freeze, sign/pin the exact installer,
   test version-specific upgrade and rollback on clean **disposable** Windows
   accounts, independently check installed GUI/auth/permissions and negative
   failures, then require a separate operator release approval.

The read-only tool deliberately never emits production `GO` without
independent installed/signed-upgrade and finance evidence. Its purpose is to
prevent a tested QA-only executable from being misrepresented as a complete
safe update.
