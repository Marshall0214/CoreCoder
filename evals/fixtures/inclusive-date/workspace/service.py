from datetime import date
from window import query_window


def query_dates(values, start, end):
    lower, upper = query_window(start, end)
    return [value for value in values if lower <= date.fromisoformat(value) < upper]
