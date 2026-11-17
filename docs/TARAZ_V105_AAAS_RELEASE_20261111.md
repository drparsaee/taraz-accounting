# Taraz 1.0.5 AaaS offline release candidate

## Purpose and scope

Build a genuine non-QA Windows Taraz v1.0.5 EXE from the **post-integration frozen**
runtime source containing the order workspace and beginner one-screen invoice.
Keep the installed v1.0.4 EXE, user data and accounts unchanged during compilation.
The only permitted repository changes belong to the new builder and tests.

## Verified installed baseline

- Active version at preparation: `1.0.4`
- Installed EXE SHA-256: `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce`
- Launcher SHA-256: `93a1b809d3499a585bb9e4fc8c232f038a3d950a467485305aa1e79ce28d2b21`
- Pointer SHA-256: `eb8d72a2c4783965876f89d494d6ecdd3502c814e0229d50cea66eb65169856d`
- Launcher keeps the versioned contract `versions\%TARAZ_VERSION%\Taraz.exe`.

## Build and installation contract

1. Prime confirms worker27's finished source and freezes its exact runtime
   inventory, computed read-only with `py -3.12 -B scripts/build_taraz_v105_aaas_20261111.py --fingerprint`.
2. Build with the resulting approved digest using
   `py -3.12 -B scripts/build_taraz_v105_aaas_20261111.py --build --freeze-sha <sha256>`.
   The script snapshots only the named source inputs into a unique create-only
   `taraz-v1.0.5-aaas\build-<id>` folder, rechecks live source bytes after
   native compilation, and requires unchanged installed baseline.
3. Inspect `build-report.json`. The only successful build status is
   `V105_AAAS_NON_QA_BUILT_NOT_INSTALLED`. The offline ZIP contains exactly
   eight independently hash-checked files: EXE, versioned npm package and lock,
   source hashes, manifest, install, activation, and rollback PowerShell scripts.
4. The default install script checks the real EXE/pointer/launcher hashes,
   process state, payload digest and manifest. With `-Apply`, it creates only
   `%LOCALAPPDATA%\Programs\Taraz\versions\1.0.5\Taraz.exe`. The pointer
   remains on `1.0.4`.
5. The independent activation script changes the pointer atomically only after
   checking the installed 1.0.5 SHA and saving the exact prior pointer. The
   rollback script restores the saved 1.0.4 pointer atomically and preserves
   both binaries. Repeating rollback makes no change.

No script edits accounting data or performs migration. Installed activation
belongs to prime after independent review.

## Verification levels

The builder inspects the *actual compiled executable* and checks PE version
`1.0.5.0`, release PYZ `APP_VERSION=1.0.5` with `QA_ONLY=False`, frozen
`TarazAPI.tarazOrderList/tarazOrderCommand`, the WebView2 allowlist, the
frozen `taraz_order_store` methods, and byte-for-byte parity of every embedded
HTML/JS/CSS/font asset with Vite output. It also checks compiled UI tokens for
orders and the beginner invoice.

The disposable Windows test suite exercises install, activation, rollback,
repeat install refusal, repeat rollback idempotence, corrupted payload, old
binary and activation backup. These are installer-path tests on synthetic
files; they do not constitute an authenticated real-data accounting or final
native GUI acceptance test. Actual EXE and ZIP hashes must be supplied from
the completed compilation, never inferred before it exists.

Preparation verification: `py -3.12 -B -m unittest
tests.test_taraz_v105_aaas_20261111 -q` completed with 7 passes and one
expected skipped check for an executable that cannot exist until prime
authorizes the frozen-source build. Synthetic rollback preserved both EXE
byte hashes and restored the original pointer; no real user profile was
modified by these tests.

## Completed immutable native build (2026-11-11)

- Approved frozen runtime source: 136 files, SHA-256
  `74b7e92295c167e1f9f8bf2ff8f16879e72ea425a8d293b7247fdccbeb0a10fb`.
  Rehashed with identical digest after build.
- Create-only output directory:
  `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.5-aaas\build-a605e1eb5052`
- Real PE 1.0.5.0, PYZ 1.0.5, `QA_ONLY=False`, `BUILD_CHANNEL=offline-production-candidate`.
- Actual native EXE `binary\Taraz.exe` SHA-256
  `59b1d32197ebbd3b1bc34f8ce4cc2a652d84fa45fa9d091379ea839e38bdf259`.
- `Taraz-v1.0.5-AAAS-OFFLINE-UPDATE.zip` SHA-256
  `709e2493a052bf941b8605cba2cb23eef620d6e2a8a9026f7f1a8bc7e048e922`.
- `offline-update\update-manifest.json` SHA-256
  `4095a874c42ce08e4615adc36d9b7bccdd348f45c4698e9cb6073aa23c362489`.
- All 8 ZIP members were independently SHA-checked; all embedded Vite
  assets matched packed EXE assets byte-for-byte. Frozen native order APIs,
  WebView2 forwarding, `taraz_order_store` PYZ, order/invoice JS and CSS
  witnesses all passed.
- Final tests:
  `py -3.12 -B -m unittest tests.test_taraz_v105_aaas_20261111 -v`
  **8/8 PASS, zero skips**. This includes Windows disposable
  install/activation/rollback, repeat-rollback and tamper-denial cases.
- All three compiled PowerShell scripts parsed with **zero errors**.
- Read-only production install preflight **blocked as designed** because the
  actual installed Taraz 1.0.4 process was running. The active pointer
  remained 1.0.4, the installed 1.0.4 EXE hash stayed pinned, and no real
  `versions\1.0.5` directory existed at final check.

This result is **a built, internally inspected, noninstalled release
candidate**, not evidence of end-to-end real user GUI acceptance or
permission to activate without the prime's own preflight.
