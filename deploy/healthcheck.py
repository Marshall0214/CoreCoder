"""Dependency-free HTTP readiness probe, without model calls."""

import json
from urllib.request import urlopen


def main():
    with urlopen('http://127.0.0.1:8000/health', timeout=2) as response:
        if response.status != 200 or json.load(response) != {'status': 'ok'}:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
