import asyncio
from collections.abc import Iterable

from fastapi import HTTPException, status

from api.services.discord_guilds import (
    add_guild_member_role,
    fetch_guild_channels,
    fetch_guild_roles,
    remove_guild_member_role,
    update_channel_role_overwrite,
    update_guild_role_permissions,
)
from src.db.models import ServerSecuritySettings

CATEGORY_CHANNEL_TYPE = 4
TEXT_CHANNEL_TYPES = {0, 5, 15, 16}
VOICE_CHANNEL_TYPES = {2, 13}

PERMISSION_STREAM = 1 << 9
PERMISSION_EMBED_LINKS = 1 << 14
PERMISSION_ATTACH_FILES = 1 << 15
PERMISSION_USE_APPLICATION_COMMANDS = 1 << 31
PERMISSION_CREATE_PUBLIC_THREADS = 1 << 35
PERMISSION_CREATE_PRIVATE_THREADS = 1 << 36

# These are never safe to copy from a role selected as the normal member role.
DANGEROUS_MEMBER_PERMISSIONS = (
    (1 << 1)   # KICK_MEMBERS
    | (1 << 2)  # BAN_MEMBERS
    | (1 << 3)  # ADMINISTRATOR
    | (1 << 4)  # MANAGE_CHANNELS
    | (1 << 5)  # MANAGE_GUILD
    | (1 << 13) # MANAGE_MESSAGES
    | (1 << 28) # MANAGE_ROLES
    | (1 << 29) # MANAGE_WEBHOOKS
    | (1 << 40) # MODERATE_MEMBERS
)


def newcomer_restriction_mask(
    settings: ServerSecuritySettings,
    channel_type: int,
) -> int:
    mask = 0
    is_text = channel_type in TEXT_CHANNEL_TYPES
    is_voice = channel_type in VOICE_CHANNEL_TYPES
    is_category = channel_type == CATEGORY_CHANNEL_TYPE

    if settings.newcomer_block_bot_commands and (is_text or is_category):
        mask |= PERMISSION_USE_APPLICATION_COMMANDS
    if settings.newcomer_block_attachments and (is_text or is_category):
        mask |= PERMISSION_ATTACH_FILES
    if settings.newcomer_block_embeds and (is_text or is_category):
        mask |= PERMISSION_EMBED_LINKS
    if settings.newcomer_block_threads and (is_text or is_category):
        mask |= (
            PERMISSION_CREATE_PUBLIC_THREADS
            | PERMISSION_CREATE_PRIVATE_THREADS
        )
    if settings.newcomer_block_streaming and (is_voice or is_category):
        mask |= PERMISSION_STREAM
    return mask


def newcomer_base_restriction_mask(settings: ServerSecuritySettings) -> int:
    return (
        newcomer_restriction_mask(settings, CATEGORY_CHANNEL_TYPE)
        | newcomer_restriction_mask(settings, 0)
        | newcomer_restriction_mask(settings, 2)
    )


def _role_overwrite(channel: dict, role_id: int) -> tuple[int, int]:
    for overwrite in channel.get("permission_overwrites") or []:
        if str(overwrite.get("id")) != str(role_id):
            continue
        if int(overwrite.get("type", 0)) != 0:
            continue
        return int(overwrite.get("allow") or 0), int(overwrite.get("deny") or 0)
    return 0, 0


def _role_permissions(roles: Iterable[dict], role_id: int) -> int | None:
    for role in roles:
        if str(role.get("id")) == str(role_id):
            return int(role.get("permissions") or 0)
    return None


def assert_newcomer_role_configuration(
    settings: ServerSecuritySettings,
    *,
    require_member_role: bool = True,
) -> tuple[int, int | None]:
    if settings.newcomer_role_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="newcomer_role_id is not configured",
        )
    if require_member_role and settings.newcomer_member_role_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="newcomer_member_role_id is not configured",
        )
    if (
        settings.newcomer_member_role_id is not None
        and settings.newcomer_role_id == settings.newcomer_member_role_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The newcomer and member roles must be different",
        )
    return settings.newcomer_role_id, settings.newcomer_member_role_id


async def apply_newcomer_restriction_template(
    *,
    server_id: int,
    settings: ServerSecuritySettings,
) -> tuple[int, int]:
    newcomer_role_id, member_role_id = assert_newcomer_role_configuration(settings)
    if member_role_id is None:
        raise AssertionError("member role is required for the newcomer template")
    if settings.role_mutations_paused:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Role mutations are paused by server security settings",
        )

    roles, channels = await asyncio.gather(
        fetch_guild_roles(server_id),
        fetch_guild_channels(server_id),
    )
    member_permissions = _role_permissions(roles, member_role_id)
    if member_permissions is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="newcomer_member_role_id is not available in this server",
        )
    if member_permissions & DANGEROUS_MEMBER_PERMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The selected member role has moderation or administrator permissions and cannot be copied",
        )

    await update_guild_role_permissions(
        server_id=server_id,
        role_id=newcomer_role_id,
        permissions=member_permissions & ~newcomer_base_restriction_mask(settings),
    )

    updated = 0
    skipped = 0
    for channel in channels:
        channel_id = channel.get("id")
        channel_type = channel.get("type")
        if channel_id is None or not isinstance(channel_type, int):
            skipped += 1
            continue
        mask = newcomer_restriction_mask(settings, channel_type)
        if not mask:
            skipped += 1
            continue
        source_allow, source_deny = _role_overwrite(channel, member_role_id)
        await update_channel_role_overwrite(
            int(channel_id),
            newcomer_role_id,
            allow=source_allow & ~mask,
            deny=source_deny | mask,
        )
        updated += 1
        # Stay well under Discord's global REST request limit on large guilds.
        await asyncio.sleep(0.05)

    return updated, skipped


async def promote_newcomer_member(
    *,
    server_id: int,
    user_id: int,
    settings: ServerSecuritySettings,
    current_role_ids: set[int] | None = None,
) -> None:
    newcomer_role_id, member_role_id = assert_newcomer_role_configuration(settings)
    if member_role_id is None:
        raise AssertionError("member role is required for promotion")
    if current_role_ids is None or member_role_id not in current_role_ids:
        await add_guild_member_role(server_id, user_id, member_role_id)
    if current_role_ids is None or newcomer_role_id in current_role_ids:
        await remove_guild_member_role(server_id, user_id, newcomer_role_id)


async def reapply_newcomer_member(
    *,
    server_id: int,
    user_id: int,
    settings: ServerSecuritySettings,
) -> None:
    newcomer_role_id, member_role_id = assert_newcomer_role_configuration(settings)
    await add_guild_member_role(server_id, user_id, newcomer_role_id)
    if member_role_id is not None:
        await remove_guild_member_role(server_id, user_id, member_role_id)
