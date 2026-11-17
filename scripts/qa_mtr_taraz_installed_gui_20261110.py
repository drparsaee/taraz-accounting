"""Fail-closed Taraz installed-GUI feasibility and *unpacked* synthetic UI QA.

This file NEVER starts the installed EXE, connects to a service, or reads an
existing user ledger/Parsian profile. It tests the real source-host Inbox API
against disposable, newly constructed paths. Optional JSX compilation and
React server rendering use an explicitly supplied read-only node_modules tree.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SCRATCH_PARENT = REPO.parents[1]
SYNTHETIC_ID = "a1" * 16
BLOCKER = (
    "Installed Taraz.exe not launched: taraz_desktop.run() requires a "
    "migrated personal SQLite ledger (revision >=608 and two specific Parsian "
    "event IDs) and verified personal Parsian history. Official public "
    "accounting APIs cannot provision that personal provenance for a fresh "
    "synthetic book. Forging historical events or bypassing AUTH is forbidden."
)


class QABlocked(RuntimeError):
    pass


@contextmanager
def isolated_environment(base: Path):
    """Redirect BOTH profile roots before importing the host bridge."""
    appdata = base / "qa" / "roaming"
    local = base / "qa" / "local"
    appdata.mkdir(parents=True)
    local.mkdir(parents=True)
    env = {
        "APPDATA": str(appdata), "LOCALAPPDATA": str(local),
        "TARAZ_QA_MODE": "1",
        "TARAZ_QA_DATA_DIR": str(base / "qa" / "ledger"),
        "TARAZ_DATA_DIR": str(base / "qa" / "ledger"),
    }
    for key in ("TARAZ_QA_REPORT",):
        if key in os.environ:
            env[key] = ""
    with patch.dict(os.environ, env):
        yield appdata, local


def refuse_installed_launch():
    """A public fail-closed refusal, not an AUTH override or EXE probe."""
    raise QABlocked(BLOCKER)


def _request(id_: str, title: str) -> dict:
    return {
        "schema": 1, "source": "madar", "id": id_,
        "taskId": "synthetic.task", "projectId": "synthetic.project",
        "title": title, "amountRial": "12000",
        "createdUtc": "2026-11-10T10:00:00+00:00",
    }


def probe_synthetic_host(base: Path) -> dict:
    """Public Store and TarazAPI only, all writes in the disposable QA tree."""
    if not base.is_absolute() or base.exists() and base.is_symlink():
        raise QABlocked("Unsafe synthetic QA root")
    if "qa" not in (p.lower() for p in (base / "qa").parts):
        raise QABlocked("QA-only path marker missing")
    with isolated_environment(base) as (appdata, local):
        from standalone_accounting import StandaloneAccountingStore
        from taraz_desktop import TarazAPI
        from taraz_integration import list_requests

        data = appdata / "Taraz"
        data.mkdir()
        db = data / "standalone-accounting.sqlite3"
        store = StandaloneAccountingStore(db, default_currency="RIAL")
        accounts = {"local": {"username": "local", "role": "admin"}}
        first = store.read(actor="local", accounts=accounts)
        if first["revision"] != 0 or not db.is_file():
            raise AssertionError("Fresh official synthetic store is not empty")
        api = TarazAPI(data)
        host_read = api.standaloneAccountingRead()
        if host_read["revision"] != 0:
            raise AssertionError("Actual host read failed on synthetic official store")

        # This is the decisive installed-startup blocker, checked through the
        # unmodified public method, without calling run() or reading real data.
        guard_denied = False
        try:
            api.standaloneAccountingParsianHistory()
        except PermissionError as exc:
            guard_denied = "Unverified personal accounting ledger" in str(exc)
        if not guard_denied:
            raise AssertionError("Personal provenance guard did not deny fresh QA book")

        bridge = local / "Madar-Taraz-Bridge"
        pending = bridge / "pending"
        pending.mkdir(parents=True)
        initial = api.tarazIntegrationList()
        if initial != {"connected": True, "requests": [], "invalidCount": 0}:
            raise AssertionError("Nonempty initial synthetic inbox")
        source = pending / (SYNTHETIC_ID + ".json")
        source.write_text(json.dumps(_request(SYNTHETIC_ID, "QA Inbox item"),
                                     ensure_ascii=False), encoding="utf-8")
        # Invalid input is counted but never shown to the GUI.
        (pending / ("b2" * 16 + ".json")).write_text("{}", encoding="utf-8")
        listed = api.tarazIntegrationList()
        if (not listed["connected"] or len(listed["requests"]) != 1
                or listed["invalidCount"] != 1
                or listed["requests"][0]["id"] != SYNTHETIC_ID):
            raise AssertionError("Inbox did not show exactly one safe QA proposal")
        before = sha256(db.read_bytes()).hexdigest()
        receipt = api.tarazIntegrationReview(SYNTHETIC_ID, "reviewed")
        after = sha256(db.read_bytes()).hexdigest()
        if receipt != {
            "id": SYNTHETIC_ID, "state": "reviewed",
            "financialEventCreated": False,
        }:
            raise AssertionError("Inbox review contract failed")
        if before != after or store.read(actor="local", accounts=accounts)["revision"] != 0:
            raise AssertionError("Inbox review touched the accounting ledger")
        if api.tarazIntegrationList()["requests"]:
            raise AssertionError("Reviewed QA item remained pending")
        if not (bridge / "reviewed" / (SYNTHETIC_ID + ".review.json")).is_file():
            raise AssertionError("Review was not persisted as metadata intent")
        if list_requests(bridge)["invalidCount"] != 1:
            raise AssertionError("Invalid pending proposal was not quarantined")
        return {
            "host": "TarazAPI (unpacked source)",
            "syntheticLedgerRevision": 0,
            "guardDeniedPersonalHistory": guard_denied,
            "inboxPendingBeforeReview": 1,
            "invalidInboxItemsNotDisplayed": 1,
            "reviewedAsMetadataOnly": True,
            "financialEventCreated": False,
            "ledgerSha256Unchanged": before == after,
            "realProfileAccessed": False,
            "installedExeLaunched": False,
        }


# This is a disposable compiler harness. It compiles actual, UNMODIFIED JSX;
# a test-only named export exposes an existing private component for SSR, but
# does not alter any source code, AUTH path or distributable EXE.
BUILD_JS = r"""
const fs = require('node:fs');
const path = require('node:path');
const esbuild = require(process.argv[2]);
const repo = path.resolve(process.argv[3]), out = path.resolve(process.argv[4]);
const entry = path.join(repo, 'src', 'taraz_settings.jsx');
const bridge = path.join(repo, 'src', 'taraz_integration_panel.jsx');
async function build(input, output, expose) {
  await esbuild.build({
    entryPoints:[input], outfile:output, bundle:true, platform:'node',
    format:'cjs', logLevel:'silent', external:['react','lucide-react'],
    loader:{'.css':'empty'},
    plugins: expose ? [{
      name:'expose-existing-ui-component-for-ssr',
      setup(build) {
        build.onLoad({filter:/taraz_settings\.jsx$/}, args => ({
          contents:fs.readFileSync(args.path,'utf8') +
            '\nexport { IntegrationSettings };\n',
          loader:'jsx', resolveDir:path.dirname(args.path)
        }));
      }
    }] : [],
  });
}
(async()=>{
  await build(entry,path.join(out,'settings.cjs'),true);
  await build(bridge,path.join(out,'panel.cjs'),false);
})().catch(e=>{console.error(String(e));process.exitCode=1});
"""

SSR_JS = r"""
const assert = require('node:assert/strict');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const path = require('node:path');
const directory = path.resolve(process.argv[2]);
const Settings = require(path.join(directory,'settings.cjs'));
const Panel = require(path.join(directory,'panel.cjs')).default;
let inboxCalls = 0, financeCalls = 0;
const api = {
  tarazIntegrationList:async()=>{inboxCalls++;return {connected:true,requests:[]};},
  tarazIntegrationReview:async()=>{throw Error('No review without a gesture');},
  standaloneAccountingCommand:()=>{financeCalls++;throw Error('Ledger call forbidden');},
};
const settings = renderToStaticMarkup(
  React.createElement(Settings.default,{api,currentUser:{username:'qa'},canManage:true}));
const integration = renderToStaticMarkup(
  React.createElement(Settings.IntegrationSettings,{api,canReview:true}));
const collapsed = renderToStaticMarkup(React.createElement(Panel,{api}));
assert.match(settings,/taraz-settings/);
assert.match(settings,/تنظیمات برنامه/);
assert.match(integration,/اتصال اختیاری مدار به تراز/);
assert.match(integration,/type="checkbox"/);
assert.match(integration,/disabled=""/);
assert.match(integration,/اجازه می‌دهم ارجاع‌های مدار را دستی بررسی کنم/);
assert.doesNotMatch(integration,/QA Inbox item/);
assert.match(collapsed,/taraz-bridge-toggle/);
assert.doesNotMatch(collapsed,/ارجاع‌های دریافتی از مدار/);
assert.equal(inboxCalls,0);
assert.equal(financeCalls,0);
process.stdout.write(JSON.stringify({
  compiledRealJsx:true, realReactServerRender:true,
  settingsTabAvailable:true, integrationCheckboxDisabledInitially:true,
  collapsedPanelNoAutoLoad:true, inboxCalls, financeCalls,
}));
"""


def probe_compiled_ui(base: Path, node_modules: Path) -> dict:
    """Read-only external toolchain, output only to disposable QA tree."""
    modules = node_modules.resolve(strict=True)
    if modules.name != "node_modules" or not modules.is_dir():
        raise QABlocked("Explicit read-only node_modules path required")
    esbuild = modules / "esbuild" / "lib" / "main.js"
    if not esbuild.is_file():
        raise QABlocked("esbuild unavailable in supplied toolchain")
    for dep in ("react", "react-dom"):
        if not (modules / dep).is_dir():
            raise QABlocked(dep + " unavailable in supplied toolchain")
    node = shutil.which("node")
    if not node:
        raise QABlocked("node executable unavailable")
    work = base / "qa" / "compiled"
    work.mkdir(parents=True, exist_ok=True)
    build = work / "build.cjs"
    render = work / "render.cjs"
    build.write_text(BUILD_JS, encoding="utf-8")
    render.write_text(SSR_JS, encoding="utf-8")
    env = dict(os.environ)
    env["NODE_PATH"] = str(modules)
    env["APPDATA"] = str(base / "qa" / "roaming")
    env["LOCALAPPDATA"] = str(base / "qa" / "local")
    env["npm_config_offline"] = "true"
    for command in (
        [node, str(build), str(esbuild), str(REPO), str(work)],
        [node, str(render), str(work)],
    ):
        done = subprocess.run(command, cwd=work, env=env, capture_output=True,
                              text=True, timeout=45, check=False)
        if done.returncode != 0:
            raise AssertionError(
                "Synthetic compiled UI failed (exit {}): {}".format(
                    done.returncode, (done.stderr or done.stdout)[-1800:]))
    result = json.loads(done.stdout)
    if not result["compiledRealJsx"] or result["inboxCalls"] != 0:
        raise AssertionError("Compiled UI consent assertion failed")
    result["installedExeLaunched"] = False
    result["browserGuiOpened"] = False
    return result


def run_qa(*, node_modules: Path | None = None) -> dict:
    """Never inspect installed program paths or touch persistent profiles."""
    with tempfile.TemporaryDirectory(prefix="qa-taraz-gui-", dir=SCRATCH_PARENT) as raw:
        base = Path(raw)
        sys.path.insert(0, str(REPO))
        try:
            host = probe_synthetic_host(base)
        finally:
            sys.path.remove(str(REPO))
        compiled = (probe_compiled_ui(base, node_modules)
                    if node_modules is not None else {"status": "NOT_RUN_NO_TOOLCHAIN"})
        return {"decision": "INSTALLED_GUI_BLOCKED_UNPACKED_QA_ONLY",
                "installedBlocker": BLOCKER,
                "syntheticHost": host, "compiledUnpackedUI": compiled}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("unpacked", "installed"), default="unpacked")
    parser.add_argument("--node-modules", type=Path,
                        help="Explicit read-only node_modules for JSX/React SSR; no downloads")
    args = parser.parse_args(argv)
    if args.mode == "installed":
        print(json.dumps({"decision": "BLOCKED", "reason": BLOCKER}))
        return 2
    try:
        report = run_qa(node_modules=args.node_modules)
    except (QABlocked, AssertionError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"decision": "QA_FAILED_CLOSED", "error": str(exc)}))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
