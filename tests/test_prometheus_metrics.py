from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.modules.observability.prometheus import instrument_fastapi_app


def test_metrics_use_route_templates_not_request_values():
    app = FastAPI()
    instrument_fastapi_app(app, service_name="metrics-test")

    @app.get("/items/{item_id}")
    async def get_item(item_id: str):
        return {"id": item_id}

    with TestClient(app) as client:
        assert client.get("/items/secret-user-value").status_code == 200
        metrics = client.get("/metrics")

    assert metrics.status_code == 200
    assert (
        'cybercolors_http_requests_total{method="GET",route="/items/{item_id}",'
        'service="metrics-test",status="200"} 1.0'
    ) in metrics.text
