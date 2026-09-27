
import os
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from app import storage


class TestBackendSecurity(unittest.TestCase):

    def setUp(self):
        # Use a temporary database for each test.
        # The real Alphaik database must never be modified.
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        test_db = Path(self.temp_dir.name) / "test_alphaik.db"

        db_patcher = patch.object(
            storage,
            "DB_PATH",
            test_db
        )
        db_patcher.start()
        self.addCleanup(db_patcher.stop)

    def test_startup_without_admin_credentials(self):
        """Startup must fail when admin credentials are missing."""

        with patch.dict(os.environ, {}, clear=True):

            with self.assertRaisesRegex(
                RuntimeError,
                "Administrator credentials must be configured"
            ):
                storage.init_db()

    def test_startup_without_admin_password(self):
        """Startup must fail when only the username is set."""

        with patch.dict(
            os.environ,
            {"ALPHAIK_ADMIN_USER": "test_admin"},
            clear=True
        ):

            with self.assertRaises(RuntimeError):
                storage.init_db()

    def test_admin_login_with_valid_credentials(self):
        """The configured admin must be able to log in."""

        with patch.dict(
            os.environ,
            {
                "ALPHAIK_ADMIN_USER": "test_admin",
                "ALPHAIK_ADMIN_PASSWORD": "TestPassword_987!"
            },
            clear=True
        ):

            storage.init_db()

            token = storage.login(
                "test_admin",
                "TestPassword_987!"
            )

            self.assertIsNotNone(token)

            user = storage.user_for_token(token)

            self.assertIsNotNone(user)
            self.assertEqual(
                user["username"],
                "test_admin"
            )

    def test_admin_login_with_wrong_password(self):
        """An incorrect password must be rejected."""

        with patch.dict(
            os.environ,
            {
                "ALPHAIK_ADMIN_USER": "test_admin",
                "ALPHAIK_ADMIN_PASSWORD": "TestPassword_987!"
            },
            clear=True
        ):

            storage.init_db()

            token = storage.login(
                "test_admin",
                "IncorrectPassword"
            )

            self.assertIsNone(token)

    def test_invalid_session_token(self):
        """An unknown session token must not grant access."""

        with patch.dict(
            os.environ,
            {
                "ALPHAIK_ADMIN_USER": "test_admin",
                "ALPHAIK_ADMIN_PASSWORD": "TestPassword_987!"
            },
            clear=True
        ):

            storage.init_db()

            user = storage.user_for_token(
                "invalid_session_token"
            )

            self.assertIsNone(user)


if __name__ == "__main__":
    unittest.main()
