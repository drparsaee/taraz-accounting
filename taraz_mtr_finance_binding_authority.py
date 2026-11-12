"""Manual, single-use readback of a signed Madar claim and a real Taraz journal.

This is a deliberately narrow *evidence* authority, not a finance receipt issuer.
The current Madar v2 envelope only authenticates the configured peer key and
role claim; it does not provide an independently authenticated actor identity.
Taraz has no trusted cross-application invoice-source authority or signed
official-finance-receipt protocol. Consequently even the positive result below
keeps all official-finance flags false. This code NEVER runs an accounting
command and cannot create/repair/retry an invoice or journal.

The operator must independently provision the live peer registry/configuration,
authenticated registered-company AccountingDesktopAPI, and independent private
one-time marker directory. Only a previously received signed request AND
previously registered signed query may be used; no request-provided secrets or
transport-authentication boolean are accepted here.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock
from urllib.parse import quote

from standalone_accounting_desktop import AccountingDesktopAPI
from taraz_desktop import bridge_root
from taraz_mtr_official_receipt_gate import (
    _principal, _safe_company, _snapshot, assess_official_receipt,
)
from taraz_mtr_peer_registry import PeerConfig, TarazPeerRegistry, _verify
from taraz_mtr_review_attestation_issuer import (
    _directory, _read_review, _registry_original_binding,
)
from taraz_mtr_external_actor_link import ManualExternalActorLinks

_HEX32 = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_ID = re.compile(r"[a-zA-Z0-9._-]{1,100}\Z", re.ASCII)
_JOURNAL = re.compile(r"J:[a-zA-Z0-9._-]{1,100}\Z", re.ASCII)
_ACTOR = re.compile(r"[a-zA-Z0-9._-]{1,100}\Z", re.ASCII)
_EXTERNAL_ACTOR = re.compile(r"mtr-actor-v1-[0-9a-f]{64}\Z", re.ASCII)
_SIGNED_BINDING = frozenset({
    "id", "taskId", "projectId", "sourceDigest", "companyId",
    "actorId", "invoiceId", "issueEventId", "journalId",
})
_MARKER_PREFIX = "finance-evidence-"


class FinanceBindingDenied(PermissionError):
    """No one-time evidence claim was authorized or issued."""


def _deny(reason: str):
    raise FinanceBindingDenied(reason)


def _now_utc(now: datetime | None):
    current = datetime.now(timezone.utc)
    if now is None:
        candidate = current.replace(microsecond=0)
        return candidate + (timedelta(seconds=1) if current.microsecond else timedelta())
    if (type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None
            or now.microsecond):
        _deny("trusted second-precision UTC time required")
    stamp = now.astimezone(timezone.utc)
    if abs((stamp - current).total_seconds()) > 5:
        _deny("injected test time must match current trusted UTC time")
    return stamp


def _registered_query(registry: TarazPeerRegistry, original: dict, query: dict):
    """Read durable trusted peer receipt-query intake without writing to it."""
    path = registry.path
    _directory(path.parent)
    if (not path.is_file() or path.is_symlink()
            or getattr(path, "is_junction", lambda: False)()):
        _deny("trusted peer query registry unavailable")
    uri = "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5)) as con:
        con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN")
        try:
            if con.execute("PRAGMA user_version").fetchone()[0] != 1:
                _deny("trusted peer schema changed")
            rows = con.execute(
                "SELECT org,original_id,original_sha,query_sha,actor_role "
                "FROM queries WHERE query_id=?", (query["requestId"],)
            ).fetchall()
            expected = (
                registry.config.organization_id,
                original["requestId"], original["payloadSha256"],
                query["payloadSha256"], original["actorRole"],
            )
            if len(rows) != 1 or tuple(rows[0]) != expected:
                _deny("Madar challenge not recorded by trusted peer registry")
        finally:
            if con.in_transaction:
                con.execute("ROLLBACK")


class ManualFinanceBindingAuthority:
    """Inspect only preexisting bookings, with manual one-time evidence claim."""

    def __init__(self, *, accounting_host: AccountingDesktopAPI,
                 peer_registry: TarazPeerRegistry,
                 trusted_config: PeerConfig,
                 reviewed_root: Path,
                 consumed_bindings_dir: Path,
                 external_actor_links: ManualExternalActorLinks | None = None):
        if (type(accounting_host) is not AccountingDesktopAPI
                or type(peer_registry) is not TarazPeerRegistry
                or type(trusted_config) is not PeerConfig
                or peer_registry.config is not trusted_config):
            _deny("real company host and operator-provisioned peer authority required")
        self._host = accounting_host
        self._registry = peer_registry
        self._config = trusted_config
        self._reviewed_root = _directory(reviewed_root)
        self._consumed = _directory(consumed_bindings_dir)
        if external_actor_links is not None and (
                type(external_actor_links) is not ManualExternalActorLinks
                or external_actor_links._host is not accounting_host
                or external_actor_links._registry is not peer_registry
                or external_actor_links._config is not trusted_config
                or external_actor_links._reviewed != self._reviewed_root):
            _deny("external actor link must use same verified company and peer")
        self._external_links = external_actor_links
        accounting_dir = Path(accounting_host.path).parent
        if (self._reviewed_root != _directory(bridge_root())
                or self._consumed.is_relative_to(self._reviewed_root)
                or self._reviewed_root.is_relative_to(self._consumed)
                or self._consumed.is_relative_to(accounting_dir)
                or accounting_dir.is_relative_to(self._consumed)):
            _deny("trusted bridge and independent one-time journal required")
        self._lock = RLock()

    def bind_preexisting_manual(
            self, *, signed_madar_original: bytes,
            signed_madar_query_challenge: bytes,
            madar_request_id: str, company_id: str, invoice_id: str,
            issue_event_id: str, journal_id: str, expected_revision: int,
            explicit_manual_action: bool, now: datetime | None = None,
            external_link_admin_token: str | None = None):
        """Return bounded journal evidence, never official finance success.

        Any ambiguous interruption consumes the claim once it has been minted;
        callers must inspect a previously created journal, not retry posting.
        """
        if explicit_manual_action is not True:
            _deny("explicit operator action required")
        if (type(madar_request_id) is not str or not _HEX32.fullmatch(madar_request_id)
                or type(company_id) is not str or not _HEX32.fullmatch(company_id)
                or type(invoice_id) is not str or not _ID.fullmatch(invoice_id)
                or type(issue_event_id) is not str or not _ID.fullmatch(issue_event_id)
                or type(journal_id) is not str or not _JOURNAL.fullmatch(journal_id)
                or journal_id != "J:" + issue_event_id
                or type(expected_revision) is not int or expected_revision < 1):
            _deny("invalid exact-bound request and accounting identifiers")
        stamp = _now_utc(now)
        with self._lock, self._host._lock:
            if (self._registry.config is not self._config
                    or self._reviewed_root != _directory(bridge_root())
                    or self._consumed != _directory(self._consumed)):
                _deny("operator-provisioned peer or source changed")
            identity = _safe_company(self._host, company_id)
            _principal(self._host, identity)
            authenticated_actor = identity.require_session(
                self._host._identity_token, "editor")
            original = _verify(
                signed_madar_original, config=self._config, now=stamp,
                expected_kind="request", purpose="finance_review_request")
            query = _verify(
                signed_madar_query_challenge, config=self._config, now=stamp,
                expected_kind="query", purpose="receipt_lookup")
            if (original["requestId"] != madar_request_id
                    or query["requestId"] == madar_request_id
                    or original["organizationId"] != query["organizationId"]
                    or original["senderId"] != query["senderId"]
                    or original["keyId"] != query["keyId"]
                    or original["actorRole"] != query["actorRole"]
                    or query["payload"]["originalRequestId"] != madar_request_id
                    or query["payload"]["originalPayloadSha256"] != original["payloadSha256"]):
                _deny("Madar signed request/challenge differs")
            source_raw, review_raw, source, review = _read_review(
                self._reviewed_root, madar_request_id)
            if review["state"] != "reviewed":
                _deny("only an affirmative durable manual review is eligible")
            # An invoice can be fabricated with matching sourceType/sourceId.
            # The original reviewed Madar file must itself commit to a positive
            # exact-RIAL amount; fail closed for old metadata-only proposals.
            amount_text = source.get("amountRial")
            if (type(amount_text) is not str or not amount_text.isascii()
                    or not amount_text.isdecimal() or not 1 <= len(amount_text) <= 16):
                _deny("durable Madar proposal lacks exact RIAL finance amount")
            amount_rial = int(amount_text)
            if not 0 < amount_rial <= 9007199254740991:
                _deny("invalid reviewed RIAL amount")
            requested = original["payload"]
            if type(requested) is not dict or set(requested) != _SIGNED_BINDING:
                _deny("Madar signed finance-specific binding fields unavailable")
            actor = requested["actorId"]
            if (type(actor) is not str or not _ACTOR.fullmatch(actor)
                    or original["actorRole"] not in ("admin", "editor")
                    or original["actorRole"] != authenticated_actor["role"]):
                _deny("signed actor/role has no matching live finance-editor session")
            external_actor = actor != authenticated_actor["username"]
            if external_actor:
                if (not _EXTERNAL_ACTOR.fullmatch(actor)
                        or self._external_links is None
                        or type(external_link_admin_token) is not str):
                    _deny("external Madar actor requires explicit admin-approved identity link")
                self._external_links.verify_pending(
                    signed_madar_original=signed_madar_original,
                    signed_madar_query_challenge=signed_madar_query_challenge,
                    company_id=company_id,
                    administrator_token=external_link_admin_token,
                    now=stamp,
                )
            bound = {
                "id": madar_request_id,
                "taskId": source["taskId"],
                "projectId": source["projectId"],
                "sourceDigest": hashlib.sha256(source_raw).hexdigest(),
                "companyId": company_id,
                "actorId": actor,
                "invoiceId": invoice_id,
                "issueEventId": issue_event_id,
                "journalId": journal_id,
            }
            if requested != bound:
                _deny("Madar HMAC did not bind exact company/project/actor/journal")
            _registry_original_binding(self._registry, original)
            _registered_query(self._registry, original, query)

            def readback():
                evidence = assess_official_receipt(
                    host=self._host, company_id=company_id,
                    madar_request_id=madar_request_id,
                    invoice_id=invoice_id, issue_event_id=issue_event_id,
                    journal_id=journal_id, expected_revision=expected_revision,
                    review_marker=review,
                )
                if evidence["decision"] != "PERSISTED_INVOICE_JOURNAL_OBSERVED_UNBOUND":
                    _deny("existing journal readback failed: " + evidence["decision"])
                # A signed reference to an invoice number is insufficient
                # without matching the source's exact financial amount and
                # the genuinely replayed ledger currency.
                accounts = _principal(self._host, identity)
                revision, _, view = _snapshot(self._host, accounts)
                invoice = view.get("invoices", {}).get(invoice_id)
                if (revision != expected_revision or view.get("currency") != "RIAL"
                        or type(invoice) is not dict
                        or type(invoice.get("total")) is not int
                        or invoice["total"] != amount_rial):
                    _deny("invoice amount/currency does not match signed Madar source")
                return evidence

            readback()
            if (_read_review(self._reviewed_root, madar_request_id)[:2]
                    != (source_raw, review_raw)):
                _deny("durable review mutated during evidence assessment")
            _principal(self._host, identity)
            # One request may be used for one manual binding regardless of
            # how many valid query challenges arrive. Atomic mkdir is the
            # cross-process no-clobber decision; a crash cannot authorize retry.
            marker = self._consumed / (_MARKER_PREFIX + madar_request_id)
            if os.path.lexists(marker):
                _deny("manual finance evidence request was already consumed")
            try:
                os.mkdir(marker, 0o700)
            except FileExistsError as exc:
                raise FinanceBindingDenied("concurrent manual claim already consumed") from exc
            if os.name != "nt":
                fd = os.open(self._consumed, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            if external_actor:
                # A crash or revocation after the accounting marker was minted
                # must remain denied. The actor admission is consumed once and
                # can never become an unsigned, reusable identity alias.
                self._external_links.consume_manual(
                    signed_madar_original=signed_madar_original,
                    signed_madar_query_challenge=signed_madar_query_challenge,
                    company_id=company_id,
                    administrator_token=external_link_admin_token,
                    explicit_manual_action=True, now=stamp,
                )
            # A final second verified read catches ordinary revisions after
            # the earlier snapshot; a change is an ambiguous used claim.
            readback()
            _principal(self._host, identity)
            if _read_review(self._reviewed_root, madar_request_id)[:2] != (source_raw, review_raw):
                _deny("durable review changed after one-time claim")
            return {
                "schemaVersion": 1,
                "decision": "SIGNED_BINDING_TO_EXISTING_JOURNAL_OBSERVED_NOT_OFFICIAL",
                "madarRequestId": madar_request_id,
                "companyId": company_id,
                "projectId": source["projectId"],
                "invoiceId": invoice_id,
                "journalId": journal_id,
                "ledgerRevisionObserved": expected_revision,
                "sourceAmountRial": amount_rial,
                "sourceDigest": bound["sourceDigest"],
                "madarHmacRequestAndQueryVerified": True,
                "durableReviewedSourceVerified": True,
                "currentCompanyAndRoleChecked": True,
                "persistedInvoiceJournalVerified": True,
                "oneTimeManualEvidenceConsumed": True,
                "oneTimeAdminExternalActorLinkConsumed": external_actor,
                "independentlyAuthenticatedMadarActorVerified": False,
                "trustedMadarInvoiceBindingVerified": False,
                "officialFinanceReceiptVerified": False,
                "signedTarazFinanceReceiptPresent": False,
                "financialEventCreatedByThisOperation": False,
                "safeToRetryFinancialPosting": False,
            }


__all__ = ("ManualFinanceBindingAuthority", "FinanceBindingDenied")
