"""AI-optional capability discovery with no implicit inference or cloud call.

The runtime may use this only after the native host has authenticated a
company/session. This is a capability status, NOT a quality certificate for a
model and never a permission to execute an Agent's proposed financial action.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ProviderConfigurationError(ValueError):
    pass


def _local_url(raw):
    parsed=urlsplit(raw)
    if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path not in ('','/') or
            not 1<= (parsed.port or 0)<=65535):
        raise ProviderConfigurationError('Local provider must be pinned to 127.0.0.1')
    return f'http://127.0.0.1:{parsed.port}/api/tags'


def _get_tags(url):
    request=Request(url,headers={'Accept':'application/json'},method='GET')
    with urlopen(request,timeout=1.5) as resp:
        if resp.status!=200:
            raise OSError('Provider discovery failed')
        body=resp.read(524289)
        if len(body)>524288:
            raise ProviderConfigurationError('Provider discovery too large')
        return json.loads(body.decode('utf-8'))


def provider_status(config=None,*,transport=None):
    """Source policy = server-owned environment, never a browser argument.

    Local model discovery is GET-only and sends no company business data.
    Cloud mode never sends a request during status inspection. All unverified
    models remain unavailable for Agent execution until independent quality
    and permission tests are separately passed.
    """
    source=os.environ if config is None else config
    mode=source.get('TARAZ_AI_MODE','disabled')
    status={'mode':mode,'enabledForActions':False,'modelRan':False,
            'requestSentToOnlineProvider':False,
            'coreCommercialFeaturesAvailable':True,
            'requiresIndependentQualityGate':True}
    if mode=='disabled':
        return {**status,'availability':'DISABLED_BY_POLICY',
                'reason':'AI is optional; no verified provider configured'}
    if mode=='online':
        # Presence of a server-owned key is not permission to run a model,
        # nor proof of egress, quality, provider identity or data consent.
        provider=source.get('TARAZ_AI_ONLINE_PROVIDER','')
        if provider not in ('openai','openrouter'):
            return {**status,'availability':'UNCONFIGURED',
                    'reason':'No supported online provider selected'}
        if source.get('TARAZ_AI_ONLINE_CONSENT') != '1':
            return {**status,'availability':'CONSENT_REQUIRED',
                    'provider':provider,
                    'reason':'Online data transfer has not been authorized'}
        return {**status,'availability':'CONFIGURED_UNVERIFIED',
                'provider':provider,
                'reason':'No external request or model-quality test was made'}
    if mode!='local':
        raise ProviderConfigurationError('Unrecognized AI policy; fail closed')
    model=source.get('TARAZ_AI_LOCAL_MODEL','')
    if (not isinstance(model,str) or not model or len(model)>100 or
            any(c.isspace() or ord(c)<32 for c in model)):
        return {**status,'availability':'NO_LOCAL_MODEL_SELECTED',
                'reason':'No installed local model selected'}
    url=_local_url(source.get('TARAZ_AI_LOCAL_ENDPOINT',
                              'http://127.0.0.1:11434'))
    try:
        tags=(transport or _get_tags)(url)
        if (type(tags) is not dict or type(tags.get('models')) is not list or
                len(tags['models'])>1000):
            raise ProviderConfigurationError('Invalid local discovery result')
        names=[item.get('name') for item in tags['models'] if type(item) is dict]
        if model not in names:
            return {**status,'availability':'MODEL_NOT_INSTALLED',
                    'provider':'ollama','model':model,
                    'reason':'Selected local model absent from Ollama discovery'}
        return {**status,'availability':'INSTALLED_QUALITY_UNVERIFIED',
                'provider':'ollama','model':model,
                'reason':'Discovery does not establish Persian model reliability'}
    except (OSError,TimeoutError,ValueError,TypeError,UnicodeError):
        return {**status,'availability':'LOCAL_PROVIDER_UNAVAILABLE',
                'provider':'ollama','model':model,
                'reason':'Bounded local discovery did not establish availability'}
