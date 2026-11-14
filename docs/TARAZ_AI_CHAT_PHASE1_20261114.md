# TARAZ AI Workspace Phase 1 — Private local prototype (2026-11-14)

## Decision and boundary

**IMPLEMENTED + SOURCE-HOSTED WINDOWS WEBVIEW2 VERIFIED PASS; NOT FROZEN, NOT INSTALLED.**
The real installed user program remains **1.0.4**. The previously
accepted frozen **1.0.6** (build-e13b4438f5d4, EXE SHA
`300dfff312dad2c5e5cc3984fc5afb39bc381857889989d4072ab83a34b592d3`)
predates this AI workspace. Neither its previous acceptance nor this
source-hosted smoke test establishes an AI feature inside that EXE.

Do not install or activate a candidate until the separate upgrade data
protection and regression gates pass. No live company/accounting/Parsian
data was changed or opened by this feature QA.

**Additional production integration blocker found by source inspection:**
`taraz_desktop.py:711` currently creates `TarazAPI(data)` without an
identity store/token or immutable company workspace ID. The new AI service
correctly **denies** that legacy implicit-admin route. The passing native
QA explicitly constructs a *synthetic authenticated company session*; it
does not establish a functioning production login/AI tab. Wire a real
verified company selector/identity session before using AI in normal
TARAZ startup. Do not solve this by granting AI access to implicit
`local` admin. **The current automatic backup implementation does not
include this new AI chat DB**: `standalone_accounting_auto_backup.py`
backs up `standalone-accounting.sqlite3` and optional `.templates.json`
and `.users.json` companions. Portable DPAPI key recovery is likewise
unimplemented. Do not treat existing automatic accounting backups as
complete profile backups.

## Implemented vertical path

1. The user opens **دستیار تجاری** from the existing TARAZ navigation,
   creates a conversation, writes a Persian request and sees history.
2. Deterministic **local rules-v1** recognize an exact company customer,
   exact catalog item + unit + quantity, and the last **issued invoice
   belonging to the same customer** with the exact catalog `itemId`.
   The newest source is selected by the **official invoice issue
   sequence number**, never a backdated `documentDate`. If two
   different unit prices for the same item coexist in that source
   invoice, the operation fails closed rather than inventing a price.
3. For every proposed line, the UI displays the source invoice ID/date
   and price. No source or ambiguous customer means **BLOCKED**.
4. The proposal displays total, RIAL/TOMAN source currency, and explicit
   zero discount/tax warning. The operator must manually review a checkbox.
5. Only then does the native API use `standaloneAccountingCommand` and
   its authorized `invoice.create` CAS to create a **draft**, never issue
   or post. A pending action is first claimed as uncertain; ambiguous
   retries are not replayed blindly.
6. The same user/company can reopen the encrypted conversation after
   restarting the host, search titles/messages, export JSON, and request
   deletion/redaction while retaining minimal execution audit metadata.

Example verified only with synthetic records:

> برای شرکت آریا یک فاکتور فروش بساز. ۱۰۰ عدد جعبه و ۲۰۰ عدد لیبل اضافه کن.
> قیمت هر کالا را از آخرین فاکتور معتبر همین مشتری بردار.

The test fixture contained an issued source invoice with catalog-linked
prices 1,000 and 500 RIAL. The request produced an inspectable
**200,000-RIAL draft** only after a distinct explicit user approval.
The test's synthetic source invoice was manually seeded; its original
synthetic Journal existed **before** AI execution. AI execution did not
increase the journal count. This does not authorize live financial posting.

## Storage contract v1

Module `taraz_ai_chat_store.py`, DB `taraz-ai-chat.sqlite3` inside the
selected **company** data directory (never the installed program folder).
Tables: `conversations` (tenant/user/status/title/timestamps/schema),
`messages` (role, DPAPI ciphertext, revision, timestamp/status, source
references), `executions` (tool, encrypted proposal, source revision,
approval/execution status, audit timestamp), `provider_requests`
(model/provider/status/latency/token/consent), `context_links` (source
entity/reference/revision), `action_keys` (actor/tenant scoped encrypted
replay receipts for create/send with cryptographically random request IDs).
`PRAGMA user_version=1`; read-only calls do not create the DB; future
unsupported schema versions fail closed.

**Security:** account identity is revalidated in the native host for every
operation; explicit company directory and tenant/user ownership are checked
before reading a conversation or querying prices. Message/proposal bodies
are Windows DPAPI encrypted with tenant + user entropy. Credentials, tokens,
and PEM markers are rejected as chat input. No HTTP/model request is made
by this vertical. The provider status correctly reports whether any actual
model is selected and whether it remains unverified.

**Important limitation:** Windows DPAPI protection is bound to the current
Windows security principal. A plain copied DB is **not independently
restorable on another computer/user**. Secure key export/restore and
multi-host synchronization are **BLOCKED** until independently designed and
tested. Encrypted content remains readable after ordinary same-user
restart; a portable backup guarantee is not claimed. Title and structured
audit metadata are not encrypted and should not contain secrets.

## Supported, rejected and pending capabilities

| Capability | State |
| --- | --- |
| Local conversation create, reopen, search and encrypted messages | VERIFIED PASS (Windows synthetic) |
| Company/user separation | VERIFIED PASS (Python synthetic) |
| Native UI → WebView2 bridge → SQLite | VERIFIED PASS, source-hosted only |
| Last same-customer issued-invoice price from catalog-linked lines | VERIFIED PASS (synthetic; official issue order and conflicting source price negatives) |
| Manual approval to official API **draft** | VERIFIED PASS (synthetic) |
| Unauthorized or stale action replay refusal | VERIFIED PASS (Python synthetic) |
| Lost-response/concurrent create-send idempotency | VERIFIED PASS (13 focused synthetic tests; atomic encrypted receipt) |
| Online model inference / web search / cloud consent | NOT TESTED; no connection made |
| Quality-certified local LLM | BLOCKED pending independent quality evidence |
| Read actual MADAR task | BLOCKED pending authenticated, pinned source |
| RADAR adapter | BLOCKED pending real source/API discovery |
| Cross-device encrypted history sync / portable key recovery | NOT IMPLEMENTED |
| Frozen EXE UI acceptance for this new AI feature | NOT TESTED |
| Real installed/runtime company identity → AI access | BLOCKED: normal entrypoint uses unauthenticated `TarazAPI(data)` |
| User 1.0.4 → new app upgrade while retaining AI history | NOT TESTED |
| Physical printing / official issuance / real bank actions | NOT TESTED / PROHIBITED IN THIS QA |

## Evidence

- `py -3.12 -B -m unittest tests.test_taraz_ai_chat_vertical_20261114 -q`:
  **11 tests PASS**, Exit **0**, real Windows DPAPI/SQLite and native
  `TarazAPI` with synthetic ledger.
- `py -3.12 -B -m unittest tests.test_taraz_ai_chat_vertical_20261114 tests.test_taraz_ai_chat_idempotency_20261114 -q`:
  **24 tests PASS**, Exit **0**. The 13 extra tests verify stable
  client-generated request IDs, encrypted durable replay receipts,
  crash/lost-response safety, concurrency duplicate prevention,
  source-price immutability after a lost reply and transaction rollback.
- `npm run build`: **2,062 modules**, Exit **0**;
  current source UI build, not a frozen package.
- Independent existing-feature regression:
  `npm run test:orders` passed **59 Python + 16 Edge/Node**
  tests, Exit **0**. `npm run test:p1` passed **34 Python +
  11 Edge/Node** tests, Exit **0** when rerun without another
  simultaneous browser suite. An earlier concurrent P1 run failed
  at Edge `page.reload: net::ERR_EMPTY_RESPONSE`; the isolated
  single test and then the entire sequential P1 suite passed.
  The concurrency hypothesis is plausible, not independently proven.
- `py -3.12 -B scripts/qa_taraz_ai_chat_native_20261114.py`:
  `PASS_SOURCE_HOSTED_NATIVE_AI_VERTICAL`, private Windows desktop,
  WebView2, actual production native bridge and independent SQLite.
  Both `PASS_AI_CHAT_NATIVE_BRIDGE_SQLITE` and same-account readback
  verified, no cloud/model call, no unintended Journal delta.
  Evidence under
  `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\ai-chat-native-qa-20261114\`.
- A synthetic **nonblank native screenshot was individually visually
  inspected** and clearly displayed the real dark TARAZ «دستیار تجاری»
  WebView2 UI, the Persian conversation, the assistant response and
  the source-linked proposal with **RIAL** as the currency:
  `ai-chat-native-qa-20261114/qa-760c5985023e/ai-chat-native.png`.
  It was generated via exact owned-window `PrintWindow`, not a mockup;
  SHA-256 `b5babd045f3f5b0dca5a9dd792a9381ff5bbff2522a8ed3cbf356902cff60b0a`.
  The same run's native bridge/SQLite readback confirmed `currency=RIAL`
  and Draft total `200000`. A preceding all-white ImageGrab frame was
  rejected and Win32 pointer-handle cleanup signatures were corrected.
  A create-only copy was hash-verified at
  `docs/assets/taraz-ai-chat-native-qa-20261114.png` and a read-only
  visual preview is available at
  `docs/TARAZ_AI_VISUAL_PREVIEW_FA_20261114.html`.
- Source-hosted WebView2 emitted the protective
  `PermissionError: Unverified personal accounting ledger` on guarded
  Parsian history access and a temporary directory cleanup warning; these
  are not falsely counted as an all-path release pass.

## Files introduced or modified

- `taraz_ai_chat_store.py`, `taraz_ai_invoice_intake.py`,
  `taraz_ai_business_service.py`.
- `taraz_desktop.py` authenticated bridge endpoints
  `tarazAiChatList/Read/Command`.
- `standalone_accounting_desktop.py` explicit WebView2 bridge methods.
- `src/taraz_ai_chat_workspace.jsx` and
  `src/taraz_ai_chat_workspace.css`.
- `src/standalone_accounting_workspace.jsx` navigation/section.
- `tests/test_taraz_ai_chat_vertical_20261114.py`.
- `scripts/qa_taraz_ai_chat_native_20261114.py`.
- `tests/test_taraz_ai_chat_idempotency_20261114.py`.

## Remaining product gates

Do not label the rules-v1 interpreter as an LLM. Before release:
finalize a robust typed request/proposal contract, bounded history retention,
multi-user identity policy, provider consent, stronger DLP, independent
source-confidence tests, portable DPAPI key backup/migration plan,
real secure upgrade with existing company books, packaged Frozen EXE
regression and user-visible visual QA. No automatic official posting.
