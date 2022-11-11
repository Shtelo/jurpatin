import re
from asyncio import sleep
from sys import argv

from discord import Intents, Interaction, Member
from discord.ext.commands import Bot, when_mentioned
from sat_datetime import SatDatetime

from util import get_secret, get_const

intents = Intents.default()
intents.members = True

bot = Bot(when_mentioned, intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print('Ürpatin is running.')


DECORATED_NICK_RE = re.compile(r'^\d{7} .+$')


@bot.tree.command(
    description='규칙에 따라 로판파샤스 아이디를 부여합니다.'
)
async def id(ctx: Interaction, member: Member, role: int = 5):
    if not (1 <= role <= 6):
        await ctx.response.send_message(':x: 잘못된 역할 형식입니다.')
        return

    year = SatDatetime.get_from_datetime(member.joined_at.replace(tzinfo=None)).year
    index = 1
    names = tuple(map(lambda x: x.display_name[:7], ctx.guild.members))

    while (candidate := f'{role}{year*10 + index:06d}') in names:
        index += 1

    name = member.display_name if DECORATED_NICK_RE.match(member.display_name) is None else member.display_name[8:]

    await member.edit(nick=f'{candidate} {name}')
    await ctx.response.send_message(f'이름을 변경했습니다.\n> `{member.display_name}` > `{candidate} {name}`')


ROLE_ID_TABLE = (
    get_const('role.harnavin'), get_const('role.erasheniluin'),
    get_const('role.quocerin'), get_const('role.lofanin'), get_const('role.hjulienin')
)


@bot.tree.command(
    name='role',
    description='닉네임에 따라 로판파샤스 역할을 부여합니다.'
)
async def role_(ctx: Interaction, member: Member):
    if (role_number := member.display_name[0]) not in '12345':
        await ctx.response.send_message(f'닉네임이 학번으로 시작하지 않거나 역할 지급 대상이 아닙니다.')
        return

    role_index = int(role_number)-1
    for i in range(role_index):
        await sleep(0)
        role = ctx.guild.get_role(ROLE_ID_TABLE[i])
        if role in member.roles:
            await member.remove_roles(role)
    role = ctx.guild.get_role(ROLE_ID_TABLE[role_index])
    await member.add_roles(role)

    await ctx.response.send_message(f'역할을 부여했습니다.')


if __name__ == '__main__':
    bot.run(get_secret('test_bot_token' if '-t' in argv else 'bot_token'))
