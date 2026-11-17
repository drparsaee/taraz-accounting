"""Read-only purchase tax preview; never a legal tax or posting authority."""
from datetime import date
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_MAX = 10**15


def _date(value, key):
    if type(value) is not str or not _DATE.fullmatch(value):
        raise ValueError(f"Invalid {key} date")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Noncanonical date")
    except ValueError as exc:
        raise ValueError(f"Invalid {key} date") from exc
    return value


def inspect_purchase_tax(command):
    """Suggest account classification only; no statutory rate is invented."""
    keys = {"type", "invoiceId", "currency", "documentDate", "taxPolicyId",
            "policyEffectiveFrom", "netAmountRial", "taxAmountRial",
            "treatment", "eligibilityVerified"}
    if type(command) is not dict or set(command) != keys:
        raise ValueError("Tax classification requires exact explicit fields")
    if command["type"] != "purchase.tax.preview":
        raise ValueError("Unsupported tax request")
    for key in ("invoiceId", "taxPolicyId"):
        if type(command[key]) is not str or not _ID.fullmatch(command[key]):
            raise ValueError(f"Invalid {key}")
    if type(command["currency"]) is not str or command["currency"] != "RIAL":
        raise ValueError("Explicit RIAL currency required")
    posted = _date(command["documentDate"], "document")
    effective = _date(command["policyEffectiveFrom"], "policy")
    if effective > posted:
        raise ValueError("Tax policy cannot take effect after document date")
    net, tax = command["netAmountRial"], command["taxAmountRial"]
    if (type(net) is not int or type(tax) is not int
            or not 1 <= net <= _MAX or not 0 <= tax <= _MAX or net + tax > _MAX):
        raise ValueError("Exact, bounded RIAL net and tax required")
    treatment = command["treatment"]
    if type(treatment) is not str or treatment not in ("exempt", "expense", "recoverable"):
        raise ValueError("Explicit tax treatment required")
    if type(command["eligibilityVerified"]) is not bool:
        raise ValueError("Eligibility review must be a boolean")
    if treatment == "exempt" and tax != 0:
        raise ValueError("Exempt purchase cannot include tax")
    if treatment == "recoverable" and (tax == 0 or not command["eligibilityVerified"]):
        raise ValueError("Recoverable tax needs nonzero tax and eligibility review")
    if treatment == "expense" and command["eligibilityVerified"]:
        raise ValueError("Expense classification cannot claim recoverability")
    return {
        "status": "PREVIEW_ONLY_POLICY_UNVERIFIED",
        "postingAllowed": False,
        "taxPolicyAuthenticated": False,
        "humanApproved": False,
        "currency": "RIAL",
        "classification": treatment,
        "candidateTaxDebitAccount": (
            "1250" if treatment == "recoverable" else
            "5200" if treatment == "expense" and tax else None),
        "netAmountRial": net,
        "taxAmountRial": tax,
        "grossAmountRial": net + tax
    }
