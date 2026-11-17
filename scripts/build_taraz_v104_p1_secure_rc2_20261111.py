"""Create-only native Taraz v1.0.4 RC2 builder with independent QA gates.

This builder NEVER patches the original v1.0.4 RC1 builder, stage, EXE, ZIP,
installed application, profile or ledger. It reads a NEW, externally frozen
131-input RC2 source stage. It requires new, SHA-pinned worker29 stage+Vite
and independent Edge proof of both original seven and residual three leaks.

Without all attested inputs, --build fails BEFORE creating a build directory.
Successful output is still a noninstalled, unsigned QA candidate, NOT GO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import build_taraz_v104_p1_secure_release_20261111 as rc1

BuildBlocked = rc1.BuildBlocked
OUTPUT = rc1.OUTPUT
BASE_STAGE = rc1.STAGE
BASE_SHA = rc1.STAGE_SHA
BASE_MANIFEST_SHA = rc1.STAGE_INVENTORY_FILE_SHA
RC1_EXE_SHA = "8e2a8026b48e278df95693d9349f5a566df9b75c12497882b3bebca96679adc6"
RC1_JS_SHA = "b72441a9ed6413e5260f861add679f99979192ba228a476eaa6220a21504f453"
RC1_REPORT_SHA = "c2f3ed699c679098e158f8dff619fc440abaf180089ea30a4e5796139bb8027b"
RC1_RUN = OUTPUT / "build-6d851f756264"
FAILED_RC2_STAGE = OUTPUT / "source-stage-146b4c62e3f8"
FAILED_RC2_SHA = "aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8"
FAILED_RC2_MANIFEST_SHA = "33892e1772ba79a5476dc69520d0e79197a5adcd2ec1bba797c98974032129f7"
FAILED_RC2_REPORT_SHA = "72171484e6e509244ef16e61cadb4d6eeab8e987f50edd399d93c8a1d360c4e9"
FAILED_RC2_JS_SHA = "39295ea85bf2d6ee9fd94fce862c2bc505d4ac6ce01153fbc7ef9d8eea0b5b79"
RC3_STAGE = OUTPUT / "source-stage-ca9761aa43d8"
RC3_SOURCE_SHA = "e2f5da849743df6627f24862b1f7613781fb000890adb0aac8a75b17651cf1de"
RC3_MANIFEST_SHA = "b31db9348ad61f132be02788adfbbf5b93cc532f7f25bed25a7c701d8ed4ef11"
RC3_STAGE_REPORT_SHA = "2813cbcaeab16b7cbc9ce9b79d19fa3f5c24688cc2906e7fed06352f0a0b0ebe"
RC3_VITE = OUTPUT / "vite-qa-72ee216638e4"
RC3_VITE_JS_SHA = "3f2fe8b66ad83b0214e1de86b51f8e8be0112fb34c29ce1d2ba46411391feea9"
RC3_VITE_REPORT_SHA = "5940d2765b6a9ff6810078364fb5422c1eb112697f7f02f46156aa85624d69b8"
COUNT = 131
EXTRA_PATHS = frozenset({
    "src/accounting_print_designer.jsx",
    "src/accounting_operational_panels.jsx",
    "src/accounting_management_dashboard.jsx",
})
ALLOWED_INVENTORIES = frozenset({
    "patched-source-sha256.json",
    "rc2-source-sha256.json",
    "rc2-patched-source-sha256.json",
})
EXPECTED_QA = {
    "rc2-source-stage": 10,
    "rc2-original-seven-edge": 7,
    "rc2-residual-three-edge": 3,
}


def _sha(path: Path, cap: int = rc1.MAX_SOURCE_BYTES) -> str:
    return rc1._sha(path, cap=cap)


def _json(path: Path) -> dict:
    return rc1._json(path)


def _pin(value: str, context: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise BuildBlocked("Explicit lowercase SHA-256 required for " + context)
    return value


def fixed_rc1_preflight() -> dict:
    """Read-only immutable baseline; RC2 cannot silently start from v103/RC1."""
    root = rc1._regular(RC1_RUN, folder=True)
    report_path = root / "build-report.json"
    if _sha(report_path) != RC1_REPORT_SHA:
        raise BuildBlocked("Original RC1 build report changed")
    report = _json(report_path)
    if (report.get("sourceFreezeSha256") != BASE_SHA
            or report.get("status") != "PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED"
            or report.get("sourceFileCount") != COUNT
            or report.get("compiled", {}).get("peVersion") != "1.0.4.0"
            or report.get("compiled", {}).get("pyzVersion") != "1.0.4"
            or report.get("installed") is not False
            or report.get("pointerChanged") is not False):
        raise BuildBlocked("RC1 immutable release baseline inconsistent")
    exe = root / "binary" / "Taraz.exe"
    if _sha(exe, cap=rc1.MAX_EXE_BYTES) != RC1_EXE_SHA:
        raise BuildBlocked("RC1 frozen EXE changed")
    baseline = rc1.source_preflight()
    if baseline["sourceSha256"] != BASE_SHA:
        raise BuildBlocked("RC1 applied source no longer matches")
    return {"run": str(RC1_RUN), "exeSha256": RC1_EXE_SHA,
            "buildReportSha256": RC1_REPORT_SHA,
            "sourceSha256": baseline["sourceSha256"],
            "inventory": baseline["snapshot"]}


def source_preflight(stage: Path, *, source_sha: str, inventory_sha: str,
                     stage_report_sha: str, inventory_name: str) -> dict:
    """Rehash all 131 actual RC3 bytes, and 3 repaired files versus RC1.

    RC2's dynamic bank/print improvements passed, but the analytics error
    still leaked a host-controlled invoice key; no RC2 output is admissible.
    """
    _pin(source_sha, "RC2 131 source digest")
    _pin(inventory_sha, "RC2 source manifest file")
    _pin(stage_report_sha, "RC2 producer stage-report file")
    if stage is None:
        raise BuildBlocked("Explicit RC3 stage path and SHA pins required")
    stage = Path(stage).absolute()
    rc1._regular(stage, folder=True)
    if stage != RC3_STAGE:
        raise BuildBlocked("Only SHA-pinned RC3 source-stage-ca9761aa43d8 can be built")
    if (source_sha != RC3_SOURCE_SHA or inventory_sha != RC3_MANIFEST_SHA
            or stage_report_sha != RC3_STAGE_REPORT_SHA):
        raise BuildBlocked("Exact independently observed RC3 source/report hashes required")
    if stage in (BASE_STAGE, FAILED_RC2_STAGE):
        raise BuildBlocked("Failed RC1/RC2 stage cannot be relabeled as repaired RC3")
    if inventory_name not in ALLOWED_INVENTORIES:
        raise BuildBlocked("Unexpected RC2 source manifest filename")
    manifest_file = stage / inventory_name
    report_file = stage / "stage-report.json"
    if _sha(manifest_file) != inventory_sha:
        raise BuildBlocked("RC2 source manifest bytes not pinned")
    if _sha(report_file) != stage_report_sha:
        raise BuildBlocked("RC2 producer report bytes not pinned")
    old = fixed_rc1_preflight()
    items = _json(manifest_file)
    if len(items) != COUNT or rc1.inventory_sha(items) != source_sha:
        raise BuildBlocked("RC2 131-input fingerprint does not match actual manifest")
    if items.keys() != old["inventory"].keys():
        raise BuildBlocked("RC2 source membership differs from 131-file RC1")
    modified = {name for name in items if items[name] != old["inventory"][name]}
    if modified != EXTRA_PATHS:
        raise BuildBlocked("RC2 must change exactly the three approved additional JSX files")
    source_dir = stage / "source"
    rc1._regular(source_dir, folder=True)
    present = set()
    for name, expected in items.items():
        if _sha(source_dir / rc1._rel(name)) != expected:
            raise BuildBlocked("RC2 actual source file SHA differs: " + name)
        present.add(name)
    enumerated = set()
    for parent, dirs, files in os.walk(source_dir, followlinks=False):
        for dirname in dirs:
            rc1._regular(Path(parent) / dirname, folder=True)
        for filename in files:
            file = rc1._regular(Path(parent) / filename)
            enumerated.add(file.relative_to(source_dir).as_posix())
    if present != enumerated:
        raise BuildBlocked("RC2 source directory contains unpinned files/links")
    report = _json(report_file)
    status = report.get("status")
    if not (
        status == "V104_RC3_SOURCE_ONLY_EDGE_QA_PENDING"
        and report.get("sourceCount") == COUNT
        and report.get("sourceSha256") == source_sha
        and report.get("sourceInventoryFileSha256") == inventory_sha
        and report.get("executableBuilt") is False
        and report.get("releaseApproved") is False
        and report.get("dynamicEdgeApproved") is False
        and report.get("startingSourceSha256") == FAILED_RC2_SHA
        and report.get("parentStage") == str(FAILED_RC2_STAGE)
        and report.get("originalRC2StageUnchanged") is True
        and report.get("originalV104CandidateUnchanged") is True
        and report.get("originalV104CandidateModified") is False
        and report.get("stagedPackageVersionUntouched") == "1.0.0"
        and set(report.get("changedSourceFiles", []))
            == {"src/accounting_management_dashboard.jsx"}
    ):
        raise BuildBlocked("Unreviewed/ambiguous RC3 frozen-source stage report")
    # Verify RC3 was derived from the real preceding RC2 patch and changes
    # only the remaining dashboard sink rather than replacing unrelated UI.
    rc1._regular(FAILED_RC2_STAGE, folder=True)
    if (_sha(FAILED_RC2_STAGE / "patched-source-sha256.json") != FAILED_RC2_MANIFEST_SHA
            or _sha(FAILED_RC2_STAGE / "stage-report.json") != FAILED_RC2_REPORT_SHA):
        raise BuildBlocked("Failed RC2 baseline source/witness drift")
    previous = _json(FAILED_RC2_STAGE / "patched-source-sha256.json")
    if rc1.inventory_sha(previous) != FAILED_RC2_SHA:
        raise BuildBlocked("Failed RC2 baseline fingerprint drift")
    incremental = {name for name in items if items[name] != previous.get(name)}
    if incremental != {"src/accounting_management_dashboard.jsx"}:
        raise BuildBlocked("RC3 must repair only one remaining dashboard JSX file versus RC2")
    pkg, lock = _json(source_dir / "package.json"), _json(source_dir / "package-lock.json")
    if (pkg.get("name") != "taraz-accounting"
            or lock.get("name") != "taraz-accounting"
            or [pkg.get("version"), lock.get("version"),
                lock.get("packages", {}).get("", {}).get("version")] != ["1.0.0"] * 3):
        raise BuildBlocked("RC2 version/package-lock inputs are not original 1.0.0")
    return {
        "stage": str(stage), "source": str(source_dir),
        "sourceSha256": source_sha, "sourceCount": COUNT,
        "inventorySha256": inventory_sha, "inventoryName": inventory_name,
        "stageReportSha256": stage_report_sha, "status": status,
        "additionalFiles": sorted(modified), "incrementalFiles": sorted(incremental),
        "snapshot": items,
    }


def vite_preflight(proof: dict, *, vite_dir: Path, vite_js_sha: str,
                   vite_report_sha: str) -> dict:
    """Pin worker29 NEW Vite HTML/CSS/JS bytes to the RC2 source, not RC1."""
    _pin(vite_js_sha, "RC2 Vite JS")
    _pin(vite_report_sha, "RC2 Vite QA report")
    if vite_js_sha in (RC1_JS_SHA, FAILED_RC2_JS_SHA) or vite_js_sha != RC3_VITE_JS_SHA:
        raise BuildBlocked("RC1/failing RC2 compiled JavaScript reused instead of RC3")
    if vite_dir is None:
        raise BuildBlocked("Explicit pinned RC3 Vite stage required")
    vite_dir = Path(vite_dir).absolute()
    rc1._regular(vite_dir, folder=True)
    if vite_dir != RC3_VITE or vite_report_sha != RC3_VITE_REPORT_SHA:
        raise BuildBlocked("RC2 Vite directory outside allowed isolated root")
    report_file = vite_dir / "rc3-vite-qa-report.json"
    if _sha(report_file) != vite_report_sha:
        raise BuildBlocked("RC2 Vite report SHA changed")
    report = _json(report_file)
    if not (
        "RC3" in str(report.get("status", ""))
        and "STAGE_UI_ONLY" in str(report.get("status", ""))
        and report.get("sourceCount") == COUNT
        and report.get("compiledExe") is False
        and report.get("releaseApproved") is False
        and report.get("originalV104CandidateUnchanged") is True
        and report.get("stage", report.get("sourceStagePath")) == proof["stage"]
        and report.get("sourceSha256", report.get("patchedSourceSha256")) == proof["sourceSha256"]
        and report.get("sourceInventoryFileSha256", report.get("sourceInventorySha256")) == proof["inventorySha256"]
        and report.get("sourceStageReportSha256") == proof["stageReportSha256"]
        and report.get("jsSha256", report.get("viteJsSha256")) == vite_js_sha
        and report.get("dynamicEdgeApproved", report.get("browserQaVerified")) is False
    ):
        raise BuildBlocked("RC2 Vite stage does not match frozen source or is not staged-only")
    ui: dict[str, dict] = {}
    for field, digest_key in [
        ("htmlRelativePath", "htmlSha256"),
        ("jsRelativePath", "jsSha256"),
        ("cssRelativePath", "cssSha256"),
    ]:
        name = rc1._rel(report.get(field))
        if name.parts[0] != "dist" or len(name.parts) > 4:
            raise BuildBlocked("Vite asset path outside isolated dist")
        checksum = _sha(vite_dir / name)
        known = report.get(digest_key, report.get("vite" + digest_key[0].upper() + digest_key[1:]))
        if checksum != known:
            raise BuildBlocked("RC2 Vite stage asset bytes differ: " + field)
        ui[field] = {"relative": name.as_posix(), "sha256": checksum}
    return {"root": str(vite_dir), "reportSha256": vite_report_sha,
            "jsSha256": vite_js_sha, "ui": ui}


def qa_preflight(proof: dict, vite: dict, *, witnesses: dict[str, tuple[Path, str]]) -> dict:
    """Independent source-stage, seven-inverse, and three-inverse Edge proofs.

    Witnesses are produced outside this builder and must include actual run
    identities, counts, stage pin, Vite SHA, and explicit STAGE_UI_ONLY mode.
    """
    if set(witnesses) != set(EXPECTED_QA):
        raise BuildBlocked("Three separate QA witness groups are mandatory")
    accepted = {}
    for kind, minimum in EXPECTED_QA.items():
        file, expected_hash = witnesses[kind]
        _pin(expected_hash, kind + " witness")
        if file is None:
            raise BuildBlocked(kind + " independently SHA-pinned QA witness path required")
        file = rc1._regular(Path(file), cap=rc1.MAX_REPORT_BYTES)
        if file.parent == Path(proof["stage"]) or file.parent == Path(vite["root"]):
            raise BuildBlocked("QA witness may not be producer's RC2 stage report")
        if _sha(file) != expected_hash:
            raise BuildBlocked(kind + " QA witness bytes changed")
        report = _json(file)
        if not (
            report.get("kind") == kind
            and report.get("status") == "PASS"
            and report.get("sourceStage") == proof["stage"]
            and report.get("sourceSha256") == proof["sourceSha256"]
            and report.get("sourceCount") == COUNT
            and report.get("failures") == 0
            and report.get("skipped") == 0
            and report.get("exitCode") == 0
            and isinstance(report.get("checksPassed"), int)
            and report["checksPassed"] >= minimum
            and isinstance(report.get("command"), str)
            and bool(report["command"].strip())
        ):
            raise BuildBlocked(kind + " independent QA PASS/command evidence absent")
        if kind != "rc2-source-stage" and not (
            report.get("verifiedMode") in ("STAGE_UI_ONLY", "RC3_INVERTED_STAGE_UI_ONLY")
            and report.get("viteQaRoot") == vite["root"]
            and report.get("viteJsSha256") == vite["jsSha256"]
            and report.get("financialCommands") == 0
            and report.get("compiledNativeExeTested") is False
        ):
            raise BuildBlocked(kind + " must prove new STAGE_UI_ONLY Edge fixture")
        accepted[kind] = {
            "path": str(file), "sha256": expected_hash, "checksPassed": report["checksPassed"],
            "kind": kind, "verifiedMode": report.get("verifiedMode", "SOURCE_STAGE_ONLY"),
        }
    return accepted


def secure_scripts(exe_sha: str, source_sha: str, inventory_sha: str) -> dict[str, str]:
    """Transform only the two pinned RC1 secure PS5.1 templates, not RC1 files."""
    _pin(exe_sha, "new RC2 EXE")
    _pin(source_sha, "new RC2 source")
    _pin(inventory_sha, "new RC2 manifest")
    if exe_sha in (RC1_EXE_SHA, rc1.V103_EXE_SHA) or source_sha == BASE_SHA:
        raise BuildBlocked("Refusing recycled RC1/v103 EXE or source for RC2")
    scripts = rc1.secure_installation_scripts("1" * 64, rc1.STAGE_SHA)
    result = {}
    for name, text in scripts.items():
        if (text.count("1" * 64) != 4 or
                text.count(BASE_SHA) < 1 or
                text.count(BASE_MANIFEST_SHA) != 1):
            raise BuildBlocked("RC1 secure template changed; cannot safely retarget")
        updated = text.replace("1" * 64, exe_sha)
        updated = updated.replace(BASE_SHA, source_sha)
        updated = updated.replace(BASE_MANIFEST_SHA, inventory_sha)
        if (BASE_SHA in updated or BASE_MANIFEST_SHA in updated
                or "1.0.3" in updated or "V103" in updated
                or "TarazV104SecureLinkInfo" not in updated
                or "$parent=$item.Directory" not in updated
                or "GetFileInformationByHandle" not in updated):
            raise BuildBlocked("Unsafe RC2 secure PowerShell source transformation")
        result[name] = updated
    # The source SHA in CheckPackagePins must equal RC2 input, while
    # installed 1.0.2 baseline binary SHA remains unchanged.
    for script in result.values():
        if rc1.BASE_SHA not in script or source_sha not in script:
            raise BuildBlocked("RC2 secure installer lost old binary/source independent pins")
    return result


def package(run: Path, exe: Path, source: dict, stamped: dict, observed: dict,
            baseline: dict, proof: dict, vite: dict, qa: dict) -> dict:
    """Build seven exact SHA-pinned ZIP members, without an obsolete rollback."""
    new_exe_sha = _sha(exe, cap=rc1.MAX_EXE_BYTES)
    if new_exe_sha in (RC1_EXE_SHA, rc1.V103_EXE_SHA) or observed.get("peVersion") != "1.0.4.0":
        raise BuildBlocked("New native binary did not change from RC1/v103")
    scripts = secure_scripts(new_exe_sha, proof["sourceSha256"], proof["inventorySha256"])
    target = run / "offline-update"
    target.mkdir(exist_ok=False)
    with exe.open("rb") as f, (target / "Taraz.exe").open("xb") as o:
        shutil.copyfileobj(f, o, 1024 * 1024)
    if _sha(target / "Taraz.exe", cap=rc1.MAX_EXE_BYTES) != new_exe_sha:
        raise BuildBlocked("RC2 copied binary failed SHA readback")
    for name, text in scripts.items():
        with (target / name).open("x", encoding="utf-8", newline="\n") as out:
            out.write(text)
    for name in ("package.json", "package-lock.json"):
        with (run / "source" / name).open("rb") as old, (target / name).open("xb") as dest:
            shutil.copyfileobj(old, dest, 1024 * 1024)
    mf = target / "source-sha256.json"
    with mf.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(source, out, sort_keys=True, indent=2)
        out.write("\n")
    manifest = {
        "schemaVersion": 1, "application": "Taraz", "releaseCandidateRevision": "RC3",
        "targetVersion": "1.0.4", "installedBaselineVersion": "1.0.2",
        "installedBaselineSha256": rc1.BASE_SHA,
        "qaOnly": False, "productionCandidate": True, "unsigned": True,
        "installed": False, "pointerActivated": False, "realLedgerModified": False,
        "activationApprovalGranted": False, "financePostingProven": False,
        "installedGuiTested": False, "compiledEdgeRedactionApproved": False,
        "previousVersionRetained": "1.0.2",
        "freshIndependentBackupRequired": True,
        "freshIndependentBackupVerified": False,
        "defaultDataRoot": "%APPDATA%\\Taraz",
        "launcherContract": "versions\\%TARAZ_VERSION%\\Taraz.exe",
        "exeSha256": new_exe_sha, "exeBytes": exe.stat().st_size,
        "peVersion": observed["peVersion"], "pyzVersion": observed["pyzVersion"],
        "sourceSnapshotSha256": proof["sourceSha256"],
        "sourceFilesCount": COUNT, "sourceFileManifestSha256": _sha(mf),
        "stagedVersionSourceSha256": stamped,
        "stagedPackageSha256": _sha(target / "package.json"),
        "stagedLockSha256": _sha(target / "package-lock.json"),
        "compiledEvidence": observed, "installedBaseline": baseline,
        "installScriptSha256": _sha(target / "Install-Taraz-V104.ps1"),
        "activationScriptSha256": _sha(target / "Activate-Taraz-V104.ps1"),
        "secureRepackage": {
            "schemaVersion": 1,
            "sourceStageInventorySha256": proof["inventorySha256"],
            "sourceStageReportSha256": proof["stageReportSha256"],
            "sourceStagePath": proof["stage"],
            "hardlinkAndAncestorGuard": "Win32-linkcount-and-each-ancestor",
            "launcherBackupName": "Run-Taraz-pre-1.0.4.cmd",
            "pathPolicy": "local-absolute-no-reparse-no-hardlinks",
            "viteStage": vite,
            "qa": qa,
            "rollbackIncluded": False,
            "rollbackReason": "RC3 dedicated rollback requires actual new binary SHA",
            "productionApproved": False,
        },
    }
    meta = target / "update-manifest.json"
    with meta.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(manifest, out, sort_keys=True, indent=2, ensure_ascii=True)
        out.write("\n")
    zip_path = run / "Taraz-v1.0.4-P1-RC3-SECURE-OFFLINE-UPDATE.zip"
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(target.iterdir()):
            archive.write(file, file.name)
    unpacked = {p.name: _sha(p, cap=rc1.MAX_EXE_BYTES) for p in target.iterdir()}
    expected_names = {
        "Taraz.exe", "Install-Taraz-V104.ps1", "Activate-Taraz-V104.ps1",
        "package.json", "package-lock.json", "source-sha256.json",
        "update-manifest.json",
    }
    if set(unpacked) != expected_names:
        raise BuildBlocked("RC2 offline package members wrong or old rollback included")
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if len(members) != 7 or set(archive.namelist()) != expected_names:
            raise BuildBlocked("RC2 ZIP missing or duplicate member")
        for member in members:
            if (member.is_dir() or member.file_size > rc1.MAX_EXE_BYTES
                    or hashlib.sha256(archive.read(member.filename)).hexdigest()
                    != unpacked[member.filename]):
                raise BuildBlocked("RC2 ZIP member SHA mismatch: " + member.filename)
    return {
        "exe": str(exe), "exeSha256": new_exe_sha,
        "zip": str(zip_path), "zipSha256": _sha(zip_path, cap=rc1.MAX_EXE_BYTES),
        "manifest": str(meta), "manifestSha256": _sha(meta),
        "installScriptSha256": unpacked["Install-Taraz-V104.ps1"],
        "activationScriptSha256": unpacked["Activate-Taraz-V104.ps1"],
    }


def build(*, stage: Path, source_sha: str, inventory_sha: str, stage_report_sha: str,
          inventory_name: str, vite_dir: Path, vite_js_sha: str,
          vite_report_sha: str, witnesses: dict[str, tuple[Path, str]]) -> Path:
    """All real input gates run BEFORE a build-* directory is created."""
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise BuildBlocked("Windows Python 3.12 required for real native build")
    proof = source_preflight(stage, source_sha=source_sha,
                             inventory_sha=inventory_sha, stage_report_sha=stage_report_sha,
                             inventory_name=inventory_name)
    vite = vite_preflight(proof, vite_dir=vite_dir, vite_js_sha=vite_js_sha,
                          vite_report_sha=vite_report_sha)
    qa = qa_preflight(proof, vite, witnesses=witnesses)
    installed = rc1.installed_preflight()
    rc1._regular(OUTPUT, folder=True)
    run = OUTPUT / ("build-" + uuid.uuid4().hex[:12])
    run.mkdir(exist_ok=False)
    result_file = run / "build-report.json"
    report = {
        "status": "IN_PROGRESS", "version": "1.0.4", "releaseCandidateRevision": "RC3",
        "output": str(run), "sourceFreezeSha256": source_sha,
        "sourceFileCount": COUNT, "sourceStagePath": proof["stage"],
        "sourceStageReportSha256": proof["stageReportSha256"],
        "installed": False, "pointerChanged": False, "realLedgerModified": False,
        "stagedRedactionApproved": True, "compiledRedactionApproved": False,
        "releaseApproved": False, "qaBeforeBuild": qa,
    }
    try:
        snapshot = run / "source"
        rc1.base.snapshot_source(Path(proof["source"]), snapshot, proof["snapshot"])
        staged = rc1.stage_version(snapshot)
        from scripts.qa_mtr_taraz_build_20261110 import _trusted_modules, _safe_copytree
        _safe_copytree(_trusted_modules(), snapshot / "node_modules")
        env = rc1.base.offline_environment(run)
        dist = run / "web" / "dist"
        dist.parent.mkdir()
        rc1.base.run_command(
            [shutil.which("node") or "node",
             str(snapshot / "node_modules" / "vite" / "bin" / "vite.js"),
             "build", "--config", str(snapshot / "vite.config.js"),
             "--outDir", str(dist), "--emptyOutDir"],
            cwd=snapshot, env=env, log=run / "vite-build.log", timeout=240,
        )
        if not (dist / "accounting.html").is_file():
            raise BuildBlocked("RC2 Vite accounting.html missing")
        for asset in vite["ui"].values():
            relative = asset["relative"].removeprefix("dist/")
            if _sha(dist / rc1._rel(relative)) != asset["sha256"]:
                raise BuildBlocked("RC2 native Vite asset differs from worker29/27 QA stage")
        pe = run / "taraz-v104-rc2-pe-version.txt"
        rc1.pe_resource(pe)
        binary = run / "binary"
        binary.mkdir()
        rc1.base.run_command(
            [sys.executable, "-B", "-m", "PyInstaller", "--onefile",
             "--windowed", "--noconfirm", "--version-file", str(pe), "--name", "Taraz",
             "--hidden-import", "taraz_madar_data_reader",
             "--hidden-import", "standalone_accounting_template_store",
             "--hidden-import", "taraz_integration",
             "--hidden-import", "personal_parsian_bridge",
             "--hidden-import", "standalone_accounting_auto_backup",
             "--icon", str(snapshot / "assets" / "taraz.ico"),
             "--add-data", str(dist) + ";dist", "--distpath", str(binary),
             "--workpath", str(run / "pyinstaller" / "work"),
             "--specpath", str(run / "pyinstaller" / "spec"),
             "--paths", str(snapshot), str(snapshot / "taraz_desktop.py")],
            cwd=snapshot, env=env, log=run / "pyinstaller-build.log", timeout=780,
        )
        exe = binary / "Taraz.exe"
        rc1._regular(exe, cap=rc1.MAX_EXE_BYTES)
        native = rc1.inspect_binary(exe, dist)
        if (_sha(exe, cap=rc1.MAX_EXE_BYTES) == RC1_EXE_SHA or
                any(x in (RC1_JS_SHA, FAILED_RC2_JS_SHA)
                    for x in native["compiledJsSha256"].values())):
            raise BuildBlocked("Old RC1/failing RC2 compiled binary or JS reused")
        if (source_preflight(stage, source_sha=source_sha, inventory_sha=inventory_sha,
                             stage_report_sha=stage_report_sha,
                             inventory_name=inventory_name)["sourceSha256"] != source_sha):
            raise BuildBlocked("RC2 source changed while native compiler ran")
        if rc1.installed_preflight() != installed:
            raise BuildBlocked("Installed v1.0.2 state changed during isolated RC2 build")
        packaged = package(run, exe, proof["snapshot"], staged, native,
                           installed, proof, vite, qa)
        report.update({
            "status": "PRODUCTION_V104_P1_CANDIDATE_BUILT_NOT_INSTALLED",
            "compiled": native, "baseline": installed, "staged": staged,
            "qa": qa, "viteStage": vite, **packaged,
        })
    except Exception as error:
        report.update({"status": "BLOCKED", "errorType": type(error).__name__,
                       "error": str(error)})
        result_file.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    result_file.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true",
                        help="Create isolated RC2 candidate ONLY with all QA pins")
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--source-sha", default="")
    parser.add_argument("--inventory-sha", default="")
    parser.add_argument("--stage-report-sha", default="")
    parser.add_argument("--inventory-name", default="patched-source-sha256.json")
    parser.add_argument("--vite-dir", type=Path)
    parser.add_argument("--vite-js-sha", default="")
    parser.add_argument("--vite-report-sha", default="")
    for flag in ("source-qa", "original-edge-qa", "residual-edge-qa"):
        parser.add_argument("--" + flag, type=Path)
        parser.add_argument("--" + flag + "-sha", default="")
    args = parser.parse_args()
    try:
        if not args.build:
            print(json.dumps({
                "status": "RC2_BUILDER_AUTHORED_NOT_EXECUTED",
                "rc1FrozenExeSha256": RC1_EXE_SHA,
                "rc1FrozenJsSha256": RC1_JS_SHA,
                "requiredNewSourceFiles": sorted(EXTRA_PATHS),
                "sourceCount": COUNT,
                "requires": sorted(EXPECTED_QA),
                "installed": False, "productionReleaseApproved": False,
            }, indent=2))
            return 0
        witnesses = {
            "rc2-source-stage": (args.source_qa, args.source_qa_sha),
            "rc2-original-seven-edge": (args.original_edge_qa, args.original_edge_qa_sha),
            "rc2-residual-three-edge": (args.residual_edge_qa, args.residual_edge_qa_sha),
        }
        result = build(
            stage=args.stage, source_sha=args.source_sha,
            inventory_sha=args.inventory_sha, stage_report_sha=args.stage_report_sha,
            inventory_name=args.inventory_name,
            vite_dir=args.vite_dir, vite_js_sha=args.vite_js_sha,
            vite_report_sha=args.vite_report_sha, witnesses=witnesses,
        )
        print(json.dumps(_json(result), indent=2, sort_keys=True))
        return 0
    except (BuildBlocked, ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        print("TARAZ V104 RC2 BUILD BLOCKED: " + type(error).__name__ + ": " + str(error),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
