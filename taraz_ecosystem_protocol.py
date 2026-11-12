"""Versioned nonfinancial interoperability contract for TARAZ/MADAR/RADAR.

This module does not claim that RADAR has a deployed API, and is not an
authentication endpoint. Trusted company and actor identity must come from
the verified host session, never from JSON supplied by a desktop/browser.
Financial ledgers, payments, official numbers and receipts are EXCLUDED until
a single-writer/fencing ADR is approved.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re


SCHEMA_VERSION = 1
PRODUCTS = frozenset({'TARAZ', 'MADAR', 'RADAR'})
ROLES = frozenset({'viewer', 'editor', 'admin'})
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$')
_HEX = re.compile(r'^[a-f0-9]{32}$')
_SHA = re.compile(r'^[a-f0-9]{64}$')

# Typed, metadata-only business references. These do not represent authority
# to issue financial documents, modify a customer's data or post to a host.
EVENT_SCHEMAS = {
    'order.project_link_proposed': {
        'source': 'TARAZ', 'target': 'MADAR', 'entity': 'order',
        'fields': {'projectId': 'id'},
    },
    'task.progress_observed': {
        'source': 'MADAR', 'target': 'TARAZ', 'entity': 'task',
        'fields': {'orderId': 'id', 'state': ('pending', 'done', 'unknown')},
    },
    'reference.link_proposed': {
        'source': None, 'target': None, 'entity': 'reference',
        'fields': {'localRef': 'id', 'remoteRef': 'id'},
    },
}


class ProtocolError(ValueError):
    """Fail-closed contract violation. Never return a silent success."""


@dataclass(frozen=True)
class TrustedScope:
    """Supplied by a native/HTTP host AFTER successful authenticated session.

    Passing a forged TrustedScope is not an authentication mechanism. This is
    deliberately not exposed as a browser-controllable construction service.
    """
    company_id: str
    actor_id: str
    role: str
    source_system: str

    def __post_init__(self):
        for name, value in (('company_id', self.company_id),
                            ('actor_id', self.actor_id)):
            if not isinstance(value, str) or not _ID.fullmatch(value):
                raise ProtocolError('Invalid trusted ' + name)
        if self.role not in ROLES or self.source_system not in PRODUCTS:
            raise ProtocolError('Invalid trusted actor role or product')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def validate_envelope(message, *, scope: TrustedScope):
    """Return normalized nonfinancial event after strict scope/schema checks.

    The caller MUST independently validate sourceEntityId+Revision+Digest
    against the authoritative source store before the event is emitted.
    Successful validation alone does NOT prove source existence or receipt.
    """
    exact = {'schemaVersion', 'eventId', 'idempotencyKey', 'sourceSystem',
             'targetSystem', 'companyId', 'actorId', 'entityType', 'entityId',
             'sourceRevision', 'sourceDigest', 'eventType', 'payload'}
    if type(message) is not dict or set(message) != exact:
        raise ProtocolError('Unexpected or missing interoperability fields')
    if type(scope) is not TrustedScope:
        raise ProtocolError('Verified session scope is required')
    if type(message['schemaVersion']) is not int or message['schemaVersion'] != 1:
        raise ProtocolError('Unsupported protocol version')
    if (message['companyId'] != scope.company_id or
            message['actorId'] != scope.actor_id or
            message['sourceSystem'] != scope.source_system):
        raise PermissionError('Cross-company or forged source identity')
    source, target = message['sourceSystem'], message['targetSystem']
    if source not in PRODUCTS or target not in PRODUCTS or source == target:
        raise ProtocolError('Unknown or identical interoperability endpoints')
    if scope.role not in ('editor', 'admin'):
        raise PermissionError('Viewing role cannot stage business events')
    if (type(message['eventId']) is not str or
            not _HEX.fullmatch(message['eventId']) or
            type(message['idempotencyKey']) is not str or
            not _HEX.fullmatch(message['idempotencyKey'])):
        raise ProtocolError('Invalid event identity or replay key')
    if type(message['entityId']) is not str or not _ID.fullmatch(message['entityId']):
        raise ProtocolError('Invalid stable source entity reference')
    if (type(message['sourceRevision']) is not int or
            message['sourceRevision'] < 1 or
            message['sourceRevision'] > 2**53 - 1 or
            type(message['sourceDigest']) is not str or
            not _SHA.fullmatch(message['sourceDigest'])):
        raise ProtocolError('Invalid source CAS/digest')
    spec = EVENT_SCHEMAS.get(message['eventType'])
    if spec is None or message['entityType'] != spec['entity']:
        raise ProtocolError('Unrecognized or financial business event')
    if (spec['source'] is not None and source != spec['source'] or
            spec['target'] is not None and target != spec['target']):
        raise ProtocolError('Event routed outside its authoritative products')
    if type(message['payload']) is not dict or set(message['payload']) != set(spec['fields']):
        raise ProtocolError('Unknown payload, financial attributes or PII refused')
    for field, expected in spec['fields'].items():
        val = message['payload'][field]
        if expected == 'id':
            if type(val) is not str or not _ID.fullmatch(val):
                raise ProtocolError('Invalid payload reference ' + field)
        elif type(val) is not str or val not in expected:
            raise ProtocolError('Invalid typed payload state ' + field)
    if len(canonical(message).encode('utf-8')) > 8192:
        raise ProtocolError('Event exceeds transport metadata limit')
    return dict(message)
