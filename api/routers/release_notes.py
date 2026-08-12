from fastapi import APIRouter, Depends, Query, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.release_notes import (
    PublicProductUpdatesManifestModel,
    ReleaseNotesManifestModel,
)
from api.services.release_notes import (
    list_public_product_updates,
    list_published_release_notes,
)
from src.db.database import get_session


release_notes = APIRouter(prefix="/release-notes", tags=["release-notes"])


@release_notes.get("", response_model=ReleaseNotesManifestModel)
async def get_release_notes(
    response: Response,
    limit: int = Query(default=30, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    return await list_published_release_notes(session, limit=limit)


@release_notes.get("/public", response_model=PublicProductUpdatesManifestModel)
async def get_public_product_updates(
    response: Response,
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = (
        "public, max-age=300, stale-while-revalidate=86400"
    )
    return await list_public_product_updates(session, limit=limit)
