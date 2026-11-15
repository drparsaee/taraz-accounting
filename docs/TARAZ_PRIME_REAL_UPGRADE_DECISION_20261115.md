# TARAZ PRIME — 1.0.4 → 1.0.6 gate decision (2026-11-15)

**Release decision: BLOCKED. The real installed app remains 1.0.4; no operational ledger or live profile was modified.** The user-defined DONE condition is not achieved.

## Actual recovery and implementation

- Started at actual Git HEAD `24b8ef9bde278a7ca70b0e71b579558168b895b6`; all pre-existing Untracked material was preserved. Older successful 52 focused tests were not blanket-rerun.
- Original Gate B snapshot: `D:\CoS-Test\TARAZ-REAL-BACKUP-20261114-GATE-B\snapshot`, manifest SHA-256 `ba8c16f1ae83bc270d4b3910fbd124e5e8c6c570f1c1012f8db1a30a6673248d`. It contains 179 portable members including 67 SQLite stores. Cross-root VSS atomicity and transient writer exclusion are **not** independently established.
- Real legacy ledger revision **609**, event count **609**, stable event ID SHA-256 `830140fa5d125c3e9a904a521a977269dfbd9d54f24e131f6adf7c6ff4aa6291`. On a freshly restored real clone, a company Workspace with a **non-legal, ownerless label** was created. Its original data, original profile and companion stores remained untouched; repeating Stage returned `ALREADY_STAGED_OWNERLESS`.
- New `taraz_legacy_ownership_enrollment.py` and native Tk `taraz_legacy_enrollment_dialog.py` bind Stage to the same Windows machine/SID and source manifest. The Declaration is an explicit human action, recorded as a **self-declaration, not independent proof of legal ownership**. No credentials, company legal name or admin rights are invented. An administrator is created only after deliberate confirmation and a user-chosen password. Multi-company conflicts and altered source files fail closed; interrupted declarations can resume only for the same declared user.
- Five focused synthetic enrollment tests passed, including idempotency, invalid claims, conflicting companies, authenticated login and interrupted declaration recovery. The **real user's declaration has not occurred**.

## Actual 1.0.6 candidate and isolated installer run

| Evidence | Direct result |
| --- | --- |
| Final non-installed Build | `build-e538f3ec5e8d` / PE 1.0.6.0 |
| Source freeze | 155 members / `7b2a154092df7ed6570b37cf9ab744759d2c545c12423f3c9360e03e0d8958a9` |
| EXE SHA-256, matching both binary and package payload | `b3463132a069e171f1c3bd480423087a31e9f0450a5ea63df46cd82ae7b99e6d` |
| ZIP SHA-256 | `4cdb0969abe8b5ebe3d14b118b8604a23efcf004ce95166bab5690da434c2381` |
| Build manifest SHA-256 | `65c5e6b0c36120f97fa269a17f9a3ce9e0821429e5dbfcc26a15083d18886e55` |
| Package evidence | `compiledByteParity=true`; `installApplyAllowed=false`, `activateApplyAllowed=false` |

- Exact emitted installer/activator/rollback scripts ran **on an isolated 1.0.4 installation clone**: Install 1.0.6, activate, simulate interruption before activation, restore 1.0.4 pointer and EXE, restore three data roots. **PASS**. On restore, all **67 SQLite**, **112 other original files**, **85 tables** and **25,745 rows** matched Gate B. Source: `D:\CoS-Test\TARAZ-INSTALL-REAL-CLONE-QA-20261115\qa-e0c5a0faf916\installer-clone-verification.json`. This is *not* production Apply or an atomic three-root filesystem swap.
- Exact final frozen EXE displayed the native one-time enrollment window on a private Windows desktop and exited gracefully *without* accepting a declaration. Original 67 SQLite and 112 other files remained intact. Source: `D:\CoS-Test\TARAZ-ENROLLMENT-NATIVE-QA-20261115\qa-5ae3efdc4749\native-enrollment-acceptance.json`. The private synthetic authenticated invoice/AI harness remained **BLOCKED**, currently `OWNED_NATIVE_WINDOW_NOT_FOUND` in UI Automation; this is not proof of application failure. No fully authenticated orders/invoices/PDF/AI clickthrough was accepted on the final EXE.
- Focused installer PowerShell AST/production-lock tests **2/2 PASS**; native harness tests **14/14 PASS** following the exact Taraz login-title correction. No forced process termination was used; all owned Taraz QA processes were gracefully closed, and no installed EXE ran.

## Required gates before any production mutation

**Not yet satisfied:** (1) genuine human Declaration and verified registered-company login on the actual old book; (2) real UI → Bridge → SQLite checks for invoices, proformas, orders, print/PDF, AI chat, explicit draft approval and restart; (3) final write-quiescent and cross-store-consistent live backup, same-principal restoration and controlled full-profile rollback proof; (4) production release-gate evidence authorizing installer Apply. The old 1.0.4 pointer and original financial profile must stay unchanged until every gate passes.

**AI/provider statement:** source-level/private synthetic AI chat is not proof of a connected LLM; real legacy AI chat history was not found in the original roots. MADAR/RADAR online integration is **not** accepted as operational by this run. DPAPI recovery is proven only for the same Windows device/principal, not other computers.
