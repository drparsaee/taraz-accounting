"""Bounded, local Ollama hints for order intake; no persistence or side effects.

Only a user-initiated text request reaches the fixed loopback Ollama endpoint.
Output is advisory form data requiring explicit user review and save. The
module never reads customers, accounting data, orders, credentials or files.
"""
from __future__ import annotations

import http.client
import json
import re


LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 11434
LOCAL_PATH = "/api/generate"
MODEL = "qwen3:4b"
TIMEOUT_SECONDS = 45
MAX_TEXT_CHARS = 4000
MAX_REQUEST_BYTES = 16000
MAX_RESPONSE_BYTES = 24000
_STAGES = frozenset(("print", "bindery", "laser", "packaging", "shipping",
                     "material", "other"))
# Text evidence is required for every suggested kind. An allowed enum value
# alone does not establish that the customer requested the production stage.
_STAGE_EVIDENCE = {
    "print": re.compile(r"چاپ|افست|دیجیتال"),
    "bindery": re.compile(r"صحافی|دوخت|منگنه|سیم(?:ی|ی\s*کردن)"),
    "laser": re.compile(r"لیزر|laser", re.I),
    "packaging": re.compile(r"بسته\s*[‌-]?\s*بندی|بسته\s*کردن"),
    "shipping": re.compile(r"حمل|ارسال|باربری|پست|تحویل"),
    "material": re.compile(r"مواد\s*اولیه|تهیه\s*متریال|خرید\s*(?:کاغذ|مقوا|ورق)"),
    "other": re.compile(r"سایر\s*خدمات|خدمات\s*متفرقه"),
}
_FIELDS = {"customerName": 120, "title": 200, "quantity": 18,
           "productionQuantity": 18, "unit": 32}
_MISSING = {"customerName": "نام مشتری", "title": "شرح سفارش",
            "quantity": "تعداد سفارش", "productionQuantity": "تعداد تولید برنامه‌ای"}


class SuggestionUnavailable(RuntimeError):
    """No trustworthy local inference result could be obtained."""


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate response object key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Non-JSON numeric constant")


def _strict_json(raw):
    return json.loads(raw, object_pairs_hook=_reject_duplicate_keys,
                      parse_constant=_reject_constant)


def _redact(text: str) -> str:
    """Avoid sending obvious credentials/contact data even to the local model."""
    if "-----BEGIN " in text or "-----END " in text:
        raise ValueError("Credential material is not a valid order description")
    text = re.sub(r"(?i)\b(?:bearer)\s+[A-Za-z0-9._~+/-]+", "[REDACTED]", text)
    text = re.sub(
        r"(?im)\b(?:password|passphrase|secret|token|api[_ -]?key|رمز|گذرواژه)\s*[:=]\s*\S+",
        "[REDACTED]", text)
    text = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
                  "[CONTACT]", text)
    text = re.sub(r"(?i)https?://\S+", "[LINK]", text)
    return text


def _source_ascii(source: str) -> str:
    return source.translate(str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def _grounded_text(value: str, source: str) -> str:
    value = value.strip()
    if not value:
        return ""
    # The local model may summarize, but only verbatim user-provided values
    # qualify as populated party/title/unit fields.
    return value if " ".join(value.casefold().split()) in " ".join(
        source.casefold().split()) else ""


def _quantity(value, source: str, *, production: bool = False) -> str:
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,7}", value):
        return ""
    if int(value) > 10_000_000:
        return ""
    # Require the value to be present explicitly in the user's text. Never
    # extrapolate quantities or manufacture a production waste allowance.
    source_ascii = _source_ascii(source)
    appearances = list(re.finditer(
        r"(?<!\d)" + re.escape(value) + r"(?!\d)", source_ascii))
    for item in appearances:
        before = source_ascii[max(0, item.start() - 30):item.start()]
        after = source_ascii[item.end():item.end() + 24]
        if production:
            if (re.search(r"(?:تعداد\s*)?(?:تولید|تیراژ\s*تولید)\s*[:：]?\s*$", before)
                    or re.match(r"\s*(?:عدد\s*)?تولید", after)):
                return value
        else:
            if re.search(r"(?:تولید|تیراژ\s*تولید)\s*[:：]?\s*$", before):
                continue
            if (re.search(r"(?:تعداد(?:\s*(?:سفارش|فروش))?|مقدار\s*سفارش|تیراژ)\s*[:：]?\s*$", before)
                    or re.match(r"\s*(?:عدد|برگ|نسخه|متر(?:\s*مربع)?|کیلوگرم|جعبه|بروشور|کارتن)(?:\b|\s|$)", after)):
                return value
    return ""


def _validate_result(content, redacted_text: str) -> dict:
    if not isinstance(content, str) or len(content) > MAX_RESPONSE_BYTES:
        raise SuggestionUnavailable("Local suggestion response is invalid")
    try:
        parsed = _strict_json(content)
    except (ValueError, TypeError) as exc:
        raise SuggestionUnavailable("Local suggestion response is not strict JSON") from exc
    if (type(parsed) is not dict or set(parsed) != {"fields", "suggestedStages", "warnings"}
            or type(parsed["fields"]) is not dict
            or set(parsed["fields"]) != set(_FIELDS)
            or type(parsed["suggestedStages"]) is not list
            or type(parsed["warnings"]) is not list):
        raise SuggestionUnavailable("Local suggestion schema mismatch")

    fields = {}
    for field, maximum in _FIELDS.items():
        value = parsed["fields"][field]
        if field in ("quantity", "productionQuantity"):
            fields[field] = _quantity(value, redacted_text,
                                      production=field == "productionQuantity")
        elif type(value) is str and len(value) <= maximum and not any(
                ord(ch) < 32 or ord(ch) == 127 for ch in value):
            fields[field] = _grounded_text(value, redacted_text)
        else:
            raise SuggestionUnavailable("Local suggestion contains invalid fields")

    if (len(parsed["suggestedStages"]) > 7 or
            any(type(stage) is not str or stage not in _STAGES
                for stage in parsed["suggestedStages"]) or
            len(set(parsed["suggestedStages"])) != len(parsed["suggestedStages"])):
        raise SuggestionUnavailable("Local suggestion contains unsupported stages")
    # Reject the entire response on a single fabricated stage. Merely
    # dropping ungrounded stages would incorrectly mark a nonsensical list
    # containing every allowed kind as successful model inference.
    if any(not _STAGE_EVIDENCE[stage].search(redacted_text)
           for stage in parsed["suggestedStages"]):
        raise SuggestionUnavailable("Local suggestion contains ungrounded stages")
    if not any(fields.values()) and not parsed["suggestedStages"]:
        raise SuggestionUnavailable("Local suggestion contains no grounded order information")
    if (len(parsed["warnings"]) > 5 or
            any(type(warning) is not str or len(warning) > 180 or not warning.strip()
                for warning in parsed["warnings"])):
        raise SuggestionUnavailable("Local suggestion warnings invalid")
    missing = [caption for field, caption in _MISSING.items() if not fields[field]]
    return {
        "fields": fields, "suggestedStages": parsed["suggestedStages"],
        "missing": missing, "warnings": parsed["warnings"],
        "source": "LOCAL_OLLAMA", "model": MODEL,
        "modelRan": True, "externalModelCalled": False,
        "financialEventCreated": False,
    }


def suggest_order(text: str) -> dict:
    """Give user-reviewable hints from a real local qwen3:4b model.

    Errors are explicit. Never return a rule-based result labeled as model-run.
    """
    if (type(text) is not str or not text.strip() or len(text) > MAX_TEXT_CHARS
            or any(ord(ch) < 32 and ch not in "\r\n\t" for ch in text)):
        raise ValueError("Order description must be 1..4000 printable characters")
    description = _redact(text.strip())
    # Ollama's JSON-schema chat route has repeatedly stalled on this device.
    # Use the measured, working bounded generate/format=json route; the Python
    # validator below remains the authoritative strict schema gate.
    prompt = (
        'Extract Persian order data. JSON ONLY with EXACT keys: '
        '{"fields":{"customerName":"","title":"","quantity":"",'
        '"productionQuantity":"","unit":""},"suggestedStages":[],'
        '"warnings":[]}. Copy explicit values only; unknown = "". '
        'Stages: print,bindery,laser,packaging,shipping,material,other. '
        'No actions. Input data:\n' + description
    )
    request = {
        "model": MODEL, "prompt": prompt, "stream": False, "think": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 80, "num_ctx": 512},
    }
    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("Order description is too long")

    connection = None
    try:
        connection = http.client.HTTPConnection(LOCAL_HOST, LOCAL_PORT, timeout=TIMEOUT_SECONDS)
        connection.request("POST", LOCAL_PATH, body=payload,
                           headers={"Content-Type": "application/json",
                                    "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200 or not response.getheader("Content-Type", "").lower().startswith("application/json"):
            raise SuggestionUnavailable("Local Ollama service returned an invalid response")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SuggestionUnavailable("Local Ollama response exceeds size limit")
        envelope = _strict_json(raw.decode("utf-8"))
        if (type(envelope) is not dict or envelope.get("model") != MODEL or
                envelope.get("done") is not True or
                type(envelope.get("response")) is not str):
            raise SuggestionUnavailable("Local Ollama response schema mismatch")
        return _validate_result(envelope["response"], description)
    except (OSError, TimeoutError, UnicodeError, ValueError,
            http.client.HTTPException) as exc:
        if isinstance(exc, SuggestionUnavailable):
            raise
        raise SuggestionUnavailable("Local Ollama model unavailable or invalid") from exc
    finally:
        if connection is not None:
            connection.close()


__all__ = ["suggest_order", "SuggestionUnavailable"]
