"""Create-only v1.0.4 P1 staging with exact frozen v1.0.3 source and proposals.

The 131 trusted runtime inputs are copied by the original snapshot mechanism.
Source files in the stage remain byte-exact; edits are stored only as detached
unified diffs for review. Does not execute npm, build native binaries, install,
run Taraz, or inspect/write financial profiles.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import build_taraz_v103_p1_release_20261111 as v103

base = v103.base
START_SHA = "a545cae1f4d338607e052087e144245ba7d18cb71d9874915e0b0d391b0b8279"
SOURCE_COUNT = 131
OUTPUT = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.4-p1"
CONFIRMED_DYNAMIC = {
    "src/personal_parsian_company.jsx",
    "src/taraz_home_command.jsx",
    "src/personal_parsian_extended.jsx",
    "src/personal_parsian_invoices.jsx",
    "src/personal_parsian_bank_movements.jsx",
    "src/parsian_raw_archive_explorer.jsx",
    "src/provider_csv_migration.jsx",
}
TARGET_VERSION = "1.0.4"
RAW_HOST_SENTINEL = "QA-V103-HOST-SECRET-72973"


class StageBlocked(RuntimeError):
    """Required source integrity or anchored patch condition was not proven."""


def _sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for buf in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(buf)
    return result.hexdigest()


def _relative(value: str) -> Path:
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or value.startswith("/") or "//" in value):
        raise StageBlocked("Untrusted source-relative path")
    parts = PurePosixPath(value).parts
    if len(parts) < 1 or any(part in (".", "..", "") for part in parts):
        raise StageBlocked("Unsafe source path")
    return Path(*parts)


def checked_inventory() -> dict[str, str]:
    originals = v103.inventory()
    if not isinstance(originals, dict) or len(originals) != SOURCE_COUNT:
        raise StageBlocked("Expected exactly 131 known runtime input files")
    if v103.fingerprint(originals) != START_SHA:
        raise StageBlocked("Frozen 1.0.3 runtime inputs changed; staging refused")
    for relative, digest in originals.items():
        _relative(relative)
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise StageBlocked("Malformed frozen source digest")
    return originals


# Each transformation is limited to ONE explicit source span with a reviewed
# purpose. No catch-all replacement, and no source tree edits. Keep locally
# authored validation copy, but never trust arbitrary host exception.message.
PROPOSALS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "src/personal_parsian_company.jsx": (
        (
            ".catch(e=>{if(active)setError(String(e?.message||e))})",
            ".catch(_error=>{if(active)setError('خواندن مشخصات شرکت از بکاپ پارسیان ناموفق بود.')})",
            "untrusted company metadata bridge exception",
        ),
    ),
    "src/personal_parsian_bank_movements.jsx": (
        (
            ".catch(e=>{if(active)setError(String(e?.message||e))});",
            ".catch(_error=>{if(active)setError('خواندن گردش تاریخی بانک و صندوق ناموفق بود.')});",
            "untrusted history bridge exception in cash/bank alert",
        ),
    ),
    "src/personal_parsian_invoices.jsx": (
        (
            "}).catch(e=>{if(active)setError(String(e?.message||e))})",
            "}).catch(e=>{if(active)setError(\n"
            "      e?.message==='اطلاعات معتبر ۱۹۵ فاکتور پارسیان دریافت نشد.'\n"
            "        ?'اطلاعات معتبر ۱۹۵ فاکتور پارسیان دریافت نشد.'\n"
            "        :'خواندن فاکتورهای تاریخی پارسیان ناموفق بود.')})",
            "preserve locally generated invalid-195-invoice validation",
        ),
        (
            "}catch(e){setExportError(String(e?.message||e));}",
            "}catch(_error){setExportError('ساخت خروجی فاکتور آرشیوی ناموفق بود.');}",
            "export exception text may contain arbitrary data or file paths",
        ),
    ),
    "src/personal_parsian_extended.jsx": (
        (
            ".catch(e=>{if(active)setError(String(e?.message||e))})",
            ".catch(_error=>{if(active)setError('خواندن داده‌های تکمیلی پارسیان ناموفق بود.')})",
            "untrusted extended archive bridge exception",
        ),
    ),
    "src/parsian_raw_archive_explorer.jsx": (
        (
            "}).catch(err=>{if(active)setError(err?.message||'آرشیو قابل خواندن نیست.')})",
            "}).catch(err=>{if(active)setError(\n"
            "        err?.message==='مرورگر آرشیو کامل در میزبان فعال نیست.'\n"
            "          ?'مرورگر آرشیو کامل در میزبان فعال نیست.'\n"
            "          :'آرشیو قابل خواندن نیست.')})",
            "preserve locally generated invalid archive-index message",
        ),
        (
            ".catch(err=>{if(active){setPage(null);setError(err?.message||'خواندن سطرهای آرشیوی ناموفق بود.')}})",
            ".catch(_error=>{if(active){setPage(null);setError('خواندن سطرهای آرشیوی ناموفق بود.')}})",
            "untrusted per-table archive row exception",
        ),
    ),
    "src/taraz_home_command.jsx": (
        (
            "setHistory(null);setError(err?.message||L.error);",
            "setHistory(null);setError(L.error);",
            "untrusted history bridge exception in home warning",
        ),
    ),
    "src/provider_csv_migration.jsx": (
        (
            "}catch(exc){setError(exc?.message||'انتخاب فایل ناموفق بود.');}",
            "}catch(exc){setError(\n"
            "      exc?.message==='انتخاب فایل در نسخه میزبان فعال نیست.'\n"
            "        ?'انتخاب فایل در نسخه میزبان فعال نیست.'\n"
            "        :'انتخاب فایل ناموفق بود.');}",
            "preserve locally authored CSV chooser-not-available message",
        ),
        (
            "    try{\n"
            "      const request=buildProviderCsvRequest({...config,files,mappings:mapping,ignored,valueMaps});\n"
            "      if(typeof api?.standaloneAccountingCsvPreview!=='function')\n"
            "        throw new Error('پیش‌نمایش در نسخه میزبان فعال نیست.');\n"
            "      setResult(await api.standaloneAccountingCsvPreview(request));\n"
            "    }catch(exc){setError(exc?.message||'اعتبارسنجی CSV ناموفق بود.');}\n"
            "    finally{setBusy(false);}",
            "    let request;\n"
            "    try{\n"
            "      // Local-only validation; its authored messages are safe for users.\n"
            "      request=buildProviderCsvRequest({...config,files,mappings:mapping,ignored,valueMaps});\n"
            "    }catch(exc){\n"
            "      setError(exc instanceof Error?exc.message:'اعتبارسنجی CSV ناموفق بود.');\n"
            "      setBusy(false);return;\n"
            "    }\n"
            "    try{\n"
            "      if(typeof api?.standaloneAccountingCsvPreview!=='function'){\n"
            "        setError('پیش‌نمایش در نسخه میزبان فعال نیست.');return;\n"
            "      }\n"
            "      setResult(await api.standaloneAccountingCsvPreview(request));\n"
            "    }catch(_error){setError('خواندن پیش‌نمایش CSV از میزبان ناموفق بود.');}\n"
            "    finally{setBusy(false);}",
            "separate strictly local request validation from untrusted native preview",
        ),
    ),
    "src/personal_parsian_dashboard.jsx": (
        (
            "else setError(String(ledger.reason?.message||ledger.reason||'داده دفتر کل در دسترس نیست'));",
            "else setError('داده دفتر کل در دسترس نیست. اتصال و دسترسی را بررسی کنید.');",
            "untrusted backend ledger rejection in dashboard",
        ),
        (
            "else {setHistory(null);setError(String(historic.reason?.message||historic.reason||'Source archive unavailable'));}",
            "else {setHistory(null);setError('خواندن آرشیو تاریخی پارسیان ناموفق بود.');}",
            "untrusted history rejection in dashboard",
        ),
    ),
    "src/accounting_action_home.jsx": (
        (
            ".catch(error=>{if(active)setParsianSourceError(String(error?.message||error))});",
            ".catch(_error=>{if(active)setParsianSourceError('خواندن منبع آرشیوی پارسیان ناموفق بود.')});",
            "untrusted historical data exception in action dashboard",
        ),
    ),
}


def changed_text(relative: str, before: str) -> tuple[str, list[dict]]:
    edits = []
    result = before
    for old, new, purpose in PROPOSALS.get(relative, ()):
        newline = "\r\n" if "\r\n" in result else "\n"
        anchor = old.replace("\n", newline)
        replacement = new.replace("\n", newline)
        if not old or not new or old == new or result.count(anchor) != 1:
            raise StageBlocked("Unexpected source handler anchor: " + relative)
        line = result[:result.index(anchor)].count("\n") + 1
        edits.append({"line": line, "purpose": purpose, "anchorSha256": hashlib.sha256(
            old.encode("utf-8")).hexdigest(), "editedAnchorSha256": hashlib.sha256(
            new.encode("utf-8")).hexdigest()})
        result = result.replace(anchor, replacement, 1)
    return result, edits


def version_proposals(originals: dict[str, str]) -> dict[str, str]:
    """Detached manifest/lock proposals. The 131 copied bytes stay unchanged."""
    result = {}
    for rel in ("package.json", "package-lock.json"):
        source = (ROOT / rel).read_bytes().decode("utf-8")
        parsed = json.loads(source)
        if parsed.get("name") != "taraz-accounting" or parsed.get("version") != "1.0.0":
            raise StageBlocked("Unexpected legacy package version")
        if rel == "package-lock.json":
            if parsed.get("packages", {}).get("", {}).get("version") != "1.0.0":
                raise StageBlocked("Unexpected legacy lock root")
            if source.count('"version": "1.0.0"') != 2:
                raise StageBlocked("Noncanonical lock version anchors")
            next_text = source.replace('"version": "1.0.0"', '"version": "1.0.4"')
        else:
            if source.count('"version": "1.0.0"') != 1:
                raise StageBlocked("Noncanonical package version anchor")
            next_text = source.replace('"version": "1.0.0"', '"version": "1.0.4"')
        if hashlib.sha256(source.encode("utf-8")).hexdigest() != originals[rel]:
            raise StageBlocked("Version proposal input drift")
        result[rel] = next_text
    return result


def verify_snapshot(snapshot: Path, expected: dict[str, str]) -> None:
    for rel, digest in expected.items():
        path = snapshot / _relative(rel)
        base.refuse_links(path)
        if not path.is_file() or not stat.S_ISREG(path.lstat().st_mode) or _sha(path) != digest:
            raise StageBlocked("Staged byte mismatch: " + rel)
    found = {path.relative_to(snapshot).as_posix() for path in snapshot.rglob("*")
             if path.is_file()}
    if found != set(expected):
        raise StageBlocked("Staged source file set changed")


def build_proposals(snapshot: Path, proposal_dir: Path, originals: dict[str, str]) -> dict:
    proposal_dir.mkdir(exist_ok=False)
    record = {}
    versions = version_proposals(originals)
    for relative in sorted(set(PROPOSALS) | set(versions)):
        if relative not in originals:
            raise StageBlocked("Review proposal targets file outside trusted 131")
        old = (snapshot / _relative(relative)).read_bytes().decode("utf-8")
        if relative in versions:
            new, edits = versions[relative], [{"line": 1, "purpose": "detached 1.0.4 version proposal"}]
        else:
            new, edits = changed_text(relative, old)
        if old == new or hashlib.sha256(old.encode("utf-8")).hexdigest() != originals[relative]:
            raise StageBlocked("No-op or unpinned proposal")
        diff = "".join(difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile="a/" + relative, tofile="b/" + relative, n=3))
        if not diff.startswith("--- a/" + relative + "\n") or "@@" not in diff:
            raise StageBlocked("Patch generation failed")
        path = proposal_dir / (relative.replace("/", "__") + ".patch")
        with path.open("x", encoding="utf-8", newline="\n") as writer:
            writer.write(diff)
        record[relative] = {
            "startingSha256": originals[relative],
            "proposedSha256": hashlib.sha256(new.encode("utf-8")).hexdigest(),
            "patchName": path.name, "patchSha256": _sha(path),
            "edits": edits,
            "riskCategory": "compiled v1.0.3 Edge demonstrated raw backend exception"
            if relative in CONFIRMED_DYNAMIC else
            "static source candidate awaiting worker27 dynamic review"
            if relative not in versions else "version proposal only",
            "appliedToSnapshot": False,
        }
    if not CONFIRMED_DYNAMIC <= set(record):
        raise StageBlocked("Dynamic-confirmed company sink not proposed")
    return record


def stage() -> Path:
    originals = checked_inventory()
    base.refuse_links(OUTPUT.parent)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    base.refuse_links(OUTPUT)
    run = OUTPUT / ("source-stage-" + uuid.uuid4().hex[:12])
    run.mkdir(exist_ok=False)
    report_path = run / "stage-report.json"
    report = {"status": "BLOCKED", "fromVersion": "1.0.3", "targetVersion": TARGET_VERSION,
              "frozenStartingSha256": START_SHA, "sourceCount": SOURCE_COUNT,
              "executableBuilt": False, "productionInstalled": False,
              "sourceSnapshotModified": False, "runtimeReleaseAuthorized": False,
              "worker27DynamicApproval": False, "secureInstallerApproved": False}
    try:
        snapshot = run / "source"
        base.snapshot_source(ROOT, snapshot, originals)
        verify_snapshot(snapshot, originals)
        proposals = build_proposals(snapshot, run / "proposals", originals)
        verify_snapshot(snapshot, originals)
        if v103.fingerprint(v103.inventory()) != START_SHA:
            raise StageBlocked("Runtime source drifted after snapshot")
        inventory_file = run / "starting-source-sha256.json"
        with inventory_file.open("x", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(originals, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        proposals_file = run / "proposal-index.json"
        with proposals_file.open("x", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(proposals, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        report.update({"status": "V104_SOURCE_STAGE_ONLY_PATCHES_PENDING_REVIEW",
                       "sourceManifestSha256": _sha(inventory_file),
                       "proposalsIndexSha256": _sha(proposals_file),
                       "proposedPatchFileCount": len(proposals),
                       "confirmedDynamicSinkCount": len(CONFIRMED_DYNAMIC),
                       "sourceExactlyMirrorsFrozen": True,
                       "nodeModulesCopied": False,
                       "unverifiedErrorsRemain": True})
    except Exception as exc:
        report.update({"status": "BLOCKED", "errorType": type(exc).__name__,
                       "error": str(exc)})
        with report_path.open("x", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        raise
    with report_path.open("x", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return report_path


def materialize_reviewed(first_stage: Path) -> Path:
    """Apply approved frontend proposals ONLY in a NEW second-stage source copy.

    Version proposals remain packaging-only. This keeps package/lock baseline
    at 1.0.0, as required by the existing build-versioning contract. Neither
    source stage is eligible for EXE release while security gates are open.
    """
    expected = checked_inventory()
    base.refuse_links(first_stage)
    if (first_stage.parent.resolve() != OUTPUT.resolve()
            or not first_stage.name.startswith("source-stage-")):
        raise StageBlocked("Original detached source stage path not trusted")
    report_file = first_stage / "stage-report.json"
    proposal_index = first_stage / "proposal-index.json"
    first_inventory = first_stage / "starting-source-sha256.json"
    for file in (report_file, proposal_index, first_inventory):
        base.refuse_links(file)
        if not file.is_file():
            raise StageBlocked("Original source stage attestation missing")
    report = json.loads(report_file.read_text(encoding="utf-8"))
    proposed = json.loads(proposal_index.read_text(encoding="utf-8"))
    listed = json.loads(first_inventory.read_text(encoding="utf-8"))
    if (report.get("status") != "V104_SOURCE_STAGE_ONLY_PATCHES_PENDING_REVIEW"
            or report.get("sourceManifestSha256") != _sha(first_inventory)
            or report.get("proposalsIndexSha256") != _sha(proposal_index)
            or report.get("frozenStartingSha256") != START_SHA
            or report.get("sourceSnapshotModified") is not False
            or listed != expected
            or set(proposed) != (set(PROPOSALS) | {"package.json", "package-lock.json"})):
        raise StageBlocked("Detached stage metadata or proposal inventory changed")
    verify_snapshot(first_stage / "source", expected)
    for relative, detail in proposed.items():
        patch_path = first_stage / "proposals" / detail["patchName"]
        base.refuse_links(patch_path)
        if (not patch_path.is_file() or _sha(patch_path) != detail["patchSha256"]
                or detail["startingSha256"] != expected[relative]):
            raise StageBlocked("Unpinned detached proposal file")
        original = (first_stage / "source" / relative).read_bytes().decode("utf-8")
        edited = (version_proposals(expected)[relative] if relative in
                  ("package.json", "package-lock.json") else changed_text(relative, original)[0])
        if hashlib.sha256(edited.encode("utf-8")).hexdigest() != detail["proposedSha256"]:
            raise StageBlocked("Detached proposal target digest mismatch")
    run = OUTPUT / ("source-stage-" + uuid.uuid4().hex[:12])
    run.mkdir(exist_ok=False)
    status = {"status": "BLOCKED", "fromStage": str(first_stage),
              "targetVersion": TARGET_VERSION, "baseVersionFieldsUnchanged": True,
              "executableBuilt": False, "runtimeReleaseAuthorized": False,
              "worker27PostpatchEdgeApproval": False, "secureInstallerApproved": False}
    result = run / "stage-report.json"
    try:
        snapshot = run / "source"
        base.snapshot_source(ROOT, snapshot, expected)
        verify_snapshot(snapshot, expected)
        patched = {}
        for relative in sorted(PROPOSALS):
            path = snapshot / _relative(relative)
            old = path.read_bytes()
            if hashlib.sha256(old).hexdigest() != expected[relative]:
                raise StageBlocked("New second-stage copy mismatched original")
            updated, edits = changed_text(relative, old.decode("utf-8"))
            if not edits or updated.encode("utf-8") == old:
                raise StageBlocked("Proposed source patch unexpectedly empty")
            with path.open("wb") as writer:
                writer.write(updated.encode("utf-8"))
                writer.flush()
                os.fsync(writer.fileno())
            patched[relative] = _sha(path)
            if patched[relative] != proposed[relative]["proposedSha256"]:
                raise StageBlocked("Applied detached patch result differs from review proposal")
        resulting = {rel: _sha(snapshot / _relative(rel)) for rel in expected}
        if set(resulting) != set(expected):
            raise StageBlocked("Revised source inventory keys changed")
        if {rel for rel in expected if resulting[rel] != expected[rel]} != set(PROPOSALS):
            raise StageBlocked("Unexpected changed source inputs")
        if (resulting["package.json"] != expected["package.json"]
                or resulting["package-lock.json"] != expected["package-lock.json"]):
            raise StageBlocked("Version baseline modified before build stage")
        verify_snapshot(snapshot, resulting)
        if v103.fingerprint(v103.inventory()) != START_SHA:
            raise StageBlocked("Frozen shared source modified during stage")
        files = run / "patched-source-sha256.json"
        with files.open("x", encoding="utf-8", newline="\n") as writer:
            writer.write(json.dumps(resulting, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        status.update({
            "status": "V104_PATCHED_SOURCE_FROZEN_QA_PENDING_NO_EXE",
            "sourceCount": len(resulting),
            "patchedSourceSha256": v103.fingerprint(resulting),
            "patchedInventoryFileSha256": _sha(files),
            "frozenStartingSha256": START_SHA,
            "editedSourceFiles": sorted(patched),
            "editedSourceFileCount": len(patched),
            "originalPackageLockSha256": expected["package-lock.json"],
            "proposedVersion": TARGET_VERSION,
            "versionBumpIsPackagingOnly": True,
            "allOriginalSourceInputsUnchanged": True,
            "reviewedProposalSourceSha256": _sha(proposal_index),
        })
    except Exception as exc:
        status.update({"errorType": type(exc).__name__, "error": str(exc)})
        with result.open("x", encoding="utf-8", newline="\n") as writer:
            writer.write(json.dumps(status, ensure_ascii=False, indent=2) + "\n")
        raise
    with result.open("x", encoding="utf-8", newline="\n") as writer:
        writer.write(json.dumps(status, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return result


def build_detached_frontend(patched_stage: Path) -> Path:
    """Vite frontend QA only, outside the source stage; never builds native EXE."""
    patched_stage = Path(patched_stage)
    base.refuse_links(patched_stage)
    if (patched_stage.parent.resolve() != OUTPUT.resolve()
            or not patched_stage.name.startswith("source-stage-")):
        raise StageBlocked("Untrusted patched stage path")
    report_path = patched_stage / "stage-report.json"
    pins_path = patched_stage / "patched-source-sha256.json"
    if not report_path.is_file() or not pins_path.is_file():
        raise StageBlocked("Missing patched source-stage attestation")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    if (report.get("status") != "V104_PATCHED_SOURCE_FROZEN_QA_PENDING_NO_EXE"
            or report.get("patchedInventoryFileSha256") != _sha(pins_path)
            or report.get("patchedSourceSha256") != v103.fingerprint(pins)
            or report.get("sourceCount") != SOURCE_COUNT):
        raise StageBlocked("Patched source freeze not approved for isolated Vite QA")
    verify_snapshot(patched_stage / "source", pins)
    from scripts.qa_mtr_taraz_build_20261110 import _trusted_modules, _safe_copytree
    deps = _trusted_modules()
    run = OUTPUT / ("vite-qa-" + uuid.uuid4().hex[:12])
    run.mkdir(exist_ok=False)
    record_path = run / "vite-qa-report.json"
    record = {"status": "BLOCKED", "compiledExeBuilt": False,
              "installedTarazTouched": False, "browserQaVerified": False,
              "patchedSourceSha256": report["patchedSourceSha256"],
              "sourceStagePath": str(patched_stage),
              "sourceStageReportSha256": _sha(report_path),
              "sourceInventorySha256": _sha(pins_path)}
    try:
        source = run / "workspace"
        shutil.copytree(patched_stage / "source", source, symlinks=False)
        verify_snapshot(source, pins)
        _safe_copytree(deps, source / "node_modules")
        env = os.environ.copy()
        for variable in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
                         "USERPROFILE", "HOME", "XDG_CACHE_HOME", "npm_config_cache"):
            path = run / "private-env" / variable.lower()
            path.mkdir(parents=True, exist_ok=True)
            env[variable] = str(path)
        env["CI"] = "true"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = ["node", str(source / "node_modules" / "vite" / "bin" / "vite.js"),
                   "build", "--config", str(source / "vite.config.js"),
                   "--outDir", str(run / "dist"), "--emptyOutDir"]
        completed = subprocess.run(command, cwd=source, env=env, timeout=240,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", check=False)
        with (run / "vite-build.log").open("x", encoding="utf-8") as writer:
            writer.write(completed.stdout[-60000:])
        if completed.returncode != 0:
            raise StageBlocked("Detached Vite compile failed; see isolated log")
        dist = run / "dist"
        html = dist / "accounting.html"
        assets = sorted((dist / "assets").glob("accounting-*.js"))
        css = sorted((dist / "assets").glob("accounting-*.css"))
        if not html.is_file() or len(assets) != 1 or len(css) != 1:
            raise StageBlocked("Detached Vite output is incomplete or ambiguous")
        verify_snapshot(patched_stage / "source", pins)
        verify_snapshot(source, pins) if not (source / "node_modules").exists() else None
        if v103.fingerprint(v103.inventory()) != START_SHA:
            raise StageBlocked("Original frozen runtime changed during Vite QA")
        record.update({"status": "STAGE_UI_ONLY",
                       "vitedJsFile": assets[0].name, "viteJsSha256": _sha(assets[0]),
                       "vitedCssFile": css[0].name, "viteCssSha256": _sha(css[0]),
                       "viteHtmlSha256": _sha(html),
                       "jsRelativePath": assets[0].relative_to(run).as_posix(),
                       "cssRelativePath": css[0].relative_to(run).as_posix(),
                       "htmlRelativePath": html.relative_to(run).as_posix(),
                       "compiledFrontend": True, "compiledExeBuilt": False,
                       "sourceShaBeforeAfterIdentical": True,
                       "compiledBundleReleaseReady": False})
    except Exception as exc:
        record.update({"errorType": type(exc).__name__,
                       "error": str(exc) if isinstance(exc, StageBlocked) else "Detached Vite QA failed"})
        with record_path.open("x", encoding="utf-8", newline="\n") as writer:
            writer.write(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        raise
    with record_path.open("x", encoding="utf-8", newline="\n") as writer:
        writer.write(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return record_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fingerprint", action="store_true", help="Read-only source inventory check")
    parser.add_argument("--stage", action="store_true", help="Create detached source and patch proposals")
    parser.add_argument("--materialize-reviewed", type=Path, metavar="SOURCE_STAGE_PATH",
                        help="Create a NEW second-stage source copy with narrow fixes applied")
    parser.add_argument("--vite-qa", type=Path, metavar="PATCHED_SOURCE_STAGE",
                        help="Compile frontend only in a disposable copied QA workspace")
    args = parser.parse_args()
    try:
        if args.fingerprint:
            originals = checked_inventory()
            print(json.dumps({"status": "FROZEN_131_INPUTS_MATCH", "sourceCount": len(originals),
                              "sha256": v103.fingerprint(originals)}, indent=2))
        elif args.stage:
            path = stage()
            report = json.loads(path.read_text(encoding="utf-8"))
            print(json.dumps({"status": report["status"], "output": str(path.parent),
                              "sourceCount": report["sourceCount"],
                              "proposals": report["proposedPatchFileCount"],
                              "startingSha256": report["frozenStartingSha256"]}, indent=2))
        elif args.materialize_reviewed:
            path = materialize_reviewed(args.materialize_reviewed)
            report = json.loads(path.read_text(encoding="utf-8"))
            print(json.dumps({"status": report["status"], "output": str(path.parent),
                              "sourceCount": report["sourceCount"],
                              "patchedSourceSha256": report["patchedSourceSha256"],
                              "editedSourceFiles": report["editedSourceFileCount"],
                              "compiledExecutableBuilt": False}, indent=2))
        elif args.vite_qa:
            path = build_detached_frontend(args.vite_qa)
            record = json.loads(path.read_text(encoding="utf-8"))
            print(json.dumps({"status": record["status"], "output": str(path.parent),
                              "frontendJsSha256": record["viteJsSha256"],
                              "compiledExeBuilt": False}, indent=2))
        else:
            parser.print_help()
        return 0
    except Exception as exc:
        print("V104 DETACHED SOURCE STAGE BLOCKED: " + type(exc).__name__ + ": " + str(exc),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
