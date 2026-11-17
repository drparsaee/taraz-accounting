# Taraz 1.0.6 final immutable build: independent native GUI QA

Date: 2026-11-12. Status: **PASS for native navigation and visible rendering of three screens; NOT full functional acceptance.**

## Exact frozen binary tested

- Final candidate: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-777cb53341bb\binary\Taraz.exe`.
- Actual EXE SHA-256 (independently computed): `54aa3f8ca32703bbc20a033a281197fb1e1cbe88889d6951e92803c702b4b6a4`.
- Build-report source fingerprint: `d07e92f054066858459d4d836de7bf4a56ece0362e8ae9ece755e743ef7a5fcf`. This is a build-report assertion about the frozen source, not a new full checkout hash measurement.
- Independently extracted EXE-embedded GUI JS SHA-256: `70ce00e84c70716e11213c7169375081e9e83b2889bb130b34f14bdebb57e223`, matched to the candidate's compiled asset inventory.
- Build metadata: non-QA, Windows PE 1.0.6.0, marked NOT installed. 181 offline backup members checked using the existing verification function.

## Final native execution and evidence

New independent runner: `scripts/qa_taraz_v106_final_private_gui_20261112.py`.

Run:

```powershell
py -3.12 -B scripts/qa_taraz_v106_final_private_gui_20261112.py --static
py -3.12 -B scripts/qa_taraz_v106_final_private_gui_20261112.py --run-private
```

Final evidence is stored under the restricted QA directory:

`D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\final-native-gui-qa-20261112\qa-final-native-822dcc86e23c\native-gui-report.json`

The runner launches only the SHA-pinned EXE on a new, non-input Win32 desktop, using an ACL-restricted clone of the verified cold backup. It checks the spawned PID binary path before probing. UI Automation selects only controls owned by the spawned process and descendants. The menu button did not expose a usable Invoke pattern; a bounded `WM_LBUTTONDOWN/UP` pair posted to a uniquely identified, owned `Chrome_RenderWidgetHostHWND` under the same private window opened it. **No SendInput, SetForegroundWindow, SwitchDesktop, global keyboard/mouse event, installer, update or signing action was used.**

| Scope | Result | Evidence boundary |
| --- | --- | --- |
| Native EXE startup | **PASS** | Native WebView loaded, native accounting JS bridge present, six WebView2 children, one uniquely owned QA window |
| Sales invoices screen | **PASS, visible** | `فروش` UIA button invoked; page-specific accessible content found; native PrintWindow screenshot `private-invoice.png` examined |
| Orders screen | **PASS, visible** | Private drawer opened, owned `سفارش‌ها` button invoked; form/section markers observed; screenshot `private-order.png` examined |
| Print designer screen | **PASS, visible** | Drawer reopened, `طراحی فرم فاکتور` button invoked; designer markers observed; screenshot `private-print.png` examined |
| Live print design canvas | **PASS, rendered** | Targeted private `WM_MOUSEWHEEL` scrolled page; screenshot `private-print-scrolled.png` was visually inspected, showing template preset controls and actual populated canvas |
| New sales invoice composer | **PASS, opened only** | `ثبت فاکتور جدید` invoked; beginner editor accessible markers observed; `private-invoice-beginner.png` captured. No line editing, save or issue |
| Orders professional mode | **NOT VERIFIED** | UIA lookup found its button, but invocation raised `RuntimeException`; no confirmed mode switch |
| Physical print, PDF file export, template save | **NOT TESTED** | No printing or saving action was triggered |
| Local AI inference for order or print | **NOT TESTED** | No model request made; mere visible controls are not runtime inference evidence |
| Financial and order mutations | **NOT ATTEMPTED** | No save, issue, posting, approval, invoice/bill/order command from this QA |
| Original installed app and pre-existing processes | **UNCHANGED** | Installed 1.0.4 attestation same before/after; all pre-existing Taraz PID/start-time pairs preserved |
| QA cloned ledger | **UNCHANGED** | Full cloned SQLite file SHA-256 identical before/after |
| Test EXE shutdown | **Graceful** | `WM_CLOSE` posted to the unique private QA window; spawned root process exited; no process was forcibly terminated. Descendant post-exit count was not independently audited |
| External network connections | **NOT AUDITED** | No external network-safety guarantee derived from this test |

Screenshots are retained **only in `qa-final-native-822dcc86e23c\private-profile\`** behind QA directory ACLs. Some cloned ledger information may appear in them; avoid treating them as public fixtures or uploading them outside the authorized QA environment. These are PrintWindow captures from the native process, not a separate Vite/Edge mock.

## Earlier steps and observations

- Initial final-build run: `qa-final-native-80d48dc80c1d`. Native invoice screen opened and screenshot was captured. CLI stdout encountered a PowerShell console encoding limitation for Persian JSON; the UTF-8 report persisted. The subsequent runner prints ASCII-escaped JSON.
- Next run: `qa-final-native-6d2e1954d655`. Actual native invoices, orders and print designer reached and captured.
- Final run: `qa-final-native-822dcc86e23c`. The same three pages plus native print canvas after scrolling and an opened invoice beginner composer observed; bounded order professional mode control remained unavailable through UIA. **Final status: `PASS_NATIVE_THREE_SCREEN_NAVIGATION_VIEW_ONLY`.**

The prior production build's WebView2 CDP port issue is not retroactively considered fixed. This final test used actual Windows UI Automation and targeted messages under a private desktop instead of CDP. The final candidate's DevTools configuration was not changed.

This proof is specific to frozen build `build-777cb53341bb`. Subsequent source changes or newer rebuilt candidates require their own exact SHA pin and native verification. This result is **not an installation, production finance, cross-user workflow, hardware print, AI-quality, release or complete GUI approval**.
