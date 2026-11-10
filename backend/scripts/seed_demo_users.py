"""Seed fictional MEMBER accounts for local Meridian development.

The script is idempotent: existing users are skipped and their credentials are
never regenerated or overwritten.  It writes local-only credential manifests
for the development demo-account endpoint and the operator's reference.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, text
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin_api import _audit, _role, _set_memberships  # noqa: E402
from app.auth import hash_password, next_user_id, user_roles  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Department, Team, User, UserRole  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_OUTPUT = PROJECT_ROOT / "test_users.txt"
JSON_OUTPUT = PROJECT_ROOT / "test_users.json"

ORGANIZATION = {
    "Human Resources": ["People Operations", "Talent Acquisition"],
    "Engineering": ["Backend Platform", "Frontend Experience", "Data Engineering"],
    "Finance": ["Financial Planning", "Accounts Payable"],
    "IT and Security": ["Infrastructure", "Security Operations"],
    "Operations": ["Business Operations", "Customer Success"],
}

USERS = [
    ("Aisha Khan", "aisha.khan@meridian.example", ["Human Resources"], [("Human Resources", "People Operations")]),
    ("Mateo Silva", "mateo.silva@meridian.example", ["Human Resources", "Operations"], [("Human Resources", "Talent Acquisition"), ("Operations", "Customer Success")]),
    ("Priya Nair", "priya.nair@meridian.example", ["Engineering"], [("Engineering", "Backend Platform"), ("Engineering", "Data Engineering")]),
    ("Daniel Brooks", "daniel.brooks@meridian.example", ["Engineering", "IT and Security"], [("Engineering", "Frontend Experience"), ("IT and Security", "Infrastructure")]),
    ("Sofia Chen", "sofia.chen@meridian.example", ["Engineering"], [("Engineering", "Data Engineering")]),
    ("Omar Haddad", "omar.haddad@meridian.example", ["Finance"], [("Finance", "Financial Planning")]),
    ("Grace Wilson", "grace.wilson@meridian.example", ["Finance", "Operations"], [("Finance", "Accounts Payable"), ("Operations", "Business Operations")]),
    ("Noah Patel", "noah.patel@meridian.example", ["IT and Security"], [("IT and Security", "Security Operations"), ("IT and Security", "Infrastructure")]),
    ("Elena Rossi", "elena.rossi@meridian.example", ["IT and Security", "Engineering"], [("IT and Security", "Security Operations"), ("Engineering", "Backend Platform")]),
    ("Lucas Martin", "lucas.martin@meridian.example", ["Operations"], [("Operations", "Customer Success")]),
    ("Harper Lee", "harper.lee@meridian.example", ["Operations", "Human Resources"], [("Operations", "Business Operations"), ("Human Resources", "People Operations")]),
    ("Ethan Cole", "ethan.cole@meridian.example", ["Finance", "Engineering"], [("Finance", "Financial Planning"), ("Engineering", "Data Engineering")]),
]


def generate_password() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(24))
        try:
            hash_password(value)
            return value
        except ValueError:
            continue


def load_manifest() -> dict[str, dict]:
    if not JSON_OUTPUT.exists():
        return {}
    try:
        payload = json.loads(JSON_OUTPUT.read_text(encoding="utf-8"))
        return {item["email"].casefold(): item for item in payload.get("accounts", [])}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"Cannot read existing {JSON_OUTPUT.name}: {exc}") from exc


def save_manifests(accounts: list[dict]) -> None:
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "accounts": accounts}
    JSON_OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "Meridian fictional demo users",
        "Local development credentials. Do not commit this file.",
        "",
    ]
    for account in accounts:
        lines.extend(
            [
                f"User ID: {account['user_id']}",
                f"Name: {account['name']}",
                f"Email: {account['email']}",
                f"Password: {account['password']}",
                f"Platform role: {account['platform_role']}",
                f"Departments: {', '.join(account['departments'])}",
                f"Teams: {', '.join(account['teams'])}",
                "-" * 60,
            ]
        )
    TEXT_OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def find_admin(db: object) -> User:
    for user in db.query(User).filter(User.is_active.is_(True)).order_by(User.created_at).all():
        if {role.upper() for role in user_roles(db, user.id)} & {"ADMIN", "SUPER_ADMIN"}:
            return user
    raise RuntimeError("An active ADMIN or SUPER_ADMIN is required to seed demo users.")


def ensure_organization(db, actor: User) -> tuple[dict[str, Department], dict[tuple[str, str], Team]]:
    departments: dict[str, Department] = {}
    teams: dict[tuple[str, str], Team] = {}
    for department_name, team_names in ORGANIZATION.items():
        department = db.query(Department).filter(func.lower(Department.name) == department_name.casefold()).first()
        if department is None:
            department = Department(name=department_name, is_active=True)
            db.add(department)
            db.flush()
            _audit(db, actor, "department.created", "department", department_name, {"source": "demo_seed"})
        elif not department.is_active:
            raise RuntimeError(f"Required department is archived: {department_name}")
        departments[department_name] = department
        for team_name in team_names:
            team = (
                db.query(Team)
                .filter(Team.department_id == department.id, func.lower(Team.name) == team_name.casefold())
                .first()
            )
            if team is None:
                team = Team(name=team_name, department_id=department.id, is_active=True)
                db.add(team)
                db.flush()
                _audit(db, actor, "team.created", "team", str(team.id), {"department_id": department.id, "source": "demo_seed"})
            elif not team.is_active:
                raise RuntimeError(f"Required team is archived: {department_name} / {team_name}")
            teams[(department_name, team_name)] = team
    return departments, teams


def seed() -> dict[str, int]:
    db = SessionLocal()
    manifest = load_manifest()
    created: list[dict] = list(manifest.values())
    created_by_email = {item["email"].casefold(): item for item in created}
    counts = {"created": 0, "skipped": 0, "failed": 0}
    try:
        actor = find_admin(db)
        departments, teams = ensure_organization(db, actor)
        member_role = _role(db, "MEMBER")
        db.commit()
        for name, email, department_names, team_specs in USERS:
            normalized_email = email.casefold()
            existing = db.query(User).filter(func.lower(User.email) == normalized_email).first()
            if existing is not None:
                counts["skipped"] += 1
                continue
            password = generate_password()
            try:
                db.execute(text("SELECT pg_advisory_xact_lock(48193019)"))
                user = User(
                    id=next_user_id(db),
                    name=name,
                    email=normalized_email,
                    password_hash=hash_password(password),
                    is_active=True,
                    # Demo credentials are already operator-controlled. They
                    # still use the normal password policy and Argon2id hash.
                    must_change_password=False,
                    password_changed_at=datetime.now(timezone.utc),
                )
                db.add(user)
                db.flush()
                db.add(UserRole(user_id=user.id, role_id=member_role.id))
                _set_memberships(
                    db,
                    user,
                    [departments[item].id for item in department_names],
                    [teams[item].id for item in team_specs],
                )
                _audit(db, actor, "user.created", "user", user.id, {"roles": ["MEMBER"], "source": "demo_seed"})
                db.commit()
            except Exception:
                db.rollback()
                counts["failed"] += 1
                print(f"FAILED {email}", file=sys.stderr)
                continue
            account = {
                "user_id": user.id,
                "name": user.name,
                "email": user.email,
                "password": password,
                "platform_role": "MEMBER",
                "departments": department_names,
                "teams": [f"{department} / {team}" for department, team in team_specs],
            }
            created_by_email[normalized_email] = account
            counts["created"] += 1
        created = [created_by_email[email.casefold()] for _, email, _, _ in USERS if email.casefold() in created_by_email]
        save_manifests(created)
        return counts
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        counts = seed()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Demo user seed summary")
    for key in ("created", "skipped", "failed"):
        print(f"  {key}: {counts[key]}")
    print(f"  credentials text: {TEXT_OUTPUT}")
    print(f"  credentials manifest: {JSON_OUTPUT}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
