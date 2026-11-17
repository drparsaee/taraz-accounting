# Taraz P0 | Madar bridge and accounting-safety audit | 2026-11-11

**Finding:** The tested source bridge persists manual `reviewed` / `rejected`
metadata, safely resumes interrupted decisions, and leaves an isolated
accounting-book sentinel untouched. The source fix for inbox truncation is now
covered by a regression test. **No installed-release GO is asserted.**

## Exact audit boundary

- Read-only inspection: `taraz_integration.py`, `taraz_madar_data_reader.py`,
  `taraz_desktop.py`, `standalone_accounting_desktop.py`,
  `src/taraz_settings_integration.js`,
  `src/taraz_madar_dashboard.jsx`, and
  `src/taraz_madar_invoice_draft.js`.
- New independent test only: `tests/test_taraz_p0_bridge_20261111.py`.
  Each dynamic case uses a newly created disposable `Roaming`, `Local`, and
  `Taraz` directory under `D:\CoS-Test\000- Taraz`.
- Bridge proposals and markers are written **only** in that disposable
  `LOCALAPPDATA/Madar-Taraz-Bridge`. A synthetic, deliberately non-SQLite
  `standalone-accounting.sqlite3` sentinel must stay byte-for-byte identical;
  the test traps finance command/store invocation.
- The installed EXE, version pointer, and its PyInstaller embedded archive
  were **read only**. The executable and packed code were **not executed**.
  No real Madar host login, service, production Taraz profile, personal ledger,
  or native installed GUI was accessed through a write path.

## Reproduced source behavior

1. Before user consent, inbox listing does not read `MadarDesk/tasks.json`.
   A missing mailbox is represented as disconnected and is not created.
2. Native `tarazIntegrationReview(id, 'reviewed'/'rejected')` writes a source
   SHA-bound, fsynced intent before moving its proposal; receipt and intent
   carry `financialEventCreated: false`. Repeating a committed decision does
   not replace its marker; opposite decisions fail.
3. Injected failure **after intent, before move** leaves one recoverable
   decision; the still-pending proposal is suppressed from fresh-review UI.
   `tarazIntegrationRecover(id)` without `manual_action=True` fails. After
   explicit recovery the pending file moves and the receipt is completed.
4. Injected failure **after move, before receipt** exposes the original
   rejected decision for manual replay. Opposite redecision is refused.
5. Changing a proposal after durable intent invalidates recovery, surfaces
   `recoveryInvalidCount`, and does not generate a financial receipt.
6. `tarazMadarDataRead` requires explicit consent and Taraz admin for
   non-inbox projections; test fixture financial amounts, passwords, and
   arbitrary private fields are excluded. Local fallback is explicitly marked
   unauthenticated and possibly stale. The real host's ACL was **not tested**.
7. The WebView `window.madar` forwarder exposes the five bridge APIs. The
   reviewed JSX and JavaScript helper require manual confirmation and validate
   `financialEventCreated === false`; invoice draft suggestions omit price,
   account, and item assignments. The source contract checks are additional
   evidence; they do not by themselves prove browser rendering.

## Found P0 defect and source correction

**Originally reproduced:** 101 valid pending JSON proposals yielded 100
visible entries, `invalidCount=0`, and **no truncation indication**. This
could be misread as a complete inbox.

**Current source after prime-owned correction:**

- `list_requests()` returns `pendingTruncated=True` for more than 100
  candidate proposals and `False` for a missing inbox.
- The JavaScript result adapter forwards that field.
- The Madar dashboard shows a visible warning when the inbox is truncated.
- This worker's regression now **requires** `pendingTruncated is True`
  for 101 pending requests while confirming the synthetic accounting store
  was not accessed. The updated test passed.

The candidate count is conservative: it can flag incompleteness even if some
extra candidates are invalid or already associated with a persisted intent.
The UI displays only a bounded prefix; overflow items require revisiting
after decisions. It does not yet implement inbox pagination.

## Actual installed v1.0.2 binary evidence (read-only)

Observed `%LOCALAPPDATA%\Programs\Taraz\current-version.txt`: `1.0.2`.
Its `versions\1.0.2\Taraz.exe` has **17,056,486 bytes** and SHA-256:

`095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52`

`PyInstaller 6.22.3`, using `CArchiveReader`/embedded `PYZ.pyz` without
launching the EXE, yielded the following exact **marshal code-object** SHA-256
values for the installed artifact:

| Packed module | SHA-256 |
| --- | --- |
| `taraz_integration` | `4d7981ef3a1e502a5703dff3be1ff4d65a9a1245caa1b162b890a5c6a49809d7` |
| `taraz_madar_data_reader` | `a066e3cd3c6cc15d74b9232747b80acb7617f925112c94e2ad4e5700e04eff57` |
| `standalone_accounting_desktop` | `39fa65d4d43927b9df628cd6bd8b6b46d361c3bcd3a73109daf95448aaaa4d3e` |

The installed `taraz_desktop` entrypoint contains all five methods:
`tarazIntegrationList`, `tarazIntegrationReview`,
`tarazIntegrationRecover`, `tarazMadarDataOverview`, and
`tarazMadarDataRead`. Each method's normalized code object matched its source
counterpart after removing file/first-line debug offsets. The packed
`standalone_accounting_desktop` code contains all five JS forwarders, and
the bundled JS asset contains dashboard, recovery, and data-read symbols.

Before the inbox-overflow source fix, normalized code objects for the three
PYZ modules matched the source snapshot. **After the source correction,
`taraz_integration.py` no longer has exact bytecode parity with the installed
v1.0.2 PYZ**; a direct recheck returned `False`. This is the expected,
actionable installed-source gap. The audited original installed 1.0.2 remains
unchanged. The regression checks the installed baseline's pinned hashes rather
than pretending that this source change was deployed.

## Test evidence

All commands executed in
`D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

```powershell
py -3.12 -B -m unittest discover -s tests -p test_taraz_p0_bridge_20261111.py -v
# 9 tests, OK (1.600s on final rerun; no skips)

py -3.12 -B -m unittest discover -s tests -p test_taraz_integration.py -q
# 22 tests, OK (1.933s on final rerun after overflow source fix)

py -3.12 -B -m unittest discover -s tests -p test_taraz_madar_data_reader_20261110.py -q
# 7 tests, OK (0.083s on final rerun)

node --test tests/taraz_settings.test.cjs tests/taraz_madar_dashboard_browser_20261111.test.cjs
# 8 tests, 8 passed, 0 failed (4.150s)
```

The browser suite uses a headless synthetic API fixture and does **not** launch
the installed native EXE. The current source's 101-pending overflow warning
is checked by this worker's source contract assertion, not by a new browser
visual test. No source files owned by other workers were changed here.

## Remaining release gates / concrete next actions

1. Build a new independently staged EXE containing the source overflow fix,
   then check its actual packed `taraz_integration` and GUI assets. The
   installed **1.0.2** cannot be credited with the new behavior.
2. Run the new package through isolated native WebView2 and real interaction
   QA, including >100 pending items, pending/recovery alert visibility,
   partial-error state, and no finance command during mailbox operations.
3. For authenticated host mode, validate actual Madar host principal/project
   grants and TLS pinning on an isolated test host before any production-wide
   permission claim. The present host read tests use mocked responses.
4. Perform full release parity, migration, rollback, and installer acceptance
   against the independent staged candidate. The P0 source suite and pinned
   installed archive scan alone do **not** constitute a P1 release approval.
