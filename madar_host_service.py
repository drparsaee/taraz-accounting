r"""Headless, opt-in Windows Service host for Madar Desk.

The GUI keeps its independent per-user APPDATA store. This service owns a
separately provisioned ProgramData store and uses the existing authenticated
LAN server, so clients should JOIN it rather than also becoming a GUI host.

Usage (interactive provision, without exposing a password in argv):
    python madar_host_service.py provision --data-dir C:\ProgramData\MadarDeskHost\Data --owner admin
    python madar_host_service.py check --data-dir C:\ProgramData\MadarDeskHost\Data
    python madar_host_service.py console --data-dir <isolated-test-folder> --port 48370

SCM registration is performed separately by Install-MadarHostService.ps1.
The "service" mode implements StartServiceCtrlDispatcherW directly so it
works without optional pywin32. Never launch the GUI or spawn another host.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import getpass
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
from unittest.mock import patch
import uuid

from offline_exchange import atomic_json


SERVICE_NAME = "MadarHost"
AUTHORITY_NAME = "host-service-authority.json"
_SENSITIVE_FILES = {
    "tasks.json", "lan-users.json", "lan-connection.json", "madar-unified.sqlite3",
    "unified-active.json", "collab.json", "finance.json",
}
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,39}\Z")


def _root(data_root: str | Path) -> Path:
    if not data_root:
        raise ValueError("Explicit service data directory is required")
    supplied = Path(data_root).expanduser().absolute()
    for item in (supplied, *supplied.parents):
        if item.exists() and item.is_symlink():
            raise ValueError("Service data directory must not contain links")
    path = supplied.resolve(strict=False)
    if not path.is_absolute() or path == path.parent:
        raise ValueError("Invalid service data directory")
    for item in (path, *path.parents):
        if item.exists() and item.is_symlink():
            raise ValueError("Service data directory must not contain links")
    # Local GUI storage is deliberately a separate authority. Even a
    # manually supplied --data-dir must never resolve to these locations.
    for env in ("APPDATA", "LOCALAPPDATA"):
        parent = os.environ.get(env)
        if parent and path == (Path(parent) / "MadarDesk").resolve():
            raise ValueError("Refusing GUI APPDATA authority")
    return path


def _files(root: Path) -> tuple[Path, Path]:
    return root / "tls" / "cert.pem", root / "tls" / "key.pem"


def _require_programdata_authority(root: Path) -> None:
    if sys.platform != "win32":
        raise OSError("An installed service requires Windows")
    base = os.environ.get("PROGRAMDATA")
    if not base:
        raise ValueError("PROGRAMDATA is unavailable")
    approved = (Path(base) / "MadarDeskHost" / "Data").resolve()
    if root != approved:
        raise ValueError("SCM host must use dedicated ProgramData authority")


def _check_transport(root: Path) -> str:
    cert, key = _files(root)
    if not cert.is_file() or not key.is_file():
        raise ValueError("Host requires a unique TLS cert.pem and key.pem under data-root/tls")
    if cert.is_symlink() or key.is_symlink():
        raise ValueError("TLS files must not be symlinks")
    from lan import certificate_fingerprint
    import ssl
    fingerprint = certificate_fingerprint(str(cert))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    return fingerprint


def check_authority(data_root: str | Path) -> dict:
    """Read-only preflight. Never start/migrate the GUI's own host data."""
    root = _root(data_root)
    marker = root / AUTHORITY_NAME
    if not marker.is_file() or marker.is_symlink():
        raise RuntimeError("Dedicated service authority has not been provisioned")
    raw = json.loads(marker.read_text(encoding="utf8"))
    if not isinstance(raw, dict) or set(raw) != {"schema", "kind", "authorityId"}:
        raise ValueError("Invalid service authority marker")
    if (raw["schema"] != 1 or raw["kind"] != "madar-windows-service"
            or not isinstance(raw["authorityId"], str)
            or not re.fullmatch(r"[0-9a-f]{32}", raw["authorityId"])):
        raise ValueError("Invalid service authority identity")
    if (root / "lan-connection.json").exists():
        raise RuntimeError("Refusing an existing GUI LAN configuration in service authority")
    # Do not create any files while checking. Validate at least one admin
    # exists; the server does not need the original admin password to restart.
    users_file = root / "lan-users.json"
    if not users_file.is_file() or users_file.is_symlink():
        raise ValueError("No provisioned LAN users in service authority")
    users = json.loads(users_file.read_text(encoding="utf8"))
    if (not isinstance(users, dict)
            or not any(isinstance(u, dict) and u.get("role") == "admin"
                       and u.get("username") == key and u.get("passwordHash")
                       for key, u in users.items())):
        raise ValueError("Service authority requires a registered admin")
    if not (root / "tasks.json").is_file() and not (root / "unified-active.json").is_file():
        raise ValueError("Service authority has no initialized tasks")
    fingerprint = _check_transport(root)
    return {"dataRoot": str(root), "authorityId": raw["authorityId"],
            "fingerprint": fingerprint}


def provision_authority(data_root: str | Path, owner: str, *,
                        password_reader=None) -> dict:
    """Explicit, interactive, new-directory-only provisioning.

    TLS files must have been put in root/tls first by an administrator. No
    existing task/users/finance data is read, migrated or overwritten.
    """
    root = _root(data_root)
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        raise ValueError("Invalid administrator username")
    if root.exists():
        allowed = {"tls"}
        if set(p.name for p in root.iterdir()) - allowed:
            raise RuntimeError("Refusing to provision over existing Madar data")
        if (root / "tls").exists() and set(
                p.name for p in (root / "tls").iterdir()) - {"cert.pem", "key.pem"}:
            raise RuntimeError("Refusing unexpected TLS directory contents")
    _check_transport(root)
    password_reader = password_reader or getpass.getpass
    secret = password_reader("New host administrator password: ")
    repeated = password_reader("Repeat host administrator password: ")
    if not isinstance(secret, str) or secret != repeated or len(secret) < 10:
        raise ValueError("Passwords do not match or are too short (min 10)")
    # Lazy imports; no GUI window is created or required by this process.
    from lan import LanService
    import native_app
    with patch.object(native_app, "datadir", lambda: root):
        # Bridge creates a pristine standalone tasks.json in this new authority.
        bridge = native_app.Bridge()
        if bridge.connection.get("mode") != "solo" or bridge.lan is not None:
            raise RuntimeError("Cannot provision a GUI LAN host")
        lan = LanService(bridge, root / "lan-users.json", bind="127.0.0.1", port=48370)
        lan.setup_owner(owner, secret)
    # The marker is written last, so a failed bootstrap cannot be mistaken
    # for a ready authority. Secret remains only in this process's memory.
    marker = {"schema": 1, "kind": "madar-windows-service",
              "authorityId": uuid.uuid4().hex}
    atomic_json(root / AUTHORITY_NAME, marker)
    return check_authority(root)


@contextmanager
def _exclusive_host_lock(root: Path):
    """Cross-process Windows byte-range lock; held for the service lifetime."""
    if os.name != "nt":
        raise OSError("Madar Host service requires Windows")
    import msvcrt
    filename = root / "madar-host-owner.lock"
    if filename.is_symlink() or (filename.exists() and not filename.is_file()):
        raise RuntimeError("Unsafe host ownership lock file")
    with filename.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"\x00")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("CONFLICT: another Madar Host owns this service data root") from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _exclusive_lan_server_type():
    """Wrap existing LAN HTTP server with Windows exclusive-port semantics.

    Python's ThreadingHTTPServer permits SO_REUSEADDR by default, which on
    Windows is unsuitable for a single-authority host. SO_EXCLUSIVEADDRUSE
    prevents another GUI host or a second service from binding the same port.
    No edits to lan.py or global OS socket configuration are needed.
    """
    from lan import ThreadingHTTPServer

    class ExclusiveHostHTTPServer(ThreadingHTTPServer):
        allow_reuse_address = False

        def server_bind(self):
            if os.name == "nt":
                exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", 0x4)
                self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            return super().server_bind()

    return ExclusiveHostHTTPServer


def run_host_service(data_root: str | Path, stop_event: threading.Event, *,
                     port: int = 48370, bind: str = "0.0.0.0", on_ready=None) -> None:
    """Run existing LAN host with durable service-owned data until stopped.

    Suitable for isolated Windows QA with an ephemeral port and patched
    temporary directory. Does not install/register or touch the system.
    """
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Invalid host port")
    if bind not in {"0.0.0.0", "127.0.0.1", "::1"}:
        raise ValueError("Invalid host bind address")
    if not hasattr(stop_event, "wait") or not hasattr(stop_event, "is_set"):
        raise ValueError("stop_event must be a threading.Event")
    root = _root(data_root)
    check_authority(root)
    import lan as lan_module
    from lan import LanService
    import native_app
    cert, key = _files(root)
    with _exclusive_host_lock(root), patch.object(native_app, "datadir", lambda: root):
        bridge = native_app.Bridge()
        if bridge.connection.get("mode") != "solo" or bridge.lan is not None:
            raise RuntimeError("Service directory is configured as a GUI host or client")
        lan = LanService(bridge, root / "lan-users.json", bind=bind, port=port,
                         certfile=str(cert), keyfile=str(key))
        bridge.lan = lan
        discovery = None
        scheduler = None
        finance_backups = None
        jobs_started = False
        try:
            # lan.py's ordinary listener is backward-compatible with the
            # GUI. Replace its server factory only for this headless process.
            with patch.object(lan_module, "ThreadingHTTPServer", _exclusive_lan_server_type()):
                lan.start()
            # This is a new authority, so its standalone accounting source is
            # initialized here, with no import or migration from GUI/Parsian.
            # Use the same 5-minute validated backup policy as the desktop.
            from standalone_accounting_auto_backup import AutomaticStandaloneBackups
            bridge._standalone_accounting_store()
            finance_backups = AutomaticStandaloneBackups(
                root, plaintext_acknowledged=True)
            finance_backups.backup_now()
            finance_backups.start()
            # Existing background scheduler is host-owned and snapshots task
            # revisions only; its status deliberately marks backups partial.
            from host_backup_scheduler import HostBackupScheduler
            scheduler = HostBackupScheduler(bridge)
            scheduler.start()
            if bind == "0.0.0.0":
                # Discovery offers are unauthenticated hints. Clients still
                # must verify the TLS certificate fingerprint independently.
                from lan_discovery import DiscoveryResponder
                discovery = DiscoveryResponder(
                    "Madar Host", lan.port, certfile=str(cert))
                discovery.start()
            # Execute due/recurring automations even when every GUI is closed.
            # Bridge's existing hourly scheduler invokes the authenticated
            # in-process host route and retains its durable event receipts.
            bridge.startScheduledJobs()
            jobs_started = True
            if on_ready:
                on_ready(lan.port)
            while not stop_event.wait(0.3):
                if lan.server is None or lan.thread is None or not lan.thread.is_alive():
                    raise RuntimeError("LAN server thread terminated unexpectedly")
        finally:
            try:
                # Stop accepting new LAN writes before the final host backup.
                lan.stop()
            finally:
                if jobs_started:
                    bridge.stopScheduledJobs()
                if discovery is not None:
                    discovery.stop()
                if scheduler is not None:
                    scheduler.stop()
                if finance_backups is not None:
                    finance_backups.stop()
                    # Save a final validated snapshot on orderly shutdown.
                    finance_backups.backup_now()
            bridge.lan = None


def _service_dispatch(root: Path, port: int):
    """Native SCM service process entrypoint. No pywin32 dependency."""
    if sys.platform != "win32":
        raise OSError("Windows Service Control Manager is available only on Windows")
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("Advapi32", use_last_error=True)
    WINAPI = ctypes.WINFUNCTYPE
    DWORD = wintypes.DWORD
    HANDLE = wintypes.HANDLE
    service_type, running, start_pending, stop_pending, stopped = 0x10, 4, 2, 3, 1

    class SERVICE_STATUS(ctypes.Structure):
        _fields_ = [
            ("dwServiceType", DWORD), ("dwCurrentState", DWORD),
            ("dwControlsAccepted", DWORD), ("dwWin32ExitCode", DWORD),
            ("dwServiceSpecificExitCode", DWORD), ("dwCheckPoint", DWORD),
            ("dwWaitHint", DWORD)]

    HANDLER = WINAPI(DWORD, DWORD, DWORD, ctypes.c_void_p, ctypes.c_void_p)
    SERVICE_MAIN = WINAPI(None, DWORD, ctypes.POINTER(ctypes.c_wchar_p))

    class SERVICE_TABLE_ENTRY(ctypes.Structure):
        _fields_ = [("lpServiceName", wintypes.LPWSTR),
                    ("lpServiceProc", SERVICE_MAIN)]

    advapi.RegisterServiceCtrlHandlerExW.argtypes = [wintypes.LPCWSTR, HANDLER, ctypes.c_void_p]
    advapi.RegisterServiceCtrlHandlerExW.restype = HANDLE
    advapi.SetServiceStatus.argtypes = [HANDLE, ctypes.POINTER(SERVICE_STATUS)]
    advapi.SetServiceStatus.restype = wintypes.BOOL
    advapi.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(SERVICE_TABLE_ENTRY)]
    advapi.StartServiceCtrlDispatcherW.restype = wintypes.BOOL
    done = threading.Event()
    status_handle = None

    def report(state, *, failure=False):
        status = SERVICE_STATUS(
            service_type, state, 0x05 if state == running else 0,
            1066 if failure else 0, 1 if failure else 0,
            0, 30000 if state in (start_pending, stop_pending) else 0)
        if not advapi.SetServiceStatus(status_handle, ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())

    @HANDLER
    def handler(control, _event_type, _event_data, _context):
        if control in (1, 5):  # SERVICE_CONTROL_STOP / SHUTDOWN
            done.set()
            try:
                report(stop_pending)
            except OSError:
                pass
            return 0
        return 0

    @SERVICE_MAIN
    def service_main(_argc, _argv):
        nonlocal status_handle
        status_handle = advapi.RegisterServiceCtrlHandlerExW(SERVICE_NAME, handler, None)
        if not status_handle:
            return
        try:
            report(start_pending)
            run_host_service(root, done, port=port, on_ready=lambda _port: report(running))
            report(stopped)
        except Exception:
            # Report only a generic service-specific error to SCM. Never
            # log passwords, tokens, task or financial contents to disk.
            report(stopped, failure=True)

    table = (SERVICE_TABLE_ENTRY * 2)()
    table[0].lpServiceName = SERVICE_NAME
    table[0].lpServiceProc = service_main
    table[1].lpServiceName = None
    table[1].lpServiceProc = SERVICE_MAIN()
    if not advapi.StartServiceCtrlDispatcherW(table):
        raise ctypes.WinError(ctypes.get_last_error())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Madar Desk dedicated Windows LAN Host")
    sub = parser.add_subparsers(dest="mode", required=True)
    for command in ("provision", "check", "console", "service"):
        item = sub.add_parser(command)
        item.add_argument("--data-dir", type=Path, required=True)
        if command == "provision":
            item.add_argument("--owner", required=True)
        if command in ("console", "service"):
            item.add_argument("--port", type=int, default=48370)
        if command == "console":
            item.add_argument("--bind", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1")
    options = parser.parse_args(argv)
    if options.mode == "provision":
        details = provision_authority(options.data_dir, options.owner)
        print("Provisioned unique host authority. TLS SHA256:", details["fingerprint"])
    elif options.mode == "check":
        details = check_authority(options.data_dir)
        print("Dedicated host authority ready. TLS SHA256:", details["fingerprint"])
    elif options.mode == "console":
        stopped = threading.Event()
        try:
            run_host_service(options.data_dir, stopped, port=options.port,
                             bind=options.bind, on_ready=lambda port: print(
                                 "Madar Host listening via HTTPS on port", port))
        except KeyboardInterrupt:
            stopped.set()
    elif options.mode == "service":
        if not 1024 <= options.port <= 65535:
            raise ValueError("A fixed unprivileged port is required for Windows Service")
        root = _root(options.data_dir)
        _require_programdata_authority(root)
        _service_dispatch(root, options.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
