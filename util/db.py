from datetime import datetime, timedelta, date
from typing import Optional, Any, Generator

from pymysql import connect, Connection

from util import get_secret

_get_connection_cache: Optional[Connection] = None
_get_connection_last_used = None


def get_connection():
    global _get_connection_cache, _get_connection_last_used
    now = datetime.now()

    # if old connection
    if _get_connection_last_used is not None \
            and now - _get_connection_last_used > timedelta(hours=1) \
            and _get_connection_cache is not None:
        _get_connection_cache.close()
        _get_connection_cache = None

    # if connection does not exist
    if _get_connection_cache is None:
        _get_connection_cache = connect(
            host=get_secret('database.host'),
            user=get_secret('database.user'),
            password=get_secret('database.password'),
            database=get_secret('database.database'),
        )
        _get_connection_last_used = now

    return _get_connection_cache


def get_money(user_id: int) -> int:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT money FROM money WHERE id = %s', (user_id,))
        data = cursor.fetchone()

        if data:
            return data[0]

        create_account(user_id)
        return 0


def create_account(user_id: int) -> None:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO money (id) VALUES (%s)', (user_id,))
        database.commit()


def set_money(user_id: int, money: int) -> None:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('UPDATE money SET money = %s WHERE id = %s', (money, user_id))
        database.commit()


def add_money(user_id: int, money: int) -> None:
    """
    :param user_id: User ID
    :param money: Amount of money to add in cŁ
    """
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO money (id, money) VALUES (%s, %s) '
                       'ON DUPLICATE KEY UPDATE money = money + %s',
                       (user_id, money, money))
        database.commit()


def get_money_ranking(limit: int = 10) -> tuple[tuple[Any, ...], ...]:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT id, money, rank() OVER (ORDER BY money DESC) FROM money LIMIT %s', (limit,))
        return cursor.fetchall()


def set_value(key: str, value) -> None:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO `values` (`key`, value) VALUES (%s, %s) '
                       'ON DUPLICATE KEY UPDATE value = %s', (key, value, value))
        database.commit()


def get_value(key: str) -> Optional[str]:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT value FROM `values` WHERE `key` = %s', (key,))
        data = cursor.fetchone()

        if data:
            return data[0]

        return None


def remove_value(key: str) -> None:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('DELETE FROM `values` WHERE `key` = %s', (key,))
        database.commit()


def get_inventory(user_id: int) -> dict[str, tuple[int, int]]:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT name, amount, price FROM inventory WHERE id = %s', (user_id,))
        # noinspection PyTypeChecker
        return dict(map(lambda x: (x[0], (x[1], x[2])), cursor.fetchall()))


def get_total_inventory_value(user_id) -> int:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT SUM(price * amount) FROM inventory WHERE id = %s', (user_id,))
        data = cursor.fetchone()
    return int(data[0] if data[0] is not None else 0)


def set_inventory(user_id: int, name: str, amount: int, price: int = 0) -> None:
    database = get_connection()
    with database.cursor() as cursor:
        if amount:
            cursor.execute('INSERT INTO inventory (id, name, amount, price) VALUES (%s, %s, %s, %s) '
                           'ON DUPLICATE KEY UPDATE amount = %s, price = %s',
                           (user_id, name, amount, price, amount, price))
        else:
            cursor.execute('DELETE FROM inventory WHERE id = %s AND name = %s', (user_id, name))
        database.commit()


def add_inventory(user_id: int, name: str, amount: int, price: int = 0) -> None:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO inventory (id, name, amount, price) VALUES (%s, %s, %s, %s) '
                       'ON DUPLICATE KEY UPDATE amount = amount + %s', (user_id, name, amount, price, amount))
        database.commit()


# noinspection PyTypeChecker
def get_lotteries() -> tuple[tuple[int, str, int], ...]:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute("SELECT id, name, amount FROM inventory WHERE name LIKE '로또: %'")
        return cursor.fetchall()


def clear_lotteries():
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute("DELETE FROM inventory WHERE name LIKE '로또: %'")
        database.commit()


# noinspection PyTypeChecker
def get_streak_information(user_id: int) -> tuple[int, date, int]:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT streak, last_attend, max_streak FROM attendance WHERE id = %s', (user_id,))
        return cursor.fetchall()[0]


def update_streak(user_id: int, streak: int, today: date, max_streak: int):
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO attendance (id, streak, last_attend, max_streak) VALUES (%s, %s, %s, %s) '
                       'ON DUPLICATE KEY UPDATE streak = %s, last_attend = %s, max_streak = %s',
                       (user_id, streak, today, max_streak, streak, today, max_streak))
        database.commit()


def get_streak_rank() -> tuple[tuple[int, int]]:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT id, streak FROM attendance ORDER BY streak DESC LIMIT 10')
        return cursor.fetchall()


def get_tax(user_id: int) -> int:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT tax FROM money WHERE id = %s', (user_id,))
        data = cursor.fetchone()
    return 0 if data is None else data[0]


def add_tax(user_id: int, amount: int):
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO money (id, tax) VALUES (%s, %s) '
                       'ON DUPLICATE KEY UPDATE tax = tax + %s',
                       (user_id, amount, amount))
        database.commit()


def add_money_with_tax(user_id: int, amount: int) -> tuple[int, int]:
    """
    proceeds tax paying and give money.

    :param user_id:
    :param amount:
    :return: non_tax amount and tax amount
    """

    tax = min(round(amount * 0.3), get_tax(user_id))
    non_tax = amount - tax

    add_tax(user_id, -tax)
    add_money(user_id, non_tax)

    return non_tax, tax


def get_everyone_id() -> Generator[int, None, None]:
    database = get_connection()
    with database.cursor() as cursor:
        cursor.execute('SELECT id FROM money')
        while (row := cursor.fetchone()) is not None:
            yield row[0]


if __name__ == '__main__':
    set_value('test', timedelta(seconds=1239487))
