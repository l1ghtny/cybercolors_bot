import discord

from src.db.models import ServerReplySettings
from src.modules.discord_mentions import allowed_explicit_mentions
from src.modules.on_message_processing.reply_matcher import (
    CompiledReplySettings,
    claim_reply_cooldown,
    get_reply_matcher,
)


def automatic_reply_allowed(
    message,
    settings: ServerReplySettings | CompiledReplySettings | None,
) -> bool:
    if settings is None:
        return True

    channel_ids = {str(message.channel.id)}
    parent_id = getattr(message.channel, "parent_id", None)
    if parent_id is None:
        parent_id = getattr(getattr(message.channel, "parent", None), "id", None)
    if parent_id is not None:
        channel_ids.add(str(parent_id))

    included_channels = set(settings.included_channel_ids or [])
    excluded_channels = set(settings.excluded_channel_ids or [])
    if excluded_channels.intersection(channel_ids):
        return False
    if included_channels and not included_channels.intersection(channel_ids):
        return False

    author = message.author
    if str(author.id) in set(settings.excluded_user_ids or []):
        return False
    author_role_ids = {
        str(role.id)
        for role in (getattr(author, "roles", None) or [])
    }
    if set(settings.excluded_role_ids or []).intersection(author_role_ids):
        return False
    return True


async def check_for_replies(message):
    server_id = message.guild.id
    matcher = await get_reply_matcher(server_id)
    if not automatic_reply_allowed(message, matcher.settings):
        return False, server_id

    matched_rule = matcher.match(message.content)
    if matched_rule is None:
        return False, server_id
    if not claim_reply_cooldown(server_id, matched_rule):
        return False, server_id

    await send_reply(
        message,
        matched_rule.response_text,
        matched_rule.is_fstring,
        allowed_user_ids=matched_rule.mention_user_ids,
        allowed_role_ids=matched_rule.mention_role_ids,
    )
    return True, server_id

async def send_reply(
    message,
    response_text,
    is_fstring,
    *,
    allowed_user_ids: frozenset[str] = frozenset(),
    allowed_role_ids: frozenset[str] = frozenset(),
):
    if is_fstring:
        try:
            # Dangerous, but maintaining compatibility with existing logic
            # Using eval to process f-string. 
            # Note: We need to be careful about what variables are available in eval.
            processed_response = eval(response_text)
            if message.content.isupper():
                processed_response = processed_response.upper()
            await _send_reply(
                message,
                processed_response,
                allowed_user_ids=allowed_user_ids,
                allowed_role_ids=allowed_role_ids,
            )
        except Exception:
            # Fallback to literal if eval fails
            final_resp = response_text.upper() if message.content.isupper() else response_text
            await _send_reply(
                message,
                final_resp,
                allowed_user_ids=allowed_user_ids,
                allowed_role_ids=allowed_role_ids,
            )
    else:
        final_resp = response_text.upper() if message.content.isupper() else response_text
        await _send_reply(
            message,
            final_resp,
            allowed_user_ids=allowed_user_ids,
            allowed_role_ids=allowed_role_ids,
        )


async def _send_reply(
    message,
    content: str,
    *,
    allowed_user_ids: frozenset[str] = frozenset(),
    allowed_role_ids: frozenset[str] = frozenset(),
) -> None:
    user_ids, role_ids = allowed_explicit_mentions(
        content,
        allowed_user_ids=allowed_user_ids,
        allowed_role_ids=allowed_role_ids,
    )
    allowed_mentions = discord.AllowedMentions(
        everyone=False,
        users=[discord.Object(id=user_id) for user_id in user_ids] if user_ids else False,
        roles=[discord.Object(id=role_id) for role_id in role_ids] if role_ids else False,
        replied_user=False,
    )
    await message.reply(
        content,
        mention_author=False,
        allowed_mentions=allowed_mentions,
    )
