import asyncio
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.modules.ai.embeddings import KnowledgeEmbedder, get_knowledge_embedder


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return int(raw_value)


MAX_BATCH_SIZE = _env_int("AI_KNOWLEDGE_EMBEDDING_MAX_BATCH_SIZE", 64)
MAX_TEXT_CHARS = _env_int("AI_KNOWLEDGE_EMBEDDING_MAX_TEXT_CHARS", 20_000)
MAX_TOTAL_CHARS = _env_int("AI_KNOWLEDGE_EMBEDDING_MAX_TOTAL_CHARS", 100_000)
MAX_CONCURRENCY = _env_int("AI_KNOWLEDGE_EMBEDDING_MAX_CONCURRENCY", 1)


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class EmbeddingResponse(BaseModel):
    provider: str
    model: str
    dimensions: int
    embeddings: list[list[float]]


def create_embedding_app(
    embedder_loader: Callable[[], Awaitable[KnowledgeEmbedder]] = get_knowledge_embedder,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.embedder = await embedder_loader()
        app.state.inference_semaphore = asyncio.Semaphore(max(MAX_CONCURRENCY, 1))
        yield

    app = FastAPI(
        title="CyberColors Embedding Service",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        embedder = app.state.embedder
        return {
            "status": "ok",
            "provider": embedder.provider_name,
            "model": embedder.model,
            "dimensions": embedder.dimensions,
        }

    @app.post("/embed", response_model=EmbeddingResponse)
    async def embed(body: EmbeddingRequest):
        if len(body.texts) > MAX_BATCH_SIZE:
            raise HTTPException(status_code=413, detail=f"At most {MAX_BATCH_SIZE} texts are allowed.")
        if any(not text.strip() for text in body.texts):
            raise HTTPException(status_code=422, detail="Embedding texts must not be blank.")
        if any(len(text) > MAX_TEXT_CHARS for text in body.texts):
            raise HTTPException(
                status_code=413,
                detail=f"Each embedding text must be at most {MAX_TEXT_CHARS} characters.",
            )
        if sum(len(text) for text in body.texts) > MAX_TOTAL_CHARS:
            raise HTTPException(
                status_code=413,
                detail=f"Embedding request must be at most {MAX_TOTAL_CHARS} total characters.",
            )

        embedder = app.state.embedder
        try:
            async with app.state.inference_semaphore:
                embeddings = await embedder.embed_texts(body.texts)
            if len(embeddings) != len(body.texts):
                raise ValueError(
                    f"Embedding count mismatch: expected {len(body.texts)}, got {len(embeddings)}"
                )
            if any(len(vector) != embedder.dimensions for vector in embeddings):
                raise ValueError(f"Expected {embedder.dimensions}-dimensional embeddings.")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Embedding inference failed.") from exc

        return EmbeddingResponse(
            provider=embedder.provider_name,
            model=embedder.model,
            dimensions=embedder.dimensions,
            embeddings=embeddings,
        )

    return app


app = create_embedding_app()
