"""Account authentication and server-managed session helpers.

This module intentionally does not change document ACL behavior yet. Stage 3
will replace the development identity dependency with the trusted user context
created here.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Role, User, UserRole, UserSession

PASSWORD_HASHER = PasswordHasher(
    type=Type.ID,
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)
SESSION_COOKIE = "meridian_session"
CSRF_COOKIE = "meridian_csrf"
try:
    _session_ttl_hours = max(1, int(os.getenv("AUTH_SESSION_TTL_HOURS", "8")))
except ValueError:
    _session_ttl_hours = 8
SESSION_TTL = timedelta(hours=_session_ttl_hours)
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = timedelta(minutes=15)
_attempt_lock = threading.Lock()
_failed_attempts: dict[str, list[datetime]] = {}


def _auth_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@dataclass(frozen=True)
class AuthenticatedUser:
    user: User
    roles: frozenset[str]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain an uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain a lowercase letter.")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain a number.")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError("Password must contain a special character.")


def hash_password(password: str) -> str:
    validate_password(password)
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def next_user_id(db: Session) -> str:
    """Return the next USR-##### identifier without touching existing users."""

    highest = 0
    for (user_id,) in db.query(User.id).all():
        match = re.fullmatch(r"USR-(\d+)", user_id or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"USR-{highest + 1:05d}"


def _login_keys(request: Request, identifier: str) -> tuple[str, str]:
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}", f"account:{identifier.casefold().strip()}"


def login_allowed(request: Request, identifier: str) -> bool:
    cutoff = utc_now() - LOGIN_WINDOW
    with _attempt_lock:
        allowed = True
        for key in _login_keys(request, identifier):
            attempts = [item for item in _failed_attempts.get(key, []) if item >= cutoff]
            _failed_attempts[key] = attempts
            allowed = allowed and len(attempts) < MAX_LOGIN_ATTEMPTS
        return allowed


def record_login_failure(request: Request, identifier: str) -> None:
    with _attempt_lock:
        now = utc_now()
        for key in _login_keys(request, identifier):
            _failed_attempts.setdefault(key, []).append(now)


def clear_login_failures(request: Request, identifier: str) -> None:
    with _attempt_lock:
        for key in _login_keys(request, identifier):
            _failed_attempts.pop(key, None)


def validate_origin(request: Request) -> None:
    """Reject browser requests from origins not explicitly trusted."""

    origin = request.headers.get("origin")
    if not origin:
        return
    configured = os.getenv(
        "AUTH_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    allowed = {item.strip().rstrip("/") for item in configured.split(",") if item.strip()}
    if origin.rstrip("/") not in allowed:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User) -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            id=secrets.token_hex(24),
            user_id=user.id,
            token_hash=_token_hash(raw_token),
            expires_at=utc_now() + SESSION_TTL,
        )
    )
    return raw_token, csrf_token


def revoke_sessions(db: Session, user_id: str) -> None:
    now = utc_now()
    db.query(UserSession).filter(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    ).update({UserSession.revoked_at: now}, synchronize_session=False)


def revoke_session(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    db.query(UserSession).filter(
        UserSession.token_hash == _token_hash(raw_token),
        UserSession.revoked_at.is_(None),
    ).update({UserSession.revoked_at: utc_now()}, synchronize_session=False)


def set_auth_cookies(response, session_token: str, csrf_token: str) -> None:
    secure = os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() == "true"
    samesite = os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    if samesite not in {"lax", "strict", "none"}:
        samesite = "lax"
    if samesite == "none" and not secure:
        raise RuntimeError("AUTH_COOKIE_SAMESITE=none requires AUTH_COOKIE_SECURE=true.")
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite=samesite,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )


def clear_auth_cookies(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _load_session_user(db: Session, raw_token: str | None) -> User | None:
    if not raw_token:
        return None
    session = db.query(UserSession).filter(UserSession.token_hash == _token_hash(raw_token)).first()
    if not session or session.revoked_at is not None or session.expires_at <= utc_now():
        return None
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user or not user.is_active:
        return None
    return user


def get_session_user(
    db: Session = Depends(_auth_db),
    meridian_session: str | None = Cookie(default=None),
) -> User:
    user = _load_session_user(db, meridian_session)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def get_current_user(
    db: Session = Depends(_auth_db),
    meridian_session: str | None = Cookie(default=None),
) -> User:
    user = get_session_user(db, meridian_session)
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Password change required before continuing.")
    return user


def require_csrf(
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")


def require_request_security(
    request: Request,
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    validate_origin(request)
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")


def user_roles(db: Session, user_id: str) -> frozenset[str]:
    rows = (
        db.query(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id)
        .all()
    )
    return frozenset(name for (name,) in rows)
