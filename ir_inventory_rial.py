"""Pure, immutable RIAL inventory ledger. No storage, permissions service, or GL posting.

Quantities are exact integer *base units*. FIFO layers carry their remaining total
RIAL cost, so partial issues use integer floor allocation and the final issue
receives the exact remainder. Host-supplied authority is a preflight contract,
not a substitute for authentication or atomic durable persistence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import re

from money_policy import MAX_RIAL, require_rial_amount, snapshot_sha256

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.([0-9]+))?\Z", re.ASCII)
_GENESIS = "0" * 64
KINDS = frozenset({"RECEIPT", "ISSUE", "TRANSFER", "ADJUSTMENT",
                   "PRICE", "RETURN", "REVERSAL"})
MAX_EVENTS = 10_000
MAX_LAYERS = 20_000
MAX_EVENT_SLICES = 256
MAX_QUANTITY = 1_000_000_000_000
MAX_SCOPE_SIZE = 2_000


class InventoryError(ValueError):
    """Invalid stock operation, damaged history, or unsafe measurement."""


class InventoryConflict(InventoryError):
    """Stale revision, conflicting event ID, or reused commercial source."""


def _id(value: str, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise InventoryError("Invalid " + field)
    return value


def _whole(value: int, label: str, *, zero: bool = True) -> int:
    if type(value) is not int or value < (0 if zero else 1) or value > MAX_QUANTITY:
        raise InventoryError("Invalid bounded integer " + label)
    return value


def _rial(value: int, *, negative: bool = False) -> int:
    try:
        return require_rial_amount(value, allow_negative=negative)
    except ValueError as exc:
        raise InventoryError("Invalid bounded integer RIAL valuation") from exc


def _bounded_sum(values, *, unit: str) -> int:
    result = sum(values)
    if unit == "rial":
        _rial(result)
    else:
        _whole(result, "aggregate quantity")
    return result


def _reason(value: str) -> str:
    if (type(value) is not str or not value.strip() or len(value) > 500
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise InventoryError("Nonempty readable audit reason required")
    return value


@dataclass(frozen=True, slots=True)
class ItemSpec:
    company_id: str
    item_id: str
    unit: str
    base_units_per_unit: int

    def __post_init__(self) -> None:
        _id(self.company_id, "item company")
        _id(self.item_id, "item ID")
        _id(self.unit, "item measurement unit")
        _whole(self.base_units_per_unit, "unit scale", zero=False)


def to_base_quantity(item: ItemSpec, displayed: str) -> int:
    """Parse e.g. '1.025' kg to 1025 g with scale=1000; never use float."""
    if type(item) is not ItemSpec or type(displayed) is not str:
        raise InventoryError("Explicit item and decimal quantity text required")
    match = _DECIMAL.fullmatch(displayed)
    if match is None or len(displayed) > 40:
        raise InventoryError("Invalid exact displayed quantity")
    whole, _, fractional = displayed.partition(".")
    denominator = 10 ** len(fractional)
    numerator = int(whole) * denominator + (int(fractional) if fractional else 0)
    scaled, remainder = divmod(numerator * item.base_units_per_unit, denominator)
    if remainder:
        raise InventoryError("Fraction cannot be represented in item base units")
    return _whole(scaled, "base quantity")


@dataclass(frozen=True, slots=True)
class BusinessSource:
    kind: str
    source_id: str

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind.upper() not in KINDS or self.kind != self.kind.lower():
            raise InventoryError("Business source must use lowercase movement type")
        _id(self.source_id, "business source")


@dataclass(frozen=True, slots=True)
class StockAuthority:
    """Server-verified scope evidence; NEVER accept this from an untrusted client."""
    company_id: str
    actor_ids: frozenset[str]
    warehouse_ids: frozenset[str]
    item_ids: frozenset[str]
    source_scopes: frozenset[tuple[str, str]]
    project_ids: frozenset[str] = frozenset()
    work_scopes: frozenset[tuple[str, str, str]] = frozenset()

    def __post_init__(self) -> None:
        _id(self.company_id, "authority company")
        for name in ("actor_ids", "warehouse_ids", "item_ids", "source_scopes",
                     "project_ids", "work_scopes"):
            values = getattr(self, name)
            if type(values) is not frozenset or len(values) > MAX_SCOPE_SIZE:
                raise InventoryError("Invalid bounded verified " + name)
            for entry in values:
                if name in ("source_scopes", "work_scopes"):
                    count = 2 if name == "source_scopes" else 3
                    if type(entry) is not tuple or len(entry) != count:
                        raise InventoryError("Invalid verified scope tuple")
                    for token in entry:
                        if name == "work_scopes" and token == "":
                            continue
                        _id(token, name)
                else:
                    _id(entry, name)
        if any(kind not in (k.lower() for k in KINDS) for kind, _ in self.source_scopes):
            raise InventoryError("Invalid business source category in authority")
        if any(not project for project, _, _ in self.work_scopes):
            raise InventoryError("Work references require an explicit project")


def _authority_payload(auth: StockAuthority) -> dict:
    return {name: sorted([list(v) if type(v) is tuple else v
                          for v in getattr(auth, name)])
            for name in ("actor_ids", "warehouse_ids", "item_ids",
                         "source_scopes", "project_ids", "work_scopes")} | {
                             "company_id": auth.company_id}


@dataclass(frozen=True, slots=True)
class StockEvent:
    event_id: str
    company_id: str
    actor_id: str
    kind: str
    source: BusinessSource
    warehouse_id: str
    item_id: str
    unit: str
    base_units_per_unit: int
    quantity_base: int
    destination_warehouse_id: str = ""
    cost_rial: int | None = None
    expected_quantity_base: int | None = None
    counted_quantity_base: int | None = None
    related_event_id: str = ""
    reason: str = ""
    project_id: str = ""
    job_id: str = ""
    cost_center_id: str = ""

    def __post_init__(self) -> None:
        for name in ("event_id", "company_id", "actor_id", "warehouse_id", "item_id",
                     "unit"):
            _id(getattr(self, name), name)
        if type(self.kind) is not str or self.kind not in KINDS:
            raise InventoryError("Unsupported movement type")
        if type(self.source) is not BusinessSource or self.source.kind != self.kind.lower():
            raise InventoryError("Business source must declare actual movement type")
        _whole(self.base_units_per_unit, "event measurement scale", zero=False)
        _whole(self.quantity_base, "movement quantity")
        for name in ("destination_warehouse_id", "related_event_id", "project_id",
                     "job_id", "cost_center_id"):
            field = getattr(self, name)
            if type(field) is not str:
                raise InventoryError("Malformed " + name)
            if field:
                _id(field, name)
        if type(self.reason) is not str or len(self.reason) > 500:
            raise InventoryError("Invalid audit reason")
        if self.reason and any(ord(c) < 32 or ord(c) == 127 for c in self.reason):
            raise InventoryError("Invalid audit reason control characters")
        if self.cost_rial is not None:
            _rial(self.cost_rial)
        if self.expected_quantity_base is not None:
            _whole(self.expected_quantity_base, "pre-count quantity")
        if self.counted_quantity_base is not None:
            _whole(self.counted_quantity_base, "observed count")
        if self.kind == "TRANSFER":
            if (not self.destination_warehouse_id or
                    self.destination_warehouse_id == self.warehouse_id):
                raise InventoryError("Transfer requires distinct warehouses")
        elif self.destination_warehouse_id:
            raise InventoryError("Only transfer has a destination warehouse")
        if self.kind == "ADJUSTMENT":
            if self.expected_quantity_base is None or self.counted_quantity_base is None:
                raise InventoryError("Cycle count must retain both observed and expected")
            if self.quantity_base != abs(self.counted_quantity_base - self.expected_quantity_base):
                raise InventoryError("Count variance differs from movement quantity")
        elif self.expected_quantity_base is not None or self.counted_quantity_base is not None:
            raise InventoryError("Cycle-count fields on non-adjustment")
        if self.kind in ("PRICE", "RETURN", "REVERSAL"):
            _id(self.related_event_id, "related movement event")
            if self.event_id == self.related_event_id:
                raise InventoryError("Cannot refer event to itself")
        elif self.related_event_id:
            raise InventoryError("Unexpected related event")
        if self.kind in ("RETURN", "REVERSAL", "ADJUSTMENT"):
            _reason(self.reason)
        if self.kind != "ADJUSTMENT" and self.quantity_base == 0:
            raise InventoryError("Movement quantity must be positive")
        if self.kind in ("ISSUE", "TRANSFER", "RETURN", "REVERSAL") and self.cost_rial is not None:
            raise InventoryError("Stock cost must be derived from historic FIFO, not supplied")
        if self.kind == "PRICE" and self.cost_rial is None:
            raise InventoryError("Pricing event requires explicit verified total cost")
        if self.kind == "ADJUSTMENT":
            delta = self.counted_quantity_base - self.expected_quantity_base
            if (delta > 0 and self.cost_rial is None) or (delta <= 0 and self.cost_rial is not None):
                raise InventoryError("Positive count variance needs cost; other variance derives cost")
        if self.job_id or self.cost_center_id:
            if not self.project_id:
                raise InventoryError("Work reference needs an explicit project")


@dataclass(frozen=True, slots=True)
class StockLayer:
    warehouse_id: str
    item_id: str
    origin_event_id: str
    created_by_event_id: str
    quantity_base: int
    value_rial: int


@dataclass(frozen=True, slots=True)
class StagedLot:
    warehouse_id: str
    item_id: str
    origin_event_id: str
    created_by_event_id: str
    quantity_base: int


@dataclass(frozen=True, slots=True)
class MovementEffects:
    consumed: tuple[StockLayer, ...] = ()
    created: tuple[StockLayer, ...] = ()
    staged_added: tuple[StagedLot, ...] = ()
    staged_removed: tuple[StagedLot, ...] = ()
    asset_delta_rial: int = 0
    valued_cost_rial: int = 0


@dataclass(frozen=True, slots=True)
class PostedMovement:
    event: StockEvent
    authority: StockAuthority
    effects: MovementEffects
    command_digest: str
    previous_hash: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class InventoryState:
    company_id: str
    items: tuple[ItemSpec, ...]
    warehouse_ids: tuple[str, ...]
    events: tuple[PostedMovement, ...] = ()

    @property
    def revision(self) -> str:
        return snapshot_sha256({
            "schema": "MADAR-RIAL-INVENTORY-1", "companyId": self.company_id,
            "items": [asdict(i) for i in self.items],
            "warehouses": list(self.warehouse_ids),
            "count": len(self.events),
            "tail": self.events[-1].event_hash if self.events else _GENESIS})


@dataclass(frozen=True, slots=True)
class StockPosition:
    warehouse_id: str
    item_id: str
    valued_quantity_base: int
    staged_quantity_base: int
    value_rial: int


@dataclass(frozen=True, slots=True)
class InventoryReplay:
    revision: str
    positions: tuple[StockPosition, ...]
    layers: tuple[StockLayer, ...]
    staging: tuple[StagedLot, ...]
    event_count: int


def new_inventory_state(company_id: str, items: tuple[ItemSpec, ...],
                        warehouse_ids: tuple[str, ...]) -> InventoryState:
    _id(company_id, "inventory company")
    if (type(items) is not tuple or type(warehouse_ids) is not tuple or
            not items or not warehouse_ids or len(items) > 2000 or
            len(warehouse_ids) > 2000):
        raise InventoryError("Explicit bounded item and warehouse catalog required")
    for item in items:
        if type(item) is not ItemSpec or item.company_id != company_id:
            raise InventoryError("Cross-company item specification")
    for warehouse in warehouse_ids:
        _id(warehouse, "warehouse")
    if (len({i.item_id for i in items}) != len(items) or
            len(set(warehouse_ids)) != len(warehouse_ids)):
        raise InventoryError("Duplicate item or warehouse in inventory catalog")
    return InventoryState(company_id, tuple(sorted(items, key=lambda i: i.item_id)),
                          tuple(sorted(warehouse_ids)))


def _check_scope(state: InventoryState, event: StockEvent, auth: StockAuthority) -> None:
    if type(auth) is not StockAuthority or type(event) is not StockEvent:
        raise InventoryError("Verified authority and typed event required")
    if auth.company_id != event.company_id or event.company_id != state.company_id:
        raise InventoryError("Cross-company inventory operation")
    if event.actor_id not in auth.actor_ids:
        raise InventoryError("Actor is not host-verified")
    for warehouse in (event.warehouse_id, event.destination_warehouse_id):
        if warehouse and (warehouse not in state.warehouse_ids or warehouse not in auth.warehouse_ids):
            raise InventoryError("Warehouse is not in verified company scope")
    if event.kind == "REVERSAL":
        # Reversing a transfer also removes inventory from its DESTINATION.
        # The reversal command itself has no destination_warehouse_id field.
        original = next((p.event for p in state.events
                         if p.event.event_id == event.related_event_id), None)
        if original is not None and original.kind == "TRANSFER":
            if original.destination_warehouse_id not in auth.warehouse_ids:
                raise InventoryError("Transfer reversal lacks destination warehouse permission")
    item = next((i for i in state.items if i.item_id == event.item_id), None)
    if item is None or item.item_id not in auth.item_ids:
        raise InventoryError("Item is not in verified company scope")
    if (item.unit != event.unit or
            item.base_units_per_unit != event.base_units_per_unit):
        raise InventoryError("Event unit/scale differs from immutable item catalog")
    if (event.source.kind, event.source.source_id) not in auth.source_scopes:
        raise InventoryError("Commercial source has not been verified by host")
    if event.project_id:
        if event.project_id not in auth.project_ids:
            raise InventoryError("Cross-company/unverified project")
    if (event.job_id or event.cost_center_id) and (
            event.project_id, event.job_id, event.cost_center_id) not in auth.work_scopes:
        raise InventoryError("Unverified project/job/cost-center binding")


def _consume_fifo(layers: list[StockLayer], warehouse: str, item: str,
                  qty: int) -> tuple[StockLayer, ...]:
    remaining = qty
    taken = []
    kept = []
    for lot in layers:
        if remaining and lot.warehouse_id == warehouse and lot.item_id == item:
            use = min(remaining, lot.quantity_base)
            value = lot.value_rial if use == lot.quantity_base else (
                lot.value_rial * use // lot.quantity_base)
            taken.append(replace(lot, quantity_base=use, value_rial=value))
            if use != lot.quantity_base:
                kept.append(replace(lot, quantity_base=lot.quantity_base-use,
                                    value_rial=lot.value_rial-value))
            remaining -= use
        else:
            kept.append(lot)
    if remaining:
        raise InventoryError("Insufficient valued stock; negative stock denied")
    layers[:] = kept
    return tuple(taken)


def _take_created(layers: list[StockLayer], created: tuple[StockLayer, ...]) -> None:
    """Full exact reversal requires the particular resulting lots to be untouched."""
    for wanted in created:
        try:
            index = layers.index(wanted)
        except ValueError as exc:
            raise InventoryError("Original lot already consumed or altered; reversal denied") from exc
        layers.pop(index)


def _get_related(history: dict[str, PostedMovement], event: StockEvent) -> PostedMovement:
    related = history.get(event.related_event_id)
    if related is None or related.event.company_id != event.company_id:
        raise InventoryError("Missing or cross-company related stock event")
    if (related.event.item_id != event.item_id or
            related.event.warehouse_id != event.warehouse_id or
            related.event.unit != event.unit or
            related.event.base_units_per_unit != event.base_units_per_unit):
        raise InventoryError("Related event differs in warehouse/item/measurement")
    if (related.event.project_id != event.project_id or
            related.event.job_id != event.job_id or
            related.event.cost_center_id != event.cost_center_id):
        raise InventoryError("Related event work identity changed")
    return related


def _transition(layers: list[StockLayer], staging: list[StagedLot],
                history: dict[str, PostedMovement], event: StockEvent) -> MovementEffects:
    consumed: tuple[StockLayer, ...] = ()
    created: tuple[StockLayer, ...] = ()
    added: tuple[StagedLot, ...] = ()
    removed: tuple[StagedLot, ...] = ()
    wh, item, qty = event.warehouse_id, event.item_id, event.quantity_base
    if event.kind == "RECEIPT":
        if event.cost_rial is None:
            added = (StagedLot(wh, item, event.event_id, event.event_id, qty),)
            staging.extend(added)
        else:
            created = (StockLayer(wh, item, event.event_id,
                                  event.event_id, qty, event.cost_rial),)
    elif event.kind == "ISSUE":
        consumed = _consume_fifo(layers, wh, item, qty)
    elif event.kind == "TRANSFER":
        consumed = _consume_fifo(layers, wh, item, qty)
        created = tuple(replace(lot, warehouse_id=event.destination_warehouse_id,
                                created_by_event_id=event.event_id) for lot in consumed)
    elif event.kind == "ADJUSTMENT":
        valued = sum(l.quantity_base for l in layers if l.warehouse_id == wh and l.item_id == item)
        pending = sum(l.quantity_base for l in staging if l.warehouse_id == wh and l.item_id == item)
        if pending:
            raise InventoryError("Cycle count requires pricing or segregating staged stock first")
        if valued != event.expected_quantity_base:
            raise InventoryConflict("Cycle-count baseline stale or forged")
        if event.counted_quantity_base > valued:
            created = (StockLayer(wh, item, event.event_id, event.event_id, qty, event.cost_rial),)
        elif event.counted_quantity_base < valued:
            consumed = _consume_fifo(layers, wh, item, qty)
    elif event.kind == "PRICE":
        related = _get_related(history, event)
        if related.event.kind != "RECEIPT" or related.event.cost_rial is not None:
            raise InventoryError("Pricing only allowed for costless receipt")
        if qty != related.event.quantity_base:
            raise InventoryError("Pricing requires entire pending receipt quantity")
        pending = [lot for lot in staging if lot.warehouse_id == wh and
                   lot.item_id == item and lot.origin_event_id == related.event.event_id]
        if len(pending) != 1 or pending[0].quantity_base != qty:
            raise InventoryError("Receipt already priced or staged quantity missing")
        removed = (pending[0],)
        staging.remove(pending[0])
        created = (StockLayer(wh, item, related.event.event_id, event.event_id,
                              qty, event.cost_rial),)
    elif event.kind == "RETURN":
        related = _get_related(history, event)
        if related.event.kind != "ISSUE" or qty != related.event.quantity_base:
            raise InventoryError("Only complete returns of a recorded issue are supported")
        created = tuple(replace(lot, created_by_event_id=event.event_id)
                        for lot in related.effects.consumed)
    elif event.kind == "REVERSAL":
        related = _get_related(history, event)
        original = related.event
        if (original.kind in ("RETURN", "REVERSAL") or qty != original.quantity_base or
                event.destination_warehouse_id):
            raise InventoryError("Only full original movements may be reversed once")
        if original.kind == "TRANSFER":
            _take_created(layers, related.effects.created)
            consumed = related.effects.created
            created = tuple(replace(lot, created_by_event_id=event.event_id)
                            for lot in related.effects.consumed)
        elif original.kind in ("ISSUE", "ADJUSTMENT") and related.effects.consumed:
            created = tuple(replace(lot, created_by_event_id=event.event_id)
                            for lot in related.effects.consumed)
        else:
            _take_created(layers, related.effects.created)
            consumed = related.effects.created
            for lot in related.effects.staged_added:
                pending = [row for row in staging if row.origin_event_id == lot.origin_event_id
                           and row.warehouse_id == lot.warehouse_id
                           and row.item_id == lot.item_id and
                           row.quantity_base == lot.quantity_base]
                if len(pending) != 1:
                    raise InventoryError("Staged original has already been priced")
                staging.remove(pending[0])
                removed += (pending[0],)
            if original.kind == "PRICE":
                added = tuple(replace(lot, created_by_event_id=event.event_id)
                              for lot in related.effects.staged_removed)
                staging.extend(added)
    if created:
        layers.extend(created)
    if (len(created) + len(consumed) + len(added) + len(removed) >
            MAX_EVENT_SLICES):
        raise InventoryError("Inventory event references too many FIFO lot slices")
    if len(layers) + len(staging) > MAX_LAYERS:
        raise InventoryError("Inventory layer capacity exceeded")
    for lot in layers:
        _whole(lot.quantity_base, "layer quantity", zero=False)
        _rial(lot.value_rial)
    for lot in staging:
        _whole(lot.quantity_base, "staged layer quantity", zero=False)
    _bounded_sum((l.value_rial for l in layers), unit="rial")
    _bounded_sum((l.quantity_base for l in layers), unit="quantity")
    _bounded_sum((l.quantity_base for l in staging), unit="quantity")
    taken_cost = _bounded_sum((l.value_rial for l in consumed), unit="rial")
    added_cost = _bounded_sum((l.value_rial for l in created), unit="rial")
    return MovementEffects(consumed, created, added, removed,
                           added_cost - taken_cost,
                           taken_cost if consumed else added_cost)


def _json_ready(value):
    """Only exact JSON atoms, lists and dictionaries enter the canonical hash."""
    if type(value) is tuple:
        return [_json_ready(v) for v in value]
    if type(value) is list:
        return [_json_ready(v) for v in value]
    if type(value) is dict:
        return {k: _json_ready(v) for k, v in value.items()}
    return value


def _command(event: StockEvent, auth: StockAuthority, effects: MovementEffects) -> dict:
    return {"event": asdict(event), "authority": _authority_payload(auth),
            "effects": _json_ready(asdict(effects)),
            "schema": "MADAR-RIAL-INVENTORY-EVENT-1"}


def _hash(command: dict, previous: str) -> str:
    return snapshot_sha256({"prev": previous, "digest": snapshot_sha256(command),
                            "command": command})


def _calculate(state: InventoryState) -> InventoryReplay:
    if type(state) is not InventoryState or type(state.events) is not tuple:
        raise InventoryError("Malformed inventory snapshot")
    baseline = new_inventory_state(state.company_id, state.items, state.warehouse_ids)
    if baseline.items != state.items or baseline.warehouse_ids != state.warehouse_ids:
        raise InventoryError("Item catalog or warehouse ordering modified")
    if len(state.events) > MAX_EVENTS:
        raise InventoryError("Inventory replay capacity exceeded")
    layers: list[StockLayer] = []
    staging: list[StagedLot] = []
    by_id: dict[str, PostedMovement] = {}
    by_source = set()
    closed_targets = set()
    previous = _GENESIS
    for entry in state.events:
        if type(entry) is not PostedMovement:
            raise InventoryError("Malformed posted inventory event")
        event = entry.event
        _check_scope(state, event, entry.authority)
        if event.event_id in by_id or event.source.source_id in by_source:
            raise InventoryError("Duplicate historic event or commercial source")
        if event.kind in ("RETURN", "REVERSAL"):
            if event.related_event_id in closed_targets:
                raise InventoryError("Original was already returned or reversed")
            closed_targets.add(event.related_event_id)
        expected = _transition(layers, staging, by_id, event)
        if entry.effects != expected:
            raise InventoryError("Inventory cost or movement effects were altered")
        command = _command(event, entry.authority, expected)
        if (entry.previous_hash != previous or
                entry.command_digest != snapshot_sha256(command) or
                entry.event_hash != _hash(command, previous)):
            raise InventoryError("Inventory history/hash chain damaged")
        previous = entry.event_hash
        by_id[event.event_id] = entry
        by_source.add(event.source.source_id)
    totals: dict[tuple[str, str], list[int]] = {}
    for lot in layers:
        record = totals.setdefault((lot.warehouse_id, lot.item_id), [0, 0, 0])
        record[0] += lot.quantity_base
        record[2] += lot.value_rial
    for lot in staging:
        record = totals.setdefault((lot.warehouse_id, lot.item_id), [0, 0, 0])
        record[1] += lot.quantity_base
    positions = []
    for (warehouse, item), (qty, pending, value) in sorted(totals.items()):
        _whole(qty, "position stock")
        _whole(pending, "position staging")
        _rial(value)
        positions.append(StockPosition(warehouse, item, qty, pending, value))
    return InventoryReplay(state.revision, tuple(positions), tuple(layers),
                           tuple(staging), len(state.events))


def replay_inventory(state: InventoryState) -> InventoryReplay:
    """Verify all source keys, event payload hashes and recomputed FIFO effects."""
    return _calculate(state)


def append_stock_event(state: InventoryState, event: StockEvent,
                       authority: StockAuthority, *, expected_revision: str) -> InventoryState:
    """CAS preflight and pure append; host MUST atomically store against persisted CAS."""
    prior = _calculate(state)
    _check_scope(state, event, authority)
    existing = next((p for p in state.events if p.event.event_id == event.event_id), None)
    if existing is not None:
        if existing.event == event and existing.authority == authority:
            return state
        raise InventoryConflict("Event ID reused with changed payload/authority")
    if any(p.event.source.source_id == event.source.source_id for p in state.events):
        raise InventoryConflict("Business source already recorded under another event ID")
    if (type(expected_revision) is not str or expected_revision != prior.revision):
        raise InventoryConflict("Stale inventory CAS revision")
    if len(state.events) >= MAX_EVENTS:
        raise InventoryError("Inventory capacity exceeded")
    if event.kind in ("RETURN", "REVERSAL") and any(
            p.event.kind in ("RETURN", "REVERSAL") and
            p.event.related_event_id == event.related_event_id for p in state.events):
        raise InventoryConflict("Original event already returned or reversed")
    layers, staging = list(prior.layers), list(prior.staging)
    prior_events = {p.event.event_id: p for p in state.events}
    effects = _transition(layers, staging, prior_events, event)
    command = _command(event, authority, effects)
    previous = state.events[-1].event_hash if state.events else _GENESIS
    posted = PostedMovement(event, authority, effects, snapshot_sha256(command),
                            previous, _hash(command, previous))
    return replace(state, events=state.events + (posted,))


@dataclass(frozen=True, slots=True)
class InventoryAccountMapping:
    company_id: str
    inventory_asset: str
    receipt_clearing: str
    issue_expense: str
    adjustment_gain: str
    adjustment_loss: str
    pricing_clearing: str

    def __post_init__(self) -> None:
        for field in ("company_id", "inventory_asset", "receipt_clearing",
                      "issue_expense", "adjustment_gain", "adjustment_loss",
                      "pricing_clearing"):
            _id(getattr(self, field), field)
        if len({self.inventory_asset, self.receipt_clearing, self.issue_expense,
                self.adjustment_gain, self.adjustment_loss, self.pricing_clearing}) != 6:
            raise InventoryError("Explicit inventory journal roles must map to distinct accounts")


@dataclass(frozen=True, slots=True)
class ProposedLine:
    account_code: str
    debit_rial: int
    credit_rial: int


@dataclass(frozen=True, slots=True)
class InventoryJournalProposal:
    company_id: str
    inventory_event_id: str
    source_kind: str
    source_id: str
    project_id: str
    job_id: str
    cost_center_id: str
    lines: tuple[ProposedLine, ...]


def propose_inventory_journal(state: InventoryState, event_id: str,
                              accounts: InventoryAccountMapping) -> InventoryJournalProposal | None:
    """Balanced RIAL account-code proposal, NOT an authorized or committed GL journal."""
    replay_inventory(state)
    if type(accounts) is not InventoryAccountMapping or accounts.company_id != state.company_id:
        raise InventoryError("Explicit company-matched inventory GL mapping required")
    _id(event_id, "proposed event")
    posted = next((p for p in state.events if p.event.event_id == event_id), None)
    if posted is None:
        raise InventoryError("Unrecorded inventory source cannot create GL proposal")
    event = posted.event
    delta = posted.effects.asset_delta_rial
    if delta == 0:
        return None
    original_kind = event.kind
    if original_kind == "REVERSAL":
        original = next(p for p in state.events
                        if p.event.event_id == event.related_event_id)
        original_kind = original.event.kind
    if original_kind == "RECEIPT":
        contra = accounts.receipt_clearing
    elif original_kind in ("ISSUE", "RETURN"):
        contra = accounts.issue_expense
    elif original_kind == "PRICE":
        contra = accounts.pricing_clearing
    elif original_kind == "ADJUSTMENT":
        contra = (accounts.adjustment_gain if delta > 0 else accounts.adjustment_loss)
        if event.kind == "REVERSAL":
            contra = (accounts.adjustment_loss if delta > 0 else accounts.adjustment_gain)
    else:
        raise InventoryError("No inventory GL role available for movement")
    amount = abs(delta)
    _rial(amount)
    if delta > 0:
        lines = (ProposedLine(accounts.inventory_asset, amount, 0),
                 ProposedLine(contra, 0, amount))
    else:
        lines = (ProposedLine(contra, amount, 0),
                 ProposedLine(accounts.inventory_asset, 0, amount))
    if sum(line.debit_rial for line in lines) != sum(line.credit_rial for line in lines):
        raise InventoryError("Unbalanced inventory journal proposal")
    return InventoryJournalProposal(state.company_id, event.event_id,
                                    event.source.kind, event.source.source_id,
                                    event.project_id, event.job_id,
                                    event.cost_center_id, lines)


__all__ = ["InventoryError", "InventoryConflict", "MAX_EVENTS", "MAX_LAYERS",
           "MAX_EVENT_SLICES",
           "MAX_QUANTITY", "ItemSpec", "to_base_quantity", "BusinessSource",
           "StockAuthority", "StockEvent", "StockLayer", "StagedLot",
           "MovementEffects", "PostedMovement", "InventoryState", "StockPosition",
           "InventoryReplay", "new_inventory_state", "replay_inventory",
           "append_stock_event", "InventoryAccountMapping", "ProposedLine",
           "InventoryJournalProposal", "propose_inventory_journal"]
