from fastapi import APIRouter, Depends, status
from sqlmodel.ext.asyncio.session import AsyncSession

from api.dependencies.auth import get_bearer_access_token
from api.dependencies.current_user import get_current_discord_user_id
from api.dependencies.server_access import require_server_dashboard_access, require_server_permission
from api.models.rbac import (
    RbacAssignmentReadModel,
    RbacAssignmentWriteModel,
    RbacAssignmentsReadModel,
    RbacCatalogModel,
    RbacCheckRequestModel,
    RbacCheckResponseModel,
    RbacEffectivePermissionsModel,
)
from api.services.rbac_catalog import get_rbac_catalog, validate_permission_keys
from api.services.rbac_service import (
    delete_rbac_assignment,
    get_rbac_assignment,
    list_rbac_assignments,
    resolve_effective_permissions,
    upsert_rbac_assignment,
)
from src.db.database import get_session

rbac_router = APIRouter(prefix="/servers/{server_id}/rbac")


@rbac_router.get(
    "/permissions",
    response_model=RbacCatalogModel,
    dependencies=[Depends(require_server_dashboard_access)],
)
async def get_server_rbac_permissions(server_id: int):
    return get_rbac_catalog()


@rbac_router.get(
    "/assignments",
    response_model=RbacAssignmentsReadModel,
)
async def get_server_rbac_assignments(
    server_id: int,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("rbac.manage")),
):
    return await list_rbac_assignments(session=session, server_id=server_id)


@rbac_router.get(
    "/assignments/{subject_type}/{subject_id}",
    response_model=RbacAssignmentReadModel,
)
async def get_server_rbac_assignment(
    server_id: int,
    subject_type: str,
    subject_id: str,
    session: AsyncSession = Depends(get_session),
    _: int = Depends(require_server_permission("rbac.manage")),
):
    return await get_rbac_assignment(
        session=session,
        server_id=server_id,
        subject_type=subject_type,
        subject_id=subject_id,
    )


@rbac_router.put(
    "/assignments/{subject_type}/{subject_id}",
    response_model=RbacAssignmentReadModel,
)
async def put_server_rbac_assignment(
    server_id: int,
    subject_type: str,
    subject_id: str,
    body: RbacAssignmentWriteModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("rbac.manage")),
):
    return await upsert_rbac_assignment(
        session=session,
        server_id=server_id,
        subject_type=subject_type,
        subject_id=subject_id,
        body=body,
        actor_user_id=current_user_id,
    )


@rbac_router.delete(
    "/assignments/{subject_type}/{subject_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_server_rbac_assignment(
    server_id: int,
    subject_type: str,
    subject_id: str,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("rbac.manage")),
):
    await delete_rbac_assignment(
        session=session,
        server_id=server_id,
        subject_type=subject_type,
        subject_id=subject_id,
        actor_user_id=current_user_id,
    )
    return None


@rbac_router.get(
    "/effective/{user_id}",
    response_model=RbacEffectivePermissionsModel,
)
async def get_server_rbac_effective_permissions(
    server_id: int,
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_permission("rbac.manage")),
    access_token: str = Depends(get_bearer_access_token),
):
    return await resolve_effective_permissions(
        session=session,
        server_id=server_id,
        user_id=user_id,
        access_token=access_token if user_id == current_user_id else None,
    )


@rbac_router.post(
    "/check",
    response_model=RbacCheckResponseModel,
)
async def check_server_rbac_permissions(
    server_id: int,
    body: RbacCheckRequestModel,
    session: AsyncSession = Depends(get_session),
    current_user_id: int = Depends(require_server_dashboard_access),
    access_token: str = Depends(get_bearer_access_token),
):
    requested_keys = validate_permission_keys(body.permission_keys)
    effective = await resolve_effective_permissions(
        session=session,
        server_id=server_id,
        user_id=current_user_id,
        access_token=access_token,
    )
    effective_keys = set(effective.permission_keys)
    return RbacCheckResponseModel(
        server_id=str(server_id),
        user_id=str(current_user_id),
        results={permission_key: permission_key in effective_keys for permission_key in requested_keys},
        permission_keys=effective.permission_keys,
    )
