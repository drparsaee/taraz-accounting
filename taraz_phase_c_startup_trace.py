"""PRIVATE QA metadata-only startup trace for a disposable Taraz profile.

Never attach to installed accounts. The source is inert unless all profile
guards pass. Trace contains only whitelisted method/phase names, event codes,
times and exception CLASS names; never credentials, arguments, payloads, SQL,
document content, response bodies, JS source or filesystem values.
"""
from __future__ import annotations

from functools import wraps
import json
import os
from pathlib import Path
import re
from threading import Lock, get_ident
import time


METHODS = frozenset((
    "standaloneAccountingRead",
    "standaloneAccountingParsianCompany",
    "standaloneAccountingTemplateList",
))
TEMPLATE_KINDS = frozenset(("entry", "print", "issuer", "brand"))
_RETURN_CALLBACK = re.compile(
    r'^window\.pywebview\._returnValuesCallbacks\["'
    r'(standaloneAccountingRead|standaloneAccountingParsianCompany|'
    r'standaloneAccountingTemplateList)'  # method only; callback value is ignored
    r'"\]\["')


def private_trace_path(env=None):
    e = os.environ if env is None else env
    if e.get("TARAZ_QA_MODE") != "1" or e.get("PHASE_C_TARAZ_TRACE") != "1":
        return None
    a_value, b_value = e.get("APPDATA"), e.get("LOCALAPPDATA")
    qa = e.get("TARAZ_QA_DATA_DIR")
    if not a_value or not b_value or not qa:
        return None
    a, b, book = Path(a_value), Path(b_value), Path(qa)
    if not all(path.is_absolute() and not path.is_symlink()
               for path in (a, b, book)):
        return None
    if a.name != "APPDATA" or b.name != "LOCALAPPDATA" or a.parent != b.parent:
        return None
    root = a.parent
    if (root.parent.name != "qa-runtime" or
            root.parent.parent.name != "phase-c-frozen-close-gate-qa" or
            not root.parent.parent.is_dir() or
            not root.is_dir() or
            book.resolve() != (a / "Taraz").resolve()):
        return None
    return root / "TARAZ_NATIVE_STARTUP_TRACE.jsonl"


class NativeStartupTrace:
    def __init__(self, destination):
        self.path = Path(destination)
        self._lock = Lock()
        self._sequence = 0
        if self.path.exists() or self.path.is_symlink():
            raise PermissionError("QA trace must be a fresh create-only file")
        # Create-only avoids modifying any existing evidence.
        self.path.open("x", encoding="utf8").close()

    def event(self, method, phase, *, kind=None, error=None):
        if method not in METHODS and method != "__startup__":
            raise ValueError("Unsupported trace method")
        if not isinstance(phase, str) or not re.fullmatch(r"[a-z_]{2,48}", phase):
            raise ValueError("Unsupported phase")
        row = {"timeUnixMs": time.time_ns() // 1_000_000,
               "monotonicNs": time.monotonic_ns(), "threadId": get_ident(),
               "method": method, "phase": phase}
        if kind in TEMPLATE_KINDS:
            row["kind"] = kind
        if error is not None:
            row["errorClass"] = type(error).__name__
        with self._lock:
            self._sequence += 1
            row["sequence"] = self._sequence
            with self.path.open("a", encoding="utf8") as destination:
                destination.write(json.dumps(row, separators=(",", ":")) + "\n")
                destination.flush()
                os.fsync(destination.fileno())

    def wrap_api(self, api):
        for method in METHODS:
            original = getattr(api, method)

            @wraps(original)
            def decorated(*args, __original=original, __method=method, **kwargs):
                # Only public template category labels are included.
                kind = (args[0] if __method == "standaloneAccountingTemplateList"
                        and args and type(args[0]) is str else None)
                self.event(__method, "python_enter", kind=kind)
                try:
                    result = __original(*args, **kwargs)
                except BaseException as error:
                    self.event(__method, "python_error", kind=kind, error=error)
                    raise
                self.event(__method, "python_return", kind=kind)
                return result

            setattr(api, method, decorated)

    def wrap_window(self, window):
        original = window.evaluate_js

        @wraps(original)
        def evaluated(javascript, *args, **kwargs):
            # The returned JS snippet contains ledger data. Inspect only its
            # literal prefix; never write/hash/echo the script or its result.
            found = _RETURN_CALLBACK.match(javascript) if type(javascript) is str else None
            method = found.group(1) if found else None
            if method:
                self.event(method, "evaluate_js_enter")
            try:
                result = original(javascript, *args, **kwargs)
            except BaseException as error:
                if method:
                    self.event(method, "evaluate_js_error", error=error)
                raise
            if method:
                # Return of evaluate_js does not prove that the JS Promise
                # resolved; the in-page phase trace is authoritative there.
                self.event(method, "evaluate_js_return")
            return result

        window.evaluate_js = evaluated


def install_private_trace(api, data, *, env=None):
    destination = private_trace_path(env)
    if destination is None:
        return None
    # Only a company book under fresh isolated roaming APPDATA is authorized.
    data = Path(data).resolve()
    book = Path((os.environ if env is None else env)["TARAZ_QA_DATA_DIR"]).resolve()
    if data != book and data.parent.parent != book:
        raise PermissionError("Trace cannot observe a non-QA ledger")
    trace = NativeStartupTrace(destination)
    trace.wrap_api(api)
    trace.event("__startup__", "native_trace_ready")
    return trace
