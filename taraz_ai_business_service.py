"""Authenticated TARAZ AI chat facade; local rules, no model or external IO.

The ONLY finance mutation here is an explicitly confirmed invoice.create
*draft*, delegated to the production accounting API with its normal CAS,
authorization and event-ledger validation. Issuance and posting never occur.
"""
from __future__ import annotations

import re

from taraz_ai_chat_store import TarazAiChatStore, AiChatError, _valid_text
from taraz_ai_invoice_intake import invoice_preview, preview_reply

_ID = re.compile(r"^[a-f0-9]{32}$")


class AiBusinessService:
    def __init__(self, host):
        # The legacy single-user launcher fabricates a 'local' admin without
        # an authenticated session. It is not a valid identity for confidential
        # AI chat, even if the rest of the older desktop still supports it.
        if (getattr(host, "_identity_store", None) is None or
                not getattr(host, "_identity_token", None)):
            raise PermissionError("AI chat requires a verified company user session")
        host._require_authenticated("viewer")
        self.host = host
        # NEVER derive encryption entropy from a filesystem path: moving a
        # backup to an isolated restore directory would make same-user DPAPI
        # ciphertext undecipherable. A registry-verified immutable company ID
        # is mandatory. Older unregistered local launchers fail closed.
        scope = getattr(host, "company_workspace_id", "")
        if not isinstance(scope, str) or not _ID.fullmatch(scope):
            raise PermissionError("AI chat requires a registered immutable company ID")
        self.store = TarazAiChatStore(host.path.parent, tenant_id=scope, actor=host._actor)

    def list(self, query=""):
        self.host._require_authenticated()
        return self.store.list(query)

    def read(self, conversation_id):
        self.host._require_authenticated()
        return self.store.read(conversation_id)

    def command(self, request):
        if type(request) is not dict or type(request.get("action")) is not str:
            raise AiChatError("Invalid AI workspace command")
        action = request["action"]
        shapes = {
            "create": {"action", "title"},
            "send": {"action", "conversationId", "text"},
            "approve": {"action", "conversationId", "actionId", "manualConfirmation"},
            "reject": {"action", "conversationId", "actionId"},
            "reconcile": {"action", "conversationId", "actionId"},
            "delete": {"action", "conversationId"},
            "export": {"action", "conversationId"},
        }
        if action not in shapes or (
            set(request) != shapes[action] and
            not (action in {"create", "send"} and
                 set(request) == shapes[action] | {"clientRequestId"})
        ):
            raise AiChatError("Unexpected AI command arguments")
        if "clientRequestId" in request and request["clientRequestId"] is None:
            raise AiChatError("Explicit clientRequestId must be a valid cryptographic ID")
        if action in {"create", "send", "approve", "reject", "reconcile", "delete"}:
            self.host._require_authenticated("editor")
            if self.host._exit_backed_up:
                raise RuntimeError("Accounting desktop is closing")
        else:
            self.host._require_authenticated()
        if action == "create":
            return self.store.create(
                request["title"], client_request_id=request.get("clientRequestId"))
        conversation_id = request["conversationId"]
        if action == "export":
            return {"export": self.store.read(conversation_id),
                    "provider": "LOCAL_NO_EXTERNAL_TRANSFER"}
        if action == "delete":
            return self.store.delete(conversation_id)
        if action == "send":
            text = _valid_text(request["text"])
            # The raw payload is included in the digest, so reusing the key
            # for even a slightly different instruction fails closed.
            payload = {"action": "send", "conversationId": conversation_id,
                       "text": request["text"]}
            client_request_id = request.get("clientRequestId")
            if client_request_id is not None:
                # Recover a lost response BEFORE reading any accounting data;
                # the receipt includes the original exact proposal and IDs.
                previous = self.store.replay(client_request_id, payload)
                if previous is not None:
                    return previous
            # Authorization and conversation ownership both checked BEFORE
            # inspecting any source finance document.
            self.store.read(conversation_id)
            snapshot = self.host.standaloneAccountingRead()
            proposal = invoice_preview(text, snapshot)
            reply = preview_reply(proposal)
            response = {"status": proposal["status"], "proposal": proposal,
                        "conversationId": conversation_id, "modelRan": False,
                        "provider": "LOCAL_RULES_ONLY", "journalPosted": False,
                        "invoiceDraftCreated": False}
            stored = self.store.append(
                conversation_id, text, reply, proposal=proposal,
                source_revision=snapshot["revision"],
                refs=[{"kind": "invoice", "id": r["invoiceId"],
                       "sourceRevision": r["sourceRevision"]}
                      for r in proposal.get("sources", [])],
                client_request_id=client_request_id,
                request_payload=payload if client_request_id is not None else None,
                response_base=response)
            return stored
        action_id = request["actionId"]
        if not isinstance(action_id, str) or not _ID.fullmatch(action_id):
            raise AiChatError("Invalid AI action")
        pending = self.store.pending_action(conversation_id, action_id)
        if action == "reconcile":
            if (pending["approval_status"], pending["execution_status"]) != (
                    "approved", "uncertain"):
                raise AiChatError("No uncertain approved action to reconcile")
            proposal = pending["proposal"]
            if not proposal.get("ready") or proposal.get("status") != "READY_FOR_REVIEW":
                raise AiChatError("Unverifiable source proposal")
            draft_id = "AI-INV-" + action_id[:20]
            view = self.host.standaloneAccountingRead()["view"]
            saved = view.get("invoices", {}).get(draft_id)
            if saved is None:
                # A missing row is NOT proof the original write never ran;
                # return a read-only inconclusive result and never retry.
                return {"status": "UNCERTAIN_NOT_FOUND", "actionId": action_id,
                        "safeToRetry": False, "financialEventCreated": False,
                        "invoiceDraftCreated": None, "journalPosted": None}
            lines = saved.get("lines") or []
            expected = proposal.get("lines") or []
            verified = (
                saved.get("id") == draft_id
                and saved.get("partyId") == proposal.get("partyId")
                and saved.get("status") == "draft"
                and saved.get("number") is None
                and saved.get("postedEntryId") is None
                and saved.get("total") == proposal.get("total")
                and len(lines) == len(expected)
                and all(
                    isinstance(a, dict) and a.get("itemId") == b.get("itemId")
                    and a.get("quantity") == b.get("quantity")
                    and a.get("unitPrice") == b.get("unitPrice")
                    and a.get("description") == b.get("description")
                    for a, b in zip(lines, expected)
                )
            )
            if not verified:
                raise AiChatError("Existing invoice differs; independent audit required")
            self.store.complete_uncertain_action(
                conversation_id, action_id, result=draft_id)
            return {"status": "DRAFT_RECONCILED", "invoiceId": draft_id,
                    "financialEventCreated": False, "replayed": False,
                    "invoiceDraftCreated": True, "journalPosted": False}
        if action == "reject":
            return self.store.update_action(conversation_id, action_id,
                                            approval="rejected", status="rejected")
        if request["manualConfirmation"] is not True:
            raise PermissionError("User must explicitly review and confirm invoice draft")
        if pending["approval_status"] != "pending":
            raise AiChatError("Pending action was already handled")
        proposal = pending["proposal"]
        if not proposal.get("ready") or proposal.get("status") != "READY_FOR_REVIEW":
            raise PermissionError("Incomplete invoice cannot be approved")
        history = self.store.read(conversation_id)
        origin = [message["content"] for message in history["messages"]
                  if message["id"] == pending["message_id"] and message["role"] == "user"]
        if len(origin) != 1:
            raise AiChatError("Original audited request missing")
        snapshot = self.host.standaloneAccountingRead()
        if snapshot["revision"] != pending["source_revision"]:
            raise AiChatError("Accounting source revision changed; create a new proposal")
        fresh = invoice_preview(origin[0], snapshot)
        if (not fresh.get("ready") or fresh.get("partyId") != proposal.get("partyId")
            or fresh.get("lines") != proposal.get("lines")
            or fresh.get("sources") != proposal.get("sources")
            or fresh.get("total") != proposal.get("total")
            or fresh.get("documentDate") != proposal.get("documentDate")):
            raise AiChatError("Invoice sources changed; another review required")
        event_id = "ai-draft-create-" + action_id
        draft_id = "AI-INV-" + action_id[:20]
        command = {
            "type": "invoice.create", "eventId": event_id,
            "invoiceId": draft_id, "partyId": fresh["partyId"],
            "documentDate": fresh["documentDate"], "discount": 0, "tax": 0,
            "lines": [{"description": row["description"], "quantity": row["quantity"],
                       "unitPrice": row["unitPrice"], "accountId": row["accountId"],
                       "itemId": row["itemId"]} for row in fresh["lines"]],
            "note": "AI review-only: source invoice IDs " +
                    ", ".join(sorted({r["invoiceId"] for r in fresh["sources"]}))[:650],
        }
        # Record an UNCERTAIN claim first: if the app crashes at the finance
        # boundary, repeated clicks cannot perform another mutation blindly.
        self.store.update_action(conversation_id, action_id,
                                 approval="approved", status="uncertain")
        result = self.host.standaloneAccountingCommand(
            {"command": command, "expectedRevision": snapshot["revision"]})
        saved = result["view"]["invoices"].get(draft_id)
        if not saved or saved["status"] != "draft" or saved["total"] != fresh["total"]:
            raise AiChatError("Draft persistence uncertain; do not retry blindly")
        if result["view"]["journals"] != snapshot["view"]["journals"]:
            raise AiChatError("Unexpected ledger change; action requires independent audit")
        self.store.complete_uncertain_action(conversation_id, action_id, result=draft_id)
        return {"status": "DRAFT_SAVED", "invoiceId": draft_id, "total": saved["total"],
                "accountingRevision": result["revision"], "journalUnchanged": True,
                "financialEventCreated": False, "issued": False,
                "invoiceDraftCreated": True, "journalPosted": False,
                "modelRan": False}
