from fastapi import APIRouter

from api.routers.server_localization import server_localization_router
from api.routers.server_moderation_settings import server_moderation_settings_router
from api.routers.server_security import server_security_router

server_settings = APIRouter()

server_settings.include_router(server_security_router, tags=["servers:security"])
server_settings.include_router(server_moderation_settings_router, tags=["servers:moderation-settings"])
server_settings.include_router(server_localization_router, tags=["servers:localization"])
