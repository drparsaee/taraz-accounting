# Critical decision pending

**Which company-approved, dated purchase-tax policy and ledger account should govern recoverable input tax in Taraz, and who has authority to attest eligibility?** The software cannot independently assert a legal tax rate or whether a particular purchase is recoverable.

Until the authoritative policy is available, do not post recoverable purchase tax, create an official tax document, or silently move posted expense-account balances into an asset account.

## Completed independently

- Source review confirmed that purchases currently debit `5200` and purchase returns reverse `5200`. Warehouse receipt rejects `recoverable` treatment.
- `taraz_purchase_tax_contract.py` provides a **pure preview**, distinguishing `exempt`, `expense`, and candidate `recoverable` treatment with explicit RIAL amounts and dates. A candidate recoverable amount only suggests account `1250` and **does not create that account**.
- `tests/test_taraz_purchase_tax_contract_20261117.py`: **9/9 PASS** on synthetic inputs.
- Commit `a048ef950718af4de448f19f63dda6766cce47d8` preserves only preview code and tests; there is no real financial posting.

## Why this task remains blocked

The agreed end criterion is journal-level debit/credit and purchase-return consistency **under a real approved, versioned tax policy**. A fabricated legal rate, guessed recoverability, or automatic ledger-account conversion would be unsafe. TAR-09 stays `blocked` and can resume with a verified approved policy and independent tests.

## Safe independent next work

Move the single active task to **TAR-10**, whose source-level business-reference uniqueness and tamper-evidence tests can proceed on synthetic ledgers. Any external trust anchor, signing key or cross-machine recovery still requires separate security design and evidence; no installed or live financial data may be touched.
