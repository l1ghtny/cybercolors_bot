from prometheus_client import Gauge


DISCORD_GATEWAY_CONNECTED = Gauge(
    "cybercolors_discord_gateway_connected",
    "Whether the CyberColors Discord gateway is ready (1) or disconnected (0).",
)
