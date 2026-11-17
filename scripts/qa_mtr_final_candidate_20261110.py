"""Exact final-candidate QA EXE: packed HTML bridge and synthetic PYZ restart.

Never starts an EXE, native GUI, accounting source guard, company book or
financial API. Runs only verified taraz_integration PYZ code on a marked
disposable root, through a fresh Python -I -B child for each review operation.
This is NOT working-tree parity, signoff or installed Taraz acceptance.
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


REPO = Path(__file__).resolve().parents[1]
OLD_HELPER = REPO / "scripts" / "qa_mtr_current_bundle_review_20261110.py"
BUILD = Path(r"D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110\qa-adca5e6e4b71")
EXE = BUILD / "pyinstaller" / "dist" / "Taraz-MTR-QA-adca5e6e4b71.exe"
MANIFEST = BUILD / "qa-build-report.json"
EXE_SHA = "3e467d404e9e08ffc5da09fe4cf000cc7c3b4a75f0e59dcd7d8141e38d2fd922"
SNAPSHOT_SHA = "8d63fcd04421b391b9d5f1baed0750b0d349f4bb890d47bcb78c6bfe786acc22"
RAW_PYZ_SHA = "71cc3e7a22d471f01a5cf6e0da4eb1fab97f05d6893dac7cf4783b64ed79b036"
EXE_SIZE = 16976717
SOURCE_COUNT = 121
METHODS = ("tarazIntegrationList", "tarazIntegrationReview", "tarazIntegrationRecover")
REVIEW_METHODS = {"_atomic_json", "_request_lock", "_validate_intent",
                  "review_request", "recover_review", "list_requests",
                  "list_recoverable_reviews"}


class QABlocked(RuntimeError):
    """Deny unexpected paths, schema, package, or financial claims."""


def helper():
    if not OLD_HELPER.is_file() or OLD_HELPER.is_symlink():
        raise QABlocked("Trusted read-only synthetic QA helper missing")
    spec = importlib.util.spec_from_file_location("mtr_final_candidate_old_qa", OLD_HELPER)
    if spec is None or spec.loader is None:
        raise QABlocked("Cannot load read-only QA helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _names(code: types.CodeType) -> set[str]:
    result = set(code.co_names)
    for item in code.co_consts:
        if isinstance(item, types.CodeType):
            result.update(_names(item))
    return result


def _functions(code: types.CodeType) -> set[str]:
    values = {code.co_name}
    for item in code.co_consts:
        if isinstance(item, types.CodeType):
            values.update(_functions(item))
    return values


def verify():
    """Exact SHA and manifest + actual raw-compressed PYZ and HTML bridge."""
    if sys.version_info[:2] != (3, 12):
        raise QABlocked("Python 3.12 required to read pinned packed code")
    h = helper()
    for path in (BUILD.parent, BUILD, EXE, MANIFEST, BUILD / "snapshot"):
        h.refuse_link(path)
    if not EXE.is_file() or not MANIFEST.is_file() or EXE.stat().st_size != EXE_SIZE:
        raise QABlocked("Final-candidate QA package missing or size changed")
    try:
        report = json.loads(MANIFEST.read_text(encoding="utf8"))
    except (ValueError, UnicodeError) as error:
        raise QABlocked("Final-candidate manifest malformed") from error
    expected = {
        "status": "QA_BUNDLE_VERIFIED", "qaOnly": True,
        "installed": False, "realLedgerAccessed": False, "releaseReady": False,
        "sourceInputCount": SOURCE_COUNT, "sourceSnapshotSha256": SNAPSHOT_SHA,
        "exe": str(EXE), "output": str(BUILD), "exeSha256": EXE_SHA,
        "exeSizeBytes": EXE_SIZE, "packedHtmlBridgeForwarderPresent": True,
    }
    if not isinstance(report, dict) or any(report.get(k) != v for k, v in expected.items()):
        raise QABlocked("Final-candidate QA manifest or provenance changed")
    for field in ("uiInboxReferences", "packedNativeInboxMethods", "packedHtmlBridgeMethods"):
        if not isinstance(report.get(field), dict) or not all(
            report[field].get(method) is True for method in METHODS
        ):
            raise QABlocked("One of three required native/HTML/React methods unproven")
    durability = report.get("packedDurableReview")
    if not isinstance(durability, dict) or (
        durability.get("sourceBoundDurableIntentCode") is not True
        or not {"review_request", "recover_review", "list_recoverable_reviews"}
        .issubset(durability.get("reviewMethods", ()))
    ):
        raise QABlocked("Final-candidate manifest lacks durable review methods")
    if h.digest(EXE) != EXE_SHA:
        raise QABlocked("Final-candidate QA EXE hash mismatch")
    inventory = h.snapshot_inventory(BUILD / "snapshot")
    observed_snapshot = hashlib.sha256(
        json.dumps(inventory, sort_keys=True).encode("utf8")
    ).hexdigest()
    if len(inventory) != SOURCE_COUNT or observed_snapshot != SNAPSHOT_SHA:
        raise QABlocked("Final-candidate QA source snapshot mismatch")

    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(EXE))
    if "taraz_desktop" not in archive.toc:
        raise QABlocked("Packed desktop entrypoint absent")
    desktop_code = marshal.loads(archive.extract("taraz_desktop"))
    if not isinstance(desktop_code, types.CodeType) or not set(METHODS).issubset(
        _functions(desktop_code)
    ):
        raise QABlocked("Actual packed native method definitions missing")
    pyz = archive.open_embedded_archive("PYZ.pyz")
    member = pyz.toc.get("taraz_integration")
    if (not isinstance(member, tuple) or len(member) != 3 or
        any(type(v) is not int for v in member) or member[0] != 0 or
        member[1] < 0 or not 0 < member[2] <= 262144):
        raise QABlocked("Unexpected PYZ member offset/size")
    offset = pyz._start_offset + member[1]
    if offset < 0 or offset + member[2] > EXE_SIZE:
        raise QABlocked("PYZ member out of executable bounds")
    with EXE.open("rb") as infile:
        infile.seek(offset)
        raw = infile.read(member[2])
    raw_digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != member[2] or raw_digest != RAW_PYZ_SHA:
        raise QABlocked("Raw compressed PYZ member SHA mismatch")

    code = pyz.extract("taraz_integration")
    if not isinstance(code, types.CodeType):
        raise QABlocked("Actual packed integration bytecode missing")
    funcs = {c.co_name: c for c in code.co_consts if isinstance(c, types.CodeType)}
    if not REVIEW_METHODS.issubset(funcs) or "link" not in funcs["_atomic_json"].co_names:
        raise QABlocked("Actual packaged durable, no-clobber review missing")
    bridge = pyz.extract("standalone_accounting_desktop")
    if not isinstance(bridge, types.CodeType):
        raise QABlocked("Actual packaged native HTML bridge module absent")
    bridge_literals = [s for s in bridge.co_consts if isinstance(s, str)
                       and "window.madar = Object.fromEntries" in s]
    serve = next((x for x in bridge.co_consts if isinstance(x, types.CodeType)
                  and x.co_name == "serve_accounting_page"), None)
    if len(bridge_literals) != 1 or serve is None or "JS_BRIDGE" not in _names(serve):
        raise QABlocked("Actual packed native HTTP->HTML forwarder missing")
    literal = bridge_literals[0]
    if not all("'" + method + "'" in literal for method in METHODS):
        raise QABlocked("Actual packed HTML JS_BRIDGE missing a native recovery method")
    # The compiled app itself must request the native method, not just its manifest.
    js_assets = [k for k in archive.toc
                 if k.replace("\\", "/").startswith("dist/assets/")
                 and k.endswith(".js")]
    if not js_assets or len(js_assets) > 8 or not any(
        b"tarazIntegrationRecover" in archive.extract(name) for name in js_assets
    ):
        raise QABlocked("Actual packaged React recovery call is absent")
    return code, {
        "status": "FINAL_CANDIDATE_QA_PACKED_PROVENANCE_VERIFIED",
        "exeSha256": EXE_SHA, "source121SnapshotSha256": SNAPSHOT_SHA,
        "stableRawCompressedPyzMemberSha256": raw_digest,
        "packedNativeMethods": list(METHODS),
        "packedHtmlJsBridgeMethods": list(METHODS),
        "packedReactRecoveryReference": True,
        "qaOnly": True, "exeLaunched": False, "installed": False,
        "currentWorkingTreeParityAttested": False,
    }


def _child(root: Path, action: str, request_id: str, manual: bool) -> dict:
    h = helper()
    h.verify_scratch(root)  # marker, absolute QA path, redirected 7 env paths
    code, evidence = verify()
    packed = h.load_packed_module(code)  # only vetted integration; no desktop import
    if action == "list":
        if request_id or manual:
            raise QABlocked("Read-only list accepts no mutation arguments")
        return {"ok": True, "action": action, "data": {
            "pending": packed.list_requests(root),
            "recovery": packed.list_recoverable_reviews(root),
        }, "rawPyzSha256": evidence["stableRawCompressedPyzMemberSha256"]}
    if action == "recover":
        if not manual or not h.ID.fullmatch(request_id):
            raise QABlocked("Recovery requires exact synthetic ID plus manual consent")
        response = packed.recover_review(root, request_id)
        if response != {"id": request_id, "state": response.get("state"),
                        "financialEventCreated": False} or response["state"] not in (
                            "reviewed", "rejected"):
            raise QABlocked("Untrusted packed finance/recovery response")
        return {"ok": True, "action": action, "data": response,
                "rawPyzSha256": evidence["stableRawCompressedPyzMemberSha256"]}
    if action == "stage":
        if manual or not h.ID.fullmatch(request_id):
            raise QABlocked("Only synthetic test setup allowed")
        # Separate test choices are made by the test, not from an untrusted
        # real operator/ledger. Use per-root, per-ID fixtures with explicit
        # decision set in QA config, never a live native API.
        decision = os.environ.get("MTR_QA_SYNTHETIC_DECISION")
        if decision not in ("reviewed", "rejected"):
            raise QABlocked("Synthetic-only decision missing")
        request = h.write_proposal(root, request_id)
        original = request.read_bytes()
        moved = root / "reviewed" / (request_id + ".json")
        intent = root / "reviewed" / (request_id + ".intent.json")
        receipt = root / "reviewed" / (request_id + ".review.json")
        original_atomic = packed._atomic_json

        def stop_after_move(path, payload):
            if path == receipt:
                raise OSError("synthetic after-move before-receipt interruption")
            return original_atomic(path, payload)

        with patch.object(packed, "_atomic_json", side_effect=stop_after_move):
            try:
                packed.review_request(root, request_id, decision)
            except OSError as error:
                if "synthetic after-move" not in str(error):
                    raise
            else:
                raise QABlocked("Synthetic interruption was not injected")
        intent_data = json.loads(intent.read_text(encoding="utf8"))
        if (request.exists() or moved.read_bytes() != original or receipt.exists()
            or intent_data["state"] != decision
            or intent_data["sourceDigest"] != hashlib.sha256(original).hexdigest()
            or intent_data["financialEventCreated"] is not False):
            raise QABlocked("Synthetic after-move fixture is not durable and nonfinancial")
        return {"ok": True, "action": action, "data": {
            "id": request_id, "decision": decision,
            "movedSha256": hashlib.sha256(original).hexdigest(),
            "intentSha256": hashlib.sha256(intent.read_bytes()).hexdigest(),
            "receiptAbsent": True, "financialEventCreated": False,
        }, "rawPyzSha256": evidence["stableRawCompressedPyzMemberSha256"]}
    raise QABlocked("Unknown packed synthetic action")


def spawn(root: Path, action: str, request_id: str = "", *,
          manual: bool = False, decision: str = "") -> dict:
    h = helper()
    h.verify_scratch_marker(root)
    if action not in ("list", "recover", "stage"):
        raise QABlocked("Unsupported packed recovery command")
    env = h.sandbox_env(root)
    if decision:
        if action != "stage" or decision not in ("reviewed", "rejected"):
            raise QABlocked("Synthetic decision only supported for setup")
        env["MTR_QA_SYNTHETIC_DECISION"] = decision
    command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
               "--child", "--root", str(root), "--action", action,
               "--request-id", request_id]
    if manual:
        command.append("--manual")
    result = subprocess.run(command, cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf8", errors="replace",
                            timeout=30, check=False)
    if result.returncode not in (0, 2):
        raise QABlocked("Packed child process terminated unexpectedly")
    encoded = result.stdout if result.returncode == 0 else result.stderr
    if len(encoded) > 32768:
        raise QABlocked("Unbounded packed child response")
    parsed = json.loads(encoded.strip())
    if (result.returncode == 0) != (parsed.get("ok") is True):
        raise QABlocked("Packed child return status/response disagreement")
    return parsed


def smoke() -> dict:
    _, provenance = verify()
    h = helper()
    results = []
    for decision in ("reviewed", "rejected"):
        with h.sandbox() as root:
            request_id = uuid.uuid4().hex
            stage = spawn(root, "stage", request_id, decision=decision)
            if not stage.get("ok") or stage["data"]["decision"] != decision:
                raise QABlocked("Packed synthetic after-move setup did not succeed")
            before = spawn(root, "list")
            if (not before.get("ok") or before["data"]["pending"]["requests"]
                or len(before["data"]["recovery"]["recovery"]) != 1
                or before["data"]["recovery"]["recovery"][0]["state"] != decision):
                raise QABlocked("Packed restart listing omitted original decision")
            denied = spawn(root, "recover", request_id, manual=False)
            if denied.get("ok") or (root / "reviewed" /
                                   (request_id + ".review.json")).exists():
                raise QABlocked("Recovery allowed without manual confirmation")
            intent = root / "reviewed" / (request_id + ".intent.json")
            moved = root / "reviewed" / (request_id + ".json")
            intent_before, moved_before = intent.read_bytes(), moved.read_bytes()
            done = spawn(root, "recover", request_id, manual=True)
            if (not done.get("ok") or done["data"] != {
                "id": request_id, "state": decision, "financialEventCreated": False
            }):
                raise QABlocked("Packed explicit operator recovery failed")
            receipt = root / "reviewed" / (request_id + ".review.json")
            receipt_bytes = receipt.read_bytes()
            expected = json.loads(intent_before)
            expected.pop("sourceDigest")
            if (intent.read_bytes() != intent_before or moved.read_bytes() != moved_before
                or json.loads(receipt_bytes) != expected):
                raise QABlocked("Packed receipt not persisted against exact immutable intent")
            final = spawn(root, "list")
            if (not final.get("ok") or final["data"]["recovery"]["recovery"]
                or final["data"]["recovery"]["recoveryInvalidCount"]):
                raise QABlocked("Completed metadata review still offered for recovery")
            again = spawn(root, "recover", request_id, manual=True)
            if not again.get("ok") or receipt.read_bytes() != receipt_bytes:
                raise QABlocked("Repeat packed recovery rewrote prior receipt")
            results.append({"decision": decision, "restartProcessReadback": True,
                            "exactSourceDigest": True, "manualOnly": True,
                            "receiptPersisted": True, "idempotent": True,
                            "financialEventCreated": False})
    return {**provenance, "status": "FINAL_CANDIDATE_PACKED_SYNTHETIC_QA_PASS",
            "cases": results, "sourceGuardBypassed": False,
            "realLedgerOpened": False, "installedGuiLaunched": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--action", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--manual", action="store_true")
    args = parser.parse_args()
    try:
        if args.child:
            if args.manifest_only or args.root is None:
                raise QABlocked("Invalid child QA invocation")
            result = _child(args.root, args.action, args.request_id, args.manual)
        elif args.manifest_only:
            if args.root is not None or args.action or args.request_id or args.manual:
                raise QABlocked("Manifest accepts no user data parameters")
            _, result = verify()
        else:
            if args.root is not None or args.action or args.request_id or args.manual:
                raise QABlocked("Cannot supply explicit profile or financial data")
            result = smoke()
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "type": type(error).__name__,
                          "message": str(error)[:170]}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
