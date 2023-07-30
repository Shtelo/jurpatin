from datetime import date
from pprint import pformat

from discord import Interaction
from discord.app_commands import command
from discord.app_commands.checks import has_role
from discord.ext.commands import Cog

from util import get_const


class UtilCog(Cog):
    @command(name='eval', description='유르파틴 수식 내용을 확인합니다.')
    @has_role(get_const('role.harnavin'))
    async def eval_(self, ctx: Interaction, variable: str):
        try:
            formatted = pformat(eval(variable), indent=2)
            await ctx.response.send_message(f'```\n{variable} = \\\n{formatted}\n```', ephemeral=True)
        except Exception as e:
            await ctx.response.send_message(f':x: 수식 실행중에 문제가 발생했습니다.\n```\n{e}\n```', ephemeral=True)

    @command(description='D-Day를 계산합니다.')
    async def dday(self, ctx: Interaction, year: int, month: int, day: int, ephemeral: bool = True):
        today = date.today()
        diff = today - date(year, month, day)
        days = diff.days

        after = ''
        if days > 0:
            after = f' 당일을 포함하면 __{days + 1}일째__입니다.'

        await ctx.response.send_message(f'오늘은 {year}년 {month}월 {day}일에 대해 __D{days:+}__입니다.{after}',
                                        ephemeral=ephemeral)


async def setup(bot):
    await bot.add_cog(UtilCog(bot))
