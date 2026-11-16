"""Unit contracts for local-only manual LLM, never actual financial posting."""
from __future__ import annotations

import unittest
from unittest.mock import patch
import os
from pathlib import Path
import tempfile

import taraz_ai_local_runtime as local


class LocalRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.models=[{"name":"qwen3:0.6b","size":522000000},
                     {"name":"qwen3:4b","size":2500000000}]

    def test_discovery_get_only_and_read_only(self):
        with patch.object(local, "_query",return_value={"models":self.models}) as query:
            status=local.status()
        query.assert_called_once_with("/api/tags")
        self.assertTrue(status["available"])
        self.assertFalse(status["modelRan"])
        self.assertFalse(status["financialActionsEnabled"])
        self.assertFalse(status["qualityVerified"])
        self.assertEqual(len(status["models"]),2)

    def test_unavailable_is_not_faked_as_model(self):
        with patch.object(local, "_query",side_effect=local.LocalModelError("offline")):
            status=local.status()
        self.assertFalse(status["available"])
        self.assertFalse(status["modelRan"])

    def test_explicit_consent_and_strict_prompt(self):
        with self.assertRaises(PermissionError):
            local.generate("qwen3:0.6b","test",manual_consent=False)
        for prompt in ("", "a"*601, "bad\x00text"):
            with self.subTest(prompt=prompt[:20]):
                with self.assertRaises(ValueError):
                    local.generate("qwen3:0.6b",prompt,manual_consent=True)

    def test_never_autoposts_or_sends_company_context(self):
        def stub(path,payload=None,**_options):
            if path=="/api/tags":
                return {"models":self.models}
            self.assertEqual(path,"/api/generate")
            self.assertEqual(set(payload),{"model","system","prompt","stream","think","options"})
            self.assertEqual(payload["prompt"],"سلام")
            self.assertNotIn("financialLedger",str(payload))
            self.assertFalse(payload["stream"])
            return {"model":"qwen3:0.6b","done":True,"response":"سلام، تایید انسانی لازم است."}
        with patch.object(local,"_query",side_effect=stub) as call:
            result=local.generate("qwen3:0.6b","سلام",manual_consent=True)
        self.assertEqual(call.call_count,2)
        self.assertTrue(result["modelRan"])
        self.assertFalse(result["journalPosted"])
        self.assertFalse(result["readCompanyData"])
        self.assertFalse(result["financialActionsEnabled"])
        self.assertFalse(result["qualityVerified"])

    def test_rejects_uninstalled_large_and_incomplete_model(self):
        with patch.object(local,"_query",return_value={"models":self.models}):
            with self.assertRaises(local.LocalModelError):
                local.generate("unknown:0.5b","hi",manual_consent=True)
        oversized=[{"name":"oversized:1","size":3000000001}]
        with patch.object(local,"_query",return_value={"models":oversized}):
            with self.assertRaises(local.LocalModelError):
                local.generate("oversized:1","hi",manual_consent=True)
        def incomplete(path,payload=None,**_opts):
            if path=="/api/tags":
                return {"models":self.models}
            return {"model":"qwen3:0.6b","done":False,"response":"partial"}
        with patch.object(local,"_query",side_effect=incomplete):
            with self.assertRaises(local.LocalModelError):
                local.generate("qwen3:0.6b","hi",manual_consent=True)

    def test_rejects_duplicate_or_malformed_provider_inventory(self):
        for entries in ([self.models[0],self.models[0]],
                        [{"name":"../bad","size":100}],
                        [{"name":"x","size":0}]):
            with self.subTest(entries=entries):
                with patch.object(local,"_query",return_value={"models":entries}):
                    self.assertFalse(local.status()["available"])


@unittest.skipUnless(os.name=="nt","Authenticated Windows principal required")
class NativeBridgeAuthTest(unittest.TestCase):
    def test_real_windows_company_bridge_requires_shape_and_manual_consent(self):
        from taraz_fresh_windows_workspace import stage_new_empty_root,open_fresh_company
        with tempfile.TemporaryDirectory(prefix="taraz-local-ai-auth-") as work:
            root=Path(work)/"Taraz"
            stage_new_empty_root(root)
            api,identity,token=open_fresh_company(root)
            try:
                with patch.object(local,"status",return_value={
                        "provider":"ollama","available":True,"financialActionsEnabled":False}) as probe:
                    status=api.tarazAiLocalStatus()
                    probe.assert_called_once_with()
                    self.assertFalse(status["financialActionsEnabled"])
                with patch.object(local,"generate",return_value={
                        "provider":"ollama","modelRan":True,"response":"synthetic",
                        "journalPosted":False}) as inference:
                    with self.assertRaises(ValueError):
                        api.tarazAiLocalGenerate({"model":"qwen3:0.6b","prompt":"Hi"})
                    inference.assert_not_called()
                    out=api.tarazAiLocalGenerate({
                        "model":"qwen3:0.6b","prompt":"Hi","manualConsent":True})
                    self.assertTrue(out["modelRan"])
                    inference.assert_called_once_with(
                        "qwen3:0.6b","Hi",manual_consent=True)
                self.assertEqual(api.standaloneAccountingRead()["revision"],0)
            finally:
                identity.logout(token)


if __name__=="__main__":
    unittest.main()
