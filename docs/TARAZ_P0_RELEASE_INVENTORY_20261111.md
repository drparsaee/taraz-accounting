# Taraz P0: installed 1.0.2, candidate and source reconciliation

**Date:** 2026-11-11. **Decision: `NO_GO` for the next release.** This is a read-only check of the **existing** v1.0.2 release evidence. It does not authorize a rebuild, installation, pointer switch or accounting-data migration.

## Directly observed evidence

| Subject | Evidence | Meaning / limit |
| --- | --- | --- |
| Installed version | `%LOCALAPPDATA%\Programs\Taraz\current-version.txt` reads `1.0.2`; launcher contains `versions\%TARAZ_VERSION%\Taraz.exe` | The current version pointer and versioned launcher were read; the application was **not** started. |
| Installed executable | `versions\1.0.2\Taraz.exe`: **17,056,486 bytes**, SHA-256 `095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52` | Byte-identical to the v1.0.2 candidate EXE in the existing build directory, per independently recomputed hashes. |
| Existing build | `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.2-madar-dashboard\build-544b6e6bf45b` | The existing build report is hashed to `bf362091527d43f2ad6a50ee9f08f6bdb6d46a70a1b7886e0cb5453da12ba68f`. Its `PRODUCTION_V102_CANDIDATE_BUILT_NOT_INSTALLED` status describes the **build-time** state; the installed pointer now shows v1.0.2. |
| Package parity | `Taraz-v1.0.2-MADAR-DASHBOARD-OFFLINE-UPDATE.zip`: SHA-256 `1499170aae4fa5cfe4876e7e604db8e20e3172c48722c645c4682210275749c6` | ZIP SHA and all **5** archived members were independently compared to the existing offline package (`Taraz.exe`, two PowerShell scripts, source SHA manifest, update manifest). This is an **offline ZIP plus PowerShell scripts**, not an independently validated signed Windows Setup executable. |
| Version claim | Existing candidate manifest reports `targetVersion=1.0.2`, `peVersion=1.0.2.0`, `qaOnly=false`, `unsigned=true` | PE version and QA/runtime flags originate in the build evidence, not from a new independent PE/PyInstaller runtime inspection. No publisher-signature or upgrade-run check was performed. |
| Frozen source | Build manifest hashes **131** runtime inputs; its fingerprint is `dd38e5bdb43aa6be0dc5f96abcd62d680a5239393fee88a385c202919f86c38e` | Current runtime sources **differ**: 128 identical, 3 modified, 0 added, 0 missing, at the observed snapshot. |
| Source baseline | Git `HEAD 653089bb99747ab1c909cfdb113d2d12bc36e47a`, detached, no remote shown by `git remote -v` | A source checkout exists; the working tree is still under parallel development. The audit observed **122** Git status entries at that instant. This count is dynamic, including new worker files. |
| Source versions | `package.json`, `package-lock.json` and lockfile root: all **1.0.0**; source `package.json` `dist:rc` points to absent `scripts/build_integrated_v122.py` | Normal distribution script is not usable from this detached checkout. The v1.0.2 builder instead staged `1.0.2` in its separate source snapshot. Its own guard expects an installed **1.0.1** baseline and rejects an existing 1.0.2 directory. |
| Cold backup | `D:\CoS-Test\MTR-REAL-UPGRADE-BACKUPS-20261110\taraz-v102-cold-20261111` | Independent read-only SHA-256 rehash matched **all 181 copied files**, **124,011,875 total bytes**, and manifest/report SHA references. The backup witness reports 67 SQLite checks and readback: **those 67 SQLite checks were not rerun in this audit**. Its recorded installed before/after is **1.0.1**, so it is not a fresh backup from the currently installed 1.0.2. |

The **three changed runtime inputs** against the frozen v1.0.2 candidate are `src/standalone_main.jsx`, `src/taraz_madar_dashboard.jsx` and `src/taraz_settings.jsx`. The observed current source fingerprint was `e6089097381fbef0768ff8651bf3ab08b8fc4a432a1d13df4697373b5518f6eb`; it may change as parallel workers edit. The build tools in `scripts/` were deliberately outside the 131-file runtime-source snapshot. The audit records their current individual SHA values, but does not infer those scripts were frozen or proven build-reproducible.

## Reproduce without changing the installed app

From `D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

```powershell
py -3.12 -B -m unittest -v tests.test_taraz_p0_release_inventory_20261111
py -3.12 -B scripts/taraz_p0_release_inventory_20261111.py
```

The first command completed **9 tests, 0 failures** on 2026-11-11. The second returned `decision=NO_GO` with the full checks and gates, and intentionally exits **2**, even when all available hashes match. It recomputes installed/bundle/ZIP/backup file digests, scans Git status and fingerprints source inputs. The tests use temporary synthetic bytes and do not open an actual ledger. The audit does not execute the EXE, invoke installer scripts, write user profiles, query the Madar service, alter version pointers or independently validate a production GUI, financial posting, rollback or Windows publisher signature.

## P0 gates and concrete next actions

1. **Freeze the P1 feature sources after workers finish.** Recheck all runtime hashes, record the exact Git revision and an isolated clean build tree; include build scripts/dependencies in the reproducibility evidence. The three drifted source inputs need intentional inclusion or exclusion in the next candidate. Never silently replace an already installed v1.0.2 binary under the same version.
2. **Create a new higher-version release from the reconciled sources.** The existing v1.0.2 builder was designed for an installed v1.0.1 predecessor. Its preflight cannot be replayed as a v1.0.3 upgrade. Fix and validate an actual Taraz-specific release entrypoint, package/lock/native version coherence, installer prerequisites and exact new staged hash evidence.
3. **Capture and independently read back a new cold backup from the current v1.0.2 state.** The 181-file snapshot protects the earlier 1.0.1 state but is insufficient evidence of recovery from all current changes. Exercise new-version installation, migration and rollback on disposable Windows profiles and validate the real accounting workflow and Madar read-only boundary.
4. **Independently QA the new installer and activation.** Recheck archive-member hashes, installed EXE bytes, runtime UI with a controlled test profile, version pointer, previous-version retention and rollback on failure; verify signing/publisher authority if release policy requires it. Obtain explicit final release authority only after those checks. The existing unsigned v1.0.2 ZIP is evidence of its own historical build, not evidence that the next version is shippable.

The `NO_GO` result concerns **a new release**, not a claim that the currently installed v1.0.2 has failed in normal user operation. No changes were made to the installed program or stored data as part of this inventory.
