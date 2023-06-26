from typing import Optional, Any

from pymysql import connect

from util import get_secret

database = connect(
    host=get_secret('database.host'),
    user=get_secret('database.user'),
    password=get_secret('database.password'),
    database=get_secret('database.database'),
)


def get_money(user_id: int) -> Optional[int]:
    with database.cursor() as cursor:
        cursor.execute('SELECT money FROM money WHERE id = %s', (user_id,))
        data = cursor.fetchone()

        if data:
            return data[0]

        create_account(user_id)
        return 0


def create_account(user_id: int) -> None:
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO money (id) VALUES (%s)', (user_id,))
        database.commit()


def set_money(user_id: int, money: int) -> None:
    with database.cursor() as cursor:
        cursor.execute('UPDATE money SET money = %s WHERE id = %s', (money, user_id))
        database.commit()


def add_money(user_id: int, money: int) -> None:
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO money (id, money) VALUES (%s, %s) '
                       'ON DUPLICATE KEY UPDATE money = money + %s',
                       (user_id, money, money))
        database.commit()


def get_money_ranking(limit: int = 10) -> list[tuple[int, int, int]]:
    with database.cursor() as cursor:
        cursor.execute('SELECT id, money, rank() OVER (ORDER BY money DESC) FROM money LIMIT %s', (limit,))
        return cursor.fetchall()


def set_value(key: str, value: str) -> None:
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO `values` (`key`, value) VALUES (%s, %s)', (key, value))
        database.commit()


def get_value(key: str) -> Optional[str]:
    with database.cursor() as cursor:
        cursor.execute('SELECT value FROM `values` WHERE `key` = %s', (key,))
        data = cursor.fetchone()

        if data:
            return data[0]

        return None


def remove_value(key: str) -> None:
    with database.cursor() as cursor:
        cursor.execute('DELETE FROM `values` WHERE `key` = %s', (key,))
        database.commit()


def get_inventory(user_id: int) -> dict[str, int]:
    with database.cursor() as cursor:
        cursor.execute('SELECT name, amount FROM inventory WHERE id = %s', (user_id,))
        # noinspection PyTypeChecker
        return dict(cursor.fetchall())


def set_inventory(user_id: int, name: str, amount: int) -> None:
    with database.cursor() as cursor:
        if amount:
            cursor.execute('INSERT INTO inventory (id, name, amount) VALUES (%s, %s, %s) '
                           'ON DUPLICATE KEY UPDATE amount = %s', (user_id, name, amount, amount))
        else:
            cursor.execute('DELETE FROM inventory WHERE id = %s AND name = %s', (user_id, name))
        database.commit()


def add_inventory(user_id: int, name: str, amount: int) -> None:
    with database.cursor() as cursor:
        cursor.execute('INSERT INTO inventory (id, name, amount) VALUES (%s, %s, %s) '
                       'ON DUPLICATE KEY UPDATE amount = amount + %s', (user_id, name, amount, amount))
        database.commit()


if __name__ == '__main__':
    from pprint import pprint
    pprint(get_money_ranking())