"""Readable, exactly reversible sharing of repeated JSON string tokens in evidence."""
import json
import re
from collections import Counter

TOKENS = re.compile(r'"(?:\\.|[^"\\])*"')


def pack(items):
    counts = Counter(token for body in items.values() if isinstance(body,str)
                     for token in TOKENS.findall(body) if len(token)>=256)
    names = {token:f'text-{number}' for number,(token,count) in enumerate(counts.items()) if count>1}
    shared = {name:token for token,name in names.items()}
    files = {}
    for path,body in items.items():
        if not isinstance(body,str):
            files[path]=body
            continue
        pieces, position = [], 0
        for match in TOKENS.finditer(body):
            if match.group() in names:
                pieces.extend([body[position:match.start()],{'verbatim_text_ref':names[match.group()]}])
                position=match.end()
        files[path] = {'verbatim_segments':pieces+[body[position:]]} if pieces else body
    value={'encoding':'verbatim_segments concatenate strings and referenced text exactly',
           'shared_verbatim_text':shared,'files':files}
    if unpack(value)!=items:
        raise ValueError('Evidence encoding failed exact round-trip')
    if len(json.dumps(value,ensure_ascii=False))>160000:
        raise ValueError('Editor evidence exceeds local transport bound after lossless sharing')
    return value


def unpack(value):
    shared=value['shared_verbatim_text']
    return {path:(''.join(piece if isinstance(piece,str) else shared[piece['verbatim_text_ref']]
                for piece in body['verbatim_segments'])
                 if isinstance(body,dict) and set(body)=={'verbatim_segments'} else body)
            for path,body in value['files'].items()}
