import asyncio
from datetime import datetime, timezone

from starlette.routing import Match

from api.api_main import app
from api.services.release_notes import list_published_release_notes
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


async def _release_notes_scenario() -> None:
    await engine.dispose()

    async with get_async_session() as session:
        session.add(
            ProductReleaseNote(
                id="unpublished-future-note",
                published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                title_en="Draft",
                title_ru="Черновик",
                summary_en="Not published.",
                summary_ru="Ещё не опубликовано.",
                surface="dashboard",
                feature_en="Testing",
                feature_ru="Тестирование",
                changes=[{"en": "Hidden", "ru": "Скрыто"}],
                is_published=False,
            )
        )
        await session.commit()

        manifest = await list_published_release_notes(session, limit=100)

    assert len(manifest.releases) == 37
    assert manifest.releases[0].id == "2026-08-11-member-name-preference-v2"
    assert manifest.releases[-1].id == "2026-07-14-bilingual-moderation-v2"
    assert all(release.title.en and release.title.ru for release in manifest.releases)
    assert all(release.feature.en and release.feature.ru for release in manifest.releases)
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

    await engine.dispose()


def test_seeded_release_history_is_localized_ordered_and_published_only():
    asyncio.run(_release_notes_scenario())
