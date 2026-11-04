"""Verified official-registry transfer into a task-owned D: cache; no daemon settings changes."""
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile

from evals.swebench_mini import docker, sha, write


def space(path, required=15_000_000_000):
    if shutil.disk_usage(path).free < required:
        raise OSError('Insufficient free space on runtime drive; batch paused')


class ImageTransfer:
    def __init__(self, folder, proxy='http://127.0.0.1:7890'):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.proxy = proxy

    def fetch(self, url, destination, header=None, resume=False, seconds=60):
        args = ['curl.exe' if os.name == 'nt' else 'curl', '-q', '--location', '--fail',
                '--silent', '--show-error', '--connect-timeout', '10', '--max-time', str(seconds),
                '--output', str(destination)]
        if self.proxy:
            args += ['--proxy', self.proxy]
        if header:
            args += ['--header', '@' + str(header)]
        if resume:
            args += ['--continue-at', '-']
        return subprocess.run(args + [url], capture_output=True, timeout=seconds + 15, check=False).returncode

    def metadata(self, url, destination, header=None):
        for _ in range(4):
            if self.fetch(url, destination, header, seconds=30) == 0:
                return destination.read_bytes()
        raise OSError('Official registry metadata transfer failed: ' + destination.name)

    def authenticate(self, repo, header):
        raw = self.metadata('https://auth.docker.io/token?service=registry.docker.io&scope=repository:'
                            + repo + ':pull', self.folder / 'token.json')
        token = json.loads(raw)['token']
        header.write_text('Authorization: Bearer ' + token + '\nAccept: application/vnd.oci.image.index.v1+json, '
                          'application/vnd.docker.distribution.manifest.list.v2+json, '
                          'application/vnd.oci.image.manifest.v1+json, '
                          'application/vnd.docker.distribution.manifest.v2+json\n', encoding='ascii')

    def load(self, tag):
        if not tag.startswith('swebench/sweb.eval.x86_64.') or not tag.endswith(':latest'):
            raise ValueError('Only official single-instance task images')
        try:
            image = json.loads(docker('image', 'inspect', tag).decode())[0]
        except subprocess.CalledProcessError:
            image = None
        if image:
            return {'image_id': image['Id'], 'layers': image['RootFS']['Layers'], 'owned': False,
                    'tag': tag, 'source': 'preexisting_local_image'}
        repo = tag.rsplit(':', 1)[0]
        base = 'https://registry-1.docker.io/v2/' + repo
        header = self.folder / 'headers.txt'
        self.authenticate(repo, header)
        manifest_file = self.folder / 'manifest.json'
        # Once selected, resume by manifest digest rather than mutable latest.
        ref = 'sha256:' + sha(manifest_file) if manifest_file.exists() else 'latest'
        raw = self.metadata(base + '/manifests/' + ref, self.folder / 'tag.json', header)
        manifest = json.loads(raw)
        if 'manifests' in manifest:
            descriptor = next(row for row in manifest['manifests'] if row.get('platform', {}).get('os') == 'linux'
                              and row.get('platform', {}).get('architecture') == 'amd64')
            raw = self.metadata(base + '/manifests/' + descriptor['digest'], manifest_file, header)
            if 'sha256:' + hashlib.sha256(raw).hexdigest() != descriptor['digest']:
                raise ValueError('Registry manifest checksum mismatch')
            manifest = json.loads(raw)
        else:
            manifest_file.write_bytes(raw)
        space(self.folder, 15_000_000_000 + sum(row['size'] for row in manifest['layers']) * 5)
        for descriptor in [manifest['config'], *manifest['layers']]:
            digest = descriptor['digest'].removeprefix('sha256:')
            target = self.folder / digest
            if target.exists() and target.stat().st_size == descriptor['size'] and sha(target) == digest:
                continue
            part = self.folder / (digest + '.part')
            for _ in range(18):
                if part.exists() and part.stat().st_size >= descriptor['size']:
                    part.unlink()
                code = self.fetch(base + '/blobs/' + descriptor['digest'], part, header, resume=True)
                if code == 22:
                    self.authenticate(repo, header)
                if part.exists() and part.stat().st_size == descriptor['size'] and sha(part) == digest:
                    part.replace(target)
                    break
            else:
                raise OSError('Registry blob transfer incomplete: ' + digest[:12])
        config_digest = manifest['config']['digest'].removeprefix('sha256:')
        archive = self.folder / 'image.tar'
        layer_names = [row['digest'].removeprefix('sha256:') + '.tar.gz' for row in manifest['layers']]
        with tarfile.open(archive, 'w') as stream:
            stream.add(self.folder / config_digest, arcname=config_digest + '.json')
            for row, name in zip(manifest['layers'], layer_names):
                stream.add(self.folder / row['digest'].removeprefix('sha256:'), arcname=name)
            data = json.dumps([{'Config': config_digest + '.json', 'RepoTags': [tag], 'Layers': layer_names}]).encode()
            info = tarfile.TarInfo('manifest.json')
            info.size = len(data)
            stream.addfile(info, io.BytesIO(data))
        docker('load', '--input', archive, timeout=600)
        image = json.loads(docker('image', 'inspect', tag).decode())[0]
        config = json.loads((self.folder / config_digest).read_bytes())
        if image['RootFS']['Layers'] != config['rootfs']['diff_ids']:
            raise ValueError('Loaded image layer identity mismatch')
        result = {'image_id': image['Id'], 'layers': image['RootFS']['Layers'], 'owned': True, 'tag': tag,
                  'manifest_digest': 'sha256:' + hashlib.sha256(raw).hexdigest(),
                  'registry_config_digest': manifest['config']['digest']}
        write(self.folder / 'receipt.json', result)
        # Only our disposable archive/blobs; retain provenance, never remove other caches.
        archive.unlink()
        for descriptor in [manifest['config'], *manifest['layers']]:
            (self.folder / descriptor['digest'].removeprefix('sha256:')).unlink()
        return result


def release(receipt):
    if not receipt.get('owned'):
        return
    image = json.loads(docker('image', 'inspect', receipt['tag']).decode())[0]
    if image['Id'] != receipt['image_id']:
        raise ValueError('Task image changed; refusing cleanup')
    # No force, no prune: shared layers and images used by others are retained.
    docker('image', 'rm', receipt['tag'], timeout=120)
