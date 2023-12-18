from asyncio import wait, TimeoutError as AsyncioTimeoutError
from datetime import datetime
from random import randint
from typing import Any, Optional

from discord import app_commands, Interaction, InteractionMessage
from discord.ext.commands import Cog, Bot

from util import get_const, check_reaction, custom_emoji
from util.db import get_money, add_money, get_connection

OX_EMOJIS = [get_const('emoji.x'), get_const('emoji.o')]
DICE_EMOJI = [
    custom_emoji('die1', 1186274944422781019),
    custom_emoji('die2', 1186274946989694986),
    custom_emoji('die3', 1186274950500327454),
    custom_emoji('die4', 1186274953696399410),
    custom_emoji('die5', 1186274955646742638),
    custom_emoji('die6', 1186274958796673086)
]

START_COST = 1000_00  # cŁ


def make_pig_row(user_id: int):
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('INSERT IGNORE INTO pig(user_id) VALUES (%s)', (user_id,))
        database.commit()


def update_pig_score(user_id: int, score: int):
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('UPDATE pig SET score = %s WHERE user_id = %s AND score < %s', (score, user_id, score))
        database.commit()


def get_rank() -> tuple[tuple[int, int, ...], ...]:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT user_id, score FROM pig ORDER BY score DESC LIMIT 10')
        return cursor.fetchall()


def get_pig_score(user_id: int) -> Optional[int]:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT score FROM pig WHERE user_id = %s', (user_id,))
        data = cursor.fetchone()
    return data[0] if data is not None else None


class MoneyAmusementPigCog(Cog):
    pig_group = app_commands.Group(name="pig", description="돼지 게임과 관련된 명령어입니다.")

    def __init__(self, bot: Bot):
        self.bot = bot

    @pig_group.command(name='describe', description='돼지 게임에 대한 설명을 확인합니다.')
    async def describe(self, ctx: Interaction):
        await ctx.response.send_message(
            '# 돼지 게임 설명\n'
            '돼지 게임은 주사위를 활용하여 높은 점수를 내는 게임입니다.\n'
            '1. 주사위를 굴려서 나온 눈의 수만큼 점수를 얻게 됩니다.\n'
            '2. 만약 굴려서 나온 눈의 수가 1이라면 __**즉시 모든 점수를 잃고 게임을 종료하게 됩니다.**__ (참가비는 반환되지 않습니다.)\n'
            '3. 더 이상 주사위를 굴리지 않겠다고 결정하면 게임이 종료되고, 지금까지 얻은 점수만큼 점수를 얻게 됩니다.',
            ephemeral=True)

    @pig_group.command(name='start', description=f'돼지 게임을 시작합니다. ({START_COST/100:,.2f} Ł)')
    async def start(self, ctx: Interaction):
        # check have enough money or not
        having = get_money(ctx.user.id)
        if having < START_COST:
            await ctx.response.send_message(
                f'돼지 게임을 시작하기 위한 소지금이 부족합니다! 소지금이 __{START_COST/100:,.2f} Ł__ 필요합니다.')
            return
        add_money(ctx.user.id, -START_COST)

        # process game
        make_pig_row(ctx.user.id)
        score = 0
        template = f'현재 점수는 0점입니다. 주사위를 굴리시겠습니까? (60초)'
        await ctx.response.send_message(template.format(score))
        message: InteractionMessage = await ctx.original_response()
        while True:
            await message.clear_reactions()
            await wait((message.add_reaction(get_const('emoji.x')), message.add_reaction(get_const('emoji.o'))))

            try:
                res = await self.bot.wait_for(
                    'reaction_add',
                    timeout=60.0,
                    check=check_reaction(OX_EMOJIS, ctx, message.id))
                await message.clear_reactions()
            except AsyncioTimeoutError:
                await message.edit(content=f':x: 시간이 초과되어 작업이 취소되었습니다. 참가비는 반환되지 않습니다.')
                return

            if res[0].emoji == get_const('emoji.x'):
                break

            die = randint(1, 6)
            if die == 1:
                await message.edit(content=f'{DICE_EMOJI[0]} {score}점에서 **1이 나와 점수가 초기화되었습니다.**')
                return

            score += die
            await message.edit(content=f'{DICE_EMOJI[die-1]} 점수가 **{score}점**이 되었습니다. '
                                       f'한번 더 주사위를 굴리시겠습니까? (60초)')

        update_pig_score(ctx.user.id, score)
        await message.edit(content=f'{score}점으로 게임이 종료되었습니다!!')

    @pig_group.command(name='leaderboard', description=f'돼지 게임 최고 점수 순위를 확인합니다.')
    async def rank(self, ctx: Interaction):
        contents = list()
        for user_id, score in get_rank():
            user = self.bot.get_user(user_id)
            if user is None:
                user = f'||{user_id}||'
            else:
                user = user.display_name
            contents.append(f'1. {user}: {score}점')
        await ctx.response.send_message(f'돼지 게임 최고점수표 ({datetime.now()})\n' + '\n'.join(contents))

    @pig_group.command(name='score', description='돼지게임 점수를 확인합니다.')
    async def score(self, ctx: Interaction):
        score = get_pig_score(ctx.user.id)
        if score is None:
            await ctx.response.send_message(f'__{ctx.user.display_name}__님은 돼지게임을 플레이한 적이 없습니다.')
            return

        await ctx.response.send_message(f'__{ctx.user.display_name}__님의 돼지 게임 최고 점수는 __**{score}**__점입니다.')


async def setup(bot):
    await bot.add_cog(MoneyAmusementPigCog(bot))
