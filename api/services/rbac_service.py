from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.rbac import (
    RbacAssignmentReadModel,
    RbacAssignmentWriteModel,
    RbacAssignmentsReadModel,
    RbacEffectivePermissionsModel,
)
from api.services.dashboard_access_service import (
    get_current_user_guild_access_flags,
    get_dashboard_member_role_ids,
    get_or_create_server,
)
from api.services.discord_guilds import fetch_guild_metadata, fetch_guild_roles
from api.services.rbac_catalog import (
    expand_assignment_permissions,
    get_all_permission_keys,
    validate_permission_keys,
    validate_preset,
)
from src.db.models import GlobalUser, ServerRbacAssignment, ServerRbacAuditEvent, utcnow_utc_tz

ADMINISTRATOR_PERMISSION_FLAG = 1 << 3
SUPPORTED_SUBJECT_TYPES = {"user", "role"}


def normalize_subject(subject_type: str, subject_id: str) -> tuple[str, str]:
    normalized_type = subject_type.strip().lower()
    normalized_id = str(subject_id).strip()
    if normalized_type not in SUPPORTED_SUBJECT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="RBAC subject type must be user or role",
        )
    if not normalized_id.isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="RBAC user and role subject IDs must be Discord numeric IDs",
        )
    return normalized_type, normalized_id


async def _ensure_global_user(session: AsyncSession, user_id: int) -> None:
    existing = await session.get(GlobalUser, user_id)
    if existing:
        return
    session.add(GlobalUser(discord_id=user_id, username=None))
    await session.flush()


def _assignment_snapshot(assignment: ServerRbacAssignment | None) -> dict | None:
    if assignment is None:
        return None
    return {
        "id": str(assignment.id),
        "server_id": str(assignment.server_id),
        "subject_type": assignment.subject_type,
        "subject_id": assignment.subject_id,
        "preset": assignment.preset,
        "permission_keys": list(assignment.permission_keys or []),
        "effective_permission_keys": expand_assignment_permissions(
            assignment.preset,
            list(assignment.permission_keys or []),
        ),
    }


def _to_assignment_read_model(assignment: ServerRbacAssignment) -> RbacAssignmentReadModel:
    return RbacAssignmentReadModel(
        id=assignment.id,
        server_id=str(assignment.server_id),
        subject_type=assignment.subject_type,
        subject_id=assignment.subject_id,
        preset=assignment.preset,
        permission_keys=list(assignment.permission_keys or []),
        effective_permission_keys=expand_assignment_permissions(
            assignment.preset,
            list(assignment.permission_keys or []),
        ),
        created_by_user_id=str(assignment.created_by_user_id),
        updated_by_user_id=str(assignment.updated_by_user_id),
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


async def _get_assignment(
    session: AsyncSession,
    server_id: int,
    subject_type: str,
    subject_id: str,
) -> ServerRbacAssignment | None:
    return (
        await session.exec(
            select(ServerRbacAssignment).where(
                ServerRbacAssignment.server_id == server_id,
                ServerRbacAssignment.subject_type == subject_type,
                ServerRbacAssignment.subject_id == subject_id,
            )
        )
    ).first()


async def list_rbac_assignments(session: AsyncSession, server_id: int) -> RbacAssignmentsReadModel:
    assignments = (
        await session.exec(
            select(ServerRbacAssignment)
            .where(ServerRbacAssignment.server_id == server_id)
            .order_by(
                ServerRbacAssignment.subject_type.asc(),
                ServerRbacAssignment.subject_id.asc(),
            )
        )
    ).all()
    return RbacAssignmentsReadModel(
        server_id=str(server_id),
        assignments=[_to_assignment_read_model(assignment) for assignment in assignments],
    )


async def get_rbac_assignment(
    session: AsyncSession,
    server_id: int,
    subject_type: str,
    subject_id: str,
) -> RbacAssignmentReadModel:
    normalized_type, normalized_id = normalize_subject(subject_type, subject_id)
    assignment = await _get_assignment(session, server_id, normalized_type, normalized_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RBAC assignment not found")
    return _to_assignment_read_model(assignment)


async def upsert_rbac_assignment(
    session: AsyncSession,
    server_id: int,
    subject_type: str,
    subject_id: str,
    body: RbacAssignmentWriteModel,
    actor_user_id: int,
) -> RbacAssignmentReadModel:
    normalized_type, normalized_id = normalize_subject(subject_type, subject_id)
    preset = validate_preset(body.preset)
    permission_keys = validate_permission_keys(body.permission_keys)
    if preset is None and not permission_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="RBAC assignment must include a preset or at least one permission key",
        )

    await get_or_create_server(session, server_id)
    await _ensure_global_user(session, actor_user_id)
    if normalized_type == "user":
        await _ensure_global_user(session, int(normalized_id))

    existing = await _get_assignment(session, server_id, normalized_type, normalized_id)
    before_json = _assignment_snapshot(existing)
    now = utcnow_utc_tz()

    if existing is None:
        existing = ServerRbacAssignment(
            server_id=server_id,
            subject_type=normalized_type,
            subject_id=normalized_id,
            preset=preset,
            permission_keys=permission_keys,
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(existing)
    else:
        existing.preset = preset
        existing.permission_keys = permission_keys
        existing.updated_by_user_id = actor_user_id
        existing.updated_at = now
        session.add(existing)

    await session.flush()
    after_json = _assignment_snapshot(existing)
    session.add(
        ServerRbacAuditEvent(
            server_id=server_id,
            actor_user_id=actor_user_id,
            subject_type=normalized_type,
            subject_id=normalized_id,
            before_json=before_json,
            after_json=after_json,
            created_at=now,
        )
    )
    await session.flush()
    return _to_assignment_read_model(existing)


async def delete_rbac_assignment(
    session: AsyncSession,
    server_id: int,
    subject_type: str,
    subject_id: str,
    actor_user_id: int,
) -> None:
    normalized_type, normalized_id = normalize_subject(subject_type, subject_id)
    assignment = await _get_assignment(session, server_id, normalized_type, normalized_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RBAC assignment not found")

    await _ensure_global_user(session, actor_user_id)
    before_json = _assignment_snapshot(assignment)
    now = utcnow_utc_tz()
    await session.delete(assignment)
    session.add(
        ServerRbacAuditEvent(
            server_id=server_id,
            actor_user_id=actor_user_id,
            subject_type=normalized_type,
            subject_id=normalized_id,
            before_json=before_json,
            after_json=None,
            created_at=now,
        )
    )
    await session.flush()


async def _user_is_server_owner(server_id: int, user_id: int) -> bool:
    metadata = await fetch_guild_metadata(server_id)
    owner_id = metadata.get("owner_id")
    return owner_id is not None and str(owner_id) == str(user_id)


async def _role_ids_include_administrator(server_id: int, role_ids: set[int]) -> bool:
    role_ids_with_everyone = set(role_ids)
    role_ids_with_everyone.add(server_id)
    roles = await fetch_guild_roles(server_id)
    for role in roles:
        raw_role_id = role.get("id")
        if raw_role_id is None or not str(raw_role_id).isdigit():
            continue
        if int(raw_role_id) not in role_ids_with_everyone:
            continue
        permissions = int(role.get("permissions", 0))
        if permissions & ADMINISTRATOR_PERMISSION_FLAG:
            return True
    return False


async def _resolve_fallback_flags(
    server_id: int,
    user_id: int,
    access_token: str | None,
) -> tuple[bool, bool]:
    if access_token is not None:
        try:
            return await get_current_user_guild_access_flags(server_id=server_id, access_token=access_token)
        except HTTPException:
            raise

    is_owner = await _user_is_server_owner(server_id, user_id)
    if is_owner:
        return True, False

    role_ids = await get_dashboard_member_role_ids(server_id=server_id, user_id=user_id)
    is_admin = await _role_ids_include_administrator(server_id=server_id, role_ids=role_ids)
    return False, is_admin


async def resolve_effective_permissions(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    access_token: str | None = None,
) -> RbacEffectivePermissionsModel:
    user_role_ids = await get_dashboard_member_role_ids(server_id=server_id, user_id=user_id)
    matched_role_ids = {str(role_id) for role_id in user_role_ids}
    owner_fallback, admin_fallback = await _resolve_fallback_flags(
        server_id=server_id,
        user_id=user_id,
        access_token=access_token,
    )

    direct_assignment = await _get_assignment(session, server_id, "user", str(user_id))
    role_assignments: list[ServerRbacAssignment] = []
    if matched_role_ids:
        role_assignments = (
            await session.exec(
                select(ServerRbacAssignment).where(
                    ServerRbacAssignment.server_id == server_id,
                    ServerRbacAssignment.subject_type == "role",
                    ServerRbacAssignment.subject_id.in_(matched_role_ids),
                )
            )
        ).all()

    if owner_fallback or admin_fallback:
        permission_keys = sorted(get_all_permission_keys())
    else:
        permission_set: set[str] = set()
        if direct_assignment is not None:
            permission_set.update(
                expand_assignment_permissions(
                    direct_assignment.preset,
                    list(direct_assignment.permission_keys or []),
                )
            )
        for assignment in role_assignments:
            permission_set.update(
                expand_assignment_permissions(
                    assignment.preset,
                    list(assignment.permission_keys or []),
                )
            )
        permission_keys = sorted(permission_set)

    return RbacEffectivePermissionsModel(
        server_id=str(server_id),
        user_id=str(user_id),
        permission_keys=permission_keys,
        matched_role_ids=sorted(matched_role_ids),
        direct_assignment=_to_assignment_read_model(direct_assignment) if direct_assignment else None,
        role_assignments=[_to_assignment_read_model(assignment) for assignment in role_assignments],
        owner_fallback_applied=owner_fallback,
        admin_fallback_applied=admin_fallback,
    )


async def assert_user_has_permission(
    session: AsyncSession,
    server_id: int,
    user_id: int,
    permission_key: str,
    access_token: str | None = None,
) -> RbacEffectivePermissionsModel:
    validate_permission_keys([permission_key])
    effective = await resolve_effective_permissions(
        session=session,
        server_id=server_id,
        user_id=user_id,
        access_token=access_token,
    )
    if permission_key not in effective.permission_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {permission_key}",
        )
    return effective


async def count_rbac_audit_events(session: AsyncSession, server_id: int) -> int:
    value = (
        await session.exec(
            select(func.count(ServerRbacAuditEvent.id)).where(ServerRbacAuditEvent.server_id == server_id)
        )
    ).one()
    return int(value or 0)
