"""Explicit read-only Ollama inference for the Taraz desktop.

No online providers, business tools, journal writes, model downloads or
implicit transmission of company context. User-initiated text only.
Only loopback HTTP, never DNS, proxies or configurable remote endpoints.
"""
from __future__ import annotations

import http.client
import json
import os
import platform
import re
import shutil
import threading
from pathlib import Path

import psutil

HOST = "127.0.0.1"
PORT = 11434
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,99}$")
_SINGLE_MODEL = threading.BoundedSemaphore(1)


class LocalModelError(RuntimeError):
    pass


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
    except (OSError, TimeoutError, ValueError, UnicodeError, http.client.HTTPException) as exc:
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


def hardware_profile():
    """Actual host measurements; never guess GPU compatibility or VRAM."""
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(Path.home())
    return {
        "os": platform.system(),
        "architecture": platform.machine(),
        "cpu": platform.processor() or "Unknown",
        "logicalCpus": os.cpu_count(),
        "ramTotalBytes": memory.total,
        "ramAvailableBytes": memory.available,
        "diskFreeBytes": disk.free,
        "gpu": "Unknown",
        "vramBytes": None,
        "gpuAccelerationVerified": False,
    }


def status():
    hardware = hardware_profile()
    try:
        models = installed_models()
    except LocalModelError:
        return {"available": False, "provider": "ollama", "models": [],
                "scope": "local_text_only", "modelRan": False,
                "financialActionsEnabled": False, "hardware": hardware,
                "reason": "LOCAL_PROVIDER_UNAVAILABLE"}
    return {"available": bool(models), "provider": "ollama", "models": models,
            "scope": "local_text_only", "modelRan": False, "hardware": hardware,
            "financialActionsEnabled": False,
            "qualityVerified": False, "offlineInferenceTested": False,
            "reason": "INSTALLED_MODELS_REQUIRE_SEPARATE_QUALITY_TEST"}


def generate(model: str, prompt: str, *, manual_consent: bool):
    """One bounded manual inference; no model can call a financial tool here."""
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
    if matched[0]["bytes"] > 3_000_000_000:
        raise LocalModelError("Model exceeds cautious desktop memory budget")
    if not _SINGLE_MODEL.acquire(blocking=False):
        raise LocalModelError("A local model request is already running")
    try:
        response = _query("/api/generate", {
            "model": model,
            "system": (
                "تو یک دستیار متن محلی هستی. هیچ اختیار صدور، پرداخت، ثبت دفترکل یا "
                "اجرای عملیات مالی نداری. پاسخ غیرمطمئن را مشخص کن. "
                "هرگز تأیید انسان را جایگزین نکن."
            ),
            "prompt": prompt.strip(),
            "stream": False,
            "think": False,
            "options": {"temperature": 0.1, "num_predict": 192},
        }, timeout=45)
        answer = response.get("response")
        if (response.get("model") != model or response.get("done") is not True or
                type(answer) is not str or not answer.strip() or len(answer) > 5000):
            raise LocalModelError("Local inference is incomplete or unverifiable")
        return {"model": model, "provider": "ollama", "modelRan": True,
                "response": answer, "journalPosted": False,
                "financialActionsEnabled": False, "readCompanyData": False,
                "savedToLedger": False, "qualityVerified": False}
    finally:
        _SINGLE_MODEL.release()
