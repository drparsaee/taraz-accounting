"""Pure in-memory contract for the actual standalone Taraz HTML/WebView2 bridge.

No GUI, server, user profile, accounting book, network or finance is opened.
"""
import json
import shutil
import subprocess
import unittest

from standalone_accounting_desktop import JS_BRIDGE
from taraz_desktop import TarazAPI


class EmbeddedRecoveryBridgeTests(unittest.TestCase):
    def test_packed_html_bridge_exposes_same_explicit_native_recovery_method(self):
        self.assertTrue(callable(TarazAPI.tarazIntegrationRecover))
        self.assertIn("'tarazIntegrationRecover'", JS_BRIDGE)
        self.assertIn("window.pywebview?.api?.[key]", JS_BRIDGE)
        self.assertIn('new Promise((resolve, reject)', JS_BRIDGE)

    def test_real_bridge_script_routes_exact_manual_recovery_call_only(self):
        if shutil.which('node') is None:
            self.skipTest('Node executable not available to execute bridge JS')
        script = JS_BRIDGE.removeprefix('<script>').removesuffix('</script>')
        javascript = r"""
const vm=require('node:vm');
const fs=require('node:fs');
const assert=require('node:assert/strict');
const script=fs.readFileSync(0,'utf8');
const calls=[];
const id='a'.repeat(32);
const window={pywebview:{api:{
  tarazIntegrationRecover:async(...args)=>{
    calls.push(args);
    return {id,state:'reviewed',financialEventCreated:false};
  },
  standaloneAccountingCommand:()=>{throw new Error('ledger forbidden');}
}}};
vm.runInNewContext(script,{window,Date,Promise,Error,setTimeout});
assert.equal(window.__madarStandaloneOnly,true);
assert.equal(typeof window.madar.tarazIntegrationRecover,'function');
assert.deepEqual(calls,[]);
window.madar.tarazIntegrationRecover(id,true).then(value=>{
  assert.equal(value.id,id);
  assert.equal(value.financialEventCreated,false);
  assert.deepEqual(calls,[[id,true]]);
  process.stdout.write('EMBEDDED_RECOVERY_BRIDGE_PASS');
}).catch(error=>{process.stderr.write(String(error));process.exitCode=2});
"""
        outcome = subprocess.run(
            ['node', '-e', javascript], input=script, text=True,
            capture_output=True, timeout=10, check=False,
            encoding='utf-8', errors='replace',
        )
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        self.assertEqual(outcome.stdout, 'EMBEDDED_RECOVERY_BRIDGE_PASS')


if __name__ == '__main__':
    unittest.main()
