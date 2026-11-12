"""Company-scoped, tool-using AaaS review and human-governed memory.

The review executes real read-only tools against Taraz's operational SQLite.
It is deterministic until a separately measured/approved LLM planner exists;
it does NOT claim to be an autonomous LLM or perform financial mutations.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3

from taraz_order_store import TarazOrderStore, OrderConflict, _path_ok


class AgentMemoryError(ValueError):
    pass


_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_HEX = re.compile(r"^[a-f0-9]{32}$")


def _json(data):
    return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":"))


def _source(order):
    """Bounded, inspectable facts; no raw customer ledger or passwords."""
    return {
        "orderId":order["id"],"revision":order["revision"],
        "kind":order["kind"],"currency":order["currency"],
        "quantity":order["quantity"],
        "plannedProduction":order["productionQuantity"],
        "productionReconciliation":order["productionReconciliation"]["state"],
        "estimatedCostTotal":order.get("estimatedCostTotal"),
        "approvedActualCostTotal":order.get("actualCostTotal"),
        "paymentBalance":order.get("paymentBalance"),
        "status":order["status"],
    }


def _digest(facts):
    return hashlib.sha256(_json(facts).encode('utf-8')).hexdigest()


class CompanyAgentMemory:
    """One local SQLite memory, versioned and auditable; read makes no file."""
    def __init__(self, company_directory):
        self.root=Path(company_directory)
        _path_ok(self.root)
        self.path=self.root/'taraz-agent-memory.sqlite3'

    def _db(self,write=False):
        _path_ok(self.root)
        if self.path.is_symlink():
            raise AgentMemoryError('Linked agent memory refused')
        if not write and not self.path.is_file():
            return None
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        if write:
            db.execute('PRAGMA journal_mode=WAL')
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0,1):
                db.close()
                raise AgentMemoryError('Unsupported agent memory schema')
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('''CREATE TABLE IF NOT EXISTS entries(
                    id TEXT PRIMARY KEY,order_id TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,source_digest TEXT NOT NULL,
                    body TEXT NOT NULL,normalized_digest TEXT NOT NULL,
                    status TEXT NOT NULL,created_by TEXT NOT NULL,
                    reviewed_by TEXT,created_at TEXT NOT NULL,reviewed_at TEXT,
                    UNIQUE(order_id,normalized_digest))''')
                db.execute('''CREATE TABLE IF NOT EXISTS commands(
                    idempotency_key TEXT PRIMARY KEY,digest TEXT NOT NULL,
                    response_json TEXT NOT NULL)''')
                db.execute('''CREATE TABLE IF NOT EXISTS revisions(
                    id INTEGER PRIMARY KEY CHECK(id=1),value INTEGER NOT NULL)''')
                db.execute('INSERT OR IGNORE INTO revisions(id,value) VALUES(1,0)')
                db.execute('''CREATE TABLE IF NOT EXISTS audit(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL,action TEXT NOT NULL,actor TEXT NOT NULL,
                    revision INTEGER NOT NULL,at TEXT NOT NULL)''')
                db.execute('PRAGMA user_version=1')
                db.execute('COMMIT')
            except BaseException:
                if db.in_transaction:db.execute('ROLLBACK')
                db.close()
                raise
        return db

    def list(self, order_id):
        if not isinstance(order_id,str) or not _HEX.fullmatch(order_id):
            raise AgentMemoryError('Invalid source order')
        db=self._db()
        if db is None:
            return {'revision':0,'entries':[],'source':'LOCAL_AUDITED_MEMORY',
                    'financialEventCreated':False}
        try:
            revision=db.execute('SELECT value FROM revisions WHERE id=1').fetchone()[0]
            entries=[dict(row) for row in db.execute(
                'SELECT * FROM entries WHERE order_id=? ORDER BY created_at,id',
                (order_id,))]
            return {'revision':revision,'entries':entries,
                    'source':'LOCAL_AUDITED_MEMORY','financialEventCreated':False}
        finally:db.close()

    def command(self, request, *, actor, role):
        if not isinstance(actor,str) or not _IDENT.fullmatch(actor) or role not in (
                'editor','admin'):
            raise PermissionError('Authenticated agent memory editor required')
        expected={'action','orderId','entryId','text','sourceRevision',
                  'expectedMemoryRevision','idempotencyKey','manualConfirmation'}
        if type(request) is not dict or set(request)!=expected:
            raise AgentMemoryError('Invalid memory command shape')
        action=request['action']
        if action not in ('propose','accept','reject'):
            raise AgentMemoryError('Invalid agent memory action')
        if action!='propose' and role!='admin':
            raise PermissionError('Only administrators may accept or reject memory')
        if request['manualConfirmation'] is not (action!='propose'):
            raise PermissionError('Human review confirmation required')
        order_id=request['orderId']
        if not isinstance(order_id,str) or not _HEX.fullmatch(order_id):
            raise AgentMemoryError('Invalid linked order')
        if type(request['expectedMemoryRevision']) is not int or (
                request['expectedMemoryRevision']<0):
            raise AgentMemoryError('Invalid memory CAS')
        key=request['idempotencyKey']
        if not isinstance(key,str) or not _HEX.fullmatch(key):
            raise AgentMemoryError('Invalid memory idempotency key')
        order=TarazOrderStore(self.root).get(order_id)
        facts=_source(order)
        if order['revision'] != request['sourceRevision']:
            raise OrderConflict('Source order revision changed')
        if action=='propose':
            if request['entryId'] is not None or type(request['text']) is not str or (
                    not request['text'].strip() or len(request['text'])>800 or
                    any(ord(c)<32 for c in request['text'])):
                raise AgentMemoryError('Proposed memory must be explicit short text')
        elif (not isinstance(request['entryId'],str) or
              not _HEX.fullmatch(request['entryId']) or request['text'] is not None):
            raise AgentMemoryError('Reviewed entry must be explicit')
        digest=_digest({'request':request,'actor':actor,'role':role})
        db=self._db(write=True)
        try:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT * FROM commands WHERE idempotency_key=?',
                                (key,)).fetchone()
            if existing:
                if existing['digest']!=digest:
                    raise AgentMemoryError('Idempotency key already used')
                db.execute('COMMIT')
                return json.loads(existing['response_json'])
            rev=db.execute('SELECT value FROM revisions WHERE id=1').fetchone()[0]
            if rev!=request['expectedMemoryRevision']:
                raise AgentMemoryError('Memory revision conflict')
            now=datetime.now(timezone.utc).isoformat()
            if action=='propose':
                normalized=' '.join(request['text'].strip().casefold().split())
                nd=hashlib.sha256(normalized.encode('utf-8')).hexdigest()
                if db.execute('SELECT 1 FROM entries WHERE order_id=? AND normalized_digest=?',
                              (order_id,nd)).fetchone():
                    raise AgentMemoryError('Proposed or rejected memory already exists')
                entry_id=secrets.token_hex(16)
                db.execute('''INSERT INTO entries VALUES
                    (?,?,?,?,?,?,'proposed',?,NULL,?,NULL)''',
                    (entry_id,order_id,order['revision'],_digest(facts),
                     request['text'].strip(),nd,actor,now))
            else:
                entry_id=request['entryId']
                item=db.execute('SELECT * FROM entries WHERE id=? AND order_id=?',
                                (entry_id,order_id)).fetchone()
                if not item or item['status']!='proposed':
                    raise AgentMemoryError('Only a proposed memory can be reviewed')
                if (item['source_revision']!=order['revision'] or
                    item['source_digest']!=_digest(facts)):
                    raise OrderConflict('Proposed memory source evidence is stale')
                db.execute('UPDATE entries SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?',
                           ('accepted' if action=='accept' else 'rejected',actor,now,entry_id))
            rev+=1
            db.execute('UPDATE revisions SET value=? WHERE id=1',(rev,))
            db.execute('INSERT INTO audit(entry_id,action,actor,revision,at) VALUES(?,?,?,?,?)',
                       (entry_id,action,actor,rev,now))
            output={'id':entry_id,'revision':rev,
                    'status':'proposed' if action=='propose' else
                             'accepted' if action=='accept' else 'rejected',
                    'financialEventCreated':False}
            db.execute('INSERT INTO commands VALUES(?,?,?)',(key,digest,_json(output)))
            db.execute('COMMIT')
            return output
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()


def review_order_tools(company_directory, order_id):
    """A bounded multi-tool review; all output has source IDs/revisions."""
    order=TarazOrderStore(company_directory).get(order_id)
    facts=_source(order)
    memory=CompanyAgentMemory(company_directory).list(order_id)
    recommendations=[]
    if facts['productionReconciliation'] in ('incomplete','not_recorded'):
        recommendations.append({'action':'request_measured_quantities',
            'reason':'Actual production, scrap and healthy surplus must be measured'})
    if facts['approvedActualCostTotal'] is None:
        recommendations.append({'action':'review_actual_costs',
            'reason':'All stage actual costs have not received finance approval'})
    if facts['paymentBalance'] is None:
        recommendations.append({'action':'verify_agreed_amount',
            'reason':'Order contract price is unknown; do not invent a balance'})
    elif facts['paymentBalance']>0:
        recommendations.append({'action':'review_remaining_settlement',
            'reason':'Confirmed settlement is below the agreed amount'})
    return {'source':'REAL_SQLITE_TOOLS','toolTrace':[
        {'tool':'order.get','orderId':order['id'],'revision':order['revision']},
        {'tool':'memory.list','memoryRevision':memory['revision']}],
        'facts':facts,'sourceDigest':_digest(facts),'recommendations':recommendations,
        'acceptedMemory':[entry for entry in memory['entries']
                          if entry['status']=='accepted' and
                             entry['source_revision']==order['revision'] and
                             entry['source_digest']==_digest(facts)],
        'requiresHumanApproval':True,'modelRan':False,
        'financialEventCreated':False,'toolsReadOnly':True}


def interpret_natural_order_request(company_directory, order_id, request_text):
    """Conservative, local Persian intent -> real tools -> editable proposal.

    This is explicitly a rules fallback, not a completed LLM inference. It
    never calls remote providers, changes the order or writes agent memory.
    A separate authenticated, human-reviewed memory command may later persist
    the revised proposal using source/memory CAS and audit guarantees.
    """
    if (type(request_text) is not str or not request_text.strip() or
            len(request_text)>1200 or
            any(ord(character)<32 and character not in '\t\n\r'
                for character in request_text)):
        raise AgentMemoryError('Natural language request is invalid')
    reviewed=review_order_tools(company_directory,order_id)
    facts=reviewed['facts']
    normalized=' '.join(request_text.strip().casefold().split())
    if re.search(r'پرداخت|تسویه|مانده|واریز|دریافت',normalized):
        intent='review_remaining_settlement'
        if facts['paymentBalance'] is None:
            suggestion='مبلغ یا وضعیت تسویه مشخص نیست؛ از مسئول مالی رسید معتبر درخواست شود.'
        elif facts['paymentBalance']>0:
            suggestion='مانده تسویه سفارش با رسیدهای واقعی بررسی و برای تأیید مالی پیگیری شود.'
        else:
            suggestion='تسویه ثبت‌شده با مرجع رسید و تأیید مالی بازبینی شود.'
    elif re.search(r'هزینه|رسید|پیمانکار|تأمین|تامین',normalized):
        intent='review_actual_costs'
        suggestion=('هزینه واقعی هر مرحله با رسید و تأیید مسئول مالی بررسی شود؛ '
                    'هزینه نامشخص به‌عنوان صفر ثبت نشود.')
    elif re.search(r'تولید|پرت|ضایعات|مازاد|کسری|تحویل',normalized):
        intent='request_measured_quantities'
        suggestion=('تولید واقعی، پرت و مازاد سالم از گزارش تولید بازبینی و '
                    'فقط با اندازه‌گیری مستند تأیید شود.')
    elif re.search(r'وضعیت|پیگیری|سفارش|گزارش',normalized):
        intent='read_order_status'
        suggestion=('وضعیت سفارش و گیت‌های هزینه، تولید و تسویه با داده‌های '
                    'واقعی بررسی و موارد ناقص پیگیری شود.')
    else:
        intent='unclassified'
        suggestion=''
    memory=CompanyAgentMemory(company_directory).list(order_id)
    rejected={ ' '.join(entry['body'].strip().casefold().split())
        for entry in memory['entries'] if entry['status']=='rejected'}
    previously_rejected=bool(suggestion and
                              ' '.join(suggestion.casefold().split()) in rejected)
    return {
        'source':'REAL_SQLITE_TOOLS',
        'inference':'RULE_BASED_FALLBACK',
        'modelRan':False,'externalModelCalled':False,
        'intent':intent,
        'missingInformation':[hint['action'] for hint in
                              reviewed['recommendations']],
        'editableProposal':'' if previously_rejected else suggestion,
        'previouslyRejected':previously_rejected,
        'sourceDigest':reviewed['sourceDigest'],
        'sourceRevision':facts['revision'],
        'memoryRevision':memory['revision'],
        'toolTrace':reviewed['toolTrace'],
        'acceptedMemory':reviewed['acceptedMemory'],
        'requiresHumanApproval':True,
        'autoActionPerformed':False,'financialEventCreated':False,
    }
