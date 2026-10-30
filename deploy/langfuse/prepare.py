"""Generate ignored local credentials; never overwrite secrets or change Docker settings."""
import argparse
import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def docker_storage():
    if os.name != 'nt':
        return {'check': 'operator-managed Docker storage on non-Windows'}
    settings_path = Path(os.environ['APPDATA']) / 'Docker/settings-store.json'
    settings = json.loads(settings_path.read_text(encoding='utf-8'))
    path = settings.get('CustomWslDistroDir') or settings.get('diskImageLocation')
    if not isinstance(path, str) or not path.lower().startswith('d:\\'):
        raise ValueError('Confirm Docker Desktop disk storage on D: before preparing this stack')
    return {'docker_disk_directory': path}


def prepare(output, port=3300, minio_port=13390):
    output = Path(output).resolve()
    if (output.exists() or not output.is_relative_to(ROOT / '.tmp') or port == minio_port
            or any(type(value) is not int or not 1024 <= value <= 65535 for value in (port, minio_port))):
        raise ValueError('Use a fresh project .tmp directory and two distinct unprivileged ports')
    if os.name == 'nt' and output.drive.lower() != 'd:':
        raise ValueError('Keep credentials and runtime files on D:')
    storage = docker_storage()
    values = {key: secrets.token_hex(24) for key in ('POSTGRES_PASSWORD', 'CLICKHOUSE_PASSWORD', 'REDIS_PASSWORD',
               'MINIO_PASSWORD', 'LANGFUSE_SALT', 'NEXTAUTH_SECRET', 'LANGFUSE_LOGIN_PASSWORD')}
    values.update(LANGFUSE_ENCRYPTION_KEY=secrets.token_hex(32), LANGFUSE_PUBLIC_KEY='pk-lf-' + secrets.token_hex(16),
                  LANGFUSE_SECRET_KEY='sk-lf-' + secrets.token_hex(24), LANGFUSE_LOGIN_EMAIL='admin@corecoder.local',
                  LANGFUSE_PORT=str(port), MINIO_PORT=str(minio_port), LANGFUSE_BASE_URL=f'http://127.0.0.1:{port}')
    output.mkdir(parents=True)
    (output / '.env').write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
    (output / 'login.txt').write_text('Local Langfuse only. Do not commit this file.\n'
        f"URL: {values['LANGFUSE_BASE_URL']}\nEmail: {values['LANGFUSE_LOGIN_EMAIL']}\n"
        f"Password: {values['LANGFUSE_LOGIN_PASSWORD']}\n", encoding='utf-8')
    (output / 'storage.json').write_text(json.dumps(storage, indent=2), encoding='utf-8')
    return {'url': values['LANGFUSE_BASE_URL'], 'env_file': str(output / '.env'), 'storage': storage}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=3300)
    parser.add_argument('--minio-port', type=int, default=13390)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.port, args.minio_port)))
