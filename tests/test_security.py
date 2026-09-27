
import os
import sqlite3
import tempfile
import unittest

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import storage


class TestBackendSecurity(unittest.TestCase):

    def setUp(self):
        # Each test uses a separate temporary database.
        # The application's real database is never modified.
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.test_db = (
            Path(self.temp_dir.name) / "test_alphaik.db"
        )

        db_patcher = patch.object(
            storage,
            "DB_PATH",
            self.test_db
        )
        db_patcher.start()
        self.addCleanup(db_patcher.stop)

        self.credentials = {
            "ALPHAIK_ADMIN_USER": "test_admin",
            "ALPHAIK_ADMIN_PASSWORD": "TestPassword_987!"
        }

    def initialize_database(self):
        with patch.dict(
            os.environ,
            self.credentials,
            clear=True
        ):
            storage.init_db()

    # ========================================================
    # Existing authentication tests
    # ========================================================

    def test_startup_without_admin_credentials(self):
        """Startup must fail without administrator credentials."""

        with patch.dict(
            os.environ,
            {},
            clear=True
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Administrator credentials must be configured"
            ):
                storage.init_db()

    def test_startup_without_admin_password(self):
        """Startup must fail when the password is missing."""

        with patch.dict(
            os.environ,
            {"ALPHAIK_ADMIN_USER": "test_admin"},
            clear=True
        ):
            with self.assertRaises(RuntimeError):
                storage.init_db()

    def test_admin_login_with_valid_credentials(self):
        """Valid administrator credentials must work."""

        self.initialize_database()

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

        self.initialize_database()

        token = storage.login(
            "test_admin",
            "IncorrectPassword"
        )

        self.assertIsNone(token)

    def test_invalid_session_token(self):
        """An unknown token must not grant access."""

        self.initialize_database()

        user = storage.user_for_token(
            "invalid_session_token"
        )

        self.assertIsNone(user)

    # ========================================================
    # New session expiration tests
    # ========================================================

    def test_new_session_expires_after_eight_hours(self):
        """A new session must have an eight-hour lifetime."""

        self.initialize_database()

        token = storage.login(
            "test_admin",
            "TestPassword_987!"
        )

        self.assertIsNotNone(token)

        with sqlite3.connect(self.test_db) as con:
            row = con.execute(
                """
                SELECT created_at, expires_at
                FROM sessions
                WHERE token = ?
                """,
                (token,)
            ).fetchone()

        self.assertIsNotNone(row)

        created_at = datetime.fromisoformat(row[0])
        expires_at = datetime.fromisoformat(row[1])

        self.assertEqual(
            expires_at - created_at,
            timedelta(hours=8)
        )

        self.assertIsNotNone(
            storage.user_for_token(token)
        )

    def test_expired_session_is_rejected(self):
        """An expired token must not grant access."""

        self.initialize_database()

        token = storage.login(
            "test_admin",
            "TestPassword_987!"
        )

        self.assertIsNotNone(token)

        expired_at = (
            datetime.now(timezone.utc)
            - timedelta(minutes=1)
        ).isoformat()

        with sqlite3.connect(self.test_db) as con:
            con.execute(
                """
                UPDATE sessions
                SET expires_at = ?
                WHERE token = ?
                """,
                (expired_at, token)
            )

        user = storage.user_for_token(token)

        self.assertIsNone(user)

    # ========================================================
    # New logout test
    # ========================================================

    def test_logout_revokes_session(self):
        """Logout must immediately invalidate the token."""

        self.initialize_database()

        token = storage.login(
            "test_admin",
            "TestPassword_987!"
        )

        self.assertIsNotNone(token)

        self.assertIsNotNone(
            storage.user_for_token(token)
        )

        result = storage.logout(token)

        self.assertTrue(result)

        self.assertIsNone(
            storage.user_for_token(token)
        )

        # Repeating logout must not restore access.
        self.assertFalse(
            storage.logout(token)
        )

    # ========================================================
    # New database migration test
    # ========================================================

    def test_legacy_sessions_are_revoked(self):
        """
        Migrating an old database must preserve users
        and invalidate sessions without expiration dates.
        """

        old_password_hash = storage._hash_password(
            "TestPassword_987!"
        )

        with sqlite3.connect(self.test_db) as con:

            con.executescript(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL
                        REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL
                );
                """
            )

            con.execute(
                """
                INSERT INTO users (
                    username,
                    password_hash,
                    created_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    "test_admin",
                    old_password_hash,
                    datetime.now(timezone.utc).isoformat()
                )
            )

            con.execute(
                """
                INSERT INTO sessions (
                    token,
                    user_id,
                    created_at
                )
                VALUES (
                    ?,
                    1,
                    ?
                )
                """,
                (
                    "old_session_token",
                    datetime.now(timezone.utc).isoformat()
                )
            )

        self.initialize_database()

        with sqlite3.connect(self.test_db) as con:

            columns = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info(sessions)"
                )
            }

            user_count = con.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]

            old_session_count = con.execute(
                """
                SELECT COUNT(*)
                FROM sessions
                WHERE token = ?
                """,
                ("old_session_token",)
            ).fetchone()[0]

        self.assertIn(
            "expires_at",
            columns
        )

        self.assertEqual(
            user_count,
            1
        )

        self.assertEqual(
            old_session_count,
            0
        )

        self.assertIsNone(
            storage.user_for_token("old_session_token")
        )


if __name__ == "__main__":
    unittest.main()
