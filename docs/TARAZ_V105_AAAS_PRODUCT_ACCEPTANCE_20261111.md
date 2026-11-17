# Taraz 1.0.5: AaaS-first candidate and Green user testing

**Date:** 2026-11-11. **Status:** GREEN USER-TEST AVAILABLE, NOT PUBLIC LAUNCH.

## User product intent

Taraz must be an agent-assisted work desk, not a traditional accounting
collection or Mohsen Faktor clone. The beginner completes invoice and order
work with a simple flow; the professional retains all controls. Orders must
remain separate from quotes and financial journals, with real production
quantities, vendor costs, and human approval.

## Implemented in this candidate

- One-screen beginner invoice: customer, line items, numeric/tax preview,
  required-field feedback, explicit Save Draft, mode switching to the
  retained professional editor. No automatic issue or financial posting.
- Separate sales/purchase order workspace, novice and professional modes,
  100 sold vs 120 planned-production quantity with 20 planned waste,
  vendor names and production-stage estimates, manually confirmed states.
- Authenticated native order bridge and separate per-company SQLite orders
  store with optimistic concurrency (CAS), exact request validation,
  idempotency, audit records and no automatic financial events.
- Conservative free-text local suggestion for order fields is deterministic,
  and is NOT a general-purpose LLM autonomous agent.

## Build evidence and test scope

Immutable build directory:

    D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.5-aaas\build-a605e1eb5052

136-source SHA-256: 74b7e92295c167e1f9f8bf2ff8f16879e72ea425a8d293b7247fdccbeb0a10fb

Actual native EXE: 17,075,059 bytes; SHA-256
59b1d32197ebbd3b1bc34f8ce4cc2a652d84fa45fa9d091379ea839e38bdf259

ZIP: 16,815,597 bytes; SHA-256
709e2493a052bf941b8605cba2cb23eef620d6e2a8a9026f7f1a8bc7e048e922

- The actual EXE passed PE 1.0.5.0 / PYZ 1.0.5 / QA_ONLY=False checks,
  TarazAPI method + WebView2 bridge + order module inclusion, and byte
  equality of compiled Vite resources packed in PyInstaller.
- Worker23 reported 8/8 Windows disposable install/activate/rollback
  acceptance tests passed; eight-member ZIP hashes verified.
- Prime observed 14/14 order-store tests, 9/9 order UI source tests,
  2/2 private real Microsoft Edge order-flow tests, and
  2/2 direct synthetic native TarazAPI tests passed.
- Worker27 reported 6/6 real Edge tests of compiled beginner invoice UI
  using a synthetic host. These are not live financial posting tests.
- Prime executed the actual 1.0.5 EXE on a **private non-input desktop**
  against a cloned verified offline backup: native window and WebView2
  loaded, native accounting bridge present, test-owned processes cleaned up.
  Status PASS_GREEN_V105_PRIVATE_NATIVE_STARTUP_ONLY.

## Current test arrangement

Blue v1.0.4 is installed and active. Its installed binary SHA-256 still is
9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce.
Read-only install preflight refused to install 1.0.5 while Blue processes
were running; this guard was respected. The installed pointer remains 1.0.4
and installed versions/1.0.5 does not yet exist.

The real non-QA Green v1.0.5 was then visibly launched **outside the
installed version pointer** against a persistent, independently copied
QA-marked profile. The cold backup's 181 files were individually rehashed.
After launching Green, direct readback showed both Blue and Green Taraz
processes, Green native WebView loaded=true, bridge=function, 21 navigation
buttons, and no task bridge. Blue profile/pointer were not edited.

Green test launcher (double-click; independent QA data):

    D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.5-aaas\Run-Taraz-v1.0.5-GREEN-TEST.cmd

After **closing all Blue/Green windows**, optional installed-version
installer/activator (created, NOT executed):

    D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.5-aaas\Install-Activate-Taraz-v1.0.5-WHEN-CLOSED.cmd

Rollback wrapper (created, NOT executed):

    D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.5-aaas\Rollback-Taraz-v1.0.5-To-v1.0.4-WHEN-CLOSED.cmd

## Still not certified

Manual end-to-end acceptance in Green, real financial post/issue, clean
onboarding for a new company, autonomous AI reasoning and tools, Madar
order-state integration, public distribution/signing and real installed
production rollback are NOT verified. The isolated Green profile uses a
copy of private cold backup data; its new test entries do not alter Blue
and will not automatically migrate into the installed version later.
