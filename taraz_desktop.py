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


def private_qa_cdp_port(data, environment=None):
    """Enable WebView2's official CDP hook ONLY for a marked private QA book.

    No debugging listener is opened during ordinary Taraz runs. Setting an
    environment variable alone cannot attach to a normal accounting profile.
    This grants no new financial permissions; the real WebView2 bridge still
    enforces the same authenticated API and accounting revision guards.
    """
    variables = os.environ if environment is None else environment
    requested = variables.get('TARAZ_QA_CDP_PORT')
    if requested is None:
        return None
    path = Path(data).resolve()
    ambient = variables.get('APPDATA')
    override = variables.get('TARAZ_QA_DATA_DIR')
    marker = path / '.taraz-private-cdp-qa.json'
    if (variables.get('TARAZ_QA_MODE') != '1' or
            not ambient or not override or
            not Path(ambient).is_absolute() or
            path != Path(override).resolve() or
            path.parent != Path(ambient).resolve() or
            'qa' not in [part.casefold() for part in path.parts] or
            'qa-runtime' not in [part.casefold() for part in path.parts] or
            marker.is_symlink() or not marker.is_file() or
            not requested.isascii() or not requested.isdecimal() or
            str(int(requested)) != requested or
            not 1024 <= int(requested) <= 65535):
        raise PermissionError('Private QA-only CDP preflight failed')
    try:
        data_marker = json.loads(marker.read_text(encoding='utf-8'))
        if (type(data_marker) is not dict or
                data_marker != {'privateQaOnly': True, 'profile': str(path)}):
            raise ValueError('Unrecognized QA profile marker')
    except (ValueError, OSError) as exc:
        raise PermissionError('Private QA marker is untrusted') from exc
    return int(requested)

class TarazAPI(AccountingDesktopAPI):
    def __init__(self, path):
        super().__init__(str(path))
        self._requires_migration = (path / "taraz-migration-manifest.json").exists()

    def tarazEcosystemStatus(self):
        """Authenticated, read-only truth about this local ecosystem boundary.

        Do not claim a shared RADAR deployment, a central Cloud/finance lease,
        working remote transport or an operational model from code presence.
        No internet, mutable accounting call or LAN host side effect.
        """
        from taraz_ecosystem_protocol import SCHEMA_VERSION, EVENT_SCHEMAS
        with self._lock:
            self._require_authenticated()
            return {
                'schemaVersion': SCHEMA_VERSION,
                'product': 'TARAZ',
                'localCompanyDirectory': True,
                'localManualBusinessFunctions': True,
                'networkState': 'NOT_PROBED',
                'centralFinancialAuthorityTransfer': 'OPEN_NOT_IMPLEMENTED',
                'outbox': {
                    'nonfinancialSchemaAvailable': True,
                    'eventTypes': sorted(EVENT_SCHEMAS),
                    'remoteSenderAvailable': False,
                    'remoteReceiptTransportVerified': False,
                },
                'otherProducts': {
                    'MADAR': 'REQUIRES_AUTHENTICATED_PINNED_HOST',
                    'RADAR': 'SOURCE_NOT_VERIFIED',
                },
                'source': 'LOCAL_AUTHENTICATED_TARAZ',
                'readOnly': True,
                'financialEventCreated': False,
            }

    def tarazAiProviderStatus(self):
        """AI status only; explicitly never invokes the model or a cloud API."""
        from taraz_ai_provider_status import provider_status
        with self._lock:
            self._require_authenticated()
            return provider_status()

    def tarazOrderList(self, offset=0, limit=50):
        """Read the operational order desk for the selected accounting company."""
        from taraz_order_store import TarazOrderStore
        with self._lock:
            self._require_authenticated()
            return TarazOrderStore(self.path.parent).list(offset=offset, limit=limit)

    def tarazOrderCommand(self, request):
        """Manual order-only mutation. No journal, invoice or payment is posted."""
        from taraz_order_store import TarazOrderStore
        with self._lock:
            checked = self._require_authenticated("editor")
            # A browser-supplied confirmation is not proof of finance authority.
            # The trusted native session must authorize approval/settlement.
            if isinstance(request, dict) and request.get("action") in {
                "cost.approve", "payment.settle", "handoff.prepare"
            } and (checked.get("role") != "admin" or
                   checked.get("financeEdit") is not True):
                raise PermissionError("Finance approval requires authenticated finance admin")
            if self._exit_backed_up:
                raise RuntimeError("Taraz is closing; order mutations are unavailable")
            return TarazOrderStore(self.path.parent).command(
                request, actor=self._actor, role=checked["role"],
            )

    def tarazOrderFinanceDraft(self, request):
        """Explicit admin-approved order -> accounting DRAFT, never issue/post.

        This is the only order-to-accounting write gate. Registered real party,
        matching ledger currency, immutable handoff snapshot, document date,
        finance authorization and current accounting CAS are mandatory. A
        deterministic source reference prevents duplicate documents.
        """
        from taraz_order_store import TarazOrderStore, OrderConflict
        fields = {"orderId", "expectedOrderRevision", "expectedAccountingRevision",
                  "previewDigest", "documentDate", "explicitConfirmation"}
        if type(request) is not dict or set(request) != fields or (
            request["explicitConfirmation"] is not True):
            raise PermissionError("Explicit reviewed accounting draft confirmation required")
        order_id = request["orderId"]
        if not isinstance(order_id, str) or not re.fullmatch(r"[0-9a-f]{32}", order_id):
            raise ValueError("Invalid verified source order")
        if (type(request["expectedOrderRevision"]) is not int or
            request["expectedOrderRevision"] < 1 or
            type(request["expectedAccountingRevision"]) is not int or
            request["expectedAccountingRevision"] < 0 or
            not isinstance(request["previewDigest"], str) or
            not re.fullmatch(r"[0-9a-f]{64}", request["previewDigest"])):
            raise ValueError("Invalid financial preview/CAS")
        document_date = request["documentDate"]
        if not isinstance(document_date, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", document_date):
            raise ValueError("Document date must be explicitly supplied")
        try:
            datetime.strptime(document_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Invalid accounting document date") from exc
        if document_date > datetime.now(timezone.utc).date().isoformat():
            raise ValueError("Future accounting document date is forbidden")
        with self._lock:
            checked = self._require_authenticated("admin")
            if checked.get("role") != "admin" or checked.get("financeEdit") is not True:
                raise PermissionError("Current finance administrator approval required")
            if self._exit_backed_up:
                raise RuntimeError("Accounting desktop is closing")
            order = TarazOrderStore(self.path.parent).get(order_id)
            handoff = order.get("financeHandoff")
            if (order["revision"] != request["expectedOrderRevision"] or
                not order.get("financialHandoffReady") or
                not handoff or handoff["source_revision"]+1 != order["revision"] or
                handoff["preview_digest"] != request["previewDigest"]):
                raise OrderConflict("Order finance handoff not authorized or source changed")
            account = self.standaloneAccountingRead()
            view = account["view"]
            if view["currency"] != order["currency"]:
                raise ValueError("Order and accounting currency differ; no implicit conversion")
            sales = order["kind"] == "sale"
            party = view["parties"].get(order["customerId"])
            if party is None or party.get("kind") != ("customer" if sales else "vendor"):
                raise ValueError("An actual registered customer/vendor is required")
            account_id = "4000" if sales else "5000"
            if view["accounts"].get(account_id, {}).get("kind") != (
                    "revenue" if sales else "expense"):
                raise ValueError("Required accounting chart account is missing")
            doc_type = "invoice" if sales else "bill"
            collection = view["invoices" if sales else "bills"]
            doc_id = "ORD-" + order_id
            matched = [document for document in collection.values() if
                document.get("sourceType") == "taraz.order" and
                document.get("sourceId") == order_id]
            if matched:
                previous = matched[0]
                if (len(matched) == 1 and previous["id"] == doc_id and
                    previous["partyId"] == order["customerId"] and
                    previous["total"] == order["estimatedSalesTotal"] and
                    previous["status"] == "draft"):
                    return {"status": "ALREADY_DRAFT", "documentId": doc_id,
                            "orderId":order_id,"accountingRevision":account["revision"],
                            "journalCreated":False,"financialDocumentIssued":False}
                raise OrderConflict("Conflicting existing source accounting document")
            if doc_id in collection:
                raise OrderConflict("Target accounting document ID already used")
            if account["revision"] != request["expectedAccountingRevision"]:
                raise OrderConflict("Accounting book changed; review preview again")
            command = {
                "type":doc_type+".create",
                "eventId":"ORD-FIN-DRAFT-"+order_id,
                doc_type+"Id":doc_id,"partyId":order["customerId"],
                "documentDate":document_date,
                "lines":[{"description":order["title"],
                          "quantity":order["quantity"],
                          "unitPrice":order["unitPrice"],
                          "accountId":account_id}],
                "sourceType":"taraz.order","sourceId":order_id,
                "note":"Operational order reference: "+order_id,
            }
            result = self.standaloneAccountingCommand({
                "expectedRevision":account["revision"],"command":command})
            doc=result["view"]["invoices" if sales else "bills"][doc_id]
            if (doc["status"] != "draft" or doc["postedEntryId"] is not None or
                len(result["view"]["journals"]) != len(view["journals"])):
                raise RuntimeError("Accounting draft invariant breached; inspect ledger")
            return {"status":"DRAFT_CREATED","documentId":doc_id,
                    "orderId":order_id,"accountingRevision":result["revision"],
                    "journalCreated":False,"financialDocumentIssued":False}

    def tarazAgentOrderReview(self, orderId):
        """Read-only tool-backed review, with auditable evidence and no LLM claim."""
        from taraz_aaas_agent import review_order_tools
        with self._lock:
            self._require_authenticated()
            return review_order_tools(self.path.parent,orderId)

    def tarazAgentNaturalRequest(self, orderId, requestText):
        """Local grounded Persian request handling; no inferred finance actions."""
        from taraz_aaas_agent import interpret_natural_order_request
        with self._lock:
            self._require_authenticated()
            return interpret_natural_order_request(
                self.path.parent,orderId,requestText)

    def tarazAgentMemoryList(self, orderId):
        from taraz_aaas_agent import CompanyAgentMemory
        with self._lock:
            self._require_authenticated()
            return CompanyAgentMemory(self.path.parent).list(orderId)

    def tarazAgentMemoryCommand(self, request):
        from taraz_aaas_agent import CompanyAgentMemory
        with self._lock:
            actor=self._require_authenticated('editor')
            if self._exit_backed_up:
                raise RuntimeError('Taraz closing; memory changes locked')
            return CompanyAgentMemory(self.path.parent).command(
                request,actor=self._actor,role=actor['role'])

    def tarazMadarOrderPreview(self, orderId, projectId, connection,
                              explicitConsent=False):
        """Read authenticated Madar state; preview a non-financial new task."""
        from taraz_order_store import TarazOrderStore
        from taraz_madar_order_link import MadarOrderLinkStore
        from taraz_madar_order_sync import sync_order_to_madar
        if explicitConsent is not True:
            raise PermissionError('Madar project read consent required')
        with self._lock:
            actor=self._require_authenticated('admin')
            if actor.get('role')!='admin':
                raise PermissionError('Taraz administrator required')
            order=TarazOrderStore(self.path.parent).get(orderId)
            linked=MadarOrderLinkStore(self.path.parent).read(orderId)
            witness=linked.get('link') or {}
            if (order.get('projectReference')!=projectId or
                witness.get('project_id')!=projectId or
                witness.get('host_url')!=connection.get('url','').rstrip('/') or
                witness.get('tls_fingerprint')!=str(
                    connection.get('fingerprint','')).lower()):
                raise PermissionError('Verified matching Madar project link required')
            # The order may have advanced since its last local link. A fresh
            # authenticated Madar state read below rechecks current membership,
            # and its exact revision is mandatory at final human-approved POST.
            return sync_order_to_madar(order=order,project_id=projectId,
                connection=connection,reviewed_revision=None,preview_digest=None,
                dry_run=True,manual_confirmation=False)

    def tarazMadarOrderProgress(self, orderId, projectId, connection,
                               explicitConsent=False):
        """Read actual Madar checklist status; NEVER copy finance or overwrite it."""
        from taraz_order_store import TarazOrderStore
        from taraz_madar_order_link import MadarOrderLinkStore
        from taraz_madar_order_sync import read_madar_order_stage_progress
        if explicitConsent is not True or type(connection) is not dict:
            raise PermissionError('Explicit Madar status-read consent required')
        with self._lock:
            who=self._require_authenticated('admin')
            if who.get('role')!='admin':
                raise PermissionError('Active Taraz administrator required')
            order=TarazOrderStore(self.path.parent).get(orderId)
            link=MadarOrderLinkStore(self.path.parent).read(orderId).get('link') or {}
            if (order.get('projectReference')!=projectId or
                link.get('project_id')!=projectId or
                link.get('host_url')!=connection.get('url','').rstrip('/') or
                link.get('tls_fingerprint')!=str(
                    connection.get('fingerprint','')).lower()):
                raise PermissionError('Verified matching Madar project required')
            progress=read_madar_order_stage_progress(
                order=order,project_id=projectId,connection=connection)
            return {**progress,'orderId':orderId,
                    'orderRevision':order['revision']}

    def tarazMadarOrderCommit(self, request, connection):
        """Explicit human-approved CAS operational sync; never finance posting."""
        from taraz_order_store import TarazOrderStore, OrderConflict
        from taraz_madar_order_link import MadarOrderLinkStore
        from taraz_madar_order_sync import sync_order_to_madar
        exact={'orderId','expectedOrderRevision','projectId',
               'expectedMadarRevision','previewDigest',
               'explicitConsent','manualConfirmation'}
        if type(request) is not dict or set(request)!=exact or (
            request['explicitConsent'] is not True or
            request['manualConfirmation'] is not True or
            type(request['expectedOrderRevision']) is not int):
            raise PermissionError('Human-reviewed Madar sync request required')
        with self._lock:
            checked=self._require_authenticated('admin')
            if checked.get('role')!='admin' or self._exit_backed_up:
                raise PermissionError('Active Taraz administrator required')
            store=TarazOrderStore(self.path.parent)
            order=store.get(request['orderId'])
            if request['expectedOrderRevision']!=order['revision']:
                raise OrderConflict('Taraz order revision changed before Madar sync')
            link_store=MadarOrderLinkStore(self.path.parent)
            linked=link_store.read(request['orderId'])
            witness=linked.get('link') or {}
            if (order.get('projectReference')!=request['projectId'] or
                witness.get('project_id')!=request['projectId'] or
                witness.get('host_url')!=connection.get('url','').rstrip('/') or
                witness.get('tls_fingerprint')!=str(
                    connection.get('fingerprint','')).lower()):
                raise PermissionError('Verified current Madar project link required')
            attempt=link_store.begin_sync_attempt(
                order_id=order['id'],order_revision=order['revision'],
                project_id=request['projectId'],actor=self._actor,
                preview_digest=request['previewDigest'],
                host_revision=request['expectedMadarRevision'])
            transmission_started=False
            def record_possible_write():
                nonlocal transmission_started
                link_store.mark_sync_transmitting(attempt)
                transmission_started=True
            try:
                result=sync_order_to_madar(
                    order=order,project_id=request['projectId'],
                    connection=connection,
                    reviewed_revision=request['expectedMadarRevision'],
                    preview_digest=request['previewDigest'],
                    manual_confirmation=True,dry_run=False,source_store=store,
                    before_remote_write=record_possible_write)
            except BaseException as exc:
                # Only error *type* is persisted, never host response, token,
                # PIN, password, project payload or finance content.
                link_store.finish_sync_attempt(
                    attempt,status=('OUTCOME_UNKNOWN' if
                        transmission_started else 'REJECTED'),
                    error_type=type(exc).__name__)
                raise
            link_store.finish_sync_attempt(
                attempt,status=('SYNCHRONIZED' if
                    result['wroteMadarState'] else 'ALREADY_SYNCED'))
            return result

    def tarazMadarOrderSyncHistory(self, orderId):
        """Company-scoped, read-only durable synchronization audit."""
        from taraz_order_store import TarazOrderStore
        from taraz_madar_order_link import MadarOrderLinkStore
        with self._lock:
            who=self._require_authenticated('admin')
            if who.get('role')!='admin':
                raise PermissionError('Taraz administrator required')
            TarazOrderStore(self.path.parent).get(orderId)
            return {'orderId':orderId,
                    **MadarOrderLinkStore(self.path.parent).sync_history(orderId)}

    def tarazMadarOrderRecover(self, orderId, projectId, connection,
                              explicitConsent=False):
        """Read-only host reconciliation; NEVER re-POST or auto-retry a task."""
        from taraz_madar_order_link import MadarOrderLinkStore
        if explicitConsent is not True:
            raise PermissionError('Explicit Madar recovery read consent required')
        with self._lock:
            self._require_authenticated('admin')
            preview=self.tarazMadarOrderPreview(
                orderId,projectId,connection,explicitConsent=True)
            if preview.get('status') not in ('ALREADY_SYNCED','PREVIEW_ONLY'):
                raise ValueError('Unrecognized host reconciliation outcome')
            # Never derive current source revision from a truncated list.
            from taraz_order_store import TarazOrderStore
            order=TarazOrderStore(self.path.parent).get(orderId)
            outcome=('RECOVERED_CONFIRMED' if
                preview['status']=='ALREADY_SYNCED' else 'REVIEW_REQUIRED')
            history=MadarOrderLinkStore(self.path.parent)
            settled=history.reconcile_uncertain(
                order_id=orderId,order_revision=order['revision'],
                project_id=projectId,status=outcome)
            return {'status':outcome,'priorUnknownResolved':settled,
                    'taskId':preview['taskId'],'orderId':orderId,
                    'orderRevision':order['revision'],
                    'wroteMadarState':False,'financialEventCreated':False,
                    'requiresNewHumanReview':outcome=='REVIEW_REQUIRED'}

    def tarazOrderMadarLinkRead(self, orderId):
        """Read Taraz-stored verification, not a claim of live Madar membership."""
        from taraz_madar_order_link import MadarOrderLinkStore
        with self._lock:
            self._require_authenticated('admin')
            return MadarOrderLinkStore(self.path.parent).read(orderId)

    def tarazOrderMadarLink(self, request):
        """Revalidate a selected project via authenticated pinned HTTPS Madar.

        Only a read of the remote ACL-scoped project page occurs. Credentials
        stay in this call and are never stored. Association is written only to
        the current Taraz company's local SQLite; Madar itself is unchanged.
        """
        from taraz_madar_order_link import MadarOrderLinkStore
        from taraz_order_store import TarazOrderStore
        if type(request) is not dict or set(request) != {
                'orderId','expectedOrderRevision','projectId','pageOffset',
                'expectedLinkRevision','connection','explicitConsent',
                'idempotencyKey'} or request['explicitConsent'] is not True:
            raise PermissionError('Explicit scoped Madar project association required')
        if type(request['pageOffset']) is not int or (
                not 0<=request['pageOffset']<=50000):
            raise ValueError('Invalid authenticated project page')
        with self._lock:
            checked=self._require_authenticated('admin')
            if checked.get('role')!='admin':
                raise PermissionError('Authenticated Taraz administrator required')
            if self._exit_backed_up:
                raise RuntimeError('Taraz closing; Madar linkage refused')
            order=TarazOrderStore(self.path.parent).get(request['orderId'])
            if (order['revision']!=request['expectedOrderRevision'] or
                order['projectReference']!=request['projectId']):
                raise ValueError('Selected project does not match persisted order')
            # Only the real host reader validates credentials/TLS, principal,
            # ACL and SHA-256 state revision. No local-file fallback.
            page=self.tarazMadarDataRead('projects',request['pageOffset'],50,True,
                                         request['connection'],'host')
            return MadarOrderLinkStore(self.path.parent).bind(
                order_id=request['orderId'],
                expected_order_revision=request['expectedOrderRevision'],
                project_id=request['projectId'],page=page,
                pin=request['connection']['fingerprint'],
                expected_link_revision=request['expectedLinkRevision'],
                idempotency_key=request['idempotencyKey'])

    def tarazOrderSuggest(self, requestText):
        """Read-only, local-model order hints for authenticated users.

        This never calls the accounting command API, persists order data, or
        posts a financial event. The user must review and apply hints in UI.
        """
        with self._lock:
            self._require_authenticated()
            if self._exit_backed_up:
                raise RuntimeError("Taraz is closing; suggestions are unavailable")
        from taraz_llm_order_suggest import suggest_order
        return suggest_order(requestText)

    def tarazPrintSuggest(self, promptText):
        """Authenticate an on-device AI suggestion without passing any ledger data."""
        with self._lock:
            self._require_authenticated()
            if self._exit_backed_up:
                raise RuntimeError("Taraz is closing; suggestions are unavailable")
        from taraz_llm_print_suggest import suggest_print_layout
        return suggest_print_layout(promptText)

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
        from taraz_integration import _exists, list_requests, list_recoverable_reviews
        with self._lock:
            self._require_authenticated()
            root = bridge_root()
            pending = list_requests(root)
            recovery = list_recoverable_reviews(root)
            # An interrupted pre-move decision may still reside in pending.
            # Never offer a fresh review for any existing intent, even corrupt:
            # corrupt cases are operator incidents, not new decisions.
            pending["requests"] = [item for item in pending["requests"]
                                   if not _exists(root / "reviewed" /
                                                  (item["id"] + ".intent.json"))]
            return {**pending, **recovery}

    def tarazIntegrationReview(self, request_id, decision):
        """Explicit acknowledgement; never issues invoices or financial events."""
        from taraz_integration import review_request
        with self._lock:
            self._require_authenticated('editor')
            return review_request(bridge_root(), request_id, decision)

    def tarazIntegrationRecover(self, request_id, manual_action=False):
        """Resume a persisted metadata decision on explicit user action only."""
        from taraz_integration import recover_review
        if manual_action is not True:
            raise PermissionError("manual recovery confirmation required")
        with self._lock:
            self._require_authenticated('editor')
            return recover_review(bridge_root(), request_id)

    def tarazMadarDataOverview(self, explicitConsent=False):
        """Dashboard-visible real inbox, plus optional user-approved local counts.

        Without consent we do NOT inspect the content of Madar's private task
        file.  Presence and mailbox metadata are sufficient to draw the panel.
        """
        from taraz_madar_data_reader import local_madar_available, read_local_madar_state
        with self._lock:
            self._require_authenticated()
            inbox = self.tarazIntegrationList()
            result = {
                "inbox": inbox,
                "local": local_madar_available(),
                "fullReadRequiresExplicitConsent": True,
                "readOnly": True, "financialEventCreated": False,
            }
            if explicitConsent is True:
                self._require_authenticated('admin')
                result["snapshot"] = read_local_madar_state(
                    scope="summary", explicit_consent=True)
            elif explicitConsent is not False:
                raise PermissionError("Explicit consent must be a boolean")
            return result

    def tarazMadarDataRead(self, scope="inbox", offset=0, limit=50,
                           explicitConsent=False, connection=None, source="local"):
        """On-demand dashboard data. No ledger access, financial posting or cache.

        'inbox': existing pending/recovery metadata, no private data read.
        'summary'/'all'/named collection: require explicit consent + Taraz admin.
        source='local' reads only same-user Madar tasks.json (may be stale);
        source='host' requires separately authenticated pinned HTTPS Madar login.
        """
        from taraz_madar_data_reader import (
            MadarReadError, _validate_paging, read_authorized_madar_state,
            read_local_madar_state,
        )
        with self._lock:
            self._require_authenticated()
            if scope == "inbox":
                if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
                    raise MadarReadError("Invalid inbox page")
                inbox = self.tarazIntegrationList()
                visible = inbox["requests"][offset:offset + limit]
                return {
                    **inbox, "requests": visible,
                    "pendingCount": len(inbox["requests"]),
                    "scope": "inbox", "offset": offset, "limit": limit,
                    "source": {"kind": "madar-local-metadata-proposals",
                               "hostAuthenticated": False, "readOnly": True},
                    "financialEventCreated": False,
                }
            _validate_paging(scope, offset, limit)
            self._require_authenticated('admin')
            if source not in ("local", "host") or type(source) is not str:
                raise MadarReadError("Unknown Madar data source")
            if explicitConsent is not True:
                raise PermissionError("Explicit consent required for Madar data")
            if source == "local":
                if connection is not None:
                    raise MadarReadError("Local data read cannot accept host credentials")
                return read_local_madar_state(
                    scope=scope, explicit_consent=True, offset=offset, limit=limit)
            return read_authorized_madar_state(
                scope=scope, explicit_consent=True, connection=connection,
                offset=offset, limit=limit)


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
        private_cdp_port = private_qa_cdp_port(data)
        if private_cdp_port is not None:
            # pywebview's EdgeChromiumCreationProperties only recognizes this
            # official internal setting, not an environment-only CDP flag.
            webview.settings['REMOTE_DEBUGGING_PORT'] = private_cdp_port
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
