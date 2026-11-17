# Taraz v1.0.6 Madar project picker: independent contract audit

Date: 2026-11-12. Scope: read-only source and frozen-build inspection, real Python backend methods with in-memory mocks, and synthetic Edge browser tests. No real Madar login, installed Taraz, live ledger, pointer change, rebuild, or commit.

## Outcome and source freeze

**Current source behavior:** the optional project picker uses actual project IDs from an explicitly requested authenticated Madar host projection. The user separately chooses a project and applies the ID to the order form. Saving the order remains another explicit action. This is a verified source reference at selection time, not a synchronized relationship or an enforced foreign key.

**Archived build-777 mismatch (confirmed historical baseline):** The immutable v1.0.6 build was produced before the latest admin-only UI fix. Its frozen order component lacks the canAdmin prop, canAdmin checks in readMadarProjects and applyMadarProject, and conditional canAdmin rendering. Its parent component also fails to pass the canAdmin prop. The current source implements all four restrictions. The actual backend independently requires Taraz admin and consent, so this is evidence of an incorrectly visible picker for non-admin editors in the archived build, not evidence of a successful unauthorized Madar data read. **Do not use build-777 as evidence that the current gate was packaged.**

**Latest prime-reported status:** The prime has completed a clean Vite build of current source and separately passed admin picker Edge (3/3) and non-admin gate Edge (1/1). This worker has not independently inspected a newer immutable EXE and does not treat build-777 as the current post-gate release. Any final EXE/package acceptance still requires its own source/asset manifest evidence.

Frozen immutable build directory:
D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-777cb53341bb

Read-only comparison:

| File | Frozen build | Current source | Interpretation |
| --- | --- | --- | --- |
| src/taraz_order_workspace.jsx | SHA-256 2F00F8AC8E4D1F685819A33B8F8FE0C19ED1147CEE34E282ADC8710AD6FA198E | SHA-256 B3DD03E55378E3CE68C44C91404B1D96E972F0003F030B6790C658AAFEC546C7 | Current admin-only gate not in frozen build |
| src/standalone_accounting_workspace.jsx | Does not pass canAdmin | Passes canAdmin | Current caller updated after freeze |
| taraz_madar_data_reader.py | Equal hash to current | Equal hash to frozen | No source drift observed |
| taraz_order_store.py | Equal hash to current | Equal hash to frozen | No source drift observed |

This audit inspected the build's frozen source and build-report.json, but did not launch or reverse engineer its executable. The compiled browser/PE runtime was not independently exercised here.

## Contract evidence

- Madar source reader: project projection allowlists id, name, title, description, status and color. The server checks nonempty stable project IDs. The picker additionally rejects duplicate IDs, control characters, IDs longer than 120 characters and missing names.
- TarazAPI.tarazMadarDataRead requires authenticated Taraz administrator and explicit consent for project scope. Host mode requires an explicitly supplied private HTTPS IP/port, TLS fingerprint and Madar login; the live TLS handshake was not performed.
- The host reader checks that the login principal/grants equal state principal/grants and that the revision SHA-256 matches canonical JSON. Non-allowlisted price/secret fields are excluded. The UI requires the authenticated-host projection kind, serverAclApplied, readOnly, a 64-character hex revision and financialEventCreated=false.
- In synthetic Edge, the current picker was absent for non-admins, never read without consent, did not auto-apply a project, ignored an in-flight response after credentials changed, rejected malformed/local project responses and only submitted an ID after explicit Apply plus separate Save. The mock finance endpoint was never called. No browser Storage writes or password in the saved order request were observed.

## Tests

New independent test: tests/taraz_v106_madar_project_contract_20261112.test.cjs

Run from repository root: node --test tests/taraz_v106_madar_project_contract_20261112.test.cjs

**Updated independent suite:** 6 tests, **6 PASS** after separating current-source acceptance from historical build provenance. The six tests cover source schema/invalid ID validation, real Python API auth/consent routing, source identity/revision and redaction, replay/freshness boundary, archival build-777 drift with current admin gate check, and synthetic Edge workflow. Earlier 5 PASS / 1 FAIL was caused by incorrectly treating historical build-777 as the post-gate release target; its discrepancy remains documented and checked, rather than erased.

## Residual gaps

1. A correctly shaped projection with a very old readUtc value passes the current client validator. Backend digest validation verifies self-consistency of a returned state, but this protocol does not provide a client freshness/monotonicity guarantee. The UI does correctly reject an old asynchronous response after the credentials change. Do not call these equivalent.
2. The stored projectReference is an optional bounded string. Manual entry or another intake method can insert a reference without rechecking Madar membership. There is no foreign key, enforced cross-system identity, or automatic synchronization.
3. Synthetic backend and Edge tests do not prove real Madar LAN login, native v1.0.6 GUI acceptance, physical printing or real-ledger effects.

The prime's clean current-source Vite build is a separate artifact from historical build-777. Final native executable packaging and source/asset manifest acceptance remain with the prime. This audit made no application-source modifications and did not touch any immutable build.
