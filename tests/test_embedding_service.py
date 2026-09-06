import asyncio
import pytest

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


@pytest.mark.parametrize("texts,expected_sizes", [
    ([str(i) for i in range(77)], [64, 13]),
    (["x" * 2000 for _ in range(60)], [50, 10]),
])
def test_remote_embedder_batches_against_real_service_limits(monkeypatch, texts, expected_sizes):
    import src.modules.ai.embeddings as module
    calls = []
    with TestClient(create_embedding_app(load_fake_embedder)) as client:
        class Response:
            def __init__(self, response):
                self.response = response
                self.status = response.status_code
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def json(self): return self.response.json()
            async def text(self): return self.response.text
        class Session:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def post(self, url, *, json):
                calls.append(json["texts"])
                return Response(client.post("/embed", json=json))
        monkeypatch.setattr(module.aiohttp, "ClientSession", Session)
        result = asyncio.run(RemoteKnowledgeEmbedder(model="test-model", dimensions=3).embed_texts(texts))
    assert [len(batch) for batch in calls] == expected_sizes
    assert [text for batch in calls for text in batch] == texts
    assert result == [[float(len(text)), 1.0, 2.0] for text in texts]


def test_remote_embedder_does_not_return_partial_vectors_after_later_batch_failure(monkeypatch):
    embedder = RemoteKnowledgeEmbedder(dimensions=3)
    calls = []
    async def embed_batch(session, texts):
        calls.append(texts)
        if len(calls) == 2:
            raise RuntimeError("service unavailable")
        return [[1.0, 2.0, 3.0] for _ in texts]
    monkeypatch.setattr(embedder, "_embed_batch", embed_batch)
    with pytest.raises(RuntimeError, match="service unavailable"):
        asyncio.run(embedder.embed_texts(["text"] * 77))
    assert [len(batch) for batch in calls] == [64, 13]


def test_remote_embedder_validates_all_inputs_before_first_request(monkeypatch):
    embedder = RemoteKnowledgeEmbedder()
    async def unexpected_request(*args):
        raise AssertionError("invalid input must fail before sending a request")
    monkeypatch.setattr(embedder, "_embed_batch", unexpected_request)
    with pytest.raises(ValueError, match="request limits"):
        asyncio.run(embedder.embed_texts(["valid"] * 64 + ["x" * 20_001]))
