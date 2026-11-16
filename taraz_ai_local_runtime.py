"""Explicit read-only Ollama inference for the Taraz desktop.

No online providers, business tools, journal writes, model downloads or
implicit transmission of company context. User-initiated text only.
Only loopback HTTP, never DNS, proxies or configurable remote endpoints.
"""
from __future__ import annotations

import ctypes
import http.client
import json
import os
import platform
import re
import shutil
import threading
from pathlib import Path

HOST = "127.0.0.1"
PORT = 11434
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,99}$")
_SINGLE_MODEL = threading.BoundedSemaphore(1)
# A bounded CPU-only text path, not a benchmark or a financial decision engine.
# Keep the same explicitly selected installed model even on a timeout.
_CPU_MODEL_MAX_BYTES = 1_500_000_000
_CPU_CTX_TOKENS = 512
_CPU_PREDICT_TOKENS = 32
_CPU_FALLBACK_TOKENS = 12
_CPU_TIMEOUT_SECONDS = 12
_CPU_FALLBACK_TIMEOUT_SECONDS = 7
_RAM_HEADROOM_BYTES = 1_000_000_000


class LocalModelError(RuntimeError):
    pass


class LocalModelTimeout(LocalModelError):
    """A timed-out local request; permits at most one smaller same-model retry."""


def _query(path: str, payload: dict | None = None, *, timeout: float = 4):
    if path not in ("/api/tags", "/api/generate"):
        raise LocalModelError("Unsupported local model operation")
    connection = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        body = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if payload is not None else None)
        connection.request("POST" if body is not None else "GET", path, body=body,
                           headers={"Content-Type": "application/json", "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise LocalModelError("Local model runtime rejected request")
        raw = response.read(65537)
        if len(raw) > 65536:
            raise LocalModelError("Local model response exceeds byte limit")
        decoded = json.loads(raw.decode("utf-8"))
        if type(decoded) is not dict:
            raise LocalModelError("Invalid local model response")
        return decoded
    except TimeoutError as exc:
        raise LocalModelTimeout("Local Ollama request exceeded its socket timeout") from exc
    except (OSError, ValueError, UnicodeError, http.client.HTTPException) as exc:
        raise LocalModelError("Local Ollama runtime unavailable or invalid response") from exc
    finally:
        connection.close()


def installed_models():
    """GET-only discovery, no model loading or user data transmission."""
    result = _query("/api/tags")
    entries = result.get("models")
    if type(entries) is not list or len(entries) > 100:
        raise LocalModelError("Invalid local model inventory")
    models = []
    seen = set()
    for item in entries:
        if type(item) is not dict:
            raise LocalModelError("Invalid local model inventory entry")
        name, size = item.get("name"), item.get("size")
        if (type(name) is not str or not _NAME.fullmatch(name) or
                type(size) is not int or size <= 0 or size > 200_000_000_000 or name in seen):
            raise LocalModelError("Invalid installed model metadata")
        seen.add(name)
        models.append({"name": name, "bytes": size})
    return models


class _MemoryStatus(ctypes.Structure):
    """Win32 MEMORYSTATUSEX; avoids a third-party dependency in frozen hosts."""

    _fields_ = [
        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _memory_bytes():
    """(total, available) measured by Windows, or fail closed if unavailable."""
    if os.name != "nt":
        raise LocalModelError("Windows host RAM measurement is required")
    values = _MemoryStatus()
    values.dwLength = ctypes.sizeof(values)
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MemoryStatus)]
        kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
        success = kernel32.GlobalMemoryStatusEx(ctypes.byref(values))
    except (OSError, AttributeError) as exc:
        raise LocalModelError("Windows host RAM measurement failed") from exc
    if not success or values.ullTotalPhys <= 0 or values.ullAvailPhys > values.ullTotalPhys:
        raise LocalModelError("Windows host RAM measurement is invalid")
    return int(values.ullTotalPhys), int(values.ullAvailPhys)


def hardware_profile():
    """Actual host measurements; never guess GPU compatibility or VRAM."""
    try:
        total_ram, available_ram = _memory_bytes()
    except LocalModelError:
        total_ram, available_ram = None, None
    disk = shutil.disk_usage(Path.home())
    return {
        "os": platform.system(),
        "architecture": platform.machine(),
        "cpu": platform.processor() or "Unknown",
        "logicalCpus": os.cpu_count(),
        "ramTotalBytes": total_ram,
        "ramAvailableBytes": available_ram,
        "diskFreeBytes": disk.free,
        "gpu": "Unknown",
        "vramBytes": None,
        "gpuAccelerationVerified": False,
    }


def _qos_policy():
    """Explain the executable safeguards, not model quality or GPU capacity."""
    return {
        "execution": "cpu_only",
        "gpuAccelerationVerified": False,
        "contextTokens": _CPU_CTX_TOKENS,
        "maxPredictionTokens": _CPU_PREDICT_TOKENS,
        "fallbackPredictionTokens": _CPU_FALLBACK_TOKENS,
        "socketTimeoutSeconds": _CPU_TIMEOUT_SECONDS,
        "fallbackSocketTimeoutSeconds": _CPU_FALLBACK_TIMEOUT_SECONDS,
        "maxModelBytes": _CPU_MODEL_MAX_BYTES,
        "automaticModelSelection": False,
        "automaticDownloads": False,
        "manualConsentRequired": True,
        "financialDecisionAuthority": False,
    }


def status():
    hardware = hardware_profile()
    try:
        models = installed_models()
    except LocalModelError:
        return {"available": False, "provider": "ollama", "models": [],
                "scope": "local_text_only", "modelRan": False,
                "financialActionsEnabled": False, "hardware": hardware,
                "qualityVerified": False, "offlineInferenceTested": False,
                "inferencePolicy": _qos_policy(),
                "reason": "LOCAL_PROVIDER_UNAVAILABLE"}
    return {"available": bool(models), "provider": "ollama", "models": models,
            "scope": "local_text_only", "modelRan": False, "hardware": hardware,
            "financialActionsEnabled": False,
            "inferencePolicy": _qos_policy(),
            "qualityVerified": False, "offlineInferenceTested": False,
            "reason": "INSTALLED_MODELS_REQUIRE_SEPARATE_QUALITY_TEST"}


def generate(model: str, prompt: str, *, manual_consent: bool):
    """One manually selected model; conservative CPU-only, nonfinancial text.

    A socket timeout can trigger ONE smaller same-model request. No hidden
    downloads, alternate model, GPU scheduling, company data, persistence or
    finance authority. Socket timeouts are per blocking operation and are not
    a mathematically strict whole-request wall-clock deadline.
    """
    if manual_consent is not True:
        raise PermissionError("Explicit local model request required")
    if (type(model) is not str or not _NAME.fullmatch(model) or
            type(prompt) is not str or not 1 <= len(prompt.strip()) <= 600 or
            len(prompt.encode("utf-8")) > 2400 or
            any(ord(char) < 32 and char not in "\n\t" for char in prompt)):
        raise ValueError("Model or local prompt invalid")
    installed = installed_models()
    matched = [m for m in installed if m["name"] == model]
    if len(matched) != 1:
        raise LocalModelError("Selected model is not already installed")
    if matched[0]["bytes"] > _CPU_MODEL_MAX_BYTES:
        raise LocalModelError(
            "Selected model is too large for conservative CPU-only text inference; "
            "choose a smaller installed model manually")
    _, available_ram = _memory_bytes()
    if available_ram < max(
            _RAM_HEADROOM_BYTES, matched[0]["bytes"] * 2):
        raise LocalModelError(
            "Insufficient currently available RAM for conservative CPU-only inference")
    if not _SINGLE_MODEL.acquire(blocking=False):
        raise LocalModelError("A local model request is already running")
    try:
        payload = {
            "model": model,
            "system": (
                "تو فقط دستیار محلی متن غیرمالی هستی. کوتاه و دقیق پاسخ بده. "
                "هیچ تصمیم یا عملیات مالی، صدور سند، پرداخت یا ثبت دفترکل انجام نده. "
                "برای امور مالی صلاحیت نداری؛ عدم اطمینان را مشخص کن."
            ),
            "prompt": prompt.strip(),
            "stream": False,
            "think": False,
            "options": {"temperature": 0.1, "num_gpu": 0,
                        "num_ctx": _CPU_CTX_TOKENS,
                        "num_predict": _CPU_PREDICT_TOKENS},
        }
        fallback_used = False
        try:
            response = _query("/api/generate", payload,
                              timeout=_CPU_TIMEOUT_SECONDS)
        except LocalModelTimeout:
            # A lighter request to the same manually chosen model can succeed
            # after initial cold-start timeout. Never retry malformed replies,
            # authorization errors, missing models or other transport failures.
            fallback_used = True
            fallback = {**payload, "options": {
                **payload["options"], "num_predict": _CPU_FALLBACK_TOKENS}}
            response = _query("/api/generate", fallback,
                              timeout=_CPU_FALLBACK_TIMEOUT_SECONDS)
        answer = response.get("response")
        if (response.get("model") != model or response.get("done") is not True or
                type(answer) is not str or not answer.strip() or len(answer) > 5000):
            raise LocalModelError("Local inference is incomplete or unverifiable")
        return {"model": model, "provider": "ollama", "modelRan": True,
                "response": answer, "journalPosted": False,
                "financialActionsEnabled": False, "readCompanyData": False,
                "savedToLedger": False, "qualityVerified": False,
                "financialDecisionAuthority": False,
                "inferencePolicy": {
                    "execution": "cpu_only",
                    "outputMayBeTruncated": response.get("done_reason") == "length",
                    "contextTokens": _CPU_CTX_TOKENS,
                    "predictionTokenLimit": (
                        _CPU_FALLBACK_TOKENS if fallback_used
                        else _CPU_PREDICT_TOKENS),
                    "fallbackUsed": fallback_used,
                    "socketTimeoutSeconds": (
                        _CPU_FALLBACK_TIMEOUT_SECONDS if fallback_used
                        else _CPU_TIMEOUT_SECONDS),
                }}
    finally:
        _SINGLE_MODEL.release()
