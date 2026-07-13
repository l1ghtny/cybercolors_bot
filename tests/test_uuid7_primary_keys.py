from uuid import UUID

import pytest

from src.db.models import (
    AIAnswerLog,
    AIKnowledgeChunk,
    AIKnowledgeIndexJob,
    AIModerationDecision,
    AttachmentLog,
    DeletedMessage,
    ModerationAction,
    ModerationActionDeletedMessageLink,
    ModerationActionRuleCitation,
    ModerationCase,
    ModerationCaseActionLink,
    ModerationCaseEvidence,
    ModerationCaseNote,
    ModerationCaseRuleCitation,
    ModerationCaseUser,
    ModerationImportRun,
    ModerationImportSourceItem,
    MonitoredUserActivityEvent,
    MonitoredUserComment,
    MonitoredUserStatusEvent,
    ServerRbacAuditEvent,
    TempVoiceLog,
    TempVoiceParticipant,
    Triggers,
)

UUID7_MODELS = (
    AIModerationDecision,
    AIAnswerLog,
    AIKnowledgeChunk,
    AIKnowledgeIndexJob,
    ModerationAction,
    ModerationImportRun,
    ModerationImportSourceItem,
    MonitoredUserComment,
    MonitoredUserStatusEvent,
    MonitoredUserActivityEvent,
    ServerRbacAuditEvent,
    ModerationCase,
    ModerationCaseUser,
    ModerationCaseActionLink,
    ModerationActionRuleCitation,
    ModerationCaseRuleCitation,
    ModerationCaseNote,
    ModerationCaseEvidence,
    DeletedMessage,
    ModerationActionDeletedMessageLink,
    TempVoiceLog,
    TempVoiceParticipant,
    AttachmentLog,
    Triggers,
)


@pytest.mark.parametrize("model", UUID7_MODELS, ids=lambda model: model.__name__)
def test_append_models_generate_uuid7_with_database_fallback(model) -> None:
    factory = model.model_fields["id"].default_factory

    assert factory is not None
    generated = factory()
    assert isinstance(generated, UUID)
    assert generated.version == 7

    server_default = model.__table__.c.id.server_default
    assert server_default is not None
    assert str(server_default.arg) == "uuidv7()"
