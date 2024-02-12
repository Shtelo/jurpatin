from asyncio import sleep
from datetime import date, datetime, timedelta
from pprint import pformat
from typing import Optional

from discord import Interaction, app_commands
from discord.app_commands import command, Choice
from discord.app_commands.checks import has_role
from discord.ext.commands import Cog

from util import get_const, get_exchange_rates, eun_neun, exchangeable_currencies


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


async def invoke_reminder(reminder: Reminder, ctx: Interaction, reminders: list):
    # set reminder
    await ctx.response.send_message(f'__{reminder.time}__에 알리는 리마인더를 설정했습니다. '
                                    f'리마인더 실행 중에 유르파틴이 재시작되는경우 **리마인더가 실행되지 않습니다.**')
    reminders.append(reminder)
    await reminder.wait()

    # notification
    content = f'\n> {reminder.message}' if reminder.message else ''
    await ctx.user.send(f'{ctx.user.mention} 리마인더가 알려드립니다. __{reminder.time}__입니다.{content}')
    reminders.remove(reminder)


class UtilCog(Cog):
    reminder_group = app_commands.Group(name='reminder', description='리마인더 관련 명령어입니다.')

    def __init__(self):
        self.reminders = list()

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

        await invoke_reminder(Reminder(time, message, ctx.user.id), ctx, self.reminders)

    @reminder_group.command(description='특정 시간에 리마인더를 설정합니다.')
    async def on(self, ctx: Interaction, hour: int, minute: int = 0, second: int = 0, day: Optional[int] = None,
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

        await invoke_reminder(Reminder(time, message, ctx.user.id), ctx, self.reminders)

    @reminder_group.command(description='예약되어있는 리마인더를 확인합니다.')
    async def check(self, ctx: Interaction):
        reminders = sorted(filter(lambda x: x.user_id == ctx.user.id, self.reminders), key=lambda x: x.time)

        if not reminders:
            await ctx.response.send_message('생성되어있는 리마인더가 없습니다.', ephemeral=True)
            return

        messages = list()
        for reminder in reminders:
            messages.append(f'* __**{reminder.time}**__' + (f': {reminder.message}' if reminder.message else ''))

        await ctx.response.send_message(f'총 __{len(reminders)}개__의 리마인더가 있습니다.\n' + '\n'.join(messages),
                                        ephemeral=True)

    @command(name='exchange', description='한국 원(KRW)을 다른 단위의 돈으로 환전합니다.')
    async def exchange(self, ctx: Interaction, currency: str, amount: float = 0.0):
        exchange_rates = get_exchange_rates()

        if currency not in exchange_rates:
            await ctx.response.send_message(f'화폐 `{currency}`에 대한 환전 정보를 확인할 수 없습니다.')
            return

        rate = exchange_rates[currency]
        if currency.endswith('(100)'):
            rate /= 100
            currency = currency[:-5]

        message = f'__1 {currency}__{eun_neun(currency)} __{rate:,.2f} 원__입니다. '

        if amount > 0:
            message += f'__{amount:,.2f} {currency}__{eun_neun(currency)} __**{rate * amount:,.2f} 원**__입니다.'

        await ctx.response.send_message(message)

    @exchange.autocomplete("currency")
    async def sell_autocomplete(self, ctx: Interaction, current: str) -> list[Choice[str]]:
        candidates = list()
        for currency in exchangeable_currencies:
            if current.upper() not in currency.upper():
                continue

            name = currency
            if currency.endswith('(100)'):
                name = currency[:-5]

            candidates.append(Choice(name=name, value=currency))

        return candidates

    @command(description='멋있는 문자로 바꿔줍니다')
    async def fancy(self, ctx: Interaction, message: str):
        original = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
        templates = [
            '𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷𝔄𝔅ℭ𝔇𝔈𝔉𝔊ℌℑ𝔍𝔎𝔏𝔐𝔑𝔒𝔓𝔔ℜ𝔖𝔗𝔘𝔙𝔚𝔛𝔜ℨ',
            '𝖆𝖇𝖈𝖉𝖊𝖋𝖌𝖍𝖎𝖏𝖐𝖑𝖒𝖓𝖔𝖕𝖖𝖗𝖘𝖙𝖚𝖛𝖜𝖝𝖞𝖟𝕬𝕭𝕮𝕯𝕰𝕱𝕲𝕳𝕴𝕵𝕶𝕷𝕸𝕹𝕺𝕻𝕼𝕽𝕾𝕿𝖀𝖁𝖂𝖃𝖄𝖅',
            '𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃𝓐𝓑𝓒𝓓𝓔𝓕𝓖𝓗𝓘𝓙𝓚𝓛𝓜𝓝𝓞𝓟𝓠𝓡𝓢𝓣𝓤𝓥𝓦𝓧𝓨𝓩',
            '𝒶𝒷𝒸𝒹𝑒𝒻𝑔𝒽𝒾𝒿𝓀𝓁𝓂𝓃𝑜𝓅𝓆𝓇𝓈𝓉𝓊𝓋𝓌𝓍𝓎𝓏𝒜𝐵𝒞𝒟𝐸𝐹𝒢𝐻𝐼𝒥𝒦𝐿𝑀𝒩𝒪𝒫𝒬𝑅𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵',
            '𝕒𝕓𝕔𝕕𝕖𝕗𝕘𝕙𝕚𝕛𝕜𝕝𝕞𝕟𝕠𝕡𝕢𝕣𝕤𝕥𝕦𝕧𝕨𝕩𝕪𝕫𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ',
            'ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘQʀꜱᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘQʀꜱᴛᴜᴠᴡxʏᴢ',
            '𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙',
            '𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭',
            '𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘓𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘞𝘟𝘠𝘡',
            '𝙖𝙗𝙘𝙙𝙚𝙛𝙜𝙝𝙞𝙟𝙠𝙡𝙢𝙣𝙤𝙥𝙦𝙧𝙨𝙩𝙪𝙫𝙬𝙭𝙮𝙯𝘼𝘽𝘾𝘿𝙀𝙁𝙂𝙃𝙄𝙅𝙆𝙇𝙈𝙉𝙊𝙋𝙌𝙍𝙎𝙏𝙐𝙑𝙒𝙓𝙔𝙕',
            '𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉']

        result = ['' for _ in templates]
        for letter in message:
            if letter in original:
                for i in range(len(templates)):
                    result[i] += templates[i][original.index(letter)]
            else:
                for i in range(len(templates)):
                    result[i] += letter

        await ctx.response.send_message('* ' + '\n* '.join(result))


async def setup(bot):
    await bot.add_cog(UtilCog())
