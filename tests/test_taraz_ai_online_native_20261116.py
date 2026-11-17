"""Native company auth + actual DPAPI + fail-closed online release gate QA.

Only disposable newly created Windows books under repository tests/output.
Network is always mocked; no actual API credential or provider transmission.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from standalone_accounting_desktop import JS_BRIDGE
from taraz_ai_online_native_boundary import (
    DIRECTORY, ONLINE_EXTERNAL_TRANSMISSION_ENABLED,
    company_online_vault, _acl_is_private,
)
import taraz_ai_online_provider as provider
from taraz_ai_online_credentials import OnlineCredentialError

ENDPOINT = "https://api.openai.com/v1/chat/completions"


@unittest.skipUnless(os.name == 'nt', 'Current Windows user and DPAPI required')
class NativeRegisteredCompanyOnlineTests(unittest.TestCase):
    def setUp(self):
        from taraz_fresh_windows_workspace import (
            stage_new_empty_root, open_fresh_company,
        )
        parent = Path(__file__).resolve().parent / "output"
        self.assertTrue(parent.is_dir())
        temp = tempfile.TemporaryDirectory(prefix='taraz-online-native-qa-', dir=parent)
        self.addCleanup(temp.cleanup)
        self.profile = Path(temp.name) / 'fresh-qa-only'
        stage_new_empty_root(self.profile)
        self.api, self.identity, self.token = open_fresh_company(self.profile)
        self.addCleanup(lambda: self.identity.logout(self.token))
        self.book = self.api.path.parent
        self.directory = self.book / DIRECTORY
        self.secret = secrets.token_urlsafe(48)  # never a provider-issued API key

    def configure(self, **changes):
        request = {
            'provider':'openai', 'endpoint': ENDPOINT, 'model':'user-chosen-model',
            'apiKey': self.secret, 'inputUsdPerMillion':'2',
            'outputUsdPerMillion':'4', 'manualConsent':True,
        }
        request.update(changes)
        return self.api.tarazAiOnlineConfigure(request)

    def test_status_before_config_never_creates_vault_or_probes_network(self):
        with patch.object(provider, '_connect', side_effect=AssertionError('network')):
            result = self.api.tarazAiOnlineStatus()
        self.assertFalse(result['configured'])
        self.assertFalse(result['externalTransmissionEnabled'])
        self.assertFalse(result['aggregateCostCapEnforced'])
        self.assertFalse(result['providerHealthVerified'])
        self.assertFalse(self.directory.exists())

    def test_admin_config_seals_secret_with_real_dpapi_and_root_acl(self):
        with patch.object(provider, '_connect', side_effect=AssertionError('network')):
            result = self.configure()
        self.assertTrue(result['configured'])
        self.assertFalse(result['externalTransmissionEnabled'])
        self.assertNotIn(self.secret, json.dumps(result))
        self.assertNotIn('apiKey', result)
        self.assertTrue(self.directory.is_dir())
        _acl_is_private(self.directory)
        self.assertEqual(self.directory.parent, self.book)
        files = list(self.directory.iterdir())
        self.assertEqual(len(files), 2)
        for file in files:
            self.assertNotIn(self.secret.encode(), file.read_bytes())
        self.assertEqual(company_online_vault(self.book)._trusted_config()['apiKey'],
                         self.secret)
        self.assertEqual(self.api.tarazAiOnlineStatus()['model'], 'user-chosen-model')
        self.assertEqual(self.api.standaloneAccountingRead()['revision'], 0)

    def test_browser_boolean_never_authorizes_external_network_or_charges(self):
        self.configure()
        with patch.object(provider, '_post', side_effect=AssertionError('online POST')), \
             patch.object(provider, '_connect', side_effect=AssertionError('online TLS')):
            for index in range(30):
                with self.subTest(index=index):
                    with self.assertRaisesRegex(PermissionError, 'TRANSMISSION_DISABLED'):
                        self.api.tarazAiOnlineGenerate({
                            'text': 'hello', 'manualConsent': True,
                            'maxEstimatedUsd': '0.02',
                        })
            with self.assertRaisesRegex(PermissionError, 'TRANSMISSION_DISABLED'):
                self.api.tarazAiOnlineHealth({'manualConsent': True})
        self.assertFalse(ONLINE_EXTERNAL_TRANSMISSION_ENABLED)
        self.assertEqual(self.api.standaloneAccountingRead()['revision'], 0)

    def test_admin_clear_removes_current_key_and_never_revokes_remote_key(self):
        self.configure()
        cleared = self.api.tarazAiOnlineClear({'manualConsent': True})
        self.assertTrue(cleared['clearedLocally'])
        self.assertFalse(cleared['providerKeyRevoked'])
        self.assertFalse(self.api.tarazAiOnlineStatus()['configured'])
        self.assertFalse(self.api.tarazAiOnlineStatus()['externalTransmissionEnabled'])
        with self.assertRaises(OnlineCredentialError):
            company_online_vault(self.book)._trusted_config()

    def test_missing_manual_consent_or_invalid_endpoint_no_directory(self):
        for changes in ({'manualConsent': False},
                        {'manualConsent': 1},
                        {'endpoint': 'https://127.0.0.1/v1/chat/completions'}):
            with self.subTest(changes=changes):
                with self.assertRaises((PermissionError, ValueError)):
                    self.configure(**changes)
                self.assertFalse(self.directory.exists())

    def test_session_logout_denies_status_and_online_configuration(self):
        self.identity.logout(self.token)
        with self.assertRaises(PermissionError):
            self.api.tarazAiOnlineStatus()
        with self.assertRaises(PermissionError):
            self.configure()
        self.assertFalse(self.directory.exists())

    def test_existing_folder_with_foreign_acl_is_refused(self):
        self.configure()
        with patch('taraz_ai_online_native_boundary._acl_is_private',
                   side_effect=OnlineCredentialError('foreign ACE')):
            with self.assertRaises(OnlineCredentialError):
                self.api.tarazAiOnlineStatus()
        self.assertTrue(self.directory.exists())

    def test_invalid_online_methods_do_not_read_book_data(self):
        self.configure()
        with patch.object(self.api, 'standaloneAccountingRead',
                          side_effect=AssertionError('ledger read')):
            with patch.object(provider, '_post',
                              side_effect=AssertionError('outbound request')):
                with self.assertRaises(PermissionError):
                    self.api.tarazAiOnlineGenerate({
                        'text': 'hello', 'manualConsent': True,
                        'maxEstimatedUsd': '0.02',
                    })


class BrowserBridgeSourceContractTests(unittest.TestCase):
    def test_bridge_names_and_online_panel_are_separate_from_finance(self):
        names = ('tarazAiOnlineStatus', 'tarazAiOnlineConfigure',
                 'tarazAiOnlineClear', 'tarazAiOnlineHealth',
                 'tarazAiOnlineGenerate')
        for name in names:
            self.assertIn("'" + name + "'", JS_BRIDGE)
        panel = (Path(__file__).resolve().parent.parent /
                 'src/taraz_ai_online_panel.jsx').read_text(encoding='utf-8')
        self.assertNotIn('standaloneAccountingRead', panel)
        self.assertNotIn('tarazAiChatRead', panel)
        self.assertNotIn('localStorage', panel)
        self.assertIn('disabled={busy||!canEdit||!available||!canTransmit', panel)
        self.assertIn('manualConsent:true', panel)
        self.assertIn('setConsent(false)', panel)


if __name__ == '__main__':
    unittest.main()
