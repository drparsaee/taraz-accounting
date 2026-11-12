"""Offline-first durable NONFINANCIAL event outbox for a single company.

No network sender is provided here: no RADAR endpoint or shared identity
provider has been verified, and official finance authority is still OPEN.
Only transport-authenticated receipts from future product adapters may resolve
an uncertain write. Never auto-resend an uncertain event.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock

from taraz_ecosystem_protocol import (
    ProtocolError, TrustedScope, canonical, digest, validate_envelope,
)
from taraz_order_store import _path_ok


class SyncConflict(ProtocolError):
    pass


@dataclass(frozen=True)
class VerifiedReceipt:
    """Must be created by a separate authenticated + pinned host adapter.

    This type does not authenticate a remote host by itself. Do not expose its
    constructor as a browser/RPC endpoint, and do not count it as proof of
    network or other-product interoperability in tests.
    """
    company_id: str
    target_system: str
    event_id: str
    source_digest: str
    result: str
    target_revision: str


def _utc():
    return datetime.now(timezone.utc).isoformat()


class EcosystemOutbox:
    SCHEMA_VERSION = 1
    FILE = 'taraz-ecosystem-outbox.sqlite3'
    _init_lock = RLock()

    def __init__(self, company_directory):
        self.root = Path(company_directory)
        _path_ok(self.root)
        self.path = self.root / self.FILE

    def _open(self, write):
        # Serialize first-use WAL initialization between local desktop calls.
        # Cross-process operations are still serialized by SQLite IMMEDIATE.
        with self._init_lock:
            return self._open_serial(write)

    def _open_serial(self, write):
        _path_ok(self.root)
        if self.path.is_symlink() or (self.path.exists() and
                getattr(self.path.lstat(), 'st_file_attributes', 0) & 0x400):
            raise PermissionError('Linked ecosystem synchronization database')
        if not write and not self.path.is_file():
            return None
        if self.path.exists() and not self.path.is_file():
            raise PermissionError('Invalid synchronization database path')
        if write:
            db=sqlite3.connect(self.path, isolation_level=None,timeout=10)
        else:
            db=sqlite3.connect(self.path.as_uri()+'?mode=ro',
                               uri=True,isolation_level=None,timeout=10)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        version=db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, self.SCHEMA_VERSION):
            db.close()
            raise SyncConflict('Unsupported future synchronization schema')
        if not write:
            if version!=self.SCHEMA_VERSION:
                db.close()
                raise SyncConflict('Uninitialized synchronization store')
            return db
        if version == 0:
            try:
                db.execute('PRAGMA journal_mode=WAL')
            except sqlite3.OperationalError as exc:
                # Another process may be initializing the database. SQLite's
                # own transaction lock still preserves correctness in DELETE
                # journal mode, and a live lock must never strand this handle.
                if 'locked' not in str(exc).lower():
                    db.close()
                    raise
        db.execute('PRAGMA synchronous=FULL')
        try:
            db.execute('BEGIN IMMEDIATE')
        except BaseException:
            db.close()
            raise
        try:
            db.execute('''CREATE TABLE IF NOT EXISTS event_outbox(
                event_id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
                idempotency_key TEXT UNIQUE NOT NULL,
                envelope_hash TEXT NOT NULL, source_system TEXT NOT NULL,
                target_system TEXT NOT NULL, entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL, source_revision INTEGER NOT NULL,
                source_digest TEXT NOT NULL, envelope_json TEXT NOT NULL,
                state TEXT NOT NULL, remote_may_have_changed INTEGER NOT NULL,
                created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
                UNIQUE(company_id,source_system,entity_type,entity_id,
                       source_revision))''')
            db.execute('''CREATE TABLE IF NOT EXISTS sync_receipts(
                event_id TEXT PRIMARY KEY, result TEXT NOT NULL,
                target_system TEXT NOT NULL, target_revision TEXT NOT NULL,
                received_utc TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES event_outbox(event_id))''')
            db.execute('''CREATE INDEX IF NOT EXISTS idx_outbox_company_state
                ON event_outbox(company_id,state,created_utc)''')
            db.execute('PRAGMA user_version=1')
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            db.close()
            raise
        return db

    def enqueue(self, message, *, scope, source_witness):
        """Durably stage a verified nonfinancial change, without posting.

        source_witness() must independently read the authoritative entity and
        return (revision,sha256). It is invoked again just before COMMIT.
        """
        if not callable(source_witness):
            raise PermissionError('Trusted source store witness is required')
        envelope=validate_envelope(message,scope=scope)
        expected=(envelope['sourceRevision'],envelope['sourceDigest'])
        if source_witness()!=expected:
            raise SyncConflict('Source revision/digest is not authoritative')
        key=envelope['idempotencyKey']
        fingerprint=digest(envelope)
        db=self._open(True)
        try:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT * FROM event_outbox '
                                'WHERE idempotency_key=?',(key,)).fetchone()
            if existing is not None:
                if existing['envelope_hash']!=fingerprint:
                    raise SyncConflict('Idempotency key reused for another event')
                db.execute('COMMIT')
                return self._public(existing)
            same=db.execute('SELECT * FROM event_outbox WHERE event_id=?',
                            (envelope['eventId'],)).fetchone()
            if same:
                raise SyncConflict('Event ID reused with different idempotency key')
            latest=db.execute('''SELECT source_revision AS revision,state
                FROM event_outbox WHERE company_id=? AND source_system=?
                AND entity_type=? AND entity_id=?
                ORDER BY source_revision DESC LIMIT 1''',
                (envelope['companyId'],envelope['sourceSystem'],
                 envelope['entityType'],envelope['entityId'])).fetchone()
            if latest is not None and latest['state'] != 'ACKNOWLEDGED':
                raise SyncConflict('Prior entity event is not remotely acknowledged')
            if latest is not None and (
                envelope['sourceRevision']!=latest['revision']+1):
                raise SyncConflict('Stale/gapped entity event ordering requires review')
            stamp=_utc()
            db.execute('''INSERT INTO event_outbox(
                event_id,company_id,idempotency_key,envelope_hash,
                source_system,target_system,entity_type,entity_id,
                source_revision,source_digest,envelope_json,state,
                remote_may_have_changed,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (envelope['eventId'],envelope['companyId'],key,fingerprint,
                 envelope['sourceSystem'],envelope['targetSystem'],
                 envelope['entityType'],envelope['entityId'],
                 envelope['sourceRevision'],envelope['sourceDigest'],
                 canonical(envelope),'PENDING',0,stamp,stamp))
            if source_witness()!=expected:
                raise SyncConflict('Source changed before durable staging')
            db.execute('COMMIT')
            return self.get(envelope['eventId'],company_id=scope.company_id)
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()

    @staticmethod
    def _public(row):
        data=dict(row)
        # Do not expose stored payload or replay keys in ordinary status views.
        return {field:data[field] for field in (
            'event_id','company_id','source_system','target_system',
            'entity_type','entity_id','source_revision','state',
            'created_utc','updated_utc')} | {
            'remoteMayHaveChanged': bool(data['remote_may_have_changed']),
            'financialEventCreated':False,
        }

    def get(self,event_id,*,company_id):
        if not isinstance(event_id,str) or len(event_id)!=32:
            raise ProtocolError('Invalid event reference')
        if not isinstance(company_id,str) or not company_id:
            raise PermissionError('Verified company scope required')
        db=self._open(False)
        if db is None:
            return None
        try:
            record=db.execute('SELECT * FROM event_outbox WHERE event_id=? '
                              'AND company_id=?',(event_id,company_id)).fetchone()
            return self._public(record) if record else None
        finally:db.close()

    def list(self,*,company_id,limit=50):
        if not isinstance(company_id,str) or not company_id or (
            type(limit) is not int or limit<1 or limit>100):
            raise ProtocolError('Invalid company/limit')
        db=self._open(False)
        if db is None:
            return {'entries':[],'total':0,'readOnly':True,
                    'networkSenderAvailable':False,'financialEventCreated':False}
        try:
            rows=db.execute('''SELECT * FROM event_outbox WHERE company_id=?
                ORDER BY created_utc,event_id LIMIT ?''',(company_id,limit)).fetchall()
            total=db.execute('SELECT COUNT(*) FROM event_outbox WHERE company_id=?',
                             (company_id,)).fetchone()[0]
            return {'entries':[self._public(r) for r in rows],'total':total,
                    'readOnly':True,'networkSenderAvailable':False,
                    'financialEventCreated':False}
        finally:db.close()

    def mark_possibly_sent(self,event_id,*,scope,source_witness):
        """Recheck source CAS before durable send intent; never auto-retry.

        The caller must supply an independently backed source witness. This
        does not remove the need for CAS at the destination: the source can
        change immediately after this function returns.
        """
        if type(scope) is not TrustedScope or scope.role!='admin':
            raise PermissionError('Only trusted admin transport may dispatch')
        if not callable(source_witness):
            raise PermissionError('Trusted source store witness is required at dispatch')
        db=self._open(True)
        try:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('''SELECT source_revision,source_digest
                FROM event_outbox WHERE event_id=? AND company_id=?
                AND source_system=? AND state='PENDING' ''',
                (event_id,scope.company_id,scope.source_system)).fetchone()
            if current is None:
                raise SyncConflict('Only never-sent event may start transmission')
            if source_witness()!=(current['source_revision'],current['source_digest']):
                raise SyncConflict('Source changed after staging, remote send refused')
            result=db.execute('''UPDATE event_outbox SET state='OUTCOME_UNKNOWN',
                remote_may_have_changed=1,updated_utc=?
                WHERE event_id=? AND company_id=? AND source_system=?
                AND state='PENDING' ''',
                (_utc(),event_id,scope.company_id,scope.source_system))
            if result.rowcount!=1:
                raise SyncConflict('Only never-sent event may start transmission')
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()

    def reconcile_verified_receipt(self,receipt,*,scope):
        """Apply authenticated target receipt; this function never uses network.

        Caller must be a trusted, pinned transport adapter. It may return
        ACKNOWLEDGED or REVIEW_REQUIRED, never a financial posting result.
        """
        if type(scope) is not TrustedScope or scope.role!='admin':
            raise PermissionError('Host-owned receipt application required')
        if type(receipt) is not VerifiedReceipt:
            raise PermissionError('Transport-verified receipt required')
        if (receipt.company_id!=scope.company_id or
            receipt.result not in ('APPLIED','DUPLICATE','CONFLICT') or
            not isinstance(receipt.target_revision,str) or
            not 1<=len(receipt.target_revision)<=120):
            raise PermissionError('Untrusted receipt actor/scope/state')
        db=self._open(True)
        try:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM event_outbox WHERE event_id=? '
                           'AND company_id=?',(receipt.event_id,
                                               scope.company_id)).fetchone()
            if (row is None or row['source_system']!=scope.source_system or
                row['target_system']!=receipt.target_system or
                row['source_digest']!=receipt.source_digest):
                raise SyncConflict('Receipt disagrees with source identity')
            status='REVIEW_REQUIRED' if receipt.result=='CONFLICT' else 'ACKNOWLEDGED'
            old=db.execute('SELECT * FROM sync_receipts WHERE event_id=?',
                           (receipt.event_id,)).fetchone()
            if old:
                if (old['result']!=receipt.result or
                    old['target_revision']!=receipt.target_revision or
                    row['state']!=status):
                    raise SyncConflict('Conflicting repeated host receipt')
                db.execute('COMMIT')
                return self._public(row)
            if row['state']!='OUTCOME_UNKNOWN':
                raise SyncConflict('Unexpected receipt without durable send intent')
            db.execute('INSERT INTO sync_receipts VALUES(?,?,?,?,?)',
                       (receipt.event_id,receipt.result,receipt.target_system,
                        receipt.target_revision,_utc()))
            db.execute('UPDATE event_outbox SET state=?,updated_utc=? '
                       'WHERE event_id=?',(status,_utc(),receipt.event_id))
            db.execute('COMMIT')
            return self.get(receipt.event_id,company_id=scope.company_id)
        except BaseException:
            if db.in_transaction:db.execute('ROLLBACK')
            raise
        finally:db.close()
