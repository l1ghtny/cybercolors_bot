from api.models.birthday_settings import BirthdaySettingsWarningModel
from api.services.discord_guilds import fetch_channel, fetch_current_bot_user, fetch_guild_member, fetch_guild_roles
from src.db.models import Server

ADMINISTRATOR = 1 << 3
VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
MANAGE_ROLES = 1 << 28
EMBED_LINKS = 1 << 14
MESSAGEABLE_CHANNEL_TYPES = {0, 5}


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _warning(target: str, key: str, message: str) -> BirthdaySettingsWarningModel:
    return BirthdaySettingsWarningModel(target=target, key=key, message=message)


def _role_id(role: dict) -> int | None:
    return _as_int(role.get("id"))


def _role_permissions(role: dict | None) -> int:
    if not role:
        return 0
    return _as_int(role.get("permissions")) or 0


def _member_role_ids(member: dict) -> set[int]:
    return {role_id for role_id in (_as_int(role_id) for role_id in member.get("roles", [])) if role_id is not None}


def _guild_permissions(server_id: int, roles: list[dict], member: dict) -> int:
    member_role_ids = _member_role_ids(member)
    permissions = 0
    for role in roles:
        role_id = _role_id(role)
        if role_id == server_id or role_id in member_role_ids:
            permissions |= _role_permissions(role)
    return permissions


def _top_role_position(roles: list[dict], role_ids: set[int]) -> int:
    positions = [int(role.get("position") or 0) for role in roles if _role_id(role) in role_ids]
    return max(positions, default=0)


def _apply_overwrite(permissions: int, overwrite: dict) -> int:
    deny = _as_int(overwrite.get("deny")) or 0
    allow = _as_int(overwrite.get("allow")) or 0
    return (permissions & ~deny) | allow


def _channel_permissions(server_id: int, bot_user_id: int, roles: list[dict], member: dict, channel: dict) -> int:
    permissions = _guild_permissions(server_id, roles, member)
    if permissions & ADMINISTRATOR:
        return permissions

    member_role_ids = _member_role_ids(member)
    overwrites = channel.get("permission_overwrites") or []

    everyone_overwrite = next((ow for ow in overwrites if _as_int(ow.get("id")) == server_id), None)
    if everyone_overwrite:
        permissions = _apply_overwrite(permissions, everyone_overwrite)

    role_deny = 0
    role_allow = 0
    for overwrite in overwrites:
        if _as_int(overwrite.get("type")) != 0:
            continue
        if _as_int(overwrite.get("id")) not in member_role_ids:
            continue
        role_deny |= _as_int(overwrite.get("deny")) or 0
        role_allow |= _as_int(overwrite.get("allow")) or 0
    permissions = (permissions & ~role_deny) | role_allow

    member_overwrite = next(
        (
            ow
            for ow in overwrites
            if _as_int(ow.get("type")) == 1 and _as_int(ow.get("id")) == bot_user_id
        ),
        None,
    )
    if member_overwrite:
        permissions = _apply_overwrite(permissions, member_overwrite)

    return permissions


def _missing_permissions(permissions: int, required: dict[int, str]) -> list[str]:
    if permissions & ADMINISTRATOR:
        return []
    return [label for bit, label in required.items() if not permissions & bit]


async def build_birthday_settings_warnings(server: Server) -> list[BirthdaySettingsWarningModel]:
    if not server.birthday_channel_id and not server.birthday_role_id:
        return []

    try:
        bot_user = await fetch_current_bot_user()
        bot_user_id = int(bot_user["id"])
        bot_member = await fetch_guild_member(server.server_id, bot_user_id)
        roles = await fetch_guild_roles(server.server_id)
    except Exception:
        return [
            _warning(
                "settings",
                "verification_failed",
                "Saved, but I could not verify the bot's Discord permissions. Check the bot role and channel permissions manually.",
            )
        ]

    if not bot_member:
        return [
            _warning(
                "settings",
                "bot_not_member",
                "Saved, but the bot is not visible as a member of this server, so birthday automation will not run.",
            )
        ]

    warnings: list[BirthdaySettingsWarningModel] = []
    guild_permissions = _guild_permissions(server.server_id, roles, bot_member)

    if server.birthday_role_id:
        target_role = next((role for role in roles if _role_id(role) == server.birthday_role_id), None)
        if not target_role:
            warnings.append(
                _warning(
                    "role",
                    "role_not_found",
                    "Saved, but Discord did not return this birthday role. The bot will not be able to assign it.",
                )
            )
        else:
            if target_role.get("managed") or _role_id(target_role) == server.server_id:
                warnings.append(
                    _warning(
                        "role",
                        "role_not_assignable",
                        "Saved, but this role is managed by Discord or is @everyone, so the bot cannot assign it.",
                    )
                )

            missing = _missing_permissions(guild_permissions, {MANAGE_ROLES: "Manage Roles"})
            if missing:
                warnings.append(
                    _warning(
                        "role",
                        "bot_missing_manage_roles",
                        "Saved, but the bot is missing Manage Roles, so it cannot assign the birthday role.",
                    )
                )

            bot_top_position = _top_role_position(roles, _member_role_ids(bot_member))
            target_position = int(target_role.get("position") or 0)
            if bot_top_position <= target_position:
                warnings.append(
                    _warning(
                        "role",
                        "bot_role_too_low",
                        "Saved, but the bot's highest role is not above the birthday role. Move the bot role higher in Discord.",
                    )
                )

    if server.birthday_channel_id:
        try:
            channel = await fetch_channel(server.server_id, server.birthday_channel_id)
        except Exception:
            channel = None

        if not channel:
            warnings.append(
                _warning(
                    "channel",
                    "channel_not_found",
                    "Saved, but Discord did not return this birthday channel. The bot will not be able to post there.",
                )
            )
        else:
            channel_type = _as_int(channel.get("type"))
            if channel_type not in MESSAGEABLE_CHANNEL_TYPES:
                warnings.append(
                    _warning(
                        "channel",
                        "unsupported_channel_type",
                        "Saved, but birthday announcements should use a text or announcement channel.",
                    )
                )

            channel_permissions = _channel_permissions(server.server_id, bot_user_id, roles, bot_member, channel)
            missing = _missing_permissions(
                channel_permissions,
                {
                    VIEW_CHANNEL: "View Channel",
                    SEND_MESSAGES: "Send Messages",
                    EMBED_LINKS: "Embed Links",
                },
            )
            if missing:
                warnings.append(
                    _warning(
                        "channel",
                        "bot_missing_channel_permissions",
                        "Saved, but the bot is missing channel permissions for birthday announcements: "
                        + ", ".join(missing)
                        + ".",
                    )
                )

    return warnings