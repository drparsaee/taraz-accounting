# P0 latest Taraz packaged-recovery evidence (2026-11-10)

**Result: LATEST_PACKED_OPERATOR_RECOVERY_QA_PASS**, limited to synthetic
metadata using the actual SHA-pinned PYZ taraz_integration module executed in
isolated Python 3.12 children. **Not an installed, financial or release test.**

## Exact build fingerprint

- QA-only EXE: D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110\qa-52f6b2776362\pyinstaller\dist\Taraz-MTR-QA-52f6b2776362.exe
- EXE SHA-256: f3c4d65418d8f9d80a40618c01bb1534841ca18bf863fd9d09d5ca0fb8449662
- Source snapshot SHA-256: cedd3c8cc51802afe0270cbd08971a1f67347ed3a269d7ec5908fe4c62b6f0cc
- Source input count: 120; recomputed from the preserved build snapshot
- Actual embedded PYZ taraz_integration code-object SHA-256:
  e2c12afc893dff7ab04ba090266e15172309ba4a2e90a6869106fe974e7a457e
- Verified original QA build manifest: QA_BUNDLE_VERIFIED, qaOnly true,
  installed false, releaseReady false, and the three native Taraz Inbox
  methods including tarazIntegrationRecover.

The new runner reuses the previous QA runner's no-link checks, snapshot
inventory, scratch isolation and packed-code loader **read-only**. It reads
the EXE using PyInstaller CArchiveReader, SHA-verifies the embedded Python
code object, then executes only that module in fresh Python -I -B child
processes. It does not run Taraz.exe or taraz_desktop.

## Tests actually executed

- py -3.12 -B scripts/qa_mtr_latest_bundle_recovery_20261110.py --manifest-only
- py -3.12 -B scripts/qa_mtr_latest_bundle_recovery_20261110.py
- py -3.12 -B -m unittest -q tests.test_mtr_latest_bundle_recovery_20261110 tests.test_mtr_taraz_manual_review_recovery_20261110

**All exit 0. The combined suite passed 25/25 tests**: 18 new packed-module
cases plus 7 existing current-source recovery cases. Both new files passed
Python AST syntax checks.

The packed module demonstrated manual recovery after a synthetic **after-move,
before-receipt interruption** for both original decisions: reviewed and
rejected. Each case left the exact original proposal bytes in reviewed,
persisted its source SHA-bound intent, and had no receipt. A fresh process
listed the original recoverable decision. Another fresh process explicitly
invoked recover_review with the QA manual-action gate, produced the
metadata-only receipt, and preserved the exact decision. Subsequent listing
showed no recovery entry and repeat recovery did not rewrite receipt bytes.

Legacy reviewed payloads and review markers without a durable intent were
not offered for recovery and were refused without generating an intent.
Additional negative tests covered missing or duplicated source, modified
source digest, forged financialEventCreated=true intent, absent manual
confirmation, unmarked scratch directories, and forged or mismatched EXE,
manifest, snapshot or PYZ pins.

## Explicit limits

Tests used only marked disposable QA directories, with APPDATA, LOCALAPPDATA,
TEMP, TMP, USERPROFILE and HOME all redirected there. Test directories were
cleaned on completion. No installed program startup, native WebView2,
authenticated live user/role, financial ledger, official invoice or receipt,
LAN peer, network, backup/restore, rollback or power-loss persistence was
validated. This is an **isolated metadata recovery result only**, not P0
release acceptance.

Worker-10 owned and created only the new latest-bundle runner, its test file
and this document. Prior QA runner, original source, installed program,
financial profiles, and release files were not edited.
