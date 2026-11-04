"""Fetch only pinned, hash-checked upstream core files into project .tmp on D:."""
import hashlib
import io
import json
import urllib.request
import zipfile

from integrations.harness2_runtime import COMMIT, ROOT, UPSTREAM


def main():
    if UPSTREAM.exists():
        raise SystemExit('Upstream directory exists; keep it and verify hashes with the controller')
    expected = json.loads((ROOT / 'integrations/harness2-source.json').read_text(encoding='utf-8'))
    request = urllib.request.Request('https://api.github.com/repos/google-research/harness2/zipball/'+COMMIT,
                                     headers={'User-Agent':'CoreCoder-local-learning'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=40) as response:
        raw = response.read(16000001)
    if len(raw)>16000000:
        raise ValueError('Unexpected upstream archive size')
    found = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for entry in archive.infolist():
            name = '/'.join(entry.filename.split('/')[1:])
            if name not in expected['files']:
                continue
            if entry.file_size>1000000 or (entry.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Unexpected source member')
            data = archive.read(entry)
            if hashlib.sha256(data).hexdigest()!=expected['files'][name]:
                raise ValueError('Source checksum mismatch: '+name)
            found[name]=data
    if set(found)!=set(expected['files']):
        raise ValueError('Incomplete pinned source archive')
    UPSTREAM.mkdir(parents=True,exist_ok=False)
    for name,data in found.items():
        path=UPSTREAM/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
    (UPSTREAM/'source-origin.json').write_text(json.dumps({key:expected[key] for key in
        ('repository','commit','tree','archive_sha256')},indent=2),encoding='utf-8')
    print('Installed verified core files:',len(found))


if __name__=='__main__':
    main()
