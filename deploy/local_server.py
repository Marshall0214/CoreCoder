"""Private loopback server used only by the local HTTP acceptance harness."""

import argparse
from pathlib import Path

import uvicorn

from service.app import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--faults', action='store_true')
    args = parser.parse_args()
    app = create_app(args.data, worker_module='tests.dispatch_worker_stub' if args.faults else 'service.worker')
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, log_level='warning'))

    @app.post('/__acceptance__/shutdown', include_in_schema=False)
    async def shutdown():
        server.should_exit = True
        return {'stopping': True}

    server.run()


if __name__ == '__main__':
    main()
