"""Focused RBAC/ACL tests using an isolated in-memory database."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.dependencies import get_authenticated_permission_context
from app.models import Department, Document, Role, Team, User, UserDepartment, UserRole, UserTeam
from app.permissions import PermissionContext, can_access_document


class RbacTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def setUp(self):
        self.db = self.Session()
        suffix = self._testMethodName
        self.user = User(id=f"USR-{len(suffix):05d}", name="Alice", email=f"{suffix}@example.com", password_hash="hash", is_active=True, must_change_password=False)
        self.department = Department(name=f"Engineering-{suffix}", is_active=True)
        self.team = Team(name=f"Backend-{suffix}", department_id=1, is_active=True)
        self.db.add_all([self.user, self.department])
        self.db.flush()
        self.team.department_id = self.department.id
        self.db.add(self.team)
        self.db.flush()
        self.db.add(UserTeam(user_id=self.user.id, team_id=self.team.id))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_team_membership_grants_parent_department_context(self):
        context = get_authenticated_permission_context(self.db, self.user)
        self.assertEqual(context.teams, frozenset({self.team.name}))
        self.assertEqual(context.departments, frozenset({self.department.name}))

    def test_explicit_department_and_multiple_acl_values(self):
        document = Document(
            filename="multi.pdf", object_key="multi.pdf", content_type="application/pdf",
            file_size=1, checksum="m" * 64, permission_tier="department",
            permission_departments=["Engineering", "Finance"],
        )
        self.assertTrue(can_access_document(document, PermissionContext(user_id=self.user.id, departments=frozenset({"Engineering"}))))
        self.assertFalse(can_access_document(document, PermissionContext(user_id=self.user.id, departments=frozenset({"engineering"}))))

    def test_public_does_not_require_admin_role(self):
        document = Document(
            filename="public.pdf", object_key="public.pdf", content_type="application/pdf",
            file_size=1, checksum="p" * 64, permission_tier="public",
        )
        self.assertTrue(can_access_document(document, PermissionContext(user_id=self.user.id)))
        self.assertFalse(can_access_document(document, PermissionContext()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
