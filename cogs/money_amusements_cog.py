import re
from asyncio import sleep, TimeoutError as AsyncioTimeoutError
from datetime import datetime, timedelta, timezone
from math import inf, exp
from random import randint, shuffle
from typing import Union

from discord import app_commands, Interaction, Member, Embed, Message
from discord.app_commands import command
from discord.ext import tasks
from discord.ext.commands import Cog, Bot

from util import get_const, parse_datetime, check_reaction, custom_emoji
from util.db import get_value, get_inventory, get_money, add_money, add_inventory, set_inventory, get_lotteries, \
    set_value, clear_lotteries

PREDICTION_FEE = 500  # cŁ
LOTTERY_PRICE = 2000  # cŁ
LOTTERY_NUMBER_RANGE = 100
LOTTERY_COLOR = 0xfcba03
LOTTERY_RE = re.compile(r'^로또: (\d{1,3}), (\d{1,3}), (\d{1,3}), (\d{1,3}), (\d{1,3}), (\d{1,3})$')
LOTTERY_FEE_RATE = -0.1  # 수수료 비율
INSTANT_LOTTERY_EMOJIS = [
    custom_emoji('vea1', 1136151830691332146),
    custom_emoji('vea5', 1136151832863965204),
    custom_emoji('vea10', 1136151836521410565),
    custom_emoji('vea50', 1136151839847501904),
    custom_emoji('vea100', 1136151841718145064),
]
INSTANT_LOTTERY_SELECTIONS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']


async def validate_lottery_amount(ctx: Interaction, amount: int) -> bool:
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


def calculate_lottery_similarity(lotto1: set[int], lotto2: set[int]) -> float:
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
        similarity = calculate_lottery_similarity(win, numbers)
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


def get_lottery_embed(prices, win, now) -> Embed:
    embed = Embed(
        title=f'{now.year}년 {now.month}월 {now.day}일 로또 당첨 결과',
        description=f'총 {sum(prices.values()) / 100:,.2f} Ł이 당첨되었습니다.',
        color=LOTTERY_COLOR)
    embed.add_field(name='참여자', value=f'{len(prices)}명', inline=True)
    embed.add_field(name='당첨 번호', value=', '.join(map(str, sorted(win))), inline=False)
    embed.add_field(name='최고 당첨 금액', value=f'{max(prices.values()) / 100:,.2f} Ł', inline=False)

    return embed


class MoneyAmusementsCog(Cog):
    ppl_group = app_commands.Group(name="ppl", description="PPL 지수와 관련된 명령어입니다.")
    bet_group = app_commands.Group(name='bet', description='베팅 관련 명령어입니다.')
    prediction_group = app_commands.Group(name='predict', description='예측 베팅 관련 명령어입니다.')
    lottery_group = app_commands.Group(name='lottery', description='로또 관련 명령어입니다.')

    def __init__(self, bot: Bot):
        self.bot = bot

        self.bets: dict[int, dict[int, int]] = dict()
        self.predictions: dict[int, tuple[str, str, str, datetime, dict[int, int], dict[int, int]]] = dict()
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

    @Cog.listener()
    async def on_ready(self):
        self.lottery_tick.start()

    @ppl_group.command(name='check', description='로판파샤스의 금일 PPL 지수를 확인합니다.')
    async def ppl_check(self, ctx: Interaction, ephemeral: bool = True):
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
    async def ppl_buy(self, ctx: Interaction, amount: int = 1):
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
    async def ppl_sell(self, ctx: Interaction, amount: int = 1, force: bool = False):
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

    def make_bet_embed(self, ctx: Interaction, dealer: Member) -> Embed:
        """ make embed for checking betting information """

        total_bet = sum(self.bets[dealer.id].values())
        max_bet = max(self.bets[dealer.id].values())

        embed = Embed(
            title=f'__{dealer}__ 딜러 베팅 정보',
            description=f'최고 베팅 금액: __**{max_bet / 100:,.2f} Ł**__',
            colour=get_const('color.lofanfashasch'))
        for better_id, bet_ in self.bets[dealer.id].items():
            better = ctx.guild.get_member(better_id)
            embed.add_field(
                name=f'__{better}__' if better.id == ctx.user.id else str(better),
                value=f'**{bet_ / 100:,.2f} Ł** (M{(bet_ - max_bet) / 100:+,.2f} Ł)',
                inline=False)
        embed.set_footer(text=f'총 베팅 금액: {total_bet / 100:,.2f} Ł')

        return embed

    async def handle_bet(self, ctx: Interaction, dealer: Member, amount: int):
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
        if dealer.id not in self.bets:
            self.bets[dealer.id] = dict()
        if ctx.user.id not in self.bets[dealer.id]:
            self.bets[dealer.id][ctx.user.id] = amount
        else:
            self.bets[dealer.id][ctx.user.id] += amount

        # make embed and send message
        embed = self.make_bet_embed(ctx, dealer)
        my_total_bet = self.bets[dealer.id][ctx.user.id]
        total_bet = sum(self.bets[dealer.id].values())
        await ctx.response.send_message(
            f'{dealer.mention}님을 딜러로 하여 __**{amount / 100:,.2f} Ł**__을 베팅했습니다.\n'
            f'현재 __{ctx.user}__님이 베팅한 금액은 총 __**{my_total_bet / 100:,.2f} Ł**__이며, '
            f'딜러 앞으로 베팅된 금액은 총 __{total_bet / 100:,.2f} Ł__입니다.', embed=embed)

    @bet_group.command(name='raise', description='베팅 금액을 올립니다.')
    async def bet_raise(self, ctx: Interaction, dealer: Member, amount: float = 0.0):
        # preprocess amount
        amount = round(amount * 100)

        if not amount:
            await ctx.response.send_message(':x: 베팅 금액을 입력해주세요.', ephemeral=True)
            return

        # process betting
        await self.handle_bet(ctx, dealer, amount)

    @bet_group.command(name='info', description='베팅 현황을 확인합니다.')
    async def bet_info(self, ctx: Interaction, dealer: Member):
        if dealer.id not in self.bets:
            await ctx.response.send_message(':x: 베팅 정보가 없습니다.', ephemeral=True)
            return

        embed = self.make_bet_embed(ctx, dealer)
        await ctx.response.send_message(embed=embed)

    @bet_group.command(name='unroll', description='베팅된 금액을 모두 회수하여 제공합니다.')
    async def bet_unroll(self, ctx: Interaction, to: Member):
        if ctx.user.id not in self.bets:
            await ctx.response.send_message(':x: 베팅 정보가 없습니다.', ephemeral=True)
            return

        total_bet = sum(self.bets[ctx.user.id].values())

        # update database
        add_money(to.id, total_bet)
        self.bets.pop(ctx.user.id)

        await ctx.response.send_message(
            f'__{ctx.user}__ 딜러 베팅 금액 __**{total_bet / 100:,.2f} Ł**__을 {to.mention}님에게 제공하였습니다.')

    @prediction_group.command(name='extend', description='예측 세션 참여 시간을 연장합니다.')
    async def prediction_extend(self, ctx: Interaction, duration_second_from_now: int):
        # check if user has prediction session
        if ctx.user.id not in self.predictions:
            await ctx.response.send_message(':x: 예측 세션이 진행 중이지 않습니다.', ephemeral=True)
            return

        if duration_second_from_now <= 0:
            await ctx.response.send_message(':x: 예측 세션의 지속 시간은 0초보다 커야 합니다.', ephemeral=True)
            return

        # update database
        title, option1, option2, until, option_1_players, option_2_players = self.predictions[ctx.user.id]
        until += timedelta(seconds=duration_second_from_now)
        self.predictions[ctx.user.id] = (title, option1, option2, until, option_1_players, option_2_players)

        await ctx.response.send_message(
            f'__{ctx.user}__님의 예측 세션의 지속 시간이 연장되었습니다.\n'
            f'예측 세션 제목: __**{title}**__, '
            f'예측 세션 지속 시간: __**{duration_second_from_now}초** ({until}까지)__.\n'
            f'세션 지속 시간을 늘리고 싶다면 `/predict extend`를 입력해주세요.\n'
            f'\n'
            f'> __**{option1}**__에 대한 예측을 하려면 __`/predict for option:1 dealer:{ctx.user} [베팅 금액]`__을 입력해주세요.\n'
            f'> __**{option2}**__에 대한 예측을 하려면 __`/predict for option:2 dealer:{ctx.user} [베팅 금액]`__을 입력해주세요.\n'
            f'> 예측 세션을 종료하려면 __**`/predict end`**__를 입력해주세요.',
            embed=self.get_prediction_info(ctx.user.id))

    @tasks.loop(hours=1)
    async def lottery_tick(self):
        # check new day
        last_record = datetime.now(timezone.utc)
        previous = parse_datetime(get_value('lottery.last_record'))
        # if not yet 7 days passed, return
        if previous is not None and (last_record - previous).days < 7:
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
            user = self.bot.get_user(user_id)
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
        text_channel = self.bot.get_channel(get_const('channel.general'))
        await text_channel.send(result_message, embed=get_lottery_embed(prices, win, now))

    @prediction_group.command(name='start', description=f'예측 세션을 시작합니다. {PREDICTION_FEE / 100:,.2f}Ł가 소모됩니다.')
    async def prediction_start(self, ctx: Interaction, title: str, option1: str, option2: str,
                               duration_second: int = 30):
        # check if user already has a prediction session
        if ctx.user.id in self.predictions:
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
        self.predictions[ctx.user.id] = prediction

        await ctx.response.send_message(
            f'__{ctx.user}__님의 예측 세션이 시작되었습니다.\n'
            f'예측 세션 제목: __**{title}**__, '
            f'예측 세션 지속 시간: __**{duration_second}초** ({until}까지)__.\n'
            f'세션 지속 시간을 늘리고 싶다면 `/predict extend`를 입력해주세요.\n'
            f'\n'
            f'> __**{option1}**__에 대한 예측을 하려면 __`/predict for option:1 dealer:{ctx.user} [베팅 금액]`__을 입력해주세요.\n'
            f'> __**{option2}**__에 대한 예측을 하려면 __`/predict for option:2 dealer:{ctx.user} [베팅 금액]`__을 입력해주세요.\n'
            f'> 예측 세션을 종료하려면 __**`/predict end`**__를 입력해주세요.',
            embed=self.get_prediction_info(ctx.user.id))

    def get_prediction_info(self, dealer_id: int) -> Embed:
        embed = Embed(title='예측 세션 정보', colour=get_const('color.lofanfashasch'))

        title, option1, option2, until, option_1_players, option_2_players = self.predictions[dealer_id]
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
    async def prediction_for(self, ctx: Interaction, option: int, dealer: Member, amount: float):
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
        if dealer.id not in self.predictions:
            await ctx.response.send_message(':x: 예측 세션이 진행 중이 아닙니다.', ephemeral=True)
            return

        # check if prediction session is expired
        if datetime.now() > self.predictions[dealer.id][3]:
            await ctx.response.send_message(':x: 예측 세션 참여 제한시간이 경과되었습니다.', ephemeral=True)
            return

        # check if option is valid
        if option not in (1, 2):
            await ctx.response.send_message(':x: 옵션은 1 또는 2여야 합니다.', ephemeral=True)
            return

        # update database
        add_money(ctx.user.id, -amount)
        index = 4 if option == 1 else 5
        self.predictions[dealer.id][index][ctx.user.id] = self.predictions[dealer.id][index].get(ctx.user.id,
                                                                                                 0) + amount

        await ctx.response.send_message(
            f'{ctx.user.mention}님이 __**{amount / 100:,.2f} Ł**__를 __**{dealer}**__님의 예측 세션에 베팅하였습니다.',
            embed=self.get_prediction_info(dealer.id))

    @prediction_group.command(name='end', description='예측 세션을 종료합니다.')
    async def prediction_end(self, ctx: Interaction, result: int):
        # check if prediction session is running
        if ctx.user.id not in self.predictions:
            await ctx.response.send_message(':x: 예측 세션이 진행 중이 아닙니다.', ephemeral=True)
            return

        # check if result is valid
        if result not in (1, 2):
            await ctx.response.send_message(':x: 결과는 1 또는 2여야 합니다.', ephemeral=True)
            return

        # calculate multiplier
        winner_is_option_1 = result == 1
        option1_betting = sum(self.predictions[ctx.user.id][4].values())
        option2_betting = sum(self.predictions[ctx.user.id][5].values())
        total_betting = option1_betting + option2_betting
        option1 = self.predictions[ctx.user.id][1]
        option2 = self.predictions[ctx.user.id][2]
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
                embed=self.get_prediction_info(ctx.user.id))
            del self.predictions[ctx.user.id]
            return

        # update database
        for user_id, amount in self.predictions[ctx.user.id][4 if winner_is_option_1 else 5].items():
            add_money(user_id, round(amount * multiplier))

        # send message
        await ctx.response.send_message(message, embed=self.get_prediction_info(ctx.user.id))
        del self.predictions[ctx.user.id]

    @prediction_group.command(name='info', description='예측 세션 정보를 확인합니다.')
    async def prediction_info(self, ctx: Interaction, dealer: Member):
        # check if prediction session is running
        if dealer.id not in self.predictions:
            await ctx.response.send_message(':x: 예측 세션이 진행 중이 아닙니다.', ephemeral=True)
            return

        # send message
        await ctx.response.send_message(embed=self.get_prediction_info(dealer.id))

    @lottery_group.command(
        name='auto', description=f'수를 자동으로 발급하여 로또를 구매합니다. 로또는 한 장에 {LOTTERY_PRICE / 100:,.2f} Ł입니다.')
    async def lottery_auto(self, ctx: Interaction, amount: int):
        if amount <= 0:
            await ctx.response.send_message(':x: 구매할 로또의 개수는 0보다 커야 합니다.', ephemeral=True)
            return
        if await validate_lottery_amount(ctx, amount):
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
            f'{ctx.user.mention}님이 __**{amount}**__개의 로또를 구매하였습니다. '
            f'(총 __**{amount * LOTTERY_PRICE / 100:,.2f} Ł**__)',
            embed=Embed(
                title='구매한 로또',
                description='\n'.join(
                    f'**{i + 1}**. {", ".join(map(str, sorted(lotto)))}' for i, lotto in enumerate(bought)),
                color=LOTTERY_COLOR))

    @lottery_group.command(
        name='buy', description=f'로또를 구매합니다. 로또는 한 장에 {LOTTERY_PRICE / 100:,.2f} Ł입니다.')
    async def lottery_buy(self, ctx: Interaction, a: int, b: int, c: int, d: int, e: int, f: int):
        if await validate_lottery_amount(ctx, 1):
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
            f'{ctx.user.mention}님이 로또를 구매하였습니다. '
            f'(총 __**{LOTTERY_PRICE / 100:,.2f} Ł**__)',
            embed=Embed(
                title='구매한 로또',
                description=f'{", ".join(map(str, sorted(lottery)))}',
                color=LOTTERY_COLOR))

    @command(
        name='instant', description=f'즉석 복권을 발행합니다. 즉석 복권의 기대치는 100%입니다.')
    async def instant(self, ctx: Interaction, price: float):
        price = round(price * 100)
        having = get_money(ctx.user.id)

        # check if user has enough money
        if price > having * 0.1:
            await ctx.response.send_message(f'소지하고 있는 금액의 20%까지만 즉석 복권 발행에 사용할 수 있습니다. '
                                            f'현재 __{ctx.user}__님의 소지금은 __{having / 100:,.2f} Ł__이므로 '
                                            f'__**{having * 0.1 / 100:,.2f} Ł**__까지 즉석 복권을 발행할 수 있습니다.',
                                            ephemeral=True)
            return
        add_money(ctx.user.id, -price)

        # make lottery
        lottery: list[Union[tuple, int]] = list(range(5))
        shuffle(lottery)

        for i in range(5):
            lottery[i] = ((lottery[i] + 1) ** 2 / 11, INSTANT_LOTTERY_EMOJIS[lottery[i]])

        # make embed for lottery scratching
        embed = Embed(title='즉석 복권 발행',
                      description=f'__{ctx.user}__님이 __{price / 100:,.2f} Ł__ 상당의 즉석 복권을 발행했습니다.',
                      colour=LOTTERY_COLOR)
        embed.add_field(name='복권',
                        value=':orange_square: :orange_square: :orange_square: :orange_square: :orange_square:',
                        inline=False)
        embed.add_field(name='복권 당첨금 비율',
                        value=f'* {INSTANT_LOTTERY_EMOJIS[0]}: {100 / 11:.0f}% ({price * 1 / 1100:,.2f} Ł)\n'
                              f'* {INSTANT_LOTTERY_EMOJIS[1]}: {400 / 11:.0f}% ({price * 4 / 1100:,.2f} Ł)\n'
                              f'* {INSTANT_LOTTERY_EMOJIS[2]}: {900 / 11:.0f}% ({price * 9 / 1100:,.2f} Ł)\n'
                              f'* {INSTANT_LOTTERY_EMOJIS[3]}: {1600 / 11:.0f}% ({price * 16 / 1100:,.2f} Ł)\n'
                              f'* {INSTANT_LOTTERY_EMOJIS[4]}: {2500 / 11:.0f}% ({price * 25 / 1100:,.2f} Ł)\n',
        inline=False)
        await ctx.response.send_message(
            '5개의 버튼 중 하나를 1분 안에 눌러주세요. 선택을 진행하지 않으면 복권 발행이 취소되고 발행 비용이 반환되지 않습니다.',
            embed=embed)
        message = await ctx.original_response()

        for emoji in INSTANT_LOTTERY_SELECTIONS:
            await message.add_reaction(emoji)

        # wait for reaction added
        try:
            res = await self.bot.wait_for('reaction_add',
                                          check=check_reaction(INSTANT_LOTTERY_SELECTIONS, ctx, message.id),
                                          timeout=60.0)
        except AsyncioTimeoutError:
            await message.edit(content=':x: 시간이 초과되어 작업이 취소되었습니다. 복권 발행 비용은 반환되지 않습니다.',
                               embed=None)
            return

        # send and apply result
        index = INSTANT_LOTTERY_SELECTIONS.index(res[0].emoji)
        win = round(price * lottery[index][0])
        embed.set_field_at(0, name='복권', value=' '.join(map(lambda x: x[1], lottery)), inline=False)
        embed.add_field(name='결과', value=f'{lottery[index][1]} - __**{win / 100:,.2f} Ł** 당첨__')
        await message.edit(content=f'__**{index + 1}**__번을 선택했습니다. 당첨금은 __**{win / 100:,.2f} Ł**__입니다.',
                           embed=embed)
        add_money(ctx.user.id, win)


async def setup(bot):
    await bot.add_cog(MoneyAmusementsCog(bot))
