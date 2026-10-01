import base64
import json


def encode_cursor(row):
    data = [row["created"], row["id"]]
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def decode_cursor(cursor):
    if cursor is None:
        return None
    return tuple(json.loads(base64.urlsafe_b64decode(cursor).decode()))
