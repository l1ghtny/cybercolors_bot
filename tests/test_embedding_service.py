from fastapi.testclient import TestClient

from src.modules.ai.embedding_service import create_embedding_app
from src.modules.ai.embeddings import RemoteKnowledgeEmbedder


class FakeEmbedder:
    provider_name = "local"
    model = "test-model"
    dimensions = 3

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 2.0] for text in texts]


async def load_fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


def test_remote_embedder_preserves_the_local_vector_identity():
    embedder = RemoteKnowledgeEmbedder(
        service_url="http://embeddings.test/",
        timeout_seconds=30,
        model="test-model",
        dimensions=3,
    )

    assert embedder.provider_name == "local"
    assert embedder.service_url == "http://embeddings.test"
    assert embedder.model == "test-model"
    assert embedder.dimensions == 3


def test_embedding_service_health_and_embedding_contract():
    with TestClient(create_embedding_app(load_fake_embedder)) as client:
        health = client.get("/healthz")
        response = client.post("/embed", json={"texts": ["hello", "world!"]})

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "provider": "local",
        "model": "test-model",
        "dimensions": 3,
    }
    assert response.status_code == 200
    assert response.json() == {
        "provider": "local",
        "model": "test-model",
        "dimensions": 3,
        "embeddings": [[5.0, 1.0, 2.0], [6.0, 1.0, 2.0]],
    }


def test_embedding_service_rejects_blank_texts():
    with TestClient(create_embedding_app(load_fake_embedder)) as client:
        response = client.post("/embed", json={"texts": ["  "]})

    assert response.status_code == 422
    assert response.json()["detail"] == "Embedding texts must not be blank."
