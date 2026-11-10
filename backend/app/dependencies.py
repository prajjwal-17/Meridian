from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.auth import get_current_user, user_roles
from app.models import Department, Team, UserDepartment, UserTeam, User
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
        raise HTTPException(
            status_code=401,
            detail="X-Meridian-User is required for development ACL context.",
        )
    return PermissionContext(
        user_id=user_id,
        team=clean(x_meridian_team),
        department=clean(x_meridian_department),
    )


def get_authenticated_permission_context(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PermissionContext:
    """Build trusted ACL context from the authenticated user's memberships."""

    team_rows = (
        db.query(Team.name, Department.name)
        .join(UserTeam, UserTeam.team_id == Team.id)
        .join(Department, Department.id == Team.department_id)
        .filter(UserTeam.user_id == user.id, Team.is_active.is_(True), Department.is_active.is_(True))
        .all()
    )
    explicit_departments = (
        db.query(Department.name)
        .join(UserDepartment, UserDepartment.department_id == Department.id)
        .filter(UserDepartment.user_id == user.id, Department.is_active.is_(True))
        .all()
    )
    teams = frozenset(name for name, _ in team_rows if name)
    departments = frozenset(
        {name for _, name in team_rows if name}
        | {name for (name,) in explicit_departments if name}
    )
    return PermissionContext(
        user_id=user.id,
        roles=user_roles(db, user.id),
        teams=teams,
        departments=departments,
    )


def require_admin(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    roles = user_roles(db, user.id)
    if not ({"ADMIN", "SUPER_ADMIN"} & {role.upper() for role in roles}):
        raise HTTPException(status_code=403, detail="Administrator role required.")
    return user


def require_super_admin(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    roles = user_roles(db, user.id)
    if "SUPER_ADMIN" not in {role.upper() for role in roles}:
        raise HTTPException(status_code=403, detail="Super administrator role required.")
    return user
