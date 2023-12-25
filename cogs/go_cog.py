from copy import copy
from random import random
from typing import Optional

from PIL import Image, ImageDraw, ImageFont
from discord import app_commands, Interaction, File
from discord.app_commands import Choice
from discord.ext.commands import Cog, Bot

from util import eul_reul
from util.db import get_connection

SIDE = 19
IMAGE_SIDE = 128

GO_LU = Image.open('res/go/go1.png')
GO_RU = Image.open('res/go/go2.png')
GO_LD = Image.open('res/go/go3.png')
GO_RD = Image.open('res/go/go4.png')
GO_U = Image.open('res/go/go5.png')
GO_L = Image.open('res/go/go6.png')
GO_R = Image.open('res/go/go7.png')
GO_D = Image.open('res/go/go8.png')
GO_H = Image.open('res/go/go9.png')
GO_BLANK = Image.open('res/go/go0.png')
GO_BLACK = Image.open('res/go/gob.png')
GO_WHITE = Image.open('res/go/gow.png')
GO_BLACK_PREVIOUS = Image.open('res/go/gobp.png')
GO_WHITE_PREVIOUS = Image.open('res/go/gowp.png')
GO_NONE = Image.open('res/go/gon.png')

Board = list[list[Image]]


def get_blank_board() -> Board:
    row_1 = [GO_LU] + [GO_U] * 17 + [GO_RU]
    row_general = [GO_L] + [GO_BLANK] * 17 + [GO_R]
    row_hwajeom = [GO_L] + [GO_BLANK] * 2 + [GO_H] + ([GO_BLANK] * 5 + [GO_H]) * 2 + [GO_BLANK] * 2 + [GO_R]
    row_19 = [GO_LD] + [GO_D] * 17 + [GO_RD]

    return [
        row_1,
        copy(row_general),
        copy(row_general),
        copy(row_hwajeom),
        copy(row_general),
        copy(row_general),
        copy(row_general),
        copy(row_general),
        copy(row_general),
        copy(row_hwajeom),
        copy(row_general),
        copy(row_general),
        copy(row_general),
        copy(row_general),
        copy(row_general),
        copy(row_hwajeom),
        copy(row_general),
        copy(row_general),
        copy(row_19),
    ]


def draw_board(content: str, last: int = -1) -> Board:
    board = get_blank_board()

    for i in range(min(len(content), SIDE*SIDE)):
        if not content[i]:
            continue

        y = i // SIDE
        x = i % SIDE

        if content[i] == 'w':
            board[y][x] = GO_WHITE_PREVIOUS if last == i else GO_WHITE
        elif content[i] == 'b':
            board[y][x] = GO_BLACK_PREVIOUS if last == i else GO_BLACK

    return board


def create_image(board: str, last: int = -1, id_: int = -1) -> Image:
    image = Image.new("RGB", ((SIDE + 2) * IMAGE_SIDE, (SIDE + 2) * IMAGE_SIDE), '#eac159')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('res/font/Pretendard-Light_0.otf', 64)

    # write id
    if id_ != -1:
        text = f'#{id_}'
        w = draw.textlength(text, font)
        dx = round((IMAGE_SIDE - w) / 2)
        dy = round((IMAGE_SIDE - 64) / 2)
        draw.text((dx, dy), text, (0, 0, 0), font)

    # write label
    for i in range(SIDE):
        text = chr(ord('A') + i)
        w = draw.textlength(text, font)
        dx = round((IMAGE_SIDE - w) / 2)
        dy = round((IMAGE_SIDE - 64) / 2)
        draw.text(((i + 1) * IMAGE_SIDE + dx, 0 + dy), text, (0, 0, 0), font)
        draw.text(((i + 1) * IMAGE_SIDE + dx, 20 * IMAGE_SIDE + dy), text, (0, 0, 0), font)

        text = str(i+1)
        w = draw.textlength(text, font)
        dx = round((IMAGE_SIDE - w) / 2)
        dy = round((IMAGE_SIDE - 64) / 2)
        draw.text((dx, (i + 1) * IMAGE_SIDE + dy), text, (0, 0, 0), font)
        draw.text((dx + 20 * IMAGE_SIDE, (i + 1) * IMAGE_SIDE + dy), text, (0, 0, 0), font)

    # draw dots
    board = draw_board(board, last)
    for i in range(SIDE):
        for j in range(SIDE):
            content = board[i][j]
            image.paste(content, (IMAGE_SIDE * (j+1), IMAGE_SIDE * (i+1)))

    return image


def change_single(board: str, y: int, x: int, to: str) -> str:
    now = list(' ' * SIDE * SIDE)
    for i in range(len(board)):
        now[i] = board[i]
    now[y * SIDE + x] = to
    return ''.join(now)


def get_board_by_id(id_: int) -> tuple[str, int, int, int]:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT content, last, changes, last_putter FROM go_board WHERE id = %s', (id_,))
        data = cursor.fetchone()
    return data if data is not None else ('', -1, 0, -1)


def update_board_by_id(id_: int, board: str, last: int, changes: int, last_putter: int):
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO go_board(id, content, last, last_putter) VALUES (%s, %s, %s, %s) '
                       'ON DUPLICATE KEY UPDATE content = %s, last = %s, changes = %s, last_putter = %s',
                       (id_, board, last, last_putter, board, last, changes, last_putter))
        database.commit()


def parse_place(place: str):
    if len(place) < 1:
        return -1, -1

    place = place.upper()

    x = 0
    y = 0

    if place[0] in 'ABCDEFGHIJKLMNOPQRS':
        x = ord(place[0]) - ord('A')
        try:
            y = int(place[1:]) - 1
        except ValueError:
            y = -1
    elif place[-1] in 'ABCDEFGHIJKLMNOPQRS':
        x = ord(place[-1]) - ord('A')
        try:
            y = int(place[:-1]) - 1
        except ValueError:
            y = -1

    if not (0 <= x < SIDE):
        x = -1
    if not (0 <= y < SIDE):
        y = -1

    return x, y


class GoCog(Cog):
    go_group = app_commands.Group(name="go", description="바둑판과 관련된 명령어입니다.")

    def __init__(self, bot: Bot):
        self.bot = bot

    @go_group.command(name='show', description='현재 바둑판을 확인합니다.')
    async def show(self, ctx: Interaction, id_: int = 0):
        board, last, changes, last_putter = get_board_by_id(id_)
        image = create_image(board, last, id_)
        image.save('res/go/tmp.png')

        if last_putter is None or last_putter == -1:
            last_putter = ''
        else:
            user = self.bot.get_user(last_putter)
            if user is not None:
                last_putter = f'마지막 착수는 __{user.name}__님입니다. '

        await ctx.response.send_message(
            f'__{id_}번__ 바둑판을 확인합니다. {last_putter}',
            file=File('res/go/tmp.png', f'go_{id_}_{changes}.png'))

    @go_group.command(name='put', description='바둑판에 착수합니다.')
    async def put(self, ctx: Interaction, color: str, place: str, id_: int = 0):
        board, last, changes, _ = get_board_by_id(id_)

        x, y = parse_place(place)
        if y == -1 or x == -1:
            await ctx.response.send_message('입력한 위치가 올바르지 않습니다.', ephemeral=True)
            return

        board = change_single(board, y, x, color)
        changes += 1
        update_board_by_id(id_, board, y * SIDE + x, changes, ctx.user.id)

        image = create_image(board, y * SIDE + x, id_)
        image.save('res/go/tmp.png')

        color = '흑' if color == 'b' else '백' if color == 'w' else 'undefined'
        await ctx.response.send_message(
            f'__{ctx.user.name}__님이 __{id_}번 바둑판 **{place.upper()}**__에 __{color}__{eul_reul(color)} 착수했습니다.',
            file=File('res/go/tmp.png', f'go_{id_}_{changes}.png'))

    @put.autocomplete('color')
    async def color(self, _ctx: Interaction, _current: str) -> list[Choice]:
        return [Choice(name='흑 Black', value='b'),
                Choice(name='백 White', value='w'),
                Choice(name='없애기 None', value=' ')]

    @go_group.command(name='clear', description='바둑판을 초기화합니다.')
    async def clear(self, ctx: Interaction, id_: int = 0):
        board, last, changes, _ = get_board_by_id(id_)
        changes += 1
        update_board_by_id(id_, '', -1, changes, id_)

        image = create_image('')
        image.save('res/go/tmp.png')

        await ctx.response.send_message(
            f'__{id_}번__ 바둑판을 초기화했습니다.', file=File('res/go/tmp.png', f'go_{id_}_{changes}.png'))


async def setup(bot: Bot):
    await bot.add_cog(GoCog(bot))