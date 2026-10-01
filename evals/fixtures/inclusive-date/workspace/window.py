from datetime import date
from date_utils import next_day


def query_window(start, end):
    return date.fromisoformat(start), date.fromisoformat(end)
