"""Create-only RC2 v1.0.4 source and frontend QA; never produces native EXE.

Three independently reproduced UI exception sinks are masked ONLY in a new
131-file detached source-stage copied from the rejected v104 Stage B.
The rejected EXE, ZIP, prior stages and installed profiles are immutable.
"""
from __future__ import annotations

import argparse
import hashlib
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


class StageRC2Blocked(qa.Blocked):
    pass


def stage() -> Path:
    """Copies trusted RC1 Stage B and replaces only three exact audited sinks."""
    path = qa.build_rc2_source_stage()
    return path


def verify_rc2(path: Path) -> dict:
    path = Path(path)
    qa.regular(path, directory=True)
    if (path.parent.resolve() != qa.OUTPUT.resolve()
            or not re.fullmatch(r"source-stage-[a-f0-9]{12}", path.name)
            or path == qa.STAGE):
        raise StageRC2Blocked("RC2 must be a new direct child of v104 QA output")
    data = qa.load_json(path / "stage-report.json")
    inventory_file = path / "patched-source-sha256.json"
    source = qa.load_json(inventory_file)
    if (data.get("status") != "V104_RC2_SOURCE_ONLY_DYNAMIC_QA_PENDING"
            or data.get("parentStage") != str(qa.STAGE)
            or data.get("startingSourceSha256") != qa.STAGE_SOURCE_SHA
            or data.get("sourceCount") != qa.COUNT
            or data.get("changedFileCount") != 3
            or set(data.get("changedFiles", [])) != qa.RC2_TARGETS
            or data.get("executableBuilt") is not False
            or data.get("releaseApproved") is not False
            or data.get("dynamicRC2EdgeVerified") is not False
            or data.get("originalV104BuildModified") is not False
            or data.get("originalStageRehashedAndUnchanged") is not True
            or data.get("originalCandidateRehashedAndUnchanged") is not True
            or data.get("stagedPackageVersionUntouched") != "1.0.0"
            or len(source) != qa.COUNT
            or qa.fingerprint(source) != data.get("patchedSourceSha256")
            or qa.hash_file(inventory_file, max_bytes=qa.MAX_JSON) !=
            data.get("patchedInventoryFileSha256")):
        raise StageRC2Blocked("RC2 source stage witness incomplete or contradicted")
    qa.check_source_tree(path / "source", source)
    prior = qa.verify_stage()["inventory"]
    if {key for key in prior if prior[key] != source[key]} != qa.RC2_TARGETS:
        raise StageRC2Blocked("RC2 source diff is not exactly three audited files")
    patches = qa.load_json(path / "rc2-patch-evidence.json")
    if set(patches) != qa.RC2_TARGETS:
        raise StageRC2Blocked("Incomplete RC2 patch evidence")
    for relative, witness in patches.items():
        file = path / "reviewed-patches" / witness["patch"]
        qa.checked_hash(file, witness.get("patchSha256"), cap=qa.MAX_SOURCE)
        if (witness.get("beforeSha256") != prior[relative]
                or witness.get("afterSha256") != source[relative]):
            raise StageRC2Blocked("RC2 patch witness SHA drift")
    return {"status": data["status"], "sourceCount": qa.COUNT,
            "sourceSha256": data["patchedSourceSha256"],
            "stageReportSha256": qa.hash_file(path / "stage-report.json",
                                              max_bytes=qa.MAX_JSON),
            "sourceInventoryFileSha256": data["patchedInventoryFileSha256"],
            "sourceFiles": source, "stage": str(path)}


def frontend_qa(rc2: Path) -> Path:
    evidence = verify_rc2(rc2)
    qa.checked_hash(qa.REJECTED_V104_BUILD / "binary" / "Taraz.exe",
                    qa.REJECTED_V104_EXE_SHA)
    qa.checked_hash(qa.REJECTED_V104_BUILD /
                    "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip",
                    qa.REJECTED_V104_ZIP_SHA, cap=qa.MAX_ARCHIVE)
    from scripts.qa_mtr_taraz_build_20261110 import _trusted_modules, _safe_copytree
    root = qa.OUTPUT / ("vite-qa-" + uuid.uuid4().hex[:12])
    root.mkdir(exist_ok=False)
    report_path = root / "rc2-vite-qa-report.json"
    report = {
        "status": "BLOCKED", "stage": str(rc2), "sourceSha256": evidence["sourceSha256"],
        "sourceCount": qa.COUNT, "nativeExeBuilt": False, "originalCandidateTouched": False,
        "dynamicEdgeApproved": False, "releaseApproved": False,
    }
    try:
        workspace = root / "workspace"
        shutil.copytree(rc2 / "source", workspace, symlinks=False)
        qa.check_source_tree(workspace, evidence["sourceFiles"])
        _safe_copytree(_trusted_modules(), workspace / "node_modules")
        env = dict(os.environ)
        for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "USERPROFILE",
                    "HOME", "XDG_CACHE_HOME", "npm_config_cache"):
            p = root / "private-env" / key.lower()
            p.mkdir(parents=True, exist_ok=True)
            env[key] = str(p)
        env["CI"] = "true"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [
            shutil.which("node") or "node",
            str(workspace / "node_modules" / "vite" / "bin" / "vite.js"),
            "build", "--config", str(workspace / "vite.config.js"),
            "--outDir", str(root / "dist"), "--emptyOutDir",
        ]
        completed = subprocess.run(
            command, cwd=workspace, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", timeout=240, check=False,
        )
        with (root / "vite-build.log").open("x", encoding="utf-8") as writer:
            writer.write(completed.stdout[-60000:])
        if completed.returncode != 0:
            raise StageRC2Blocked("RC2 detached Vite compilation failed")
        dist = root / "dist"
        js = list((dist / "assets").glob("accounting-*.js"))
        css = list((dist / "assets").glob("accounting-*.css"))
        html = dist / "accounting.html"
        if not html.is_file() or len(js) != 1 or len(css) != 1:
            raise StageRC2Blocked("RC2 compiled web assets incomplete")
        if qa.hash_file(js[0], max_bytes=qa.MAX_SOURCE) in (qa.VITE_JS_SHA, qa.V103_JS_SHA):
            raise StageRC2Blocked("RC2 JavaScript accidentally identical to rejected release")
        current = verify_rc2(rc2)
        if current["sourceSha256"] != evidence["sourceSha256"]:
            raise StageRC2Blocked("RC2 source changed during detached Vite")
        qa.checked_hash(qa.REJECTED_V104_BUILD / "binary" / "Taraz.exe",
                        qa.REJECTED_V104_EXE_SHA)
        qa.checked_hash(qa.REJECTED_V104_BUILD /
                        "Taraz-v1.0.4-P1-SECURE-OFFLINE-UPDATE.zip",
                        qa.REJECTED_V104_ZIP_SHA, cap=qa.MAX_ARCHIVE)
        report.update({
            "status": "V104_RC2_STAGE_UI_ONLY_EDGE_QA_PENDING",
            "sourceStageReportSha256": evidence["stageReportSha256"],
            "sourceInventoryFileSha256": evidence["sourceInventoryFileSha256"],
            "jsRelativePath": js[0].relative_to(root).as_posix(),
            "jsSha256": qa.hash_file(js[0], max_bytes=qa.MAX_SOURCE),
            "cssRelativePath": css[0].relative_to(root).as_posix(),
            "cssSha256": qa.hash_file(css[0], max_bytes=qa.MAX_SOURCE),
            "htmlRelativePath": html.relative_to(root).as_posix(),
            "htmlSha256": qa.hash_file(html, max_bytes=qa.MAX_SOURCE),
            "viteExitCode": completed.returncode,
            "sourceRehashedBeforeAfter": True,
            "rejectedV104CandidateUnchanged": True,
        })
    except Exception as exc:
        report["error"] = str(exc) if isinstance(exc, qa.Blocked) else type(exc).__name__
        with report_path.open("x", encoding="utf-8") as writer:
            writer.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        raise
    with report_path.open("x", encoding="utf-8") as writer:
        writer.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stage", action="store_true")
    group.add_argument("--vite-qa", type=Path, metavar="RC2_SOURCE_STAGE")
    group.add_argument("--verify", type=Path, metavar="RC2_SOURCE_STAGE")
    args = parser.parse_args()
    try:
        if args.stage:
            evidence_file = stage()
            data = qa.load_json(evidence_file)
            response = {"status": data["status"], "sourceStage": str(evidence_file.parent),
                        "sourceSha256": data["patchedSourceSha256"],
                        "editedSourceFiles": data["changedFiles"]}
        elif args.verify:
            response = verify_rc2(args.verify)
            response.pop("sourceFiles")
        else:
            report_path = frontend_qa(args.vite_qa)
            data = qa.load_json(report_path)
            response = {"status": data["status"], "output": str(report_path.parent),
                        "sourceSha256": data["sourceSha256"],
                        "jsSha256": data["jsSha256"],
                        "compiledExeBuilt": False}
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0
    except (qa.Blocked, OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError) as exc:
        print("V104 RC2 SOURCE STAGE BLOCKED: " + type(exc).__name__ + ": " + str(exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
