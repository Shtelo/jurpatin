from typing import Optional

from pytimeparse.timeparse import timeparse
from datetime import datetime, timedelta


def parse_datetime(string: str) -> Optional[datetime]:
    if string is None:
        return None

    try:
        return datetime.strptime(string, '%Y-%m-%d %H:%M:%S.%f')
    except ValueError:
        return datetime.strptime(string, '%Y-%m-%d %H:%M:%S.%f%z')


def parse_timedelta(string: Optional[str]) -> timedelta:
    if string is None:
        return timedelta()

    seconds = timeparse(string)
    return timedelta(seconds=seconds)
