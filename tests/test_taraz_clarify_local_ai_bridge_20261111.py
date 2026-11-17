"""Synthetic local-model bridge tests. Never contact network or live ledger."""
import json
from threading import RLock
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler

import taraz_llm_print_suggest as print_llm
import taraz_llm_order_suggest as order_llm
from taraz_desktop import TarazAPI
from standalone_accounting_desktop import JS_BRIDGE

class Reply:
    def __init__(self, layout):
        self.packet=json.dumps({"model":"qwen3:0.6b","response":json.dumps(layout),"done":True,"done_reason":"stop"}).encode()
    def __enter__(self):return self
    def __exit__(self,*a):return None
    def read(self,n):return self.packet

class FakeApi:
    def __init__(self, allowed=True, closing=False):
        self._lock=RLock()
        self._exit_backed_up=closing
        self.allowed=allowed
        self.auth_checked=0
    def _require_authenticated(self,*args):
        self.auth_checked+=1
        if not self.allowed:raise PermissionError("auth")

class ModelBridgeTests(unittest.TestCase):
    def test_print_model_uses_direct_loopback_transport_without_proxy_or_redirect(self):
        opener=getattr(print_llm.urlopen,'__self__',None)
        self.assertIsNotNone(opener)
        proxy_handlers=[handler for handler in opener.handlers
                        if isinstance(handler,ProxyHandler)]
        # urllib intentionally omits the ProxyHandler when constructed with
        # an empty proxy map, so no environment/system proxy is installed.
        self.assertEqual(proxy_handlers,[])
        self.assertTrue(any(isinstance(handler,print_llm._NoRedirect)
                            for handler in opener.handlers))
        self.assertIsNone(print_llm._NoRedirect().redirect_request(
            None,None,302,'redirect',{},'https://example.invalid/leak'))

    def test_print_suggest_local_model_only_and_never_finance(self):
        layout={"page":"A4","orientation":"portrait","font":"Vazirmatn","color":"#234567"}
        with patch.object(print_llm,'urlopen',return_value=Reply(layout)) as call:
            result=print_llm.suggest_print_layout('?????? ???? ????')
        self.assertEqual(result['layout'],layout)
        self.assertTrue(result['requiresUserApproval'])
        self.assertTrue(result['modelRan'])
        self.assertFalse(result['financialEventCreated'])
        self.assertFalse(result['externalModelCalled'])
        request=call.call_args.args[0]
        self.assertEqual(request.full_url,'http://127.0.0.1:11434/api/generate')
        sent=json.loads(request.data)
        self.assertEqual(sent['model'],'qwen3:0.6b')
        self.assertEqual(sent['keep_alive'],'15m')
        self.assertFalse(sent['stream'])
        self.assertTrue(sent['prompt'].endswith('?????? ???? ????'))
        self.assertNotIn('invoices',request.data.decode())
    def test_print_bad_prompt_rejected_before_network(self):
        with patch.object(print_llm,'urlopen') as call:
            with self.assertRaises(ValueError):print_llm.suggest_print_layout('')
            with self.assertRaises(ValueError):print_llm.suggest_print_layout('x'*501)
            with self.assertRaises(ValueError):print_llm.suggest_print_layout('a\x00b')
            call.assert_not_called()
    def test_print_unsafe_output_fail_closed(self):
        bad={"page":"A4","orientation":"portrait","font":"Vazirmatn","color":"#234567","eval":"danger"}
        with patch.object(print_llm,'urlopen',return_value=Reply(bad)):
            with self.assertRaises(print_llm.PrintSuggestionUnavailable):
                print_llm.suggest_print_layout('????')
        bad.pop('eval');bad['font']='Injected.js'
        with patch.object(print_llm,'urlopen',return_value=Reply(bad)):
            with self.assertRaises(print_llm.PrintSuggestionUnavailable):
                print_llm.suggest_print_layout('????')
    def test_no_network_failure_leaks_backend_or_secrets(self):
        with patch.object(print_llm,'urlopen',side_effect=OSError('TOKEN-SECRET-PRIVATE')):
            with self.assertRaises(print_llm.PrintSuggestionUnavailable) as trapped:
                print_llm.suggest_print_layout('????')
        self.assertNotIn('TOKEN-SECRET-PRIVATE',str(trapped.exception))
    def test_native_authenticated_bridge_and_close_gate(self):
        self.assertIn("'tarazOrderSuggest'",JS_BRIDGE)
        self.assertIn("'tarazPrintSuggest'",JS_BRIDGE)
        client=FakeApi()
        with patch.object(print_llm,'suggest_print_layout',return_value={'layout':{}}) as suggest:
            self.assertEqual(TarazAPI.tarazPrintSuggest(client,'prompt'),{'layout':{}})
            suggest.assert_called_once_with('prompt')
        self.assertEqual(client.auth_checked,1)
        with patch.object(order_llm,'suggest_order',return_value={'fields':{}}) as suggest:
            self.assertEqual(TarazAPI.tarazOrderSuggest(client,'request'),{'fields':{}})
            suggest.assert_called_once_with('request')
        for method in (TarazAPI.tarazOrderSuggest,TarazAPI.tarazPrintSuggest):
            with self.assertRaises(PermissionError):method(FakeApi(False),'data')
            with self.assertRaises(RuntimeError):method(FakeApi(True,True),'data')

if __name__=='__main__':unittest.main()
