import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from fastapi.routing import APIRoute
from starlette.routing import Match
from sqlmodel import SQLModel

from api.api_main import app
from api.dependencies.server_access import require_server_permission
from api.models.moderation_cases import ModerationCaseActionCreateFromCaseModel
from api.routers.moderation_cases import require_case_action_apply_permission
from api.models.rbac import RbacAssignmentWriteModel
from api.services.rbac_catalog import get_rbac_catalog
from api.services.rbac_service import (
    count_rbac_audit_events,
    delete_rbac_assignment,
    resolve_effective_permissions,
    upsert_rbac_assignment,
)
from src.db.database import engine, get_async_session
from src.db.models import ActionType, GlobalUser, Server
from tests.db_helpers import ensure_pgvector_or_skip


def _make_discord_id() -> int:
    return 8_000_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


async def _ensure_schema() -> None:
    await engine.dispose()
    async with engine.begin() as conn:
        await ensure_pgvector_or_skip(conn)
        await conn.run_sync(SQLModel.metadata.create_all)


def test_rbac_catalog_contains_presets_and_permission_keys():
    catalog = get_rbac_catalog()
    permission_keys = {permission.key for permission in catalog.permissions}
    preset_keys = {preset.key for preset in catalog.presets}

    assert "rbac.manage" in permission_keys
    assert "commands.visibility.manage" in permission_keys
    assert "localization.settings.edit" in permission_keys
    assert "overview.settings.edit" in permission_keys
    assert "temp_voice.settings.edit" in permission_keys
    assert "temp_voice.settings.view" in permission_keys
    assert "ai.suggestions.view" in permission_keys
    assert "ai.decisions.view" in permission_keys
    assert "ai.suggestions.review" in permission_keys
    assert "birthdays.records.manage" in permission_keys
    assert "moderation.cases.view" in permission_keys
    assert "moderation.cases.manage" in permission_keys
    assert "communications.send_as_bot" in permission_keys
    for action_type in ActionType:
        assert f"moderation.actions.apply.{action_type.value}" in permission_keys
    assert "admin" in preset_keys
    assert "moderator" in preset_keys
    birthday_records = next(permission for permission in catalog.permissions if permission.key == "birthdays.records.manage")
    assert birthday_records.group == "birthdays"
    moderator = next(preset for preset in catalog.presets if preset.key == "moderator")
    assert "birthdays.records.manage" in moderator.permission_keys
    assert "communications.send_as_bot" in moderator.permission_keys
    admin = next(preset for preset in catalog.presets if preset.key == "admin")
    assert "commands.visibility.manage" in admin.permission_keys


def _route_permission_keys(path: str, method: str) -> set[str]:
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path != path or method.upper() not in route.methods:
            continue
        return {
            dependency.call.permission_key
            for dependency in route.dependant.dependencies
            if hasattr(dependency.call, "permission_key")
        }
    raise AssertionError(f"Route not found: {method} {path}")


CASE_ENDPOINT_PERMISSION_MATRIX = (
    ("GET", "/moderation/cases/{server_id}", "moderation.cases.view"),
    ("GET", "/moderation/cases/{server_id}/{case_id}", "moderation.cases.view"),
    ("GET", "/moderation/cases/{server_id}/{case_id}/users", "moderation.cases.view"),
    (
        "GET",
        "/moderation/cases/{server_id}/{case_id}/evidence/{evidence_id}/download-url",
        "moderation.cases.view",
    ),
    ("POST", "/moderation/cases/{server_id}", "moderation.cases.manage"),
    ("PATCH", "/moderation/cases/{server_id}/{case_id}/status", "moderation.cases.manage"),
    ("POST", "/moderation/cases/{server_id}/{case_id}/users", "moderation.cases.manage"),
    ("DELETE", "/moderation/cases/{server_id}/{case_id}/users/{user_id}", "moderation.cases.manage"),
    ("POST", "/moderation/cases/{server_id}/{case_id}/notes", "moderation.cases.manage"),
    ("POST", "/moderation/cases/{server_id}/{case_id}/evidence", "moderation.cases.manage"),
    ("POST", "/moderation/cases/{server_id}/{case_id}/evidence/upload-url", "moderation.cases.manage"),
    ("POST", "/moderation/cases/{server_id}/{case_id}/actions", "moderation.cases.manage"),
    ("DELETE", "/moderation/cases/{server_id}/{case_id}/actions/{action_id}", "moderation.cases.manage"),
    ("POST", "/moderation/cases/{server_id}/{case_id}/rules", "moderation.cases.manage"),
    ("DELETE", "/moderation/cases/{server_id}/{case_id}/rules/{rule_id}", "moderation.cases.manage"),
    ("POST", "/moderation/cases/{server_id}/{case_id}/actions/create", "moderation.cases.manage"),
)


def _route_permission_dependency(path: str, method: str, permission_key: str):
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path != path or method.upper() not in route.methods:
            continue
        for dependency in route.dependant.dependencies:
            if getattr(dependency.call, "permission_key", None) == permission_key:
                return dependency.call
        raise AssertionError(f"Permission dependency not found: {method} {path} -> {permission_key}")
    raise AssertionError(f"Route not found: {method} {path}")


async def _case_endpoint_permission_denial_scenario(
    monkeypatch,
    method: str,
    path: str,
    permission_key: str,
) -> None:
    import api.dependencies.server_access as server_access

    async def allow_dashboard_access(**kwargs):
        return None

    async def deny_permission(**kwargs):
        assert kwargs["permission_key"] == permission_key
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission",
        )

    monkeypatch.setattr(server_access, "assert_dashboard_access", allow_dashboard_access)
    monkeypatch.setattr(server_access, "assert_user_has_permission", deny_permission)
    dependency = _route_permission_dependency(path, method, permission_key)

    with pytest.raises(HTTPException) as exc_info:
        await dependency(
            server_id=123,
            session=object(),
            current_user_id=456,
            access_token="token",
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.parametrize(("method", "path", "permission_key"), CASE_ENDPOINT_PERMISSION_MATRIX)
def test_case_endpoints_reject_users_without_required_permission(
    monkeypatch,
    method: str,
    path: str,
    permission_key: str,
):
    asyncio.run(
        _case_endpoint_permission_denial_scenario(
            monkeypatch,
            method,
            path,
            permission_key,
        )
    )


def test_permission_dependency_exposes_permission_key_for_route_inspection():
    dependency = require_server_permission("security.settings.edit")

    assert dependency.permission_key == "security.settings.edit"
    assert dependency.__name__ == "require_server_permission_security_settings_edit"


def test_settings_write_routes_use_feature_permissions():
    expected = {
        ("PUT", "/servers/{server_id}/overview-settings"): {"overview.settings.edit"},
        ("PUT", "/servers/{server_id}/localization"): {"localization.settings.edit"},
        ("PUT", "/servers/{server_id}/security/verified-role"): {"security.settings.edit"},
        ("GET", "/servers/{server_id}/security/newcomer-role/suggestion"): {"security.settings.edit"},
        ("PUT", "/servers/{server_id}/security/newcomer-role"): {"security.settings.edit"},
        ("POST", "/servers/{server_id}/security/newcomer-role/create"): {"security.settings.edit"},
        ("POST", "/servers/{server_id}/security/newcomer-role/apply-restrictions"): {"security.settings.edit"},
        ("PUT", "/servers/{server_id}/security/permissions"): {"security.settings.edit"},
        ("PUT", "/servers/{server_id}/security/lockdown"): {"security.lockdown.manage"},
        ("PUT", "/servers/{server_id}/security/incident-actions"): {"security.lockdown.manage"},
        ("GET", "/servers/{server_id}/temp-voice"): {"temp_voice.settings.view"},
        ("GET", "/servers/{server_id}/temp-voice/archives"): {"temp_voice.settings.view"},
        ("GET", "/servers/{server_id}/temp-voice/archives/{log_id}"): {"temp_voice.settings.view"},
        ("GET", "/servers/{server_id}/temp-voice/archives/{log_id}/transcript.txt"): {"temp_voice.settings.view"},
        ("PUT", "/servers/{server_id}/temp-voice"): {"temp_voice.settings.edit"},
        ("POST", "/servers/{server_id}/temp-voice/trigger-channel/create"): {"temp_voice.settings.edit"},
        ("GET", "/moderation/message-log/{server_id}"): {"moderation.actions.view"},
        ("GET", "/moderation/deleted-attachments/{server_id}"): {"moderation.actions.view"},
        ("GET", "/moderation/cases/{server_id}"): {"moderation.cases.view"},
        ("GET", "/moderation/cases/{server_id}/{case_id}"): {"moderation.cases.view"},
        ("GET", "/moderation/cases/{server_id}/{case_id}/users"): {"moderation.cases.view"},
        (
            "GET",
            "/moderation/cases/{server_id}/{case_id}/evidence/{evidence_id}/download-url",
        ): {"moderation.cases.view"},
        ("POST", "/moderation/cases/{server_id}"): {"moderation.cases.manage"},
        ("PATCH", "/moderation/cases/{server_id}/{case_id}/status"): {"moderation.cases.manage"},
        ("POST", "/moderation/cases/{server_id}/{case_id}/users"): {"moderation.cases.manage"},
        ("DELETE", "/moderation/cases/{server_id}/{case_id}/users/{user_id}"): {"moderation.cases.manage"},
        ("POST", "/moderation/cases/{server_id}/{case_id}/notes"): {"moderation.cases.manage"},
        ("POST", "/moderation/cases/{server_id}/{case_id}/evidence"): {"moderation.cases.manage"},
        ("POST", "/moderation/cases/{server_id}/{case_id}/evidence/upload-url"): {"moderation.cases.manage"},
        ("POST", "/moderation/cases/{server_id}/{case_id}/actions"): {"moderation.cases.manage"},
        ("DELETE", "/moderation/cases/{server_id}/{case_id}/actions/{action_id}"): {"moderation.cases.manage"},
        ("POST", "/moderation/cases/{server_id}/{case_id}/rules"): {"moderation.cases.manage"},
        ("DELETE", "/moderation/cases/{server_id}/{case_id}/rules/{rule_id}"): {"moderation.cases.manage"},
        ("POST", "/moderation/cases/{server_id}/{case_id}/actions/create"): {"moderation.cases.manage"},
        ("PUT", "/servers/{server_id}/moderation-settings"): {"moderation.settings.edit"},
        ("POST", "/servers/{server_id}/moderation-settings/create-mute-role"): {"moderation.settings.edit"},
        ("PUT", "/servers/{server_id}/ai-settings"): {"ai.settings.edit"},
        ("GET", "/servers/{server_id}/discord-command-visibility"): {"commands.visibility.manage"},
        ("PUT", "/servers/{server_id}/discord-command-visibility"): {"commands.visibility.manage"},
        ("GET", "/servers/{server_id}/ai/suggestions"): {"ai.suggestions.view"},
        ("POST", "/servers/{server_id}/ai/suggestions/{suggestion_id}/approve"): {"ai.suggestions.review"},
        ("POST", "/servers/{server_id}/ai/suggestions/{suggestion_id}/tweak"): {"ai.suggestions.review"},
        ("POST", "/servers/{server_id}/ai/suggestions/{suggestion_id}/dismiss"): {"ai.suggestions.review"},
        ("GET", "/servers/{server_id}/ai/decisions"): {"ai.decisions.view"},
        ("GET", "/servers/{server_id}/ai/knowledge"): {"ai.knowledge.view"},
        ("POST", "/servers/{server_id}/ai/knowledge"): {"ai.knowledge.manage"},
        ("POST", "/servers/{server_id}/ai/knowledge/search"): {"ai.knowledge.view"},
        ("GET", "/servers/{server_id}/ai/knowledge/jobs"): {"ai.knowledge.manage"},
        ("POST", "/servers/{server_id}/ai/knowledge/jobs/process-one"): {"ai.knowledge.manage"},
        ("GET", "/servers/{server_id}/ai/knowledge/{source_id}"): {"ai.knowledge.view"},
        ("PUT", "/servers/{server_id}/ai/knowledge/{source_id}"): {"ai.knowledge.manage"},
        ("DELETE", "/servers/{server_id}/ai/knowledge/{source_id}"): {"ai.knowledge.manage"},
        ("POST", "/servers/{server_id}/ai/knowledge/{source_id}/reindex"): {"ai.knowledge.manage"},
        ("POST", "/replies/{server_id}/add_replies"): {"replies.manage"},
        ("POST", "/replies/{server_id}/delete_replies"): {"replies.manage"},
        ("POST", "/replies/{server_id}/edit_replies"): {"replies.manage"},
        ("POST", "/replies/{server_id}/duplicate-selected"): {"replies.manage"},
        ("POST", "/birthdays/{server_id}"): {"birthdays.records.manage"},
        ("PUT", "/birthdays/{server_id}/{user_id}"): {"birthdays.records.manage"},
        ("DELETE", "/birthdays/{server_id}/{user_id}"): {"birthdays.records.manage"},
        ("PUT", "/birthdays/{server_id}/settings/channel"): {"birthdays.settings.edit"},
        ("PUT", "/birthdays/{server_id}/settings/role"): {"birthdays.settings.edit"},
        ("POST", "/birthdays/{server_id}/settings/messages"): {"birthdays.settings.edit"},
        ("PUT", "/birthdays/{server_id}/settings/messages/{message_id}"): {"birthdays.settings.edit"},
        ("DELETE", "/birthdays/{server_id}/settings/messages/{message_id}"): {"birthdays.settings.edit"},
        ("POST", "/moderation/rules/{server_id}"): {"moderation.rules.manage"},
        ("POST", "/moderation/rules/{server_id}/import-text"): {"moderation.rules.manage"},
        ("POST", "/moderation/rules/{server_id}/import-message"): {"moderation.rules.manage"},
        ("POST", "/moderation/rules/{server_id}/import-messages"): {"moderation.rules.manage"},
        ("DELETE", "/moderation/rules/{server_id}/{rule_id}"): {"moderation.rules.manage"},
        ("DELETE", "/moderation/rules/{server_id}/{rule_id}/hard"): {"moderation.rules.edit"},
    }

    for (method, path), permission_keys in expected.items():
        assert permission_keys.issubset(_route_permission_keys(path, method))


async def _case_action_permission_denial_scenario(monkeypatch) -> None:
    import api.routers.moderation_cases as moderation_cases_router

    checked_permissions: list[str] = []

    async def deny_permission(**kwargs):
        checked_permissions.append(kwargs["permission_key"])
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission",
        )

    monkeypatch.setattr(moderation_cases_router, "assert_user_has_permission", deny_permission)

    for action_type in ActionType:
        with pytest.raises(HTTPException) as exc_info:
            await require_case_action_apply_permission(
                server_id=123,
                body=ModerationCaseActionCreateFromCaseModel(action_type=action_type),
                session=object(),
                current_user_id=456,
                access_token="token",
            )
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    assert checked_permissions == [
        f"moderation.actions.apply.{action_type.value}"
        for action_type in ActionType
    ]


def test_case_action_creation_requires_action_specific_permission(monkeypatch):
    asyncio.run(_case_action_permission_denial_scenario(monkeypatch))


def test_rbac_assignment_route_is_registered_under_server_settings():
    path = "/servers/123/rbac/assignments/user/456"
    scope = {"type": "http", "method": "PUT", "path": path}

    for route in app.routes:
        match, child_scope = route.matches(scope)
        if match == Match.FULL:
            assert route.path == "/servers/{server_id}/rbac/assignments/{subject_type}/{subject_id}"
            assert child_scope["path_params"] == {
                "server_id": "123",
                "subject_type": "user",
                "subject_id": "456",
            }
            return

    raise AssertionError("RBAC assignment route did not match")


async def _assignment_resolution_scenario(monkeypatch) -> None:
    import api.services.rbac_service as rbac_service

    await _ensure_schema()
    server_id = _make_discord_id()
    actor_id = _make_discord_id()
    target_id = _make_discord_id()
    role_id = _make_discord_id()

    async def fake_member_role_ids(server_id: int, user_id: int) -> set[int]:
        if user_id == target_id:
            return {role_id}
        return set()

    async def fake_guild_metadata(server_id: int) -> dict:
        return {"owner_id": str(_make_discord_id())}

    async def fake_guild_roles(server_id: int) -> list[dict]:
        return [{"id": str(role_id), "name": "Moderators", "permissions": "0"}]

    monkeypatch.setattr(rbac_service, "get_dashboard_member_role_ids", fake_member_role_ids)
    monkeypatch.setattr(rbac_service, "fetch_guild_metadata", fake_guild_metadata)
    monkeypatch.setattr(rbac_service, "fetch_guild_roles", fake_guild_roles)

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="rbac-server", bot_active=True))
        session.add(GlobalUser(discord_id=actor_id, username="actor"))
        session.add(GlobalUser(discord_id=target_id, username="target"))
        await session.flush()

        direct = await upsert_rbac_assignment(
            session=session,
            server_id=server_id,
            subject_type="user",
            subject_id=str(target_id),
            body=RbacAssignmentWriteModel(preset="viewer"),
            actor_user_id=actor_id,
        )
        role = await upsert_rbac_assignment(
            session=session,
            server_id=server_id,
            subject_type="role",
            subject_id=str(role_id),
            body=RbacAssignmentWriteModel(permission_keys=["moderation.actions.apply.mute"]),
            actor_user_id=actor_id,
        )
        await session.commit()

        assert direct.subject_type == "user"
        assert role.effective_permission_keys == ["moderation.actions.apply.mute"]

        effective = await resolve_effective_permissions(
            session=session,
            server_id=server_id,
            user_id=target_id,
        )

        assert effective.owner_fallback_applied is False
        assert effective.admin_fallback_applied is False
        assert effective.matched_role_ids == [str(role_id)]
        assert "overview.view" in effective.permission_keys
        assert "moderation.actions.apply.mute" in effective.permission_keys
        assert "moderation.actions.apply.ban" not in effective.permission_keys
        assert await count_rbac_audit_events(session, server_id) == 2

        await delete_rbac_assignment(
            session=session,
            server_id=server_id,
            subject_type="role",
            subject_id=str(role_id),
            actor_user_id=actor_id,
        )
        await session.commit()

        assert await count_rbac_audit_events(session, server_id) == 3

    await engine.dispose()


def test_rbac_assignments_resolve_direct_and_role_permissions(monkeypatch):
    asyncio.run(_assignment_resolution_scenario(monkeypatch))


async def _admin_fallback_scenario(monkeypatch) -> None:
    import api.services.rbac_service as rbac_service

    await _ensure_schema()
    server_id = _make_discord_id()
    user_id = _make_discord_id()

    async def fake_member_role_ids(server_id: int, user_id: int) -> set[int]:
        return set()

    async def fake_access_flags(server_id: int, access_token: str) -> tuple[bool, bool]:
        return False, True

    monkeypatch.setattr(rbac_service, "get_dashboard_member_role_ids", fake_member_role_ids)
    monkeypatch.setattr(rbac_service, "get_current_user_guild_access_flags", fake_access_flags)

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="rbac-admin-server", bot_active=True))
        session.add(GlobalUser(discord_id=user_id, username="admin"))
        await session.commit()

        effective = await resolve_effective_permissions(
            session=session,
            server_id=server_id,
            user_id=user_id,
            access_token="token",
        )

        assert effective.owner_fallback_applied is False
        assert effective.admin_fallback_applied is True
        assert "rbac.manage" in effective.permission_keys
        assert "moderation.actions.apply.ban" in effective.permission_keys

    await engine.dispose()


def test_rbac_admin_fallback_grants_full_catalog(monkeypatch):
    asyncio.run(_admin_fallback_scenario(monkeypatch))
