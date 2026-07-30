from api.services.moderation_actions_service import _dashboard_monitoring_url
from src.modules.moderation.mod_log import build_monitoring_activity_log_embed


def test_monitoring_log_embed_links_to_server_monitoring_page(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://dash.example/")
    dashboard_url = _dashboard_monitoring_url(123)

    embed = build_monitoring_activity_log_embed(
        server_id=123,
        dashboard_url=dashboard_url,
        event_type="message",
        user_id=456,
        user_display="Member",
        channel_id=789,
        message_id=101112,
        message_content="hello",
        metadata={},
        locale="en",
    )

    assert dashboard_url == "https://dash.example/dashboard/123/monitoring"
    assert embed.url == dashboard_url
    assert embed.description == f"[Open in dashboard]({dashboard_url})"


def test_monitoring_log_embed_localizes_dashboard_link():
    dashboard_url = "https://dash.example/dashboard/123/monitoring"

    embed = build_monitoring_activity_log_embed(
        server_id=123,
        dashboard_url=dashboard_url,
        event_type="voice_join",
        user_id=456,
        user_display="Member",
        channel_id=789,
        message_id=None,
        message_content=None,
        metadata={},
        locale="ru",
    )

    assert embed.description == f"[Открыть в дашборде]({dashboard_url})"
