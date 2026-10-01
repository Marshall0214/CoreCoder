from paging import page_rows


def browse_records(rows, limit=2, cursor=None):
    if limit < 1:
        raise ValueError("limit must be positive")
    return page_rows(rows, limit, cursor)
