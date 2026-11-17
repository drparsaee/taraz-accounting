# Taraz: offline v1.0.1-target review candidate (2026-11-10)

## Verdict

**A ZIP review package exists and was verified. A true v1.0.1 installer does
not exist.** The user authorized creation of an offline update *package*,
**not installation**. The only frozen, hash-pinned executable available is
the newer QA-only build compiled from **Taraz source `1.0.0`**. The output
directory's `taraz-v1.0.1` and ZIP target label do not upgrade the PE,
installed version, update protocol or data schema. The PE's embedded
v1.0.1 version was not verified. **Installation and release: NO_GO.**

## Actual create-only outputs

Folder: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.1`

| Artifact | Verified data |
| --- | --- |
| `Taraz-target-v1.0.1-QA-binary-from-v1.0.0-OFFLINE-REVIEW-ONLY.zip` | **17,036,928 bytes**, SHA-256 `40f03472919e964edee26a1406d8092f53d7420ddead4341f18b2f176f06bcda` |
| `offline-candidate-manifest.json` | Separate ZIP SHA-256/byte count; explicitly `safeToInstall=false`, `realInstallerCreated=false`, `releaseDecision=NO_GO` |
| ZIP `payload/Taraz-MTR-QA-4ae81695ac39.exe` | Unmodified QA-only EXE; **17,033,670 bytes**, SHA-256 `49ef093765801c56fc1b9e04eabe3d8370d7db7982de51a28ef996e7079dc7d6` |
| ZIP `manifest.json` | Version label `1.0.1`; source package version `1.0.0`; embedded executable version unverified; backend updater unavailable; known packed peer/finance modules listed |
| ZIP `CHECK_BEFORE_ANY_INSTALL.md`, `INSTALL_BLOCKED.md`, `ROLLBACK_PRECONDITIONS.md` | Read-only checking instructions, explicit prohibition on executing as installer, required independent backups/migration/rollback gates |

The SHA-256 manifest is **integrity evidence, not a digital signature**
or publisher identity. Do not use a candidate version label as a version
resource. No install launcher, update API change, rollback executable or
profile/data migration is included.

## Measured inputs and boundaries

- Installed program under `%LOCALAPPDATA%/Programs/Taraz/versions/1.0.0/Taraz.exe`
  was **only read** for hash/size. SHA-256:
  `de5005579039bd86890c1dca1f5f1d9c760e6c47579a42f649f80096f158e70c`,
  16,968,567 bytes. No personal `APPDATA/Taraz` files or ledger accessed.
- The QA report and executable were checked against independent SHA pins;
  QA status `QA_BUNDLE_VERIFIED`, `qaOnly=true`, `releaseReady=false`,
  `installed=false`. Source frozen 128-input snapshot SHA-256:
  `3b39a7f55d30b98064f5df5ec913ef0e544f41dc46614cb7102d39c766166be7`.
  Current source snapshot was independently recomputed and matched.
- Source `package.json`, `package-lock.json` and lock root still state
  **`1.0.0`**; the Taraz updater methods explicitly raise
  `not configured`, and `npm run dist:rc` references the missing
  `scripts/build_integrated_v122.py`.
- The QA EXE's real packed `PYZ.pyz` includes metadata `taraz_integration`
  but does **not** include the five source-only Taraz peer/finance/attestation
  modules. No authenticated financial receipt is demonstrated.

## Re-run the safe QA only

```powershell
# From D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109
py -3.12 -B -m unittest -v tests.test_taraz_v101_update_package_20261110
py -3.12 -B scripts/qa_taraz_v101_update_package_20261110.py --verify 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.1\Taraz-target-v1.0.1-QA-binary-from-v1.0.0-OFFLINE-REVIEW-ONLY.zip'
Get-FileHash -Algorithm SHA256 -LiteralPath 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.1\Taraz-target-v1.0.1-QA-binary-from-v1.0.0-OFFLINE-REVIEW-ONLY.zip'
```

Observed: **11/11 synthetic tests passed**, archive creation exit 0,
internal ZIP verification passed, read-only hash verification performed.
Calling the packager again refuses to overwrite existing output.
These tests intentionally do not install, launch, sign or access user data.
No claim is made for a production Windows installer, publisher validation,
power-loss-safe migration, real LAN connection or finance booking.

## Required before a genuine offline 1.0.1 update

1. Freeze and build a genuinely version-bumped executable from
   `1.0.1` source/lock and independently inspect embedded version.
2. Create and sign an actual Taraz-specific offline installer with
   version checks, WebView2 prerequisites and safe update/rollback protocol.
3. Validate create-only, independently readable backups of **all three**
   data stores and run migration/rollback on disposable accounts; never
   overwrite the existing installed `1.0.0` as part of QA.
4. Integrate and test the missing attested peer/finance issuer features
   and prove a genuine authorized financial receipt, distinct from
   nonfinancial UI metadata review.
5. Verify source/EXE/installer hashes, real post-upgrade GUI and login,
   negative failure cases, and obtain release/installation approval.

The present ZIP is a **review and transport candidate**, not an
installer and not evidence that an update has been installed.
