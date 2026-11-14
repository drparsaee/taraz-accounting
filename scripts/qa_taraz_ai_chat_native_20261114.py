"""Private Windows WebView2 AI chat UI -> native bridge -> real isolated SQLite.

SOURCE-HOSTED only, NOT a frozen EXE test. Never operates on ambient Windows
desktop or installed accounting data, opens an online provider, or sends money.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import psutil
import sys
import time
import uuid
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v103_native_gui_20261111 as native
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acl
from standalone_accounting_desktop import AccountingDesktopAPI, serve_accounting_page
from standalone_accounting import StandaloneAccountingStore
from taraz_desktop import TarazAPI

OUT = ROOT.parents[1] / "MTR-NEXT-UPDATE-CANDIDATES-20261110" / "taraz-v1.0.6-aaas" / "ai-chat-native-qa-20261114"
FILES = [
    "taraz_ai_chat_store.py", "taraz_ai_invoice_intake.py",
    "taraz_ai_business_service.py", "taraz_desktop.py",
    "standalone_accounting_desktop.py",
    "src/taraz_ai_chat_workspace.jsx", "src/taraz_ai_chat_workspace.css",
    "src/standalone_accounting_workspace.jsx",
]
REQUEST = ("برای شرکت آریا یک فاکتور فروش بساز. ۱۰۰ عدد جعبه و ۲۰۰ عدد لیبل اضافه کن. "
           "قیمت هر کالا را از آخرین فاکتور معتبر همین مشتری بردار.")


class Identity:
    user = {"username": "qa-ai-private", "role": "admin", "financeView": True,
            "financeEdit": True, "jobTitle": "QA"}

    def require_session(self, token, required="viewer"):
        if token != "qa-private-ai-session":
            raise PermissionError("Invalid private AI QA session")
        return dict(self.user)

    def accounting_accounts(self):
        return {self.user["username"]: dict(self.user)}


class QAAPI(TarazAPI):
    def __init__(self, root):
        ident = Identity()
        AccountingDesktopAPI.__init__(
            self, root, authenticated_user=ident.user,
            company_workspace_id="c" * 32, identity_store=ident,
            identity_token="qa-private-ai-session")
        self._requires_migration = False

    def standaloneAccountingCommand(self, request):
        command = request.get("command") if isinstance(request, dict) else None
        if not isinstance(command, dict) or command.get("type") != "invoice.create":
            raise PermissionError("Private AI QA disallows approval, issue and journal post")
        return super().standaloneAccountingCommand(request)


def fingerprint():
    source = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}
    web = ROOT / "dist"
    html = web / "accounting.html"
    scripts = list((web / "assets").glob("accounting-*.js"))
    styles = list((web / "assets").glob("accounting-*.css"))
    if not html.is_file() or len(scripts) != 1 or len(styles) != 1:
        raise RuntimeError("Missing unique compiled source UI")
    markup = html.read_text(encoding="utf-8")
    if scripts[0].name not in markup or styles[0].name not in markup:
        raise RuntimeError("Source HTML not bound to compiled assets")
    return {"source": source, "html": hashlib.sha256(html.read_bytes()).hexdigest(),
            "script": hashlib.sha256(scripts[0].read_bytes()).hexdigest(),
            "css": hashlib.sha256(styles[0].read_bytes()).hexdigest()}


def fixture(root):
    root.mkdir(parents=True, exist_ok=False)
    ledger = StandaloneAccountingStore(root / "standalone-accounting.sqlite3",
                                       default_currency="RIAL")
    accounts = Identity().accounting_accounts()
    revision = 0
    commands = [
        {"type": "party.register", "eventId": "qa-ai-party-1", "partyId": "arya",
         "name": "شرکت آریا", "kind": "customer"},
        {"type": "item.create", "eventId": "qa-ai-item-1", "itemId": "box",
         "name": "جعبه", "sku": "QA-BOX", "kind": "goods", "unit": "piece"},
        {"type": "item.create", "eventId": "qa-ai-item-2", "itemId": "label",
         "name": "لیبل", "sku": "QA-LABEL", "kind": "goods", "unit": "piece"},
        {"type": "invoice.create", "eventId": "qa-ai-source-create",
         "invoiceId": "QA-SOURCE-INV", "partyId": "arya", "documentDate": "2026-11-12",
         "lines": [{"description": "جعبه", "quantity": 1, "unitPrice": 1000,
                    "accountId": "4000", "itemId": "box"},
                   {"description": "لیبل", "quantity": 1, "unitPrice": 500,
                    "accountId": "4000", "itemId": "label"}]},
        {"type": "invoice.approve", "eventId": "qa-ai-source-approve",
         "invoiceId": "QA-SOURCE-INV"},
        {"type": "invoice.issue", "eventId": "qa-ai-source-issue",
         "invoiceId": "QA-SOURCE-INV", "postingDate": "2026-11-12"},
    ]
    for command in commands:
        result = ledger.command(
            command, actor=Identity.user["username"], accounts=accounts,
            expected_revision=revision, now="2026-11-14T08:00:00+00:00")
        revision = result["revision"]
    return revision


def capture_owned_window(path):
    """Only screenshot the exact current process's private synthetic QA UI."""
    from PIL import Image, ImageStat
    user32 = ctypes.windll.user32
    proc_id = os.getpid()
    hwnds = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.GetWindowRect.restype = wintypes.BOOL
    @callback_type
    def enum_windows(hwnd, _param):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != proc_id:
            return True
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        if title.value == "تراز QA خصوصی - AI" and user32.IsWindowVisible(hwnd):
            hwnds.append(hwnd)
        return True
    user32.EnumWindows(enum_windows, 0)
    if len(hwnds) != 1:
        return {"captured": False, "reason": "OWNED_WINDOW_NOT_UNIQUE"}
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        class INFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_ushort),
                        ("biBitCount", ctypes.c_ushort), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        class INFO(ctypes.Structure):
            _fields_ = [("bmiHeader", INFOHEADER), ("bmiColors", wintypes.DWORD)]
        hwnd = wintypes.HWND(hwnds[0])
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if not 500 <= width <= 2400 or not 350 <= height <= 1600:
            return {"captured": False, "reason": "INVALID_WINDOW_DIMENSIONS"}
        user32.GetWindowDC.argtypes = [wintypes.HWND]
        user32.GetWindowDC.restype = wintypes.HDC
        gdi = ctypes.windll.gdi32
        gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi.CreateCompatibleDC.restype = wintypes.HDC
        gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi.SelectObject.restype = wintypes.HGDIOBJ
        gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi.DeleteObject.restype = wintypes.BOOL
        gdi.DeleteDC.argtypes = [wintypes.HDC]
        gdi.DeleteDC.restype = wintypes.BOOL
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                                wintypes.UINT, ctypes.c_void_p,
                                ctypes.POINTER(INFO), wintypes.UINT]
        gdi.GetDIBits.restype = ctypes.c_int
        hdc = user32.GetWindowDC(hwnd)
        memory = gdi.CreateCompatibleDC(hdc)
        bitmap = gdi.CreateCompatibleBitmap(hdc, width, height)
        old = gdi.SelectObject(memory, bitmap)
        try:
            user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
            user32.PrintWindow.restype = wintypes.BOOL
            printed = bool(user32.PrintWindow(hwnd, memory, 2))
            info = INFO()
            info.bmiHeader.biSize = ctypes.sizeof(INFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = 0
            raw = ctypes.create_string_buffer(width * height * 4)
            fetched = gdi.GetDIBits(memory, bitmap, 0, height, raw,
                                    ctypes.byref(info), 0)
            if not printed or fetched != height:
                return {"captured": False, "reason": "PRINTWINDOW_DIB_FAILED"}
            image = Image.frombytes("RGB", (width, height), raw.raw, "raw", "BGRX")
            variation = round(sum(ImageStat.Stat(image).var), 2)
            if variation < 200:
                return {"captured": False, "reason": "WHITE_OR_BLANK_FRAME",
                        "variation": variation}
            image.save(path, format="PNG")
            return {"captured": True, "width": width, "height": height,
                    "variance": variation,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        finally:
            gdi.SelectObject(memory, old)
            gdi.DeleteObject(bitmap)
            gdi.DeleteDC(memory)
            user32.ReleaseDC(hwnd, hdc)
    except Exception as exc:
        return {"captured": False, "reason": type(exc).__name__,
                "diagnostic": str(exc)[:160]}


JS_TEST = r'''(() => {
  const qa=window.__qaAi={status:'RUNNING',phase:'NAV',reason:'',modelRan:false};
  const sleep=ms=>new Promise(done=>setTimeout(done,ms));
  const until=async(fn)=>{
    const end=Date.now()+16000;
    while(Date.now()<end){const res=await fn();if(res)return res;await sleep(120);}
    throw Error('TIMEOUT_'+qa.phase);
  };
  (async()=>{
    await until(()=>document.querySelector('.sac-root'));
    await until(()=>typeof window.madar?.tarazAiChatCommand==='function');
    const open=await until(()=>document.querySelector('.sac-sidebar button[aria-current]') ||
      document.querySelector('.sac-sidebar'));
    const tab=Array.from(document.querySelectorAll('.sac-sidebar button'))
      .find(b=>b.textContent.includes('دستیار تجاری'));
    if(!tab)throw Error('AI_NAV_MISSING');
    tab.click();
    qa.phase='NEW';
    const pane=await until(()=>document.querySelector('.taraz-ai-chat'));
    const button=label=>Array.from(pane.querySelectorAll('button')).find(
      b=>b.textContent.trim()===label&&!b.disabled);
    const create=await until(()=>button('گفتگوی جدید'));
    create.click();
    await until(()=>pane.querySelector('.taraz-ai-compose textarea:not(:disabled)'));
    qa.phase='SEND';
    const field=pane.querySelector('.taraz-ai-compose textarea');
    const set=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;
    set.call(field, 'برای شرکت آریا یک فاکتور فروش بساز. ۱۰۰ عدد جعبه و ۲۰۰ عدد لیبل اضافه کن. قیمت هر کالا را از آخرین فاکتور معتبر همین مشتری بردار.');
    field.dispatchEvent(new Event('input',{bubbles:true}));
    field.dispatchEvent(new Event('change',{bubbles:true}));
    await until(()=>button('ثبت درخواست و تهیه پیشنهاد'));
    button('ثبت درخواست و تهیه پیشنهاد').click();
    qa.phase='PROPOSAL';
    await until(()=>{
      const proposal=pane.querySelector('.taraz-ai-proposal');
      return proposal?.querySelector('[data-amount="200000"]') ||
        proposal?.textContent.includes('200000');
    });
    if(!pane.textContent.includes('QA-SOURCE-INV'))throw Error('MISSING_INVOICE_SOURCE');
    const before=await window.madar.standaloneAccountingRead();
    if(Object.keys(before.view.invoices).length!==1)throw Error('AUTOMATIC_DRAFT_BEFORE_APPROVAL');
    qa.phase='REVIEW';
    const box=pane.querySelector('.taraz-ai-review input[type=checkbox]');
    if(!box)throw Error('NO_HUMAN_REVIEW_CHECKBOX');
    box.click();
    await until(()=>button('تأیید و ذخیره پیش‌نویس'));
    button('تأیید و ذخیره پیش‌نویس').click();
    qa.phase='READBACK';
    const after=await until(async()=>{
      const response=await window.madar.standaloneAccountingRead();
      return response.revision===before.revision+1?response:null;
    });
    const docs=Object.values(after.view.invoices);
    const draft=docs.find(d=>d.id.startsWith('AI-INV-'));
    if(docs.length!==2||!draft||draft.status!=='draft'||draft.total!==200000||
       after.view.currency!=='RIAL'||
       draft.postedEntryId!==null||after.view.journals.length!==before.view.journals.length)
       throw Error('INVOICE_PERSISTENCE_OR_LEDGER_MISMATCH');
    const chat=await window.madar.tarazAiChatList('');
    if(chat.conversations?.length!==1)throw Error('CHAT_LIST_NOT_PERSISTED');
    const detail=await window.madar.tarazAiChatRead(chat.conversations[0].id);
    if(detail.messages?.length!==2||detail.executions[0].status!=='executed')
      throw Error('CHAT_MESSAGE_OR_EXECUTION_NOT_PERSISTED');
    window.__qaAi={status:'PASS_AI_CHAT_NATIVE_BRIDGE_SQLITE',phase:'DONE',
      sourceInvoice:'QA-SOURCE-INV',savedInvoice:draft.id,total:draft.total,
      currency:after.view.currency,
      messageCount:detail.messages.length,journalUnchanged:true,
      pendingApprovals:0,modelRan:false,cloudSent:false};
  })().catch(e=>{window.__qaAi={status:'FAIL',phase:qa.phase,
    reason:String(e?.message||e).slice(0,90),modelRan:false,cloudSent:false};});
  return true;
})()'''


def child(work):
    marker = json.loads((work / "qa-owned-marker.json").read_text(encoding="utf-8"))
    if not marker.get("syntheticOnly") or marker.get("fingerprint") != fingerprint():
        raise RuntimeError("Source compiled assets changed after QA isolation")
    if not Path(os.environ["APPDATA"]).resolve().is_relative_to(work):
        raise RuntimeError("Untrusted ambient roaming directory")
    api = QAAPI(work / "private-book")
    server = serve_accounting_page(ROOT / "dist")
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    import webview
    window = webview.create_window(
        "تراز QA خصوصی - AI", f"http://127.0.0.1:{server.server_port}/accounting.html",
        width=1490, height=960, js_api=api)
    api._native_window = window
    result = {"status": "NOT_RUN"}

    def test():
        nonlocal result
        try:
            for _ in range(240):
                time.sleep(.15)
                try:
                    if window.evaluate_js("Boolean(document.querySelector('.sac-root') && typeof window.madar?.tarazAiChatCommand==='function')"):
                        break
                except Exception:
                    continue
            else:
                raise RuntimeError("WebView2 native startup unavailable")
            window.evaluate_js(JS_TEST)
            for _ in range(230):
                time.sleep(.18)
                try:
                    raw = window.evaluate_js("JSON.stringify(window.__qaAi||{})")
                    status = json.loads(raw) if isinstance(raw, str) else raw
                    if status.get("status") in ("PASS_AI_CHAT_NATIVE_BRIDGE_SQLITE", "FAIL"):
                        result = status
                        break
                except Exception:
                    continue
            else:
                result = {"status": "BLOCKED", "reason": "QA_RUNNING_TIMEOUT"}
        except Exception as exc:
            result = {"status": "BLOCKED", "reason": type(exc).__name__}
        finally:
            if result.get("status") == "PASS_AI_CHAT_NATIVE_BRIDGE_SQLITE":
                result["syntheticScreenshot"] = capture_owned_window(work / "ai-chat-native.png")
            (work / "native-ai-result.json").write_text(
                json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
            try: window.destroy()
            except Exception: pass

    try:
        webview.start(test, debug=False)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)


def parent():
    if os.name != "nt":
        raise RuntimeError("Windows only")
    start = fingerprint()
    if not OUT.exists():
        acl.secure_private_directory(OUT)
    work = OUT / ("qa-" + uuid.uuid4().hex[:12])
    acl.secure_private_directory(work)
    (work / "qa-owned-marker.json").write_text(
        json.dumps({"syntheticOnly": True, "fingerprint": start}), encoding="utf-8")
    initial = fixture(work / "private-book")
    runtime = work / "qa" / "qa-runtime"
    runtime.mkdir(parents=True)
    roots = {}
    for item in ("roaming", "localappdata", "temp", "userprofile", "webview-profile"):
        roots[item] = runtime / item
        roots[item].mkdir(parents=True)
    env = native.isolated_env(runtime,
        {"roaming": roots["roaming"], "local": roots["localappdata"],
         "bridge": roots["localappdata"]},
        work / "qa-startup.json", native.unused_port())
    env["PYTHONPATH"] = str(ROOT)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
        "--disable-background-networking --disable-sync --no-first-run "
        "--proxy-server=http://127.0.0.1:9 --proxy-bypass-list=<-loopback>")
    previous = {p.pid: p.create_time() for p in psutil.process_iter(["name"])
                if (p.info.get("name") or "").casefold() == "taraz.exe"}
    with native.PrivateDesktop() as desktop:
        pid, handle, thread = desktop.spawn(
            Path(sys.executable), work, env,
            ("-B", str(Path(__file__).resolve()), "--child", str(work)))
        try:
            finished = ctypes.windll.kernel32.WaitForSingleObject(handle, 130000)
            if finished != 0:
                raise RuntimeError("Private native AI QA did not exit; no force kill applied")
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
            ctypes.windll.kernel32.CloseHandle(thread)
    child_report = json.loads((work / "native-ai-result.json").read_text(encoding="utf-8"))
    qa = QAAPI(work / "private-book")
    final = qa.standaloneAccountingRead()
    chats = qa.tarazAiChatList("")["conversations"]
    current = {p.pid: p.create_time() for p in psutil.process_iter(["name"])
               if (p.info.get("name") or "").casefold() == "taraz.exe"}
    passed = (
        child_report.get("status") == "PASS_AI_CHAT_NATIVE_BRIDGE_SQLITE"
        and fingerprint() == start and len(chats) == 1
        and final["revision"] == initial + 1 and len(final["view"]["invoices"]) == 2
        and len(final["view"]["journals"]) == 1
        and final["view"]["currency"] == "RIAL"
        and previous == current
    )
    result = {"status": "PASS_SOURCE_HOSTED_NATIVE_AI_VERTICAL" if passed else "BLOCKED",
              "sourceHostedNotFrozenExe": True, "syntheticOnly": True,
              "uiBridgeSqliteReadback": passed,
              "journalCountUnchangedSinceSyntheticFixture": len(final["view"]["journals"]) == 1,
              "currency": final["view"]["currency"],
              "installedProcessesUnchanged": previous == current,
              "sourceAssetsUnchanged": fingerprint() == start,
              "child": child_report, "qaRun": str(work)}
    (work / "acceptance.json").write_text(
        json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]))
    elif len(sys.argv) == 1:
        raise SystemExit(parent())
    else:
        raise SystemExit("Invalid private AI QA arguments")
