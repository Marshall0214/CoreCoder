from settings import parse_settings
from transport import request_options


def build_request(url, raw_config):
    return {"url": url, **request_options(parse_settings(raw_config))}
