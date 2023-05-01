import os
import openai
from dotenv import load_dotenv
from logs_setup import logger

load_dotenv()
openai.organization = "org-dTq0wzkkXgmTQ1GIDabM4fva"
openai.api_key = os.getenv("OPENAI_API_KEY")
model = 'gpt-3.5-turbo'
role = """"""
logger = logger.logging.getLogger("bot")


def one_response(message):
    response = openai.ChatCompletion.create(
        model=model,
        temperature=0.4,
        max_tokens=512,
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
