from sqlmodel import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.release_notes import (
    LocalizedReleaseTextModel,
    ReleaseNoteActionModel,
    ReleaseNoteReadModel,
    ReleaseNotesManifestModel,
)
from src.db.models import ProductReleaseNote


def to_release_note_read_model(note: ProductReleaseNote) -> ReleaseNoteReadModel:
    action = None
    if note.action_label_en and note.action_label_ru and note.action_path:
        action = ReleaseNoteActionModel(
            label=LocalizedReleaseTextModel(
                en=note.action_label_en,
                ru=note.action_label_ru,
            ),
            path=note.action_path,
        )
    return ReleaseNoteReadModel(
        id=note.id,
        published_at=note.published_at,
        title=LocalizedReleaseTextModel(en=note.title_en, ru=note.title_ru),
        summary=LocalizedReleaseTextModel(en=note.summary_en, ru=note.summary_ru),
        surface=note.surface,
        feature=LocalizedReleaseTextModel(en=note.feature_en, ru=note.feature_ru),
        action=action,
        changes=[LocalizedReleaseTextModel.model_validate(change) for change in note.changes],
    )


async def list_published_release_notes(
    session: AsyncSession,
    *,
    limit: int,
) -> ReleaseNotesManifestModel:
    statement = (
        select(ProductReleaseNote)
        .where(ProductReleaseNote.is_published.is_(True))
        .order_by(desc(ProductReleaseNote.published_at), desc(ProductReleaseNote.id))
        .limit(limit)
    )
    notes = (await session.exec(statement)).all()
    return ReleaseNotesManifestModel(
        releases=[to_release_note_read_model(note) for note in notes]
    )
