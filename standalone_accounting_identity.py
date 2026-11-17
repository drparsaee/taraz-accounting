"""Local, per-company password identities; never an accounting journal store.

Company mode authenticates *before* opening the ledger. Secrets are not passed
through the WebView JavaScript bridge. Offline local security is not a defence
against an OS administrator with unrestricted access to the underlying files.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
import stat

class IdentityError(PermissionError): pass
_LOCK=threading.RLock()
_USER=re.compile(r'^[A-Za-z][A-Za-z0-9_.-]{2,39}$')
_ROLES={'admin','editor','viewer'}
_ITERATIONS=600000
_TITLE_MAX=80


def _job_title(value):
    if (not isinstance(value,str) or len(value)>_TITLE_MAX or
        any(ord(c)<32 or ord(c)==127 for c in value)):
        raise IdentityError('عنوان شغلی باید متن معتبر و حداکثر ۸۰ نویسه باشد')
    return value.strip()


def validate_identity_document(data):
    if (not isinstance(data,dict) or set(data)!={'version','users'} or
        data['version']!=1 or not isinstance(data['users'],dict) or
        len(data['users'])>100):
        raise IdentityError('Invalid identity registry structure')
    for username,record in data['users'].items():
        if (not isinstance(username,str) or not _USER.fullmatch(username) or
            not isinstance(record,dict) or
            not {'role','salt','hash','iterations','enabled'}<=set(record) or
            set(record)-{'role','salt','hash','iterations','enabled','failCount','lockUntil','jobTitle'} or
            record['role'] not in _ROLES or type(record['iterations']) is not int or
            not min(100000,_ITERATIONS)<=record['iterations']<=2000000 or
            type(record['enabled']) is not bool):
            raise IdentityError('Invalid user record')
        _job_title(record.get('jobTitle',''))
        if (type(record.get('failCount',0)) is not int or
            not 0<=record.get('failCount',0)<=10000 or
            type(record.get('lockUntil',0)) not in (int,float) or
            not 0<=record.get('lockUntil',0)<=9999999999):
            raise IdentityError('Invalid login lockout record')
        for key in ('salt','hash'):
            value=record[key]
            if not isinstance(value,str) or len(value)!=64:
                raise IdentityError('Invalid credential verifier')
            try:bytes.fromhex(value)
            except ValueError as exc:raise IdentityError('Invalid credential encoding') from exc
    if data['users'] and not any(record['role']=='admin' and record['enabled']
                                  for record in data['users'].values()):
        raise IdentityError('At least one active administrator required')
    return data

def _validate_password(password):
    # New credentials must not be trivially enumerable four-digit PINs.
    # Historical 4+ character accounts may still authenticate in login() so
    # an upgrade does not strand the only administrator. Reset always applies
    # the new policy; production UI must guide legacy users to rotate secrets.
    if (not isinstance(password,str) or len(password)<10 or len(password)>256 or
            '\x00' in password):
        raise IdentityError('رمز عبور جدید باید حداقل ۱۰ نویسه داشته باشد؛ PIN چهاررقمی مجاز نیست')

class LocalCompanyIdentity:
    def __init__(self,root):
        self.root=Path(root)
        if not self.root.is_absolute() or not self.root.is_dir() or self.root.is_symlink():
            raise IdentityError('Existing absolute non-linked company folder required')
        for component in (self.root,*self.root.parents):
            if component.is_symlink() or (getattr(component.lstat(),'st_file_attributes',0) &
                    getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)):
                raise IdentityError('Reparse points are forbidden in identity paths')
        self.path=self.root/'local-users.json'
        self._attempts={}
        self._sessions={}

    def _read(self):
        if self.path.is_symlink():raise IdentityError('Linked identity file denied')
        if not self.path.exists():return {'version':1,'users':{}}
        if self.path.stat().st_size>1024*1024:raise IdentityError('Invalid user registry size')
        try:data=json.loads(self.path.read_text(encoding='utf-8'))
        except Exception as exc:raise IdentityError('Corrupt identity registry') from exc
        return validate_identity_document(data)

    def _save(self,data):
        validate_identity_document(data)
        fd,tmp=tempfile.mkstemp(prefix='.madar-identity-',dir=self.root)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump(data,stream,ensure_ascii=False)
                stream.flush();os.fsync(stream.fileno())
            try:os.chmod(tmp,0o600)
            except OSError:pass
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)

    def initialized(self):
        with _LOCK:return bool(self._read()['users'])

    def add_user(self,username,password,role='viewer',*,administrator=None,job_title=''):
        if not isinstance(username,str) or not _USER.fullmatch(username) or role not in _ROLES:
            raise IdentityError('Invalid username or role')
        _validate_password(password)
        title=_job_title(job_title)
        with _LOCK:
            data=self._read()
            if data['users']:
                self.require_session(administrator,'admin')
            elif role!='admin':
                raise IdentityError('First user must be administrator')
            if username in data['users']:raise IdentityError('Duplicate username')
            salt=secrets.token_bytes(32)
            digest=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,_ITERATIONS)
            data['users'][username]={'role':role,'jobTitle':title,'salt':salt.hex(),
                                     'hash':digest.hex(),'iterations':_ITERATIONS,'enabled':True}
            self._save(data)

    def login(self,username,password):
        # Login cannot accept credentials that account creation cannot store.
        # Reject before PBKDF2 or mutating persistent lockout counters.
        if (not isinstance(username,str) or not _USER.fullmatch(username) or
                not isinstance(password,str) or not 4<=len(password)<=256 or
                '\x00' in password):
            raise IdentityError('Authentication failed')
        with _LOCK:
            now=time.monotonic()
            fail_count,locked_until=self._attempts.get(username,(0,0))
            if now<locked_until:raise IdentityError('Login temporarily locked')
            data=self._read()
            record=data['users'].get(username)
            if record and time.time()<record.get('lockUntil',0):
                raise IdentityError('Login temporarily locked')
            if record and record.get('enabled') is True:
                try:
                    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),
                        bytes.fromhex(record['salt']),record['iterations'])
                    valid=hmac.compare_digest(digest,bytes.fromhex(record['hash']))
                except (ValueError,TypeError,KeyError):valid=False
            else:
                hashlib.pbkdf2_hmac('sha256',password.encode(),b'\0'*32,_ITERATIONS)
                valid=False
            if not valid:
                fails=fail_count+1
                self._attempts[username]=(fails,now+min(300,2**min(fails,8)))
                if record:
                    failure_count=min(10000,record.get('failCount',0)+1)
                    record['failCount']=failure_count
                    record['lockUntil']=time.time()+min(300,2**min(failure_count,8))
                    self._save(data)
                raise IdentityError('Authentication failed')
            self._attempts.pop(username,None)
            if record.get('failCount',0) or record.get('lockUntil',0):
                record['failCount']=0;record['lockUntil']=0
                self._save(data)
            token=secrets.token_urlsafe(48)
            self._sessions[token]=(username,now+3600)
            return token

    def require_session(self,token,required='viewer'):
        with _LOCK:
            record=self._sessions.get(token) if isinstance(token,str) else None
            if not record or time.monotonic()>record[1]:raise IdentityError('Session expired or missing')
            user=self._read()['users'].get(record[0])
            if not user or user.get('enabled') is not True:raise IdentityError('Account inactive')
            permissions={'viewer':{'viewer'},'editor':{'viewer','editor'},
                         'admin':{'viewer','editor','admin'}}
            if required not in permissions[user['role']]:raise IdentityError('Permission denied')
            return {'username':record[0],'role':user['role'],
                    'jobTitle':user.get('jobTitle','')}

    def logout(self,token):
        with _LOCK:self._sessions.pop(token,None)

    def accounting_accounts(self):
        with _LOCK:
            return {name:{'username':name,'role':value['role'],
                          'financeView':True,'financeEdit':value['role'] in ('admin','editor')}
                    for name,value in self._read()['users'].items() if value.get('enabled') is True}

    def list_users(self,administrator):
        with _LOCK:
            self.require_session(administrator,'admin')
            return sorted(({'username':name,'role':record['role'],
                            'jobTitle':record.get('jobTitle',''),
                            'enabled':record.get('enabled') is True}
                           for name,record in self._read()['users'].items()),
                          key=lambda entry: entry['username'])

    def disable_user(self,username,*,administrator):
        with _LOCK:
            operator=self.require_session(administrator,'admin')['username']
            if username==operator:
                raise IdentityError('Cannot disable the current administrator')
            data=self._read()
            user=data['users'].get(username)
            if not user:raise IdentityError('Unknown user')
            if user['role']=='admin' and user['enabled']:
                if sum(r['role']=='admin' and r.get('enabled') is True
                       for r in data['users'].values())<2:
                    raise IdentityError('Cannot disable the last administrator')
            user['enabled']=False
            self._save(data)

    def change_role(self,username,role,*,administrator):
        if role not in _ROLES:raise IdentityError('Invalid role')
        with _LOCK:
            operator=self.require_session(administrator,'admin')['username']
            data=self._read()
            user=data['users'].get(username)
            if user is None:raise IdentityError('Unknown user')
            if username==operator and role!='admin':
                raise IdentityError('Cannot downgrade the current administrator')
            if user['role']=='admin' and role!='admin' and user['enabled']:
                if sum(r['role']=='admin' and r.get('enabled') is True
                       for r in data['users'].values())<2:
                    raise IdentityError('Cannot downgrade the last administrator')
            user['role']=role
            self._save(data)

    def change_job_title(self,username,job_title,*,administrator):
        title=_job_title(job_title)
        with _LOCK:
            self.require_session(administrator,'admin')
            data=self._read()
            user=data['users'].get(username)
            if user is None:raise IdentityError('Unknown user')
            user['jobTitle']=title
            self._save(data)

    def reset_password(self,username,new_password,*,administrator):
        _validate_password(new_password)
        with _LOCK:
            self.require_session(administrator,'admin')
            data=self._read()
            user=data['users'].get(username)
            if user is None:raise IdentityError('Unknown user')
            salt=secrets.token_bytes(32)
            user['salt']=salt.hex()
            user['hash']=hashlib.pbkdf2_hmac('sha256',new_password.encode(),
                                            salt,_ITERATIONS).hex()
            user['iterations']=_ITERATIONS
            user['failCount']=0
            user['lockUntil']=0
            self._save(data)
            for token,session in tuple(self._sessions.items()):
                if session[0]==username:self._sessions.pop(token,None)
