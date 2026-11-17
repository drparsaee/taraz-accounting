# External Madar actor link, Taraz QA source only (2026-11-10)

## Why this is necessary

The real Madar `principal_actor_id` has the form
`mtr-actor-v1-` followed by 64 lowercase hex characters (77 total).
Taraz's `LocalCompanyIdentity` username is at most 40 characters.
Comparing these as the same identity always fails. The external ID stays
external; a current Taraz finance operator remains a distinct local user.

## Manual synthetic flow

1. Construct `ManualExternalActorLinks` with an authenticated,
   registered-company `AccountingDesktopAPI`, the existing
   `TarazPeerRegistry` and **same trusted** `PeerConfig`, the canonical
   reviewed bridge root, and an **independent, private, existing-directory**
   `external-actor-links.sqlite3` path.
2. A real local company administrator explicitly invokes
   `authorize_manual(signed_madar_original=..., signed_madar_query_challenge=...,
   company_id=..., administrator_token=..., explicit_manual_action=True)`.
   Both exact Madar v2 HMAC messages must already be registered, current and
   agree on sender, organization, key, role, original request and digest.
   Durable source and review are read independently. The grant binds the
   external actor, company, Taraz operator and role, project, source digest,
   peer configuration identity, original and query wire hashes. It expires
   no later than 90 seconds, and cannot be granted again.
3. Attach the *same instance* as `external_actor_links` when constructing
   `ManualFinanceBindingAuthority`. During explicit manual evidence
   inspection, pass `external_link_admin_token` for a **current admin
   session**. The finance authority validates the signed request/query and
   exact preexisting ledger evidence, consumes the admin grant once and
   performs its final readback. It never posts, retries or reverses anything.
4. `revoke_manual(...)` permanently revokes an unused grant. A revoked,
   expired, already consumed, role-changed, company-changed, key-mismatched or
   signature-mismatched request fails closed. SQLite PK and immediate
   transaction protect one-time consumption among processes.

## Security boundary and remaining blockers

The peer HMAC authenticates a **configured Madar peer key**. It does not
independently attest which Madar human owns the 77-character actor ID.
Manual Taraz admin approval creates a local consent mapping, **not**
independent Madar identity proof. The output therefore retains:

- `independentlyAuthenticatedMadarActorVerified=False`
- `trustedMadarInvoiceBindingVerified=False`
- `officialFinanceReceiptVerified=False`
- `financialEventCreatedByThisOperation=False`

This is **SOURCE-ONLY, NONOPERATIONAL**. Prime's separately reported
inspection of the current SHA-pinned QA EXE's embedded PYZ TOC found neither
`taraz_mtr_external_actor_link` nor
`taraz_mtr_finance_binding_authority` bundled there. That observation has
not been independently reproduced in this worker's scope.
There is no GUI/admin flow or deployed company provisioning for this new
operator-only QA API. No signed official finance receipt protocol or
end-to-end authenticated Madar principal certificate is implemented here.
Local OS administrators with unfettered access to private SQLite files remain
outside this security model. Under ambiguous failures after one-time
consumption, the workflow stops and requires manual investigation.

Synthetic validations:
`python -m unittest discover -s tests -p test_taraz_mtr_external_actor_link_20261110.py -v`
and the preexisting
`test_taraz_mtr_finance_binding_authority_20261110.py`.
