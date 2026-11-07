"""Public GitHub release checker and fail-closed Windows setup updater.

After explicit user confirmation, a verified installer may run only after the
owning desktop process exits. Inno preflight must verify a full data backup.
No LAN credentials or application data are sent to GitHub.
"""
from __future__ import annotations

import hashlib
import base64
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


REPOSITORY = "drparsaee/madar-desk-updates"
CURRENT_VERSION = "1.0.22"
API = "https://api.github.com/repos/" + REPOSITORY + "/releases/latest"
MAX_RELEASE_BYTES = 400 * 1024 * 1024
HEX64 = re.compile(r"sha256:([0-9a-f]{64})\Z")
VERSION = re.compile(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")


def version_tuple(version):
    match = VERSION.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        raise ValueError("Invalid release version")
    return tuple(map(int, match.groups()))


def _fetch_json(url):
    if url != API:
        raise ValueError("Untrusted release endpoint")
    request = Request(url, headers={"Accept": "application/vnd.github+json",
                                    "User-Agent": "MadarDesk-Update-Checker/1"})
    with urlopen(request, timeout=8) as response:
        if response.geturl() != API:
            raise ValueError("Unexpected release API redirect")
        raw = response.read(256001)
        if len(raw) > 256000:
            raise ValueError("Release index oversized")
    return json.loads(raw)


def inspect_release(document, installed=CURRENT_VERSION):
    if not isinstance(document, dict) or document.get("draft") or document.get("prerelease"):
        raise ValueError("No stable release")
    tag = document.get("tag_name")
    remote = version_tuple(tag)
    local = version_tuple(installed)
    version = ".".join(map(str, remote))
    if remote <= local:
        return {"available": False, "current": installed, "latest": version}
    filename = f"Madar-Desk-{version}-Setup.exe"
    expected_url = (f"https://github.com/{REPOSITORY}/releases/download/"
                    f"v{version}/{filename}")
    matches = [item for item in document.get("assets", [])
               if isinstance(item, dict) and item.get("name") == filename]
    if len(matches) != 1:
        raise ValueError("Release setup asset is missing or ambiguous")
    asset = matches[0]
    digest = HEX64.fullmatch(str(asset.get("digest", "")))
    size = asset.get("size")
    if (asset.get("browser_download_url") != expected_url or digest is None or
            type(size) is not int or not 512 <= size <= MAX_RELEASE_BYTES):
        raise ValueError("Release setup does not have a trusted GitHub SHA256 digest")
    return {"available": True, "current": installed, "latest": version,
            "filename": filename, "url": expected_url, "sha256": digest.group(1),
            "size": size, "notes": str(document.get("body") or "")[:1200]}


def check():
    return inspect_release(_fetch_json(API))


def _verified_release(info):
    if not isinstance(info, dict) or info.get("available") is not True:
        raise ValueError("An update is not available")
    candidate = inspect_release({"tag_name": "v" + str(info.get("latest")),
                                 "assets": [{"name": info.get("filename"),
                                             "browser_download_url": info.get("url"),
                                             "digest": "sha256:" + str(info.get("sha256")),
                                             "size": info.get("size")}]})
    if any(candidate.get(key) != info.get(key) for key in
           ("latest", "filename", "url", "sha256", "size")):
        raise ValueError("Release metadata changed")
    return candidate


def download(info, download_root=None):
    validated = _verified_release(info)
    root = Path(download_root) if download_root else (
        Path(os.environ["LOCALAPPDATA"]) / "MadarDesk" / "Updates")
    if not root.is_absolute():
        raise ValueError("Update cache must be absolute")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("Update cache cannot be a link")
    destination = root / validated["filename"]
    expected_hash = validated["sha256"]
    if destination.exists():
        if destination.is_symlink() or destination.stat().st_size != validated["size"]:
            raise ValueError("Existing update has unexpected size or link type")
        with destination.open("rb") as source:
            existing_digest = hashlib.file_digest(source, "sha256").hexdigest()
        if existing_digest != expected_hash:
            raise ValueError("Existing update checksum mismatch")
        return {"path": str(destination), "verified": True}
    part = root / (".madar-" + secrets.token_hex(12) + ".partial")
    checksum = hashlib.sha256()
    total = 0
    try:
        request = Request(validated["url"], headers={"User-Agent": "MadarDesk-Update-Checker/1"})
        with urlopen(request, timeout=25) as response, part.open("xb") as target:
            final_url = urlsplit(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in {
                    "github.com", "release-assets.githubusercontent.com",
                    "objects.githubusercontent.com"}:
                raise ValueError("Untrusted asset redirect")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > validated["size"] or total > MAX_RELEASE_BYTES:
                    raise ValueError("Oversized update")
                checksum.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if total != validated["size"] or checksum.hexdigest() != expected_hash:
            raise ValueError("Update SHA256 verification failed")
        with part.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("Downloaded setup is not a Windows executable")
        os.replace(part, destination)
    finally:
        part.unlink(missing_ok=True)
    return {"path": str(destination), "verified": True}


def schedule_verified_install(info, saved, *, parent_pid=None):
    """Install only a host-discovered, verified release after this process exits.

    No URL, shell command, installer path or checksum is accepted from the UI.
    The installer itself must separately back up the full application profile.
    """
    validated = _verified_release(info)
    if not isinstance(saved, dict) or saved.get("verified") is not True:
        raise ValueError("Verified Windows setup is required")
    if sys.platform != "win32":
        raise RuntimeError("Windows update installation is not available")
    path = Path(saved.get("path", ""))
    if (not path.is_absolute() or path.is_symlink() or
            path.name != validated["filename"] or not path.is_file() or
            path.stat().st_size != validated["size"]):
        raise ValueError("Untrusted or changed Windows setup")
    with path.open("rb") as source:
        if source.read(2) != b"MZ":
            raise ValueError("Windows setup header mismatch")
        source.seek(0)
        if hashlib.file_digest(source, "sha256").hexdigest() != validated["sha256"]:
            raise ValueError("Windows setup digest mismatch")
    pid = os.getpid() if parent_pid is None else parent_pid
    if type(pid) is not int or pid <= 0:
        raise ValueError("Invalid host process")
    # Quoting is used only for a trusted host-generated absolute path.
    ps = ("$ErrorActionPreference='Stop'; "
          f"if(Get-Process -Id {pid} -ErrorAction SilentlyContinue)"
          f"{{Wait-Process -Id {pid} -Timeout 1800 -ErrorAction Stop}}; "
          f"$file='{str(path).replace(chr(39), chr(39)*2)}'; "
          f"if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine '{validated['sha256']}')"
          "{throw 'Update integrity mismatch'}; "
          "Start-Process -FilePath $file -Wait")
    subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive",
                      "-EncodedCommand", base64.b64encode(ps.encode("utf-16le")).decode("ascii")],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True)
    return {"scheduledAfterExit": True, "version": validated["latest"]}
