from asyncio import sleep, TimeoutError as AsyncioTimeoutError, wait
from datetime import datetime, timezone, timedelta
from typing import Optional

from discord import NotFound, Member, VoiceState, InteractionMessage, RawReactionActionEvent, Interaction, Embed, \
    VoiceChannel, Reaction
from discord.app_commands import command, Choice, Group, MissingRole
from discord.app_commands.checks import has_role
from discord.ext import tasks
from discord.ext.commands import Cog, Bot

from cogs.admin_cog import OX_EMOJIS
from util import parse_timedelta, get_const, parse_datetime, eul_reul, check_reaction, generate_tax_message
from util.db import get_value, set_value, add_money, get_money, get_inventory, get_money_ranking, set_inventory, \
    get_tax, add_tax, add_money_with_tax, get_everyone_id, get_total_inventory_value

MONEY_CHECK_FEE = 50


def get_asset(user_id):
    wallet = get_money(user_id)

    inventory = get_total_inventory_value(user_id)

    ppl_price = int(get_value(get_const('db.ppl'))) * 100
    ppl_having, _ = get_inventory(user_id).get(get_const('db.ppl_having'), (0, 0))
    ppls = ppl_having * ppl_price

    tax = get_tax(user_id)

    return wallet + inventory + ppls - tax


def calculate_tax(x: float) -> float:
    """
    :param x: asset amount in centilos
    :return: tax in centilos
    """
    if x <= 0:
        return 0.0

    x /= 100
    result = (x - 1_000_000 * (1 - pow(0.999, 0.9 * x / 1000))) * 100
    return float(result)


class MoneyCog(Cog):
    item_group = Group(name='item', description='인벤토리와 아이템 관련 명령어입니다.')
    tax_group = Group(name='tax', description='세금과 관련된 명령어입니다.')

    def __init__(self, bot: Bot):
        self.bot = bot

        self.today_people = set()
        self.message_logs: dict[int, int] = dict()
        self.voice_people = set()

    async def collect_taxes(self):
        tasks_ = list()
        for member_id in get_everyone_id():
            asset = get_asset(member_id)
            tax = calculate_tax(asset)
            tax_rate = tax / asset

            add_tax(member_id, round(tax))

            member = self.bot.get_user(member_id)

            embed = Embed(title='로판파샤스 로스 세금 명세서', description=f'{member.mention}님께',
                          colour=get_const('color.lofanfashasch'))
            embed.add_field(name='자산 인정액', value=f'{asset / 100:,.2f} Ł')
            embed.add_field(name='자산 인정액에 대한 세율', value=f'{tax_rate * 100:,.2f}%')
            embed.add_field(name='세금', value=f'**{tax / 100:,.2f} Ł**')
            tasks_.append(member.send(
                '월 1일이 되어, 저번달 세금 명세서가 도착했습니다.\n'
                '`/tax check`를 통해 현재 미납된 세금의 액수를 확인할 수 있고, '
                '`/tax pay`를 통해 세금을 납부할 수 있습니다. '
                '세금을 납부하지 않으면 로스화 지급 시 지급액의 일정 부분을 자동으로 징수하여 지급합니다.', embed=embed))

        await wait(tasks_)

    @Cog.listener()
    async def on_ready(self):
        self.today_statistics.start()
        self.give_money_if_call.start()

    @Cog.listener()
    async def on_voice_state_update(self, member: Member, before: VoiceState, after: VoiceState):
        await self.voice_channel_notification(member, before, after)

        # track whether member is in voice channel
        if member.guild.id == get_const('guild.lofanfashasch'):
            if after.channel is None:
                self.voice_people.remove(member.id)
            if before.channel is None:
                self.voice_people.add(member.id)

    @Cog.listener()
    async def on_message(self, message: InteractionMessage):
        lofanfashasch_id = get_const('guild.lofanfashasch')

        # record today statistics
        try:
            if message.guild.id == lofanfashasch_id:
                today_messages = int(get_value('today_messages'))
                set_value('today_messages', today_messages + 1)
                today_messages_length = int(get_value('today_messages_length'))
                set_value('today_messages_length', today_messages_length + len(message.content))
                self.today_people.add(message.author.id)
        except AttributeError:
            pass

        # give money by message content
        try:
            if message.guild.id == lofanfashasch_id and (amount := len(set(message.content))):
                # 지급 기준 변경 시 readme.md 수정 필요
                add_money_with_tax(message.author.id, amount)
        except AttributeError:
            pass

    @Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        # record today statistics
        if payload.guild_id == get_const('guild.lofanfashasch'):
            today_reactions = get_value('today_reactions')
            set_value('today_reactions', int(today_reactions) + 1)
            self.today_people.add(payload.user_id)

    @tasks.loop(minutes=1)
    async def give_money_if_call(self):
        for member_id in self.voice_people:
            # 지급 기준 변경 시 readme.md 수정 필요
            add_money_with_tax(member_id, 5)

    @tasks.loop(minutes=1)
    async def today_statistics(self):
        last_record = datetime.now(timezone.utc)

        # check new day
        previous = parse_datetime(get_value('last_record'))
        # if same day, do nothing
        if previous.day == last_record.day:
            return

        set_value('last_record', str(last_record))

        # record ppl on database
        previous_ppl = int(get_value(get_const('db.ppl')))
        set_value(get_const('db.ppl'), str(len(self.today_people)))
        set_value(get_const('db.yesterday_ppl'), str(previous_ppl))

        # get server and send statistics message
        text_channel = self.bot.get_channel(get_const('channel.general'))

        await text_channel.send(f'# `{previous.date()}`의 통계\n{await self.generate_today_statistics()}')

        # collect taxes if it's first day of the month
        if last_record.day == 1:
            await self.collect_taxes()

        # reset
        set_value('today_messages', 0)
        set_value('today_messages_length', 0)
        set_value('today_calls', 0)
        set_value('today_call_duration', timedelta())
        set_value('today_reactions', 0)
        self.today_people.clear()

    async def voice_channel_notification(self, member: Member, before: VoiceState, after: VoiceState):
        if member.guild.id != get_const('guild.lofanfashasch'):
            return

        self.today_people.add(member.id)

        text_channel = member.guild.get_channel(get_const('channel.general'))

        # if leaving
        if before.channel is not None and len(before.channel.members) < 1:
            if before.channel.id not in self.message_logs:
                return

            message_id = self.message_logs.pop(before.channel.id)
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

        # if connecting to an empty channel
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
        self.message_logs[after.channel.id] = message.id

        today_calls = int(get_value('today_calls'))
        set_value('today_calls', today_calls + 1)

    async def generate_today_statistics(self) -> str:
        await sleep(0)

        # calculate total call duration
        call_duration = parse_timedelta(get_value('today_call_duration'))
        # add current call duration
        now = datetime.now(timezone.utc)
        for message_id in self.message_logs.values():
            try:
                message = await self.bot.get_channel(get_const('channel.general')).fetch_message(message_id)
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

    @command(description='지금까지의 오늘 통계를 확인합니다.')
    async def today(self, ctx: Interaction):
        now = datetime.now(timezone.utc)

        await ctx.response.send_message(
            f'`{now.date()}`의 현재까지의 통계\n{await self.generate_today_statistics()}', ephemeral=True)

    @command(description='음성 채널의 업타임을 계산합니다.')
    async def uptime(self, ctx: Interaction, channel: Optional[VoiceChannel] = None):
        if channel is None and ctx.user.voice is not None:
            channel = ctx.user.voice.channel

        if channel is None:
            await ctx.response.send_message('음성 채널 정보를 찾을 수 없습니다.', ephemeral=True)
            return

        if ctx.guild.id != get_const('guild.lofanfashasch'):
            await ctx.response.send_message('음성 채널 시작 시간에 대한 정보가 없습니다.', ephemeral=True)
            pass

        message_id = self.message_logs.get(channel.id)
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

    @command(description=f'소지금을 확인합니다. '
                         f'다른 사람의 소지금을 확인할 때에는 {MONEY_CHECK_FEE / 100:,.2f} Ł의 수수료가 부과됩니다.')
    async def money(self, ctx: Interaction, member: Optional[Member] = None, ephemeral: bool = True):
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
        ppl_having, _ = get_inventory(member.id).get(get_const('db.ppl_having'), (0, 0))
        ppl_money = 0
        if ppl_having > 0:
            ppl_price = int(get_value(get_const('db.ppl'))) * 100
            ppl_money = ppl_having * ppl_price
            ppl_message = f'PPL은 __**{ppl_having}개**__를 가지고 있고, PPL 가격은 총 __{ppl_money / 100:,.2f} Ł__입니다. '

        # unpaid taxes
        tax = get_tax(ctx.user.id)
        tax_message = ''
        if tax:
            tax_message = f'미납 세금은 __**{tax / 100:,.2f} Ł**__입니다. '

        total_message = f'따라서 총자산은 __**{(having + ppl_money - tax) / 100:,.2f} Ł**__입니다. '

        await ctx.response.send_message(f'{feed}__{member}__님의 소지금은 __**{having / 100:,.2f} Ł**__입니다. '
                                        f'{ppl_message}{tax_message}\n'
                                        f'{total_message}', ephemeral=ephemeral)

    @command(description='돈을 송금합니다.')
    async def transfer(self, ctx: Interaction, to: Member, amount: float):
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

    @command(description='돈 소지 현황을 확인합니다.')
    async def rank(self, ctx: Interaction, ephemeral: bool = True):
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

    @item_group.command(description='소지품을 확인합니다.')
    async def inventory(self, ctx: Interaction):
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

        for key, (count, price) in having.items():
            embed.add_field(name=key, value=f'* 가격: {price / 100:,.2f} Ł\n* 개수: {count}개', inline=True)

        await ctx.response.send_message(embed=embed, ephemeral=True)

    @item_group.command(description='가지고 있는 물건을 판매합니다.')
    async def sell(self, ctx: Interaction, item: str, amount: int = 1):
        inventory = get_inventory(ctx.user.id)
        having, price = inventory.get(item, (0, 0))

        if amount < 1:
            await ctx.response.send_message(f':x: 1개 이상만 판매할 수 있습니다.', ephemeral=True)
            return

        if amount > having:
            await ctx.response.send_message(
                f':x: 가지고 있는 것보다 많이 판매할 수 없습니다. '
                f'현재 __{having}개__ 가지고 있고, __{amount}개__ 판매를 시도했습니다.', ephemeral=True)
            return

        # check if sure when price == 0
        message = None
        if not price:
            await ctx.response.send_message(
                ':warning: 이 상품은 가격이 책정되어있지 않습니다. 이 상품을 판매한다면 __**0.00 Ł**__를 받게 됩니다. '
                '이 상품을 그래도 판매하시겠습니까?')
            message = await ctx.original_response()
            await wait((message.add_reaction(get_const('emoji.x')), message.add_reaction(get_const('emoji.o'))))

            try:
                res: tuple[Reaction, Member] = await self.bot.wait_for(
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

        # process sell
        delta = price * amount
        set_inventory(ctx.user.id, item, having - amount, price)
        non_tax, tax = add_money_with_tax(ctx.user.id, delta)
        tax_message = generate_tax_message(tax)
        content = f'__{item}__{eul_reul(item)} __{amount}개__ 판매하여 __**{delta / 100:,.2f} Ł**__를 얻었습니다. ' \
                  f'{tax_message}현재 소지금은 __{get_money(ctx.user.id) / 100:,.2f} Ł__입니다.'

        if message is None:
            await ctx.response.send_message(content)
        else:
            await message.edit(content=content)

    @sell.autocomplete("item")
    async def sell_autocomplete(self, ctx: Interaction, current: str) -> list[Choice[str]]:
        inventory = get_inventory(ctx.user.id)

        result = list(map(lambda x: Choice(name=f'{x[0]} ({x[1][0]} 개, 각각 {x[1][1] / 100:,.2f} Ł)', value=x[0]),
                          filter(lambda x: current.lower() in x[0].lower(), inventory.items())))

        return result

    @tax_group.command(description='미납 세금을 확인합니다.', name='check')
    async def tax_check(self, ctx: Interaction):
        # if there is no tax
        tax_amount = get_tax(ctx.user.id)
        if tax_amount <= 0:
            try:
                name = ctx.user.nick
            except AttributeError:
                name = ctx.user.name
            await ctx.response.send_message(f'현재 __{name}__님 앞으로 미납된 세금이 없습니다.', ephemeral=True)
            return

        await ctx.response.send_message(
            f'현재 __{ctx.user.nick}__님 앞으로 __**{tax_amount/100:,.2f} Ł**__가 미납되어 있습니다.', ephemeral=True)

    @tax_group.command(description='세금을 납세합니다. 액수를 지정하지 않으면 최대한 많이 납세합니다.', name='pay')
    async def tax_pay(self, ctx: Interaction, amount: float = 0.0):
        # postprocess amount
        amount = round(amount * 100)

        # calculate `will_pay`
        tax_amount = get_tax(ctx.user.id)
        having: int = get_money(ctx.user.id)
        if amount == 0.0:
            amount = tax_amount
        will_pay: int = min(tax_amount, amount)

        # if will_pay is zero then do nothing
        if will_pay <= 0:
            await ctx.response.send_message(f'납부할 세금이 없거나 세금 액수가 잘못 입력되어 작업이 취소되었습니다.', ephemeral=True)
            return

        # if user has not enough money
        if having < will_pay:
            await ctx.response.send_message(
                f'세금을 납세하기에 가진 돈이 충분하지 않습니다. __{will_pay / 100:,.2f} Ł__를 납세하도록 설정했고, '
                f'현재 __**{having / 100:,.2f} Ł**__를 가지고 있습니다.',
                ephemeral=True)
            return

        # process
        add_money(ctx.user.id, -will_pay)
        add_tax(ctx.user.id, -will_pay)
        await ctx.response.send_message(
            f'__**{will_pay / 100:,.2f} Ł**__를 납세했습니다. '
            f'현재 미납 세금은 __{(tax_amount - will_pay) / 100:,.2f} Ł__입니다.')

    @tax_group.command(description='주어진 액수에 대한 세금을 확인합니다. 액수를 지정하지 않으면 총 자산에 대한 세금을 확인합니다.', name='calculate')
    async def tax_calculate(self, ctx: Interaction, amount: float = 0.0):
        amount *= 100

        if amount <= 0.0:
            amount = get_asset(ctx.user.id)

        tax = calculate_tax(amount)
        await ctx.response.send_message(f'__{amount / 100:,.2f} Ł__에 대한 세율은 __{tax / amount * 100:.2f}%__로, '
                                        f'세금은 __**{tax / 100:,.2f} Ł/월**__입니다.',
                                        ephemeral=True)

    @has_role(get_const('role.harnavin'))
    @tax_group.command(description='세금을 징수합니다.', name='collect')
    async def tax_collect(self, ctx: Interaction):
        await self.collect_taxes()
        await ctx.response.send_message('세금을 징수했습니다.', ephemeral=True)

    @tax_collect.error
    async def new_lecture_error(self, ctx: Interaction, error: Exception):
        if isinstance(error, MissingRole):
            await ctx.response.send_message(':x: 명령어를 사용하기 위한 권한이 부족합니다!')
            return

async def setup(bot):
    await bot.add_cog(MoneyCog(bot))
