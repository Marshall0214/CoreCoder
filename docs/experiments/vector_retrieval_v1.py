"""Optional exact-vector retrieval; deliberately outside the frozen repair engine."""

import hashlib
import json
import math
import time
import urllib.request
from urllib.parse import urlparse

from corecoder.retrieval.keyword import KeywordIndex
from corecoder.tools.search_code import SearchCodeTool


def unit(vector):
    if not vector or any(isinstance(x, bool) or not isinstance(x, (int, float))
                         or not math.isfinite(x) for x in vector):
        raise ValueError("Embedding must contain finite numbers")
    norm = math.hypot(*vector)
    if not norm or not math.isfinite(norm):
        raise ValueError("Embedding must have finite nonzero norm")
    return tuple(x / norm for x in vector)


class OllamaEmbeddings:
    def __init__(self, model="qwen3-embedding:0.6b", base_url="http://localhost:11434", timeout=120):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("This experiment only sends source to local Ollama")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("Use the Ollama server root URL")
        self.model, self.base_url, self.timeout = model, base_url.rstrip("/"), timeout
        self.model_digest = self.identity()
        self.dimension = None
        self.cache = {}
        self.usage = {"calls": 0, "inputs": 0, "cache_hits": 0, "prompt_tokens": 0,
                      "missing_usage_calls": 0, "seconds": 0.0}

    def request(self, path, body=None):
        request = urllib.request.Request(self.base_url + path,
                                        data=json.dumps(body).encode() if body is not None else None,
                                        headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def identity(self):
        matches = [row["digest"] for row in self.request("/api/tags")["models"]
                   if row["name"] == self.model]
        if len(matches) != 1:
            raise ValueError("Install the exact embedding model tag before running")
        return matches[0]

    def verify_identity(self):
        if self.identity() != self.model_digest:
            raise ValueError("Embedding model digest changed during experiment")

    def embed(self, texts):
        if any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("Embedding input must be nonempty text")
        self.verify_identity()
        missing = list(dict.fromkeys(t for t in texts if t not in self.cache))
        self.usage["cache_hits"] += len(texts) - len(missing)
        for offset in range(0, len(missing), 16):
            batch = missing[offset:offset + 16]
            started = time.perf_counter()
            response = self.request("/api/embed", {"model": self.model, "input": batch,
                                                   "truncate": False, "keep_alive": "5m"})
            self.usage["seconds"] += time.perf_counter() - started
            self.usage["calls"] += 1
            self.usage["inputs"] += len(batch)
            tokens = response.get("prompt_eval_count")
            if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
                self.usage["prompt_tokens"] += tokens
            else:
                self.usage["missing_usage_calls"] += 1
            vectors = response.get("embeddings", [])
            if len(vectors) != len(batch):
                raise ValueError("Embedding response count differs from input count")
            normalized = [unit(v) for v in vectors]
            dimensions = {len(v) for v in normalized}
            if len(dimensions) != 1 or (self.dimension is not None and dimensions != {self.dimension}):
                raise ValueError("Embedding dimension changed")
            self.verify_identity()
            self.dimension = len(normalized[0])
            self.cache.update(zip(batch, normalized))
        return [self.cache[t] for t in texts]


class VectorIndex:
    """Exact cosine scan of the same chunks as BM25; equal-weight RRF for hybrid."""
    def __init__(self, workspace, provider, allowed_sources=None, strategy="dense"):
        if strategy not in {"dense", "hybrid"}:
            raise ValueError("Strategy must be dense or hybrid")
        self.lexical = KeywordIndex(workspace, allowed_sources)
        self.provider, self.strategy = provider, strategy
        self.vectors, self.fingerprint = [], None

    @property
    def chunks(self):
        return self.lexical.chunks

    def refresh(self):
        metadata = self.lexical.refresh()
        if self.fingerprint != metadata["index_hash"]:
            vectors = self.provider.embed([c.path + "\n" + c.content for c in self.chunks])
            if len(vectors) != len(self.chunks):
                raise ValueError("Document embedding count mismatch")
            self.vectors = vectors
            self.fingerprint = metadata["index_hash"]
        return metadata

    def rank(self, query):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be nonempty")
        q = self.provider.embed([query])[0]
        if any(len(v) != len(q) for v in self.vectors):
            raise ValueError("Query/document dimensions differ")
        dense = sorted([(sum(a * b for a, b in zip(q, v)), c)
                        for v, c in zip(self.vectors, self.chunks)],
                       key=lambda row: (-row[0], row[1].path, row[1].start_line))
        if self.strategy == "dense":
            return dense
        scores = {}
        for ranked in (dense, self.lexical.rank(query)):
            for rank, (_, chunk) in enumerate(ranked, 1):
                scores[chunk] = scores.get(chunk, 0.0) + 1 / (60 + rank)
        return sorted([(score, c) for c, score in scores.items()],
                      key=lambda row: (-row[0], row[1].path, row[1].start_line))


class VectorSearchCodeTool(SearchCodeTool):
    """Reuse the existing schema, packing, citations and history deduplication."""
    def __init__(self, workspace, provider, allowed_sources=None, strategy="dense", **kwargs):
        emit = kwargs.pop("emit", None)

        def strategy_event(event, **fields):
            fields["backend"] = strategy
            fields["embedding_model_digest"] = provider.model_digest
            emit(event, **fields)

        # The parent uses 'keyword' as its nonempty-index execution switch.
        # Actual ranking comes entirely from the injected index; trace names the strategy.
        super().__init__(workspace, allowed_sources, backend="keyword",
                         emit=strategy_event if emit else None, **kwargs)
        self.index = VectorIndex(workspace, provider, allowed_sources, strategy)


def adapter_hash():
    from pathlib import Path
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
