def newest_first(rows):
    return sorted(rows, key=lambda row: row["created"], reverse=True)
