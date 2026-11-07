"""Taraz: independent personal Windows accounting application.

Launches accounting.html only, never creates a Madar task Bridge, never opens
MadarDesk task data. Source year archives live under LOCALAPPDATA/Taraz.
The optional Madar bridge receives metadata only and never posts journals.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from standalone_accounting_desktop import (
    AccountingDesktopAPI, NativeAccountingCloseGate,
    recover_native_editor_after_close_abort, serve_accounting_page,
)

def taraz_data_root():
    override = os.environ.get("TARAZ_QA_DATA_DIR")
    if override:
        if os.environ.get("TARAZ_QA_MODE") != "1":
            raise PermissionError("QA data override is unavailable outside QA")
        path = Path(override)
        if not path.is_absolute() or path.is_symlink() or "qa" not in [p.lower() for p in path.parts]:
            raise PermissionError("QA directory must be an absolute QA-only path")
        return path
    home = os.environ.get("APPDATA")
    if not home:
        raise RuntimeError("APPDATA is unavailable")
    return Path(home) / "Taraz"

def bridge_root():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    return Path(local) / "Madar-Taraz-Bridge"

class TarazAPI(AccountingDesktopAPI):
    def __init__(self, path):
        super().__init__(str(path))
        self._requires_migration = (path / "taraz-migration-manifest.json").exists()

    def _source_guard(self):
        self._require_authenticated()
        import sqlite3
        ledger = self.path
        if not ledger.is_file() or ledger.is_symlink():
            raise PermissionError("Taraz source ledger unavailable")
        con = sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)
        try:
            row = con.execute("SELECT revision,state,digest FROM standalone_accounting WHERE id=1").fetchone()
        finally:
            con.close()
        if not row or row[0] < 608 or hashlib.sha256(row[1]).hexdigest() != row[2]:
            raise PermissionError("Unverified personal accounting ledger")
        events = {e.get("eventId") for e in json.loads(row[1]).get("events", [])}
        expected = {
            "ps.parsian.journal.1405.14050201.1",
            "ps.parsian.reconcile.1404.pnl-close.20261107",
        }
        if not expected.issubset(events):
            raise PermissionError("Not the expected personal accounting book")

    def standaloneAccountingParsianHistory(self):
        with self._lock:
            self._source_guard()
            from personal_parsian_bridge import read_verified_history
            return read_verified_history()

    def standaloneAccountingParsianCompany(self):
        with self._lock:
            self._source_guard()
            from personal_parsian_bridge import read_personal_company
            return read_personal_company()

    def standaloneAccountingParsianExtended(self):
        with self._lock:
            self._source_guard()
            from personal_parsian_bridge import read_personal_extended
            return read_personal_extended()

    def standaloneAccountingParsianArchiveIndex(self):
        with self._lock:
            self._source_guard()
            from personal_parsian_bridge import list_archives
            return list_archives()

    def standaloneAccountingParsianArchiveRows(self, year, table, offset=0):
        with self._lock:
            self._source_guard()
            from personal_parsian_bridge import read_archive_rows
            return read_archive_rows(year, table, offset)

    def releaseCheck(self):
        raise RuntimeError("Taraz updater is independent from Madar and not configured")
    def releaseDownload(self):
        raise RuntimeError("Taraz updater is independent from Madar and not configured")
    def releaseInstall(self):
        raise RuntimeError("Taraz updater is independent from Madar and not configured")

    def tarazIntegrationList(self):
        """Only metadata of explicitly exported Madar tasks; no ledger data."""
        from taraz_integration import list_requests
        with self._lock:
            self._require_authenticated()
            return list_requests(bridge_root())

    def tarazIntegrationReview(self, request_id, decision):
        """Explicit acknowledgement; never issues invoices or financial events."""
        from taraz_integration import review_request
        with self._lock:
            self._require_authenticated('editor')
            return review_request(bridge_root(), request_id, decision)


def run():
    import msvcrt
    data = taraz_data_root()
    data.mkdir(parents=True, exist_ok=True)
    if data.is_symlink():
        raise PermissionError("Taraz profile symlink refused")
    if not (data / "standalone-accounting.sqlite3").is_file():
        raise RuntimeError("Taraz accounting book was not migrated; refusing an empty replacement")
    lock_file = data / ".taraz-session.lock"
    lock = open(lock_file, "a+b")
    try:
        lock.seek(0)
        if lock.read(1) == b"":
            lock.seek(0); lock.write(b"0"); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError("Taraz is already running using this accounting book")
        os.environ["TARAZ_DATA_DIR"] = str(data)
        api = TarazAPI(data)
        from standalone_accounting_auto_backup import AutomaticStandaloneBackups
        backups = AutomaticStandaloneBackups(data, plaintext_acknowledged=True)
        with api._lock:
            api.standaloneAccountingRead()
            api.standaloneAccountingParsianHistory()
            backups.backup_now()
        backups.start()
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        server = serve_accounting_page(root / "dist")
        Thread(target=server.serve_forever, daemon=True).start()
        import webview
        window = webview.create_window(
            "\u062a\u0631\u0627\u0632 | \u062d\u0633\u0627\u0628\u062f\u0627\u0631\u06cc",
            f"http://127.0.0.1:{server.server_port}/accounting.html",
            width=1500,height=950,min_size=(920,640),js_api=api,
        )
        api._native_window = window
        exit_backed_up = False
        def backup_on_close():
            nonlocal exit_backed_up
            if exit_backed_up:
                return True
            try:
                with api._lock:
                    backups.backup_now()
                    api._exit_backed_up = True
                exit_backed_up = True
                return True
            except Exception:
                return False
        def abort_close():
            nonlocal exit_backed_up
            if recover_native_editor_after_close_abort(window, api):
                exit_backed_up = False
                return True
            return False
        close_gate = NativeAccountingCloseGate(window, api, backup_on_close,
            on_aborted_close=abort_close)
        window.events.closing += close_gate.closing
        if os.environ.get("TARAZ_QA_REPORT") and os.environ.get("TARAZ_QA_MODE") == "1":
            def check_ui():
                time.sleep(1.6)
                values = {"app":"Taraz","ledgerFile":str(api.path)}
                for key, expression in {
                    "title":"document.title",
                    "loaded":"!!document.querySelector('.sac-root')",
                    "theme":"document.documentElement.dataset.theme",
                    "accountingBridge":"typeof window.madar?.standaloneAccountingRead",
                    "taskBridgeExposed":"typeof window.madar?.getState",
                    "tabCount":"document.querySelectorAll('.sac-sidebar nav button').length",
                    "historyVisible":"!!document.querySelector('.ppd-root')",
                    "integrationPanel":"!!document.querySelector('.taraz-bridge-panel')",
                }.items():
                    try: values[key] = window.evaluate_js(expression)
                    except Exception as exc: values[key] = "error:"+str(exc)
                from pathlib import Path
                Path(os.environ["TARAZ_QA_REPORT"]).write_text(json.dumps(values,ensure_ascii=False,indent=2),encoding="utf-8")
            window.events.loaded += lambda: Thread(target=check_ui, daemon=True).start()
        try:
            webview.start(gui="edgechromium", debug=False)
        finally:
            try:
                backups.stop()
                if not exit_backed_up:
                    with api._lock:
                        backups.backup_now()
                        api._exit_backed_up = True
            finally:
                server.shutdown(); server.server_close()
    finally:
        try:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
        finally: lock.close()

if __name__ == "__main__":
    run()
