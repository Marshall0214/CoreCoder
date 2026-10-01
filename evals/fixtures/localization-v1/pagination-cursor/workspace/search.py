def search_title(rows, text):
    return [row for row in rows if text in row.get("title", "")]
