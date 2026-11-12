"""Provider policy cannot disable manual business work or leak to cloud."""
import unittest
from taraz_ai_provider_status import (
    ProviderConfigurationError,provider_status
)


class OptionalAiPolicyTests(unittest.TestCase):
    def test_disabled_default_does_no_provider_io(self):
        def forbidden(_url):
            raise AssertionError('An AI-disabled app must not call any provider')
        value=provider_status({},transport=forbidden)
        self.assertEqual(value['availability'],'DISABLED_BY_POLICY')
        self.assertFalse(value['modelRan'])
        self.assertFalse(value['enabledForActions'])
        self.assertTrue(value['coreCommercialFeaturesAvailable'])

    def test_online_requires_consent_and_never_calls_during_status_read(self):
        def forbidden(_url):
            raise AssertionError('Do not make cloud request merely to test presence')
        state=provider_status({'TARAZ_AI_MODE':'online',
                               'TARAZ_AI_ONLINE_PROVIDER':'openai'},transport=forbidden)
        self.assertEqual(state['availability'],'CONSENT_REQUIRED')
        not_consent=provider_status({'TARAZ_AI_MODE':'online',
             'TARAZ_AI_ONLINE_PROVIDER':'openai','TARAZ_AI_ONLINE_CONSENT':'0'},
             transport=forbidden)
        self.assertEqual(not_consent['availability'],'CONSENT_REQUIRED')
        granted=provider_status({'TARAZ_AI_MODE':'online',
             'TARAZ_AI_ONLINE_PROVIDER':'openai','TARAZ_AI_ONLINE_CONSENT':'1'},
             transport=forbidden)
        self.assertEqual(granted['availability'],'CONFIGURED_UNVERIFIED')
        self.assertFalse(granted['requestSentToOnlineProvider'])
        self.assertFalse(granted['enabledForActions'])

    def test_local_installed_is_not_falsely_presented_as_usable_model(self):
        seen=[]
        def probe(url):
            seen.append(url)
            return {'models':[{'name':'qwen3:4b'},{'name':'qwen3:0.6b'}]}
        val=provider_status({'TARAZ_AI_MODE':'local',
             'TARAZ_AI_LOCAL_MODEL':'qwen3:4b'},transport=probe)
        self.assertEqual(seen,['http://127.0.0.1:11434/api/tags'])
        self.assertEqual(val['availability'],'INSTALLED_QUALITY_UNVERIFIED')
        self.assertFalse(val['enabledForActions'])
        self.assertFalse(val['modelRan'])

    def test_local_missing_model_or_host_fail_closed(self):
        c={'TARAZ_AI_MODE':'local','TARAZ_AI_LOCAL_MODEL':'qwen3:4b'}
        no_model=provider_status(c,transport=lambda _: {'models':[]})
        self.assertEqual(no_model['availability'],'MODEL_NOT_INSTALLED')
        unavailable=provider_status(c,transport=lambda _: (_ for _ in ()).throw(
            TimeoutError('QA timeout')))
        self.assertEqual(unavailable['availability'],'LOCAL_PROVIDER_UNAVAILABLE')
        self.assertTrue(unavailable['coreCommercialFeaturesAvailable'])

    def test_provider_hostname_cannot_be_redirected_outside_loopback(self):
        for unsafe in ('http://example.org:11434',
                       'https://127.0.0.1:11434',
                       'http://127.0.0.1:11434@evil.test:80',
                       'http://127.0.0.1:11434/api/generate'):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ProviderConfigurationError):
                    provider_status({'TARAZ_AI_MODE':'local',
                        'TARAZ_AI_LOCAL_MODEL':'qwen3:4b',
                        'TARAZ_AI_LOCAL_ENDPOINT':unsafe},
                        transport=lambda _: (_ for _ in ()).throw(
                            AssertionError('No external fetch')))

    def test_unknown_policy_refuses_instead_of_silent_fallback_to_online(self):
        with self.assertRaises(ProviderConfigurationError):
            provider_status({'TARAZ_AI_MODE':'magic'},
                            transport=lambda _:None)


if __name__=='__main__':
    unittest.main()
