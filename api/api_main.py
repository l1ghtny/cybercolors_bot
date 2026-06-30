import os

from fastapi import FastAPI, APIRouter
import fastapi_swagger_dark as fsd
from starlette.middleware.cors import CORSMiddleware

from api.routers.auth import auth
from api.routers.activity import activity
from api.routers.birthdays import birthdays
from api.routers.bot_commands import bot_commands
from api.routers.moderation import moderation
from api.routers.replies import replies
from api.routers.servers import servers
from api.routers.server_settings import server_settings

app = FastAPI(title="CyberColors API", version="0.1.0", docs_url=None, redoc_url=None)


def _csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://id-preview--ee4421b9-d859-42bd-b506-4c32a5dc1982.lovable.app",
    "https://preview--bot-pal-dash.lovable.app",
    *_csv_env("CORS_ALLOWED_ORIGINS"),
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https://([a-z0-9-]+\.)?(lovable\.app|lovableproject\.com)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


docs_router = APIRouter()
fsd.install(docs_router)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}

# Include your routes and the docs router
app.include_router(auth)
app.include_router(docs_router)
app.include_router(activity)
app.include_router(birthdays)
app.include_router(bot_commands)
app.include_router(servers)
app.include_router(server_settings)
app.include_router(replies)
app.include_router(moderation)
