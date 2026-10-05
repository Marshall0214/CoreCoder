"""Python-only BM25 corpora for controlled line/symbol and query-expansion diagnostics."""

import hashlib
import re
from collections import Counter

from corecoder.retrieval.keyword import Chunk, KeywordIndex, terms


def expand_query(query, policy):
    if policy not in {'plain', 'aliases', 'identifiers'}:
        raise ValueError('Unknown query policy')
    additions = []
    if policy != 'plain':
        if re.search(r'\benvironment[\s-]+variables?\b', query, re.IGNORECASE):
            additions.append('envvar')
        if re.search(r'\bboolean\b', query, re.IGNORECASE):
            additions.append('bool')
    if policy == 'identifiers':
        additions.extend(re.findall(r'\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b', query))
        return ' '.join(dict.fromkeys(additions)) if additions else query
    return query + ('\n' + ' '.join(additions) if additions else '')


class PythonCodeIndex(KeywordIndex):
    def __init__(self, workspace, allowed_sources, mode):
        if mode not in {'lines', 'symbols'}:
            raise ValueError('Unknown Python index mode')
        super().__init__(workspace, allowed_sources)
        self.mode = mode

    def refresh(self):
        from .symbol_context import parse_source

        files = {path: data for path, data in self._files().items() if path.endswith('.py')}
        source_hash = hashlib.sha256()
        chunks = []
        for path, data in sorted(files.items()):
            source_hash.update(path.encode() + b'\0' + data + b'\0')
            content_hash = hashlib.sha256(data).hexdigest()
            info = parse_source(path, data, {})
            lines = info['lines']
            spans = []
            if self.mode == 'symbols' and info['symbols']:
                for name, (start, end, node) in info['symbols'].items():
                    # Index class headers and attributes, not a second copy of every method body.
                    if node.__class__.__name__ == 'ClassDef':
                        children = [a for child, (a, _, _) in info['symbols'].items()
                                    if child.startswith(name + '.')]
                        if children:
                            end = min(children) - 1
                    if end >= start:
                        spans.append((start, end))
                covered = {line for start, end in spans for line in range(start, end + 1)}
                # Keep imports, module constants and other non-symbol code searchable.
                for offset in range(0, len(lines), self.chunk_lines):
                    remaining = [line for line in range(offset + 1, min(offset + self.chunk_lines, len(lines)) + 1)
                                 if line not in covered]
                    if remaining:
                        for line in remaining:
                            if lines[line - 1].strip():
                                spans.append((line, line))
            else:
                spans = [(offset + 1, min(offset + self.chunk_lines, len(lines)))
                         for offset in range(0, len(lines), self.chunk_lines)]
            for start, end in sorted(set(spans)):
                content = ''.join(lines[start - 1:end])
                if content.strip():
                    chunks.append(Chunk(path, start, end, content, content_hash))
        self.chunks = chunks
        self.counts = [Counter(terms(chunk.path + '\n' + chunk.content)) for chunk in chunks]
        self.document_frequency = Counter(term for count in self.counts for term in count)
        self.average_length = sum(sum(count.values()) for count in self.counts) / max(1, len(chunks)) or 1.0
        self.fingerprint = source_hash.hexdigest()
        return {'index_hash': hashlib.sha256((self.mode + self.fingerprint).encode()).hexdigest(),
                'source_hash': self.fingerprint, 'mode': self.mode, 'files': len(files), 'chunks': len(chunks)}
