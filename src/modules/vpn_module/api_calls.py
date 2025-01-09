import os

import aiohttp
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('VPN_API_KEY')
vpn_url = os.getenv('VPN_API_URL')

async def get_vpn_promo_code_api(discord_id: int):
    async with aiohttp.ClientSession() as session:
        url = vpn_url+'bots/promo_codes'
        headers = {
            "Authorization": api_key
        }
        params = {
            "amount": 1,
            "usages": 1,
            "percent_off": 100,
            "card_needed": 'False',
            "created_by": 'cybercolors',
            "created_for": discord_id,
            "payment_plan": 'free',
            "days_active": 15
        }
        async with session.get(url, headers=headers, params=params) as response:
            result = await response.json()
            print(result)
            return result, response.status


async def get_promocodes_by_user(discord_id: int):
    async with aiohttp.ClientSession() as session:
        url = vpn_url + f'bots/promo_codes/{discord_id}'
        headers = {
            "Authorization": api_key
        }
        async with session.get(url, headers=headers) as response:
            result = await response.json()
            return result, response.status

