# Taraz v1.0.3 P1 | Disposable financial clone gate | 2026-11-11

**Decision: NO FINANCE / MIGRATION / PRODUCTION RELEASE SIGNOFF.**

This gate inspected an ACL-protected disposable copy of an independently
attested **offline** backup. It did not open an installed finance profile,
launch Taraz, or post real transactions. The only posting/revision test used
a completely invented ledger created in a separate QA-only directory.

## Exact pinned inputs

| Input | SHA-256 |
| --- | --- |
| Frozen v1.0.3 native EXE | `e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c` |
| Fresh backup snapshot manifest | `8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d` |
| Independent backup acceptance report | `68bb6e26b9a9a10818e6752a7cc1475a3861c5f380f2021eb5c112a74cd7d2c9` |

Offline input:
`D:\CoS-Test\MTR-REAL-UPGRADE-BACKUPS-20261110\taraz-v103-cold-20261111`

The manifest declares 181 files / 124,011,875 bytes / 67 SQLite files.
The report records installed baseline `1.0.2` before/after and independent
readback. The new gate independently verifies file lists, exact hashes,
sizes, the two attestation pins and safe source-relative paths.

## Actual executed clone audit

Sanitized QA report:

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.3-p1\finance-clone-gate-23f38f2e6ed3\finance-clone-report.json`

Observed status:
`CLONE_READONLY_INVARIANTS_PASSED_NO_FINANCE_SIGNOFF`.

- Every **181 of 181** source backup file SHA-256 matched pre-audit and
  post-audit. Every **181 of 181** cloned file also matched pre/post.
- All **67 of 67** SQLite databases passed integrity-check and schema
  user_version witness checks on the **clone only**, opened with
  `mode=ro&immutable=1` and `PRAGMA query_only=ON`.
- SQLite schema_version and schema SQL fingerprints remained identical
  before and after checks. The main copied accounting journal's exact
  schema, revision head, stored state digest and full event-chain replay
  passed the existing independent `_check_snapshot` verifier. Source
  state contents/digests were not printed.
- A distinct, newly invented synthetic RIAL ledger accepted four
  command events: party, invoice draft, approval, and invoice issue.
  Its revision reached 4, exact replay retained revision 4, stale
  revision was rejected and the synthetic state passed replay readback.
- The temporary 181-file private financial clone was removed, as confirmed
  by `privateCloneCleaned=true`. Only synthetic QA data and a sanitized
  result report were retained in the ACL-restricted QA output.
- `compiledCandidateLaunched=false`, `realTransactionsPosted=false`,
  `originalDataWritten=false` and `productionFinanceSignoff=false`.

## Repeatable tests

All three task files are new and task-scoped:

- `scripts/qa_taraz_v103_finance_clone_20261111.py`
- `tests/test_taraz_v103_finance_clone_20261111.py`
- `docs/TARAZ_V103_FINANCE_CLONE_20261111.md`

From the isolated source root:

```powershell
python -B -m unittest -v tests.test_taraz_v103_finance_clone_20261111
python -B scripts/qa_taraz_v103_finance_clone_20261111.py --preflight
python -B scripts/qa_taraz_v103_finance_clone_20261111.py --audit
```

Observed: **10/10 unit tests passed**, `Ran 10 tests in 0.534s`, exit 0.
The preflight returned `OFFLINE_PIN_AND_181_HASH_PREFLIGHT_PASS`.
The full audited clone returned the success status above, with explicit
`NO_FINANCE_SIGNOFF`. Negative tests covered untrusted backup/attestation,
path traversal, missing/extra/tampered files, corrupt SQLite, incompatible
schema, and write attempts on query-only connections.

## Compiled startup and uncovered financial risks

This worker did **not** run compiled v1.0.3 on the clone; worker22 was
already exercising the private native UI, and the prime reported worker26
had checked a separate read-only private startup. Those are other workers'
reports, not independent startup evidence from this finance clone gate.
No shared desktop, service, installed profile or production executable
was touched.

The following claims remain **UNVERIFIED** here:

1. Compiled v1.0.3 successfully using real historical finance data through
   all GUI workflows in a private installed environment, including
   authentication and permissions after restart.
2. Correct real invoice and payment posting, official receipts, tax/VAT,
   balance reconciliation, payroll, stock, external Madar/Parsian syncing,
   posting idempotence across crashes, or financial migration.
3. Lossless restore/migration in both directions on actual target devices,
   production-load race behavior, or financial audit approval.
4. Publisher signing, release approval, and successful installed version
   upgrade/rollback on a production account.

**Separate critical release gate:** the original frozen v1.0.3 install and
activation scripts have a Windows PowerShell 5.1 ancestor traversal bug:
`FileInfo.Parent` is absent, so an executable file routed through an
ancestor junction could pass their `SafePath` checks. The prime separately
reproduced this on disposable paths. Therefore the original frozen
v1.0.3 ZIP remains **NO_GO for operator deployment**, even though its
offline backup clone is internally consistent. It requires a corrected,
separately pinned complete update package and independent acceptance.

**This report does not authorize real finance posting or deployment.**
