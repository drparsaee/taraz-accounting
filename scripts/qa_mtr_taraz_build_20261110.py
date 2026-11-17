"""Build a non-release Taraz QA EXE from the current, isolated source snapshot.

Output and tool caches are confined to a unique D:\\CoS-Test QA directory.
The installed Taraz, actual accounting profile, repo node_modules and release
outputs are never used as build destinations. The EXE is NEVER launched here.
"""

from __future__ import annotations

import hashlib
import json
import marshal
import os
from pathlib import Path
import shutil
import subprocess
import sys
import types
import uuid


SOURCE = Path(__file__).resolve().parents[1]
QA_PARENT = SOURCE.parents[1] / "MTR-TARAZ-QA-BUNDLE-20261110"
TRUSTED_MODULES = (
    # The reviewed source's own lockfile-pinned dependencies must win over an
    # older sibling checkout. A sibling may lack newly adopted Sileo entirely.
    SOURCE / "node_modules",
    SOURCE.parent / "taraz-accounting-desktop" / "node_modules",
    SOURCE.parents[1] / "000- Madar" / "madar-p2-gantt-notifications-20261107" / "node_modules",
)
MANDATORY_SOURCES = (
    "src/taraz_madar_invoice_draft.js",
    "src/taraz_settings.jsx",
    "src/standalone_accounting_workspace.jsx",
    "taraz_desktop.py",
    "taraz_integration.py",
    "accounting.html",
    "vite.config.js",
)
UI_PHRASE = "آماده‌سازی پیش‌نویس فروش"
INBOX_METHODS = ("tarazIntegrationList", "tarazIntegrationReview", "tarazIntegrationRecover")


class QABuildBlocked(RuntimeError):
    pass


def _no_link(path: Path) -> None:
    if path.is_symlink() or (path.exists() and
            bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)):
        raise QABuildBlocked(f"Unsafe linked/junction path: {path}")


def _tree_fingerprint(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for folder, subfolders, filenames in os.walk(root, followlinks=False):
        relative_folder = Path(folder).relative_to(root)
        if relative_folder.parts and relative_folder.parts[0] in (
                "node_modules", "dist", "release", "build", ".git", "__pycache__"):
            subfolders.clear()
            continue
        subfolders[:] = [
            name for name in subfolders
            if name not in ("node_modules", "dist", "release", "build", ".git", "__pycache__")
        ]
        for name in filenames:
            relative = relative_folder / name
            # Only shipped source inputs, never existing test/release material.
            if not (
                (len(relative.parts) == 1 and
                 (name.endswith(".py") or name in (
                     "accounting.html", "vite.config.js", "package.json", "package-lock.json")))
                or relative.parts[0] in ("src", "public", "assets")
            ):
                continue
            full = root / relative
            _no_link(full)
            result[relative.as_posix()] = hashlib.sha256(full.read_bytes()).hexdigest()
    for mandatory in MANDATORY_SOURCES:
        if mandatory not in result:
            raise QABuildBlocked(f"Missing source: {mandatory}")
    return dict(sorted(result.items()))


def _safe_copytree(source: Path, destination: Path) -> None:
    _no_link(source)
    if not source.is_dir():
        raise QABuildBlocked(f"Missing build dependency: {source}")
    for folder, dirs, files in os.walk(source, followlinks=False):
        for name in dirs + files:
            _no_link(Path(folder) / name)
    shutil.copytree(source, destination, symlinks=False)


def _snapshot_source(target: Path, source_hashes: dict[str, str]) -> None:
    for relative in source_hashes:
        copied = target / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / relative, copied)
        if hashlib.sha256(copied.read_bytes()).hexdigest() != source_hashes[relative]:
            raise QABuildBlocked(f"Source changed during QA snapshot: {relative}")


def _trusted_modules() -> Path:
    required = ["vite/bin/vite.js", "@vitejs/plugin-react", "react", "react-dom",
                "lucide-react", "@fontsource-variable/estedad", "vazirmatn"]
    installed = json.loads((SOURCE / "package.json").read_text(encoding="utf8"))
    if "sileo" in installed.get("dependencies", {}):
        required += ["sileo", "motion"]
    for candidate in TRUSTED_MODULES:
        if candidate.is_dir():
            _no_link(candidate)
            if all((candidate / package).exists() for package in required):
                return candidate
    raise QABuildBlocked("No trusted offline node_modules tree with Taraz dependencies")


def _sandbox_environment(target: Path) -> dict[str, str]:
    env = os.environ.copy()
    mapping = {
        "APPDATA": target / "profile" / "roaming",
        "LOCALAPPDATA": target / "profile" / "local",
        "USERPROFILE": target / "profile",
        "HOME": target / "profile",
        "TEMP": target / "tmp",
        "TMP": target / "tmp",
        "PYINSTALLER_CONFIG_DIR": target / "pyinstaller-cache",
        "npm_config_cache": target / "npm-cache",
    }
    for variable, directory in mapping.items():
        directory.mkdir(parents=True, exist_ok=True)
        env[variable] = str(directory)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["TARAZ_QA_MODE"] = "1"
    env["TARAZ_QA_DATA_DIR"] = str(target / "profile" / "qa" / "ledger")
    env.pop("TARAZ_QA_REPORT", None)
    return env


def _run_command(command: list[str], *, cwd: Path, env: dict[str, str],
                 log: Path, timeout_seconds: int) -> None:
    try:
        result = subprocess.run(command, cwd=str(cwd), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        log.write_text(str(exc), encoding="utf-8")
        raise QABuildBlocked(f"Build command timed out; inspect {log.name}") from exc
    log.write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise QABuildBlocked(
            f"Build command failed (exit {result.returncode}); inspect {log.name}: "
            + result.stdout[-1300:]
        )


def _method_names(code: types.CodeType) -> set[str]:
    result = {code.co_name}
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            result.update(_method_names(value))
    return result


def _code_strings(code: types.CodeType) -> set[str]:
    """Inspect frozen bytecode recursively; this does not execute packaged code."""
    values = set()
    def collect(part):
        if isinstance(part, str):
            values.add(part)
        elif isinstance(part, types.CodeType):
            values.update(_code_strings(part))
        elif isinstance(part, (tuple, frozenset)):
            for entry in part:
                collect(entry)
    for part in code.co_consts:
        collect(part)
    return values


def _check_packed_durable_review(code: types.CodeType) -> dict:
    """Reject the old installed Taraz implementation that has no durable intent."""
    methods = _method_names(code)
    literals = _code_strings(code)
    required_methods = {"review_request", "recover_review", "list_recoverable_reviews",
                        "_atomic_json", "_request_lock", "_validate_intent", "_read_record"}
    required_literals = {".intent.json", "sourceDigest", "financialEventCreated"}
    absent_methods = required_methods - methods
    absent_literals = required_literals - literals
    if absent_methods or absent_literals:
        raise QABuildBlocked(
            "Packed Taraz review lacks durable intent/restart contract: "
            + ",".join(sorted(absent_methods | absent_literals))
        )
    return {"sourceBoundDurableIntentCode": True,
            "reviewMethods": sorted(required_methods),
            "intentLiterals": sorted(required_literals)}


def _check_packed_html_bridge(code: types.CodeType) -> dict:
    """Require the real packaged HTML forwarder, not merely a Python API.

    The React UI can expose a recover button and TarazAPI can have a method
    while the embedded ``window.madar`` allowlist silently omits that method.
    This is a static presence gate, not proof of WebView2 startup or login.
    """
    scripts = [value for value in _code_strings(code)
               if "window.madar = Object.fromEntries(" in value
               and "window.pywebview?.api?.[key]" in value]
    if len(scripts) != 1:
        raise QABuildBlocked("Packed HTML WebView2 bridge is missing or ambiguous")
    methods = {name: ("'" + name + "'") in scripts[0] for name in INBOX_METHODS}
    if not all(methods.values()):
        raise QABuildBlocked("Packed HTML bridge omits native methods: "
                             + ",".join(name for name, present in methods.items()
                                        if not present))
    return {"packedHtmlBridgeForwarderPresent": True,
            "packedHtmlBridgeMethods": methods}


def _inspect_bundle(exe: Path) -> dict:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(exe))
    candidates = [
        filename for filename in archive.toc
        if filename.replace("\\", "/").startswith("dist/assets/")
        and filename.lower().endswith(".js")
    ]
    if not candidates:
        raise QABuildBlocked("Packed EXE is missing dist/assets JavaScript UI")
    blobs = [archive.extract(filename) for filename in candidates]
    if any(not isinstance(blob, bytes) for blob in blobs):
        raise QABuildBlocked("Cannot read packed UI assets")
    ui = b" ".join(blobs)
    phrase = UI_PHRASE.encode("utf-8") in ui
    # This is intentionally only compiled-asset presence evidence; no native
    # GUI/authenticated-user experience is implied by matching JS literals.
    new_surfaces = {
        "sileoToastReactHost": b"taraz-feedback-host" in ui,
        "perSectionContextHelpTrigger": b"taraz-context-help-trigger" in ui,
    }
    browser_methods = {name: name.encode("ascii") in ui for name in INBOX_METHODS}
    entry = archive.extract("taraz_desktop")
    if not isinstance(entry, bytes):
        raise QABuildBlocked("Packed Taraz Python entry is missing")
    native = marshal.loads(entry)
    if not isinstance(native, types.CodeType):
        raise QABuildBlocked("Packed Taraz Python entry has unexpected structure")
    names = _method_names(native)
    native_methods = {name: name in names for name in INBOX_METHODS}
    if (not phrase or not all(browser_methods.values())
            or not all(native_methods.values())
            or not all(new_surfaces.values())):
        raise QABuildBlocked(
            f"Packed feature inspection failed: phrase={phrase}, "
            f"UI={browser_methods}, native={native_methods}, extras={new_surfaces}"
        )
    archive_python = archive.open_embedded_archive("PYZ.pyz")
    packed_html_server = archive_python.extract("standalone_accounting_desktop")
    if not isinstance(packed_html_server, types.CodeType):
        raise QABuildBlocked("Packed standalone HTML bridge implementation unavailable")
    html_bridge = _check_packed_html_bridge(packed_html_server)
    packed_review = archive_python.extract("taraz_integration")
    if not isinstance(packed_review, types.CodeType):
        raise QABuildBlocked("Packed Taraz review implementation is unavailable")
    durable = _check_packed_durable_review(packed_review)
    return {
        "uiInvoiceDraftButtonPresent": phrase,
        "uiInboxReferences": browser_methods,
        "compiledNewUISurfaces": new_surfaces,
        "packedNativeInboxMethods": native_methods,
        **html_bridge,
        "packedDurableReview": durable,
        "uiAssetCount": len(candidates),
        "exeSha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "exeSizeBytes": exe.stat().st_size,
    }


def run() -> Path:
    if os.name != "nt":
        raise QABuildBlocked("QA Windows EXE bundle requires Windows")
    _no_link(SOURCE)
    _no_link(QA_PARENT.parent)
    if QA_PARENT.exists():
        _no_link(QA_PARENT)
    else:
        QA_PARENT.mkdir(parents=True)
    target = QA_PARENT / ("qa-" + uuid.uuid4().hex[:12])
    target.mkdir(exist_ok=False)
    report_path = target / "qa-build-report.json"
    report: dict = {
        "status": "IN_PROGRESS", "qaOnly": True, "installed": False,
        "realLedgerAccessed": False, "releaseReady": False,
        "source": str(SOURCE), "output": str(target),
    }
    try:
        expected = _tree_fingerprint(SOURCE)
        snapshot = target / "snapshot"
        snapshot.mkdir()
        _snapshot_source(snapshot, expected)
        trusted = _trusted_modules()
        _safe_copytree(trusted, snapshot / "node_modules")
        environment = _sandbox_environment(target)
        web = target / "web" / "dist"
        web.parent.mkdir()
        _run_command([
            shutil.which("node") or "node",
            str(snapshot / "node_modules" / "vite" / "bin" / "vite.js"),
            "build", "--config", str(snapshot / "vite.config.js"),
            "--outDir", str(web), "--emptyOutDir",
        ], cwd=snapshot, env=environment,
            log=target / "vite-build.log", timeout_seconds=180)
        html = web / "accounting.html"
        if not html.is_file() or not list((web / "assets").glob("*.js")):
            raise QABuildBlocked("Vite output lacks accounting.html or compiled JS")
        result_dir = target / "pyinstaller" / "dist"
        result_dir.mkdir(parents=True)
        exe_name = "Taraz-MTR-QA-" + target.name.removeprefix("qa-")
        _run_command([
            sys.executable, "-B", "-m", "PyInstaller",
            "--onefile", "--windowed", "--noconfirm",
            "--name", exe_name, "--icon", str(snapshot / "assets" / "taraz.ico"),
            "--add-data", str(web) + ";dist",
            "--distpath", str(result_dir),
            "--workpath", str(target / "pyinstaller" / "build"),
            "--specpath", str(target / "pyinstaller" / "spec"),
            "--paths", str(snapshot),
            str(snapshot / "taraz_desktop.py"),
        ], cwd=snapshot, env=environment,
            log=target / "pyinstaller-build.log", timeout_seconds=600)
        exe = result_dir / (exe_name + ".exe")
        if not exe.is_file() or exe.is_symlink():
            raise QABuildBlocked("QA EXE was not created at the specified external path")
        observed = _inspect_bundle(exe)
        if _tree_fingerprint(SOURCE) != expected:
            raise QABuildBlocked("Source inputs changed during QA build; snapshot is stale")
        report.update({
            "status": "QA_BUNDLE_VERIFIED", "exe": str(exe),
            "sourceInputCount": len(expected), "sourceSnapshotSha256":
                hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest(),
            "dependenciesCopiedFrom": str(trusted), **observed,
        })
    except Exception as exc:
        report.update({"status": "BLOCKED", "error": str(exc),
                       "errorType": type(exc).__name__})
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        raise
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return report_path


if __name__ == "__main__":
    try:
        path = run()
        print(path.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"QA BUILD BLOCKED: {type(error).__name__}: {error}",
              file=sys.stderr)
        sys.exit(1)
