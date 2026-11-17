"""P0 source/native Madar->Taraz bridge contract tests using disposable profiles.

This is deliberately not an installed-EXE, WebView2, live Madar service, or
personal finance ledger test.  All bridge writes stay inside this test's
temporary LOCALAPPDATA, and any accounting command is trapped.
"""
from __future__ import annotations

import hashlib
import json
import marshal
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import taraz_integration as integration
import taraz_madar_data_reader as reader
from standalone_accounting_desktop import JS_BRIDGE
from taraz_desktop import TarazAPI


SOURCE = Path(__file__).resolve().parents[1]
LEDGER_SENTINEL = b"P0 DO NOT TOUCH THE EXISTING ACCOUNTING BOOK\n"


class TarazP0MadarBridgeTests(unittest.TestCase):
    def setUp(self):
        self.installed_program_root = (Path(os.environ["LOCALAPPDATA"]) /
                                       "Programs" / "Taraz") if os.environ.get(
                                           "LOCALAPPDATA") else None
        # Keep every test artifact within the approved CoS-Test project root.
        tmp = tempfile.TemporaryDirectory(
            prefix="qa-taraz-p0-", dir=SOURCE.parent)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.appdata = self.root / "Roaming"
        self.localappdata = self.root / "Local"
        self.book_dir = self.root / "Taraz"
        for directory in (self.appdata, self.localappdata, self.book_dir):
            directory.mkdir()
        self.book = self.book_dir / "standalone-accounting.sqlite3"
        self.book.write_bytes(LEDGER_SENTINEL)
        env = patch.dict(os.environ, {
            "APPDATA": str(self.appdata),
            "LOCALAPPDATA": str(self.localappdata),
        })
        env.start()
        self.addCleanup(env.stop)
        self.bridge_root = self.localappdata / "Madar-Taraz-Bridge"
        self.api = TarazAPI(self.book_dir)
        # Trap both the public financial command and lower-level store access.
        self.financial_command = patch.object(
            self.api, "standaloneAccountingCommand",
            side_effect=AssertionError("bridge called accounting command"))
        self.financial_store = patch.object(
            self.api, "_store",
            side_effect=AssertionError("bridge opened accounting store"))
        self.command_mock = self.financial_command.start()
        self.store_mock = self.financial_store.start()
        self.addCleanup(self.financial_command.stop)
        self.addCleanup(self.financial_store.stop)

    def _proposal(self, number, amount="250000"):
        self.bridge_root.joinpath("pending").mkdir(parents=True, exist_ok=True)
        request_id = f"{number:032x}"
        payload = {
            "schema": 1, "source": "madar", "id": request_id,
            "taskId": f"task-{number}", "projectId": "project-qa",
            "title": f"QA draft {number}", "amountRial": amount,
            "createdUtc": "2026-11-11T09:00:00+00:00",
        }
        file = self.bridge_root / "pending" / f"{request_id}.json"
        file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return request_id, file

    def _markers(self, request_id):
        reviewed = self.bridge_root / "reviewed"
        return (
            reviewed / f"{request_id}.json",
            reviewed / f"{request_id}.intent.json",
            reviewed / f"{request_id}.review.json",
        )

    def _no_financial_effect(self):
        self.assertEqual(self.book.read_bytes(), LEDGER_SENTINEL)
        self.assertEqual({p.name for p in self.book_dir.iterdir()},
                         {self.book.name})
        self.command_mock.assert_not_called()
        self.store_mock.assert_not_called()

    def test_empty_native_inbox_does_not_create_bridge_or_read_private_madar(self):
        with patch.object(reader, "_read_local_state",
                          side_effect=AssertionError("private Madar read")):
            inbox = self.api.tarazIntegrationList()
            overview = self.api.tarazMadarDataOverview()
            page = self.api.tarazMadarDataRead("inbox")
        self.assertFalse(inbox["connected"])
        self.assertEqual(inbox["requests"], [])
        self.assertEqual(overview["inbox"], inbox)
        self.assertEqual(page["pendingCount"], 0)
        self.assertIs(page["financialEventCreated"], False)
        self.assertFalse(self.bridge_root.exists())
        self._no_financial_effect()

    def test_review_and_reject_commit_only_source_bound_metadata(self):
        reviewed_id, original = self._proposal(1)
        rejected_id, rejected_file = self._proposal(2)
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        self.assertEqual(len(self.api.tarazIntegrationList()["requests"]), 2)
        for request_id, decision in (
                (reviewed_id, "reviewed"), (rejected_id, "rejected")):
            answer = self.api.tarazIntegrationReview(request_id, decision)
            self.assertEqual(answer, {"id": request_id, "state": decision,
                                      "financialEventCreated": False})
            stored, intent_path, receipt_path = self._markers(request_id)
            self.assertTrue(stored.is_file())
            intent = json.loads(intent_path.read_text(encoding="utf-8"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(intent["state"], decision)
            self.assertEqual(intent["source"], "taraz")
            self.assertFalse(intent["financialEventCreated"])
            self.assertEqual(receipt["state"], decision)
            self.assertFalse(receipt["financialEventCreated"])
            self.assertEqual(self.api.tarazIntegrationReview(request_id, decision),
                             answer)
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                self.api.tarazIntegrationReview(
                    request_id, "rejected" if decision == "reviewed" else "reviewed")
        self.assertEqual(json.loads(self._markers(reviewed_id)[1].read_text(
            encoding="utf-8"))["sourceDigest"], digest)
        self.assertFalse(original.exists())
        self.assertFalse(rejected_file.exists())
        self.assertEqual(self.api.tarazIntegrationList()["requests"], [])
        self.assertEqual(self.api.tarazIntegrationList()["recovery"], [])
        self._no_financial_effect()

    def test_pre_move_crash_exposes_only_manual_recovery_on_restarted_api(self):
        request_id, pending = self._proposal(3)
        original_rename = os.rename

        def interrupt_move(src, dest):
            if Path(src) == pending:
                raise OSError("P0 simulated crash before proposal move")
            return original_rename(src, dest)

        with patch.object(integration.os, "rename", side_effect=interrupt_move):
            with self.assertRaisesRegex(OSError, "P0 simulated crash"):
                self.api.tarazIntegrationReview(request_id, "reviewed")
        stored, intent, receipt = self._markers(request_id)
        self.assertTrue(intent.exists())
        self.assertTrue(pending.exists())
        self.assertFalse(stored.exists())
        self.assertFalse(receipt.exists())
        restarted = TarazAPI(self.book_dir)
        listed = restarted.tarazIntegrationList()
        self.assertEqual(listed["requests"], [])
        self.assertEqual([(r["id"], r["state"]) for r in listed["recovery"]],
                         [(request_id, "reviewed")])
        with self.assertRaises(PermissionError):
            restarted.tarazIntegrationRecover(request_id)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            restarted.tarazIntegrationReview(request_id, "rejected")
        self.assertTrue(pending.exists())
        result = restarted.tarazIntegrationRecover(request_id, True)
        self.assertEqual(result["state"], "reviewed")
        self.assertFalse(result["financialEventCreated"])
        self.assertFalse(pending.exists())
        self.assertTrue(stored.is_file() and receipt.is_file())
        self.assertEqual(restarted.tarazIntegrationList()["recovery"], [])
        self._no_financial_effect()

    def test_post_move_crash_recovers_same_rejected_decision_only(self):
        request_id, pending = self._proposal(4)
        stored, intent, receipt = self._markers(request_id)
        original_atomic = integration._atomic_json

        def interrupt_receipt(path, payload):
            if path == receipt:
                raise OSError("P0 simulated receipt write crash")
            return original_atomic(path, payload)

        with patch.object(integration, "_atomic_json", side_effect=interrupt_receipt):
            with self.assertRaisesRegex(OSError, "receipt write crash"):
                self.api.tarazIntegrationReview(request_id, "rejected")
        self.assertFalse(pending.exists())
        self.assertTrue(stored.is_file() and intent.is_file())
        self.assertFalse(receipt.exists())
        listed = TarazAPI(self.book_dir).tarazIntegrationList()
        self.assertEqual(listed["requests"], [])
        self.assertEqual([(r["id"], r["state"]) for r in listed["recovery"]],
                         [(request_id, "rejected")])
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.api.tarazIntegrationReview(request_id, "reviewed")
        result = self.api.tarazIntegrationRecover(request_id, True)
        self.assertEqual(result["state"], "rejected")
        self.assertFalse(result["financialEventCreated"])
        self.assertTrue(receipt.is_file())
        self._no_financial_effect()

    def test_changed_source_after_intent_is_not_silently_replayed(self):
        request_id, pending = self._proposal(5)
        original_rename = os.rename
        with patch.object(integration.os, "rename", side_effect=lambda src, dst:
                          (_ for _ in ()).throw(OSError("injected interruption"))
                          if Path(src) == pending else original_rename(src, dst)):
            with self.assertRaisesRegex(OSError, "injected interruption"):
                self.api.tarazIntegrationReview(request_id, "reviewed")
        altered = json.loads(pending.read_text(encoding="utf-8"))
        altered["title"] = "Changed after decision"
        pending.write_text(json.dumps(altered), encoding="utf-8")
        listed = self.api.tarazIntegrationList()
        self.assertEqual(listed["requests"], [])
        self.assertEqual(listed["recovery"], [])
        self.assertEqual(listed["recoveryInvalidCount"], 1)
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.api.tarazIntegrationRecover(request_id, True)
        self.assertFalse(self._markers(request_id)[2].exists())
        self._no_financial_effect()

    def test_admin_consent_and_read_only_projection_are_enforced(self):
        madar = self.appdata / "MadarDesk"
        madar.mkdir()
        (madar / "tasks.json").write_text(json.dumps({
            "projects": [{"id": "p1", "name": "Project", "salary": "PRIVATE"}],
            "tasks": [{"id": "t1", "projectId": "p1", "title": "Task",
                       "amount": 100, "password": "SECRET", "status": "todo"}],
            "boards": [], "workspaces": [], "templates": [],
        }), encoding="utf-8")
        with self.assertRaises(PermissionError):
            self.api.tarazMadarDataRead("all", 0, 50, False)
        with patch.object(self.api, "_require_authenticated",
                          side_effect=lambda role="viewer": (
                              (_ for _ in ()).throw(PermissionError("admin required"))
                              if role == "admin" else {"role": "viewer"})):
            self.assertEqual(self.api.tarazMadarDataRead("inbox")["pendingCount"], 0)
            with self.assertRaises(PermissionError):
                self.api.tarazMadarDataRead("tasks", 0, 50, True)
            with self.assertRaises(PermissionError):
                self.api.tarazMadarDataOverview(True)
        snapshot = self.api.tarazMadarDataRead("all", 0, 50, True)
        serialized = json.dumps(snapshot["items"])
        self.assertEqual(snapshot["counts"]["tasks"], 1)
        self.assertFalse(snapshot["source"]["hostAuthenticated"])
        self.assertTrue(snapshot["source"]["mayBeStale"])
        self.assertFalse(snapshot["financialEventCreated"])
        for forbidden in ("PRIVATE", "SECRET", "salary", "password", "amount"):
            self.assertNotIn(forbidden, serialized)
        self._no_financial_effect()

    def test_native_js_contract_exposes_only_explicit_manual_bridge_actions(self):
        methods = (
            "tarazIntegrationList", "tarazIntegrationReview",
            "tarazIntegrationRecover", "tarazMadarDataOverview", "tarazMadarDataRead")
        for method in methods:
            with self.subTest(method=method):
                self.assertTrue(callable(getattr(TarazAPI, method)))
                self.assertIn("'" + method + "'", JS_BRIDGE)
        frontend = (SOURCE / "src" / "taraz_madar_dashboard.jsx").read_text(
            encoding="utf-8")
        wrapper = (SOURCE / "src" / "taraz_settings_integration.js").read_text(
            encoding="utf-8")
        draft = (SOURCE / "src" / "taraz_madar_invoice_draft.js").read_text(
            encoding="utf-8")
        self.assertIn("setSelection({id:item.id,state:'rejected'", frontend)
        self.assertIn("setSelection({id:item.id,state:'reviewed'", frontend)
        self.assertIn("بازیابی دستی تصمیم پیشین", frontend)
        self.assertIn("onClick={()=>void decide()}", frontend)
        self.assertIn("api.tarazIntegrationRecover(id,true)", wrapper)
        self.assertIn("financialEventCreated!==false", wrapper)
        self.assertIn("pendingTruncated:result.pendingTruncated===true", wrapper)
        self.assertIn('result.pendingTruncated&&<span role="alert">', frontend)
        self.assertIn("unitPrice:''", draft)
        for source in (frontend, wrapper, draft):
            self.assertNotIn("standaloneAccountingCommand", source)
        self._no_financial_effect()

    def test_pending_limit_must_disclose_overflow_without_financial_effect(self):
        # P0 regression: never imply that the first 100 are the whole inbox.
        for number in range(1000, 1101):
            self._proposal(number)
        listing = self.api.tarazIntegrationList()
        self.assertEqual(len(listing["requests"]), 100)
        self.assertEqual(listing["invalidCount"], 0)
        self.assertIs(listing["pendingTruncated"], True)
        self.assertNotIn("pendingTotal", listing)
        self.assertEqual(len(list(self.bridge_root.joinpath("pending").glob("*.json"))),
                         101)
        self._no_financial_effect()

    def test_installed_102_archive_has_pinned_bridge_contract(self):
        """Read installed EXE archive bytes only; never execute the EXE or its modules.

        The pinned installed 1.0.2 is pre-overflow-fix. A source-only fix needs
        a new build; the installed Taraz archive is deliberately not overwritten.
        """
        if self.installed_program_root is None or sys.version_info[:2] != (3, 12):
            self.skipTest("Win32 installed 1.0.2 and Python 3.12 required")
        pointer = self.installed_program_root / "current-version.txt"
        if not pointer.is_file():
            self.skipTest("No installed Taraz version pointer")
        version = pointer.read_text(encoding="utf-8").strip()
        if version != "1.0.2":
            self.skipTest("Installed version is no longer audited 1.0.2")
        executable = self.installed_program_root / "versions" / version / "Taraz.exe"
        if not executable.is_file():
            self.fail("Installed 1.0.2 pointer has no executable")
        self.assertEqual(executable.stat().st_size, 17056486)
        self.assertEqual(hashlib.sha256(executable.read_bytes()).hexdigest(),
                         "095a7c25f678d61c0729e5bc86c930024f5b67ee608ce90371fc8f04c0888b52")
        try:
            from PyInstaller.archive.readers import CArchiveReader
        except ImportError:
            self.skipTest("PyInstaller archive reader unavailable")

        def normalize(code, *, keep_original_start=False):
            return code.replace(
                co_filename="<canonical>",
                co_firstlineno=code.co_firstlineno if keep_original_start else 1,
                co_consts=tuple(normalize(v, keep_original_start=keep_original_start)
                                if isinstance(v, types.CodeType) else v
                                for v in code.co_consts),
            )

        archive = CArchiveReader(str(executable))
        packed = archive.open_embedded_archive("PYZ.pyz")
        pinned_module_hashes = {
            "taraz_integration": "4d7981ef3a1e502a5703dff3be1ff4d65a9a1245caa1b162b890a5c6a49809d7",
            "taraz_madar_data_reader": "a066e3cd3c6cc15d74b9232747b80acb7617f925112c94e2ad4e5700e04eff57",
            "standalone_accounting_desktop": "39fa65d4d43927b9df628cd6bd8b6b46d361c3bcd3a73109daf95448aaaa4d3e",
        }
        for module, expected_sha in pinned_module_hashes.items():
            with self.subTest(packed_module=module):
                frozen = packed.extract(module)
                self.assertIsInstance(frozen, types.CodeType)
                self.assertEqual(hashlib.sha256(marshal.dumps(frozen)).hexdigest(),
                                 expected_sha)
                # The two unchanged runtime modules should also match their
                # current source; integration.py may intentionally have a
                # newer pending overflow fix absent from installed 1.0.2.
                if module != "taraz_integration":
                    source = compile((SOURCE / (module + ".py")).read_text(
                        encoding="utf-8-sig"), str(SOURCE / (module + ".py")), "exec")
                    self.assertEqual(marshal.dumps(normalize(frozen, keep_original_start=True)),
                                     marshal.dumps(normalize(source, keep_original_start=True)))

        native_blob = archive.extract("taraz_desktop")
        self.assertIsInstance(native_blob, bytes)
        native = marshal.loads(native_blob)
        self.assertIsInstance(native, types.CodeType)
        source = compile((SOURCE / "taraz_desktop.py").read_text(
            encoding="utf-8-sig"), str(SOURCE / "taraz_desktop.py"), "exec")

        def nested(code, *parts):
            for part in parts:
                code = next(value for value in code.co_consts
                            if isinstance(value, types.CodeType) and value.co_name == part)
            return code

        for method in ("tarazIntegrationList", "tarazIntegrationReview",
                       "tarazIntegrationRecover", "tarazMadarDataOverview",
                       "tarazMadarDataRead"):
            with self.subTest(native_method=method):
                self.assertEqual(
                    marshal.dumps(normalize(nested(native, "TarazAPI", method))),
                    marshal.dumps(normalize(nested(source, "TarazAPI", method))),
                )
        assets = [name for name in archive.toc
                  if name.replace("\\", "/").startswith("dist/assets/")
                  and name.endswith(".js")]
        self.assertTrue(any(
            all(marker in archive.extract(name) for marker in
                (b"taraz-madar-dashboard", b"tarazIntegrationRecover",
                 b"tarazMadarDataRead")) for name in assets))
        self._no_financial_effect()


if __name__ == "__main__":
    unittest.main()
