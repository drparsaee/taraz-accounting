"""Human-approved, CAS guarded Taraz order -> Madar task synchronizer.

Madar stays authoritative for projects/cards; Taraz stays authoritative for
costs, payments and accounting. A new operational card contains a currency-
labelled summary, NEVER a fabricated numeric cost or financial transaction.
The original Madar state is preserved except one newly appended task.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
from http.client import HTTPSConnection
import json
import re
import ssl

from taraz_madar_data_reader import (
    MadarReadError, _network_config, _pinned_json, _validate_host_result,
)

_SHA = re.compile(r'^[0-9a-f]{64}$')
_MAX = 12 * 1024 * 1024


def _canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _source_digest(order):
    return hashlib.sha256(_canonical({
        'id': order['id'], 'revision': order['revision'],
        'kind': order['kind'], 'currency': order['currency'],
        'quantity': order['quantity'], 'production': order['productionQuantity'],
        'actualProduced': order['actualProducedQuantity'],
        'scrap': order['scrapQuantity'],
        'surplus': order['healthySurplusQuantity'],
        'status': order['status'], 'costStages': order['costStages'],
        'costRecords': order.get('costRecords', []),
    }).encode('utf-8')).hexdigest()


def _money(value, currency):
    return 'نامشخص' if value is None else f'{value:,} {currency}'


def _order_task(order, project_id, state):
    if (not isinstance(project_id, str) or not 1 <= len(project_id) <= 120 or
        not any(p.get('id') == project_id for p in state.get('projects', []))):
        raise MadarReadError('Madar project must be visible in authenticated state')
    stages = state.get('stages')
    if not isinstance(stages, list):
        raise MadarReadError('Madar task workflow is missing')
    stage_ids = [item.get('id') for item in stages
                 if type(item) is dict and type(item.get('id')) is str
                 and item.get('archived') is not True]
    if not stage_ids:
        raise MadarReadError('Madar has no active task stage')
    chosen_stage = 'planned' if 'planned' in stage_ids else stage_ids[0]
    definitions = state.get('settings', {}).get('priorityDefinitions')
    priorities = [row.get('id') for row in definitions if type(row) is dict
                  and type(row.get('id')) is str] if isinstance(definitions, list) else []
    chosen_priority = ('medium' if not priorities or 'medium' in priorities else priorities[0])
    currency = order['currency']
    estimated = order.get('estimatedCostTotal')
    approved = order.get('actualCostTotal')
    order_id = order['id']
    records = {row['stage_index']: row for row in order.get('costRecords', [])}
    checklist = []
    for index, stage in enumerate(order['costStages']):
        actual = records.get(index)
        verified = (actual is not None and actual['status'] == 'approved')
        cost_text = _money(actual['actual_cost'] if verified else None, currency)
        description = stage.get('description') or stage['kind']
        caption = (f'{description} | برآورد: {_money(stage["estimatedCost"], currency)}'
                   f' | واقعی تأییدشده: {cost_text}')
        checklist.append({
            'id': f'taraz-step-{order_id[:12]}-{index}',
            'text': caption[:300], 'done': False,
        })
    production = ('فروش/خرید: '+str(order['quantity'])+' '+order['unit']+
                  ' | برنامه تولید: '+str(order['productionQuantity'])+
                  ' | تولید واقعی: '+str(order['actualProducedQuantity'])
                  if order['actualProducedQuantity'] is not None else
                  'فروش/خرید: '+str(order['quantity'])+' '+order['unit']+
                  ' | برنامه تولید: '+str(order['productionQuantity'])+
                  ' | تولید واقعی: نامشخص')
    desc = '\n'.join([
        'خروجی عملیاتی سفارش تراز. مرجع اعداد مالی و تأییدها فقط تراز است.',
        f'Order ID: {order_id} | Revision: {order["revision"]}',
        f'Currency: {currency} | {production}',
        f'ضایعات: {order["scrapQuantity"] if order["scrapQuantity"] is not None else "نامشخص"}',
        f'مازاد سالم: {order["healthySurplusQuantity"] if order["healthySurplusQuantity"] is not None else "نامشخص"}',
        f'برآورد کل هزینه: {_money(estimated,currency)}',
        f'هزینه واقعی تأییدشده: {_money(approved,currency)}',
        'وضعیت سفارش: '+order['status'],
    ])
    now = datetime.now(timezone.utc).isoformat()
    return {
        'id': 'taraz-order-'+order_id,'projectId':project_id,
        'title': ('[Taraz] '+order['title'])[:300],
        'description':desc[:3000],
        'status':chosen_stage,'priority':chosen_priority,
        'dueDate':order.get('scheduleDueDate',''),
        'labels':['Taraz','Order'],
        'createdAt':now,'updatedAt':now,'checklist':checklist,
        'reports':[],'costEnabled':False,'cost':0,
        'tarazOrderSourceId':order_id,
        'tarazOrderSourceRevision':order['revision'],
        'tarazOrderSourceSha256':_source_digest(order),
    }


def prepare_madar_order_state(state, *, order, project_id):
    """Pure, non-mutating and no-clobber planner for ONE operational Madar card."""
    if type(state) is not dict or type(state.get('tasks')) is not list or (
        state.get('version') != 1):
        raise MadarReadError('Unsupported Madar host state')
    identifier = 'taraz-order-'+order['id']
    if any(task.get('id') == identifier or
           task.get('tarazOrderSourceId') == order['id']
           for task in state['tasks'] if isinstance(task, dict)):
        matches = [task for task in state['tasks'] if isinstance(task, dict) and
            (task.get('id') == identifier or
             task.get('tarazOrderSourceId') == order['id'])]
        if (len(matches)==1 and matches[0].get('id')==identifier and
            matches[0].get('tarazOrderSourceId')==order['id'] and
            matches[0].get('tarazOrderSourceRevision')==order['revision'] and
            matches[0].get('tarazOrderSourceSha256')==_source_digest(order) and
            matches[0].get('projectId')==project_id):
            return None, matches[0], 'ALREADY_SYNCED'
        raise MadarReadError('Madar order card already exists or changed; manual reconciliation required')
    if len(state['tasks']) >= 20000:
        raise MadarReadError('Madar task capacity reached')
    candidate = deepcopy(state)
    task = _order_task(order, project_id, state)
    candidate['tasks'].append(task)
    return candidate, task, 'NEW_TASK'


def extract_madar_order_stage_progress(state, *, order, project_id):
    """Return actual checklist completion, never infer it from Taraz costs.

    Read-only reconciliation of human-edited Madar task state. Missing or
    malformed checklist items remain UNKNOWN; no process/finance data is
    copied back and unrelated manual fields are never overwritten.
    """
    if (type(state) is not dict or state.get('version')!=1 or
            type(state.get('projects')) is not list or
            type(state.get('tasks')) is not list or
            not any(type(p) is dict and p.get('id')==project_id
                    for p in state['projects'])):
        raise MadarReadError('Authorized Madar project/tasks state unavailable')
    order_id=order['id']
    task_id='taraz-order-'+order_id
    matches=[item for item in state['tasks'] if type(item) is dict and (
        item.get('id')==task_id or item.get('tarazOrderSourceId')==order_id)]
    if len(matches)>1:
        raise MadarReadError('Duplicate Madar task source identity')
    if not matches:
        return {'status':'NOT_SYNCED','taskId':task_id,'projectId':project_id,
                'stages':[],'readOnly':True,'financialEventCreated':False}
    task=matches[0]
    if (task.get('id')!=task_id or
            task.get('tarazOrderSourceId')!=order_id or
            task.get('projectId')!=project_id):
        raise MadarReadError('Madar project/source identity conflict')
    checklist=task.get('checklist')
    if type(checklist) is not list:
        raise MadarReadError('Madar task checklist is unavailable')
    ids=[item.get('id') for item in checklist if type(item) is dict]
    if any(type(identifier) is not str for identifier in ids):
        raise MadarReadError('Madar checklist identity malformed')
    if len(ids)!=len(set(ids)):
        raise MadarReadError('Madar task has repeated checklist identities')
    witnessed={item['id']:item for item in checklist if type(item) is dict
               and type(item.get('id')) is str}
    stages=[]
    for index,stage in enumerate(order['costStages']):
        source_id=f'taraz-step-{order_id[:12]}-{index}'
        row=witnessed.get(source_id)
        done=row.get('done') if row is not None else None
        stages.append({'index':index,'kind':stage['kind'],'sourceId':source_id,
                       'state':('done' if done is True else
                                'pending' if done is False else 'unknown')})
    same=(task.get('tarazOrderSourceRevision')==order['revision'] and
          task.get('tarazOrderSourceSha256')==_source_digest(order))
    return {'status':'CURRENT_SOURCE' if same else 'SOURCE_CHANGED',
            'taskId':task_id,'projectId':project_id,
            'taskStatus':task.get('status') if type(task.get('status')) is str else None,
            'sourceMatchesCurrent':same,'stages':stages,
            'completedStages':sum(s['state']=='done' for s in stages),
            'unknownStages':sum(s['state']=='unknown' for s in stages),
            'readOnly':True,'financialEventCreated':False}


def read_madar_order_stage_progress(*, order, project_id, connection):
    """Authenticated pinned HTTPS host-read, never POST a task or a journal."""
    host,port,pin,username,password,_origin=_network_config(connection)
    login=_pinned_json(host,port,pin,'POST','/api/login',
                       payload={'username':username,'password':password})
    token=login.get('token')
    if type(token) is not str or not 20 <= len(token) <= 4096:
        raise MadarReadError('Authorized Madar read session unavailable')
    snapshot=_pinned_json(host,port,pin,'GET','/api/state',token=token)
    state,who,revision=_validate_host_result(login,snapshot)
    if who.get('role') not in ('viewer','editor','admin'):
        raise PermissionError('Madar project-view permission required')
    progress=extract_madar_order_stage_progress(
        state,order=order,project_id=project_id)
    return {**progress,'hostRevision':revision,'hostRole':who['role'],
            'source':'MADAR_AUTHENTICATED_HOST_READ','hostWriteAttempted':False}


def _write_pinned_state(host, port, pin, token, state, revision):
    """One TLS-pinned Madar CAS write; never redirects or posts to other origins."""
    if not isinstance(token,str) or not 20 <= len(token) <= 4096 or (
        not isinstance(revision,str) or not _SHA.fullmatch(revision)):
        raise MadarReadError('Madar authentication or source revision unavailable')
    body = _canonical({'state':state,'revision':revision}).encode('utf-8')
    if not 0 < len(body) <= _MAX:
        raise MadarReadError('Madar state write exceeds bounded limit')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    conn = HTTPSConnection(host,port,timeout=8,context=context)
    try:
        conn.connect()
        leaf=conn.sock.getpeercert(binary_form=True)
        if not leaf or not hmac.compare_digest(hashlib.sha256(leaf).digest(),pin):
            raise MadarReadError('Madar TLS certificate changed before write')
        conn.request('POST','/api/state',body=body,headers={
            'Accept':'application/json','Content-Type':'application/json',
            'Authorization':'Bearer '+token,'Connection':'close'})
        response=conn.getresponse()
        if response.status != 200 or (
            response.getheader('Content-Type','').split(';',1)[0].strip().lower()
                != 'application/json'):
            raise MadarReadError('Madar CAS write refused; no retry without fresh review')
        raw=response.read(_MAX+1)
        if not 0 < len(raw) <= _MAX:
            raise MadarReadError('Invalid Madar write acknowledgement length')
        result=json.loads(raw.decode('utf-8'))
        if type(result) is not dict:
            raise MadarReadError('Invalid Madar write acknowledgement')
        return result
    finally:
        conn.close()


def sync_order_to_madar(*, order, project_id, connection, reviewed_revision,
                        preview_digest, manual_confirmation=False, dry_run=True,
                        source_store=None):
    """On-demand verified Madar sync. Real mutation requires admin review.

    The host POST is made only after the human reviewed exact order/project and
    current Madar state revision. Test/preview runs never POST to Madar.
    """
    if type(dry_run) is not bool or type(manual_confirmation) is not bool:
        raise MadarReadError('Explicit boolean sync intent required')
    if not dry_run and manual_confirmation is not True:
        raise PermissionError('Explicit human approval is required before Madar write')
    if (not dry_run and (not isinstance(reviewed_revision,str) or
                        not _SHA.fullmatch(reviewed_revision) or
                        not isinstance(preview_digest,str) or
                        not _SHA.fullmatch(preview_digest))):
        raise MadarReadError('Exact reviewed state revision and digest required')
    if (reviewed_revision is not None and
        (not isinstance(reviewed_revision,str) or not _SHA.fullmatch(reviewed_revision))):
        raise MadarReadError('Invalid Madar revision')
    if (preview_digest is not None and
        (not isinstance(preview_digest,str) or not _SHA.fullmatch(preview_digest))):
        raise MadarReadError('Invalid preview digest')
    host, port, pin, username, password, _origin=_network_config(connection)
    login=_pinned_json(host,port,pin,'POST','/api/login',
                       payload={'username':username,'password':password})
    token=login.get('token')
    if type(token) is not str or not 20 <= len(token) <= 4096:
        raise MadarReadError('Madar session unavailable')
    current=_pinned_json(host,port,pin,'GET','/api/state',token=token)
    state,who,revision=_validate_host_result(login,current)
    if who['role'] not in ('editor','admin'):
        raise PermissionError('Madar editor or admin authorization required')
    if reviewed_revision is not None and revision != reviewed_revision:
        raise MadarReadError('Madar state changed after preview; refresh required')
    candidate,task,status=prepare_madar_order_state(
        state,order=order,project_id=project_id)
    evidence={'orderId':order['id'],'orderRevision':order['revision'],
              'sourceDigest':_source_digest(order),
              'projectId':project_id,'madarRevision':revision,
              'taskId':task['id'],'operation':status}
    digest=hashlib.sha256(_canonical(evidence).encode('utf-8')).hexdigest()
    if preview_digest is not None and preview_digest != digest:
        raise MadarReadError('Madar task preview does not match reviewed source')
    if status=='ALREADY_SYNCED':
        return {'status':status,'taskId':task['id'],'sourceRevision':revision,
                'financialEventCreated':False,'wroteMadarState':False}
    if dry_run:
        return {'status':'PREVIEW_ONLY','taskId':task['id'],
                'sourceRevision':revision,'previewDigest':digest,
                'taskPreview':task,'wroteMadarState':False,
                'financialEventCreated':False}
    if source_store is None:
        raise PermissionError('Authoritative Taraz source recheck required before Madar write')
    fresh=source_store.get(order['id'])
    if fresh['revision']!=order['revision'] or _source_digest(fresh)!=_source_digest(order):
        raise MadarReadError('Taraz order changed before Madar write')
    response=_write_pinned_state(host,port,pin,token,candidate,revision)
    returned,after_who,after_revision=_validate_host_result(login,response)
    match=[t for t in returned['tasks'] if t.get('id')==task['id']]
    if len(match)!=1 or match[0].get('tarazOrderSourceSha256')!=evidence['sourceDigest']:
        raise MadarReadError('Madar task CAS acknowledgement failed verification')
    return {'status':'SYNCHRONIZED','taskId':task['id'],
            'sourceRevision':after_revision,'wroteMadarState':True,
            'financialEventCreated':False}
