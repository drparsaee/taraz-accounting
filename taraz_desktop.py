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
import stat
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
    # QA root can be the historical single-book fixture or a registered
    # company hub. The latter opens a verified nested books/<company-id> book;
    # the old equality check would silently disable private CDP there.
    roaming = Path(ambient).resolve() if ambient and Path(ambient).is_absolute() else None
    qa_hub = Path(override).resolve() if override and Path(override).is_absolute() else None
    single_book = bool(qa_hub and roaming and path == qa_hub and path.parent == roaming)
    registered_book = False
    if (qa_hub and roaming and qa_hub.parent == roaming and
            path.parent == qa_hub / 'books' and re.fullmatch(r'[0-9a-f]{32}', path.name)):
        try:
            from standalone_accounting_company_registry import StandaloneCompanyRegistry
            registered_book = (StandaloneCompanyRegistry(qa_hub).company_data_directory(
                path.name).resolve() == path)
        except (OSError, ValueError, RuntimeError):
            registered_book = False
    marker = path / '.taraz-private-cdp-qa.json'
    if (variables.get('TARAZ_QA_MODE') != '1' or
            not ambient or not override or
            not (single_book or registered_book) or
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
    def __init__(self, path, *, company_name="", company_workspace_id="",
                 authenticated_user=None, identity_store=None, identity_token=None,
                 legacy_workspace=None):
        # The production launcher always supplies an authenticated company
        # principal. The original one-argument constructor remains available
        # to legacy isolated API fixtures, never used by run().
        super().__init__(str(path), company_name=company_name,
                         company_workspace_id=company_workspace_id,
                         authenticated_user=authenticated_user,
                         identity_store=identity_store,
                         identity_token=identity_token)
        self._requires_migration = (path / "taraz-migration-manifest.json").exists()
        self._legacy_workspace = legacy_workspace

    def _with_migration(self, result):
        result = super()._with_migration(result)
        if getattr(self, '_legacy_workspace', None) is not None:
            result['view']['legacyWorkspaceState'] = {
                'identityStatus': 'identity_pending',
                'ownershipStatus': 'ownership_unclaimed',
                'label': self._legacy_workspace['label'],
                'readOnly': True,
            }
        return result

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

    def tarazAiChatList(self, query=''):
        """List only current authenticated actor's company-scoped AI history."""
        from taraz_ai_business_service import AiBusinessService
        with self._lock:
            return AiBusinessService(self).list(query)

    def tarazAiChatRead(self, conversationId):
        """Decrypt only current actor's authorized conversation."""
        from taraz_ai_business_service import AiBusinessService
        with self._lock:
            return AiBusinessService(self).read(conversationId)

    def tarazAiChatCommand(self, request):
        """Reviewable AI workspace commands; only explicit finance DRAFT save."""
        from taraz_ai_business_service import AiBusinessService
        with self._lock:
            return AiBusinessService(self).command(request)

    def tarazOrderList(self, offset=0, limit=50):
        """Read the operational order desk for the selected accounting company."""
        from taraz_order_store import TarazOrderStore
        with self._lock:
            self._require_authenticated()
            return TarazOrderStore(self.path.parent).list(offset=offset, limit=limit)

    def tarazCustomerOrderHistory(self, partyId, offset=0, limit=25):
        """Local Taraz admin-only redacted history; no Madar peer granted.

        A future transport must authenticate the Madar principal and project
        before any of these already-redacted rows leave Taraz.
        """
        from taraz_order_store import TarazOrderStore
        with self._lock:
            actor = self._require_authenticated("admin")
            authority = self._accounts.get(self._actor, {})
            if (self._identity_store is None or
                    actor.get("role") != "admin" or
                    authority.get("financeView") is not True):
                raise PermissionError("Native authenticated finance-view admin required")
            from taraz_order_store import _ID as _ORDER_PARTY_ID
            if type(partyId) is not str or not _ORDER_PARTY_ID.fullmatch(partyId):
                raise PermissionError("Invalid party ID for authorized history read")
            view = self.standaloneAccountingRead()["view"]
            if (type(view.get("parties")) is not dict or
                    partyId not in view["parties"]):
                raise PermissionError("Counterparty not in authenticated company ledger")
            return TarazOrderStore(self.path.parent).customer_order_history(
                partyId, offset=offset, limit=limit)

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


def prepare_offline_accounting_on_launch(api, backups):
    """Initialize only the selected book and its backup, never personal history.

    History APIs keep their independent _source_guard(). This function is
    intentionally usable with a freshly initialized legitimate RIAL book.
    """
    with api._lock:
        api.standaloneAccountingRead()
        backups.backup_now()


def _pick_existing_taraz_company(companies):
    """Read-only native selector: deliberately NO create-company control."""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("تراز | انتخاب شرکت ثبت‌شده")
    root.geometry("540x390")
    root.minsize(440, 320)
    panel = ttk.Frame(root, padding=20)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="شرکت ثبت‌شده را برای ورود انتخاب کنید:").pack(anchor="e")
    choices = tk.Listbox(panel, exportselection=False, height=11)
    choices.pack(fill="both", expand=True, pady=(12, 12))
    for record in companies:
        choices.insert(tk.END, record["name"])
    selected = {"id": None}

    def accept(_event=None):
        indices = choices.curselection()
        if not indices:
            return
        selected["id"] = companies[indices[0]]["id"]
        root.quit()

    def cancel(_event=None):
        selected["id"] = None
        root.quit()

    controls = ttk.Frame(panel)
    controls.pack(fill="x")
    ttk.Button(controls, text="ورود به شرکت", command=accept).pack(side="right")
    ttk.Button(controls, text="انصراف", command=cancel).pack(side="left")
    choices.bind("<Double-Button-1>", accept)
    choices.bind("<Return>", accept)
    root.bind("<Escape>", cancel)
    root.protocol("WM_DELETE_WINDOW", cancel)
    try:
        if companies:
            choices.selection_set(0)
            choices.activate(0)
            choices.focus_set()
        root.mainloop()
        return selected["id"]
    finally:
        root.destroy()


def select_existing_taraz_company(registry_root, *, choose=None):
    """Resolve a registered existing book without creating ANY profile files.

    The historical unregistered `%APPDATA%/Taraz` ledger is NOT silently
    assigned an invented company ID. Moving it into registry is a separate,
    explicitly authorized offline migration with verified backup/restore.
    """
    from standalone_accounting_company_registry import StandaloneCompanyRegistry
    hub = Path(registry_root)
    if not hub.is_absolute() or not hub.is_dir() or hub.is_symlink():
        raise PermissionError("Existing absolute Taraz company registry required")
    # list_companies() intentionally returns [] when companies.json is absent.
    registry = StandaloneCompanyRegistry(hub)
    companies = registry.list_companies()
    if not companies:
        raise PermissionError("No registered Taraz company; offline migration/setup required")
    # For one verified registered company, there is nothing meaningful to pick.
    # Continue to the real credential gate; never infer a company from an
    # unregistered legacy ledger or bypass identity authentication.
    selected = (companies[0]["id"] if len(companies) == 1 and choose is None else
                (choose or _pick_existing_taraz_company)([dict(c) for c in companies]))
    if selected is None:
        return None
    if type(selected) is not str or selected not in {c["id"] for c in companies}:
        raise PermissionError("Selected company was not present in verified registry")
    # Verify membership again after the native chooser; selection may be stale.
    directory = registry.company_data_directory(selected)
    name = next(c["name"] for c in registry.list_companies() if c["id"] == selected)
    return directory, name, selected


def open_authenticated_taraz_company(registry_root, *, choose=None, login=None):
    """Read-only preflight, then native real identity login; never boots a DB.

    `choose` and `login` injection is used ONLY by synthetic unit fixtures.
    The production entrypoint calls this function without overrides.
    """
    selected = select_existing_taraz_company(registry_root, choose=choose)
    if selected is None:
        return None
    directory, name, company_id = selected
    from standalone_accounting_identity import LocalCompanyIdentity
    from standalone_accounting_desktop import _native_accounting_login
    from taraz_order_store import _path_ok
    _path_ok(directory)
    ledger = directory / "standalone-accounting.sqlite3"
    identity_path = directory / "local-users.json"
    def regular_unlinked(file):
        return (file.is_file() and not file.is_symlink() and
                not (getattr(file.lstat(), "st_file_attributes", 0) &
                     getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))

    if not regular_unlinked(ledger) or not regular_unlinked(identity_path):
        raise PermissionError("Existing company requires ledger and protected identity registry")
    identity = LocalCompanyIdentity(directory)
    if not identity.initialized():
        raise PermissionError("Existing company has no valid authenticated user")
    authenticated = ((login or (lambda store: _native_accounting_login(
        store, require_existing=True)))(identity))
    if authenticated is None:
        return None
    if (not isinstance(authenticated, tuple) or len(authenticated) != 2):
        raise PermissionError("Native company login returned an invalid session")
    user, token = authenticated
    try:
        if not isinstance(token, str) or not token:
            raise PermissionError("Native company login returned no session token")
        current = identity.require_session(token, "viewer")
        if type(user) is not dict or user != current:
            raise PermissionError("Native login returned a mismatched company identity")
        api = TarazAPI(directory, company_name=name,
                       company_workspace_id=company_id,
                       authenticated_user=current, identity_store=identity,
                       identity_token=token)
        return api, identity, token
    except BaseException:
        if isinstance(token, str):
            identity.logout(token)
        raise


def open_identity_pending_legacy_workspace(root):
    """Open a proven migrated *local* legacy ledger with viewer rights only.

    No password, company administrator, financial approval or network identity
    is synthesized. An independent clone migration must have created the
    provenance-bound versioned sidecar before this path can become available.
    """
    from taraz_legacy_workspace_bridge import (
        LegacyLocalViewerIdentity, verify_workspace)
    directory = Path(root)
    if directory.resolve() != taraz_data_root().resolve():
        raise PermissionError('Legacy viewing is restricted to the local Taraz profile')
    workspace = verify_workspace(directory)
    identity = LegacyLocalViewerIdentity(directory)
    user, token = identity.session()
    try:
        api = TarazAPI(directory, company_name=workspace['label'],
                       company_workspace_id=workspace['workspaceId'],
                       authenticated_user=user, identity_store=identity,
                       identity_token=token, legacy_workspace=workspace)
        return api, identity, token
    except BaseException:
        identity.logout(token)
        raise


def _run_authenticated_taraz_api(api):
    """Existing Taraz financial/UI lifecycle, now bound to a real login."""
    import msvcrt
    from standalone_accounting_company_registry import (
        CompanySessionGuard, StandaloneCompanyRegistry)
    data = api.path.parent
    if getattr(api, "_identity_store", None) is None or not api._identity_token:
        raise PermissionError("Production Taraz startup requires a live company user session")
    api._require_authenticated("viewer")
    from taraz_legacy_workspace_bridge import LegacyLocalViewerIdentity, verify_workspace
    is_pending_legacy = isinstance(api._identity_store, LegacyLocalViewerIdentity)
    if is_pending_legacy:
        current = verify_workspace(data)
        if (current['workspaceId'] != api.company_workspace_id or
                data.resolve() != taraz_data_root().resolve() or
                api._actor != LegacyLocalViewerIdentity.USER or
                api._accounts[api._actor].get('role') != 'viewer'):
            raise PermissionError('Unverified legacy workspace or viewer permission')
    elif (not api.company_workspace_id or data.parent.name != "books" or
            StandaloneCompanyRegistry(data.parent.parent).company_data_directory(
                api.company_workspace_id) != data):
        raise PermissionError("Taraz book is not bound to its registered company")
    if not data.is_dir() or data.is_symlink():
        raise PermissionError("Existing registered Taraz book required")
    if not (data / "standalone-accounting.sqlite3").is_file():
        raise RuntimeError("Taraz accounting book is missing; refusing an empty replacement")
    # The legacy Taraz session lock and the common company lock both remain
    # active, preventing a second standalone session on this same ledger.
    guard = CompanySessionGuard(data).acquire()
    lock_file = data / ".taraz-session.lock"
    try:
        if (lock_file.is_symlink() or (lock_file.exists() and
                getattr(lock_file.lstat(), "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))):
            raise PermissionError("Linked Taraz session lock refused")
        lock = open(lock_file, "a+b")
    except BaseException:
        guard.release()
        raise
    previous_data_env = os.environ.get("TARAZ_DATA_DIR")
    lock_acquired = False
    try:
        lock.seek(0)
        if lock.read(1) == b"":
            lock.seek(0); lock.write(b"0"); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            lock_acquired = True
        except OSError:
            raise RuntimeError("Taraz is already running using this accounting book")
        os.environ["TARAZ_DATA_DIR"] = str(data)
        from standalone_accounting_auto_backup import AutomaticStandaloneBackups
        backups = AutomaticStandaloneBackups(
            data, plaintext_acknowledged=True,
            preserve_existing=is_pending_legacy)
        prepare_offline_accounting_on_launch(api, backups)
        backups.start()
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        server = serve_accounting_page(root / "dist")
        Thread(target=server.serve_forever, daemon=True).start()
        import webview
        # PyWebView's EdgeChromium backend cancels every browser download
        # while ALLOW_DOWNLOADS is False (its default). The accounting UI
        # generates an in-memory PDF and requests a normal anchor download;
        # enabling this path invokes the OS SaveFileDialog, which requires
        # an explicit destination choice. It does not write financial data.
        webview.settings['ALLOW_DOWNLOADS'] = True
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
        # An explicit private-QA native close intent must still travel through
        # the exact same financial JS confirmation and verified backup gate.
        from taraz_private_qa_close import (
            install_private_close_witness, record_private_close_exit)
        private_close_enabled = install_private_close_witness(window, api, data, close_gate)
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
                        exit_backed_up = True
                record_private_close_exit(private_close_enabled, close_gate,
                                          backup_completed=exit_backed_up)
            finally:
                server.shutdown(); server.server_close()
    finally:
        try:
            if lock_acquired:
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
        finally:
            lock.close()
            guard.release()
            if previous_data_env is None:
                os.environ.pop("TARAZ_DATA_DIR", None)
            else:
                os.environ["TARAZ_DATA_DIR"] = previous_data_env


def run():
    """Native production login precedes any accounting initialization/backup.

    An unregistered legacy profile stays untouched; no implicit local admin,
    company creation, or finance DB migration occurs in this entrypoint.
    """
    root = taraz_data_root()
    # An explicitly published NEW empty profile can use its bound Windows
    # identity without a redundant company/password dialog. Old/legacy books
    # NEVER enter this path and receive no fabricated administrator.
    from taraz_fresh_windows_workspace import MARKER as FRESH_MARKER
    registry_marker = root / "companies.json"
    fresh_marked = False
    if registry_marker.is_file():
        from standalone_accounting_company_registry import StandaloneCompanyRegistry
        existing = StandaloneCompanyRegistry(root).list_companies()
        if len(existing) == 1:
            book = StandaloneCompanyRegistry(root).company_data_directory(existing[0]["id"])
            fresh_marked = (book / FRESH_MARKER).is_file()
    if fresh_marked:
        from taraz_fresh_windows_workspace import open_fresh_company
        api, identity, token = open_fresh_company(root)
        try:
            return _run_authenticated_taraz_api(api)
        finally:
            identity.logout(token)
    # The v1.0.4 ledger may now have a new *ownerless* company workspace.
    # User confirmation happens once, in a native Tk dialog, before any admin
    # identity exists. No password or declaration enters the WebView bridge.
    if ((root / 'companies.json').is_file() and
            (root / 'legacy-enrollment-intent.json').is_file()):
        from taraz_legacy_ownership_enrollment import pending_company
        if pending_company(root) is not None:
            from taraz_legacy_enrollment_dialog import prompt_pending_legacy_enrollment
            if not prompt_pending_legacy_enrollment(root):
                return
    # An unclaimed historical book is a viewer-only mode, not an admin bypass.
    # The marker must already exist from a separately verified migration.
    if (root / 'legacy-workspace.json').is_file() and not (root / 'companies.json').exists():
        session = open_identity_pending_legacy_workspace(root)
    else:
        session = open_authenticated_taraz_company(root)
    if session is None:  # User cancelled the native selection/login UI.
        return
    api, identity, token = session
    try:
        return _run_authenticated_taraz_api(api)
    finally:
        identity.logout(token)

if __name__ == "__main__":
    run()
