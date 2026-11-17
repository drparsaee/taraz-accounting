# E2 Taraz peer HTTPS loopback pilot | 2026-11-09

Status: **isolated, explicitly opted-in, synthetic-test-only pilot**.
This is not a Windows service, installed listener, production certificate,
Taraz finance API or approved live networking integration.

Implemented in new taraz_mtr_peer_http.py. Uses only Python standard-library
http.server, ssl, socketserver, hashlib/hmac and the existing
taraz_mtr_peer_registry.py. The existing registry was not edited.

## API and route contract

Factory:

    create_loopback_https_server(
        *, registry: TarazPeerRegistry, transport_bearer: bytes,
        certfile: Path, keyfile: Path, opt_in: bool = False,
        port: int = 0, read_timeout_seconds: float = 2.0
    ) -> ThreadingHTTPServer

There is deliberately no module entry point, autorun or background service.
The caller has to provide opt_in=True, an independently provisioned
**at least 32-byte**, printable ASCII transport bearer, and trusted TLS server
certificate/private-key paths, then explicitly invoke serve_forever().
The factory always binds IPv4 127.0.0.1, never 0.0.0.0, ::, a LAN hostname
or any caller-specified interface. Port zero is suitable for synthetic tests.
No server is running after the tests shut down their temporary fixture.

Accepted request routes, **POST only**:

    /mtr/peer/v2/intake
    /mtr/peer/v2/query

Both require exact Content-Type: application/vnd.mtr-peer+json, exact
Host: 127.0.0.1:<selected port>, HTTP/1.1, exactly one Content-Length
containing an integer 1 through 32768, exactly one Authorization header
using the form Bearer <opaque-server-configured-token>, and no duplicate
headers. Transfer-Encoding, chunking, Expect: 100-continue, forwarded
identity assertions, unrecognized headers, non-JSON media, querystrings,
alternative route spellings and unapproved methods are rejected.
The connection closes after each response. Body reads have a monotonic
total deadline plus a socket read timeout.

The server validates TLS and constant-time compares SHA-256 digests of
configured bearer and submitted bearer **before reading a body**. Only after
this separate transport authentication does it call the existing registry
with verified_transport_peer=True, which is never obtained from a header,
JSON field, URL parameter or user-supplied Boolean.

Registry then independently verifies a canonical v2 signed request or query
envelope, HMAC-SHA256, directional Madar key, organization, sender, audience,
actor role and timestamp. Payload / envelope validation is performed by
the existing registry and its durable metadata database.

### Responses

- Intake success: HTTP 200, Content-Type application/json, bounded metadata
  body with requestId, received=true, idempotent=true/false and
  financialEventCreated=false. No official approval or ledger posting.
- Query success: HTTP 200, Content-Type application/vnd.mtr-peer+json,
  **unchanged canonical signed v2 receipt bytes from TarazPeerRegistry**.
  The registry emits status received or unknown, never a fabricated proof of
  not_received. This is a metadata arrival receipt only.
- Bad/missing bearer: 401. Valid bearer but invalid signed envelope, role,
  organization, key or time: 403. Conflicting request/query identity: 409.
  Invalid HTTP structure/Host or duplicate headers: 400; missing/invalid
  length: 411; oversized body: 413; wrong content-type: 415; unsupported
  Expect: 417; read timeout: 408; unknown route: 404; wrong method: 405.
  Internal server failures: 503 without exception detail.

Errors do not echo authorization, payload, MAC, HMAC keys or filesystem paths.
Responses include Cache-Control: no-store, Content-Length, Connection: close
and X-Content-Type-Options: nosniff. HTTP request logging is suppressed.
At most eight handler threads run concurrently, with a small accept backlog.

## Security boundaries and operational gaps

- Server-side TLS authenticates the server to a properly validating client,
  **not the client to the server**. The independent bearer authenticates the
  client in this pilot; this is NOT mutual TLS, enterprise identity, certificate
  pinning or proof of a hardware-bound key. Host configuration and TLS
  certificate trust on the Madar client remain a separate integration gate.
- Bearer and both HMAC directional secrets must be distinct, randomly
  generated, confidential, rotated and ACL-protected in any future deployment.
  Test-only fixed bearer/certificate/unencrypted private key embedded in the
  synthetic test file are deliberately public and **must never be reused**.
- No outbound network connection is implemented; tests use client requests
  to a temporary HTTPS listener bound to 127.0.0.1 only. There is no
  production service launch, installer, firewall change, LAN listener,
  background retry, queue worker, ledger, invoice or official finance write.
  Registry does persist **metadata-only intake/query/audit** in synthetic
  SQLite during the tests. No finance posting or approval occurs.
- Strict paths/header checks reduce ambiguity but are not an internet-exposed
  HTTP security audit or protection against every HTTP/1.1 parser issue.
  TLS handshake still runs during accept with a bounded timeout; high-load,
  idle-client abuse, resource-exhaustion behavior, cancellation, certificate
  revocation, true multi-PC/LAN interoperability, installer lifecycle and
  power-loss durability remain unverified.
- The current registry is independent and remains the final authority for
  signed peer envelopes and receipt metadata. Any eventual live integration
  requires a trusted session/ACL handoff, transport peer provisioning,
  audited certificate pinning or mTLS design, explicit enablement and a
  separately approved operational acceptance process.

## Synthetic verification

    $env:PYTHONDONTWRITEBYTECODE='1'
    python -B -m unittest discover -s tests -p test_taraz_mtr_peer_registry.py -v
    python -B -m unittest discover -s tests -p test_taraz_mtr_peer_http.py -v

HTTPS tests use only TemporaryDirectory certificate/key fixtures, the test
bearer, a fresh synthetic registry SQLite file and 127.0.0.1. Passing them
does not constitute real finance or production security acceptance.
