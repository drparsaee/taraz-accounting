"""Pure, fail-closed commercial-source preflight across legacy and RIAL V2.

Only an authenticated host may assemble CommercialEvidence from AUTHORITATIVE
locked ledger/project/document snapshots. Dataclasses are not credentials.
This module does not issue, post, commit, reserve, authenticate or persist.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from ir_company_registry import (
    CompanyRegistry, RegistryError, resolve_project_company, replay_registry,
    stable_financial_source_id,
)
from ir_journal_v2 import (
    JournalSource, JournalState, PostedJournal, replay_journal,
)
from money_policy import MAX_RIAL

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_LEGACY = frozenset({"finance.sales", "accounting.invoice", "accounting.bill"})
_SIDE = frozenset({"legacy", "rial_v2"})
_KINDS = {"sale": "sale", "sales": "sale", "purchase": "purchase"}
_CANON = frozenset({"sale", "purchase"})
MAX_LEGACY = 20_000
MAX_BINDINGS = 20_000


class CommercialSourceError(ValueError):
    """Missing or contradictory authoritative business identity/evidence."""


class CommercialSourceConflict(CommercialSourceError):
    """Already posted under another event ID, or divergent legacy/V2 mirror."""


def _id(value: object, name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise CommercialSourceError("Invalid " + name)
    return value


def normalize_commercial_kind(value: str) -> str:
    """Only these authoritative application aliases are supported."""
    if type(value) is not str or value not in _KINDS:
        raise CommercialSourceError("Unknown or ambiguous commercial kind")
    return _KINDS[value]


def _rial(value: object, name: str) -> int:
    if type(value) is not int or not 0 < value <= MAX_RIAL:
        raise CommercialSourceError("Invalid positive integer RIAL " + name)
    return value


@dataclass(frozen=True, slots=True)
class CommercialIdentity:
    company_id: str
    project_id: str
    kind: str
    document_id: str

    def __post_init__(self):
        _id(self.company_id, "company")
        _id(self.project_id, "project")
        _id(self.document_id, "document")
        object.__setattr__(self, "kind", normalize_commercial_kind(self.kind))

    @property
    def registry_source_id(self) -> str:
        return stable_financial_source_id(
            self.company_id, self.project_id, self.kind, self.document_id)


@dataclass(frozen=True, slots=True)
class LegacyCommercialPosting:
    """Only *issued* host-reconstructed TOMAN invoice/bill issue, not a draft.

    finance.sales maps finance.py ledger invoice.issue, accounting.invoice
    maps accounting_core invoice.issue, accounting.bill maps bill.issue.
    """
    identity: CommercialIdentity
    ledger: str
    issue_event_id: str
    amount_toman: int
    party_id: str = ""

    def __post_init__(self):
        if type(self.identity) is not CommercialIdentity:
            raise CommercialSourceError("Exact legacy commercial identity required")
        if type(self.ledger) is not str or self.ledger not in _LEGACY:
            raise CommercialSourceError("Unsupported legacy ledger family")
        if (self.identity.kind == "sale") != (
                self.ledger in ("finance.sales", "accounting.invoice")):
            raise CommercialSourceError("Legacy ledger kind and document disagree")
        _id(self.issue_event_id, "legacy issue event")
        if (type(self.amount_toman) is not int or self.amount_toman <= 0
                or self.amount_toman > MAX_RIAL // 10):
            raise CommercialSourceError("Legacy amount must be exact positive TOMAN")
        _id(self.party_id, "legacy party", optional=True)

    @property
    def amount_rial(self) -> int:
        return self.amount_toman * 10


@dataclass(frozen=True, slots=True)
class CommercialV2Binding:
    """Host-attested reverse mapping: source key -> exact issued document.

    V2 source can be a card/task, a bill/invoice ID or co.hash. Never guess.
    """
    identity: CommercialIdentity
    source: JournalSource
    party_id: str = ""

    def __post_init__(self):
        if type(self.identity) is not CommercialIdentity or type(self.source) is not JournalSource:
            raise CommercialSourceError("Structured commercial V2 source binding required")
        if self.source.project_id != self.identity.project_id:
            raise CommercialSourceError("V2 source/project binding mismatch")
        _id(self.party_id, "V2 binding party", optional=True)
        if (self.source.source_id.startswith("co.") and (
                self.source.kind != "independent" or
                self.source.source_id != self.identity.registry_source_id)):
            raise CommercialSourceError("Forged/foreign registry co.hash binding")


@dataclass(frozen=True, slots=True)
class MirrorAuthorization:
    """Host-derived proof of a SINGLE intentional paired TOMAN/RIAL issuance.

    Must be reconstructed from host's locked issue transition, NOT caller text.
    """
    identity: CommercialIdentity
    legacy_ledger: str
    legacy_event_id: str
    rial_event_id: str
    rial_source: JournalSource
    amount_rial: int
    party_id: str = ""

    def __post_init__(self):
        if type(self.identity) is not CommercialIdentity:
            raise CommercialSourceError("Mirror lacks canonical commercial identity")
        if type(self.legacy_ledger) is not str or self.legacy_ledger not in _LEGACY:
            raise CommercialSourceError("Invalid mirrored legacy ledger")
        if (self.identity.kind == "sale") != (
                self.legacy_ledger in ("finance.sales", "accounting.invoice")):
            raise CommercialSourceError("Mirror direction/type mismatch")
        _id(self.legacy_event_id, "mirror legacy event")
        _id(self.rial_event_id, "mirror RIAL event")
        if type(self.rial_source) is not JournalSource or (
                self.rial_source.project_id != self.identity.project_id):
            raise CommercialSourceError("Mirror requires exact V2 source/project")
        _rial(self.amount_rial, "mirrored amount")
        _id(self.party_id, "mirror party", optional=True)


@dataclass(frozen=True, slots=True)
class CommercialCandidate:
    identity: CommercialIdentity
    ledger: str
    event_id: str
    amount_rial: int
    source: JournalSource | None = None
    party_id: str = ""

    def __post_init__(self):
        if type(self.identity) is not CommercialIdentity:
            raise CommercialSourceError("Candidate requires canonical identity")
        if type(self.ledger) is not str or self.ledger not in _LEGACY | {"rial_v2"}:
            raise CommercialSourceError("Unknown commercial destination ledger")
        allowed = ({"accounting.bill", "rial_v2"} if self.identity.kind == "purchase"
                   else {"finance.sales", "accounting.invoice", "rial_v2"})
        if self.ledger not in allowed:
            raise CommercialSourceError("Commercial kind/destination mismatch")
        _id(self.event_id, "candidate event")
        _rial(self.amount_rial, "candidate amount")
        _id(self.party_id, "candidate party", optional=True)
        if self.ledger == "rial_v2":
            if type(self.source) is not JournalSource:
                raise CommercialSourceError("RIAL V2 candidate needs exact source")
            if self.source.project_id != self.identity.project_id:
                raise CommercialSourceError("Candidate V2 source/project mismatch")
            if self.source.source_id.startswith("co.") and (
                    self.source.kind != "independent" or
                    self.source.source_id != self.identity.registry_source_id):
                raise CommercialSourceError("Candidate supplied mismatched co.hash")
        elif self.source is not None:
            raise CommercialSourceError("Legacy candidate must not carry V2 source")


@dataclass(frozen=True, slots=True)
class CommercialEvidence:
    """Trusted host-resolved evidence, NOT a client-constructable proof token.

    All V2 originals in the supplied JournalState(s) must be classified by a
    verified commercial binding or an explicit verified noncommercial source.
    """
    authenticated_actor_id: str
    authenticated: bool
    registry: CompanyRegistry
    verified_project_company_pairs: frozenset[tuple[str, str]]
    legacy_postings: tuple[LegacyCommercialPosting, ...]
    journals: tuple[JournalState, ...]
    v2_bindings: tuple[CommercialV2Binding, ...]
    noncommercial_v2_sources: frozenset[tuple[str, JournalSource]] = frozenset()
    mirrors: tuple[MirrorAuthorization, ...] = ()

    def __post_init__(self):
        _id(self.authenticated_actor_id, "host actor")
        if type(self.authenticated) is not bool or type(self.registry) is not CompanyRegistry:
            raise CommercialSourceError("Missing authenticated registry snapshot")
        if type(self.verified_project_company_pairs) is not frozenset:
            raise CommercialSourceError("Missing frozen host project/company mapping")
        if type(self.legacy_postings) is not tuple or len(self.legacy_postings) > MAX_LEGACY:
            raise CommercialSourceError("Invalid legacy evidence tuple")
        if type(self.journals) is not tuple or len(self.journals) > 100:
            raise CommercialSourceError("Invalid journal snapshot tuple")
        if type(self.v2_bindings) is not tuple or len(self.v2_bindings) > MAX_BINDINGS:
            raise CommercialSourceError("Invalid immutable V2 bindings")
        if type(self.noncommercial_v2_sources) is not frozenset:
            raise CommercialSourceError("Noncommercial exclusions must be host verified")
        if type(self.mirrors) is not tuple or len(self.mirrors) > MAX_LEGACY:
            raise CommercialSourceError("Mirror authorizations must be immutable tuple")
        if any(type(mirror) is not MirrorAuthorization for mirror in self.mirrors):
            raise CommercialSourceError("Mirror authority type unsupported")
        for p in self.verified_project_company_pairs:
            if type(p) is not tuple or len(p) != 2:
                raise CommercialSourceError("Malformed host project/company proof")
            _id(p[0], "verified project")
            _id(p[1], "verified company")


@dataclass(frozen=True, slots=True)
class CommercialDecision:
    """NEW, RETRY or PAIRED_MIRROR. Only a proposal, never a transaction."""
    disposition: str
    identity: CommercialIdentity
    registry_source_id: str
    host_actor_id: str


@dataclass(frozen=True, slots=True)
class _Posting:
    identity: CommercialIdentity
    ledger: str
    event_id: str
    amount_rial: int
    party_id: str
    source: JournalSource | None


def _verified_identity(identity: CommercialIdentity, evidence: CommercialEvidence,
                       cache: dict[str, str]) -> None:
    if type(identity) is not CommercialIdentity:
        raise CommercialSourceError("Malformed source identity")
    if identity.project_id not in cache:
        try:
            cache[identity.project_id] = resolve_project_company(
                evidence.registry, identity.project_id,
                verified_project_company_pairs=evidence.verified_project_company_pairs)
        except RegistryError as exc:
            raise CommercialSourceError("Unverified or ambiguous legal project owner") from exc
    if cache[identity.project_id] != identity.company_id:
        raise CommercialSourceError("Project belongs to a different legal company")


def _scan(evidence: CommercialEvidence) -> list[_Posting]:
    if type(evidence) is not CommercialEvidence or not evidence.authenticated:
        raise PermissionError("Verified authenticated host context required")
    replay_registry(evidence.registry)
    owner_cache: dict[str, str] = {}
    rows: list[_Posting] = []
    for original in evidence.legacy_postings:
        if type(original) is not LegacyCommercialPosting:
            raise CommercialSourceError("Malformed legacy issue evidence")
        _verified_identity(original.identity, evidence, owner_cache)
        rows.append(_Posting(original.identity, original.ledger,
                             original.issue_event_id, original.amount_rial,
                             original.party_id, None))
    bindings: dict[tuple[str, JournalSource], CommercialV2Binding] = {}
    identity_bindings: dict[CommercialIdentity, CommercialV2Binding] = {}
    for binding in evidence.v2_bindings:
        if type(binding) is not CommercialV2Binding:
            raise CommercialSourceError("Malformed V2 binding")
        _verified_identity(binding.identity, evidence, owner_cache)
        key = (binding.identity.company_id, binding.source)
        if key in bindings or binding.identity in identity_bindings:
            raise CommercialSourceConflict("Ambiguous V2 source/identity mapping")
        bindings[key] = binding
        identity_bindings[binding.identity] = binding
    seen_ignored = set()
    for excluded in evidence.noncommercial_v2_sources:
        if (type(excluded) is not tuple or len(excluded) != 2 or
                type(excluded[1]) is not JournalSource):
            raise CommercialSourceError("Invalid noncommercial V2 source exemption")
        _id(excluded[0], "excluded company")
        if excluded in bindings:
            raise CommercialSourceError("Source cannot be commercial and exempt")
        seen_ignored.add(excluded)
    seen_journal_companies = set()
    for journal in evidence.journals:
        if type(journal) is not JournalState:
            raise CommercialSourceError("Original immutable RIAL JournalState required")
        replay_journal(journal)
        if journal.company_id in seen_journal_companies:
            raise CommercialSourceError("Ambiguous duplicate company journal snapshots")
        seen_journal_companies.add(journal.company_id)
        for posting in journal.events:
            if type(posting) is not PostedJournal:
                continue
            source_key = (journal.company_id, posting.source)
            binding = bindings.get(source_key)
            if binding is None:
                if source_key in seen_ignored:
                    continue
                raise CommercialSourceError("V2 original has no host-verified commercial classification")
            if posting.reversal_of:
                # Reversal does not erase its commercial origin or authorize re-issue.
                continue
            if (posting.company_id != binding.identity.company_id or
                    posting.source.project_id != binding.identity.project_id or
                    any(line.reference.company_id != posting.company_id or
                        line.reference.project_id != binding.identity.project_id
                        for line in posting.lines)):
                raise CommercialSourceError("Cross-company/project V2 commercial event")
            debit = sum(line.debit_rial for line in posting.lines)
            credit = sum(line.credit_rial for line in posting.lines)
            _rial(debit, "V2 debit amount")
            if debit != credit:
                raise CommercialSourceError("Unbalanced historical V2 commercial posting")
            rows.append(_Posting(binding.identity, "rial_v2", posting.event_id,
                                 debit, binding.party_id, posting.source))
    for binding in evidence.v2_bindings:
        if binding.identity.company_id not in seen_journal_companies:
            raise CommercialSourceError("Commercial V2 binding lacks company journal")
    for company, source in seen_ignored:
        if company not in seen_journal_companies:
            raise CommercialSourceError("Unverified noncommercial journal company")
    # Reject aliases for the same document across project boundaries as well as
    # multiple issued postings under alternate event IDs in the same ledger.
    document_owners: dict[tuple[str, str, str], str] = {}
    unique_postings = set()
    by_identity: dict[CommercialIdentity, dict[str, _Posting]] = {}
    for row in rows:
        owner_key = (row.identity.company_id, row.identity.kind,
                     row.identity.document_id)
        previous_owner = document_owners.setdefault(owner_key, row.identity.project_id)
        if previous_owner != row.identity.project_id:
            raise CommercialSourceConflict("Same company/document used by multiple projects")
        event_key = (row.identity.company_id, row.ledger, row.event_id)
        if event_key in unique_postings:
            raise CommercialSourceConflict("Reused issue event ID")
        unique_postings.add(event_key)
        sides = by_identity.setdefault(row.identity, {})
        if row.ledger == "rial_v2":
            slot = "rial_v2"
        else:
            slot = "legacy"
        if slot in sides:
            raise CommercialSourceConflict("Same commercial source posted twice on one side")
        sides[slot] = row
    # A company may contain an already-posted verified mirror, but must have
    # the same immutable document, amount, optional party, and ONE exact proof.
    proofs: dict[CommercialIdentity, MirrorAuthorization] = {}
    for mirror in evidence.mirrors:
        _verified_identity(mirror.identity, evidence, owner_cache)
        if mirror.identity in proofs:
            raise CommercialSourceConflict("Duplicate/ambiguous mirror authorization")
        proofs[mirror.identity] = mirror
    for identity, pair in by_identity.items():
        if len(pair) == 2:
            mirror = proofs.get(identity)
            if mirror is None:
                raise CommercialSourceConflict("Existing unverified legacy/RIAL dual posting")
            _match_mirror(pair["legacy"], pair["rial_v2"], mirror)
    return rows


def _match_mirror(legacy: _Posting, rial: _Posting, proof: MirrorAuthorization) -> None:
    if (legacy.identity != proof.identity or rial.identity != proof.identity or
            legacy.ledger != proof.legacy_ledger or
            legacy.event_id != proof.legacy_event_id or
            rial.event_id != proof.rial_event_id or
            rial.source != proof.rial_source or
            legacy.amount_rial != rial.amount_rial or
            legacy.amount_rial != proof.amount_rial or
            legacy.party_id != rial.party_id or
            legacy.party_id != proof.party_id):
        raise CommercialSourceConflict("Legacy/RIAL mirror identities or values diverge")


def _as_posting(candidate: CommercialCandidate) -> _Posting:
    return _Posting(candidate.identity, candidate.ledger, candidate.event_id,
                    candidate.amount_rial, candidate.party_id, candidate.source)


def preflight_commercial_source(
    evidence: CommercialEvidence, candidate: CommercialCandidate,
) -> CommercialDecision:
    """Return NEW/RETRY/PAIRED_MIRROR, or reject. No writes or reservations.

    The host must recheck beneath its finance+registry+journal write lock.
    Candidate is host-reconstructed from an issued document/command, NOT UI.
    """
    if type(candidate) is not CommercialCandidate:
        raise CommercialSourceError("Structured commercial candidate required")
    rows = _scan(evidence)
    verified_owners: dict[str, str] = {}
    _verified_identity(candidate.identity, evidence, verified_owners)
    if candidate.ledger == "rial_v2":
        matches = [binding for binding in evidence.v2_bindings
                   if binding.identity == candidate.identity]
        if (len(matches) != 1 or matches[0].source != candidate.source or
                matches[0].party_id != candidate.party_id):
            raise CommercialSourceError("Candidate V2 source not bound to verified document")
    # Canonical doc IDs are single-project identities inside a company,
    # including when conflicting postings reside in the other ledger.
    for row in rows:
        if (row.identity.company_id == candidate.identity.company_id
                and row.identity.kind == candidate.identity.kind
                and row.identity.document_id == candidate.identity.document_id
                and row.identity.project_id != candidate.identity.project_id):
            raise CommercialSourceConflict("Issued document moved to another project")
        if (row.identity.company_id == candidate.identity.company_id
                and row.ledger == candidate.ledger
                and row.event_id == candidate.event_id
                and row.identity != candidate.identity):
            raise CommercialSourceConflict("Event ID already belongs to another source")
    current = _as_posting(candidate)
    existing = [row for row in rows if row.identity == current.identity]
    side = lambda row: "rial_v2" if row.ledger == "rial_v2" else "legacy"
    same_side = [row for row in existing if side(row) == side(current)]
    other_side = [row for row in existing if side(row) != side(current)]
    if same_side:
        past = same_side[0]
        if past != current:
            raise CommercialSourceConflict("Commercial source already posted under alternate event ID/amount")
        disposition = "RETRY"
    elif other_side:
        matching = [m for m in evidence.mirrors if m.identity == current.identity]
        if len(matching) != 1:
            raise CommercialSourceConflict("Unpaired legacy/RIAL duplicate source")
        legacy, rial = ((current, other_side[0]) if side(current) == "legacy"
                        else (other_side[0], current))
        _match_mirror(legacy, rial, matching[0])
        disposition = "PAIRED_MIRROR"
    else:
        disposition = "NEW"
    # A registry posted lock is a committed posting claim, not an extra ledger.
    # If no matching V2 evidence exists, refuse silently orphaned/replayed locks.
    projection = replay_registry(evidence.registry)
    locks = [lock for lock in projection.posted_locks
             if lock.company_id == current.identity.company_id and
             lock.business_source_id == current.identity.registry_source_id]
    if locks and not any(row.ledger == "rial_v2" for row in existing):
        raise CommercialSourceConflict(
            "Registry claims committed posting without matching V2 journal evidence")
    return CommercialDecision(
        disposition, current.identity, current.identity.registry_source_id,
        evidence.authenticated_actor_id)
