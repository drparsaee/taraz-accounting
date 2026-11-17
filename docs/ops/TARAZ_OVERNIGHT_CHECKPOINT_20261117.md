# Taraz overnight execution checkpoint

**Checkpoint date:** November 17, 2026. **Not a final morning-run report.**

## Questions requiring authoritative answers (leave blocked until verified)

1. **TAR-06, Parsian provenance:** Which company-authorized, complete, read-only source or isolated clone supplies the full fiscal-year/module inventory? Do not infer that the known 1404 and 1405 samples cover every year. See [TAR-06 blocker](TAR_06_PARSIAN_SOURCE_BLOCKER_20261117_FA.md).
2. **TAR-09, tax policy:** Which formally approved, effective-dated purchase-tax policy and GL chart account govern recoverable input tax, and who attests its legal eligibility? Do not guess a statutory rate or post any tax entry. See [TAR-09 blocker](TAR_09_TAX_POLICY_BLOCKER_20261117_FA.md).

## Completed with source-level evidence

| Task | Work performed | Evidence |
| --- | --- | --- |
| TAR-04 | Strict, read-only RIAL AR/AP opening contract; no posting | `2fa8f1e`; 10/10 tests |
| TAR-05 | Single-transaction opening batch in isolated kernel; per-party AR/AP balances, later settlements, reverse guards | `bf0866e`; 13/13 ledger tests plus 8/8 previous finance gates |
| TAR-06 safe portion | Synthetic Parsian fiscal-year/module coverage inspector, never claims verified source | `6d52b69`; 9/9 tests; task remains BLOCKED |
| TAR-09 safe portion | Read-only tax classification for exempt/expense/potentially recoverable treatment | `a048ef9`; 9/9 tests; task remains BLOCKED |
| TAR-10 safe portion | Read-only duplicate business-source audit, exposes no source IDs and never claims tamper proof | `9e500c1`; 7/7 tests; task remains ACTIVE |

Source/legacy acceptance additionally passed: existing accounting core 8/8, product contract 13/13, finance authority 10/10, migration rehearsal 18/18, finance clone 10/10, backup retention 2/2. `npm test` passed Vite compilation (2,067 modules), 34 Python and 11 JS/Edge tests; this is **not** a frozen EXE or real-printer acceptance.

## What broke and what was resolved

- New opening ledger initially failed six of seven RED tests due to unknown command and missing opening view. The new kernel and tests now pass 13/13 on disposable SQLite only.
- A new-worktree migration test originally lacked a QA output folder. The test harness was fixed separately; 18/18 migration tests passed afterward.
- A test fixture initially reused a historical project-context amount. **Before any push**, unpublished local commits were rebuilt with a generic synthetic number. The sanitized TAR-04 SHA is `2fa8f1e`; the earlier local `d36f8b6` is not the published branch history.
- One transient connected-Windows service failure recovered on retry. Do not claim continuous service availability from that observation.
- Vite still warns of a JS chunk larger than 500 KB.

## Current hard boundary

- **NO-GO** for installing, upgrading, merging to the default branch, importing Parsian, or posting real financial data.
- All new work occurred in the isolated worktree `D:\CoS-Test\ECOSYSTEM-PRIME-20261116\taraz-accounting-p0-fixes-20261117`.
- The public GitHub source branch is `feat/taraz-opening-ledger-20261117`, distinct from the unchanged default branch.
- Gitleaks checks over changed files found no flagged secrets. This is not a comprehensive proof of no secrets anywhere in Git history.
- An automation was scheduled for seven hourly continuation attempts. **Whether each future run could access the Windows machine is not yet known.** Do not report future progress without run evidence.

## Small first action in the morning

Open `docs/ops/taraz-phase-board.json`, check **which single task is active**, and verify the latest Commit and test evidence before doing anything else. If still TAR-10, the next executable step is a synthetic RED test for kernel-level duplicate `sourceType/sourceId` posting with a different event ID, preserving historical replay; do not implement an external trust anchor without key-management/restore requirements.
