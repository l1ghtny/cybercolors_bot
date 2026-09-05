import asyncio
from datetime import datetime, timezone

from sqlmodel import delete
from starlette.routing import Match

from api.api_main import app
from api.services.release_notes import (
    list_public_product_updates,
    list_published_release_notes,
)
from src.db.database import engine, get_async_session
from src.db.models import ProductReleaseNote


def test_release_notes_route_is_available_without_server_context():
    scope = {"type": "http", "method": "GET", "path": "/release-notes"}

    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            assert route.path == "/release-notes"
            return

    raise AssertionError("release notes route did not match")


def test_public_product_updates_route_is_available_without_authentication():
    scope = {"type": "http", "method": "GET", "path": "/release-notes/public"}

    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            assert route.path == "/release-notes/public"
            return

    raise AssertionError("public product updates route did not match")


async def _release_notes_scenario() -> None:
    await engine.dispose()

    async with get_async_session() as session:
        await session.exec(
            delete(ProductReleaseNote).where(
                ProductReleaseNote.id == "unpublished-future-note"
            )
        )
        await session.commit()
        session.add(
            ProductReleaseNote(
                id="unpublished-future-note",
                published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                title_en="Draft",
                title_ru="Черновик",
                summary_en="Not published.",
                summary_ru="Ещё не опубликовано.",
                change_type="improved",
                surface="dashboard",
                feature_en="Testing",
                feature_ru="Тестирование",
                changes=[{"en": "Hidden", "ru": "Скрыто"}],
                is_published=False,
            )
        )
        await session.commit()

        manifest = await list_published_release_notes(session, limit=100)
        public_manifest = await list_public_product_updates(session, limit=50)

    assert len(manifest.releases) == 58
    assert manifest.releases[0].id == "2026-09-04-youtube-audio-download-compatibility"
    assert all(release.id != "2026-09-04-knowledge-discord-identities" for release in manifest.releases)
    assert manifest.releases[1].id == "2026-09-03-readable-member-profile-layout"
    assert manifest.releases[1].title.en == "Member profiles stay readable in narrower windows"
    assert manifest.releases[1].title.ru == "Профили участников удобно читать даже в узких окнах"
    shared_history_release = next(
        release
        for release in manifest.releases
        if release.id == "2026-09-03-shared-member-notes-history"
    )
    assert shared_history_release.title.en == "Shared member notes and one moderation timeline"
    preserved_reason_release = next(
        release
        for release in manifest.releases
        if release.id == "2026-08-26-preserve-moderation-action-reasons"
    )
    assert preserved_reason_release.title.en == "Action reasons are saved with cited rules"
    member_identity_release = next(
        release
        for release in manifest.releases
        if release.id == "2026-08-11-member-name-preference-v2"
    )
    assert member_identity_release.title.en == "Member names now follow Discord consistently"
    assert "server nickname first" in member_identity_release.summary.en
    assert "глобальное имя" in member_identity_release.summary.ru
    assert manifest.releases[-1].id == "2026-07-14-bilingual-moderation-v2"
    assert all(release.title.en and release.title.ru for release in manifest.releases)
    assert all(release.feature.en and release.feature.ru for release in manifest.releases)
    assert {release.change_type for release in manifest.releases} == {
        "added",
        "fixed",
        "improved",
    }
    assert {release.surface for release in manifest.releases} == {
        "dashboard",
        "bot",
        "both",
    }
    assert all(release.changes for release in manifest.releases)
    assert any(
        release.action
        and release.action.path
        == "/dashboard/{server_id}/moderation?tab=actions"
        for release in manifest.releases
    )
    assert all(release.id != "unpublished-future-note" for release in manifest.releases)
    assert all(release.id != "2026-08-06-bot-profiles-v2" for release in manifest.releases)
    assert {
        release.id
        for release in manifest.releases
        if release.feature.en == "Discord command · /warns"
    } == {
        "2026-08-06-warns-command",
        "2026-08-11-warns-legacy-reasons",
    }

    assert len(public_manifest.updates) == 8
    assert public_manifest.updates[0].slug == "shared-member-notes-history"
    assert public_manifest.updates[0].title.en == "Shared moderation memory for every member"
    assert public_manifest.updates[0].title.ru == "Единая история модерации для каждого участника"
    assert {
        update.slug
        for update in public_manifest.updates
    } == {
        "public-product-updates",
        "members-can-review-active-warnings",
        "scheduled-discord-posts",
        "meaning-based-automatic-replies",
        "discord-command-access",
        "private-moderation-case-evidence",
        "batch-ai-moderation-review",
        "shared-member-notes-history",
    }
    assert all(update.title.en and update.title.ru for update in public_manifest.updates)
    assert all(update.summary.en and update.summary.ru for update in public_manifest.updates)
    assert any(
        update.action
        and update.action.url == "/docs/moderation/cases-and-evidence"
        for update in public_manifest.updates
    )

    await engine.dispose()


def test_seeded_release_history_is_localized_ordered_and_published_only():
    asyncio.run(_release_notes_scenario())
