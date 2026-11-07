"""Pure immutable, explicitly mapped multi-company registry for Madar RIAL V2.

Untrusted clients cannot create authority: VerifiedRegistryAuthority and project
ownership proofs MUST be constructed by an authenticated host from its current
locked records, never from UI input. No DB/host/storage effects occur here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
import re

from money_policy import CompanyMoneyPolicy, snapshot_sha256
from ir_chart_model import ChartSnapshot, validate_chart
from ir_journal_v2 import JournalSource, JournalState, PostedJournal, VerifiedScopes, replay_journal

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z", re.ASCII)
_ROLES = frozenset({"finance_admin", "finance_issuer", "finance_reader"})
_ACTIONS = frozenset({
    "REGISTER", "LEGAL_UPDATE", "YEAR_ADD", "YEAR_REPLACE",
    "PROJECT_ASSIGN", "BANK_ADD", "CASH_ADD", "PARTY_ADD",
    "GRANT", "REVOKE", "COMPANY_DISPLAY", "USER_DISPLAY",
    "LEGACY_LINK", "POSTED_LOCK",
})
_PERMISSION = {
    "finance_admin": frozenset({"read", "issue", "admin"}),
    "finance_issuer": frozenset({"read", "issue"}),
    "finance_reader": frozenset({"read"}),
}
MAX_EVENTS = 20_000
_GENESIS = "0" * 64


class RegistryError(ValueError):
    """Invalid company, reference, source, period or registry state."""


class RegistryConflict(RegistryError):
    """Stale CAS, duplicate source, locked record or ambiguous project."""


def _id(value: str, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise RegistryError("Invalid " + label)
    return value


def _date(value: str) -> str:
    if type(value) is not str or _DATE.fullmatch(value) is None:
        raise RegistryError("Expected Gregorian ISO YYYY-MM-DD date")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise RegistryError("Invalid Gregorian calendar date") from exc
    return value


def _str(value: str, label: str, *, optional: bool = False, limit: int = 200) -> str:
    if type(value) is not str or len(value) > limit or (
            not optional and not value.strip()) or value != value.strip() or any(
                ord(char) < 32 or ord(char) == 127 for char in value):
        raise RegistryError("Invalid " + label)
    return value


def _unit(value: str) -> str:
    if type(value) is not str or value not in ("RIAL", "TOMAN"):
        raise RegistryError("Presentation must be RIAL or TOMAN")
    return value


@dataclass(frozen=True, slots=True)
class LegalEntity:
    """Optional Iranian references are caller supplied; never auto-filled."""
    legal_name: str
    national_id: str = ""
    registration_number: str = ""
    economic_code: str = ""
    tax_id: str = ""
    registered_address: str = ""

    def __post_init__(self):
        _str(self.legal_name, "legal name")
        for field in ("national_id", "registration_number", "economic_code", "tax_id"):
            value = _str(getattr(self, field), field, optional=True, limit=64)
            if value and re.fullmatch(r"[0-9A-Za-z/-]{1,64}", value, re.ASCII) is None:
                raise RegistryError("Legal reference has unsupported characters: " + field)
        _str(self.registered_address, "registered address", optional=True, limit=400)


@dataclass(frozen=True, slots=True)
class FiscalYear:
    company_id: str
    fiscal_year_id: str
    start_date: str
    end_date: str

    def __post_init__(self):
        _id(self.company_id, "fiscal-year company")
        _id(self.fiscal_year_id, "fiscal-year ID")
        _date(self.start_date)
        _date(self.end_date)
        if self.end_date < self.start_date:
            raise RegistryError("Fiscal year ends before it begins")


@dataclass(frozen=True, slots=True)
class RegisteredCompany:
    company_id: str
    legal: LegalEntity
    fiscal_years: tuple[FiscalYear, ...]
    presentation_unit: str = "RIAL"
    currency: str = "RIAL"

    def __post_init__(self):
        _id(self.company_id, "company")
        if type(self.legal) is not LegalEntity or self.currency != "RIAL":
            raise RegistryError("Registered legal entity and canonical RIAL required")
        _unit(self.presentation_unit)
        if type(self.fiscal_years) is not tuple or not self.fiscal_years:
            raise RegistryError("Company must declare fiscal years explicitly")
        if len(self.fiscal_years) > 1000:
            raise RegistryError("Too many fiscal years")
        years = sorted(self.fiscal_years, key=lambda y: (y.start_date, y.fiscal_year_id))
        ids = set()
        end = ""
        for year in years:
            if type(year) is not FiscalYear or year.company_id != self.company_id:
                raise RegistryError("Foreign/malformed fiscal year")
            if year.fiscal_year_id in ids or year.start_date <= end:
                raise RegistryError("Duplicate/overlapping company fiscal years")
            ids.add(year.fiscal_year_id)
            end = year.end_date
        object.__setattr__(self, "fiscal_years", tuple(years))


@dataclass(frozen=True, slots=True)
class ProjectAssignment:
    company_id: str
    project_id: str

    def __post_init__(self):
        _id(self.company_id, "project company")
        _id(self.project_id, "project")


@dataclass(frozen=True, slots=True)
class CompanyBankRef:
    company_id: str
    bank_id: str
    account_id: str

    def __post_init__(self):
        _id(self.company_id, "bank company")
        _id(self.bank_id, "bank")
        _id(self.account_id, "bank account")


@dataclass(frozen=True, slots=True)
class CompanyCashRef:
    company_id: str
    cashbox_id: str

    def __post_init__(self):
        _id(self.company_id, "cashbox company")
        _id(self.cashbox_id, "cashbox")


@dataclass(frozen=True, slots=True)
class CompanyPartyRef:
    company_id: str
    party_id: str

    def __post_init__(self):
        _id(self.company_id, "party company")
        _id(self.party_id, "party")


@dataclass(frozen=True, slots=True)
class FinanceGrant:
    company_id: str
    principal_id: str
    role: str

    def __post_init__(self):
        _id(self.company_id, "grant company")
        _id(self.principal_id, "principal")
        if type(self.role) is not str or self.role not in _ROLES:
            raise RegistryError("Invalid finance grant role")


@dataclass(frozen=True, slots=True)
class UserPresentation:
    company_id: str
    principal_id: str
    unit: str

    def __post_init__(self):
        _id(self.company_id, "presentation company")
        _id(self.principal_id, "presentation principal")
        _unit(self.unit)


@dataclass(frozen=True, slots=True)
class LegacyProjectLink:
    """Explicit migration identity, never an inferred company for a flat project."""
    company_id: str
    project_id: str
    legacy_project_id: str

    def __post_init__(self):
        _id(self.company_id, "legacy company")
        _id(self.project_id, "linked project")
        _id(self.legacy_project_id, "legacy project")


@dataclass(frozen=True, slots=True)
class PostedLock:
    company_id: str
    project_id: str
    fiscal_year_id: str
    business_source_id: str

    def __post_init__(self):
        for name in ("company_id", "project_id", "fiscal_year_id", "business_source_id"):
            _id(getattr(self, name), name)


_PAYLOAD = (
    RegisteredCompany, LegalEntity, FiscalYear, ProjectAssignment, CompanyBankRef,
    CompanyCashRef, CompanyPartyRef, FinanceGrant, UserPresentation,
    LegacyProjectLink, PostedLock,
)


@dataclass(frozen=True, slots=True)
class RegistryCommand:
    action: str
    company_id: str
    actor_id: str
    source_id: str
    payload: object

    def __post_init__(self):
        if type(self.action) is not str or self.action not in _ACTIONS:
            raise RegistryError("Unknown registry action")
        _id(self.company_id, "command company")
        _id(self.actor_id, "actor")
        _id(self.source_id, "business source")
        types = {
            "REGISTER": RegisteredCompany,
            "LEGAL_UPDATE": LegalEntity,
            "YEAR_ADD": FiscalYear,
            "YEAR_REPLACE": FiscalYear,
            "PROJECT_ASSIGN": ProjectAssignment,
            "BANK_ADD": CompanyBankRef,
            "CASH_ADD": CompanyCashRef,
            "PARTY_ADD": CompanyPartyRef,
            "GRANT": FinanceGrant,
            "REVOKE": FinanceGrant,
            "COMPANY_DISPLAY": str,
            "USER_DISPLAY": UserPresentation,
            "LEGACY_LINK": LegacyProjectLink,
            "POSTED_LOCK": PostedLock,
        }
        if type(self.payload) is not types[self.action]:
            raise RegistryError("Malformed registry command payload")
        if self.action == "COMPANY_DISPLAY":
            _unit(self.payload)
        elif self.action != "LEGAL_UPDATE" and self.payload.company_id != self.company_id:
            raise RegistryError("Registry command/payload company mismatch")


@dataclass(frozen=True, slots=True)
class RegistryEvent:
    command: RegistryCommand
    digest: str
    previous_hash: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class CompanyRegistry:
    events: tuple[RegistryEvent, ...] = ()

    @property
    def revision(self) -> str:
        return snapshot_sha256({
            "schema": "IR-COMPANY-REGISTRY-1",
            "count": len(self.events),
            "head": self.events[-1].event_hash if self.events else _GENESIS,
        })


@dataclass(frozen=True, slots=True)
class RegistryProjection:
    revision: str
    companies: tuple[RegisteredCompany, ...]
    assignments: tuple[ProjectAssignment, ...]
    banks: tuple[CompanyBankRef, ...]
    cashboxes: tuple[CompanyCashRef, ...]
    parties: tuple[CompanyPartyRef, ...]
    grants: tuple[FinanceGrant, ...]
    presentations: tuple[UserPresentation, ...]
    legacy_links: tuple[LegacyProjectLink, ...]
    posted_locks: tuple[PostedLock, ...]


@dataclass(frozen=True, slots=True)
class ScopedCompanyView:
    """Company-only records; never disclose other legal entities via this reader."""
    company: RegisteredCompany
    projects: tuple[ProjectAssignment, ...]
    banks: tuple[CompanyBankRef, ...]
    cashboxes: tuple[CompanyCashRef, ...]
    parties: tuple[CompanyPartyRef, ...]
    grants: tuple[FinanceGrant, ...]
    legacy_links: tuple[LegacyProjectLink, ...]
    registry_revision: str


@dataclass(frozen=True, slots=True)
class VerifiedRegistryAuthority:
    """Must originate in authenticated host, NOT in client or registry storage.

    The project ownership proof is a two-column host mapping, not a wildcard.
    Posting locks originate from a verified already committed financial source.
    """
    actor_id: str
    authenticated: bool
    registration_right: bool = False
    project_company_pairs: frozenset[tuple[str, str]] = frozenset()
    bank_accounts: frozenset[tuple[str, str, str]] = frozenset()
    cashboxes: frozenset[tuple[str, str]] = frozenset()
    parties: frozenset[tuple[str, str]] = frozenset()
    verified_postings: frozenset[tuple[str, str, str, str]] = frozenset()
    verified_legacy_links: frozenset[tuple[str, str, str]] = frozenset()

    def __post_init__(self):
        _id(self.actor_id, "authenticated actor")
        if type(self.authenticated) is not bool or type(self.registration_right) is not bool:
            raise RegistryError("Authority flags must be bool")
        for name, width in (
            ("project_company_pairs", 2), ("bank_accounts", 3),
            ("cashboxes", 2), ("parties", 2), ("verified_postings", 4),
            ("verified_legacy_links", 3),
        ):
            values = getattr(self, name)
            if type(values) is not frozenset:
                raise RegistryError("Host scope must be immutable frozenset")
            for row in values:
                if type(row) is not tuple or len(row) != width:
                    raise RegistryError("Invalid verified host tuple")
                for element in row:
                    _id(element, name)


def _jsonable(value):
    """Convert frozen tuple-containing records to canonical JSON-safe structures."""
    if type(value) is tuple:
        return [_jsonable(item) for item in value]
    if type(value) is list:
        return [_jsonable(item) for item in value]
    if type(value) is dict:
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _digest(command: RegistryCommand) -> str:
    return snapshot_sha256({"action": command.action, "company": command.company_id,
                            "actor": command.actor_id, "source": command.source_id,
                            "payload": _jsonable(asdict(command.payload)) if type(command.payload) in _PAYLOAD
                            else command.payload})


def _event_hash(command: RegistryCommand, previous: str) -> str:
    return snapshot_sha256({"commandDigest": _digest(command),
                            "previousHash": previous})


def _reconstruct(registry: CompanyRegistry) -> RegistryProjection:
    if type(registry) is not CompanyRegistry or type(registry.events) is not tuple:
        raise RegistryError("Malformed registry")
    if len(registry.events) > MAX_EVENTS:
        raise RegistryError("Registry history exceeds bounded limit")
    companies = {}
    projects = {}
    banks = {}
    cashboxes = {}
    parties = {}
    grants = {}
    preferences = {}
    legacy = {}
    posted = {}
    seen_sources = {}
    prev_hash = _GENESIS
    for event in registry.events:
        if type(event) is not RegistryEvent or type(event.command) is not RegistryCommand:
            raise RegistryError("Malformed registry audit event")
        cmd = event.command
        if (event.previous_hash != prev_hash or event.digest != _digest(cmd)
                or event.event_hash != _event_hash(cmd, prev_hash)):
            raise RegistryError("Corrupt registry digest/hash chain")
        source_key = (cmd.company_id, cmd.source_id)
        if source_key in seen_sources:
            raise RegistryConflict("Business source reused in registry history")
        seen_sources[source_key] = event.digest
        company = companies.get(cmd.company_id)
        act, payload = cmd.action, cmd.payload
        if act == "REGISTER":
            if company is not None:
                raise RegistryConflict("Registered company cannot be recreated")
            companies[cmd.company_id] = payload
            grants[(cmd.company_id, cmd.actor_id)] = FinanceGrant(
                cmd.company_id, cmd.actor_id, "finance_admin")
        else:
            if company is None:
                raise RegistryError("Unregistered company")
            current_grant = grants.get((cmd.company_id, cmd.actor_id))
            if current_grant is None:
                raise PermissionError("Actor has no company membership")
            if act == "USER_DISPLAY":
                if (payload.principal_id != cmd.actor_id or
                        current_grant.role not in _ROLES):
                    raise PermissionError("Users may change only their own presentation")
            elif current_grant.role != "finance_admin":
                raise PermissionError("Company finance administrator permission required")
            if act == "LEGAL_UPDATE":
                if any(lock.company_id == cmd.company_id for lock in posted.values()):
                    raise RegistryConflict("Legal entity locked by posted GL")
                companies[cmd.company_id] = replace(company, legal=payload)
            elif act in ("YEAR_ADD", "YEAR_REPLACE"):
                years = {item.fiscal_year_id: item for item in company.fiscal_years}
                if act == "YEAR_ADD" and payload.fiscal_year_id in years:
                    raise RegistryConflict("Fiscal year already registered")
                if act == "YEAR_REPLACE" and payload.fiscal_year_id not in years:
                    raise RegistryConflict("Cannot replace unknown fiscal year")
                if act == "YEAR_REPLACE" and any(
                        lock.company_id == cmd.company_id for lock in posted.values()):
                    raise RegistryConflict("Fiscal-year amendment blocked after company GL posting")
                years[payload.fiscal_year_id] = payload
                companies[cmd.company_id] = replace(
                    company, fiscal_years=tuple(years.values()))
            elif act == "PROJECT_ASSIGN":
                if payload.project_id in projects:
                    raise RegistryConflict("Project already assigned to a company")
                projects[payload.project_id] = payload
            elif act == "BANK_ADD":
                key = (cmd.company_id, payload.bank_id, payload.account_id)
                if key in banks:
                    raise RegistryConflict("Duplicate company bank account")
                banks[key] = payload
            elif act == "CASH_ADD":
                key = (cmd.company_id, payload.cashbox_id)
                if key in cashboxes:
                    raise RegistryConflict("Duplicate company cashbox")
                cashboxes[key] = payload
            elif act == "PARTY_ADD":
                key = (cmd.company_id, payload.party_id)
                if key in parties:
                    raise RegistryConflict("Duplicate company party")
                parties[key] = payload
            elif act == "GRANT":
                key = (cmd.company_id, payload.principal_id)
                if key in grants:
                    raise RegistryConflict("Change existing grant only via revoke")
                grants[key] = payload
            elif act == "REVOKE":
                key = (cmd.company_id, payload.principal_id)
                previous = grants.get(key)
                if previous is None or previous.role != payload.role:
                    raise RegistryConflict("Revoke must identify exact existing role")
                if previous.role == "finance_admin" and sum(
                        g.company_id == cmd.company_id and g.role == "finance_admin"
                        for g in grants.values()) <= 1:
                    raise RegistryConflict("Cannot revoke final finance administrator")
                del grants[key]
                preferences.pop(key, None)
            elif act == "COMPANY_DISPLAY":
                companies[cmd.company_id] = replace(company, presentation_unit=payload)
            elif act == "USER_DISPLAY":
                preferences[(cmd.company_id, payload.principal_id)] = payload
            elif act == "LEGACY_LINK":
                key = payload.legacy_project_id
                if key in legacy:
                    raise RegistryConflict("Legacy project already mapped")
                if projects.get(payload.project_id) != ProjectAssignment(
                        cmd.company_id, payload.project_id):
                    raise RegistryError("Legacy link requires exact assigned project")
                legacy[key] = payload
            elif act == "POSTED_LOCK":
                if projects.get(payload.project_id) != ProjectAssignment(
                        cmd.company_id, payload.project_id):
                    raise RegistryError("Posted project/company has no explicit mapping")
                if payload.fiscal_year_id not in {
                        year.fiscal_year_id for year in company.fiscal_years}:
                    raise RegistryError("Posted fiscal year missing")
                key = (cmd.company_id, payload.business_source_id)
                if key in posted:
                    raise RegistryConflict("Business posting lock already recorded")
                posted[key] = payload
            else:
                raise RegistryError("Unsupported registry action")
        prev_hash = event.event_hash
    def rows(mapping, key):
        return tuple(sorted(mapping.values(), key=key))
    return RegistryProjection(
        registry.revision,
        rows(companies, lambda v: v.company_id),
        rows(projects, lambda v: v.project_id),
        rows(banks, lambda v: (v.company_id, v.bank_id, v.account_id)),
        rows(cashboxes, lambda v: (v.company_id, v.cashbox_id)),
        rows(parties, lambda v: (v.company_id, v.party_id)),
        rows(grants, lambda v: (v.company_id, v.principal_id)),
        rows(preferences, lambda v: (v.company_id, v.principal_id)),
        rows(legacy, lambda v: v.legacy_project_id),
        rows(posted, lambda v: (v.company_id, v.business_source_id)),
    )


def replay_registry(registry: CompanyRegistry) -> RegistryProjection:
    return _reconstruct(registry)


def _authority(cmd: RegistryCommand, before: RegistryProjection,
               authority: VerifiedRegistryAuthority) -> None:
    if (type(authority) is not VerifiedRegistryAuthority or not authority.authenticated
            or authority.actor_id != cmd.actor_id):
        raise PermissionError("Host-authenticated actor required")
    if cmd.action == "REGISTER":
        if not authority.registration_right:
            raise PermissionError("Host authorization required for company registration")
    elif cmd.action == "PROJECT_ASSIGN":
        owners = {owner for project, owner in authority.project_company_pairs
                  if project == cmd.payload.project_id}
        if owners != {cmd.company_id}:
            raise PermissionError("Host did not verify exact project/company owner")
    elif cmd.action == "BANK_ADD":
        if (cmd.company_id, cmd.payload.bank_id,
                cmd.payload.account_id) not in authority.bank_accounts:
            raise PermissionError("Bank account has not been verified by host")
    elif cmd.action == "CASH_ADD":
        if (cmd.company_id, cmd.payload.cashbox_id) not in authority.cashboxes:
            raise PermissionError("Cashbox not verified by host")
    elif cmd.action == "PARTY_ADD":
        if (cmd.company_id, cmd.payload.party_id) not in authority.parties:
            raise PermissionError("Party not verified by host")
    elif cmd.action == "LEGACY_LINK":
        if (cmd.company_id, cmd.payload.project_id,
                cmd.payload.legacy_project_id) not in authority.verified_legacy_links:
            raise PermissionError("Migration mapping missing host evidence")
    elif cmd.action == "POSTED_LOCK":
        if (cmd.company_id, cmd.payload.project_id, cmd.payload.fiscal_year_id,
                cmd.payload.business_source_id) not in authority.verified_postings:
            raise PermissionError("Posting lock must originate in committed host GL")


def apply_registry_command(registry: CompanyRegistry, command: RegistryCommand, *,
                           authority: VerifiedRegistryAuthority,
                           expected_revision: str) -> CompanyRegistry:
    before = replay_registry(registry)
    if type(expected_revision) is not str or _SHA.fullmatch(expected_revision) is None:
        raise RegistryError("Expected canonical SHA-256 revision")
    if before.revision != expected_revision:
        raise RegistryConflict("Stale registry CAS revision")
    if type(command) is not RegistryCommand:
        raise RegistryError("Structured immutable command required")
    _authority(command, before, authority)
    digest = _digest(command)
    for event in registry.events:
        if event.command.company_id == command.company_id and (
                event.command.source_id == command.source_id):
            if event.digest == digest:
                return registry
            raise RegistryConflict("Business source replay changed payload")
    if len(registry.events) >= MAX_EVENTS:
        raise RegistryError("Registry event limit exceeded")
    previous = registry.events[-1].event_hash if registry.events else _GENESIS
    candidate = replace(registry, events=registry.events + (
        RegistryEvent(command, digest, previous, _event_hash(command, previous)),))
    replay_registry(candidate)
    return candidate


def _company(projection: RegistryProjection, company_id: str) -> RegisteredCompany:
    _id(company_id, "company")
    company = next((c for c in projection.companies if c.company_id == company_id), None)
    if company is None:
        raise RegistryError("Unknown legal company")
    return company


def resolve_project_company(registry: CompanyRegistry, project_id: str, *,
                            verified_project_company_pairs: frozenset[tuple[str, str]]) -> str:
    """Requires BOTH immutable assignment and authoritative current host proof."""
    _id(project_id, "project")
    if type(verified_project_company_pairs) is not frozenset:
        raise RegistryError("Verified mapping must be an immutable frozenset")
    matching = [row for row in replay_registry(registry).assignments
                if row.project_id == project_id]
    proofs = [pair for pair in verified_project_company_pairs
              if type(pair) is tuple and len(pair) == 2 and pair[0] == project_id]
    if len(matching) != 1 or len(proofs) != 1 or proofs[0][1] != matching[0].company_id:
        raise RegistryError("Missing or ambiguous verified project/company assignment")
    return matching[0].company_id


def read_company_registry(registry: CompanyRegistry, *, company_id: str,
                          authority: VerifiedRegistryAuthority) -> ScopedCompanyView:
    """Authorized company-local read projection; host must keep raw registry private."""
    projection = replay_registry(registry)
    company = _company(projection, company_id)
    if (type(authority) is not VerifiedRegistryAuthority or
            authority.authenticated is not True or
            not any(grant.company_id == company_id and
                    grant.principal_id == authority.actor_id and
                    "read" in _PERMISSION[grant.role]
                    for grant in projection.grants)):
        raise PermissionError("Company registry read permission denied")
    return ScopedCompanyView(
        company=company,
        projects=tuple(item for item in projection.assignments
                       if item.company_id == company_id),
        banks=tuple(item for item in projection.banks if item.company_id == company_id),
        cashboxes=tuple(item for item in projection.cashboxes
                        if item.company_id == company_id),
        parties=tuple(item for item in projection.parties if item.company_id == company_id),
        grants=tuple(item for item in projection.grants if item.company_id == company_id),
        legacy_links=tuple(item for item in projection.legacy_links
                           if item.company_id == company_id),
        registry_revision=projection.revision,
    )


def presentation_unit(registry: CompanyRegistry, *, company_id: str,
                      principal_id: str) -> str:
    projection = replay_registry(registry)
    company = _company(projection, company_id)
    _id(principal_id, "presentation principal")
    if not any(g.company_id == company_id and g.principal_id == principal_id
               for g in projection.grants):
        raise PermissionError("Presentation access requires company finance membership")
    return next((p.unit for p in projection.presentations
                 if p.company_id == company_id and p.principal_id == principal_id),
                company.presentation_unit)


def company_money_policy(registry: CompanyRegistry, *, company_id: str,
                         principal_id: str) -> CompanyMoneyPolicy:
    return CompanyMoneyPolicy(company_id, display_unit=presentation_unit(
        registry, company_id=company_id, principal_id=principal_id))


def stable_financial_source_id(company_id: str, project_id: str, kind: str,
                               document_id: str) -> str:
    _id(company_id, "company")
    _id(project_id, "project")
    _id(document_id, "source document")
    if type(kind) is not str or kind not in ("sale", "purchase"):
        raise RegistryError("Only explicit sale/purchase source type supported")
    return "co." + snapshot_sha256({
        "domain": "madar.company.sales-purchases.1",
        "companyId": company_id, "projectId": project_id,
        "kind": kind, "documentId": document_id,
    })


@dataclass(frozen=True, slots=True)
class GLCompanyGate:
    """Read-only guard result for an authenticated host to consume, no posting."""
    company_id: str
    project_id: str
    fiscal_year_id: str
    fiscal_period_id: str
    posting_date: str
    actor_id: str
    action: str
    journal_source: JournalSource
    registry_revision: str
    journal_revision: str


def verify_sale_purchase_gl_gate(
    registry: CompanyRegistry, *, company_id: str, project_id: str,
    fiscal_year_id: str, fiscal_period_id: str, posting_date: str, actor_id: str,
    kind: str, document_id: str, authority: VerifiedRegistryAuthority,
    journal_state: JournalState, chart: ChartSnapshot, scopes: VerifiedScopes,
    party_id: str,
) -> GLCompanyGate:
    """Fail-closed preflight; a HOST must still authenticate and post atomically."""
    projection = replay_registry(registry)
    company = _company(projection, company_id)
    if (type(authority) is not VerifiedRegistryAuthority or
            not authority.authenticated or authority.actor_id != actor_id):
        raise PermissionError("Authenticated host actor required")
    if (resolve_project_company(
            registry, project_id, verified_project_company_pairs=
            authority.project_company_pairs) != company_id):
        raise RegistryError("Project belongs to another company")
    grant = next((g for g in projection.grants
                  if g.company_id == company_id and g.principal_id == actor_id), None)
    if grant is None or "issue" not in _PERMISSION[grant.role]:
        raise PermissionError("Finance issuer or administrator permission required")
    _id(fiscal_year_id, "fiscal year")
    _id(fiscal_period_id, "fiscal period")
    _id(party_id, "financial party")
    _date(posting_date)
    year = next((y for y in company.fiscal_years
                 if y.fiscal_year_id == fiscal_year_id), None)
    if year is None or not year.start_date <= posting_date <= year.end_date:
        raise RegistryError("Unknown/out-of-year fiscal posting")
    if (type(journal_state) is not JournalState or journal_state.company_id != company_id or
            type(chart) is not ChartSnapshot or chart.company_id != company_id or
            type(scopes) is not VerifiedScopes):
        raise RegistryError("Chart/journal/verified scopes must match company")
    validate_chart(chart)
    history = replay_journal(journal_state)
    period = next((p for p in journal_state.periods
                   if p.fiscal_period_id == fiscal_period_id), None)
    if (period is None or fiscal_period_id in history.closed_period_ids or
            not year.start_date <= period.start_date <= period.end_date <= year.end_date or
            not period.start_date <= posting_date <= period.end_date):
        raise RegistryError("Journal fiscal period unknown/closed/misaligned")
    if (project_id not in chart.project_ids or project_id not in scopes.project_ids or
            party_id not in scopes.party_ids or
            CompanyPartyRef(company_id, party_id) not in projection.parties):
        raise RegistryError("Unverified company project/party in GL chart/scope")
    # Validate ALL discovered references, not just the selected row, so forged
    # extra projects or parties cannot be smuggled into a company-wide scope.
    assigned_here = {item.project_id for item in projection.assignments
                     if item.company_id == company_id}
    verified_here = {project for project, owner in authority.project_company_pairs
                     if owner == company_id and sum(
                         p == project for p, _ in authority.project_company_pairs) == 1}
    projected_projects = (
        set(chart.project_ids) | set(scopes.project_ids) |
        {p for p, _ in scopes.task_scopes} |
        {p for p, _, _ in scopes.checklist_scopes} |
        {p for p, _ in scopes.independent_source_scopes if p}
    )
    if not projected_projects.issubset(assigned_here & verified_here):
        raise RegistryError("Foreign/unassigned projects in chart or verified scopes")
    company_parties = {row.party_id for row in projection.parties
                       if row.company_id == company_id}
    host_parties = {party for owner, party in authority.parties
                    if owner == company_id}
    parties_seen = set(scopes.party_ids) | {row.party_id for row in chart.party_links}
    if not parties_seen.issubset(company_parties & host_parties):
        raise RegistryError("Foreign/unregistered parties in GL chart/scopes")
    source_id = stable_financial_source_id(company_id, project_id, kind, document_id)
    source = JournalSource("independent", source_id, project_id=project_id)
    if (project_id, source_id) not in scopes.independent_source_scopes:
        raise RegistryError("Journal source must have verified project/document scope")
    if any(type(e) is PostedJournal and e.source == source for e in journal_state.events):
        raise RegistryConflict("Business source already posted in journal")
    if any(lock.company_id == company_id and lock.business_source_id == source_id
           for lock in projection.posted_locks):
        raise RegistryConflict("Registered business source has already been posted")
    return GLCompanyGate(
        company_id, project_id, fiscal_year_id, fiscal_period_id, posting_date,
        actor_id, kind, source, projection.revision, journal_state.revision,
    )
