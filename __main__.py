from asyncio import run
from os import listdir
from sys import argv

from discord import Intents
from discord.ext.commands import Bot, when_mentioned

from util import get_secret

intents = Intents.default()
intents.members = True
intents.message_content = True

# noinspection PyTypeChecker
bot = Bot(when_mentioned, intents=intents)


@bot.event
async def on_ready():
    # await bot.tree.sync()
    pass


async def load_extensions():
    for filename in listdir('cogs'):
        if not filename.endswith('.py'):
            continue
        await bot.load_extension(f'cogs.{filename[:-3]}')
        print(f'Loaded cog: `{filename[:-3]}`')


if __name__ == '__main__':
    run(load_extensions())
    bot.run(get_secret('test_bot_token' if '-t' in argv else 'bot_token'))
