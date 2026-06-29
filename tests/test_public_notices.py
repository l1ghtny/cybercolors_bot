from types import SimpleNamespace

import discord

from src.modules.moderation.public_notices import send_public_action_notice


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content, allowed_mentions=None):
        self.sent.append({"content": content, "allowed_mentions": allowed_mentions})


def test_public_action_notice_sends_to_interaction_channel_without_pings():
    channel = FakeChannel()
    interaction = SimpleNamespace(channel=channel, guild=SimpleNamespace(id=123))

    import asyncio

    sent = asyncio.run(send_public_action_notice(interaction, "<@456> warned"))

    assert sent is True
    assert channel.sent[0]["content"] == "<@456> warned"
    assert isinstance(channel.sent[0]["allowed_mentions"], discord.AllowedMentions)
    assert channel.sent[0]["allowed_mentions"].to_dict() == {"parse": []}