"""Read-only, opt-in-gated local Madar/Taraz inbox *availability* status.

This module deliberately reads file metadata only. A filename/size matching the
proposal format is NOT a validated proposal or a verified peer installation.
The host must authenticate and authorize the caller, and provide its own app's
explicit consent flag. No consent is persisted or changed here.
"""
from __future__ import annotations

from itertools import islice
import os
from pathlib import Path
import re
import stat

_ID_FILE = re.compile(r"[0-9a-f]{32}\.json\Z")
_MAX_SCAN = 200
_MAX_PENDING = 100
_MAX_BYTES = 32768


def _unsafe_directory(path: Path) -> bool:
    """Reject Windows junctions/reparse points in addition to symlinks."""
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        return True
    if path.exists():
        return bool(
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    return False


def inspect_local_link_status(root: Path, *, app: str, opted_in: bool = False) -> dict:
    """Only inspect local pending filenames after explicit caller-side opt-in.

    root is the trusted OS-user bridge directory chosen by a native host,
    never a UI-supplied arbitrary filesystem path. Does not create directories.
    A disabled status does not even stat root, preventing ambient disclosure.
    """
    if app not in ("madar", "taraz"):
        raise ValueError("Unsupported link participant")
    if type(opted_in) is not bool:
        raise TypeError("opted_in must be an explicit boolean")
    result = {
        "schema": 1,
        "app": app,
        "transport": "local-file-proposals",
        "state": "disabled",
        "optedIn": opted_in,
        "localInboxPresent": False,
        "pendingCandidates": 0,
        "invalidEntries": 0,
        "scanTruncated": False,
        "candidateContentValidated": False,
        "peerVerified": False,
        "postingEnabled": False,
        "readOnly": True,
    }
    if not opted_in:
        return result
    if not isinstance(root, Path):
        raise TypeError("root must be a trusted pathlib.Path")
    try:
        if _unsafe_directory(root):
            result["state"] = "unavailable"
            return result
        inbox = root / "pending"
        if _unsafe_directory(inbox):
            result["state"] = "unavailable"
            return result
        if not inbox.is_dir():
            result["state"] = "not-created"
            return result
        result["localInboxPresent"] = True
        with os.scandir(inbox) as entries:
            for index, entry in enumerate(islice(entries, _MAX_SCAN + 1)):
                if index == _MAX_SCAN:
                    result["scanTruncated"] = True
                    break
                if not entry.name.endswith(".json"):
                    continue
                if (
                    not _ID_FILE.fullmatch(entry.name)
                    or not entry.is_file(follow_symlinks=False)
                    or entry.stat(follow_symlinks=False).st_size > _MAX_BYTES
                ):
                    result["invalidEntries"] += 1
                elif result["pendingCandidates"] < _MAX_PENDING:
                    result["pendingCandidates"] += 1
                else:
                    result["scanTruncated"] = True
        result["state"] = (
            "pending" if result["pendingCandidates"]
            else "needs-review" if result["invalidEntries"] or result["scanTruncated"]
            else "empty"
        )
        return result
    except (OSError, ValueError):
        result.update({
            "state": "unavailable",
            "localInboxPresent": False,
            "pendingCandidates": 0,
            "invalidEntries": 0,
            "scanTruncated": False,
        })
        return result
