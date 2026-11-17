"""Strict online text-only AI adapter; never a financial agent.

OpenAI Chat Completions and Anthropic Messages are the ONLY supported
endpoints in v1. Configuration/credentials are owned by an authenticated
native host via the separate DPAPI vault. Nothing here reads a company book,
performs SQL, executes tools, logs, downloads models, selects models, or
automatically sends data. Both TLS health and inference require user consent.

DNS is resolved and ALL returned IPs screened before a connection is made
to a prevalidated numeric address with certificate verification/SNI for the
original allowed hostname. No proxy, redirects or custom endpoint routing.
Billing limits are CONSERVATIVE LOCAL ESTIMATES, not provider-enforced limits.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import http.client
import ipaddress
import json
import re
import socket
import ssl

from taraz_ai_online_credentials import (
    TarazOnlineAiCredentialVault, OnlineCredentialError, validate_provider,
)

_HOSTS = {"openai": "api.openai.com", "anthropic": "api.anthropic.com"}
_PATHS = {"openai": "/v1/chat/completions",
          "anthropic": "/v1/messages"}
_PORT = 443
_SOCKET_TIMEOUT = 8
_MAX_RESPONSE_BYTES = 65536
_MAX_PROMPT_BYTES = 2048
_MAX_OUTPUT_CHARACTERS = 4000
_MAX_OUTPUT_TOKENS = 64
_MAX_ESTIMATED_USD = Decimal("0.02")
_MAX_RESOLVED_ADDRESSES = 16
_SYSTEM = (
    "You only help with user-initiated nonfinancial wording and general text. "
    "Never decide about accounting, balances, invoices, payments or financial "
    "policy. You have no tools, database access or authorization to take actions. "
    "Do not claim otherwise. Answer succinctly, mention uncertainty."
)
_DENY_FINANCIAL = re.compile(
    r"\b(?:accounting|ledger|invoice|balance|bookkeep(?:ing)?|tax|payroll|"
    r"bank|transfer|payment|transaction|financial|credit\s*card|debit|"
    r"profit|expense|stock\s*trade|forex|trading|salary|revenue)\b|"
    r"(?:حسابداری|دفترکل|صورت[‌ ]?حساب|فاکتور|مالیات|پرداخت|تراکنش|"
    r"موجودی|ترازنامه|بانک|واریز|برداشت|سود|زیان|حساب\s*بانکی|حقوق\s*و\s*دستمزد)",
    re.IGNORECASE,
)
_DENY_SECRETS = re.compile(
    r"(?i)(?:\b(?:api[-_ ]?key|secret|password|bearer|access[-_ ]?token)"
    r"\b|-----BEGIN [A-Z ]+ PRIVATE KEY-----|\b\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}\b)"
)


class OnlineAiError(RuntimeError):
    """Constant-category errors only; remote responses and secrets are hidden."""


def _require_native_release() -> None:
    """Deliberate fail-closed source-only release gate for ALL direct callers.

    A JS boolean is not verified native consent. User-entered prices are not
    authoritative billing data and no aggregate budget reservation exists.
    There is no environment setting or renderer command to enable this.
    """
    raise PermissionError(
        "ONLINE_EXTERNAL_TRANSMISSION_DISABLED: verified native consent and "
        "aggregate spending controls are not implemented")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Override connect: socket target is a checked numerical IP, not DNS."""

    def __init__(self, hostname: str, address: str, *, timeout=_SOCKET_TIMEOUT):
        self._pinned_address = address
        super().__init__(hostname, _PORT, timeout=timeout,
                         context=ssl.create_default_context())

    def connect(self):
        raw = socket.create_connection((self._pinned_address, _PORT),
                                       timeout=self.timeout,
                                       source_address=self.source_address)
        try:
            # Verify both certificate chain and the fixed hostname with SNI.
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _public_address(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    if (not ip.is_global or ip.is_multicast or ip.is_unspecified or
            ip.is_reserved or ip.is_loopback or ip.is_link_local or
            ip.is_private):
        return False
    if isinstance(ip, ipaddress.IPv6Address) and (
            ip.ipv4_mapped is not None or ip.sixtofour is not None or
            ip.teredo is not None or ip.scope_id is not None):
        return False
    return True


def _resolve_public_ip(hostname: str) -> str:
    if hostname not in _HOSTS.values():
        raise OnlineAiError("UNSUPPORTED_PROVIDER_DESTINATION")
    try:
        answers = socket.getaddrinfo(hostname, _PORT,
                                     type=socket.SOCK_STREAM,
                                     proto=socket.IPPROTO_TCP)
        if not 1 <= len(answers) <= _MAX_RESOLVED_ADDRESSES:
            raise OnlineAiError("DNS_RESOLUTION_REJECTED")
        addresses = []
        for family, socket_type, protocol, _canonical, sockaddr in answers:
            if (family not in (socket.AF_INET, socket.AF_INET6) or
                    socket_type != socket.SOCK_STREAM or
                    protocol != socket.IPPROTO_TCP or
                    not isinstance(sockaddr, tuple) or len(sockaddr) < 2 or
                    sockaddr[1] != _PORT or
                    not isinstance(sockaddr[0], str) or
                    not _public_address(sockaddr[0])):
                raise OnlineAiError("DNS_RESOLUTION_REJECTED")
            if sockaddr[0] not in addresses:
                addresses.append(sockaddr[0])
        if not addresses:
            raise OnlineAiError("DNS_RESOLUTION_REJECTED")
        # Prefer IPv4 to avoid unnecessary IPv6 routing problems. ALL DNS
        # results have nevertheless been validated, including AAAA records.
        return next((a for a in addresses if ":" not in a), addresses[0])
    except OnlineAiError:
        raise
    except (OSError, ValueError, TypeError):
        raise OnlineAiError("DNS_RESOLUTION_REJECTED") from None


def _connect(provider: str):
    hostname = _HOSTS[provider]
    address = _resolve_public_ip(hostname)
    return _PinnedHTTPSConnection(hostname, address, timeout=_SOCKET_TIMEOUT)


def _consent(manual_consent: bool) -> None:
    if manual_consent is not True:
        raise PermissionError("Explicit per-request online transmission consent required")


def _vault_configuration(vault: TarazOnlineAiCredentialVault) -> dict:
    if type(vault) is not TarazOnlineAiCredentialVault:
        raise OnlineAiError("TRUSTED_HOST_VAULT_REQUIRED")
    try:
        record = vault._trusted_config()
        validate_provider(record["provider"], record["endpoint"], record["model"])
        return record
    except (KeyError, TypeError, OnlineCredentialError):
        raise OnlineAiError("PROVIDER_NOT_CONFIGURED_OR_UNREADABLE") from None


def _request_text(value: str) -> str:
    if (type(value) is not str or not value.strip() or len(value) > 1000 or
            len(value.encode("utf-8")) > _MAX_PROMPT_BYTES or
            any(ord(c) < 32 and c not in "\n\t" for c in value)):
        raise ValueError("Nonfinancial text request is missing or exceeds limits")
    if _DENY_FINANCIAL.search(value) or _DENY_SECRETS.search(value):
        raise ValueError(
            "Financial, credential-bearing or sensitive text is outside online AI scope")
    return value.strip()


def _cost_cap(max_estimated_usd: str) -> Decimal:
    if (type(max_estimated_usd) is not str or not
            re.fullmatch(r"0\.0[0-2](?:[0-9]{0,4})?", max_estimated_usd)):
        raise ValueError("Invalid small per-request estimate cap")
    try:
        amount = Decimal(max_estimated_usd)
    except InvalidOperation:
        raise ValueError("Invalid per-request estimate cap") from None
    if not Decimal("0.001") <= amount <= _MAX_ESTIMATED_USD:
        raise ValueError("Requested estimate cap exceeds safety ceiling")
    return amount


def _estimated_price(input_tokens: int, output_tokens: int,
                     config: dict) -> Decimal:
    return ((Decimal(config["inputUsdPerMillion"]) * input_tokens +
             Decimal(config["outputUsdPerMillion"]) * output_tokens) /
            Decimal(1_000_000))


def _parse_usage(data, *, input_key, output_key):
    if (type(data) is not dict or
            not {input_key, output_key}.issubset(data)):
        raise OnlineAiError("PROVIDER_USAGE_UNVERIFIED")
    first, second = data[input_key], data[output_key]
    if (type(first) is not int or type(second) is not int or first < 0 or
            second < 0 or first > 20000 or second > 20000):
        raise OnlineAiError("PROVIDER_USAGE_UNVERIFIED")
    return first, second


def _provider_payload(config: dict, text: str) -> dict:
    if config["provider"] == "openai":
        return {
            "model": config["model"], "stream": False,
            "max_completion_tokens": _MAX_OUTPUT_TOKENS,
            "messages": [{"role": "system", "content": _SYSTEM},
                         {"role": "user", "content": text}],
        }
    return {
        "model": config["model"], "stream": False,
        "max_tokens": _MAX_OUTPUT_TOKENS,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": text}],
    }


def _headers(config: dict) -> dict:
    # Never persist, print or log the key. In-memory only for this one call.
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config["provider"] == "openai":
        headers["Authorization"] = "Bearer " + config["apiKey"]
    else:
        headers["x-api-key"] = config["apiKey"]
        headers["anthropic-version"] = "2023-06-01"
    return headers


def _post(config: dict, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(body) > 8192:
        raise OnlineAiError("REQUEST_SIZE_LIMIT")
    connection = None
    try:
        connection = _connect(config["provider"])
        connection.request("POST", _PATHS[config["provider"]],
                           body=body, headers=_headers(config))
        result = connection.getresponse()
        if 300 <= result.status <= 399:
            raise OnlineAiError("PROVIDER_REDIRECT_REFUSED")
        if result.status != 200:
            raise OnlineAiError("PROVIDER_REJECTED_REQUEST")
        content_type = result.getheader("Content-Type", "")
        content_encoding = result.getheader("Content-Encoding", "identity")
        if (type(content_type) is not str or
                content_type.split(";", 1)[0].strip().lower() != "application/json" or
                type(content_encoding) is not str or
                content_encoding.lower() != "identity"):
            raise OnlineAiError("UNSUPPORTED_PROVIDER_RESPONSE")
        raw = result.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise OnlineAiError("PROVIDER_RESPONSE_SIZE_LIMIT")
        parsed = json.loads(raw.decode("utf-8"))
        if type(parsed) is not dict:
            raise OnlineAiError("UNSUPPORTED_PROVIDER_RESPONSE")
        return parsed
    except OnlineAiError:
        raise
    except (OSError, TimeoutError, ValueError, UnicodeError,
            http.client.HTTPException, ssl.SSLError):
        raise OnlineAiError("PROVIDER_TRANSPORT_OR_RESPONSE_FAILURE") from None
    finally:
        if connection is not None:
            connection.close()


def _result(provider: str, data: dict):
    if provider == "openai":
        choices = data.get("choices")
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
            raise OnlineAiError("PROVIDER_CONTENT_UNVERIFIED")
        choice = choices[0]
        message = choice.get("message")
        if (choice.get("finish_reason") != "stop" or type(message) is not dict or
                message.get("role") != "assistant" or
                "tool_calls" in message or "function_call" in message or
                type(message.get("content")) is not str):
            raise OnlineAiError("PROVIDER_CONTENT_UNVERIFIED")
        text = message["content"]
        usage = _parse_usage(data.get("usage"), input_key="prompt_tokens",
                             output_key="completion_tokens")
    else:
        parts = data.get("content")
        if (data.get("stop_reason") != "end_turn" or type(parts) is not list or
                not 1 <= len(parts) <= 8 or
                any(type(item) is not dict or item.get("type") != "text" or
                    type(item.get("text")) is not str for item in parts)):
            raise OnlineAiError("PROVIDER_CONTENT_UNVERIFIED")
        text = "".join(p["text"] for p in parts)
        usage = _parse_usage(data.get("usage"), input_key="input_tokens",
                             output_key="output_tokens")
    if not text.strip() or len(text) > _MAX_OUTPUT_CHARACTERS:
        raise OnlineAiError("PROVIDER_CONTENT_UNVERIFIED")
    return text, usage


def configured_status(vault: TarazOnlineAiCredentialVault) -> dict:
    """Read only local vault metadata; does not contact any online endpoint."""
    if type(vault) is not TarazOnlineAiCredentialVault:
        raise OnlineAiError("TRUSTED_HOST_VAULT_REQUIRED")
    try:
        info = vault.metadata()
    except OnlineCredentialError:
        raise OnlineAiError("PROVIDER_NOT_CONFIGURED_OR_UNREADABLE") from None
    return {**info, "providerHealthVerified": False,
            "credentialsVerified": False, "financialActionsEnabled": False,
            "remoteRequestMade": False}


def health_check(vault: TarazOnlineAiCredentialVault, *,
                 manual_consent: bool) -> dict:
    """Consent-gated DNS/TLS-only probe. Never transmits API key or prompt."""
    _consent(manual_consent)
    _require_native_release()
    config = _vault_configuration(vault)
    connection = None
    try:
        connection = _connect(config["provider"])
        connection.connect()  # TLS verification/SNI; no HTTP authorization header.
        return {"provider": config["provider"], "tlsReachable": True,
                "credentialsVerified": False, "providerHealthVerified": False,
                "requestBilled": False, "financialActionsEnabled": False}
    except OnlineAiError:
        raise
    except (OSError, TimeoutError, ValueError, ssl.SSLError):
        raise OnlineAiError("PROVIDER_TLS_UNAVAILABLE") from None
    finally:
        if connection is not None:
            connection.close()


def generate(vault: TarazOnlineAiCredentialVault, text: str, *,
             manual_consent: bool, max_estimated_usd: str = "0.02") -> dict:
    """One external, user-consented, nonfinancial text request (NO tools)."""
    _consent(manual_consent)
    _require_native_release()
    prompt = _request_text(text)
    cap = _cost_cap(max_estimated_usd)
    config = _vault_configuration(vault)
    payload = _provider_payload(config, prompt)
    # UTF-8 bytes + reserved protocol/tokenizer overhead is a conservative
    # estimate, NOT a contract with the provider's actual billing tokenizer.
    preflight_input = len((_SYSTEM + prompt).encode("utf-8")) + 512
    preflight = _estimated_price(preflight_input, _MAX_OUTPUT_TOKENS, config)
    if preflight > cap:
        raise OnlineAiError("LOCAL_ESTIMATED_COST_CAP_EXCEEDED")
    response = _post(config, payload)
    answer, (input_tokens, output_tokens) = _result(config["provider"], response)
    amount = _estimated_price(input_tokens, output_tokens, config)
    if amount > cap:
        # A refusal cannot reverse already-incurred remote charges.
        raise OnlineAiError("REPORTED_USAGE_EXCEEDS_ESTIMATED_COST_CAP")
    return {
        "provider": config["provider"], "model": config["model"],
        "response": answer, "modelRan": True,
        "externalTransmission": True, "manualConsent": True,
        "inputTokensReported": input_tokens,
        "outputTokensReported": output_tokens,
        "estimatedCostUsd": str(amount.quantize(Decimal("0.000001"))),
        "maxEstimatedCostUsd": str(cap),
        "providerEnforcesCostCap": False, "pricingVerifiedByProvider": False,
        "financialActionsEnabled": False, "financialDecisionAuthority": False,
        "readCompanyData": False, "journalPosted": False,
        "savedToLedger": False, "toolCallsEnabled": False,
        "qualityVerified": False,
    }


__all__ = ["OnlineAiError", "configured_status", "health_check", "generate"]
