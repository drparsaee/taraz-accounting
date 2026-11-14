# TARAZ — Frozen Gate A synthetic acceptance evidence (2026-11-14)

## Scope and decision

**Gate A's scoped synthetic Windows Frozen-EXE application flows: VERIFIED PASS,
subject to the separate native Save As reconciliation below.**
This is NOT production deployment approval, financial-posting authorization,
physical-printer acceptance, or approval of unrelated P2/P3/P4/Cloud/Madar gates.
No installer was executed, no candidate was published and no live accounting,
bank, or MadarHost data was used.

This section supersedes only earlier Gate A findings for prior Frozen candidates.
Historical failed and blocked reports are preserved rather than relabeled.

## Binary identity and isolated runs

- Git baseline at recovery: `f38729ce16999b03ba62e5972de424dadec4118d`.
- Candidate: `build-e13b4438f5d4` (built, **NOT installed**).
- Frozen EXE SHA-256: `300dfff312dad2c5e5cc3984fc5afb39bc381857889989d4072ab83a34b592d3`.
- Source freeze: `73b692ca3b8790315a3c41be96960e059a06c6f9d6884cd8205edb1c2fe460c8`.
- Main synthetic run: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\frozen-synthetic-private-uia-20261112\qa-8d2a2170c741`.
- Fresh, independently owned invoice run: same parent, `qa-958f63883537`.
- QA runs use private Windows desktops, private app profiles and standalone SQLite.
  Source-hosted browser tests are supporting regression, **not** substituted for Frozen tests.

## Native UI → real backend → isolated SQLite witnesses

| Gate | Raw evidence JSON | Result |
| --- | --- | --- |
| Invoice new draft (fresh owned book) | `qa-958f63883537/synthetic-invoice-252b3673.json` | PASS; `INV-1405-0001`, 13,500 RIAL, accounting revision 1→2 |
| Invoice same-ID edit | `qa-8d2a2170c741/synthetic-invoice-edit-25dc5661.json` | PASS; 13,500→18,000 RIAL, revision 3→4, no duplicate |
| Proforma draft | `qa-8d2a2170c741/synthetic-proforma-5934dee3.json` | PASS; `PF-1405-0001`, 5,000 RIAL |
| Proforma same-ID edit | `qa-8d2a2170c741/synthetic-proforma-edit-03dde646.json` | PASS; 5,000→7,500 RIAL, revision 4→5, editor provenance recorded, no duplicate |
| Print-template persistence | `qa-8d2a2170c741/synthetic-print-21a081ef.json` | PASS; `QA FROZEN PRIVATE PRINT TEMPLATE` re-read |
| Order creation | `qa-8d2a2170c741/synthetic-order-create-9a73becc.json` | PASS; 100 sold, 120 production planned, one cost stage |
| Actual order cost | `qa-8d2a2170c741/synthetic-order-cost-1752f55e.json` | PASS; 180,000 RIAL, persisted date 2026-11-14, order revision 1→2 |
| Recorded order payment | `qa-8d2a2170c741/synthetic-order-payment-a6100dee.json` | PASS; 500,000 RIAL, `recorded`, order revision 2→3; no bank settlement |

Every successful relevant report records normal QA app exit, unchanged installed
baseline and zero accounting journals. The order readbacks show
`financialEventCreated=false`. The order cost and payment have **not**
been approved/settled as official accounting events.

### PDF: separate native Save As reconciliation

The initial `synthetic-pdf-invoice-6848c0a3.json` remains **BLOCKED** because
the main phase returned before the Windows Save As dialog was fulfilled.
The exact owned dialog was subsequently completed with the restricted
`scripts/qa_taraz_private_save_dialog_20261114.py` helper; this is a separate
verified outcome, NOT a retroactive PASS for the earlier report.

- Native Save As report:
  `qa-8d2a2170c741/private-profile/qa-private-save-4162ede3.json`.
- It records: `saved=true`, exact QA path set and read back, Save button
  invoked, file produced, 56,462 bytes.
- PDF: `qa-8d2a2170c741/private-downloads/QA-FROZEN-INV-1405-0001.pdf`.
- SHA-256: `0413641cde01ee0d99692a21962f704e4ef916677a896fc8246cdf3444452466`.
- PDF header and EOF valid, one page, 1050×1485 nonblank embedded JPEG;
  visual inspection confirmed the synthetic edited invoice, 18,000 RIAL.
- The PDF was **not** saved to the user's Downloads folder.
- No physical printer test was conducted.

### False negatives and QA-only correction

- The original main-run invoice creation report
  `synthetic-invoice-4b7c2d20.json` retained `BLOCKED` because a
  phase-independent validator indexed an empty list after a successful UI
  Save. The new **fresh** owned invoice run above achieved a clean PASS.
- Proforma-edit UIA initially counted a Text label and an Edit input, both
  named `تعداد`, as two field candidates. The editable input had genuinely
  retained `3`. The QA harness now filters `ControlType.Edit` and the same
  Frozen executable passed same-ID update and SQLite readback.
- The product change `webview.settings['ALLOW_DOWNLOADS']=True` enabled the
  Windows Save As flow; a native `امروز` button made the cost date editable
  without relying on Chromium calendar UIA. Both are in this **uninstalled**
  candidate.

## Safety, regression and release boundary

- All accounting readbacks: `journalCount=0`; no live bank request was made.
  The QA WebView2 runtime was isolated and configured to block background
  external network activity.
- New negative-test runs on 2026-11-14:
  `python -m unittest tests.test_taraz_independent_frozen_bootstrap_20261112 tests.test_taraz_prime_independent_qa_20261112`: **8 PASS**, exit 0;
  `python -m unittest tests.test_taraz_order_finance_20261112 tests.test_taraz_order_accounting_draft_20261112`: **8 PASS**, exit 0.
  These check Parsian source guarding, corrupt digest failure, permissions,
  revision/idempotency and nonfinancial drafts. They are source tests, not
  direct attempts to make live bank requests.
- `npm run test:orders:all`: exit 0, Vite 2,060 modules,
  59 Python, 16 Edge and source-hosted native `PASS_ORDER_NATIVE`.
  Protective Parsian PermissionErrors and a temporary-folder cleanup warning
  were observed in that source-hosted test, not silently treated as universal success.
- Explicit user confirmation remains mandatory for formal financial posting.
  No upgrade, installation, publication, rollback or live data migration was performed.

## Residual limits

- The native PDF has been saved, parsed and visually inspected, but the
  Windows physical-print flow is not tested.
- `ALLOW_DOWNLOADS` applies to the WebView application globally. Route and
  content restrictions require separate security review; Gate A does not imply
  arbitrary-content download safety.
- This verifies one exact Windows candidate and isolated synthetic data; it
  does not establish installation compatibility on other devices, live banking,
  official finance approval, Madar sync, disaster recovery, or release readiness.
