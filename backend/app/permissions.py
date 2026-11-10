"""Centralized, fail-closed document ACL checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import Document, DocumentChunk

PERMISSION_TIERS = frozenset({"public", "team", "department", "restricted"})


@dataclass(frozen=True)
class PermissionContext:
    user_id: str | None = None
    team: str | None = None
    department: str | None = None
    roles: frozenset[str] = frozenset()
    teams: frozenset[str] = frozenset()
    departments: frozenset[str] = frozenset()


def validate_acl_metadata(
    tier: str | None,
    team: str | None = None,
    department: str | None = None,
    restricted_user_ids: list[str] | None = None,
) -> dict:
    """Normalize and validate ACL metadata before a document is persisted."""

    normalized_tier = _valid_text(tier)
    if normalized_tier:
        normalized_tier = normalized_tier.lower()
    if normalized_tier not in PERMISSION_TIERS:
        raise ValueError("A valid permission tier is required.")

    normalized_team = _valid_text(team)
    normalized_department = _valid_text(department)
    normalized_users = (
        [item.strip() for item in restricted_user_ids if isinstance(item, str) and item.strip()]
        if restricted_user_ids is not None
        else None
    )
    if normalized_tier == "team" and not normalized_team:
        raise ValueError("Team permission requires a team.")
    if normalized_tier == "department" and not normalized_department:
        raise ValueError("Department permission requires a department.")
    if normalized_tier == "restricted" and not normalized_users:
        raise ValueError("Restricted permission requires at least one user ID.")

    return {
        "permission_tier": normalized_tier,
        "permission_team": normalized_team,
        "permission_department": normalized_department,
        "restricted_user_ids": normalized_users,
    }


def _valid_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def can_access_document(document: Document, context: PermissionContext) -> bool:
    """Return whether context can access document; malformed ACLs are denied."""

    tier = _valid_text(getattr(document, "permission_tier", None))
    if tier not in PERMISSION_TIERS:
        return False
    # Development identity is explicit, but it is not authentication. Even
    # public documents require a non-empty identity so missing identity fails
    # closed rather than becoming an anonymous read path.
    if not _valid_text(context.user_id):
        return False

    if tier == "public":
        return True
    if tier == "team":
        allowed_teams = _acl_values(
            getattr(document, "permission_teams", None),
            getattr(document, "permission_team", None),
        )
        context_teams = _context_values(context.teams, context.team)
        return bool(allowed_teams.intersection(context_teams))
    if tier == "department":
        allowed_departments = _acl_values(
            getattr(document, "permission_departments", None),
            getattr(document, "permission_department", None),
        )
        context_departments = _context_values(context.departments, context.department)
        return bool(allowed_departments.intersection(context_departments))
    if tier == "restricted":
        allowed_users = getattr(document, "restricted_user_ids", None)
        if not isinstance(allowed_users, list) or not all(
            isinstance(item, str) and item.strip() for item in allowed_users
        ):
            return False
        return bool(
            context.user_id
            and context.user_id in {item.strip() for item in allowed_users}
        )
    return False


def _context_values(values: frozenset[str] | set[str], fallback: str | None) -> set[str]:
    result = {_normalise_acl_value(item) for item in values if _valid_text(item)}
    if _valid_text(fallback):
        result.add(_normalise_acl_value(fallback))
    return result


def _acl_values(values: Any, fallback: str | None) -> set[str]:
    if isinstance(values, list):
        result = {
            _normalise_acl_value(item)
            for item in values
            if isinstance(item, str) and item.strip()
        }
        if result:
            return result
    if _valid_text(fallback):
        return {_normalise_acl_value(fallback)}
    return set()


def _normalise_acl_value(value: str) -> str:
    # ACL matching is intentionally exact after whitespace normalization.
    return value.strip()


def can_access_chunk(
    chunk: DocumentChunk,
    document: Document,
    context: PermissionContext,
) -> bool:
    """Check both the document ACL and the chunk's ACL snapshot."""

    chunk_tier = _valid_text(getattr(chunk, "permission_tier", None))
    document_tier = _valid_text(getattr(document, "permission_tier", None))
    return bool(
        chunk_tier
        and document_tier
        and chunk_tier == document_tier
        and can_access_document(document, context)
    )


def authorized_chunk_ids(
    db,
    context: PermissionContext,
    chunk_ids: list[int] | None = None,
) -> set[int]:
    """Resolve authorized chunk IDs for diagnostics and downstream safeguards."""

    from app.models import DocumentChunk

    query = db.query(
        DocumentChunk.id,
        DocumentChunk.permission_tier,
        Document,
    ).join(
        Document, Document.id == DocumentChunk.document_id
    )
    if chunk_ids is not None:
        if not chunk_ids:
            return set()
        query = query.filter(DocumentChunk.id.in_(chunk_ids))
    return {
        chunk_id
        for chunk_id, chunk_tier, document in query.all()
        if _valid_text(chunk_tier)
        and _valid_text(getattr(document, "permission_tier", None)) == _valid_text(chunk_tier)
        and can_access_document(document, context)
    }
