"""Shared helpers for live tests against a running Meridian API.

Live tests sign in with the development demo accounts (backend/test_users.json,
created by scripts/seed_demo_users.py) and compare API output with an
independent ACL oracle computed directly from the database.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

BASE_URL = os.getenv("MERIDIAN_API_URL", "http://127.0.0.1:8000")
ORIGIN = os.getenv("MERIDIAN_TEST_ORIGIN", "http://localhost:5173")
MANIFEST = BACKEND / "test_users.json"


class LiveSkip(Exception):
    """Raised when the live environment is not available."""


def demo_accounts() -> list[dict]:
    if not MANIFEST.exists():
        raise LiveSkip(f"{MANIFEST.name} not found; run scripts/seed_demo_users.py first")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["accounts"]


def login(account: dict) -> requests.Session:
    session = requests.Session()
    try:
        response = session.post(
            f"{BASE_URL}/auth/login",
            json={"identifier": account["email"], "password": account["password"]},
            headers={"Origin": ORIGIN},
            timeout=30,
        )
    except requests.ConnectionError as exc:
        raise LiveSkip(f"Meridian API is not running at {BASE_URL}") from exc
    if response.status_code != 200:
        raise AssertionError(f"login failed for {account['email']}: HTTP {response.status_code} {response.text[:200]}")
    session.headers.update({"Origin": ORIGIN, "X-CSRF-Token": session.cookies.get("meridian_csrf", "")})
    return session


def user_id_for(session: requests.Session) -> str:
    return session.get(f"{BASE_URL}/auth/me", timeout=30).json()["user_id"]


def authorized_document_ids(user_id: str) -> set[int]:
    """ACL oracle: documents this user may read, straight from the database."""

    from app.database import SessionLocal
    from app.dependencies import get_authenticated_permission_context
    from app.models import Document, User
    from app.permissions import can_access_document

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        context = get_authenticated_permission_context(db, user)
        return {doc.id for doc in db.query(Document).all() if can_access_document(doc, context)}
    finally:
        db.close()


def run_live(main) -> int:
    try:
        return main()
    except LiveSkip as exc:
        print(f"SKIP: {exc}")
        return 0
