from fastapi import FastAPI, APIRouter
import fastapi_swagger_dark as fsd

from routers.auth import auth
from routers.birthdays import birthdays
from routers.replies import replies
from routers.servers import servers

app = FastAPI(title="CyberColors API", version="0.1.0", docs_url=None, redoc_url=None)


docs_router = APIRouter()
fsd.install(docs_router)

# Include your routes and the docs router
app.include_router(auth)
app.include_router(docs_router)
app.include_router(birthdays)
app.include_router(servers)
app.include_router(replies)