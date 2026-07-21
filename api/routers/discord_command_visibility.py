from fastapi import APIRouter, Depends, HTTPException

from api.dependencies.auth import get_bearer_access_token
from api.dependencies.server_access import require_server_permission
from api.models.discord_command_visibility import (
    DiscordCommandVisibilityReadModel,
    DiscordCommandVisibilityWriteModel,
    DiscordCommandVisibilityWriteResponseModel,
)
from api.services.discord_command_visibility import DiscordVisibilityError, read_visibility, write_visibility


discord_command_visibility_router = APIRouter(prefix="/servers/{server_id}/discord-command-visibility")
_require_visibility_management = require_server_permission("commands.visibility.manage")


def _raise(error: DiscordVisibilityError) -> None:
    raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.detail})


@discord_command_visibility_router.get("", response_model=DiscordCommandVisibilityReadModel)
async def get_discord_command_visibility(
    server_id: int,
    _: int = Depends(_require_visibility_management),
    access_token: str = Depends(get_bearer_access_token),
):
    try:
        return await read_visibility(server_id, access_token)
    except DiscordVisibilityError as error:
        _raise(error)


@discord_command_visibility_router.put("", response_model=DiscordCommandVisibilityWriteResponseModel)
async def put_discord_command_visibility(
    server_id: int,
    body: DiscordCommandVisibilityWriteModel,
    _: int = Depends(_require_visibility_management),
    access_token: str = Depends(get_bearer_access_token),
):
    try:
        return await write_visibility(server_id, access_token, body.snapshot_id, body.updates)
    except DiscordVisibilityError as error:
        _raise(error)
