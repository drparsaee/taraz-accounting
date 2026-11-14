# TARAZ 1.0.4 → 1.0.6 — Upgrade safety gate (2026-11-14)

## Operational decision

**BLOCKED — no installed version changed, no production backup/restore/migration
or activation was performed.** The user's conditional installation authorization
requires every protection gate to pass first. Successful Frozen synthetic
invoice testing is not an in-place upgrade acceptance witness.

## Read-only baseline from the actual Windows installation

| Subject | Directly observed |
| --- | --- |
| Installed program | `%LOCALAPPDATA%\Programs\Taraz` |
| Active version pointer | `1.0.4`, SHA-256 pinned against earlier acceptance |
| Installed 1.0.4 EXE | SHA-256 `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` |
| Launcher | Pinned `Run-Taraz.cmd`, original version pointer retained |
| Current source commit at mission start | `c4052e547e06a0fc898b9039c0fb0691df5e2168` |
| Installed Taraz-named processes | 0 in read-only inventory |
| Latest timestamped non-QA candidate | `build-e13b4438f5d4` (1.0.6, not installed) |
| Candidate EXE SHA-256 | `300dfff312dad2c5e5cc3984fc5afb39bc381857889989d4072ab83a34b592d3` |
| Candidate status | Build report/manifest agree on EXE; no live upgrade acceptance |

Real profile inventory inspected **names, metadata, sizes and file types only**:

| Root | Files | SQLite | Bytes |
| --- | ---: | ---: | ---: |
| `%APPDATA%\Taraz` | 128 | 63 | 85,180,568 |
| `%LOCALAPPDATA%\Taraz` | 49 | 4 | 38,830,511 |
| `%LOCALAPPDATA%\Madar-Taraz-Bridge` | 4 | 0 | 796 |
| **Total** | **181** | **67** | **124,011,875** |

A `-shm` SQLite companion was present (32,768 bytes), with a zero-length
`-wal` and three lock-marker files. This **does not prove an active
writer**: the SHM may be stale. However, absence of an active writer and
cross-Store consistent snapshot were NOT established. No customer names,
invoice contents, accounting rows, private source archives or secrets were
read as part of this audit.

## Synthetic technical safeguards, not live-data proof

Owned tools: `scripts/taraz_upgrade_profile_safety_20261114.py` and
`tests/test_taraz_upgrade_profile_20261114.py`.

- Synthetic QA: **13/13 PASS**, covering all three expected roots,
  canonical path/link/hardlink refusal, bounded private ACL, SQLite online
  backup and `PRAGMA integrity_check`, SHA-256 manifest, no-clobber and
  create-only isolated restore, tampered/extra-member/changed-source negatives.
- The script's live-mode entry point is deliberately **metadata-only** and
  refuses to use those copying methods against live APPDATA roots. This is
  a safety gate, not proof of a production backup.
- Original real profile remains unchanged. No installer, activation,
  rollback, migration, payment, bank call, restore to production or
  public push occurred.

## Blocking items before any real installation

1. **Quiescence and source scope:** identify every active SQLite connection,
   lock owner, company data root and service/writer, then secure a consistent
   read-only snapshot boundary. Never delete `-wal`/`-shm` just to make
   a test pass.
2. **Full verifiable live backup:** approved private destination, complete
   coherent capture of all stores/data/attachments and metadata, encrypted
   at rest and with protected keys; SHA manifest, independent readback and
   isolated restore, with no real content exposed unnecessarily.
3. **Upgrade rehearsal:** clone the installed 1.0.4 profile and exact
   installer, apply candidate in isolation, verify old invoice/proforma/order,
   revisions, user permissions, templates, Agent/Madar/Outbox and any Parsian
   history. Test restart, idempotent migrations and fault-injection.
4. **Rollback:** restore both compatible schema and previous executable
   on an isolated clone after an interrupted/failed upgrade.
5. **Installer provenance mismatch:** top-level
   `Install-Activate-Taraz-v1.0.6-FINAL-WHEN-CLOSED.cmd` still points to
   *older* `build-e1723a88abe2`, not the verified latest
   `build-e13b4438f5d4`. Never execute an ambiguous wrapper.
6. **Global WebView2 downloads:** current source uses
   `webview.settings['ALLOW_DOWNLOADS']=True` to support native PDF
   Save As. Scope/behavior of non-PDF downloads must be security reviewed
   and tested before an operational release.
7. **AI history portability:** a new development-only
   `taraz-ai-chat.sqlite3` uses Windows-user DPAPI. Same-principal restart
   works in QA, but portable backup/restore to another identity/device
   cannot be promised without a protected key recovery design.
8. **AI startup identity:** production `taraz_desktop.run()` currently
   instantiates `TarazAPI(data)` with no identity store/token or verified
   company workspace ID. The confidential AI service deliberately refuses
   this legacy implicit-admin identity. End-user login/selection must be
   genuinely connected and tested before shipping this UI; no bypass is
   permitted. Source inspection of `standalone_accounting_auto_backup.py`
   confirms that its current automatic backup members are accounting
   SQLite plus optional templates/users JSON. **It does not back up
   `taraz-ai-chat.sqlite3`**, nor recover its Windows DPAPI key.

**Gate status:** `UPGRADE-DATA-PRESERVATION=BLOCKED`;
`LATEST_NONINSTALLED_CANDIDATE=1.0.6`;
`INSTALLED_VERSION=1.0.4`; `RELEASE=NOT_READY_FOR_APPROVAL`.
No production changes were made to resolve blocked checks by guesswork.
