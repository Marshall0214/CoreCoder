from cursor_codec import decode_cursor, encode_cursor
from query import select_after


def page_rows(rows, limit, cursor):
    selected = select_after(rows, decode_cursor(cursor))[:limit + 1]
    items = selected[:limit]
    next_cursor = encode_cursor(selected[-1]) if len(selected) > limit else None
    return {"items": items, "next_cursor": next_cursor}
