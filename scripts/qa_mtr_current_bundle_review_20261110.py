"""Exercise the *packed* Taraz PYZ Inbox module without starting the EXE.

Only a SHA-pinned QA-only PyInstaller bundle and synthetic, explicitly marked
scratch roots are accepted. No taraz_desktop import, GUI, ledger or app profile.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import marshal
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import types
import uuid
from unittest.mock import patch


QA_PARENT = Path(r"D:\CoS-Test\MTR-TARAZ-QA-BUNDLE-20261110")
BUILD = QA_PARENT / "qa-457b29e2f80b"
EXE = BUILD / "pyinstaller" / "dist" / "Taraz-MTR-QA-457b29e2f80b.exe"
BUILD_MANIFEST = BUILD / "qa-build-report.json"
SCRATCH_PARENT = Path(r"D:\CoS-Test\MTR-TARAZ-PACKED-REVIEW-QA-20261110")
PINNED_EXE_SHA256 = "278106886eccf169551f734c9c01fc10225969f12a7b4e9d06229b894ad06cd2"
PINNED_SNAPSHOT_SHA256 = "e168a6d70e19e0ea883ced2dac8ab0f1b46bb55ea94302f6380cfacbf4e21969"
PINNED_MODULE_SHA256 = "c20f2259a98bc871177bd4488bd901236baf68eaea6b3a53802ad8ac962e4b9d"
MARKER_NAME = ".mtr-packed-taraz-synthetic-qa"
MARKER_BODY = b"QA ONLY: isolated, synthetic, no real accounting\n"
ID = re.compile(r"^[0-9a-f]{32}$")
STATES = ("reviewed", "rejected")
EXPECTED_API = frozenset(("review_request", "list_requests", "_atomic_json",
                          "_request_lock", "_read_marker", "_validate_intent"))


class QABlocked(RuntimeError):
    pass


def refuse_link(path: Path) -> None:
    for item in (path, *path.parents):
        if not os.path.lexists(item):
            continue
        mode = item.lstat()
        if (stat.S_ISLNK(mode.st_mode) or
                getattr(mode, "st_file_attributes", 0) & 0x400 or
                getattr(item, "is_junction", lambda: False)()):
            raise QABlocked("Symlink/junction forbidden in QA boundary")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def snapshot_inventory(snapshot: Path) -> dict[str, str]:
    """Recreate original build input fingerprint, without scanning node_modules."""
    refuse_link(snapshot)
    result: dict[str, str] = {}
    for item in snapshot.iterdir():
        if item.is_file() and (item.suffix == ".py" or item.name in {
            "accounting.html", "vite.config.js", "package.json", "package-lock.json"
        }):
            refuse_link(item)
            result[item.name] = digest(item)
    for folder in ("src", "assets", "public"):
        sub = snapshot / folder
        if not sub.is_dir():
            raise QABlocked(f"Missing QA snapshot source directory: {folder}")
        for base, dirs, files in os.walk(sub, followlinks=False):
            for name in dirs:
                refuse_link(Path(base) / name)
            for name in files:
                file = Path(base) / name
                refuse_link(file)
                result[file.relative_to(snapshot).as_posix()] = digest(file)
    return dict(sorted(result.items()))


def verify_bundle():
    """Reconfirm immutable QA manifest, exact EXE SHA, source snapshot and PYZ."""
    if sys.version_info[:2] != (3, 12):
        raise QABlocked("Pinned PYZ requires Python 3.12 for QA code inspection")
    for path in (QA_PARENT, BUILD, BUILD_MANIFEST, EXE, BUILD / "snapshot"):
        refuse_link(path)
    if not EXE.is_file() or not BUILD_MANIFEST.is_file():
        raise QABlocked("Pinned QA build or manifest unavailable")
    try:
        manifest = json.loads(BUILD_MANIFEST.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as error:
        raise QABlocked("Invalid QA build manifest") from error
    expected_fields = {
        "status": "QA_BUNDLE_VERIFIED", "qaOnly": True,
        "installed": False, "realLedgerAccessed": False, "releaseReady": False,
        "exe": str(EXE), "output": str(BUILD),
        "exeSha256": PINNED_EXE_SHA256,
        "sourceSnapshotSha256": PINNED_SNAPSHOT_SHA256,
        "sourceInputCount": 119,
    }
    if any(manifest.get(key) != value for key, value in expected_fields.items()):
        raise QABlocked("QA manifest does not match exact pinned build provenance")
    if manifest.get("packedDurableReview", {}).get("sourceBoundDurableIntentCode") is not True:
        raise QABlocked("QA build manifest lacks durable-intent inspection")
    if digest(EXE) != PINNED_EXE_SHA256:
        raise QABlocked("QA executable SHA-256 mismatch")
    if manifest.get("exeSizeBytes") != EXE.stat().st_size:
        raise QABlocked("QA executable size changed")
    inventory = snapshot_inventory(BUILD / "snapshot")
    fingerprint = hashlib.sha256(
        json.dumps(inventory, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if len(inventory) != 119 or fingerprint != PINNED_SNAPSHOT_SHA256:
        raise QABlocked("QA source snapshot changed after bundle build")

    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(EXE))
    if "taraz_desktop" not in archive.toc:
        raise QABlocked("QA bundle missing Taraz entrypoint")
    code = archive.open_embedded_archive("PYZ.pyz").extract("taraz_integration")
    if not isinstance(code, types.CodeType):
        raise QABlocked("No packed Taraz integration code object")
    module_sha = hashlib.sha256(marshal.dumps(code)).hexdigest()
    if module_sha != PINNED_MODULE_SHA256:
        raise QABlocked("PYZ Taraz integration code object does not match pin")
    functions = {item.co_name: item for item in code.co_consts
                 if isinstance(item, types.CodeType)}
    if not EXPECTED_API.issubset(functions):
        raise QABlocked("Packed integration lacks durable review functions")
    if ("link" not in functions["_atomic_json"].co_names or
            "_request_lock" not in functions["review_request"].co_names):
        raise QABlocked("Packed integration lacks atomic no-clobber and lock")
    return code, {
        "bundle": "QA_ONLY",
        "installed": False, "exeLaunched": False,
        "sha256": PINNED_EXE_SHA256,
        "snapshotSha256": fingerprint,
        "packedModuleSha256": module_sha,
        "packedModuleFunctions": sorted(EXPECTED_API),
    }


def load_packed_module(code: types.CodeType) -> types.ModuleType:
    """Execute ONLY taraz_integration's verified code object, not desktop APIs."""
    module = types.ModuleType("mtr_qa_packed_taraz_integration")
    module.__dict__.update({"__file__": "<SHA-pinned-PYZ/taraz_integration>",
                            "__package__": ""})
    exec(code, module.__dict__)
    if not callable(getattr(module, "review_request", None)):
        raise QABlocked("Verified packed PYZ did not expose review_request")
    return module


def verify_scratch_marker(root: Path) -> None:
    root = Path(root)
    if (not root.is_absolute() or root.parent != SCRATCH_PARENT
            or not root.name.startswith("qa-") or not root.is_dir()):
        raise QABlocked("Only a direct, existing QA scratch directory is accepted")
    refuse_link(root)
    marker = root / MARKER_NAME
    refuse_link(marker)
    if not marker.is_file() or marker.read_bytes() != MARKER_BODY:
        raise QABlocked("Unmarked or altered QA scratch directory")
    for folder in ("pending", "reviewed"):
        refuse_link(root / folder)


def verify_scratch(root: Path) -> None:
    verify_scratch_marker(root)
    for key in ("APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "USERPROFILE", "HOME",
                "TARAZ_QA_DATA_DIR"):
        value = os.environ.get(key)
        if not value or not Path(value).is_absolute() or not Path(value).is_relative_to(root):
            raise QABlocked(f"Unisolated QA child environment: {key}")
        refuse_link(Path(value))
    if os.environ.get("TARAZ_QA_MODE") != "1":
        raise QABlocked("QA mode was not explicitly enabled")


def sandbox_env(root: Path) -> dict[str, str]:
    """Construct a child environment with NO ambient personal data paths."""
    verify_scratch_marker(root)
    env = {key: value for key, value in os.environ.items()
           if key.upper() in ("SYSTEMROOT", "WINDIR", "PATH", "PATHEXT",
                              "COMSPEC", "PROCESSOR_ARCHITECTURE",
                              "NUMBER_OF_PROCESSORS", "PYTHONUTF8",
                              "PYTHONIOENCODING")}
    for key, relative in {
        "APPDATA": "qa-profile/roaming", "LOCALAPPDATA": "qa-profile/local",
        "TEMP": "qa-profile/temp", "TMP": "qa-profile/temp",
        "HOME": "qa-profile/home", "USERPROFILE": "qa-profile/user",
        "TARAZ_QA_DATA_DIR": "qa-profile/qa/ledger",
    }.items():
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update({"TARAZ_QA_MODE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1", "PYTHONPATH": ""})
    return env


@contextmanager
def sandbox():
    refuse_link(SCRATCH_PARENT.parent)
    SCRATCH_PARENT.mkdir(exist_ok=True)
    refuse_link(SCRATCH_PARENT)
    with tempfile.TemporaryDirectory(prefix="qa-", dir=SCRATCH_PARENT) as directory:
        root = Path(directory)
        (root / MARKER_NAME).write_bytes(MARKER_BODY)
        (root / "pending").mkdir()
        yield root


def write_proposal(root: Path, request_id: str, *, title="QA-only packaging service") -> Path:
    if not ID.fullmatch(request_id):
        raise QABlocked("Synthetic request ID must be lowercase UUID hex")
    path = root / "pending" / (request_id + ".json")
    if path.exists():
        raise QABlocked("Refusing to replace a synthetic proposal")
    proposal = {
        "schema": 1, "source": "madar", "id": request_id,
        "taskId": "qa.task." + request_id[:8], "projectId": "qa.project",
        "title": title, "createdUtc": "2026-11-10T10:00:00+00:00",
        "amountRial": "1500",
    }
    path.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
    return path


def spawn_packed(root: Path, action: str, request_id: str = "", decision: str = "",
                 fault: str = "") -> subprocess.CompletedProcess:
    if action not in ("list", "review") or fault not in (
            "", "before-intent", "before-move", "before-receipt", "after-receipt",
            "competing-intent"):
        raise QABlocked("Invalid packed QA action")
    env = sandbox_env(root)
    return subprocess.run([
        sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--child",
        "--root", str(root), "--action", action, "--request-id", request_id,
        "--decision", decision, "--fault", fault,
    ], cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", timeout=30, check=False)


def child_run(root: Path, action: str, request_id: str, decision: str,
              fault: str) -> dict:
    verify_scratch(root)
    code, verified = verify_bundle()
    integration = load_packed_module(code)
    if action == "list":
        if fault or request_id or decision:
            raise QABlocked("List accepts no review arguments")
        answer = integration.list_requests(root)
        return {"ok": True, "provenance": verified, "list": answer}
    if action != "review" or not ID.fullmatch(request_id) or decision not in STATES:
        raise QABlocked("Invalid synthetic review request")
    if fault not in ("", "before-intent", "before-move",
                     "before-receipt", "after-receipt", "competing-intent"):
        raise QABlocked("Unknown fault injection")
    receipt = root / "reviewed" / (request_id + ".review.json")
    intent = root / "reviewed" / (request_id + ".intent.json")
    source = root / "pending" / (request_id + ".json")
    original_atomic = integration._atomic_json
    original_rename = integration.os.rename
    original_link = integration.os.link

    def fail_atomic(path, payload):
        if fault == "before-intent" and path == intent:
            raise OSError("synthetic fault before durable intent")
        if fault == "before-receipt" and path == receipt:
            raise OSError("synthetic fault before metadata receipt")
        result = original_atomic(path, payload)
        if fault == "after-receipt" and path == receipt:
            raise OSError("synthetic fault after metadata receipt")
        return result

    def fail_move(src, dst):
        if fault == "before-move" and str(src) == str(source):
            raise OSError("synthetic fault before move")
        return original_rename(src, dst)

    def inject_competing_marker(src, dst):
        if fault == "competing-intent" and str(dst) == str(intent):
            if intent.exists():
                raise QABlocked("Unexpected early competing marker")
            intent.write_bytes(b"QA competing untrusted marker; must survive")
        return original_link(src, dst)

    with patch.object(integration, "_atomic_json", side_effect=fail_atomic), \
            patch.object(integration.os, "rename", side_effect=fail_move), \
            patch.object(integration.os, "link", side_effect=inject_competing_marker):
        result = integration.review_request(root, request_id, decision)
    if result != {"id": request_id, "state": decision,
                  "financialEventCreated": False}:
        raise QABlocked("Packed integration returned unexpected review result")
    return {"ok": True, "provenance": verified, "review": result}


def assert_child(result: subprocess.CompletedProcess, *, success: bool) -> dict:
    data = json.loads((result.stdout if success else result.stderr).strip())
    if bool(data.get("ok")) != success or (result.returncode == 0) != success:
        raise AssertionError(f"Unexpected isolated child outcome: {data}")
    return data


def smoke() -> dict:
    _, evidence = verify_bundle()
    with sandbox() as root:
        reviewed, rejected, legacy, interrupted = (uuid.uuid4().hex for _ in range(4))
        for identifier in (reviewed, rejected, legacy, interrupted):
            write_proposal(root, identifier)
        initially = assert_child(spawn_packed(root, "list"), success=True)
        if len(initially["list"]["requests"]) != 4:
            raise QABlocked("Packed module did not list all four synthetic proposals")
        for identifier, decision in ((reviewed, "reviewed"), (rejected, "rejected")):
            result = assert_child(spawn_packed(root, "review", identifier, decision),
                                  success=True)
            if result["review"]["financialEventCreated"] is not False:
                raise QABlocked("Unexpected financial result")
            intent = root / "reviewed" / (identifier + ".intent.json")
            dest = root / "reviewed" / (identifier + ".json")
            receipt = root / "reviewed" / (identifier + ".review.json")
            saved = (intent.read_bytes(), dest.read_bytes(), receipt.read_bytes())
            assert_child(spawn_packed(root, "review", identifier, decision), success=True)
            if saved != (intent.read_bytes(), dest.read_bytes(), receipt.read_bytes()):
                raise QABlocked("Replay mutated persisted durable metadata")
        assert_child(spawn_packed(root, "review", interrupted, "reviewed",
                                  "before-receipt"), success=False)
        if not (root / "reviewed" / (interrupted + ".intent.json")).is_file():
            raise QABlocked("Interrupted request did not persist durable intent")
        assert_child(spawn_packed(root, "review", interrupted, "reviewed"), success=True)
        legacy_marker = root / "reviewed" / (legacy + ".review.json")
        legacy_marker.write_text(json.dumps({"legacy": True,
                    "financialEventCreated": False}), encoding="utf-8")
        old_receipt = legacy_marker.read_bytes()
        denied = assert_child(spawn_packed(root, "review", legacy, "reviewed"),
                              success=False)
        if denied.get("exception") != "ValueError":
            raise QABlocked("Legacy marker was not refused by durable intent validation")
        if (old_receipt != legacy_marker.read_bytes() or
                not (root / "pending" / (legacy + ".json")).exists()):
            raise QABlocked("Legacy marker was changed during denial")
        return {**evidence, "status": "PACKED_DURABLE_SYNTHETIC_QA_PASS",
                "reviewed": True, "rejected": True,
                "restartMetadataReadback": True, "faultRecovery": True,
                "legacyMarkerRefused": denied.get("exception") == "ValueError",
                "financialPostingTested": False, "realLedgerAccessed": False,
                "installedTarazLaunched": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--action", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--decision", default="")
    parser.add_argument("--fault", default="")
    parser.add_argument("--manifest-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.child:
            data = child_run(args.root, args.action, args.request_id,
                             args.decision, args.fault)
        elif args.manifest_only:
            _, data = verify_bundle()
        else:
            data = smoke()
        print(json.dumps(data, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        # Expected fail-closed response: no payload, personal paths or tokens.
        print(json.dumps({"ok": False, "exception": type(exc).__name__,
                          "reason": str(exc)[:170]}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
