"""Authenticated organization and account administration endpoints."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password, next_user_id, revoke_sessions, user_roles
from app.database import SessionLocal
from app.dependencies import get_db, require_admin, require_super_admin
from app.models import (
    AuditLog,
    Department,
    Role,
    Team,
    User,
    UserDepartment,
    UserRole,
    UserSession,
    UserTeam,
)

router = APIRouter(prefix="/admin", tags=["admin"])
ROLE_NAMES = {"MEMBER", "ADMIN", "SUPER_ADMIN"}


class UserCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=320)
    roles: list[str] = ["MEMBER"]
    department_ids: list[int] = []
    team_ids: list[int] = []


class UserPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    is_active: bool | None = None


class RoleAssignmentRequest(BaseModel):
    roles: list[str]


class MembershipRequest(BaseModel):
    department_ids: list[int] = []
    team_ids: list[int] = []


class DepartmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_active: bool = True


class DepartmentPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class TeamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    department_id: int
    is_active: bool = True


class TeamPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    department_id: int | None = None
    is_active: bool | None = None


def _role(db: Session, name: str) -> Role:
    normalized = name.strip().upper()
    if normalized not in ROLE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unsupported role: {name}")
    result = db.query(Role).filter(func.upper(Role.name) == normalized).first()
    if result is None:
        result = Role(name=normalized)
        db.add(result)
        db.flush()
    return result


def _role_set(roles: list[str]) -> set[str]:
    normalized = {role.strip().upper() for role in roles if role and role.strip()}
    if not normalized or not normalized.issubset(ROLE_NAMES):
        raise HTTPException(status_code=400, detail="Roles must be MEMBER, ADMIN, or SUPER_ADMIN.")
    return normalized


def _is_super(db: Session, user_id: str) -> bool:
    return "SUPER_ADMIN" in {role.upper() for role in user_roles(db, user_id)}


def _target_is_non_member_admin(db: Session, user_id: str) -> bool:
    return bool({role.upper() for role in user_roles(db, user_id)} - {"MEMBER"})


def _audit(db: Session, actor: User, action: str, target_type: str, target_id: str, details: dict | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor.id, action=action, target_type=target_type, target_id=target_id, details=details))


def _temporary_password() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(20))
        try:
            hash_password(candidate)
            return candidate
        except ValueError:
            continue


def _user_payload(db: Session, user: User) -> dict:
    departments = (
        db.query(Department.id, Department.name)
        .join(UserDepartment, UserDepartment.department_id == Department.id)
        .filter(UserDepartment.user_id == user.id)
        .all()
    )
    teams = (
        db.query(Team.id, Team.name, Department.id, Department.name)
        .join(UserTeam, UserTeam.team_id == Team.id)
        .join(Department, Department.id == Team.department_id)
        .filter(UserTeam.user_id == user.id)
        .all()
    )
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "roles": sorted(user_roles(db, user.id)),
        "departments": [{"id": row[0], "name": row[1]} for row in departments],
        "teams": [{"id": row[0], "name": row[1], "department_id": row[2], "department": row[3]} for row in teams],
    }


@router.get("/users")
def list_users(
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _actor: User = Depends(require_admin),
):
    query = db.query(User).order_by(User.created_at.desc())
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter((User.id.ilike(term)) | (User.name.ilike(term)) | (User.email.ilike(term)))
    users = query.all()
    return {"total": len(users), "users": [_user_payload(db, user) for user in users]}


@router.post("/users")
def create_user(
    request: UserCreateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    roles = _role_set(request.roles)
    actor_is_super = _is_super(db, actor.id)
    if not actor_is_super and roles != {"MEMBER"}:
        raise HTTPException(status_code=403, detail="Only Super Admin can create administrators.")
    email = request.email.strip().casefold()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="Email is already in use.")
    db.execute(text("SELECT pg_advisory_xact_lock(48193018)"))
    temporary_password = _temporary_password()
    user = User(
        id=next_user_id(db),
        name=request.name.strip(),
        email=email,
        password_hash=hash_password(temporary_password),
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    for role_name in roles:
        db.add(UserRole(user_id=user.id, role_id=_role(db, role_name).id))
    _set_memberships(db, user, request.department_ids, request.team_ids)
    _audit(db, actor, "user.created", "user", user.id, {"roles": sorted(roles)})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="User could not be created due to a uniqueness conflict.") from exc
    return {"user": _user_payload(db, user), "temporary_password": temporary_password}


@router.get("/users/{user_id}")
def get_user(user_id: str, db: Session = Depends(get_db), _actor: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return _user_payload(db, user)


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    request: UserPatchRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == actor.id and request.is_active is False:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
    actor_is_super = _is_super(db, actor.id)
    if _target_is_non_member_admin(db, user.id) and not actor_is_super:
        raise HTTPException(status_code=403, detail="Only Super Admin can modify administrator accounts.")
    if request.name is not None:
        user.name = request.name.strip()
    if request.email is not None:
        email = request.email.strip().casefold()
        conflict = db.query(User).filter(func.lower(User.email) == email, User.id != user.id).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Email is already in use.")
        user.email = email
    if request.is_active is not None:
        user.is_active = request.is_active
        if not request.is_active:
            revoke_sessions(db, user.id)
    _audit(db, actor, "user.updated", "user", user.id, {"fields": request.model_dump(exclude_none=True)})
    db.commit()
    return _user_payload(db, user)


@router.put("/users/{user_id}/roles")
def assign_roles(
    user_id: str,
    request: RoleAssignmentRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    roles = _role_set(request.roles)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    actor_is_super = _is_super(db, actor.id)
    if user.id == actor.id:
        raise HTTPException(status_code=403, detail="Administrators cannot change their own roles.")
    if not actor_is_super and (roles != {"MEMBER"} or _is_super(db, user.id)):
        raise HTTPException(status_code=403, detail="Only Super Admin can manage administrator roles.")
    db.query(UserRole).filter(UserRole.user_id == user.id).delete(synchronize_session=False)
    for role_name in roles:
        db.add(UserRole(user_id=user.id, role_id=_role(db, role_name).id))
    _audit(db, actor, "user.roles_changed", "user", user.id, {"roles": sorted(roles)})
    db.commit()
    return _user_payload(db, user)


def _set_memberships(db: Session, user: User, department_ids: list[int], team_ids: list[int]) -> None:
    departments = {row[0] for row in db.query(Department.id).filter(Department.id.in_(department_ids or [-1]), Department.is_active.is_(True)).all()}
    if len(departments) != len(set(department_ids)):
        raise HTTPException(status_code=400, detail="One or more departments are invalid or archived.")
    teams = db.query(Team).filter(Team.id.in_(team_ids or [-1]), Team.is_active.is_(True)).all()
    if len(teams) != len(set(team_ids)):
        raise HTTPException(status_code=400, detail="One or more teams are invalid or archived.")
    db.query(UserDepartment).filter(UserDepartment.user_id == user.id).delete(synchronize_session=False)
    db.query(UserTeam).filter(UserTeam.user_id == user.id).delete(synchronize_session=False)
    for department_id in departments:
        db.add(UserDepartment(user_id=user.id, department_id=department_id))
    for team in teams:
        db.add(UserTeam(user_id=user.id, team_id=team.id))


@router.put("/users/{user_id}/memberships")
def assign_memberships(
    user_id: str,
    request: MembershipRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if _target_is_non_member_admin(db, user.id) and not _is_super(db, actor.id):
        raise HTTPException(status_code=403, detail="Only Super Admin can modify administrator memberships.")
    _set_memberships(db, user, request.department_ids, request.team_ids)
    _audit(db, actor, "user.memberships_changed", "user", user.id, {"department_ids": request.department_ids, "team_ids": request.team_ids})
    db.commit()
    return _user_payload(db, user)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == actor.id or (_target_is_non_member_admin(db, user.id) and not _is_super(db, actor.id)):
        raise HTTPException(status_code=403, detail="This account cannot be reset by the current administrator.")
    temporary_password = _temporary_password()
    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    user.password_changed_at = None
    revoke_sessions(db, user.id)
    _audit(db, actor, "user.password_reset", "user", user.id)
    db.commit()
    return {"user_id": user.id, "temporary_password": temporary_password}


@router.get("/departments")
def list_departments(db: Session = Depends(get_db), _actor: User = Depends(require_admin)):
    departments = db.query(Department).order_by(Department.name).all()
    return {"total": len(departments), "departments": [{"id": d.id, "name": d.name, "is_active": d.is_active} for d in departments]}


@router.post("/departments")
def create_department(request: DepartmentRequest, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    department = Department(name=request.name.strip(), is_active=request.is_active)
    db.add(department)
    _audit(db, actor, "department.created", "department", request.name.strip())
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Department already exists.") from exc
    db.refresh(department)
    return {"id": department.id, "name": department.name, "is_active": department.is_active}


@router.patch("/departments/{department_id}")
def update_department(department_id: int, request: DepartmentPatchRequest, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    department = db.query(Department).filter(Department.id == department_id).first()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found.")
    if request.name is not None:
        department.name = request.name.strip()
    if request.is_active is not None:
        department.is_active = request.is_active
    _audit(db, actor, "department.updated", "department", str(department.id), request.model_dump(exclude_none=True))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Department name already exists.") from exc
    return {"id": department.id, "name": department.name, "is_active": department.is_active}


@router.get("/teams")
def list_teams(db: Session = Depends(get_db), _actor: User = Depends(require_admin)):
    rows = db.query(Team, Department.name).join(Department, Department.id == Team.department_id).order_by(Team.name).all()
    return {"total": len(rows), "teams": [{"id": t.id, "name": t.name, "department_id": t.department_id, "department": name, "is_active": t.is_active} for t, name in rows]}


@router.post("/teams")
def create_team(request: TeamRequest, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if not db.query(Department).filter(Department.id == request.department_id, Department.is_active.is_(True)).first():
        raise HTTPException(status_code=400, detail="Active department is required.")
    team = Team(name=request.name.strip(), department_id=request.department_id, is_active=request.is_active)
    db.add(team)
    _audit(db, actor, "team.created", "team", request.name.strip(), {"department_id": request.department_id})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Team already exists in this department.") from exc
    db.refresh(team)
    return {"id": team.id, "name": team.name, "department_id": team.department_id, "is_active": team.is_active}


@router.patch("/teams/{team_id}")
def update_team(team_id: int, request: TeamPatchRequest, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")
    if request.department_id is not None:
        if not db.query(Department).filter(Department.id == request.department_id, Department.is_active.is_(True)).first():
            raise HTTPException(status_code=400, detail="Active department is required.")
        team.department_id = request.department_id
    if request.name is not None:
        team.name = request.name.strip()
    if request.is_active is not None:
        team.is_active = request.is_active
    _audit(db, actor, "team.updated", "team", str(team.id), request.model_dump(exclude_none=True))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Team already exists in this department.") from exc
    return {"id": team.id, "name": team.name, "department_id": team.department_id, "is_active": team.is_active}


@router.get("/audit-logs")
def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _actor: User = Depends(require_admin),
):
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    return {"total": len(rows), "logs": [{"id": row.id, "actor_user_id": row.actor_user_id, "action": row.action, "target_type": row.target_type, "target_id": row.target_id, "details": row.details, "created_at": row.created_at} for row in rows]}
