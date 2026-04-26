from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.database import get_async_session
from src.db.models import Server, ServerLocalizationSettings
from src.modules.localization.catalog import DEFAULT_LOCALE, SUPPORTED_LOCALES, TRANSLATIONS


def normalize_locale_code(locale_code: str | None) -> str:
    if not locale_code:
        return DEFAULT_LOCALE
    return locale_code.strip().lower()


def is_supported_locale(locale_code: str | None) -> bool:
    return normalize_locale_code(locale_code) in SUPPORTED_LOCALES


async def get_or_create_server_localization_settings(
    session: AsyncSession,
    server_id: int,
    server_name: str | None = None,
) -> ServerLocalizationSettings:
    server = await session.get(Server, server_id)
    if not server:
        server = Server(server_id=server_id, server_name=server_name or str(server_id))
        session.add(server)
        await session.flush()

    settings = await session.get(ServerLocalizationSettings, server_id)
    if settings:
        return settings

    settings = ServerLocalizationSettings(server_id=server_id, locale_code=DEFAULT_LOCALE)
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


async def get_server_locale(server_id: int) -> str:
    async with get_async_session() as session:
        settings = await get_or_create_server_localization_settings(session=session, server_id=server_id)
        return normalize_locale_code(settings.locale_code)


async def set_server_locale(server_id: int, server_name: str | None, locale_code: str) -> str:
    normalized = normalize_locale_code(locale_code)
    if normalized not in SUPPORTED_LOCALES:
        raise ValueError("Unsupported locale code")
    async with get_async_session() as session:
        settings = await get_or_create_server_localization_settings(
            session=session,
            server_id=server_id,
            server_name=server_name,
        )
        settings.locale_code = normalized
        session.add(settings)
        await session.commit()
    return normalized


def tr(locale_code: str | None, key: str, **kwargs) -> str:
    locale = normalize_locale_code(locale_code)
    template = (
        TRANSLATIONS.get(locale, {}).get(key)
        or TRANSLATIONS[DEFAULT_LOCALE].get(key)
        or key
    )
    if not kwargs:
        return template
    return template.format(**kwargs)
