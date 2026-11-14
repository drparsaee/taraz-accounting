# TARAZ PRIME — actual execution evidence, 2026-11-14

## Decision

**RELEASE / LIVE IN-PLACE UPDATE: BLOCKED.** A new non-installed Windows EXE
has been built from a SHA-pinned source snapshot. Its actual frozen AI workflow
is **not accepted**: the first private native GUI run failed the company-selection
automation gate and stopped before user login. Do not describe the packaged AI
as end-to-end verified, and never activate the packaged installer.

The installed version remains **1.0.4**. No operational finance books, bank
transactions, real profile backup, migration, installation, activation or
automatic journal posting were performed in this execution.

## Source and artifact identity

| Item | Direct observation |
| --- | --- |
| Worktree | `D:/CoS-Test/000- Taraz/taraz-mtr-e2-isolated-20261109` |
| Git starting HEAD | `7c77f2c1629560437c819a45feffce22d28e5535` |
| Branch | `codex/taraz-final-integration-20261112` |
| Source fingerprint | `04a95b21e9c4323c0aae615d76a6d225f6e4ea160ffcc1290f37f822be24c076` |
| Source fingerprint members | `152` |
| New build | `build-d87b73dc956c`, `V106_AAAS_NON_QA_BUILT_NOT_INSTALLED` |
| EXE SHA-256 | `186d551f35a37a8cdef92ba5d182b4ddc80946e248e0efca198f90473dd450c8` |
| ZIP SHA-256 | `c141cca5d703d7e7c5faec7ed2aa2f69fedec04890d42540603fa976b84700df` |
| Update manifest SHA-256 | `d53bf1a52614efcc6141571ecb73b388eaddf9640f9c3d4b04b31a61b286a6a1` |
| Installed EXE SHA-256 | `9712ac008e6b68ddf8a7331bee2d412f3a788750a2cd02e529088e5603e624ce` |
| Installed pointer | `1.0.4` |

Build directory: `D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.6-aaas/build-d87b73dc956c`.
The matching `build-report.json` records PyInstaller PYZ module presence for
`taraz_ai_chat_store`, `taraz_ai_invoice_intake`, `taraz_ai_business_service`,
`standalone_accounting_identity`, registered-company machinery, and the actual
packed JS/CSS bytes. This is **static bundle provenance, not proof of UI use**.

The generated `update-manifest.json` explicitly sets:

```json
{"releaseGateStatus":"BLOCKED_DATA_PRESERVATION","installApplyAllowed":false,"activateApplyAllowed":false}
```

The newly generated `Install-Taraz-V106.ps1` and `Activate-Taraz-V106.ps1`
**reject `-Apply`** until a separately reviewed release-gate implementation
exists. Rollback code is preserved. The old top-level final-install wrapper
still targets an unrelated earlier build and must not be invoked.

## Directly rerun test matrix in this Prime execution

| Scope | Prime-observed outcome | Evidence boundary |
| --- | --- | --- |
| Real registered-company startup/identity | `12/12 PASS` | Temporary identities and company books; not frozen UI login |
| Company QA-only CDP + auth | `18/18 PASS` | Includes nested `books/<company-id>`; source policy, not live WebView acceptance |
| AI encrypted history, review, idempotency and historical search | `35/35 PASS` | Windows DPAPI + SQLite synthetic; includes old >80 conversations, >200 messages |
| Search-truncation UI notification | `2/2 PASS` | Headless Edge React fixture, not actual frozen executable |
| Full registered-company profile snapshot/restore | `12/12 PASS` | Isolated Registry and same Windows principal |
| Three-root snapshot/restore | `16/16 PASS` | Synthetic roaming, local and bridge roots; not real cross-store quiescence |
| Legacy unregistered migration rehearsal | `18/18 PASS` | Strictly synthetic clones, verified existing identity required |
| Earlier synthetic upgrade preflight/restore controls | `13/13 PASS` | Does not authorize live backup or migration |
| Orders/AaaS Python + Edge | `59/59 + 16/16 PASS` | Source/backend/browser, not current frozen order clickthrough |
| P1 invoices, PDF and template Python + Edge | `34/34 + 11/11 PASS` | Source/backend/browser, not current frozen print acceptance |
| v1.0.6 builder/install/rollback fixture | `8/8 PASS` | Disposable paths, hard-block `-Apply`, preserves rollback |
| Frozen AI QA harness contract | `12/12 PASS` | Preflight/fixture/owner/UIA policy; does not prove actual UI |

Actual command groups included `npm run test:orders`, `npm run test:p1`,
`py -3.12 -B -m unittest` for the individual Python suites,
`node --test tests/taraz_ai_chat_search_notice_20261114.test.cjs`, and
`py -3.12 -B scripts/build_taraz_v106_aaas_20261111.py --build --freeze-sha <source fingerprint above>`.
Each listed PASS is limited to the described test scope. These checks do not
prove production backup or installation correctness.

## Actual frozen runtime witness (not accepted)

`scripts/qa_taraz_ai_frozen_real_auth_20261114.py` checked the exact EXE hash,
source hash and non-installed build report, then launched that EXE in a private
Win32 QA desktop with a synthetic company/ledger. The first launch reached an
owned native company-selection window, but owner-scoped UIAutomation did not
successfully submit a company selection. No login, AI chat, draft or SQLite
readback was accepted by this frozen run.

Observed first report:

- `status=BLOCKED`, `frozenExeExecuted=true`, `realNativeLogin=false`,
  `privateUiTest=false`.
- First-phase blocker: `Native QA login or selection was not proven`.
- `gracefulShutdown=true`, `ownedChildrenRemaining=0`,
  `qaTarazProcessesRemain=0`.
- `candidateShaUnchanged=true`, `preexistingTarazPidsUnchanged=true`.

Evidence:
`D:/CoS-Test/MTR-NEXT-UPDATE-CANDIDATES-20261110/taraz-v1.0.6-aaas/frozen-ai-real-auth-qa-20261114/qa-079349154b5848a3/frozen-real-auth-acceptance.json`

The matching `private-auth-1-select.json` says
`ownerVerified=true`, `submitted=false`, `status=BLOCKED_NATIVE_UIA`.
This is an automation/accessibility blocker, **not evidence that the finance
application or AI draft itself failed**. Do not bypass authentication or use
global input to produce a fake successful path.

**Follow-up private run:** The same SHA-pinned candidate was rerun under a
second isolated QA profile at
`frozen-ai-real-auth-qa-20261114/qa-00aef408a757488d`.
The reported native failure was narrowed to
`selectionMethod=SINGLE_REGISTERED_PRESELECTED_TK` and
`errorCode=EXACT_NATIVE_BUTTON_UNAVAILABLE`: the synthetic company's
`tk.Listbox` selection was resolved, but its `ttk.Button` was not exposed as
an invokable UIAutomation Button. The owned EXE again closed gracefully,
leaving no QA Taraz process, and source/binary pins were unchanged. A strictly
owned private-window input fallback is under investigation; this second run
does **not** supersede the `BLOCKED` acceptance status.

**Third private run, independent report readback:**
`frozen-ai-real-auth-qa-20261114/qa-adb61d335ce148ce` confirmed
`private-auth-1-select.json` with `status=PASS_NATIVE_OWNED_UIA`,
`activationMethod=OWNED_TK_FOCUSED_HWND_RETURN`, and
`verifiedTransition=true`. The actual EXE reached its native password login
window. The next `private-auth-1-login.json` was `BLOCKED_NATIVE_UIA` with
`NATIVE_LOGIN_FIELDS_AMBIGUOUS`, as Tk Entry controls were not exposed as two
reliable UIA Edit elements. The third frozen report remained `BLOCKED`, with
graceful close, no orphaned QA Taraz process and unchanged pins. **This is
progress within the test harness, not successful financial/AI acceptance.**

**Fourth private run, final bounded attempt:**
`frozen-ai-real-auth-qa-20261114/qa-63c4a254df694b5f` again confirmed
the legitimate single-company native selector, owned Tk Return activation
and transition to the password window. Its private login helper reported
`PRIVATE_TK_GUI_THREAD_UNAVAILABLE`: the target GUI thread/focus could not
be identified with the strict owner checks needed for private native input.
The top-level frozen report remained `BLOCKED`, `realNativeLogin=false`,
`privateUiTest=false`, `gracefulShutdown=true`,
`qaTarazProcessesRemain=0`, and `candidateShaUnchanged=true`.

Further speculative native-input retries were **stopped**. The test tool
must never escalate to global keyboard/mouse events or implicit-admin login
merely to turn this acceptance gate green. GUI accessibility remains
unresolved until a separately reviewed, independently testable solution is
available. No additional test success is claimed.

## Live data protection gate

Read-only `--live-preflight` reported `BLOCKED_FOR_LIVE_UPGRADE`:
`181` files (`67` SQLite) across roaming Taraz, local Taraz and local
Madar-Taraz-Bridge, totaling `124,011,875` bytes in metadata inventory.
There was a nonempty `-shm` (which alone does not establish an active writer),
plus old lock markers. **Stable source quiescence and cross-database atomic
snapshot have not been proven**, so no live backup was taken. Three separate
restore directory publications also cannot form one atomic operation.

The original unregistered 1.0.4 ledger has no guaranteed attributable
`companies.json` immutable company ID and `local-users.json` identity. The new
startup intentionally rejects it rather than inventing an administrator or
tenant. Existing source copies need independent provenance, authorized company
mapping and migration/rollback on a validated offline clone before any update.

DPAPI-backed AI chat can be restored under the tested same Windows principal;
cross-machine or different-principal disaster recovery is **not implemented**.
Some conversation titles/reference metadata remain plaintext; export is
plaintext with a visible warning. The WebView `ALLOW_DOWNLOADS=True` setting
remains global and requires further download-origin/security review before
publication. AI proposal interpretation is local `rules-v1`, **not a running
LLM**; no cloud model or live MADAR/RADAR data was invoked.

## Remaining required evidence

1. Diagnose private Tk listbox/UIAutomation mismatch without global input;
   run the exact hash-pinned frozen EXE through legitimate login, chat,
   human-reviewed draft, restart and independent SQLite/Journals readback.
2. Independently establish quiescence/authority across all three real roots;
   prove full encrypted backup, cross-store coherent snapshot, isolated
   restore, schema migration, idempotent restart and rollback of a real 1.0.4
   clone, with original data never overwritten.
3. Resolve DPAPI portability/recovery and the legacy company-ID authority
   mapping. Review non-PDF WebView downloads and plaintext chat metadata.
4. Only after all gates are proven may a new hash-pinned installer capable
   of `-Apply` be designed and tested. Do not repurpose the blocked package.

**Release status: NOT READY FOR APPROVAL.**
