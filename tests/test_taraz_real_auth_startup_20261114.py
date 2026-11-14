"""Isolated existing-company native startup and identity acceptance.

Runs no GUI, installer, live user profile, or production backup. Real
LocalCompanyIdentity (PBKDF2/session/role checks) is used in disposable books.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import os
import unittest

from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_desktop import _native_accounting_login
from standalone_accounting_identity import LocalCompanyIdentity
from taraz_desktop import (
    TarazAPI, open_authenticated_taraz_company, run,
    select_existing_taraz_company, _run_authenticated_taraz_api,
)


class RealNativeTarazStartupTests(unittest.TestCase):
    def setUp(self):
        root = TemporaryDirectory(prefix="qa-taraz-real-auth-20261114-")
        self.addCleanup(root.cleanup)
        self.hub = Path(root.name) / "Taraz"
        self.hub.mkdir()
        self.registry = StandaloneCompanyRegistry(self.hub)

    def company(self, name="QA شرکت", username="qa_admin", password="strong-qa-only"):
        record = self.registry.create_company(name)
        directory = self.registry.company_data_directory(record["id"])
        identity = LocalCompanyIdentity(directory)
        identity.add_user(username, password, "admin")
        # Initialize only a disposable real SQLite accounting ledger.
        token = identity.login(username, password)
        accounts = identity.accounting_accounts()
        from standalone_accounting import StandaloneAccountingStore
        StandaloneAccountingStore(
            directory / "standalone-accounting.sqlite3",
            default_currency="RIAL").read(actor=username, accounts=accounts)
        identity.logout(token)
        return record, directory, identity

    @staticmethod
    def login_as(username, password):
        def callback(store):
            token = store.login(username, password)
            return store.require_session(token, "viewer"), token
        return callback

    @staticmethod
    def inventory(directory):
        return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in directory.rglob("*") if p.is_file()}

    def test_no_registered_company_fails_without_creating_any_files(self):
        before = self.inventory(self.hub)
        with self.assertRaisesRegex(PermissionError, "No registered"):
            select_existing_taraz_company(self.hub, choose=lambda _: "a" * 32)
        self.assertEqual(self.inventory(self.hub), before)
        self.assertFalse((self.hub / "books").exists())

    def test_unregistered_legacy_book_is_unchanged_and_never_opened(self):
        legacy = self.hub / "standalone-accounting.sqlite3"
        legacy.write_bytes(b"LEGACY_BOOK_UNCHANGED")
        before = self.inventory(self.hub)
        with patch("taraz_desktop.taraz_data_root", return_value=self.hub), patch(
                "taraz_desktop._run_authenticated_taraz_api") as launch:
            with self.assertRaisesRegex(PermissionError, "No registered"):
                run()
            launch.assert_not_called()
        self.assertEqual(self.inventory(self.hub), before)
        self.assertFalse((self.hub / "local-users.json").exists())

    def test_single_registered_company_skips_chooser_but_not_real_login(self):
        record, directory, identity = self.company()
        before = self.inventory(self.hub)
        with patch('taraz_desktop._pick_existing_taraz_company',
                   side_effect=AssertionError('Single company picker must not open')):
            session = open_authenticated_taraz_company(
                self.hub, login=self.login_as('qa_admin', 'strong-qa-only'))
        api, actual_identity, token = session
        try:
            self.assertEqual(api.path.parent, directory)
            self.assertEqual(api.company_workspace_id, record['id'])
            self.assertEqual(actual_identity.require_session(token)['username'], 'qa_admin')
        finally:
            actual_identity.logout(token)
        self.assertEqual(self.inventory(self.hub), before)

    def test_existing_company_login_binds_true_actor_and_registry_id(self):
        record, directory, identity = self.company()
        before = self.inventory(self.hub)
        session = open_authenticated_taraz_company(
            self.hub, choose=lambda _: record["id"],
            login=self.login_as("qa_admin", "strong-qa-only"))
        self.assertIsNotNone(session)
        api, store, token = session
        try:
            self.assertIs(store.__class__, LocalCompanyIdentity)
            self.assertEqual(api._actor, "qa_admin")
            self.assertEqual(api.company_workspace_id, record["id"])
            self.assertEqual(api.company_name, record["name"])
            self.assertEqual(api.path.parent, directory)
            self.assertEqual(api.standaloneAccountingRead()["currentUser"]["role"], "admin")
            self.assertEqual(store.require_session(token)["username"], "qa_admin")
        finally:
            store.logout(token)
        with self.assertRaises(PermissionError):
            api.standaloneAccountingRead()
        self.assertEqual(self.inventory(self.hub), before)

    def test_native_existing_login_uses_real_local_identity_no_admin_setup(self):
        record, directory, identity = self.company()
        def simulated_native_dialog(native_identity):
            self.assertTrue(native_identity.initialized())
            with self.assertRaises(PermissionError):
                native_identity.add_user("unauthorized", "password", "admin")
            token = native_identity.login("qa_admin", "strong-qa-only")
            return native_identity.require_session(token), token

        with patch("standalone_accounting_secure_login.prompt_premium_accounting_login",
                   side_effect=simulated_native_dialog) as dialog:
            session = open_authenticated_taraz_company(
                self.hub, choose=lambda _: record["id"])
            self.assertEqual(dialog.call_count, 1)
        api, store, token = session
        try:
            self.assertEqual(api._actor, "qa_admin")
            self.assertNotEqual(api._actor, "local")
        finally:
            store.logout(token)

    def test_existing_ledger_without_identity_cannot_open_setup_screen(self):
        record, directory, identity = self.company()
        identity.path.unlink()  # Disposable QA identity only.
        before = self.inventory(self.hub)
        with patch("standalone_accounting_secure_login.prompt_premium_accounting_login") as login:
            with self.assertRaises(PermissionError):
                open_authenticated_taraz_company(
                    self.hub, choose=lambda _: record["id"])
            login.assert_not_called()
        self.assertEqual(self.inventory(self.hub), before)

    def test_native_login_helper_refuses_first_admin_setup_when_required(self):
        record, directory, identity = self.company()
        identity.path.unlink()  # Remove QA-only user registry without live data.
        with patch("standalone_accounting_secure_login.prompt_premium_accounting_login") as dialog:
            with self.assertRaises(PermissionError):
                _native_accounting_login(LocalCompanyIdentity(directory), require_existing=True)
            dialog.assert_not_called()

    def test_bad_selected_id_and_cancel_leave_all_company_files_unchanged(self):
        record, directory, _ = self.company()
        before = self.inventory(self.hub)
        with self.assertRaisesRegex(PermissionError, "not present"):
            select_existing_taraz_company(self.hub, choose=lambda _: "f" * 32)
        self.assertIsNone(select_existing_taraz_company(self.hub, choose=lambda _: None))
        self.assertIsNone(open_authenticated_taraz_company(
            self.hub, choose=lambda _: record["id"], login=lambda _: None))
        self.assertEqual(self.inventory(self.hub), before)
        self.assertFalse((directory / ".taraz-session.lock").exists())
        self.assertFalse((directory / ".standalone-company-active.lock").exists())

    def test_rejected_session_token_never_opens_company_book(self):
        record, directory, identity = self.company()
        before = self.inventory(self.hub)
        with self.assertRaises(PermissionError):
            open_authenticated_taraz_company(
                self.hub, choose=lambda _: record["id"],
                login=lambda _: ({"username": "qa_admin", "role": "admin"}, "wrong-token"))
        self.assertEqual(self.inventory(self.hub), before)

    def test_mismatched_user_identity_fails_and_revokes_token(self):
        record, directory, identity = self.company()
        issued = []
        def wrong_user(store):
            token = store.login("qa_admin", "strong-qa-only")
            issued.append((store, token))
            return {"username": "qa_other", "role": "admin"}, token
        with self.assertRaises(PermissionError):
            open_authenticated_taraz_company(self.hub,
                choose=lambda _: record["id"], login=wrong_user)
        store, token = issued[0]
        with self.assertRaises(PermissionError):
            store.require_session(token)

    def test_cross_company_id_and_active_user_permissions_remain_isolated(self):
        first, dir_a, identity_a = self.company("QA A", "adminA", "passwordA")
        second, dir_b, identity_b = self.company("QA B", "adminB", "passwordB")
        identity_a.add_user("qa_viewer", "viewerpass", "viewer",
                            administrator=identity_a.login("adminA", "passwordA"))
        sessions = []
        for record, user, password in (
            (first, "qa_viewer", "viewerpass"),
            (second, "adminB", "passwordB"),
        ):
            session = open_authenticated_taraz_company(
                self.hub, choose=lambda _: record["id"], login=self.login_as(user, password))
            sessions.append(session)
        try:
            viewer, admin = sessions[0][0], sessions[1][0]
            self.assertEqual(viewer.company_workspace_id, first["id"])
            self.assertEqual(admin.company_workspace_id, second["id"])
            self.assertNotEqual(viewer.path, admin.path)
            self.assertEqual(viewer.standaloneAccountingRead()["currentUser"]["role"], "viewer")
            with self.assertRaises(PermissionError):
                viewer.standaloneAccountingCommand({
                    "command": {"type": "party.register", "eventId": "qa-denied",
                                "partyId": "unauthorized", "name": "NO", "kind": "customer"},
                    "expectedRevision": 0})
            self.assertNotIn("unauthorized", admin.standaloneAccountingRead()["view"]["parties"])
            self.assertNotIn("unauthorized", viewer.standaloneAccountingRead()["view"]["parties"])
        finally:
            for api, store, token in sessions:
                store.logout(token)

    def test_production_lifecycle_refuses_unverified_default_admin_before_writes(self):
        record, directory, identity = self.company()
        implicit = TarazAPI(directory)
        before = self.inventory(self.hub)
        with self.assertRaises(PermissionError):
            _run_authenticated_taraz_api(implicit)
        self.assertEqual(self.inventory(self.hub), before)
        self.assertFalse((directory / ".taraz-session.lock").exists())

    def test_run_routes_real_authenticated_session_and_logs_out(self):
        record, directory, identity = self.company()
        with patch("taraz_desktop.taraz_data_root", return_value=self.hub), patch(
                "taraz_desktop._pick_existing_taraz_company", return_value=record["id"]), patch(
                "standalone_accounting_secure_login.prompt_premium_accounting_login",
                side_effect=lambda store: self.login_as("qa_admin", "strong-qa-only")(store)), patch(
                "taraz_desktop._run_authenticated_taraz_api", return_value="synthetic-no-ui") as launcher:
            result = run()
            self.assertEqual(result, "synthetic-no-ui")
            self.assertEqual(launcher.call_count, 1)
            api = launcher.call_args.args[0]
            self.assertEqual(api.company_workspace_id, record["id"])
            self.assertEqual(api._actor, "qa_admin")
            with self.assertRaises(PermissionError):
                api.standaloneAccountingRead()  # run() revoked its session.
        self.assertFalse((directory / ".standalone-company-active.lock").exists())
        self.assertFalse((directory / ".taraz-session.lock").exists())


if __name__ == "__main__":
    unittest.main()
