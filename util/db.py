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


if __name__ == '__main__':
    money = get_money(366565792910671873)
    print(money)
