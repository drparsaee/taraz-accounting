# Taraz v1.0.4 RC2 | source-only corrective stage | 2026-11-11

**Result: RC2 structurally verified, dynamic Edge did NOT approve it.**

Worker27 reproduced three raw errors against the rejected compiled 1.0.4
Vite frontend. RC2 introduced isolated corrections for:

- `src/accounting_print_designer.jsx`: generic preview-render failure
  rather than raw browser Canvas `Error.message`, preserving locally
  authored template and image validations.
- `src/accounting_operational_panels.jsx`: generic `File.text()` error
  before any CSV parser call; locally authored, enumerated parser errors
  remain visible, unexpected messages become generic.
- `src/accounting_management_dashboard.jsx`: generic thrown analytics
  exception, preserving locally authored date-range validation.

The input Stage B:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-959986753b61`
retained 131 inputs with SHA
`6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1`.

The **new create-only RC2** Stage C:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-146b4c62e3f8`
contains 131 files with SHA
`aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8`.
Only the three listed JSX files differ; 128 files, including version
`1.0.0` package/lock baseline, are byte-identical.
Manifest file SHA:
`33892e1772ba79a5476dc69520d0e79197a5adcd2ec1bba797c98974032129f7`.
Patch witness SHA:
`1cd28652160ed6c5339f5f8e9f2b6db41819880cdfbed0b3b71b888252dd80b4`.

Actual detached Vite-only build:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-899a40d30820`.
Report is called `rc2-vite-qa-report.json`, status
`V104_RC2_STAGE_UI_ONLY_EDGE_QA_PENDING`, JS:
`dist/assets/accounting-CHreeEUA.js` SHA
`39295ea85bf2d6ee9fd94fce862c2bc505d4ac6ce01153fbc7ef9d8eea0b5b79`.
No native EXE or offline ZIP was built.

**Direct worker29 verification:** `python -B -m unittest -v
tests.test_stage_taraz_v104_rc2_20261111` returned **12/12 tests PASS**,
exit 0, no skipped tests; 131 SHA readback, three-source exact scope,
Babel JSX parsing, reverse `git apply --check`, valid Vite asset hashes
and old EXE/ZIP hashes unchanged.

**Crucial residual:** worker27 subsequently observed that
`buildManagementAnalytics` can return an object containing a raw
`analytics.error` without throwing, and JSX directly rendered
`{error||analytics.error}` on line ~304. Thus RC2 alone did not mask
the invoice-key echo. It is **not Edge-approved**; successor RC3 patches
only that remaining sink.

An early attempted stage `source-stage-b6d5dcb91a3f` was BLOCKED by a
missing Python module import and is INVALID, not an operator artifact.
It remains untouched. Source stages RC1/RC2, rejected compiled EXE and
original installed 1.0.2 remained unmodified.

