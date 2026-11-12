"""Loopback-only fixture joining compiled Taraz UI to REAL isolated SQLite APIs.

No production books, network listeners outside 127.0.0.1, finance issue,
installation or live authentication. Exposes only enumerated QA actions.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import os
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from standalone_accounting_desktop import AccountingDesktopAPI
from taraz_desktop import TarazAPI

ASSET_MODE = os.environ.get("TARAZ_QA_WEB_ASSETS", "frozen-98")
PHASE4_ORDER_MODE = os.environ.get("TARAZ_QA_PHASE4_ORDERS") == "1"
if ASSET_MODE not in {"frozen-98", "current-source-dist"}:
    raise RuntimeError("Unsupported offline QA asset mode")
WEB = ((ROOT / "dist") if ASSET_MODE == "current-source-dist" else
       (ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" /
        "taraz-v1.0.6-aaas" / "build-98e815dd931c" / "web" / "dist"))


class Identity:
    def __init__(self):
        self.user = {"username": "qa-invoice-operator", "role": "admin",
                     "financeView": True, "financeEdit": True, "jobTitle": "QA"}

    def require_session(self, token, required="viewer"):
        if token != "private-qa-session":
            raise PermissionError("Invalid QA session")
        return dict(self.user)

    def accounting_accounts(self):
        return {self.user["username"]: dict(self.user)}


class AuthenticatedQaTarazAPI(TarazAPI):
    """Taraz production methods using an explicitly synthetic QA principal."""

    def __init__(self, root, identity):
        AccountingDesktopAPI.__init__(self, root, authenticated_user=identity.user,
                                      identity_store=identity, identity_token="private-qa-session")
        self._requires_migration = False


BRIDGE = """<script>
(() => {
 const names=['standaloneAccountingRead','standaloneAccountingCommand',
  'standaloneAccountingTemplateList','standaloneAccountingTemplateSave',
  'standaloneAccountingTemplateDefault','standaloneAccountingTemplateDuplicate',
  'standaloneAccountingTemplateDelete','tarazOrderList','tarazOrderCommand'];
 if (%s) names.push('tarazOrderFinanceDraft',
  'tarazAgentOrderReview','tarazAgentMemoryList','tarazAgentMemoryCommand');
 window.madar=Object.fromEntries(names.map(name=>[name,async (...args)=>{
   const response=await fetch('/__qa_rpc',{method:'POST',
     headers:{'Content-Type':'application/json'},
     body:JSON.stringify({name,args})});
   const payload=await response.json();
   if(!response.ok)throw Error(payload.error||'QA backend error');
   return payload.value;
 }]));
})();
</script>""" % ("true" if PHASE4_ORDER_MODE else "false")


def run():
    if not WEB.is_dir():
        raise RuntimeError("Pinned compiled build unavailable")
    # This fixture is an independent disposable company, NOT a backup clone.
    with TemporaryDirectory(prefix="qa-taraz-realbridge-", dir=str(ROOT.parent)) as directory:
        root = Path(directory)
        identity = Identity()
        api = AuthenticatedQaTarazAPI(root, identity)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def reply(self, code, payload):
                data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                if self.path == "/__qa_shutdown":
                    self.reply(200, {"stopping": True})
                    Thread(target=server.shutdown, daemon=True).start()
                    return
                if self.path != "/__qa_rpc":
                    self.reply(404, {"error": "Unknown QA path"})
                    return
                try:
                    n = int(self.headers.get("Content-Length", "-1"))
                    if n < 0 or n > 200000:
                        raise ValueError("QA RPC body size invalid")
                    item = json.loads(self.rfile.read(n))
                    if type(item) is not dict or set(item) != {"name", "args"} or type(item["args"]) is not list:
                        raise ValueError("QA RPC envelope invalid")
                    methods = {
                        "standaloneAccountingRead": api.standaloneAccountingRead,
                        "standaloneAccountingCommand": api.standaloneAccountingCommand,
                        "standaloneAccountingTemplateList": api.standaloneAccountingTemplateList,
                        "standaloneAccountingTemplateSave": api.standaloneAccountingTemplateSave,
                        "standaloneAccountingTemplateDefault": api.standaloneAccountingTemplateDefault,
                        "standaloneAccountingTemplateDuplicate": api.standaloneAccountingTemplateDuplicate,
                        "standaloneAccountingTemplateDelete": api.standaloneAccountingTemplateDelete,
                        "tarazOrderList": api.tarazOrderList,
                        "tarazOrderCommand": api.tarazOrderCommand,
                    }
                    if PHASE4_ORDER_MODE:
                        methods["tarazOrderFinanceDraft"] = api.tarazOrderFinanceDraft
                        methods["tarazAgentOrderReview"] = api.tarazAgentOrderReview
                        methods["tarazAgentMemoryList"] = api.tarazAgentMemoryList
                        methods["tarazAgentMemoryCommand"] = api.tarazAgentMemoryCommand
                    name = item["name"]
                    if name not in methods:
                        raise PermissionError("QA action not allowed")
                    if name == "standaloneAccountingCommand":
                        request = item["args"][0]
                        command = request.get("command") if isinstance(request, dict) else None
                        if not isinstance(command, dict) or command.get("type") not in {
                            "party.register", "invoice.create", "invoice.update", "proforma.create", "proforma.update"
                        }:
                            raise PermissionError("QA does not permit financial posting")
                    if name == "tarazOrderCommand":
                        request = item["args"][0]
                        if (not isinstance(request, dict) or request.get("action") not in
                                ({"create", "update", "transition",
                                  "cost.record", "cost.approve", "payment.record",
                                  "payment.confirm", "payment.settle", "handoff.prepare"}
                                  if PHASE4_ORDER_MODE else
                                  {"create", "update", "transition"})):
                            raise PermissionError("QA only allows operational order changes")
                    value = methods[name](*item["args"])
                    self.reply(200, {"value": value})
                except Exception as exc:
                    self.reply(400, {"error": type(exc).__name__ + ": " + str(exc)[:160]})

            def do_GET(self):
                target = urlsplit(self.path).path
                if target in ("/", "/accounting.html"):
                    text = (WEB / "accounting.html").read_text(encoding="utf-8")
                    html = text.replace("</head>", BRIDGE + "</head>")
                    data = html.encode("utf-8")
                    mime = "text/html; charset=utf-8"
                else:
                    path = (WEB / target.lstrip("/")).resolve()
                    if not path.is_relative_to(WEB.resolve()) or not path.is_file():
                        self.send_error(404)
                        return
                    data = path.read_bytes()
                    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            server.daemon_threads = True
            print(json.dumps({"port": server.server_address[1], "isolated": True}), flush=True)
            server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    run()
