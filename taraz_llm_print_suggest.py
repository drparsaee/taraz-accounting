"""Optional on-device AI for print-layout suggestions, never a financial action.

Only the instruction is sent to a fixed loopback Ollama model. Customer, company,
ledger and invoice data are neither accepted nor transmitted by this endpoint.
"""
from __future__ import annotations

import json
import re
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

_OLLAMA = "http://127.0.0.1:11434/api/generate"
# The 4B model repeatedly timed out on this workstation. The 0.6B model
# returned independently validated layout JSON in two actual local runs.
# It only proposes a small, allowlisted set of visual choices.
_MODEL = "qwen3:0.6b"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_FIELDS = frozenset({"page", "orientation", "font", "color"})


class _NoRedirect(HTTPRedirectHandler):
    """An HTTP redirect must never turn a loopback request into external traffic."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Explicitly bypass system/environment HTTP proxies and refuse redirects.
# Without this, urllib can send a 127.0.0.1 prompt through a configured proxy.
urlopen = build_opener(ProxyHandler({}), _NoRedirect()).open

class PrintSuggestionUnavailable(RuntimeError):
    pass


def suggest_print_layout(prompt_text: str) -> dict:
    """Return a *suggestion* only. The caller must show and explicitly apply it."""
    if not isinstance(prompt_text, str) or not 1 <= len(prompt_text.strip()) <= 500:
        raise ValueError("Print layout instruction must be 1..500 characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in prompt_text):
        raise ValueError("Invalid print instruction")
    safe_instruction = ("Return only JSON with exactly four keys: "
        "page (A4 or A5), orientation (portrait or landscape), "
        "font (Vazirmatn, Tahoma or Arial), color (#RRGGBB). "
        "No explanation. Invoice style request: " + prompt_text.strip())
    body = {"model": _MODEL, "stream": False, "think": False,
            "format": "json", "prompt": safe_instruction,
            "keep_alive": "15m",
            "options": {"temperature": 0, "num_predict": 80, "num_ctx": 512}}
    request = Request(_OLLAMA, data=json.dumps(body,ensure_ascii=False).encode('utf-8'),
                      headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urlopen(request, timeout=60) as response:
            data=response.read(16385)
        if len(data)>16384: raise PrintSuggestionUnavailable("Oversized model response")
        packet=json.loads(data)
        if (type(packet) is not dict or packet.get("model") != _MODEL
                or type(packet.get("response")) is not str
                or packet.get("done") is not True
                or packet.get("done_reason") != "stop"):
            raise PrintSuggestionUnavailable("Untrusted or truncated local model output")
        raw=packet["response"]
        if not isinstance(raw,str) or len(raw)>4096:
            raise PrintSuggestionUnavailable("Model response missing or oversized")
        layout=json.loads(raw)
    except PrintSuggestionUnavailable:
        raise
    except (OSError, TimeoutError, ValueError, TypeError, KeyError, UnicodeError) as error:
        raise PrintSuggestionUnavailable("Local print model unavailable or invalid result") from error
    if not isinstance(layout,dict) or set(layout)!=_FIELDS or (
        layout["page"] not in ("A4","A5") or
        layout["orientation"] not in ("portrait","landscape") or
        layout["font"] not in ("Vazirmatn","Tahoma","Arial") or
        not isinstance(layout["color"],str) or not _HEX.fullmatch(layout["color"])):
        raise PrintSuggestionUnavailable("Local print model returned unsupported layout")
    return {"layout":layout,"source":"LOCAL_OLLAMA","modelRan":True,
            "externalModelCalled":False,"financialEventCreated":False,
            "requiresUserApproval":True}
