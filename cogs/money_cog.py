from asyncio import sleep
from datetime import datetime, timezone, timedelta
from typing import Optional

from discord import NotFound, Member, VoiceState, InteractionMessage, RawReactionActionEvent, Interaction, Embed, \
    VoiceChannel
from discord.app_commands import command
from discord.ext import tasks
from discord.ext.commands import Cog, Bot

from util import parse_timedelta, get_const, parse_datetime
from util.db import get_value, set_value, add_money, get_money, get_inventory, get_money_ranking

MONEY_CHECK_FEE = 50


class MoneyCog(Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

        self.today_people = set()
        self.message_logs: dict[int, int] = dict()
        self.voice_people = set()

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
                add_money(message.author.id, amount)
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
            add_money(member_id, 5)

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

        # reset
        set_value('today_messages', 0)
        set_value('today_messages_length', 0)
        set_value('today_calls', 0)
        set_value('today_call_duration', timedelta())
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
    async def money(self, ctx: Interaction, member: Optional[Member] = None, total: bool = False,
                    ephemeral: bool = True):
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
        ppl_having, _ = get_inventory(member.id).get(get_const('db.ppl_having'), (0, 0))
        if total and ppl_having > 0:
            ppl_price = int(get_value(get_const('db.ppl'))) * 100
            ppl_money = ppl_having * ppl_price
            ppl_message = f'PPL은 __**{ppl_having}개**__를 가지고 있고, PPL 가격은 총 __{ppl_money / 100:,.2f} Ł__입니다.\n'

            total_message = f'따라서 총자산은 __**{(having + ppl_money) / 100:,.2f} Ł**__입니다.\n'

        await ctx.response.send_message(f'{feed}__{member}__님의 소지금은 __**{having / 100:,.2f} Ł**__입니다.\n'
                                        f'{ppl_message}{total_message}', ephemeral=ephemeral)

    @command(name='inventory', description='소지품을 확인합니다.')
    async def inventory_(self, ctx: Interaction):
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


async def setup(bot):
    await bot.add_cog(MoneyCog(bot))
