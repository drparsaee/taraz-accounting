# TARAZ PRIME — legacy 1.0.4 recovery and release decision (2026-11-14)

## Decision: BLOCK PRODUCTION INSTALL

The installed application is still **1.0.4**, independently read back from
`C:\Users\Parsa\AppData\Local\Programs\Taraz\current-version.txt`.
The new 1.0.6 executable **has not been installed or activated**. No production
financial events were intentionally written, no company owner or administrator
was invented, and no push or public release was performed.

## Independent source, snapshot and binary evidence

| Evidence | Observed result |
| --- | --- |
| Starting Git HEAD / branch | `23b2753e6bb981b5831c2868f46646a90fdef685` / `codex/taraz-final-integration-20261112` |
| Real three-root Gate B source inventory | 181 files, 67 SQLite databases; 124,011,875 bytes |
| Snapshot content | 179 portable members, 67 SQLite databases; original WAL/SHM not deleted |
| Snapshot manifest SHA-256 | `ba8c16f1ae83bc270d4b3910fbd124e5e8c6c570f1c1012f8db1a30a6673248d` |
| Old EXE SHA-256 | `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` |
| Final non-installed candidate | `build-8a8ec1717a58`, 1.0.6, PE 1.0.6.0 |
| Frozen source | 153 files, `c308c5e19b506f73dd8a7e19693efc99dd2a366132b565ff15965fbaf54c4469` |
| Final candidate EXE and package EXE SHA-256 | `1f8f7f5c1923460e14487efc6aa4a106fb71a0efbcc36dbda1e1969ed65c99d0` (matched) |
| ZIP SHA-256 | `cb1392765a76e0b5a99e15cc661281961f3d910ddfc0a5ad9e924e47459f4659` |
| Update manifest SHA-256 | `9713b708b8da9771e5c7d1b1be1bd845b91af15fe87dc680a13a29c36217ab4b` |
| Manifest release state | `BLOCKED_DATA_PRESERVATION`, `installApplyAllowed=false`, `activateApplyAllowed=false` |

Final build directory:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-8a8ec1717a58`.
Static compiled parity is reported in the matching build manifest. **The
actual frozen UI run below refers to the earlier post-retention-fix executable
`build-4a5ff6a0d32d`, not to this final candidate**, which additionally
contains a ledger-digest-variable fix. Do not transfer native UI acceptance
from one binary to another.

## Actual restored legacy identity and data

The verified Gate B backup was cloned to
`D:\CoS-Test\TARAZ-REAL-LEGACY-CLONE-20261114-PRIME-C`.
The real 1.0.4 ledger contains revision **609**, **609 immutable events** and
**388 journal events**. A provenance-based workspace ID was derived, but it
is **not a legal company ID**. There is no verified company name, owner,
administrator, registered `companies.json` or authenticated `local-users.json`
from the historical ledger.

`taraz_legacy_workspace_bridge.py` added a versioned, idempotent
`identity_pending` **viewer-only** sidecar to a fresh restored clone.
Repeating migration returned `ALREADY_MIGRATED`, with unchanged original
event IDs and financial digest. No admin, password, role grant, financial
posting or registered company context was invented. The viewer can read
original accounting data; local Persian AI chat can create and search
conversations and survive a new session, but financial approval is denied.
That real-clone AI provider reported `disabled`, not an LLM.

Real-clone evidence: `legacy-clone-verification.json`,
`legacy-real-viewer-verification.json`,
`legacy-real-chat-verification.json`,
`legacy-rollback-verification.json` in the clone directory.
Data-only rollback restored 179 files and 67 SQLite databases, with the
sidecar absent. **This is not an EXE/installer rollback after full upgrade.**

## Frozen runtime observation and discovered regression

An earlier frozen 1.0.6 run on a private real-data clone actually opened
the Taraz native WebView: title `تراز | حسابداری مستقل`,
`loaded=true`, `accountingBridge=function`, 21 observed tabs.
That run exposed rotation of four **pre-existing automatic backup archive
members** (two SQLite and two matching manifests) during launch/exit.

Remediation: `AutomaticStandaloneBackups(preserve_existing=True)`
is now required specifically for the unclaimed legacy viewer. In the next
fresh-clone frozen run (`build-4a5ff6a0d32d`), independent postflight
matched **all 67 original SQLite databases, 112 original other files,
85 tables and 25,745 rows**. The frozen EXE exited gracefully with no
remaining owned child processes. Source tests passed for historical backup
preservation and existing ordinary rotation.

However WebView2 CDP was **not listening** on the expected verified private
port: six owned WebView2 processes with debug flag were observed but
`cdpPortListening=false`. Consequently no authenticated CDP navigation,
actual order clickthrough or AI-UI interaction was accepted for the frozen
executable. This is a QA access limitation, not proof that those pages are
unusable. Do not bypass the private-session security boundary to force PASS.

Frozen evidence for the post-fix run:
`D:\CoS-Test\TARAZ-LEGACY-FROZEN-QA-20261114\qa-98f908c89b3d\frozen-legacy-acceptance.json`.
The source-backed synthetic tests are **not equivalent** to native UI acceptance.

## Targeted tests run in this continuation

* Legacy workspace/read-only ACL/idempotency: **7/7 PASS**.
* Backup preservation vs normal rotation: **2/2 PASS**.
* Existing frozen bootstrap: **3/3 PASS**.
* AI encrypted chat, search, idempotency, privacy: **38/38 PASS**.
* Browser chat search notice: **2/2 PASS**.
* Python and embedded JavaScript syntax of private frozen QA runner: PASS.
* `git diff --check`: exit 0.
* Direct invocation of synthetic migration rehearsal no longer raises import
  error. That script remains **synthetic-only**.

## Eight mandatory production gates

| Gate | Current outcome |
| --- | --- |
| `FULL_PROFILE_BACKUP_RESTORE` | Same-principal baseline restore proved; cross-root atomicity/external writers not exhaustively proved |
| `LEGACY_104_TO_NEW_SCHEMA` | **BLOCKED**: verified pending viewer, not authorized company/admin migration |
| `REAL_104_CLONE_UPGRADE` | **BLOCKED**: frozen real-clone startup/readback only; authenticated full UI and installed upgrade unproved |
| `ROLLBACK_RESTORE` | Data marker rollback PASS; complete EXE/schema/installer rollback **NOT RUN** |
| `UPDATE_PACKAGE_BUILD` | 1.0.6 candidate built and fingerprinted; explicitly non-installed |
| `INSTALLER_BUILD_MATCH` | Package EXE matches final EXE; Apply remains deliberately blocked; full install rehearsal NOT RUN |
| `AUTHENTICATED_APP_RUNTIME` | **BLOCKED**: legitimate registered legacy company administrator unresolved; private CDP not listening |
| `CRITICAL_FINANCIAL_REGRESSION` | Targeted tests PASS; frozen authenticated invoice/order/AI clickthrough NOT ACCEPTED |

### Remaining authority and acceptance boundary

A legitimate claim of **company legal identity, ownership and authorized
administrator** must come from independently verifiable evidence, not the
registration/economic code alone, historical actor labels, Windows username,
an old migration manifest, or a made-up password. Until that mapping can be
proven, full editing, financial posting and the real in-place update are
intentionally blocked. The baseline Gate B is recoverable under the same
machine/principal; **cross-device DPAPI recovery, VSS cross-root atomicity and
post-upgrade rollback are not claimed**.
