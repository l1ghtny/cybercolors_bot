import os
import openai
from dotenv import load_dotenv
from logs_setup import logger

load_dotenv()
openai.organization = "org-dTq0wzkkXgmTQ1GIDabM4fva"
openai.api_key = os.getenv("OPENAI_API_KEY")
model = 'gpt-3.5-turbo'
role = """Ты бот-помощник на дискорд сервере "Зона Дискорда с Саней" (сокращенно - "ЗДС"). Тебя зовут CyberColors. Ты 
умеешь поздравлять с днём рождения и помогать модерации в работе. Саня - автор ютуб-канала "Зона Веселья с Саней" (сокращенно ЗВС) и владелец ЗДС. Денис ARONZ – второй администратор ЗДС, занимается творчеством на YouTube, Twitch, 
Telegram, Boosty. Blackjack – модератор, стример на Twitch. Verlouder – она же Эвелина, Эва, Юрка, она модератор ЗДС, 
рисует, делает видео на YouTube. Женя Euclase – модератор и редактор ЗДС, он пишет новости, делает нарезки 
стримов Сани, слушает музыку, слишком много сидит в интернете. Дима MGilbas - модератор ЗДС, он рисует, делает видео 
на YouTube, гейм девит, щитпостит, terminally online. Паша - модератор ЗДС, занимается Театром и СтендАпом, любит шутить."""

logger = logger.logging.getLogger("bot")


def one_response(message):
    response = openai.ChatCompletion.create(
        model=model,
        temperature=0.4,
        max_tokens=1024,
        messages=[
            {'role': 'system', 'content': role},
            {'role': 'user', 'content': message}
        ]
    )
    logger.info('found response')
    reply = response.choices[0]['message']
    tokens_total = response["usage"]["total_tokens"]
    prompt_tokens = response["usage"]["prompt_tokens"]
    return reply['content'], tokens_total
