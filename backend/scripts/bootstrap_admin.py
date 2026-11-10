"""Create the initial Meridian administrator once.

The generated temporary password is printed exactly once by this process and
is never written to the database or logs. Run this command from backend/ after
the additive auth migration.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from app.auth import hash_password, next_user_id
from app.database import Base, SessionLocal, engine
from app.models import Role, User, UserRole


def temporary_password() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(20))
        try:
            hash_password(value)
            return value
        except ValueError:
            continue


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first Meridian administrator")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Serialize bootstrap checks so two simultaneous invocations cannot
        # both observe an empty administrator set and create two admins.
        db.execute(text("SELECT pg_advisory_xact_lock(48193017)"))
        admin_role = db.query(Role).filter(Role.name.in_(["SUPER_ADMIN", "ADMIN", "admin"])).order_by(Role.name.desc()).first()
        if admin_role is None:
            admin_role = Role(name="SUPER_ADMIN")
            db.add(admin_role)
            db.flush()

        active_admin_exists = (
            db.query(User)
            .join(UserRole, UserRole.user_id == User.id)
            .filter(UserRole.role_id == admin_role.id, User.is_active.is_(True))
            .first()
        )
        if active_admin_exists:
            print("Bootstrap skipped: an active administrator already exists.")
            return 0

        name = args.name.strip()
        email = args.email.strip().casefold()
        if not name:
            print("Bootstrap failed: a non-empty name is required.", file=sys.stderr)
            return 2
        if not email or "@" not in email:
            print("Bootstrap failed: a valid email address is required.", file=sys.stderr)
            return 2
        if db.query(User).filter(User.email == email).first():
            print("Bootstrap failed: that email already belongs to an account.", file=sys.stderr)
            return 2

        password = temporary_password()
        user = User(
            id=next_user_id(db),
            name=args.name.strip(),
            email=email,
            password_hash=hash_password(password),
            is_active=True,
            must_change_password=True,
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=admin_role.id))
        db.commit()
        print(f"Administrator created: {user.id} ({user.email})")
        print("Temporary password (displayed once):")
        print(password)
        print("Change this password immediately at first login.")
        return 0
    except IntegrityError:
        db.rollback()
        print("Bootstrap failed: the account could not be created safely; no account was added.", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
