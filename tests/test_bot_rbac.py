import asyncio

from fastapi import HTTPException, status

from src.modules.moderation.bot_rbac import ensure_bot_permission


class FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeResponse:
    def __init__(self, done: bool):
        self._done = done
        self.sent: list[dict] = []

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, content: str, ephemeral: bool = False):
        self.sent.append({"content": content, "ephemeral": ephemeral})


class FakeFollowup:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, content: str, ephemeral: bool = False):
        self.sent.append({"content": content, "ephemeral": ephemeral})


class FakeInteraction:
    def __init__(self, *, response_done: bool = True):
        self.guild = type("Guild", (), {"id": 123})()
        self.user = type("User", (), {"id": 456})()
        self.response = FakeResponse(response_done)
        self.followup = FakeFollowup()


async def _allowed_scenario(monkeypatch) -> None:
    import src.modules.moderation.bot_rbac as bot_rbac

    calls: list[dict] = []

    async def fake_assert_user_has_permission(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(bot_rbac, "get_async_session", lambda: FakeSessionContext())
    monkeypatch.setattr(bot_rbac, "assert_user_has_permission", fake_assert_user_has_permission)

    interaction = FakeInteraction()
    allowed = await ensure_bot_permission(
        interaction,
        "moderation.actions.apply.warn",
        locale="en",
    )

    assert allowed is True
    assert calls[0]["server_id"] == 123
    assert calls[0]["user_id"] == 456
    assert calls[0]["permission_key"] == "moderation.actions.apply.warn"
    assert interaction.followup.sent == []


async def _denied_scenario(monkeypatch) -> None:
    import src.modules.moderation.bot_rbac as bot_rbac

    async def fake_assert_user_has_permission(**kwargs):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission",
        )

    monkeypatch.setattr(bot_rbac, "get_async_session", lambda: FakeSessionContext())
    monkeypatch.setattr(bot_rbac, "assert_user_has_permission", fake_assert_user_has_permission)

    interaction = FakeInteraction(response_done=True)
    allowed = await ensure_bot_permission(
        interaction,
        "moderation.actions.apply.ban",
        locale="en",
    )

    assert allowed is False
    assert interaction.followup.sent == [
        {
            "content": "You do not have the required dashboard permission for this command: `moderation.actions.apply.ban`.",
            "ephemeral": True,
        }
    ]


def test_bot_rbac_allows_when_effective_permission_exists(monkeypatch):
    asyncio.run(_allowed_scenario(monkeypatch))


def test_bot_rbac_denies_with_ephemeral_followup(monkeypatch):
    asyncio.run(_denied_scenario(monkeypatch))
