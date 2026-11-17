# Taraz v1.0.3 Secure Repackage: Independent P1 Acceptance

**2026-11-11. Final release decision: NO_GO.** This work repairs packaging path and hardlink protections only. The frozen v1.0.3 executable remains unchanged and separately contains HIGH severity host-error leaks reported by worker27. This is a QA-only preservation package, **not a production-approved installer**.

## Original vulnerability and preserved baseline

The diagnostic at D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v103-safepath-diagnostic-20261111/safepath-diagnostic.json recorded both frozen installer and activator as accepting a file reached through a junction. Their Windows PowerShell 5.1 SafePath loop used FileInfo.Parent, which fails to walk the file's ancestor directories. ReparsePoint alone also cannot distinguish a second NTFS hardlink.

Frozen source, compiled executable, original ZIP, manifest, installed baseline and backup were **read-only** throughout this work. The original ZIP SHA-256 is **4e46df72c488f824b9a5eb9683b8d7f32b7d1f94d4af2858f9c8623b40ca0eae** and remains UNSAFE.

## Canonical create-only secure output

Folder: D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.3-p1/secure-repackage-be460926d766

| Item | Recomputed SHA-256 |
| --- | --- |
| Unchanged Taraz.exe | e81003a339cabd0c17965f467111560fe72cb8595186c8cec3b7a3d37764ca1c |
| **New secure offline ZIP** | **1a5cf09709e755e194dab93f677f7f087ae359a5affaa80541be2812ab4f1112** |
| New update-manifest.json | 6910a09d29a667a3af6aaf4d11f5154e1052847b28e9790315a7d395ee980bd6 |
| New Install-Taraz-V103.ps1 | c2ba2503038583d87ccf41003490e43bfd3cc0af70d6f8e06dedb8f165242314 |
| New Activate-Taraz-V103.ps1 | a23b47888e62899f8b54f97366fe23ce610462e2c632db38512fce55e751cd40 |
| Original update manifest (unchanged) | 0f76af740467a1630be9aca7477df5f4a920fdfc879a9aa68a29807f5ecac634 |

All **7** ZIP members were independently SHA-256 compared with the new offline-update folder. The unchanged compiled EXE, package.json, package-lock.json and source-sha256.json retain their original individually pinned bytes. Original build report fingerprint is 5303e16ed411d55b34aa81178a79b7e883dd4d56b7e5210ce068dffebb9fbf94. The old source fingerprint is a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279.

The create-only package includes a **separate operator-rollback companion** under operator-rollback/, not inside the 7-member ZIP. It copies exclusively worker29's latest rollback-gate-3714fee2ca06, with pinned script SHA-256 39b62821db04b3c2fc8de783148bf1e374113802fa1d36702cb89ab50c970c5a and manifest SHA-256 dcf868d2f483c7514ce5f80c3713850a14d78aa2e1d71d6aeb8c9700af7be1f6. Its independent installation integration has not been tested as part of this task. Earlier provisional secure-repackage-b6ae0b74da3e is superseded, since it lacks this companion.

## Hardened PowerShell 5.1 behavior

1. **Every ancestor is checked.** The replacement SafePath uses FileInfo.Directory followed by DirectoryInfo.Parent and rejects the ReparsePoint attribute at each level. Local absolute Windows drive paths are required, while relative paths, traversal, UNC and ambiguous alternate streams are refused.
2. **Real NTFS hardlink checks.** A read-attributes-only Windows CreateFileW / GetFileInformationByHandle call verifies link count equals exactly **1**. An unavailable count, a count above one, or a check failure blocks execution. The check includes packaged scripts and other members, backup files, pointer, launcher, and both old/new EXEs.
3. **Create-only writes and backups.** The new executable is created without overwriting, activation creates a versioned pointer backup via atomic File.Replace, and an additional launcher backup named Run-Taraz-pre-1.0.3.cmd is created without overwriting. Both backups are checked, including launcher SHA equality.
4. **Bounded input/data scope.** The fresh backup's manifest and report hashes, individually inventoried backup-file hashes and byte limits, source/EXE/package hashes, no-running-Taraz guard and version pointers are checked before writes. File enumeration is bounded and does not blindly traverse junctions.

These checks close the **demonstrated** nested junction and NTFS hardlink defects. This does not establish protection against a hostile concurrent filesystem namespace-swap race: handle-anchored creation/replacement would be needed for that stronger guarantee.

## Native test evidence

Environment: Windows PowerShell **5.1** using actual script execution on a new, disposable LOCALAPPDATA. Real pinned v1.0.2 and v1.0.3 executables were **copied** into the private fixture. The 181-file cold-backup witness was read-only. Financial data in the fixture is an invented canary; the EXE was never launched.

Command from the detached Taraz project:

    py -3.12 -B -m unittest -v tests.test_taraz_v103_secure_repackage_20261111
    py -3.12 -B scripts/taraz_v103_secure_repackage_20261111.py --verify D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.3-p1/secure-repackage-be460926d766

The tests check:

- PowerShell 5.1 AST parsing and real dry-run, installation, activator dry-run, activation, readback and launcher/pointer backup retention.
- Negative nested junctions in the Programs install hierarchy, package location, and new-version EXE folder.
- Negative hardlinked pointer, old EXE, new EXE, package EXE and launcher, including checks specifically during activation.
- Negative missing backup path and independently tampered staged bytes.
- Unchanged old executable, launcher and an isolated synthetic-finance file after each test.

**All 17 tests passed (0 failures, 0 skips) in the completed suite.** The script generator and test harness do not alter installed Taraz, user accounts, production profiles, original backup records, local services or the existing frozen EXE and ZIP.

## Outstanding NO_GO gates

Worker27 reported **seven raw secret/error exposure cases** from the frozen v1.0.3 compiled user interface. Since the secure ZIP includes that same executable hash, the vulnerability remains present. Separately, signing, real finance posting and migration, login/role-controlled Madar actions, full rollback integration and explicit release authority remain unresolved.

**Repackage QA passed. Production update: NO_GO.** The secure installer functions are reusable as an independently tested starting point for a later fixed-runtime release, but the v1.0.3 executable must not be approved merely because its ZIP is now better protected.
