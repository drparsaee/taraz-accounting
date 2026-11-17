# Taraz: isolated P0 Madar invoice suggestion QA build (2026-11-10)

## Result

**QA_BUNDLE_VERIFIED**, source snapshot and packaged archive inspection only.
The source was already modified to include an optional **in-memory**
description-only sales invoice draft action from incoming Madar metadata.
No amount, party, ledger account, item ID, tax or official accounting document
is authorized or populated by this integration.

- Script (new): `scripts/qa_mtr_taraz_build_20261110.py`
- Run: `py -3.12 -B scripts/qa_mtr_taraz_build_20261110.py`
- Result (new external folder):
  `D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110\qa-e82a53f3a9ae`
- QA EXE:
  `pyinstaller\dist\Taraz-MTR-QA-e82a53f3a9ae.exe`
- SHA-256: `a7cb890a7fe45be5e276bffddd971f257baaced1284b6a91aa0b0733f4fcf444`
- EXE size: 16,974,184 bytes
- Source snapshot: 118 inputs; source fingerprint SHA-256:
  `7b6990b7dcff1b6658b4a7a8ff83e47d80534c71536e37db87547515d1612b46`
- Node dependencies: trusted offline copy of
  `D:\CoS-Test\000- Taraz\taraz-accounting-desktop\node_modules`,
  copied into an external QA snapshot. No mutation of the detached project's
  node_modules or use of npm install.

## Evidence

The script copied the current detached Taraz Python and frontend inputs
and the trusted dependency tree without symlinks or junctions into a unique
external QA directory, then ran Vite and onefile PyInstaller against that
snapshot. All Vite outputs, PyInstaller work/spec/dist, npm cache, Python
cache roots and temporary profiles were directed to the external QA directory.
Source inputs were SHA-256 checked before and after. The result is recorded at:

`D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110\qa-e82a53f3a9ae\qa-build-report.json`

The build logs are in that same directory:
`vite-build.log` and `pyinstaller-build.log`.
The report records:

| Packed artifact check | Observed |
| --- | --- |
| Vite `accounting.html` and JS assets | Present |
| UI action text `آماده‌سازی پیش‌نویس فروش` | Present |
| Compiled UI reference `tarazIntegrationList` | Present |
| Compiled UI reference `tarazIntegrationReview` | Present |
| Packed `taraz_desktop` Python method `tarazIntegrationList` | Present |
| Packed `taraz_desktop` Python method `tarazIntegrationReview` | Present |
| Direct post-build `Get-FileHash -Algorithm SHA256` | Matches report |

The new draft feature's dedicated regression was independently rerun with
`NODE_PATH` set to the previously installed Madar node_modules:

`node --test tests/taraz_madar_invoice_draft_20261110.test.cjs`

Observed **4 tests pass, 0 fail**. The 14/14 result supplied by prime was
not independently rerun as the same complete command by this worker.

## Limits and handoff

This is an **isolated, unsigned, non-release QA-only bundle**, deliberately
not installed, started or published. Packed code presence does not establish
GUI click success, financial workflow completion or the presence of a valid
personal ledger. The installed Taraz startup requires its verified prior
accounting book; an unrelated worker owns safe installed-GUI synthetic QA.
The QA build did not touch the installed binary, real profile, accounting
database, ledger, migration archive, running app, network or release output.

Prime can use the report's exact EXE path as a uniquely identifiable source
artifact for subsequent controlled GUI testing after its ledger/source guard
and profile isolation checks. No commit/push/install/sign/release was done.
