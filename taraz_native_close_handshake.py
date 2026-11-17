"""Bounded, one-use native close/abort handshake for local Taraz React.

No JS approval is synthesized. React must answer with an exact nonce; missing,
late, ambiguous and repeated responses never authorize native close or unlock.
"""
from __future__ import annotations

from threading import Event, Lock
import secrets
import time


class TarazNativeCloseHandshake:
    def __init__(self, *, timeout_seconds=12.0, clock=time.monotonic):
        if type(timeout_seconds) not in (int, float) or not 0.2 <= timeout_seconds <= 15:
            raise ValueError('Native close timeout must be bounded')
        self.timeout = float(timeout_seconds)
        self.clock = clock
        self._lock = Lock()
        self._request = None

    def _await(self, kind, warning_code=None):
        with self._lock:
            if self._request is not None:
                return None
            request = {'requestId': secrets.token_hex(16), 'kind': kind,
                       'deadline': self.clock() + self.timeout,
                       'event': Event(), 'answer': False,
                       'warningCode': warning_code}
            self._request = request
        finished = request['event'].wait(self.timeout)
        with self._lock:
            if self._request is request:
                self._request = None
            if not finished or self.clock() > request['deadline']:
                return None
            return request['answer']

    def await_close_consent(self):
        """True=React confirmed, False=explicit refusal, None=expired/unknown."""
        return self._await('close')

    def await_abort_ack(self, *, warning_code=None):
        if warning_code not in (None, 'BACKUP_FAILED'):
            raise ValueError('Unsupported abort warning')
        return self._await('abort', warning_code) is True

    def poll(self):
        with self._lock:
            req = self._request
            if req is None or req['event'].is_set() or self.clock() >= req['deadline']:
                return {'pending': False}
            return {'pending': True, 'requestId': req['requestId'],
                    'kind': req['kind'], 'warningCode': req['warningCode']}

    def respond(self, payload):
        if (type(payload) is not dict or
                set(payload) != {'requestId', 'kind', 'confirmed'} or
                type(payload['requestId']) is not str or
                len(payload['requestId']) != 32 or
                any(c not in '0123456789abcdef' for c in payload['requestId']) or
                payload['kind'] not in ('close', 'abort') or
                type(payload['confirmed']) is not bool):
            raise ValueError('Malformed native close response')
        with self._lock:
            req = self._request
            if (req is None or req['event'].is_set() or
                    self.clock() >= req['deadline'] or
                    payload['requestId'] != req['requestId'] or
                    payload['kind'] != req['kind']):
                raise PermissionError('Unknown, expired or replayed close response')
            req['answer'] = payload['confirmed']
            req['event'].set()
        return {'accepted': True}


__all__ = ['TarazNativeCloseHandshake']
