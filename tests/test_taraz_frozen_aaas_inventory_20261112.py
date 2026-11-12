"""Guard the non-installed frozen candidate against missing Phase4/5/6 modules.

Static release-contract preflight, not proof of a successful EXE build.
"""
import ast
from pathlib import Path
import unittest

from scripts import build_taraz_v106_aaas_20261111 as builder


ROOT = Path(__file__).resolve().parents[1]
PHASE_MODULES = {
    "taraz_order_store": {"get"},
    "taraz_aaas_agent": {"CompanyAgentMemory", "review_order_tools",
                         "interpret_natural_order_request"},
    "taraz_madar_order_link": {"MadarOrderLinkStore", "bind",
                               "reconcile_uncertain"},
    "taraz_madar_order_sync": {"sync_order_to_madar",
                               "read_madar_order_stage_progress"},
    "taraz_ecosystem_protocol": {"TrustedScope", "validate_envelope"},
    "taraz_ecosystem_outbox": {"EcosystemOutbox", "enqueue",
                                "reconcile_verified_receipt"},
    "taraz_repository_contracts": {"TarazOrderReadRepository",
                                   "VersionedReference", "read_reference"},
    "taraz_ai_provider_status": {"provider_status"},
}
BRIDGE_API = {
    "tarazOrderFinanceDraft", "tarazAgentOrderReview",
    "tarazAgentMemoryList", "tarazAgentMemoryCommand",
    "tarazAgentNaturalRequest", "tarazMadarOrderProgress",
    "tarazMadarOrderSyncHistory", "tarazMadarOrderRecover",
    "tarazOrderMadarLink", "tarazOrderMadarLinkRead",
    "tarazMadarOrderPreview", "tarazMadarOrderCommit",
    "tarazEcosystemStatus", "tarazAiProviderStatus",
}


class FrozenAgentInventoryTests(unittest.TestCase):
    def test_all_source_modules_are_frozen_and_required_in_pyz(self):
        inventory = builder.source_inventory()
        for module, methods in PHASE_MODULES.items():
            with self.subTest(module=module):
                self.assertIn(module + ".py", inventory)
                self.assertIn(module + ".py", builder.MANDATORY)
                self.assertTrue(methods <= builder.REQUIRED_PYZ[module])
                source = ast.parse((ROOT / (module + ".py")).read_text(encoding="utf-8"))
                names = {node.name for node in ast.walk(source)
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                self.assertTrue(methods <= names)

    def test_native_api_and_bridge_are_both_required(self):
        self.assertTrue(BRIDGE_API <= builder.REQUIRED_ORDER_API)
        api = (ROOT / "taraz_desktop.py").read_text(encoding="utf-8")
        bridge = (ROOT / "standalone_accounting_desktop.py").read_text(encoding="utf-8")
        for method in BRIDGE_API:
            with self.subTest(method=method):
                self.assertIn("def " + method + "(", api)
                self.assertIn("'" + method + "'", bridge)

    def test_compiler_explicitly_collects_every_new_runtime_module(self):
        compiler = (ROOT / "scripts" / "build_taraz_v106_aaas_20261111.py").read_text(
            encoding="utf-8")
        tree = ast.parse(compiler)
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "run_command"]
        self.assertTrue(calls, "PyInstaller invocation must remain identifiable")
        for module in PHASE_MODULES:
            with self.subTest(module=module):
                self.assertIn('"--hidden-import", "' + module + '"', compiler)
        self.assertIn("for module_name, required in REQUIRED_PYZ.items()", compiler)
        self.assertIn("pyz.extract(module_name)", compiler)


if __name__ == "__main__":
    unittest.main()
