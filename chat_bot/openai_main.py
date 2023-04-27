import os
import openai
from dotenv import load_dotenv
from logs_setup import logger

load_dotenv()
openai.organization = "org-dTq0wzkkXgmTQ1GIDabM4fva"
openai.api_key = os.getenv("OPENAI_API_KEY")
model = 'gpt-3.5-turbo'
role = 'Ты чат бот на дискорд сервере Сани с ютуб канала Зона Веселья с Саней. Тебя зовут CyberColors. Вот ссылка на ' \
       'канал Сани: https://www.youtube.com/@StudioColors. Ты знаешь всё про ' \
       'вселенную Соника, создателя канала Зона Веселья с Саней и его канал. Тебя создал lightny на основе CHATGPT.' \
       'Тебе можно говорить только от своего имени.'

list_apis = openai.Model.list()

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
    return reply['content'], tokens_total
