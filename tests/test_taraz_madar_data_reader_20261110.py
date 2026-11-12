"""Disposable Madar->Taraz dashboard reads, no installed storage/network writes."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import taraz_madar_data_reader as reader
from standalone_accounting_desktop import JS_BRIDGE
from taraz_desktop import TarazAPI


def state_fixture():
    return {
        "version": 4,
        "projects": [{"id": "project-1", "name": "نمونه", "price": "SECRET-PRICE"}],
        "tasks": [
            {"id": "task-1", "projectId": "project-1", "title": "کار اول",
             "description": "توضیح مجاز", "fileLinks": ["SECRET-LINK"],
             "passwordHash": "SECRET-HASH", "cost": 200, "status": "active"},
            {"id": "task-2", "projectId": "project-1", "title": "کار دوم"},
        ],
        "boards": [{"id": "board-1", "projectId": "project-1", "name": "برد"}],
        "workspaces": [{"id": "workspace-1", "name": "دفتر"}],
        "templates": [],
        "unrelatedSecret": {"password": "SECRET-NOT-EXPOSED"},
    }


class MadarDashboardBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="qa-taraz-madar-", dir=Path(__file__).resolve().parents[2])
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.profile = root / "Roaming"
        self.local = root / "Local"
        self.taraz = root / "Taraz"
        self.taraz.mkdir()
        self.local.mkdir()
        self.profile.mkdir()
        (self.profile / "MadarDesk").mkdir()
        self.file = self.profile / "MadarDesk" / "tasks.json"
        self.file.write_text(json.dumps(state_fixture(), ensure_ascii=False),
                             encoding="utf-8")
        environ = patch.dict(os.environ, {"APPDATA": str(self.profile),
                                           "LOCALAPPDATA": str(self.local)})
        environ.start()
        self.addCleanup(environ.stop)
        self.api = TarazAPI(self.taraz)

    def test_real_native_overview_shows_real_inbox_without_private_read(self):
        bridge = self.local / "Madar-Taraz-Bridge" / "pending"
        bridge.mkdir(parents=True)
        request_id = "a" * 32
        request = {"schema": 1, "source": "madar", "id": request_id,
                   "taskId": "task-1", "title": "ارجاع ساختگی",
                   "projectId": "project-1",
                   "createdUtc": "2026-11-10T09:00:00+00:00"}
        (bridge / f"{request_id}.json").write_text(json.dumps(request), encoding="utf-8")
        with patch.object(reader, "_read_local_state", side_effect=AssertionError("must not read")):
            overview = self.api.tarazMadarDataOverview()
            inbox = self.api.tarazMadarDataRead("inbox")
        self.assertEqual(len(overview["inbox"]["requests"]), 1)
        self.assertEqual(inbox["pendingCount"], 1)
        self.assertEqual(inbox["requests"][0]["id"], request_id)
        self.assertTrue(overview["local"]["available"])
        self.assertTrue(overview["fullReadRequiresExplicitConsent"])
        self.assertFalse(overview["financialEventCreated"])
        self.assertIn("'tarazMadarDataOverview'", JS_BRIDGE)
        self.assertIn("'tarazMadarDataRead'", JS_BRIDGE)
        self.assertFalse(list(self.taraz.glob("*.sqlite3")))

    def test_local_explicit_consent_real_read_paged_and_redacted(self):
        with self.assertRaises(PermissionError):
            self.api.tarazMadarDataRead("tasks")
        overview = self.api.tarazMadarDataOverview(True)
        self.assertEqual(overview["snapshot"]["counts"]["tasks"], 2)
        rows = self.api.tarazMadarDataRead("tasks", 1, 1, True)
        self.assertEqual([record["id"] for record in rows["items"]["tasks"]],
                         ["task-2"])
        self.assertFalse(rows["more"]["tasks"])
        self.assertTrue(rows["source"]["mayBeStale"])
        self.assertFalse(rows["source"]["hostAuthenticated"])
        all_rows = self.api.tarazMadarDataRead("all", 0, 10, True)
        self.assertEqual(all_rows["counts"]["projects"], 1)
        self.assertEqual(all_rows["counts"]["boards"], 1)
        rendered = json.dumps(all_rows, ensure_ascii=False)
        for secret in ("SECRET-PRICE", "SECRET-LINK", "SECRET-HASH",
                       "SECRET-NOT-EXPOSED", "fileLinks", "cost"):
            self.assertNotIn(secret, rendered)
        self.assertIn("کار اول", rendered)
        self.assertFalse(list(self.taraz.glob("*.sqlite3")))

    def test_invalid_sources_bounds_and_link_are_fail_closed(self):
        invalid_calls = (
            ("../../tasks", 0, 10, True),
            ("all", -1, 10, True),
            ("all", 0, 201, True),
            ("all", True, 10, True),
        )
        for args in invalid_calls:
            with self.subTest(args=args):
                with self.assertRaises(reader.MadarReadError):
                    self.api.tarazMadarDataRead(*args)
        with self.assertRaises(reader.MadarReadError):
            self.api.tarazMadarDataRead("tasks", 0, 10, True, {"password": "x"})
        with self.assertRaises(reader.MadarReadError):
            self.api.tarazMadarDataRead("tasks", 0, 10, True, None, "../root")
        before = self.file.read_bytes()
        with self.assertRaises(reader.MadarReadError):
            self.file.write_text("not-json", encoding="utf-8")
            self.api.tarazMadarDataRead("summary", 0, 10, True)
        self.assertEqual(self.file.read_text(encoding="utf-8"), "not-json")
        self.file.write_bytes(before)
        self.assertEqual(self.api.tarazMadarDataRead("summary", 0, 10, True)["counts"]["tasks"], 2)

    def test_full_read_requires_taraz_admin_even_if_host_grants_access(self):
        with patch.object(self.api, "_require_authenticated", side_effect=lambda required="viewer": (
                (_ for _ in ()).throw(PermissionError("admin required")) if required == "admin" else {})):
            self.assertTrue(self.api.tarazMadarDataOverview()["local"]["available"])
            with self.assertRaises(PermissionError):
                self.api.tarazMadarDataRead("all", 0, 20, True)
            with self.assertRaises(PermissionError):
                self.api.tarazMadarDataOverview(True)

    def test_authenticated_host_uses_only_read_routes_and_acl_scoped_projection(self):
        connection = {"url": "https://127.0.0.1:48370", "fingerprint": "f" * 64,
                      "username": "operator", "password": "temporary-password"}
        host_user = {"username": "operator", "role": "viewer", "projects": ["project-1"]}
        state = state_fixture()
        canonical = json.dumps(state, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode()
        responses = (
            {"token": "X" * 40, "user": host_user},
            {"state": state, "user": host_user,
             "revision": hashlib.sha256(canonical).hexdigest()},
        )
        with patch.object(reader, "_pinned_json", side_effect=responses) as transport:
            result = self.api.tarazMadarDataRead(
                "tasks", 0, 50, True, connection, "host")
        self.assertEqual(result["counts"]["tasks"], 2)
        self.assertTrue(result["source"]["serverAclApplied"])
        self.assertEqual(result["source"]["projectGrants"], ["project-1"])
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(transport.call_args_list[0].args[3:5],
                         ("POST", "/api/login"))
        self.assertEqual(transport.call_args_list[1].args[3:5],
                         ("GET", "/api/state"))
        self.assertNotIn("temporary-password", json.dumps(result))
        self.assertNotIn("SECRET-HASH", json.dumps(result))
        self.assertFalse(list(self.taraz.glob("*.sqlite3")))

    def test_host_rejects_bad_identity_revision_and_unsafe_urls_before_io(self):
        base = {"url": "https://127.0.0.1:48370", "fingerprint": "a" * 64,
                "username": "operator", "password": "temporary-password"}
        for override in ({"url": "http://127.0.0.1:48370"},
                         {"url": "https://example.com:443"},
                         {"url": "https://127.0.0.1:48370/madar"},
                         {"url": "https://127.0.0.1:48370@evil.com:443"},
                         {"fingerprint": ""}, {"password": ""}):
            with self.subTest(override=override):
                with patch.object(reader, "_pinned_json") as transport:
                    with self.assertRaises(reader.MadarReadError):
                        self.api.tarazMadarDataRead("all", 0, 10, True,
                                                    {**base, **override}, "host")
                    transport.assert_not_called()
        with patch.object(reader, "_pinned_json", side_effect=[
                {"token": "X" * 40,
                 "user": {"username": "operator", "role": "viewer", "projects": []}},
                {"state": state_fixture(), "revision": "0" * 64,
                 "user": {"username": "operator", "role": "viewer", "projects": []}}]):
            with self.assertRaises(reader.MadarReadError):
                self.api.tarazMadarDataRead("all", 0, 10, True, base, "host")

    def test_tls_pin_checked_before_http_credentials_are_transmitted(self):
        connection = Mock()
        connection.sock.getpeercert.return_value = b"test-certificate"
        with patch.object(reader, "HTTPSConnection", return_value=connection):
            with self.assertRaises(reader.MadarReadError):
                reader._pinned_json("127.0.0.1", 48370, b"0" * 32,
                                    "POST", "/api/login",
                                    payload={"username": "operator",
                                             "password": "must-not-send"})
        connection.request.assert_not_called()
        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
