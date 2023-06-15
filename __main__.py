import re
from asyncio import sleep, wait, TimeoutError as AsyncioTimeoutError
from datetime import date, datetime, timedelta, timezone
from math import inf
from sys import argv
from typing import Tuple, List, Optional

from discord import Intents, Interaction, Member, Role, Reaction, User, InteractionMessage, Guild, VoiceState, \
    VoiceChannel, NotFound, RawReactionActionEvent
from discord.app_commands import MissingRole
from discord.app_commands.checks import has_role
from discord.ext import tasks
from discord.ext.commands import Bot, when_mentioned
from sat_datetime import SatDatetime

from util import get_secret, get_const, eul_reul

intents = Intents.default()
intents.members = True

bot = Bot(when_mentioned, intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    today_statistics.start()
    print('Ürpatin is running.')


@bot.event
async def on_member_join(member: Member):
    if member.guild.id != get_const('guild.lofanfashasch'):
        return

    candidate = get_proper_id(member, 5, member.guild)
    name = member.display_name if DECORATED_NICK_RE.match(member.display_name) is None else member.display_name[8:]
    nick = f'{candidate} {name}'
    await member.edit(nick=nick)
    await assign_role(member, nick[0], member.guild)


today_messages = 0
today_messages_length = 0
today_calls = 0
today_reactions = 0
today_people = set()
last_record = datetime.now(timezone.utc)


def generate_today_statistics() -> str:
    return f'> `{today_messages}`개의 메시지가 전송되었습니다. (총 길이: `{today_messages_length}`문자)\n' \
           f'> 음성 채널이 `{today_calls}`번 활성화되었습니다.\n' \
           f'> `{len(today_people)}`명의 사람이 서버에 접속했습니다.\n' \
           f'> 총 `{today_reactions}`개의 반응이 추가되었습니다.'


@tasks.loop(minutes=1)
async def today_statistics():
    global today_messages, today_calls, today_people
    global last_record

    print("loop")

    # check new day
    previous = last_record
    last_record = datetime.now(timezone.utc)
    if previous.day == last_record.day:
        return

    # reset
    today_messages = 0
    today_calls = 0
    today_people = set()

    # get server and send statistics message
    text_channel = bot.get_channel(get_const('channel.general'))

    await text_channel.send(f'# `{previous.date()}`의 통계\n{generate_today_statistics()}')


message_logs = dict()


@bot.event
async def on_voice_state_update(member: Member, before: VoiceState, after: VoiceState):
    await voice_channel_notification(member, before, after)


async def voice_channel_notification(member: Member, before: VoiceState, after: VoiceState):
    global today_calls

    if member.guild.id != get_const('guild.lofanfashasch'):
        return

    today_people.add(member.id)

    text_channel = member.guild.get_channel(get_const('channel.general'))

    # if leaving
    if before.channel is not None and len(before.channel.members) < 1:
        if before.channel.id not in message_logs:
            return

        message_id = message_logs.pop(before.channel.id)
        if message_id is None:
            return

        message = await text_channel.fetch_message(message_id)
        duration = datetime.now(timezone.utc) - message.created_at
        await message.delete()

        if duration >= timedelta(hours=1):
            await text_channel.send(f'{before.channel.mention} 채널이 비활성화되었습니다. (활성 시간: {duration})')

        return

    # if connecting to empty channel
    if after.channel is None:
        return
    if before.channel is not None and before.channel.id == after.channel.id:
        return
    if len(after.channel.members) > 1:
        return

    generals = get_const('voice_channel.generals')
    bored_role = member.guild.get_role(get_const('role.bored_mention'))
    if bored_role is not None and after.channel.id in generals:
        mention_string = f'{bored_role.mention} (알림 해제를 위해서는 `/remove_role` 명령어를 사용하세요.)'
    else:
        mention_string = ""

    message = await text_channel.send(f'{member.mention}님이 {after.channel.mention} 채널을 활성화했습니다. {mention_string}')
    message_logs[after.channel.id] = message.id

    today_calls += 1


@bot.event
async def on_message(message: InteractionMessage):
    global today_messages, today_messages_length

    # record today statistics
    if message.guild.id == get_const('guild.lofanfashasch'):
        today_messages += 1
        today_messages_length += len(message.content)
        today_people.add(message.author.id)


@bot.event
async def on_raw_reaction_add(payload: RawReactionActionEvent):
    global today_reactions

    # record today statistics
    if payload.guild_id == get_const('guild.lofanfashasch'):
        today_reactions += 1
        today_people.add(payload.user_id)


DECORATED_NICK_RE = re.compile(r'^\d{7} .+$')


def check_reaction(emojis: List[str], ctx: Interaction, message_id: int):
    def checker(reaction: Reaction, user: User):
        return user.id == ctx.user.id and str(reaction.emoji) in emojis and reaction.message.id == message_id

    return checker


OX_EMOJIS = [get_const('emoji.x'), get_const('emoji.o')]


def get_proper_id(member: Member, role: int, guild: Guild) -> str:
    year = SatDatetime.get_from_datetime(member.joined_at.replace(tzinfo=None)).year
    index = 1
    names = tuple(map(lambda x: x.display_name[:7], guild.members))

    while (candidate := f'{role}{year*10 + index:06d}') in names:
        index += 1

    return candidate


@bot.tree.command(name='id', description='규칙에 따라 로판파샤스 아이디를 부여합니다.')
async def id_(ctx: Interaction, member: Member, role: int = 5):
    if not (1 <= role <= 6):
        await ctx.response.send_message(':x: 잘못된 역할 형식입니다.')
        return

    candidate = get_proper_id(member, role, ctx.guild)

    name = member.display_name if DECORATED_NICK_RE.match(member.display_name) is None else member.display_name[8:]
    post_name = f'{candidate} {name}'

    await ctx.response.send_message(
        f'현재 이름은 `{member.display_name}`이고, 이름을 변경하면 `{post_name}`으로 변경됩니다.\n이름을 변경하시겠습니까?')
    message: InteractionMessage = await ctx.original_response()
    await wait((message.add_reaction(get_const('emoji.x')), message.add_reaction(get_const('emoji.o'))))

    try:
        res: Tuple[Reaction] = await bot.wait_for(
            'reaction_add',
            timeout=60.0,
            check=check_reaction(OX_EMOJIS, ctx, message.id))
        await message.clear_reactions()
    except AsyncioTimeoutError:
        await message.edit(content=f':x: 시간이 초과되어 작업이 취소되었습니다.')
        return

    if res[0].emoji == get_const('emoji.x'):
        await message.edit(content=f':x: 사용자가 작업을 취소하였습니다.')
        return

    await member.edit(nick=post_name)
    await message.edit(content=f'이름을 변경했습니다.\n> `{member.display_name}` > `{post_name}`')


ROLE_ID_TABLE = (
    get_const('role.harnavin'), get_const('role.erasheniluin'), get_const('role.quocerin'), get_const('role.lofanin'),
    get_const('role.hjulienin'))


async def assign_role(member: Member, role_number: str, guild: Guild):
    role_index = int(role_number) - 1
    for i in range(role_index):
        await sleep(0)
        role = guild.get_role(ROLE_ID_TABLE[i])
        if role in member.roles:
            await member.remove_roles(role)
    for i in range(role_index, 5):
        await sleep(0)
        role = guild.get_role(ROLE_ID_TABLE[i])
        if role not in member.roles:
            await member.add_roles(role)


@bot.tree.command(name='role', description='닉네임에 따라 로판파샤스 역할을 부여합니다.')
async def role_(ctx: Interaction, member: Member):
    if (role_number := member.display_name[0]) not in '12345':
        await ctx.response.send_message(f'닉네임이 학번으로 시작하지 않거나 역할 지급 대상이 아닙니다.')
        return

    await assign_role(member, role_number, ctx.guild)
    await ctx.response.send_message(f'역할을 부여했습니다.')


@bot.tree.command(description='역할에 어떤 멤버가 있는지 확인합니다.')
async def check_role(ctx: Interaction, role: Role):
    members = list()
    last_member_number = ''
    last_index = 0
    for member in sorted(role.members, key=lambda x: x.display_name):
        if last_member_number != (last_member_number := member.display_name[:7]):
            last_index += 1
        members.append(f'{last_index}. `{member.display_name}` ({member})')

    list_string = '> ' + '\n> '.join(members)

    await ctx.response.send_message(
            f'{role.name} 역할에 있는 멤버 목록은 다음과 같습니다. (총 {last_index}명, 계정 {len(members)}개)'
            f'\n{list_string}'
    )


async def get_position(ctx: Interaction, term: int, is_lecture: bool = True):
    prefix = '강의' if is_lecture else '스터디'
    position = inf
    index = 0
    for guild_role in sorted(ctx.guild.roles, key=lambda x: x.name):
        await sleep(0)
        if not guild_role.name.startswith(f'{prefix}:'):
            continue
        position = min(guild_role.position, position)

        guild_name = guild_role.name[len(prefix):]
        role_term = int(guild_name[2:4])
        role_index = int(guild_name[4:5])
        if role_term != term:
            continue
        index = max(index, role_index)
    return index, position


@bot.tree.command(description='강의를 개설합니다.')
@has_role(get_const('role.harnavin'))
async def new_lecture(ctx: Interaction, name: str, term: int, erasheniluin: Member):
    # noinspection DuplicatedCode
    await ctx.response.send_message(f'이름이 `{name}`인 {term}기 강의를 개설합니다. 이 작업을 취소하는 기능은 지원되지 않습니다. 동의하십니까?')
    message = await ctx.original_response()
    await wait((message.add_reaction(get_const('emoji.x')), message.add_reaction(get_const('emoji.o'))))

    try:
        res: Tuple[Reaction] = await bot.wait_for('reaction_add', check=check_reaction(OX_EMOJIS, ctx, message.id))
        await message.clear_reactions()
    except AsyncioTimeoutError:
        await message.edit(content=':x: 시간이 초과되어 작업이 취소되었습니다.')
        return

    if res[0].emoji == get_const('emoji.x'):
        await message.edit(content=':x: 사용자가 작업을 취소하였습니다.')
        return

    index, position = await get_position(ctx, term)

    role = await ctx.guild.create_role(
        name=f'강의:1{term:02d}{index + 1} ' + name, colour=get_const('color.lecture'),
        mentionable=True)
    await role.edit(position=position)
    await erasheniluin.add_roles(role)

    await message.edit(content=f'{role.mention} 강의를 개설했습니다.')


@new_lecture.error
async def new_lecture_error(ctx: Interaction, error: Exception):
    if isinstance(error, MissingRole):
        await ctx.response.send_message(':x: 명령어를 사용하기 위한 권한이 부족합니다!')
        return

    print(error.with_traceback(error.__traceback__))


@bot.tree.command(description='스터디를 개설합니다.')
@has_role(get_const('role.harnavin'))
async def new_study(ctx: Interaction, name: str, term: int):
    # noinspection DuplicatedCode
    await ctx.response.send_message(f'이름이 `{name}`인 {term}기 스터디를 개설합니다. 이 작업을 취소하는 기능은 지원되지 않습니다. 동의하십니까?')
    message = await ctx.original_response()
    await wait((message.add_reaction(get_const('emoji.x')), message.add_reaction(get_const('emoji.o'))))

    try:
        res: Tuple[Reaction] = await bot.wait_for('reaction_add', check=check_reaction(OX_EMOJIS, ctx, message.id))
        await message.clear_reactions()
    except AsyncioTimeoutError:
        await message.edit(content=':x: 시간이 초과되어 작업이 취소되었습니다.')
        return

    if res[0].emoji == get_const('emoji.x'):
        await message.edit(content=':x: 사용자가 작업을 취소하였습니다.')
        return

    index, position = await get_position(ctx, term, False)

    role = await ctx.guild.create_role(
        name=f'스터디:2{term:02d}{index + 1} ' + name, colour=get_const('color.study'),
        mentionable=True)
    await role.edit(position=position)

    await message.edit(content=f'{role.mention} 스터디를 개설했습니다.')


@new_study.error
async def new_study_error(ctx: Interaction, error: Exception):
    if isinstance(error, MissingRole):
        await ctx.response.send_message(':x: 명령어를 사용하기 위한 권한이 부족합니다!')
        return

    print(error.with_traceback(error.__traceback__))


def parse_role_name(name: str) -> Tuple[bool, int, int, str]:
    """
    출력 값으로는 tuple[bool, int, int, str] 형태의 값을 출력합니다.

    첫 번째 요소가 True이면 role이 강의라는 의미이고, False이면 스터디라는 의미입니다.
    두 번째 요소는 기수, 세 번째 요소는 인덱스 번호입니다.
    마지막 요소는 강의/스터디의 이름입니다.
    """

    if name.startswith('스터디:'):
        name = name[4:]
    elif name.startswith('강의:'):
        name = name[3:]
    else:
        raise ValueError

    is_lecture = name[0] == '1'
    term = int(name[1:3])
    index = int(name[3:4])
    title = name[5:]

    return is_lecture, term, index, title


@bot.tree.command(description='강의 목록을 확인합니다.')
async def lectures(ctx: Interaction, term: int):
    if term <= 0:
        await ctx.response.send_message(f':x: 기수는 1 이상으로 입력해야 합니다.')
        return

    lines = list()
    for role in ctx.guild.roles:
        try:
            is_lecture, role_term, index, title = parse_role_name(role.name)
        except ValueError:
            continue

        if not is_lecture:
            continue
        if role_term != term:
            continue

        lines.append(role.name)

    list_string = '> ' + '\n> '.join(lines[::-1])

    if not lines:
        await ctx.response.send_message(f'{term}기에는 (아직) 강의가 없습니다!')
        return

    await ctx.response.send_message(f'{term}기의 강의 목록은 다음과 같습니다.\n{list_string}')


@bot.tree.command(description='스터디 목록을 확인합니다.')
async def studies(ctx: Interaction, term: int):
    if term <= 0:
        await ctx.response.send_message(f':x: 기수는 1 이상으로 입력해야 합니다.')
        return

    lines = list()
    for role in ctx.guild.roles:
        try:
            is_lecture, role_term, index, title = parse_role_name(role.name)
        except ValueError:
            continue

        if is_lecture:
            continue
        if role_term != term:
            continue

        lines.append(role.name)

    list_string = '> ' + '\n> '.join(lines[::-1])

    if not lines:
        await ctx.response.send_message(f'{term}기에는 (아직) 스터디가 없습니다!')
        return

    await ctx.response.send_message(f'{term}기의 스터디 목록은 다음과 같습니다.\n{list_string}')


@bot.tree.command(description='역할을 부여합니다.')
async def give_role(ctx: Interaction, role: Role):
    await ctx.user.add_roles(role)
    await ctx.response.send_message(f'{ctx.user.mention}에게 {role}{eul_reul(role.name)} 부여했습니다.')


@bot.tree.command(description='역할을 제거합니다.')
async def remove_role(ctx: Interaction, role: Role):
    await ctx.user.remove_roles(role)
    await ctx.response.send_message(f'{ctx.user.mention}에게서 {role}{eul_reul(role.name)} 제거했습니다.')


@bot.tree.command(description='D-Day를 계산합니다.')
async def dday(ctx: Interaction, year: int, month: int, day: int):
    today = date.today()
    diff = today - date(year, month, day)
    days = diff.days

    after = ''
    if days > 0:
        after = f' 당일을 포함하면 __{days + 1}일째__입니다.'

    await ctx.response.send_message(f'오늘은 {year}년 {month}월 {day}일에 대해 __D{days:+}__입니다.{after}')


@bot.tree.command(description='음성 채널의 업타임을 계산합니다.')
async def uptime(ctx: Interaction, channel: Optional[VoiceChannel] = None):
    if channel is None and ctx.user.voice is not None:
        channel = ctx.user.voice.channel

    if channel is None:
        await ctx.response.send_message('음성 채널 정보를 찾을 수 없습니다.')
        return

    if ctx.guild.id != get_const('guild.lofanfashasch'):
        await ctx.response.send_message('음성 채널 시작 시간에 대한 정보가 없습니다.')
        pass

    message_id = message_logs.get(channel.id)
    if message_id is None:
        await ctx.response.send_message('음성 채널 시작 시간에 대한 정보가 없습니다.')
        return

    text_channel = ctx.guild.get_channel(get_const('channel.general'))
    try:
        message = await text_channel.fetch_message(message_id)
    except NotFound:
        await ctx.response.send_message('음성 채널 시작 시간에 대한 정보가 없습니다.')
        return

    duration = datetime.now(timezone.utc) - message.created_at
    await ctx.response.send_message(f'{channel.mention}의 업타임은 __{duration}__입니다.')


@bot.tree.command(description='지금까지의 오늘 통계를 확인합니다.')
async def today(ctx: Interaction):
    now = datetime.now(timezone.utc)

    await ctx.response.send_message(f'`{now.date()}`의 현재까지의 통계\n{generate_today_statistics()}')


if __name__ == '__main__':
    bot.run(get_secret('test_bot_token' if '-t' in argv else 'bot_token'))
