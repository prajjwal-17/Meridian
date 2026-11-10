"""Focused administrator authorization tests using an isolated database."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_api import _role, _role_set
from app.database import Base
from app.dependencies import require_admin, require_super_admin
from app.models import Role, User, UserRole


class AdminApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def test_role_validation_and_admin_boundaries(self):
        db = self.Session()
        member = User(id="USR-00001", name="Member", email="member@example.com", password_hash="x", is_active=True, must_change_password=False)
        admin = User(id="USR-00002", name="Admin", email="admin@example.com", password_hash="x", is_active=True, must_change_password=False)
        super_admin = User(id="USR-00003", name="Super", email="super@example.com", password_hash="x", is_active=True, must_change_password=False)
        db.add_all([member, admin, super_admin]); db.flush()
        db.add_all([UserRole(user_id=admin.id, role_id=_role(db, "ADMIN").id), UserRole(user_id=super_admin.id, role_id=_role(db, "SUPER_ADMIN").id)])
        db.commit()
        with self.assertRaises(HTTPException):
            require_admin(db, member)
        self.assertIs(require_admin(db, admin), admin)
        with self.assertRaises(HTTPException):
            require_super_admin(db, admin)
        self.assertIs(require_super_admin(db, super_admin), super_admin)
        self.assertEqual(_role_set(["member"]), {"MEMBER"})
        with self.assertRaises(HTTPException):
            _role_set(["OWNER"])
        db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
