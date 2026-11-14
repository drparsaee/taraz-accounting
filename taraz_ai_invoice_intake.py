"""Conservative Persian request -> source-linked invoice *draft proposal*.

This deterministic planner is deliberately NOT called an LLM. No online
lookup, Madar read, accounting write, price invention or financial posting.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re


_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ITEM = re.compile(
    r"(?<!\w)(\d{1,7})\s*(عدد|بسته|کیلوگرم|کیلو|متر|سرویس)\s+"
    r"([\u0600-\u06FFA-Za-z0-9 _-]{1,90}?)"
    r"(?=\s+و\s+\d|\s+اضافه\s+کن|\s+ثبت\s+کن|[،.؛]|$)"
)
_UNITS = {
    "عدد": {"piece", "unit", "عدد"},
    "بسته": {"pack", "بسته"},
    "کیلوگرم": {"kg", "کیلوگرم"},
    "کیلو": {"kg", "کیلوگرم"},
    "متر": {"meter", "m", "متر"},
    "سرویس": {"service", "سرویس"},
}


def _blocked(reason, *, revision, detail=None):
    return {"status": "BLOCKED", "reason": reason, "sourceRevision": revision,
            "lines": [], "sources": [], "missing": detail or [], "ready": False,
            "financialEventCreated": False, "modelRan": False}


def invoice_preview(text, snapshot):
    """Only same-customer issued invoices with explicit catalog-linked lines."""
    if not isinstance(text, str) or len(text) > 4000:
        raise ValueError("Invalid AI command length")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("view"), dict):
        raise ValueError("Source accounting view required")
    revision, view = snapshot["revision"], snapshot["view"]
    request = " ".join(text.translate(_DIGITS).strip().split())
    if any(token in request for token in ("مدار", "تسک", "RADAR", "رادار")):
        return _blocked("TASK_SOURCE_NOT_CONNECTED", revision=revision,
                        detail=["ارتباط با تسک باید از منبع معتبر و مجاز تأیید شود."])
    if any(token in request for token in ("اینترنت", "وب", "آنلاین", "جست‌وجو")):
        return _blocked("ONLINE_CONSENT_REQUIRED", revision=revision,
                        detail=["درخواست وب به رضایت و جست‌وجوی دارای منبع نیاز دارد."])
    customer = re.search(r"برای\s+(.+?)\s+(?:یک\s+)?فاکتور(?:\s+فروش)?", request)
    if not customer:
        return _blocked("CUSTOMER_NAME_REQUIRED", revision=revision)
    customer_name = customer.group(1).strip(" ،.")
    parties = view.get("parties") or {}
    possible = [p for p in parties.values() if p.get("name") == customer_name and
                p.get("kind") in ("customer", "both")]
    if len(possible) != 1:
        return _blocked("CUSTOMER_NOT_UNIQUELY_MATCHED", revision=revision,
                        detail=[customer_name])
    if "آخرین فاکتور" not in request and "آخرین پیش‌فاکتور" not in request:
        return _blocked("EXPLICIT_PRICE_SOURCE_REQUIRED", revision=revision)
    if "آخرین پیش‌فاکتور" in request:
        return _blocked("PROFORMA_PRICE_POLICY_NOT_ACCEPTED", revision=revision)
    raw_items = list(_ITEM.finditer(request))
    if not raw_items or len(raw_items) > 50:
        return _blocked("ITEMS_NOT_PARSED", revision=revision)
    catalog = view.get("items") or {}
    invoices = view.get("invoices") or {}
    lines, sources, missing = [], [], []
    for quantity, unit, label in (m.groups() for m in raw_items):
        item_name = label.strip()
        matches = [i for i in catalog.values() if
                   i.get("name") == item_name and i.get("active") is True and
                   i.get("unit") in _UNITS[unit]]
        if len(matches) != 1:
            missing.append({"item": item_name, "reason": "CATALOG_OR_UNIT_AMBIGUOUS"})
            continue
        item = matches[0]
        prior = []
        for doc in invoices.values():
            if doc.get("status") != "issued" or doc.get("partyId") != possible[0]["id"]:
                continue
            if doc.get("currency", view.get("currency")) != view.get("currency"):
                continue
            # Issue sequence is the authoritative ordering, not editable
            # documentDate or lexical invoice ID. Last valid issued invoice
            # *containing this exact catalog item* provides the price.
            number = doc.get("number")
            if type(number) is not int or number < 1:
                continue
            matching_lines = [line for line in doc.get("lines") or []
                              if line.get("itemId") == item["id"]]
            if matching_lines:
                prior.append((number, doc, matching_lines))
        if not prior:
            missing.append({"item": item_name, "reason": "NO_ISSUED_CUSTOMER_PRICE"})
            continue
        newest = max(candidate[0] for candidate in prior)
        latest = [candidate for candidate in prior if candidate[0] == newest]
        if len(latest) != 1:
            missing.append({"item": item_name, "reason": "AMBIGUOUS_ISSUE_SEQUENCE"})
            continue
        source_no, source_doc, matching_lines = latest[0]
        prices = [line.get("unitPrice") for line in matching_lines]
        if (not prices or any(type(price) is not int or price < 0 for price in prices)
            or len(set(prices)) != 1):
            missing.append({"item": item_name, "reason": "AMBIGUOUS_SOURCE_LINE_PRICES"})
            continue
        price = prices[0]
        source_date, source_id = source_doc["documentDate"], source_doc["id"]
        if not 1 <= int(quantity) <= 1000000:
            missing.append({"item": item_name, "reason": "INVALID_QUANTITY"})
            continue
        lines.append({"description": item_name, "quantity": int(quantity),
                      "unitPrice": price, "itemId": item["id"],
                      "unit": unit, "accountId": "4000"})
        sources.append({"itemId": item["id"], "invoiceId": source_id,
                        "invoiceNumber": str(source_no), "invoiceDate": source_date,
                        "issuedAt": source_doc.get("lastChangedAt", ""),
                        "unitPrice": price, "currency": view.get("currency"),
                        "sourceRevision": revision})
    if missing or len(lines) != len(raw_items):
        return {"status": "BLOCKED", "reason": "PRICE_OR_ITEM_EVIDENCE_MISSING",
                "missing": missing, "lines": lines, "sources": sources,
                "sourceRevision": revision, "ready": False,
                "financialEventCreated": False, "modelRan": False}
    total = sum(x["quantity"] * x["unitPrice"] for x in lines)
    if total <= 0 or total > 10**15:
        return _blocked("AMOUNT_NOT_ALLOWED", revision=revision)
    if view.get("accounts", {}).get("4000", {}).get("kind") != "revenue":
        return _blocked("REVENUE_ACCOUNT_UNAVAILABLE", revision=revision)
    return {"status": "READY_FOR_REVIEW", "ready": True,
            "sourceRevision": revision, "partyId": possible[0]["id"],
            "customerName": customer_name, "currency": view.get("currency"),
            "documentDate": datetime.now(timezone.utc).date().isoformat(),
            "lines": lines, "sources": sources, "missing": [],
            "discount": 0, "tax": 0, "total": total,
            "taxAssumption": "Zero until explicitly reviewed by the user",
            "financialEventCreated": False, "modelRan": False}


def preview_reply(proposal):
    if not proposal.get("ready"):
        messages = {
            "TASK_SOURCE_NOT_CONNECTED": "اتصال معتبر تسک مدار در این گفتگو تأیید نشده است.",
            "ONLINE_CONSENT_REQUIRED": "جست‌وجوی اینترنتی بدون مجوز انجام نمی‌شود.",
            "CUSTOMER_NAME_REQUIRED": "نام دقیق مشتری برای فاکتور مشخص نیست.",
            "CUSTOMER_NOT_UNIQUELY_MATCHED": "مشتری یکتا در داده‌های همین شرکت پیدا نشد.",
            "EXPLICIT_PRICE_SOURCE_REQUIRED": "منبع تعیین قیمت باید صریح باشد.",
            "PROFORMA_PRICE_POLICY_NOT_ACCEPTED": "قیمت پیش‌فاکتور به‌جای فاکتور معتبر پذیرفته نیست.",
            "ITEMS_NOT_PARSED": "اقلام با مقدار و واحد معتبر تشخیص داده نشدند.",
            "PRICE_OR_ITEM_EVIDENCE_MISSING": "برای برخی اقلام، کالای دقیق یا قیمت فاکتور صادرشده همین مشتری پیدا نشد.",
            "AMOUNT_NOT_ALLOWED": "مبلغ پیشنهاد معتبر نیست.",
            "REVENUE_ACCOUNT_UNAVAILABLE": "سرفصل فروش معتبر موجود نیست.",
        }
        return "پیشنهاد فاکتور متوقف شد: " + messages.get(
            proposal.get("reason"), "شواهد درخواست کافی نیست.") + " هیچ سندی ثبت نشده است."
    return ("پیشنهاد پیش‌نویس برای " + proposal["customerName"] +
            " با " + str(len(proposal["lines"])) + " قلم و جمع " +
            str(proposal["total"]) + " " + str(proposal["currency"]) +
            " آماده بررسی است. شماره/تاریخ فاکتور منبع در پیش‌نمایش درج شده؛ " +
            "تخفیف و مالیات فعلاً صفر هستند و تنها با تأیید صریح شما پیش‌نویس ذخیره می‌شود.")
