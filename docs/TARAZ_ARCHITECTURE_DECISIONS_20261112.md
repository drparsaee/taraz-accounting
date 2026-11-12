# TARAZ — Architecture Decision Record

**Date:** 2026-11-12
**Status:** APPROVED PRODUCT REQUIREMENTS + OPEN FINANCIAL AUTHORITY DETAILS
**Blocking milestone:** PostgreSQL DB2 isolated pilot
**Decision owner:** User; Prime prepares evidence and options

## Purpose

This record separates the user's **approved product requirements** of
2026-11-12 from operational decisions requiring a separate architecture gate.
Earlier all-or-nothing LAN-vs-Cloud and online-only-vs-offline option lists
are historical proposals, not blockers to implementing the approved modes.

## Approved product requirements (2026-11-12)

1. TARAZ, MADAR and RADAR remain independently deployable and releaseable but
   must interoperate through compatible, versioned contracts. Do not assume
   RADAR implementation details until its actual source is recovered.
2. All core business workflows must remain available without **internet**,
   using a designated LAN host or customer-controlled local server.
   An absent local model may disable AI-dependent functions, never manual
   business functions or deterministic validation.
3. Support **A: small-business LAN host**, **B: customer-managed enterprise
   host** and **C: Cloud + on-premises offline node**. In C, clients use a
   central customer LAN node while disconnected; they are not each an
   independent authoritative financial server.
4. Support fully Cloud-only operation when connectivity is available, in
   addition to Cloud + local offline node. It does not replace A/B/C.
5. AI is optional: online model only when configured, authorized and online;
   local model only when installed, reachable and explicitly configured;
   otherwise AI-dependent functionality is disabled with a visible reason.
   No silent external model calls or fabricated inference success.
6. Hardware/network installation, LAN maintenance and physical availability
   are the customer's responsibility. Application-level security, durable
   synchronization, CAS, duplication prevention, error reporting and recovery
   remain the product's responsibility.
7. No internet dependence may be introduced into LAN-local invoicing, order,
   task or other verified core commercial workflows. **Local host failure is
   distinct from internet failure** and needs its own backup/HA policy.
8. Identity, company isolation, stable entity references, event provenance,
   human approvals, idempotency and structured version compatibility must
   span product boundaries. Formal accounting has one explicit authority.

These are **APPROVED PRODUCT REQUIREMENTS**, not claims that the three
implementations already satisfy them.

## Open architecture decisions — NOT approved by implication

The following still need a reviewed ADR, synthetic failure tests and where
necessary explicit user choice:

1. Official-finance **single writer / lease / fencing** and authority
   transfer between Cloud and LAN offline node; split-brain prevention.
2. Reconciliation/conflict policy for nonfinancial and financial events,
   especially prolonged disconnection and two-site changes. **Never use
   last-write-wins for financial records.**
3. RPO, RTO, backup/restore ownership, minimum hardware/capacity,
   supported topology combinations, retention and key rotation.
4. Tenant-level installation/authorization boundaries, permitted offline
   login lifetime, audit retention and administrative break-glass policy.

No PostgreSQL DB2 pilot, live data cutover or two-way official ledger
replication can infer answers to these OPEN decisions.

### Historical decisions superseded by explicit user instruction

The two former open questions were:

1. Where the central Taraz Backend will run: Office LAN or Cloud/managed
   hosting.
2. What the desktop must do when the central Backend or internet is
   unavailable: online-only, read-only local cache, offline Drafts, or a
   bounded command outbox.

**Superseded:** the product must support **all approved deployment modes**
instead of choosing only LAN *or* Cloud; core business operation without
internet is required instead of choosing online-only/cache-only/drafts-only.
The *specific official financial authority transfer* during an outage remains
OPEN, as documented above.

## ADR-TARAZ-001 — Central Backend topology

**Status: APPROVED multi-topology product requirement; finance authority OPEN**

| Option | Advantages to evaluate | Risks and questions to resolve |
| --- | --- | --- |
| Office LAN host | Local network latency; can remain available during an external internet outage; data may stay on premises | Host availability, power/backup, remote access, TLS and certificate lifecycle, LAN segmentation, maintenance ownership and disaster recovery |
| Cloud / managed host | Remote access across locations; managed availability and backup options; easier centralized updates | Internet dependency, recurring cost, data residency, provider access, connectivity failure, key custody and recovery ownership |

Both LAN and Cloud are supported deployment targets; Cloud + customer LAN
offline node is a separate required option. Customer chooses at installation.
The DB2 architecture gate remains on financial authority, reconciliation,
isolation, backups and RPO/RTO rather than on LAN-versus-Cloud selection.

### Existing network constraints

- Preserve the existing MadarHost and office LAN services.
- Do not change Windows Firewall, DHCP, gateway, router, Wi-Fi, existing
  network shares, printer sharing or unrelated services as part of a Taraz
  topology experiment.
- Do not replace, reconfigure or interrupt the existing MadarHost.
- A future LAN Taraz Backend must be isolated from MadarHost and other office
  services unless a separate, bounded change is explicitly authorized.
- A Cloud option must not silently introduce remote access to Madar data or
  company financial records.

## ADR-TARAZ-002 — Offline policy and operating behavior

**Status: APPROVED offline-first commercial behavior; exact official finance
authority/fencing OPEN**

| Option | User-visible behavior | Required safety model |
| --- | --- | --- |
| Online-only | Read/write requires the central Backend | Clear unavailable state; no false success or locally implied financial posting |
| Read-only cache | Previously synchronized information can be viewed offline | Show source and last-sync time; stale data must be visibly marked; no writes |
| Offline Drafts | User can prepare a local Draft while disconnected | Draft remains Pending and local; no official issue, approval, payment settlement or ledger posting before server acceptance |
| Bounded offline command queue | A limited set of explicitly permitted commands can wait for sync | Per-command identity, company scope, actor, idempotency key, base revision, source digest, expiry and conflict review; no last-write-wins |

The online-only/read-only-cache alternatives **do not meet** the newly approved
core-offline requirement. A customer LAN host must keep commercial operations
available without internet. Pending Drafts are acceptable only where an
operation lacks independently provable official-finance authority; they are
not a substitute for all offline business functions. Durable event outbox and
read-only receipts are allowed to implement nonfinancial sync safely.

### Non-negotiable financial rules

- SQLite business data and the installed 1.0.4 environment remain untouched
  until a separately authorized migration or installation.
- A local Draft is not an issued invoice, approved payment or official
  accounting event.
- Never dual-write to SQLite and PostgreSQL as two authoritative ledgers.
- Never resolve financial conflicts with last-write-wins.
- Every replayable command must be idempotent and revision-aware.
- An uncertain acknowledgement must be reconciled by reading authoritative
  state; do not blindly repeat a financial POST.
- Madar remains read-only by default; broader access requires explicit
  consent and bounded permissions. Taraz remains the authority for formal
  accounting.

## Required decision inputs

Before asking the user to choose, Prime should collect:

1. Expected number of offices, PCs and simultaneous users.
2. Whether users must access Taraz outside the office.
3. Actual internet reliability and acceptable outage duration.
4. Whether offline work means viewing, Draft creation, or executing commands.
5. Data residency, privacy and access-control requirements.
6. Who owns host maintenance, patching, backups and incident response.
7. Required recovery point (RPO), recovery time (RTO) and acceptable cost.

Do not infer these from the MadarHost LAN setup. The existence of a LAN host
does not prove that Taraz should use the same host or share its operational
dependencies.

## Decision gate and allowed work

| Work item | Current permission/status |
| --- | --- |
| DB0 inventory of existing SQLite stores and data ownership | May proceed read-only |
| DB1 Repository contracts and SQLite contract tests | May proceed in an isolated worktree without changing live data |
| DB2 PostgreSQL provisioning/pilot | **BLOCKED on OPEN authority/fencing, conflict resolution, tenant boundaries, backup and RPO/RTO**; LAN/Cloud and offline-first deployment modes are already approved |
| Schema migration against real company data | Not authorized |
| Cutover, dual-write, production connection switch or SQLite deletion | Not authorized; separate explicit approval required |

For unresolved *authority and recovery* details, record the user-approved
outcome with decision date, selected option, rejected alternatives, rationale,
constraints and acceptance criteria. Until then DB2 remains BLOCKED; proceed
with DB0 read-only and DB1 isolated contract tests.
