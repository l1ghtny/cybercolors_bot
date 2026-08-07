from prometheus_client import Counter, Gauge


DISCORD_GATEWAY_CONNECTED = Gauge(
    "cybercolors_discord_gateway_connected",
    "Whether a Discord application gateway is ready (1) or disconnected (0).",
    ("bot_profile",),
)
BIRTHDAY_ROLE_REMOVALS = Counter(
    "cybercolors_birthday_role_removals_total",
    "Birthday role removal attempts by outcome.",
    ("outcome",),
)
BIRTHDAY_ROLE_CLEANUP_MEMBERSHIPS = Counter(
    "cybercolors_birthday_role_cleanup_memberships_total",
    "Server memberships processed for birthday role cleanup by outcome.",
    ("outcome",),
)
BIRTHDAY_ROLE_CLEANUP_PENDING = Gauge(
    "cybercolors_birthday_role_cleanup_pending",
    "Server memberships still awaiting successful birthday role cleanup after the latest run.",
)
