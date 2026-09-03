from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from api.api_main import app
from api.models.monitoring import MonitoredUserCreateModel, MonitoredUserUpdateModel
from api.models.user_profiles import (
    MemberHistoryEventModel,
    MemberNoteCreateModel,
    MemberNoteDeleteModel,
)
from src.db.models import MemberNote, MonitoredUserStatusEvent


def test_member_note_inputs_are_trimmed_and_empty_text_is_rejected():
    assert MemberNoteCreateModel(note="  useful context  ").note == "useful context"
    assert MemberNoteDeleteModel(reason="  duplicate note  ").reason == "duplicate note"

    with pytest.raises(ValidationError):
        MemberNoteCreateModel(note="   ")
    with pytest.raises(ValidationError):
        MemberNoteDeleteModel(reason="\n\t")


def test_manual_monitoring_and_status_changes_require_a_reason():
    assert MonitoredUserCreateModel(user_id="123", reason="  Initial concern  ").reason == "Initial concern"
    assert MonitoredUserUpdateModel(is_active=False, reason="  Review complete  ").reason == "Review complete"
    assert MonitoredUserUpdateModel(snooze_minutes=30).snooze_minutes == 30

    with pytest.raises(ValidationError):
        MonitoredUserCreateModel(user_id="123", reason="  ")
    with pytest.raises(ValidationError):
        MonitoredUserUpdateModel(is_active=True)


def test_member_history_event_keeps_private_context_fields_separate():
    event = MemberHistoryEventModel(
        id="moderation_action:123",
        event_type="moderation_action",
        occurred_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        reason="Member-facing reason",
        commentary="Private moderator context",
        action_type="warn",
    )

    assert event.reason == "Member-facing reason"
    assert event.commentary == "Private moderator context"
    assert event.note is None


def test_member_note_and_history_routes_are_present_in_the_api_contract():
    paths = app.openapi()["paths"]
    notes_path = "/moderation/users/{server_id}/{user_id}/notes"
    note_path = "/moderation/users/{server_id}/{user_id}/notes/{note_id}"
    history_path = "/moderation/users/{server_id}/{user_id}/history"

    assert {"get", "post"}.issubset(paths[notes_path])
    assert "delete" in paths[note_path]
    assert "get" in paths[history_path]
    assert "before" in {
        parameter["name"]
        for parameter in paths[history_path]["get"]["parameters"]
    }


def test_member_note_storage_enforces_scrubbed_soft_removal_state():
    constraint_names = {
        constraint.name
        for constraint in MemberNote.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_member_notes_content_lifecycle" in constraint_names
    assert MonitoredUserStatusEvent.__table__.c.changed_by_user_id.nullable is True
