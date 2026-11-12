"""Build a distinct, version-stamped Taraz 1.0.1 sandbox QA Inno installer.

No source, installed application, actual profile or ledger is modified. An
independently attested 1.0.0 QA source snapshot is copied into a fresh run
directory, retagged in *both* npm manifests, protected with a QA launch gate,
and freshly compiled to a real versioned PE binary. Inno is COMPILED ONLY.

This is not a production upgrade, signed release or permitted live install.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True

SOURCE = Path(__file__).resolve().parents[1]
QA_PARENT = SOURCE.parents[1]
BASELINE = QA_PARENT / "MTR-TARAZ-QA-BUNDLE-20261110" / "qa-4ae81695ac39"
OUTPUT = QA_PARENT / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.1-inno-qa"
ISCC = Path(r"C:\Users\Parsa\AppData\Local\Programs\Inno Setup 6\ISCC.exe")
TARGET_VERSION = "1.0.1"
SOURCE_VERSION = "1.0.0"
EXPECTED_QA_EXE_SHA256 = "49ef093765801c56fc1b9e04eabe3d8370d7db7982de51a28ef996e7079dc7d6"


class SandboxBuildBlocked(RuntimeError):
    """A safety or provenance condition required for compilation is absent."""


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def no_links(path: Path) -> None:
    """Reject directory junctions and file symlinks before any traversal."""
    parts = [path, *path.parents]
    for item in parts:
        if item.exists() or item.is_symlink():
            mode = item.lstat()
            if item.is_symlink() or (getattr(mode, "st_file_attributes", 0) & 0x400):
                raise SandboxBuildBlocked(f"linked path refused: {item}")


def copy_no_links(src: Path, dst: Path) -> None:
    no_links(src)
    if not src.is_dir() or dst.exists():
        raise SandboxBuildBlocked("source missing or output exists")
    for root, dirs, files in os.walk(src, followlinks=False):
        for name in dirs + files:
            no_links(Path(root) / name)
    shutil.copytree(src, dst, symlinks=False)


def baseline_report() -> dict:
    report = BASELINE / "qa-build-report.json"
    no_links(report)
    if not report.is_file():
        raise SandboxBuildBlocked("pinned QA report unavailable")
    data = json.loads(report.read_text(encoding="utf-8"))
    if data.get("status") != "QA_BUNDLE_VERIFIED" or data.get("releaseReady") is not False:
        raise SandboxBuildBlocked("baseline QA verdict not verified")
    exe = BASELINE / "pyinstaller" / "dist" / "Taraz-MTR-QA-4ae81695ac39.exe"
    no_links(exe)
    if not exe.is_file() or sha(exe) != EXPECTED_QA_EXE_SHA256:
        raise SandboxBuildBlocked("pinned 1.0.0 QA executable digest changed")
    if data.get("exeSha256") != EXPECTED_QA_EXE_SHA256 or data.get("exeSizeBytes") != exe.stat().st_size:
        raise SandboxBuildBlocked("QA report/binary mismatch")
    snapshot = BASELINE / "snapshot"
    no_links(snapshot)
    if not snapshot.is_dir():
        raise SandboxBuildBlocked("baseline QA source snapshot missing")
    # Reuse the original audited source fingerprint algorithm. Read only.
    sys.path.insert(0, str(SOURCE / "scripts"))
    from qa_mtr_taraz_build_20261110 import _tree_fingerprint
    digests = _tree_fingerprint(snapshot)
    fingerprint = hashlib.sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest()
    if (fingerprint != data.get("sourceSnapshotSha256") or
            len(digests) != data.get("sourceInputCount")):
        raise SandboxBuildBlocked("source snapshot drifted since verified 1.0.0 build")
    source_package = json.loads((snapshot / "package.json").read_text(encoding="utf-8"))
    source_lock = json.loads((snapshot / "package-lock.json").read_text(encoding="utf-8"))
    if any(v != SOURCE_VERSION for v in (
            source_package.get("version"), source_lock.get("version"),
            source_lock.get("packages", {}).get("", {}).get("version"))):
        raise SandboxBuildBlocked("baseline package/lock versions differ")
    return {"report": data, "snapshot": snapshot, "fingerprint": fingerprint}


def sandbox_environment(run: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("TARAZ_")}
    paths = {
        "APPDATA": "qa-runtime/appdata", "LOCALAPPDATA": "qa-runtime/localappdata",
        "USERPROFILE": "qa-runtime/userprofile", "HOME": "qa-runtime/home",
        "TEMP": "qa-runtime/temp", "TMP": "qa-runtime/temp",
        "PYINSTALLER_CONFIG_DIR": "qa-runtime/pyinstaller-cache",
        "PYTHONPYCACHEPREFIX": "qa-runtime/python-bytecode",
        "npm_config_cache": "qa-runtime/npm-cache",
    }
    for name, relative in paths.items():
        directory = run / relative
        directory.mkdir(parents=True, exist_ok=True)
        env[name] = str(directory)
    env.update({"TARAZ_QA_MODE": "1", "TARAZ_QA_RUN_ROOT": str(run / "qa-runtime"),
                "TARAZ_QA_DATA_DIR": str(run / "qa-runtime" / "qa" / "ledger"),
                "PYTHONDONTWRITEBYTECODE": "1", "INNOSETUP_LOG": ""})
    (run / "qa-runtime" / "qa" / "ledger").mkdir(parents=True, exist_ok=True)
    return env


def stage_real_version(snapshot: Path, installed_exe: Path) -> dict:
    """Version the copied npm package/lock and native PE, adding a runtime QA guard."""
    package = snapshot / "package.json"
    lock = snapshot / "package-lock.json"
    p = json.loads(package.read_text(encoding="utf-8"))
    l = json.loads(lock.read_text(encoding="utf-8"))
    if p.get("version") != SOURCE_VERSION or l.get("version") != SOURCE_VERSION or l["packages"][""]["version"] != SOURCE_VERSION:
        raise SandboxBuildBlocked("invalid version inputs")
    p["version"] = TARGET_VERSION
    l["version"] = TARGET_VERSION
    l["packages"][""]["version"] = TARGET_VERSION
    package.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lock.write_text(json.dumps(l, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    version_module = snapshot / "taraz_qa_build_version.py"
    version_module.write_text(
        f'"""Version and sandbox authority for the independently built QA executable."""\n'
        f'APP_VERSION = "{TARGET_VERSION}"\n'
        f'QA_ONLY = True\n'
        f'ALLOWED_EXE = {str(installed_exe)!r}\n', encoding="utf-8")
    entry = snapshot / "taraz_desktop.py"
    original = entry.read_text(encoding="utf-8")
    anchor = "from __future__ import annotations\n"
    if original.count(anchor) != 1:
        raise SandboxBuildBlocked("cannot safely insert QA launch guard")
    guard = '''\n# QA safeguard added only to a disposable copy of the Taraz source.
import os as _qa_os
import sys as _qa_sys
from pathlib import Path as _qa_Path
from taraz_qa_build_version import APP_VERSION as _qa_version, ALLOWED_EXE as _qa_exe

def _taraz_qa_launch_gate():
    if _qa_version != "1.0.1" or _qa_os.environ.get("TARAZ_QA_MODE") != "1":
        raise PermissionError("Taraz 1.0.1 QA binary requires explicit QA mode")
    expected = _qa_Path(_qa_exe).resolve()
    if _qa_Path(_qa_sys.executable).resolve() != expected:
        raise PermissionError("Taraz QA executable is outside the disposable install path")
    root = _qa_Path(_qa_os.environ.get("TARAZ_QA_RUN_ROOT", ""))
    if not root.is_absolute() or not root.is_dir() or "qa-runtime" not in [p.lower() for p in root.parts]:
        raise PermissionError("Taraz sandbox runtime root is missing")
    root = root.resolve()
    for variable in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "TEMP", "TMP", "TARAZ_QA_DATA_DIR"):
        current = _qa_os.environ.get(variable)
        if not current or not _qa_Path(current).is_absolute() or not _qa_Path(current).resolve().is_relative_to(root):
            raise PermissionError("Taraz sandbox profile requirement failed: " + variable)

if __name__ == "__main__":
    _taraz_qa_launch_gate()
'''
    entry.write_text(original.replace(anchor, anchor + guard, 1), encoding="utf-8")
    return {"packageVersion": p["version"], "lockVersion": l["version"],
            "lockRootVersion": l["packages"][""]["version"],
            "qaVersionModuleSha256": sha(version_module), "nativeEntrySha256": sha(entry)}


def version_resource(path: Path) -> None:
    path.write_text('''VSVersionInfo(
  ffi=FixedFileInfo(filevers=(1, 0, 1, 0), prodvers=(1, 0, 1, 0),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Taraz QA sandbox only'),
    StringStruct('FileDescription', 'Taraz side-by-side QA binary (not release)'),
    StringStruct('FileVersion', '1.0.1.0'),
    StringStruct('ProductName', 'Taraz sandbox QA'),
    StringStruct('ProductVersion', '1.0.1.0'),
    StringStruct('OriginalFilename', 'Taraz-v1.0.1-SANDBOX-QA.exe')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)\n''', encoding="utf-8")


def pe_product_version(exe: Path) -> str:
    if os.name != "nt":
        raise SandboxBuildBlocked("Windows version resources require Windows")
    version = ctypes.windll.version
    version.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    version.GetFileVersionInfoSizeW.restype = ctypes.c_ulong
    handle = ctypes.c_ulong()
    size = version.GetFileVersionInfoSizeW(str(exe), ctypes.byref(handle))
    if not size:
        raise SandboxBuildBlocked("new Taraz EXE has no PE version resource")
    buffer = ctypes.create_string_buffer(size)
    version.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    version.GetFileVersionInfoW.restype = ctypes.c_int
    if not version.GetFileVersionInfoW(str(exe), 0, size, buffer):
        raise SandboxBuildBlocked("cannot inspect binary version metadata")
    ptr, length = ctypes.c_void_p(), ctypes.c_uint()
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    version.VerQueryValueW.restype = ctypes.c_int
    if not version.VerQueryValueW(buffer, r"\\", ctypes.byref(ptr), ctypes.byref(length)):
        raise SandboxBuildBlocked("PE fixed file version absent")
    fields = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32))
    if fields[0] != 0xFEEF04BD:
        raise SandboxBuildBlocked("invalid PE version signature")
    major, minor, patch, build = fields[2] >> 16, fields[2] & 65535, fields[3] >> 16, fields[3] & 65535
    text = f"{major}.{minor}.{patch}.{build}"
    if text != "1.0.1.0":
        raise SandboxBuildBlocked(f"new binary version mismatch: {text}")
    return text


def execute(command: list[str], *, cwd: Path, env: dict[str, str], logfile: Path, timeout: int) -> None:
    try:
        result = subprocess.run(command, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout, check=False,
                                text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        logfile.write_text(str(exc), encoding="utf-8")
        raise SandboxBuildBlocked(f"compiler timeout: {logfile}") from exc
    logfile.write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise SandboxBuildBlocked(f"compiler exit {result.returncode}: {logfile}: {result.stdout[-750:]}")


def inno_script(exe: Path, manifest: Path, destination: Path, output_dir: Path) -> str:
    """Pinned, non-uninstalling, nonprivileged package with fixed sandbox destination."""
    for p in (exe, manifest, destination, output_dir):
        no_links(p)
    if not destination.resolve().is_relative_to(OUTPUT.resolve()):
        raise SandboxBuildBlocked("Inno install path would escape QA output")
    dest = str(destination)
    setup_base = "Taraz-v1.0.1-SANDBOX-QA-COMPILE-ONLY"
    appid = "{{" + str(uuid.uuid5(uuid.NAMESPACE_URL, "taraz-1.0.1-disposable-qa-isolated")) + "}"
    # Only include known, newly compiled files. No desktop/taskbar icons, Run,
    # registry modifications, services or vendor WebView2 installers.
    return f'''[Setup]
AppId={appid}
AppName=Taraz Sandbox QA
AppVersion=1.0.1
AppVerName=Taraz 1.0.1 sandbox QA only
AppPublisher=Taraz QA (unapproved)
DefaultDirName={dest}
OutputDir={output_dir}
OutputBaseFilename={setup_base}
PrivilegesRequired=lowest
Uninstallable=no
CreateUninstallRegKey=no
UsePreviousAppDir=no
UsePreviousLanguage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
DisableWelcomePage=no
AllowRootDirectory=no
AllowNetworkDrive=no
AllowUNCPath=no
ChangesEnvironment=no
ChangesAssociations=no
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=no
ArchitecturesAllowed=x64compatible
CloseApplications=no
RestartApplications=no

[Files]
Source: "{exe}"; DestDir: "{{app}}"; DestName: "Taraz-v1.0.1-SANDBOX-QA.exe"; Flags: ignoreversion
Source: "{manifest}"; DestDir: "{{app}}"; DestName: "sandbox-qa-manifest.json"; Flags: ignoreversion

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Requested: String;
begin
  Requested := RemoveBackslashUnlessRoot(ExpandConstant('{{app}}'));
  if CompareText(Requested, '{dest.replace("'", "''")}') <> 0 then
    Result := 'QA install blocked: location must remain inside disposable sandbox.';
end;
'''


def run() -> Path:
    if os.name != "nt" or not ISCC.is_file():
        raise SandboxBuildBlocked("Windows Inno Setup 6 compiler not available")
    for p in (SOURCE, BASELINE, OUTPUT, ISCC):
        no_links(p)
    attestation = baseline_report()  # all read-only checks before creating output
    OUTPUT.mkdir(parents=True, exist_ok=True)
    run_dir = OUTPUT / ("compile-" + uuid.uuid4().hex[:12])
    run_dir.mkdir(exist_ok=False)
    report_file = run_dir / "compile-report.json"
    report = {"status": "IN_PROGRESS", "qaOnly": True, "productionRelease": False,
              "installed": False, "installerExecuted": False, "installedUserDataAccessed": False,
              "unsigned": True, "baselineSourceVersion": SOURCE_VERSION,
              "targetVersion": TARGET_VERSION, "output": str(run_dir)}
    try:
        source = run_dir / "snapshot"
        copy_no_links(attestation["snapshot"], source)
        install_dir = run_dir / "disposable-side-by-side-install"
        compiled_name = "Taraz-v1.0.1-SANDBOX-QA.exe"
        compiled_exe = run_dir / "binary" / compiled_name
        staged = stage_real_version(source, install_dir / compiled_name)
        environment = sandbox_environment(run_dir)
        web_out = run_dir / "web" / "dist"
        web_out.parent.mkdir()
        execute([shutil.which("node") or "node", str(source / "node_modules" / "vite" / "bin" / "vite.js"),
                 "build", "--config", str(source / "vite.config.js"),
                 "--outDir", str(web_out), "--emptyOutDir"],
                cwd=source, env=environment, logfile=run_dir / "vite.log", timeout=180)
        html = web_out / "accounting.html"
        ui_files = list((web_out / "assets").glob("*.js"))
        if not html.is_file() or not ui_files:
            raise SandboxBuildBlocked("versioned UI did not compile")
        version_file = run_dir / "taraz-v101-pe-version.txt"
        version_resource(version_file)
        compiled_exe.parent.mkdir()
        execute([sys.executable, "-B", "-m", "PyInstaller", "--onefile", "--windowed",
                 "--noconfirm", "--version-file", str(version_file),
                 "--name", compiled_name.removesuffix(".exe"),
                 "--icon", str(source / "assets" / "taraz.ico"),
                 "--add-data", str(web_out) + ";dist",
                 "--distpath", str(compiled_exe.parent),
                 "--workpath", str(run_dir / "pyi-work"),
                 "--specpath", str(run_dir / "pyi-spec"),
                 "--paths", str(source), str(source / "taraz_desktop.py")],
                cwd=source, env=environment, logfile=run_dir / "pyinstaller.log", timeout=600)
        if not compiled_exe.is_file() or compiled_exe.is_symlink():
            raise SandboxBuildBlocked("PyInstaller binary absent")
        version = pe_product_version(compiled_exe)
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(str(compiled_exe))
        archive_module = archive.open_embedded_archive("PYZ.pyz")
        if not archive_module.extract("taraz_qa_build_version"):
            raise SandboxBuildBlocked("compiled binary missing real version module")
        js_bundled = [name for name in archive.toc if name.replace("\\", "/").startswith("dist/assets/") and name.endswith(".js")]
        if not js_bundled:
            raise SandboxBuildBlocked("compiled binary missing React UI")
        js_bytes = b" ".join(archive.extract(name) for name in js_bundled)
        if b"taraz-feedback-host" not in js_bytes or b"taraz-context-help-trigger" not in js_bytes:
            raise SandboxBuildBlocked("compiled Sileo/help features absent")
        payload_manifest = run_dir / "sandbox-qa-manifest.json"
        payload = {"schemaVersion": 1, "application": "Taraz", "qaOnly": True,
                   "sourceBaselineVersion": SOURCE_VERSION, "stagedPackageVersion": TARGET_VERSION,
                   "stagedLockVersion": staged["lockVersion"],
                   "stagedLockRootVersion": staged["lockRootVersion"],
                   "compiledPEProductVersion": version,
                   "sourceSnapshotSha256": attestation["fingerprint"],
                   "baselineQaExeSha256": EXPECTED_QA_EXE_SHA256,
                   "compiledExeSha256": sha(compiled_exe),
                   "compiledExeBytes": compiled_exe.stat().st_size,
                   "nativeGuard": "requires explicit QA mode, disposable executable path and all sandbox profile variables",
                   "innoAppIdDistinct": True,
                   "sandboxInstallDir": str(install_dir), "installerNotExecuted": True,
                   "selfContainedWebView2": False, "signed": False, "releaseApproved": False}
        payload_manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        compiler_dir = run_dir / "inno"
        compiler_dir.mkdir()
        iss = run_dir / "Taraz-v1.0.1-SANDBOX-QA.iss"
        iss.write_text(inno_script(compiled_exe, payload_manifest, install_dir, compiler_dir), encoding="utf-8")
        execute([str(ISCC), str(iss)], cwd=run_dir, env=environment,
                logfile=run_dir / "inno-compile.log", timeout=240)
        setup = compiler_dir / "Taraz-v1.0.1-SANDBOX-QA-COMPILE-ONLY.exe"
        if not setup.is_file() or setup.is_symlink() or setup.stat().st_size < compiled_exe.stat().st_size // 4:
            raise SandboxBuildBlocked("Inno setup artifact missing or anomalously small")
        report.update({"status": "COMPILED_QA_SETUP_NOT_EXECUTED",
                       "setupExe": str(setup), "setupSha256": sha(setup),
                       "setupBytes": setup.stat().st_size,
                       "tarazExe": str(compiled_exe), "tarazExeSha256": sha(compiled_exe),
                       "tarazPEVersion": version,
                       "innoScriptSha256": sha(iss), "manifestSha256": sha(payload_manifest),
                       "stagedVersions": staged, "baselineSnapshotSha256": attestation["fingerprint"],
                       "sideBySideInstallPath": str(install_dir),
                       "webView2RuntimeNotBundled": True,
                       "limits": "Compile-only. Actual install, WebView2 startup, rollback and production upgrade unverified."})
    except Exception as exc:
        report.update({"status": "BLOCKED", "errorType": type(exc).__name__, "error": str(exc)})
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_file


if __name__ == "__main__":
    try:
        print(run().read_text(encoding="utf-8"))
    except Exception as error:
        print(f"TARAZ INNO QA BUILD BLOCKED: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
