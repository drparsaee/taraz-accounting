"""Exercise the exact newest QA-only Taraz PYZ recovery code, in a disposable child.

Never launches a Taraz executable, imports taraz_desktop, authenticates a user,
posts finance, accesses a real app profile or changes the project source.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import subprocess
import sys
import types
import uuid
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
PREVIOUS_RUNNER = SCRIPT_DIR / "qa_mtr_current_bundle_review_20261110.py"
QA_PARENT = Path(r"D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110")
BUILD = QA_PARENT / "qa-52f6b2776362"
EXE = BUILD / "pyinstaller" / "dist" / "Taraz-MTR-QA-52f6b2776362.exe"
MANIFEST = BUILD / "qa-build-report.json"
EXE_SHA256 = "f3c4d65418d8f9d80a40618c01bb1534841ca18bf863fd9d09d5ca0fb8449662"
SNAPSHOT_SHA256 = "cedd3c8cc51802afe0270cbd08971a1f67347ed3a269d7ec5908fe4c62b6f0cc"
PYZ_MODULE_SHA256 = "e2c12afc893dff7ab04ba090266e15172309ba4a2e90a6869106fe974e7a457e"
EXE_SIZE_BYTES = 16976264
SOURCE_INPUT_COUNT = 120
EXPECTED_MODULE_FUNCTIONS = frozenset((
    "list_requests", "review_request", "_atomic_json", "_request_lock",
    "_read_marker", "_validate_intent", "list_recoverable_reviews",
    "recover_review",
))
EXPECTED_REVIEW_METHODS_IN_MANIFEST = frozenset((
    "review_request", "recover_review", "list_recoverable_reviews",
    "_atomic_json", "_request_lock", "_validate_intent", "_read_record",
))
EXPECTED_NATIVE_METHODS = frozenset((
    "tarazIntegrationList", "tarazIntegrationReview", "tarazIntegrationRecover",
))
EXPECTED_RECEIPT = {"financialEventCreated": False}


class QABlocked(RuntimeError):
    """QA gate or untrusted input has failed; no fallback is allowed."""


def previous_runner():
    """Load the previous QA helper read-only, without invoking its CLI/smoke."""
    if not PREVIOUS_RUNNER.is_file() or PREVIOUS_RUNNER.is_symlink():
        raise QABlocked("Previous pinned QA helper is unavailable")
    spec = importlib.util.spec_from_file_location(
        "mtr_previous_packed_bundle_readonly_qa", PREVIOUS_RUNNER)
    if spec is None or spec.loader is None:
        raise QABlocked("Previous QA helper cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _code_names(code: types.CodeType) -> set[str]:
    names = {code.co_name}
    for item in code.co_consts:
        if isinstance(item, types.CodeType):
            names.update(_code_names(item))
    return names


def verify_latest_bundle():
    """Verify exact EXE, build manifest, 120-file snapshot and actual PYZ code."""
    if sys.version_info[:2] != (3, 12):
        raise QABlocked("Python 3.12 required for pinned PYZ code")
    helper = previous_runner()
    for path in (QA_PARENT, BUILD, EXE, MANIFEST, BUILD / "snapshot"):
        helper.refuse_link(path)
    if not EXE.is_file() or not MANIFEST.is_file():
        raise QABlocked("Latest QA-only bundle or build manifest absent")
    try:
        report = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise QABlocked("Unreadable QA-only build manifest") from exc
    expected = {
        "status": "QA_BUNDLE_VERIFIED", "qaOnly": True,
        "installed": False, "realLedgerAccessed": False, "releaseReady": False,
        "exe": str(EXE), "output": str(BUILD),
        "exeSha256": EXE_SHA256, "exeSizeBytes": EXE_SIZE_BYTES,
        "sourceSnapshotSha256": SNAPSHOT_SHA256,
        "sourceInputCount": SOURCE_INPUT_COUNT,
    }
    if not isinstance(report, dict) or any(
        report.get(key) != value for key, value in expected.items()
    ):
        raise QABlocked("Newest QA-only build manifest pin mismatch")
    packed_api = report.get("packedNativeInboxMethods")
    packed_ui = report.get("uiInboxReferences")
    durable = report.get("packedDurableReview")
    if not isinstance(packed_api, dict) or not isinstance(packed_ui, dict):
        raise QABlocked("Missing packed native or UI references in build manifest")
    if not isinstance(durable, dict) or durable.get("sourceBoundDurableIntentCode") is not True:
        raise QABlocked("Newest packed durable-review evidence is missing")
    if any(packed_api.get(method) is not True or packed_ui.get(method) is not True
           for method in EXPECTED_NATIVE_METHODS):
        raise QABlocked("Newest build manifest lacks required three Inbox methods")
    if not EXPECTED_REVIEW_METHODS_IN_MANIFEST.issubset(durable.get("reviewMethods", ())):
        raise QABlocked("Newest build manifest lacks recovery implementation")
    if helper.digest(EXE) != EXE_SHA256 or EXE.stat().st_size != EXE_SIZE_BYTES:
        raise QABlocked("Newest QA executable SHA-256 or size mismatch")
    fingerprint_map = helper.snapshot_inventory(BUILD / "snapshot")
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_map, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if len(fingerprint_map) != SOURCE_INPUT_COUNT or fingerprint != SNAPSHOT_SHA256:
        raise QABlocked("Newest source snapshot is not the pinned build snapshot")

    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(EXE))
    if "taraz_desktop" not in archive.toc:
        raise QABlocked("QA archive lacks desktop entrypoint")
    desktop_bytes = archive.extract("taraz_desktop")
    if not isinstance(desktop_bytes, bytes):
        raise QABlocked("QA archive desktop entrypoint cannot be inspected")
    native = marshal.loads(desktop_bytes)  # static code object only: never exec
    if not isinstance(native, types.CodeType):
        raise QABlocked("Unexpected packed desktop code format")
    if not EXPECTED_NATIVE_METHODS.issubset(_code_names(native)):
        raise QABlocked("Packed Taraz desktop lacks new native recovery method")

    packed = archive.open_embedded_archive("PYZ.pyz").extract("taraz_integration")
    if not isinstance(packed, types.CodeType):
        raise QABlocked("Packed Taraz integration PYZ code unavailable")
    module_sha = hashlib.sha256(marshal.dumps(packed)).hexdigest()
    if module_sha != PYZ_MODULE_SHA256:
        raise QABlocked("Latest actual PYZ integration code object SHA-256 mismatch")
    functions = {
        item.co_name: item for item in packed.co_consts
        if isinstance(item, types.CodeType)
    }
    if not EXPECTED_MODULE_FUNCTIONS.issubset(functions):
        raise QABlocked("Packed integration lacks recovery function definitions")
    if ("link" not in functions["_atomic_json"].co_names
            or "_request_lock" not in functions["review_request"].co_names
            or "review_request" not in functions["recover_review"].co_names):
        raise QABlocked("Missing packed atomic marker/recovery control flow")
    return packed, {
        "status": "PINNED_LATEST_QA_PYZ_VERIFIED",
        "exeSha256": EXE_SHA256,
        "sourceSnapshotSha256": SNAPSHOT_SHA256,
        "packedModuleSha256": module_sha,
        "packedRecoveryFunctions": sorted(EXPECTED_MODULE_FUNCTIONS),
        "packedDesktopMethods": sorted(EXPECTED_NATIVE_METHODS),
        "sourceInputCount": SOURCE_INPUT_COUNT,
        "qaOnly": True, "exeLaunched": False, "installed": False,
        "financialPosted": False,
    }


def child_run(root: Path, action: str, request_id: str, decision: str,
              fault: str, manual_action: bool) -> dict:
    helper = previous_runner()
    helper.verify_scratch(root)
    packed, provenance = verify_latest_bundle()
    # Import/execute only SHA-verified taraz_integration PYZ bytecode.
    integration = helper.load_packed_module(packed)
    if action == "list-recoverable":
        if request_id or decision or fault or manual_action:
            raise QABlocked("Read-only recovery list has unexpected arguments")
        result = integration.list_recoverable_reviews(root)
        if not isinstance(result.get("recovery"), list) or result.get(
            "recoveryInvalidCount", -1) < 0:
            raise QABlocked("Invalid packed recovery listing")
        for item in result["recovery"]:
            if item.get("financialEventCreated") is not False:
                raise QABlocked("Recovery list claimed a financial event")
        return {"ok": True, "provenance": provenance, "listing": result}

    if not helper.ID.fullmatch(request_id):
        raise QABlocked("Only valid synthetic metadata identifiers are supported")
    if action == "recover":
        if decision or fault or not manual_action:
            raise QABlocked("Recovery requires explicit manual acknowledgement")
        result = integration.recover_review(root, request_id)
    elif action == "review":
        if decision not in ("reviewed", "rejected") or manual_action:
            raise QABlocked("Only explicit metadata review/rejection is allowed")
        if fault not in ("", "before-receipt"):
            raise QABlocked("Unknown synthetic interruption stage")
        receipt = root / "reviewed" / (request_id + ".review.json")
        original_atomic = integration._atomic_json

        def interrupt(path, payload):
            if fault == "before-receipt" and path == receipt:
                raise OSError("synthetic crash after move, before receipt")
            return original_atomic(path, payload)

        with patch.object(integration, "_atomic_json", side_effect=interrupt):
            result = integration.review_request(root, request_id, decision)
    else:
        raise QABlocked("Unsupported packaged integration QA action")
    if result != {"id": request_id, "state": result.get("state"),
                  "financialEventCreated": False}:
        raise QABlocked("Unexpected packed metadata recovery response")
    if result["state"] not in ("reviewed", "rejected"):
        raise QABlocked("Packed metadata decision has unsupported state")
    return {"ok": True, "provenance": provenance, "receipt": result}


def spawn_child(root: Path, action: str, request_id: str = "", decision: str = "",
                *, fault: str = "", manual_action: bool = False):
    helper = previous_runner()
    helper.verify_scratch_marker(root)
    if action not in ("list-recoverable", "review", "recover"):
        raise QABlocked("Unsupported recovery QA action")
    if fault not in ("", "before-receipt"):
        raise QABlocked("Unsupported simulated crash stage")
    env = helper.sandbox_env(root)
    command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
               "--child", "--root", str(root), "--action", action,
               "--request-id", request_id, "--decision", decision,
               "--fault", fault]
    if manual_action:
        command.append("--manual-action")
    return subprocess.run(
        command, cwd=root, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8",
        errors="replace", timeout=30, check=False)


def parse_child(outcome, *, success: bool) -> dict:
    if (outcome.returncode == 0) != success:
        raise AssertionError("Unexpected child status: " +
                             (outcome.stderr if success else outcome.stdout)[:240])
    text = outcome.stdout if success else outcome.stderr
    if len(text) > 32768:
        raise QABlocked("Excessive child QA result")
    parsed = json.loads(text.strip())
    if bool(parsed.get("ok")) != success:
        raise QABlocked("Child result does not match process exit status")
    return parsed


def smoke() -> dict:
    _, provenance = verify_latest_bundle()
    helper = previous_runner()
    with helper.sandbox() as root:
        ids = {"reviewed": uuid.uuid4().hex, "rejected": uuid.uuid4().hex,
               "legacy": uuid.uuid4().hex}
        for identifier in ids.values():
            helper.write_proposal(root, identifier)
        for decision in ("reviewed", "rejected"):
            identifier = ids[decision]
            pending = root / "pending" / (identifier + ".json")
            before = pending.read_bytes()
            crashed = parse_child(
                spawn_child(root, "review", identifier, decision,
                            fault="before-receipt"), success=False)
            if crashed.get("exception") != "OSError":
                raise QABlocked("No deterministic after-move synthetic crash")
            dest = root / "reviewed" / (identifier + ".json")
            intent = root / "reviewed" / (identifier + ".intent.json")
            receipt = root / "reviewed" / (identifier + ".review.json")
            if (pending.exists() or dest.read_bytes() != before or
                    not intent.is_file() or receipt.exists()):
                raise QABlocked("After-move synthetic state was not preserved")
            listed = parse_child(spawn_child(root, "list-recoverable"), success=True)
            recovery = listed["listing"]["recovery"]
            if not any(item["id"] == identifier and
                       item["state"] == decision and
                       item["financialEventCreated"] is False for item in recovery):
                raise QABlocked("Packed operator list omitted persisted decision")
            resumed = parse_child(spawn_child(
                root, "recover", identifier, manual_action=True), success=True)
            if resumed["receipt"] != {
                "id": identifier, "state": decision, "financialEventCreated": False
            }:
                raise QABlocked("Packed operator recovery changed persisted decision")
            if not receipt.is_file():
                raise QABlocked("Operator recovery did not durably persist receipt")
            listed_after = parse_child(spawn_child(root, "list-recoverable"),
                                       success=True)
            if any(item["id"] == identifier for item in
                   listed_after["listing"]["recovery"]):
                raise QABlocked("Completed review remained incorrectly recoverable")
        legacy = ids["legacy"]
        (root / "reviewed").mkdir(exist_ok=True)
        (root / "reviewed" / (legacy + ".review.json")).write_text(
            json.dumps({"schema": 1, "id": legacy, "state": "reviewed",
                        "financialEventCreated": False}), encoding="utf-8")
        before_legacy = (root / "pending" / (legacy + ".json")).read_bytes()
        list_legacy = parse_child(spawn_child(root, "list-recoverable"), success=True)
        if any(item["id"] == legacy for item in list_legacy["listing"]["recovery"]):
            raise QABlocked("Legacy no-intent marker appeared recoverable")
        denied = parse_child(spawn_child(root, "recover", legacy,
                                          manual_action=True), success=False)
        if denied.get("exception") != "FileNotFoundError":
            raise QABlocked("Legacy no-intent recovery was not refused")
        if (root / "pending" / (legacy + ".json")).read_bytes() != before_legacy:
            raise QABlocked("Legacy denial changed original synthetic proposal")
        return {**provenance, "status": "LATEST_PACKED_OPERATOR_RECOVERY_QA_PASS",
                "reviewedAfterMoveRecovered": True,
                "rejectedAfterMoveRecovered": True,
                "postRecoveryListingEmpty": True,
                "legacyNoIntentRefused": True, "manualOnly": True,
                "dataType": "SYNTHETIC_METADATA_ONLY",
                "actualTarazExeLaunched": False, "ledgerAccessed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--action", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--decision", default="")
    parser.add_argument("--fault", default="")
    parser.add_argument("--manual-action", action="store_true")
    args = parser.parse_args()
    try:
        if args.child:
            if args.manifest_only or not args.root:
                raise QABlocked("Invalid child QA invocation")
            result = child_run(args.root, args.action, args.request_id, args.decision,
                               args.fault, args.manual_action)
        elif args.manifest_only:
            _, result = verify_latest_bundle()
        else:
            result = smoke()
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "exception": type(exc).__name__,
                          "reason": str(exc)[:160]}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
