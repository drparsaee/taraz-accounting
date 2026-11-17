"""Pure bytecode verification of the QA-only Taraz durable review build gate."""
import unittest

from scripts.qa_mtr_taraz_build_20261110 import (
    QABuildBlocked, _check_packed_durable_review, _check_packed_html_bridge,
)
from standalone_accounting_desktop import JS_BRIDGE


class PackedTarazSourceGate(unittest.TestCase):
    def test_packaged_html_proxy_must_forward_actual_recovery_method(self):
        code = compile('JS_BRIDGE = ' + repr(JS_BRIDGE), '<synthetic-html>', 'exec')
        proof = _check_packed_html_bridge(code)
        self.assertTrue(proof['packedHtmlBridgeForwarderPresent'])
        self.assertTrue(all(proof['packedHtmlBridgeMethods'].values()))

    def test_old_bridge_allowlist_cannot_pass_native_recovery_bundle_gate(self):
        legacy = JS_BRIDGE.replace("'tarazIntegrationRecover',", '')
        code = compile('JS_BRIDGE = ' + repr(legacy), '<legacy-html>', 'exec')
        with self.assertRaisesRegex(QABuildBlocked, 'omits native methods'):
            _check_packed_html_bridge(code)

    def test_requires_durable_intent_and_source_bound_receipt(self):
        synthetic = compile('''
def _read_record(): pass
def _request_lock(): pass
def _atomic_json(): pass
def _validate_intent(): pass
def recover_review(): pass
def list_recoverable_reviews(): pass
def review_request():
    return (".intent.json", "sourceDigest", "financialEventCreated")
''', '<synthetic>', 'exec')
        proof = _check_packed_durable_review(synthetic)
        self.assertTrue(proof["sourceBoundDurableIntentCode"])

    def test_installed_old_style_review_is_rejected(self):
        legacy = compile('''
def _read_record(): pass
def review_request():
    return (".review.json", "financialEventCreated")
''', '<synthetic-legacy>', 'exec')
        with self.assertRaisesRegex(QABuildBlocked, 'durable intent'):
            _check_packed_durable_review(legacy)

    def test_method_names_alone_do_not_prove_durable_code(self):
        no_intent = compile('''
def _read_record(): pass
def _request_lock(): pass
def _atomic_json(): pass
def _validate_intent(): pass
def recover_review(): pass
def list_recoverable_reviews(): pass
def review_request():
    return "financialEventCreated"
''', '<synthetic-spoof>', 'exec')
        with self.assertRaisesRegex(QABuildBlocked, 'intent/restart'):
            _check_packed_durable_review(no_intent)


if __name__ == '__main__':
    unittest.main()
