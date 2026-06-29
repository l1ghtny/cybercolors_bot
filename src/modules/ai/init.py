from src.modules.ai.ai_main import AIMain
from src.modules.ai.context import ChannelFetcher
from src.modules.ai.providers import AIProvider


def create_ai_main(
    provider: AIProvider | None = None,
    model: str | None = None,
    channel_fetcher: ChannelFetcher | None = None,
) -> AIMain:
    return AIMain(provider=provider, model=model, channel_fetcher=channel_fetcher)
