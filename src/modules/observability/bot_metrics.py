from prometheus_client import Gauge


DISCORD_GATEWAY_CONNECTED = Gauge(
    "cybercolors_discord_gateway_connected",
    "Whether a Discord application gateway is ready (1) or disconnected (0).",
    ("bot_profile",),
)
