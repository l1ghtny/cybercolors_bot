import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from pydantic import ValidationError

from api.models.moderation_actions import ModerationActionCommentaryUpdate
from api.services import moderation_actions_service
from src.db.models import ActionType


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_count = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1


def test_commentary_update_normalizes_empty_values_and_forbids_reason_changes() -> None:
    assert ModerationActionCommentaryUpdate(commentary="  private note  ").commentary == "private note"
    assert ModerationActionCommentaryUpdate(commentary="   ").commentary is None

    with pytest.raises(ValidationError):
        ModerationActionCommentaryUpdate(commentary="private", reason="public must stay immutable")


def test_commentary_update_changes_only_commentary_and_writes_private_mod_log(monkeypatch) -> None:
    action_id = uuid4()
    action = SimpleNamespace(
        id=action_id,
        server_id=123,
        action_number=42,
        action_type=ActionType.WARN,
        reason="Member-facing reason",
        commentary="Old private note",
    )
    session = _FakeSession()
    logged: list[dict[str, object]] = []

    async def load_action_for_read(*, session, action_id):
        return action

    async def send_update_log(**kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(moderation_actions_service, "_load_action_for_read", load_action_for_read)
    monkeypatch.setattr(
        moderation_actions_service,
        "_send_action_commentary_update_to_mod_log",
        send_update_log,
    )
    monkeypatch.setattr(
        moderation_actions_service,
        "to_moderation_history",
        lambda actions: [SimpleNamespace(reason=actions[0].reason, commentary=actions[0].commentary)],
    )

    result = asyncio.run(
        moderation_actions_service.update_action_commentary(
            session=session,
            server_id=123,
            action_id=action_id,
            moderator_user_id=456,
            commentary="  New private note  ",
        )
    )

    assert result.reason == "Member-facing reason"
    assert result.commentary == "New private note"
    assert action.reason == "Member-facing reason"
    assert session.added == [action]
    assert session.flush_count == 1
    assert logged[0]["previous_commentary"] == "Old private note"
    assert logged[0]["moderator_user_id"] == 456


def test_commentary_update_rejects_action_from_another_server(monkeypatch) -> None:
    action_id = uuid4()

    async def load_action_for_read(*, session, action_id):
        return SimpleNamespace(server_id=999)

    monkeypatch.setattr(moderation_actions_service, "_load_action_for_read", load_action_for_read)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            moderation_actions_service.update_action_commentary(
                session=_FakeSession(),
                server_id=123,
                action_id=action_id,
                moderator_user_id=456,
                commentary="Private note",
            )
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_commentary_update_log_embed_contains_audit_values() -> None:
    action = SimpleNamespace(
        id=uuid4(),
        server_id=123,
        action_number=42,
        action_type=ActionType.WARN,
        commentary="New private note",
    )

    embed = moderation_actions_service._build_action_commentary_update_log_embed(
        action=action,
        moderator_user_id=456,
        moderator_username="moderator",
        previous_commentary="Old private note",
        locale="en",
    )

    assert embed["title"] == "Action commentary updated"
    assert embed["fields"][2]["value"] == "Old private note"
    assert embed["fields"][3]["value"] == "New private note"


def test_legacy_commentary_suffix_stays_private_after_commentary_is_edited() -> None:
    assert moderation_actions_service._reason_without_commentary_suffix(
        "Member-facing reason\nCommentary: Old private note",
        "New private note",
    ) == "Member-facing reason"
