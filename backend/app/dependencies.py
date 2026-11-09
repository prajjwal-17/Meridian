from fastapi import Header

from app.database import SessionLocal
from app.permissions import PermissionContext


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def get_permission_context(
    x_meridian_user: str | None = Header(default=None),
    x_meridian_team: str | None = Header(default=None),
    x_meridian_department: str | None = Header(default=None),
) -> PermissionContext:
    """Build explicit test-stage identity context from request headers.

    These headers are not authentication. A real auth layer must validate and
    populate this context before exposing protected retrieval in production.
    """

    clean = lambda value: value.strip() if value and value.strip() else None
    user_id = clean(x_meridian_user)
    if not user_id:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=401,
            detail="X-Meridian-User is required for development ACL context.",
        )
    return PermissionContext(
        user_id=user_id,
        team=clean(x_meridian_team),
        department=clean(x_meridian_department),
    )
