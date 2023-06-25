from typing import Optional

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


def set_account(user_id: int, money: int) -> None:
    with database.cursor() as cursor:
        cursor.execute('UPDATE money SET money = %s WHERE id = %s', (money, user_id))
        database.commit()


def add_account(user_id: int, money: int) -> None:
    with database.cursor() as cursor:
        cursor.execute('UPDATE money SET money = money + %s WHERE id = %s', (money, user_id))
        database.commit()


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
