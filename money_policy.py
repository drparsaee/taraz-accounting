"""Pure, opt-in RIAL-canonical money policy for NEW Madar finance domains.

This module does not mutate historical TOMAN finance/accounting snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import re
from typing import Any, Mapping

RIAL_PER_TOMAN = 10
ACCOUNTING_CURRENCY = "RIAL"
DISPLAY_UNITS = frozenset({"RIAL", "TOMAN"})
# JS Number-safe cap. Larger future totals need an explicit string-based wire format.
MAX_RIAL = 9_007_199_254_740_991
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z", re.ASCII)
_HASH = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
_WHOLE = re.compile(r"(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)", re.ASCII)
_FA = "۰۱۲۳۴۵۶۷۸۹"
_AR = "٠١٢٣٤٥٦٧٨٩"
_ASCII = str.maketrans({**{d: str(i) for i, d in enumerate(_FA)},
                        **{d: str(i) for i, d in enumerate(_AR)},
                        "٬": ",", "٫": "."})
_PERSIAN = str.maketrans({str(i): d for i, d in enumerate(_FA)})


class MoneyPolicyError(ValueError):
    """Reject ambiguous units, lossy conversions, or altered snapshots."""


def _id(value: Any, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise MoneyPolicyError("Invalid " + name)
    return value


def _unit(unit: Any) -> str:
    if type(unit) is not str or unit not in DISPLAY_UNITS:
        raise MoneyPolicyError("Explicit display unit RIAL or TOMAN required")
    return unit


def _cap(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= MAX_RIAL:
        raise MoneyPolicyError("Invalid canonical RIAL ceiling")
    return value


def require_rial_amount(value: Any, *, max_abs_rial: int = MAX_RIAL,
                        allow_negative: bool = False, allow_zero: bool = True) -> int:
    limit = _cap(max_abs_rial)
    if type(value) is not int or abs(value) > limit:
        raise MoneyPolicyError("Canonical RIAL must be an exact bounded integer")
    if value < 0 and not allow_negative:
        raise MoneyPolicyError("Negative RIAL amount not authorized")
    if value == 0 and not allow_zero:
        raise MoneyPolicyError("Zero amount not authorized")
    return value


@dataclass(frozen=True, slots=True)
class CompanyMoneyPolicy:
    company_id: str
    accounting_currency: str = "RIAL"
    display_unit: str = "RIAL"
    max_abs_rial: int = MAX_RIAL

    def __post_init__(self) -> None:
        _id(self.company_id, "company ID")
        if self.accounting_currency != "RIAL":
            raise MoneyPolicyError("Canonical accounting currency must be RIAL")
        _unit(self.display_unit)
        _cap(self.max_abs_rial)

    def with_display_unit(self, unit: str) -> "CompanyMoneyPolicy":
        return replace(self, display_unit=_unit(unit))

    def parse(self, raw: str, *, allow_zero: bool = True,
              allow_negative: bool = False) -> int:
        return parse_money_input(raw, self.display_unit, max_abs_rial=self.max_abs_rial,
                                 allow_zero=allow_zero, allow_negative=allow_negative)

    def format(self, rial: int, *, persian_digits: bool = False) -> str:
        require_rial_amount(rial, max_abs_rial=self.max_abs_rial, allow_negative=True)
        return format_money(rial, self.display_unit, persian_digits=persian_digits)


def parse_money_input(raw: str, unit: str, *, max_abs_rial: int = MAX_RIAL,
                      allow_zero: bool = True, allow_negative: bool = False) -> int:
    """Strict text parser; exactly one fractional TOMAN digit represents one RIAL."""
    unit = _unit(unit)
    limit = _cap(max_abs_rial)
    if type(raw) is not str or not raw or len(raw) > 128:
        raise MoneyPolicyError("Money entry must be a bounded text string")
    value = raw.strip().translate(_ASCII)
    negative = value.startswith("-")
    if negative:
        if not allow_negative:
            raise MoneyPolicyError("Negative money entry is unauthorized")
        value = value[1:]
    if not value or value[0] in ("-", "+"):
        raise MoneyPolicyError("Invalid sign")
    if unit == "TOMAN":
        whole, separator, fraction = value.partition(".")
        if separator and (len(fraction) != 1 or fraction not in "0123456789"):
            raise MoneyPolicyError("TOMAN accepts exactly tenths, not rounded hundredths")
    else:
        if "." in value:
            raise MoneyPolicyError("Fractional RIAL forbidden")
        whole, fraction = value, "0"
    if _WHOLE.fullmatch(whole) is None:
        raise MoneyPolicyError("Invalid digit grouping or numeric characters")
    number = int(whole.replace(",", ""))
    if unit == "TOMAN":
        if number > limit // RIAL_PER_TOMAN:
            raise MoneyPolicyError("TOMAN input exceeds maximum RIAL")
        number = number * RIAL_PER_TOMAN + int(fraction or "0")
    if negative and number == 0:
        raise MoneyPolicyError("Signed negative zero is not a canonical amount")
    number = -number if negative else number
    return require_rial_amount(number, max_abs_rial=limit,
                               allow_negative=allow_negative, allow_zero=allow_zero)


def format_money(rial: int, unit: str, *, persian_digits: bool = False,
                 include_unit: bool = False) -> str:
    unit = _unit(unit)
    require_rial_amount(rial, allow_negative=True)
    positive = abs(rial)
    if unit == "RIAL":
        body = f"{positive:,}"
    else:
        toman, leftover_rial = divmod(positive, RIAL_PER_TOMAN)
        body = f"{toman:,}" + (f".{leftover_rial}" if leftover_rial else "")
    result = ("-" if rial < 0 else "") + body
    if persian_digits:
        result = result.translate(_PERSIAN)
    return result + (" " + unit if include_unit else "")


def sum_rial_amounts(values: Any, *, max_abs_rial: int = MAX_RIAL) -> int:
    limit = _cap(max_abs_rial)
    total = 0
    for item in values:
        total += require_rial_amount(item, max_abs_rial=limit, allow_negative=True)
        require_rial_amount(total, max_abs_rial=limit, allow_negative=True)
    return total


def multiply_rial(rial: int, quantity: int, *,
                  max_abs_rial: int = MAX_RIAL) -> int:
    limit = _cap(max_abs_rial)
    require_rial_amount(rial, max_abs_rial=limit, allow_negative=True)
    if type(quantity) is not int or not 0 <= quantity <= 1_000_000:
        raise MoneyPolicyError("Quantity must be a bounded integer")
    return require_rial_amount(rial * quantity, max_abs_rial=limit, allow_negative=True)


def _snapshot_bytes(value: Any) -> bytes:
    """Canonical immutable JSON encoding. Forbid float anywhere in snapshots."""
    def inspect(node: Any, depth: int = 0) -> None:
        if depth > 64:
            raise MoneyPolicyError("Unsafe nested snapshot")
        if node is None or type(node) in (str, bool, int):
            return
        if type(node) is list:
            for item in node:
                inspect(item, depth + 1)
            return
        if type(node) is dict and all(type(k) is str for k in node):
            for item in node.values():
                inspect(item, depth + 1)
            return
        raise MoneyPolicyError("Floats and non-JSON values forbidden in money snapshots")

    inspect(value)
    try:
        result = json.dumps(value, sort_keys=True, ensure_ascii=False,
                            allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, OverflowError, UnicodeError) as exc:
        raise MoneyPolicyError("Invalid JSON snapshot") from exc
    if len(result) > 1_000_000:
        raise MoneyPolicyError("Money snapshot exceeds one megabyte")
    return result


def snapshot_sha256(snapshot: Any) -> str:
    return sha256(_snapshot_bytes(snapshot)).hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenPostedDocument:
    company_id: str
    event_id: str
    amount_rial: int
    canonical_json: bytes
    sha256: str

    def document_copy(self) -> dict[str, Any]:
        return json.loads(self.canonical_json.decode("utf-8"))


def freeze_posted_document(document: Mapping[str, Any],
                           policy: CompanyMoneyPolicy) -> FrozenPostedDocument:
    """Freeze ALL posted fields. Host must enforce durable append-only storage."""
    if type(document) is not dict or type(policy) is not CompanyMoneyPolicy:
        raise MoneyPolicyError("Expected plain posted document and company policy")
    company = _id(document.get("companyId"), "posted company")
    event = _id(document.get("eventId"), "posted event")
    if company != policy.company_id or document.get("currency") != "RIAL":
        raise MoneyPolicyError("Posted document must be same-company canonical RIAL")
    if document.get("status") != "posted":
        raise MoneyPolicyError("Drafts cannot be frozen as posted documents")
    amount = require_rial_amount(document.get("amountRial"),
                                 max_abs_rial=policy.max_abs_rial, allow_negative=True)
    def verify_rial_fields(node: Any, depth: int = 0) -> None:
        if depth > 64:
            raise MoneyPolicyError("Unsafe nested posted money fields")
        if type(node) is dict:
            for key, value in node.items():
                if type(key) is str and key.lower().endswith("rial"):
                    require_rial_amount(value, max_abs_rial=policy.max_abs_rial,
                                        allow_negative=True)
                verify_rial_fields(value, depth + 1)
        elif type(node) is list:
            for value in node:
                verify_rial_fields(value, depth + 1)

    verify_rial_fields(document)
    raw = _snapshot_bytes(document)
    return FrozenPostedDocument(company, event, amount, raw, sha256(raw).hexdigest())


def assert_posted_document_unchanged(frozen: FrozenPostedDocument,
                                      candidate: Mapping[str, Any],
                                      policy: CompanyMoneyPolicy) -> None:
    if type(frozen) is not FrozenPostedDocument or frozen.company_id != policy.company_id:
        raise MoneyPolicyError("Wrong company or posted snapshot type")
    if sha256(frozen.canonical_json).hexdigest() != frozen.sha256:
        raise MoneyPolicyError("Posted snapshot digest corrupted")
    if frozen.amount_rial != frozen.document_copy().get("amountRial"):
        raise MoneyPolicyError("Posted amount envelope corrupted")
    actual = freeze_posted_document(candidate, policy)
    if actual.sha256 != frozen.sha256 or actual.canonical_json != frozen.canonical_json:
        raise MoneyPolicyError("Posted documents are immutable: create a reversing event")


@dataclass(frozen=True, slots=True)
class LegacySourceEvidence:
    """Data structure only: verifier identity MUST be authenticated by host."""
    source_id: str
    declared_unit: str
    verified_unit: str
    source_snapshot_sha256: str
    verifier_id: str
    verification_reference: str

    def __post_init__(self) -> None:
        _id(self.source_id, "source")
        _id(self.verifier_id, "verifier")
        _id(self.verification_reference, "verification reference")
        if self.declared_unit != "TOMAN" or self.verified_unit != "TOMAN":
            raise MoneyPolicyError("Legacy source unit must be independently verified TOMAN")
        if (type(self.source_snapshot_sha256) is not str or
                _HASH.fullmatch(self.source_snapshot_sha256) is None):
            raise MoneyPolicyError("Invalid verified source digest")


@dataclass(frozen=True, slots=True)
class LegacyMigrationQuote:
    company_id: str
    source_id: str
    source_snapshot_sha256: str
    field_path: tuple[str | int, ...]
    legacy_toman: int
    converted_rial: int
    verifier_id: str
    verification_reference: str
    quote_sha256: str


def quote_legacy_toman_migration(snapshot: dict[str, Any],
                                 field_path: tuple[str | int, ...],
                                 evidence: LegacySourceEvidence,
                                 policy: CompanyMoneyPolicy,
                                 *, allow_negative: bool = False) -> LegacyMigrationQuote:
    """Migration PREVIEW only; never import or rewrite original TOMAN data."""
    if type(snapshot) is not dict or type(field_path) is not tuple or not 1 <= len(field_path) <= 24:
        raise MoneyPolicyError("A bounded full legacy snapshot and path are required")
    if type(evidence) is not LegacySourceEvidence or type(policy) is not CompanyMoneyPolicy:
        raise MoneyPolicyError("Verified source evidence and policy required")
    digest = snapshot_sha256(snapshot)
    if digest != evidence.source_snapshot_sha256:
        raise MoneyPolicyError("Legacy source differs from unit-verified snapshot")
    value: Any = snapshot
    for field in field_path:
        if type(field) is str and type(value) is dict and field in value:
            value = value[field]
        elif type(field) is int and field >= 0 and type(value) is list and field < len(value):
            value = value[field]
        else:
            raise MoneyPolicyError("Legacy monetary field path not found")
    if type(value) is not int or (value < 0 and not allow_negative):
        raise MoneyPolicyError("Legacy amount must be an exact integer TOMAN")
    if abs(value) > policy.max_abs_rial // RIAL_PER_TOMAN:
        raise MoneyPolicyError("Legacy TOMAN conversion overflows RIAL cap")
    rial = require_rial_amount(value * RIAL_PER_TOMAN,
                               max_abs_rial=policy.max_abs_rial,
                               allow_negative=allow_negative)
    payload = {"companyId": policy.company_id, "sourceId": evidence.source_id,
               "snapshot": digest, "path": list(field_path),
               "sourceUnit": "TOMAN", "targetUnit": "RIAL",
               "sourceAmount": value, "targetAmount": rial,
               "verifierId": evidence.verifier_id,
               "verificationReference": evidence.verification_reference}
    return LegacyMigrationQuote(
        policy.company_id, evidence.source_id, digest, field_path,
        value, rial, evidence.verifier_id, evidence.verification_reference,
        snapshot_sha256(payload),
    )


def verify_legacy_migration_quote(quote: LegacyMigrationQuote,
                                  snapshot: dict[str, Any],
                                  evidence: LegacySourceEvidence,
                                  policy: CompanyMoneyPolicy) -> None:
    if type(quote) is not LegacyMigrationQuote:
        raise MoneyPolicyError("Immutable migration quote expected")
    rebuilt = quote_legacy_toman_migration(snapshot, quote.field_path, evidence, policy,
                                           allow_negative=quote.legacy_toman < 0)
    if rebuilt != quote:
        raise MoneyPolicyError("Migration quote differs from verified original")


__all__ = [
    "RIAL_PER_TOMAN", "ACCOUNTING_CURRENCY", "DISPLAY_UNITS", "MAX_RIAL",
    "MoneyPolicyError", "CompanyMoneyPolicy", "require_rial_amount",
    "parse_money_input", "format_money", "sum_rial_amounts", "multiply_rial",
    "snapshot_sha256", "FrozenPostedDocument", "freeze_posted_document",
    "assert_posted_document_unchanged", "LegacySourceEvidence",
    "LegacyMigrationQuote", "quote_legacy_toman_migration",
    "verify_legacy_migration_quote",
]
