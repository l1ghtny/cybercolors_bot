import asyncio
import os
from functools import lru_cache
from threading import Lock
from typing import Protocol

import aiohttp
from openai import AsyncOpenAI


DEFAULT_KNOWLEDGE_EMBEDDING_PROVIDER = "local"
DEFAULT_LOCAL_KNOWLEDGE_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_OPENAI_KNOWLEDGE_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_KNOWLEDGE_EMBEDDING_DIMENSIONS = 1024
DEFAULT_KNOWLEDGE_EMBEDDING_SERVICE_URL = "http://cybercolors-embeddings"
DEFAULT_KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS = 180


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return int(raw_value)


KNOWLEDGE_EMBEDDING_PROVIDER = (
    os.getenv("AI_KNOWLEDGE_EMBEDDING_PROVIDER") or DEFAULT_KNOWLEDGE_EMBEDDING_PROVIDER
).strip().lower()
KNOWLEDGE_EMBEDDING_DIMENSIONS = _env_int(
    "AI_KNOWLEDGE_EMBEDDING_DIMENSIONS",
    DEFAULT_KNOWLEDGE_EMBEDDING_DIMENSIONS,
)
KNOWLEDGE_LOCAL_EMBEDDING_MODEL = (
    os.getenv("AI_KNOWLEDGE_LOCAL_EMBEDDING_MODEL") or DEFAULT_LOCAL_KNOWLEDGE_EMBEDDING_MODEL
)
KNOWLEDGE_OPENAI_EMBEDDING_MODEL = (
    os.getenv("AI_KNOWLEDGE_OPENAI_EMBEDDING_MODEL")
    or os.getenv("AI_KNOWLEDGE_EMBEDDING_MODEL")
    or DEFAULT_OPENAI_KNOWLEDGE_EMBEDDING_MODEL
)
KNOWLEDGE_EMBEDDING_SERVICE_URL = (
    os.getenv("AI_KNOWLEDGE_EMBEDDING_SERVICE_URL") or DEFAULT_KNOWLEDGE_EMBEDDING_SERVICE_URL
).rstrip("/")
KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS = _env_int(
    "AI_KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS",
    DEFAULT_KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS,
)
KNOWLEDGE_EMBEDDING_MODEL = (
    KNOWLEDGE_OPENAI_EMBEDDING_MODEL
    if KNOWLEDGE_EMBEDDING_PROVIDER == "openai"
    else os.getenv("AI_KNOWLEDGE_EMBEDDING_MODEL") or KNOWLEDGE_LOCAL_EMBEDDING_MODEL
)


class KnowledgeEmbedder(Protocol):
    provider_name: str
    model: str
    dimensions: int

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAIKnowledgeEmbedder:
    provider_name = "openai"

    def __init__(
        self,
        *,
        client: AsyncOpenAI | None = None,
        model: str = KNOWLEDGE_OPENAI_EMBEDDING_MODEL,
        dimensions: int = KNOWLEDGE_EMBEDDING_DIMENSIONS,
    ) -> None:
        self.client = client or AsyncOpenAI()
        self.model = model
        self.dimensions = dimensions

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
        )
        embeddings = [list(item.embedding) for item in response.data]
        self._validate_embeddings(embeddings)
        return embeddings

    def _validate_embeddings(self, embeddings: list[list[float]]) -> None:
        for embedding in embeddings:
            if len(embedding) != self.dimensions:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {self.dimensions}, got {len(embedding)}"
                )


class RemoteKnowledgeEmbedder:
    provider_name = "local"

    def __init__(
        self,
        *,
        service_url: str = KNOWLEDGE_EMBEDDING_SERVICE_URL,
        timeout_seconds: int = KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS,
        model: str = KNOWLEDGE_LOCAL_EMBEDDING_MODEL,
        dimensions: int = KNOWLEDGE_EMBEDDING_DIMENSIONS,
    ) -> None:
        self.service_url = service_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.dimensions = dimensions

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.service_url}/embed", json={"texts": texts}) as response:
                    if response.status != 200:
                        detail = (await response.text())[:500]
                        raise RuntimeError(
                            f"Embedding service returned HTTP {response.status}: {detail}"
                        )
                    payload = await response.json()
        except TimeoutError as exc:
            raise RuntimeError(
                f"Embedding service timed out after {self.timeout_seconds} seconds."
            ) from exc
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"Embedding service request failed: {exc}") from exc

        response_model = payload.get("model")
        response_dimensions = payload.get("dimensions")
        if response_model != self.model or response_dimensions != self.dimensions:
            raise ValueError(
                "Embedding service configuration mismatch: "
                f"expected {self.model}/{self.dimensions}, got {response_model}/{response_dimensions}"
            )

        raw_embeddings = payload.get("embeddings")
        if not isinstance(raw_embeddings, list) or len(raw_embeddings) != len(texts):
            raise ValueError(
                f"Embedding count mismatch: expected {len(texts)}, got "
                f"{len(raw_embeddings) if isinstance(raw_embeddings, list) else 'invalid response'}"
            )

        embeddings = [[float(item) for item in vector] for vector in raw_embeddings]
        for embedding in embeddings:
            if len(embedding) != self.dimensions:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {self.dimensions}, got {len(embedding)}"
                )
        return embeddings


class LocalSentenceTransformerEmbedder:
    provider_name = "local"

    def __init__(
        self,
        *,
        model: str = KNOWLEDGE_LOCAL_EMBEDDING_MODEL,
        dimensions: int = KNOWLEDGE_EMBEDDING_DIMENSIONS,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for local AI knowledge embeddings. "
                "Install the embedding dependencies with `uv sync --group embeddings`, use the "
                "embedding service provider, or set AI_KNOWLEDGE_EMBEDDING_PROVIDER=openai."
            ) from exc

        self.model = model
        self.dimensions = dimensions
        self._model = SentenceTransformer(model)
        self._encode_lock = Lock()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        def encode():
            with self._encode_lock:
                return self._model.encode(
                    texts,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )

        embeddings = await asyncio.to_thread(encode)
        vectors = embeddings.tolist()
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ValueError(
                    f"Embedding dimension mismatch for {self.model}: expected {self.dimensions}, got {len(vector)}"
                )
        return [[float(item) for item in vector] for vector in vectors]


_KNOWLEDGE_EMBEDDER_BUILD_LOCK = Lock()


@lru_cache(maxsize=4)
def _build_knowledge_embedder_cached(
    provider: str,
    local_model: str,
    openai_model: str,
    dimensions: int,
    service_url: str,
    timeout_seconds: int,
) -> KnowledgeEmbedder:
    if provider == "openai":
        return OpenAIKnowledgeEmbedder(model=openai_model, dimensions=dimensions)
    if provider == "remote":
        return RemoteKnowledgeEmbedder(
            service_url=service_url,
            timeout_seconds=timeout_seconds,
            model=local_model,
            dimensions=dimensions,
        )
    if provider == "local":
        return LocalSentenceTransformerEmbedder(model=local_model, dimensions=dimensions)
    raise ValueError(
        "Unsupported AI knowledge embedding provider: "
        f"{provider!r}. Expected 'local', 'remote', or 'openai'."
    )


def build_knowledge_embedder() -> KnowledgeEmbedder:
    with _KNOWLEDGE_EMBEDDER_BUILD_LOCK:
        return _build_knowledge_embedder_cached(
            KNOWLEDGE_EMBEDDING_PROVIDER,
            KNOWLEDGE_LOCAL_EMBEDDING_MODEL,
            KNOWLEDGE_OPENAI_EMBEDDING_MODEL,
            KNOWLEDGE_EMBEDDING_DIMENSIONS,
            KNOWLEDGE_EMBEDDING_SERVICE_URL,
            KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS,
        )


async def get_knowledge_embedder() -> KnowledgeEmbedder:
    return await asyncio.to_thread(build_knowledge_embedder)
