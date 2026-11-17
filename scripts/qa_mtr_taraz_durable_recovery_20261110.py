"""Read-only packed Taraz v1.0.0 inspection and disposable recovery probe.

This script NEVER launches an installed EXE, imports its bytecode, reads a
personal accounting database, or calls taraz_desktop/TarazAPI. It only imports
current taraz_integration in the explicitly marked, disposable replay mode.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import types


PROJECT = Path(__file__).resolve().parents[1]
PINNED_INSTALLED_SHA256 = (
    "de5005579039bd86890c1dca1f5f1d9c760e6c47579a42f649f80096f158e70c"
)
QA_OWNER_MARKER = ".mtr-taraz-durable-synthetic-only"
QA_OWNER_VALUE = "MTR-TARAZ-DISPOSABLE-LOCAL-SYNTHETIC-V1\n"
REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_DURABLE_API = frozenset((
    "_atomic_json", "_read_marker", "_request_lock", "_validate_intent",
    "_receipt", "review_request", "list_requests",
))


class QABlocked(RuntimeError):
    """An unexpected input cannot be treated as successful recovery evidence."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _no_links(path: Path) -> None:
    for item in (path, *path.parents):
        if not os.path.lexists(item):
            continue
        stat_result = item.lstat()
        if stat.S_ISLNK(stat_result.st_mode) or (
            getattr(stat_result, "st_file_attributes", 0) & 0x400
        ) or getattr(item, "is_junction", lambda: False)():
            raise QABlocked("QA path contains a link or junction")


def source_manifest() -> dict:
    path = PROJECT / "taraz_integration.py"
    _no_links(path)
    content = path.read_bytes()
    definitions = {
        child.name for child in ast.parse(content, filename=str(path)).body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if not _DURABLE_API.issubset(definitions):
        raise QABlocked("Current Taraz source lacks durable review API")
    return {
        "sourceSha256": hashlib.sha256(content).hexdigest(),
        "sourceDurableFunctionNames": sorted(_DURABLE_API),
        "sourceHasDurableIntent": True,
    }


def installed_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise QABlocked("LOCALAPPDATA is unavailable")
    return Path(local) / "Programs" / "Taraz" / "versions" / "1.0.0" / "Taraz.exe"


def _function_names(code: types.CodeType) -> set[str]:
    collected = {code.co_name}
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            collected.update(_function_names(const))
    return collected


def installed_packed_manifest(exe: Path, expected_sha256: str = PINNED_INSTALLED_SHA256) -> dict:
    """Hash-gated static PyInstaller inspection; never executes packed code."""
    exe = Path(exe)
    if (not exe.is_absolute() or exe.suffix.lower() != ".exe"
            or not exe.is_file() or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
        raise QABlocked("Invalid explicit, pinned installed executable")
    _no_links(exe)
    measured = _sha256(exe)
    if measured != expected_sha256:
        raise QABlocked("Installed executable SHA-256 does not match pinned digest")

    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(exe))
    if "taraz_desktop" not in archive.toc:
        raise QABlocked("Pinned archive lacks the Taraz desktop entrypoint")
    import marshal
    entry = marshal.loads(archive.extract("taraz_desktop"))
    if not isinstance(entry, types.CodeType):
        raise QABlocked("Unexpected packed Taraz entrypoint type")
    desktop_methods = _function_names(entry)
    integration = archive.open_embedded_archive("PYZ.pyz").extract("taraz_integration")
    if not isinstance(integration, types.CodeType):
        raise QABlocked("Pinned Taraz integration module is absent")
    definitions = {
        value.co_name: value for value in integration.co_consts
        if isinstance(value, types.CodeType)
    }
    review = definitions.get("review_request")
    if not review:
        raise QABlocked("Pinned archive has no review_request")
    old_style = ("rename" in review.co_names and "open" in review.co_names
                 and "_atomic_json" not in definitions and
                 "_request_lock" not in definitions)
    return {
        "installedExecutableSha256": measured,
        "installedExecutableBytes": exe.stat().st_size,
        "installedVersionFolder": exe.parent.name,
        "installedTarazApiMethods": {
            key: key in desktop_methods
            for key in ("tarazIntegrationList", "tarazIntegrationReview")
        },
        "installedDurableFunctionNames": sorted(_DURABLE_API & definitions.keys()),
        "installedReviewHasRenameThenDirectReceiptWritePattern": old_style,
        "installedHasPreMoveIntent": "_atomic_json" in definitions,
        "installedHasPerRequestLock": "_request_lock" in definitions,
        "packedCodeExecuted": False,
        "installedExecutableLaunched": False,
    }


def require_disposable_root(root: Path) -> None:
    """Reject arbitrary paths even when a caller invokes the replay CLI."""
    root = Path(root)
    if not root.is_absolute() or not root.is_dir() or not root.name.startswith("qa-"):
        raise QABlocked("Recovery requires an existing absolute qa-* directory")
    _no_links(root)
    marker = root / QA_OWNER_MARKER
    if not marker.is_file() or marker.read_bytes() != QA_OWNER_VALUE.encode("ascii"):
        raise QABlocked("Unmarked or corrupted QA-only recovery root")
    _no_links(marker)
    # QA root must be separate from any ordinary application profile root.
    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    for ambient in (appdata, localappdata):
        if ambient:
            path = Path(ambient).absolute()
            if root == path or path in root.parents:
                raise QABlocked("Recovery root is within an application profile")
    for part in ("pending", "reviewed"):
        _no_links(root / part)


def replay_disposable(root: Path, request_id: str, decision: str) -> dict:
    require_disposable_root(root)
    if not REQUEST_ID_RE.fullmatch(request_id) or decision not in ("reviewed", "rejected"):
        raise QABlocked("Invalid bounded synthetic replay arguments")
    sys.path.insert(0, str(PROJECT))
    from taraz_integration import review_request
    result = review_request(root, request_id, decision)
    if result != {"id": request_id, "state": decision, "financialEventCreated": False}:
        raise QABlocked("Unexpected replay response")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    manifest = subparsers.add_parser("manifest", help="Read-only pinned package comparison")
    manifest.add_argument("--installed-exe", type=Path)
    recovery = subparsers.add_parser("recover", help="Replay only explicitly marked disposable QA root")
    recovery.add_argument("--root", type=Path, required=True)
    recovery.add_argument("--id", required=True)
    recovery.add_argument("--decision", required=True, choices=("reviewed", "rejected"))
    options = parser.parse_args()
    try:
        if options.mode == "manifest":
            data = {**source_manifest(), **installed_packed_manifest(
                options.installed_exe or installed_path())}
        else:
            data = replay_disposable(options.root, options.id, options.decision)
    except Exception as exc:
        # No user-source content, profile paths, ledger or payload are echoed.
        print(json.dumps({"ok": False, "errorClass": type(exc).__name__,
                          "message": str(exc)[:160]}), file=sys.stderr)
        return 2
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
