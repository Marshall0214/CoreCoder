from datetime import date, timedelta


def next_day(value):
    return date.fromisoformat(value) + timedelta(days=1)
