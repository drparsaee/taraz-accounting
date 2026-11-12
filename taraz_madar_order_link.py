"""Verified, read-only Madar project affiliation for a Taraz order.

The Madar host remains authoritative for its projects. No remote project/task
write, credential persistence, bank transfer or accounting journal is possible.
Every association requires a fresh caller-authorized pinned HTTPS project read.
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


class MadarOrderLinkError(ValueError):
    pass


_HEX = re.compile(r"^[0-9a-f]{32}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")


def _canonical(data):
    return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":"))


class MadarOrderLinkStore:
    """Independent additive sidecar, version 1, never modifies order state."""
    def __init__(self, company_directory):
        self.root=Path(company_directory)
        _path_ok(self.root)
        self.path=self.root/"taraz-madar-order-links.sqlite3"

    def _open(self,write):
        _path_ok(self.root)
        if self.path.is_symlink():
            raise MadarOrderLinkError("Linked Madar association DB refused")
        if not write and not self.path.exists():
            return None
        db=sqlite3.connect(self.path,isolation_level=None,timeout=10)
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        if write:
            db.execute("PRAGMA journal_mode=WAL")
            version=db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0,1):
                db.close()
                raise MadarOrderLinkError("Unsupported Madar link schema")
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("""CREATE TABLE IF NOT EXISTS links(
                    order_id TEXT PRIMARY KEY,order_revision INTEGER NOT NULL,
                    project_id TEXT NOT NULL,host_state_revision TEXT NOT NULL,
                    actor TEXT NOT NULL,host_url TEXT NOT NULL,
                    tls_fingerprint TEXT NOT NULL,host_read_utc TEXT NOT NULL,
                    linked_utc TEXT NOT NULL,revision INTEGER NOT NULL)""")
                db.execute("""CREATE TABLE IF NOT EXISTS commands(
                    key TEXT PRIMARY KEY,request_digest TEXT NOT NULL,
                    response TEXT NOT NULL)""")
                db.execute("""CREATE TABLE IF NOT EXISTS audit(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,source_revision TEXT NOT NULL,
                    actor TEXT NOT NULL,verified_at TEXT NOT NULL)""")
                db.execute("""CREATE TABLE IF NOT EXISTS sync_attempts(
                    attempt_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL, order_revision INTEGER NOT NULL,
                    project_id TEXT NOT NULL, actor TEXT NOT NULL,
                    preview_digest TEXT NOT NULL, host_revision TEXT NOT NULL,
                    status TEXT NOT NULL, remote_write_attempted INTEGER NOT NULL,
                    error_type TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL)""")
                db.execute("PRAGMA user_version=1")
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:db.execute("ROLLBACK")
                db.close()
                raise
        return db

    def begin_sync_attempt(self, *, order_id, order_revision, project_id,
                           actor, preview_digest, host_revision):
        """Durable intent BEFORE a possible Madar POST, no secrets stored."""
        if (type(order_id) is not str or not _HEX.fullmatch(order_id) or
            type(order_revision) is not int or order_revision<1 or
            type(project_id) is not str or not _PROJECT.fullmatch(project_id) or
            type(actor) is not str or not 1<=len(actor)<=80 or
            type(preview_digest) is not str or not _SHA.fullmatch(preview_digest) or
            type(host_revision) is not str or not _SHA.fullmatch(host_revision)):
            raise MadarOrderLinkError('Invalid reviewed synchronization identity')
        attempt_id=secrets.token_hex(16)
        now=datetime.now(timezone.utc).isoformat()
        db=self._open(True)
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''INSERT INTO sync_attempts(
                attempt_id,order_id,order_revision,project_id,actor,
                preview_digest,host_revision,status,remote_write_attempted,
                error_type,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                (attempt_id,order_id,order_revision,project_id,actor,
                 preview_digest,host_revision,'PREPARED',0,'',now,now))
            db.execute('COMMIT')
            return attempt_id
        except BaseException:
            if db.in_transaction: db.execute('ROLLBACK')
            raise
        finally: db.close()

    def mark_sync_transmitting(self, attempt_id):
        """Commit a durable possible-remote-write marker before network I/O."""
        if type(attempt_id) is not str or not _HEX.fullmatch(attempt_id):
            raise MadarOrderLinkError('Unrecognized sync attempt')
        db=self._open(True)
        try:
            db.execute('BEGIN IMMEDIATE')
            cur=db.execute('''UPDATE sync_attempts SET
                status='TRANSMITTING',remote_write_attempted=1,updated_at=?
                WHERE attempt_id=? AND status='PREPARED' ''',
                (datetime.now(timezone.utc).isoformat(),attempt_id))
            if cur.rowcount!=1:
                raise MadarOrderLinkError('Sync attempt cannot transmit twice')
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction: db.execute('ROLLBACK')
            raise
        finally: db.close()

    def finish_sync_attempt(self, attempt_id, *, status, error_type=''):
        """Exactly one terminal state, except manual authenticated reconciliation."""
        allowed={'SYNCHRONIZED','ALREADY_SYNCED','REJECTED',
                 'OUTCOME_UNKNOWN','RECOVERED_CONFIRMED','REVIEW_REQUIRED'}
        if (type(attempt_id) is not str or not _HEX.fullmatch(attempt_id) or
            status not in allowed or type(error_type) is not str or
            len(error_type)>80 or
            any(not (x.isalnum() or x=='_') for x in error_type)):
            raise MadarOrderLinkError('Invalid sync outcome')
        db=self._open(True)
        try:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT status,remote_write_attempted FROM sync_attempts '
                           'WHERE attempt_id=?',(attempt_id,)).fetchone()
            if row is None:
                raise MadarOrderLinkError('Sync attempt identity absent')
            before=row['status']
            allowed_transitions={
                'PREPARED':{'REJECTED','ALREADY_SYNCED'},
                'TRANSMITTING':{'SYNCHRONIZED','OUTCOME_UNKNOWN'},
                'OUTCOME_UNKNOWN':{'RECOVERED_CONFIRMED','REVIEW_REQUIRED'},
            }
            if status not in allowed_transitions.get(before,set()):
                raise MadarOrderLinkError('Sync outcome transition refused')
            db.execute('UPDATE sync_attempts SET status=?,error_type=?,'
                       'updated_at=? WHERE attempt_id=?',
                       (status,error_type,datetime.now(timezone.utc).isoformat(),
                        attempt_id))
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction: db.execute('ROLLBACK')
            raise
        finally: db.close()

    def sync_history(self, order_id, limit=30):
        if (type(order_id) is not str or not _HEX.fullmatch(order_id) or
            type(limit) is not int or not 1<=limit<=50):
            raise MadarOrderLinkError('Invalid sync history query')
        db=self._open(False)
        if db is None:
            return {'entries':[],'readOnly':True,'financialEventCreated':False}
        try:
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                          "AND name='sync_attempts'").fetchone() is None:
                # Pre-upgrade database: a read cannot create/migrate tables.
                return {'entries':[],'readOnly':True,'financialEventCreated':False}
            rows=db.execute('''SELECT attempt_id,order_id,order_revision,
                project_id,actor,status,remote_write_attempted,error_type,
                created_at,updated_at FROM sync_attempts WHERE order_id=?
                ORDER BY created_at DESC,attempt_id DESC LIMIT ?''',
                (order_id,limit)).fetchall()
            return {'entries':[{
                **dict(row),
                'remote_write_attempted':bool(row['remote_write_attempted'])
            } for row in rows],'readOnly':True,'financialEventCreated':False}
        finally: db.close()

    def reconcile_uncertain(self, *, order_id, order_revision, project_id,
                            status):
        """Reconcile ONLY latest uncertain intent after a fresh verified host read."""
        if status not in ('RECOVERED_CONFIRMED','REVIEW_REQUIRED'):
            raise MadarOrderLinkError('Explicit read-only recovery outcome required')
        history=self.sync_history(order_id,limit=50)['entries']
        row=next((item for item in history if item['status'] in (
                  'OUTCOME_UNKNOWN','TRANSMITTING') and
                  item['order_revision']==order_revision and
                  item['project_id']==project_id),None)
        if row:
            if row['status']=='TRANSMITTING':
                # A process crashed after durable pre-POST intent was saved.
                # No proof of remote non-write exists; promote to UNKNOWN first.
                self.finish_sync_attempt(row['attempt_id'],status='OUTCOME_UNKNOWN')
            self.finish_sync_attempt(row['attempt_id'],status=status)
        return row is not None

    def read(self, order_id):
        if not isinstance(order_id,str) or not _HEX.fullmatch(order_id):
            raise MadarOrderLinkError("Invalid Taraz order reference")
        order=TarazOrderStore(self.root).get(order_id)
        db=self._open(False)
        if db is None:
            return {"link":None,"currentOrderMatches":False,
                    "hostMembershipRechecked":False,"readOnly":True}
        try:
            record=db.execute("SELECT * FROM links WHERE order_id=?",
                              (order_id,)).fetchone()
            if record is None:
                return {"link":None,"currentOrderMatches":False,
                        "hostMembershipRechecked":False,"readOnly":True}
            link=dict(record)
            matches=(link["order_revision"]==order["revision"] and
                     link["project_id"]==order["projectReference"])
            return {"link":link,"currentOrderMatches":matches,
                    "hostMembershipRechecked":False,"readOnly":True,
                    "financialEventCreated":False}
        finally:db.close()

    def bind(self, *, order_id, expected_order_revision, project_id,
             page, pin, expected_link_revision, idempotency_key):
        """Bind only server-verified (not JS-asserted) authenticated page data."""
        if (not isinstance(order_id,str) or not _HEX.fullmatch(order_id) or
            type(expected_order_revision) is not int or expected_order_revision<1 or
            not isinstance(project_id,str) or not _PROJECT.fullmatch(project_id) or
            type(expected_link_revision) is not int or expected_link_revision<0 or
            not isinstance(idempotency_key,str) or
            not _HEX.fullmatch(idempotency_key)):
            raise MadarOrderLinkError("Invalid Madar link CAS/identity")
        if (not isinstance(pin,str) or
            not _SHA.fullmatch(pin.lower())):
            raise MadarOrderLinkError("Verified TLS fingerprint required")
        source=page.get("source") if type(page) is dict else None
        projects=page.get("items",{}).get("projects",[]) if type(page) is dict else None
        if (type(page) is not dict or
            page.get("scope")!="projects" or page.get("connected") is not True or
            page.get("financialEventCreated") is not False or type(source) is not dict or
            source.get("kind")!="madar-authorized-host-state-projection" or
            source.get("serverAclApplied") is not True or
            source.get("readOnly") is not True or
            not isinstance(source.get("revision"),str) or
            not _SHA.fullmatch(source["revision"]) or
            not isinstance(source.get("url"),str) or
            not source["url"].startswith("https://") or
            len(source["url"])>140 or
            not isinstance(source.get("actor"),str) or
            not 1<=len(source["actor"])<=80 or
            source.get("role") not in ("viewer","editor","admin") or
            type(projects) is not list or
            sum(1 for project in projects if type(project) is dict and
                project.get("id")==project_id)!=1):
            raise MadarOrderLinkError("Authenticated Madar project witness unavailable")
        order=TarazOrderStore(self.root).get(order_id)
        if order["revision"]!=expected_order_revision or (
                order["projectReference"]!=project_id):
            raise OrderConflict("Taraz order/project changed since selection")
        data={
            "orderId":order_id,"orderRevision":expected_order_revision,
            "projectId":project_id,"hostStateRevision":source["revision"],
            "hostActor":source["actor"],"hostRole":source["role"],
            "hostUrl":source["url"],"tlsFingerprint":pin.lower(),
            "hostReadUtc":source.get("readUtc",""),
        }
        # readUtc is a fresh observation timestamp, not part of the host state
        # identity. Same idempotency key + identical verified snapshot is safe
        # to replay even when a retry performs a fresh HTTPS read.
        stable={key:value for key,value in data.items() if key!="hostReadUtc"}
        digest=hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()
        db=self._open(True)
        try:
            db.execute("BEGIN IMMEDIATE")
            earlier=db.execute("SELECT * FROM commands WHERE key=?",
                               (idempotency_key,)).fetchone()
            if earlier:
                if earlier["request_digest"]!=digest:
                    raise MadarOrderLinkError("Idempotency key reused for different witness")
                db.execute("COMMIT")
                return json.loads(earlier["response"])
            previous=db.execute("SELECT * FROM links WHERE order_id=?",
                                (order_id,)).fetchone()
            current_rev=previous["revision"] if previous else 0
            if current_rev!=expected_link_revision:
                raise OrderConflict("Madar link revision stale")
            if previous and previous["project_id"]!=project_id:
                raise MadarOrderLinkError("Cannot silently reassign a verified project")
            next_rev=current_rev+1
            now=datetime.now(timezone.utc).isoformat()
            db.execute("""INSERT INTO links(
                order_id,order_revision,project_id,host_state_revision,actor,
                host_url,tls_fingerprint,host_read_utc,linked_utc,revision)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(order_id) DO UPDATE SET
                order_revision=excluded.order_revision,
                host_state_revision=excluded.host_state_revision,actor=excluded.actor,
                host_url=excluded.host_url,tls_fingerprint=excluded.tls_fingerprint,
                host_read_utc=excluded.host_read_utc,linked_utc=excluded.linked_utc,
                revision=excluded.revision""",(
                    order_id,expected_order_revision,project_id,source["revision"],
                    source["actor"],source["url"],pin.lower(),
                    source.get("readUtc",""),now,next_rev))
            db.execute("INSERT INTO audit(order_id,revision,source_revision,actor,verified_at) "
                       "VALUES(?,?,?,?,?)",
                       (order_id,next_rev,source["revision"],source["actor"],now))
            response={"status":"VERIFIED_READ_ONLY_MADAR_LINK",
                      "orderId":order_id,"projectId":project_id,
                      "linkRevision":next_rev,"orderRevision":expected_order_revision,
                      "sourceRevision":source["revision"],
                      "hostActor":source["actor"],"hostAuthenticated":True,
                      "serverAclApplied":True,
                      "madarWritePerformed":False,"financialEventCreated":False}
            db.execute("INSERT INTO commands VALUES(?,?,?)",
                       (idempotency_key,digest,_canonical(response)))
            db.execute("COMMIT")
            return response
        except BaseException:
            if db.in_transaction:db.execute("ROLLBACK")
            raise
        finally:db.close()
