from fastapi import APIRouter

from api.routers.moderation_actions import moderation_actions_router
from api.routers.moderation_cases import moderation_cases_router
from api.routers.moderation_users import moderation_users_router

moderation = APIRouter(prefix="/moderation")

moderation.include_router(moderation_actions_router, tags=["moderation:actions"])
moderation.include_router(moderation_cases_router, tags=["moderation:cases"])
moderation.include_router(moderation_users_router, tags=["moderation:users"])
