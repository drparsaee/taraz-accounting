"""Side-effect-free quote from the same standalone accounting line calculator.

No task, project, party or ledger references are accepted here. The caller's
authenticated host controls visibility; a quote can never post any money.
"""
from accounting_core import MAX_TOMAN, _int, _lines, _new_projection


def quote_standalone_sale(payload, *, ledger_currency="TOMAN"):
    """Exact {quantity,unitPrice,currency} -> original currency amount string.

    The standalone ledger is integer TOMAN. RIAL works only when unitPrice is
    divisible by 10, without any rounding. Big original-currency totals are
    returned as decimal strings, never unsafe JavaScript floating point.
    """
    if type(payload) is not dict or set(payload) != {"quantity", "unitPrice", "currency"}:
        raise ValueError("Quote requires quantity, unitPrice and currency only")
    quantity = _int(payload["quantity"], "quantity", positive=True, cap=1000000)
    currency = payload["currency"]
    if currency not in ("TOMAN", "RIAL"):
        raise ValueError("Quote currency must be TOMAN or RIAL")
    if ledger_currency not in ("TOMAN", "RIAL"):
        raise ValueError("Unknown accounting ledger currency")
    raw_price = payload["unitPrice"]
    if ledger_currency == "RIAL":
        if type(raw_price) is not int or raw_price <= 0:
            raise ValueError("RIAL unit price must be an exact positive integer")
        rial_price = raw_price * (10 if currency == "TOMAN" else 1)
        _int(rial_price, "RIAL unit price", positive=True)
        _, rial_total = _lines(_new_projection(currency="RIAL"), [{
            "description": "Sale quote", "quantity": quantity,
            "unitPrice": rial_price,
        }], sales=True)
        return {"currency": currency, "quantity": quantity,
                "amount": str(rial_total // (10 if currency == "TOMAN" else 1)),
                "amountRial": str(rial_total), "status": "quote-only"}
    if currency == "RIAL":
        if type(raw_price) is not int or raw_price <= 0 or raw_price > 10 * MAX_TOMAN:
            raise ValueError("RIAL unit price must be an exact positive integer")
        if raw_price % 10 != 0:
            raise ValueError("RIAL unit price cannot be represented as exact TOMAN")
        toman_price = raw_price // 10
    else:
        toman_price = raw_price
    _int(toman_price, "unitPrice", positive=True)
    # Reuse the authoritative accounting line engine for range and overflow.
    _, subtotal = _lines(_new_projection(), [{
        "description": "Sale quote", "quantity": quantity,
        "unitPrice": toman_price,
    }], sales=True)
    return {"currency": currency, "quantity": quantity,
            "amount": str(subtotal * (10 if currency == "RIAL" else 1)),
            "amountToman": subtotal, "status": "quote-only"}
