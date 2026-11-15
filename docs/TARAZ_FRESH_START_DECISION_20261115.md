# TARAZ — fresh start requested on 2026-11-15

The user explicitly abandoned the old 1.0.4 ledger and wants to re-enter
financial data from scratch. Legacy ownership declaration is irrelevant to
creating a NEW local book.

## Implementation

- New module: taraz_fresh_windows_workspace.py
- New absent-only profile creates a single zero-revision RIAL ledger.
- A local Windows-principal-bound authenticated administrator is created
  for this new empty book, with an encrypted generated secret via DPAPI.
  No separate accounting password screen is needed for this personal mode.
- The normal Taraz API still validates each company/user session.
- Existing legacy data, wrong principal, modified marker and missing book
  must fail closed rather than being overwritten.
- Four Windows focused tests passed.

## Exact frozen GUI result

Built candidate: build-5e5253cd7449
SHA-256: d4692dfaf66b4de52e778bea59099ad2ea661f4e47493877a4ca9d4b6c322305

In a private Windows desktop the actual frozen EXE reached the real
Taraz accounting window with a zero-revision synthetic book, without
company selection, legacy enrollment or a password prompt.

**BLOCKED:** Graceful native close did not complete in the private desktop.
Two exact QA EXE processes (PID 37456 and child 26844) remained in the
last readback. No force kill was performed. The compiled candidate was built
before a subsequent missing-ledger safety fix; it is not the newest source.
Full invoice/order/AI acceptance has not been established.

## Production status

**NO LIVE DATA RESET, DELETION, PROFILE MOVE, INSTALL OR ACTIVATION.**
Installed 1.0.4 and all original data roots are unchanged.
Gate B backup remains available. The official 1.0.6 install Apply is blocked.

Before the real reset: close QA processes safely, accept an exact new frozen
build with normal exit, independently verify a complete old-data archive,
rehearse a clean-install + full rollback, then replace the installed version
and retire the old three data roots reversibly. Do not delete backups.
