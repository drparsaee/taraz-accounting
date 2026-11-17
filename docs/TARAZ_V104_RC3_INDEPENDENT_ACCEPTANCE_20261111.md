# Taraz 1.0.4 RC3 | Independent downstream acceptance | 2026-11-11

## Decision

**Independent binary / source / ZIP / v102-backup subgate: `GO`.**

**Native Windows disposable install + activation subgate: `GO`.**
After worker26's own **20/20 native PS5.1 PASS**, also independently
rerun and reported by prime, the genuine newly pinned RC3 installer
and activator were exercised by worker29 in a disposable Windows profile.
The worker26 original QA report document was SHA-pinned and checked
before worker29's test began. This was a *previous result witness*,
not a newly rerun worker26 suite by worker29.

**Production release: `NO_GO`.** This does not grant installation, real
activation, financial posting, rollback approval or publication.

The first 1.0.4 build `build-6d851f756264` was rejected by worker27
dynamic Edge leak tests. This independent run inspected the different, newly
compiled and exact SHA-pinned RC3 candidate.

## Actual RC3 candidate and hashes

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\build-0bde36e11d99`

| Artifact independently read byte-by-byte | SHA-256 |
| --- | --- |
| New `binary/Taraz.exe` | `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` |
| `Taraz-v1.0.4-P1-RC3-SECURE-OFFLINE-UPDATE.zip` | `1a9ca13c914385c92be68ffdd2034c723843dde1846fa548762864aa98ac134e` |
| `offline-update/update-manifest.json` | `b6ac2e3050274e3ec8e3bcaaf32b694d673b1747cfab580245136ec500e65bc6` |
| `build-report.json` | `510de237a7fcea8553e0a64951bf76f3f7bef722318585db016d4e602df8b9fb` |
| RC3 canonical fingerprint, 131 source files | `e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de` |
| RC3 `patched-source-sha256.json` | `b31db9348ad61f132be02788adfbbf5b93cc532f7f25bed25a7c701d8ed4ef11` |
| RC3 `stage-report.json` | `2813cbcaeab16b7cbc9ce9b79d19fa3f5c24688cc2906e7fed06352f0a0b0ebe` |
| RC3 detached Vite JavaScript | `3f2fe8b66ad83b0214e1de86b51f8e8be01153fbc7ef9d8eea0b5b79` |
| RC3 `rc3-vite-qa-report.json` | `5940d2765b6a9ff6810078364fb5422c1eb112697f7f02f46156aa85624d69b8` |

Source:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\source-stage-ca9761aa43d8`

Vite:
`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.4-p1\vite-qa-72ee216638e4`

Rejected RC1 EXE SHA
`8e2a8026b48e278df95693d9349f5a566df9b75c12497882b3bebca96679adc6`
was independently rehashed and is different from RC3.

## Evidence directly checked by worker29

1. The real RC3 source stage contained **131/131** manifest-matched
   sources. All file hashes, case-safe relative paths and membership
   were verified. Build-only package/lock version was `1.0.4`.
2. All detached RC3 Vite HTML/CSS/JS hashes matched independently
   pinned Vite evidence. Compiled JS SHA:
   `3f2fe8b66ad83b0214e1de86b51f8e8be01153fbc7ef9d8eea0b5b79`.
3. **Actual Windows EXE** native PE VS_FIXEDFILEINFO was `1.0.4.0`.
   PyInstaller CArchive/PYZ was opened **without launching the EXE**:
   `taraz_release_version.APP_VERSION='1.0.4'`,
   `QA_ONLY=False`, correct channel, five native bridge methods,
   five required PYZ runtime modules, and WebView forwarder present.
4. **All 15 compiled UI assets** in `web/dist` individually matched
   the **actual bytes extracted from the new EXE**. The exact RC3
   JavaScript was among them.
5. **All seven ZIP members** were decompressed and hashed individually
   against loose `offline-update` files; no duplicates/unexpected files.
6. Static installer/activation syntax checked for source/EXE/v102 SHA,
   NTFS hardlink-count guard, junction ancestry, running-process and
   independent-backup prerequisites, `1.0.4` pointer/launcher backup
   naming and atomic pointer replacement. Static syntax is *not* a
   substitute for Windows PowerShell execution.
7. The original cold backup had **181/181 independently rehashed files**
   totalling **124,011,875 bytes**, manifest SHA
   `8d5beae6fb2e5fa9fd5dbc7aadfd73e9568f185299cca1a1abd8b7bb1bcff98d`.
   Previous witness reported 67 SQLite checks; **not rerun** here.
8. The real installed Taraz pointer remains `1.0.2`, old EXE SHA
   `095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52`,
   with real `versions\1.0.4` folder absent.

### Separate upstream QA evidence

The build carries three original SHA-pinned QA witnesses. This independent
gate rehashed their JSON files and checked PASS, exact RC3 source/JS,
zero failures/skips, reported command and staged-only context:

| Witness | Verified checks | JSON SHA |
| --- | --- | --- |
| RC3 source-stage | 10 | `0accc1863a82dadfd057b19ad48c962747b1f2a06290c7937c207d4d958b027f` |
| Original seven host-error inverted Edge | 7 | `1743aaa93d185c1895545b497b324344d25541ef1bde1d2e4df54bf1524ece54` |
| Three residual leak inverted Edge | 3 | `b6db26fceb2197e1125c97e313cf16ff510ddb64ae7eef9d1aaa519928e08f25` |

The prime's separate status indicated **14/14 Vite Edge tests PASS**.
These were *not* newly rerun by worker29, and a staged Edge browser
result is not an installed native WebView2 guarantee.

## Commands and tests actually executed

Run from
`D:\CoS-Test\000- Taraz\taraz-mtr-e2-isolated-20261109`:

```powershell
python -B scripts/qa_taraz_v104_rc3_independent_acceptance_20261111.py
python -B -m unittest -v tests.test_taraz_v104_rc3_independent_acceptance_20261111
```

Observed: CLI exit `0`,
`subgate=RC3_STATIC_BINARY_SOURCE_BACKUP_ZIP_GO` and
**19/19 tests PASS** (5.009 seconds on the final new test suite,
zero failures/errors/skips).

Negative tests cover wrong EXE pin, prior rejected candidate,
tampered and duplicate-member synthetic ZIP, incomplete/extra source,
traversal paths, conflicting external QA evidence and missing worker26
native test witness.

The premature attempt:

```powershell
python -B scripts/qa_taraz_v104_rc3_independent_acceptance_20261111.py --disposable-test
```

**correctly failed closed with exit 2**:
`RC3 INDEPENDENT NO_GO: NoGo: Worker26 prior RC3 native QA witness was not supplied`.
No PowerShell installer/activator execution occurred in that run.

### Independently executed disposable Windows PS5.1 gate

The new script exercised a strictly isolated private profile fixture
with fresh synthetic `LOCALAPPDATA` / `APPDATA` / `USERPROFILE` / `TEMP`
and an invented nonfinancial sentinel. It copies real pinned EXE bytes
but never launches them. It successfully checked preflight, side-by-side install,
atomic `1.0.4` pointer activation, both retained EXEs, backup file names,
hardlink/junction rejection, process-running refusal and CIM failure,
and rehashed production v102 and backup before and after completion.

Verified prior worker26 source report:
`docs/TARAZ_V104_P1_SECURE_RC2_20261111.md`
SHA `6f4dafda65de6095f200be7cdd48306136592369d4819eefb9a0372ce54b310d`.
Its documented native PS5.1 result was **20/20 PASS, 0 skipped** with
the exact RC3 binary SHA; prime separately reported rerunning it with
20/20 PASS. This is an original SHA-pinned Markdown completion report,
not a fabricated JSON witness.

The actual command executed:

```powershell
python -B scripts/qa_taraz_v104_rc3_independent_acceptance_20261111.py --disposable-test --use-pinned-worker26-doc
```

**Exit code 0**, status
`RC3_STATIC_AND_DISPOSABLE_GO_PRODUCTION_NO_GO`,
with `disposable.subgate=RC3_DISPOSABLE_INSTALL_ACTIVATION_GO`.
The following fourteen distinct bounded checks were reported from the
actual disposable fixture:

- Preflight with no `-Apply` and pointer unchanged
- Side-by-side `-Apply` installation of actual RC3 EXE bytes
- Preflight of activation with no `-Apply`
- Atomic 1.0.4 pointer activation with `-Apply`
- Original 1.0.2 pointer backup readback
- Versioned launcher backup SHA readback
- Original 1.0.2 and new 1.0.4 EXE SHA readbacks
- Synthetic finance sentinel unchanged
- Duplicate activation refused
- Duplicate create-only install refused
- Hardlinked pointer refused
- Synthetic running Taraz process refused
- Synthetic process-enumeration failure refused
- NTFS junction within required version-directory ancestor refused

The proof is limited to this synthetic Windows filesystem profile.
Real installed v102 pointer and 181-file backup rehashes were identical
before and after. No real app executable was launched or posted finance.

## Limitations and remaining gates

This worker did not launch compiled Taraz or test actual installed GUI,
financial posting, data migration, production activation, signing,
operator rollback or real ledger effects. Worker22's **dedicated RC3
rollback** requires new pins and independent acceptance before
publication. The ZIP reports `unsigned=true`.

**Conclusion: static RC3 subgate GO; disposable PS5.1 subgate GO;
release production NO_GO.**
