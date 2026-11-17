"""Explicit recovery of source-bound unfinished metadata reviews, no accounting."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

import taraz_integration as integration


class ManualRecovery(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='mtr-taraz-manual-recovery-qa-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / 'bridge'
        (self.root / 'pending').mkdir(parents=True)
        self.request_id = uuid.uuid4().hex
        self.pending = self.root / 'pending' / (self.request_id + '.json')
        self.reviewed = self.root / 'reviewed'
        self.payload = {'schema': 1, 'source': 'madar', 'id': self.request_id,
                        'taskId': 'task-synthetic', 'projectId': 'project-synthetic',
                        'title': 'Synthetic metadata only',
                        'createdUtc': '2026-11-10T12:00:00+00:00'}
        self.pending.write_text(json.dumps(self.payload), encoding='utf-8')

    def interrupt_before_receipt(self, decision='reviewed'):
        original = integration._atomic_json
        def fault(path, value):
            if path.name.endswith('.review.json'):
                raise OSError('synthetic after-move interruption')
            return original(path, value)
        with patch.object(integration, '_atomic_json', side_effect=fault):
            with self.assertRaisesRegex(OSError, 'interruption'):
                integration.review_request(self.root, self.request_id, decision)

    def test_manual_recovery_from_after_move_before_receipt(self):
        self.interrupt_before_receipt()
        result = integration.list_recoverable_reviews(self.root)
        self.assertEqual(result['recoveryInvalidCount'], 0)
        self.assertEqual(result['recovery'], [{
            'id': self.request_id, 'taskId': 'task-synthetic',
            'title': 'Synthetic metadata only', 'state': 'reviewed',
            'financialEventCreated': False}])
        outcome = integration.recover_review(self.root, self.request_id)
        self.assertEqual(outcome, {'id': self.request_id, 'state': 'reviewed',
                                   'financialEventCreated': False})
        self.assertEqual(integration.list_recoverable_reviews(self.root)['recovery'], [])
        self.assertTrue((self.reviewed / (self.request_id + '.review.json')).is_file())

    def test_persisted_pre_move_intent_is_not_offered_as_fresh_pending(self):
        real_rename = os.rename
        def interrupt(source, destination):
            if source == self.pending:
                raise OSError('synthetic pre-move crash')
            return real_rename(source, destination)
        with patch.object(integration.os, 'rename', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'pre-move crash'):
                integration.review_request(self.root, self.request_id, 'rejected')
        self.assertTrue(self.pending.is_file())
        self.assertEqual(integration.list_requests(self.root)['requests'], [])
        recovery = integration.list_recoverable_reviews(self.root)
        self.assertEqual([item['state'] for item in recovery['recovery']], ['rejected'])
        self.assertEqual(integration.recover_review(self.root, self.request_id)['state'], 'rejected')

    def test_complete_receipt_still_checks_underlying_source_integrity(self):
        integration.review_request(self.root, self.request_id, 'reviewed')
        dest = self.reviewed / (self.request_id + '.json')
        dest.write_bytes(dest.read_bytes() + b' ')
        result = integration.list_recoverable_reviews(self.root)
        self.assertEqual(result['recovery'], [])
        self.assertEqual(result['recoveryInvalidCount'], 1)

    def test_complete_receipt_with_replayed_pending_is_invalid_not_fresh(self):
        integration.review_request(self.root, self.request_id, 'reviewed')
        dest = self.reviewed / (self.request_id + '.json')
        self.pending.write_bytes(dest.read_bytes())
        self.assertEqual(integration.list_requests(self.root)['requests'], [])
        result = integration.list_recoverable_reviews(self.root)
        self.assertEqual(result['recovery'], [])
        self.assertEqual(result['recoveryInvalidCount'], 1)

    def test_manual_recovery_does_not_reverse_rejection(self):
        self.interrupt_before_receipt('rejected')
        self.assertEqual(integration.list_recoverable_reviews(self.root)['recovery'][0]['state'], 'rejected')
        self.assertEqual(integration.recover_review(self.root, self.request_id)['state'], 'rejected')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            integration.review_request(self.root, self.request_id, 'reviewed')

    def test_missing_intent_never_recovers_legacy_review(self):
        integration.review_request(self.root, self.request_id, 'reviewed')
        (self.reviewed / (self.request_id + '.intent.json')).unlink()
        self.assertEqual(integration.list_recoverable_reviews(self.root)['recovery'], [])
        with self.assertRaises(FileNotFoundError):
            integration.recover_review(self.root, self.request_id)

    def test_changed_source_becomes_invalid_never_a_new_review(self):
        self.interrupt_before_receipt()
        target = self.reviewed / (self.request_id + '.json')
        target.write_bytes(target.read_bytes() + b' ')
        result = integration.list_recoverable_reviews(self.root)
        self.assertEqual(result['recovery'], [])
        self.assertEqual(result['recoveryInvalidCount'], 1)
        with self.assertRaisesRegex(ValueError, 'source changed'):
            integration.recover_review(self.root, self.request_id)

    def test_duplicate_intent_json_is_invalid(self):
        self.interrupt_before_receipt()
        intent = self.reviewed / (self.request_id + '.intent.json')
        body = intent.read_text(encoding='utf-8')
        intent.write_text(body.rstrip()[:-1] + ',"state":"reviewed"}', encoding='utf-8')
        result = integration.list_recoverable_reviews(self.root)
        self.assertEqual(result['recovery'], [])
        self.assertEqual(result['recoveryInvalidCount'], 1)
        with self.assertRaises(ValueError):
            integration.recover_review(self.root, self.request_id)

    def test_missing_pending_and_reviewed_payload_blocks_recovery(self):
        self.interrupt_before_receipt()
        (self.reviewed / (self.request_id + '.json')).unlink()
        self.assertEqual(integration.list_recoverable_reviews(self.root)['recovery'], [])
        with self.assertRaises(FileNotFoundError):
            integration.recover_review(self.root, self.request_id)

    def test_forged_intent_must_not_supply_financial_authority(self):
        self.interrupt_before_receipt()
        intent = self.reviewed / (self.request_id + '.intent.json')
        body = json.loads(intent.read_text(encoding='utf-8'))
        body['financialEventCreated'] = True
        intent.write_text(json.dumps(body), encoding='utf-8')
        self.assertEqual(integration.list_recoverable_reviews(self.root)['recovery'], [])
        with self.assertRaises(ValueError):
            integration.recover_review(self.root, self.request_id)


if __name__ == '__main__':
    unittest.main()
