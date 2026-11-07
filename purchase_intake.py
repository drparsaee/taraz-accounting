"""Unpriced supplier work intake with immutable audit receipts.

An intake represents a supplier's *work and quantity*, not a booked payable.
Only after the accountant prices, reviews and issues a separately created bill
may the existing double-entry ledger recognize liability. Pure and bounded.
"""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json
import re

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z')
MAX_INTAKES = 20_000
MAX_EVENTS = 50_000
MAX_PRICE = 10**15


def _id(value):
    if type(value) is not str or not ID.fullmatch(value):
        raise ValueError('Invalid intake identity')
    return value


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()


def _text(value, maximum=300):
    if type(value) is not str or not value.strip() or len(value) > maximum or any(
            ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid supplier intake description')
    return value.strip()


def empty_intakes():
    return {'schemaVersion': 1, 'records': {}, 'receipts': {}}


def validate_intakes(value):
    if type(value) is not dict or set(value) != {'schemaVersion', 'records', 'receipts'} or value['schemaVersion'] != 1:
        raise ValueError('Invalid intake state')
    records, receipts = value['records'], value['receipts']
    if type(records) is not dict or len(records) > MAX_INTAKES or type(receipts) is not dict or len(receipts) > MAX_EVENTS:
        raise ValueError('Unbounded intake state')
    for key, row in records.items():
        _id(key)
        expected = {'id', 'projectId', 'cardId', 'stepId', 'description', 'quantity',
                    'supplier', 'unitPrice', 'status', 'createdAt', 'updatedAt', 'billId'}
        if type(row) is not dict or set(row) != expected or row['id'] != key:
            raise ValueError('Invalid supplier intake record')
        for field in ('projectId', 'cardId', 'stepId'):
            _id(row[field])
        _text(row['description'])
        if type(row['quantity']) is not int or not 1 <= row['quantity'] <= 1_000_000:
            raise ValueError('Invalid intake quantity')
        party = row['supplier']
        if type(party) is not dict or set(party) != {'id','name','kind','reference'} or party['kind'] != 'supplier':
            raise ValueError('Invalid intake counterparty')
        _id(party['id']); _text(party['name'])
        if type(party['reference']) is not str or len(party['reference']) > 100:
            raise ValueError('Invalid intake supplier reference')
        if row['unitPrice'] is not None and (type(row['unitPrice']) is not int or
                                             not 0 < row['unitPrice'] <= MAX_PRICE):
            raise ValueError('Invalid intake unit price')
        if row['status'] not in {'unpriced','priced','converted','cancelled'}:
            raise ValueError('Invalid intake status')
        if ((row['status'] == 'unpriced') != (row['unitPrice'] is None)) and row['status'] not in {'cancelled'}:
            raise ValueError('Unpriced intake must not have a price')
        if (row['status'] == 'converted') != (row['billId'] is not None):
            raise ValueError('Converted intake requires bill reference')
        if row['billId'] is not None:
            _id(row['billId'])
        if not all(type(row[f]) is str and 0 < len(row[f]) <= 64 for f in ('createdAt','updatedAt')):
            raise ValueError('Invalid intake timestamp')
    for key, receipt in receipts.items():
        _id(key)
        if type(receipt) is not dict or set(receipt) != {'fingerprint','result'} or type(receipt['fingerprint']) is not str:
            raise ValueError('Invalid intake receipt')
        if not re.fullmatch(r'[a-f0-9]{64}', receipt['fingerprint']):
            raise ValueError('Invalid intake event digest')
    return True


def selected_step(card, step_id):
    """Only recorded steps with a stable ID may become supplier intakes."""
    _id(step_id)
    found = []
    for item in card.get('checklist', []):
        if item.get('id') == step_id:
            found.append(item)
    for group in card.get('checklists', []):
        for item in group.get('items', []):
            if item.get('id') == step_id:
                found.append(item)
    if not found:
        raise ValueError('Selected work step missing or not uniquely identified')
    # Normalized Madar state mirrors legacy checklist items into its generated
    # named checklist. Both representations refer to the SAME stable item ID.
    # Reject genuinely conflicting records instead of confusing this mirror
    # for two different supplier work steps.
    descriptions = {_text(item.get('text', '')) for item in found}
    if len(descriptions) != 1:
        raise ValueError('Conflicting work step description')
    return descriptions.pop()


def _command(state, command, *, cards, projects, now):
    typ = command['type']
    if typ == 'intake.create':
        if set(command) != {'type','eventId','intakeId','projectId','cardId','stepId','quantity','supplier'}:
            raise ValueError('Unexpected intake create fields')
        if len(state['records']) >= MAX_INTAKES:
            raise ValueError('Intake capacity exceeded')
        iid = _id(command['intakeId']); pid = _id(command['projectId'])
        cid = _id(command['cardId']); sid = _id(command['stepId'])
        if not any(p.get('id') == pid for p in projects):
            raise ValueError('Unknown project')
        selected = [t for t in cards if t.get('id') == cid and t.get('projectId') == pid
                    and t.get('deleted') is not True]
        if len(selected) != 1:
            raise ValueError('Task missing from project')
        description = selected_step(selected[0], sid)
        quantity = command['quantity']
        if type(quantity) is not int or not 1 <= quantity <= 1_000_000:
            raise ValueError('Invalid work quantity')
        supplier = command['supplier']
        if type(supplier) is not dict:
            raise ValueError('Supplier required')
        if set(supplier) != {'id','name','kind','reference'} or supplier['kind'] != 'supplier':
            raise ValueError('Named supplier required')
        _id(supplier['id']);_text(supplier['name'])
        if type(supplier['reference']) is not str or len(supplier['reference']) > 100:
            raise ValueError('Invalid supplier reference')
        if iid in state['records'] or any(r['projectId'] == pid and r['cardId'] == cid and
           r['stepId'] == sid and r['status'] != 'cancelled' for r in state['records'].values()):
            raise ValueError('Work step already assigned to a supplier intake')
        state['records'][iid] = {'id': iid,'projectId': pid, 'cardId': cid, 'stepId': sid,
            'description': description, 'quantity': quantity, 'supplier': deepcopy(supplier),
            'unitPrice': None, 'status':'unpriced', 'createdAt':now,
            'updatedAt': now, 'billId': None}
        return {'intakeId':iid, 'status':'unpriced', 'bookedPayable':0}
    if typ == 'intake.price':
        if set(command) != {'type','eventId','intakeId','unitPrice'}:
            raise ValueError('Unexpected intake price fields')
        row = state['records'].get(_id(command['intakeId']))
        if row is None or row['status'] not in {'unpriced','priced'}:
            raise ValueError('Only open supplier intakes may be priced')
        price = command['unitPrice']
        if type(price) is not int or not 1 <= price <= MAX_PRICE or row['quantity']*price > MAX_PRICE:
            raise ValueError('Invalid supplier work unit price')
        row.update(unitPrice=price,status='priced',updatedAt=now)
        return {'intakeId':row['id'],'status':'priced','proposedTotal':row['quantity']*price,
                'bookedPayable':0}
    if typ == 'intake.cancel':
        if set(command) != {'type','eventId','intakeId'}:
            raise ValueError('Unexpected intake cancellation fields')
        row = state['records'].get(_id(command['intakeId']))
        if row is None or row['status'] not in {'unpriced','priced'}:
            raise ValueError('Only an unconverted supplier intake can be cancelled')
        row.update(status='cancelled',updatedAt=now)
        return {'intakeId':row['id'],'status':'cancelled','bookedPayable':0}
    raise ValueError('Unsupported supplier intake command')


def apply_intake(state, command, *, cards, projects, now):
    validate_intakes(state)
    if type(command) is not dict or type(command.get('type')) is not str:
        raise ValueError('Invalid intake command')
    eid = _id(command.get('eventId'))
    fingerprint = _digest(command)
    if eid in state['receipts']:
        saved = state['receipts'][eid]
        if saved['fingerprint'] != fingerprint:
            raise ValueError('Intake eventId payload conflict')
        return {'state': deepcopy(state), 'result': deepcopy(saved['result']), 'changed': False}
    if len(state['receipts']) >= MAX_EVENTS:
        raise ValueError('Intake audit receipt capacity reached')
    cloned = deepcopy(state)
    result = _command(cloned, command, cards=cards, projects=projects, now=now)
    cloned['receipts'][eid] = {'fingerprint':fingerprint,'result':deepcopy(result)}
    validate_intakes(cloned)
    return {'state':cloned,'result':result,'changed':True}


def mark_converted(state, intake_id, bill_id, now):
    validate_intakes(state)
    cloned=deepcopy(state)
    row=cloned['records'].get(_id(intake_id))
    if row is None or row['status'] != 'priced':
        raise ValueError('Only priced supplier intake can become a bill draft')
    row.update(status='converted',billId=_id(bill_id),updatedAt=now)
    validate_intakes(cloned)
    return cloned
