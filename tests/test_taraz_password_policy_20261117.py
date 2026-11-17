"""Credential hardening with legacy admin-recovery compatibility; synthetic only."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import unittest

from standalone_accounting_identity import (
    IdentityError, LocalCompanyIdentity, _ITERATIONS,
)


class PasswordPolicyTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="taraz-qa-password-")
        self.addCleanup(directory.cleanup)
        self.identity = LocalCompanyIdentity(Path(directory.name))

    def test_new_four_digit_pin_denied_without_creating_account(self):
        for candidate in ("1234", "123456789", "abcdefghj"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(IdentityError):
                    self.identity.add_user("admin", candidate, "admin")
        self.assertFalse(self.identity.initialized())

    def test_new_strong_password_can_login_and_weak_reset_is_rejected(self):
        self.identity.add_user("admin", "strong-qa-only-password", "admin")
        admin = self.identity.login("admin", "strong-qa-only-password")
        with self.assertRaises(IdentityError):
            self.identity.reset_password("admin", "1234", administrator=admin)
        self.assertEqual(self.identity.require_session(admin, "admin")["role"], "admin")
        self.identity.reset_password("admin", "new-strong-qa-password", administrator=admin)
        with self.assertRaises(IdentityError):
            self.identity.require_session(admin, "admin")
        renewed = self.identity.login("admin", "new-strong-qa-password")
        self.assertEqual(self.identity.require_session(renewed)["role"], "admin")

    def test_legacy_four_digit_administrator_not_locked_out_of_reset(self):
        # Emulate only a previously persisted password verifier in a temp book.
        legacy_password = "4321"
        salt = b"0" * 32
        record = {"role": "admin", "salt": salt.hex(),
                  "hash": hashlib.pbkdf2_hmac(
                      "sha256", legacy_password.encode(), salt,
                      _ITERATIONS).hex(),
                  "iterations": _ITERATIONS, "enabled": True}
        self.identity._save({"version": 1, "users": {"admin": record}})
        token = self.identity.login("admin", legacy_password)
        self.assertEqual(self.identity.require_session(token, "admin")["username"], "admin")
        self.identity.reset_password("admin", "rotated-strong-password", administrator=token)
        new_token = self.identity.login("admin", "rotated-strong-password")
        self.assertEqual(self.identity.require_session(new_token)["role"], "admin")
        with self.assertRaises(IdentityError):
            self.identity.login("admin", legacy_password)


if __name__ == "__main__":
    unittest.main()
