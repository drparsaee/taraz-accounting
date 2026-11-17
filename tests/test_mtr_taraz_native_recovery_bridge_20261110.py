"""Native Taraz API manual recovery gate, exclusively disposable metadata.

Directly calls the REAL TarazAPI method code against a deliberately minimal
synthetic authenticated test actor. Never launches the desktop, opens a book,
imports private migrated archive data or bypasses its startup source guard.
"""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from taraz_desktop import TarazAPI
import taraz_integration


class SyntheticActor:
    def __init__(self):
        self._lock = threading.RLock()
        self.allowed = True
        self.edit = True
        self.permissions = []

    def _require_authenticated(self, role=None):
        self.permissions.append(role)
        if not self.allowed or (role == 'editor' and not self.edit):
            raise PermissionError('synthetic role revoked')


class RealNativeMethodManualRecovery(unittest.TestCase):
    def setUp(self):
        disposable = tempfile.TemporaryDirectory(prefix='mtr-taraz-native-qa-')
        self.addCleanup(disposable.cleanup)
        self.root = Path(disposable.name) / 'Madar-Taraz-Bridge'
        (self.root / 'pending').mkdir(parents=True)
        self.key = uuid.uuid4().hex
        self.pending = self.root / 'pending' / (self.key + '.json')
        self.pending.write_text(json.dumps({
            'schema': 1, 'source': 'madar', 'id': self.key,
            'taskId': 'synthetic-task', 'projectId': 'synthetic-project',
            'title': 'Disposable synthetic card',
            'createdUtc': '2026-11-10T12:00:00+00:00',
        }), encoding='utf8')
        self.actor = SyntheticActor()
        mock = patch('taraz_desktop.bridge_root', return_value=self.root)
        mock.start()
        self.addCleanup(mock.stop)

    def interrupt_after_intent_before_move(self, decision='reviewed'):
        original_rename = os.rename
        def crash(source, target):
            if str(source) == str(self.pending):
                raise OSError('synthetic crash after intent before move')
            return original_rename(source, target)
        with patch.object(taraz_integration.os, 'rename', side_effect=crash):
            with self.assertRaisesRegex(OSError, 'synthetic crash'):
                taraz_integration.review_request(self.root, self.key, decision)

    def test_list_distinguishes_pending_and_durable_recovery(self):
        before = TarazAPI.tarazIntegrationList(self.actor)
        self.assertEqual([p['id'] for p in before['requests']], [self.key])
        self.assertEqual(before['recovery'], [])
        self.interrupt_after_intent_before_move()
        after = TarazAPI.tarazIntegrationList(self.actor)
        self.assertEqual(after['requests'], [], 'pending duplicate choice is prohibited')
        self.assertEqual(len(after['recovery']), 1)
        self.assertEqual(after['recovery'][0]['state'], 'reviewed')
        self.assertEqual(after['recoveryInvalidCount'], 0)

    def test_manual_action_completes_persisted_decision_and_cannot_post(self):
        self.interrupt_after_intent_before_move('rejected')
        with self.assertRaises(PermissionError):
            TarazAPI.tarazIntegrationRecover(self.actor, self.key, False)
        result = TarazAPI.tarazIntegrationRecover(self.actor, self.key, True)
        self.assertEqual(result, {
            'id': self.key, 'state': 'rejected', 'financialEventCreated': False})
        self.assertFalse(self.pending.exists())
        self.assertTrue((self.root / 'reviewed' / (self.key + '.review.json')).is_file())
        after = TarazAPI.tarazIntegrationList(self.actor)
        self.assertEqual(after['recovery'], [])
        self.assertEqual(after['requests'], [])
        self.assertIn('editor', self.actor.permissions)

    def test_role_revocation_blocks_recovery(self):
        self.interrupt_after_intent_before_move()
        self.actor.edit = False
        with self.assertRaises(PermissionError):
            TarazAPI.tarazIntegrationRecover(self.actor, self.key, True)
        self.assertTrue(self.pending.exists())
        self.assertTrue((self.root / 'reviewed' / (self.key + '.intent.json')).is_file())

    def test_unauthenticated_actor_cannot_list(self):
        self.actor.allowed = False
        with self.assertRaises(PermissionError):
            TarazAPI.tarazIntegrationList(self.actor)

    def test_corrupt_intent_is_hidden_from_normal_pending_inbox(self):
        self.interrupt_after_intent_before_move()
        intent = self.root / 'reviewed' / (self.key + '.intent.json')
        intent.write_text('{"corrupt":true}', encoding='utf8')
        result = TarazAPI.tarazIntegrationList(self.actor)
        self.assertEqual(result['requests'], [])
        self.assertEqual(result['recovery'], [])
        self.assertEqual(result['recoveryInvalidCount'], 1)
        with self.assertRaises(ValueError):
            TarazAPI.tarazIntegrationRecover(self.actor, self.key, True)

    def test_missing_intent_recovery_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            TarazAPI.tarazIntegrationRecover(self.actor, self.key, True)
        self.assertTrue(self.pending.is_file())


if __name__ == '__main__':
    unittest.main()
