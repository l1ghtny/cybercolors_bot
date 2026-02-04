from fastapi import FastAPI, APIRouter
import fastapi_swagger_dark as fsd
from starlette.middleware.cors import CORSMiddleware

from api.routers.auth import auth
from api.routers.birthdays import birthdays
from api.routers.moderation import moderation
from api.routers.replies import replies
from api.routers.servers import servers

app = FastAPI(title="CyberColors API", version="0.1.0", docs_url=None, redoc_url=None)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


docs_router = APIRouter()
fsd.install(docs_router)

# Include your routes and the docs router
app.include_router(auth)
app.include_router(docs_router)
app.include_router(birthdays)
app.include_router(servers)
app.include_router(replies)
app.include_router(moderation)
