import ast
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from src.modules.observability.bot_metrics import DISCORD_GATEWAY_CONNECTED
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


def test_product_metric_families_are_registered_without_sensitive_labels():
    DISCORD_GATEWAY_CONNECTED.labels(bot_profile="cybercolors").set(0)
    DISCORD_GATEWAY_CONNECTED.labels(bot_profile="modral").set(0)
    metrics = generate_latest().decode()

    assert "cybercolors_discord_gateway_connected" in metrics
    assert (
        'cybercolors_discord_gateway_connected{bot_profile="cybercolors"} 0.0'
        in metrics
    )
    assert 'cybercolors_discord_gateway_connected{bot_profile="modral"} 0.0' in metrics
    assert "cybercolors_message_ingestion_queue_depth" in metrics
    assert "cybercolors_message_ingestion_messages_total" in metrics
    assert "cybercolors_ai_moderation_decisions_total" in metrics
    assert "cybercolors_ai_moderation_duration_seconds" in metrics


def test_discord_gateway_metric_recovers_after_a_session_resume():
    module = ast.parse(
        (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    )
    client_class = next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Aclient"
    )

    for handler_name in ("on_ready", "on_resumed"):
        handler = next(
            node
            for node in client_class.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == handler_name
        )
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "DISCORD_GATEWAY_STATUS"
            and node.func.attr == "set"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == 1
            for node in ast.walk(handler)
        )


def test_runtime_dashboard_tracks_both_discord_gateways():
    dashboard_path = (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "k8s"
        / "observability"
        / "dashboards"
        / "cybercolors-runtime.json"
    )
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    assert dashboard["title"] == "Modral / CyberColors Runtime"
    assert 'bot_profile="cybercolors"' in panels["CyberColors gateway"]["targets"][0]["expr"]
    assert 'bot_profile="modral"' in panels["Modral gateway"]["targets"][0]["expr"]
    assert "max by (bot_profile)" in panels["Discord gateway history"]["targets"][0]["expr"]
    assert "(cybercolors|modral)-.*" in panels["Pod readiness"]["targets"][0]["expr"]
