"""Non-destructive Stage 1 authentication checks.

These checks exercise password/session primitives and model constraints without
creating accounts or changing the live database.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.auth import (
    clear_login_failures,
    create_session,
    hash_password,
    login_allowed,
    next_user_id,
    require_csrf,
    record_login_failure,
    set_auth_cookies,
    validate_origin,
    validate_password,
    verify_password,
)
from app.models import AuditLog, Department, Role, Team, User, UserSession


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, user_ids=()):
        self.user_ids = [(item,) for item in user_ids]
        self.added = []

    def query(self, model):
        return FakeQuery(self.user_ids)

    def add(self, value):
        self.added.append(value)


def request_with_headers(headers: dict[str, str]) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw_headers, "client": ("192.0.2.10", 1234)})


class AuthTests(unittest.TestCase):
    def test_argon2id_password_hash_round_trip(self):
        password = "Secure!Passw0rd123"
        password_hash = hash_password(password)
        self.assertTrue(password_hash.startswith("$argon2id$"))
        self.assertTrue(verify_password(password_hash, password))
        self.assertFalse(verify_password(password_hash, "wrong-password"))

    def test_password_policy_rejects_weak_passwords(self):
        with self.assertRaises(ValueError):
            validate_password("short")
        validate_password("Longer!Password123")

    def test_user_ids_increment_without_replacing_existing_ids(self):
        db = FakeDB(["USR-00001", "legacy-user", "USR-00009"])
        self.assertEqual(next_user_id(db), "USR-00010")

    def test_session_creation_stores_only_hashable_token_material(self):
        from app.models import User

        db = FakeDB()
        token, csrf = create_session(db, User(id="USR-00001"))
        self.assertGreater(len(token), 30)
        self.assertGreater(len(csrf), 20)
        self.assertEqual(len(db.added), 1)
        self.assertNotEqual(db.added[0].token_hash, token)

    def test_csrf_requires_matching_double_submit_tokens(self):
        with self.assertRaises(HTTPException) as error:
            require_csrf("cookie", "different")
        self.assertEqual(error.exception.status_code, 403)
        self.assertIsNone(require_csrf("same", "same"))

    def test_login_throttle_covers_account_and_ip_without_permanent_lockout(self):
        request = request_with_headers({})
        for _ in range(5):
            record_login_failure(request, "USR-00001")
        self.assertFalse(login_allowed(request, "USR-00001"))
        self.assertFalse(login_allowed(request, "different-user"))
        clear_login_failures(request, "USR-00001")
        self.assertTrue(login_allowed(request, "different-user"))

    def test_origin_validation_rejects_untrusted_browser_origin(self):
        with self.assertRaises(HTTPException) as error:
            validate_origin(request_with_headers({"origin": "https://evil.example"}))
        self.assertEqual(error.exception.status_code, 403)
        validate_origin(request_with_headers({"origin": "http://localhost:5173"}))

    def test_production_cookie_configuration_is_http_only_and_secure(self):
        response = Response()
        with patch.dict(
            "os.environ",
            {"AUTH_COOKIE_SECURE": "true", "AUTH_COOKIE_SAMESITE": "strict"},
            clear=False,
        ):
            set_auth_cookies(response, "session-token", "csrf-token")
        headers = response.headers.getlist("set-cookie")
        session_cookie = next(item for item in headers if "meridian_session=" in item)
        csrf_cookie = next(item for item in headers if "meridian_csrf=" in item)
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("Secure", session_cookie)
        self.assertIn("samesite=strict", session_cookie.lower())
        self.assertNotIn("HttpOnly", csrf_cookie)
        self.assertIn("Secure", csrf_cookie)

    def test_auth_tables_have_expected_primary_entities(self):
        self.assertEqual(User.__tablename__, "users")
        self.assertEqual(Role.__tablename__, "roles")
        self.assertEqual(Department.__tablename__, "departments")
        self.assertEqual(Team.__tablename__, "teams")
        self.assertEqual(UserSession.__tablename__, "user_sessions")
        self.assertEqual(AuditLog.__tablename__, "audit_logs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
