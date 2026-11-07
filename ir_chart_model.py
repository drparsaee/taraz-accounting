"""Pure, immutable *candidate* Iranian chart-of-accounts domain.

This module validates structure and posting references only. It does not
create journal entries, change parties, infer account balances, or migrate the
current flat TOMAN ledger. Callers must supply authoritative company, party,
project, and task ownership checks at the eventual host integration boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_CODE = {"KOL": re.compile(r"[0-9]{2}\Z", re.ASCII),
         "MOEIN": re.compile(r"[0-9]{4}\Z", re.ASCII),
         "TAFSILI": re.compile(r"[0-9]{6}\Z", re.ASCII)}
_DETAIL = re.compile(r"FD-[0-9]{6}\Z", re.ASCII)
_COST = re.compile(r"CC-[0-9]{4}\Z", re.ASCII)
_KIND = frozenset({"asset", "liability", "equity", "revenue", "expense"})
_LEVELS = ("KOL", "MOEIN", "TAFSILI")


def _identifier(value: str, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label}: invalid identifier")
    return value


def _name(value: str, label: str) -> str:
    if (type(value) is not str or not value or value != value.strip()
            or len(value) > 200 or
            any(not (ch.isprintable() or ch == "\u200c") for ch in value)):
        raise ValueError(f"{label}: invalid name")
    return value


def _flag(value: bool, label: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{label}: expected boolean")


def _code(value: str, level: str) -> None:
    if type(level) is not str or level not in _LEVELS:
        raise ValueError("Unknown chart account level")
    if type(value) is not str or not _CODE[level].fullmatch(value):
        raise ValueError(f"{level}: expected ASCII digits of length {2 * (_LEVELS.index(level) + 1)}")
    if value[-2:] == "00":
        raise ValueError("Each chart code segment must be 01..99")


@dataclass(frozen=True, slots=True)
class ChartAccount:
    company_id: str
    code: str
    level: str
    parent_code: str | None
    name: str
    kind: str
    active: bool = True
    accountable: bool = False
    archived: bool = False
    frozen: bool = False
    has_postings: bool = False
    requires_detail: bool = False
    requires_cost_center: bool = False
    requires_job: bool = False

    def __post_init__(self) -> None:
        _identifier(self.company_id, "company_id")
        _code(self.code, self.level)
        _name(self.name, "account name")
        if type(self.kind) is not str or self.kind not in _KIND:
            raise ValueError("Invalid account kind")
        for name in ("active", "accountable", "archived", "frozen", "has_postings",
                     "requires_detail", "requires_cost_center", "requires_job"):
            _flag(getattr(self, name), name)
        if self.level == "KOL":
            if self.parent_code is not None or self.accountable:
                raise ValueError("KOL is a root group, never postable")
        else:
            if type(self.parent_code) is not str:
                raise ValueError("MOEIN/TAFSILI require an explicit parent")
            parent_level = _LEVELS[_LEVELS.index(self.level) - 1]
            _code(self.parent_code, parent_level)
            if not self.code.startswith(self.parent_code):
                raise ValueError("Child code must begin with its immediate parent code")
        if self.level == "TAFSILI" and not self.accountable:
            raise ValueError("Terminal TAFSILI accounts must be accountable")
        if self.archived and self.active:
            raise ValueError("Archived account cannot be active")
        if self.has_postings and (self.archived or not self.active):
            raise ValueError("Account with postings cannot be archived or inactive")
        if not self.accountable and (self.requires_detail or self.requires_cost_center
                                     or self.requires_job):
            raise ValueError("Only accountable accounts can require analytic dimensions")


@dataclass(frozen=True, slots=True)
class FloatingDetail:
    company_id: str
    code: str
    name: str
    kind: str = "GENERAL"  # PARTY is an external party link, not a copied party.
    active: bool = True

    def __post_init__(self) -> None:
        _identifier(self.company_id, "company_id")
        if type(self.code) is not str or not _DETAIL.fullmatch(self.code):
            raise ValueError("Floating detail code must be FD- plus six ASCII digits")
        _name(self.name, "floating detail name")
        if self.kind not in ("GENERAL", "PARTY"):
            raise ValueError("Unknown floating detail kind")
        _flag(self.active, "detail active")


@dataclass(frozen=True, slots=True)
class DetailBinding:
    company_id: str
    account_code: str
    detail_code: str

    def __post_init__(self) -> None:
        _identifier(self.company_id, "company_id")
        if type(self.account_code) is not str or (
                not any(regex.fullmatch(self.account_code) for regex in _CODE.values())):
            raise ValueError("Invalid detail-binding account code")
        if type(self.detail_code) is not str or not _DETAIL.fullmatch(self.detail_code):
            raise ValueError("Invalid bound floating detail code")


@dataclass(frozen=True, slots=True)
class PartyDetailLink:
    company_id: str
    party_id: str
    detail_code: str

    def __post_init__(self) -> None:
        _identifier(self.company_id, "company_id")
        _identifier(self.party_id, "party_id")
        if type(self.detail_code) is not str or not _DETAIL.fullmatch(self.detail_code):
            raise ValueError("Invalid party floating detail code")


@dataclass(frozen=True, slots=True)
class CostCenter:
    company_id: str
    code: str
    project_id: str
    name: str
    active: bool = True

    def __post_init__(self) -> None:
        _identifier(self.company_id, "company_id")
        if type(self.code) is not str or not _COST.fullmatch(self.code):
            raise ValueError("Cost center code must be CC- plus four ASCII digits")
        _identifier(self.project_id, "project_id")
        _name(self.name, "cost center name")
        _flag(self.active, "cost center active")


@dataclass(frozen=True, slots=True)
class JobReference:
    company_id: str
    job_id: str
    project_id: str
    task_id: str = ""
    cost_center_code: str = ""
    active: bool = True

    def __post_init__(self) -> None:
        _identifier(self.company_id, "company_id")
        _identifier(self.job_id, "job_id")
        _identifier(self.project_id, "project_id")
        if type(self.task_id) is not str:
            raise ValueError("Invalid job task_id type")
        if self.task_id:
            _identifier(self.task_id, "task_id")
        if type(self.cost_center_code) is not str or (
                self.cost_center_code and not _COST.fullmatch(self.cost_center_code)):
            raise ValueError("Invalid job cost center code")
        _flag(self.active, "job active")


@dataclass(frozen=True, slots=True)
class LegacyAccountLink:
    company_id: str
    legacy_account_id: str
    account_code: str
    legacy_kind: str

    def __post_init__(self) -> None:
        _identifier(self.company_id, "company_id")
        _identifier(self.legacy_account_id, "legacy_account_id")
        if type(self.account_code) is not str:
            raise ValueError("Invalid chart account code")
        if type(self.legacy_kind) is not str or self.legacy_kind not in _KIND:
            raise ValueError("Legacy account kind must be explicit and valid")


@dataclass(frozen=True, slots=True)
class PostingReference:
    company_id: str
    account_code: str
    detail_code: str = ""
    party_id: str = ""
    project_id: str = ""
    cost_center_code: str = ""
    job_id: str = ""
    task_id: str = ""

    def __post_init__(self) -> None:
        _identifier(self.company_id, "company_id")
        if type(self.account_code) is not str:
            raise ValueError("Invalid account code")
        for key in ("party_id", "project_id", "job_id", "task_id"):
            val = getattr(self, key)
            if type(val) is not str:
                raise ValueError(f"Invalid {key} type")
            if val:
                _identifier(val, key)
        if type(self.detail_code) is not str or (
                self.detail_code and not _DETAIL.fullmatch(self.detail_code)):
            raise ValueError("Invalid posting detail")
        if type(self.cost_center_code) is not str or (
                self.cost_center_code and not _COST.fullmatch(self.cost_center_code)):
            raise ValueError("Invalid posting cost center")


def _members(values: tuple, item_type: type, name: str, key) -> tuple:
    if type(values) is not tuple or any(type(v) is not item_type for v in values):
        raise ValueError(f"{name}: expected immutable tuple of {item_type.__name__}")
    return tuple(sorted(values, key=key))


@dataclass(frozen=True, slots=True)
class ChartSnapshot:
    company_id: str
    accounts: tuple[ChartAccount, ...] = ()
    details: tuple[FloatingDetail, ...] = ()
    bindings: tuple[DetailBinding, ...] = ()
    party_links: tuple[PartyDetailLink, ...] = ()
    project_ids: tuple[str, ...] = ()
    cost_centers: tuple[CostCenter, ...] = ()
    jobs: tuple[JobReference, ...] = ()
    legacy_links: tuple[LegacyAccountLink, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.company_id, "company_id")
        for field, typ, key in (
            ("accounts", ChartAccount, lambda x: x.code),
            ("details", FloatingDetail, lambda x: x.code),
            ("bindings", DetailBinding, lambda x: (x.account_code, x.detail_code)),
            ("party_links", PartyDetailLink, lambda x: (x.party_id, x.detail_code)),
            ("cost_centers", CostCenter, lambda x: x.code),
            ("jobs", JobReference, lambda x: x.job_id),
            ("legacy_links", LegacyAccountLink, lambda x: x.legacy_account_id),
        ):
            object.__setattr__(self, field, _members(getattr(self, field), typ, field, key))
        if type(self.project_ids) is not tuple:
            raise ValueError("project_ids: expected immutable tuple")
        for project_id in self.project_ids:
            _identifier(project_id, "project_id")
        object.__setattr__(self, "project_ids", tuple(sorted(self.project_ids)))
        validate_chart(self)


def _unique(rows, label: str, key):
    seen = set()
    for row in rows:
        identity = key(row)
        if identity in seen:
            raise ValueError(f"{label}: duplicate {identity}")
        seen.add(identity)


def validate_chart(chart: ChartSnapshot) -> bool:
    """Deterministic structural validation with no IO or mutable global state."""
    if type(chart) is not ChartSnapshot:
        raise ValueError("Expected ChartSnapshot")
    _identifier(chart.company_id, "company_id")
    for field in ("accounts", "details", "bindings", "party_links",
                  "cost_centers", "jobs", "legacy_links"):
        for row in getattr(chart, field):
            if row.company_id != chart.company_id:
                raise ValueError(f"{field}: cross-company reference")
    _unique(chart.accounts, "accounts", lambda a: a.code)
    _unique(chart.details, "details", lambda a: a.code)
    _unique(chart.project_ids, "project_ids", lambda p: p)
    _unique(chart.cost_centers, "cost_centers", lambda c: c.code)
    _unique(chart.jobs, "jobs", lambda j: j.job_id)
    _unique(chart.bindings, "bindings", lambda b: (b.account_code, b.detail_code))
    _unique(chart.party_links, "party links", lambda p: p.party_id)
    _unique(chart.party_links, "party links", lambda p: p.detail_code)
    _unique(chart.legacy_links, "legacy links", lambda a: a.legacy_account_id)
    _unique(chart.legacy_links, "legacy links", lambda a: a.account_code)

    accounts = {a.code: a for a in chart.accounts}
    details = {d.code: d for d in chart.details}
    cost_centers = {c.code: c for c in chart.cost_centers}
    projects = set(chart.project_ids)
    children = {code: [] for code in accounts}
    for acc in chart.accounts:
        if acc.parent_code is not None:
            parent = accounts.get(acc.parent_code)
            if parent is None or _LEVELS.index(parent.level) + 1 != _LEVELS.index(acc.level):
                raise ValueError(f"Account {acc.code}: missing immediate parent")
            if acc.kind != parent.kind:
                raise ValueError(f"Account {acc.code}: account kind differs from parent")
            if acc.active and not parent.active:
                raise ValueError(f"Account {acc.code}: active under inactive parent")
            children[parent.code].append(acc.code)
    for acc in chart.accounts:
        if acc.accountable and children[acc.code]:
            raise ValueError(f"Account {acc.code}: group accounts cannot be accountable")
        if acc.archived and children[acc.code]:
            raise ValueError(f"Account {acc.code}: archived group still has children")
        if acc.has_postings and not acc.accountable:
            raise ValueError(f"Account {acc.code}: posted group is invalid")

    for detail in chart.details:
        if detail.kind == "PARTY" and not any(p.detail_code == detail.code
                                               for p in chart.party_links):
            raise ValueError(f"Floating detail {detail.code}: party link required")
    for link in chart.party_links:
        _identifier(link.party_id, "party_id")
        detail = details.get(link.detail_code)
        if detail is None or detail.kind != "PARTY":
            raise ValueError("Party link requires a PARTY floating detail")
    for binding in chart.bindings:
        acc = accounts.get(binding.account_code)
        if acc is None or not acc.accountable or acc.archived:
            raise ValueError("Floating detail binding requires an unarchived accountable account")
        if binding.detail_code not in details:
            raise ValueError("Floating detail binding references an unknown detail")
    for center in chart.cost_centers:
        if center.project_id not in projects:
            raise ValueError("Cost center requires a project in this company scope")
    for job in chart.jobs:
        if job.project_id not in projects:
            raise ValueError("Job requires a project in this company scope")
        if job.cost_center_code:
            center = cost_centers.get(job.cost_center_code)
            if center is None or center.project_id != job.project_id:
                raise ValueError("Job cost center must belong to the same project")
    for link in chart.legacy_links:
        acc = accounts.get(link.account_code)
        if acc is None or not acc.accountable or acc.archived:
            raise ValueError("Legacy mapping requires an unarchived accountable leaf")
        if acc.kind != link.legacy_kind:
            raise ValueError("Legacy kind differs from chart account kind")
    return True


def validate_chart_transition(
    before: ChartSnapshot,
    after: ChartSnapshot,
    *,
    verified_new_posting_codes: frozenset[str] = frozenset(),
) -> bool:
    """Cross-snapshot policy; cannot be replaced by validating only the new chart."""
    validate_chart(before)
    validate_chart(after)
    if before.company_id != after.company_id:
        raise ValueError("Cannot change chart company")
    if type(verified_new_posting_codes) is not frozenset:
        raise ValueError("Verified posting codes must be a frozen set")
    old = {a.code: a for a in before.accounts}
    new = {a.code: a for a in after.accounts}
    for code, account in old.items():
        if code not in new:
            raise ValueError(f"Account {code}: deletion requires a separate migration")
        if (account.frozen or account.archived or account.has_postings) and new[code] != account:
            raise ValueError(f"Account {code}: frozen/archived/posted account is immutable")
        if (not account.has_postings and new[code].has_postings
                and code not in verified_new_posting_codes):
            raise ValueError(f"Account {code}: new posted state needs host verification")
        if new[code].parent_code != account.parent_code or new[code].level != account.level:
            raise ValueError(f"Account {code}: hierarchy cannot be reassigned")
        if account.has_postings and new[code].kind != account.kind:
            raise ValueError(f"Account {code}: kind of posted account is immutable")
    old_legacy = {l.legacy_account_id: l for l in before.legacy_links}
    new_legacy = {l.legacy_account_id: l for l in after.legacy_links}
    for legacy_id, row in old_legacy.items():
        if new_legacy.get(legacy_id) != row:
            raise ValueError(f"Legacy account {legacy_id}: mapping cannot be rewritten")
    old_parties = {row.party_id: row for row in before.party_links}
    new_parties = {row.party_id: row for row in after.party_links}
    for party_id, row in old_parties.items():
        if new_parties.get(party_id) != row:
            raise ValueError(f"Party {party_id}: floating detail link cannot be rewritten")
    new_details = {row.code: row for row in after.details}
    for detail in before.details:
        updated = new_details.get(detail.code)
        if updated is None or updated.kind != detail.kind:
            raise ValueError(f"Floating detail {detail.code}: deletion or kind change denied")
    if not set(before.project_ids).issubset(after.project_ids):
        raise ValueError("Removing project references requires separate migration")
    new_centers = {row.code: row for row in after.cost_centers}
    for center in before.cost_centers:
        updated = new_centers.get(center.code)
        if updated is None or updated.project_id != center.project_id:
            raise ValueError(f"Cost center {center.code}: project reassignment denied")
    new_jobs = {row.job_id: row for row in after.jobs}
    for job in before.jobs:
        updated = new_jobs.get(job.job_id)
        if (updated is None or updated.project_id != job.project_id
                or updated.task_id != job.task_id
                or updated.cost_center_code != job.cost_center_code):
            raise ValueError(f"Job {job.job_id}: reference reassignment denied")
    for code, account in old.items():
        if account.has_postings:
            old_bindings = tuple(b for b in before.bindings if b.account_code == code)
            new_bindings = tuple(b for b in after.bindings if b.account_code == code)
            if old_bindings != new_bindings:
                raise ValueError(f"Account {code}: used detail bindings cannot change")
    return True


def add_account(chart: ChartSnapshot, account: ChartAccount) -> ChartSnapshot:
    if account.company_id != chart.company_id:
        raise ValueError("Cross-company account creation")
    if account.has_postings:
        raise ValueError("A new chart account cannot claim prior posted journals")
    candidate = replace(chart, accounts=chart.accounts + (account,))
    validate_chart_transition(chart, candidate)
    return candidate


def revise_account(chart: ChartSnapshot, account: ChartAccount) -> ChartSnapshot:
    if account.company_id != chart.company_id:
        raise ValueError("Cross-company account update")
    previous = next((a for a in chart.accounts if a.code == account.code), None)
    if previous is None:
        raise ValueError("Unknown account: use add_account")
    if previous.frozen or previous.archived or previous.has_postings:
        raise ValueError("Frozen, archived and posted accounts cannot be modified")
    if account.has_postings != previous.has_postings:
        raise ValueError("Only lock_posted_account may acknowledge a host-verified posting")
    candidate = replace(chart, accounts=tuple(
        account if a.code == account.code else a for a in chart.accounts))
    validate_chart_transition(chart, candidate)
    return candidate


def lock_posted_account(chart: ChartSnapshot, code: str) -> ChartSnapshot:
    """Record host-verified prior posting usage; irreversible domain lock.

    This does NOT create a posting. The host must derive usage from an actual
    committed journal before invoking it and atomically persist the snapshot.
    """
    previous = next((a for a in chart.accounts if a.code == code), None)
    if previous is None or not previous.accountable or not previous.active or previous.archived:
        raise ValueError("Only an active accountable account can have postings")
    if previous.has_postings:
        return chart
    candidate = replace(chart, accounts=tuple(
        replace(a, has_postings=True) if a.code == code else a for a in chart.accounts))
    validate_chart_transition(
        chart, candidate, verified_new_posting_codes=frozenset({code}))
    return candidate


def resolve_legacy_account(chart: ChartSnapshot, company_id: str,
                           legacy_account_id: str) -> str:
    """Explicit verified map from existing flat host account IDs to chart codes."""
    if company_id != chart.company_id:
        raise ValueError("Cross-company legacy account lookup")
    _identifier(legacy_account_id, "legacy_account_id")
    link = next((row for row in chart.legacy_links
                 if row.legacy_account_id == legacy_account_id), None)
    if link is None:
        raise ValueError("Unmapped legacy account; never infer chart codes")
    return link.account_code


def reverse_legacy_account(chart: ChartSnapshot, company_id: str,
                           chart_account_code: str) -> str:
    """Explicit inverse of the one-to-one legacy adapter; no inferred fallback."""
    if company_id != chart.company_id:
        raise ValueError("Cross-company reverse legacy account lookup")
    if type(chart_account_code) is not str:
        raise ValueError("Invalid chart account code")
    link = next((row for row in chart.legacy_links
                 if row.account_code == chart_account_code), None)
    if link is None:
        raise ValueError("Chart account has no verified legacy mapping")
    return link.legacy_account_id


def validate_external_references(
    chart: ChartSnapshot,
    *,
    verified_party_ids: frozenset[str],
    verified_project_ids: frozenset[str],
    verified_task_scopes: frozenset[tuple[str, str]],
) -> bool:
    """Host-gated full-snapshot ownership preflight, before durable saving.

    Passed sets must be established by an authoritative, company-scoped host.
    Unlike a posting preflight, this examines even currently unused mappings.
    """
    validate_chart(chart)
    for label, value in (("party", verified_party_ids),
                         ("project", verified_project_ids),
                         ("task", verified_task_scopes)):
        if type(value) is not frozenset:
            raise ValueError(f"Verified {label} scope must be a frozen set")
    for party in chart.party_links:
        if party.party_id not in verified_party_ids:
            raise ValueError(f"Party {party.party_id}: not verified for this company")
    for project in chart.project_ids:
        if project not in verified_project_ids:
            raise ValueError(f"Project {project}: not verified for this company")
    for job in chart.jobs:
        if job.task_id and (job.project_id, job.task_id) not in verified_task_scopes:
            raise ValueError(f"Job {job.job_id}: task/project ownership unverified")
    return True


def validate_posting_reference(
    chart: ChartSnapshot,
    reference: PostingReference,
    *,
    verified_party_ids: frozenset[str] | None = None,
    verified_project_ids: frozenset[str] | None = None,
    verified_task_scopes: frozenset[tuple[str, str]] | None = None,
) -> PostingReference:
    """Pure preflight only. Does not authorize or post a journal entry.

    Host passes identity/ownership verified identifiers for referenced entities,
    not user-supplied lists. Exact company-scope checks precede lookup.
    """
    if type(reference) is not PostingReference or reference.company_id != chart.company_id:
        raise ValueError("Cross-company or malformed posting reference")
    for title, ids in (("party", verified_party_ids),
                       ("project", verified_project_ids),
                       ("task", verified_task_scopes)):
        if ids is not None and type(ids) is not frozenset:
            raise ValueError(f"Host-verified {title} scope must be a frozen set")
    accounts = {a.code: a for a in chart.accounts}
    account = accounts.get(reference.account_code)
    if account is None or not account.active or account.archived or account.frozen:
        raise ValueError("Posting account is missing or unavailable")
    if not account.accountable or any(a.parent_code == account.code for a in chart.accounts):
        raise ValueError("Cannot post to a KOL/MOEIN group")

    details = {d.code: d for d in chart.details}
    if account.requires_detail and not reference.detail_code:
        raise ValueError("Posting account requires a floating detail")
    if reference.detail_code:
        detail = details.get(reference.detail_code)
        if (detail is None or not detail.active or
                DetailBinding(chart.company_id, account.code, detail.code) not in chart.bindings):
            raise ValueError("Detail is not active or allowed for this account")
        if detail.kind == "PARTY" and not reference.party_id:
            raise ValueError("PARTY detail requires a party reference")
    if reference.party_id:
        if verified_party_ids is None or reference.party_id not in verified_party_ids:
            raise ValueError("Party identity/ownership has not been verified by host")
        mapped = next((p for p in chart.party_links
                       if p.party_id == reference.party_id), None)
        if reference.detail_code and (mapped is None or
                                      mapped.detail_code != reference.detail_code):
            raise ValueError("Party does not own the selected floating detail")

    if account.requires_cost_center and not reference.cost_center_code:
        raise ValueError("Account requires a cost center")
    if account.requires_job and not reference.job_id:
        raise ValueError("Account requires a job")
    if (reference.cost_center_code or reference.job_id or reference.task_id) and not reference.project_id:
        raise ValueError("Cost center, job and task require explicit project")
    if reference.project_id:
        if (reference.project_id not in chart.project_ids or
                verified_project_ids is None or
                reference.project_id not in verified_project_ids):
            raise ValueError("Project identity/ownership has not been verified by host")
    centers = {c.code: c for c in chart.cost_centers}
    if reference.cost_center_code:
        center = centers.get(reference.cost_center_code)
        if center is None or not center.active or center.project_id != reference.project_id:
            raise ValueError("Inactive, missing or cross-project cost center")
    jobs = {j.job_id: j for j in chart.jobs}
    if reference.job_id:
        job = jobs.get(reference.job_id)
        if job is None or not job.active or job.project_id != reference.project_id:
            raise ValueError("Inactive, missing or cross-project job")
        if job.cost_center_code and reference.cost_center_code != job.cost_center_code:
            raise ValueError("Posting must use job's assigned cost center")
        if job.task_id and reference.task_id != job.task_id:
            raise ValueError("Posting task must match the job's assigned task")
    if reference.task_id:
        if (verified_task_scopes is None or
                (reference.project_id, reference.task_id) not in verified_task_scopes):
            raise ValueError("Task project ownership has not been verified by host")
        if not reference.job_id:
            raise ValueError("Task requires a registered job reference")
    return reference


__all__ = ["ChartAccount", "FloatingDetail", "DetailBinding", "PartyDetailLink",
           "CostCenter", "JobReference", "LegacyAccountLink", "PostingReference",
           "ChartSnapshot", "validate_chart", "validate_chart_transition",
           "add_account", "revise_account", "lock_posted_account",
           "resolve_legacy_account", "reverse_legacy_account",
           "validate_external_references",
           "validate_posting_reference"]
