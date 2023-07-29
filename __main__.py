import re
from asyncio import sleep, wait, TimeoutError as AsyncioTimeoutError
from datetime import date, datetime, timedelta, timezone
from math import inf, exp
from pprint import pformat
from random import randint
from sys import argv
from typing import Tuple, List, Optional

from discord import Intents, Interaction, Member, Role, Reaction, User, InteractionMessage, Guild, VoiceState, \
    VoiceChannel, NotFound, RawReactionActionEvent, Embed, app_commands
from discord.app_commands import MissingRole
from discord.app_commands.checks import has_role
from discord.ext import tasks
from discord.ext.commands import Bot, when_mentioned
from sat_datetime import SatDatetime

from util import get_const, eul_reul, parse_datetime, parse_timedelta, get_secret
from util.db import get_money, add_money, set_value, get_value, add_inventory, get_inventory, set_inventory, \
    get_money_ranking, get_lotteries, clear_lotteries

intents = Intents.default()
intents.members = True
intents.message_content = True

bot = Bot(when_mentioned, intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    today_statistics.start()
    give_money_if_call.start()
    lottery_tick.start()
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


today_people = set()


async def generate_today_statistics() -> str:
    await sleep(0)

    # calculate total call duration
    call_duration = parse_timedelta(get_value('today_call_duration'))
    # add current call duration
    now = datetime.now(timezone.utc)
    for message_id in message_logs.values():
        try:
            message = await bot.get_channel(get_const('channel.general')).fetch_message(message_id)
        except NotFound:
            continue

        call_duration += now - message.created_at

    # make formatted string
    today_messages = get_value('today_messages')
    today_messages_length = get_value('today_messages_length')
    today_calls = get_value('today_calls')
    today_reactions = get_value('today_reactions')
    return f'* `{today_messages}`개의 메시지가 전송되었습니다. (총 길이: `{today_messages_length}`문자)\n' \
           f'* 음성 채널이 `{today_calls}`번 활성화되었습니다.\n' \
           f'  * 총 통화 길이는 `{call_duration}`입니다.\n' \
           f'* 총 `{today_reactions}`개의 반응이 추가되었습니다.'


@tasks.loop(minutes=1)
async def today_statistics():
    global today_people

    last_record = datetime.now(timezone.utc)

    # check new day
    previous = parse_datetime(get_value('last_record'))
    # if same day, do nothing
    if previous.day == last_record.day:
        return

    set_value('last_record', str(last_record))

    # record ppl on database
    previous_ppl = int(get_value(get_const('db.ppl')))
    set_value(get_const('db.ppl'), str(len(today_people)))
    set_value(get_const('db.yesterday_ppl'), str(previous_ppl))

    # get server and send statistics message
    text_channel = bot.get_channel(get_const('channel.general'))

    await text_channel.send(f'# `{previous.date()}`의 통계\n{await generate_today_statistics()}')

    # reset
    set_value('today_messages', 0)
    set_value('today_messages_length', 0)
    set_value('today_calls', 0)
    set_value('today_call_duration', timedelta())
    today_people.clear()


voice_people = set()


@tasks.loop(minutes=1)
async def give_money_if_call():
    for member_id in voice_people:
        # 지급 기준 변경 시 readme.md 수정 필요
        add_money(member_id, 5)


@bot.event
async def on_voice_state_update(member: Member, before: VoiceState, after: VoiceState):
    await voice_channel_notification(member, before, after)

    # track whether member is in voice channel
    if member.guild.id == get_const('guild.lofanfashasch'):
        if after.channel is None:
            voice_people.remove(member.id)
        if before.channel is None:
            voice_people.add(member.id)


message_logs: dict[int, int] = dict()


async def voice_channel_notification(member: Member, before: VoiceState, after: VoiceState):
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
        today_call_duration = parse_timedelta(get_value('today_call_duration'))
        set_value('today_call_duration', today_call_duration + duration)

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

    today_calls = int(get_value('today_calls'))
    set_value('today_calls', today_calls + 1)


@bot.event
async def on_message(message: InteractionMessage):
    lofanfashasch_id = get_const('guild.lofanfashasch')

    # record today statistics
    try:
        if message.guild.id == lofanfashasch_id:
            today_messages = int(get_value('today_messages'))
            set_value('today_messages', today_messages + 1)
            today_messages_length = int(get_value('today_messages_length'))
            set_value('today_messages_length', today_messages_length + len(message.content))
            today_people.add(message.author.id)
    except AttributeError:
        pass

    # give money by message content
    try:
        if message.guild.id == lofanfashasch_id and (amount := len(set(message.content))):
            # 지급 기준 변경 시 readme.md 수정 필요
            add_money(message.author.id, amount)
    except AttributeError:
        pass


@bot.event
async def on_raw_reaction_add(payload: RawReactionActionEvent):
    # record today statistics
    if payload.guild_id == get_const('guild.lofanfashasch'):
        today_reactions = get_value('today_reactions')
        set_value('today_reactions', int(today_reactions) + 1)
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


@bot.tree.command(name='eval', description='유르파틴 수식 내용을 확인합니다.')
@has_role(get_const('role.harnavin'))
async def eval_(ctx: Interaction, variable: str):
    try:
        formatted = pformat(eval(variable), indent=2)
        await ctx.response.send_message(f'```\n{variable} = \\\n{formatted}\n```', ephemeral=True)
    except Exception as e:
        await ctx.response.send_message(f':x: 수식 실행중에 문제가 발생했습니다.\n```\n{e}\n```', ephemeral=True)


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
async def check_role(ctx: Interaction, role: Role, ephemeral: bool = True):
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
            f'\n{list_string}', ephemeral=ephemeral)


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
    await ctx.response.send_message(
        f'이름이 `{name}`인 {term}기 강의를 개설합니다. 이 작업을 취소하는 기능은 지원되지 않습니다. 동의하십니까?')
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
    await ctx.response.send_message(
        f'이름이 `{name}`인 {term}기 스터디를 개설합니다. 이 작업을 취소하는 기능은 지원되지 않습니다. 동의하십니까?')
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
        await ctx.response.send_message(f':x: 기수는 1 이상으로 입력해야 합니다.', ephemeral=True)
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
        await ctx.response.send_message(f'{term}기에는 (아직) 강의가 없습니다!', ephemeral=True)
        return

    await ctx.response.send_message(f'{term}기의 강의 목록은 다음과 같습니다.\n{list_string}', ephemeral=True)


@bot.tree.command(description='스터디 목록을 확인합니다.')
async def studies(ctx: Interaction, term: int):
    if term <= 0:
        await ctx.response.send_message(f':x: 기수는 1 이상으로 입력해야 합니다.', ephemeral=True)
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
        await ctx.response.send_message(f'{term}기에는 (아직) 스터디가 없습니다!', ephemeral=True)
        return

    await ctx.response.send_message(f'{term}기의 스터디 목록은 다음과 같습니다.\n{list_string}', ephemeral=True)


@bot.tree.command(description='역할을 부여합니다.')
async def give_role(ctx: Interaction, role: Role):
    await ctx.user.add_roles(role)
    await ctx.response.send_message(f'{ctx.user.mention}에게 {role}{eul_reul(role.name)} 부여했습니다.', ephemeral=True)


@bot.tree.command(description='역할을 제거합니다.')
async def remove_role(ctx: Interaction, role: Role):
    await ctx.user.remove_roles(role)
    await ctx.response.send_message(f'{ctx.user.mention}에게서 {role}{eul_reul(role.name)} 제거했습니다.', ephemeral=True)


@bot.tree.command(description='D-Day를 계산합니다.')
async def dday(ctx: Interaction, year: int, month: int, day: int, ephemeral: bool = True):
    today = date.today()
    diff = today - date(year, month, day)
    days = diff.days

    after = ''
    if days > 0:
        after = f' 당일을 포함하면 __{days + 1}일째__입니다.'

    await ctx.response.send_message(f'오늘은 {year}년 {month}월 {day}일에 대해 __D{days:+}__입니다.{after}',
                                    ephemeral=ephemeral)


@bot.tree.command(description='음성 채널의 업타임을 계산합니다.')
async def uptime(ctx: Interaction, channel: Optional[VoiceChannel] = None):
    if channel is None and ctx.user.voice is not None:
        channel = ctx.user.voice.channel

    if channel is None:
        await ctx.response.send_message('음성 채널 정보를 찾을 수 없습니다.', ephemeral=True)
        return

    if ctx.guild.id != get_const('guild.lofanfashasch'):
        await ctx.response.send_message('음성 채널 시작 시간에 대한 정보가 없습니다.', ephemeral=True)
        pass

    message_id = message_logs.get(channel.id)
    if message_id is None:
        await ctx.response.send_message('음성 채널 시작 시간에 대한 정보가 없습니다.', ephemeral=True)
        return

    text_channel = ctx.guild.get_channel(get_const('channel.general'))
    try:
        message = await text_channel.fetch_message(message_id)
    except NotFound:
        await ctx.response.send_message('음성 채널 시작 시간에 대한 정보가 없습니다.', ephemeral=True)
        return

    duration = datetime.now(timezone.utc) - message.created_at
    await ctx.response.send_message(f'{channel.mention}의 업타임은 __{duration}__입니다.', ephemeral=True)


@bot.tree.command(description='지금까지의 오늘 통계를 확인합니다.')
async def today(ctx: Interaction):
    now = datetime.now(timezone.utc)

    await ctx.response.send_message(
        f'`{now.date()}`의 현재까지의 통계\n{await generate_today_statistics()}', ephemeral=True)


MONEY_CHECK_FEE = 50


@bot.tree.command(description=f'소지금을 확인합니다. 다른 사람의 소지금을 확인할 때에는 {MONEY_CHECK_FEE / 100:,.2f} Ł의 수수료가 부과됩니다.')
async def money(ctx: Interaction, member: Optional[Member] = None, total: bool = False, ephemeral: bool = True):
    if member is None:
        member = ctx.user

    # fee
    feed = ''
    if member.id != ctx.user.id:
        having = get_money(ctx.user.id)
        if having < MONEY_CHECK_FEE:
            await ctx.response.send_message(f':x: 소지금이 부족하여 다른 사람의 소지금을 확인할 수 없습니다. '
                                            f'(현재 {having / 100:,.2f} Ł)', ephemeral=ephemeral)
            return

        add_money(ctx.user.id, -MONEY_CHECK_FEE)
        feed = f'__{MONEY_CHECK_FEE / 100:,.2f} Ł__를 사용하여 다른 사람의 소지금을 확인했습니다. '

    # money in hand
    having = get_money(member.id)

    # ppl
    ppl_message = ''
    total_message = ''
    ppl_having = get_inventory(member.id).get(get_const('db.ppl_having'), 0)
    if total and ppl_having > 0:
        ppl_price = int(get_value(get_const('db.ppl'))) * 100
        ppl_money = ppl_having * ppl_price
        ppl_message = f'PPL은 __**{ppl_having}개**__를 가지고 있고, PPL 가격은 총 __{ppl_money / 100:,.2f} Ł__입니다.\n'

        total_message = f'따라서 총자산은 __**{(having + ppl_money) / 100:,.2f} Ł**__입니다.\n'

    await ctx.response.send_message(f'{feed}__{member}__님의 소지금은 __**{having / 100:,.2f} Ł**__입니다.\n'
                                    f'{ppl_message}{total_message}', ephemeral=ephemeral)


@bot.tree.command(name='inventory', description='소지품을 확인합니다.')
async def inventory_(ctx: Interaction):
    having = get_inventory(ctx.user.id)

    # if inventory is empty
    if len(having) <= 0:
        await ctx.response.send_message(f'소지품이 없습니다.', ephemeral=True)
        return

    # if not empty
    embed = Embed(
        colour=get_const('color.lofanfashasch'), title=f'__{ctx.user}__의 소지품',
        description='소지품을 확인합니다.')
    embed.set_thumbnail(url=ctx.user.avatar)

    for key, value in having.items():
        embed.add_field(name=key, value=f'{value}개', inline=True)

    await ctx.response.send_message(embed=embed, ephemeral=True)


ppl_group = app_commands.Group(name="ppl", description="PPL 지수와 관련된 명령어입니다.")

@ppl_group.command(name='check', description='로판파샤스의 금일 PPL 지수를 확인합니다.')
async def ppl_check(ctx: Interaction, ephemeral: bool = True):
    # fetch ppl index from database
    ppl_index = int(get_value(get_const('db.ppl')))
    yesterday_ppl = int(get_value(get_const('db.yesterday_ppl')))

    # calculate multiplier
    try:
        multiplier = ppl_index / yesterday_ppl
    except ZeroDivisionError:
        multiplier = inf

    # calculate price of having ppl's
    having = get_inventory(ctx.user.id).get(get_const('db.ppl_having'), 0)
    having_price = having * ppl_index * 100

    if multiplier > 1:
        up_down = '상승 ▲'
    elif multiplier < 1:
        up_down = '하락 ▼'
    else:
        up_down = '유지'

    await ctx.response.send_message(
        f'로판파샤스의 금일 PPL 지수는 __**{ppl_index}**__입니다.\n'
        f'작일 PPL 지수는 __{yesterday_ppl}__이고, '
        f'오늘은 어제에 비해 __**{multiplier * 100:.2f}%로 {up_down}**__했습니다.\n'
        f'__{ctx.user}__님은 __**{having:,}개**__의 PPL 상품을 가지고 있고, 총 __{having_price / 100:,.2f} Ł__입니다.',
        ephemeral=ephemeral)


@ppl_group.command(name='buy', description='PPL 상품을 구매합니다.')
async def ppl_buy(ctx: Interaction, amount: int = 1):
    if amount < 1:
        await ctx.response.send_message(f':x: 구매 수량은 1 이상으로 입력해야 합니다.', ephemeral=True)
        return

    # fetch ppl index from database
    ppl_index = int(get_value(get_const('db.ppl')))
    price = amount * ppl_index * 100

    if ppl_index <= 0:
        await ctx.response.send_message(
            f':x: PPL 지수가 0 이하일 때에는 상품을 구매할 수 없습니다.', ephemeral=True)
        return

    # check if user has enough money
    having = get_money(ctx.user.id)
    if having < price:
        await ctx.response.send_message(
            f':x: 소지금이 부족합니다. '
            f'(소지금: __**{having / 100:,.2f} Ł**__, '
            f'가격: __{amount:,}개 \* {ppl_index:,} Ł = **{price / 100:,.2f} Ł**__)',
            ephemeral=True)
        return

    # update database
    add_money(ctx.user.id, -price)
    add_inventory(ctx.user.id, get_const('db.ppl_having'), amount)

    now_having = get_inventory(ctx.user.id).get(get_const('db.ppl_having'))
    now_money = get_money(ctx.user.id)
    await ctx.response.send_message(
        f'PPL 상품 __{amount:,}__개를 구매했습니다. '
        f'현재 상품 당 PPL 가치는 __{ppl_index:,} Ł__이며, 총 __{now_having:,}__개를 소지하고 있습니다.\n'
        f'현재 소지금은 __**{now_money / 100:,.2f} Ł**__입니다.')


@ppl_group.command(name='sell', description='PPL 상품을 판매합니다.')
async def ppl_sell(ctx: Interaction, amount: int = 1, force: bool = False):
    if amount < 1:
        await ctx.response.send_message(f':x: 판매 수량은 1 이상으로 입력해야 합니다.', ephemeral=True)
        return

    # fetch ppl index from database
    ppl_index = int(get_value(get_const('db.ppl')))
    price = amount * ppl_index * 100

    # handle ppl_index == 0
    if ppl_index <= 0 and not force:
        await ctx.response.send_message(
            f':x: 현재 PPL 지수가 0 이하입니다. '
            f'그래도 판매하시려면 `force` 값을 `True`로 설정해주시기 바랍니다.', ephemeral=True)
        return

    # check if user has enough ppl
    having = get_inventory(ctx.user.id).get(get_const('db.ppl_having'), 0)
    if_all = ''
    if having < amount:
        if_all = f'현재 소지하고 있는 PPL 상품은 총 __{having}__개입니다. 상품을 모두 판매합니다.\n'
        amount = having
        price = amount * ppl_index * 100

    # update database
    add_money(ctx.user.id, price)
    set_inventory(ctx.user.id, get_const('db.ppl_having'), having - amount)

    now_having = get_inventory(ctx.user.id).get(get_const('db.ppl_having'), 0)
    now_money = get_money(ctx.user.id)
    await ctx.response.send_message(
        f'{if_all}'
        f'PPL 상품 __{amount:,}__개를 판매하여 __**{price / 100:,.2f} Ł**__를 벌었습니다. '
        f'현재 PPL 지수는 __{ppl_index:,}__이며, PPL 상품을 __{now_having:,}__개를 소지하고 있습니다.\n'
        f'현재 소지금은 __**{now_money / 100:,.2f} Ł**__입니다.')


bot.tree.add_command(ppl_group)


bets: dict[int, dict[int, int]] = dict()


def make_bet_embed(ctx: Interaction, dealer: Member) -> Embed:
    """ make embed for checking betting information """

    total_bet = sum(bets[dealer.id].values())
    max_bet = max(bets[dealer.id].values())

    embed = Embed(
        title=f'__{dealer}__ 딜러 베팅 정보',
        description=f'최고 베팅 금액: __**{max_bet / 100:,.2f} Ł**__',
        colour=get_const('color.lofanfashasch'))
    for better_id, bet_ in bets[dealer.id].items():
        better = ctx.guild.get_member(better_id)
        embed.add_field(
            name=f'__{better}__' if better.id == ctx.user.id else str(better),
            value=f'**{bet_ / 100:,.2f} Ł** (M{(bet_ - max_bet) / 100:+,.2f} Ł)',
            inline=False)
    embed.set_footer(text=f'총 베팅 금액: {total_bet / 100:,.2f} Ł')

    return embed


async def handle_bet(ctx: Interaction, dealer: Member, amount: int):
    # check if user has enough money
    having = get_money(ctx.user.id)
    if having < amount:
        await ctx.response.send_message(
            f':x: 소지금이 부족합니다. '
            f'(소지금: __**{having / 100:,.2f} Ł**__, 베팅 금액: __{amount / 100:,.2f} Ł__)',
            ephemeral=True)
        return

    # update database
    add_money(ctx.user.id, -amount)
    if dealer.id not in bets:
        bets[dealer.id] = dict()
    if ctx.user.id not in bets[dealer.id]:
        bets[dealer.id][ctx.user.id] = amount
    else:
        bets[dealer.id][ctx.user.id] += amount

    # make embed and send message
    embed = make_bet_embed(ctx, dealer)
    my_total_bet = bets[dealer.id][ctx.user.id]
    total_bet = sum(bets[dealer.id].values())
    await ctx.response.send_message(
        f'{dealer.mention}님을 딜러로 하여 __**{amount / 100:,.2f} Ł**__을 베팅했습니다.\n'
        f'현재 __{ctx.user}__님이 베팅한 금액은 총 __**{my_total_bet / 100:,.2f} Ł**__이며, '
        f'딜러 앞으로 베팅된 금액은 총 __{total_bet / 100:,.2f} Ł__입니다.', embed=embed)


bet_group = app_commands.Group(name='bet', description='베팅 관련 명령어입니다.')


@bet_group.command(name='raise', description='베팅 금액을 올립니다.')
async def bet_raise(ctx: Interaction, dealer: Member, amount: float = 0.0):
    # preprocess amount
    amount = round(amount * 100)

    if not amount:
        await ctx.response.send_message(':x: 베팅 금액을 입력해주세요.', ephemeral=True)
        return

    # process betting
    await handle_bet(ctx, dealer, amount)


@bet_group.command(name='info', description='베팅 현황을 확인합니다.')
async def bet_info(ctx: Interaction, dealer: Member):
    if dealer.id not in bets:
        await ctx.response.send_message(':x: 베팅 정보가 없습니다.', ephemeral=True)
        return

    embed = make_bet_embed(ctx, dealer)
    await ctx.response.send_message(embed=embed)


@bet_group.command(name='unroll', description='베팅된 금액을 모두 회수하여 제공합니다.')
async def bet_unroll(ctx: Interaction, to: Member):
    if ctx.user.id not in bets:
        await ctx.response.send_message(':x: 베팅 정보가 없습니다.', ephemeral=True)
        return

    total_bet = sum(bets[ctx.user.id].values())

    # update database
    add_money(to.id, total_bet)
    bets.pop(ctx.user.id)

    await ctx.response.send_message(
        f'__{ctx.user}__ 딜러 베팅 금액 __**{total_bet / 100:,.2f} Ł**__을 {to.mention}님에게 제공하였습니다.')


bot.tree.add_command(bet_group)

@bot.tree.command(description='돈을 송금합니다.')
async def transfer(ctx: Interaction, to: Member, amount: float):
    # preprocessing
    amount = round(amount * 100)

    # check if amount is valid
    if amount <= 0:
        await ctx.response.send_message(':x: 송금할 금액은 0을 초과해야 합니다.', ephemeral=True)
        return

    # check if user has enough money
    having = get_money(ctx.user.id)
    if having < amount:
        await ctx.response.send_message(
            f':x: 소지금이 부족합니다. '
            f'(소지금: __**{having / 100:,.2f} Ł**__, 송금 금액: __{amount / 100:,.2f} Ł__)',
            ephemeral=True)
        return

    # update database
    add_money(ctx.user.id, -amount)
    add_money(to.id, amount)

    await ctx.response.send_message(
        f'{ctx.user.mention}님이 {to.mention}님에게 __**{amount / 100:,.2f} Ł**__를 송금하였습니다.')


@bot.tree.command(description='돈 소지 현황을 확인합니다.')
async def rank(ctx: Interaction, ephemeral: bool = True):
    ranking = get_money_ranking()

    strings = list()
    for user_id, money_, _ in ranking:
        member = ctx.guild.get_member(user_id)

        # skip the bot
        if member is not None and member.bot:
            continue

        # handle member is None
        if member is None:
            member_string = f'||{user_id}||'
        else:
            member_string = str(member)

        strings.append(f'1. __{member_string}__: __**{money_ / 100:,.2f} Ł**__')

    message = '\n'.join(strings)
    await ctx.response.send_message(f'**돈 소지 현황** ({datetime.now()})\n{message}', ephemeral=ephemeral)


prediction_group = app_commands.Group(name='predict', description='예측 베팅 관련 명령어입니다.')
predictions: dict[int, tuple[str, str, str, datetime, dict[int, int], dict[int, int]]] = dict()
"""
dict[
    dealer_id: int,
    tuple[
        title: str,
        option1: str,
        option2: str,
        until: datetime,
        option_1_players: dict[
            predictor_id: int,
            amount: int(cŁ)
        ],
        option_2_players: dict[
            predictor_id: int,
            amount: int(cŁ)
        ]
    ]
]
"""
PREDICTION_FEE = 500  # cŁ


@prediction_group.command(name='start', description=f'예측 세션을 시작합니다. {PREDICTION_FEE / 100:,.2f}Ł가 소모됩니다.')
async def prediction_start(ctx: Interaction, title: str, option1: str, option2: str, duration_second: int = 30):
    # check if user already has a prediction session
    if ctx.user.id in predictions:
        await ctx.response.send_message(':x: 이미 예측 세션이 진행 중입니다. 세션을 종료한 후에 다시 시작해주세요.', ephemeral=True)
        return

    # check if duration is valid
    if duration_second <= 0:
        await ctx.response.send_message(':x: 예측 세션의 지속 시간은 0초보다 커야 합니다.', ephemeral=True)
        return

    # check if user has enough money
    having = get_money(ctx.user.id)
    if having < PREDICTION_FEE:
        await ctx.response.send_message(
            f':x: 소지금이 부족합니다. '
            f'(소지금: __**{having / 100:,.2f} Ł**__, 예측 세션 시작 비용: __{PREDICTION_FEE / 100:,.2f} Ł__)',
            ephemeral=True)
        return

    # update database
    add_money(ctx.user.id, -PREDICTION_FEE)

    until = datetime.now() + timedelta(seconds=duration_second)
    prediction = (title, option1, option2, until, dict(), dict())
    predictions[ctx.user.id] = prediction

    await ctx.response.send_message(
        f'__{ctx.user}__님의 예측 세션이 시작되었습니다.\n'
        f'예측 세션 제목: __**{title}**__, '
        f'예측 세션 지속 시간: __**{duration_second}초** ({until}까지)__.\n'
        f'세션 지속 시간을 늘리고 싶다면 `/predict extend`를 입력해주세요.\n'
        f'\n'
        f'> __**{option1}**__에 대한 예측을 하려면 __`/predict for option:1 dealer:{ctx.user} [베팅 금액]`__을 입력해주세요.\n'
        f'> __**{option2}**__에 대한 예측을 하려면 __`/predict for option:2 dealer:{ctx.user} [베팅 금액]`__을 입력해주세요.\n'
        f'> 예측 세션을 종료하려면 __**`/predict end`**__를 입력해주세요.',
        embed=get_prediction_info(ctx.user.id))


@prediction_group.command(name='extend', description='예측 세션 참여 시간을 연장합니다.')
async def prediction_extend(ctx: Interaction, duration_second_from_now: int):
    # check if user has prediction session
    if ctx.user.id not in predictions:
        await ctx.response.send_message(':x: 예측 세션이 진행 중이지 않습니다.', ephemeral=True)
        return

    if duration_second_from_now <= 0:
        await ctx.response.send_message(':x: 예측 세션의 지속 시간은 0초보다 커야 합니다.', ephemeral=True)
        return

    # update database
    title, option1, option2, until, option_1_players, option_2_players = predictions[ctx.user.id]
    until += timedelta(seconds=duration_second_from_now)
    predictions[ctx.user.id] = (title, option1, option2, until, option_1_players, option_2_players)

    await ctx.response.send_message(
        f'__{ctx.user}__님의 예측 세션의 지속 시간이 연장되었습니다.\n'
        f'예측 세션 제목: __**{title}**__, '
        f'예측 세션 지속 시간: __**{duration_second_from_now}초** ({until}까지)__.\n'
        f'세션 지속 시간을 늘리고 싶다면 `/predict extend`를 입력해주세요.\n'
        f'\n'
        f'> __**{option1}**__에 대한 예측을 하려면 __`/predict for option:1 dealer:{ctx.user} [베팅 금액]`__을 입력해주세요.\n'
        f'> __**{option2}**__에 대한 예측을 하려면 __`/predict for option:2 dealer:{ctx.user} [베팅 금액]`__을 입력해주세요.\n'
        f'> 예측 세션을 종료하려면 __**`/predict end`**__를 입력해주세요.',
        embed=get_prediction_info(ctx.user.id))


def get_prediction_info(dealer_id: int) -> Embed:
    embed = Embed(title='예측 세션 정보', colour=get_const('color.lofanfashasch'))

    title, option1, option2, until, option_1_players, option_2_players = predictions[dealer_id]
    embed.add_field(name='예측 세션 제목', value=title, inline=False)
    embed.add_field(name='예측 세션 종료 시간', value=str(until))
    embed.add_field(name='예측 세션 참여자 수', value=str(len(option_1_players) + len(option_2_players)))
    embed.add_field(name='예측 옵션', value=f'1번 옵션: {option1}\n2번 옵션: {option2}', inline=False)
    embed.add_field(name='예측자 수', value=f'1번 옵션: {len(option_1_players)}명, 2번 옵션: {len(option_2_players)}명',
                    inline=False)
    embed.add_field(name='베팅 금액', value=f'1번 옵션: {sum(option_1_players.values()) / 100:,.2f} Ł, '
                                           f'2번 옵션: {sum(option_2_players.values()) / 100:,.2f} Ł', inline=False)

    return embed


@prediction_group.command(name='for', description='예측 세션에 베팅합니다.')
async def prediction_for(ctx: Interaction, option: int, dealer: Member, amount: float):
    # preprocess amount
    amount = round(amount * 100)

    # check if amount is valid
    if amount <= 0:
        await ctx.response.send_message(':x: 베팅 금액은 0을 초과해야 합니다.', ephemeral=True)
        return

    # check if user has enough money
    having = get_money(ctx.user.id)
    if having < amount:
        await ctx.response.send_message(
            f':x: 소지금이 부족합니다. '
            f'(소지금: __**{having / 100:,.2f} Ł**__, 베팅 금액: __{amount / 100:,.2f} Ł__)',
            ephemeral=True)
        return

    # check if prediction session is running
    if dealer.id not in predictions:
        await ctx.response.send_message(':x: 예측 세션이 진행 중이 아닙니다.', ephemeral=True)
        return

    # check if prediction session is expired
    if datetime.now() > predictions[dealer.id][3]:
        await ctx.response.send_message(':x: 예측 세션 참여 제한시간이 경과되었습니다.', ephemeral=True)
        return

    # check if option is valid
    if option not in (1, 2):
        await ctx.response.send_message(':x: 옵션은 1 또는 2여야 합니다.', ephemeral=True)
        return

    # update database
    add_money(ctx.user.id, -amount)
    if option == 1:
        predictions[dealer.id][4][ctx.user.id] = predictions[dealer.id][4].get(ctx.user.id, 0) + amount
    else:
        predictions[dealer.id][5][ctx.user.id] = predictions[dealer.id][5].get(ctx.user.id, 0) + amount

    await ctx.response.send_message(
        f'{ctx.user.mention}님이 __**{amount / 100:,.2f} Ł**__를 __**{dealer}**__님의 예측 세션에 베팅하였습니다.',
        embed=get_prediction_info(dealer.id))


@prediction_group.command(name='end', description='예측 세션을 종료합니다.')
async def prediction_end(ctx: Interaction, result: int):
    # check if prediction session is running
    if ctx.user.id not in predictions:
        await ctx.response.send_message(':x: 예측 세션이 진행 중이 아닙니다.', ephemeral=True)
        return

    # check if result is valid
    if result not in (1, 2):
        await ctx.response.send_message(':x: 결과는 1 또는 2여야 합니다.', ephemeral=True)
        return

    # calculate multiplier
    winner_is_option_1 = result == 1
    option1_betting = sum(predictions[ctx.user.id][4].values())
    option2_betting = sum(predictions[ctx.user.id][5].values())
    total_betting = option1_betting + option2_betting
    option1 = predictions[ctx.user.id][1]
    option2 = predictions[ctx.user.id][2]
    message = f'__**{ctx.user}**__님의 예측 세션이 종료되었습니다.\n' \
              f'> 1번 옵션: __**{option1_betting / 100:,.2f} Ł**__\n' \
              f'> 2번 옵션: __**{option2_betting / 100:,.2f} Ł**__\n' \
              f'> 총 베팅 금액: __**{total_betting / 100:,.2f} Ł**__\n' \
              f'> 결과: **__{"1번" if winner_is_option_1 else "2번"} 옵션__ ' \
              f'({option1 if winner_is_option_1 else option2}) 승리**'
    try:
        multiplier = total_betting / (option1_betting if winner_is_option_1 else option2_betting)
    except ZeroDivisionError:
        add_money(ctx.user.id, total_betting)
        await ctx.response.send_message(
            message + '\n> 승리 옵션의 베팅 금액이 없으므로 베팅 진행자가 베팅 금액을 모두 가져갑니다.',
            embed=get_prediction_info(ctx.user.id))
        del predictions[ctx.user.id]
        return

    # update database
    for user_id, amount in predictions[ctx.user.id][4 if winner_is_option_1 else 5].items():
        add_money(user_id, round(amount * multiplier))

    # send message
    await ctx.response.send_message(message, embed=get_prediction_info(ctx.user.id))
    del predictions[ctx.user.id]


@prediction_group.command(name='info', description='예측 세션 정보를 확인합니다.')
async def prediction_info(ctx: Interaction, dealer: Member):
    # check if prediction session is running
    if dealer.id not in predictions:
        await ctx.response.send_message(':x: 예측 세션이 진행 중이 아닙니다.', ephemeral=True)
        return

    # send message
    await ctx.response.send_message(embed=get_prediction_info(dealer.id))


bot.tree.add_command(prediction_group)


lottery_group = app_commands.Group(name='lottery', description='로또 관련 명령어입니다.')
LOTTERY_PRICE = 2000
LOTTERY_NUMBER_RANGE = 100
LOTTERY_COLOR = 0xfcba03
LOTTERY_RE = re.compile(r'^로또: (\d{1,3}), (\d{1,3}), (\d{1,3}), (\d{1,3}), (\d{1,3}), (\d{1,3})$')
LOTTERY_FEE_RATE = 0.05


async def check_lottery_having(ctx: Interaction, amount: int) -> bool:
    # get current lottery having amount
    inventory = get_inventory(ctx.user.id)
    lotteries = list()
    now_having = 0
    for item in inventory.items():
        if item[0].startswith('로또: '):
            lotteries.append(item)
            now_having += item[1]

    # check if amount is valid
    if now_having + amount > 10:
        await ctx.response.send_message(f':x: 로또는 한번에 최대 10개까지 보유할 수 있습니다. '
                                        f'(현재 __{now_having}개__ 보유중입니다.)', ephemeral=True)
        return True

    return False


@lottery_group.command(
    name='auto', description=f'수를 자동으로 발급하여 로또를 구매합니다. 로또는 한 장에 {LOTTERY_PRICE / 100:,.2f} Ł입니다.')
async def lottery_auto(ctx: Interaction, amount: int):
    if await check_lottery_having(ctx, amount):
        return

    # check if having enough money
    having = get_money(ctx.user.id)
    if having < LOTTERY_PRICE * amount:
        await ctx.response.send_message(
            f':x: 로또 {amount}개를 구매하기에 충분한 돈이 없습니다. '
            f'(현재 __{having / 100:,.2f} Ł__ 보유중입니다.)', ephemeral=True)
        return

    # process buy
    bought = list()
    for _ in range(amount):
        lottery = process_buy_lottery(ctx.user.id, generate_lottery_numbers())
        bought.append(lottery)

    # send message
    await ctx.response.send_message(
        f'{ctx.user.mention}님이 __**{amount}**__개의 로또를 구매하였습니다.',
        embed=Embed(
            title='구매한 로또',
            description='\n'.join(f'**{i + 1}**. {", ".join(map(str, sorted(lotto)))}' for i, lotto in enumerate(bought)),
            color=LOTTERY_COLOR))


def generate_lottery_numbers() -> set[int]:
    numbers = set()
    while len(numbers) < 6:
        numbers.add(randint(1, LOTTERY_NUMBER_RANGE))
    return numbers


def process_buy_lottery(user_id: int, lotto_set: set[int]) -> set[int]:
    # update database
    add_money(user_id, -LOTTERY_PRICE)
    add_inventory(user_id, f'로또: {", ".join(map(str, sorted(lotto_set)))}', 1)
    return lotto_set


@lottery_group.command(
    name='buy', description=f'로또를 구매합니다. 로또는 한 장에 {LOTTERY_PRICE / 100:,.2f} Ł입니다.')
async def lottery_buy(ctx: Interaction, a: int, b: int, c: int, d: int, e: int, f: int):
    if await check_lottery_having(ctx, 1):
        return

    # check lottery validity
    lottery_set = {a, b, c, d, e, f}
    if len(lottery_set) != 6:
        await ctx.response.send_message(f':x: 로또는 1부터 {LOTTERY_NUMBER_RANGE}까지의 서로 다른 숫자 6개를 입력해야 합니다.',
                                        ephemeral=True)
        return

    for number in lottery_set:
        if not (1 <= number <= LOTTERY_NUMBER_RANGE):
            await ctx.response.send_message(f':x: 로또는 1부터 {LOTTERY_NUMBER_RANGE}까지의 서로 다른 숫자 6개를 입력해야 합니다.',
                                            ephemeral=True)
            return

    lottery = process_buy_lottery(ctx.user.id, lottery_set)

    # send message
    await ctx.response.send_message(
        f'{ctx.user.mention}님이 로또를 구매하였습니다.',
        embed=Embed(
            title='구매한 로또',
            description=f'{", ".join(map(str, sorted(lottery)))}',
            color=LOTTERY_COLOR))


def calculate_similarity(lotto1: set[int], lotto2: set[int]) -> float:
    difference = 0
    for number1 in lotto1:
        number2 = min(lotto2, key=lambda x: abs(x - number1))
        difference += min(abs(number1 - number2),
                          abs(number1 - number2 - LOTTERY_NUMBER_RANGE),
                          abs(number1 - number2 + LOTTERY_NUMBER_RANGE))
    for number1 in lotto2:
        number2 = min(lotto1, key=lambda x: abs(x - number1))
        difference += min(abs(number1 - number2),
                          abs(number1 - number2 - LOTTERY_NUMBER_RANGE),
                          abs(number1 - number2 + LOTTERY_NUMBER_RANGE))
    # return (1 - difference / 400) ** 15
    return exp((-0.8 * difference + 92) / 20) / exp(92 / 20)


def calculate_lottery_prices(win: set[int]):
    similarity_sum = 0
    similarity_by_user: dict[int, list[float]] = dict()
    lottery_count = 0
    for user_id, name, amount in get_lotteries():
        numbers = set(map(int, LOTTERY_RE.match(name).groups()))
        similarity = calculate_similarity(win, numbers)
        similarity_sum += similarity
        similarity_by_user[user_id] = similarity_by_user.get(user_id, list()) + [similarity]
        lottery_count += amount

        # print(f'{name} ({similarity})'
        #         f' -> {similarity_by_user[user_id]} ({sum(similarity_by_user[user_id]) / similarity_sum * lottery_count})')

    lottery_prize = lottery_count * LOTTERY_PRICE
    prices = dict()
    for user_id, similarities in similarity_by_user.items():
        prices[user_id] = round(sum(similarities) / similarity_sum * lottery_prize * (1 - LOTTERY_FEE_RATE))

    return prices


bot.tree.add_command(lottery_group)


def get_lottery_embed(prices, win, now) -> Embed:
    embed = Embed(
        title=f'{now.year}년 {now.month}월 {now.day}일 로또 당첨 결과',
        description=f'총 {sum(prices.values()) / 100:,.2f} Ł이 당첨되었습니다.',
        color=LOTTERY_COLOR)
    embed.add_field(name='참여자', value=f'{len(prices)}명', inline=True)
    embed.add_field(name='당첨 번호', value=', '.join(map(str, sorted(win))), inline=False)
    embed.add_field(name='최고 당첨 금액', value=f'{max(prices.values()) / 100:,.2f} Ł', inline=False)

    return embed


@tasks.loop(hours=1)
async def lottery_tick():
    # check new day
    last_record = datetime.now(timezone.utc)
    previous = parse_datetime(get_value('lottery.last_record'))
    # if not yet 7 days passed, return
    if previous is not None and previous.day + 7 <= last_record.day:
        return
    set_value('lottery.last_record', str(last_record))

    # log lottery
    win = generate_lottery_numbers()
    prices = calculate_lottery_prices(win)
    now = datetime.now(timezone.utc)
    result_message = f'{now.year}년 {now.month}월 {now.day}일: 로또 번호가 추첨되었습니다.'

    # send message per user
    for user_id, price in prices.items():
        await sleep(0)
        user = bot.get_user(user_id)
        if user is None:
            continue

        lotteries = filter(lambda x: x[0] == user_id, get_lotteries())

        embed = get_lottery_embed(prices, win, now)
        embed.add_field(
            name='구매한 로또 목록', value='\n'.join(map(lambda x: f'{x[1]} ({x[2]}개)', lotteries)), inline=False)
        embed.add_field(name='당첨 금액', value=f'{price / 100:,.2f} Ł', inline=False)

        # database update
        add_money(user_id, price)

        # send message
        await user.send(result_message, embed=embed)

    clear_lotteries()

    # send result message
    text_channel = bot.get_channel(get_const('channel.general'))
    await text_channel.send(result_message, embed=get_lottery_embed(prices, win, now))


if __name__ == '__main__':
    bot.run(get_secret('test_bot_token' if '-t' in argv else 'bot_token'))
