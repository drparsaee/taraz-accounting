# Madar ↔ Taraz P0: current packaged PYZ durable review QA (10 Nov 2026)

**Result: PASS for synthetic, disposable packaged-module recovery only.**
This is not an installed-app, native GUI, finance, release or personal ledger test.

## Exact artifact and verified provenance

The test targets the new **QA-only**, non-release executable:

`D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110\qa-457b29e2f80b\pyinstaller\dist\Taraz-MTR-QA-457b29e2f80b.exe`

| Item | Observed and enforced |
| --- | --- |
| SHA-256, QA EXE | `278106886eccf169551f734c9c01fc10225969f12a7b4e9d06229b894ad06cd2` |
| SHA-256, original source snapshot manifest | `e168a6d70e19e0ea883ced2dac8ab0f1b46bb55ea94302f6380cfacbf4e21969` |
| SHA-256, **actual packed `taraz_integration` Python code object** | `c20f2259a98bc871177bd4488bd901236baf68eaea6b3a53802ad8ac962e4b9d` |
| Source input inventory | 119 files, checked against full build source snapshot |
| `qa-build-report.json` status | `QA_BUNDLE_VERIFIED`, `qaOnly=true`, `installed=false`, `releaseReady=false` |

The runner fails closed on a changed binary, missing/contradictory build
manifest, changed source snapshot, altered packed bytecode, missing no-clobber
publication or missing per-request lock.

The actual PYZ `taraz_integration` Python code object is obtained using
PyInstaller `CArchiveReader` and `PYZ.pyz`. **The code object is executed**
as the isolated integration module in a fresh Python 3.12 child process. This
is stronger than searching an EXE for strings. Only that integration module is
evaluated, **never the EXE entrypoint or `taraz_desktop.py`**; neither
`TarazAPI` nor `source_guard` is invoked, edited or bypassed.

Every child process runs in an explicitly marked, newly created disposable QA
directory. Its APPDATA, LOCALAPPDATA, TEMP, TMP, USERPROFILE, HOME, and
TARAZ_QA_DATA_DIR all resolve inside that directory; subprocess uses
`python -I -B`, a reduced environment and a bounded execution timeout.
The parent checks the fixed, SHA-pinned QA build read-only. No real profile,
installed application, ledger, service, actual network, installer or release
files are used or modified.

## Tested behaviors

New files owned exclusively by worker-10:

- `scripts/qa_mtr_current_bundle_review_20261110.py`
- `tests/test_mtr_current_bundle_review_20261110.py`
- `docs/MTR_CURRENT_PACKED_BUNDLE_REVIEW_20261110.md`

Commands executed in the isolated Taraz worktree:

```powershell
py -3.12 -B scripts/qa_mtr_current_bundle_review_20261110.py --manifest-only
py -3.12 -B scripts/qa_mtr_current_bundle_review_20261110.py
py -3.12 -B -m unittest -q tests.test_mtr_current_bundle_review_20261110
```

Observed **manifest exit 0; synthetic packaged-module smoke exit 0;
24/24 Python tests passed**. The smoke result identified
`PACKED_DURABLE_SYNTHETIC_QA_PASS`.

Tests include:

- A genuine synthetic pending Madar proposal listed by the packed module,
  then a manual `reviewed` or `rejected` decision. Its exact original bytes
  move to reviewed and a source-SHA-bound durable intent and separate
  metadata-only review receipt are persisted.
- A fresh child Python process reads each persisted decision on idempotent
  replay without rewriting the intent, moved source or receipt.
- Interrupted before durable intent, after intent but before move, after move
  but before receipt, and after receipt publication, all followed by restart
  and bounded recovery or fail-closed rejection.
- Conflicting decision, corrupted intent, source digest mismatch, forged
  `financialEventCreated=true` receipt, stale duplicate pending+reviewed
  record, orphan reviewed entry and pre-durable **legacy receipt-only marker**
  rejected without silently replacing source data or inventing a ledger entry.
- Competing intent marker injected at the packed no-clobber `os.link`
  publication boundary, preserved without a source move or receipt.
- Tampered manifest, binary hash/code-object pin and unmarked QA scratch
  directory fail closed.

### Separate existing frontend tests

```powershell
$env:NODE_PATH='D:\CoS-Test\000- Madar\madar-p2-gantt-notifications-20261107\node_modules'
node --test --test-concurrency=1 tests/taraz_madar_draft_browser_20261110.test.cjs tests/taraz_madar_full_workspace_browser_20261110.test.cjs
```

Observed **3/3 Chromium/React synthetic tests passed**. They demonstrate the
manual draft button and actual current-source React interaction, including
role restrictions and no finance command. They are **separate** from the
packed-PYZ tests; they do *not* demonstrate an integrated packaged EXE window
or browser-to-packed-module roundtrip.

## Release gate: still not fulfilled

These results demonstrate packaged metadata review/recovery behavior under
controlled local process restarts. They **do not** verify official finance,
an authenticated user role in the installed Taraz, actual receipt posting,
power-loss durability, installed application behavior, LAN/TLS, native WebView2
startup, a real installed version, backups or rollback. A valid
`financialEventCreated=false` in this work is an explicitly **nonfinancial**
metadata acknowledgement. **No P0 release or deployment acceptance is
granted by this QA.**

The separate Chromium frontend tests did not instrument browser-level
background network egress; no application network integration was exercised.

The existing installed Taraz v1.0.0 is a different binary and must not be
represented by this newer QA-only artifact. The old package's durable review
parity limitations remain distinct from the new packed-module tests.
