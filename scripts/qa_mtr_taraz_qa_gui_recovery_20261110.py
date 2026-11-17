"""Pinned QA EXE startup refusal and native-WebView recovery gap evidence.

Never launches the *installed* Taraz. One pinned QA-only EXE may start only
against a fresh disposable QA profile with NO personal or synthetic ledger.
No fake historical accounting events, real credentials, port or source-guard
bypass. The expected result is a startup refusal, not a GUI acceptance.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import types
import uuid
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
PRIOR_RUNNER = PROJECT / "scripts" / "qa_mtr_latest_bundle_recovery_20261110.py"
EXPECTED_EXE_SHA = "f3c4d65418d8f9d80a40618c01bb1534841ca18bf863fd9d09d5ca0fb8449662"
EXPECTED_PYZ_SHA = "e2c12afc893dff7ab04ba090266e15172309ba4a2e90a6869106fe974e7a457e"
NEWEST_QA_EXE_SHA = "75d1aadd2988d2c09b6d9de0516ef63a90445088120199ea7d1916811540d328"
NEWEST_SNAPSHOT_SHA = "d7e5ff8c0d8c6a87ea2249d73c7589c53587396c8447899610f467a74545bb1a"
# SHA-256 of the *raw compressed PYZ member*, not marshal.dumps(code), whose
# byte ordering can differ across Python processes for frozen collections.
NEWEST_RAW_PYZ_MEMBER_SHA = "71cc3e7a22d471f01a5cf6e0da4eb1fab97f05d6893dac7cf4783b64ed79b036"
NEWEST_QA_BUILD_NAME = "qa-bf41a4980db3"
NO_LEDGER = "standalone-accounting.sqlite3"
_QA_ID = re.compile(r"^[0-9a-f]{32}$")


class QABlocked(RuntimeError):
    """Unsafe precondition or unexpected native outcome, never silent success."""


def prior_runner():
    if not PRIOR_RUNNER.is_file() or PRIOR_RUNNER.is_symlink():
        raise QABlocked("Immutable pinned packaged-QA helper is unavailable")
    spec = importlib.util.spec_from_file_location("mtr_taraz_prior_pinned_qa", PRIOR_RUNNER)
    if spec is None or spec.loader is None:
        raise QABlocked("Pinned packaged-QA helper could not be loaded")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def _func(tree: ast.AST, name: str):
    return next((node for node in getattr(tree, "body", ())
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == name), None)


def _recursive_code_names(code: types.CodeType) -> set[str]:
    result = set(code.co_names)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            result.update(_recursive_code_names(const))
    return result


def inspect_native_qa_gate() -> dict:
    """Static evidence from the exact EXE and its preserved source snapshot."""
    runner = prior_runner()
    code, provenance = runner.verify_latest_bundle()  # rehash EXE, manifest, PYZ, 120 files
    if (provenance.get("exeSha256") != EXPECTED_EXE_SHA
            or provenance.get("packedModuleSha256") != EXPECTED_PYZ_SHA):
        raise QABlocked("The exact authorized QA executable has changed")
    snapshot = runner.BUILD / "snapshot"
    helper = runner.previous_runner()
    source_entry = snapshot / "taraz_desktop.py"
    source_bridge = snapshot / "standalone_accounting_desktop.py"
    for item in (source_entry, source_bridge):
        helper.refuse_link(item)
        if not item.is_file():
            raise QABlocked("Pinned build snapshot has missing native startup source")
    tree = ast.parse(source_entry.read_text(encoding="utf-8"))
    entry = _func(tree, "run")
    if entry is None:
        raise QABlocked("Frozen Taraz native entrypoint is unavailable")
    body = ast.get_source_segment(source_entry.read_text(encoding="utf-8"), entry) or ""
    no_book = "if not (data / \"standalone-accounting.sqlite3\").is_file():"
    check_pos = body.find(no_book)
    init_pos = body.find("api = TarazAPI(data)")
    history_pos = body.find("api.standaloneAccountingParsianHistory()")
    server_pos = body.find("server = serve_accounting_page(")
    webview_pos = body.find("webview.create_window(")
    if (-1 in (check_pos, init_pos, history_pos, server_pos, webview_pos)
            or not (check_pos < init_pos < history_pos < server_pos < webview_pos)
            or "Taraz accounting book was not migrated" not in body):
        raise QABlocked("Native startup no-ledger fail-closed order is not verified")
    api_cls = next((node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "TarazAPI"), None)
    guard = next((node for node in api_cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_source_guard"), None) if api_cls else None
    if guard is None:
        raise QABlocked("Native personal accounting source guard is missing")
    guard_code = ast.get_source_segment(source_entry.read_text(encoding="utf-8"), guard) or ""
    if not all(token in guard_code for token in (
        "_require_authenticated()", "mode=ro", "row[0] < 608",
        "Not the expected personal accounting book", "ps.parsian.journal.1405.14050201.1",
        "ps.parsian.reconcile.1404.pnl-close.20261107",
    )):
        raise QABlocked("Personal ledger source_guard invariants changed")

    # Critical secondary blockade: the actual packed HTML bridge does NOT
    # expose recover, even though the packed API and React expect it.
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(runner.EXE))
    packed_native_bridge = archive.open_embedded_archive("PYZ.pyz").extract(
        "standalone_accounting_desktop")
    if not isinstance(packed_native_bridge, types.CodeType):
        raise QABlocked("Cannot statically inspect actual packed HTML bridge")
    literals = [value for value in packed_native_bridge.co_consts
                if isinstance(value, str) and "window.madar = Object.fromEntries" in value]
    if len(literals) != 1:
        raise QABlocked("Packed HTML-to-native bridge literal is missing/ambiguous")
    bridge_literal = literals[0]
    # Ensure the actual packed bridge implementation still injects this JS.
    packed_functions = {value.co_name: value for value in packed_native_bridge.co_consts
                        if isinstance(value, types.CodeType)}
    server = packed_functions.get("serve_accounting_page")
    if server is None or "JS_BRIDGE" not in _recursive_code_names(server):
        raise QABlocked("Packed HTTP-host-to-HTML JS bridge not established")
    recover_method = "tarazIntegrationRecover"
    if ("tarazIntegrationList" not in bridge_literal
            or "tarazIntegrationReview" not in bridge_literal):
        raise QABlocked("Actual packaged HTML bridge lacks baseline Taraz Inbox methods")
    native_methods = provenance.get("packedDesktopMethods", ())
    if recover_method not in native_methods:
        raise QABlocked("Native recover method absent from exact QA EXE")
    ui_assets = [name for name in archive.toc
                 if name.replace("\\", "/").startswith("dist/assets/")
                 and name.lower().endswith(".js")]
    if not ui_assets or len(ui_assets) > 8:
        raise QABlocked("Bounded packed React UI JavaScript assets unavailable")
    packed_ui_recovery_present = any(
        recover_method.encode("ascii") in archive.extract(name)
        for name in ui_assets)
    if not packed_ui_recovery_present:
        raise QABlocked("Actual packaged React UI lacks a recovery reference")

    return {
        "qaExeSha256": provenance["exeSha256"],
        "sourceSnapshotSha256": provenance["sourceSnapshotSha256"],
        "packedIntegrationPyzSha256": provenance["packedModuleSha256"],
        "noLedgerGateBeforeNativeWindow": True,
        "nativeHistoryGuardRequiresRevisionAtLeast608": True,
        "nativeHistoryGuardRequiresActualNamedPersonalEvents": True,
        "packedNativeRecoverMethodPresent": True,
        "packedHtmlBridgeHasList": True,
        "packedHtmlBridgeHasReview": True,
        "packedHtmlBridgeHasRecover": recover_method in bridge_literal,
        "packedReactExpectsRecover": packed_ui_recovery_present,
        "nativeJsBridgeMissingRecoverBug": recover_method not in bridge_literal,
        "nativeFullRecoveryUiPossibleWithoutLedger": False,
        "nativeFullRecoveryUiPossibleWithCurrentBridge": recover_method in bridge_literal,
        "examinedActualPackedHtmlBridgeCode": True,
        "launchPerformed": False,
        "financialPostingTested": False,
    }


def verify_newest_packed_raw_member():
    """Optional no-launch post-fix EXE: immutable *compressed* PYZ bytes pin.

    Does not trust marshal.dumps(code) as a content fingerprint: hash the raw
    PYZ archive member between its validated offset/length after exe+manifest
    and complete source snapshot pins have been checked.
    """
    runner = prior_runner()
    helper = runner.previous_runner()
    build = runner.QA_PARENT / NEWEST_QA_BUILD_NAME
    exe = build / "pyinstaller" / "dist" / "Taraz-MTR-QA-bf41a4980db3.exe"
    report_path = build / "qa-build-report.json"
    snapshot = build / "snapshot"
    for item in (runner.QA_PARENT, build, exe, report_path, snapshot):
        helper.refuse_link(item)
    if not exe.is_file() or not report_path.is_file() or exe.stat().st_size != 16977131:
        raise QABlocked("Post-fix QA artifact was replaced, missing or size changed")
    try:
        manifest = json.loads(report_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as error:
        raise QABlocked("Post-fix build manifest invalid") from error
    required = {
        "status": "QA_BUNDLE_VERIFIED", "qaOnly": True,
        "installed": False, "realLedgerAccessed": False,
        "releaseReady": False, "sourceInputCount": 121,
        "sourceSnapshotSha256": NEWEST_SNAPSHOT_SHA,
        "exeSha256": NEWEST_QA_EXE_SHA,
        "exeSizeBytes": 16977131, "exe": str(exe), "output": str(build),
    }
    if not isinstance(manifest, dict) or any(manifest.get(k) != v for k, v in required.items()):
        raise QABlocked("Post-fix QA manifest does not match exact artifact pin")
    for key in ("uiInboxReferences", "packedNativeInboxMethods"):
        if not isinstance(manifest.get(key), dict) or any(
                manifest[key].get(method) is not True for method in
                ("tarazIntegrationList", "tarazIntegrationReview", "tarazIntegrationRecover")):
            raise QABlocked("Post-fix QA build methods were not attested")
    if helper.digest(exe) != NEWEST_QA_EXE_SHA:
        raise QABlocked("Post-fix QA EXE hash mismatch")
    inventory = helper.snapshot_inventory(snapshot)
    if (len(inventory) != 121 or
            hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
            != NEWEST_SNAPSHOT_SHA):
        raise QABlocked("Post-fix 121-source SHA snapshot mismatch")

    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    toc_entry = pyz.toc.get("taraz_integration")
    if (not isinstance(toc_entry, tuple) or len(toc_entry) != 3 or
            any(type(value) is not int for value in toc_entry) or
            toc_entry[0] != 0 or toc_entry[1] < 0 or
            not 0 < toc_entry[2] <= 262144):
        raise QABlocked("Untrusted compressed PYZ module offset or length")
    offset = pyz._start_offset + toc_entry[1]
    length = toc_entry[2]
    if offset < 0 or offset + length > exe.stat().st_size:
        raise QABlocked("Compressed PYZ member escaped pinned executable")
    with exe.open("rb") as handle:
        handle.seek(offset)
        compressed = handle.read(length)
    raw_hash = hashlib.sha256(compressed).hexdigest()
    if len(compressed) != length or raw_hash != NEWEST_RAW_PYZ_MEMBER_SHA:
        raise QABlocked("Post-fix compressed PYZ member hash does not match pin")
    code = pyz.extract("taraz_integration")
    if not isinstance(code, types.CodeType):
        raise QABlocked("Post-fix packed Taraz integration code was not extracted")
    functions = {member.co_name for member in code.co_consts
                 if isinstance(member, types.CodeType)}
    if not {"review_request", "list_requests", "list_recoverable_reviews",
            "recover_review", "_atomic_json"}.issubset(functions):
        raise QABlocked("Post-fix packed metadata-review implementation missing")
    bridge = pyz.extract("standalone_accounting_desktop")
    literals = [item for item in bridge.co_consts if isinstance(item, str) and
                "window.madar = Object.fromEntries" in item] if isinstance(bridge, types.CodeType) else []
    if len(literals) != 1:
        raise QABlocked("Post-fix packed HTML native bridge was not recovered")
    return code, {
        "status": "POST_FIX_QA_PYZ_RAW_MEMBER_PIN_VERIFIED",
        "postFixQaExeSha256": NEWEST_QA_EXE_SHA,
        "postFixSource121SnapshotSha256": NEWEST_SNAPSHOT_SHA,
        "stableRawCompressedPyzMemberSha256": raw_hash,
        "packedJsBridgeExposesRecover": "tarazIntegrationRecover" in literals[0],
        "packedModuleExecuted": False, "exeLaunched": False,
        "syntheticOnly": True, "installed": False,
    }


def verify_newest_synthetic_recovery():
    """Test latest source fixes safely; never open GUI or create an account."""
    code, provenance = verify_newest_packed_raw_member()
    runner = prior_runner()
    helper = runner.previous_runner()
    with helper.sandbox() as root:
        instance = helper.load_packed_module(code)
        request_id = uuid.uuid4().hex
        source = helper.write_proposal(root, request_id)
        pending_source = source.read_bytes()
        dest = root / "reviewed" / (request_id + ".json")
        intent = root / "reviewed" / (request_id + ".intent.json")
        receipt = root / "reviewed" / (request_id + ".review.json")
        original_rename = instance.os.rename

        def crash_before_move(src, target):
            if str(src) == str(source):
                raise OSError("synthetic after-intent before-move failure")
            return original_rename(src, target)

        with patch.object(instance.os, "rename", side_effect=crash_before_move):
            try:
                instance.review_request(root, request_id, "rejected")
            except OSError as error:
                if "synthetic after-intent" not in str(error):
                    raise
            else:
                raise QABlocked("Synthetic interruption did not occur")
        if (not intent.is_file() or not source.is_file() or dest.exists()
                or receipt.exists()):
            raise QABlocked("Post-fix pre-move intent not durable")
        pending = instance.list_requests(root)["requests"]
        recovery = instance.list_recoverable_reviews(root)
        if pending or len(recovery["recovery"]) != 1 or recovery["recovery"][0]["state"] != "rejected":
            raise QABlocked("Post-fix source still displays duplicate pending decision")
        done = instance.recover_review(root, request_id)
        if done != {"id": request_id, "state": "rejected", "financialEventCreated": False}:
            raise QABlocked("Post-fix manual recovery returned malformed metadata")
        if dest.read_bytes() != pending_source or not receipt.is_file():
            raise QABlocked("Post-fix recovery did not persist original metadata")
        complete = instance.list_recoverable_reviews(root)
        if complete["recovery"]:
            raise QABlocked("Completed post-fix recovery still appears pending")
        dest.write_bytes(pending_source + b" ")
        damaged = instance.list_recoverable_reviews(root)
        if damaged["recovery"] or damaged["recoveryInvalidCount"] != 1:
            raise QABlocked("Post-fix complete receipt ignored tampered source")
        return {**provenance,
                "status": "POST_FIX_QA_PYZ_SYNTHETIC_RECOVERY_PASS",
                "packedModuleExecuted": True,
                "preMoveIntentSuppressesDuplicatePending": True,
                "completedReceiptSourceTamperFlagged": True,
                "manualRecoveryNonfinancial": True,
                "qaExeLaunched": False}


def _create_synthetic_interrupted_review(root: Path, request_id: str) -> dict:
    """Runs pinned PYZ review only in an isolated QA child; no forged receipt."""
    runner = prior_runner()
    helper = runner.previous_runner()
    helper.verify_scratch(root)
    if not _QA_ID.fullmatch(request_id):
        raise QABlocked("Unsafe synthetic request identifier")
    code, _ = runner.verify_latest_bundle()
    packed = helper.load_packed_module(code)
    bridge = Path(os.environ["LOCALAPPDATA"]) / "Madar-Taraz-Bridge"
    helper.refuse_link(bridge)
    if bridge.exists():
        raise QABlocked("QA bridge already exists; create-only synthetic fixture")
    (bridge / "pending").mkdir(parents=True)
    pending = helper.write_proposal(bridge, request_id)
    before = pending.read_bytes()
    receipt = bridge / "reviewed" / (request_id + ".review.json")
    original_atomic = packed._atomic_json

    def crash_after_move(path, value):
        if path == receipt:
            raise OSError("QA synthetic crash immediately before receipt publication")
        return original_atomic(path, value)

    with patch.object(packed, "_atomic_json", side_effect=crash_after_move):
        try:
            packed.review_request(bridge, request_id, "reviewed")
        except OSError as exc:
            if "QA synthetic crash" not in str(exc):
                raise
        else:
            raise QABlocked("Synthetic interruption was unexpectedly bypassed")
    moved = bridge / "reviewed" / (request_id + ".json")
    intent = bridge / "reviewed" / (request_id + ".intent.json")
    metadata = json.loads(intent.read_text(encoding="utf-8"))
    if (pending.exists() or moved.read_bytes() != before or receipt.exists()
            or metadata.get("sourceDigest") != hashlib.sha256(before).hexdigest()
            or metadata.get("state") != "reviewed"
            or metadata.get("financialEventCreated") is not False):
        raise QABlocked("Packed synthetic crash fixture is not durable/nonfinancial")
    return {"bridge": str(bridge), "id": request_id,
            "movedSha256": hashlib.sha256(moved.read_bytes()).hexdigest(),
            "intentSha256": hashlib.sha256(intent.read_bytes()).hexdigest(),
            "receiptAbsent": True}


def _isolated_env(root: Path):
    runner = prior_runner()
    helper = runner.previous_runner()
    helper.verify_scratch_marker(root)
    env = helper.sandbox_env(root)
    env.pop("TARAZ_QA_REPORT", None)
    env.pop("TARAZ_DATA_DIR", None)
    ledger_dir = Path(env["TARAZ_QA_DATA_DIR"])
    if (ledger_dir / NO_LEDGER).exists():
        raise QABlocked("An accounting book exists in this QA root; GUI launch refused")
    # The override must remain a recognized QA-only path; no fallback to
    # APPDATA/Taraz or installed user profile is permitted.
    if "qa" not in [p.lower() for p in ledger_dir.parts]:
        raise QABlocked("Native QA data-directory override does not meet guard")
    for field in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "HOME", "USERPROFILE"):
        value = Path(env[field])
        if not value.is_relative_to(root):
            raise QABlocked("QA native child environment escaped isolated root")
    return env, ledger_dir


def _run_pinned_exe(root: Path, max_seconds: float = 15.) -> dict:
    """Start only pinned QA EXE and kill its process tree if it remains open."""
    import psutil

    runner = prior_runner()
    helper = runner.previous_runner()
    helper.verify_scratch_marker(root)
    env, ledger_dir = _isolated_env(root)
    if runner.EXE.resolve() != Path(runner.BUILD / "pyinstaller" / "dist" /
                                     "Taraz-MTR-QA-52f6b2776362.exe").resolve():
        raise QABlocked("Executable target must be exact QA-only bundle")
    if helper.digest(runner.EXE) != EXPECTED_EXE_SHA:
        raise QABlocked("QA executable changed immediately before launch")
    if not 2.0 <= max_seconds <= 20.0:
        raise QABlocked("Unbounded native GUI QA process timeout")

    started = time.monotonic()
    # --windowed one-file PyInstaller might display a modal error on an
    # unhandled startup exception; never mistake such an alert for a GUI pass.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    launched = subprocess.Popen(
        [str(runner.EXE)], cwd=str(root), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, creationflags=flags)
    observed = psutil.Process(launched.pid)
    seen_descendants = []
    seen_webview = False
    timeout = False
    exit_code = None
    try:
        while time.monotonic() - started < max_seconds:
            if launched.poll() is not None:
                exit_code = launched.returncode
                break
            try:
                descendants = observed.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                descendants = []
            for child in descendants:
                try:
                    desc = child.name().lower()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if desc == "msedgewebview2.exe":
                    seen_webview = True
                seen_descendants.append((child.pid, child.create_time()))
            time.sleep(0.1)
        else:
            timeout = True
    finally:
        # Clean only descendants of the exact newly launched QA executable;
        # never stop any installed Taraz or unrelated user processes.
        processes = []
        for pid, birth in dict.fromkeys(seen_descendants):
            try:
                process = psutil.Process(pid)
                if abs(process.create_time() - birth) < 0.1:
                    processes.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            processes.extend(observed.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        processes.append(observed)
        for process in reversed(processes):
            try:
                if process.is_running():
                    process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        psutil.wait_procs(processes, timeout=3.)
        try:
            launched.wait(timeout=3)
        except subprocess.TimeoutExpired:
            raise QABlocked("Owned QA EXE did not terminate after bounded cleanup")

    if not ledger_dir.is_dir() or (ledger_dir / NO_LEDGER).exists():
        raise QABlocked("QA startup wrote an unauthorized ledger or missing data directory")
    return {"qaExecutableWasActuallyLaunched": True,
            "qaExecutableProcessExitedWithoutManualInteraction": not timeout,
            "qaExecutableExitCode": exit_code,
            "windowedExecutableNeededForcedTermination": timeout,
            "webView2DescendantObserved": seen_webview,
            "syntheticLedgerCreated": False,
            "realAccountingProfileTouched": False,
            "elapsedSeconds": round(time.monotonic() - started, 3)}


def _prepare_child(root: Path, ident: str) -> dict:
    runner = prior_runner()
    helper = runner.previous_runner()
    helper.verify_scratch(root)
    fixture = _create_synthetic_interrupted_review(root, ident)
    return {"status": "PINNED_SYNTHETIC_CRASH_FIXTURE_CREATED",
            "synthetic": True, "requestId": ident,
            "fixtureSourceSha256": fixture["movedSha256"],
            "intentSha256": fixture["intentSha256"],
            "receiptAbsent": True, "financialEventCreated": False}


def run_probe(*, launch: bool = True):
    report = inspect_native_qa_gate()
    runner = prior_runner()
    helper = runner.previous_runner()
    with helper.sandbox() as root:
        env, ledger_dir = _isolated_env(root)
        request_id = uuid.uuid4().hex
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
             "--prepare-child", "--root", str(root), "--request-id", request_id],
            cwd=root, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False)
        if result.returncode != 0:
            raise QABlocked("Synthetic packed-PYZ QA fixture creation was refused")
        fixture = json.loads(result.stdout)
        if fixture.get("status") != "PINNED_SYNTHETIC_CRASH_FIXTURE_CREATED":
            raise QABlocked("Synthetic packed-PYZ metadata fixture is not attested")
        bridge = Path(env["LOCALAPPDATA"]) / "Madar-Taraz-Bridge"
        reviewed = bridge / "reviewed"
        receipt = reviewed / (request_id + ".review.json")
        payload = reviewed / (request_id + ".json")
        intent = reviewed / (request_id + ".intent.json")
        before = (hashlib.sha256(payload.read_bytes()).hexdigest(),
                  hashlib.sha256(intent.read_bytes()).hexdigest())
        if receipt.exists() or (ledger_dir / NO_LEDGER).exists():
            raise QABlocked("Disposable GUI preflight unexpectedly created ledger or receipt")

        launched = _run_pinned_exe(root) if launch else {"qaExecutableWasActuallyLaunched": False}
        after = (hashlib.sha256(payload.read_bytes()).hexdigest(),
                 hashlib.sha256(intent.read_bytes()).hexdigest())
        if before != after or receipt.exists():
            raise QABlocked("QA executable altered synthetic durable metadata without operator action")
        if launched.get("webView2DescendantObserved", False):
            raise QABlocked("Unexpected WebView2 startup in a no-ledger QA profile")
        if launch and launched.get("qaExecutableExitCode") == 0:
            raise QABlocked("Pinned QA EXE unexpectedly claimed no-ledger success")
        if launch and launched.get("qaExecutableProcessExitedWithoutManualInteraction") is False:
            # A PyInstaller --windowed unhandled-error dialog may prevent exit.
            # Already terminated safely. It is a HARD GUI gate, not a pass.
            status = "GUI_STARTUP_BLOCKED_WINDOWED_ERROR_DIALOG_OR_TIMEOUT"
        elif launch:
            status = "GUI_STARTUP_BLOCKED_NO_AUTHENTICATED_LEDGER"
        else:
            status = "GUI_NOT_LAUNCHED_READONLY_PRECHECK"
        return {**report, **launched,
                "status": status,
                "launchPerformed": launched.get("qaExecutableWasActuallyLaunched", False),
                "actualNativeWebView2RecoveryGuiVerified": False,
                "realAuthenticatedRecoveryVerified": False,
                "syntheticSourceAndIntentUnchanged": True,
                "syntheticReceiptStillAbsent": True,
                "realFinancialOperationsExecuted": False,
                "installedTarazExeLaunched": False,
                "syntheticQaProfileOnly": True,
                "sourceGuardBypassed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--post-fix-static-only", action="store_true")
    parser.add_argument("--post-fix-synthetic", action="store_true")
    parser.add_argument("--prepare-child", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--request-id", default="")
    args = parser.parse_args()
    try:
        if sum(bool(k) for k in (args.prepare_child, args.static_only,
                                args.post_fix_static_only, args.post_fix_synthetic)) > 1:
            raise QABlocked("Conflicting QA mode switches")
        if args.prepare_child:
            if args.static_only or args.root is None:
                raise QABlocked("Invalid synthetic child arguments")
            answer = _prepare_child(args.root, args.request_id)
        elif args.static_only:
            if args.root is not None or args.request_id:
                raise QABlocked("Static QA inspection accepts no data paths")
            answer = inspect_native_qa_gate()
        elif args.post_fix_static_only:
            if args.root is not None or args.request_id:
                raise QABlocked("Post-fix QA accepts no user-supplied paths")
            _, answer = verify_newest_packed_raw_member()
        elif args.post_fix_synthetic:
            if args.root is not None or args.request_id:
                raise QABlocked("Post-fix QA accepts no user-supplied paths")
            answer = verify_newest_synthetic_recovery()
        else:
            if args.root is not None or args.request_id:
                raise QABlocked("Explicit real-profile/bridge paths are forbidden")
            answer = run_probe()
        print(json.dumps(answer, sort_keys=True, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "type": type(exc).__name__,
                          "message": str(exc)[:200]}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
