# Taraz v1.0.4 RC3 | Returned analytic error masking | 2026-11-11

**Status: SOURCE + VITE QA PASS; independent dynamic Edge QA PENDING.**

Worker27 separately demonstrated that RC2’s management dashboard still
echoed attacker-controlled invoice identifiers: `buildManagementAnalytics`
sometimes **returns** `{error: ...}`; its error need not throw. RC3
therefore keeps the original visible-error condition
`(error||analytics?.error)`, but replaces user-visible
`{error||analytics.error}` with a fixed Persian fallback when `error`
is empty. The locally authored `!validRange` error remains visible.
No other source line is intentionally changed.

Parent RC2 source:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-146b4c62e3f8`
SHA `aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8`.

New create-only RC3:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-ca9761aa43d8`

| Artifact | Observed SHA-256 |
| --- | --- |
| RC3 source **131-file inventory fingerprint** | `e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de` |
| `patched-source-sha256.json` | `b31db9348ad61f132be02788adfbbf5b93cc532f7f25bed25a7c701d8ed4ef11` |
| `stage-report.json` | `2813cbcaeab16b7cbc9ce9b79d19fa3f5c24688cc2906e7fed06352f0a0b0ebe` |

Exactly one source file differs from RC2:
`src/accounting_management_dashboard.jsx`. The package/lock remain
version `1.0.0` baseline so a future separately approved builder may
stamp `1.0.4` only in its own new snapshot.
No original source, RC1/RC2, frozen compiled build or installed user
files were modified.

RC3 detached Vite:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-72ee216638e4`
with `rc3-vite-qa-report.json` status
`V104_RC3_STAGE_UI_ONLY_EDGE_QA_PENDING` and actual compiled JS SHA
`3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9`.
This is not a native executable and is not a new installer.

**Direct worker29 validation:**

```powershell
python -B -m unittest -v tests.test_stage_taraz_v104_rc3_20261111
python -B scripts/stage_taraz_v104_rc3_20261111.py --verify 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-ca9761aa43d8'
```

**10/10 Python tests PASS**, zero skips/errors, exit 0 (4.532 seconds).
Verified actual 131-file SHA inventory, single-file diff scope, JSX Babel
parser, reversed Git patch dry-run, unchanged validRange authored errors,
full RC3 Vite JS/CSS/HTML SHA readback, and rejected old EXE/ZIP hashes.

**Open requirements:** worker27 must run inverted Edge tests on the
**exact RC3 Vite** JS SHA above, including the returned analytics.error
case, Canvas and File.text errors, and retained local validations.
Only then may worker26 begin a **new create-only RC3-native build**
from the separately frozen RC3 source, with independent PE/PYZ/ZIP,
secure operator installer and rollback QA. This RC3 stage alone is NOT
permission for a compiled production release.
