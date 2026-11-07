"""Standalone immutable RIAL cheque domain. No storage, GL posting or calendar conversion.

Dates are explicit ASCII YYYY-MM-DD *Jalali* dates. Hosting applications must
authorize actors, validate actual bank evidence and commit a CAS snapshot.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import re

from money_policy import require_rial_amount, snapshot_sha256

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})\Z", re.ASCII)
_SHA = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
_GENESIS = "0" * 64
_DIRECTIONS = frozenset({"RECEIVABLE", "PAYABLE"})
_ACTIONS = frozenset({
    "RECEIVE", "ISSUE", "ENDORSE", "DEPOSIT", "PRESENT", "CLEAR",
    "BOUNCE", "REDEPOSIT", "REPRESENT", "RETURN", "CANCEL", "REVERSE",
})
_SOURCES = frozenset({"invoice", "expense", "task", "purchase", "bank", "independent"})
_TERMINAL = frozenset({"CLEARED", "RETURNED", "CANCELLED"})
_REVERSIBLE = frozenset({"DEPOSIT", "PRESENT", "BOUNCE", "REDEPOSIT", "REPRESENT"})
MAX_EVENTS = 20_000
MAX_CHEQUES = 10_000
_JALALI_BREAKS = (-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
                  1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178)


class ChequeError(ValueError):
    """Invalid cheque command, corrupted history or unsupported transition."""


class ChequeConflict(ChequeError):
    """Stale revision, reused business source or conflicting external identifier."""


def _id(value: str, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ChequeError("Invalid " + field)
    return value


def _optional_id(value: str, field: str) -> str:
    if type(value) is not str:
        raise ChequeError("Invalid " + field)
    if value:
        _id(value, field)
    return value


def _jalali_leap_year(year: int) -> bool:
    """Jalaali break-year leap rule, with no conversion to Gregorian or timestamp."""
    last = _JALALI_BREAKS[0]
    for next_break in _JALALI_BREAKS[1:]:
        jump = next_break - last
        if year < next_break:
            n = year - last
            if jump - n < 6:
                n = n - jump + ((jump + 4) // 33) * 33
            return ((n + 1) % 33 - 1) % 4 == 0
        last = next_break
    raise ChequeError("Unsupported Jalali year")


def _date(value: str) -> str:
    """Canonical Jalali shape, valid month lengths and astronomical leap pattern.

    Date strings retain Jalali semantics. There is no inferred conversion into
    the journal kernel's Gregorian calendar.
    """
    if type(value) is not str:
        raise ChequeError("Jalali date must be ASCII YYYY-MM-DD")
    match = _DATE.fullmatch(value)
    if not match:
        raise ChequeError("Jalali date must be ASCII YYYY-MM-DD")
    year, month, day = map(int, match.groups())
    if not (1200 <= year <= 1600 and 1 <= month <= 12):
        raise ChequeError("Jalali year/month out of supported range")
    max_day = (31 if month <= 6 else
               30 if month <= 11 or _jalali_leap_year(year) else 29)
    if not 1 <= day <= max_day:
        raise ChequeError("Invalid Jalali calendar day")
    return value


def _text(value: str, field: str) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 300 or
            value != value.strip() or not value.strip() or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ChequeError("Invalid " + field)
    return value


def _hash(value: str, field: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ChequeError("Invalid " + field)
    return value


@dataclass(frozen=True, slots=True)
class ChequePeriod:
    company_id: str
    fiscal_period_id: str
    start_date: str
    end_date: str

    def __post_init__(self):
        _id(self.company_id, "period company")
        _id(self.fiscal_period_id, "fiscal period")
        _date(self.start_date)
        _date(self.end_date)
        if self.start_date > self.end_date:
            raise ChequeError("Fiscal period end precedes start")


@dataclass(frozen=True, slots=True)
class ChequeBusinessSource:
    kind: str
    source_id: str

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in _SOURCES:
            raise ChequeError("Invalid business source kind")
        _id(self.source_id, "business source ID")


@dataclass(frozen=True, slots=True)
class VerifiedChequeRefs:
    """Host-supplied, company-specific references; NEVER trust client-supplied sets."""

    company_id: str
    party_ids: frozenset[str]
    bank_ids: frozenset[str]
    own_bank_accounts: frozenset[tuple[str, str]]
    supplier_party_ids: frozenset[str] = frozenset()
    closed_period_ids: frozenset[str] = frozenset()

    def __post_init__(self):
        _id(self.company_id, "verified company")
        for field in ("party_ids", "bank_ids", "own_bank_accounts",
                      "supplier_party_ids", "closed_period_ids"):
            if type(getattr(self, field)) is not frozenset:
                raise ChequeError("Verified scopes must be frozensets")
        for field in ("party_ids", "bank_ids", "supplier_party_ids",
                      "closed_period_ids"):
            for value in getattr(self, field):
                _id(value, field)
        if not self.supplier_party_ids.issubset(self.party_ids):
            raise ChequeError("Suppliers must belong to verified parties")
        for ref in self.own_bank_accounts:
            if type(ref) is not tuple or len(ref) != 2:
                raise ChequeError("Bank account reference must be a pair")
            bank, account = ref
            _id(bank, "account bank")
            _id(account, "account ID")
            if bank not in self.bank_ids:
                raise ChequeError("Own account bank not verified")


@dataclass(frozen=True, slots=True)
class ChequeInstrument:
    company_id: str
    cheque_id: str
    instrument_id: str
    direction: str
    amount_rial: int
    bank_id: str
    drawer_account_id: str
    party_id: str
    maturity_date: str

    def __post_init__(self):
        for field in ("company_id", "cheque_id", "instrument_id", "bank_id",
                      "drawer_account_id", "party_id"):
            _id(getattr(self, field), field)
        if type(self.direction) is not str or self.direction not in _DIRECTIONS:
            raise ChequeError("Direction must be RECEIVABLE or PAYABLE")
        try:
            require_rial_amount(self.amount_rial, allow_zero=False)
        except ValueError as exc:
            raise ChequeError("Cheque amount must be exact positive bounded RIAL") from exc
        _date(self.maturity_date)


@dataclass(frozen=True, slots=True)
class ChequeCommand:
    event_id: str
    company_id: str
    fiscal_period_id: str
    actor_id: str
    event_date: str
    cheque_id: str
    action: str
    source: ChequeBusinessSource
    instrument: ChequeInstrument | None = None
    bank_id: str = ""
    bank_account_id: str = ""
    supplier_party_id: str = ""
    reverses_event_id: str = ""
    reason: str = ""

    def __post_init__(self):
        for field in ("event_id", "company_id", "fiscal_period_id", "actor_id", "cheque_id"):
            _id(getattr(self, field), field)
        _date(self.event_date)
        if type(self.action) is not str or self.action not in _ACTIONS:
            raise ChequeError("Unsupported cheque action")
        if type(self.source) is not ChequeBusinessSource:
            raise ChequeError("Structured business source required")
        for field in ("bank_id", "bank_account_id", "supplier_party_id",
                      "reverses_event_id"):
            _optional_id(getattr(self, field), field)
        if type(self.reason) is not str or len(self.reason) > 300:
            raise ChequeError("Invalid cheque reason")
        if self.reason:
            _text(self.reason, "reason")
        if self.action in ("RECEIVE", "ISSUE"):
            if type(self.instrument) is not ChequeInstrument:
                raise ChequeError("Cheque registration requires instrument")
        elif self.instrument is not None:
            raise ChequeError("Only registration may supply instrument")
        if self.action == "DEPOSIT" or self.action == "REDEPOSIT":
            if not self.bank_id or not self.bank_account_id:
                raise ChequeError("Deposit requires explicit verified bank/account")
        elif self.bank_id or self.bank_account_id:
            raise ChequeError("Unexpected settlement bank reference")
        if self.action == "ENDORSE":
            if not self.supplier_party_id:
                raise ChequeError("Endorsement requires supplier")
        elif self.supplier_party_id:
            raise ChequeError("Unexpected supplier reference")
        if self.action == "REVERSE":
            if not self.reverses_event_id or not self.reason:
                raise ChequeError("Reversal requires target and reason")
        elif self.reverses_event_id:
            raise ChequeError("Only reversal may reference target")
        if self.action in ("BOUNCE", "RETURN", "CANCEL") and not self.reason:
            raise ChequeError("Bounce/return/cancellation requires reason")


@dataclass(frozen=True, slots=True)
class ChequeEvent:
    command: ChequeCommand
    command_digest: str
    previous_hash: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class ChequeState:
    company_id: str
    currency: str
    calendar: str
    periods: tuple[ChequePeriod, ...]
    events: tuple[ChequeEvent, ...] = ()

    @property
    def revision(self) -> str:
        return snapshot_sha256({
            "schema": "IR-TREASURY-CHEQUE-1",
            "companyId": self.company_id, "currency": self.currency,
            "calendar": self.calendar, "periods": [asdict(p) for p in self.periods],
            "events": len(self.events),
            "head": self.events[-1].event_hash if self.events else _GENESIS,
        })


@dataclass(frozen=True, slots=True)
class ChequePosition:
    instrument: ChequeInstrument
    status: str
    last_event_id: str
    last_event_date: str
    active_event_id: str
    active_action: str
    receiving_bank_id: str = ""
    receiving_account_id: str = ""
    endorsed_supplier_id: str = ""
    cleared_date: str = ""


@dataclass(frozen=True, slots=True)
class PostingIntent:
    """Review-only journal candidate. It never writes to ir_journal_v2."""

    event_id: str
    company_id: str
    fiscal_period_id: str
    cheque_id: str
    business_source: ChequeBusinessSource
    kind: str
    amount_rial: int
    cash_effect: str  # NONE / DEBIT_BANK / CREDIT_BANK
    requires_accounting_review: bool


@dataclass(frozen=True, slots=True)
class ChequeReplay:
    revision: str
    company_id: str
    currency: str
    calendar: str
    positions: tuple[ChequePosition, ...]
    intents: tuple[PostingIntent, ...]
    reversed_event_ids: frozenset[str]


def new_cheque_state(company_id: str, periods: tuple[ChequePeriod, ...]) -> ChequeState:
    _id(company_id, "company")
    if type(periods) is not tuple or not 1 <= len(periods) <= 1000:
        raise ChequeError("Explicit non-empty fiscal period tuple required")
    ordered = tuple(sorted(periods, key=lambda p: (p.start_date, p.fiscal_period_id)))
    seen = set()
    end = ""
    for period in ordered:
        if type(period) is not ChequePeriod or period.company_id != company_id:
            raise ChequeError("Malformed or foreign fiscal period")
        if period.fiscal_period_id in seen or period.start_date <= end:
            raise ChequeError("Duplicate/overlapping fiscal period")
        end = period.end_date
        seen.add(period.fiscal_period_id)
    return ChequeState(company_id, "RIAL", "JALALI", ordered)


def _command_digest(command: ChequeCommand) -> str:
    return snapshot_sha256(asdict(command))


def _event_hash(command: ChequeCommand, previous_hash: str) -> str:
    return snapshot_sha256({
        "command": asdict(command), "commandDigest": _command_digest(command),
        "previousHash": previous_hash,
    })


def _reference_preflight(command: ChequeCommand, scopes: VerifiedChequeRefs) -> None:
    if type(scopes) is not VerifiedChequeRefs or scopes.company_id != command.company_id:
        raise ChequeError("Host verified company scope required")
    instrument = command.instrument
    if instrument is not None:
        if instrument.company_id != command.company_id or instrument.cheque_id != command.cheque_id:
            raise ChequeError("Cross-company/mismatched instrument")
        if instrument.party_id not in scopes.party_ids or instrument.bank_id not in scopes.bank_ids:
            raise ChequeError("Unverified instrument party or bank")
        if (instrument.direction == "PAYABLE" and
                (instrument.bank_id, instrument.drawer_account_id) not in scopes.own_bank_accounts):
            raise ChequeError("Payable instrument must use a verified company account")
    if command.action in ("DEPOSIT", "REDEPOSIT") and (
            command.bank_id, command.bank_account_id) not in scopes.own_bank_accounts:
        raise ChequeError("Unverified deposit account")
    if command.action == "ENDORSE" and command.supplier_party_id not in scopes.supplier_party_ids:
        raise ChequeError("Endorsement recipient is not a verified supplier")


def _transition(position: ChequePosition | None, command: ChequeCommand,
                previous_by_event: dict[str, ChequePosition | None],
                reversed_ids: set[str]) -> ChequePosition:
    action = command.action
    ins = command.instrument
    if position is None:
        if action not in ("RECEIVE", "ISSUE") or ins is None:
            raise ChequeError("Unknown cheque; register first")
        if action != ("RECEIVE" if ins.direction == "RECEIVABLE" else "ISSUE"):
            raise ChequeError("Cheque direction/registration action mismatch")
        return ChequePosition(ins, "RECEIVED" if action == "RECEIVE" else "ISSUED",
                              command.event_id, command.event_date,
                              command.event_id, action)
    if action in ("RECEIVE", "ISSUE"):
        raise ChequeConflict("Cheque already registered; instrument IDs cannot be reused")
    if command.event_date < position.last_event_date:
        raise ChequeError("Cheque transition cannot precede prior recorded action")
    old = position.status
    direction = position.instrument.direction
    if action == "REVERSE":
        if (command.reverses_event_id != position.active_event_id or
                position.active_action not in _REVERSIBLE or
                command.reverses_event_id in reversed_ids):
            raise ChequeError("Only latest active nonterminal bank movement may be reversed")
        prior = previous_by_event.get(command.reverses_event_id)
        if prior is None:
            raise ChequeError("Cannot reverse registration")
        reversed_ids.add(command.reverses_event_id)
        return replace(prior, last_event_id=command.event_id,
                       last_event_date=command.event_date)
    allowed = {
        "RECEIVED": {"ENDORSE", "DEPOSIT", "RETURN"},
        "ISSUED": {"PRESENT", "RETURN", "CANCEL"},
        "DEPOSITED": {"CLEAR", "BOUNCE"},
        "PRESENTED": {"CLEAR", "BOUNCE"},
        "BOUNCED": {"REDEPOSIT", "REPRESENT", "RETURN"},
        "ENDORSED": {"RETURN"},
    }
    if action not in allowed.get(old, set()):
        raise ChequeError(f"Illegal cheque transition {old} -> {action}")
    if direction == "RECEIVABLE" and action in ("PRESENT", "REPRESENT", "CANCEL"):
        raise ChequeError("Payable-only action on receivable cheque")
    if direction == "PAYABLE" and action in ("DEPOSIT", "REDEPOSIT", "ENDORSE"):
        raise ChequeError("Receivable-only action on payable cheque")
    if action in ("DEPOSIT", "PRESENT", "REDEPOSIT", "REPRESENT", "CLEAR"):
        if command.event_date < position.instrument.maturity_date:
            raise ChequeError("Bank presentation/clearing precedes maturity")
    if action in ("DEPOSIT", "REDEPOSIT"):
        return replace(position, status="DEPOSITED", last_event_id=command.event_id,
                       last_event_date=command.event_date, active_event_id=command.event_id,
                       active_action=action, receiving_bank_id=command.bank_id,
                       receiving_account_id=command.bank_account_id)
    result = {
        "ENDORSE": "ENDORSED", "PRESENT": "PRESENTED",
        "REPRESENT": "PRESENTED", "CLEAR": "CLEARED",
        "BOUNCE": "BOUNCED", "RETURN": "RETURNED", "CANCEL": "CANCELLED",
    }[action]
    return replace(position, status=result, last_event_id=command.event_id,
                   last_event_date=command.event_date, active_event_id=command.event_id,
                   active_action=action,
                   endorsed_supplier_id=(command.supplier_party_id if action == "ENDORSE"
                                         else position.endorsed_supplier_id),
                   cleared_date=command.event_date if action == "CLEAR" else position.cleared_date)


def _intent(command: ChequeCommand, position: ChequePosition) -> PostingIntent:
    action = command.action
    kinds = {
        "RECEIVE": "RECEIPT_REVIEW", "ISSUE": "ISSUE_REVIEW",
        "ENDORSE": "ENDORSEMENT_REVIEW", "DEPOSIT": "BANK_DEPOSIT_MEMO",
        "PRESENT": "BANK_PRESENTATION_MEMO", "CLEAR": "CLEARED_SETTLEMENT",
        "BOUNCE": "BOUNCE_REVIEW", "REDEPOSIT": "BANK_DEPOSIT_MEMO",
        "REPRESENT": "BANK_PRESENTATION_MEMO", "RETURN": "RETURN_REVIEW",
        "CANCEL": "CANCELLATION_REVIEW", "REVERSE": "BANK_ACTION_REVERSAL_REVIEW",
    }
    cash_effect = "NONE"
    if action == "CLEAR":
        cash_effect = ("DEBIT_BANK" if position.instrument.direction == "RECEIVABLE"
                       else "CREDIT_BANK")
    return PostingIntent(command.event_id, command.company_id, command.fiscal_period_id,
                         command.cheque_id, command.source, kinds[action],
                         position.instrument.amount_rial, cash_effect,
                         action not in ("DEPOSIT", "REDEPOSIT", "PRESENT", "REPRESENT"))


def replay_cheques(state: ChequeState) -> ChequeReplay:
    """Verify complete hash chain, transitions, identities, dates and cash-on-clear rule."""
    if type(state) is not ChequeState:
        raise ChequeError("Invalid cheque state type")
    baseline = new_cheque_state(state.company_id, state.periods)
    if (state.currency != "RIAL" or state.calendar != "JALALI" or
            type(state.events) is not tuple or len(state.events) > MAX_EVENTS):
        raise ChequeError("Malformed/foreign currency/calendar cheque state")
    if state.periods != baseline.periods:
        raise ChequeError("Fiscal period order changed")
    periods = {p.fiscal_period_id: p for p in state.periods}
    positions: dict[str, ChequePosition] = {}
    previous_by_event: dict[str, ChequePosition | None] = {}
    used_sources = set()
    event_ids = set()
    instrument_ids = set()
    reversed_ids: set[str] = set()
    intents = []
    preceding_hash = _GENESIS
    for item in state.events:
        if type(item) is not ChequeEvent or type(item.command) is not ChequeCommand:
            raise ChequeError("Malformed cheque history")
        command = item.command
        if command.company_id != state.company_id:
            raise ChequeError("Cross-company cheque event")
        period = periods.get(command.fiscal_period_id)
        if period is None or not period.start_date <= command.event_date <= period.end_date:
            raise ChequeError("Cheque event outside its fiscal period")
        if command.event_id in event_ids:
            raise ChequeConflict("Duplicate cheque event ID")
        source_key = (command.source.kind, command.source.source_id)
        if source_key in used_sources:
            raise ChequeConflict("Business source reused by another cheque event")
        if item.previous_hash != preceding_hash:
            raise ChequeError("Broken cheque hash chain")
        if (item.command_digest != _command_digest(command) or
                item.event_hash != _event_hash(command, item.previous_hash)):
            raise ChequeError("Cheque payload/digest/hash altered")
        prior = positions.get(command.cheque_id)
        if command.instrument is not None:
            ins = command.instrument
            if ins.company_id != state.company_id or ins.cheque_id != command.cheque_id:
                raise ChequeError("Cross-company/cheque instrument mismatch")
            if ins.instrument_id in instrument_ids:
                raise ChequeConflict("Duplicate cheque identifier across registry")
            if len(instrument_ids) >= MAX_CHEQUES:
                raise ChequeError("Cheque registry capacity exceeded")
            instrument_ids.add(ins.instrument_id)
        previous_by_event[command.event_id] = prior
        current = _transition(prior, command, previous_by_event, reversed_ids)
        positions[command.cheque_id] = current
        intents.append(_intent(command, current))
        used_sources.add(source_key)
        event_ids.add(command.event_id)
        preceding_hash = item.event_hash
    return ChequeReplay(state.revision, state.company_id, "RIAL", "JALALI",
                        tuple(positions[k] for k in sorted(positions)),
                        tuple(intents), frozenset(reversed_ids))


def append_cheque_event(state: ChequeState, command: ChequeCommand, *,
                        scopes: VerifiedChequeRefs, expected_revision: str,
                        today: str) -> ChequeState:
    """Optimistic CAS preflight. Host must provide real transaction and trusted scopes."""
    history = replay_cheques(state)
    _hash(expected_revision, "expected revision")
    if history.revision != expected_revision:
        raise ChequeConflict("Stale cheque CAS revision")
    if type(command) is not ChequeCommand or command.company_id != state.company_id:
        raise ChequeError("Malformed or cross-company cheque command")
    _date(today)
    if command.event_date > today:
        raise ChequeError("Future-dated cheque action")
    _reference_preflight(command, scopes)
    period_ids = {p.fiscal_period_id for p in state.periods}
    if not scopes.closed_period_ids.issubset(period_ids):
        raise ChequeError("Unrecognized host-closed fiscal period")
    if command.fiscal_period_id in scopes.closed_period_ids:
        raise ChequeError("Host reports closed fiscal period")
    period = next((p for p in state.periods if p.fiscal_period_id == command.fiscal_period_id), None)
    if period is None or not period.start_date <= command.event_date <= period.end_date:
        raise ChequeError("Cheque action outside fiscal period")
    digest = _command_digest(command)
    for event in state.events:
        if event.command.event_id == command.event_id:
            if event.command_digest == digest:
                return state
            raise ChequeConflict("Cheque event ID reused with another command")
        if event.command.source == command.source:
            raise ChequeConflict("Different event ID cannot reuse business source")
        if (command.instrument is not None and
                event.command.instrument is not None and
                event.command.instrument.instrument_id == command.instrument.instrument_id):
            raise ChequeConflict("Cheque instrument ID already registered")
    if len(state.events) >= MAX_EVENTS:
        raise ChequeError("Cheque event capacity exceeded")
    previous = state.events[-1].event_hash if state.events else _GENESIS
    entry = ChequeEvent(command, digest, previous, _event_hash(command, previous))
    result = replace(state, events=state.events + (entry,))
    replay_cheques(result)
    return result


def overdue_cheques(state: ChequeState, *, today: str) -> tuple[ChequePosition, ...]:
    """Deterministic, sorted due-date query; no clock, date conversion or side effects."""
    _date(today)
    candidates = (p for p in replay_cheques(state).positions
                  if p.instrument.maturity_date < today and
                  p.status not in _TERMINAL and p.status != "ENDORSED")
    return tuple(sorted(candidates, key=lambda p: (p.instrument.maturity_date,
                                                   p.instrument.cheque_id)))
