"""Launch Madar's isolated accounting desk without loading the task manager.

Development/explicit local mode. The operator must specify an ABSOLUTE private
data directory; this module never discovers or opens Madar's task/finance DB.
No network or real user files are touched simply by importing the module.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock, Thread
from urllib.parse import urlsplit, unquote


ACCOUNTING_FILE = "standalone-accounting.sqlite3"

JS_BRIDGE = """<script>
window.__madarStandaloneOnly = true;
window.madar = Object.fromEntries(
  ['standaloneAccountingRead', 'standaloneAccountingCommand',
   'nativeCloseBootstrap',
   'standaloneAccountingCsvChooseFile', 'standaloneAccountingCsvPreview',
   'standaloneAccountingParsianHistory', 'standaloneAccountingParsianCompany', 'standaloneAccountingParsianExtended',
   'standaloneAccountingParsianArchiveIndex', 'standaloneAccountingParsianArchiveRows',
   'tarazIntegrationList', 'tarazIntegrationReview', 'tarazIntegrationRecover',
   'tarazMadarDataOverview', 'tarazMadarDataRead',
       'tarazOrderList', 'tarazCustomerOrderHistory', 'tarazOrderCommand', 'tarazOrderFinanceDraft',
   'tarazEcosystemStatus', 'tarazEcosystemConnections',
   'tarazEcosystemPair', 'tarazEcosystemCards', 'tarazEcosystemForget',
   'tarazEcosystemCounterpartiesSearch', 'tarazEcosystemCounterpartiesGet',
   'tarazEcosystemMailboxProcess',
   'tarazAiProviderStatus',
   'tarazAiLocalStatus', 'tarazAiLocalGenerate',
   'tarazAiOnlineStatus', 'tarazAiOnlineConfigure', 'tarazAiOnlineClear',
   'tarazAiOnlineHealth', 'tarazAiOnlineGenerate',
   'tarazAiChatList', 'tarazAiChatRead', 'tarazAiChatCommand',
   'tarazAgentOrderReview', 'tarazAgentNaturalRequest',
   'tarazAgentMemoryList', 'tarazAgentMemoryCommand',
   'tarazOrderMadarLinkRead', 'tarazOrderMadarLink',
   'tarazMadarOrderPreview', 'tarazMadarOrderCommit',
   'tarazMadarOrderProgress',
   'tarazMadarOrderSyncHistory', 'tarazMadarOrderRecover',
   'tarazOrderSuggest',
   'tarazPrintSuggest',
   'standaloneAccountingTemplateList', 'standaloneAccountingTemplateSave',
   'standaloneAccountingTemplateDelete', 'standaloneAccountingTemplateDefault',
   'standaloneAccountingTemplateDuplicate',
   'standaloneAccountingRequestCompanySwitch',
   'standaloneAccountingTaxPreflight',
   'standaloneAccountingManageUsers',
   'releaseCheck', 'releaseDownload', 'releaseInstall'].map(
    key => [key, (...args) => new Promise((resolve, reject) => {
      // Only five boot requests, plus the optional brand-library read, are
      // recorded. Never include financial response bodies or raw arguments.
      const tracked = window.__phaseCBridgeTraceEnabled === true &&
        ['standaloneAccountingRead','standaloneAccountingParsianCompany',
         'standaloneAccountingTemplateList'].includes(key);
      const kind = key === 'standaloneAccountingTemplateList' &&
        ['entry','print','issuer','brand'].includes(args[0]) ? args[0] : undefined;
      const entry = tracked ? {method:key,phase:'proxy-created',
        startedAt:Date.now(),monotonicMs:performance.now(),
        ...(kind ? {kind} : {})} : null;
      if (entry) {
        const history = window.__phaseCBridgeTrace || (window.__phaseCBridgeTrace = []);
        history.push(entry);
        if (history.length > 48) history.shift();
      }
      // WebView2 can expose an api object before populating the methods.
      // Checking only window.pywebview.api caused a TypeError/blank GUI on
      // slower starts. Retry only for a bounded startup window.
      const started = Date.now();
      const invoke = () => {
        const fn = window.pywebview?.api?.[key];
        if (typeof fn !== 'function') {
          if (entry) entry.phase = 'awaiting-native-method';
          if (Date.now() - started < 12000) {
            setTimeout(invoke, 80);
          } else {
            if (entry) {entry.phase='native-method-unavailable';entry.elapsedMs=Date.now()-entry.startedAt;}
            reject(new Error('ارتباط امن حسابداری ویندوز آماده نشد؛ برنامه را دوباره باز کنید.'));
          }
          return;
        }
        if (entry) entry.phase = 'native-invoked';
        try {
          Promise.resolve(fn(...args)).then(
            value => {if (entry) {entry.phase='resolved';entry.elapsedMs=Date.now()-entry.startedAt;} resolve(value);},
            error => {if (entry) {entry.phase='rejected';entry.elapsedMs=Date.now()-entry.startedAt;} reject(error);}
          );
        } catch (err) {
          if (entry) {entry.phase='sync-exception';entry.elapsedMs=Date.now()-entry.startedAt;}
          reject(err);
        }
      };
      invoke();
    })]
  )
);
</script>"""


def recover_native_editor_after_close_abort(window, api, *,
                                            attempt_limit=3,
                                            sleep_fn=time.sleep,
                                            js_script=None,
                                            host_lock_attribute='_exit_backed_up'):
    """Keep finance writes blocked until JS confirms that the editor is live.

    This runs on the close worker, never inside pywebview's blocking closing
    event. A temporarily unavailable WebView bridge is retried instead of
    leaving an inert editor with host writes silently re-enabled. A failed
    bounded recovery can be retried by the next native titlebar X. It must
    never silently grant permission to close or mutate financial records.
    """
    if host_lock_attribute not in ('_exit_backed_up', '_exit_financial_locked'):
        raise ValueError('Unknown financial close lock')
    if js_script is None:
        js_script = (
            "typeof window.__madarAccountingAbortNativeClose === 'function' "
            "&& window.__madarAccountingAbortNativeClose()")
    with api._lock:
        setattr(api, host_lock_attribute, True)
    attempts = 0
    while attempts < attempt_limit:
        try:
            acknowledged = window.evaluate_js(js_script) is True
        except Exception as exc:
            print('Native accounting editor restore unavailable: ' + str(exc),
                  file=sys.stderr)
            acknowledged = False
        if acknowledged:
            with api._lock:
                setattr(api, host_lock_attribute, False)
            return True
        attempts += 1
        if attempts >= attempt_limit:
            print('Native accounting editor remains locked. Press the native X '
                  'again to retry the editor recovery; no financial writes '
                  'are permitted until the bridge acknowledges.',file=sys.stderr)
            return False
        sleep_fn(min(3.0, 0.25 * 2 ** min(attempts - 1, 4)))


class NativeAccountingCloseGate:
    """Veto native X first; ask the live editor on a separate GUI-safe thread.

    pywebview's closing event is blocking. Calling evaluate_js *inside* that
    event can deadlock WebView2, so the request must be checked only after the
    handler has returned False. No unknown/unloaded JS state permits closing.
    """

    def __init__(self, window, api, final_backup, *, thread_factory=Thread,
                 on_aborted_close=None, decision_script=None,
                 decision_provider=None):
        self.window = window
        self.api = api
        self.final_backup = final_backup
        self.thread_factory = thread_factory
        self.on_aborted_close = on_aborted_close or (lambda: None)
        self.decision_script = decision_script or (
            "typeof window.__madarAccountingConfirmNativeClose === 'function' "
            "&& window.__madarAccountingConfirmNativeClose()")
        if decision_provider is not None and not callable(decision_provider):
            raise TypeError('Native close consent provider must be callable')
        # The provider is bounded, one-use React->native consent. Never invoke
        # synchronous evaluate_js on the close worker when it is configured.
        self.decision_provider = decision_provider
        self._lock = RLock()
        self._checking = False
        self._approved = False
        self._backup_accepted = False
        self._close_event_seen = False
        self._recovery_needed = False
        # Read-only close-flow evidence. This never grants permission to close.
        self._native_attempt_count = 0
        self._js_confirmed_count = 0
        self._preclose_backup_verified_count = 0
        self._reentrant_accept_count = 0

    def close_evidence(self):
        with self._lock:
            return {'nativeAttemptCount': self._native_attempt_count,
                    'jsConfirmedCount': self._js_confirmed_count,
                    'precloseBackupVerifiedCount': self._preclose_backup_verified_count,
                    'reentrantAcceptCount': self._reentrant_accept_count}

    def close_decision_pending(self):
        """For the native switch requester: a first X is being evaluated.

        This is observational only; never grants permission to close.
        """
        with self._lock:
            return self._checking or self._approved

    def _clear_aborted_switch(self):
        # The switch is a web-initiated request, NOT independent evidence that
        # an invoice/bill editor was clean or the user consented to discard.
        with self.api._lock:
            self.api._switch_requested = False

    def closing(self):
        with self._lock:
            self._native_attempt_count += 1
            if self._approved:
                reentrant=True
                self._close_event_seen=True
                self._approved = False
                authorized = True
            elif self._checking:
                return False
            elif self._recovery_needed:
                self._checking = True
                authorized = False
                retry_recovery = True
            else:
                self._checking = True
                authorized = False
                retry_recovery = False
        if authorized:
            if reentrant and self._backup_accepted:
                with self._lock:
                    self._reentrant_accept_count += 1
                return True
            return self.final_backup()
        try:
            self.thread_factory(target=(self._retry_aborted if retry_recovery
                                        else self._decide), daemon=True).start()
        except Exception as exc:
            with self._lock:
                self._checking = False
            # In a native closing event an exception is not guaranteed to
            # cancel window destruction. Always explicitly veto if the
            # decision worker could not start; the user can retry the X.
            print('Native accounting close worker failed to start: '+str(exc),
                  file=sys.stderr)
            return False
        return False

    def _recover_aborted(self):
        self._clear_aborted_switch()
        try:
            # Older fake close callbacks returned None. Explicit False means
            # the real bridge never acknowledged a recoverable live editor.
            answer = self.on_aborted_close()
            recovered = (answer is True if self.decision_provider is not None
                         else answer is not False)
        except Exception as exc:
            print('Native accounting abort recovery failed: '+str(exc),
                  file=sys.stderr)
            recovered = False
        with self._lock:
            self._recovery_needed = not recovered
        return recovered

    def _retry_aborted(self):
        try:
            self._recover_aborted()
        finally:
            with self._lock:
                self._checking = False

    def _decide(self):
        uncertain = False
        try:
            # The React handler validates busy/retry status and asks before
            # discarding any bill, invoice, or issued-document correction.
            answer = (self.decision_provider() if self.decision_provider is not None
                      else self.window.evaluate_js(self.decision_script))
            uncertain = self.decision_provider is not None and answer is None
            accepted = answer is True
        except Exception as exc:
            print('Native accounting close guard unavailable: ' + str(exc),
                  file=sys.stderr)
            accepted = False
            uncertain = self.decision_provider is not None
        js_approved = accepted
        if not js_approved:
            self._clear_aborted_switch()
        if js_approved:
            with self._lock:
                self._js_confirmed_count += 1
        if accepted:
            # Do not assume window.destroy() re-emits events.closing. Verify
            # the final backup *while the native window is still alive* so a
            # backup error can always veto the requested close.
            try:
                accepted = self.final_backup() is True
                if accepted:
                    with self._lock:
                        self._preclose_backup_verified_count += 1
            except Exception as exc:
                print('Native accounting pre-close backup failed: ' + str(exc),
                      file=sys.stderr)
                accepted = False
        if (js_approved and not accepted) or uncertain:
            # The React editor was frozen after confirmation. A failed
            # mandatory backup or late/unknown consent must re-enable that
            # same live editor through a separately confirmed abort response.
            self._recover_aborted()
        with self._lock:
            self._checking = False
            if accepted:
                self._approved = True
                self._backup_accepted = True
                self._close_event_seen = False
        if accepted:
            raised=False
            try:
                # Re-enter the normal closing event, which performs the
                # mandatory final financial backup before allowing exit.
                self.window.destroy()
            except Exception as exc:
                raised=True
                print('Native accounting close retry failed: ' + str(exc),
                      file=sys.stderr)
            finally:
                with self._lock:
                    reentered=self._close_event_seen
                    self._approved=False
                    self._backup_accepted=False
                    self._close_event_seen=False
                if raised or not reentered:
                    # A window that ignored/delayed destroy must not retain
                    # close permission or freeze a live accounting session.
                    with self._lock:
                        self._checking=True
                    try:
                        self._recover_aborted()
                    finally:
                        with self._lock:
                            self._checking=False


class AccountingDesktopAPI:
    """Single local desktop principal; not a multi-user authentication server."""

    def __init__(self, explicit_data_root, *, company_name="", company_workspace_id="",
                 authenticated_user=None, identity_store=None, identity_token=None):
        path = Path(explicit_data_root)
        if not path.is_absolute():
            raise ValueError("Accounting data directory must be explicit and absolute")
        if path.exists() and not path.is_dir():
            raise ValueError("Accounting data path must be a directory")
        self.path = path / ACCOUNTING_FILE
        self._lock = RLock()
        self._exit_backed_up = False
        self._identity_store = identity_store
        self._identity_token = identity_token
        if identity_store is not None:
            if not isinstance(identity_token,str) or not identity_token:
                raise PermissionError('Authentication is required before accessing company ledger')
            checked=identity_store.require_session(identity_token)
            if not isinstance(authenticated_user,dict) or checked != authenticated_user:
                raise PermissionError('Invalid or mismatched accounting identity')
            self._actor=checked['username']
            self._accounts=identity_store.accounting_accounts()
            if self._actor not in self._accounts:
                raise PermissionError('Inactive accounting identity')
        else:
            self._actor='local'
            self._accounts = {"local": {"username": "local", "role": "admin"}}
        # Only a display hint from an explicitly selected private company
        # directory. This never becomes an accounting event or ledger field.
        self.company_name = company_name if isinstance(company_name,str) else ""
        # Registry-verified opaque ID, never a filesystem path or accounting event.
        # Unlike the display name it is stable even if the company gets renamed.
        self.company_workspace_id = (company_workspace_id if
            isinstance(company_workspace_id,str) and
            re.fullmatch(r"[a-f0-9]{32}",company_workspace_id) else "")
        self._switch_requested = False
        self._native_window = None
        from provider_csv_bridge import ProviderCsvPreviewBridge
        self._csv_preview = ProviderCsvPreviewBridge()

    def releaseCheck(self):
        raise RuntimeError("Taraz updater is not configured for this independent app")

    def releaseDownload(self):
        raise RuntimeError("Taraz updater is not configured for this independent app")

    def releaseInstall(self):
        raise RuntimeError("Taraz updater is not configured for this independent app")

    def standaloneAccountingCsvChooseFile(self, group, encoding, delimiter):
        """Admin-selected local CSV header only; no ledger or disk writes."""
        with self._lock:
            self._require_authenticated('admin')
            if self._native_window is None:
                raise RuntimeError("Native accounting file chooser is unavailable")
            from provider_csv_bridge import GROUPS
            if group not in GROUPS or type(group) is not str:
                raise ValueError("Unknown CSV group")
            import webview
            chosen = self._native_window.create_file_dialog(
                webview.FileDialog.OPEN, file_types=("CSV files (*.csv)",))
            return self._csv_preview.select(group, encoding, delimiter, chosen)

    def standaloneAccountingCsvPreview(self, request):
        """Preview chosen user-owned CSV files; never call accounting store."""
        with self._lock:
            self._require_authenticated('admin')
            return self._csv_preview.preview(request)

    def _require_authenticated(self,required='viewer'):
        if self._identity_store is not None:
            checked=self._identity_store.require_session(self._identity_token,required)
            if checked['username'] != self._actor:
                raise PermissionError('Active accounting identity changed')
            self._accounts=self._identity_store.accounting_accounts()
            return checked
        return self._accounts[self._actor]

    def standaloneAccountingRequestCompanySwitch(self):
        """Only the native company chooser may switch the active ledger.

        This call does NOT access another book. The actual switch happens
        after the current WebView has closed, backed up and released its lock.
        """
        with self._lock:
            self._require_authenticated()
            if not self.company_name:
                raise RuntimeError("Company switching requires a selected company registry")
            if self._exit_backed_up:
                raise RuntimeError("Accounting desktop is closing")
            if self._native_window is None:
                raise RuntimeError("Accounting window is not available for switching")
            self._switch_requested = True
            # window.close() in JavaScript is ignored by some embedded
            # WebView2 configurations. Close the owned native window through
            # pywebview instead; its closing handler MUST still verify backup.
            window = self._native_window
            def close_owned_window():
                time.sleep(.12)
                try:
                    window.destroy()
                except Exception as exc:
                    print("Company switch could not close native window: " + str(exc),
                          file=sys.stderr)
                finally:
                    # The first native destroy is only a close *request*.
                    # It can return after the gate's initial veto while
                    # asynchronous React consent + verified backup are still
                    # in progress. Never cancel a legitimate pending switch,
                    # but do revoke an ignored request without a close worker.
                    gate = getattr(self, '_native_close_gate', None)
                    pending = bool(gate and gate.close_decision_pending())
                    with self._lock:
                        if not self._exit_backed_up and not pending:
                            self._switch_requested = False
            Thread(target=close_owned_window, daemon=True).start()
            return True

    def _store(self):
        from standalone_accounting import StandaloneAccountingStore
        # Only an explicit read or command may create this directory/database.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # New independent ledgers default to RIAL; existing TOMAN snapshots
        # retain their persisted currency and are never reinterpreted.
        return StandaloneAccountingStore(self.path, default_currency="RIAL")

    def _with_migration(self, result):
        """Read-only historic Parsian view, if this explicit book has a sidecar.

        The source sidecar must be packaged beside this particular standalone
        book. No directory traversal, discovery under APPDATA, or writes to
        Parsian/other account books. Historical documents remain NON-POSTED.
        """
        from parsian_legacy_views import legacy_views
        historic = legacy_views(
            result["view"],
            archive_path=self.path.parent / "parsian-all-base-tables-PRIVATE.sqlite3",
            manifest_path=self.path.parent / "parsian-archive-manifest.json",
        )
        if historic is not None:
            result["view"]["parsianMigration"] = historic
        if self.company_name:
            result["view"]["companyWorkspaceLabel"] = self.company_name
        if self.company_workspace_id:
            result["view"]["companyWorkspaceId"] = self.company_workspace_id
        if getattr(self, "_verified_fresh_workspace", False) is True:
            result["view"]["freshWindowsWorkspace"] = True
        return result

    def standaloneAccountingRead(self):
        with self._lock:
            self._require_authenticated()
            from standalone_financial_report_host import attach_verified_reports
            result = self._with_migration(attach_verified_reports(self._store().read(
                actor=self._actor, accounts=self._accounts)))
            role=self._accounts[self._actor]['role']
            result["capabilities"] = {
                "canView": True, "canManage": role in ('admin','editor'),
                "canDraft": role in ('admin','editor'), "canAdmin": role=='admin'}
            identity=(self._identity_store.require_session(self._identity_token)
                      if self._identity_store is not None else
                      {"username":self._actor,"role":role,"jobTitle":""})
            result["currentUser"]={"username":identity['username'],
                                   "jobTitle":identity.get('jobTitle',''),"role":role}
            return result

    def standaloneAccountingParsianArchiveIndex(self):
        """Admin-only catalogue of verified, immutable Parsian year archives."""
        with self._lock:
            self._require_authenticated('admin')
            from parsian_source_year_browser import list_year_archives
            return list_year_archives(self.path.parent)

    def standaloneAccountingParsianArchiveRows(self, year, table, offset=0):
        """Paginated, redacted read-only values; no arbitrary filesystem path."""
        with self._lock:
            self._require_authenticated('admin')
            from parsian_source_year_browser import source_table_page
            return source_table_page(self.path.parent, year, table, offset)

    def standaloneAccountingCommand(self, request):
        if (type(request) is not dict or
                set(request) != {"command", "expectedRevision"} or
                type(request["command"]) is not dict or
                type(request["expectedRevision"]) is not int or
                request["expectedRevision"] < 0):
            raise ValueError("Invalid accounting CAS request")
        with self._lock:
            self._require_authenticated('editor')
            if self._exit_backed_up:
                raise RuntimeError("Accounting desktop is closing; financial changes are locked")
            from standalone_financial_report_host import attach_verified_reports
            return self._with_migration(attach_verified_reports(self._store().command(
                request["command"], actor=self._actor, accounts=self._accounts,
                expected_revision=request["expectedRevision"],
                now=datetime.now(timezone.utc).isoformat(),
            )))

    def _template_store(self):
        from standalone_accounting_template_store import StandaloneAccountingTemplateStore
        return StandaloneAccountingTemplateStore(self.path.parent)

    def _require_template_permission(self,write=False):
        self._require_authenticated('editor' if write else 'viewer')

    def standaloneAccountingTemplateList(self, kind):
        with self._lock:
            self._require_template_permission()
            return self._template_store().list(kind)

    def standaloneAccountingTemplateSave(self, kind, title, data, template_id=""):
        with self._lock:
            self._require_template_permission(True)
            if self._exit_backed_up:
                raise RuntimeError("Accounting desktop is closing")
            return self._template_store().save(kind, title, data, template_id)

    def standaloneAccountingTemplateDelete(self, kind, template_id):
        with self._lock:
            self._require_template_permission(True)
            if self._exit_backed_up:
                raise RuntimeError("Accounting desktop is closing")
            return self._template_store().delete(kind, template_id)

    def standaloneAccountingTemplateDefault(self, kind, template_id):
        with self._lock:
            self._require_template_permission(True)
            if self._exit_backed_up:
                raise RuntimeError("Accounting desktop is closing")
            return self._template_store().set_default(kind, template_id)

    def standaloneAccountingTemplateDuplicate(self, kind, template_id):
        with self._lock:
            self._require_template_permission(True)
            if self._exit_backed_up:
                raise RuntimeError("Accounting desktop is closing")
            return self._template_store().duplicate(kind, template_id)

    def standaloneAccountingTaxPreflight(self, invoice_id):
        """Read-only advisory; never submits, changes or signs tax invoices."""
        if not isinstance(invoice_id,str) or len(invoice_id)>96:
            raise ValueError('Invalid invoice identifier')
        with self._lock:
            self._require_authenticated()
            from standalone_accounting_tax_advisor import preflight_einvoice
            result=self.standaloneAccountingRead()
            view=result['view']
            invoice=view.get('invoices',{}).get(invoice_id)
            if not invoice:raise ValueError('Invoice not found in active company ledger')
            company=view.get('companyProfile') or {}
            return preflight_einvoice({
                'invoiceId':invoice_id,'issueDate':invoice.get('documentDate'),
                'kind':'original','lines':[
                    {'productServiceId':line.get('taxProductServiceId') or '',
                     'quantity':line.get('quantity'), 'unitPrice':line.get('unitPrice')}
                    for line in invoice.get('lines',[])]},company)

    def standaloneAccountingManageUsers(self):
        """Native-only credential prompts; no password enters the React DOM."""
        with self._lock:
            self._require_authenticated('admin')
            if self._identity_store is None or self._identity_token is None:
                raise PermissionError('User management requires authenticated company mode')
            from standalone_accounting_user_dialog import manage_local_users
            store=self._identity_store
            token=self._identity_token
        manage_local_users(store,token)
        return {'status':'closed'}


def _phase_c_private_trace_enabled():
    """Private metadata-only trace; never enable it for a normal Taraz profile."""
    if os.environ.get("PHASE_C_BRIDGE_TRACE") != "1":
        return False
    roaming = os.environ.get("APPDATA")
    local = os.environ.get("LOCALAPPDATA")
    if not roaming or not local:
        return False
    a, b = Path(roaming), Path(local)
    if (not a.is_absolute() or not b.is_absolute() or
            a.is_symlink() or b.is_symlink() or
            a.name != "APPDATA" or b.name != "LOCALAPPDATA" or
            a.parent != b.parent):
        return False
    return (a.parent.parent.name == "qa-runtime" and
            a.parent.parent.parent.name == "phase-c-frozen-close-gate-qa")


def serve_accounting_page(site, *, close_handshake=None, close_http_token=None,
                          close_session_token=None):
    """Host only the built accounting page on an ephemeral loopback port."""
    site = Path(site)
    if not (site / "accounting.html").is_file():
        raise FileNotFoundError("Run npm run build before launching accounting")
    if len([v for v in (close_handshake, close_http_token,
                       close_session_token) if v is not None]) not in (0,3):
        raise ValueError('Native close requires both window and bridge session tokens')
    if close_handshake is not None and (
            type(close_http_token) is not str or
            len(close_http_token) < 32 or not close_http_token.isascii() or
            type(close_session_token) is not str or
            len(close_session_token) < 32 or not close_session_token.isascii() or
            close_session_token == close_http_token):
        raise ValueError('Native close requires two distinct strong tokens')
    close_prelude = (
        '<script>window.__tarazNativeCloseToken=' +
        json.dumps(close_http_token) + ';</script>'
        if close_handshake is not None else '')
    phase_c_trace_prelude = (
        "<script>window.__phaseCBridgeTraceEnabled=true;</script>"
        if _phase_c_private_trace_enabled() else "")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(site), **kwargs)

        def do_GET(self):
            pathname = urlsplit(self.path).path
            decoded = unquote(pathname)
            # SimpleHTTPRequestHandler unquotes before resolving the filesystem.
            # Deny aliases too; this host must never serve task-manager HTML.
            if decoded.lower().endswith(('/index.html', '/index.htm')):
                self.send_error(404, "Task manager not part of standalone accounting")
                return
            if pathname in ("/", "/accounting.html"):
                content = (site / "accounting.html").read_text(encoding="utf-8")
                content = content.replace("</head>",
                    close_prelude + phase_c_trace_prelude + JS_BRIDGE + "</head>")
                encoded = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(encoded)
                return
            if pathname in ("/index.html",):
                self.send_error(404, "Task manager not part of standalone accounting")
                return
            super().do_GET()

        def do_POST(self):
            # Only this ephemeral GUI host accepts same-origin, per-window
            # one-use native close consent. No cross-origin or LAN authority.
            if (close_handshake is None or self.path not in (
                    '/__taraz_native_close_v1/poll',
                    '/__taraz_native_close_v1/respond')):
                self.send_error(404)
                return
            origin='http://127.0.0.1:' + str(self.server.server_port)
            if (self.headers.get('Host') != origin[7:] or
                    self.headers.get('Origin') not in (None, origin) or
                    not secrets.compare_digest(
                        self.headers.get('X-Taraz-Close-Token',''),close_http_token) or
                    not secrets.compare_digest(
                        self.headers.get('X-Taraz-Close-Session-Token',''),
                        close_session_token) or
                    self.headers.get('Content-Type','').split(';')[0].strip().lower()
                        != 'application/json' or
                    self.headers.get('Transfer-Encoding') is not None):
                self.send_error(403)
                return
            try:
                size=int(self.headers.get('Content-Length','-1'))
                if not 1 <= size <= 512:
                    raise ValueError('Unexpected close request size')
                payload=json.loads(self.rfile.read(size))
                if self.path.endswith('/poll'):
                    if payload != {}:
                        raise ValueError('Unexpected fields in native poll')
                    response=close_handshake.poll()
                else:
                    response=close_handshake.respond(payload)
            except (ValueError,TypeError,UnicodeError,PermissionError):
                self.send_error(403)
                return
            output=json.dumps(response,separators=(',',':')).encode('ascii')
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(output)))
            self.end_headers()
            self.wfile.write(output)

        def log_message(self, *_args):
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def _native_accounting_login(store, *, require_existing=False):
    """Native credential gate, optionally forbidding *all* first-user setup.

    An existing Taraz production book must never become an implicit first-run
    admin even if the identity file is replaced while the dialog opens.
    Standalone's explicit *new book* workflow keeps its existing behavior.
    """
    if require_existing:
        if not store.initialized():
            raise PermissionError('Existing accounting company requires its user registry')

        class _ExistingLoginOnly:
            def initialized(self):
                if not store.initialized():
                    raise PermissionError('Company identity disappeared before login')
                return True

            def add_user(self, *_args, **_kwargs):
                raise PermissionError('Creating a first administrator at Taraz login is forbidden')

            def login(self, *args, **kwargs):
                return store.login(*args, **kwargs)

            def require_session(self, *args, **kwargs):
                return store.require_session(*args, **kwargs)

        store_for_login = _ExistingLoginOnly()
    else:
        store_for_login = store
    if not store.initialized() and (store.root/ACCOUNTING_FILE).exists():
        raise PermissionError('Existing ledger has no identity file: restore its backup before login')
    from standalone_accounting_secure_login import prompt_premium_accounting_login
    return prompt_premium_accounting_login(store_for_login)


def _run_company_session(data_dir, selected_company_name, args):
    company_guard = None
    identity_store = None
    logged_in_user = None
    identity_token = None
    from standalone_accounting_company_registry import (
        CompanySessionGuard, StandaloneCompanyRegistry)
    directory=Path(data_dir)
    registered=False
    if directory.parent.name=='books' and (directory.parent.parent/'companies.json').exists():
        registry=StandaloneCompanyRegistry(directory.parent.parent)
        registered=directory==registry.company_data_directory(directory.name)
    if args.companies_dir or registered:
        company_guard = CompanySessionGuard(Path(data_dir)).acquire()
    try:
        identity_path=Path(data_dir)/'local-users.json'
        if (args.companies_dir or registered or identity_path.exists() or
            identity_path.is_symlink() or (Path(data_dir)/ACCOUNTING_FILE).exists()):
            from standalone_accounting_identity import LocalCompanyIdentity
            identity_store=LocalCompanyIdentity(Path(data_dir))
            # Never let a missing identity registry convert an existing book
            # into a new local-admin account, regardless of launch switches.
            if not identity_store.initialized() and (Path(data_dir)/ACCOUNTING_FILE).exists():
                raise PermissionError('Existing ledger has no user registry; restore identity backup before login')
            login=_native_accounting_login(identity_store)
            if login is None:
                if company_guard:
                    company_guard.release()
                return False
            logged_in_user,identity_token=login
        api = AccountingDesktopAPI(data_dir, company_name=selected_company_name,
            company_workspace_id=directory.name if registered else "",
            authenticated_user=logged_in_user,identity_store=identity_store,
            identity_token=identity_token)
        from standalone_accounting_auto_backup import AutomaticStandaloneBackups
        backups = AutomaticStandaloneBackups(
            api.path.parent, plaintext_acknowledged=True)
        # Fail closed at startup if a verified baseline cannot be backed up.
        with api._lock:
            api.standaloneAccountingRead()
            backups.backup_now()
        backups.start()
    except BaseException:
        if company_guard:
            company_guard.release()
        raise
    server = None
    server_thread = None
    exit_backup_saved = False
    try:
        server = serve_accounting_page(args.site_dir)
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        import webview
        window = webview.create_window(
            "مدار | حسابداری مستقل", f"http://127.0.0.1:{server.server_port}/accounting.html",
            width=1450, height=925, min_size=(880, 620), js_api=api,
        )
        api._native_window = window

        def backup_on_close():
            nonlocal exit_backup_saved
            if exit_backup_saved:
                return True
            try:
                with api._lock:
                    backups.backup_now()
                    # Financial commands cannot race in after the final
                    # verified backup has been published.
                    api._exit_backed_up = True
            except Exception as exc:
                # pywebview events.closing cancels the close when a handler
                # returns False. The user may retry after fixing disk access.
                api._switch_requested = False
                print("Mandatory accounting exit backup failed: " + str(exc),
                      file=sys.stderr)
                failure_message=str(exc)
                # Never call evaluate_js in a blocking close event: on some
                # pywebview backends that deadlocks the GUI thread.
                def notify():
                    try:
                        window.evaluate_js("window.alert(" + json.dumps(
                            "بستن حسابداری متوقف شد. پشتیبان‌گیری مالی ناموفق بود: " +
                            failure_message, ensure_ascii=False) + ")")
                    except Exception:
                        pass  # Still prevent close even if dialog unavailable.
                Thread(target=notify,daemon=True).start()
                return False
            exit_backup_saved = True
            return True

        def reset_aborted_close():
            nonlocal exit_backup_saved
            # Do not unlock host financial commands before the browser has
            # acknowledged that its inert editor has actually been restored.
            # If the bridge is transiently unavailable, this worker retries;
            # another native X is vetoed until the editor is recovered.
            if recover_native_editor_after_close_abort(window, api):
                exit_backup_saved=False
                return True
            return False

        close_gate=NativeAccountingCloseGate(window,api,backup_on_close,
            on_aborted_close=reset_aborted_close)
        api._native_close_gate=close_gate
        window.events.closing += close_gate.closing
        webview.start()
    finally:
        try:
            backups.stop()
            # Recovery path for a webview runtime that terminates without
            # delivering its normal closing event. Never silently exit on a
            # failed final backup, even when the native window already died.
            if not exit_backup_saved:
                with api._lock:
                    backups.backup_now()
                    api._exit_backed_up = True
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if server_thread is not None:
                server_thread.join(timeout=5)
            if company_guard:
                company_guard.release()
            if identity_store is not None and identity_token is not None:
                identity_store.logout(identity_token)

    return bool(api._switch_requested and exit_backup_saved)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Madar isolated accounting desktop")
    parser.add_argument("--data-dir",
                        help="Explicit absolute private directory for accounting data; if omitted, select a folder")
    parser.add_argument("--companies-dir",
                        help="Existing absolute registry root for independent per-company accounting books")
    parser.add_argument("--recovery", action="store_true",
                        help="Open a separate OFFLINE restore wizard; NEVER start the live accounting host")
    bundled_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    parser.add_argument("--site-dir", default=str(bundled_root / "dist"),
                        help="Directory containing built accounting.html")
    parser.add_argument("--restore-ui", action="store_true",
                        help="Run the OFFLINE no-overwrite graphical restore wizard and exit")
    args = parser.parse_args(argv)
    if args.companies_dir and (args.data_dir or args.recovery or args.restore_ui):
        parser.error("--companies-dir requires standalone company mode without other launch modes")
    if args.recovery:
        from standalone_accounting_recovery_wizard import run_offline_recovery_wizard
        return 0 if run_offline_recovery_wizard(
            Path(args.data_dir) if args.data_dir else None) else 1
    if args.restore_ui:
        # Must run BEFORE AccountingDesktopAPI, backup timers and WebView host.
        from standalone_accounting_restore_ui import run_restore_wizard
        return run_restore_wizard()
    while True:
        data_dir = args.data_dir
        selected_company_name = ""
        if args.companies_dir:
            from standalone_accounting_company_registry import (
                StandaloneCompanyRegistry, pick_company_dialog,
            )
            selected = pick_company_dialog(StandaloneCompanyRegistry(
                Path(args.companies_dir)))
            if selected is None:
                return 0
            data_dir = selected["path"]
            selected_company_name = selected["name"]
        if data_dir is None:
            # A packaged EXE must be launchable by double-click without silently
            # selecting an existing task-manager or finance database.
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            try:
                data_dir = filedialog.askdirectory(
                    parent=root, title="پوشه اختصاصی اطلاعات حسابداری مدار را انتخاب کنید",
                    mustexist=True,
                )
            finally:
                root.destroy()
            if not data_dir:
                return 0
        switch_requested = _run_company_session(data_dir, selected_company_name, args)
        if not args.companies_dir or not switch_requested:
            return 0

if __name__ == "__main__":
    main()
