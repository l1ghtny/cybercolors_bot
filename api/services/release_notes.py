from sqlmodel import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.release_notes import (
    LocalizedReleaseTextModel,
    PublicProductUpdateActionModel,
    PublicProductUpdateReadModel,
    PublicProductUpdatesManifestModel,
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
        change_type=note.change_type,
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


def to_public_product_update_read_model(
    note: ProductReleaseNote,
) -> PublicProductUpdateReadModel:
    if not all(
        (
            note.public_slug,
            note.public_title_en,
            note.public_title_ru,
            note.public_summary_en,
            note.public_summary_ru,
        )
    ):
        raise ValueError(f"Public release note {note.id!r} is missing public copy")

    action = None
    if (
        note.public_action_label_en
        and note.public_action_label_ru
        and note.public_action_url
    ):
        action = PublicProductUpdateActionModel(
            label=LocalizedReleaseTextModel(
                en=note.public_action_label_en,
                ru=note.public_action_label_ru,
            ),
            url=note.public_action_url,
        )

    return PublicProductUpdateReadModel(
        id=note.id,
        slug=note.public_slug,
        published_at=note.published_at,
        title=LocalizedReleaseTextModel(
            en=note.public_title_en,
            ru=note.public_title_ru,
        ),
        summary=LocalizedReleaseTextModel(
            en=note.public_summary_en,
            ru=note.public_summary_ru,
        ),
        change_type=note.change_type,
        surface=note.surface,
        feature=LocalizedReleaseTextModel(en=note.feature_en, ru=note.feature_ru),
        action=action,
        image_url=note.public_image_url,
    )


async def list_public_product_updates(
    session: AsyncSession,
    *,
    limit: int,
) -> PublicProductUpdatesManifestModel:
    statement = (
        select(ProductReleaseNote)
        .where(
            ProductReleaseNote.is_published.is_(True),
            ProductReleaseNote.is_public.is_(True),
        )
        .order_by(desc(ProductReleaseNote.published_at), desc(ProductReleaseNote.id))
        .limit(limit)
    )
    notes = (await session.exec(statement)).all()
    return PublicProductUpdatesManifestModel(
        updates=[to_public_product_update_read_model(note) for note in notes]
    )
