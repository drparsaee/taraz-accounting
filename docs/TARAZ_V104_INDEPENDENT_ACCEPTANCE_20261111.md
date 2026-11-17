# Taraz 1.0.4 P1 | Independent acceptance gate | 2026-11-11

**Verdict: STATIC BINARY CHECKS PASS, PRODUCTION RELEASE NO_GO.**

The genuine worker26 create-only compiled candidate was opened for read-only
binary, source, backup and ZIP verification. The signed-off financial,
installed-GUI, migration and release gates were **not** established.
Subsequent independent worker27 residual Edge testing found *three new*
visible error/host-data echoes. Consequently this original 1.0.4 candidate
is explicitly **REJECTED/NO_GO**; static validity must not be conflated
with security or production approval.

## Frozen candidate selected and inspected

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-6d851f756264`

| Authentic artifact | Independently rehashed SHA-256 |
| --- | --- |
| `binary/Taraz.exe` | `8e2a8026b48e278df95693d9349f5a566df9b75c12497882b3bebca96679adc6` |
| `Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip` | `721bbf8d6fd461fb1317fb1394b26d0ad67237d4fbc8f3d9cbfc8442b5f79777` |
| `offline-update/update-manifest.json` | `116f325052c8db7b5386e0eae937d45db809760fbac42780d3e0d62657b32c75` |
| `build-report.json` | `c2f3ed699c679098e158f8dff619fc440abaf180089ea30a4e5796139bb8027b` |

Actual status is
`PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED`, which means the
builder produced a candidate, **not** that it was installed, approved
or fit for deployment.

### Directly verified by worker29

- Actual Windows PE fixed version `1.0.4.0`; CArchive/PYZ
  `taraz_release_version.APP_VERSION=1.0.4`,
  `QA_ONLY=False` and correct release channel.
- Presence of five required native Madar API methods, five expected
  PYZ modules, and the WebView2 bridge method allowlist.
- Entire compiled UI asset set: **15/15** actual `web/dist` assets equal
  bytes embedded inside the real EXE; embedded JavaScript SHA-256
  `b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453`,
  equal to independently pinned Stage B Vite UI. Different from old v103 JS.
- **131/131** actual source inputs traced to approved Stage B fingerprint
  `6cf6ca02af79100600ad183fec0579c9a5162908bac245d4b220ffa9d57acdd1`;
  build-only package/lock correctly stamped `1.0.4` and native release module.
- **7/7** exact ZIP members rehashed byte-for-byte against detached
  `offline-update` contents. No duplicate or unexpected ZIP file.
- Static installer/activation inspection found explicit `1.0.4` naming,
  `FileInfo.Directory` ancestor traversal, hardlink count, process and
  backup checks, side-by-side creation and atomic pointer replacement.
  **A static text inspection is not an actual Windows negative-path test.**
- Read-only original installed baseline remains `1.0.2`, with
  `versions\1.0.4` absent and EXE SHA-256
  `095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52`.
  All **181** files of the independently attested old cold backup were
  rehashed (124,011,875 bytes). Its prior 67 SQLite checks were **not**
  reexecuted by this independent binary gate.

### Executed commands and tests

From `D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

```powershell
python -B scripts/qa_taraz_v104_independent_acceptance_20261111.py --preflight

$env:TARAZ_V104_BUILD_DIR='D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-6d851f756264'
python -B -m unittest -v tests.test_taraz_v104_independent_acceptance_20261111
Remove-Item Env:TARAZ_V104_BUILD_DIR

python -B scripts/qa_taraz_v104_independent_acceptance_20261111.py --candidate 'D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-6d851f756264'
```

Observed: **15 of 15 tests PASS**, no skips, exit 0 (3.137 seconds).
Candidate CLI exit 0 with status
`STATIC_V104_ARTIFACTS_PASS_BUT_PRODUCTION_NO_GO`.
Negative synthetic tests reject missing candidate, wrong source SHA,
unexpected/missing files, forged version/QA metadata, changed ZIP byte,
duplicate ZIP member, unsafe paths, incomplete installer safety anchors,
and unpinned or contradictory external QA witness.

### Unverified dynamic and operator acceptance

Prime reported that worker27's separate actual Edge tests proved three
**remaining** unsafe Vite UI paths (this is *worker27 evidence*, not
an independent Edge run performed by worker29):

1. `src/accounting_print_designer.jsx:32` emitted raw local Canvas error.
2. `src/accounting_operational_panels.jsx:615` emitted raw `File.text()`
   exception in bank CSV import UI.
3. `src/accounting_management_dashboard.jsx:250/303` echoed an untrusted
   invoice identifier from an analytics **returned error object**, not
   merely from a thrown exception.

The source-only RC2 stage fixed the first two, and the RC3 stage additionally
masks the third returned-error display. These changes **do not alter this
compiled EXE or ZIP**. See RC2/RC3 companion documents for their SHA and
stage provenance.

**Independent disposable PowerShell test scope:** the new script supports a
strictly isolated `--disposable-test` fixture path, but execution of the
actual installer and activator is gated on a separately pinned, **already
executed** worker26 QA report. No such external test witness was supplied
at the point of this first static verdict, and worker29 **did not run the
v1.0.4 PS1 with -Apply**. This must be reported as *unverified*, not a
passing acceptance claim. Worker22's separate v104 operator rollback
requires actual newly pinned candidate and launcher contract; it is not
proven by this static check.

No real financial posting or migration, installed GUI launch, official
finance receipt, production installation/activation, operator rollback,
digital-signature or publish approval was observed here.

**Current release decision:** `NO_GO` for the original
`build-6d851f756264`. A new independently pinned and rebuilt RC3 candidate,
independent Edge anti-echo acceptance, secure installer negative testing,
rollback acceptance and financial/operator gates must precede any
production GO.

