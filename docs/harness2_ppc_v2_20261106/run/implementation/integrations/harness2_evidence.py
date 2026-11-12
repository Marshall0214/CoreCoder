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
        return pack_nested(items)
    return value


def _spans(body):
    """Literal JSON strings and balanced containers, without evaluating their contents."""
    quotes = {match.start(): match.end() for match in TOKENS.finditer(body)}
    spans = [(start, end) for start, end in quotes.items() if end - start >= 128]
    stack, position = [], 0
    while position < len(body):
        if position in quotes:
            position = quotes[position]
            continue
        char = body[position]
        if char in '{[':
            stack.append((char, position))
        elif char in '}]' and stack:
            opening, start = stack.pop()
            if (opening, char) in (('{', '}'), ('[', ']')) and position + 1 - start >= 128:
                spans.append((start, position + 1))
        position += 1
    return sorted(spans, key=lambda span: (span[0], -span[1]))


def pack_nested(items):
    """Share repeated public-result objects as well as strings; never shorten evidence."""
    counts = Counter(body[start:end] for body in items.values() if isinstance(body, str)
                     for start, end in _spans(body))
    names = {body: f'nested-{i}' for i, (body, count) in enumerate(counts.items()) if count > 1}
    shared = {}

    def encode(body, exclude=None):
        pieces, position = [], 0
        for start, end in _spans(body):
            raw = body[start:end]
            if start < position or raw == exclude or raw not in names:
                continue
            name = names[raw]
            pieces.extend([body[position:start], {'verbatim_text_ref': name}])
            position = end
            if name not in shared:
                # Every dependency is strictly shorter; references form an acyclic graph.
                shared[name] = encode(raw, exclude=raw)
        return {'verbatim_segments': pieces + [body[position:]]} if pieces else body

    value = {'encoding': 'nested_verbatim_segments; recursively concatenate strings and referenced text exactly',
             'shared_verbatim_text': shared,
             'files': {path: encode(body) if isinstance(body, str) else body for path, body in items.items()}}
    if unpack(value) != items:
        raise ValueError('Nested evidence encoding failed exact round-trip')
    if len(json.dumps(value, ensure_ascii=False)) > 160000:
        raise ValueError('Editor evidence exceeds local transport bound after nested lossless sharing')
    return value


def unpack(value):
    shared=value['shared_verbatim_text']
    cache, active = {}, set()

    def reference(name):
        if name in active:
            raise ValueError('Cyclic evidence reference')
        if name not in cache:
            active.add(name)
            cache[name] = decode(shared[name])
            active.remove(name)
        return cache[name]

    def decode(body):
        if isinstance(body, dict) and set(body) == {'verbatim_segments'}:
            return ''.join(piece if isinstance(piece, str) else reference(piece['verbatim_text_ref'])
                           for piece in body['verbatim_segments'])
        return body

    return {path: decode(body) for path, body in value['files'].items()}
