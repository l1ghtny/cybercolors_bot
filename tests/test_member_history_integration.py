import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from api.models.moderation_actions import ModerationActionCreate
from api.models.moderation_cases import ModerationCaseCreateModel, ModerationCaseNoteCreateModel
from api.models.user_profiles import MemberNoteCreateModel
from api.services.member_history import (
    create_member_note,
    delete_member_note,
    list_member_history,
    list_member_notes,
)
from api.services.moderation_actions_service import create_action
from api.services.moderation_cases_service import add_case_note, create_case
from api.services.moderation_users_service import build_user_profile_card
from api.services.monitoring_service import (
    add_monitored_user_comment,
    update_monitored_user,
    upsert_monitored_user,
)
from src.db.database import get_async_session
from src.db.models import ActionType, GlobalUser, Server, User


def _discord_id() -> int:
    return 7_100_000_000_000_000 + (uuid4().int % 100_000_000_000_000)


async def _scenario() -> None:
    server_id = _discord_id()
    moderator_id = _discord_id()
    target_id = _discord_id()

    async with get_async_session() as session:
        session.add(Server(server_id=server_id, server_name="member-history", bot_active=True))
        for user_id, username in ((moderator_id, "moderator"), (target_id, "target")):
            session.add(GlobalUser(discord_id=user_id, username=username))
            session.add(
                User(
                    user_id=user_id,
                    server_id=server_id,
                    server_nickname=username,
                    is_member=True,
                )
            )
        await session.flush()

        note = await create_member_note(
            session=session,
            server_id=server_id,
            user_id=target_id,
            author_user_id=moderator_id,
            body=MemberNoteCreateModel(note="  Context without a warning  "),
        )
        assert note.note == "Context without a warning"
        assert note.author is not None
        assert note.author.user_id == str(moderator_id)

        profile = await build_user_profile_card(
            session=session,
            server_id=server_id,
            user_id=target_id,
        )
        assert profile.member_notes_count == 1

        action = await create_action(
            session=session,
            action=ModerationActionCreate(
                action_type=ActionType.WARN,
                moderator_user_id=moderator_id,
                reason="Repeated personal attacks",
                commentary="Prior context was reviewed",
                rule_ids=[],
                expires_at=None,
                case_id=None,
                target_user_id=target_id,
                target_user_name="target",
                target_user_joined_at=datetime.now(timezone.utc),
                target_user_server_nickname="target",
                server_id=server_id,
                server_name="member-history",
            ),
            moderator_user_id=moderator_id,
        )
        moderation_case = await create_case(
            session=session,
            server_id=server_id,
            body=ModerationCaseCreateModel(
                target_user_id=str(target_id),
                title="Repeated disruption",
                summary="Reviewing behavior across channels",
                rule_ids=[],
                users=[],
            ),
            opened_by_user_id=moderator_id,
        )
        await add_case_note(
            session=session,
            server_id=server_id,
            case_id=UUID(moderation_case.id),
            body=ModerationCaseNoteCreateModel(
                note="Context collected during the case",
                is_internal=True,
            ),
            author_user_id=moderator_id,
        )

        await upsert_monitored_user(
            session=session,
            server_id=server_id,
            user_id=target_id,
            reason="Watch for repeat behavior",
            added_by_user_id=moderator_id,
        )
        await add_monitored_user_comment(
            session=session,
            server_id=server_id,
            user_id=target_id,
            comment="Follow-up context while monitoring",
            author_user_id=moderator_id,
        )
        await update_monitored_user(
            session=session,
            server_id=server_id,
            user_id=target_id,
            reason="No incidents during the review period",
            is_active=False,
            updated_by_user_id=moderator_id,
        )
        await update_monitored_user(
            session=session,
            server_id=server_id,
            user_id=target_id,
            reason="New report received",
            is_active=True,
            updated_by_user_id=moderator_id,
        )

        history = await list_member_history(
            session=session,
            server_id=server_id,
            user_id=target_id,
            limit=100,
        )
        assert [item.occurred_at for item in history] == sorted(
            (item.occurred_at for item in history),
            reverse=True,
        )
        assert len({item.id for item in history}) == len(history)

        action_event = next(item for item in history if item.id == f"moderation_action:{action.id}")
        assert action_event.reason == "Repeated personal attacks"
        assert action_event.commentary == "Prior context was reviewed"
        assert action_event.actor is not None
        assert action_event.actor.user_id == str(moderator_id)

        case_event = next(item for item in history if item.id == f"case_opened:{moderation_case.id}")
        assert case_event.case_title == "Repeated disruption"
        assert case_event.reason == "Reviewing behavior across channels"
        assert any(
            item.event_type == "case_note" and item.note == "Context collected during the case"
            for item in history
        )
        assert any(
            item.event_type == "monitoring_comment"
            and item.note == "Follow-up context while monitoring"
            for item in history
        )

        monitoring_events = [
            item for item in history if item.event_type in {"monitoring_enabled", "monitoring_disabled"}
        ]
        assert {item.reason for item in monitoring_events} == {
            "Watch for repeat behavior",
            "No incidents during the review period",
            "New report received",
        }

        removed = await delete_member_note(
            session=session,
            server_id=server_id,
            user_id=target_id,
            note_id=UUID(note.id),
            deleted_by_user_id=moderator_id,
            reason="Outdated context",
        )
        assert removed.note is None
        assert removed.deletion_reason == "Outdated context"
        assert await list_member_notes(
            session=session,
            server_id=server_id,
            user_id=target_id,
        ) == []

        history_after_removal = await list_member_history(
            session=session,
            server_id=server_id,
            user_id=target_id,
            limit=100,
        )
        removal_event = next(
            item for item in history_after_removal if item.id == f"member_note_removed:{note.id}"
        )
        assert removal_event.note is None
        assert removal_event.reason == "Outdated context"

        profile_after_removal = await build_user_profile_card(
            session=session,
            server_id=server_id,
            user_id=target_id,
        )
        assert profile_after_removal.member_notes_count == 0
        await session.rollback()


def test_member_notes_and_unified_history_integration():
    asyncio.run(_scenario())
