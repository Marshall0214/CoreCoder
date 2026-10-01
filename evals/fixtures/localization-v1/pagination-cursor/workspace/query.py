def select_after(rows, after):
    ordered = sorted(rows, key=lambda row: (row["created"], row["id"]))
    if after is None:
        return ordered
    return [row for row in ordered if row["created"] > after[0]]
