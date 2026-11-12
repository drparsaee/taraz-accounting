"""Native authenticated read-only ecosystem and AI-disabled status checks.

Uses disposable company principals; does not import a running Madar host.
"""
from pathlib import Path
import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tests.taraz_p1_real_backend_http_fixture_20261112 import (
    AuthenticatedQaTarazAPI, Identity,
)


class EcosystemNativeBridgeTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(prefix='qa-taraz-ecosystem-api-')
        self.addCleanup(temp.cleanup)
        self.company=Path(temp.name)/'company'
        self.company.mkdir()
        self.api=AuthenticatedQaTarazAPI(self.company,Identity())

    def test_local_manual_business_and_ai_disabled_are_reported_not_faked(self):
        with patch.dict(os.environ,{'TARAZ_AI_MODE':'disabled'}):
            ecosystem=self.api.tarazEcosystemStatus()
            ai=self.api.tarazAiProviderStatus()
        self.assertEqual(ecosystem['schemaVersion'],1)
        self.assertEqual(ecosystem['product'],'TARAZ')
        self.assertEqual(ecosystem['networkState'],'NOT_PROBED')
        self.assertEqual(ecosystem['otherProducts']['RADAR'],'SOURCE_NOT_VERIFIED')
        self.assertEqual(ecosystem['outbox']['remoteSenderAvailable'],False)
        self.assertEqual(ecosystem['centralFinancialAuthorityTransfer'],
                         'OPEN_NOT_IMPLEMENTED')
        self.assertTrue(ecosystem['readOnly'])
        self.assertFalse(ecosystem['financialEventCreated'])
        self.assertEqual(ai['availability'],'DISABLED_BY_POLICY')
        self.assertTrue(ai['coreCommercialFeaturesAvailable'])
        self.assertFalse(ai['enabledForActions'])
        self.assertFalse((self.company/'taraz-ecosystem-outbox.sqlite3').exists())
        self.assertFalse((self.company/'standalone-accounting.sqlite3').exists())

    def test_revoked_session_denies_both_native_capabilities(self):
        with patch.object(self.api,'_require_authenticated',
                          side_effect=PermissionError('revoked session')):
            with self.assertRaises(PermissionError):
                self.api.tarazEcosystemStatus()
            with self.assertRaises(PermissionError):
                self.api.tarazAiProviderStatus()

    def test_viewer_may_inspect_but_no_business_write_or_model_execution(self):
        visitor=Identity()
        visitor.user.update(username='qa-viewer',role='viewer',financeEdit=False)
        api=AuthenticatedQaTarazAPI(self.company,visitor)
        with patch.dict(os.environ,{'TARAZ_AI_MODE':'disabled'}):
            self.assertTrue(api.tarazEcosystemStatus()['readOnly'])
            self.assertFalse(api.tarazAiProviderStatus()['enabledForActions'])


if __name__=='__main__':
    unittest.main()
