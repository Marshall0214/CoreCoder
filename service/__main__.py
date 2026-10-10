"""Launch one local ASGI process from the repository checkout."""

import argparse
from pathlib import Path

import uvicorn

from service.app import create_app

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeout', type=int, default=240)
    args = parser.parse_args()
    uvicorn.run(create_app(output=args.output, timeout=args.timeout), host='127.0.0.1', port=args.port)
