"""Detached v1.0.4 RC3: mask the analytic result.error DOM echo only.

The error from buildManagementAnalytics is often a returned object, not a
thrown exception. RC2 masked the catch but not this rendered result. This
script creates a new 131-file source copy and Vite QA output, never EXE/ZIP.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v104_independent_acceptance_20261111 as qa
from scripts import stage_taraz_v104_rc2_20261111 as rc2

RC2_STAGE = qa.OUTPUT / "source-stage-146b4c62e3f8"
RC2_SOURCE_SHA = "aed268223d707dde24a383f9ce013c9c18fd60b80836bec9222db5e9f9d78ef8"
TARGET = "src/accounting_management_dashboard.jsx"
OLD = "      {error||analytics.error}</div>}"
NEW = "      {error||'محاسبه شاخص‌های مدیریتی ناموفق بود؛ داده‌های منبع را بررسی کنید.'}</div>}"


class RC3Blocked(qa.Blocked):
    pass


def change_text(source: str) -> str:
    if source.count(OLD) != 1:
        raise RC3Blocked("Expected exactly one untrusted analytics.error DOM sink")
    if "if(!validRange)return {analytics:null,error:'بازهٔ زمانی باید معتبر" not in source:
        raise RC3Blocked("Locally authored date-range validation disappeared")
    if "catch(_error){return {analytics:null,error:'محاسبه شاخص‌های مدیریتی ناموفق بود؛" not in source:
        raise RC3Blocked("Earlier RC2 catch masking unexpectedly absent")
    new = source.replace(OLD, NEW, 1)
    if OLD in new or new == source:
        raise RC3Blocked("RC3 sink patch did not uniquely replace raw error")
    return new


def verify_rc3(stage_dir: Path) -> dict:
    path = qa.regular(stage_dir, directory=True)
    if (path.parent.resolve() != qa.OUTPUT.resolve()
            or not re.fullmatch(r"source-stage-[a-f0-9]{12}", path.name)
            or path == RC2_STAGE):
        raise RC3Blocked("Untrusted RC3 source stage path")
    report = qa.load_json(path / "stage-report.json")
    manifest_path = path / "patched-source-sha256.json"
    manifest = qa.load_json(manifest_path)
    prior = rc2.verify_rc2(RC2_STAGE)
    if not (report.get("status") == "V104_RC3_SOURCE_ONLY_EDGE_QA_PENDING"
            and report.get("startingSourceSha256") == RC2_SOURCE_SHA
            and report.get("parentStage") == str(RC2_STAGE)
            and report.get("changedSourceFiles") == [TARGET]
            and report.get("sourceCount") == qa.COUNT
            and report.get("executableBuilt") is False
            and report.get("releaseApproved") is False
            and report.get("dynamicEdgeApproved") is False
            and report.get("stagedPackageVersionUntouched") == "1.0.0"
            and report.get("sourceSha256") == qa.fingerprint(manifest)
            and report.get("sourceInventoryFileSha256") ==
            qa.hash_file(manifest_path, max_bytes=qa.MAX_JSON)
            and len(manifest) == qa.COUNT):
        raise RC3Blocked("RC3 manifest/status/source SHA mismatch")
    differences = {name for name in manifest if
                   manifest[name] != prior["sourceFiles"].get(name)}
    if differences != {TARGET}:
        raise RC3Blocked("RC3 patch scope differs from one approved source sink")
    qa.check_source_tree(path / "source", manifest)
    old = (RC2_STAGE / "source" / TARGET).read_bytes().decode("utf-8")
    new = change_text(old)
    if (path / "source" / TARGET).read_bytes() != new.encode("utf-8"):
        raise RC3Blocked("RC3 rendered management source did not match reviewed patch")
    index = qa.load_json(path / "rc3-patch-evidence.json")
    witness = index.get(TARGET)
    if set(index) != {TARGET} or not isinstance(witness, dict):
        raise RC3Blocked("RC3 patch provenance missing")
    qa.checked_hash(path / "reviewed-patches" / witness["filename"],
                    witness.get("patchSha256"), cap=qa.MAX_SOURCE)
    if (witness.get("previousSha256") != prior["sourceFiles"][TARGET]
            or witness.get("currentSha256") != manifest[TARGET]):
        raise RC3Blocked("RC3 reviewed patch SHA differs")
    return {"status": report["status"], "stage": str(path), "sourceSha256":
            report["sourceSha256"], "sourceCount": len(manifest),
            "sourceManifestSha256": report["sourceInventoryFileSha256"],
            "stageReportSha256": qa.hash_file(path / "stage-report.json",
                                             max_bytes=qa.MAX_JSON),
            "sourceFiles": manifest}


def create_stage() -> Path:
    prior = rc2.verify_rc2(RC2_STAGE)
    if prior["sourceSha256"] != RC2_SOURCE_SHA:
        raise RC3Blocked("RC2 starting source fingerprint changed")
    qa.checked_hash(qa.REJECTED_V104_BUILD / "binary" / "Taraz.exe",
                    qa.REJECTED_V104_EXE_SHA)
    qa.checked_hash(qa.REJECTED_V104_BUILD /
                    "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip",
                    qa.REJECTED_V104_ZIP_SHA, cap=qa.MAX_ARCHIVE)
    path = qa.OUTPUT / ("source-stage-" + uuid.uuid4().hex[:12])
    path.mkdir(exist_ok=False)
    report_path = path / "stage-report.json"
    report = {"status": "BLOCKED", "parentStage": str(RC2_STAGE),
              "startingSourceSha256": RC2_SOURCE_SHA, "executableBuilt": False,
              "releaseApproved": False, "dynamicEdgeApproved": False,
              "originalV104CandidateModified": False}
    try:
        from scripts.build_taraz_v103_p1_release_20261111 import base
        snapshot = path / "source"
        base.snapshot_source(RC2_STAGE / "source", snapshot, prior["sourceFiles"])
        qa.check_source_tree(snapshot, prior["sourceFiles"])
        target = snapshot / TARGET
        old = target.read_bytes().decode("utf-8")
        new = change_text(old)
        with target.open("wb") as output:
            output.write(new.encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
        current = dict(prior["sourceFiles"])
        current[TARGET] = qa.hash_file(target, max_bytes=qa.MAX_SOURCE)
        if (len(current) != qa.COUNT or
                {name for name in current if current[name] != prior["sourceFiles"][name]} != {TARGET}):
            raise RC3Blocked("Unexpected source scope beyond management error sink")
        qa.check_source_tree(snapshot, current)
        patches = path / "reviewed-patches"
        patches.mkdir(exist_ok=False)
        diff = "".join(difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile="a/" + TARGET, tofile="b/" + TARGET))
        if not diff.startswith("--- a/" + TARGET + "\n"):
            raise RC3Blocked("RC3 patch format invalid")
        patch_file = patches / (TARGET.replace("/", "__") + ".patch")
        with patch_file.open("x", encoding="utf-8", newline="\n") as output:
            output.write(diff)
        patch_witness = {
            TARGET: {"previousSha256": prior["sourceFiles"][TARGET],
                     "currentSha256": current[TARGET], "filename": patch_file.name,
                     "patchSha256": qa.hash_file(patch_file, max_bytes=qa.MAX_SOURCE)},
        }
        with (path / "rc3-patch-evidence.json").open("x", encoding="utf-8") as output:
            output.write(json.dumps(patch_witness, ensure_ascii=False, sort_keys=True,
                                    indent=2) + "\n")
        inventory = path / "patched-source-sha256.json"
        with inventory.open("x", encoding="utf-8") as output:
            output.write(json.dumps(current, ensure_ascii=False, sort_keys=True,
                                    indent=2) + "\n")
        if rc2.verify_rc2(RC2_STAGE)["sourceSha256"] != RC2_SOURCE_SHA:
            raise RC3Blocked("RC2 parent was modified during copy")
        qa.checked_hash(qa.REJECTED_V104_BUILD / "binary" / "Taraz.exe",
                        qa.REJECTED_V104_EXE_SHA)
        qa.checked_hash(qa.REJECTED_V104_BUILD /
                        "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip",
                        qa.REJECTED_V104_ZIP_SHA, cap=qa.MAX_ARCHIVE)
        report.update({"status": "V104_RC3_SOURCE_ONLY_EDGE_QA_PENDING",
                       "sourceSha256": qa.fingerprint(current), "sourceCount": qa.COUNT,
                       "sourceInventoryFileSha256": qa.hash_file(inventory, max_bytes=qa.MAX_JSON),
                       "changedSourceFiles": [TARGET],
                       "stagedPackageVersionUntouched": "1.0.0",
                       "originalRC2StageUnchanged": True,
                       "originalV104CandidateUnchanged": True})
    except Exception as exc:
        report["error"] = str(exc) if isinstance(exc, qa.Blocked) else type(exc).__name__
        with report_path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        raise
    with report_path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return report_path


def vite_qa(source: Path) -> Path:
    provenance = verify_rc3(source)
    from scripts.qa_mtr_taraz_build_20261110 import _safe_copytree, _trusted_modules
    root = qa.OUTPUT / ("vite-qa-" + uuid.uuid4().hex[:12])
    root.mkdir(exist_ok=False)
    record_path = root / "rc3-vite-qa-report.json"
    record = {"status": "BLOCKED", "stage": str(source),
              "sourceSha256": provenance["sourceSha256"],
              "compiledExe": False, "dynamicEdgeApproved": False,
              "releaseApproved": False}
    try:
        workspace = root / "workspace"
        shutil.copytree(source / "source", workspace, symlinks=False)
        qa.check_source_tree(workspace, provenance["sourceFiles"])
        _safe_copytree(_trusted_modules(), workspace / "node_modules")
        env = dict(os.environ)
        for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "HOME", "USERPROFILE",
                    "npm_config_cache"):
            destination = root / "private-env" / key.lower()
            destination.mkdir(parents=True, exist_ok=True)
            env[key] = str(destination)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["CI"] = "true"
        command = [
            shutil.which("node") or "node",
            str(workspace / "node_modules" / "vite" / "bin" / "vite.js"),
            "build", "--config", str(workspace / "vite.config.js"),
            "--outDir", str(root / "dist"), "--emptyOutDir",
        ]
        executed = subprocess.run(
            command, cwd=workspace, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", timeout=240, check=False)
        with (root / "vite-build.log").open("x", encoding="utf-8") as output:
            output.write(executed.stdout[-60000:])
        if executed.returncode:
            raise RC3Blocked("Vite RC3 compile failed; see detached QA log")
        dist = root / "dist"
        scripts = list((dist / "assets").glob("accounting-*.js"))
        styles = list((dist / "assets").glob("accounting-*.css"))
        html = dist / "accounting.html"
        if len(scripts) != 1 or len(styles) != 1 or not html.is_file():
            raise RC3Blocked("RC3 Vite JS/CSS/HTML inventory incomplete")
        js_sha = qa.hash_file(scripts[0], max_bytes=qa.MAX_SOURCE)
        if js_sha in (qa.VITE_JS_SHA, rc2.qa.VITE_JS_SHA,
                      "39295ea85bf2d6ee9fd94fce862c2bc505d4ac6ce01153fbc7ef9d8eea0b5b79"):
            raise RC3Blocked("RC3 compiled JS unexpectedly identical to an unsafe release")
        if verify_rc3(source)["sourceSha256"] != provenance["sourceSha256"]:
            raise RC3Blocked("RC3 source changed during frontend QA")
        qa.checked_hash(qa.REJECTED_V104_BUILD / "binary" / "Taraz.exe",
                        qa.REJECTED_V104_EXE_SHA)
        record.update({"status": "V104_RC3_STAGE_UI_ONLY_EDGE_QA_PENDING",
                       "sourceCount": qa.COUNT, "sourceStageReportSha256":
                       provenance["stageReportSha256"], "sourceInventoryFileSha256":
                       provenance["sourceManifestSha256"], "jsRelativePath":
                       scripts[0].relative_to(root).as_posix(), "jsSha256": js_sha,
                       "cssRelativePath": styles[0].relative_to(root).as_posix(),
                       "cssSha256": qa.hash_file(styles[0], max_bytes=qa.MAX_SOURCE),
                       "htmlRelativePath": html.relative_to(root).as_posix(),
                       "htmlSha256": qa.hash_file(html, max_bytes=qa.MAX_SOURCE),
                       "originalV104CandidateUnchanged": True})
    except Exception as exc:
        record["error"] = str(exc) if isinstance(exc, qa.Blocked) else type(exc).__name__
        with record_path.open("x", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        raise
    with record_path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return record_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stage", action="store_true")
    group.add_argument("--verify", type=Path)
    group.add_argument("--vite-qa", type=Path)
    args = parser.parse_args()
    try:
        if args.stage:
            report = create_stage()
            info = qa.load_json(report)
            summary = {"status": info["status"], "stage": str(report.parent),
                       "sourceSha256": info["sourceSha256"], "modifiedFiles":
                       info["changedSourceFiles"]}
        elif args.verify:
            summary = verify_rc3(args.verify)
            summary.pop("sourceFiles")
        else:
            report = vite_qa(args.vite_qa)
            info = qa.load_json(report)
            summary = {"status": info["status"], "vite": str(report.parent),
                       "sourceSha256": info["sourceSha256"],
                       "jsSha256": info["jsSha256"], "nativeExeBuilt": False}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (qa.Blocked, OSError, ValueError, TypeError, KeyError,
            subprocess.SubprocessError) as exc:
        print("V104 RC3 SOURCE STAGE BLOCKED: " + type(exc).__name__ + ": " + str(exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
