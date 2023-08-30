from asyncio import tasks, sleep
from datetime import date, datetime, timedelta
from pprint import pformat
from typing import Optional

from discord import Interaction, app_commands, Embed
from discord.app_commands import command
from discord.app_commands.checks import has_role
from discord.ext.commands import Cog

from util import get_const


class Reminder:
    def __init__(self, time: datetime, message: str, user_id: int):
        self.time = time
        self.message = message
        self.user_id = user_id

    async def wait(self):
        delta = self.time - datetime.now()
        seconds = delta.days * 24 * 60 + delta.seconds + delta.microseconds / 1000000

        await sleep(seconds)


def check_reminder(delta: timedelta) -> str:
    if delta < timedelta(seconds=10):
        return '리마인더 길이는 10초 이상이어야 합니다.'
    if delta > timedelta(days=7):
        return '리마인더 길이는 7일보다 짧아야 합니다.'

    return ''


async def invoke_reminder(reminder: Reminder, ctx: Interaction):
    # set reminder
    await ctx.response.send_message(f'__{reminder.time}__에 알리는 리마인더를 설정했습니다. '
                                    f'리마인더 실행 중에 유르파틴이 재시작되는경우 **리마인더가 실행되지 않습니다.**')
    await reminder.wait()

    # notification
    content = f'\n> {reminder.message}' if reminder.message else ''
    await ctx.user.send(f'{ctx.user.mention} 리마인더가 알려드립니다. __{reminder.time}__입니다.{content}')


class UtilCog(Cog):
    reminder_group = app_commands.Group(name='reminder', description='리마인더 관련 명령어입니다.')

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

    @reminder_group.command(description='현재 시간으로부터 일정 시간 후에 리마인더를 설정합니다.')
    async def after(self, ctx: Interaction, minutes: float, message: str = ''):
        # get time
        delta = timedelta(minutes=minutes)
        time = datetime.now() + delta

        # reminder validity
        if error := check_reminder(delta):
            await ctx.response.send_message(f':x: 리마인더 설정에 실패했습니다. {error}')
            return

        await invoke_reminder(Reminder(time, message, ctx.user.id), ctx)

    @reminder_group.command(description='특정 시간에 리마인더를 설정합니다.')
    async def on(self, ctx: Interaction, hour: int, minute: int, second: int = 0, day: Optional[int] = None,
                 message: str = ''):
        # get time
        now = datetime.now()
        if day is None:
            day = now.day

        if day < now.day:
            month_delta = 1
        else:
            month_delta = 0

        time = datetime(now.year, now.month + month_delta, now.day, hour, minute, second)

        # reminder validity
        if error := check_reminder(time - now):
            await ctx.response.send_message(f':x: 리마인더 설정에 실패했습니다. {error}')
            return

        await invoke_reminder(Reminder(time, message, ctx.user.id), ctx)


async def setup(bot):
    await bot.add_cog(UtilCog(bot))
