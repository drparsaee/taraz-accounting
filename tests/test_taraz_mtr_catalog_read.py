"""Read-only local catalog pilot with ONLY disposable, synthetic company books."""

from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from standalone_accounting import StandaloneAccountingStore
from standalone_accounting_company_registry import StandaloneCompanyRegistry
from standalone_accounting_identity import LocalCompanyIdentity
from taraz_mtr_catalog_read import (
    CatalogReadError, CatalogStale, HostCatalogScope, TarazCatalogRead,
)

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
STAMP = "2026-11-09T12:00:00Z"


class LocalCatalogReadTests(unittest.TestCase):
    def setUp(self):
        sandbox = tempfile.TemporaryDirectory(prefix="synthetic-taraz-catalog-")
        self.addCleanup(sandbox.cleanup)
        root = Path(sandbox.name) / "company-hub"
        root.mkdir()
        self.registry = StandaloneCompanyRegistry(root)
        self.company = self.registry.create_company("Synthetic E2 Test Company")
        self.book = self.registry.company_data_directory(self.company["id"])
        self.identity = LocalCompanyIdentity(self.book)
        self.identity.add_user("reviewer", "synthetic-only-secret", role="admin")
        self.token = self.identity.login("reviewer", "synthetic-only-secret")
        self.store = StandaloneAccountingStore(
            self.book / "standalone-accounting.sqlite3", default_currency="RIAL"
        )
        self.accounts = self.identity.accounting_accounts()
        self.revision = 0
        for command in (
            {"type": "party.register", "eventId": "party-evt-1",
             "partyId": "party-1", "name": "Same name", "kind": "customer",
             "creditLimit": 99999999},
            {"type": "party.register", "eventId": "party-evt-2",
             "partyId": "party-2", "name": "Same name", "kind": "vendor"},
            {"type": "party.register", "eventId": "party-evt-3",
             "partyId": "party-private", "name": "Hidden company",
             "kind": "both", "creditLimit": 12345},
            {"type": "item.create", "eventId": "item-evt-1",
             "itemId": "item-1", "sku": "SKU1", "name": "Box", "kind": "goods",
             "unit": "piece"},
            {"type": "item.create", "eventId": "item-evt-2",
             "itemId": "item-2", "sku": "SKU2", "name": "Box", "kind": "service",
             "unit": "service"},
        ):
            outcome = self.store.command(
                command, actor="reviewer", accounts=self.accounts,
                expected_revision=self.revision, now=STAMP,
            )
            self.revision = outcome["revision"]
        self.policy = HostCatalogScope(
            company_id=self.company["id"], org_id=self.company["id"],
            project_id="project-1", project_grants=frozenset({"project-1"}),
            role_grants=frozenset({"admin", "editor"}),
            party_fields=frozenset({"id", "name", "kind"}),
            item_fields=frozenset({"id", "sku", "name", "kind", "unit", "active"}),
            party_ids=frozenset({"party-1", "party-2"}),
            item_ids=frozenset({"item-1", "item-2"}),
            source_revision=self.revision, observed_at=NOW,
        )
        self.adapter = self.make_adapter()

    def make_adapter(self, *, policy=None, registry=None, identity=None, store=None):
        return TarazCatalogRead(
            registry=registry or self.registry,
            identity=identity or self.identity,
            store=store or self.store,
            host_scope=self.policy if policy is None else policy,
        )

    def query(self, kind="parties", *, offset=0, limit=10, revision=None,
              adapter=None, token=None, now=None):
        obj = {
            "kind": kind, "offset": offset, "limit": limit,
            "expectedRevision": self.revision if revision is None else revision,
        }
        return (adapter or self.adapter).read(
            session_token=self.token if token is None else token,
            query_json=json.dumps(obj, ensure_ascii=False),
            trusted_now=NOW if now is None else now,
        )

    def test_parties_full_authorized_candidates_include_conflicting_names(self):
        result = self.query("parties")
        self.assertEqual(result["revision"], self.revision)
        self.assertEqual(result["companyId"], self.company["id"])
        self.assertEqual(result["orgId"], self.company["id"])
        self.assertEqual(result["authorizedCount"], 2)
        self.assertEqual(result["rows"], [
            {"id": "party-1", "name": "Same name", "kind": "customer"},
            {"id": "party-2", "name": "Same name", "kind": "vendor"},
        ])
        self.assertTrue(result["authenticatedLocalCompany"])
        for name in (
            "remoteTarazPeerAuthenticated", "importedIdentityOfficiallyVerified",
            "officialPartyLinkCreated", "financialPostingPerformed",
            "networkUsed",
        ):
            self.assertFalse(result[name])

    def test_items_products_and_services_projection(self):
        result = self.query("items")
        self.assertEqual(result["authorizedCount"], 2)
        self.assertEqual(result["rows"], [
            {"id": "item-1", "sku": "SKU1", "name": "Box",
             "kind": "goods", "unit": "piece", "active": True},
            {"id": "item-2", "sku": "SKU2", "name": "Box",
             "kind": "service", "unit": "service", "active": True},
        ])
        self.assertNotIn("stockTracked", repr(result))

    def test_no_ledger_financial_balances_documents_or_history_leak(self):
        # accounting_view includes sensitive AR/AP/credit limits and GL.
        full = self.store.read(actor="reviewer", accounts=self.accounts)["view"]
        self.assertIn("accounts", full)
        self.assertIn("receivable", full["parties"]["party-1"])
        self.assertEqual(full["parties"]["party-1"]["creditLimit"], 99999999)
        output = repr(self.query())
        for fragment in (
            "creditLimit", "receivable", "payable", "historicalBalance",
            "journals", "invoices", "payments", "receipts",
            "accounts", "companyProfile", "99999999", "Hidden company",
        ):
            self.assertNotIn(fragment, output)

    def test_host_field_visibility_redacts_even_safe_columns(self):
        scope = replace(
            self.policy, party_fields=frozenset({"id", "name"}),
            item_fields=frozenset({"id", "name"}),
        )
        adapter = self.make_adapter(policy=scope)
        self.assertEqual(self.query(adapter=adapter)["rows"], [
            {"id": "party-1", "name": "Same name"},
            {"id": "party-2", "name": "Same name"},
        ])
        self.assertEqual(self.query("items", adapter=adapter)["rows"], [
            {"id": "item-1", "name": "Box"},
            {"id": "item-2", "name": "Box"},
        ])

    def test_host_row_grants_not_client_candidate_selection(self):
        granted = replace(self.policy, party_ids=frozenset({"party-2"}))
        self.assertEqual(self.query(adapter=self.make_adapter(policy=granted))["rows"], [
            {"id": "party-2", "kind": "vendor", "name": "Same name"}
        ])
        for forbidden in ("candidateIds", "actor", "organizationId", "projectId",
                          "financeView", "sourceVerified", "allowedIds",
                          "verifiedTarazSource"):
            query = {"kind": "parties", "offset": 0, "limit": 5,
                     "expectedRevision": self.revision, forbidden: True}
            with self.subTest(forbidden=forbidden), self.assertRaises(CatalogReadError):
                self.adapter.read(
                    session_token=self.token, query_json=json.dumps(query),
                    trusted_now=NOW,
                )

    def test_pagination_retains_duplicates_across_pages(self):
        one = self.query(limit=1)
        two = self.query(offset=one["nextOffset"], limit=1)
        self.assertEqual(one["rows"][0]["id"], "party-1")
        self.assertEqual(two["rows"][0]["id"], "party-2")
        self.assertEqual(one["nextOffset"], 1)
        self.assertIsNone(two["nextOffset"])
        self.assertEqual(self.query(offset=99)["rows"], [])

    def test_limit_offset_schema_and_boolean_int_confusion_rejected(self):
        for values in (
            {"limit": 0}, {"limit": 51}, {"offset": -1}, {"offset": 9000},
            {"limit": True}, {"offset": False}, {"revision": True},
            {"limit": "5"}, {"offset": 1.5},
        ):
            obj = {"kind": "parties", "offset": 0, "limit": 10,
                   "expectedRevision": self.revision}
            changes = dict(values)
            if "revision" in changes:
                changes["expectedRevision"] = changes.pop("revision")
            obj.update(changes)
            with self.subTest(obj=obj), self.assertRaises(CatalogReadError):
                self.adapter.read(
                    session_token=self.token, query_json=json.dumps(obj),
                    trusted_now=NOW,
                )

    def test_duplicate_key_nested_unknown_and_oversized_json_rejected(self):
        for value in (
            '{"kind":"parties","kind":"items","offset":0,"limit":1,"expectedRevision":5}',
            '{"kind":"parties","offset":0,"limit":1,"expectedRevision":5,"x":{"a":1,"a":2}}',
            '{"kind":NaN}', '{"kind":"parties","offset":1}',
            "[]" , "{}", " " * 1100,
        ):
            with self.subTest(value=value[:50]), self.assertRaises(CatalogReadError):
                self.adapter.read(session_token=self.token, query_json=value,
                                  trusted_now=NOW)
        with self.assertRaises(CatalogReadError):
            self.adapter.read(session_token=self.token, query_json="\ud800",
                              trusted_now=NOW)

    def test_wrong_or_revoked_local_company_session(self):
        with self.assertRaises(PermissionError):
            self.query(token="wrong-" + "x" * 50)
        self.identity.logout(self.token)
        with self.assertRaises(PermissionError):
            self.query()

    def test_role_downgrade_or_view_capability_revoked(self):
        with patch.object(self.identity, "accounting_accounts", return_value={
            "reviewer": {"username": "reviewer", "role": "admin",
                         "financeView": False},
        }):
            with self.assertRaises(PermissionError):
                self.query()
        with patch.object(self.identity, "accounting_accounts", return_value={
            "reviewer": {"username": "reviewer", "role": "viewer",
                         "financeView": True},
        }):
            with self.assertRaises(PermissionError):
                self.query()
        viewer_policy = replace(self.policy, role_grants=frozenset({"viewer"}))
        with self.assertRaises(PermissionError):
            self.query(adapter=self.make_adapter(policy=viewer_policy))

    def test_real_identity_role_change_invalidates_old_catalog_authorization(self):
        self.identity.add_user(
            "supervisor", "synthetic-supervisor-secret", role="admin",
            administrator=self.token,
        )
        supervisor_token = self.identity.login(
            "supervisor", "synthetic-supervisor-secret"
        )
        self.identity.change_role("reviewer", "viewer", administrator=supervisor_token)
        with self.assertRaises(PermissionError):
            self.query()

    def test_real_identity_disable_revokes_active_session(self):
        self.identity.add_user(
            "supervisor", "synthetic-supervisor-secret", role="admin",
            administrator=self.token,
        )
        supervisor_token = self.identity.login(
            "supervisor", "synthetic-supervisor-secret"
        )
        self.identity.disable_user("reviewer", administrator=supervisor_token)
        with self.assertRaises(PermissionError):
            self.query()

    def test_negative_tenant_company_binding_prevents_cross_book(self):
        second = self.registry.create_company("Another Synthetic Company")
        wrong = replace(self.policy, company_id=second["id"], org_id=second["id"])
        with self.assertRaises(PermissionError):
            self.query(adapter=self.make_adapter(policy=wrong))
        with self.assertRaises(PermissionError):
            replace(self.policy, org_id="unrelated-org")
        with self.assertRaises(PermissionError):
            self.query(adapter=self.make_adapter(
                policy=self.policy, identity=LocalCompanyIdentity(
                    self.registry.company_data_directory(second["id"])
                )))

    def test_missing_or_foreign_project_scope_rejected(self):
        for granted in (frozenset(), frozenset({"other-project"})):
            with self.subTest(granted=granted), self.assertRaises(PermissionError):
                replace(self.policy, project_grants=granted)
        with self.assertRaises(PermissionError):
            replace(self.policy, project_id="different")

    def test_malformed_field_or_role_grants_denied(self):
        for fields in (frozenset({"name"}), frozenset({"id", "creditLimit"}),
                       frozenset({"id", "receivable"})):
            with self.subTest(fields=fields), self.assertRaises(PermissionError):
                replace(self.policy, party_fields=fields)
        with self.assertRaises(PermissionError):
            replace(self.policy, item_fields=frozenset({"id", "stockTracked"}))
        with self.assertRaises(PermissionError):
            replace(self.policy, role_grants=frozenset())
        with self.assertRaises(PermissionError):
            replace(self.policy, role_grants=frozenset({"finance_reviewer"}))

    def test_stale_client_revision_and_host_source_revision(self):
        with self.assertRaises(CatalogStale):
            self.query(revision=self.revision - 1)
        with self.assertRaises(CatalogStale):
            self.query(adapter=self.make_adapter(
                policy=replace(self.policy, source_revision=self.revision - 1)
            ))

    def test_source_observation_date_stale_future_or_naive(self):
        with self.assertRaises(CatalogStale):
            self.query(now=NOW + timedelta(seconds=301))
        with self.assertRaises(CatalogStale):
            self.query(now=NOW - timedelta(seconds=31))
        with self.assertRaises(CatalogReadError):
            self.query(now=NOW.replace(tzinfo=None))
        with self.assertRaises(CatalogReadError):
            replace(self.policy, observed_at=NOW.replace(tzinfo=None))
        self.assertEqual(self.query(now=NOW + timedelta(seconds=300))["revision"],
                         self.revision)

    def test_actual_local_write_raises_catalog_revision_staleness(self):
        self.store.command(
            {"type": "party.register", "eventId": "later-evt",
             "partyId": "party-later", "name": "New registered party",
             "kind": "customer"},
            actor="reviewer", accounts=self.accounts,
            expected_revision=self.revision, now=STAMP,
        )
        with self.assertRaises(CatalogStale):
            self.query()

    def test_stale_or_unknown_host_granted_row_id_fails_closed(self):
        bad = replace(self.policy, party_ids=frozenset({"party-1", "party-gone"}))
        with self.assertRaises(CatalogStale):
            self.query(adapter=self.make_adapter(policy=bad))

    def test_no_write_and_exact_revision_preserved_after_many_reads(self):
        def raw():
            with closing(sqlite3.connect(self.store.path)) as conn:
                return conn.execute(
                    "SELECT revision,digest,state FROM standalone_accounting"
                ).fetchone()
        before = raw()
        for _ in range(4):
            self.query()
            self.query("items")
        after = raw()
        self.assertEqual(before, after)
        self.assertEqual(self.store.read(
            actor="reviewer", accounts=self.accounts)["revision"], self.revision)

    def test_catalog_return_does_not_expose_token_credentials(self):
        self.assertNotIn(self.token, repr(self.query()))
        self.assertNotIn("synthetic-only-secret", repr(self.query("items")))

    def test_missing_or_incompatible_company_book_denied_without_creation(self):
        self.store.path.rename(self.store.path.with_name("moved.sqlite3"))
        with self.assertRaises(PermissionError):
            self.query()
        self.assertFalse(self.store.path.exists())

    def test_malformed_core_view_rejected_without_hidden_fields(self):
        original = self.store.read
        def corrupt(*, actor, accounts):
            data = original(actor=actor, accounts=accounts)
            data["view"]["parties"]["party-1"]["id"] = "wrong-id"
            return data
        with patch.object(self.store, "read", side_effect=corrupt):
            with self.assertRaises(CatalogReadError):
                self.query()
        with patch.object(self.store, "read", return_value={
            "revision": self.revision, "view": {"parties": [], "items": {},
                                               "currency": "RIAL"},
        }):
            with self.assertRaises(CatalogReadError):
                self.query()

    def test_corrupt_underlying_accounting_digest_refused_not_projected(self):
        with closing(sqlite3.connect(self.store.path)) as conn:
            conn.execute(
                "UPDATE standalone_accounting SET digest=?",
                ("0" * 64,)
            )
            conn.commit()
        with self.assertRaises(Exception) as observed:
            self.query()
        self.assertIn("AccountingIntegrityError", type(observed.exception).__name__)

    def test_no_default_path_or_untrusted_connector_objects(self):
        for kwargs in (
            {"registry": object()},
            {"identity": object()},
            {"store": object()},
            {"host_scope": {}},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(PermissionError):
                TarazCatalogRead(
                    registry=kwargs.get("registry", self.registry),
                    identity=kwargs.get("identity", self.identity),
                    store=kwargs.get("store", self.store),
                    host_scope=kwargs.get("host_scope", self.policy),
                )


if __name__ == "__main__":
    unittest.main()
