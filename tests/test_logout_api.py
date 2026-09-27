
import os
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import main, storage


class TestLogoutAPI(unittest.TestCase):

    def setUp(self):
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

        credentials = {
            "ALPHAIK_ADMIN_USER": "test_admin",
            "ALPHAIK_ADMIN_PASSWORD": "TestPassword_987!"
        }

        with patch.dict(os.environ, credentials, clear=True):
            storage.init_db()

    def login(self):
        return main.api_login(
            main.LoginIn(
                username="test_admin",
                password="TestPassword_987!"
            )
        )

    def test_login_returns_session_lifetime(self):
        response = self.login()

        self.assertTrue(response["token"])
        self.assertEqual(
            response["expires_in"],
            8 * 60 * 60
        )

    def test_logout_invalidates_token(self):
        response = self.login()
        token = response["token"]
        authorization = f"Bearer {token}"

        self.assertIsNotNone(
            main.auth(authorization)
        )

        result = main.api_logout(
            authorization=authorization
        )

        self.assertEqual(result["status"], "ok")

        with self.assertRaises(HTTPException) as error:
            main.auth(authorization)

        self.assertEqual(
            error.exception.status_code,
            401
        )

    def test_logout_requires_authentication(self):
        with self.assertRaises(HTTPException) as error:
            main.api_logout(authorization=None)

        self.assertEqual(
            error.exception.status_code,
            401
        )

    def test_logout_rejects_invalid_token(self):
        with self.assertRaises(HTTPException) as error:
            main.api_logout(
                authorization="Bearer invalid_token"
            )

        self.assertEqual(
            error.exception.status_code,
            401
        )

    def test_logout_rejects_invalid_header(self):
        response = self.login()

        with self.assertRaises(HTTPException) as error:
            main.api_logout(
                authorization=f"Basic {response['token']}"
            )

        self.assertEqual(
            error.exception.status_code,
            401
        )

    def test_logout_does_not_revoke_other_sessions(self):
        first_token = self.login()["token"]
        second_token = self.login()["token"]

        self.assertNotEqual(
            first_token,
            second_token
        )

        main.api_logout(
            authorization=f"Bearer {first_token}"
        )

        self.assertIsNone(
            storage.user_for_token(first_token)
        )

        self.assertIsNotNone(
            storage.user_for_token(second_token)
        )


if __name__ == "__main__":
    unittest.main()
