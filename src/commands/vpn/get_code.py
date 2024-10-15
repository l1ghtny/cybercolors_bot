from src.modules.logs_setup import logger
from src.modules.vpn_module.api_calls import get_promocodes_by_user, get_vpn_promo_code_api
from src.modules.vpn_module.checks import check_roles

logger = logger.logging.getLogger("bot")


async def get_vpn_promo_code(interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    has_roles = await check_roles(interaction)
    if has_roles:
        result, status = await get_promocodes_by_user(interaction.user.id)
        if status == 200:
            if result is not bool:
                promo_codes_count = len(result)
                if promo_codes_count < 1:
                    result, status = await get_vpn_promo_code_api(interaction.user.id)
                    if status == 200:
                        promo_code = result[0]
                        await interaction.followup.send(f'Твой промокод: {promo_code}\nЧтобы им воспользоваться, иди в этого тг бота: https://t.me/YourYoutubeVpnBot')
                    else:
                        await interaction.followup.send('Что-то пошло не так, дай знать админу')
            else:
                await interaction.followup.send(f'У тебя уже есть промокод, имей совесть \nЕсли что, напоминаю его: {result[0][0]['code']}')
        else:
            await interaction.followup.send('Что-то пошло не так, дай знать админу')
    else:
        await interaction.followup.send('К сожалению, у тебя пока нет доступа к этой команде')

