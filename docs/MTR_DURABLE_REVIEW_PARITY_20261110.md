# P0 Madar -> Taraz: durable review and installed parity, 2026-11-10

## Decision

**Current-source metadata recovery passed synthetic QA. Installed Taraz v1.0.0
is NOT equivalent to current source and is NOT accepted for P0 release.**

Worker-owned changes are limited to three new files:

- `scripts/qa_mtr_taraz_durable_recovery_20261110.py`: SHA-gated, **read-only**
  inspection of a packed installed EXE; `recover` runs only on explicitly
  marked, disposable synthetic QA folders. Never imports/executes installed code.
- `tests/test_mtr_taraz_durable_recovery_20261110.py`: isolated local restart,
  corruption, forged/replayed receipt, concurrency, and interruption QA.
- `docs/MTR_DURABLE_REVIEW_PARITY_20261110.md`: this bounded evidence report.

No source changes were made by worker-10. The source-owner/prime concurrently
fixed the marker-publication race described below; all final test results
refer to the **post-fix** source, not the earlier failing version.

## Exactly observed installed package

Read **only** the program binary under `%LOCALAPPDATA%/Programs/Taraz/versions/1.0.0/`.
No run, unpacked execution, imported bytecode, login, or file inspection under
the user's `%APPDATA%/Taraz` or personal accounting data root.

| Inspectable property | Observed |
| --- | --- |
| Executable | `versions/1.0.0/Taraz.exe` |
| Size | 16,968,567 bytes |
| Measured and then required SHA-256 | `de5005579039bd86890c1dca1f5f1d9c760e6c47579a42f649f80096f158e70c` |
| Packed native methods | `tarazIntegrationList`, `tarazIntegrationReview` present |
| Packed `taraz_integration.review_request` | Uses `os.rename` and direct receipt `open` |
| Packed pre-move durable `_atomic_json` intent | **Absent** |
| Packed per-request `_request_lock` | **Absent** |

The installed function's static PyInstaller code-object inventory (from its
SHA-pinned archive) supports the last three claims. **It does not establish
actual installed GUI behavior, recovery success or finance authorization.**
In particular, interrupted rename-before-receipt in the older installed code
cannot be assigned the current source's documented recovery guarantee.

## Current source and independent QA

Final inspected `taraz_integration.py` SHA-256:
`c508963b0449cd63ba0f76f924c9ba48cae278677992dbbf635ccc8ed605364e`.
This value is **a measured working-tree snapshot**, not a release artifact.

The current source has a fsynced pre-move `<id>.intent.json` containing the
untrusted Madar request's exact SHA-256, immutable decision, and metadata-only
`financialEventCreated=false`. The later `reviewed/<id>.json` move and
`<id>.review.json` receipt are retried against that intent under a per-ID
OS lock. A source/decision mismatch fails closed.

An earlier QA run exposed a concrete marker-publishing race: checking that a
marker did not exist, then calling `os.replace(temp, target)`, overwrote an
adversarial marker created between those operations. This was confirmed in
a disposable fixture. **Prime changed the source** to use `os.link(temp, target)`
on one filesystem (atomic no-clobber), with a fail-closed exception and cleanup.
Worker-10 updated its **new test only** to inject a competing marker at the
link boundary; the fixture now proves the competitor bytes are preserved,
pending input remains untouched and no receipt is fabricated.

Final commands run from detached Taraz checkout:

```
py -3.12 -B scripts/qa_mtr_taraz_durable_recovery_20261110.py manifest
py -3.12 -B -m unittest -q tests.test_mtr_taraz_durable_recovery_20261110 tests.test_taraz_integration
```

Observed: **manifest command exit 0**; **38 tests OK, exit 0** (16 independent
QA cases + 22 source integration cases). The independent tests create temporary
`qa-` directories, synthetically write incoming task metadata, simulate a
failure at each of the intent/move/receipt boundaries, and spawn **fresh Python
processes** for recovery. No financial API is called. Verified scenarios:

- Restart before intent; after intent but before move; after move but before
  receipt; and after receipt write. Same choice replay is idempotent, opposing
  choice cannot reinterpret an existing decision.
- Corrupt/malformed intent, changed source bytes, forged receipt with
  `financialEventCreated=true`, another request's receipt, missing reviewed
  source, ambiguous orphan receipt, stale duplicate pending+reviewed records:
  none are accepted or silently repaired as valid finance proof.
- Two competing fresh interpreter processes choosing opposite outcomes:
  exactly one durable decision wins, the other fails.
- Adversarial marker publication at the no-clobber boundary:
  injected contents survive unchanged and no moved source/receipt appears.
- Wrong installed executable SHA or unmarked synthetic recovery folder:
  rejected before processing.

## Remaining P0 release gates and limitations

1. **Installed parity:** Existing v1.0.0 still contains the earlier,
   non-durable implementation. P0 requires packaging, installing and verifying
   a *new* revision with the current source. No installed EXE was replaced,
   signed, launched or accepted in this task.
2. **Operator recovery surface:** `list_requests()` lists pending only. An
   interrupted **after-move/pre-receipt** request is no longer in pending;
   the current UI does not expose a documented, authenticated route to inspect
   that persisted intent and re-run recovery with its original decision. The
   CLI in this QA is restricted to disposable marked paths, not user data.
   Recommended source-owner implementation: authenticated, read-only,
   bounded review-state inspection keyed by exact request ID with explicit
   review/resume action using the persisted decision; never claim an absent
   receipt proves failure or trigger a financial write.
3. **Power-loss durability:** File data fsync and atomic no-clobber publication
   are exercised, but filesystem/controller durability under sudden power
   loss or Windows directory metadata flush was **not** established by these
   process-interruption tests. Likewise, hostile concurrent mutation of
   shared bridge folders beyond the specific tested races needs separate QA.
4. **Finance boundary:** Current APIs exchange metadata decisions, not ledger
   approvals, signed accounting receipts, invoice posting or live peer status.
   Even a new QA EXE plus these tests cannot be called an operational finance
   release or confirmed two-machine link.

This file is evidence for prime's release gating. It is not an approval to
modify an existing user installation or accounting profile.
