# Taraz 1.0.6 — final frozen invoice Clarify acceptance

**Date:** 2026-11-12. **Scope:** read-only acceptance of the immutable release `build-777cb53341bb`, with a disposable synthetic accounting host in Microsoft Edge. This report does not certify interaction with a live ledger, installed application, native WebView2 automation, or a physical printer.

## Exact artifact checked

- Build directory: `D:\CoS-Test\MTR-NEXT-UPDATE-CANDIDATES-20261110\taraz-v1.0.6-aaas\build-777cb53341bb`
- Actual EXE: `binary\Taraz.exe`; measured SHA-256 `54aa3f8ca32703bbc20a033a281197fb1e1cbe88889d6951e92803c702b4b6a4`.
- Frozen source inventory SHA-256 declared in that build's `build-report.json`: `d07e92f054066858459d4d836de7bf4a56ece0362e8ae9ece755e743ef7a5fcf`. The inventory itself was not rebuilt for this acceptance.
- Compiled HTML, JS and CSS were read from `web\dist`, their hashes compared against the release report, and the **matching binary members were extracted directly from the EXE** with Python PyInstaller `CArchiveReader`. Extraction was read-only. For each of the three members, SHA-256 **and byte length** agreed with the release file. Thus the tested JS/CSS are the assets embedded in the named EXE, rather than a new local Vite build.

| Frozen member | SHA-256 from actual frozen bytes |
| --- | --- |
| `assets/accounting-CeHlft_L.js` | `70ce00e84c70716e11213c7169375081e9e83b2889bb130b34f14bdebb57e223` |
| `assets/accounting-D-3ByABZ.css` | `1d8c84737f31364d78ab0db5359f6108ec91794c4a81d46ed3a829ba87d4c309` |
| `accounting.html` | Parity checked programmatically against EXE extraction and release report |

## Browser acceptance results

**Command:** `node --test tests/taraz_v106_invoice_final_acceptance_20261112.test.cjs`

**Observed:** 7 tests passed, 0 failed, 0 skipped. The suite used installed Microsoft Edge in headless mode, loading only the above frozen compiled CSS and JavaScript. A fake `window.madar` handled in-memory accounting reads and commands; all non-fixture network requests were blocked. All test customers, products, project IDs, prices and invoices were fictional.

1. Confirmed that declining new-customer registration produces **zero** host commands; accepting it produces exactly one `party.register`. Verified a real returned party ID is subsequently used in `invoice.create`.
2. Verified active catalog SKU proposal, explicit rejection, subsequent explicit acceptance, actual catalog item ID and `متر مربع` unit display. Hitting Enter after a completed line appends a new empty line; the saved invoice contains only the completed line.
3. Saved an invoice draft with independently edited note and additional explanation. The host returned the saved draft, then the UI opened an actual in-memory PDF `blob:` preview and explicit open-for-print link.
4. Existing registered walk-in customer was reused without creating another party. An unregistered walk-in could not save an invoice until the operator separately confirmed a valid `party.register`. Uncoded service remained without `itemId`; its displayed default unit was `عدد`.
5. Creating a sales proforma used `proforma.create` and generated a proforma PDF preview; no `invoice.create` or issue/journal command was sent.
6. Reject/hide semantics: after `دیگر پیشنهاد کد کالا نشان داده نشود`, the preference was persisted in browser `localStorage`, remained effective across a page reload, and did not link catalog IDs automatically.
7. A synthetic Madar inbox proposal inserted an initial text suggestion. After the operator rewrote it and then deleted the note, further edits did not repopulate the original text; the saved invoice command contained no `note` field.

**Financial guard:** every command was captured and validated by the synthetic host; there were no `invoice.issue`, `invoice.approve`, `journal.manual` or `receipt.record` calls during the tested flows. It is an observation about the synthetic scenarios, not a guarantee for every native operation.

The first exploratory run failed two **test setup/expectation** steps: it expected a rejected suggestion to reappear for identical text, and had not reinstalled the synthetic host when reloading the browser. Only the new test file was corrected. The second full run was 7/7 pass; **no production defect was demonstrated and no source patch is proposed**.

## Scope limits and file ownership

- Did not launch, install, mutate or send input to the Windows EXE; the EXE was read only for package parity. The actual native financial screens, printer dialog, paper output, installed v1.0.6 pointer and real ledger remain untested by this worker.
- Browser-generated PDF previews were inspected for the `blob:` URL and printable link; printed pages and actual on-paper catalog unit placement were not visually or physically verified here.
- Catalog records are synthetic entries made available through the same shape as the host's catalog; no real customer or product database was queried.
- Browser `localStorage` persistence was validated in the same synthetic browser context. Cross-device settings persistence is neither present nor claimed.
- Only two new untracked files were created: `tests/taraz_v106_invoice_final_acceptance_20261112.test.cjs` and this report. Existing source, release, installed executables and financial data were left unchanged.
