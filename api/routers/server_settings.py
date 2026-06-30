from fastapi import APIRouter

from api.routers.rbac import rbac_router
from api.routers.server_ai import server_ai_router
from api.routers.server_ai_settings import server_ai_settings_router
from api.routers.server_ai_stream import server_ai_stream_router
from api.routers.server_localization import server_localization_router
from api.routers.server_moderation_settings import server_moderation_settings_router
from api.routers.server_temp_voice import server_temp_voice_router
from api.routers.server_security import server_security_router

server_settings = APIRouter()

server_settings.include_router(rbac_router, tags=["servers:rbac"])
server_settings.include_router(server_security_router, tags=["servers:security"])
server_settings.include_router(server_ai_settings_router, tags=["servers:ai-settings"])
server_settings.include_router(server_ai_router, tags=["servers:ai"])
server_settings.include_router(server_ai_stream_router, tags=["servers:ai"])
server_settings.include_router(server_moderation_settings_router, tags=["servers:moderation-settings"])
server_settings.include_router(server_temp_voice_router, tags=["servers:temp-voice"])
server_settings.include_router(server_localization_router, tags=["servers:localization"])
