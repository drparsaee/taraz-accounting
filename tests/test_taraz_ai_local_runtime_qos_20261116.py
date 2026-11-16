"""Focused CPU-only QoS tests. All normal tests use mocks, no ledger or disk."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import Mock, patch

import taraz_ai_local_runtime as local

SMALL = "qwen3:0.6b"
LARGE = "qwen3:4b"
MODELS = [{"name": SMALL, "bytes": 522_000_000},
          {"name": LARGE, "bytes": 2_700_000_000}]


class QoSContractTests(unittest.TestCase):
    def setUp(self):
        self.models = patch.object(local, "installed_models", return_value=MODELS)
        self.memory = patch.object(local, "_memory_bytes",
                                   return_value=(16_000_000_000, 8_000_000_000))
        self.models.start()
        self.memory.start()
        self.addCleanup(self.models.stop)
        self.addCleanup(self.memory.stop)

    def test_manual_consent_is_checked_before_any_network_or_memory_work(self):
        with patch.object(local, "_query") as query:
            for consent in (False, None, 1, "true"):
                with self.subTest(consent=consent):
                    with self.assertRaises(PermissionError):
                        local.generate(SMALL, "سلام", manual_consent=consent)
        query.assert_not_called()

    def test_explicitly_selected_installed_small_model_is_cpu_only(self):
        with patch.object(local, "_query", return_value={
                "model": SMALL, "done": True, "response": "یک متن کوتاه."}) as query:
            result = local.generate(SMALL, "سلام", manual_consent=True)
        query.assert_called_once()
        args, kwargs = query.call_args
        self.assertEqual(args[0], "/api/generate")
        self.assertEqual(kwargs, {"timeout": 12})
        payload = args[1]
        self.assertEqual(set(payload), {"model", "system", "prompt", "stream",
                                        "think", "options"})
        self.assertEqual(payload["model"], SMALL)
        self.assertEqual(payload["prompt"], "سلام")
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])
        self.assertEqual(payload["options"], {
            "temperature": 0.1, "num_gpu": 0, "num_ctx": 512, "num_predict": 32})
        self.assertFalse(result["journalPosted"])
        self.assertFalse(result["financialActionsEnabled"])
        self.assertFalse(result["financialDecisionAuthority"])
        self.assertFalse(result["qualityVerified"])
        self.assertFalse(result["readCompanyData"])
        self.assertFalse(result["savedToLedger"])
        self.assertEqual(result["inferencePolicy"]["execution"], "cpu_only")
        self.assertFalse(result["inferencePolicy"]["fallbackUsed"])

    def test_one_bounded_timeout_fallback_keeps_same_model_and_cpu(self):
        with patch.object(local, "_query", side_effect=[
                local.LocalModelTimeout("synthetic timeout"),
                {"model": SMALL, "done": True, "response": "پاسخ کوتاه."}]) as query:
            result = local.generate(SMALL, "سلام", manual_consent=True)
        self.assertEqual(query.call_count, 2)
        first, second = query.call_args_list
        self.assertEqual(first.args[1]["model"], SMALL)
        self.assertEqual(second.args[1]["model"], SMALL)
        self.assertEqual(first.kwargs["timeout"], 12)
        self.assertEqual(second.kwargs["timeout"], 7)
        self.assertEqual(first.args[1]["options"]["num_predict"], 32)
        self.assertEqual(second.args[1]["options"]["num_predict"], 12)
        self.assertEqual(first.args[1]["options"]["num_ctx"], 512)
        self.assertEqual(second.args[1]["options"]["num_ctx"], 512)
        self.assertEqual(first.args[1]["options"]["num_gpu"], 0)
        self.assertEqual(second.args[1]["options"]["num_gpu"], 0)
        self.assertTrue(result["inferencePolicy"]["fallbackUsed"])
        self.assertEqual(result["inferencePolicy"]["predictionTokenLimit"], 12)
        self.assertFalse(result["qualityVerified"])

    def test_second_timeout_never_causes_third_attempt_and_lock_is_released(self):
        with patch.object(local, "_query", side_effect=[
                local.LocalModelTimeout("first"),
                local.LocalModelTimeout("second")]) as query:
            with self.assertRaises(local.LocalModelTimeout):
                local.generate(SMALL, "سلام", manual_consent=True)
            self.assertEqual(query.call_count, 2)
        with patch.object(local, "_query", return_value={
                "model": SMALL, "done": True, "response": "بعدی"}):
            self.assertTrue(local.generate(SMALL, "بعد", manual_consent=True)["modelRan"])

    def test_malformed_or_incomplete_inference_is_not_retried(self):
        for response in ({"model": SMALL, "done": False, "response": "partial"},
                         {"model": LARGE, "done": True, "response": "wrong"},
                         {"model": SMALL, "done": True, "response": ""},
                         {"model": SMALL, "done": True, "response": "x" * 5001}):
            with self.subTest(response=response.get("response", "")[:8]):
                with patch.object(local, "_query", return_value=response) as query:
                    with self.assertRaises(local.LocalModelError):
                        local.generate(SMALL, "سلام", manual_consent=True)
                self.assertEqual(query.call_count, 1)

    def test_token_limit_completion_is_flagged_as_potentially_truncated(self):
        with patch.object(local, "_query", return_value={
                "model": SMALL, "done": True, "done_reason": "length",
                "response": "پاسخ کوتاه است"}):
            result = local.generate(SMALL, "سلام", manual_consent=True)
        self.assertTrue(result["inferencePolicy"]["outputMayBeTruncated"])
        self.assertFalse(result["qualityVerified"])

    def test_transport_error_other_than_timeout_is_not_retried(self):
        with patch.object(local, "_query",
                          side_effect=local.LocalModelError("invalid provider")) as query:
            with self.assertRaises(local.LocalModelError):
                local.generate(SMALL, "سلام", manual_consent=True)
        query.assert_called_once()

    def test_large_selected_model_never_autoswitches_or_loads(self):
        with patch.object(local, "_query") as query:
            with self.assertRaisesRegex(local.LocalModelError, "choose a smaller"):
                local.generate(LARGE, "سلام", manual_consent=True)
        query.assert_not_called()

    def test_low_ram_refuses_without_inference_or_download(self):
        with patch.object(local, "_memory_bytes",
                          return_value=(16_000_000_000, 100_000_000)):
            with patch.object(local, "_query") as query:
                with self.assertRaisesRegex(local.LocalModelError, "RAM"):
                    local.generate(SMALL, "سلام", manual_consent=True)
        query.assert_not_called()

    def test_missing_selected_model_never_chooses_another(self):
        with patch.object(local, "_query") as query:
            with self.assertRaisesRegex(local.LocalModelError, "not already installed"):
                local.generate("unknown:latest", "سلام", manual_consent=True)
        query.assert_not_called()

    def test_busy_model_semaphore_refuses_additional_request(self):
        with patch.object(local, "_SINGLE_MODEL") as semaphore:
            semaphore.acquire.return_value = False
            with patch.object(local, "_query") as query:
                with self.assertRaisesRegex(local.LocalModelError, "already running"):
                    local.generate(SMALL, "سلام", manual_consent=True)
            query.assert_not_called()
            semaphore.release.assert_not_called()

    def test_provider_inventory_status_never_claims_quality_or_financial_safety(self):
        with patch.object(local, "hardware_profile", return_value={
                "gpu": "Unknown", "gpuAccelerationVerified": False}) as hw:
            status = local.status()
        self.assertTrue(status["available"])
        self.assertFalse(status["modelRan"])
        self.assertFalse(status["qualityVerified"])
        self.assertFalse(status["financialActionsEnabled"])
        self.assertFalse(status["inferencePolicy"]["financialDecisionAuthority"])
        self.assertFalse(status["inferencePolicy"]["automaticModelSelection"])
        self.assertFalse(status["inferencePolicy"]["automaticDownloads"])
        self.assertEqual(status["inferencePolicy"]["execution"], "cpu_only")
        hw.assert_called_once_with()

    def test_unavailable_status_is_diagnostic_not_verified(self):
        with patch.object(local, "installed_models",
                          side_effect=local.LocalModelError("offline")):
            with patch.object(local, "hardware_profile", return_value={}):
                result = local.status()
        self.assertFalse(result["available"])
        self.assertFalse(result["qualityVerified"])
        self.assertFalse(result["offlineInferenceTested"])
        self.assertEqual(result["reason"], "LOCAL_PROVIDER_UNAVAILABLE")

    def test_query_restricts_api_paths_and_timeout_type(self):
        with self.assertRaises(local.LocalModelError):
            local._query("/api/pull", {"name": SMALL})
        response = Mock()
        connection = Mock()
        connection.getresponse.side_effect = TimeoutError("synthetic socket timeout")
        with patch.object(local.http.client, "HTTPConnection",
                          return_value=connection) as factory:
            with self.assertRaises(local.LocalModelTimeout):
                local._query("/api/generate", {"model": SMALL}, timeout=1)
        factory.assert_called_once_with("127.0.0.1", 11434, timeout=1)
        connection.close.assert_called_once()


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("TARAZ_AI_QOS_REAL_LOCAL_PROBE") == "1",
    "Real local-only Ollama smoke probe requires explicit test opt-in")
class ActualShortLocalProbe(unittest.TestCase):
    def test_installed_small_model_short_cpu_only_local_request(self):
        """One 2-token local-only probe; not an LLM quality certification."""
        start = time.monotonic()
        try:
            inventory = local._query("/api/tags", timeout=2)
        except local.LocalModelError as exc:
            self.skipTest("Ollama not reliably available: " + str(exc))
        names = {item.get("name") for item in inventory.get("models", [])
                 if type(item) is dict}
        if SMALL not in names:
            self.skipTest("Small model is not installed; never download a model")
        request = {
            "model": SMALL, "system": "فقط سلام کوتاه بگو.",
            "prompt": "سلام", "think": False, "stream": False,
            "options": {"num_gpu": 0, "num_ctx": 512,
                        "num_predict": 2, "temperature": 0},
        }
        # 2-second discovery + 8-second socket request, well under a
        # 15-second intended probe in the ordinary no-drip response case.
        response = local._query("/api/generate", request, timeout=8)
        self.assertEqual(response.get("model"), SMALL)
        self.assertTrue(response.get("done"))
        self.assertLess(time.monotonic() - start, 15)


if __name__ == "__main__":
    unittest.main()
